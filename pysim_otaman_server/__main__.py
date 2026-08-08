import argparse
import logging
import os
import sys
import traceback
from http.server import HTTPServer
from pySim.card_handler import CardHandler
from pySim.commands import SimCardCommands
from pySim.log import PySimLogger

from .shell import load_pysim_app
from .server import PysimHandler, StderrApduTracer, VERSION


def _log_stdout(msg):
    os.write(1, (msg + '\n').encode())


def main():
    mod = load_pysim_app()
    parser = mod.option_parser
    parser.description = 'pysim-otaman-server — HTTP API for pysim'
    parser.add_argument('--http-host', default='127.0.0.1', help='Bind address (default: 127.0.0.1)')
    parser.add_argument('--http-port', type=int, default=8080, help='Bind port (default: 8080)')
    parser.add_argument('--log-requests', action='store_true', default=False, help='Log request/response payloads to stderr')
    parser.add_argument('--sms-oa', default='12345', metavar='DIGITS',
                        help='TP-Originating-Address (SMSC number) for the SMS-DELIVER TPDU (default: 12345)')
    parser.add_argument('--sms-sm-sc', default='12345678912', metavar='DIGITS',
                        help='SM-SC address for SMS-SUBMIT routing in PoR-in-submit mode (default: 12345678912)')
    parser.add_argument('--terminal-profile', default='ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff', metavar='HEX',
                        help='TERMINAL PROFILE payload (default: all-FF, 32 bytes)')

    opts = parser.parse_args()
    sl = None
    scc = None
    card = None
    rs = None
    sim_menu = None
    try:
        kwargs = {}
        if opts.apdu_trace:
            kwargs['apdu_tracer'] = StderrApduTracer()
        sl = mod.init_reader(opts, **kwargs)
        scc = SimCardCommands(sl)
        sl.wait_for_card(3)
        rs, card = mod.init_card(sl, opts.skip_card_init)
        tp_hex = opts.terminal_profile
        tp_data, tp_sw = scc._tp.send_apdu('80100000%02x%s' % (len(tp_hex) // 2, tp_hex))
        if tp_sw.startswith('91'):
            sw = tp_sw
            while sw.startswith('91'):
                fetch_len = int(sw[2:], 16) if len(sw) == 4 else 0xff
                fdata, sw = scc._tp.send_apdu('80120000%02x' % fetch_len)
                cmd_num, cmd_type = 1, 0
                if fdata:
                    raw = bytes.fromhex(fdata)
                    if raw[0] == 0xD0:
                        off = 2
                        menu = None
                        items = []
                        while off < len(raw) - 1:
                            tag, tlen = raw[off], raw[off + 1]
                            val = raw[off + 2: off + 2 + tlen]
                            off += 2 + tlen
                            if tag == 0x81 and tlen >= 3:
                                cmd_num, cmd_type = val[0], val[1]
                                if cmd_type == 0x25:
                                    menu = {'command_number': cmd_num, 'items': items}
                            elif tag == 0x05 and tlen >= 1 and menu is not None:
                                try:
                                    menu['title'] = val.decode('ascii')
                                except UnicodeDecodeError:
                                    menu['title'] = val.hex()
                            elif tag == 0x8F and tlen >= 2:
                                items.append({'id': val[0], 'text_raw': val[1:].hex()})
                        if menu:
                            sim_menu = menu
                tr_tlv = bytes([0x81, 0x03, cmd_num, cmd_type, 0x00,
                                0x82, 0x02, 0x83, 0x81,
                                0x83, 0x02, 0x00, 0x00])
                tr_rv = scc._tp.send_apdu('80140000%02x%s' % (len(tr_tlv), tr_tlv.hex()))
                sw = tr_rv[1]
    except Exception:
        print("Warning: reader/card initialization failed:", file=sys.stderr)
        traceback.print_exc()
    ch = CardHandler(sl) if sl else None
    try:
        app = mod.PysimApp(verbose=opts.verbose, card=card, rs=rs, sl=sl, ch=ch)
    except Exception:
        print("Warning: PysimApp creation failed:", file=sys.stderr)
        traceback.print_exc()
        app = None
    if app is not None and opts.apdu_trace:
        # PysimApp.__init__ routes PySimLogger through app.poutput() (app.stdout)
        # and drops the root level to INFO. Re-route pysim's own APDU trace logging
        # directly to fd 1 so it survives the app.stdout/StringIO redirection in the
        # HTTP handlers and the INFO level suppression.
        PySimLogger.setup(print_callback=_log_stdout)
        PySimLogger.set_level(logging.DEBUG)
        # PysimApp.__init__ and every `equip` wipe the transport apdu_tracer
        # (_onchange_apdu_trace sets it to None). Re-attach our tracer and make
        # sure it stays attached across equip/re-equip.
        tracer = StderrApduTracer()
        def _reattach_tracer():
            if app.card:
                app.card._scc._tp.apdu_tracer = tracer
        _reattach_tracer()
        orig_onchange = app._onchange_apdu_trace
        def _onchange_apdu_trace(param_name, old, new):
            orig_onchange(param_name, old, new)
            _reattach_tracer()
        app._onchange_apdu_trace = _onchange_apdu_trace
    server = HTTPServer((opts.http_host, opts.http_port), PysimHandler)
    server.sl = sl
    server.scc = scc
    server.card = card
    server.rs = rs
    server.app = app
    server.sms_oa = opts.sms_oa
    server.sms_sc = opts.sms_sm_sc
    server.log_requests = opts.log_requests
    server.sim_menu = sim_menu
    print("─" * 70)
    print("  pysim-otaman-server v%s listening on http://%s:%s" % (VERSION, opts.http_host, opts.http_port))
    print("  Now open OTAMan and click Connect in the pySim tab!")
    print("─" * 70)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
        server.shutdown()


if __name__ == '__main__':
    main()