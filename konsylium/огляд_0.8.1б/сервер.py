#!/usr/bin/env python3
"""Сервер огляду 0.8.1б (127.0.0.1:28716): /ціна/ТОВАР — ціна за 0,4 с; /повільно/N — «відповідь N» за 0,5 с;
/переадресація — 302; POST будь-куди — відлуння тіла. Лише локально."""
import http.server, time, urllib.parse
ЦІНИ = {'хліб': '28.50', 'сіль': '12.10', 'мед': '245.00', 'сир': '310.40', 'чай': '89.99', 'кава': '410.00',
        'олія': '67.30', 'вода': '15.00'}
class H(http.server.BaseHTTPRequestHandler):
    def send(self, code, body, extra=()):
        self.send_response(code)
        self.send_header('Content-Type', 'text/plain; charset=utf-8')
        for k, v in extra:
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body.encode())
    def do_GET(self):
        p = urllib.parse.unquote(self.path)
        if p.startswith('/ціна/'):
            time.sleep(0.4)
            return self.send(200, ЦІНИ.get(p[6:], 'немає')) if p[6:] in ЦІНИ else self.send(404, 'немає')
        if p.startswith('/повільно/'):
            time.sleep(0.5)
            return self.send(200, 'відповідь ' + p.rsplit('/', 1)[-1])
        if p == '/переадресація':
            return self.send(302, '', [('Location', 'http://example.com/')])
        self.send(200, 'гаразд ' + p)
    def do_POST(self):
        body = self.rfile.read(int(self.headers.get('Content-Length', 0)))
        self.send(200, 'отримано ' + self.headers.get('Content-Type', '') + ' ' + body.decode('utf-8', 'replace'))
    def log_message(self, *a):
        pass
http.server.ThreadingHTTPServer(('127.0.0.1', 28716), H).serve_forever()
