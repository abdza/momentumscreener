"""
Premarket Volume Tracker + Market Hour Tracker
Run: python3 server.py
  http://localhost:5000/pretop20/    – premarket tracker
  http://localhost:5000/markethour/  – intraday momentum tracker
"""
from http.server import HTTPServer, BaseHTTPRequestHandler
import json
import os
import glob
from datetime import datetime
from urllib.parse import urlparse, parse_qs

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PRETOP20_DIR = os.path.join(BASE_DIR, 'pretop20')
MOMENTUM_DIR = os.path.join(BASE_DIR, 'momentum_data')


class Handler(BaseHTTPRequestHandler):

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        params = parse_qs(parsed.query)

        # ── pretop20 ──────────────────────────────────────────────────────────
        if path in ('/', '/pretop20', '/pretop20/'):
            self._serve_file('index.html', 'text/html; charset=utf-8')
        elif path == '/pretop20/api/dates':
            self._serve_json(self._pretop20_dates())
        elif path == '/pretop20/api/data':
            date = params.get('date', [datetime.now().strftime('%Y%m%d')])[0]
            self._serve_json(self._pretop20_data(date))
        elif path == '/pretop20/api/latest':
            date = params.get('date', [datetime.now().strftime('%Y%m%d')])[0]
            self._serve_json(self._pretop20_latest(date))

        # ── markethour ────────────────────────────────────────────────────────
        elif path in ('/markethour', '/markethour/'):
            self._serve_file('index2.html', 'text/html; charset=utf-8')
        elif path == '/markethour/api/dates':
            self._serve_json(self._markethour_dates())
        elif path == '/markethour/api/data':
            date = params.get('date', [datetime.now().strftime('%Y%m%d')])[0]
            self._serve_json(self._markethour_data(date))
        elif path == '/markethour/api/latest':
            date = params.get('date', [datetime.now().strftime('%Y%m%d')])[0]
            self._serve_json(self._markethour_latest(date))

        else:
            self.send_error(404)

    # ── Responders ────────────────────────────────────────────────────────────

    def _serve_file(self, filename, content_type):
        filepath = os.path.join(BASE_DIR, filename)
        try:
            with open(filepath, 'rb') as f:
                content = f.read()
            self.send_response(200)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', len(content))
            self.end_headers()
            self.wfile.write(content)
        except FileNotFoundError:
            self.send_error(404)

    def _serve_json(self, data):
        content = json.dumps(data).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Content-Length', len(content))
        self.end_headers()
        self.wfile.write(content)

    # ── pretop20 data helpers ─────────────────────────────────────────────────

    def _pretop20_dates(self):
        files = glob.glob(os.path.join(PRETOP20_DIR, 'screener_*.json'))
        dates = set()
        for f in files:
            parts = os.path.basename(f).replace('.json', '').split('_')
            if len(parts) == 3:
                dates.add(parts[1])
        return sorted(list(dates), reverse=True)

    def _pretop20_data(self, date):
        files = sorted(glob.glob(os.path.join(PRETOP20_DIR, f'screener_{date}_*.json')))
        snapshots = []
        for f in files:
            try:
                with open(f) as fp:
                    snapshots.append(json.load(fp))
            except Exception:
                pass
        return snapshots

    def _pretop20_latest(self, date):
        files = sorted(glob.glob(os.path.join(PRETOP20_DIR, f'screener_{date}_*.json')))
        return {'latest': os.path.basename(files[-1]) if files else None, 'count': len(files)}

    # ── markethour data helpers ───────────────────────────────────────────────

    def _markethour_dates(self):
        files = glob.glob(os.path.join(MOMENTUM_DIR, 'raw_data_*.json'))
        dates = set()
        for f in files:
            parts = os.path.basename(f).replace('.json', '').split('_')
            if len(parts) == 4:
                dates.add(parts[2])
        return sorted(list(dates), reverse=True)

    def _markethour_data(self, date):
        files = sorted(glob.glob(os.path.join(MOMENTUM_DIR, f'raw_data_{date}_*.json')))
        snapshots = []
        for f in files:
            try:
                parts = os.path.basename(f).replace('.json', '').split('_')
                d, t = parts[2], parts[3]
                ts = f'{d[:4]}-{d[4:6]}-{d[6:8]}T{t[:2]}:{t[2:4]}:{t[4:6]}'
                with open(f) as fp:
                    raw = fp.read().replace('NaN', 'null').replace('Infinity', 'null')
                snapshots.append({'timestamp': ts, 'data': json.loads(raw)})
            except Exception:
                pass
        return snapshots

    def _markethour_latest(self, date):
        files = sorted(glob.glob(os.path.join(MOMENTUM_DIR, f'raw_data_{date}_*.json')))
        return {'latest': os.path.basename(files[-1]) if files else None, 'count': len(files)}

    def log_message(self, fmt, *args):
        print(f'[{self.log_date_time_string()}] {fmt % args}')


if __name__ == '__main__':
    port = 5000
    server = HTTPServer(('0.0.0.0', port), Handler)
    print(f'Server running at http://localhost:{port}')
    print(f'  Premarket tracker  → http://localhost:{port}/pretop20/')
    print(f'  Market hour tracker → http://localhost:{port}/markethour/')
    print('Press Ctrl+C to stop.')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\nStopped.')
