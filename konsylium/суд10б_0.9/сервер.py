#!/usr/bin/env python3
"""Сервер суду 10 (127.0.0.1:28731) — лише локально.

Дзеркало github для «джерела_модулів» власника суду: GET /github/ВЛАСНИК/РЕПО/КОМІТ/ШЛЯХ віддає файл
  ВЛАСНИК = nigredo  → ../дзеркало/РЕПО/КОМІТ/ШЛЯХ (спільна бібліотека суду);
  ВЛАСНИК = <суддя>  → ../<суддя>/дзеркало/РЕПО/КОМІТ/ШЛЯХ (кожен суддя «публікує» у своїй теці);
  ВЛАСНИК = sud      → межі мережі за назвою РЕПО (будь-який коміт і шлях):
      kapaie — 200 байтів по одному на 0,5 с; pereadresatsiia — 301 на модуль бібліотеки; velykyi — 1 000 001 байт;
      rivno — модуль рівно 1 000 000 байтів; obirvano — 50 зі 100 обіцяних байтів; lfs — вказівник git LFS;
      bez-dovzhyny — модуль без Content-Length; p503 — 503.
GET /журнал — останні 300 запитів до /github/ (час UTC, шлях, статус): чи ходить у мережу запуск, --печатка, --розбір.
Решта — як у сервері огляду 0.8.1е: /ціна/ТОВАР, /повільно/N, /переадресація, /байти/N, /не-utf8, /обірвано,
/капає/N; POST деінде — відлуння тіла."""
import collections
import datetime
import http.server
import pathlib
import threading
import time
import urllib.parse

K = pathlib.Path(__file__).resolve().parent
ROLES = {'skeptyk', 'praktyk', 'movoznavets', 'audytor', 'novachok', 'orkestrator', 'gemini'}
ЦІНИ = {'хліб': '28.50', 'сіль': '12.10', 'мед': '245.00', 'сир': '310.40', 'чай': '89.99', 'кава': '410.00',
        'олія': '67.30', 'вода': '15.00'}
LOG, LOCK = collections.deque(maxlen=300), threading.Lock()
RIVNO = '🜂\n← x 「'.encode() + b'a' * (1_000_000 - len('🜂\n← x 「」\n'.encode())) + '」\n'.encode()
LFS = b'version https://git-lfs.github.com/spec/v1\noid sha256:' + b'0' * 64 + b'\nsize 10\n'


class H(http.server.BaseHTTPRequestHandler):
    def send(self, code, body, extra=(), length=True):
        body = body if isinstance(body, bytes) else body.encode()
        self.send_response(code)
        self.send_header('Content-Type', 'text/plain; charset=utf-8')
        for k, v in extra:
            self.send_header(k, v)
        if length:
            self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        return code

    def note(self, code):
        with LOCK:
            LOG.append(f'{datetime.datetime.now(datetime.timezone.utc):%H:%M:%S} {self.command} {self.path} → {code}')

    def drip(self, n, total):
        try:
            self.send_response(200)
            self.send_header('Content-Length', str(total))
            self.end_headers()
            for _ in range(n):
                self.wfile.write(b'a')
                self.wfile.flush()
                time.sleep(0.5)
        except OSError:
            pass
        return 200

    def mirror(self, p):
        parts = p[len('/github/'):].split('/')
        if len(parts) < 4 or not all(parts[:3]):
            return self.send(404, 'немає')
        owner, repo, rest = parts[0], parts[1], parts[3:]
        if owner == 'sud':
            if repo == 'kapaie':
                return self.drip(200, 200)
            if repo == 'pereadresatsiia':
                return self.send(301, '', [('Location', f'/github/nigredo/tekst/{TEKST}/slova.ngr')])
            if repo == 'velykyi':
                return self.send(200, '🜂\n'.encode() + b'a' * 1_000_001)
            if repo == 'rivno':
                return self.send(200, RIVNO)
            if repo == 'obirvano':
                self.send_response(200)
                self.send_header('Content-Length', '100')
                self.end_headers()
                self.wfile.write(b'a' * 50)
                return 200
            if repo == 'lfs':
                return self.send(200, LFS)
            if repo == 'bez-dovzhyny':
                return self.send(200, '🜂\n← x 1\n', length=False)
            if repo == 'p503':
                return self.send(503, 'перевантажено')
            return self.send(404, 'немає')
        base = K / 'дзеркало' if owner == 'nigredo' else K / owner / 'дзеркало' if owner in ROLES else None
        if base is None:
            return self.send(404, 'немає')
        f = base.joinpath(repo, parts[2], *rest).resolve()
        if not f.is_relative_to(base.resolve()) or not f.is_file():
            return self.send(404, 'немає')
        return self.send(200, f.read_bytes())

    def edge(self):
        p = urllib.parse.unquote(self.path)
        if p.startswith('/капає/'):
            n = min(int(p.rsplit('/', 1)[-1] or 0), 200)
            self.drip(n, n)
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
        p = urllib.parse.unquote(self.path)
        if p.startswith('/github/'):
            code = 500
            try:
                code = self.mirror(p)
            finally:
                self.note(code)
            return
        if p == '/журнал':
            with LOCK:
                return self.send(200, '\n'.join(LOG) + '\n' if LOG else '(запитів до /github/ ще не було)\n')
        if self.edge():
            return
        if p.startswith('/ціна/'):
            time.sleep(0.4)
            return self.send(200, ЦІНИ[p[6:]]) if p[6:] in ЦІНИ else self.send(404, 'немає')
        if p.startswith('/повільно/'):
            time.sleep(0.5)
            return self.send(200, 'відповідь ' + p.rsplit('/', 1)[-1])
        if p == '/переадресація':
            return self.send(302, '', [('Location', 'http://example.com/')])
        self.send(200, 'гаразд ' + p)

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get('Content-Length', 0)))
        if urllib.parse.unquote(self.path).startswith('/github/'):
            self.note(405)
            return self.send(405, 'дзеркало — лише GET')
        if self.edge():
            return
        self.send(200, 'отримано ' + self.headers.get('Content-Type', '') + ' ' + body.decode('utf-8', 'replace'))

    def log_message(self, *a):
        pass


TEKST = 'b857639070f69dae3ddbda71c10b1ea49710b6c7'
http.server.ThreadingHTTPServer(('127.0.0.1', 28731), H).serve_forever()
