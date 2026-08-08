import json
import sys
import os
import time
import traceback
import re
from datetime import datetime, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler
from io import StringIO
from pySim.transport import ApduTracer


VERSION = '1.2.2'


class StderrApduTracer(ApduTracer):
    def trace_response(self, cmd, sw, resp):
        msg = "APDU-TRACE: %s → SW: %s" % (cmd, sw)
        if resp:
            msg += " RESP: %s" % resp
        os.write(2, (msg + '\n').encode())


ERROR_MSGS = {
    'en': {
        'app_not_init': 'Server not initialized',
        'no_card_state': 'No card state available',
        'reader_not_init': 'Reader not initialized',
        'not_found': 'Not found',
    },
    'ru': {
        'app_not_init': 'Сервер не инициализирован',
        'no_card_state': 'Состояние карты недоступно',
        'reader_not_init': 'Считыватель не инициализирован',
        'not_found': 'Не найдено',
    },
}


def _get_lang(headers):
    lang = headers.get('Accept-Language', 'en')
    if lang not in ('en', 'ru'):
        lang = 'en'
    return lang


def _err(key, lang):
    return ERROR_MSGS.get(lang, ERROR_MSGS['en']).get(key, key)


def _strip_ansi(text):
    return re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', text)


def _parse_help_text(text):
    result = {'usage': '', 'description': '', 'args': []}
    lines = text.split('\n')
    in_usage = False
    in_pos = False
    in_opt = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith('usage:'):
            result['usage'] = stripped[6:].strip()
            in_usage = True
            in_pos = in_opt = False
        elif stripped.startswith('positional arguments:'):
            in_pos = True
            in_opt = in_usage = False
        elif stripped.startswith('options:') or stripped.startswith('optional arguments:'):
            in_opt = True
            in_pos = in_usage = False
        elif in_pos and stripped and not stripped.startswith('usage:'):
            m = re.match(r'^(\S+)\s+(.+)$', stripped)
            if m:
                result['args'].append({'name': m.group(1), 'type': 'positional', 'help': m.group(2)})
        elif in_opt and stripped and not stripped.startswith('usage:'):
            m = re.match(r'^(\S+(?:,\s*\S+)?)\s+(\S+\s+)?(.+)?$', stripped)
            if m:
                names = m.group(1)
                first_name = names.split(',')[0].strip()
                result['args'].append({'name': first_name, 'type': 'optional', 'help': (m.group(3) or '').strip()})
        elif not in_pos and not in_opt and not in_usage:
            if stripped:
                result['description'] = (result['description'] + ' ' + stripped).strip()
    return result


def _get_file_type(lchan, cur_file):
    if cur_file and cur_file.name:
        if cur_file.name.startswith('EF.'):
            if lchan and lchan.selected_file_fcp:
                ft = lchan.selected_file_type()
                if ft != 'df':
                    return lchan.selected_file_structure()
            return 'transparent'
        if cur_file.name.startswith('DF.') or cur_file.name.startswith('ADF.') or cur_file.name == 'MF':
            return 'df'
    if lchan and lchan.selected_file_fcp:
        return lchan.selected_file_structure()
    return None


def _select_with_parent(lchan, name, parent_sel, app):
    if parent_sel:
        lchan.select(parent_sel, app)
    fcp = lchan.select(name, app)
    return fcp


def _parse_tree_output(output):
    lines = (output or '').split('\n')
    children = []
    for line in lines:
        if line.startswith(' '):
            continue
        m = re.match(r'^(\S+)\s+([0-9a-fA-F]{4})?(?:\s|$)', line)
        if m:
            cname = m.group(1)
            cfid = m.group(2).lower() if m.group(2) else None
            children.append({
                'name': cname,
                'fid': cfid,
                'isDir': cname.startswith('ADF.') or cname.startswith('DF.') or cname == 'MF',
            })
    return children


def _encode_sms_oa(number):
    digits = [int(c) for c in number if c.isdigit()]
    oa = bytes([len(digits), 0x91])
    for i in range(0, len(digits), 2):
        first = digits[i]
        second = digits[i + 1] if i + 1 < len(digits) else 0xF
        oa += bytes([(second << 4) | first])
    return oa


def _bcd_pair(value):
    return ((value % 10) << 4) | ((value // 10) % 10)


def _encode_scts(dt=None):
    dt = dt or datetime.now().astimezone()
    offset = dt.utcoffset() or timedelta()
    quarters = int(offset.total_seconds() // 900)
    tz = _bcd_pair(abs(quarters)) | (0x08 if quarters < 0 else 0x00)
    return bytes([
        _bcd_pair(dt.year % 100),
        _bcd_pair(dt.month),
        _bcd_pair(dt.day),
        _bcd_pair(dt.hour),
        _bcd_pair(dt.minute),
        _bcd_pair(dt.second),
        tz,
    ])


def _build_sms_tpdu(chunk_hex, chunk_total=1, chunk_num=1, oa_number='12345'):
    chunk = bytes.fromhex(chunk_hex)
    udh = b''
    if chunk_total > 1:
        udh = bytes([0x00, 0x03, 0x01, chunk_total, chunk_num])
    tp_ud = udh + chunk
    first_byte = 0x44 if udh else 0x04
    tpdu = bytes([first_byte]) + _encode_sms_oa(oa_number) + bytes([0x7F, 0xF6]) + _encode_scts() + bytes([len(tp_ud)]) + tp_ud
    return tpdu.hex()


def _send_envelope(tpdu_hex, scc):
    from pySim.ts_31_102 import SMSPPDownload
    from pySim.cat import DeviceIdentities
    from osmocom.tlv import COMPR_TLV_IE
    from pySim.utils import b2h

    class RawTpdu(COMPR_TLV_IE, tag=0x8B):
        comprehension = False
        def __init__(self, data_hex):
            super().__init__()
            self._raw = bytes.fromhex(data_hex)
        def to_bytes(self, context={}):
            return self._raw

    class Address(COMPR_TLV_IE, tag=0x86):
        comprehension = False
        def __init__(self):
            super().__init__()
            self._raw = bytes([0x80, 0xF0])
        def to_bytes(self, context={}):
            return self._raw

    dev_ids = DeviceIdentities(decoded={'source_dev_id': 'network', 'dest_dev_id': 'uicc'})
    address = Address()
    raw_tpdu = RawTpdu(tpdu_hex)
    sms_dl = SMSPPDownload(children=[dev_ids, address, raw_tpdu])
    data, sw = scc.envelope(b2h(sms_dl.to_tlv()))
    return data, sw


class PysimHandler(BaseHTTPRequestHandler):
    def _send_json(self, data, status=200):
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode())

    def _read_body(self):
        length = int(self.headers.get('Content-Length', 0))
        return json.loads(self.rfile.read(length))

    def _log_req(self, body=None):
        if self.server.log_requests:
            if body is not None:
                sys.stderr.write("REQUEST %s %s: %s\n" % (self.command, self.path, json.dumps(body)))
            else:
                sys.stderr.write("REQUEST %s %s\n" % (self.command, self.path))

    def _log_resp(self, data):
        if self.server.log_requests:
            sys.stderr.write("RESPONSE %s: %s\n" % (self.path, json.dumps(data, ensure_ascii=False)))

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def do_GET(self):
        lang = _get_lang(self.headers)
        if self.path == '/api/version':
            self._log_req()
            self._send_json({'version': VERSION})
            self._log_resp({'version': VERSION})
        elif self.path == '/api/status':
            self._log_req()
            app = self.server.app
            rs = app.rs if app else None
            lchan = rs.lchan[0] if rs else None
            cur_file = lchan.selected_file if lchan else None
            scc = app.card._scc if app and app.card else None
            data = {
                'reader': str(self.server.sl) if self.server.sl else None,
                'card': app.card.name if app and app.card else None,
                'profile': str(rs.profile) if rs and rs.profile else None,
                'app_ready': app is not None,
                'adm_verified': rs.adm_verified if rs else False,
                'atr': rs.identity.get('ATR') if rs and rs.identity else None,
                'cla_byte': scc.cla_byte if scc else None,
                'sel_ctrl': scc.sel_ctrl if scc else None,
                'current_selection': {
                    'fid': cur_file.fid.upper() if cur_file and cur_file.fid else None,
                    'name': cur_file.name if cur_file else None,
                    'desc': cur_file.desc if cur_file else None,
                    'type': cur_file.__class__.__name__ if cur_file else None,
                    'path': str(lchan.get_cwd()) if lchan else None,
                    'file_type': _get_file_type(lchan, cur_file),
                    'file_size': lchan.selected_file_size() if lchan else None,
                    'record_len': lchan.selected_file_record_len() if lchan else None,
                    'num_of_rec': lchan.selected_file_num_of_rec() if lchan else None,
                } if cur_file else None,
                'channels': [str(i) for i, ch in rs.lchan.items() if ch] if rs else [],
            }
            self._send_json(data)
            self._log_resp(data)
        elif self.path == '/api/commands':
            self._log_req()
            app = self.server.app
            if not app:
                self._send_json({'error': _err('app_not_init', lang)}, 503)
                self._log_resp({'error': _err('app_not_init', lang)})
                return
            cmds = sorted(
                attr[3:] for attr in dir(app)
                if attr.startswith('do_') and not attr.startswith('do__')
            )
            self._send_json(cmds)
            self._log_resp(cmds)
        elif self.path == '/api/cardinfo':
            self._log_req()
            app = self.server.app
            if not app:
                self._send_json({'error': _err('app_not_init', lang)}, 503)
                self._log_resp({'error': _err('app_not_init', lang)})
                return
            out = StringIO()
            old_stdout = app.stdout
            old_stderr = sys.stderr
            app.stdout = out
            sys.stderr = out
            try:
                app.onecmd_plus_hooks('cardinfo')
                output = _strip_ansi(out.getvalue())
            except Exception as e:
                output = str(e) + '\n' + traceback.format_exc()
            finally:
                app.stdout = old_stdout
                sys.stderr = old_stderr
            resp = {'output': output}
            self._send_json(resp)
            self._log_resp(resp)
        else:
            self._send_json({'error': _err('not_found', lang)}, 404)
            self._log_resp({'error': _err('not_found', lang)})

    def do_POST(self):
        lang = _get_lang(self.headers)
        if self.path == '/api/command':
            app = self.server.app
            if not app:
                self._send_json({'error': _err('app_not_init', lang)}, 503)
                self._log_resp({'error': _err('app_not_init', lang)})
                return
            body = self._read_body()
            self._log_req(body)
            cmd = body.get('cmd', '')
            t0 = time.time()
            out = StringIO()
            old_stdout = app.stdout
            old_stderr = sys.stderr
            app.stdout = out
            sys.stderr = out
            try:
                stop = app.onecmd_plus_hooks(cmd)
                output = _strip_ansi(out.getvalue())
            except Exception as e:
                output = str(e) + '\n' + traceback.format_exc()
            finally:
                app.stdout = old_stdout
                sys.stderr = old_stderr
            elapsed = int((time.time() - t0) * 1000)
            status = 'OK' if not output or 'not a recognized command' not in output else 'ERROR'
            sys.stderr.write("CMD: %s → %s (%dms)\n" % (cmd, status, elapsed))
            resp = {'output': output, 'stop': bool(stop)}
            self._send_json(resp)
            self._log_resp(resp)
        elif self.path == '/api/apdu':
            scc = self.server.scc
            if not scc:
                self._send_json({'error': _err('reader_not_init', lang)}, 503)
                self._log_resp({'error': _err('reader_not_init', lang)})
                return
            body = self._read_body()
            self._log_req(body)
            apdu_hex = body.get('apdu', '')
            t0 = time.time()
            try:
                data, sw = scc.send_apdu_checksw(apdu_hex)
                elapsed = int((time.time() - t0) * 1000)
                resp = {'response': data.hex(), 'sw': sw}
                sys.stderr.write("APDU: %s → SW: %s (%dms)\n" % (apdu_hex, sw, elapsed))
                self._send_json(resp)
                self._log_resp(resp)
            except Exception as e:
                elapsed = int((time.time() - t0) * 1000)
                err = {'error': str(e)}
                sys.stderr.write("APDU: %s → ERROR: %s (%dms)\n" % (apdu_hex, str(e), elapsed))
                self._send_json(err, 500)
                self._log_resp(err)
        elif self.path == '/api/help':
            app = self.server.app
            if not app:
                self._send_json({'error': _err('app_not_init', lang)}, 503)
                self._log_resp({'error': _err('app_not_init', lang)})
                return
            body = self._read_body()
            self._log_req(body)
            cmd = body.get('cmd', '')
            out = StringIO()
            old_stdout = app.stdout
            old_stderr = sys.stderr
            app.stdout = out
            sys.stderr = out
            try:
                app.onecmd_plus_hooks('help ' + cmd)
                raw = out.getvalue()
            finally:
                app.stdout = old_stdout
                sys.stderr = old_stderr
            clean = _strip_ansi(raw)
            parsed = _parse_help_text(clean)
            self._send_json(parsed)
            self._log_resp(parsed)
        elif self.path == '/api/select':
            app = self.server.app
            if not app:
                self._send_json({'error': _err('app_not_init', lang)}, 503)
                self._log_resp({'error': _err('app_not_init', lang)})
                return
            body = self._read_body()
            self._log_req(body)
            fid = body.get('fid')
            name = fid if fid else body.get('name', '')
            parent_sel = body.get('parent_sel')
            rs = app.rs
            if not rs:
                self._send_json({'error': _err('no_card_state', lang)}, 503)
                self._log_resp({'error': _err('no_card_state', lang)})
                return
            lchan = rs.lchan[0]
            try:
                _select_with_parent(lchan, name, parent_sel, app)
                cur = lchan.selected_file
                data = {
                    'name': cur.name if cur else None,
                    'fid': cur.fid.upper() if cur and cur.fid else None,
                    'file_type': _get_file_type(lchan, cur),
                    'exists': True,
                }
                self._send_json(data)
                self._log_resp(data)
            except Exception as e:
                err = {'error': str(e), 'exists': False}
                self._send_json(err, 404)
                self._log_resp(err)
        elif self.path == '/api/read':
            app = self.server.app
            if not app:
                self._send_json({'error': _err('app_not_init', lang)}, 503)
                self._log_resp({'error': _err('app_not_init', lang)})
                return
            body = self._read_body()
            self._log_req(body)
            fid = body.get('fid')
            name = fid if fid else body.get('name', '')
            fid = body.get('fid')
            parent_sel = body.get('parent_sel')
            mode = body.get('mode', 'raw')
            rs = app.rs
            if not rs:
                self._send_json({'error': _err('no_card_state', lang)}, 503)
                self._log_resp({'error': _err('no_card_state', lang)})
                return
            lchan = rs.lchan[0]
            try:
                sel = fid if fid else name
                _select_with_parent(lchan, sel, parent_sel, app)
                ft = _get_file_type(lchan, lchan.selected_file)
                is_record = ft in ('linear_fixed', 'cyclic')
                if mode == 'decoded':
                    cmd = 'read_records_decoded' if is_record else 'read_binary_decoded'
                else:
                    cmd = 'read_records' if is_record else 'read_binary'
                out = StringIO()
                old_stdout = app.stdout
                old_stderr = sys.stderr
                app.stdout = out
                sys.stderr = out
                try:
                    app.onecmd_plus_hooks(cmd)
                    output = _strip_ansi(out.getvalue())
                finally:
                    app.stdout = old_stdout
                    sys.stderr = old_stderr
                sw_match = re.search(r'SW:\s*(\w+)', output)
                err_match = re.search(r'got (\w+)', output)
                if err_match:
                    sw = err_match.group(1)
                    descs = {'6982': 'Security status not satisfied', '6983': 'PIN blocked',
                             '6985': 'Conditions of use not satisfied', '6A88': 'Referenced data not found',
                             '6A82': 'File not found'}
                    resp = {'success': False, 'sw': sw, 'error': descs.get(sw, 'Error')}
                    self._send_json(resp)
                    self._log_resp(resp)
                    return
                sw = sw_match.group(1) if sw_match else '9000'
                clean = re.sub(r'^SW:\s*\w+\s*', '', output, flags=re.MULTILINE).strip()
                if mode == 'decoded':
                    try:
                        parsed = json.loads(clean)
                        resp = {'success': True, 'sw': sw, 'file_type': ft, 'decoded': parsed}
                    except json.JSONDecodeError:
                        resp = {'success': True, 'sw': sw, 'file_type': ft, 'data': clean}
                elif is_record:
                    records = []
                    for line in clean.split('\n'):
                        m = re.match(r'^(\d+)\s(.+)', line)
                        if m:
                            records.append({'num': int(m.group(1)), 'data': m.group(2)})
                    resp = {'success': True, 'sw': sw, 'file_type': ft, 'records': records}
                else:
                    resp = {'success': True, 'sw': sw, 'file_type': ft, 'data': clean}
                self._send_json(resp)
                self._log_resp(resp)
            except Exception as e:
                err = {'success': False, 'error': str(e)}
                self._send_json(err, 500)
                self._log_resp(err)
        elif self.path == '/api/write':
            app = self.server.app
            if not app:
                self._send_json({'error': _err('app_not_init', lang)}, 503)
                self._log_resp({'error': _err('app_not_init', lang)})
                return
            body = self._read_body()
            self._log_req(body)
            name = body.get('name', '')
            data = body.get('data', '')
            fid = body.get('fid')
            record_nr = body.get('record_nr')
            parent_sel = body.get('parent_sel')
            rs = app.rs
            if not rs:
                self._send_json({'error': _err('no_card_state', lang)}, 503)
                self._log_resp({'error': _err('no_card_state', lang)})
                return
            lchan = rs.lchan[0]
            try:
                sel = fid if fid else name
                _select_with_parent(lchan, sel, parent_sel, app)
                ft = _get_file_type(lchan, lchan.selected_file)
                is_record = ft in ('linear_fixed', 'cyclic')
                if record_nr:
                    cmd = 'update_record %d %s' % (record_nr, data)
                elif is_record:
                    cmd = 'update_record 1 %s' % data
                else:
                    cmd = 'update_binary %s' % data
                out = StringIO()
                old_stdout = app.stdout
                old_stderr = sys.stderr
                app.stdout = out
                sys.stderr = out
                try:
                    app.onecmd_plus_hooks(cmd)
                    output = out.getvalue()
                finally:
                    app.stdout = old_stdout
                    sys.stderr = old_stderr
                sw_match = re.search(r'SW:\s*(\w+)', output)
                err_match = re.search(r'got (\w+)', output)
                if err_match:
                    sw = err_match.group(1)
                    descs = {'6982': 'Security status not satisfied', '6983': 'PIN blocked',
                             '6985': 'Conditions of use not satisfied', '6A88': 'Referenced data not found',
                             '6A82': 'File not found'}
                    resp = {'success': False, 'sw': sw, 'error': descs.get(sw, 'Error')}
                else:
                    sw = sw_match.group(1) if sw_match else '9000'
                    resp = {'success': True, 'sw': sw}
                self._send_json(resp)
                self._log_resp(resp)
            except Exception as e:
                err = {'success': False, 'error': str(e)}
                self._send_json(err, 500)
                self._log_resp(err)
        elif self.path == '/api/tree':
            app = self.server.app
            if not app:
                self._send_json({'error': _err('app_not_init', lang)}, 503)
                self._log_resp({'error': _err('app_not_init', lang)})
                return
            body = self._read_body()
            self._log_req(body)
            fid = body.get('fid')
            name = fid if fid else body.get('name', '')
            fid = body.get('fid')
            parent_sel = body.get('parent_sel')
            rs = app.rs
            if not rs:
                self._send_json({'error': _err('no_card_state', lang)}, 503)
                self._log_resp({'error': _err('no_card_state', lang)})
                return
            lchan = rs.lchan[0]
            try:
                sel = fid if fid else name
                _select_with_parent(lchan, sel, parent_sel, app)
                cur = lchan.selected_file
                out = StringIO()
                old_stdout = app.stdout
                old_stderr = sys.stderr
                app.stdout = out
                sys.stderr = out
                try:
                    app.onecmd_plus_hooks('tree')
                    output = _strip_ansi(out.getvalue())
                finally:
                    app.stdout = old_stdout
                    sys.stderr = old_stderr
                children = _parse_tree_output(output)
                sels = lchan.selected_file.get_selectables() if lchan and lchan.selected_file else {}
                for child in children:
                    if child['isDir'] and child['name'] in sels:
                        f = sels[child['name']]
                        if hasattr(f, 'aid') and f.aid:
                            child['aid'] = f.aid.upper()
                resp = {
                    'exists': True,
                    'name': cur.name if cur else None,
                    'fid': cur.fid.upper() if cur and cur.fid else None,
                    'file_type': _get_file_type(lchan, cur),
                    'children': children,
                }
                self._send_json(resp)
                self._log_resp(resp)
            except Exception as e:
                err = {'exists': False, 'error': str(e)}
                self._send_json(err, 404)
                self._log_resp(err)
        elif self.path == '/api/send-ota':
            app = self.server.app
            if not app:
                self._send_json({'error': _err('app_not_init', lang)}, 503)
                self._log_resp({'error': _err('app_not_init', lang)})
                return
            body = self._read_body()
            self._log_req(body)
            sp = body.get('sp', '')
            scc = self.server.scc
            if not scc:
                self._send_json({'error': _err('reader_not_init', lang)}, 503)
                self._log_resp({'error': _err('reader_not_init', lang)})
                return
            try:
                sp_bytes = bytes.fromhex(sp)
                max_chunk = 130
                chunks = [sp_bytes[i:i+max_chunk] for i in range(0, len(sp_bytes), max_chunk)]
                total = len(chunks)
                last_data = None
                last_sw = None
                for i, chunk in enumerate(chunks):
                    tpdu = _build_sms_tpdu(chunk.hex(), total, i + 1, oa_number=self.server.sms_oa) if total > 1 else _build_sms_tpdu(sp, oa_number=self.server.sms_oa)
                    data, sw = _send_envelope(tpdu, scc)
                    last_data = data
                    last_sw = sw
                    if sw != '9000' and not sw.startswith('91'):
                        resp = {'success': False, 'sw': sw, 'error': 'ENVELOPE failed at chunk %d' % (i + 1)}
                        break
                else:
                    resp = {'success': True, 'sw': last_sw, 'response_data': last_data.hex() if last_data else None}
                self._send_json(resp)
                self._log_resp(resp)
            except Exception as e:
                err = {'success': False, 'error': str(e)}
                self._send_json(err, 500)
                self._log_resp(err)
        else:
            self._send_json({'error': _err('not_found', lang)}, 404)
            self._log_resp({'error': _err('not_found', lang)})

    def log_message(self, format, *args):
        sys.stderr.write('%s - - [%s] %s\n' % (self.client_address[0], self.log_date_time_string(), format % args))