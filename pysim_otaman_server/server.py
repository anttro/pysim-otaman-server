import json
import sys
import time
import traceback
from http.server import HTTPServer, BaseHTTPRequestHandler
from io import StringIO
from pySim.transport import ApduTracer


class StderrApduTracer(ApduTracer):
    def trace_response(self, cmd, sw, resp):
        if resp:
            sys.stderr.write("APDU-TRACE: %s → SW: %s RESP: %s\n" % (cmd, sw, resp))
        else:
            sys.stderr.write("APDU-TRACE: %s → SW: %s\n" % (cmd, sw))


def _trunc(s, n=200):
    if len(s) > n:
        return s[:n] + '...'
    return s


def _get_file_type(lchan, cur_file):
    if lchan and lchan.selected_file_fcp:
        ft = lchan.selected_file_type()
        if ft == 'df':
            return 'df'
        return lchan.selected_file_structure()
    if cur_file and cur_file.name:
        if cur_file.name.startswith('EF.'):
            return 'transparent'
        if cur_file.name.startswith('DF.') or cur_file.name.startswith('ADF.') or cur_file.name == 'MF':
            return 'df'
    return None


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

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def do_GET(self):
        if self.path == '/api/status':
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
        elif self.path == '/api/commands':
            app = self.server.app
            if not app:
                self._send_json({'error': 'app not initialized'}, 503)
                return
            cmds = sorted(
                attr[3:] for attr in dir(app)
                if attr.startswith('do_') and not attr.startswith('do__')
            )
            self._send_json(cmds)
        elif self.path == '/api/cardinfo':
            app = self.server.app
            if not app:
                self._send_json({'error': 'app not initialized'}, 503)
                return
            out = StringIO()
            old_stdout = app.stdout
            old_stderr = sys.stderr
            app.stdout = out
            sys.stderr = out
            try:
                app.onecmd_plus_hooks('cardinfo')
                output = out.getvalue()
            except Exception as e:
                output = str(e) + '\n' + traceback.format_exc()
            finally:
                app.stdout = old_stdout
                sys.stderr = old_stderr
            self._send_json({'output': output})
        else:
            self._send_json({'error': 'not found'}, 404)

    def do_POST(self):
        if self.path == '/api/command':
            app = self.server.app
            if not app:
                self._send_json({'error': 'app not initialized'}, 503)
                return
            body = self._read_body()
            cmd = body.get('cmd', '')
            if self.server.log_requests:
                sys.stderr.write("REQUEST: %s\n" % _trunc(json.dumps(body)))
            t0 = time.time()
            out = StringIO()
            old_stdout = app.stdout
            old_stderr = sys.stderr
            app.stdout = out
            sys.stderr = out
            try:
                stop = app.onecmd_plus_hooks(cmd)
                output = out.getvalue()
            except Exception as e:
                output = str(e) + '\n' + traceback.format_exc()
            finally:
                app.stdout = old_stdout
                sys.stderr = old_stderr
            elapsed = int((time.time() - t0) * 1000)
            status = 'OK' if not output or 'not a recognized command' not in output else 'ERROR'
            sys.stderr.write("CMD: %s → %s (%dms)\n" % (cmd, status, elapsed))
            if self.server.log_requests:
                sys.stderr.write("RESPONSE: %s\n" % _trunc(output))
            self._send_json({'output': output, 'stop': bool(stop)})
        elif self.path == '/api/apdu':
            scc = self.server.scc
            if not scc:
                self._send_json({'error': 'reader not initialized'}, 503)
                return
            body = self._read_body()
            apdu_hex = body.get('apdu', '')
            if self.server.log_requests:
                sys.stderr.write("REQUEST: %s\n" % _trunc(json.dumps(body)))
            t0 = time.time()
            try:
                data, sw = scc.send_apdu_checksw(apdu_hex)
                elapsed = int((time.time() - t0) * 1000)
                resp = {'response': data.hex(), 'sw': sw}
                sys.stderr.write("APDU: %s → SW: %s (%dms)\n" % (apdu_hex, sw, elapsed))
                if self.server.log_requests:
                    sys.stderr.write("RESPONSE: %s\n" % _trunc(json.dumps(resp)))
                self._send_json(resp)
            except Exception as e:
                elapsed = int((time.time() - t0) * 1000)
                sys.stderr.write("APDU: %s → ERROR: %s (%dms)\n" % (apdu_hex, str(e), elapsed))
                self._send_json({'error': str(e)}, 500)
        else:
            self._send_json({'error': 'not found'}, 404)

    def log_message(self, format, *args):
        sys.stderr.write('%s - - [%s] %s\n' % (self.client_address[0], self.log_date_time_string(), format % args))