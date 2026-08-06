import argparse
import sys
import traceback
from http.server import HTTPServer
from pySim.card_handler import CardHandler
from pySim.commands import SimCardCommands

from .shell import load_pysim_app
from .server import PysimHandler, StderrApduTracer


def main():
    mod = load_pysim_app()
    parser = mod.option_parser
    parser.description = 'pysim-otaman-server — HTTP API for pysim'
    parser.add_argument('--http-host', default='127.0.0.1', help='Bind address (default: 127.0.0.1)')
    parser.add_argument('--http-port', type=int, default=8080, help='Bind port (default: 8080)')
    parser.add_argument('--log-requests', action='store_true', default=False, help='Log request/response payloads to stderr')

    opts = parser.parse_args()
    sl = None
    scc = None
    card = None
    rs = None
    try:
        kwargs = {}
        if opts.apdu_trace:
            kwargs['apdu_tracer'] = StderrApduTracer()
        sl = mod.init_reader(opts, **kwargs)
        scc = SimCardCommands(sl)
        sl.wait_for_card(3)
        rs, card = mod.init_card(sl, opts.skip_card_init)
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
    server = HTTPServer((opts.http_host, opts.http_port), PysimHandler)
    server.sl = sl
    server.scc = scc
    server.card = card
    server.rs = rs
    server.app = app
    server.log_requests = opts.log_requests
    print(f"pysim-otaman-server listening on http://{opts.http_host}:{opts.http_port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
        server.shutdown()


if __name__ == '__main__':
    main()