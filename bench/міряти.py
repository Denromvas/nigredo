#!/usr/bin/env python3
"""Мірило «Nigredo проти Python» (ПЛАН_1.0.md, фаза 0).

Для кожної задачі з bench/задачі/: запускає рішення.py і рішення.ngr, звіряє вивід з очікуване.txt, рахує символи
й токени (tiktoken, якщо є; інакше лише символи) і час. Пише bench/РЕЗУЛЬТАТИ.md.

  python3 bench/міряти.py                    виміряти все
  python3 bench/міряти.py --очікуване        записати очікуване.txt з виводу Python (лише де його ще немає)
"""
import http.server
import json
import os
import pathlib
import shutil
import statistics
import subprocess
import sys
import tempfile
import threading
import time

BENCH = pathlib.Path(__file__).resolve().parent
ROOT = BENCH.parent
NGR = ROOT / 'interpreter' / 'nigredo.py'

try:
    import tiktoken
    ENC = {n: tiktoken.get_encoding(n) for n in ('cl100k_base', 'o200k_base')}
except Exception:            # noqa: BLE001 — без tiktoken міряємо лише символи
    ENC = {}


class Server(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith('/slow/'):
            time.sleep(.5)
            self.reply(f'відповідь {self.path.rsplit("/", 1)[1]}', 'text/plain')
        else:
            self.send_error(404)

    def do_POST(self):
        if self.path != '/report':
            return self.send_error(404)
        body = json.loads(self.rfile.read(int(self.headers.get('Content-Length', 0))) or b'{}')
        self.reply(json.dumps({'прийнято': True, '№': 7, 'отримано': body.get('сума')}, ensure_ascii=False), 'application/json')

    def reply(self, text, ctype):
        data = text.encode()
        self.send_response(200)
        self.send_header('Content-Type', f'{ctype}; charset=utf-8')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):
        pass


def tokens(text):
    return {n: len(e.encode(text)) for n, e in ENC.items()}


def run(cmd, cwd, env, times, reset):
    out, t0 = '', time.perf_counter()
    if reset:
        (cwd / reset).unlink(missing_ok=True)
    for _ in range(times):
        p = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, timeout=120)
        out += p.stdout
        if p.returncode:
            return out, time.perf_counter() - t0, p.stderr.strip().splitlines()[-1:] or [f'код {p.returncode}']
    return out, time.perf_counter() - t0, None


def main():
    write_expected = '--очікуване' in sys.argv
    srv = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Server)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    home = pathlib.Path(tempfile.mkdtemp(prefix='ngr-bench-'))
    (BENCH / 'тимч').mkdir(exist_ok=True)
    (home / 'дозволи.json').write_text(json.dumps({'дозволено': [
        f'файл.читати:{BENCH / "дані"}', f'файл.читати:{BENCH / "тимч"}', f'файл.писати:{BENCH / "тимч"}',
        f'мережа.взяти:127.0.0.1:{port}']}, ensure_ascii=False), encoding='utf-8')
    env = dict(os.environ, NIGREDO_HOME=str(home))
    rows = []
    for d in sorted(p for p in (BENCH / 'задачі').iterdir() if p.is_dir()):
        meta = json.loads((d / 'задача.json').read_text(encoding='utf-8'))
        times, reset, limit = meta.get('запусків', 1), meta.get('скинути'), meta.get('ліміт_с')
        exp_path = d / 'очікуване.txt'
        row = {'задача': d.name, 'назва': meta['назва'], 'ліміт': limit}
        for lang, src in (('py', d / 'рішення.py'), ('ngr', d / 'рішення.ngr')):
            if not src.exists():
                row[lang] = None
                continue
            text = src.read_text(encoding='utf-8')
            code = text + ''.join((d / m).read_text(encoding='utf-8') for m in meta.get('модулі', []))
            body = text.split('\n', 1)[1] if lang == 'ngr' else code      # Nigredo без печатки (М3)
            prog = src
            if lang == 'ngr' and '{ПОРТ}' in text:
                prog = d / '.рішення.тимч.ngr'
                prog.write_text(text.replace('{ПОРТ}', str(port)), encoding='utf-8')
            if lang == 'ngr':
                cmd = [sys.executable, str(NGR), str(prog), '--', str(port)]
            else:
                cmd = [sys.executable, str(prog), str(port)]
            try:
                out, dt, err = run(cmd, d, env, times, reset)
            finally:
                if prog != src:
                    prog.unlink()
            if lang == 'py' and write_expected and not exp_path.exists() and not err:
                exp_path.write_text(out, encoding='utf-8')
            expected = exp_path.read_text(encoding='utf-8') if exp_path.exists() else None
            ok = err is None and out == expected and (limit is None or dt <= limit)
            why = err[0] if err else ('немає очікуваного' if expected is None else
                                      'інший вивід' if out != expected else
                                      f'повільно: {dt:.2f} с > {limit} с' if not ok else '')
            row[lang] = {'ok': ok, 'час': dt, 'символів': len(body), 'токени': tokens(body),
                         'токени_з_печаткою': tokens(code) if lang == 'ngr' else None, 'чому': why}
        row['гарантія'] = bool(row['ngr'] and row['ngr']['ok'])
        rows.append(row)
    srv.shutdown()
    shutil.rmtree(home, ignore_errors=True)
    report(rows)


def fmt_tok(r, key='токени'):
    if not r:
        return '—'
    t = r[key] if r.get(key) else {}
    return str(t.get('o200k_base', '')) or f'{r["символів"]} симв.'


def report(rows):
    unit = 'токени o200k' if ENC else 'символи (tiktoken немає)'
    lines = ['# Мірило: Nigredo проти Python', '',
             f'Згенеровано `bench/міряти.py` ({time.strftime("%Y-%m-%d")}). Nigredo — без рядка печатки; одиниця — {unit}.', '',
             '| Задача | Python | Nigredo | Python, ток. | Nigredo, ток. | Python, с | Nigredo, с | Чому ні |', '|---|---|---|---|---|---|---|---|']
    mark = lambda r: '—' if r is None else ('✓' if r['ok'] else '✗')   # noqa: E731
    for r in rows:
        p, n = r['py'], r['ngr']
        why = '; '.join(x for x in [f'Python: {p["чому"]}' if p and p['чому'] else '',
                                    'Nigredo: рішення немає (бракує можливості)' if n is None else
                                    f'Nigredo: {n["чому"]}' if n['чому'] else ''] if x)
        lines.append(f'| {r["задача"]} {r["назва"]} | {mark(p)} | {mark(n)} | {fmt_tok(p)} | {fmt_tok(n)} | '
                     f'{p["час"]:.2f} | {n["час"]:.2f} | {why} |' if p and n else
                     f'| {r["задача"]} {r["назва"]} | {mark(p)} | {mark(n)} | {fmt_tok(p)} | {fmt_tok(n)} | '
                     f'{p["час"]:.2f} | — | {why} |')
    both = [r for r in rows if r['py'] and r['py']['ok'] and r['ngr'] and r['ngr']['ok']]
    key = 'o200k_base' if ENC else None
    size = lambda x: x['токени'][key] if key else x['символів']   # noqa: E731
    tok = statistics.median(size(r['ngr']) / size(r['py']) for r in both) if both else None
    spd = statistics.median(r['ngr']['час'] / r['py']['час'] for r in both) if both else None
    n_ok, p_ok = sum(bool(r['ngr'] and r['ngr']['ok']) for r in rows), sum(bool(r['py'] and r['py']['ok']) for r in rows)
    lines += ['', '## Підсумок за умовами 1.0', '',
              f'- **М1 покриття:** Nigredo {n_ok}/{len(rows)}, Python {p_ok}/{len(rows)}.',
              f'- **М3 довжина:** медіана Nigredo/Python = {tok:.2f} на {len(both)} спільних задачах (умова 1.0: ≤ 1.00).' if tok else '- **М3:** немає спільних задач.',
              f'- **М4 гарантії:** печатка й слід — у {n_ok} задачах Nigredo; у Python — 0 (нема чим обмежити й перевірити).',
              f'- **М6 швидкість:** медіана часу Nigredo/Python = {spd:.2f} (умова 1.0: ≤ 3.00; час включає запуск інтерпретатора).' if spd else '',
              '- **М2, М5, М7** ще не міряються: потрібні прогін моделей, набір помилок і повтор зі сліду (фази 0, 1, 3).']
    (BENCH / 'РЕЗУЛЬТАТИ.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print('\n'.join(lines))


if __name__ == '__main__':
    main()
