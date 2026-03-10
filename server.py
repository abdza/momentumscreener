"""
Premarket Volume Tracker - simple HTTP server (no external dependencies).
Run: python3 server.py
Then open: http://localhost:5000
"""
from http.server import HTTPServer, BaseHTTPRequestHandler
import json
import os
import glob
from datetime import datetime
from urllib.parse import urlparse, parse_qs

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, 'pretop20')


class Handler(BaseHTTPRequestHandler):

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        params = parse_qs(parsed.query)

        if path == '/':
            self._serve_file('index.html', 'text/html; charset=utf-8')
        elif path == '/api/dates':
            self._serve_json(self._get_dates())
        elif path == '/api/data':
            date = params.get('date', [datetime.now().strftime('%Y%m%d')])[0]
            self._serve_json(self._get_data(date))
        elif path == '/api/latest':
            date = params.get('date', [datetime.now().strftime('%Y%m%d')])[0]
            self._serve_json(self._get_latest(date))
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

    # ── Data helpers ──────────────────────────────────────────────────────────

    def _get_dates(self):
        files = glob.glob(os.path.join(DATA_DIR, 'screener_*.json'))
        dates = set()
        for f in files:
            parts = os.path.basename(f).replace('.json', '').split('_')
            if len(parts) == 3:
                dates.add(parts[1])
        return sorted(list(dates), reverse=True)

    def _get_data(self, date):
        files = sorted(glob.glob(os.path.join(DATA_DIR, f'screener_{date}_*.json')))
        snapshots = []
        for f in files:
            try:
                with open(f) as fp:
                    snapshots.append(json.load(fp))
            except Exception:
                pass
        return snapshots

    def _get_latest(self, date):
        files = sorted(glob.glob(os.path.join(DATA_DIR, f'screener_{date}_*.json')))
        return {
            'latest': os.path.basename(files[-1]) if files else None,
            'count': len(files)
        }

    def log_message(self, fmt, *args):
        print(f'[{self.log_date_time_string()}] {fmt % args}')


if __name__ == '__main__':
    port = 5000
    server = HTTPServer(('0.0.0.0', port), Handler)
    print(f'Premarket tracker running at http://localhost:{port}')
    print('Press Ctrl+C to stop.')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\nStopped.')
