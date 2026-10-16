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
NGR = ROOT / 'interpreter' / 'ngr.py'

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

    hits = 0                  # скільки запитів отримав сервер (М7: під час повтору — жодного)

    def reply(self, text, ctype):
        Server.hits += 1
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


def held_out():
    """М3 на відкладеному наборі: програми, які моделі написали з першої спроби обома мовами для задач bench/м2
    (мову не налаштовували під ці задачі, рішення — не автора мови)."""
    ratios, n = [], 0
    for d in sorted((BENCH / 'м2').glob('прогони*/*')):
        if not d.is_dir():
            continue
        for py in sorted(d.glob('*.py.json')):
            ng = py.with_name(py.name.replace('.py.json', '.ngr.json'))
            if not ng.exists():
                continue
            a, b = (json.loads(f.read_text(encoding='utf-8')) for f in (py, ng))
            if a and b and a[0].get('гаразд') and b[0].get('гаразд'):
                n += 1
                ratios.append(tokens(b[0]['код'])['o200k_base'] / tokens(a[0]['код'])['o200k_base'])
    if not ratios:
        return '- **М3 на відкладеному наборі:** немає прогонів bench/м2.'
    return (f'- **М3 на відкладеному наборі** (рішення моделей з першої спроби обома мовами, bench/м2, {n} пар): медіана '
            f'Nigredo/Python з печаткою — **{statistics.median(ratios):.2f}** (задачі, під які мову не скорочували; програми '
            f'писав не автор мови, а моделі з памʼяткою).')


def main():
    write_expected = '--очікуване' in sys.argv
    srv = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Server)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    home = pathlib.Path(tempfile.mkdtemp(prefix='ngr-bench-'))
    (BENCH / 'тимч').mkdir(exist_ok=True)
    (home / 'дозволи.json').write_text(json.dumps({'дозволено': [
        f'файл.читати:{BENCH / "дані"}', f'файл.читати:{BENCH / "тимч"}', f'файл.писати:{BENCH / "тимч"}',
        f'мережа.взяти:127.0.0.1:{port}', f'мережа.послати:127.0.0.1:{port}']}, ensure_ascii=False), encoding='utf-8')
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
            mods = [(d / m).read_text(encoding='utf-8') for m in meta.get('модулі' if lang == 'py' else 'модулі_ngr', [])]
            code = text + ''.join(mods)
            if lang == 'ngr':                                               # Nigredo без печаток (М3)
                body = ''.join(t.split('\n', 1)[1] for t in [text, *mods])
            else:
                body = code
            prog = src
            if lang == 'ngr' and '{ПОРТ}' in text:
                prog = d / '.рішення.тимч.ngr'
                prog.write_text(text.replace('{ПОРТ}', str(port)), encoding='utf-8')
            if lang == 'ngr':
                cmd = [sys.executable, str(NGR), str(prog), '--', str(port)]
            else:
                cmd = [sys.executable, str(prog), str(port)]
            tpf = home / 'шлях_сліду.txt'
            replayed = None
            try:
                out, dt, err = run(cmd, d, dict(env, NIGREDO_TRACE_PATH_FILE=str(tpf)) if lang == 'ngr' else env,
                                   times, reset)
                if lang == 'ngr':                                           # М7: останній запуск — повторити зі сліду
                    hits0 = Server.hits
                    rp = subprocess.run([sys.executable, str(NGR), '--повторити', tpf.read_text(encoding='utf-8'),
                                         str(prog)], cwd=d, env=env, capture_output=True, text=True, timeout=120)
                    replayed = rp.returncode == 0 and rp.stdout == out[len(out) - len(rp.stdout):] and \
                        '✓ повтор збігся' in rp.stderr and Server.hits == hits0      # і сервер не отримав жодного запиту
            finally:
                if prog != src:
                    prog.unlink()
            if lang == 'py' and write_expected and not exp_path.exists() and not err:
                exp_path.write_text(out, encoding='utf-8')
            expected = exp_path.read_text(encoding='utf-8') if exp_path.exists() else None
            right = err is None and out == expected
            ok = right and (limit is None or dt <= limit)
            why = err[0] if err else ('немає очікуваного' if expected is None else
                                      'інший вивід' if out != expected else
                                      f'повільно: {dt:.2f} с > {limit} с' if not ok else '')
            row[lang] = {'ok': ok, 'вивід_ok': right, 'час': dt, 'символів': len(body), 'токени': tokens(body),
                         'токени_з_печаткою': tokens(code) if lang == 'ngr' else None, 'чому': why, 'повтор': replayed}
        row['гарантія'] = bool(row['ngr'] and row['ngr']['ok'])
        row['примітка'] = meta.get('python_вимога', '')
        rows.append(row)
    bugs = []                      # М5: однакова помилка; чи впіймано ДО запуску (нічого не виконується)
    flakes = shutil.which('pyflakes') or None
    try:
        import pyflakes  # noqa: F401
        flakes = [sys.executable, '-m', 'pyflakes']
    except ImportError:
        flakes = None
    for d in sorted(p for p in (BENCH / 'помилки').iterdir() if p.is_dir()):
        meta = json.loads((d / 'помилка.json').read_text(encoding='utf-8'))
        py = subprocess.run([sys.executable, '-m', 'py_compile', str(d / 'рішення.py')], capture_output=True)
        pf = subprocess.run(flakes + [str(d / 'рішення.py')], capture_output=True) if flakes else None
        ng = subprocess.run([sys.executable, str(NGR), '--перевірити', str(d / 'рішення.ngr')], capture_output=True,
                            text=True, env=env)
        bugs.append({'задача': d.name, 'назва': (d / 'помилка.md').read_text(encoding='utf-8').strip('# \n'),
                     'клас': meta['клас'], 'чому_клас': meta.get('чому', ''),
                     'py': py.returncode != 0, 'pyflakes': None if pf is None else (py.returncode != 0 or pf.returncode != 0),
                     'ngr': ng.returncode != 0, 'чим': (ng.stdout.strip().splitlines() or [''])[0][:110]})
    falses = []                    # хибні тривоги: правильні програми, які --перевірити не мусить відкидати
    for f in sorted((BENCH / 'правильні').glob('*.ngr')):
        ng = subprocess.run([sys.executable, str(NGR), '--перевірити', str(f)], capture_output=True, text=True, env=env)
        falses.append({'назва': f.stem, 'тривога': ng.returncode != 0, 'чим': (ng.stdout.strip().splitlines() or [''])[0][:110]})
    for p in (BENCH / 'помилки').rglob('__pycache__'):
        shutil.rmtree(p, ignore_errors=True)
    srv.shutdown()
    shutil.rmtree(home, ignore_errors=True)
    report(rows, bugs, falses)


def fmt_tok(r, key='токени'):
    if not r:
        return '—'
    t = r[key] if r.get(key) else {}
    return str(t.get('o200k_base', '')) or f'{r["символів"]} симв.'


def report(rows, bugs=(), falses=()):
    unit = 'токени o200k' if ENC else 'символи (tiktoken немає)'
    lines = ['# Мірило: Nigredo проти Python', '',
             f'Згенеровано `bench/міряти.py` ({time.strftime("%Y-%m-%d")}). Одиниця — {unit}. Nigredo — **з печаткою** '
             f'(обовʼязкова частина програми); у дужках — без печаток. Час — з запуском інтерпретатора.', '',
             '| Задача | Python | Nigredo | Python, ток. | Nigredo, ток. (без печ.) | Python, с | Nigredo, с | Примітки |',
             '|---|---|---|---|---|---|---|---|']
    mark = lambda r: '—' if r is None else ('✓' if r['ok'] else '✗')   # noqa: E731
    for r in rows:
        p, n = r['py'], r['ngr']
        why = '; '.join(x for x in [f'Python: {p["чому"]}' if p and p['чому'] else '', r.get('примітка', ''),
                                    'Nigredo: рішення немає (бракує можливості)' if n is None else
                                    f'Nigredo: {n["чому"]}' if n['чому'] else ''] if x)
        ntok = f'{fmt_tok(n, "токени_з_печаткою")} ({fmt_tok(n)})' if n else '—'
        ntime = f'{n["час"]:.2f}' if n else '—'
        lines.append(f'| {r["задача"]} {r["назва"]} | {mark(p)} | {mark(n)} | {fmt_tok(p)} | {ntok} | '
                     f'{p["час"]:.2f} | {ntime} | {why} |')
    both = [r for r in rows if r['py'] and r['py']['вивід_ok'] and r['ngr'] and r['ngr']['вивід_ok']]
    key = 'o200k_base' if ENC else None
    size = lambda x, k='токени': x[k][key] if key else x['символів']   # noqa: E731
    tok_seal = statistics.median(size(r['ngr'], 'токени_з_печаткою') / size(r['py']) for r in both) if both else None
    tok = statistics.median(size(r['ngr']) / size(r['py']) for r in both) if both else None
    spd = statistics.median(r['ngr']['час'] / r['py']['час'] for r in both) if both else None
    n_ok, p_ok = sum(bool(r['ngr'] and r['ngr']['ok']) for r in rows), sum(bool(r['py'] and r['py']['ok']) for r in rows)
    real = [b for b in bugs if b['клас'] == 'помилка']
    fp = sum(f['тривога'] for f in falses)
    lines += ['', '## Підсумок за умовами 1.0', '',
              f'- **М1 покриття:** Nigredo {n_ok}/{len(rows)}, Python {p_ok}/{len(rows)}.',
              (f'- **М3 довжина:** медіана Nigredo/Python **з печаткою — {tok_seal:.2f}**, без печаток — {tok:.2f} '
               f'({len(both)} спільних задач; умова 1.0: ≤ 1.00 з печаткою).') if tok else '- **М3:** немає спільних задач.',
              f'- **М4 гарантії** (властивість мови, не вимір): печатка й слід — у {n_ok} задачах Nigredo; у самому Python '
              f'такого засобу немає (обмежувати й перевіряти — засобами ОС і зовнішніми інструментами).',
              (f'- **М6 швидкість:** медіана часу Nigredo/Python = {spd:.2f} на всіх {len(both)} задачах з правильним '
               f'виводом обох, зокрема повільних (умова 1.0: ≤ 3.00).') if spd else '',
              (f'- **М5 помилки до запуску** (лише справжні помилки, {len(real)}): Nigredo {sum(b["ngr"] for b in real)}, '
               f'Python + pyflakes {sum(bool(b["pyflakes"]) for b in real)}, Python (`py_compile`) {sum(b["py"] for b in real)}. '
               f'Ще {len(bugs) - len(real)} випадки — властивості моделі Nigredo (дозволи, перепризначення, регулярки без '
               f'відкатів), їх порівнювати з Python нечесно. Хибні тривоги на {len(falses)} правильних програмах: {fp}. '
               f'Умова 1.0: більше, ніж Python + pyflakes, і 0 хибних тривог.') if bugs else '',
              held_out(),
              f'- **М7 відтворюваність** (перевірка наявності, не міра: повтор із записаними відповідями збігається за '
              f'побудовою): `ngr --повторити` останнього запуску збігся зі слідом у '
              f'{sum(bool(r["ngr"] and r["ngr"].get("повтор")) for r in rows)} з {sum(bool(r["ngr"]) for r in rows)} '
              f'задач Nigredo, і тестовий сервер під час повторів не отримав жодного запиту; Python як мова такого засобу '
              f'не має (є зовнішні бібліотеки record/replay, напр. для HTTP).',
              '- **М2** — окремий прогін моделей на задачах поза памʼяткою: `bench/м2/РЕЗУЛЬТАТИ.md`.']
    if bugs:
        lines += ['', '## М5: навмисні помилки — чи впіймано до запуску', '',
                  '| Помилка | Клас | Python | Python + pyflakes | Nigredo | Як Nigredo її бачить |', '|---|---|---|---|---|---|']
        yn = lambda v: '—' if v is None else ('✓' if v else '✗')       # noqa: E731
        lines += [f'| {b["задача"]} {b["назва"]} | {b["клас"]}{(": " + b["чому_клас"]) if b["чому_клас"] else ""} | '
                  f'{yn(b["py"])} | {yn(b["pyflakes"])} | {yn(b["ngr"])} | {b["чим"].replace("|", "¦")} |' for b in bugs]
    if falses:
        lines += ['', '## Хибні тривоги: правильні програми (`bench/правильні/`)', '',
                  '| Програма | Тривога | Що сказав `--перевірити` |', '|---|---|---|']
        lines += [f'| {f["назва"]} | {"✗ так" if f["тривога"] else "✓ ні"} | {f["чим"].replace("|", "¦")} |' for f in falses]
    (BENCH / 'РЕЗУЛЬТАТИ.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print('\n'.join(lines))


if __name__ == '__main__':
    main()
