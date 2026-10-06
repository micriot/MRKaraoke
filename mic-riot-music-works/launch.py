#!/usr/bin/env python3
"""Launch the auditor in a normal browser window, with an exclusive app lock."""
import argparse
import os
import sys
import fcntl
import signal
import threading
import webbrowser
from pathlib import Path
from auditor.server import Application, make_server

def main():
    frozen = getattr(sys, 'frozen', False)
    if frozen:
        os.environ['PATH'] = str(Path(sys._MEIPASS) / 'tools') + os.pathsep + os.environ.get('PATH','')
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--data', type=Path, default=(Path.home() / 'Library' / 'Application Support' / 'Mic Riot Music Works' / 'Libraries') if frozen else Path(__file__).resolve().parent / 'Libraries')
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args()
    args.data.mkdir(parents=True, exist_ok=True)
    with open(args.data / '.application.lock', 'a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            if not args.no_browser:
                webbrowser.open(f'http://127.0.0.1:{args.port}')
            print('Auditor is already running. Reopen its browser tab.')
            return
        app = Application(args.data)
        server = make_server(app, args.port)
        recent = app.libraries()
        if recent:
            app.open(recent[0]['id'])
        url = f'http://127.0.0.1:{server.server_address[1]}'
        print(f'Mic Riot Music Works v0.2 — Independent Audit and Copy Repair\n{url}\nOriginals remain read-only. Ctrl+C stops and saves the current queue.', flush=True)
        if not args.no_browser:
            webbrowser.open(url)
        def stop(*_):
            app.stop()
            threading.Thread(target=server.shutdown, daemon=True).start()
        signal.signal(signal.SIGINT, stop)
        signal.signal(signal.SIGTERM, stop)
        try:
            server.serve_forever()
        finally:
            app.stop()
            server.server_close()

if __name__ == '__main__':
    main()
