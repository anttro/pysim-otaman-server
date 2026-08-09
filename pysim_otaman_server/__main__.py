import argparse
import logging
import os
import sys
import time
import traceback
from http.server import HTTPServer
from pySim.card_handler import CardHandler
from pySim.commands import SimCardCommands
from pySim.log import PySimLogger
from pySim.cards import UiccCardBase

from .shell import load_pysim_app
from .server import PysimHandler, StderrApduTracer, VERSION, _send_terminal_profile, _DefaultProactiveHandler


_server_start = 0

def _log_stdout(msg):
    elapsed = time.time() - _server_start
    os.write(1, ('[%8.3f] %s\n' % (elapsed, msg)).encode())


def main():
    global _server_start
    _server_start = time.time()
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
    parser.add_argument('--terminal-profile', default='7FFFFFFFFF0000CF02', metavar='HEX',
                        help='TERMINAL PROFILE payload (default: 10-byte profile with SMS-PP download and event list)')
    parser.add_argument('--no-card-init', action='store_true', default=False,
                        help='Skip pysim card initialization (preserve CAT session — no file manager)')

    opts = parser.parse_args()
    opts.skip_card_init = opts.no_card_init
    sl = None
    scc = None
    card = None
    rs = None
    sim_menu = None
    event_list = None
    try:
        kwargs = {}
        if opts.apdu_trace:
            kwargs['apdu_tracer'] = StderrApduTracer()
        sl = mod.init_reader(opts, **kwargs)
        scc = SimCardCommands(sl)
        scc.cat_cla = '80'  # UICC CLA default; overridden for SIM after init_card
        scc._tp.proactive_handler = _DefaultProactiveHandler()
        sl.wait_for_card(3)
        sys.stderr.write('INIT(pre): sending TERMINAL PROFILE (CLA=%s)\n' % scc.cat_cla)
        sim_menu, event_list = _send_terminal_profile(scc, opts.terminal_profile)
        sys.stderr.write('INIT(pre): TP done, menu=%s events=%s\n' % ('yes' if sim_menu else 'no', 'yes' if event_list else 'no'))
        rs, card = mod.init_card(sl, opts.skip_card_init)
        scc.cat_cla = '80' if isinstance(card, UiccCardBase) else 'a0'
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
    if scc and hasattr(scc, '_tp'):
        scc._tp.apdu_tracer = StderrApduTracer()
        try:
            sys.stderr.write('INIT: sending TERMINAL PROFILE %s (CLA=%s)\n' % (opts.terminal_profile, scc.cat_cla))
            sm, el = _send_terminal_profile(scc, opts.terminal_profile)
            sys.stderr.write('INIT: TP done, menu=%s events=%s\n' % ('yes' if sm else 'no', 'yes' if el else 'no'))
            sim_menu = sm or sim_menu
            event_list = el or event_list
        except Exception:
            traceback.print_exc(file=sys.stderr)
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
    server.terminal_profile = opts.terminal_profile
    server.sim_menu = sim_menu
    server.event_list = event_list
    server.menu_active = False
    server.stk_pending = None
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