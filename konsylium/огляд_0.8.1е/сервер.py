#!/usr/bin/env python3
"""Сервер огляду 0.8.1е (127.0.0.1:28720): /ціна/ТОВАР — ціна за 0,4 с; /повільно/N — «відповідь N» за 0,5 с;
/переадресація — 302; /байти/N — N байтів «a»; /не-utf8; /обірвано — 50 зі 100 обіцяних байтів;
/капає/N — N байтів по одному на 0,5 с; POST на ці адреси — те саме, POST деінде — відлуння тіла. Лише локально."""
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
    def edge(self):
        p = urllib.parse.unquote(self.path)
        if p.startswith('/капає/'):
            n = min(int(p.rsplit('/', 1)[-1] or 0), 200)
            try:
                self.send_response(200)
                self.send_header('Content-Length', str(n))
                self.end_headers()
                for _ in range(n):
                    self.wfile.write(b'a')
                    self.wfile.flush()
                    time.sleep(0.5)
            except OSError:
                pass
            return True
        if p.startswith('/байти/'):
            body = b'a' * min(int(p.rsplit('/', 1)[-1] or 0), 3_000_000)
        elif p == '/не-utf8':
            body = b'ok \xff'
        elif p == '/обірвано':
            body = b'a' * 50
        else:
            return False
        self.send_response(200)
        self.send_header('Content-Length', str(100 if p == '/обірвано' else len(body)))
        self.end_headers()
        self.wfile.write(body)
        return True
    def do_GET(self):
        if self.edge():
            return
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
        if self.edge():
            return
        self.send(200, 'отримано ' + self.headers.get('Content-Type', '') + ' ' + body.decode('utf-8', 'replace'))
    def log_message(self, *a):
        pass
http.server.ThreadingHTTPServer(('127.0.0.1', 28720), H).serve_forever()
