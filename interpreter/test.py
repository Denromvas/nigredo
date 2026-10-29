#!/usr/bin/env python3
"""Тести Nigredo:
  examples/*.ngr      — stdout має збігатися з *.out;
  tests/помилки/*.ngr — код виходу й текст помилки з рядка «※ очікується: КОД текст»;
  слід                — підписаний, завершений; обрізаний і підроблений без ключа — виявляються;
  ДЛЯ_АГЕНТІВ.md      — збігається з `ngr --памʼятка`, її приклади запускаються.
Тека власника (NIGREDO_HOME) для тестів тимчасова: дозволи, ключ і сліди — там.
"""
import hashlib
import http.server
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse

ROOT = pathlib.Path(__file__).resolve().parent.parent
NGR = ROOT / 'interpreter' / 'ngr.py'
DATA = ROOT / 'examples' / 'дані'
# NGR_TEST_BIN=шлях — ті самі тести іншим виконавцем (Атанор: athanor/target/<ціль>/release/athanor)
NGR_CMD = [os.environ['NGR_TEST_BIN']] if os.environ.get('NGR_TEST_BIN') else [sys.executable, str(NGR)]


def run(args, env):
    return subprocess.run([*NGR_CMD, *args], capture_output=True, text=True, env=env)


def header(src, key):
    for line in src.splitlines():
        if line.startswith(f'※ {key}:'):
            return line.split(':', 1)[1].strip()
    return None


PAGE = ('<html><head><title>Тест &amp; браузер</title><style>.x{color:red}</style></head><body>'
        '<nav><a href="/меню">меню</a></nav><script>alert("сховане")</script>'
        '<h1>Заголовок</h1><p>Перший абзац &laquo;у лапках&raquo; з <a href="/друга?x=1">посиланням</a>.</p>'
        '<p>Невидиме:󠁉 і <A HREF=друга.html>велике</A></p><!-- коментар --></body></html>')


class Redirect(http.server.BaseHTTPRequestHandler):
    def edge(self):
        """Відповіді на межах мережі (проєкт модулів з git, §14): рівно N байтів, не UTF-8, обірвана, по байту."""
        path = urllib.parse.unquote(self.path)
        bodies = {'/не-utf8': b'ok \xff', '/розрізано': 'кі'.encode()[:-1], '/обірвано': b'a' * 50}
        if path.startswith('/капає/'):        # по байту на 0,2 с: жодна операція сокета не стоїть довше за строк
            try:
                if path.endswith('заголовки'):
                    self.wfile.write(b'HTTP/1.0 200 OK\r\nX-Slow: ')
                else:
                    self.send_response(200)
                    self.send_header('Content-Length', '40')
                    self.end_headers()
                for _ in range(40):
                    self.wfile.write(b'a')
                    time.sleep(0.2)
                self.wfile.write(b'\r\n\r\nok' if path.endswith('заголовки') else b'')
            except OSError:                   # клієнт обірвав на строку
                pass
            return True
        if path.startswith('/байти/'):
            body = b'a' * int(path.rsplit('/', 1)[1])
        elif path in bodies:
            body = bodies[path]
        else:
            return False
        self.send_response(200)
        self.send_header('Content-Length', str(100 if path == '/обірвано' else len(body)))   # обірвано: 50 зі 100
        self.end_headers()
        self.wfile.write(body)
        return True

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get('Content-Length', 0)))
        if self.edge():
            return
        self.send_response(200)
        self.send_header('Content-Type', 'text/plain; charset=utf-8')
        self.end_headers()
        self.wfile.write(b'got ' + self.headers.get('Content-Type', '').encode() + b' ' + body)

    def do_GET(self):
        if self.edge():
            return
        if urllib.parse.unquote(self.path).startswith('/повільно/'):          # ‖: кожен запит — 0,3 с
            time.sleep(0.3)
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain; charset=utf-8')
            self.end_headers()
            self.wfile.write(('відповідь ' + urllib.parse.unquote(self.path).rsplit('/', 1)[-1]).encode())
            return
        path = urllib.parse.unquote(self.path)
        if path.startswith('/сайт/'):
            body = PAGE if 'друга' not in path else '<title>Друга</title><p>Ви на другій сторінці</p>'
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(body.encode())
            return
        self.send_response(302)
        self.send_header('Location', 'http://example.com/')
        self.end_headers()

    def log_message(self, *a):
        pass


MODS = ROOT / 'tests' / 'модулі_з_мережі'
COMMIT = '4b825dc642cb6eb9a060e54bf8d69288fbee4904'      # коміт — лише адреса (вигаданий), тотожність — sha256 вмісту
LIB = f'github.com/denromvas/ngr-lib@{COMMIT}'


def store_fixtures(home, files=None):
    """Покласти модулі у сховище власника так, як це зробив би ngr --отримати: <sha256>.ngr (адресоване вмістом)."""
    (home / 'модулі').mkdir(mode=0o700, exist_ok=True)
    out = {}
    for f in files or sorted(MODS.glob('*.ngr')):
        raw = f.read_bytes() if isinstance(f, pathlib.Path) else f
        h = hashlib.sha256(raw).hexdigest()
        (home / 'модулі' / f'{h}.ngr').write_bytes(raw)
        out[f.name if isinstance(f, pathlib.Path) else h] = h
    return out


class Mirror(http.server.BaseHTTPRequestHandler):
    """Дзеркало github для --отримати (модулі з git, §16.2): «джерела_модулів»: {"github.com": "http://127.0.0.1:П/"};
    у справжню мережу тести не ходять. files — шлях у репозиторії → байти; hits — усі запити (тест «0 запитів»)."""
    files, hits = {}, []

    def do_GET(self):
        Mirror.hits.append(self.path)
        parts = urllib.parse.unquote(self.path).lstrip('/').split('/', 3)
        name = parts[3] if len(parts) == 4 else ''
        if name == 'переадресація.ngr':          # на себе ж: навіть зламаний захист не вийде в справжню мережу
            self.send_response(301)
            self.send_header('Location', f'http://127.0.0.1:{self.server.server_address[1]}/denromvas/ngr-lib/{COMMIT}/tekst.ngr')
            self.end_headers()
            return
        if name == 'збій.ngr':
            self.send_response(503)
            self.end_headers()
            return
        if name == 'капає.ngr':                # по байту на 0,2 с: жодна операція сокета не стоїть довше за строк
            try:
                self.send_response(200)
                self.send_header('Content-Length', '40')
                self.end_headers()
                for _ in range(40):
                    self.wfile.write(b'a')
                    time.sleep(0.2)
            except OSError:
                pass
            return
        body = Mirror.files.get(name)
        if body is None:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


def type_sigs():
    import importlib.util
    spec = importlib.util.spec_from_file_location('nigredo_сиг', ROOT / 'interpreter' / 'nigredo.py')
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return {g: [[m.TYPE_NAMES.get(t, 'будь-що') for t in sig] for sig in sigs] for g, sigs in m.TYPE_REQ.items()
            if g not in m.LAZY_GLYPHS and sigs}


def main():
    tmp = pathlib.Path(tempfile.mkdtemp(prefix='ngr-test-'))
    home = tmp / 'власник'
    home.mkdir()
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Redirect)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    (home / 'дозволи.json').write_text(json.dumps({'дозволено': [
        'оракул', 'жереб', 'час', f'файл.читати:{DATA}', f'файл.писати:{DATA / "звіти"}',
        f'мережа.взяти:127.0.0.1:{port}', f'послати:127.0.0.1:{port}'],
        'для_тек': {str(ROOT / 'tests' / 'помилки' / 'тека_з_правами'): [f'файл.читати:{DATA}/../..']}},
        ensure_ascii=False))
    wide = tmp / 'широкі.json'
    wide.write_text(json.dumps({'дозволено': ['файл.читати:/']}, ensure_ascii=False))
    env = dict(os.environ, NIGREDO_HOME=str(home))
    failed = 0
    store_fixtures(home)           # модулі з мережі для tests/помилки/167–190 — у сховищі тимчасового власника

    def check(ok, name, detail=''):
        nonlocal failed
        print(f'✓ {name}' if ok else f'✗ {name}\n{detail}')
        failed += not ok

    for src in sorted((ROOT / 'examples').glob('*.ngr')):
        expected = src.with_suffix('.out')
        got = run([str(src)], env)
        check(expected.exists() and got.returncode == 0 and got.stdout == expected.read_text(encoding='utf-8'),
              src.name, f'код {got.returncode}\n{got.stderr}')

    for src in sorted((ROOT / 'tests' / 'помилки').rglob('[!.]*.ngr')):
        text = src.read_text(encoding='utf-8')
        code, _, want = header(text, 'очікується').partition(' ')
        flags = (header(text, 'прапорці') or '').replace('{ШИРОКІ}', str(wide)).replace('{ДАНІ}', str(DATA)).split()
        prog = src
        if '{ПОРТ}' in text:
            prog = src.with_name(f'.{src.stem}.тимч.ngr')
            prog.write_text(text.replace('{ПОРТ}', str(port)), encoding='utf-8')
        mode = header(text, 'слід')
        tfile = tmp / f'{src.stem}.jsonl'
        if mode:
            flags += ['--слід', str(tfile)]
        try:
            got = run([*flags, str(prog)], env)
        finally:
            if prog != src:
                prog.unlink()
        ok = got.returncode == int(code) and want in got.stderr
        if mode == 'без-підробок':
            recs = [json.loads(line) for line in tfile.read_text(encoding='utf-8').split('\n') if line]
            ok = ok and run(['--перевірити-слід', str(tfile)], env).returncode == 0
            ok = ok and not any(r['подія'] in ('перевірка', 'інструмент') for r in recs)
        if mode == 'відмова-на-старті':
            recs = [json.loads(line) for line in tfile.read_text(encoding='utf-8').split('\n') if line]
            ok = ok and len(recs) == 2 and recs[-1]['подія'] == 'відмова'
            ok = ok and run(['--перевірити-слід', str(tfile)], env).returncode == 0
        if mode == 'обрізати-після-заборони':
            lines = tfile.read_text(encoding='utf-8').split('\n')[:-1]
            idx = next(i for i, line in enumerate(lines) if '"подія": "заборонено"' in line)
            cut = tmp / f'{src.stem}.обрізаний.jsonl'
            cut.write_text('\n'.join(lines[:idx + 1]) + '\n', encoding='utf-8')
            ok = ok and 'обірвано' in run(['--перевірити-слід', str(cut)], env).stdout
        if header(text, 'печатка-рядків-✓'):
            seal = run(['--печатка', str(src)], env).stdout
            ok = ok and sum(line.lstrip().startswith('✓') for line in seal.splitlines()) == int(header(text, 'печатка-рядків-✓'))
        check(ok, src.name, f'чекали {code} «{want}», маємо {got.returncode}\n{got.stderr}')

    # слід: кожен запуск лишив підписаний і завершений слід у теці власника
    traces = sorted((home / 'сліди').glob('*.jsonl'))
    bad = [t.name for t in traces if not run(['--перевірити-слід', str(t)], env).stdout.startswith('✓')]
    check(traces and not bad, f'усі {len(traces)} слідів підписані й завершені', f'погані: {bad}')
    sample = next(t for t in traces if '"подія": "кінець"' in t.read_text(encoding='utf-8'))
    lines = sample.read_text(encoding='utf-8').splitlines()
    cut = tmp / 'обрізаний.jsonl'
    cut.write_text('\n'.join(lines[:-1]) + '\n', encoding='utf-8')
    verdict = run(['--перевірити-слід', str(cut)], env).stdout
    check('обірвано' in verdict, 'обрізаний слід виявлено', verdict)
    forged = tmp / 'підроблений.jsonl'
    recs = [json.loads(line) for line in lines]
    recs[0]['програма'] = 'інша.ngr'
    prev = '0' * 16
    for r in recs:                      # перерахувати ланцюжок без ключа власника, як зловмисник
        r.pop('хеш')
        r['попередній'] = prev
        body = json.dumps(r, ensure_ascii=False, sort_keys=True)
        r['хеш'] = prev = hashlib.sha256(body.encode()).hexdigest()[:16]
    forged.write_text('\n'.join(json.dumps(r, ensure_ascii=False) for r in recs) + '\n', encoding='utf-8')
    verdict = run(['--перевірити-слід', str(forged)], env).stdout
    check(verdict.startswith('✗'), 'слід, перерахований без ключа, виявлено', verdict)
    dup = tmp / 'дубль.jsonl'                 # повторений ключ: розбір візьме останній, підпис — від першого
    first, rest_ = lines[0], lines[1:]
    dup.write_text(first.replace('{"№": 1,', '{"№": 1, "програма": "підміна.ngr",', 1) + '\n' + '\n'.join(rest_) + '\n',
                   encoding='utf-8')
    verdict = run(['--перевірити-слід', str(dup)], env).stdout
    check(verdict.startswith('✗'), 'слід із повтореним ключем виявлено', verdict)
    head = json.loads(lines[0])
    if head.get('програма') and os.path.exists(head['програма']):
        other = ROOT / 'examples' / 'pryvit.ngr'
        if os.path.realpath(head['програма']) == os.path.realpath(other):
            other = ROOT / 'examples' / 'chysla.ngr'
        own = run(['--перевірити-слід', str(sample), head['програма']], env).stdout
        alien = run(['--перевірити-слід', str(sample), str(other)], env).stdout
        check(own.startswith('✓') and 'ІНШОЇ' in alien, 'слід привʼязано до програми', own + alien)
    check('час' in head and 'запуск' in head, 'у сліді є час і ідентифікатор запуску', str(head)[:200])
    refused = ROOT / 'tests' / 'помилки' / '10_vidmova_vlasnyka.ngr'
    got = run(['--печатка', str(refused)], env)
    js = run(['--печатка', '--json', str(refused)], env)
    try:
        info = json.loads(js.stdout)
    except ValueError:
        info = {}
    check(got.returncode == 3 and '✗' in got.stdout and info.get('в_межах') is False and info.get('бракує')
          and info.get('sha256') == hashlib.sha256(refused.read_bytes()).hexdigest() and info.get('програма'),
          '--печатка: код 3 і «✗» поза межами; --json машиночитаний', got.stdout + js.stdout)
    junk = tmp / 'сміття.jsonl'
    junk.write_bytes(b'\0\0\0 not json\n')
    verdict = run(['--перевірити-слід', str(junk)], env)
    check(verdict.returncode == 1 and 'Traceback' not in verdict.stderr, 'перевірка сміття не падає', verdict.stderr)

    # повторний огляд 0.4.3: хвіст виводу, невидиме у виводі, підсумок перевірки, JSON печатки, труба, argv
    pathf = tmp / 'шлях_сліду'
    penv = dict(env, NIGREDO_TRACE_PATH_FILE=str(pathf))
    got = run(['-e', '🜂 「довгий звіт」 【】\n» ＋ ⁀ μ…1 2000 λi 「рядок звіту 」 「」 「ХВІСТ-ДЛЯ-ОТРИМУВАЧА」'], penv)
    tr = pathf.read_text(encoding='utf-8')
    check(got.returncode == 0 and 'ХВІСТ-ДЛЯ-ОТРИМУВАЧА' in pathlib.Path(tr).read_text(encoding='utf-8'),
          'довгий вивід у сліді повністю (з хвостом)', got.stderr)
    got = run(['-e', '🜂 「теги」 【】\n» δ 「"ок\\udb40\\udc49\\u200b"」'], penv)
    check(got.stdout.strip() == 'ок⟨U+E0049⟩⟨U+200B⟩', 'невидиме у виводі — як ⟨U+…⟩', repr(got.stdout))
    got = run(['-e', '🜂 「спроба поза правами」 【「файл.читати:.」】\n» ☂ 🜔файл.читати 「/etc/hostname」 λe 「ні」',
               '--тека', str(DATA)], penv)
    tr = pathf.read_text(encoding='utf-8')
    verdict = run(['--перевірити-слід', tr], env).stdout
    js = json.loads(run(['--перевірити-слід', tr, '--json'], env).stdout)
    check(verdict.startswith('✓') and '«заборонено»): 1' in verdict and 'перехоплено помилок (☂): 1' in verdict
          and js['цілий'] and len(js['заборонено']) == 1, 'підсумок перевірки сліду каже про «заборонено»', verdict)
    got = run(['--печатка', '--json', '-e', '🜂 「а」 【】\n» ＋ 1'], env)
    try:
        info = json.loads(got.stdout)
    except ValueError:
        info = {}
    check(got.returncode == 2 and info.get('в_межах') is False and info.get('помилка_розбору'),
          '--печатка --json при помилці розбору — теж JSON', got.stdout + got.stderr)
    got = run(['--перевірити', '--json', '-e', '🜂 「т」 【】\n← n 5\n» ＋ 「всього: 」 n\n» ⌕ 「a」 「(?<=x)a」'], env)
    try:
        info = json.loads(got.stdout)
    except ValueError:
        info = {}
    check(got.returncode == 2 and info.get('гаразд') is False and len(info.get('помилки', [])) == 2
          and info['помилки'][0]['рядок'] == 3, '--перевірити --json: усі помилки до запуску з місцем', got.stdout + got.stderr)
    # суд 9г (Новачок): межа 50 рахувала проходи, а не помилки — наслідки пропуску («невідоме імʼя») теж їли прохід, і з 40
    # двійників --перевірити називав 29
    many_ = '🜂\n' + ''.join(f'← {chr(0x3105 + i)} 1\n» {chr(0x3105 + i)}\n' for i in range(30)) + ''.join(
        f'← {t_} λx x\n» {t_} 1\n' for t_ in 'ҡҳơბƒ')     # двійники гліфів, які UTS #39 радить для імен (суд 9д)
    got = run(['--перевірити', '-e', many_], env)
    check(got.returncode == 2 and got.stdout.count('✗') == 35 and got.stdout.count('на вигляд — гліф') == 5
          and 'є ще' not in got.stdout,
          '--перевірити: 30 помилок письма й 5 функцій-двійників — усі 35, межа — помилок, а не проходів (суд 9г)',
          got.stdout + got.stderr)
    # суд 9д (Скептик, Новачок): на межі 50 --перевірити мовчки зупинявся — тепер «є ще», а в JSON «обрізано»
    many_ = '🜂\n' + '» + 1 2\n' * 60
    got, js_ = run(['--перевірити', '-e', many_], env), run(['--перевірити', '--json', '-e', many_], env)
    try:
        info = json.loads(js_.stdout)
    except ValueError:
        info = {}
    check(got.stdout.count('✗') == 50 and '… показано 50 помилок — є ще' in got.stdout and info.get('обрізано') is True
          and len(info.get('помилки', [])) == 50,
          '--перевірити: понад 50 помилок — показано 50 і «є ще», у JSON «обрізано» (суд 9д)', got.stdout[-300:] + js_.stdout[-300:])
    # суд 9д (Практик): файл у печатці запису — «✓ в межах», а кожен запис туди падав; тепер попередження до запуску
    (tmp / 'ф9д.db').write_text('', encoding='utf-8')
    seal_ = f'🜂 「т」 【「бд.писати:{tmp}/ф9д.db」 「файл.писати:{tmp}」】\n» 1'
    got, js_ = run(['--перевірити', '-e', seal_], env), run(['--печатка', '--json', '-e', seal_], env)
    try:
        info = json.loads(js_.stdout)
    except ValueError:
        info = {}
    check(got.stdout.count('⚠') == 1 and 'файл, а запис дозволяють у теку' in got.stdout
          and len(info.get('попередження', [])) == 1 and 'бд.писати' in info['попередження'][0],
          '--перевірити і --печатка: файл у печатці запису — попередження (суд 9д)', got.stdout + js_.stdout)
    # суд 6: --розбір шаблону ≠ рядка з {…}; підміна модуля після запуску; модуль із теки запису; зайвий аргумент
    r1 = run(['--розбір', '-e', '🜂 「т」 【「оракул」】\n» 〔А: {σ 🜔оракул 「п」}〕'], env).stdout.strip().splitlines()[-1]
    r2 = run(['--розбір', '-e', '🜂 「т」 【「оракул」】\n» 「А: {рядок(інструмент оракул(«п»))}」'], env).stdout.strip().splitlines()[-1]
    check(r1 != r2 and '«А: » + рядок(' in r1, '--розбір: дірку шаблону видно інакше, ніж текст із {…}', r1 + '\n' + r2)
    md = tmp / 'модулі'
    md.mkdir()
    (md / 'м.ngr').write_text('🜂 「модуль」 【】\n← f λx × x 2\n', encoding='utf-8')
    (md / 'п.ngr').write_text('🜂 「програма з модулем」 【】\n⊃ 「м.ngr」 【「f」】\n» f 21\n', encoding='utf-8')
    got = run([str(md / 'п.ngr')], penv)
    tr = pathf.read_text(encoding='utf-8')
    same = run(['--перевірити-слід', tr, str(md / 'п.ngr')], env).stdout
    (md / 'м.ngr').write_text('🜂 「модуль」 【】\n← f λx × x 3\n', encoding='utf-8')
    other = run(['--перевірити-слід', tr, str(md / 'п.ngr')], env).stdout
    check(got.stdout.strip() == '42' and same.startswith('✓') and 'модулі: м.ngr' in same and other.startswith('✗')
          and 'ІНШИЙ' in other, '--перевірити-слід СЛІД ПРОГРАМА ловить підміну модуля', same + other)
    wd = DATA / 'звіти'
    wd.mkdir(exist_ok=True)
    (wd / 'згенерований.ngr').write_text('🜂 「модуль із теки запису」 【】\n← f λx x\n', encoding='utf-8')
    got = run(['--тека', str(DATA), '-e', '🜂 「т」 【】\n⊃ 「звіти/згенерований.ngr」 【「f」】\n» f 1'], env)
    check(got.returncode == 3 and 'теці, куди програмам дозволено писати' in got.stderr,
          'модуль із теки запису — відмова (код, який могла написати програма)', got.stderr)
    got = run(['--печатка', str(ROOT / 'examples' / 'pryvit.ngr'), str(ROOT / 'examples' / 'ahent.ngr')], env)
    check(got.returncode == 2 and 'зайвий аргумент' in got.stderr, 'зайвий позиційний аргумент — помилка', got.stderr)
    got = run(['--розбір', '-e', '🜂 「т」 【】\n» ' + '【' * 6000 + '1' + '】' * 6000], env)
    check(got.returncode in (0, 2) and 'Traceback' not in got.stderr, '--розбір глибокої вкладеності — без трасування',
          got.stderr[-300:])
    short = tmp / 'власник_короткі'
    short.mkdir()
    (short / 'дозволи.json').write_text(json.dumps({'дозволено': [f'читати:{DATA}']}, ensure_ascii=False), encoding='utf-8')
    got = run(['-e', f'🜂 【「файл.читати:{DATA}」】\n» ρ 🜔читати 「{DATA}/продажі.json」'], dict(env, NIGREDO_HOME=str(short)))
    check(got.returncode == 0, 'короткі назви в дозволах власника = повні', got.stderr)
    got = run(['-e', f'🜂 【「послати:127.0.0.1:{port}」】\n» 🜔послати 「http://127.0.0.1:{port}/звіт」 『「сума」 12.50 「секрет」 「ХВІСТ-ТІЛА」』'], penv)
    tr = pathf.read_text(encoding='utf-8')
    check(got.stdout.startswith('got application/json {"сума": 12.5') and 'ХВІСТ-ТІЛА' in pathlib.Path(tr).read_text(encoding='utf-8'),
          'послати: JSON без втрат, тіло повністю в сліді', got.stdout + got.stderr)
    got = run(['-e', f'🜂 【「послати:127.0.0.1:{port}」】\n» 🜔послати 「http://127.0.0.1:1/x」 「a」'], env)
    check(got.returncode == 1 and 'поза дозволеним' in got.stderr, 'послати: інший порт — відмова під час виконання', got.stderr)
    # проєкт модулів з git, §14: відповідь понад 1 000 000 байтів, обірвана чи не UTF-8 — помилка, а не тихе обрізання
    # чи U+FFFD (раніше read(1_000_000) і decode('utf-8', 'replace')); понад --розмір — як файл.читати
    web_ = f'http://127.0.0.1:{port}'
    got = run(['-e', f'🜂 【「взяти:127.0.0.1:{port}」 「послати:127.0.0.1:{port}」】\n'
               f'» ρ 🜔взяти 「{web_}/байти/1000000」\n» ρ 🜔послати 「{web_}/байти/1000000」 「x」\n' + ''.join(
                   f'» ☂ {t_} 「{web_}/{p_}」{" 「x」" if t_ == "🜔послати" else ""} λe e\n' for t_, p_ in (
                       ('🜔взяти', 'байти/1000001'), ('🜔послати', 'байти/1000001'), ('🜔взяти', 'не-utf8'),
                       ('🜔взяти', 'розрізано'), ('🜔взяти', 'обірвано')))], env)
    check(got.returncode == 0 and got.stdout == (
        f'1000000\n1000000\n'
        f'мережа.взяти: відповідь понад 1 000 000 байтів — частину не читаю мовчки: {web_}/байти/1000001\n'
        f'мережа.послати: відповідь понад 1 000 000 байтів — частину не читаю мовчки: {web_}/байти/1000001\n'
        f'мережа.взяти: відповідь не UTF-8: {web_}/не-utf8\nмережа.взяти: відповідь не UTF-8: {web_}/розрізано\n'
        f'мережа.взяти: відповідь обірвано — бракує 50 байтів до Content-Length, неповну не віддаю мовчки: {web_}/обірвано\n'),
          'мережа: рівно 1 000 000 байтів — так; на байт більше (взяти, послати), не UTF-8 (і розрізаний символ), '
          'обірвана — помилка, а не обрізання (проєкт модулів з git, §14)', got.stdout + got.stderr)
    got = run(['--розмір', '300', '-e', f'🜂 【「взяти:127.0.0.1:{port}」】\n» ρ 🜔взяти 「{web_}/байти/300」\n'
               f'» ρ 🜔взяти 「{web_}/байти/301」'], env)
    check(got.returncode == 1 and got.stdout == '300\n'
          and f'мережа.взяти: відповідь понад 300 символів (--розмір) — частину не читаю мовчки: {web_}/байти/301' in got.stderr,
          'мережа: відповідь понад --розмір — помилка, як у файл.читати', got.stdout + got.stderr)
    # строк — на весь запит, а не на кожну операцію сокета: сервер віддає по байту на 0,2 с (заголовки чи тіло, разом
    # 8 с). Щоб не чекати 30 с, NET_TIME = 1 — у підпроцесі з еталоном (Атанор мережу однаково віддає еталону); потоки
    # запиту по строку закінчуються (зʼєднання обірвано), а не висять, доки сервер капає
    t0 = time.monotonic()
    got = subprocess.run([sys.executable, '-c', 'import sys, threading, time; sys.path.insert(0, sys.argv[1]); import nigredo as n\n'
                          'n.NET_TIME = 1\ncode = n.main(sys.argv[2:])\nend = time.monotonic() + 3\n'
                          'while threading.active_count() > 1 and time.monotonic() < end:\n    time.sleep(0.05)\n'
                          'print("код", code, "потоків", threading.active_count())', str(ROOT / 'interpreter'),
                          '-e', f'🜂 【「взяти:127.0.0.1:{port}」 「послати:127.0.0.1:{port}」】\n'
                          f'» ☂ 🜔взяти 「{web_}/капає/заголовки」 λe e\n» ☂ 🜔послати 「{web_}/капає/тіло」 「x」 λe e'],
                         capture_output=True, text=True, env=env)
    took = time.monotonic() - t0
    check(got.stdout == f'мережа.взяти: запит довший за 1 с — зупинено: {web_}/капає/заголовки\n'
          f'мережа.послати: запит довший за 1 с — зупинено (тіло могло вже дійти до сервера): {web_}/капає/тіло\n'
          'код 0 потоків 1\n' and took < 7,
          f'мережа: строк на весь запит — сервер, що капає по байту (заголовки, тіло), зупинено за строком ({took:.1f} с '
          'на два запити зі строком 1 с), потоки запиту не висять (проєкт модулів з git, §14)', got.stdout + got.stderr)
    # ‖: дії разом, слід — у порядку елементів
    ptr2 = tmp / 'паралельно.jsonl'
    t0 = time.monotonic()
    got = run(['--слід', str(ptr2), '-e', f'🜂 【「взяти:127.0.0.1:{port}」】\n'
               f'∀ ‖ …1 4 λn 🜔взяти 〔http://127.0.0.1:{port}/повільно/{{n}}〕 λr » r'], env)
    took = time.monotonic() - t0
    evs = [json.loads(l) for l in ptr2.read_text(encoding='utf-8').splitlines()]
    seq = [(e['подія'], e['аргументи'][0][-2]) for e in evs if e['подія'] in ('виклик', 'інструмент')]
    check(got.stdout == ''.join(f'відповідь {i}\n' for i in range(1, 5)) and took < 1.0
          and seq == [('виклик', str(i)) for i in range(1, 5)] + [('інструмент', str(i)) for i in range(1, 5)],
          f'‖: 4 запити по 0,3 с — разом ({took:.2f} с), слід у порядку елементів', got.stdout + got.stderr + str(seq))
    check(run(['--перевірити-слід', str(ptr2)], env).returncode == 0, '‖: слід проходить --перевірити-слід')
    ptr3 = tmp / 'паралельно2.jsonl'
    got = run(['--слід', str(ptr3), '-e', f'🜂 【「взяти:127.0.0.1:{port}」 「читати:{DATA}」】\n'
               f'» ‖ 【「продажі.json」 「../../поза.txt」 「продажі.json」】 λf 🜔читати f'], env)
    evs = [e['подія'] for e in map(json.loads, ptr3.read_text(encoding='utf-8').splitlines())
           if e['подія'] in ('заборонено', 'інструмент')]
    check(got.returncode == 1 and 'елемент №2 (§ 1)' in got.stderr and evs == ['інструмент', 'заборонено', 'інструмент', 'інструмент'],
          '‖: відмова з потоку — у сліді на своєму місці, решта дій записана, потім помилка', got.stderr + str(evs))
    # --повторити (М7): інструменти повертають записане (СЛІД.дані), у світі нічого не відбувається
    rp = tmp / 'повтор'
    rp.mkdir()
    (rp / 'п.ngr').write_text(f'🜂 【「взяти:127.0.0.1:{port}」 「читати:{DATA}」 「писати:{DATA / "звіти"}」 「оракул」 「жереб」】\n'
                             f'» ρ 🜔читати 「продажі.json」\n'
                             f'∀ ‖ …1 2 λn 🜔взяти 〔http://127.0.0.1:{port}/повільно/{{n}}〕 λr » r\n'
                             f'🜔писати 「{DATA / "звіти" / "повтор.txt"}」 「записано」\n'
                             f'» 【🜔жереб 1000 ± 🜔оракул 「?」】\n'
                             f'» ☂ 🜔читати 「нема.txt」 λe 「перехоплено」\n', encoding='utf-8')
    first = run(['--слід', str(rp / 'с.jsonl'), str(rp / 'п.ngr')], env)
    (DATA / 'звіти' / 'повтор.txt').unlink()
    got = run(['--повторити', str(rp / 'с.jsonl')], env)
    check(first.returncode == 0 and got.returncode == 0 and got.stdout == first.stdout and '✓ повтор збігся' in got.stderr
          and not (DATA / 'звіти' / 'повтор.txt').exists(),
          'повтор: той самий вивід (файл, ‖, жереб, оракул, перехоплена помилка), а запису у світі немає',
          first.stdout + got.stdout + got.stderr)
    data = (rp / 'с.jsonl.дані').read_text(encoding='utf-8')
    (rp / 'с.jsonl.дані').write_text(data.replace('відповідь 2', 'відповідь Ж'), encoding='utf-8')
    got = run(['--повторити', str(rp / 'с.jsonl')], env)
    check(got.returncode == 1 and 'змінено' in got.stderr, 'повтор: змінене сховище значень — відмова', got.stderr)
    (rp / 'с.jsonl.дані').write_text('', encoding='utf-8')
    got = run(['--повторити', str(rp / 'с.jsonl')], env)
    check(got.returncode == 1 and 'немає значень' in got.stderr, 'повтор: без сховища — відмова з номерами викликів',
          got.stderr)
    (rp / 'с.jsonl.дані').write_text(data, encoding='utf-8')
    (rp / 'інша.ngr').write_text('🜂\n» 1\n', encoding='utf-8')
    got = run(['--повторити', str(rp / 'с.jsonl'), str(rp / 'інша.ngr')], env)
    check(got.returncode == 1 and 'ІНШОЇ програми' in got.stderr, 'повтор: інша програма — відмова', got.stderr)
    got = run(['--слід', str(rp / 'е.jsonl'), '-e', '🜂 【「жереб」】\n» 🜔жереб 6\n» ÷ 1 ν「0」'], env)
    got2 = run(['--повторити', str(rp / 'е.jsonl')], env)
    check(got.returncode == 1 and got2.returncode == 0 and got2.stdout == got.stdout and 'завершення «помилка»' in got2.stderr,
          'повтор: -e програма (код у сліді), завершення помилкою — те саме', got2.stdout + got2.stderr)
    # --сухо: читання — так, записи й надсилання — ні (результат з впевненістю 0), наприкінці — перелік
    got = run(['--сухо', '-e', f'🜂 【「читати:{DATA}」 「писати:{DATA / "звіти"}」 「послати:127.0.0.1:{port}」】\n'
               f'← n ρ 🜔читати 「продажі.json」\n🜔писати 「{DATA / "звіти" / "сухо.txt"}」 〔{{n}}〕\n'
               f'» ± 🜔послати 「http://127.0.0.1:{port}/x」 「СЕКРЕТ」\n» n'], env)
    check(got.returncode == 0 and got.stdout.split('\n')[:1] == ['0'] and not (DATA / 'звіти' / 'сухо.txt').exists()
          and '2 дій не виконано' in got.stderr and 'мережа.послати' in got.stderr and 'сухо.txt' in got.stderr,
          '--сухо: запис і надсилання не виконано (впевненість 0), читання — так, у звіті — обидві дії',
          got.stdout + got.stderr)
    # кілька інструментів на одне обмеження: кожен — окремий дозвіл, кожен звіряється з власником
    got = run(['--печатка', '-e', f'🜂 【「читати писати:{DATA}」】\n» 1'], env)
    check(got.returncode == 3 and 'файл.писати:' in got.stdout + got.stderr and 'файл.читати' in got.stdout,
          'печатка «читати писати:тека»: обидва дозволи видно, писати поза власником — код 3', got.stdout + got.stderr)
    # шлях один раз: відносний шлях поза дозволом — відносно єдиної теки з печатки; межа та сама
    got = run(['-e', f'🜂 【「читати:{DATA}」】\n» ρ δ🜔читати 「продажі.json」'], env)
    check(got.returncode == 0 and got.stdout.strip().isdigit(), 'шлях один раз: файл відносно теки з печатки', got.stderr)
    got = run(['-e', f'🜂 【「читати:{DATA / "звіти"}」】\n» 🜔читати 「../продажі.json」'], env)
    check(got.returncode == 1 and 'поза дозволеним' in got.stderr, 'шлях один раз: «..» з теки печатки — відмова', got.stderr)
    got = run(['-e', f'🜂 【「читати:{DATA}」 「читати:{DATA / "звіти"}」】\n» 🜔читати 「продажі.json」'], env)
    check(got.returncode == 1 and 'поза дозволеним' in got.stderr, 'шлях один раз: дві теки — без здогадів', got.stderr)
    got = run(['-e', f'🜂 【「писати:{DATA / "звіти"}」 「читати:{DATA}」】\n🜔писати 「шлях_раз.txt」 「ок」\n'
               f'» 🜔читати 「звіти/шлях_раз.txt」'], env)
    check(got.stdout == 'ок\n', 'шлях один раз: запис у теку з печатки', got.stdout + got.stderr)
    got = run(['-e', f'🜂 【「читати:{DATA}」】\n» 🜁 「в」 【「читати:{DATA}/продажі.json」】 ρ 🜔читати 「продажі.json」'], env)
    check(got.returncode == 0, 'шлях один раз: дозволено один файл — відносно його теки', got.stderr)
    got = run(['-e', f'🜂 【「читати:{DATA}」】\n» 🜁 「в」 【「читати:{DATA}/продажі.json」】 🜔читати 「продажі.csv」'], env)
    check(got.returncode == 1 and 'поза дозволеним' in got.stderr, 'шлях один раз: інший файл поруч — відмова', got.stderr)
    # SQLite і процеси — окремий власник: бд у тимчасовій теці, команди — точним початком
    bh, bd = tmp / 'власник_бд', tmp / 'бд'
    bh.mkdir()
    (bd / 'bin').mkdir(parents=True)
    (bh / 'дозволи.json').write_text(json.dumps({'дозволено': [
        f'бд.читати:{bd}', f'бд.писати:{bd}', 'процес:git --version', 'процес:sh', 'процес:мій'],
        'для_тек': {}}, ensure_ascii=False), encoding='utf-8')
    benv = dict(env, NIGREDO_HOME=str(bh))
    bseal = f'🜂 【「бд.писати:{bd}」 「бд.читати:{bd}」】\n'
    btr = tmp / 'бд.jsonl'
    got = run(['--слід', str(btr), '-e', bseal + f'🜔бд.писати 「{bd}/a.db」 「CREATE TABLE t(імʼя TEXT, сума REAL)」 【】\n'
               f'» 🜔бд.писати 「{bd}/a.db」 「INSERT INTO t VALUES (?, ?), (?, ?)」 【「а」 12.50 「{"я" * 5000}СЕКРЕТНИЙ-ХВІСТ」 3】\n'
               f'» 🜔бд.читати 「{bd}/a.db」 「SELECT імʼя, сума FROM t WHERE сума > ? ORDER BY сума」 【5】'], benv)
    check(got.returncode == 0 and got.stdout == '2\n【『「імʼя」 「а」 「сума」 12.5』】\n'
          and 'СЕКРЕТНИЙ-ХВІСТ' in btr.read_text(encoding='utf-8'),
          'бд: створити, вставити з параметрами, прочитати; запис — у слід повністю', got.stdout + got.stderr)
    for q, what in [(f"VACUUM INTO '{tmp}/поза.db'", 'VACUUM INTO'), (f"ATTACH '{tmp}/поза.db' AS п", 'ATTACH'),
                    ('PRAGMA journal_mode=WAL', 'PRAGMA'), ('BEGIN', 'BEGIN'),
                    ("SELECT load_extension('x')", 'load_extension'), ('SELECT 1; DROP TABLE t', 'дві інструкції')]:
        got = run(['-e', bseal + f'» 🜔бд.писати 「{bd}/a.db」 「{q}」 【】'], benv)
        check(got.returncode == 1 and not (tmp / 'поза.db').exists(), f'бд.писати: {what} — відмова', got.stderr)
    got = run(['-e', bseal + f'» 🜔бд.читати 「{bd}/a.db」 「DELETE FROM t」 【】\n'], benv)
    check(got.returncode == 1 and 'поза дозволеним' in got.stderr, 'бд.читати: DELETE — відмова', got.stderr)
    got = run(['-e', bseal + f'» 🜔бд.читати 「{bd}/a.db」 「SELECT count(*) AS n FROM t」 【】'], benv)
    check(got.stdout == '【『「n」 2』】\n', 'бд.читати: дані після відмов не змінилися', got.stdout + got.stderr)
    got = run(['-e', bseal + f'» 🜔бд.читати 「{bd}/нема.db」 「SELECT 1」 【】'], benv)
    check(got.returncode == 1 and not (bd / 'нема.db').exists(), 'бд.читати: файл не створює', got.stderr)
    got = run(['-e', bseal + f'» 🜔бд.читати 「{tmp}/a.db」 「SELECT 1」 【】'], benv)
    check(got.returncode == 1 and 'поза дозволеним' in got.stderr, 'бд.читати: файл поза текою — відмова', got.stderr)
    got = run(['--кроки', '100000', '-e', bseal + f'» 🜔бд.читати 「{bd}/a.db」 「WITH RECURSIVE r(n) AS (SELECT 1 '
               f'UNION ALL SELECT n+1 FROM r) SELECT count(*) FROM r」 【】'], benv)
    check(got.returncode != 0 and 'кроків' in got.stderr, 'бд: нескінченний запит списує --кроки', got.stderr)
    got = run(['-e', bseal + f'» 🜔бд.читати 「{bd}/a.db」 「SELECT 1 AS x, 2 AS x」 【】'], benv)
    check(got.returncode == 1 and 'однакові назви' in got.stderr, 'бд.читати: однакові стовпці — помилка, а не втрата', got.stderr)
    got = run(['-e', '🜂 【「процес:git --version」】\n» ∋ 🜔процес 【「git」 「--version」】 「git」'], benv)
    check(got.returncode == 0 and got.stdout == '●\n', 'процес: дозволена команда виконується', got.stdout + got.stderr)
    ptr = tmp / 'процес.jsonl'
    got = run(['--слід', str(ptr), '-e', f'🜂 【「процес:sh」】\n» ρ 🜔процес 【「sh」 「-c」 「true」 「{"я" * 5000}ХВІСТ-АРГУМЕНТУ」】'], benv)
    check(got.stdout == '0\n' and 'ХВІСТ-АРГУМЕНТУ' in ptr.read_text(encoding='utf-8'), 'процес: аргументи — у слід повністю',
          got.stdout + got.stderr)
    got = run(['-e', '🜂 【「процес:git --version」】\n» 🜔процес 【「git」 「status」】'], benv)
    check(got.returncode == 1 and 'поза дозволеним' in got.stderr, 'процес: інші аргументи — відмова', got.stderr)
    got = run(['-e', '🜂 【「процес:git」】\n» 1'], benv)
    check(got.returncode == 3, 'процес: печатка ширша за дозвіл власника (git ⊄ git --version) — код 3', got.stderr)
    got = run(['-e', '🜂 【「процес:sh」】\n» ☂ 🜔процес 【「sh」 「-c」 「echo ой >&2; exit 3」】 λп ∋ п 「кодом 3: ой」'], benv)
    check(got.stdout == '●\n', 'процес: не 0 — помилка з кодом і stderr, яку ловить ☂', got.stdout + got.stderr)
    # скінченний вивід (1,1 МБ): тест безпечний, навіть якщо ліміт зламано (нескінченний yes без ліміту вбивав Termux)
    got = run(['-e', '🜂 【「процес:sh」】\n» 🜔процес 【「sh」 「-c」 「head -c 1100000 /dev/zero」】'], benv)
    check(got.returncode == 1 and '1 МБ' in got.stderr, 'процес: вивід понад 1 МБ — зупинено', got.stderr)
    (bd / 'bin' / 'мій').write_text('#!/bin/sh\necho hi\n')
    (bd / 'bin' / 'мій').chmod(0o755)
    penv2 = dict(benv, PATH=f'{bd / "bin"}{os.pathsep}{os.environ.get("PATH", "")}')
    got = run(['-e', bseal.replace('】', ' 「процес:мій」】', 1) + '» 🜔процес 【「мій」】'], penv2)
    check(got.returncode == 3 and 'куди програмам дозволено писати' in got.stderr,
          'процес: команда з теки запису — код 3', got.stderr)
    got = run(['-e', '🜂 【「процес:sh」】\n» 🜁 「в」 【「процес:sh -c」】 🜔процес 【「sh」 「-c」 「echo ок」】'], benv)
    check(got.returncode == 0 and got.stdout == 'ок\n\n', 'процес: субагент із вужчою командою', got.stdout + got.stderr)
    got = run(['-e', '🜂 【「процес:sh -c」】\n» 🜁 「в」 【「процес:sh」】 1'], benv)
    check(got.returncode != 0, 'процес: субагент із ширшою командою — відмова', got.stderr)
    # суд 7 (Мовознавець): правдивість ключа власника, код 4, точність, канал завершення
    got = run(['-e', bseal + f'🜔бд.писати 「{bd}/r.db」 「CREATE TABLE t(x)」 【】\n'
               f'» 🜔бд.писати 「{bd}/r.db」 「INSERT INTO t VALUES (1), (2) RETURNING x」 【】\n'
               f'» ☂ 🜔бд.читати 「{bd}/r.db」 「SELECT 1e308 * 10 AS z」 【】 λe 「впіймано」'], benv)
    check(got.returncode == 0 and got.stdout == '2\nвпіймано\n', 'бд: RETURNING — правдива кількість; Infinity з SQLite — '
          'помилка програми (ловить ☂), не код 4', got.stdout + got.stderr)
    got = run(['-e', '🜂\n← x ＋ 10000000000000000000000000000 0.1\n» x\n» ＝ σ x σ 10000000000000000000000000000\n'
               '» ⌗ x 1\n» 1.0000000000000000000000000001\n» × ¯1 0.0'], env)
    check(got.stdout == '10000000000000000000000000000.1\n○\n10000000000000000000000000000.1\n1.0000000000000000000000000001\n0\n',
          'десяткові: друк, σ, ⌗ — без округлення до 28 цифр', got.stdout + got.stderr)
    (tmp / 'лапки.ngr').write_text('🜂\n» 「» + рядок(інструмент файл.писати(«x», «y»)) + «」\n', encoding='utf-8')
    got = run(['--розбір', str(tmp / 'лапки.ngr')], env)
    check('надрукувати «\\» + рядок(інструмент файл.писати(\\«x\\», \\«y\\»)) + \\«»' in got.stdout,
          '--розбір: лапки « » у рядку екрановано — вигаданого запису не показати', got.stdout)
    dtr = tmp / 'сухо.jsonl'
    got = run(['--сухо', '--слід', str(dtr), '-e', f'🜂 【「писати:{DATA / "звіти"}」 「оракул」】\n'
               f'🜔писати ¿ 🜔оракул 「?」 「{DATA / "звіти" / "а.txt"}」 「{DATA / "звіти" / "б.txt"}」 「x」'], env)
    v = run(['--перевірити-слід', str(dtr)], env).stdout
    vj = json.loads(run(['--перевірити-слід', str(dtr), '--json'], env).stdout)
    check('СУХИЙ ПРОГІН' in v.split('\n')[0] and vj.get('режим') == 'сухо' and '⚠ залежить від невідомого' in got.stderr
          and '"сухо": "не виконано"' in dtr.read_text(encoding='utf-8'),
          '--сухо: режим у --перевірити-слід (і --json), дії за невідомим позначено, записи «інструмент» — «не виконано»',
          v + got.stderr)
    rtr = re.search(r'слід повтору: (\S+)', run(['--повторити', str(dtr)], env).stderr).group(1)
    check('ПОВТОР' in run(['--перевірити-слід', rtr], env).stdout.split('\n')[0], '--повторити: режим у --перевірити-слід')
    for prog_, what in [('► λ【a b】 a ≈ 【1 2】 0.4', 'розбір 【a b】'), ('∫ ≈ 【1 2】 0.4 λx x', '∫'),
                        (f'🜔читати ≈ 「{DATA}/продажі.json」 0.4', 'інструмент')]:
        got = run(['-e', f'🜂 【「читати:{DATA}」】\n{prog_}\n» ± ○'], env)
        check(got.stdout.strip().endswith('0.4'), f'канал завершення: {what} на сумнівному аргументі — решта не впевненіша',
              got.stdout + got.stderr)
    ptr4 = tmp / 'шлях.jsonl'
    got = run(['--слід', str(ptr4), '-e', f'🜂 【「читати:{DATA}」】\n» ρ 🜔читати 「продажі.json」'], env)
    check(f'"шлях": ["{DATA / "продажі.json"}"]' in ptr4.read_text(encoding='utf-8'), 'шлях один раз: справжній шлях — у сліді',
          ptr4.read_text(encoding='utf-8')[-600:])
    ptr5 = tmp / 'шлях2.jsonl'
    got = run(['--слід', str(ptr5), '-e', f'🜂 【「читати:{DATA / "звіти"}」】\n» 🜔читати 「продажі.json」', '--тека', str(DATA)], env)
    check(got.returncode == 1 and 'поза дозволеним' in got.stderr and '"заборонено"' in ptr5.read_text(encoding='utf-8'),
          'шлях один раз: наявний файл поза дозволом — відмова й «заборонено», а не інший файл', got.stderr)
    (DATA / 'звіти' / 'продажі.json').unlink(missing_ok=True)      # чистий стан (не від попереднього прогону)
    got = run(['-e', f'🜂 【「писати:{DATA / "звіти"}」】\n🜔писати 「продажі.json」 「x」', '--тека', str(DATA)], env)
    check(got.returncode == 1 and not (DATA / 'звіти' / 'продажі.json').exists(),
          'шлях один раз: запис у наявний файл поза дозволом — відмова, а не тихо в теку з печатки', got.stderr)
    got = run(['-e', f'🜂 【「писати:{DATA / "звіти"}」】\n🜔писати 「звіти/../продажі.json」 「x」', '--тека', str(DATA)], env)
    check(got.returncode == 1, 'шлях один раз: «теку/../файл» — не переносити в теку з печатки', got.stderr)
    got = run(['-e', '🜂\n» ▦ δ 「"\\\\ufeffa,b\\\\n1,2"」'], env)
    check(got.stdout == '【『「a」 「1」 「b」 「2」』】\n', '▦: BOM на початку знято (не частина ключа)', got.stdout)
    got = run(['-e', '🜂\n» ∑ 【1】 λx x'], env)
    check(got.returncode == 2 and '∫' in got.stderr, 'схожий гліф ∑ — підказка ∫ / Σ', got.stderr)
    # суд 7 (Скептик)
    ntr = tmp / 'мережа_заборонено.jsonl'
    got = run(['--слід', str(ntr), '-e', f'🜂 【「взяти:127.0.0.1:{port}」】\n» ☂ 🜔взяти 「http://example.com/витік?секрет=1」 λe 「ні」'], env)
    v = run(['--перевірити-слід', str(ntr)], env).stdout
    check('спроб поза правами («заборонено»): 1' in v and 'example.com' in v,
          'мережа поза печаткою — «заборонено» у сліді й підсумку (спроба витоку не проходить як чистий запуск)', v)
    got = run(['--сухо', '-e', f'🜂 【「взяти:127.0.0.1:{port}」 「оракул」】\n← т 🜔взяти 〔http://127.0.0.1:{port}/сайт/x〕\n'
               f'» ± т\n¿ ＝ т 「‹сухо›」 » 「сухо!」 » 「справжній」'], env)
    check(got.stdout.startswith('0\n') and 'мережа.взяти' in got.stderr and 'рішення програми залежали від невідомих' in got.stderr,
          '--сухо: взяти теж не виконується (адреса виносить дані); попередження, що рішення залежали від невідомого',
          got.stdout + got.stderr)
    md = tmp / 'повтор_модуль'
    md.mkdir()
    (md / 'м.ngr').write_text('🜂\n← f λx ＋ x 1\n', encoding='utf-8')
    (md / 'п.ngr').write_text('🜂\n⊃ 「м.ngr」 【「f」】\n» f 1\n', encoding='utf-8')
    run(['--слід', str(md / 'с.jsonl'), str(md / 'п.ngr')], env)
    (md / 'м.ngr').write_text('🜂\n← f λx ＋ x 100\n', encoding='utf-8')
    got = run(['--повторити', str(md / 'с.jsonl')], env)
    check(got.returncode == 1 and 'ІНШИЙ' in got.stderr, '--повторити: модуль змінено — відмова (звіряє sha256 модулів)', got.stderr)
    for csv_, what in [('「a,a\n1,2」', 'однакові заголовки'), ('「a,b\n1,2,3」', 'полів'), ('「a,b\n1」', 'полів'),
                       ('「a\n\"незакрита」', 'не CSV')]:
        got = run(['-e', f'🜂\n» ☂ ▦ {csv_} λe e'], env)
        check(got.returncode == 0 and what in got.stdout, f'▦: {what} — помилка, а не тиха втрата', got.stdout + got.stderr)
    got = run(['-e', '🜂\n» ρ §§▦ ＋ 「a\n」 ⁀ μ …1 200000 λi 「x」 「」 0 「a」'], env)
    check(got.stdout == '200000\n', '▦: дуже довге поле — не код 4', got.stdout + got.stderr[-300:])
    got = run(['-e', '🜂\n» ☂ ◷ 「2026-W42-1」 1 λe 「ні」\n» ☂ ◷ 「20261015」 1 λe 「ні」\n» ◷ 「2026-10-15T09:30Z」 1'], env)
    check(got.stdout == 'ні\nні\n2026-10-16T09:30:00+00:00\n', '◷: лише обіцяний ISO-формат', got.stdout + got.stderr)
    got = run(['-e', '🜂\n» ⌊ ÷ 1000000000000000000000000000000 7'], env)
    check(got.stdout == '142857142857142857142857142857\n', '⌊ ÷ великих цілих — правильне ціле', got.stdout + got.stderr)
    rtr2 = tmp / 'піднято.jsonl'
    run(['--слід', str(rtr2), '-e', '🜂 【「оракул」】\n» ≈ 🜔оракул 「?」 1'], env)
    check('ПІДНЯЛА впевненість' in run(['--перевірити-слід', str(rtr2)], env).stdout, '≈, що підняв впевненість, — у підсумку сліду')
    got = run(['-e', '🜂\n» δ 「"\\u200b"」\n» 「⟨U+200B⟩」'], env)
    a1, a2 = got.stdout.split('\n')[:2]
    check(a1 != a2 and a1 == '⟨U+200B⟩', 'невидимий символ і текст «⟨U+200B⟩» — розрізняються у виводі', got.stdout)
    got = run(['-e', bseal + f'» ☂ 🜔бд.писати 「{bd}/велика.db」 「CREATE TABLE b AS SELECT zeroblob(70000000) AS z」 【】 λe 「межа」'], benv)
    check(got.stdout == 'межа\n', 'бд.писати: база не росте понад межу (zeroblob)', got.stdout + got.stderr)
    str_ = tmp / 'бд_заборонено.jsonl'
    run(['--слід', str(str_), '-e', bseal + f'» ☂ 🜔бд.читати 「{bd}/a.db」 「DELETE FROM t」 【】 λe 1\n'
         f"» ☂ 🜔бд.писати 「{bd}/a.db」 「ATTACH '{tmp}/x.db' AS x」 【】 λe 2"], benv)
    check('спроб поза правами («заборонено»): 2' in run(['--перевірити-слід', str(str_)], benv).stdout,
          'SQLite: відмови білого списку (зміна через бд.читати, ATTACH) — «заборонено» в підсумку сліду')
    got = run(['-e', bseal + f'» 🜔бд.читати 「{bd}/a.db」 「SELECT ? AS v, typeof(?) AS t」 【12345678901234567890 ¯9223372036854775809】'], benv)
    check(got.returncode == 0 and '「12345678901234567890」' in got.stdout and '「text」' in got.stdout,
          'бд: ціле поза INTEGER SQLite — параметром-текстом, а не вада (код 4)', got.stdout + got.stderr[-300:])
    got = run(['-e', bseal + f'» ☂ 🜔бд.читати 「{bd}/a.db」 「SELECT 1e999 AS f UNION ALL SELECT 1」 【】 λe e\n'
                             f'» 🜔бд.писати 「{bd}/a.db」 「CREATE TABLE блок(x)」 【】'], benv)
    check(got.returncode == 0 and got.stdout.endswith('\n0\n'),
          'бд: читання, перерване помилкою посеред рядків, не лишає блокування бази', got.stdout + got.stderr[-300:])
    # суд 7 (Новачок)
    got = run(['-e', bseal + f'» ☂ ρ 🜔бд.читати 「{bd}/a.db」 「SELECT group_concat(hex(zeroblob(200000000))) AS z」 【】 λe 「межа」'], benv)
    check(got.stdout == 'межа\n', 'бд.читати: памʼять SQLite обмежено — помилка програми, не код 4', got.stdout + got.stderr[-300:])
    got = run(['--перевірити', '-e', '🜂\n» ‖ 【1】 λx x\n» ‖ 【1】 λx ＋ x 1'], env)
    check(got.stdout.count('‖ список') == 2, '--перевірити: усі помилки ‖, а не лише перша', got.stdout)
    # суд 8б (Новачок): «знайти ВСІ» — і помилки розбору й печатки, не лише першу; наслідки пропуску позначено
    got = json.loads(run(['--перевірити', '--json', '-e', '🜂 【「взяти:a≤0」 「взяти:b≤٣」 「агент:x≤」】\n» 1'], env).stdout)
    check([e['стовпець'] for e in got['помилки']] == [4, 5, 6], '--перевірити: усі вади квот у печатці', str(got))
    got = json.loads(run(['--перевірити', '--json', '-e', '🜂\n← x ＋ 1\n» x\n» ÷ 1\n← y 2\n» ＋ y 「a」'], env).stdout)
    check([e['рядок'] for e in got['помилки']] == [2, 4, 6] and 'після_пропуску' not in got['помилки'][0]
          and all(e.get('після_пропуску') for e in got['помилки'][1:]),
          '--перевірити: помилки розбору на кількох рядках; імʼя з пропущеного рядка — не помилка', str(got))
    got = run(['-e', '🜂\n» ⌕ 「1٣५ 7」 「\\d+」\n» ⌗ × 86400 ◷ 「2026-10-16T10:00:00」 「2026-10-16T10:00:01」 0'], env)
    check(got.stdout == '【「1」 「7」】\n1\n', '⌕: \\d — лише 0–9 (як ν); секунди з ◷ — ⌗ × 86400 … 0',
          got.stdout + got.stderr)
    got = run(['--перевірити', '-e', '🜂\n» ＋ 1 〔{＋ 1}〕'], env)
    check('чекають аргументів: ＋ (2:9) бере 2, є 1' in got.stdout and '» (' not in got.stdout and '(2:3)' not in got.stdout,
          'підказка арності в шаблоні — лише вирази всередині {…}', got.stdout)
    got = run(['-e', '🜂\n» ⌕ 「a[[b]」 ＋ 「[[」 「b]」\n» ≋ 「x--y」 ＋ 「[-」 「-]」 「_」'], env)
    check(got.stdout == '【「[」 「[」 「b」】\nx__y\n' and got.stderr == '', 'регулярка з «[[» чи «--»: попередження Python не потрапляє у вивід',
          got.stdout + got.stderr)
    got = run(['--кроки', '1000000000', '--розмір', '300000000', '-e', '🜂\n← x Σ …1 5000 【】 Λa i 【a】\n'
               '← y Σ …1 5000 【】 Λa i 【a】\n» ☂ ρ ⇅ 【x y】 λz z λe e'], env)
    check(got.returncode == 0 and got.stdout == '⇅: ключі вкладені надто глибоко\n',
          '⇅: ключі, вкладені в тисячі рівнів, — помилка мови, а не вада (код 4)', got.stdout + got.stderr[-300:])
    # межа обходу — 2000 рівнів (WALK_MAX_DEPTH), а не стек CPython: та сама для 【】 і 『』, будь-якого листка й гліфа
    deep_prog = ('🜂\n← x Σ …1 {d} 【1】 Λa i 【a】\n← y Σ …1 {d} 『「k」 「v」』 Λa i 『「k」 a』\n'
                 '» ☂ ρ σ x λe e\n» ☂ ＝ y y λe e\n» ☂ ＝ y Σ …1 {d} 『「k」 「v」』 Λa i 『「k」 a』 λe e\n'
                 '» ☂ ρ Δ y λe e\n» ☂ ρ ⇅ 【x x】 λz z λe e\n» ☂ ρ 〔{{y}}〕 λe e')
    got = run(['-e', deep_prog.format(d=1999)], env)
    check(got.returncode == 0 and got.stdout == '4001\n●\n●\n14003\n2\n12003\n', 'значення на 2000 рівнів — показ, ＝, JSON, ⇅, 〔〕 працюють',
          got.stdout + got.stderr[-300:])
    got = run(['-e', deep_prog.format(d=2000)], env)
    check(got.returncode == 0 and got.stdout == 'σ: значення вкладене надто глибоко\n●\n＝: значення вкладене надто глибоко\n'
          'Δ: значення вкладене надто глибоко\n⇅: ключі вкладені надто глибоко\n〔〕: значення вкладене надто глибоко\n',
          'на 2001 рівні — «вкладене надто глибоко» (той самий список — рівний без обходу)', got.stdout + got.stderr[-300:])
    got = run(['-e', '🜂\n← x Σ …1 5000 【】 Λa i 【a】\n» ☂ № 【1】 λq x λe e\n» ☂ ¿ x 1 2 λe ρ e\n'
               '← u ≈ 【1】 0.5\n» ρ ¿ ＝ ρ u 1 x 【】'], env)
    check(got.returncode == 0 and got.stdout == f'№ (ключ): очікувалося рядок, а не список {"【" * 40}…\n80\n1\n',
          'глибоке значення в повідомленні про помилку — його початок (а не код 4); невпевнене глибоке — без падіння',
          got.stdout + got.stderr[-300:])
    got = run(['--перевірити', '-e', '🜂\n← крок Λa x ＋ a 1\n» Σ 【1 2】 0 крок\n» μ 【1】 λx крок x'], env)
    check('«крок» у місці функції для Σ — це виклик; функцію як значення передають ∘крок' in got.stdout
          and got.stdout.count('∘крок') == 1, 'М2 (задачі3): голе імʼя ←-функції в Σ — підказка ∘імʼя', got.stdout)
    got = run(['--перевірити', '-e', '🜂\n» ✓ 1 『「a」 「число」 「a」 「рядок」』'], env)
    got2 = run(['-e', '🜂\n← k 「a」\n» ☂ 『k 1 「a」 2』 λe e'], env)
    check('ключ «a» двічі' in got.stdout and got2.stdout == 'у словнику 『』 ключ «a» двічі\n',
          '『』: той самий ключ двічі — помилка (до запуску й під час), а не тихо останній', got.stdout + got2.stdout)
    # 0.8 (суд 8б, Практик): типи елементів списку — ⌕ з групами, ✂, літерали, параметр λ у μ φ ∀ Σ …
    bad = ('🜂\n← т 「сума 12.50」\n» ν § ⌕ т 「сума (\\d+\\.\\d+)」 0\n» μ ✂ т 「 」 λw ＋ w 1\n» ⇣ § 【【1】】 0\n'
           '» § 【1 2】 「a」\n» Σ … 1 3 「」 Λa x ⇣ x')
    got = json.loads(run(['--перевірити', '--json', '-e', bad], env).stdout)
    check([e['рядок'] for e in got['помилки']] == [3, 4, 5, 6, 7] and '§ § … 0 0' in got['помилки'][0]['повідомлення']
          and 'список рядків' in got['помилки'][0]['повідомлення'], '--перевірити: типи елементів списку', str(got))
    good = ('🜂\n← т 「сума 12.50」\n» ν § ⌕ т 「\\d+\\.\\d+」 0\n» ν § § ⌕ т 「сума (\\d+\\.\\d+)」 0 0\n'
            '» μ ✂ т 「 」 λw ＋ w 「!」\n» ∫ … 1 3 λx × x x\n» Σ ✂ т 「 」 0 Λa w ＋ a ρ w\n» μ ε 『「a」 1』 λ【k v】 ＋ v 1\n'
            '» ⇣ § ＋ 【「a」】 【1】 0\n» φ 「аб」 λc ＝ c 「а」')
    got = run(['--перевірити', '-e', good], env)
    got2 = run(['-e', good], env)
    check(got.returncode == 0 and got2.returncode == 0, '--перевірити: правильні програми з типами елементів — без хибних тривог',
          got.stdout + got2.stdout + got2.stderr)
    # 0.8 (М2: пастка, на якій помилявся й автор мови): ∧ ∨ — як and/or; τ — тип значення
    got = run(['-e', '🜂\n← xs 【】\n» ∧ › ρ xs 0 ＝ § xs 0 1\n» ∨ ● ＝ 1 ÷ 1 ν 「0」\n» ☂ ∧ ● δ 「5」 λe e\n'
                     '» ∨ ○ ∧ ● ●\n» μ 【1 「a」 ● ∅ 【】 『』 λx x】 λv τ v'], env)
    check(got.stdout == '○\n●\n∧: умова має бути ● або ○, а не число 5\n●\n'
          '【「число」 「рядок」 「●/○」 「∅」 「список」 「словник」 「функція」】\n',
          '∧ ∨ обчислюють правий бік лише коли він вирішує (тип — перевірено); τ — назви типів як у ✓', got.stdout + got.stderr)
    got = run(['-e', '🜂 【「оракул」】\n← п 🜔оракул 「x」\n← r ∧ п ●\n» ± r\n» ± ∧ ○ п\n'
                     '← q ∨ п ＝ 1 ν 「x」\n» 〔{q} {± q}〕\n» ± τ п\n» ± 1'], env)
    check(got.stdout == '0.6\n1\n● 0.6\n0.6\n0.6\n',
          '∧ ∨: сумнівна ліва частина — результат не впевненіший; пропущений правий бік, що міг упасти, — канал завершення; '
          'τ сумнівного — сумнівний', got.stdout + got.stderr)
    got = run(['-e', '🜂 【「оракул」】\n← п 🜔оракул 「x」\n» ∧ ¬ п ＝ ∅ 🜄 「k」 1\n» ± 🜃 「k」'], env)
    got2 = run(['-e', '🜂\n← сп μ 【1】 λx ≈ x 0.5\n» 〔{± сп} {± τ сп} {± ρ сп}〕'], env)
    check(got2.stdout == '0.5 1 1\n', 'τ — впевненість будови (як ρ), а не вмісту', got2.stdout + got2.stderr)
    check(got.stdout == '○\n0.6\n', '∧: памʼять, яку правий бік міг змінити залежно від сумнівного, — сумнівна',
          got.stdout + got.stderr)
    short = run(['--памʼятка-коротка'], env).stdout
    check('бд.читати:тека' in short and 'процес:git status' in short and '‖ список' in short and 'Шлях' in short,
          'коротка памʼятка (MCP): дозволи бд/процес, правило шляхів, обмеження ‖', short[:500])
    # суд 7 (Аудитор)
    got = run(['-e', bseal + f'🜔бд.писати 「{bd}/v.db」 「CREATE TABLE t(x)」 【】\n🜔бд.писати 「{bd}/v.db」 「CREATE VIEW в AS SELECT x FROM t」 【】\n'
               f'🜔бд.писати 「{bd}/v.db」 「CREATE TRIGGER тр AFTER INSERT ON t BEGIN SELECT 1; END」 【】\n'
               f'🜔бд.писати 「{bd}/v.db」 「DROP VIEW в」 【】\n» 🜔бд.писати 「{bd}/v.db」 「DROP TRIGGER тр」 【】'], benv)
    check(got.returncode == 0, 'бд.писати: DROP VIEW і DROP TRIGGER — дозволено, як обіцяє печатка', got.stderr)
    got = run(['-e', '🜂 【「процес:sh」】\n» 🜔процес 【「sh」 「-c」 「echo $0」】'], benv)
    check(got.stdout == 'sh\n\n', 'процес: argv[0] — як дозволено (busybox/toybox не обрати іншу команду)', got.stdout + got.stderr)
    got = run(['--сухо', '-e', f'🜂 【「писати читати:{DATA / "звіти"}」】\n🜔писати 「{DATA / "звіти" / "с.txt"}」 「x」\n'
               f'» ± 🜔читати 「{DATA / "звіти" / "звіт_є.txt"}」'.replace('звіт_є.txt', 'шлях_раз.txt')], env)
    check(got.stdout == '0\n', '--сухо: читання після придушеного запису — невідоме (світ уже не той)', got.stdout + got.stderr)
    got = run(['-e', '🜂 【「оракул」】\n← д 『「а」 1』\n← в 🜔оракул 「?」\n◷ ¿ ¬в 「2026-10-01」 「не дата」 0\n» ± σ д\n» ± ρ д'], env)
    vals = got.stdout.split()
    check(len(vals) == 2 and all(float(v) < 1 for v in vals), 'канал завершення: σ, ρ давніх значень після сумнівного '
          '«могло впасти» — не впевненіші (суд 7)', got.stdout + got.stderr)
    # суд 7 (Оркестратор)
    got = run(['-e', bseal + f'» ☂ 🜔бд.читати 「{bd}/a.db」 「SELECT length(randomblob(200000000)) AS n」 【】 λe 「межа」\n'
               f'🜔бд.писати 「{bd}/тр.db」 「CREATE TABLE ж(x)」 【】\n🜔бд.писати 「{bd}/тр.db」 「CREATE TABLE в(x)」 【】\n'
               f'🜔бд.писати 「{bd}/тр.db」 「INSERT INTO в VALUES (1), (2), (3)」 【】\n'
               f'🜔бд.писати 「{bd}/тр.db」 「CREATE TRIGGER т AFTER INSERT ON ж BEGIN DELETE FROM в; END」 【】\n'
               f'» 🜔бд.писати 「{bd}/тр.db」 「INSERT INTO ж VALUES (1)」 【】'], benv)
    check(got.stdout == 'межа\n4\n', 'SQLite: значення понад --розмір — помилка; зміни тригерів — у кількості змінених рядків',
          got.stdout + got.stderr)
    # суд 7, раунд 2
    got = run(['-e', bseal + f'🜔бд.писати 「{bd}/і.db」 「CREATE TABLE t(x)」 【】\n🜔бд.писати 「{bd}/і.db」 「CREATE INDEX ix ON t(x)」 【】\n'
               f'🜔бд.писати 「{bd}/і.db」 「CREATE TRIGGER тр AFTER INSERT ON t BEGIN SELECT 1; END」 【】\n'
               f'🜔бд.писати 「{bd}/і.db」 「DROP INDEX ix」 【】\n» 🜔бд.писати 「{bd}/і.db」 「DROP TABLE t」 【】'], benv)
    check(got.returncode == 0, 'бд.писати: кожна дія з опису (CREATE/DROP INDEX, DROP TABLE з тригером) — дозволена', got.stderr)
    multi = tmp / 'мульти'
    multi.mkdir()
    (multi / 'multi').write_text('#!/bin/sh\necho "вибрано: $(basename "$0")"\n')
    (multi / 'multi').chmod(0o755)
    os.symlink(multi / 'multi', multi / 'ехо2')
    mh = tmp / 'власник_мульти'
    mh.mkdir()
    (mh / 'дозволи.json').write_text(json.dumps({'дозволено': ['процес:ехо2']}, ensure_ascii=False), encoding='utf-8')
    got = run(['-e', '🜂 【「процес:ехо2」】\n» 🜔процес 【「ехо2」】'],
              dict(env, NIGREDO_HOME=str(mh), PATH=f'{multi}{os.pathsep}{os.environ.get("PATH", "")}'))
    check(got.stdout == 'вибрано: ехо2\n\n', 'процес: багатокомандний файл (як busybox) бачить дозволене імʼя, а не ціль симлінка',
          got.stdout + got.stderr)
    got = run(['-e', '🜂\n» ☂ ▦ 「клієнт,сума\nПетро,1,50」 λe 「помилка」'], env)
    check(got.stdout == 'помилка\n', '▦: десяткова кома (зайве поле) — помилка, а не тихо загублені копійки', got.stdout)
    got = run(['--розбір', '-e', f'🜂 【「читати:{DATA}」】\n» 🜔читати 「x.json」'], env)
    check('від єдиної теки з печатки' in got.stdout, '--розбір: правило «шлях один раз» названо', got.stdout)
    sample = {'число': '3', 'рядок': '「аб」', 'список': '【1 2】', 'словник': '『「а」 1』', '●/○': '●', 'функція': 'λx x',
              'будь-що': '1'}
    halt = '🜂 【「оракул」】\n← в 🜔оракул 「?」\n◷ ¿ ¬в 「2026-10-01」 「не дата」 0\n'
    leaks = []
    for g_, sigs in type_sigs().items():
        if g_ in '≈±⌂':
            continue
        args_ = ' '.join(sample.get(t, '1') for t in sigs[0])
        r = run(['-e', halt + f'» ± {g_} {args_}'], env)
        if r.returncode == 0 and r.stdout.strip() and float(r.stdout.split()[-1]) >= 1:
            leaks.append(f'{g_} {args_}')
    check(not leaks, 'канал завершення: КОЖЕН гліф після сумнівного «могло впасти» — не впевненіший', ', '.join(leaks))
    # XML (χ ↘)
    xml_ = ('<s:Виписка xmlns:s="urn:bank"><s:Рух тип="прихід"><s:Сума>100.25</s:Сума></s:Рух>'
            '<s:Рух тип="видаток"><s:Сума>40</s:Сума></s:Рух><s:Рух тип="прихід"><s:Сума>0.75</s:Сума></s:Рух></s:Виписка>')
    got = run(['-e', f'🜂\n← в χ 「{xml_}」\n» ∫ ↘ в 「Рух[@тип=\'прихід\']/Сума」 λe ν§e 「текст」\n» §в 「простір」\n'
               f'» ＝ χ χ в в\n» ρ ↘ в 「//Сума」'], env)
    check(got.stdout == '101\nurn:bank\n●\n3\n', 'XML: простори імен (s:Рух — у шляху локальна назва Рух), відбір, сума, χ χ — без втрат',
          got.stdout + got.stderr)
    deep = '<a>' * 700 + '</a>' * 700
    got = run(['-e', f'🜂\n» ☂ χ 「{deep}」 λe 「глибоко」'], env)
    check(got.stdout == 'глибоко\n', 'XML: надто глибока вкладеність — помилка програми, не код 4', got.stdout + got.stderr[-200:])
    got = run(['-e', '🜂\n» ☂ χ 『「тег」 「a b」』 λe 「погано」\n» ☂ χ 『「атрибути」 『』』 λe 「без тегу」\n'
               '» χ 『「тег」 「x」 「атрибути」 『「a」 「\\"&<」』』'], env)
    check(got.stdout.startswith('без тегу\n') or 'без тегу' in got.stdout, 'XML: запис — без тегу помилка; атрибути екрановано',
          got.stdout + got.stderr)
    check('&quot;&amp;&lt;' in got.stdout, 'XML: значення атрибута екрановано при записі', got.stdout)
    # суд 8: χ-запис — лише XML Name, без керівних; ↘ — множина в порядку документа, [n] як у XPath, //b бачить корінь,
    # поза підмножиною — помилка, робота — кроки; DTD забороняє розбирач (у коментарі/CDATA — можна)
    prog = ('🜂\n← д χ 「<S a="1"><G><G><N C="UAH"><A>100</A></N></G></G></S>」\n'
            '» 〔{ρ ↘ д 「//G//A」} {ρ ↘ д 「//*//A」} {ρ ↘ д 「//S」} {Δ ↘ д 「//@C」} {Δ ↘ д 「//@a」}〕\n'
            '← рр χ 「<r><a><b>1</b></a><a><b>2</b></a><!-- <!DOCTYPE x> --><![CDATA[<!DOCTYPE y>]]></r>」\n'
            '» 〔{ρ ↘ рр 「//b[1]」} {§§ ↘ рр 「a[2]/b」 0 「текст」}〕\n'
            '∀ 【「//N[C!=\'x\']」 「//A/text()」 「//A/..」 「//N[」 「a|b」】 λшлях » ☂ ↘ д шлях λe 「поза」\n'
            '» ☂ χ 「<a xmlns:p="u1" xmlns:q="u2" p:x="1" q:x="2"/>」 λe 「простори」\n'
            '∀ 【『「тег」 「A>1</A><B」』 『「тег」 「a」 「атрибути」 『「b=\'1\' c」 「x」』』 『「тег」 「a」 「текст」 δ 「"\\u0001"」』】'
            ' λx » ☂ χ x λe 「запис»」\n'
            '» ☂ ↘ 『「тег」 「a」 「діти」 【1】』 「b」 λe 「не елемент」\n'
            '» Δ μ ↘ χ 「<r><a><c/></a><b/></r>」 「//*」 λe §e 「тег」\n← b 『「тег」 「b」 「текст」 「5」』\n'
            '← rr 『「тег」 「r」 「діти」 【b b 『「тег」 「a」 「діти」 【b】』】』\n» 〔{∫ ↘ rr 「//b」 λe ν §e 「текст」} {ρ ↘ rr 「b[2]」}〕')
    got = run(['-e', prog], env)
    check(got.stdout == '1 1 1 ["UAH"] ["1"]\n2 2\n' + 'поза\n' * 5 + 'простори\n' + 'запис»\n' * 3 + 'не елемент\n'
          + '["r", "a", "c", "b"]\n15 1\n',
          'XML (суд 8): ↘ без повторів, [n] як у XPath, //корінь, //@атр; поза підмножиною — помилка; простори атрибутів; '
          'запис — лише XML Name, без керівних; ручний вузол — не код 4; DTD у коментарі — можна', got.stdout + got.stderr)
    chain = '<a>' * 60 + '</a>' * 60
    got = run(['--кроки', '150', '-e', f'🜂\n» ρ ↘ χ 「<r>{chain}</r>」 「//a//a//a//a//a//b」'], env)
    check(got.returncode == 1 and 'кроків' in got.stderr, '↘: робота — кроки (--кроки зупиняє, не висне)', got.stdout + got.stderr)
    got = run(['-e', f'🜂\n» ρ ↘ χ 「<r>{chain}</r>」 「//a//a」'], env)
    check(got.stdout == '59\n', '↘: //a//a на ланцюжку з 60 — 59 вузлів (без повторів, лінійно)', got.stdout + got.stderr)
    # квоти «≤N»: печатка, субагент, власник; у ‖ — так само
    got = run(['-e', '🜂 【「жереб≤3」】\n» ☂ μ …1 5 λi 🜔жереб 6 λe 「квота」'], env)
    check(got.stdout == 'квота\n', 'квота печатки: четвертий виклик — відмова (ловить ☂)', got.stdout + got.stderr)
    got = run(['-e', '🜂 【「жереб」】\n» ☂ 🜁 「в」 【「жереб≤1」】 μ …1 2 λi 🜔жереб 6 λe 「квота субагента」\n» 🜔жереб 6'], env)
    check(got.stdout.startswith('квота субагента\n') and got.returncode == 0,
          'квота субагента: діє лише в ньому, головний агент далі може', got.stdout + got.stderr)
    qh = tmp / 'власник_квота'
    qh.mkdir()
    (qh / 'дозволи.json').write_text(json.dumps({'дозволено': [f'взяти:127.0.0.1:{port}≤2']}, ensure_ascii=False),
                                     encoding='utf-8')
    qtr = tmp / 'квота.jsonl'
    got = run(['--слід', str(qtr), '-e', f'🜂 【「взяти:127.0.0.1:{port}」】\n'
               f'» ☂ ‖ …1 3 λn 🜔взяти 〔http://127.0.0.1:{port}/повільно/{{n}}〕 λe 「власник: не більше 2」'],
              dict(env, NIGREDO_HOME=str(qh)))
    check(got.stdout == 'власник: не більше 2\n' and 'квота' in qtr.read_text(encoding='utf-8')
          and qtr.read_text(encoding='utf-8').count('"подія": "скасовано"') == 2,
          'квота власника на хост: і в ‖ третій запит — відмова й «заборонено» (до дії)', got.stdout + got.stderr)
    # суд 8: квоти модуля й субагента (на кожен запуск), повернення за невиконані, «квоту вичерпано» ≠ «заборонено»,
    # звуження не скидає квот власника, дві квоти й не-ASCII цифри — помилка до запуску
    qd = tmp / 'квоти8'
    (qd / 'дані').mkdir(parents=True)
    (qd / 'дані' / 'x.txt').write_text('так', encoding='utf-8')
    (qd / 'мод.ngr').write_text('🜂 【「жереб≤1」】\n← кинь λn 🜔жереб n\n', encoding='utf-8')
    (qd / 'інше').mkdir()
    (qd / 'а.ngr').write_text('🜂 【「жереб」 「читати:дані≤1」 「читати:інше」】\n⊃ 「мод.ngr」 【「кинь」】\n'
                              '∀ 【1 2】 λx » ☂ σ кинь 6 λe 「модуль: квота」\n'
                              '← питати λq 🜁 「провидець」 【「жереб≤1」】 🜔жереб 6\n» σ питати 1\n» σ питати 2\n'
                              '» ☂ 🜔читати 「x.txt」 λe 「поза текою」\n» 🜔читати 「дані/x.txt」\n', encoding='utf-8')
    q8 = tmp / 'квоти8.jsonl'
    (tmp / 'вл8').mkdir()
    (tmp / 'вл8' / 'дозволи.json').write_text(json.dumps({'дозволено': ['жереб', f'файл.читати:{qd}'],
                                                       'для_тек': {}}, ensure_ascii=False), encoding='utf-8')
    env8 = dict(env, NIGREDO_HOME=str(tmp / 'вл8'))
    got = run(['--слід', str(q8), str(qd / 'а.ngr')], env8)
    o8 = got.stdout.split('\n')
    check(len(o8) == 7 and o8[1] == 'модуль: квота' and o8[2].isdigit() and o8[3].isdigit() and o8[4:] == ['поза текою', 'так', ''],
          'квоти (суд 8): модуля — діє; субагента — на кожен запуск; відмова за правами квоти не списує',
          got.stdout + got.stderr)
    v8 = run(['--перевірити-слід', str(q8)], env8).stdout
    check('квоту вичерпано' in v8 and 'жереб≤1 (модуль мод.ngr)' in v8 and v8.count('заборонено') == 1,
          '--перевірити-слід: «квоту вичерпано» — окремо від «заборонено»', v8)
    got = run(['-e', f'🜂 【「взяти:127.0.0.1:{port}≤2」】\n← у 「http://127.0.0.1:{port}/повільно/」\n'
               f'» ☂ ‖ 【1 2 3】 λx 🜔взяти ＋ у σ x λe 「‖: квота»」\n» ρ μ 【1 2】 λx 🜔взяти ＋ у σ x'], env)
    check(got.stdout == '‖: квота»\n2\n', 'квота: скасовані в ‖ виклики квоти не списують', got.stdout + got.stderr)
    for bad_q, why in (('【「жереб≤1」 「жереб≤3」】', 'дві квоти'), ('【「жереб≤٢」】', 'цифри 0–9'), ('【「жереб≤0」】', '≤0')):
        got = run(['-e', f'🜂 {bad_q}\n» 1'], env)
        check(got.returncode == 2 and why in got.stderr, f'квота: {why} — помилка до запуску', got.stderr)
    (qh / 'вужче.json').write_text(json.dumps({'дозволено': [f'взяти:127.0.0.1:{port}']}), encoding='utf-8')
    got = run(['--дозволи', str(qh / 'вужче.json'), '-e', f'🜂 【「взяти:127.0.0.1:{port}」】\n'
               f'∀ …1 3 λn » ☂ ρ 🜔взяти 〔http://127.0.0.1:{port}/повільно/{{n}}〕 λe 「власник ≤2」'],
              dict(env, NIGREDO_HOME=str(qh)))
    check(got.stdout.endswith('власник ≤2\n') and got.stdout.count('власник') == 1,
          '--дозволи: звуження лишає квоту власника', got.stdout + got.stderr)
    (qh / 'квота1.json').write_text(json.dumps({'дозволено': [f'взяти:127.0.0.1:{port}≤1']}), encoding='utf-8')
    got = run(['--дозволи', str(qh / 'квота1.json'), '-e', f'🜂 【「взяти:127.0.0.1:{port}」】\n'
               f'∀ …1 3 λn » ☂ ρ 🜔взяти 〔http://127.0.0.1:{port}/повільно/{{n}}〕 λe 「≤1」'], dict(env, NIGREDO_HOME=str(qh)))
    check(got.returncode == 0 and got.stdout.count('≤1') == 2, '--дозволи з ≤N: звуження квотою', got.stdout + got.stderr)
    rz = run(['--розбір', str(qd / 'а.ngr')], env8).stdout
    sl = run(['--печатка', '--json', str(qd / 'а.ngr')], env8).stdout
    check(rz.count('КВОТА') == 3 and sl.count('"не_більше": 1') == 3,
          '--розбір і --печатка --json: квоти печатки, модуля й субагента', rz + sl)
    js = json.loads(run(['--печатка', '--json', '-e', '🜂 【「оракул≤5」】\n» 1'], env).stdout)
    check(js.get('квоти') == [{'інструмент': 'оракул', 'обмеження': '', 'не_більше': 5}], '--печатка --json: квоти', str(js))
    # суд 8б: вичерпана квота не ховає спроб поза правами (спершу права — «заборонено», «квоту вичерпано» — лише
    # дозволеному); --повторити повертає квоту за відмову, як справжній запуск
    (qd / 'дані' / 'під').mkdir()
    (qd / 'маска.ngr').write_text('🜂 【「читати:дані≤2」】\n» ☂ 🜔читати 「дані/../а.ngr」 λe 「поза»」\n'
                                  '» 🜔читати 「дані/x.txt」\n» 🜔читати 「дані/x.txt」\n'
                                  '» ☂ 🜔читати 「дані/../а.ngr」 λe 「поза після»」\n» ☂ 🜔читати 「дані/x.txt」 λe 「квота»」\n'
                                  '» ☂ 🜁 「вузький」 【「читати:дані/під」】 🜔читати 「дані/x.txt」 λe 「субагент поза»」\n',
                                  encoding='utf-8')
    qm = tmp / 'маска.jsonl'
    got = run(['--слід', str(qm), str(qd / 'маска.ngr')], env8)
    vm = json.loads(run(['--перевірити-слід', str(qm), str(qd / 'маска.ngr'), '--json'], env8).stdout)
    check(got.stdout == 'поза»\nтак\nтак\nпоза після»\nквота»\nсубагент поза»\n' and len(vm['заборонено']) == 3
          and len(vm['квоту_вичерпано']) == 1,
          'квота (суд 8б): після вичерпання спроба поза правами — «заборонено», а не «квоту вичерпано»', got.stdout + str(vm))
    got = run(['--повторити', str(qm), str(qd / 'маска.ngr')], env8)
    check(got.returncode == 0 and '✓ повтор збігся' in got.stderr, '--повторити: відмова за правами квоту не списує — '
          'повтор збігається', got.stderr)
    # SQLite: «заборонено» — лише від authorizer; RAISE(FAIL, 'not authorized') у тригері — звичайна помилка, квоту списує
    (qd / 'звіти').mkdir()
    (tmp / 'вл8б').mkdir()
    (tmp / 'вл8б' / 'дозволи.json').write_text(json.dumps({'дозволено': ['жереб', f'файл.читати:{qd}',
                                                        f'бд.писати:{qd}/звіти', f'бд.читати:{qd}/звіти',
                                                        f'файл.писати:{qd}/звіти']}, ensure_ascii=False), encoding='utf-8')
    env8b = dict(env, NIGREDO_HOME=str(tmp / 'вл8б'))
    sq = '🜔бд.писати 「звіти/т.db」'
    (qd / 'тригер.ngr').write_text(
        f'🜂 【「бд.писати:звіти≤4」 「бд.читати:звіти」】\n» {sq} 「CREATE TABLE x (a)」 【】\n'
        f'» {sq} 「CREATE TRIGGER t AFTER INSERT ON x BEGIN SELECT RAISE(FAIL, \'not authorized\'); END」 【】\n'
        f'∀ …1 3 λi » ☂ {sq} 「INSERT INTO x VALUES (1)」 【】 λe e\n'
        f'» § § 🜔бд.читати 「звіти/т.db」 「SELECT count(*) AS n FROM x」 【】 0 「n」\n'
        f'» ☂ {sq} 「VACUUM INTO \'/tmp/x.db\'」 【】 λe e\n» ☂ {sq} 「SELECT load_extension(\'x\')」 【】 λe e\n',
        encoding='utf-8')
    qs = tmp / 'тригер.jsonl'
    got = run(['--слід', str(qs), str(qd / 'тригер.ngr')], env8b)
    vs = json.loads(run(['--перевірити-слід', str(qs), str(qd / 'тригер.ngr'), '--json'], env8b).stdout)
    o = got.stdout.split('\n')
    check(len(o) == 9 and o[:2] == ['0', '0'] and 'not authorized' in o[2] and 'not authorized' in o[3]
          and 'вичерпано квоту' in o[4] and o[5] == '2' and 'VACUUM' in o[6] and 'load_extension' in o[7]
          and len(vs['заборонено']) == 2 and len(vs['квоту_вичерпано']) == 1,
          'бд.писати (суд 8б): RAISE(…\'not authorized\') у тригері — не «заборонено» (рядки записано, квоту списано); '
          'VACUUM і load_extension — «заборонено» й після квоти', got.stdout + got.stderr + str(vs))
    (qd / 'значення.ngr').write_text(f'🜂 【「бд.писати:звіти」】\n» {sq} 「CREATE TABLE IF NOT EXISTS y (a)」 【】\n'
                                    f'» {sq} 「INSERT INTO y VALUES (\'load_extension\')」 【】\n', encoding='utf-8')
    got = run([str(qd / 'значення.ngr')], env8b)
    check(got.returncode == 0 and got.stdout.endswith('1\n'), 'бд.писати: рядок «load_extension» у значенні — не тривога',
          got.stdout + got.stderr)
    # звуження --дозволи не вимикає «код із теки запису — не модуль»: теки запису — з дозволів власника
    (qd / 'звіти' / 'м.ngr').write_text('🜂 【「жереб」】\n← кинь λn 🜔жереб n\n', encoding='utf-8')
    (qd / 'бере.ngr').write_text('🜂 【「жереб」】\n⊃ 「звіти/м.ngr」 【「кинь」】\n» кинь 6\n', encoding='utf-8')
    (tmp / 'вл8б' / 'вужче.json').write_text(json.dumps({'дозволено': ['жереб']}), encoding='utf-8')
    got = run(['--дозволи', str(tmp / 'вл8б' / 'вужче.json'), str(qd / 'бере.ngr')], env8b)
    check(got.returncode == 3 and 'лежить у теці' in got.stderr,
          '--дозволи (суд 8б): модуль із теки запису власника — відмова й при звуженні', got.stdout + got.stderr)
    # суд 8в: теки запису — з УСІХ записів власника. Тека C може писати в A/вхідні; програма, покладена туди, не дістає
    # прав теки A, а модуль звідти — не модуль і для програми з A
    va, vc = tmp / 'в8в' / 'A', tmp / 'в8в' / 'C'
    for d_ in (va / 'вхідні', va / 'дані', vc):
        d_.mkdir(parents=True, exist_ok=True)
    (va / 'дані' / 'секрет.txt').write_text('банк', encoding='utf-8')
    (tmp / 'вл8в').mkdir(exist_ok=True)
    (tmp / 'вл8в' / 'дозволи.json').write_text(json.dumps({'для_тек': {
        str(va): [f'читати:{va}/дані', f'бд.читати:{va}/дані', 'жереб', 'процес:мій8в'], str(vc): [f'писати:{va}/вхідні']}}, ensure_ascii=False),
        encoding='utf-8')
    env8v = dict(env, NIGREDO_HOME=str(tmp / 'вл8в'))
    q_ = f'🜂 【\\u300cчитати:{va}/дані\\u300d】\\\\n» 🜔читати \\u300c{va}/дані/секрет.txt\\u300d\\\\n'
    m_ = '🜂 【\\u300cжереб\\u300d】\\\\n← кинь λn 🜔жереб n\\\\n'
    (vc / 'кладе.ngr').write_text(f'🜂 【「писати:{va}/вхідні」】\n» 🜔писати 「{va}/вхідні/q.ngr」 δ 「"{q_}"」\n'
                                  f'» 🜔писати 「{va}/вхідні/м.ngr」 δ 「"{m_}"」\n', encoding='utf-8')
    got0 = run([str(vc / 'кладе.ngr')], env8v)
    got = run([str(va / 'вхідні' / 'q.ngr')], env8v)
    (va / 'бере.ngr').write_text('🜂 【「жереб」】\n⊃ 「вхідні/м.ngr」 【「кинь」】\n» кинь 6\n', encoding='utf-8')
    got2 = run([str(va / 'бере.ngr')], env8v)
    (va / 'читає.ngr').write_text(f'🜂 【「читати:{va}/дані」】\n» 🜔читати 「дані/секрет.txt」\n', encoding='utf-8')
    got3 = run([str(va / 'читає.ngr')], env8v)
    (va / 'вхідні' / 'мій8в').write_text('#!/bin/sh\necho hi\n')
    (va / 'вхідні' / 'мій8в').chmod(0o755)
    (va / 'кличе.ngr').write_text('🜂 【「процес:мій8в」】\n» 🜔процес 【「мій8в」】\n', encoding='utf-8')
    got4 = run([str(va / 'кличе.ngr')], dict(env8v, PATH=f'{va / "вхідні"}{os.pathsep}{os.environ.get("PATH", "")}'))
    check(got0.returncode == 0 and got.returncode == 3 and 'банк' not in got.stdout
          and got2.returncode == 3 and 'лежить у теці' in got2.stderr and got3.stdout == 'банк\n'
          and got4.returncode == 3 and 'дозволено писати' in got4.stderr,
          'суд 8в: програма в теці запису іншої теки власника — без прав теки A; модуль і команда звідти — відмова; сама A — читає',
          got0.stderr + got.stdout + got.stderr + got2.stderr + got3.stdout + got3.stderr + got4.stderr)
    # «для_програм»: права саме цій програмі (за відбитком тексту й модулів); змінений байт — права немає
    sx = tmp / 'схв'
    for d_ in (sx / 'дані', sx / 'вихід', sx / 'вл'):
        d_.mkdir(parents=True, exist_ok=True)
    (sx / 'дані' / 'a.txt').write_text('привіт', encoding='utf-8')
    (sx / 'вл' / 'дозволи.json').write_text('{"дозволено": ["оракул"]}', encoding='utf-8')
    envx = dict(env, NIGREDO_HOME=str(sx / 'вл'))
    (sx / 'мод.ngr').write_text('🜂 【「читати:дані」】\n← прочитай λf 🜔читати f\n', encoding='utf-8')
    (sx / 'п.ngr').write_text('🜂 「копія」 【「читати:дані」 「писати:вихід」】\n⊃ 「мод.ngr」 【「прочитай」】\n'
                             '» 🜔писати 「вихід/b.txt」 прочитай 「дані/a.txt」\n', encoding='utf-8')
    got0 = run([str(sx / 'п.ngr')], envx)
    appr = run(['--схвалити', str(sx / 'п.ngr')], envx)
    entry = re.search(r'"для_програм": (\{.*\})', appr.stdout)
    (sx / 'вл' / 'дозволи.json').write_text(json.dumps({'дозволено': ['оракул'], 'для_програм': json.loads(entry.group(1))}
                                                       if entry else {}, ensure_ascii=False), encoding='utf-8')
    got1 = run([str(sx / 'п.ngr')], envx)
    seal_ = run(['--печатка', str(sx / 'п.ngr')], envx)
    (sx / 'мод.ngr').write_text('🜂 【「читати:дані」】\n← прочитай λf ＋ 🜔читати f 「!」\n', encoding='utf-8')
    got2 = run([str(sx / 'п.ngr')], envx)
    check(got0.returncode == 3 and appr.returncode == 0 and 'ВІДБИТОК' in appr.stdout and entry is not None
          and got1.returncode == 0 and (sx / 'вихід' / 'b.txt').read_text(encoding='utf-8') == 'привіт'
          and 'схвалено власником' in seal_.stdout and 'для_програм' in seal_.stdout
          and got2.returncode == 3 and 'просить більше' in got2.stderr,
          '«для_програм»: --схвалити друкує запис; схвалена програма — з правами, змінений модуль — відмова',
          got0.stderr + appr.stdout[-400:] + got1.stderr + seal_.stdout[-300:] + got2.stderr)
    # тека запису схваленої програми — теж тека запису: модуль звідти — відмова
    (sx / 'вихід' / 'м2.ngr').write_text('🜂\n← f λx x\n', encoding='utf-8')
    (sx / 'бере2.ngr').write_text('🜂\n⊃ 「вихід/м2.ngr」 【「f」】\n» f 1\n', encoding='utf-8')
    got3 = run([str(sx / 'бере2.ngr')], envx)
    (sx / 'вл' / 'дозволи.json').write_text('{"для_програм": ["x"]}', encoding='utf-8')
    got4 = run([str(sx / 'бере2.ngr')], envx)
    check(got3.returncode == 3 and 'дозволено писати' in got3.stderr and got4.returncode == 3
          and '«для_програм» має бути словником' in got4.stderr,
          '«для_програм»: його теки запису — теки запису для «чужий код не модуль»; не словник — відмова',
          got3.stdout + got3.stderr + got4.stderr)
    # суд 9: розділ «для_програм» уже є — --схвалити друкує злитий (ключ у JSON не повторюють); ⌂ — попередження;
    # повтор ключа в дозволах власника — відмова, а не мовчки «останній перемагає»
    (sx / 'вл' / 'дозволи.json').write_text(json.dumps({'дозволено': ['оракул'], 'для_програм': {'aa' * 32: ['оракул']}}),
                                           encoding='utf-8')
    (sx / 'арг.ngr').write_text('🜂 【「писати:вихід」】\n🜔писати § ⌂ 0 「x」\n', encoding='utf-8')
    appr2 = run(['--схвалити', str(sx / 'арг.ngr')], envx)
    (sx / 'вл' / 'дозволи.json').write_text('{"дозволено": ["оракул"], "дозволено": ["жереб"]}', encoding='utf-8')
    got5 = run(['-e', '🜂\n» 1'], envx)
    check(appr2.returncode == 0 and 'замініть його ЦІЛИМ' in appr2.stdout and 'aa' * 32 in appr2.stdout
          and 'бере аргументи запуску (⌂)' in appr2.stdout and got5.returncode == 3
          and 'ключ «дозволено» повторюється' in got5.stderr,
          '--схвалити: злитий «для_програм», попередження про ⌂; повтор ключа в дозволах — відмова',
          appr2.stdout[-700:] + got5.stderr)
    # суд 9б: відбитки, різні лише регістром, — той самий (мовчки перемагав останній); уже схвалена — «додавати нічого»
    (sx / 'вл' / 'дозволи.json').write_text(json.dumps({'дозволено': ['оракул'], 'для_програм': {
        'AB' * 32: ['оракул'], 'ab' * 32: ['жереб']}}), encoding='utf-8')
    got6 = run(['-e', '🜂\n» 1'], envx)
    (sx / 'вл' / 'дозволи.json').write_text(json.dumps({'дозволено': ['оракул']}), encoding='utf-8')
    a1_ = run(['--схвалити', str(sx / 'арг.ngr')], envx)
    m_ = re.search(r'"для_програм": (\{.*?\]\})', a1_.stdout)
    (sx / 'вл' / 'дозволи.json').write_text(json.dumps({'дозволено': ['оракул'], 'для_програм': json.loads(m_.group(1))},
                                                      ensure_ascii=False), encoding='utf-8')
    a2_ = run(['--схвалити', str(sx / 'арг.ngr')], envx)
    # суд 9в (Практик): власник записав схвалення короткими назвами — те саме право, теж «додавати нічого»
    short_ = {h: [re.sub(r'^(файл|мережа)\.([^:]*):', r'\2: ', p) for p in v] for h, v in json.loads(m_.group(1)).items()}
    (sx / 'вл' / 'дозволи.json').write_text(json.dumps({'дозволено': ['оракул'], 'для_програм': short_},
                                                      ensure_ascii=False), encoding='utf-8')
    a3_ = run(['--схвалити', str(sx / 'арг.ngr')], envx)
    check(got6.returncode == 3 and 'той самий відбиток двічі' in got6.stderr and 'вже схвалена саме цими правами' in a2_.stdout
          and 'замініть' not in a2_.stdout and 'вже схвалена саме цими правами' in a3_.stdout
          and any(': ' in p for v in short_.values() for p in v),
          '«для_програм»: AB… і ab… — помилка; --схвалити схваленої — «додавати нічого» (суд 9б), і з короткими назвами '
          'прав (суд 9в)', got6.stderr + a2_.stdout[-400:] + a3_.stdout[-400:] + str(short_))
    got = run(['-e', f'🜂 【「взяти:127.0.0.1:{port}」】\n» ☂ 🜔взяти 「http://@127.0.0.1:{port}/」 λe e'], env)
    check('поза дозволеним' in got.stdout, 'взяти (суд 8в): порожній логін «http://@хост/» — відмова за правами',
          got.stdout + got.stderr)
    (va / 'дані' / 'б.db').write_bytes(b'')
    got = run(['--тека', str(va), '-e', f'🜂 【「бд.читати:{va}/дані」】\n» ☂ 🜔бд.читати 「{va}/дані/б.db」 「REINDEX」 【】 λe e\n'
               f'» ☂ 🜔бд.читати 「{va}/дані/б.db」 「/**/ DROP TABLE IF EXISTS нема」 【】 λe e\n'
               f'» 🜔бд.читати 「{va}/дані/б.db」 「 WITH a AS (SELECT 1 AS x) SELECT x FROM a」 【】'],
              env8v)
    check(got.stdout.count('лише SELECT') == 2 and got.stdout.endswith('【『「x」 1』】\n'),
          'бд.читати (суд 8в): лише SELECT/WITH/VALUES — REINDEX, DROP IF EXISTS — відмова', got.stdout + got.stderr)
    # суд 8в р2: довідкові PRAGMA, як обіцяє памʼятка, — дозволено; інші — відмова
    sl8 = tmp / 'pragma.jsonl'
    got = run(['--слід', str(sl8), '--тека', str(va), '-e', f'🜂 【「бд.читати:{va}/дані」】\n'
               f'» ρ 🜔бд.читати 「{va}/дані/б.db」 「PRAGMA table_info(x)」 【】\n'
               f'» ☂ 🜔бд.читати 「{va}/дані/б.db」 「PRAGMA journal_mode=delete」 【】 λe e'], env8v)
    check(got.stdout.startswith('0\n') and 'поза дозволеним' in got.stdout
          and sum('"заборонено"' in l for l in sl8.read_text(encoding='utf-8').split('\n')) == 1,
          'бд.читати (суд 8в): PRAGMA table_info — можна (як у памʼятці), journal_mode — «заборонено»', got.stdout + got.stderr)
    got = run(['--тека', str(va), '-e', f'🜂 【「бд.читати:{va}/дані」】\n'
               f'» ρ 🜔бд.читати 「{va}/дані/б.db」 「pragma TABLE_INFO(x)」 【】\n'
               f'» ρ 🜔бд.читати 「{va}/дані/б.db」 「PRAGMA main.table_info(x)」 【】\n'
               f'» ρ 🜔бд.читати 「{va}/дані/б.db」 「PRAGMA/**/Table_Info(x)」 【】'], env8v)
    check(got.returncode == 0 and got.stdout == '0\n0\n0\n',
          'бд.читати (суд 8в р3): довідкові PRAGMA — без огляду на регістр, з main., з коментарем', got.stdout + got.stderr)
    # суд 8в р3: --сухо перевіряє права придушених дій — поза ними «заборонено», а не «дій не виконано»
    sl8 = tmp / 'сухо8в.jsonl'
    got = run(['--сухо', '--слід', str(sl8), '-e', f'🜂 【「взяти:127.0.0.1:{port}」】\n'
               '» ☂ 🜔взяти 「http://example.com/」 λe 「відмова」\n'
               f'» 🜔взяти 「http://127.0.0.1:{port}/ціна/x」'], env)
    vs = json.loads(run(['--перевірити-слід', str(sl8), '--json'], env).stdout)
    check(got.stdout.startswith('відмова\n') and 'example.com' not in got.stderr.split('дій не виконано')[-1]
          and len(vs['заборонено']) == 1,
          '--сухо (суд 8в р3): дія поза правами — «заборонено», не в переліку придушених', got.stdout + got.stderr + str(vs))
    # суд 8в р2: «＠», «／» (NFKC), «[::1» в адресі — «заборонено» й помилка програми, а не код 4
    sl8 = tmp / 'nfkc.jsonl'
    got = run(['--слід', str(sl8), '-e', f'🜂 【「взяти:127.0.0.1:{port}」 「послати:127.0.0.1:{port}」】\n'
               '» ☂ 🜔взяти 「http://＠example.com/x」 λe 「в1」\n'
               f'» ☂ 🜔взяти 「http://127.0.0.1:{port}／x」 λe 「в2」\n» ☂ 🜔послати 「http://[::1/」 「a」 λe 「в3」'], env)
    vs = json.loads(run(['--перевірити-слід', str(sl8), '--json'], env).stdout)
    check(got.returncode == 0 and got.stdout == 'в1\nв2\nв3\n' and len(vs['заборонено']) == 3,
          'взяти/послати (суд 8в): ＠ ／ [::1 — «заборонено», ☂ ловить (не код 4)', got.stdout + got.stderr + str(vs))
    # суд 8в р2: -e --тека <тека запису> — без прав теки, як файл у тій теці
    got = run(['--тека', str(va / 'вхідні'), '-e', f'🜂 【「читати:{va}/дані」】\n» 🜔читати 「{va}/дані/секрет.txt」'], env8v)
    check(got.returncode == 3 and 'банк' not in got.stdout,
          '-e --тека (суд 8в): тека запису іншої теки власника — без прав теки', got.stdout + got.stderr)
    # суд 8б: глибокі значення — помилка програми (☂ ловить), не код 4
    deep = 'Σ …1 5000 【】 Λa x 【a】'
    for code, what in ((f'» ☂ 〔{{{deep}}}〕 λe 「глибоко」', 'інтерполяція'),
                       (f'» ☂ 🜔жереб {deep} λe 「глибоко」', 'аргумент інструмента'),
                       (f'» ☂ 🜁 「г」 【】 {deep} λe 「глибоко」', 'результат субагента'),
                       ('» ☂ δ ＋ ⁀ μ …1 1001 λi 「[」 「」 ⁀ μ …1 1001 λi 「]」 「」 λe 「глибоко」', 'δ: JSON глибше за 1000')):
        got = run(['-e', f'🜂 【「жереб」】\n{code}\n» 「далі」'], env)
        check(got.returncode == 0 and got.stdout == 'глибоко\nдалі\n', f'глибоке значення (суд 8б): {what} — помилка, ☂ ловить',
              got.stdout + got.stderr[-300:])
    got = run(['-e', '🜂\n» ρ δ ＋ ⁀ μ …1 999 λi 「[」 「」 ⁀ μ …1 999 λi 「]」 「」'], env)
    check(got.returncode == 0, 'δ: JSON на 999 рівнів — можна', got.stderr[-300:])
    got = run(['-e', '🜂\n» ☂ δ 「["\\ud800"]」 λe e\n» ☂ δ 「{"\\ud800": 1}」 λe e'], env)
    check(got.stdout == 'δ: не JSON: у рядку неповний символ (сурогат)\n' * 2,
          'δ: самотній сурогат — помилка і в значенні, і в ключі словника (ключ пропускало)', got.stdout + got.stderr[-300:])
    # ↘: ] у лапках умови — частина значення; [n] — лише 0–9; префікс — помилка, а не всі простори
    xe = '← док χ 「<Д><N><Nm>ТОВ [Р]</Nm><A>5</A></N><N><Nm>Б</Nm><A>7</A></N></Д>」\n'
    got = run(['-e', f'🜂\n{xe}» μ ↘ док 〔//N[Nm=\'ТОВ [Р]\']/A〕 λx §x 「текст」'], env)
    check(got.returncode == 0 and got.stdout == '【「5」】\n', '↘ (суд 8б): «]» у лапках умови — частина значення, не код 4',
          got.stdout + got.stderr[-300:])
    for p_, why in (('//N[٢]', 'поза підмножиною'), ('//a:N', 'префікс')):
        got = run(['-e', f'🜂\n{xe}» ☂ ↘ док 〔{p_}〕 λe e'], env)
        check(got.returncode == 0 and why in got.stdout, f'↘ (суд 8б): {p_} — помилка', got.stdout + got.stderr[-300:])
    # ✓: перелік — раз (не n²), межі й переліки — цифри 0–9, порожні межі й альтернативи, межі для ∅ — помилка схеми
    t0 = time.monotonic()
    got = run(['-e', '🜂\n← в ⁀ μ …1 30000 λi ＋ 「a」 σ i 「|」\n» ρ ✓ μ …1 30000 λi ＋ 「a」 σ i 【＋ 「рядок:」 в】'], env)
    check(got.returncode == 0 and time.monotonic() - t0 < 30, '✓ (суд 8б): перелік із 30 000 на 30 000 — без квадрату',
          f'{time.monotonic() - t0:.1f} с ' + got.stderr[-300:])
    for sch in ('「рядок:..৪」', '「число:٣..٩」', '「ціле:」', '「ціле:..」', '「рядок:a||b」', '「рядок:a|」', '「∅:0..1」',
                '「число:٥|6」'):
        got = run(['-e', f'🜂\n» ☂ ✓ 5 {sch} λe 「схема」'], env)
        check(got.stdout == 'схема\n', f'✓ (суд 8б): {sch} — помилка схеми', got.stdout + got.stderr[-300:])
    for sch in ('「рядок:a||b」', '「рядок:a|」', '「рядок:|a」'):
        got = run(['-e', f'🜂\n» ☂ ✓ 「」 {sch} λe 「схема」'], env)
        check(got.stdout == 'схема\n', f'✓ (суд 8б): {sch} — порожній рядок не проходить мовчки', got.stdout + got.stderr[-300:])
    got = run(['-e', '🜂\n» ✓ ¯1 「число:¯1|1」\n» ✓ 2 「число:¯1|1」'], env)
    check(got.stdout.split('\n')[0] == '-1' and 'не з переліку' in got.stdout + got.stderr,
          '✓: перелік чисел — за значенням (¯1)', got.stdout + got.stderr[-300:])
    # --сухо: годинник ДО першої придушеної дії — теж невідомий
    got = run(['--сухо', '-e', f'🜂 【「послати:127.0.0.1:{port}」 「час」】\n← т 🜔час\n'
               f'» ¿ ＝ т 「x」 🜔послати 「http://127.0.0.1:{port}/」 「a」 「ні」'], env)
    check('⚠' in got.stderr, '--сухо (суд 8б): рішення за годинником до придушеної дії — ⚠', got.stderr)
    # χ-запис: записане читається назад — без префікса, лише назви, які бере розбирач; CR; невідомі ключі
    for el, why in (('『「тег」 「p:x」』', 'не назва тегу'), ('『「тег」 「xml:x」』', 'не назва тегу'), ('『「тег」 「ª」』', 'не назва тегу'),
                    ('『「тег」 「a」 「атрибути」 『「x:y」 「1」』』', 'не назва атрибута'),
                    ('『「тег」 「a」 「дiти」 【】』', 'невідомі ключі')):
        got = run(['-e', f'🜂\n» ☂ χ {el} λe e'], env)
        check(why in got.stdout, f'χ-запис (суд 8б): {el} — помилка', got.stdout + got.stderr[-300:])
    got = run(['-e', '🜂\n» Δ § χ χ 『「тег」 「a」 「текст」 δ 「"x\\ry"」』 「текст」'], env)
    check(got.stdout == '"x\\ry"\n', 'χ (суд 8б): \\r у тексті — туди й назад без втрат', got.stdout + got.stderr[-300:])
    # --печатка: квоти власника (і звуження) показано
    sl = json.loads(run(['--печатка', '--json', '-e', f'🜂 【「взяти:127.0.0.1:{port}」】\n» 1'],
                        dict(env, NIGREDO_HOME=str(qh))).stdout)
    check(sl.get('квоти_власника') == [{'інструмент': 'мережа.взяти', 'обмеження': f'127.0.0.1:{port}', 'не_більше': 2}],
          '--печатка --json (суд 8б): квоти власника', str(sl))
    got = run(['-e', '🜂\n» ⌕ 「a=1 b=2」 「(\\w)=」\n» ⌕ 「a=1」 「\\w=」'], env)
    check(got.stdout == '【【「a」】 【「b」】】\n【「a=」】\n', '⌕: з однією групою — теж список груп (як обіцяє памʼятка)', got.stdout)
    # суд 9: шаблон із даних — звичайна помилка мови (☂ ловить), а не код 4; \N{…} — однаково в обох виконавцях
    rx_cases = [('⌕ 「İstanbul」 「(?i)[a-z]+」', '【「İstanbul」】'), ('⌕ 「İi」 「(?i)i」', '【「İ」 「i」】'),
                ('⌕ 「ẞß」 「(?i)ß」', '【「ẞ」 「ß」】'), ('⌕ 「İ」 「(?i)[^a-z]」', '【】'),
                ('≋ 「ab」 「(a)」 「\\²」', '\\²b'),
                ('⌕ 「Ο Οδυσσεύς」 「(?i)ΟΔΥΣΣΕΎΣ」', '【「Οδυσσεύς」】'), ('⌕ 「5 µg」 「(?i)μg」', '【「µg」】'),
                ('⌕ 「KIRIK kırık」 「(?i)kirik」', '【「KIRIK」 「kırık」】'), ('⌕ 「Straſse」 「(?i)strasse」', '【「Straſse」】'),
                ('⌕ 「k K」 「(?i)[K-K]」', '【「k」 「K」】'), ('⌕ 「\u212a k」 「(?ai)k」', '【「k」】'), ('⌕ 「\u212a k」 「(?i)k」', '【「\u212a」 「k」】'),
                ('ρ ≋ 「a」 「a」 「\\012」', '1'), ('≋ 「ab」 「(a)」 「\\1\\.」', 'a\\.b'),
                ('≋ 「x」 「y」 「\\9」', '≋: у заміні немає групи 9'),
                ('≋ 「a」 「a」 「\\400」', '≋: у заміні вісімкове \\400 понад \\377'),
                ('≋ 「ab」 「(a)」 「\\g<١>」', '≋: у заміні немає групи «١»'),
                ('⌕ 「a」 ＋ 「a{4294967296」 「}」', '⌕: хибний шаблон: завелике число повторень (the repetition number is too large)'),
                ('⌕ 「a」 ＋ 「a{4294967295」 「}」', '⌕: хибний шаблон: завелике число повторень (the repetition number is too large)'),
                ('⌕ 「a」 ＋ 「a{1,4294967296」 「}」', '⌕: хибний шаблон: завелике число повторень (the repetition number is too large)'),
                ('⌕ 「a」 ＋ 「a{4294967294」 「}」', '⌕: шаблон розгортається понад 20000 інструкцій (зменште {m,n})'),
                ('⌕ 「a」 ＋ 「a{1073741823」 「}」', '⌕: шаблон розгортається понад 20000 інструкцій (зменште {m,n})'),
                ('⌕ 「a」 ＋ 「(?a)(?u)」 「a」', '⌕: хибний шаблон: прапорці ASCII і UNICODE несумісні (ASCII and UNICODE flags are incompatible)'),
                ('⌕ 「ab」 ＋ 「\\N{LATIN SMALL LETTER B」 「}」',
                 '⌕: \\N{…} (назва символу) у шаблоні не підтримано — напишіть сам символ'),
                ('⌕ 「a\\\\Nb」 「\\\\\\\\N」', '【「\\\\N」】')]
    got = run(['-e', '🜂\n' + ''.join(f'» ☂ {c} λe e\n' for c, _ in rx_cases)], env)
    want = [w for _, w in rx_cases]
    check(got.returncode == 0 and got.stdout.split('\n')[:-1] == want, '⌕ ≋ з даних (суд 9, 9б): İ, \\², a{2³²}, (?a)(?u), \\N{…} — '
          'помилки мови під ☂, без коду 4; (?i) і заміна — як у Python re (_casefix, \\012, \\.)', '\n'.join(f'{a!r} ≠ {b!r}' for a, b in zip(got.stdout.split('\n'), want) if a != b)
          + got.stderr)
    # суд 9б: (?i) — як у Python re, включно з таблицею еквівалентностей (_casefix) і діапазонами: кількість збігів
    try:
        import re._casefix as casefix_
        extra_ = casefix_._EXTRA_CASES
    except ImportError:            # Python 3.10 — без таблиці: перевірка лише там, де вона є
        extra_ = {}
    pairs_ = []
    for k_, v_ in sorted(extra_.items()):
        text_ = ''.join([chr(k_), *map(chr, v_), chr(k_).upper(), *(chr(x).upper() for x in v_), 'x'])
        c_ = chr(k_)
        for p_ in (f'(?i){c_}', f'(?i)[{c_}]', f'(?i)[^{c_}]', f'(?i)[{c_}-{c_}]', f'(?ai){c_}'):
            pairs_.append((p_, text_, len(re.findall(p_, text_))))
    pairs_ += [(p_, 'kKK', len(re.findall(p_, 'kKK'))) for p_ in ('(?i)[K-K]', '(?i)[K]', '(?ai)[K]', '(?i)[J-L]', '(?ai)[J-L]')]
    if pairs_:
        got = run(['-e', '🜂\n' + ''.join(f'» ρ ⌕ 「{t_}」 「{p_}」\n' for p_, t_, _ in pairs_)], env)
        diff_ = [f'{p_} на {t_!r}: re {n_}, ми {g_}' for (p_, t_, n_), g_ in zip(pairs_, got.stdout.split('\n'))
                 if str(n_) != g_]
        check(got.returncode == 0 and not diff_, f'(?i) як у Python re: {len(pairs_)} шаблонів на парах _casefix (σ/ς, µ/μ, '
              f'i/ı, s/ſ, в/ᲀ…), діапазони, (?a) (суд 9б)', '\n'.join(diff_[:5]) + got.stderr[-300:])
    for mode in (['--перевірити'], ['--печатка', '--json'], ['--розбір'], []):
        got = run([*mode, '-e', '🜂\n» ⌕ 「a」 「a{4294967296}」'], env)
        check(got.returncode == 2 and 'Traceback' not in got.stderr + got.stdout
              and 'the repetition number is too large' in got.stderr + got.stdout,
              f'буквальний a{{4294967296}} {" ".join(mode) or "запуск"} — помилка до запуску, код 2', got.stderr)
    # суд 9: 🜔читати файлу, довшого за --розмір, — помилка, а не тихе обрізання (і CRLF — один символ)
    (DATA / 'звіти' / 'межа_1000.txt').write_bytes(b'\xd0\x96' * 998 + b'\r\n!')
    (DATA / 'звіти' / 'межа_1001.txt').write_bytes(b'\xd0\x96' * 999 + b'\r\n!')
    got = run(['--розмір', '1000', '-e', f'🜂 【「читати:{DATA}」】\n» ρ 🜔читати 「звіти/межа_1000.txt」\n'
               f'» ☂ ρ 🜔читати 「звіти/межа_1001.txt」 λe e'], env)
    check(got.stdout == '1000\nфайл.читати: у файлі понад 1000 символів (--розмір) — частину не читаю мовчки: '
          'звіти/межа_1001.txt\n', '🜔читати: рівно --розмір символів — так, на один більше — помилка (суд 9)',
          got.stdout + got.stderr)

    # суд 9: розбіжності Атанора з еталоном — та сама програма тут і еталоном поруч: вивід, код, кроки — однакові
    def both(args, e=env):
        return run(args, e), subprocess.run([sys.executable, str(NGR), *args], capture_output=True, text=True, env=e)
    got, ref = both(['-e', '🜂\n» ⇣ 「ΣΣ ΑΣΣΑ ΟΔΥΣΣΕΥΣ ΑΣ\'Σ Σ」\n» ☂ δ 「1e99999999999999999999」 λe e\n'
                     '» ☂ ν 「1e-99999999999999999999」 λe e\n» ☂ δ 「[1e999999999999999999]」 λe e'])
    check(got.stdout == ref.stdout == "σς ασσα οδυσσευς ασ'ς σ\nδ: порядок числа понад 30000 цифр\n"
          "ν: порядок числа понад 30000 цифр\nδ: порядок числа понад 30000 цифр\n",
          '⇣ кінцева сигма (ΣΣ → σς) і порядок понад межі Decimal — однаково в обох', got.stdout + ref.stdout)
    got, ref = both(['-e', '🜂 「памʼять」\n← глиб Σ …1 2001 【】 Λa i 【a】\n» ☂ 🜄 「k」 глиб λe e\n» 🜃 「k」\n'
                     '← нам 1\n← นาม 2\n← नाम 3\n» ＋ ＋ нам นาม नाम'])
    check(got.stdout == ref.stdout == '🜄: значення вкладене надто глибоко\n∅\n6\n',
          '🜄 надто глибокого — помилка ДО запису в памʼять; імена зі знаками голосних (суд 9)', got.stdout + got.stderr)
    got, ref = both(['-e', '🜂\n» ☂ δ 「{"a":1,"a":2}」 λe e\n» ☂ δ 「[{"b":{"c":1,"c":1}}]」 λe e\n» δ 「{"a":1,"b":2}」\n'
                     '» ☂ δ 「」 λe e\n» ☂ ‰ ν 「3.14159265358979323846264338327950288419716939937510582097494459」 7 λe e'])
    check(got.stdout == ref.stdout and got.stdout.count('ключ в обʼєкті повторюється') == 2 and '『「a」 1 「b」 2』' in got.stdout
          and 'очікувалося значення: рядок 1, стовпець 1 (символ 0)' in got.stdout and 'Inexact' not in got.stdout
          and 'довший за 60 значущих цифр' in got.stdout,
          'δ: повтор ключа — помилка в обох (а не «останній перемагає»); помилки JSON і десяткових — словами, а не '
          '«Expecting value», «(Inexact)» (суд 9б)', got.stdout + ref.stdout)
    got, ref = both(['-e', '🜂\n» ☂ ◷ 「2026-02-29」 1 λe e\n» ☂ ◷ 「2026-2-1」 1 λe e\n» ☂ ▦ δ 「"a,b\\\\rc,d"」 λe e\n'
                     '» ☂ δ δ 「"\\\\ufeff[1]"」 λe e'])
    check(got.stdout == ref.stdout and 'такої дати чи часу немає' in got.stdout and 'не дата ISO' in got.stdout
          and 'newline' not in got.stdout and 'utf-8-sig' not in got.stdout and 'BOM (U+FEFF)' in got.stdout,
          '◷ 2026-02-29 — «такої дати немає»; CSV і BOM — без порад Python (суд 9)', got.stdout + got.stderr)
    dry_prog = (f'🜂 【「писати:{DATA}/звіти」 「оракул」】\n← p 🜔оракул 「так?」\n'
                f'🜔писати 「{DATA}/звіти/сухо_обидва.txt」 σ p\n¿ ¬ p 《 🜔писати 「{DATA}/звіти/сухо2.txt」 「b」 》 ∅\n» 「кінець」')
    got, ref = both(['--сухо', '-e', dry_prog])
    check(got.returncode == ref.returncode == 0 and got.stdout == ref.stdout and got.stderr == ref.stderr
          and '2 дій не виконано' in got.stderr and '⚠' in got.stderr and not (DATA / 'звіти' / 'сухо_обидва.txt').exists(),
          '--сухо: Атанор сам — той самий вивід і звіт, що в еталона (суд 9)', got.stderr + '\n---\n' + ref.stderr)
    deep = '🜂 「стек」\n← f λn ¿ ≤ n 0 0 ' + '＋ 1 ' * 60 + 'f － n 1\n» f 1900'
    got, ref = both(['-e', deep])
    check(got.returncode == ref.returncode == 0 and got.stdout == ref.stdout == '114000\n',
          'рекурсія 1900 × 60 вкладених ＋ — у межах мови, без коду 4 (суд 9)', got.stderr[-300:] + ref.stderr[-300:])
    # суд 9б: глибина — правило мови (виклики × висота тіла ≤ MAX_WORK), а не розмір стеку: ☂ ¿ ∧ на межі — однаково,
    # без SIGABRT і «обірваного» сліду
    for name_, body_, n_ in (('☂', '☂ ' * 100 + 'f － n 1' + ' λe 0' * 100, 1999), ('¿', '¿ ● ' * 100 + 'f － n 1' + ' 0' * 100, 1999),
                             ('∧', '∧ ● ' * 100 + 'f － n 1', 1999), ('μ λ', '§ μ 【n】 λk ' + '＋ 1 ' * 200 + 'f － k 1 0', 999)):
        rr_ = []
        for k_, cmd_ in enumerate((NGR_CMD, [sys.executable, str(NGR)])):
            tp_ = tmp / f'глиб{len(body_)}_{k_}.jsonl'
            r_ = subprocess.run([*cmd_, '--слід', str(tp_), '-e', f'🜂\n← f λn ¿ ≤ n 0 0 {body_}\n» f {n_}'],
                                capture_output=True, text=True, env=env)
            rr_.append((r_.returncode, r_.stdout, r_.stderr, run(['--перевірити-слід', str(tp_)], env).stdout))
        check(rr_[0][:3] == rr_[1][:3] and rr_[0][0] == 1 and 'понад 200000 рівнів' in rr_[0][2]
              and all('обірвано' not in x[3] and '✓' in x[3] for x in rr_),
              f'глибина: рекурсія {n_} × {len(body_.split())}… рівнів {name_} — «надто глибока рекурсія» в обох, слід цілий (суд 9б)',
              rr_[0][2][-300:] + rr_[1][2][-300:] + rr_[0][3][-200:])
    got, ref = both(['-e', '🜂\n← f λn ¿ ≤ n 0 0 ' + '☂ ' * 96 + 'f － n 1' + ' λe 0' * 96 + '\n» f 1999'])
    check(got.returncode == ref.returncode == 0 and got.stdout == ref.stdout == '0\n',
          'глибина: 1999 × 96 рівнів ☂ (у межі MAX_WORK) — відповідь в обох (суд 9б)', got.stderr[-300:] + ref.stderr[-300:])
    (tmp / 'бд_вл').mkdir()
    (tmp / 'бд_вл' / 'дозволи.json').write_text(json.dumps({'дозволено': [f'бд.писати:{DATA}/звіти', f'бд.читати:{DATA}/звіти',
                                                                        'жереб']}, ensure_ascii=False), encoding='utf-8')
    envd = dict(env, NIGREDO_HOME=str(tmp / 'бд_вл'))
    db_ = f'🜂 【「бд.писати:{DATA}/звіти」】\n» 🜔бд.писати 「{DATA}/звіти/кроки.db」 「CREATE TABLE IF NOT EXISTS т(x)」 【】'
    run(['-e', db_], envd)
    cte = (f'🜂 【「бд.читати:{DATA}/звіти」】\n» 🜔бд.читати 「{DATA}/звіти/кроки.db」 「WITH RECURSIVE t(x) AS (SELECT 1 UNION ALL '
           f'SELECT x + 1 FROM t WHERE x < 100000) SELECT count(*) AS n FROM t」 【】')
    steps_ = []
    for k_, cmd_ in enumerate((NGR_CMD, [sys.executable, str(NGR)])):
        tp_ = tmp / f'кроки{k_}.jsonl'
        subprocess.run([*cmd_, '--слід', str(tp_), '-e', cte], capture_output=True, env=envd)
        steps_.append(json.loads(tp_.read_text(encoding='utf-8').splitlines()[-1]).get('кроків'))
    check(steps_[0] == steps_[1] and steps_[0], 'кроки SQLite — детерміновано й однаково в обох (суд 9)', str(steps_))
    got, ref = both(['-e', f'🜂 【「бд.писати:{DATA}/звіти」 「жереб≤2」】\n'
                     f'» ☂ 🜔бд.писати 「{DATA}/звіти/кроки.db」 「SELECT strftime(?, ?) AS t」 【「%s」 「now」】 λe e\n'
                     f'» ☂ 🜔бд.писати 「{DATA}/звіти/кроки.db」 「SELECT random() AS r」 【】 λe e'], envd)
    dry_db = (f'🜂 【「бд.читати:{DATA}/звіти」 「бд.писати:{DATA}/звіти」 「жереб」】\n← с § § 🜔бд.читати '
              f'「{DATA}/звіти/кроки.db」 「SELECT abs(random()) % 2 AS p」 【】 0 「p」\n'
              f'¿ ＝ с 0 🜔бд.писати 「{DATA}/звіти/кроки.db」 「INSERT INTO т VALUES (1)」 【】 ∅\n» 「кінець」')
    dry_both = both(['--сухо', '-e', dry_db], envd)
    check(all(x.returncode == 0 and '⚠' in x.stderr for x in dry_both),
          '--сухо: рішення за запитом SQLite з random() (дано «жереб») — з ⚠ (суд 9)', dry_both[0].stderr + dry_both[1].stderr)
    check(got.stdout == ref.stdout and got.stdout.count('заборонено:') == 2 and 'без права «час»' in got.stdout
          and 'з квотою «жереб≤N»' in got.stdout, 'SQLite: годинник без «час» і random() під квотою жеребу — відмова (суд 9)',
          got.stdout + got.stderr)
    # суд 9б: годинник і жереб через схему (DEFAULT, rowid після 2⁶³−1) — відмова; дата з даних — без прав і без тривоги
    sch = f'{DATA}/звіти/схема9б.db'
    for f_ in (sch, sch + '-journal'):
        if os.path.exists(f_):
            os.remove(f_)
    sch_prog = (f'🜂 【「бд.писати:{DATA}/звіти」 「бд.читати:{DATA}/звіти」】\n← бд 「{sch}」\n← зап λq ☂ 🜔бд.писати бд q 【】 λe e\n'
                '» зап 「CREATE TABLE IF NOT EXISTS т(x, ч DEFAULT CURRENT_TIMESTAMP, в DEFAULT (random()), '
                's DEFAULT (strftime(\'%s\', \'NOW\')), b DEFAULT (date(x\'6e6f77\')))」\n'
                '» зап 「INSERT INTO т(x, в, s, b) VALUES (1, 0, 0, 0)」\n» зап 「INSERT INTO т(x, ч, s, b) VALUES (1, 0, 0, 0)」\n'
                '» зап 「INSERT INTO т(x, ч, в, b) VALUES (1, 0, 0, 0)」\n» зап 「INSERT INTO т(x, ч, в, s) VALUES (1, 0, 0, 0)」\n'
                '» зап 「INSERT INTO т(rowid, x, ч, в, s, b) VALUES (9223372036854775807, 2, 0, 0, 0, 0)」\n'
                '» зап 「INSERT INTO т(x, ч, в, s, b) VALUES (3, 0, 0, 0, 0)」\n'
                '» § 🜔бд.читати бд 「SELECT date(\'2026-01-31\', \'+1 month\') AS м, strftime(\'%Y-%m\', ?) AS р, '
                'julianday(\'2026-03-15\') - julianday(\'2026-03-01\') AS д, count(*) AS н FROM т」 【「2026-03-15」】 0\n'
                '» ☂ 🜔бд.читати бд 「SELECT date(\'2026-01-01\', \'localtime\') AS л」 【】 λe e')
    trs_ = []
    outs_ = []
    for k_, cmd_ in enumerate((NGR_CMD, [sys.executable, str(NGR)])):
        for f_ in (sch, sch + '-journal'):
            if os.path.exists(f_):
                os.remove(f_)
        tp_ = tmp / f'схема9б_{k_}.jsonl'
        outs_.append(subprocess.run([*cmd_, '--слід', str(tp_), '-e', sch_prog], capture_output=True, text=True, env=envd))
        trs_.append(tp_)
    o_ = outs_[0].stdout
    check(outs_[0].stdout == outs_[1].stdout and outs_[0].returncode == outs_[1].returncode == 0
          and o_.count('годинник SQLite (current_timestamp)') == 1 and o_.count('випадковість SQLite (random)') == 1
          and o_.count('годинник SQLite (strftime') == 1 and o_.count('годинник SQLite (date') == 2
          and o_.count('рядок отримав би rowid 2⁶³−1') == 1 and "『「м」 「2026-03-03」 「р」 「2026-03」 「д」 14 「н」 1』" in o_
          and 'заборонено: годинник SQLite (date — поточний час чи часовий пояс)' in o_.splitlines()[-1],
          'SQLite: DEFAULT CURRENT_TIMESTAMP / (random()) / (strftime NOW) / BLOB «now», rowid після 2⁶³−1 — відмова '
          'в обох; дати з даних — без «час» (суд 9б)', outs_[0].stdout + outs_[0].stderr + '\n---\n' + outs_[1].stdout)
    got = run(['-e', f'🜂 【「бд.читати:{DATA}/звіти」】\n» 🜔бд.читати 「{sch}」 「SELECT strftime(\'%Y-%m\', ?) AS м」 【「2026-03-15」】'],
              envd)
    gtr = tmp / 'дати9б.jsonl'
    run(['--слід', str(gtr), '-e', f'🜂 【「бд.читати:{DATA}/звіти」】\n» 🜔бд.читати 「{sch}」 「SELECT julianday(?) - julianday(?) AS д」 '
         '【「2026-03-15」 「2026-03-01」】'], envd)
    ver = run(['--перевірити-слід', str(gtr)], envd)
    check(got.stdout == '【『「м」 「2026-03」』】\n' and ver.returncode == 0 and 'заборонено' not in ver.stdout,
          'SQLite: арифметика дат з даних без «час» — не «заборонено», слід без тривоги (суд 9б)', got.stderr + ver.stdout)
    # суд 9б (атаки обома виконавцями): заглушка random() була «детермінованою» — CREATE … AS (random()) проходив і
    # писав схему, якої SQLite не відкриє; а файл — не база чи пошкоджена схема давали код 4. CHECK недетерміновані
    # функції SQLite пускає — і ми так само (а годинник у ньому — відмова)
    import sqlite3
    nd_, bad_, gen_ = (f'{DATA}/звіти/{n}' for n in ('не_база9б.db', 'схема_зламана9б.db', 'недет9б.db'))
    pathlib.Path(nd_).write_text('не база даних, а текст, довший за заголовок SQLite: ' + 'ж' * 80, encoding='utf-8')
    for f_ in (bad_, gen_):
        if os.path.exists(f_):
            os.remove(f_)
    c_ = sqlite3.connect(bad_)
    c_.create_function('random', 0, lambda: 4, deterministic=True)
    c_.execute('CREATE TABLE ж3(a, b AS (random()))')
    c_.close()
    q_ = '🜂 【「бд.писати:{0}/звіти」 「бд.читати:{0}/звіти」】\n'.format(DATA) + ''.join(
        f'» ☂ σ 🜔бд.писати 「{f_}」 「INSERT INTO ж3(a) VALUES (1)」 【】 λe e\n'
        f'» ☂ σ 🜔бд.читати 「{f_}」 「SELECT count(*) AS x FROM sqlite_master」 【】 λe e\n' for f_ in (nd_, bad_)) + ''.join(
        f'» ☂ σ 🜔бд.писати 「{gen_}」 「{s_}」 【】 λe e\n' for s_ in (
            'CREATE TABLE г(a, b AS (random()))', 'CREATE TABLE ч(a, b AS (CURRENT_DATE))', 'CREATE TABLE IF NOT EXISTS і(a)',
            'CREATE INDEX іі ON і(randomblob(2))', 'CREATE TABLE IF NOT EXISTS к(a CHECK (a < CURRENT_DATE))', 'INSERT INTO к VALUES (1)'))
    got, ref = both(['-e', q_], envd)
    c_ = sqlite3.connect(gen_)
    names_ = sorted(r[0] for r in c_.execute('SELECT name FROM sqlite_master'))
    c_.close()
    check(got.stdout == ref.stdout and got.returncode == ref.returncode == 0
          and got.stdout.count('файл — не база SQLite') == 2 and got.stdout.count('схема бази пошкоджена') == 2
          and got.stdout.count('недетермінована функція') == 3 and got.stdout.count('годинник SQLite (current_date)') == 1
          and names_ == ['к', 'і'],
          'SQLite: файл — не база / пошкоджена схема — помилка програми, не код 4; random() і CURRENT_* у GENERATED та '
          'індексі — відмова самого SQLite, у CHECK — як у SQLite; схема лишається читною (суд 9б)', got.stdout + got.stderr + ref.stderr)
    # суд 9в: свій BEFORE-тригер програми (вставка чи UPDATE rowid = 2⁶³−1) ставив межу вже після перевірки — rowid брав
    # SQLite навмання; явний rowid у таблицю на межі — хибна відмова; FTS5 (віртуальна таблиця) — відмова, без SIGSEGV
    tr_, old_, fts_ = (f'{DATA}/звіти/{n}' for n in ('тригер9в.db', 'межа9в.db', 'фтс9в.db'))

    def fresh9v():
        for f_ in (tr_, old_, fts_):
            if os.path.exists(f_):
                os.remove(f_)
        c_ = sqlite3.connect(old_)
        c_.execute('CREATE TABLE м(x)')
        c_.execute('INSERT INTO м(rowid, x) VALUES (9223372036854775807, 0)')
        c_.commit()
        c_.close()
        c_ = sqlite3.connect(fts_)
        c_.execute('CREATE VIRTUAL TABLE ф USING fts5(x)')
        c_.close()
    q9_ = ('🜂 【「бд.писати:{0}/звіти」】\n'.format(DATA) + ''.join(
        f'← {h_} λq ☂ σ 🜔бд.писати 「{f_}」 q 【】 λe e\n' for h_, f_ in (('тригер', tr_), ('межа', old_), ('фтс', fts_))) + ''.join(
        f'» {h_} 「{s_}」\n' for h_, s_ in (
            ('тригер', 'CREATE TABLE t(x)'),
            ('тригер', 'CREATE TRIGGER пастка BEFORE INSERT ON t WHEN NEW.x = 1 BEGIN INSERT OR IGNORE INTO t(rowid, x) '
                  'VALUES (9223372036854775807, 0); END'),
            ('тригер', 'INSERT INTO t(x) VALUES (1)'), ('тригер', 'INSERT INTO t(x) VALUES (0)'),
            ('тригер', 'CREATE TRIGGER пастка2 BEFORE INSERT ON t WHEN NEW.x = 2 BEGIN UPDATE t SET rowid = 9223372036854775807 '
                  'WHERE x = 0; END'),
            ('тригер', 'INSERT INTO t(x) VALUES (2)'), ('тригер', 'UPDATE t SET rowid = 9223372036854775807'),
            ('межа', 'INSERT INTO м(rowid, x) VALUES (5, 1)'), ('межа', 'INSERT INTO м(x) VALUES (2)'),
            ('межа', 'UPDATE м SET x = 3 WHERE rowid = 5'), ('фтс', "INSERT INTO ф(x) VALUES ('а')"))))
    res9v = []
    for cmd_ in (NGR_CMD, [sys.executable, str(NGR)]):
        fresh9v()
        res9v.append(subprocess.run([*cmd_, '-e', q9_], capture_output=True, text=True, env=envd))
        try:                           # програма не розібралася — таблиць немає: провал перевірки, а не traceback
            with sqlite3.connect(tr_) as c_:
                rows_ = [r[0] for r in c_.execute('SELECT rowid FROM t')]
            with sqlite3.connect(old_) as c_:
                rows_.append(sorted(r[0] for r in c_.execute('SELECT rowid FROM м')))
        except sqlite3.Error as e_:
            rows_ = str(e_)
        res9v.append(rows_)
    o_ = res9v[0].stdout
    check(o_ == res9v[2].stdout and res9v[0].returncode == res9v[2].returncode == 0 and res9v[1] == res9v[3] == [1, [5, 2 ** 63 - 1]]
          and o_.count('рядок отримав би rowid 2⁶³−1') == 3 and o_.count('дійшла до rowid 2⁶³−1') == 1
          and o_.count('дія поза дозволеним') == 1 and o_.count('\n1\n') == 3,
          'SQLite: без «жереб» жоден рядок не отримає rowid 2⁶³−1 — і своїм BEFORE-тригером (вставка, UPDATE), і UPDATE; '
          'явний rowid у таблицю на межі — можна; FTS5 — відмова, без SIGSEGV (суд 9в)',
          o_ + res9v[0].stderr + '\n---\n' + res9v[2].stdout + res9v[2].stderr + str(res9v[1::2]))
    # суд 9в: квота «час≤N» — як «жереб≤N»: годинник SQLite з квотою — відмова (його не порахувати), 🜔час — за квотою
    (tmp / 'бд_час').mkdir()
    (tmp / 'бд_час' / 'дозволи.json').write_text(json.dumps({'дозволено': [f'бд.читати:{DATA}/звіти', 'час']},
                                                         ensure_ascii=False), encoding='utf-8')
    got, ref = both(['-e', f'🜂 【「бд.читати:{DATA}/звіти」 「час≤1」】\n» ≠ 0 ρ 🜔час\n» ☂ 🜔час λe e\n'
                     f'» ☂ σ 🜔бд.читати 「{old_}」 「SELECT strftime(\'%Y\', \'now\') AS р」 【】 λe e\n'
                     f'» ☂ σ 🜔бд.читати 「{old_}」 「SELECT CURRENT_DATE AS д」 【】 λe e'],
                    dict(env, NIGREDO_HOME=str(tmp / 'бд_час')))
    check(got.stdout == ref.stdout and got.returncode == ref.returncode == 0 and got.stdout.startswith('●\n')
          and 'вичерпано квоту' in got.stdout and got.stdout.count('з квотою «час≤N» — лише 🜔час') == 2,
          'SQLite: квота «час≤N» — годинник SQLite відмова, як для «жереб≤N» (суд 9в)', got.stdout + got.stderr + ref.stderr)
    # суд 9г (Практик, Оркестратор): «;» на початку запиту валив попередній прохід EXPLAIN — тригерів не було, rowid
    # навмання; sqlite_sequence (тригерів SQLite на ній не дає) і старий файл, де системна таблиця вже на межі
    seq_, sch_, semi_, near_ = (f'{DATA}/звіти/{n}' for n in ('послідовність9г.db', 'схема9г.db', 'крапка9г.db', 'біля9г.db'))

    def fresh9g():
        for f_ in (seq_, sch_, semi_, near_):
            if os.path.exists(f_):
                os.remove(f_)
        with sqlite3.connect(seq_) as c_:
            c_.execute('CREATE TABLE п(id INTEGER PRIMARY KEY AUTOINCREMENT, x)')
            c_.execute("INSERT INTO sqlite_sequence(rowid, name, seq) VALUES (9223372036854775807, 'z', 0)")
        with sqlite3.connect(near_) as c_:     # біля межі: тригер — два нові рядки sqlite_sequence за одну інструкцію
            c_.execute('CREATE TABLE а(id INTEGER PRIMARY KEY AUTOINCREMENT, x)')
            c_.execute('CREATE TABLE б(id INTEGER PRIMARY KEY AUTOINCREMENT, x)')
            c_.execute('CREATE TRIGGER тр AFTER INSERT ON а BEGIN INSERT INTO б(x) VALUES (1); END')
            c_.execute("INSERT INTO sqlite_sequence(rowid, name, seq) VALUES (9223372036854775806, 'z', 0)")
        c_ = sqlite3.connect(sch_, isolation_level=None)
        c_.execute('CREATE TABLE а(x)')
        c_.execute('PRAGMA writable_schema = ON')
        c_.execute("UPDATE sqlite_schema SET rowid = 9223372036854775807 WHERE name = 'а'")
        c_.close()
    q9g_ = ('🜂 【「бд.писати:{0}/звіти」 「бд.читати:{0}/звіти」】\n'.format(DATA) + ''.join(
        f'← {h_} λq ☂ σ 🜔бд.писати 「{f_}」 q 【】 λe e\n' for h_, f_ in (('крапка', semi_), ('посл', seq_), ('схема', sch_),
                                                                  ('біля', near_))) + ''.join(
        f'» {h_} 「{s_}」\n' for h_, s_ in (
            ('крапка', 'CREATE TABLE t(x)'), *(('крапка', p_ + 'INSERT INTO t(rowid, x) VALUES (9223372036854775807, 0)')
                                              for p_ in (';', '  ;  ', ';;', '/* к */;', '-- к\n;')),
            ('крапка', ';INSERT INTO t(x) VALUES (1)'), ('крапка', 'EXPLAIN INSERT INTO t(x) VALUES (2)'),
            ('крапка', ';VACUUM'), ('крапка', 'CREATE TABLE q(id INTEGER PRIMARY KEY AUTOINCREMENT, x)'),
            ('крапка', 'INSERT INTO q(x) VALUES (1)'), ('крапка', "INSERT INTO sqlite_sequence(name, seq) VALUES ('w', 1)"),
            ('крапка', 'UPDATE sqlite_sequence SET rowid = 9223372036854775807'),
            ('крапка', "UPDATE sqlite_sequence SET seq = 0 WHERE name = 'q'"),
            ('посл', 'INSERT INTO п(x) VALUES (1)'), ('посл', 'DELETE FROM sqlite_sequence WHERE rowid = 9223372036854775807'),
            ('посл', 'INSERT INTO п(x) VALUES (1)'), ('схема', 'CREATE TABLE б2(x)'), ('схема', 'INSERT INTO а(x) VALUES (1)'),
            ('біля', 'INSERT INTO а(x) VALUES (1)')))
        + f'» 🜔бд.читати 「{semi_}」 「;SELECT count(*) AS н FROM t」 【】')
    res9g = []
    for cmd_ in (NGR_CMD, [sys.executable, str(NGR)]):
        fresh9g()
        res9g.append(subprocess.run([*cmd_, '-e', q9g_], capture_output=True, text=True, env=envd))
        with sqlite3.connect(semi_) as c_:
            res9g.append([r[0] for r in c_.execute('SELECT rowid FROM t')] + [r[0] for r in c_.execute('SELECT rowid FROM sqlite_sequence')])
        with sqlite3.connect(near_) as c_:
            res9g[-1].append(c_.execute('SELECT count(*) FROM sqlite_sequence').fetchone()[0])
    o_ = res9g[0].stdout
    check(o_ == res9g[2].stdout and res9g[0].returncode == res9g[2].returncode == 0 and res9g[1] == res9g[3] == [1, 1, 1]
          and o_.count('рядок отримав би rowid 2⁶³−1') == 5 and o_.count('VACUUM заборонено') == 1
          and o_.count('системна таблиця «sqlite_sequence»: INSERT і зміна rowid') == 2
          and o_.count('системна таблиця «sqlite_sequence» на межі rowid: рядок, який SQLite допише') == 2
          and o_.count('системна таблиця «sqlite_schema» підійшла до rowid 2⁶³−1') == 1 and o_.endswith('【『「н」 1』】\n'),
          'SQLite: «;», «;;», коментар перед «;» — та сама відмова rowid 2⁶³−1; sqlite_sequence без «жереб» — ні INSERT, ні '
          'rowid; старий файл, де системна таблиця на межі чи біля неї, — відмова (суд 9г)',
          o_ + res9g[0].stderr + '\n---\n' + res9g[2].stdout + res9g[2].stderr + str(res9g[1::2]))
    got, ref = both(['--сухо', '-e', f'🜂 【「бд.писати:{DATA}/звіти」】\n» 🜔бд.писати 「{semi_}」 「;PRAGMA writable_schema = 1」 【】'],
                    envd)
    pre_ = subprocess.run([sys.executable, '-c', 'import sys, sqlite3; sys.path.insert(0, sys.argv[1]); import nigredo as n\n'
                           'c = sqlite3.connect(":memory:"); c.execute("CREATE TABLE а(x)"); c.execute("CREATE TABLE б(x)")\n'
                           'it = n.Interp.__new__(n.Interp); it.caps, it.quota_stack = set(), []\n'
                           'print(sorted(n._db_written(c, it, "SELECT 1; SELECT 2", [])[0]))', str(ROOT / 'interpreter')],
                          capture_output=True, text=True)
    check(got.stdout == ref.stdout and got.returncode == ref.returncode != 0 and 'PRAGMA' in got.stdout + got.stderr
          and pre_.stdout == "['а', 'б']\n",
          '--сухо: «;PRAGMA …» — та сама відмова, що й у запуску; попередній прохід не вдався — захист на всіх таблицях (суд 9г)',
          got.stdout + got.stderr + ref.stdout + ref.stderr + pre_.stdout + pre_.stderr)
    # суд 9д (Практик): AUTOINCREMENT на межі rowid не бере навмання, а відмовляє (database or disk is full) — тригери
    # rowid йому не потрібні; (Аудитор, Оркестратор): таблиця на межі в старому файлі — запобіжна відмова, а не
    # «заборонено» (запит програми — у межах прав); запит, що не компілюється, — без тригерів на всіх таблицях; тексти
    ai_, old_ = f'{DATA}/звіти/авто9д.db', f'{DATA}/звіти/старий9д.db'
    q9d_ = (f'🜂 【「бд.писати:{DATA}/звіти」】\n← п Λф q ☂ σ 🜔бд.писати ф q 【】 λe e\n' + ''.join(
        f'» п 「{f_}」 「{s_}」\n' for f_, s_ in (
            (ai_, 'CREATE TABLE a(id INTEGER PRIMARY KEY AUTOINCREMENT, x)'), (ai_, 'INSERT INTO a(x) VALUES (1)'),
            (ai_, 'UPDATE sqlite_sequence SET seq = 9223372036854775806'), (ai_, 'INSERT INTO a(x) VALUES (2)'),
            (ai_, 'INSERT INTO a(x) VALUES (3)'), (old_, 'INSERT INTO т(x) VALUES (1)'),
            (old_, 'INSERT INTO т(rowid, x) VALUES (5, 1)'), (old_, 'INSERT INTO т(x) VALUES ('),
            (ai_, 'CREATE VIEW v AS SELECT 1 AS k'), (ai_, 'DELETE FROM v'), (ai_, 'SELECT x FROM a ORDER BY 5'),
            (ai_, "SELECT 'a"), (ai_, 'CREATE TABLE sqlite_x(a)'))))
    res9d = []
    for k_, cmd_ in enumerate((NGR_CMD, [sys.executable, str(NGR)])):
        for f_ in (ai_, old_):
            if os.path.exists(f_):
                os.remove(f_)
        with sqlite3.connect(old_) as c_:
            c_.execute('CREATE TABLE т(x)')
            c_.execute('INSERT INTO т(rowid, x) VALUES (9223372036854775807, 0)')
        tp_ = tmp / f'запобіжно{k_}.jsonl'
        res9d.append(subprocess.run([*cmd_, '--слід', str(tp_), '-e', q9d_], capture_output=True, text=True, env=envd))
        with sqlite3.connect(ai_) as c_:
            res9d.append([r[0] for r in c_.execute('SELECT id FROM a')])
        res9d.append(subprocess.run([sys.executable, str(NGR), '--перевірити-слід', str(tp_)], capture_output=True,
                                    text=True, env=envd).stdout)
    o_ = res9d[0].stdout
    check(o_ == res9d[3].stdout and res9d[0].returncode == res9d[3].returncode == 0
          and res9d[1] == res9d[4] == [1, 9223372036854775807] and o_.startswith('0\n1\n1\n1\n')
          and o_.count('таблиця з AUTOINCREMENT вичерпала номери rowid') == 1 and o_.count('запобіжна відмова') == 1
          and 'заборонено' not in o_ and o_.count('незавершений запит') == 1 and 'VIEW) не змінюють' in o_
          and 'поза межами' in o_ and 'незакрита лапка' in o_ and 'службові' in o_
          and all('запобіжних відмов (так у самій базі' in v_ and 'спроб поза правами немає' in v_ and '«заборонено»' not in v_
                  for v_ in (res9d[2], res9d[5])),
          'SQLite: AUTOINCREMENT на межі — SQLITE_FULL, а не відмова «навмання»; таблиця на межі в старому файлі — '
          'запобіжна відмова окремо від «заборонено»; тексти SQLite словами (суд 9д)',
          o_ + res9d[0].stderr + '\n---\n' + res9d[3].stdout + res9d[3].stderr + str(res9d[1::3]) + res9d[2] + res9d[5])
    pre_ = subprocess.run([sys.executable, '-c', 'import sys, sqlite3; sys.path.insert(0, sys.argv[1]); import nigredo as n\n'
                           'c = sqlite3.connect(":memory:"); c.execute("CREATE TABLE а(x)")\n'
                           'it = n.Interp.__new__(n.Interp); it.caps, it.quota_stack = set(), []\n'
                           'print(n._db_written(c, it, "INSERT INTO а VALUES (", []), n._db_written(c, it, "SELECT 1; SELECT 2", [])[0])',
                           str(ROOT / 'interpreter')], capture_output=True, text=True)
    check(pre_.stdout == "(set(), set(), [], [], [], True) {'а'}\n",
          'запит, що не компілюється й сам, — без тригерів на всіх таблицях; що компілюється — захист на всіх (суд 9д)',
          pre_.stdout + pre_.stderr)
    # огляд 0.8.1 (Н-1 Скептика, відтворили всі шестеро): на старій базі справжня спроба ставала «запобіжною відмовою»
    # («запит — у межах прав», «спроб немає»). Тепер запобіжна — лише коли в запиті заборонених дій не знайдено:
    # authorizer — одразу «заборонено»; random, годинник і таблиці-функції PRAGMA — за байткодом; і ознакою, а не
    # підрядком причини (автор: таблиця з назвою «…дійшла до rowid 2⁶³−1…» робила спробу «запобіжною» й на свіжій базі)
    old81_, full81_, new81_ = (f'{DATA}/звіти/{n_}81.db' for n_ in ('старий', 'повний', 'новий'))
    mask_ = '«x» дійшла до rowid 2⁶³−1 — далі SQLite бере його навмання'
    # огляд 0.8.1б: запобіжна для sqlite_sequence — точно (перший рядок нової таблиці з AUTOINCREMENT, а місця до межі
    # немає): решта запитів на старій базі — як на звичайній, з тригерами rowid (явний 2⁶³−1 був «запобіжним», Скептик);
    # sqlite_dbpage — відмова (запис сирих сторінок повз authorizer, Скептик); RAISE тригера бази — його слова (Новачок)
    q81_ = (f'🜂 【「бд.писати:{DATA}/звіти」】\n← п Λф q ☂ σ 🜔бд.писати ф q 【】 λe e\n' + ''.join(
        f'» п 「{f_}」 「{s_}」\n' for f_, s_ in (
            (old81_, f"ATTACH DATABASE '{DATA}/звіти/приєднана81.db' AS x"), (old81_, 'PRAGMA writable_schema = 1'),
            (old81_, 'CREATE TEMP TABLE tt(x)'), (old81_, 'INSERT INTO b(x) VALUES (random())'),
            (old81_, "INSERT INTO b(x) VALUES (date('now'))"),
            (old81_, 'INSERT INTO b(x) SELECT count(*) FROM pragma_database_list'),
            (old81_, "INSERT INTO b(x) VALUES (date('2020-01-01'))"), (old81_, 'INSERT INTO b(x) VALUES (1)'),
            (old81_, 'INSERT INTO t(x) VALUES (1)'), (old81_, 'INSERT INTO a(x) VALUES (1)'),
            (old81_, 'INSERT INTO t(rowid, x) VALUES (9223372036854775807, 1)'),
            (full81_, 'INSERT INTO f(x) VALUES (1)'), (new81_, f'CREATE TABLE "{mask_}"(x)'),
            (new81_, f'INSERT INTO "{mask_}"(rowid, x) VALUES (9223372036854775807, 1)'),
            (new81_, 'UPDATE sqlite_dbpage SET data = data WHERE pgno = 1'), (new81_, 'CREATE TABLE r(x)'),
            (new81_, "CREATE TRIGGER rr BEFORE INSERT ON r BEGIN SELECT RAISE(ABORT, 'запобіжна відмова (x)'); END"),
            (new81_, 'INSERT INTO r(x) VALUES (1)'))))
    res81 = []
    for k_, cmd_ in enumerate((NGR_CMD, [sys.executable, str(NGR)])):
        for f_ in (old81_, full81_, new81_):
            if os.path.exists(f_):
                os.remove(f_)
        with sqlite3.connect(old81_) as c_:
            c_.executescript('CREATE TABLE t(x); CREATE TABLE a(id INTEGER PRIMARY KEY AUTOINCREMENT, x); '
                             'CREATE TABLE b(id INTEGER PRIMARY KEY AUTOINCREMENT, x)')
            c_.execute("INSERT INTO sqlite_sequence(rowid, name, seq) VALUES (1, 'a', 0)")
            c_.execute("INSERT INTO sqlite_sequence(rowid, name, seq) VALUES (9223372036854775807, 'я', 1)")
        with sqlite3.connect(full81_) as c_:
            c_.execute('CREATE TABLE f(x)')
            c_.execute('INSERT INTO f(rowid, x) VALUES (9223372036854775807, 0)')
        tp_ = tmp / f'маска81_{k_}.jsonl'
        res81.append(subprocess.run([*cmd_, '--слід', str(tp_), '-e', q81_], capture_output=True, text=True, env=envd))
        res81.append(subprocess.run([sys.executable, str(NGR), '--перевірити-слід', str(tp_)], capture_output=True,
                                    text=True, env=envd).stdout)
    o_ = res81[0].stdout
    check(o_ == res81[2].stdout and res81[0].returncode == res81[2].returncode == 0
          and o_.count('запобіжна відмова (так у самій базі') == 2 and o_.count('дія поза дозволеним') == 3
          and o_.count('(random) без права «жереб» (з квотою «жереб≤N» — лише 🜔жереб); запит і не виконувався') == 1
          and o_.count('у запиті — date: «зараз» чи дата з даних') == 2
          and o_.count('таблиця-функція pragma_database_list') == 1 and o_.count('запит і не виконувався') == 4
          and o_.count('рядок отримав би rowid 2⁶³−1') == 2 and o_.count('сирі сторінки бази (sqlite_dbpage)') == 1
          and o_.count('тригер бази зупинив запит: «запобіжна відмова (x)»') == 1
          and o_.splitlines().count('1') == 2 and o_.splitlines().count('0') == 3
          and 'у межах прав' not in o_ and not os.path.exists(f'{DATA}/звіти/приєднана81.db')
          and all('⚠ спроб поза правами («заборонено»): 10' in v_ and 'дія SQLite поза дозволеним: ATTACH' in v_
                  and 'запобіжних відмов (так у самій базі; запит не виконано' in v_
                  and 'запит «INSERT INTO b(x) VALUES (1)»' in v_ for v_ in (res81[1], res81[3])),
          'SQLite: запобіжна відмова — лише коли в запиті заборонених дій не знайдено (огляд 0.8.1), а для sqlite_sequence — '
          'точно: перший рядок нової таблиці з AUTOINCREMENT без місця до межі; явний rowid 2⁶³−1 на старій базі — '
          '«заборонено»; sqlite_dbpage — відмова; RAISE тригера — слова бази (огляд 0.8.1б)',
          o_ + res81[0].stderr + '\n---\n' + res81[2].stdout + res81[2].stderr + res81[1] + res81[3])
    got, ref = both(['--сухо', '-e', f'🜂 【「бд.писати:{DATA}/звіти」】\n'
                     f'» 🜔бд.писати 「{new81_}」 「SELECT count(*) FROM pragma_database_list」 【】'], envd)
    pre_ = subprocess.run([sys.executable, '-c', 'import sys, sqlite3; sys.path.insert(0, sys.argv[1]); import nigredo as n\n'
                           'c = sqlite3.connect(":memory:"); c.execute("CREATE TABLE а(x)")\n'
                           'print(n.db_compiles(c, "UPDATE а SET x = x + 1", []), n.db_compiles(c, "INSERT INTO б VALUES (1)", []),'
                           ' n.clip("слово " * 40, 50))', str(ROOT / 'interpreter')], capture_output=True, text=True)
    check(got.stdout == ref.stdout and got.returncode == ref.returncode != 0
          and 'дія поза дозволеним (лише SELECT, INSERT' in got.stdout + got.stderr
          and pre_.stdout == 'True False ' + 'слово ' * 7 + 'слово…\n',
          '--сухо: таблиця-функція PRAGMA — та сама відмова, що й у запуску; db_compiles — за викликом authorizer, а не '
          'текстом помилки (UPDATE з читанням стовпця); підсумок сліду не обрізає посеред слова (огляд 0.8.1)',
          got.stdout + got.stderr + ref.stdout + ref.stderr + pre_.stdout + pre_.stderr)
    rd81_ = (f'🜂 【「бд.читати:{DATA}/звіти」】\n'
             f'» ☂ 🜔бд.читати 「{old81_}」 「SELECT * FROM "table sqlite_x may not be modified"」 【】 λe e\n'
             f'» ☂ 🜔бд.читати 「{old81_}」 「WITH a AS (SELECT 1) DELETE FROM sqlite_master」 【】 λe e')
    rd81 = [subprocess.run([*cmd_, '--слід', str(tmp / f'описка81_{k_}.jsonl'), '-e', rd81_], capture_output=True,
                           text=True, env=envd) for k_, cmd_ in enumerate((NGR_CMD, [sys.executable, str(NGR)]))]
    v81 = [subprocess.run([sys.executable, str(NGR), '--перевірити-слід', str(tmp / f'описка81_{k_}.jsonl')],
                          capture_output=True, text=True, env=envd).stdout for k_ in range(2)]
    check(rd81[0].stdout == rd81[1].stdout and 'немає такої таблиці' in rd81[0].stdout
          and rd81[0].stdout.count('дія поза дозволеним') == 1 and all('(«заборонено»): 1 ' in v_ for v_ in v81),
          'бд.читати: «table … may not be modified» — запис, який SQLite відкинув до authorizer, — лише весь текст '
          'помилки; описка з цими словами в назві — не «заборонено» (огляд 0.8.1)', rd81[0].stdout + rd81[1].stdout + str(v81))
    # огляд 0.8.1б (Аудитор): вичерпана квота ховала спробу — random і годинник ставали «квоту вичерпано»; права без
    # дії тепер бачать байткод, як і стара база (і --сухо: «✓» на random); rowid без виконання не перевірити — так і сказано
    quota81_ = f'{DATA}/звіти/квота81.db'
    q81q_ = (f'🜂 【「бд.писати:{DATA}/звіти≤1」】\n← п λq ☂ σ 🜔бд.писати 「{quota81_}」 q 【】 λe e\n' + ''.join(
        f'» п 「{s_}」\n' for s_ in ('INSERT INTO t(x) VALUES (1)', 'INSERT INTO t(x) VALUES (random())',
                                   "INSERT INTO t(x) VALUES (date('now'))", f"ATTACH DATABASE '{DATA}/звіти/к81.db' AS z",
                                   'INSERT INTO t(rowid, x) VALUES (9223372036854775807, 1)')))
    resq81 = []
    for k_, cmd_ in enumerate((NGR_CMD, [sys.executable, str(NGR)])):
        if os.path.exists(quota81_):
            os.remove(quota81_)
        with sqlite3.connect(quota81_) as c_:
            c_.execute('CREATE TABLE t(x)')
        tp_ = tmp / f'квота81_{k_}.jsonl'
        resq81.append(subprocess.run([*cmd_, '--слід', str(tp_), '-e', q81q_], capture_output=True, text=True, env=envd))
        resq81.append(subprocess.run([sys.executable, str(NGR), '--перевірити-слід', str(tp_)], capture_output=True,
                                     text=True, env=envd).stdout)
    dry81 = both(['--сухо', '-e', f'🜂 【「бд.писати:{DATA}/звіти」】\n'
                  f'» 🜔бд.писати 「{quota81_}」 「INSERT INTO t(x) VALUES (random())」 【】'], envd)
    o_ = resq81[0].stdout
    check(o_ == resq81[2].stdout and o_.count('вичерпано квоту') == 1 and o_.count('дія поза дозволеним (лише') == 1
          and o_.count('бд.писати: заборонено: ') == 2
          and 'випадковість SQLite (random)' in o_ and 'у запиті — date' in o_
          and all('(«заборонено»): 3 ' in v_ and 'квоту вичерпано (межа спрацювала' in v_
                  and 'VALUES (9223372036854775807, 1)' in v_ for v_ in (resq81[1], resq81[3]))
          and dry81[0].stdout == dry81[1].stdout and dry81[0].returncode == dry81[1].returncode != 0
          and 'випадковість SQLite (random)' in dry81[0].stdout + dry81[0].stderr,
          'квота не ховає спроби: random і годинник у запиті після вичерпаної квоти — «заборонено», у підсумку квоти — сам '
          'запит; --сухо бачить random (огляд 0.8.1б)', o_ + resq81[0].stderr + resq81[1] + dry81[0].stdout + dry81[0].stderr)
    # огляд 0.8.1в: службова ngr_rowid — лише з тимчасових тригерів інтерпретатора (Скептик: ngr_rowid('t', 0) у SQL
    # програми робив спробу «запобіжною», ngr_rowid('t', 9) розводив виконавців; Оркестратор: не за назвою, яку програма
    # може дати своєму тригеру чи VIEW); описка в стовпці на базі «межа» — звичайна помилка (Скептик, Оркестратор);
    # ON CONFLICT FAIL лишає зроблене, як автокоміт (транзакція запису); текст відмови під квотою — як у запуску (Аудитор)
    svc81_ = f'{DATA}/звіти/службова81.db'
    q81v_ = (f'🜂 【「бд.писати:{DATA}/звіти」】\n← п λq ☂ σ 🜔бд.писати 「{svc81_}」 q 【】 λe e\n' + ''.join(
        f'» п 「{s_}」\n' for s_ in (
            "INSERT INTO t(rowid, x) VALUES (9223372036854775807, ngr_rowid('t', 0))",
            "INSERT INTO t(x) VALUES (ngr_rowid('t', 9))", "CREATE VIEW ngr_rowid_0_0 AS SELECT ngr_rowid('t', 0) AS a",
            'INSERT INTO t(x) SELECT a FROM ngr_rowid_0_0',
            "CREATE TRIGGER ngr_rowid_0_1 AFTER INSERT ON t BEGIN SELECT ngr_rowid('t', 0); END",
            'INSERT INTO t(x) VALUES (1)', 'DROP TRIGGER ngr_rowid_0_1', 'INSERT INTO t(y) VALUES (1)',
            'INSERT INTO u(k) VALUES (1)', 'INSERT OR FAIL INTO u(k) SELECT 2 UNION ALL SELECT 1 UNION ALL SELECT 3',
            'INSERT INTO t(x) VALUES (2)')))
    res81v = []
    for k_, cmd_ in enumerate((NGR_CMD, [sys.executable, str(NGR)])):
        if os.path.exists(svc81_):
            os.remove(svc81_)
        with sqlite3.connect(svc81_) as c_:     # «межа»: sqlite_sequence на 2⁶³−1, b з AUTOINCREMENT ще без рядка
            c_.executescript('CREATE TABLE t(x); CREATE TABLE u(k UNIQUE); '
                             'CREATE TABLE b(id INTEGER PRIMARY KEY AUTOINCREMENT, x)')
            c_.execute("INSERT INTO sqlite_sequence(rowid, name, seq) VALUES (9223372036854775807, 'я', 1)")
        tp_ = tmp / f'службова81_{k_}.jsonl'
        res81v.append(subprocess.run([*cmd_, '--слід', str(tp_), '-e', q81v_], capture_output=True, text=True, env=envd))
        res81v.append(subprocess.run([sys.executable, str(NGR), '--перевірити-слід', str(tp_)], capture_output=True,
                                     text=True, env=envd).stdout)
        with sqlite3.connect(svc81_) as c_:
            res81v.append([r[0] for r in c_.execute('SELECT x FROM t')] + [r[0] for r in c_.execute('SELECT k FROM u')])
    o_ = res81v[0].stdout
    check(o_ == res81v[3].stdout and res81v[0].returncode == res81v[3].returncode == 0 and res81v[2] == res81v[5] == [2, 1, 2]
          and o_.count('бд.писати: заборонено: службова функція інтерпретатора (ngr_rowid)') == 4
          and 'запобіжн' not in o_ and o_.count('у таблиці немає стовпця з такою назвою') == 1
          and o_.count('порушено унікальність') == 1 and o_.splitlines().count('0') == 3
          and all('(«заборонено»): 4 ' in v_ and 'запобіжн' not in v_ for v_ in (res81v[1], res81v[4])),
          'SQLite: службова ngr_rowid — лише з тимчасових тригерів інтерпретатора (з SQL програми, її VIEW і тригера — '
          '«заборонено»); описка в стовпці на базі «межа» — звичайна помилка; ON CONFLICT FAIL лишає зроблене (огляд 0.8.1в)',
          o_ + res81v[0].stderr + res81v[1] + res81v[3].stdout + str(res81v[2]) + str(res81v[5]))
    # автор (огляд 0.8.1в): між попереднім проходом і запуском інший процес (чи гілка ‖) міняв схему — тригер бази писав
    # rowid 2⁶³−1 у таблицю, на якій тригерів rowid не було; тепер прохід, тригери й запит — в одній транзакції запису
    race81_ = f'{DATA}/звіти/гонка81.db'
    resr81 = []
    for cmd_ in (NGR_CMD, [sys.executable, str(NGR)]):
        if os.path.exists(race81_):
            os.remove(race81_)
        with sqlite3.connect(race81_) as c_:
            c_.executescript('CREATE TABLE t(x); CREATE TABLE u(x)')
        holder_ = subprocess.Popen([sys.executable, '-c', 'import sqlite3, sys, time\n'
                                    'c = sqlite3.connect(sys.argv[1], isolation_level=None); c.execute("BEGIN IMMEDIATE")\n'
                                    'print("так", flush=True); time.sleep(1.5)\n'
                                    'c.execute("CREATE TRIGGER tr AFTER INSERT ON t BEGIN INSERT INTO u(rowid, x) '
                                    'VALUES (9223372036854775807, 1); END"); c.execute("COMMIT")', race81_],
                                   stdout=subprocess.PIPE, text=True)
        holder_.stdout.readline()
        resr81.append(subprocess.run([*cmd_, '-e', f'🜂 【「бд.писати:{DATA}/звіти」】\n'
                                      f'» ☂ 🜔бд.писати 「{race81_}」 「INSERT INTO t(x) VALUES (1)」 【】 λe e'],
                                     capture_output=True, text=True, env=envd).stdout)
        holder_.wait()
        with sqlite3.connect(race81_) as c_:
            resr81.append(c_.execute('SELECT count(*) FROM u').fetchone()[0])
    # запит, якого попередній прохід не скомпілював (зайвий параметр), — захист на всіх таблицях, і DROP TABLE прибирає
    # з таблицею й тимчасовий тригер інтерпретатора: це не спроба
    drop81 = []
    for cmd_ in (NGR_CMD, [sys.executable, str(NGR)]):
        with sqlite3.connect(race81_) as c_:
            c_.execute('CREATE TABLE IF NOT EXISTS u(x)')
        drop81.append(subprocess.run([*cmd_, '-e', f'🜂 【「бд.писати:{DATA}/звіти」】\n'
                                      f'» ☂ 🜔бд.писати 「{race81_}」 「DROP TABLE u」 【1】 λe e\n'
                                      f'» 🜔бд.писати 「{race81_}」 「DROP TABLE u」 【】'], capture_output=True, text=True, env=envd))
    dry81v = both(['--сухо', '-e', f'🜂 【「бд.писати:{DATA}/звіти」】\n» 🜔бд.писати 「{svc81_}」 「CREATE TABLE нова(x)」 【】\n'
                   f'» 🜔бд.писати 「{svc81_}」 「INSERT INTO нова(x) VALUES (random())」 【】'], envd)
    dryn81 = both(['--сухо', '-e', f'🜂 【「бд.писати:{DATA}/звіти」】\n'
                   f"» 🜔бд.писати 「{svc81_}」 「INSERT INTO t(x) VALUES (ngr_rowid('t', 0))」 【】"], envd)
    pre81v = subprocess.run([sys.executable, '-c', 'import sys, sqlite3, types; sys.path.insert(0, sys.argv[1]); import nigredo as n\n'
                             'c = sqlite3.connect(":memory:", isolation_level=None)\n'
                             'c.executescript("CREATE TABLE t(x); CREATE VIEW ngr_rowid_0_0 AS SELECT 1")\n'
                             'm = {"запобіжна": False, "сумнів": [], "тригери": set(), "функція": "ngr_rowid_x"}\n'
                             'n._db_guard(c, types.SimpleNamespace(caps=set(), quota_stack=[]), [], m, True, '
                             '"INSERT INTO t(x) VALUES (1)", [])\nprint(sorted(m["тригери"]), c.in_transaction)',
                             str(ROOT / 'interpreter')], capture_output=True, text=True)
    check(resr81[0] == resr81[2] and resr81[1] == resr81[3] == 0
          and 'заборонено: випадковість SQLite (таблиця «u» — рядок отримав би rowid 2⁶³−1' in resr81[0]
          and dry81v[0].stderr == dry81v[1].stderr and dry81v[0].stdout == dry81v[1].stdout
          and dry81v[0].stderr.count('⚠ запит не скомпілювався на нинішній базі') == 1
          and dry81v[0].stderr.count('бд.писати без виконання: authorizer і байткод SQLite перевірено, а rowid') == 1
          and pre81v.stdout == "['ngr_rowid_0_0_'] True\n" and dryn81[0].stdout == dryn81[1].stdout
          and drop81[0].stdout == drop81[1].stdout and drop81[0].stdout.startswith('бд.писати: кількість «?»')
          and drop81[0].stdout.endswith('\n0\n') and 'дозволен' not in drop81[0].stdout
          and dryn81[0].returncode == dryn81[1].returncode != 0
          and 'бд.писати: заборонено: службова функція інтерпретатора' in dryn81[0].stdout + dryn81[0].stderr,
          'SQLite: попередній прохід, тригери й запит — в одній транзакції запису (інший процес не змінить схеми між ними); '
          'назви тимчасових тригерів — не з бази; --сухо: «не скомпілювався», rowid без виконання і ngr_rowid — '
          '«заборонено» (огляд 0.8.1в)',
          str(resr81) + dry81v[0].stderr + dry81v[1].stderr + pre81v.stdout + pre81v.stderr + dryn81[0].stdout
          + dryn81[0].stderr + drop81[0].stdout + drop81[0].stderr + drop81[1].stdout)
    # огляд 0.8.1г (Новачок, Оркестратор): ngr_rowid у DEFAULT стовпця authorizer не бачить (схему SQLite розбирає ще
    # при читанні) — явний rowid 2⁶³−1 ставав «запобіжним», а ngr_rowid('d9', 9) знову розводив виконавців; так само
    # CHECK тіньової таблиці R-Tree з бази, зробленої поза Nigredo: тіньову таблицю пише сам R-Tree, своїми запитами, —
    # у байткоді запиту їх немає (автор). Службова тепер — під випадковою назвою на кожен запит, ngr_rowid — приманка
    svc81g_ = f'{DATA}/звіти/службова81г.db'
    q81g_ = (f'🜂 【「бд.писати:{DATA}/звіти」】\n← п λq ☂ σ 🜔бд.писати 「{svc81g_}」 q 【】 λe e\n' + ''.join(
        f'» п 「{s_}」\n' for s_ in (
            "CREATE TABLE d(a, b DEFAULT (ngr_rowid('d', 0)))", 'INSERT INTO d(rowid, a) VALUES (9223372036854775807, 1)',
            "CREATE TABLE d9(a, b DEFAULT (ngr_rowid('d9', 9)))", 'INSERT INTO d9(a) VALUES (1)',
            "CREATE TABLE x(a CHECK (ngr_rowid('x', 0) IS NULL))", 'INSERT INTO r VALUES (1, 0, 1)', 'INSERT INTO c(a) VALUES (1)', 'INSERT INTO t(x) SELECT sql FROM temp.sqlite_master',
            'INSERT INTO t(x) SELECT name FROM temp.sqlite_master', 'ALTER TABLE t RENAME TO t2',
            'ALTER TABLE t2 RENAME COLUMN x TO y', 'ALTER TABLE t2 RENAME TO t', 'INSERT INTO t(y) VALUES (5)')))
    res81g = []
    for k_, cmd_ in enumerate((NGR_CMD, [sys.executable, str(NGR)])):
        if os.path.exists(svc81g_):
            os.remove(svc81g_)
        with sqlite3.connect(svc81g_) as c_:    # база не з Nigredo: CHECK зі службовою в тіньовій таблиці R-Tree і в
            c_.create_function('ngr_rowid', 2, lambda *a: None)   # таблиці «c», що вже на межі (запобіжна прийшла б раніше)
            c_.executescript("CREATE TABLE t(x); CREATE TABLE c(a CHECK (ngr_rowid('c', 0) IS NULL)); "
                             'INSERT INTO c(rowid, a) VALUES (9223372036854775807, 0); '
                             'CREATE VIRTUAL TABLE r USING rtree(id, x0, x1); PRAGMA writable_schema = ON')
            c_.execute('UPDATE sqlite_master SET sql = \'CREATE TABLE "r_rowid"(rowid INTEGER PRIMARY KEY, nodeno CHECK '
                       "(ngr_rowid(''r'', 0) IS NULL))' WHERE name = 'r_rowid'")
        tp_ = tmp / f'службова81г_{k_}.jsonl'
        res81g.append(subprocess.run([*cmd_, '--слід', str(tp_), '-e', q81g_], capture_output=True, text=True, env=envd))
        res81g.append(subprocess.run([sys.executable, str(NGR), '--перевірити-слід', str(tp_)], capture_output=True,
                                     text=True, env=envd).stdout)
        res81g.append(subprocess.run([*cmd_, '--сухо', '-e', f'🜂 【「бд.писати:{DATA}/звіти」】\n'
                                      f'» 🜔бд.писати 「{svc81g_}」 「INSERT INTO d(a) VALUES (1)」 【】'],
                                     capture_output=True, text=True, env=envd))
        with sqlite3.connect(svc81g_) as c_:
            res81g.append([r[0] for r in c_.execute('SELECT * FROM t')] + [c_.execute('SELECT count(*) FROM d').fetchone()[0]])
    o_ = res81g[0].stdout
    pre81g = subprocess.run([sys.executable, '-c', 'import sys, sqlite3, types; sys.path.insert(0, sys.argv[1]); import nigredo as n\n'
                             'c = sqlite3.connect(":memory:", isolation_level=None)\nc.execute("CREATE TABLE t(x)")\n'
                             'm, why = {"запобіжна": False, "сумнів": [], "тригери": set(), "функція": "ngr_rowid_x"}, []\n'
                             'n._db_guard(c, types.SimpleNamespace(caps=set(), quota_stack=[]), why, m, True, '
                             '"INSERT INTO t(x) VALUES (1)", [])\n'
                             'print(c.execute("SELECT count(*) FROM temp.sqlite_master WHERE sql LIKE \'%ngr_rowid_x(%\'").fetchone()[0])\n'
                             'try:\n    c.execute("SELECT ngr_rowid(\'t\', 0)")\nexcept sqlite3.Error:\n    pass\n'
                             'print(m["запобіжна"], why)\n'
                             'w, a = n._db_auth(True, types.SimpleNamespace(caps=set(), quota_stack=[]), set(), "ngr_rowid_x")\n'
                             'c.set_authorizer(a)\ntry:\n    c.execute("SELECT ngr_rowid_x(\'t\', 0)")\nexcept sqlite3.Error:\n    pass\n'
                             'print(w)', str(ROOT / 'interpreter')], capture_output=True, text=True)
    check(o_ == res81g[4].stdout and res81g[0].returncode == res81g[4].returncode == 0 and res81g[3] == res81g[7]
          and res81g[3] == [None, 'ngr_rowid_0_0', 5, 0] and o_.count('бд.писати: заборонено: службова функція') == 5
          and 'службові тригери' not in o_ and 'запобіжн' not in o_
          and all('(«заборонено»): 5 ' in v_ and 'запобіжн' not in v_ for v_ in (res81g[1], res81g[5]))
          and res81g[2].stdout == res81g[6].stdout and res81g[2].returncode == res81g[6].returncode != 0
          and 'бд.писати: заборонено: службова функція' in res81g[2].stdout + res81g[2].stderr
          and pre81g.stdout == '1\nFalse {0}\n{0}\n'.format(['службова функція інтерпретатора (ngr_rowid) — її кличуть лише '
                                                           'його тимчасові тригери']),
          'SQLite: службова функція — під випадковою назвою на кожен запит; ngr_rowid у DEFAULT стовпця, у CHECK таблиці на '
          'межі й тіньової таблиці R-Tree — «заборонено», не «запобіжна», однаково обома; текст схеми temp програма не читає '
          '(з огляду 0.8.1д — NULL), ALTER TABLE працює (огляд 0.8.1г)',
          o_ + res81g[0].stderr + res81g[1] + res81g[4].stdout + str(res81g[3]) + str(res81g[7]) + res81g[2].stdout
          + res81g[2].stderr + res81g[6].stdout + pre81g.stdout + pre81g.stderr)
    # огляд 0.8.1д (Н-1 Аудитора й Оркестратора): sqlite_stmt — перелік підготовлених запитів зʼєднання з їхнім текстом;
    # в еталона там і кеш Python з тимчасовими тригерами (назва службової — 128 біт випадковості без «жереб»), в Атанора
    # — ні: біти без «жереб» і розбіжність виконавців. Віртуальні таблиці тепер — перелік дозволених: json_each, json_tree
    # і таблиці самої бази (dbstat — теж «заборонено», а таблиця бази з назвою dbstat — таблиця); і під квотою, і в --сухо
    vt81д_ = f'{DATA}/звіти/віртуальні81д.db'
    bit81д_ = ("INSERT INTO v(s) SELECT 1 FROM sqlite_stmt WHERE sql LIKE 'CREATE TEMP TRIGGER%' AND instr(sql, "
               "'BEGIN SELECT ngr_rowid_') > 0 AND substr(sql, instr(sql, 'BEGIN SELECT ngr_rowid_') + 23, 1) < '8'")
    head81д_ = f'← п λq ☂ σ 🜔бд.писати 「{vt81д_}」 q 【】 λe e\n← ч λq ☂ σ 🜔бд.читати 「{vt81д_}」 q 【】 λe e\n'
    q81д_ = (f'🜂 【「бд.писати:{DATA}/звіти」 「бд.читати:{DATA}/звіти」】\n' + head81д_ + ''.join(
        f'» п 「{s_}」\n' for s_ in ('CREATE TABLE v(s)', *[bit81д_] * 6, 'INSERT INTO v(s) SELECT sql FROM sqlite_stmt',
                                     'INSERT INTO v(s) SELECT count(*) FROM sqlite_stmt')) + ''.join(
        f'» ч 「{s_}」\n' for s_ in ('SELECT sql FROM sqlite_stmt', 'SELECT count(*) AS n FROM Sqlite_Stmt',
                                     'SELECT count(*) AS n FROM dbstat'))
        + "» п 「INSERT INTO v(s) SELECT name FROM dbstat」\n» ч 「SELECT value FROM json_each('[1,2]')」\n" + ''.join(
        f'» п 「{s_}」\n' for s_ in ("INSERT INTO v(s) SELECT key FROM json_tree('{\"a\":1}')", 'CREATE TABLE dbstat(x)',
                                     'INSERT INTO dbstat(x) VALUES (7)'))
        + '» ч 「SELECT x FROM dbstat」\n» ч 「SELECT count(*) AS n FROM v」')
    qk81д_ = (f'🜂 【「бд.писати:{DATA}/звіти≤1」 「бд.читати:{DATA}/звіти≤1」】\n' + head81д_
              + '» п 「INSERT INTO v(s) VALUES (1)」\n» ч 「SELECT count(*) AS n FROM v」\n' + ''.join(
                  f'» п 「{s_}」\n' for s_ in ('INSERT INTO v(s) SELECT sql FROM sqlite_stmt', bit81д_)) + ''.join(
                  f'» ч 「{s_}」\n' for s_ in ('SELECT sql FROM sqlite_stmt', 'SELECT count(*) AS n FROM sqlite_stmt'))
              + '» п 「INSERT INTO v(s) VALUES (2)」\n» ч 「SELECT count(*) AS n FROM v」')
    res81д = []
    for k_, cmd_ in enumerate((NGR_CMD, [sys.executable, str(NGR)])):
        for j_ in range(2):          # двічі: біти Аудитора — ті самі в кожному запуску й в обох виконавців
            if os.path.exists(vt81д_):
                os.remove(vt81д_)
            tp_ = tmp / f'віртуальні81д_{k_}_{j_}.jsonl'
            res81д.append(subprocess.run([*cmd_, '--слід', str(tp_), '-e', q81д_], capture_output=True, text=True, env=envd))
            res81д.append(subprocess.run([sys.executable, str(NGR), '--перевірити-слід', str(tp_)], capture_output=True,
                                         text=True, env=envd).stdout)
        res81д.append(subprocess.run([*cmd_, '-e', qk81д_], capture_output=True, text=True, env=envd))
        os.remove(vt81д_)
        with sqlite3.connect(vt81д_) as c_:
            c_.execute('CREATE TABLE v(s)')
        res81д.append(subprocess.run([*cmd_, '--сухо', '-e', q81д_], capture_output=True, text=True, env=envd))
        os.remove(vt81д_)            # індекс з назвою модуля — не таблиця: модуль лишається модулем; VIEW — таблиця бази
        res81д.append(subprocess.run([*cmd_, '-e', f'🜂 【「бд.писати:{DATA}/звіти」 「бд.читати:{DATA}/звіти」】\n' + head81д_
                                      + ''.join(f'» п 「{s_}」\n' for s_ in ('CREATE TABLE v(s)', 'CREATE INDEX dbstat ON v(s)'))
                                      + '» ч 「SELECT count(*) AS n FROM dbstat」\n» п 「DROP INDEX dbstat」\n'
                                      '» п 「CREATE VIEW dbstat AS SELECT 5 AS x」\n» ч 「SELECT x FROM dbstat」'],
                                     capture_output=True, text=True, env=envd))
    o_ = res81д[0].stdout
    den81д_ = 'заборонено: віртуальна таблиця SQLite «{}» — програмі лише json_each, json_tree і таблиці самої бази'
    dry81д = [r_.stdout + r_.stderr for r_ in (res81д[5], res81д[12])]
    check(all(r_.stdout == o_ for r_ in (res81д[2], res81д[7], res81д[9])) and res81д[0].returncode == 0
          and o_.count('бд.писати: ' + den81д_.format('sqlite_stmt')) == 8 and o_.count(den81д_.format('sqlite_stmt')) == 9
          and o_.count(den81д_.format('Sqlite_Stmt')) == 1 and o_.count(den81д_.format('dbstat')) == 2
          and '【『「value」 1』 『「value」 2』】\n2\n0\n1\n【『「x」 7』】\n【『「n」 2』】\n' in o_
          and all('(«заборонено»): 12 ' in v_ for v_ in (res81д[1], res81д[3], res81д[8], res81д[10]))
          and res81д[4].stdout == res81д[11].stdout and res81д[4].stdout.count(den81д_.format('sqlite_stmt')) == 4
          and res81д[6].stdout == res81д[13].stdout == f'0\n0\nбд.читати: {den81д_.format("dbstat")}\n0\n0\n【『「x」 5』】\n'
          and res81д[4].stdout.count('вичерпано квоту') == 2
          and dry81д[0] == dry81д[1] and dry81д[0].count(den81д_.format('sqlite_stmt')) == 9
          and dry81д[0].count(den81д_.format('dbstat')) == 3,   # третя — INSERT у dbstat: таблицю створила б придушена дія
          'SQLite: віртуальні таблиці — перелік дозволених (json_each, json_tree і таблиці самої бази): sqlite_stmt і '
          'dbstat — «заборонено» в запуску, під квотою й у --сухо; біти Аудитора однакові в кожному запуску й обох '
          'виконавців; таблиця й VIEW з назвою dbstat — таблиці бази, індекс — ні (огляд 0.8.1д)',
          o_ + res81д[0].stderr + '\n---\n' + res81д[7].stdout + str(res81д[1]) + res81д[4].stdout + res81д[4].stderr
          + res81д[6].stdout + res81д[6].stderr + res81д[13].stdout
          + dry81д[0] + '\n---\n' + dry81д[1])
    # огляд 0.8.1д (Н-2 Скептика, Практика, Мовознавця): CHECK таблиці на межі й тіньової таблиці R-Tree з бази, зробленої
    # поза Nigredo, під квотою й у --сухо — «вичерпано квоту» й рядок без позначки (зʼєднання прав без дії — лише на
    # читання, і CHECK SQLite там не бере; тіньові таблиці R-Tree пише сам R-Tree). Тепер — той самий попередній прохід у
    # запуску, квоті й --сухо, з правилом тексту схеми, і з параметрами виклику (Оркестратор: «?» — «не скомпілювався»);
    # у відмові — що службову кличе схема бази, коли в запиті її немає (Практик, Оркестратор, Мовознавець, Новачок);
    # бд.читати на базі з R-Tree — не «заборонено: INSERT» (Новачок)
    f81д_, r81д_, rc81д_ = (f'{DATA}/звіти/{n_}81д.db' for n_ in ('чужа', 'дерево', 'дерево_чисте'))

    def foreign81д():
        for f_ in (f81д_, r81д_, rc81д_):
            if os.path.exists(f_):
                os.remove(f_)
        with sqlite3.connect(f81д_) as c_:   # база не з Nigredo, як в огляді 0.8.1г; k — CHECK на межі без пастки
            c_.create_function('ngr_rowid', 2, lambda *a: None)
            c_.executescript("CREATE TABLE t(x); CREATE TABLE c(a CHECK (ngr_rowid('c', 0) IS NULL)); "
                             "CREATE TABLE d(a, b DEFAULT (ngr_rowid('d', 0))); CREATE TABLE k(a CHECK (a IS NOT NULL)); "
                             'INSERT INTO c(rowid, a) VALUES (9223372036854775807, 0); '
                             'INSERT INTO k(rowid, a) VALUES (9223372036854775807, 0)')
        for f_, trap_ in ((r81д_, True), (rc81д_, False)):
            with sqlite3.connect(f_) as c_:
                c_.executescript('CREATE TABLE t(x); CREATE VIRTUAL TABLE r USING rtree(id, x0, x1)')
                if trap_:
                    c_.execute('PRAGMA writable_schema = ON')
                    c_.execute('UPDATE sqlite_master SET sql = \'CREATE TABLE "r_rowid"(rowid INTEGER PRIMARY KEY, nodeno '
                               "CHECK (ngr_rowid(''r'', 0) IS NULL))' WHERE name = 'r_rowid'")
    body81д_ = ('← п λq ☂ σ 🜔бд.писати 「' + f81д_ + '」 q 【】 λe e\n' + ''.join(f'» п 「{s_}」\n' for s_ in (
        'INSERT INTO t(x) VALUES (1)', 'INSERT INTO c(a) VALUES (1)', 'INSERT INTO d(a, b) VALUES (1, 2)',
        "INSERT INTO c(a) VALUES (NGR_ROWID('c', 1))", 'INSERT INTO k(a) VALUES (1)'))
        + f'» ☂ σ 🜔бд.писати 「{f81д_}」 「INSERT INTO t(x) VALUES (random() + ?)」 【1】 λe e\n'
        + f'» ☂ σ 🜔бд.писати 「{f81д_}」 「INSERT INTO t(x) VALUES (?)」 【2】 λe e\n'
        + f'» ☂ σ 🜔бд.писати 「{r81д_}」 「INSERT INTO r VALUES (1, 0, 1)」 【】 λe e\n'
        + f'» ☂ σ 🜔бд.писати 「{rc81д_}」 「INSERT INTO r VALUES (1, 0, 1)」 【】 λe e\n'
        + f'» ☂ σ 🜔бд.читати 「{r81д_}」 「SELECT count(*) AS n FROM r」 【】 λe e\n'
        + f'» ☂ σ 🜔бд.читати 「{rc81д_}」 「SELECT count(*) AS n FROM r」 【】 λe e')
    res81дч = []
    for k_, cmd_ in enumerate((NGR_CMD, [sys.executable, str(NGR)])):
        for mode_, seal_ in (('запуск', ''), ('квота', '≤1'), ('сухо', '')):
            foreign81д()
            before_ = pathlib.Path(r81д_).read_bytes()
            tp_ = tmp / f'чужа81д_{k_}_{mode_}.jsonl'
            res81дч.append(subprocess.run(
                [*cmd_, '--слід', str(tp_), *(['--сухо'] if mode_ == 'сухо' else []), '-e',
                 f'🜂 【「бд.писати:{DATA}/звіти{seal_}」 「бд.читати:{DATA}/звіти」】\n' + body81д_],
                capture_output=True, text=True, env=envd))
            res81дч.append(subprocess.run([sys.executable, str(NGR), '--перевірити-слід', str(tp_)],
                                          capture_output=True, text=True, env=envd).stdout)
            res81дч.append(pathlib.Path(r81д_).read_bytes() == before_)
    svc81д_ = 'бд.писати: заборонено: службова функція інтерпретатора (ngr_rowid) — її кличуть лише його тимчасові тригери'
    note81д_ = (svc81д_ + '; у запиті її немає — її кличе схема бази (DEFAULT, CHECK, згенерований стовпець, індекс, '
                'тригер, VIEW чи тіньова таблиця)')
    quota81д_ = f'бд.писати: вичерпано квоту (печатка: «бд.писати:{DATA}/звіти≤1»)'
    rnd81д_ = 'бд.писати: заборонено: випадковість SQLite (random) без права «жереб» (з квотою «жереб≤N» — лише 🜔жереб)'
    out81д = [r_.stdout.splitlines() for r_ in res81дч[0::3]]
    run81д, quota81д, dry81дч = out81д[0], out81д[1], out81д[2]
    check(out81д[:3] == out81д[3:] and all(res81дч[2::3]) and run81д[:4] == ['1', note81д_, note81д_, svc81д_]
          and run81д[4].startswith('бд.писати: запобіжна відмова (так у самій базі')
          and run81д[5] == rnd81д_     # той самий текст random(), що й під квотою та в --сухо (огляд 0.8.1е)
          and run81д[6:] == ['1', note81д_, '3', '【『「n」 0』】', '【『「n」 1』】']   # 3 — і тіньові таблиці R-Tree
          and quota81д == ['1', note81д_, note81д_, svc81д_, quota81д_, rnd81д_, quota81д_, note81д_, quota81д_,
                           '【『「n」 0』】', '【『「n」 0』】']
          and dry81дч == ['0', note81д_, note81д_, svc81д_, '0', rnd81д_, '0', note81д_, '0', '【『「n」 0』】', '【『「n」 0』】']
          and 'не скомпілювався' not in res81дч[6].stderr and 'INSERT INTO t(x) VALUES (?)' in res81дч[6].stderr
          and 'INSERT INTO k(a) VALUES (1)' in res81дч[6].stderr
          and all('(«заборонено»): 5 ' in v_ and 'у запиті її немає — її кличе схема бази' in v_
                  for v_ in (res81дч[1], res81дч[4], res81дч[10], res81дч[13])),
          'SQLite: CHECK таблиці на межі й тіньової таблиці R-Tree з чужої бази — «заборонено: службова функція» ще до '
          'виконання в запуску, під квотою й у --сухо (той самий попередній прохід; файл R-Tree незмінний), «у запиті її '
          'немає — її кличе схема бази»; права без дії — з параметрами (random() з «?» — «заборонено»); бд.читати з R-Tree '
          '— ✓ (огляд 0.8.1д)',
          '\n---\n'.join(r_.stdout + r_.stderr for r_ in res81дч[0::3]) + str(res81дч[2::3]) + res81дч[1] + res81дч[4])
    # огляд 0.8.1д (Скептик, Практик, Мовознавець): ідіома FAQ SQLite зі sqlite_temp_master давала «заборонено: службові
    # тригери інтерпретатора» — і в бд.читати, де їх немає; тепер стовпець sql схеми temp для програми — NULL; ALTER TABLE
    # працює, як і досі
    faq81д_ = f'{DATA}/звіти/ідіома81д.db'
    faq_ = "SELECT * FROM sqlite_master UNION ALL SELECT * FROM sqlite_temp_master"
    qf81д_ = (f'🜂 【「бд.писати:{DATA}/звіти」 「бд.читати:{DATA}/звіти」】\n'
              f'← п λq ☂ σ 🜔бд.писати 「{faq81д_}」 q 【】 λe e\n← ч λq ☂ σ 🜔бд.читати 「{faq81д_}」 q 【】 λe e\n'
              '» п 「CREATE TABLE v(s)」\n'
              f"» ч 「SELECT name FROM ({faq_}) WHERE type = 'table' ORDER BY name」\n" + ''.join(f'» п 「{s_}」\n' for s_ in (
                  f"INSERT INTO v(s) SELECT name FROM ({faq_}) WHERE type = 'table'",
                  'INSERT INTO v(s) SELECT count(*) FROM temp.sqlite_master WHERE sql IS NULL',
                  'INSERT INTO v(s) SELECT count(*) FROM sqlite_temp_master WHERE sql IS NOT NULL',
                  'CREATE TABLE a(x, y)', 'ALTER TABLE a RENAME TO b', 'ALTER TABLE b RENAME COLUMN x TO z',
                  'ALTER TABLE b DROP COLUMN y', 'INSERT INTO b(z) VALUES (1)'))
              + '» ч 「SELECT s FROM v」\n» ч 「SELECT z FROM b」')
    resf81д = []
    for k_, cmd_ in enumerate((NGR_CMD, [sys.executable, str(NGR)])):
        if os.path.exists(faq81д_):
            os.remove(faq81д_)
        tp_ = tmp / f'ідіома81д_{k_}.jsonl'
        resf81д.append(subprocess.run([*cmd_, '--слід', str(tp_), '-e', qf81д_], capture_output=True, text=True, env=envd))
        resf81д.append(subprocess.run([sys.executable, str(NGR), '--перевірити-слід', str(tp_)], capture_output=True,
                                      text=True, env=envd).stdout)
    check(resf81д[0].stdout == resf81д[2].stdout == '0\n【『「name」 「v」』】\n1\n1\n1\n0\n0\n0\n0\n1\n'
          '【『「s」 「v」』 『「s」 1』 『「s」 0』】\n【『「z」 1』】\n'
          and all('спроб поза правами немає' in v_ for v_ in (resf81д[1], resf81д[3])),
          'SQLite: ідіома FAQ зі sqlite_temp_master — ✓ і в бд.читати, і в бд.писати: стовпець sql схеми temp — NULL, а не '
          '«заборонено»; ALTER TABLE RENAME, RENAME COLUMN, DROP COLUMN працюють (огляд 0.8.1д)',
          resf81д[0].stdout + resf81д[0].stderr + resf81д[1] + resf81д[2].stdout + resf81д[3])
    # огляд 0.8.1е (Н-1 Скептика й автор): перелік дозволених віртуальних таблиць звіряв НАЗВУ, а SQLite розвʼязує пару
    # «схема.назва»: temp.dbstat при справжній таблиці dbstat читав модуль (сторінки файлу), а схемна CREATE VIRTUAL TABLE
    # на модулі не з даних (st USING dbstat, pg USING sqlite_dbpage) читала/писала нутрощі бази під власною назвою. Тепер —
    # за планом (EXPLAIN QUERY PLAN): модуль під назвою таблиці «заборонено» у запуску, під квотою й у --сухо однаково;
    # схемну vtab на небезпечному модулі ловить і authorizer за назвою; справжня таблиця dbstat, R-Tree і json_each — ✓
    vt81е = {n_: f'{DATA}/звіти/{n_}81е.db' for n_ in ('тінь', 'стат', 'пейдж', 'дерево')}

    def foreign81е():
        for f_ in vt81е.values():
            if os.path.exists(f_):
                os.remove(f_)
        with sqlite3.connect(vt81е['тінь']) as c_:
            c_.executescript("CREATE TABLE dbstat(x); INSERT INTO dbstat(x) VALUES (7); CREATE TABLE t(a)")
        with sqlite3.connect(vt81е['стат']) as c_:
            c_.executescript("CREATE TABLE t(a); CREATE VIRTUAL TABLE st USING dbstat")
        with sqlite3.connect(vt81е['пейдж']) as c_:
            c_.executescript("CREATE TABLE t(a); CREATE VIRTUAL TABLE pg USING sqlite_dbpage")
        with sqlite3.connect(vt81е['дерево']) as c_:
            c_.executescript("CREATE VIRTUAL TABLE r USING rtree(id, x0, x1); INSERT INTO r VALUES (1, 0, 1)")

    def rd81е(p, q):
        return f'» ☂ ＋ 「✓ 」 σ 🜔бд.читати 「{p}」 「{q}」 【】 λe ＋ 「✗ 」 e\n'

    def wr81е(p, q):
        return f'» ☂ ＋ 「✓ 」 σ 🜔бд.писати 「{p}」 「{q}」 【】 λe ＋ 「✗ 」 e\n'
    body81е = (wr81е(vt81е['тінь'], 'INSERT INTO t(a) VALUES (1)')                       # 0: квоту ≤1 вичерпує
               + wr81е(vt81е['тінь'], 'INSERT INTO t SELECT pageno FROM temp.dbstat')    # 1: модуль у підзапиті — заборонено
               + wr81е(vt81е['пейдж'], 'UPDATE pg SET data = data WHERE pgno = 1')        # 2: сліпий запис у pg — заборонено
               + rd81е(vt81е['тінь'], 'SELECT count(*) AS n FROM temp.dbstat')            # 3: модуль під назвою таблиці
               + rd81е(vt81е['тінь'], 'SELECT x FROM dbstat')                             # 4: справжня таблиця dbstat — ✓
               + rd81е(vt81е['стат'], 'SELECT count(*) AS n FROM st')                     # 5: схемна vtab на dbstat
               + rd81е(vt81е['дерево'], 'SELECT count(*) AS n FROM r')                    # 6: R-Tree — ✓
               + rd81е(vt81е['дерево'], "SELECT value AS v FROM json_each('[5]')"))       # 7: json_each — ✓
    vdbst_ = 'заборонено: віртуальна таблиця SQLite «{}» — програмі лише json_each, json_tree і таблиці самої бази'
    res81е = []
    for k_ in range(2):              # 0 — Атанор, 1 — еталон; бінарник той самий dlopen libsqlite3
        cmd_ = NGR_CMD if k_ == 0 else [sys.executable, str(NGR)]
        for mode_, seal_, dry_ in (('запуск', '', []), ('квота', '≤1', []), ('сухо', '', ['--сухо'])):
            foreign81е()
            bytes_ = {n_: pathlib.Path(p_).read_bytes() for n_, p_ in vt81е.items()}
            tp_ = tmp / f'вт81е_{k_}_{mode_}.jsonl'
            res81е.append(subprocess.run(
                [*cmd_, '--слід', str(tp_), *dry_, '-e',
                 f'🜂 【「бд.писати:{DATA}/звіти{seal_}」 「бд.читати:{DATA}/звіти」】\n' + body81е],
                capture_output=True, text=True, env=envd))
            res81е.append(all(pathlib.Path(p_).read_bytes() == bytes_[n_] for n_, p_ in vt81е.items()) if dry_ else None)
            res81е.append(subprocess.run([sys.executable, str(NGR), '--перевірити-слід', str(tp_)], capture_output=True,
                                         text=True, env=envd).stdout)
    out81е = [res81е[i_].stdout.splitlines() for i_ in range(0, len(res81е), 3)]   # [Атанор: запуск, квота, сухо; еталон: …]
    run_, quota_, dry_ = out81е[0], out81е[1], out81е[2]
    deny81е = [f'✗ бд.писати: {vdbst_.format("dbstat")}', f'✗ бд.писати: {vdbst_.format("pg")}',
               f'✗ бд.читати: {vdbst_.format("dbstat")}', f'✗ бд.читати: {vdbst_.format("st")}']   # рядки 1,2,3,5 (☂ дає ✗)
    check(out81е[:3] == out81е[3:]                        # Атанор = еталон у всіх трьох режимах
          and [run_[1], run_[2], run_[3], run_[5]] == deny81е          # модуль і схемна vtab — заборонено
          and [quota_[1], quota_[2], quota_[3], quota_[5]] == deny81е  # так само під вичерпаною квотою (не «вичерпано квоту»)
          and [dry_[1], dry_[2], dry_[3], dry_[5]] == deny81е          # і в --сухо (не «✓ без позначки»)
          and run_[4] == '✓ 【『「x」 7』】' and run_[6] == '✓ 【『「n」 1』】' and run_[7] == '✓ 【『「v」 5』】'
          and run_[0] == '✓ 1' and quota_[0] == '✓ 1'                  # перший запис бере квоту ≤1
          and res81е[1] is None and res81е[7] is True                  # --сухо лишає всі бази байт у байт
          and '(«заборонено»): 4 ' in res81е[2],                       # слід: 4 спроби поза правами (рядки 1,2,3,5)
          'SQLite: модуль під назвою справжньої таблиці (temp.dbstat) і схемна CREATE VIRTUAL TABLE на модулі не з даних '
          '(st USING dbstat, pg USING sqlite_dbpage) — «заборонено: віртуальна таблиця» за планом у запуску, під квотою й '
          'у --сухо однаково (Атанор = еталон); справжня таблиця dbstat, R-Tree і json_each — ✓; --сухо не змінює баз '
          '(огляд 0.8.1е)',
          '\n---\n'.join('\n'.join(o_) for o_ in out81е) + '\n===\n' + res81е[0].stderr + res81е[2])
    # огляд 0.8.1е, побажання. ngr_rowid, яку схема лише ЗГАДУЄ (рядок, коментар, назва стовпця чи таблиці
    # ngr_rowid_журнал), — «лише згадує», а не «кличе» (Скептик, Практик, Мовознавець, Новачок); «у запиті її немає» — за
    # викликом, а не підрядком: рядок 'ngr_rowid' у запиті й назва ngr_rowid_п з пасткою (Новачок); з 「жереб」 без квоти
    # таблиці зі згадкою пишуться (так каже відмова); random() — той самий текст у запуску, під квотою й у --сухо (Аудитор,
    # Новачок)
    m81е_ = f'{DATA}/звіти/згадка81е.db'

    def mention81е():
        if os.path.exists(m81е_):
            os.remove(m81е_)
        with sqlite3.connect(m81е_) as c_:   # база не з Nigredo: згадки поряд із пастками (CHECK кличе службову)
            c_.create_function('ngr_rowid', 2, lambda *a: None)
            c_.executescript("CREATE TABLE t(x); CREATE TABLE журнал(a, b DEFAULT 'ngr_rowid'); "
                             'CREATE TABLE к(a /* ngr_rowid */, b); CREATE TABLE ж(ngr_rowid INTEGER, x); '
                             "CREATE TABLE ngr_rowid_журнал(a); CREATE TABLE c(a CHECK (ngr_rowid('c', 0) IS NULL)); "
                             'CREATE TABLE ngr_rowid_п(a CHECK ("NGR_ROWID"(\'x\', 0) IS NULL))')
    body81еп = ''.join(wr81е(m81е_, q_) for q_ in (
        'INSERT INTO t(x) VALUES (1)', 'INSERT INTO журнал(a) VALUES (1)', 'INSERT INTO к(a) VALUES (1)',
        'INSERT INTO ж(x) VALUES (1)', 'INSERT INTO ngr_rowid_журнал(a) VALUES (1)', "INSERT INTO c(a) VALUES ('ngr_rowid')",
        'INSERT INTO ngr_rowid_п(a) VALUES (1)', 'INSERT INTO t(x) VALUES (random())'))
    res81еп = []
    for k_ in range(2):              # 0 — Атанор, 1 — еталон
        cmd_ = NGR_CMD if k_ == 0 else [sys.executable, str(NGR)]
        for mode_, seal_, dry_ in (('запуск', '」', []), ('квота', '≤1」', []), ('сухо', '」', ['--сухо']),
                                   ('жереб', '」 「жереб」', [])):
            mention81е()
            before_ = pathlib.Path(m81е_).read_bytes()
            tp_ = tmp / f'згадка81е_{k_}_{mode_}.jsonl'
            res81еп.append(subprocess.run([*cmd_, '--слід', str(tp_), *dry_, '-e',
                                           f'🜂 【「бд.писати:{DATA}/звіти{seal_}】\n' + body81еп],
                                          capture_output=True, text=True, env=envd))
            res81еп.append(pathlib.Path(m81е_).read_bytes() == before_)
            res81еп.append(subprocess.run([sys.executable, str(NGR), '--перевірити-слід', str(tp_)], capture_output=True,
                                          text=True, env=envd).stdout)
    o81еп = [r_.stdout.splitlines() for r_ in res81еп[0::3]]   # [Атанор: запуск, квота, сухо, жереб; еталон: …]
    svc81е_ = ('✗ бд.писати: заборонено: службова функція інтерпретатора (ngr_rowid) — її кличуть лише його тимчасові '
               'тригери; у запиті її немає — ')
    deny81еп = [svc81е_ + 'схема бази її не кличе, а лише згадує (назва таблиці чи стовпця, рядок, коментар); таблицю з '
                'такою схемою бд.писати пише лише з правом «жереб» без квоти'] * 4 + [
        svc81е_ + 'її кличе схема бази (DEFAULT, CHECK, згенерований стовпець, індекс, тригер, VIEW чи тіньова таблиця)'] * 2 + [
        '✗ бд.писати: заборонено: випадковість SQLite (random) без права «жереб» (з квотою «жереб≤N» — лише 🜔жереб)']
    check(o81еп[:4] == o81еп[4:]                                      # Атанор = еталон у всіх чотирьох режимах
          and o81еп[0] == o81еп[1] == ['✓ 1'] + deny81еп and o81еп[2][:8] == ['✓ 0'] + deny81еп
          and o81еп[3][:5] + o81еп[3][7:8] == ['✓ 1'] * 6              # з 「жереб」: згадки пишуться, random — теж
          and all(l_.startswith('✗ бд.писати: ') for l_ in o81еп[3][5:7])   # пастки — ні
          and res81еп[7] and res81еп[19]                               # --сухо лишає базу байт у байт
          and all('(«заборонено»): 7 ' in res81еп[i_] for i_ in (2, 5, 14, 17))
          and all('спроб поза правами немає' in res81еп[i_] for i_ in (11, 23)),   # з 「жереб」 спроб немає
          'SQLite: ngr_rowid, яку схема лише згадує (рядок, коментар, назва стовпця чи таблиці ngr_rowid_журнал), — «лише '
          'згадує», а не «кличе»; «у запиті її немає» — за викликом, а не підрядком; з 「жереб」 без квоти такі таблиці '
          'пишуться; random() — той самий текст у запуску, під квотою й у --сухо (Атанор = еталон; огляд 0.8.1е, побажання)',
          '\n---\n'.join('\n'.join(o_) for o_ in o81еп) + '\n===\n' + res81еп[0].stderr + res81еп[2])
    seal81 = tmp / 'печатка81'
    (seal81 / 'звіти').mkdir(parents=True, exist_ok=True)
    (seal81 / 'файл.ngr').write_text('🜂 「новий файл」 【「писати:звіти/нова.txt」】\n» 🜔писати 「звіти/нова.txt」 「x」\n',
                                     encoding='utf-8')
    (seal81 / 'тека.ngr').write_text('🜂 「тека, яку створить запис」 【「писати:звіти/нова.txt」】\n'
                                     '» 🜔писати 「звіти/нова.txt/зміст.txt」 「x」\n', encoding='utf-8')
    warn81 = [json.loads(run(['--перевірити', '--json', str(seal81 / f_)], env).stdout)['печатка']['попередження']
              for f_ in ('файл.ngr', 'тека.ngr')]
    rtl81 = run(['--розбір', '-e', '🜂\n» ＋ 「שלום」 「x」\n» ＋ 「мир」 「x」\n» ＋ 「١٢」 「٣٤」'], env).stdout
    check(len(warn81[0]) == 1 and 'рядок 2: файл.писати пише в «звіти/нова.txt» — це сам шлях з печатки' in warn81[0][0]
          and warn81[1] == [] and '\u200e«שלום»\u200e' in rtl81 and '«мир»\u200e' not in rtl81
          and '\u200e«мир»' not in rtl81 and '\u200e«١٢»\u200e' in rtl81,
          'попередження про запис у сам шлях з печатки — і для ще не створеного файлу, а тека, яку створить запис, — без '
          'нього; --розбір: LRM з обох боків тексту справа наліво (огляд 0.8.1, 0.8.1в)', str(warn81) + rtl81)
    # суд 9в (Аудитор): межа сліду між «виклик» і результатом — --перевірити-слід каже про виклик без результату
    lim_prog, lim_tr = '🜂 【「жереб」】\n» 🜔жереб 6\n» 🜔жереб 6\n» 🜔жереб 6', tmp / 'межа9в.jsonl'
    subprocess.run([*NGR_CMD, '--слід', str(lim_tr), '-e', lim_prog], capture_output=True, env=env)
    raw_ = lim_tr.read_bytes()         # межа рахує байти після «початок» і сховище .дані
    full_ = len(raw_) - len(raw_.split(b'\n')[0]) - 1 + pathlib.Path(str(lim_tr) + '.дані').stat().st_size
    lim_note = None
    for size_ in range(full_ - 1, full_ - 900, -9):
        for f_ in (lim_tr, pathlib.Path(str(lim_tr) + '.дані')):
            f_.unlink(missing_ok=True)
        subprocess.run([*NGR_CMD, '--слід', str(lim_tr), '--слід-розмір', str(size_), '-e', lim_prog], capture_output=True, env=env)
        evs_ = [json.loads(x)['подія'] for x in lim_tr.read_text(encoding='utf-8').splitlines()]
        if evs_[-2:] == ['виклик', 'помилка']:
            lim_note = run(['--перевірити-слід', str(lim_tr)], env).stdout
            break
    check(lim_note is not None and '✓' in lim_note and 'останній виклик інструмента — без результату' in lim_note,
          '--перевірити-слід: межа сліду між викликом і результатом — «⚠ останній виклик без результату» (суд 9в)', str(lim_note))
    got = run(['--розбір', '-e', '🜂\n← а ●\n» ¿ а ○ ∅'], env)
    check('а ← так' in got.stdout and 'якщо а то ні інакше ніщо' in got.stdout and '●' not in got.stdout.split('ПЕРЕКЛАД')[-1],
          '--розбір: ● ○ ∅ — словами (так, ні, ніщо), як і гліфи (суд 9в, Аудитор)', got.stdout)
    got = run(['--тести', str(ROOT / 'examples' / 'тести')], env)
    check(got.returncode == 0 and 'тестів пройшли' in got.stdout, 'ngr --тести: тести мовою (examples/тести) — усі пройшли',
          got.stdout + got.stderr)
    td = tmp / 'печатки_тестів'
    td.mkdir(exist_ok=True)
    (td / 'мережа.тест.ngr').write_text('🜂 【「взяти:example.com」】\n🜍 1 λx ＝ x 1\n', encoding='utf-8')
    got = run(['--тести', '--печатка', str(ROOT / 'examples' / 'тести')], env)
    got2 = run(['--тести', '--печатка', str(td)], env)
    check(got.returncode == 0 and '✓' in got.stdout and 'печатка' in got.stdout
          and got2.returncode == 1 and '✗' in got2.stdout and 'бракує' in got2.stdout,
          'ngr --тести --печатка: печатки тестів без запуску, поза дозволами — код 1', got.stdout + got2.stdout + got2.stderr)
    (tmp / 'поганий.тест.ngr').write_text('🜂\n🜍 1 λx ＝ x 2\n', encoding='utf-8')
    got = run(['--тести', str(tmp / 'поганий.тест.ngr')], env)
    check(got.returncode == 1 and '✗' in got.stdout and '0 з 1' in got.stdout, 'ngr --тести: невдалий тест — код 1 і причина', got.stdout)
    # суд 8: --тести — 🜍 під ☂, без 🜍, сумнівна — не «пройшов»; однакові тести не заважають одне одному; тест, що
    # валить розбір, — лише свій ✗; тести з тек запису не беруться
    td = tmp / 'тести8'
    (td / 'звіти').mkdir(parents=True)
    for name_, body in (('а', '» ☂ 🜍 1 λv ＝ v 2 λe 「перехоплено」'), ('б', '※ нічого'), ('в', '🜍 ≈ ● 0.01 λx x'),
                        ('г', '🜍 1 λv ＝ v 1'), ('д', '🜍 1 λv ＝ v 1'), ('е', '» ' + '¬ ' * 3000 + '●')):
        (td / f'{name_}.тест.ngr').write_text(f'🜂 【「оракул」】\n{body}\n', encoding='utf-8')
    (td / 'звіти' / 'підкинутий.тест.ngr').write_text('🜂\n🜍 1 λv ＝ v 1\n', encoding='utf-8')
    th = tmp / 'вл_тести'
    th.mkdir()
    (th / 'дозволи.json').write_text(json.dumps({'дозволено': ['оракул', 'час', f'файл.писати:{td / "звіти"}',
                                                             f'бд.писати:{td / "звіти"}']}, ensure_ascii=False), encoding='utf-8')
    got = run(['--тести', str(td), '--json'], dict(env, NIGREDO_HOME=str(th)))
    js8 = json.loads(got.stdout or '{}')
    st8 = {os.path.basename(r['файл']).split('.')[0]: r for r in js8.get('тести', [])}
    check(got.returncode == 1 and sorted(st8) == ['а', 'б', 'в', 'г', 'д', 'е'] and js8.get('пройшли') == 2
          and st8['г']['пройшов'] and st8['д']['пройшов'] and 'перехоплено' in st8['а']['помилка']
          and 'жодної перевірки' in st8['б']['помилка'] and 'сумнівній' in st8['в']['помилка'] and st8['е']['код'] == 2
          and len(js8.get('пропущено_з_тек_запису', [])) == 1,
          '--тести (суд 8): ☂ над 🜍, 0 перевірок, сумнівна — не «пройшов»; двійники-тести — обидва ✓; глибокий — свій ✗ '
          '(код 2); з теки запису — пропущено', got.stdout[-1500:] + got.stderr[-500:])
    zv = td / 'звіти'
    got = run(['--сухо', '-e', f'🜂 【「час」 「писати:{zv}」】\n← т0 🜔час\n🜔писати 「{zv}/a.txt」 「x」\n← т1 🜔час\n'
               f'» ¿ › × ◷ т0 т1 86400 1 「довго」 「швидко」'], dict(env, NIGREDO_HOME=str(th)))
    check('рішення програми залежали від невідомих' in got.stdout + got.stderr, '--сухо: час після придушеної дії — невідомий, рішення — ⚠',
          got.stdout + got.stderr)
    got = run(['-e', f'🜂 【「бд.писати:{zv}」】\n» 🜔бд.писати 「{zv}/б.db」 「CREATE TABLE t(x)」 【】\n'
               f'» ☂ 🜔бд.писати 「{zv}/б.db」 「CREATE TRIGGER м AFTER INSERT ON t BEGIN SELECT load_extension(\'x\'); END」 【】 λe e'],
              dict(env, NIGREDO_HOME=str(th)))
    check('load_extension заборонено' in got.stdout, 'SQLite: тригер із load_extension — відмова при створенні', got.stdout + got.stderr)
    got = run(['-e', '🜂\n» ' + '【' * 1500 + '】' * 1500], env)
    js = json.loads(run(['--печатка', '--json', '-e', '🜂\n» ' + '¬ ' * 5000 + '●'], env).stdout or '{}')
    check(got.returncode == 2 and 'глибше за 1000' in got.stderr and 'глибше за 1000' in js.get('помилка_розбору', ''),
          'вкладеність понад 1000 — помилка до запуску (код 2), --печатка --json — валідний JSON', got.stderr[-300:])
    # суд 8: ✓ — 「…」 S, межі, дата; ν — лише 0–9; ⌗ без -0.00; ϵ — підказка; давнє значення після «могло впасти»
    got = run(['-e', '🜂\n∀ 【【『「a」 1 「b」 「т」』 『「a」 「ціле」 「…」 「ціле」』】 【3 「число:5..1」】 【¯3 「число:¯5..5」】 '
               '【● 「будь-що:0..5」】 【「2026-10-16T23:59」 「дата」】 【5 「число:..Infinity」】】 λp » ☂ ＋ 「ок 」 Δ ✓ §p 0 §p 1 '
               'λe ¿ ∋ e 「навпаки」 「✗навпаки」 「✗」\n∀ 【「1٣」 「৪2」 「1_000」 「¯3」】 λx » ☂ ν x λe 「не число」\n» ⌗ ¯0.004 2'], env)
    check(got.stdout == '✗\n✗навпаки\nок -3\n✗\n✗\n✗\nне число\nне число\nне число\n-3\n0.00\n',
          '✓ 「…」 S і межі (навпаки, ¯, нескінченні, не для типу), дата без часу; ν — лише 0–9; ⌗ — без «-0.00»',
          got.stdout + got.stderr)
    got = run(['--кроки', '30000', '-e', '🜂\n← схема δ ＋ 「{」 ＋ ⁀ μ … 0 999 λi 〔"п{i}?": "ціле"〕 「,」 「}」\n'
               '← дані μ … 0 999 λi 『』\n» ρ ✓ дані 【схема】'], env)
    check(got.returncode == 1 and 'кроків' in got.stderr, '✓: робота (n полів × n записів) — кроки', got.stdout + got.stderr)
    got = run(['-e', '🜂\n» ϵ 1'], env)
    check('може, ε' in got.stderr, 'ϵ — підказка ε (грецький двійник гліфа)', got.stderr)
    got = run(['--зерно', '1', '-e', '🜂 【「оракул」】\n← так 『「в」 「так」』\n← в 🜔оракул 「чи сірка горить?」\n'
               '← т ◷ ¿ в 「2026-10-01」 「не дата」 0\n» ± так\n» ρ ⚗ 【так】 0.95'], env)
    check(got.stdout.split('\n')[:2] == ['0.64', '0'],
          'канал завершення: давнє значення, прочитане після «могло впасти — не впало», не впевненіше', got.stdout + got.stderr)
    import time as _t
    t0 = _t.monotonic()
    got = run(['--зерно', '1', '-e', '🜂 【「оракул」】\n← xs μ …1 20000 λi i\n← в 🜔оракул 「чи сірка горить?」\n'
               '← т ◷ ¿ в 「2026-10-01」 「не дата」 0\n» ∫ …0 1999 λi § xs i'], env)
    check(got.stdout == '2001000\n' and _t.monotonic() - t0 < 10,
          'канал завершення: обмежене давнє значення копіюється раз (не на кожне читання — було 30 с)',
          f'{_t.monotonic() - t0:.1f} с ' + got.stdout + got.stderr)
    # контракти даних ✓
    got = run(['-e', '🜂\n» ✓ 『「a」 1 「b」 「x」』 『「a」 「ціле」 「…」 「будь-що」』\n» ✓ ∅ 「рядок?」\n'
               '» ☂ ✓ 【1 「2」 3】 【「число」】 λe e\n» ☂ ✓ 『「a」 1』 『「a」 「число」 「b」 「рядок」』 λe e'], env)
    out_ = got.stdout.split('\n')
    check(out_[0] == '『「a」 1 「b」 「x」』' and out_[1] == '∅' and '[1]: очікувалося число' in out_[2]
          and 'b: бракує поля' in out_[3], '✓: інші поля з 「…」, ∅ для «?», шлях до розбіжності, бракує поля', got.stdout + got.stderr)
    got = run(['-e', f'🜂 【「послати:127.0.0.1:{port}」】\n» ☂ 🜔послати 「http://127.0.0.1:{port}/x」 '
               f'✓ 『「сума」 12 「пароль」 「1」』 『「сума」 「число」』 λe 「не відправлено」'], env)
    check(got.stdout == 'не відправлено\n', '✓ перед послати: зайве поле (пароль) — помилка ДО надсилання', got.stdout)
    got = run(['-e', '🜂 「лише намір」\n» 1'], env)
    check(got.returncode == 0, 'печатка лише з наміром (без 【】) — без дозволів')
    seal = run(['--печатка', str(ROOT / 'examples' / 'ahent.ngr')], env).stdout
    check('права теки: немає' in seal and 'намір (слова автора): 「' in seal and 'необхідно, але не досить' in seal,
          '--печатка: слова автора в 「」, «права теки: немає», «необхідно, але не досить»', seal)
    p = subprocess.Popen([*NGR_CMD, '-e', '🜂 「багато рядків」 【】\n∀ …1 100000 λi » i'],
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    p.stdout.readline()
    p.stdout.close()
    err = p.stderr.read().decode()
    p.wait()
    check(p.returncode != 4 and 'внутрішня' not in err and 'Exception' not in err, 'обірвана труба — тихо, не «вада мови»', err)
    # --слід-розмір рахує записи після «початку» (поле «інтерпретатор» у ньому різне) — межа та сама в обох (суд 9)
    flood = '🜂 「повінь」\n∀ …1 30 λi » i'
    run(['--слід', str(tmp / 'повінь1.jsonl'), '-e', flood], env)
    sizes = [len(x) + 1 for x in (tmp / 'повінь1.jsonl').read_bytes().split(b'\n')[1:-1]]
    got = run(['--слід', str(tmp / 'повінь2.jsonl'), '--слід-розмір', str(sum(sizes[:12]) - 1), '-e', flood], env)
    evs = [json.loads(x)['подія'] for x in (tmp / 'повінь2.jsonl').read_text(encoding='utf-8').splitlines()]
    check(got.returncode == 1 and len(evs) == 14 and evs[-1] == 'помилка' and got.stdout.split() == [str(i) for i in range(1, 11)],
          '--слід-розмір: «початок» не рахується — зупинка рівно після 12-го запису', f'{evs}\n{got.stderr}')
    # суд 9б: --повторити сліду, який зупинила межа сліду (і на результаті дії), — «✓ … там само», а не «вада мови»
    rprog = (f'🜂 【「писати:{DATA}/звіти」 「читати:{DATA}/звіти」】\n∀ …1 6 λi 《 🜔писати ＋ 「{DATA}/звіти/пм_」 ＋ σ i '
             f'「.txt」 ＋ 「номер 」 σ i ¦ » ρ 🜔читати ＋ 「{DATA}/звіти/пм_」 ＋ σ i 「.txt」 》')
    bad_ = []
    for lim_ in range(1500, 4200, 97):
        for k_, cmd_ in enumerate((NGR_CMD, [sys.executable, str(NGR)])):
            tp_ = tmp / f'межа_повтор_{lim_}_{k_}.jsonl'
            subprocess.run([*cmd_, '--слід', str(tp_), '--слід-розмір', str(lim_), '-e', rprog], capture_output=True, env=env)
            rp_ = run(['--повторити', str(tp_)], env)
            if rp_.returncode != 0 or 'вада' in rp_.stderr or 'межа сліду' not in rp_.stderr:
                bad_.append(f'{lim_}/{k_}: {rp_.stderr.strip()[-200:]}')
    check(not bad_, '--повторити сліду, зупиненого --слід-розмір (слід Атанора й еталона), — ✓ там само, без «вада мови»',
          '\n'.join(bad_[:3]))
    for args_ in (['--repl', '--сухо'], ['--сухо', '--repl'], ['--сухо', '--тести', str(ROOT / 'examples' / 'тести')],
                  ['--тести', str(ROOT / 'examples' / 'тести'), '--сухо']):
        got = subprocess.run([*NGR_CMD, *args_], input='{"код": "🜂\\n» 1"}\n', capture_output=True, text=True, env=env)
        check(got.returncode == 2 and 'не поєднується' in got.stderr and got.stdout == '',
              f'{" ".join(a for a in args_ if a.startswith("--"))}: помилка до запуску, а не справжні дії (суд 9б)',
              got.stdout + got.stderr)
    for bad in (['--слід-розмір', 'abc'], ['--кроки', '-5'], ['--зерно', '+-5'], ['--кроки']):
        got = run([*bad, '-e', '» 1'] if len(bad) == 2 else bad, env)
        check(got.returncode == 2 and 'Traceback' not in got.stderr and bad[0] in got.stderr,
              f'криве значення {" ".join(bad)} — помилка, не трасування', got.stderr)
    got = run(['--зерно', '007', '--слід', str(tmp / 'зерно.jsonl'), '-e', '🜂 「зерно」\n» 1'], env)
    head = json.loads((tmp / 'зерно.jsonl').read_text(encoding='utf-8').split('\n')[0])
    check(head['ліміти']['зерно'] == 7 and run(['--перевірити-слід', str(tmp / 'зерно.jsonl')], env).returncode == 0,
          '--зерно 007 — у сліді число 7, слід цілий', str(head.get('ліміти')))
    got = subprocess.run([*NGR_CMD, '-e', '🜂 「а」 【】\n» ⌂', '--', os.fsdecode(b'\xff')],
                         capture_output=True, text=True, env=penv)
    tr = pathf.read_text(encoding='utf-8')
    check(got.returncode == 2 and 'не UTF-8' in got.stderr and 'Traceback' not in got.stderr
          and run(['--перевірити-слід', tr], env).returncode == 0, 'аргумент не UTF-8 — відмова зі слідом', got.stderr)
    mcp = ROOT / 'mcp' / 'nigredo_mcp.py'
    work = tmp / 'робоча'
    work.mkdir()
    vb = subprocess.run([sys.executable, str(mcp)], input=json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
                        'params': {'name': 'nigredo_vidbytok', 'arguments': {}}}) + '\n', capture_output=True, text=True,
                        env=dict(env, NIGREDO_WORKDIR=str(work)))
    vbt = json.loads(vb.stdout.splitlines()[0])['result']['content'][0]['text'] if vb.stdout else ''
    check('sha256' in vbt, 'MCP nigredo_vidbytok — sha256 виконавця, як ngr --відбиток (суд 9б)', vb.stdout[-300:] + vb.stderr[-300:])
    reqs = [{'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'},
            {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/call', 'params': {'name': 'nigredo_vykonaty', 'arguments': {
                'code': '🜂 「теги」 【】\n» ＋ 「звіт ок」 δ 「"\\udb40\\udc49\\u2028"」'}}},
            {'jsonrpc': '2.0', 'id': 3, 'method': 'tools/call', 'params': {'name': 'nigredo_pechatka', 'arguments': {
                'code': '🜂 「а」 【「оракул」】\n» 1'}}}]
    got = subprocess.run([sys.executable, str(mcp)], input=''.join(json.dumps(r) + '\n' for r in reqs),
                         capture_output=True, text=True, env=dict(env, NIGREDO_WORKDIR=str(work)))
    res = {m['id']: m.get('result', {}) for m in map(json.loads, got.stdout.splitlines())}
    desc = next(t['description'] for t in res[1]['tools'] if t['name'] == 'nigredo_pechatka')
    out = [c['text'] for c in res[2]['content']]
    check('необхідно, але не досить' in desc and any('звіт ок⟨U+E0049⟩⟨U+2028⟩' in t for t in out)
          and len(out) >= 3 and any('спроб поза правами немає' in t for t in out)
          and len(res[3]['content']) == 2 and '"в_межах": true' in res[3]['content'][1]['text'],
          'MCP: невидиме — ⟨U+…⟩, окремі блоки, підсумок сліду, печатка з JSON', got.stdout[-800:] + got.stderr)
    trace_name = next(re.search(r'слід: (\S+\.jsonl)', t).group(1) for t in out if t.startswith('слід: '))
    reqs = [{'jsonrpc': '2.0', 'id': 4, 'method': 'tools/call', 'params': {'name': 'nigredo_povtoryty', 'arguments': {
                'path': os.path.basename(trace_name)}}},
            {'jsonrpc': '2.0', 'id': 5, 'method': 'tools/call', 'params': {'name': 'nigredo_povtoryty', 'arguments': {
                'path': '../../x.jsonl'}}},
            {'jsonrpc': '2.0', 'id': 6, 'method': 'tools/call', 'params': {'name': 'nigredo_vykonaty', 'arguments': {
                'code': f'🜂 【「писати:{DATA / "звіти"}」】\n🜔писати 「{DATA / "звіти" / "mcp_сухо.txt"}」 「x」', 'suho': True}}}]
    got = subprocess.run([sys.executable, str(mcp)], input=''.join(json.dumps(r) + '\n' for r in reqs),
                         capture_output=True, text=True, env=dict(env, NIGREDO_WORKDIR=str(work)))
    res = {m['id']: m.get('result', {}) for m in map(json.loads, got.stdout.splitlines())}
    txt = lambda i: '\n'.join(c['text'] for c in res[i]['content'])      # noqa: E731
    (work / 'а.тест.ngr').write_text('🜂\n🜍 ＋ 1 1 λs ＝ s 2\n', encoding='utf-8')
    got_t = subprocess.run([sys.executable, str(mcp)], input=json.dumps({'jsonrpc': '2.0', 'id': 9, 'method': 'tools/call',
                           'params': {'name': 'nigredo_testy', 'arguments': {}}}) + '\n',
                           capture_output=True, text=True, env=dict(env, NIGREDO_WORKDIR=str(work)))
    tres = json.loads(got_t.stdout.splitlines()[0])['result']
    check(not tres.get('isError') and '"пройшли": 1' in tres['content'][0]['text'], 'MCP: nigredo_testy проганяє *.тест.ngr робочої теки',
          got_t.stdout[-400:])
    got_s = subprocess.run([sys.executable, str(mcp)], input=json.dumps({'jsonrpc': '2.0', 'id': 10, 'method': 'tools/call',
                           'params': {'name': 'nigredo_shvalyty', 'arguments': {'code': f'🜂 【「читати:{DATA}」 「писати:{work}」】\n» 1'}}})
                           + '\n',
                           capture_output=True, text=True, env=dict(env, NIGREDO_WORKDIR=str(work)))
    sres = json.loads(got_s.stdout.splitlines()[0])['result']
    stext = sres['content'][0]['text']
    entry_ = stext[stext.find('"для_програм"'):].split('\n')[0]
    check(not sres.get('isError') and 'ВІДБИТОК' in stext and 'ПЕРЕКЛАД' in stext and f'файл.писати:{work}' in entry_
          and 'файл.читати' not in entry_ and 'уже дозволено без схвалення' in stext,
          'MCP: nigredo_shvalyty — відбиток і запис «для_програм» лише з тим, чого бракує (суд 9), без виконання',
          got_s.stdout[-600:])
    check(not res[4].get('isError') and '✓ повтор збігся' in txt(4) and res[5].get('isError')
          and '1 дій не виконано' in txt(6) and not (DATA / 'звіти' / 'mcp_сухо.txt').exists(),
          'MCP: nigredo_povtoryty (лише сліди власника) і nigredo_vykonaty з suho', got.stdout[-800:] + got.stderr)

    # браузер на Nigredo — проти локальної сторінки (печатка — на тестовий хост)
    src = (ROOT / 'браузер' / 'браузер.ngr').read_text(encoding='utf-8').split('\n', 1)[1]
    browser = f'🜂 「браузер (тест)」 【「мережа.взяти:127.0.0.1:{port}」】\n' + src
    base = f'http://127.0.0.1:{port}/сайт/'
    got = run(['-e', browser, '--', base + 'перша.html'], env)
    out = got.stdout
    check(got.returncode == 0 and 'назва: Тест & браузер' in out and '«у лапках»' in out and 'сховане' not in out
          and 'color:red' not in out and 'меню' not in out and 'коментар' not in out and '⟨U+E0049⟩' in out
          and f'[1] посиланням → http://127.0.0.1:{port}/друга?x=1' in out and '[2]велике' in out
          and f'→ {base}друга.html' in out, 'браузер: текст, сутності, посилання, приховане й невидиме', out + got.stderr)
    got = run(['-e', browser, '--', base + 'перша.html', '2'], env)
    check(got.returncode == 0 and 'Ви на другій сторінці' in got.stdout, 'браузер: перехід за посиланням N', got.stdout + got.stderr)
    got = run(['-e', browser, '--', 'https://example.com/'], env)
    check(got.returncode == 1 and 'поза дозволеним' in got.stderr, 'браузер: хост поза печаткою — відмова', got.stderr)
    tbrowser = tmp / 'браузер.ngr'
    tbrowser.write_text(browser, encoding='utf-8')
    call = lambda i, args: {'jsonrpc': '2.0', 'id': i, 'method': 'tools/call',      # noqa: E731
                            'params': {'name': 'nigredo_brauzer', 'arguments': args}}
    reqs = [{'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'}, call(2, {'url': base + 'перша.html'}),
            call(3, {'url': base + 'перша.html', 'link': 2}), call(4, {'url': base, 'search': 'x'}),
            call(5, {'url': 'файл:///etc/passwd'}), call(6, {'url': base, 'link': 0})]
    got = subprocess.run([sys.executable, str(ROOT / 'mcp' / 'nigredo_mcp.py')],
                         input=''.join(json.dumps(r) + '\n' for r in reqs), capture_output=True, text=True,
                         env=dict(env, NIGREDO_WORKDIR=str(tmp / 'робоча'), NIGREDO_BROWSER=str(tbrowser)))
    res = {m['id']: m.get('result', {}) for m in map(json.loads, got.stdout.splitlines())}
    desc = next(t['description'] for t in res[1]['tools'] if t['name'] == 'nigredo_brauzer')
    text = lambda i: '\n'.join(c['text'] for c in res[i].get('content', []))      # noqa: E731
    check(f'127.0.0.1:{port}' in desc and 'УВАГА' not in desc and not res[2]['isError']
          and '[1]посиланням' in text(2) and '«заборонено»' not in text(2) and 'спроб поза правами немає' in text(2)
          and 'Ви на другій сторінці' in text(3)
          and all(res[i]['isError'] and text(i).startswith('✗') for i in (4, 5, 6)),
          'MCP-браузер: сторінка, перехід, слід, відмови на поганих запитах', got.stdout[-1500:] + got.stderr)

    # таблиця типів = виконання (суд 6): жодна комбінація, яку виконання приймає, не відкидається до запуску,
    # і жодна комбінація типів не валить інтерпретатор (код 4)
    import importlib.util
    import io
    import itertools
    os.environ['NIGREDO_HOME'] = str(home)         # той самий ключ сліду, що й у підпроцесів (env)
    spec = importlib.util.spec_from_file_location('nigredo_тест', ROOT / 'interpreter' / 'nigredo.py')
    M = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(M)
    import decimal
    decimal.setcontext(M.DEC_CTX.copy())
    itr = tmp / 'внутрішня.jsonl'                     # код 4: у сліді — внутрішня помилка й останній виклик (суд 7)
    saved_tool = M.TOOLS['час']

    def boom(*a):
        raise RuntimeError('імітована вада')
    M.TOOLS['час'] = saved_tool[:5] + (boom,)
    try:
        import contextlib
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            rc4 = M.main(['--слід', str(itr), '-e', '🜂 【「час」】\n» 🜔час'])
    finally:
        M.TOOLS['час'] = saved_tool
    v4 = run(['--перевірити-слід', str(itr)], env).stdout
    check(rc4 == 4 and 'ВНУТРІШНЯ ПОМИЛКА' in v4 and '"останній_виклик"' in itr.read_text(encoding='utf-8'),
          'код 4: слід називає внутрішню помилку й останній виклик інструмента', v4)
    it = M.Interp(lambda *a, **k: None, out=io.StringIO())
    it.replay = ([{'подія': 'інструмент', 'назва': 'час', 'аргументи': [], 'значення': 'x'}], {'x': '2026'})
    try:
        it.run(M.parse('🜂 【「жереб」】\n» 🜔жереб 6', '.', None, []))
        mism = ''
    except M.NgrError as e:
        mism = e.msg
    check('розійшовся зі слідом' in mism, 'повтор: інший виклик, ніж у сліді, — зупинка з розбіжністю', mism)
    S = {'num': '3', 'dec': '2.5', 'str': '「аб」', 'bool': '●', 'no': '○', 'none': '∅', 'list': '【1 2】',
         'dict': '『「а」 1』', 'fn': 'λx x'}
    alarms, crashes = [], []
    for g in M.TYPE_REQ:
        for combo in itertools.product(S, repeat=M.GLYPHS[g][0]):
            line = '» ' + g + ' ' + ' '.join(S[t] for t in combo)
            if g in '∧∨' and combo[0] == ('no' if g == '∧' else 'bool'):
                continue        # правий бік не обчислюється (як and/or); не-умова там — однаково вада програми
            errs = []
            try:
                prog = M.parse('🜂 「т」 【】\n' + line, None, None, errs)
            except M.StaticError:
                continue
            try:
                M.Interp(lambda *a, **k: None, steps=200000, out=io.StringIO()).run(prog)
                if errs:
                    alarms.append(line)
            except M.NgrError:
                pass
            except Exception as e:      # noqa: BLE001
                crashes.append(f'{line}: {type(e).__name__}')
    check(not alarms and not crashes, 'таблиця типів = виконання: 0 хибних тривог, 0 падінь на всіх комбінаціях типів',
          '\n'.join(alarms[:10] + crashes[:10]))

    # ngr --формат: канонічний текст; той самий вивід програми; повторне форматування нічого не змінює
    messy = tmp / 'неохайна.ngr'
    messy.write_text('🜂   「тест」   【「оракул」】\n※ коментар\n←  x   ＋ 1\n      ２\n» 【 1 2  】   ※ хвіст\n\n\n» x\n'
                     '← f λx 《 ← a × x 2\n   ＋ a 1 》\n» μ 【1\n 2\n 】   ∘f\n', encoding='utf-8')
    fm = run(['--формат', str(messy)], env)
    want = ('🜂 「тест」 【「оракул」】\n※ коментар\n← x ＋ 1\n  2\n» 【1 2】 ※ хвіст\n\n» x\n← f λx 《← a × x 2\n  ＋ a 1》\n'
            '» μ 【1\n    2\n  】 ∘f\n')
    check(fm.returncode == 0 and fm.stdout == want, 'ngr --формат: пробіли, відступи продовження, цифри 0–9, коментарі на місці',
          fm.stdout + fm.stderr)
    fmt_bad = []
    for ex in sorted((ROOT / 'examples').glob('*.ngr')):
        f1 = run(['--формат', str(ex)], env).stdout
        tmpf = ex.parent / f'_формат_{ex.name}'
        try:
            tmpf.write_text(f1, encoding='utf-8')
            f2 = run(['--формат', str(tmpf)], env).stdout
            same = run([str(tmpf)], env).stdout == run([str(ex)], env).stdout
        finally:
            tmpf.unlink()
        if f1 != f2 or not same:
            fmt_bad.append(ex.name)
    check(not fmt_bad, 'ngr --формат на прикладах: той самий вивід програм, повторне форматування — без змін', ', '.join(fmt_bad))

    # ngr --repl: сеанс рядків JSON; імена спільні, частина з помилкою не приймається, межі — на весь сеанс, код — у сліді
    reqs = ['{"код": "🜂 【「жереб」】\\n← x 5"}', '{"код": "← y × x"}', '{"код": "» ＋ x 1"}', '{"код": "← x 1"}',
            '{"код": "÷ 1 － x x"}', '{"код": "🜔читати 「a」"}', 'сміття', '{"код": "🜔жереб 6"}', '{"кінець": true}']
    tpf = tmp / 'repl.шлях'
    rp = subprocess.run([*NGR_CMD, '--repl'], input='\n'.join(reqs) + '\n', capture_output=True, text=True,
                        env=dict(env, NIGREDO_TRACE_PATH_FILE=str(tpf)))
    ans = [json.loads(x) for x in rp.stdout.splitlines()]
    tr_repl = sorted((pathlib.Path(env['NIGREDO_HOME']) / 'сліди').glob('*-repl-*.jsonl'))[-1]
    vr = run(['--перевірити-слід', str(tr_repl)], env)
    codes = [json.loads(x)['текст'] for x in tr_repl.read_text(encoding='utf-8').splitlines() if '"код"' in x]
    check(rp.returncode == 0 and [a_['гаразд'] for a_ in ans] == [True, False, True, False, False, False, False, True]
          and ans[0]['значення'] == '5' and ans[2]['вивід'] == '6\n' and 'перепризначаються' in ans[3]['помилка']
          and 'ділення на нуль' in ans[4]['помилка'] and 'немає в печатці' in ans[5]['помилка']
          and vr.returncode == 0 and 'СЕАНС REPL' in vr.stdout and '» ＋ x 1' in codes,
          'ngr --repl: спільні імена, відхилені частини, печатка на весь сеанс, слід з кодом кожної частини',
          rp.stdout + rp.stderr + vr.stdout)
    # суд 9: перевірка програми на кожну частину; відмова й поганий UTF-8 — у сліді; --слід; провал частини — канал
    # завершення; упала перша частина — сеанс завершено (печатку не змінити)
    def repl(lines, *flags):
        old_ = set((pathlib.Path(env['NIGREDO_HOME']) / 'сліди').glob('*-repl-*.jsonl'))
        p_ = subprocess.run([*NGR_CMD, '--repl', '--тека', str(DATA), *flags], input=b'\n'.join(lines) + b'\n',
                            capture_output=True, env=env)
        # слід саме цього сеансу: назви — за секундою й pid, тож «останній за абеткою» в ту саму секунду —
        # навмання (Атанор, 0.8.1в: два сеанси в одну секунду)
        tr_ = sorted(set((pathlib.Path(env['NIGREDO_HOME']) / 'сліди').glob('*-repl-*.jsonl')) - old_)[-1]
        return p_.returncode, [json.loads(x) for x in p_.stdout.decode().splitlines()], tr_
    j = lambda c: json.dumps({'код': c}, ensure_ascii=False).encode()      # noqa: E731
    rc, ans, tr_ = repl([j('🜂 【「писати:звіти」】'), j('🜔писати 「звіти/repl_м.ngr」 「🜂\\n← f λx ＋ x 1」'),
                         j('⊃ 「звіти/repl_м.ngr」 【「f」】\n» f 1')])
    check(rc == 0 and [a_['гаразд'] for a_ in ans] == [True, True, False] and 'дозволено писати' in ans[2]['помилка'],
          '--repl: модуль із теки запису — відмова, як у файлі (суд 9)', str(ans))
    rc, ans, tr_ = repl([b'\xff\xfe', j('🜂 【「читати:/」】')])
    evs = [json.loads(x)['подія'] for x in tr_.read_text(encoding='utf-8').splitlines()]
    vr3 = run(['--перевірити-слід', str(tr_)], env)
    check(rc == 3 and 'не UTF-8' in ans[0]['помилка'] and evs == ['початок', 'код', 'код', 'відмова']
          and vr3.returncode == 0 and 'відкинуто: ✗ рядок входу — не UTF-8' in vr3.stdout,
          '--repl: поганий UTF-8 і печатка поза власником — у сліді («відмова»), без коду 4', f'{ans} {evs}')
    rc, ans, tr_ = repl([j('🜂 「довіра」\n← p ≈ ● 0.41'), j('🜄 「k」 「до」\n¿ p ☠ 「стоп」 ∅\n🜄 「k」 「після」'),
                         j('» ± 🜃 「k」')])
    check(rc == 0 and ans[1]['гаразд'] is False and ans[2]['вивід'] == '0.41\n',
          '--repl: частина впала за сумнівом — решта сеансу не впевненіша (канал завершення)', str(ans))
    rc, ans, tr_ = repl([j('🜂 【「писати:звіти」】\n☠ 「впала」'), j('🜂 【「читати:.」】\n» 1')])
    check(rc == 1 and len(ans) == 1 and ans[0].get('кінець') is True and 'сеанс завершено' in ans[0]['помилка'],
          '--repl: перша частина (з печаткою) впала — сеанс завершено, другої печатки немає', str(ans))
    own = tmp / 'repl_мій.jsonl'
    rc, ans, tr_ = repl([j('🜂 「а」'), j('» 1')], '--слід', str(own))
    recs = [json.loads(x) for x in own.read_text(encoding='utf-8').splitlines()]
    vr2 = run(['--перевірити-слід', str(own), str(ROOT / 'examples' / 'pryvit.ngr')], env)
    check(rc == 0 and [r_['подія'] for r_ in recs][-3:] == ['вивід', 'значення', 'кінець']
          and vr2.returncode == 1 and 'СЕАНС REPL' in vr2.stdout,
          '--repl --слід ФАЙЛ — копія сліду; --перевірити-слід СЛІД ПРОГРАМА для сеансу — ✗', vr2.stdout + str(recs[-3:]))
    # суд 9б: рядок входу — рівно одне поле; дубль «код», «код»+«кінець», зайве поле, масив — відкинуто й у сліді
    rc, ans, tr_ = repl([j('🜂 「а」'), '{"код": "» 1", "код": "» 2"}'.encode(), '{"код": "» 3", "кінець": true}'.encode(),
                         '{"код": "» 4", "x": 1}'.encode(), '[["код", "» 5"]]'.encode(), j('» 6')])
    recs = [json.loads(x) for x in tr_.read_text(encoding='utf-8').splitlines()]
    bad_lines = [r_['текст'] for r_ in recs if r_.get('подія') == 'код' and r_.get('стан') == 'відкинуто']
    check(rc == 0 and [a_['гаразд'] for a_ in ans] == [True, False, False, False, False, True] and ans[-1]['вивід'] == '6\n'
          and len(bad_lines) == 4 and '» 2' in bad_lines[0] and 'кінець' in bad_lines[1],
          '--repl: дубль «код», «код» з «кінець», зайве поле, масив — відкинуто, сирий рядок у сліді (суд 9б)', str(ans))
    in_seal = DATA / 'звіти' / 'repl_у_печатці.jsonl'
    rc, ans, tr_ = repl([j('🜂 【「писати:звіти」】\n» 1')], '--слід', str(in_seal))
    rc2, ans2, tr2_ = repl([j('🜂\n∀ …1 100000 λi ＋ i 1')], '--кроки', '1000')
    vr4 = run(['--перевірити-слід', str(tr2_)], env)
    check(rc == 3 and not in_seal.exists() and rc2 == 1 and ans2[0].get('рядок') == 1 and 'упало 1' in vr4.stdout,
          '--repl: --слід у теці з печатки — файл не створено; межа кроків — відповідь з «рядок», у підсумку «упало 1» '
          '(суд 9б)', str(ans) + str(ans2) + vr4.stdout)
    # суд 9в (Аудитор): копія сліду в теці бд.* з печатки — програма відкривала її СЛІД.дані як базу й тихо псувала
    in_db = DATA / 'звіти' / 'слід_у_бд9в.jsonl'
    rc, ans, tr_ = repl([j(f'🜂 【「бд.писати:{DATA}/звіти」】\n» 1')], '--слід', str(in_db))
    outs9 = [subprocess.run([*cmd_, '--слід', str(in_db), '-e', f'🜂 【「бд.писати:{DATA}/звіти」】\n» 1'], capture_output=True,
                            text=True, env=envd) for cmd_ in (NGR_CMD, [sys.executable, str(NGR)])]
    check(rc == 3 and 'лежить у теці з печатки' in ans[0].get('помилка', '') and not in_db.exists()
          and not pathlib.Path(str(in_db) + '.дані').exists()
          and all(o9.returncode == 3 and 'лежить у теці' in o9.stderr and o9.stdout == '' for o9 in outs9),
          '--слід у теці бд.* з печатки — відмова до запуску (і в REPL), файлів сліду немає (суд 9в)',
          str(ans) + outs9[0].stderr + outs9[1].stderr)

    # ------------------------------------------------------------------ модулі з git за хешем (spec/пропозиції/модулі_git.md)
    # Тека власника — своя на кожен випадок; «джерела_модулів» — дзеркало на локальному сервері (Mirror): у справжню
    # мережу тести не ходять. Кожна межа — з негативним тестом і контролем.
    msrv = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Mirror)
    threading.Thread(target=msrv.serve_forever, daemon=True).start()
    mbase = f'http://127.0.0.1:{msrv.server_address[1]}/'
    hits = Mirror.hits

    def owner(name, sources=None, extra=None, fixtures=False):
        h_ = tmp / name
        h_.mkdir(exist_ok=True)
        data = {'дозволено': ['оракул'], **({} if sources is None else {'джерела_модулів': sources}), **(extra or {})}
        (h_ / 'дозволи.json').write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
        if fixtures:
            store_fixtures(h_)
        return h_, dict(env, NIGREDO_HOME=str(h_), NIGREDO_TRACE_PATH_FILE=str(tmp / f'{name}.слід'))

    def last(e):
        return pathlib.Path(pathlib.Path(e['NIGREDO_TRACE_PATH_FILE']).read_text(encoding='utf-8'))

    def recs_of(tp):
        return [json.loads(x) for x in tp.read_text(encoding='utf-8').splitlines()]

    def sha(b):
        return hashlib.sha256(b).hexdigest()

    def addr(path, raw):
        return f'{LIB}/{path}#sha256={sha(raw)}'

    def stored(h_):
        return sorted(p_.name for p_ in (h_ / 'модулі').iterdir()) if (h_ / 'модулі').exists() else []
    mp = tmp / 'програми_модулі'
    mp.mkdir()

    def prog(name, text):
        (mp / name).write_text(text, encoding='utf-8')
        return str(mp / name)
    TEKST = (MODS / 'tekst.ngr').read_bytes()
    B = '🜂\n← подвоїти λx × x 2\n'.encode()
    A = (f'🜂 「бібліотека」\n⊃ 「util/b.ngr#sha256={sha(B)}」 【「подвоїти」】\n⊃ 「{addr("tekst.ngr", TEKST)}」 【「слова」】\n'
         '← обидва λx 【подвоїти ρ слова x  ρ слова x】\n').encode()
    Mirror.files = {'tekst.ngr': TEKST, 'lib/util/b.ngr': B, 'lib/a.ngr': A, 'інший.ngr': B, 'з_друком.ngr':
                    (MODS / 'z_drukom.ngr').read_bytes(), 'великий.ngr': b'\xf0\x9f\x9c\x82\n' + b'a' * 1_000_000,
                    'lfs.ngr': b'version https://git-lfs.github.com/spec/v1\noid sha256:' + b'0' * 64 + b'\nsize 10\n'}
    romb = prog('ромб.ngr', f'🜂 「ромб»\n'.replace('»', '」') + f'⊃ 「{addr("lib/a.ngr", A)}」 【「обидва」】\n'
                f'⊃ 「{addr("tekst.ngr", TEKST)}」 【「слова」】\n» обидва 「a b c」\n» слова 「X Y」\n')
    # немає джерела ([] у власника) — код 3 до будь-якого запиту: сервер не отримав нічого; слід — «відмова»
    nh, nenv = owner('власник_без_джерел', [])
    del hits[:]
    got = run(['--отримати', romb], nenv)
    vr_ = run(['--перевірити-слід', str(last(nenv))], nenv).stdout
    check(got.returncode == 3 and 'власник не дозволив модулів з «github.com»' in got.stderr and hits == []
          and vr_.startswith('✓ слід цілий і завершений (відмова)') and stored(nh) == [],
          '--отримати без джерела власника — код 3, 0 запитів до сервера, слід «відмова» (модулі з git, §4.2)',
          got.stderr + str(hits) + vr_)
    # під час запуску й до нього мережі немає взагалі: бракує модуля — код 2 «ще не отримано», сервер не бачить запитів
    mh, menv = owner('власник_модулі', {'github.com': mbase})
    outs_ = [run([*m_, romb], menv) for m_ in ([], ['--печатка'], ['--перевірити'], ['--розбір'], ['--сухо'])]
    js_ = json.loads(run(['--печатка', '--json', romb], menv).stdout)
    jv_ = json.loads(run(['--перевірити', '--json', romb], menv).stdout)
    check(all(o_.returncode == 2 and 'ще не отримано' in o_.stdout + o_.stderr for o_ in outs_) and hits == []
          and [x['адреса'] for x in js_.get('бракує_модулів', [])] == [f'{LIB}/lib/a.ngr', f'{LIB}/tekst.ngr']
          and js_.get('печатка_без_модулів', {}).get('в_межах_власника') is True and len(jv_.get('бракує_модулів', [])) == 2
          and 'ПЕЧАТКА БЕЗ НИХ — верхня межа' in outs_[1].stdout,
          'модуль з мережі, якого немає: запуск, --печатка, --перевірити, --розбір, --сухо — код 2 без мережі; '
          '--печатка --json — «бракує_модулів» (усі за прохід) і «печатка_без_модулів» (§10.2)',
          ''.join(o_.stdout + o_.stderr for o_ in outs_)[:900] + str(hits) + json.dumps(js_, ensure_ascii=False)[:600])
    # успіх: модуль → закріплений відносний + модуль з мережі (ромб); повтор — «уже було», без запитів
    got = run(['--отримати', romb], menv)
    ftr = last(menv)
    vr_, vj_ = run(['--перевірити-слід', str(ftr)], menv), json.loads(run(['--перевірити-слід', str(ftr), '--json'], menv).stdout)
    rp_ = run(['--повторити', str(ftr)], menv)
    want_ = sorted(f'{sha(x)}.ngr' for x in (A, B, TEKST))
    check(got.returncode == 0 and '3 отримано, 0 уже було' in got.stdout and len(hits) == 3 and stored(mh) == want_
          and vr_.returncode == 0 and 'ОТРИМАННЯ МОДУЛІВ: 3 отримано, 0 уже було — жодна програма не виконувалась' in vr_.stdout
          and vj_.get('режим') == 'отримання' and rp_.returncode == 1 and 'слід отримання' in rp_.stderr,
          '--отримати: замикання (закріплений відносний, ромб) — 3 файли у сховищі, 3 запити; слід «отримання» ✓; '
          'такий слід не повторюється', got.stdout + got.stderr + vr_.stdout + str(hits) + str(stored(mh)))
    mt_ = {p_.name: p_.stat().st_mtime_ns for p_ in (mh / 'модулі').iterdir()}
    got = run(['--отримати', romb], menv)
    check(got.returncode == 0 and '0 отримано, 3 уже було' in got.stdout and len(hits) == 3
          and mt_ == {p_.name: p_.stat().st_mtime_ns for p_ in (mh / 'модулі').iterdir()},
          '--отримати вдруге — «уже було», сховище не змінено, жодного запиту', got.stdout + got.stderr + str(hits))
    got = run([romb], menv)
    tr_ = last(menv)
    mods_ = [r_ for r_ in recs_of(tr_) if r_['подія'] == 'модуль']
    data_ = [json.loads(x) for x in pathlib.Path(str(tr_) + '.дані').read_text(encoding='utf-8').splitlines()]
    vr_ = run(['--перевірити-слід', str(tr_), romb], menv).stdout
    check(got.returncode == 0 and got.stdout == '【6 3】\n【「x」 「y」】\n' and len(mods_) == 3
          and sorted(r_['sha256'] for r_ in mods_) == sorted(sha(x) for x in (A, B, TEKST))
          and all(r_['шлях'].startswith(LIB) and r_['файл'] == str(mh / 'модулі' / f'{r_["sha256"]}.ngr') for r_ in mods_)
          and sorted(d_['sha256'] for d_ in data_ if 'модуль' in d_) == sorted(sha(x) for x in (A, B, TEKST))
          and all(d_['модуль'].encode() == {sha(x): x for x in (A, B, TEKST)}[d_['sha256']] for d_ in data_ if 'модуль' in d_)
          and vr_.startswith('✓') and 'модулі: 3 (з мережі: 3, sha256 повністю)' in vr_,
          'запуск: ромб виконано раз (3 записи «модуль» на 3 вмісти), текст кожного модуля з мережі — у СЛІД.дані (§9.2)',
          got.stdout + got.stderr + vr_)
    # --повторити й --перевірити-слід без сховища — з СЛІД.дані; без СЛІД.дані — ✗ з порадою; змінений текст — ✗
    hidden_ = tmp / 'сховище_сховане'
    shutil.move(str(mh / 'модулі'), str(hidden_))
    rp_ = run(['--повторити', str(tr_)], menv)
    vr_ = run(['--перевірити-слід', str(tr_), romb], menv).stdout
    vj_ = json.loads(run(['--перевірити-слід', str(tr_), romb, '--json'], menv).stdout)
    dpath_ = pathlib.Path(str(tr_) + '.дані')
    dtext_ = dpath_.read_text(encoding='utf-8')
    dpath_.rename(str(dpath_) + '.x')
    vr2_ = run(['--перевірити-слід', str(tr_), romb], menv).stdout
    rp2_ = run(['--повторити', str(tr_)], menv)
    dpath_.write_text(dtext_.replace('× x 2', '× x 3'), encoding='utf-8')
    rp3_ = run(['--повторити', str(tr_)], menv)
    vr3_ = run(['--перевірити-слід', str(tr_), romb], menv).stdout
    dpath_.write_text(dtext_, encoding='utf-8')
    pathlib.Path(str(dpath_) + '.x').unlink()
    shutil.move(str(hidden_), str(mh / 'модулі'))
    check(rp_.returncode == 0 and '✓ повтор збігся' in rp_.stderr and rp_.stdout == '【6 3】\n【「x」 「y」】\n'
          and vr_.startswith('✓') and '[текст для звірки — з СЛІД.дані, sha256 збігся]' in vr_ and {m_.get('джерело') for m_ in vj_.get('модулі', [])} == {'СЛІД.дані'}
          and vr2_.startswith('✗') and 'ngr --отримати ПРОГРАМА' in vr2_ and rp2_.returncode == 1
          and rp3_.returncode == 1 and 'текст модуля не збігається' in rp3_.stderr and vr3_.startswith('✗'),
          '--повторити і --перевірити-слід СЛІД ПРОГРАМА без сховища — з СЛІД.дані ✓; без СЛІД.дані — ✗ з порадою '
          '--отримати; змінений текст у СЛІД.дані — ✗ (§9.3)', rp_.stderr + vr_ + vr2_ + rp2_.stderr + rp3_.stderr + vr3_)
    # вміст не збігся — код 3, тривога в сліді, у сховищі нічого (ні запису, ні тимчасового)
    before_ = stored(mh)
    bad_ = prog('підміна.ngr', f'🜂\n⊃ 「{LIB}/інший.ngr#sha256={sha(TEKST)}」 【「слова」】\n» слова 「a」\n')
    store_ = mh / 'модулі' / f'{sha(TEKST)}.ngr'
    store_.chmod(0o600)
    store_.unlink()
    got = run(['--отримати', bad_], menv)
    vr_ = run(['--перевірити-слід', str(last(menv))], menv).stdout
    check(got.returncode == 3 and f'сервер віддав вміст із sha256 {sha(B)}, а програма закріпила {sha(TEKST)}' in got.stderr
          and 'у сховище НЕ покладено' in got.stderr and stored(mh) == sorted(set(before_) - {store_.name})
          and vr_.startswith('✓') and '⚠ вміст не збігся: 1 (можлива підміна)' in vr_ and 'ВМІСТ НЕ ЗБІГСЯ' in vr_,
          '--отримати: сервер віддав інший вміст — код 3, «вміст не збігся» у сліді, у сховищі нічого (§4.4)',
          got.stderr + vr_ + str(stored(mh)))
    store_fixtures(mh)
    # мережа: 404, переадресація, 503, LFS, понад 1 МБ — код 1; не модуль з мережі (друк) — код 2, не покладено
    for name_, code_, wtxt_ in (('нема.ngr', 1, '(404)'), ('переадресація.ngr', 1, 'переадресацію на «http://127.0.0.1:'), ('збій.ngr', 1, 'сервер відповів 503'), ('lfs.ngr', 1, 'вказівник git LFS'),
                                ('великий.ngr', 1, 'понад 1000000 байтів — не модуль'),
                                ('з_друком.ngr', 2, 'але це не модуль з мережі: у модулі')):
        n_ = len(stored(mh))
        got = run(['--отримати', f'{LIB}/{name_}'], menv)
        check(got.returncode == code_ and wtxt_ in got.stderr and len(stored(mh)) == n_
              and not any(x_.startswith('.тимч') for x_ in stored(mh)),
              f'--отримати «{name_}» — код {code_}, «{wtxt_}», у сховищі нічого', got.stdout + got.stderr)
    # строк на весь файл: сервер капає по байту на 0,2 с — зупинено (FETCH_TIME = 1 у підпроцесі з еталоном)
    t0 = time.monotonic()
    got = subprocess.run([sys.executable, '-c', 'import sys; sys.path.insert(0, sys.argv[1]); import nigredo as n\n'
                          'n.FETCH_TIME = 1\nsys.exit(n.main(sys.argv[2:]))', str(ROOT / 'interpreter'),
                          '--отримати', f'{LIB}/капає.ngr'], capture_output=True, text=True, env=menv)
    took = time.monotonic() - t0
    check(got.returncode == 1 and 'не отримано за 1 с' in got.stderr and took < 6,
          f'--отримати: сервер капає по байту — зупинено за строком на весь файл ({took:.1f} с при строку 1 с)', got.stderr)
    # TOFU: адреса без хешу — sha256 того, що віддано зараз, і готовий рядок ⊃; з хешем — «збігся»
    th, tenv = owner('власник_tofu', {'github.com': mbase})
    got = run(['--отримати', f'{LIB}/tekst.ngr'], tenv)
    gj_ = json.loads(run(['--отримати', '--json', f'{LIB}/tekst.ngr'], tenv).stdout)
    check(got.returncode == 0 and f'⊃ 「{addr("tekst.ngr", TEKST)}」 【「слова」】' in got.stdout
          and '⚠ sha256 узято з того, що сервер віддав ЗАРАЗ' in got.stdout and 'імена: слова (1 аргумент(и))' in got.stdout
          and gj_.get('довіра_з_першого_разу') is True and gj_.get('sha256') == sha(TEKST) and stored(th) == [f'{sha(TEKST)}.ngr'],
          '--отримати АДРЕСА без хешу — довіра з першого разу: sha256, імена, готовий рядок ⊃, застереження (§4.6)',
          got.stdout + got.stderr)
    # АДРЕСА#sha256 модуля, що вже у сховищі, а вкладених немає, — без запиту за ним самим, вкладені отримано
    ch_, cenv_ = owner('власник_вкладені', {'github.com': mbase})
    store_fixtures(ch_, [A])
    n_ = len(hits)
    got = run(['--отримати', addr('lib/a.ngr', A)], cenv_)
    check(got.returncode == 0 and stored(ch_) == want_ and len(hits) == n_ + 2 and 'sha256 збігся' not in got.stdout
          and '✓ отримано' in got.stdout and 'нових у сховищі: 2' in got.stdout
          and 'вміст узято зі сховища: чи віддає адреса те саме зараз, не звірено' in got.stdout,
          '--отримати АДРЕСА#sha256: модуль уже у сховищі — по мережі лише вкладені (2 запити); вивід не каже «збігся» '
          'про те, чого не звіряв (суд 10)', got.stdout + got.stderr)
    # проксі зі змінних оточення не діють: отримання йде лише туди, куди веде власник (§4.4)
    xh_, xenv_ = owner('власник_проксі', {'github.com': mbase})
    got = run(['--отримати', f'{LIB}/tekst.ngr'], dict(xenv_, http_proxy='http://127.0.0.1:9/', HTTP_PROXY='http://127.0.0.1:9/',
                                                       no_proxy='', NO_PROXY=''))
    check(got.returncode == 0 and stored(xh_) == [f'{sha(TEKST)}.ngr'], '--отримати не бере проксі зі змінних оточення',
          got.stdout + got.stderr)
    # два паралельні --отримати того самого — один файл на вміст, жодного часткового
    ph, penv2 = owner('власник_паралельно', {'github.com': mbase})
    ps_ = [subprocess.Popen([*NGR_CMD, '--отримати', romb], stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=penv2)
           for _ in range(2)]
    rc_ = [p_.wait(timeout=120) for p_ in ps_]
    for p_ in ps_:
        p_.stdout.close()
        p_.stderr.close()
    check(rc_ == [0, 0] and stored(ph) == want_, 'два паралельні --отримати — один файл на вміст, без часткових (атомарний '
          'rename)', str(rc_) + str(stored(ph)))
    # --з-теки: копія сховища іншого агента (без мережі); клон, де проміжна тека — посилання назовні; тека власника
    zh, zenv = owner('власник_з_теки', [])
    copy_ = tmp / 'копія_сховища'
    shutil.copytree(str(mh / 'модулі'), str(copy_))
    (copy_ / f'{sha(TEKST)}.ngr').write_bytes(TEKST)
    n_ = len(hits)
    got = run(['--отримати', romb, '--з-теки', str(copy_)], zenv)
    clone_, outside_ = tmp / 'клон', tmp / 'поза_клоном'
    clone_.mkdir()
    outside_.mkdir()
    (outside_ / 'a.ngr').write_bytes(A)
    (clone_ / 'lib').symlink_to(outside_)
    zh2, zenv2 = owner('власник_з_теки2', [])
    got2 = run(['--отримати', romb, '--з-теки', str(clone_)], zenv2)
    got3 = run(['--отримати', romb, '--з-теки', str(zh2)], zenv2)
    other_ = tmp / 'інша_версія'
    (other_ / 'lib').mkdir(parents=True)
    (other_ / 'lib' / 'a.ngr').write_bytes(A + b'\n')
    got4 = run(['--отримати', romb, '--з-теки', str(other_)], zenv2)
    check(got.returncode == 0 and stored(zh) == want_ and len(hits) == n_
          and got2.returncode == 1 and 'веде за межі теки' in got2.stderr and got3.returncode == 3
          and 'зачіпає теку власника' in got3.stderr and got4.returncode == 1 and 'але sha256 інший' in got4.stderr
          and stored(zh2) == [], '--з-теки: копія сховища — без мережі й без джерел; посилання з клону назовні — не взято; '
          'тека власника — 3; інша версія — 1 (§4.5)', got.stderr + got2.stderr + got3.stderr + got4.stderr)
    # вимикач власника під час запуску: модуль уже у сховищі, а джерел немає — код 3, «відмова» в сліді (§4.2, б)
    t1_ = prog('текст.ngr', f'🜂 「текст」\n⊃ 「{addr("tekst.ngr", TEKST)}」 【「слова」】\n» слова 「Раз Два」\n')
    sh_, senv = owner('власник_вимкнув', [], fixtures=True)
    got, seal_ = run([t1_], senv), run(['--печатка', t1_], senv)
    ok_ = run([t1_], menv)
    check(got.returncode == 3 and 'модуль з мережі «' in got.stderr and 'власник не дозволив модулів з «github.com»' in got.stderr
          and recs_of(last(senv))[-1]['подія'] == 'відмова' and seal_.returncode == 3 and ok_.returncode == 0
          and ok_.stdout == '【「раз」 「два」】\n', 'джерела_модулів: [] — уже отриманий модуль не запускається (код 3, '
          '«відмова»); з дозволеним джерелом — запускається', got.stderr + seal_.stdout + ok_.stdout + ok_.stderr)
    # «джерела_модулів» лише відомої форми: інакше — помилка читання дозволів (код 3) для будь-якої програми
    for i_, bad_src in enumerate((['gitlab.com'], ['github.com', 'github.com'], {'github.com': 'ftp://x/'},
                                  {'github.com': 'http://u@x/'}, {'github.com': 'http://x/a'}, 'github.com')):
        _, benv = owner(f'власник_кривий_{i_}', bad_src)
        got = run(['-e', '🜂\n» 1'], benv)
        check(got.returncode == 3 and 'джерела_модулів' in got.stderr and got.stdout == '',
              f'«джерела_модулів»: {bad_src!r} — код 3 для будь-якої програми (обома виконавцями)', got.stdout + got.stderr)
    _, genv = owner('власник_github', ['github.com'], fixtures=True)
    got = run([t1_], genv)
    check(got.returncode == 0 and got.stdout == '【「раз」 「два」】\n', '«джерела_модулів»: ["github.com"] — модуль запускається',
          got.stderr)
    # дзеркало у «джерела_модулів» (суд 10 іде з дзеркалом): програму без модулів з мережі Атанор виконує сам, якщо форма
    # проста (http(s)://хост[:порт]/шлях/ з ASCII), незвичну — віддає еталону; вивід той самий
    _, renv = owner('власник_дзеркало', {'github.com': mbase})
    _, uenv = owner('власник_дзеркало_незвичне', {'github.com': 'HTTP://127.0.0.1:80/дзеркало/'})
    got, got2 = run(['-e', '🜂\n» 1'], dict(renv, ATHANOR_NO_FALLBACK='1')), run(['-e', '🜂\n» 1'], uenv)
    check(got.returncode == 0 and got.stdout == '1\n' and got2.returncode == 0 and got2.stdout == '1\n',
          '«джерела_модулів» — дзеркало: програма без модулів з мережі запускається (Атанор просту форму — сам, незвичну '
          '— еталону)', got.stderr + got2.stderr)
    # тека запису власника охоплює сховище (файл.писати:/) — модуль з мережі запускається; локальний у теці запису — 3
    wh, wenv = owner('власник_пише_всюди', {'github.com': mbase}, {'дозволено': ['оракул', f'файл.писати:{tmp}']},
                     fixtures=True)
    (mp / 'лок.ngr').write_text('🜂\n← f λx x\n', encoding='utf-8')
    loc_ = prog('з_локальним.ngr', '🜂\n⊃ 「лок.ngr」 【「f」】\n» f 1\n')
    got, got2 = run([t1_], wenv), run([loc_], wenv)
    check(got.returncode == 0 and got2.returncode == 3 and 'дозволено писати' in got2.stderr,
          'тека запису власника охоплює сховище — модуль з мережі запускається (§5.3); локальний модуль у теці запису — 3',
          got.stderr + got2.stderr)
    # сховище змінено поза ngr: інший вміст, посилання (навіть на правильний вміст), тека, FIFO — код 3, без зависання
    xh, xenv = owner('власник_зіпсоване', {'github.com': mbase})
    (xh / 'модулі').mkdir()
    ent_ = xh / 'модулі' / f'{sha(TEKST)}.ngr'
    ent_.write_bytes(B)
    got = run([t1_], xenv)
    check(got.returncode == 3 and f'не той (вміст має sha256 {sha(B)})' in got.stderr,
          'запис сховища з іншим вмістом — код 3 «сховище змінено поза ngr» (хеш на кожному розборі)', got.stderr)
    got = run(['--отримати', t1_], xenv)
    got2 = run([t1_], xenv)
    check(got.returncode == 0 and 'замінено пошкоджений' in got.stdout + got.stderr and got2.returncode == 0,
          '--отримати замінює пошкоджений запис справжнім', got.stdout + got.stderr + got2.stderr)
    good_ = tmp / 'правильний_поза_сховищем.ngr'
    good_.write_bytes(TEKST)
    ent_.unlink()
    ent_.symlink_to(good_)
    got = run([t1_], xenv)
    ent_.unlink()
    ent_.mkdir()
    got2 = run([t1_], xenv)
    ent_.rmdir()
    os.mkfifo(ent_)
    try:
        got3 = subprocess.run([*NGR_CMD, t1_], capture_output=True, text=True, env=xenv, timeout=30)
    except subprocess.TimeoutExpired:
        got3 = subprocess.CompletedProcess([], 99, '', 'завис на FIFO')
    ent_.unlink()
    alien_ = tmp / 'чужий_файл.txt'                 # запис — посилання на чужий файл: --отримати замінює саме посилання
    alien_.write_bytes('не чіпати'.encode())
    ent_.symlink_to(alien_)
    got5 = run(['--отримати', t1_], xenv)
    check(got5.returncode == 0 and alien_.read_bytes() == 'не чіпати'.encode() and not ent_.is_symlink()
          and ent_.read_bytes() == TEKST, '--отримати замінює запис-посилання, а не пише крізь нього (O_EXCL|O_NOFOLLOW і rename)',
          got5.stdout + got5.stderr)
    ent_.unlink()
    big_ = '🜂\n※ '.encode() + b'x' * 1_000_001
    (xh / 'модулі' / f'{sha(big_)}.ngr').write_bytes(big_)
    got4 = run(['-e', f'🜂\n⊃ 「{LIB}/великий.ngr#sha256={sha(big_)}」 【「x」】\n» 1'], xenv)
    check(all(g_.returncode == 3 and 'не звичайний файл (посилання, тека, пристрій) чи понад 1000000 байтів' in g_.stderr
              for g_ in (got, got2, got3, got4)),
          'запис сховища — посилання (навіть на правильний вміст), тека, FIFO, понад 1 МБ — код 3, без зависання (§5.2)',
          got.stderr + got2.stderr + got3.stderr + got4.stderr)
    # шлях у сховище як локальний модуль — «поза текою програми» (наявне правило), і локальне посилання на запис
    store_fixtures(mh)
    rel_ = os.path.relpath(mh / 'модулі' / f'{sha(TEKST)}.ngr', mp)
    p1_ = prog('до_сховища.ngr', f'🜂\n⊃ 「{rel_}」 【「слова」】\n» 1\n')
    (mp / 'лінк.ngr').symlink_to(mh / 'модулі' / f'{sha(TEKST)}.ngr')
    p2_ = prog('лінк_у_сховище.ngr', '🜂\n⊃ 「лінк.ngr」 【「слова」】\n» 1\n')
    got, got2 = run([p1_], menv), run([p2_], menv)
    check(got.returncode == 2 and 'поза текою програми' in got.stderr and got2.returncode == 2
          and 'поза текою програми' in got2.stderr, 'запис сховища шляхом чи посиланням як локальний модуль — поза текою '
          'програми (2)', got.stderr + got2.stderr)
    # межі розбору: 65 різних модулів, вкладеність 17, разом понад 8 МБ — код 2; рівно на межі — контроль
    lh, lenv = owner('власник_межі', {'github.com': mbase})

    def word(i):
        return 'н' + ''.join(chr(0x430 + int(d_)) for d_ in str(i))
    many_ = [f'🜂\n← {word(i)} {i}\n'.encode() for i in range(65)]
    store_fixtures(lh, many_)
    imp_ = ''.join(f'⊃ 「{addr(f"m{i}.ngr", m_)}」 【「{word(i)}」】\n' for i, m_ in enumerate(many_))
    got = run(['-e', '🜂\n' + imp_ + '» 1'], lenv)
    got2 = run(['-e', '🜂\n' + ''.join(imp_.splitlines(True)[:64]) + f'» ＋ {word(0)} {word(63)}'], lenv)
    chain_ = [b'\xf0\x9f\x9c\x82\n\xe2\x86\x90 f \xce\xbbx x\n']    # 🜂 / ← f λx x
    for k_ in range(16):
        chain_.append(f'🜂\n⊃ 「{addr(f"r{k_}.ngr", chain_[-1])}」 【「f」】\n'.encode())
    store_fixtures(lh, chain_)
    got3 = run(['-e', f'🜂\n⊃ 「{addr("r16.ngr", chain_[-1])}」 【「f」】\n» f 1'], lenv)
    got4 = run(['-e', f'🜂\n⊃ 「{addr("r15.ngr", chain_[-2])}」 【「f」】\n» f 1'], lenv)
    fat_ = [f'🜂\n※ {"x" * 950_000}\n← {word(i)} {i}\n'.encode() for i in range(9)]
    store_fixtures(lh, fat_)
    imp_ = ''.join(f'⊃ 「{addr(f"f{i}.ngr", m_)}」 【「{word(i)}」】\n' for i, m_ in enumerate(fat_))
    got5 = run(['-e', '🜂\n' + imp_ + '» 1'], lenv)
    got6 = run(['-e', '🜂\n' + ''.join(imp_.splitlines(True)[:8]) + '» 1'], lenv)
    check(got.returncode == 2 and 'модулів з мережі понад 64' in got.stderr and got2.stdout == '63\n'
          and got3.returncode == 2 and 'вкладеність модулів з мережі понад 16' in got3.stderr and got4.stdout == '1\n'
          and got5.returncode == 2 and 'модулі з мережі разом понад 8000000 байтів' in got5.stderr and got6.stdout == '1\n',
          'межі розбору: 65 модулів, вкладеність 17, разом понад 8 МБ — код 2; 64, 16, 7,6 МБ — так (§7)',
          got.stderr[-300:] + got2.stderr[-300:] + got3.stderr[-300:] + got4.stderr[-300:] + got5.stderr[-300:] + got6.stderr[-300:])
    # «для_програм»: інший #sha256= — інший відбиток, права зникають
    ah, aenv = owner('власник_схвалив', {'github.com': mbase}, fixtures=True)
    ap1 = prog('схвалена.ngr', f'🜂 【「читати:{DATA}」】\n⊃ 「{addr("tekst.ngr", TEKST)}」 【「слова」】\n» ρ 🜔читати 「продажі.json」\n')
    fp_ = json.loads(run(['--печатка', '--json', ap1], aenv).stdout)['відбиток']
    store_fixtures(ah, [B])
    ap2 = prog('схвалена2.ngr', f'🜂 【「читати:{DATA}」】\n⊃ 「{addr("tekst.ngr", B)}」 【「подвоїти」】\n» ρ 🜔читати 「продажі.json」\n')
    (ah / 'дозволи.json').write_text(json.dumps({'дозволено': ['оракул'], 'для_програм': {fp_: [f'файл.читати:{DATA}']}},
                                                ensure_ascii=False), encoding='utf-8')
    got, got2, appr_ = run([ap1], aenv), run([ap2], aenv), run(['--схвалити', ap1], aenv).stdout
    check(got.returncode == 0 and got2.returncode == 3 and 'ви схвалюєте ТЕКСТ модулів' in appr_ and sha(TEKST) in appr_,
          '«для_програм» схвалює текст модулів: інший #sha256= — інший відбиток, прав немає (3); --схвалити — повні sha256',
          got.stderr + got2.stderr + appr_[-600:])
    # граматика адреси (§2.2, §12.1; 171–176 — усі варіанти): кожна частина — своя помилка, код 2; контроль — та сама
    # адреса без вади запускається
    H_ = sha(TEKST)
    for bad_a, wtxt_ in ((f'github.com/denromvas/ngr-lib@v1.2/tekst.ngr#sha256={H_}', 'гілка чи тег зсуваються'),
                         (f'github.com/denromvas/ngr-lib@4b825dc/tekst.ngr#sha256={H_}', 'скорочений коміт «4b825dc» неоднозначний'),
                         (f'raw.githubusercontent.com/denromvas/ngr-lib/{COMMIT}/tekst.ngr', f'мабуть: 「{LIB}/tekst.ngr」'),
                         (f'GitHub.com/denromvas/ngr-lib@{COMMIT}/tekst.ngr#sha256={H_}', 'поки лише з «github.com/»'),
                         (f'github.com:443/denromvas/ngr-lib@{COMMIT}/tekst.ngr#sha256={H_}', 'поки лише з «github.com/»'),
                         (f'x@github.com/denromvas/ngr-lib@{COMMIT}/tekst.ngr#sha256={H_}', 'поки лише з «github.com/»'),
                         (f'githսb.com/denromvas/ngr-lib@{COMMIT}/tekst.ngr#sha256={H_}', 'поки лише з «github.com/»'),
                         (f'github.com.evil.net/denromvas/ngr-lib@{COMMIT}/tekst.ngr#sha256={H_}', 'поки лише з «github.com/»'),
                         (f'github.com/Denromvas/ngr-lib@{COMMIT}/tekst.ngr#sha256={H_}', 'мабуть: 「github.com/denromvas/ngr-lib@…」'),
                         (f'github.com/denromvas/..@{COMMIT}/tekst.ngr#sha256={H_}', 'власник і репозиторій'),
                         (f'github.com/denromvas/ngr-lib.git@{COMMIT}/tekst.ngr#sha256={H_}', 'власник і репозиторій'),
                         (f'{LIB}/./tekst.ngr#sha256={H_}', 'шлях у репозиторії'),
                         (f'{LIB}/lib//tekst.ngr#sha256={H_}', 'шлях у репозиторії'),
                         (f'{LIB}/%2e%2e/tekst.ngr#sha256={H_}', 'шлях у репозиторії'),
                         (f'{LIB}/lib\\\\tekst.ngr#sha256={H_}', 'шлях у репозиторії'),
                         (f'{LIB}/tekst.ngr?x=1#sha256={H_}', 'шлях у репозиторії'),
                         (f'{LIB}/tekst.ngr/#sha256={H_}', 'шлях у репозиторії'),
                         (f'{LIB}/и\u0306.ngr#sha256={H_}', 'у формі NFC'),
                         (f'{LIB}/tek st.ngr#sha256={H_}', 'шлях у репозиторії'),
                         (f'{LIB}/tekst.ngr#sha256={H_[:63]}', 'модуль з мережі — 「github.com/власник'),
                         ('http://example.com/x.ngr', 'адреса, а не шлях у теці програми')):
        got = run(['-e', f'🜂\n⊃ 「{bad_a}」 【「слова」】\n» слова 「А」'], env)
        check(got.returncode == 2 and wtxt_ in got.stderr, f'адреса «{bad_a[:70]}…» — код 2, «{wtxt_}»', got.stderr)
    for bad_a in (f'{LIB}/te\u200bkst.ngr#sha256={H_}', f'{LIB}/te\u202ekst.ngr#sha256={H_}'):
        got = run(['-e', f'🜂\n⊃ 「{bad_a}」 【「слова」】\n» слова 「А」'], env)
        check(got.returncode == 2 and 'невидим' in got.stderr, 'невидиме чи bidi в адресі — код 2', got.stderr)
    got = run(['-e', f'🜂\n⊃ 「{LIB}/tekst.ngr#sha256={H_}」 【「слова」】\n» слова 「А Б」'], env)
    check(got.returncode == 0 and got.stdout == '【「а」 「б」】\n', 'контроль: правильна адреса запускається', got.stderr)
    got = run(['-e', f'🜂\n⊃ 「{LIB}/tekst.ngr」 【「слова」】\n» 1'], dict(env, NIGREDO_HOME=str(mh)))
    got2 = run(['-e', '🜂\n⊃ 「GitHub.com/a/b@4b825dc/x.ngr」 【「f」】\n» 1'], env)
    check(got.returncode == 2 and 'вміст має бути закріплено' in got.stderr and got2.returncode == 2
          and 'якщо це модуль з мережі — потрібні «@КОМІТ» і «#sha256=…»' in got2.stderr,
          'локальний шлях, схожий на адресу, якого немає, — підказка, як записати модуль з мережі (§2.5)', got.stderr + got2.stderr)
    # замок 1 — кожна дія без інструмента в тілі функції модуля з мережі — код 2 ще до запуску
    for g_, body_ in (('🜁', '🜁 「с」 【】 x'), ('🜄', '🜄 「к」 x'), ('🜃', '🜃 x'), ('≈', '≈ x 0.5'), ('⚗', '⚗ 【x】 0.5'),
                      ('🜍', '🜍 x λv ●'), ('»', '《 ← у λz » z ¦ x 》')):
        m_ = f'🜂\n← f λx {body_}\n'.encode()
        store_fixtures(lh, [m_])
        got = run(['-e', f'🜂\n⊃ 「{addr("дія.ngr", m_)}」 【「f」】\n» f 「a」'], lenv)
        q_ = '「»」' if g_ == '»' else f'«{g_}»'          # «»» не прочитати (огляд 10б)
        check(got.returncode == 2 and f'модуль з мережі лише обчислює — {q_}' in got.stderr and 'заборонено й у функціях' in got.stderr,
              f'замок 1: «{g_}» у функції модуля з мережі — код 2 (§6.2)', got.stderr)
    vg_ = (MODS / 'vgoru.ngr').read_bytes()
    got = run(['-e', f'🜂\n⊃ 「{addr("lib/vgoru.ngr", vg_)}」 【「f」】\n» f 1'], env)
    check(got.returncode == 2 and 'лише вглиб від теки модуля; вище — повною адресою' in got.stderr,
          'закріплений відносний модуль із «..» — помилка (лише вглиб, §2.3)', got.stderr)
    # замок 2 — λ того, хто кличе, викликана в модулі з мережі, і замикання, яке модуль повернув: дії — «заборонено»
    zz_ = f'⊃ 「{LIB}/zastosuvaty.ngr#sha256={sha((MODS / "zastosuvaty.ngr").read_bytes())}」 【「застосувати」 「обгортка」】\n'
    for g_, body_ in (('»', '» q'), ('🜄', '🜄 「к」 q'), ('🜃', '🜃 q'), ('≈', '≈ q 0.5'), ('⚗', '⚗ 【q】 0.5'),
                      ('🜍', '🜍 q λv ●'), ('🜁', '🜁 「с」 【】 q'), ('⌂', '⌂')):
        for how_, call_ in (('у функції', f'» застосувати λq {body_} 「x」'), ('у замиканні', f'← g обгортка λq {body_}\n» ► g 「x」')):
            got = run(['-e', f'🜂\n{zz_}{call_}'], dict(env, NIGREDO_TRACE_PATH_FILE=str(tmp / 'замок2.слід')))
            den_ = [r_ for r_ in recs_of(pathlib.Path((tmp / 'замок2.слід').read_text(encoding='utf-8')))
                    if r_['подія'] == 'заборонено']
            q_ = '「»」' if g_ == '»' else f'«{g_}»'
            check(got.returncode == 1 and f'модуль з мережі лише обчислює: {q_} тут неможливий (у виклику функції модуля '
                  f'「{LIB}/zastosuvaty.ngr」)' in got.stderr
                  and got.stdout == '' and len(den_) == 1 and den_[0]['причина'] == 'модуль з мережі лише обчислює'
                  and den_[0].get('модуль', '').startswith(f'{LIB}/zastosuvaty.ngr#sha256='),
                  f'замок 2: «{g_}» у λ того, хто кличе, {how_} модуля з мережі — «заборонено» в сліді, код 1', got.stderr)
    got = run(['-e', f'🜂\n{zz_}» застосувати λq ＋ q 1 41'], env)
    seal_ = run(['--печатка', str(ROOT / 'tests' / 'помилки' / '184_modul_merezhi_zvorotnyi_vyklyk.ngr')], env)
    got2 = run([str(ROOT / 'tests' / 'помилки' / '185_modul_merezhi_parasolka.ngr')], dict(env, NIGREDO_TRACE_PATH_FILE=str(tmp / 'п185.слід')))
    vr_ = run(['--перевірити-слід', (tmp / 'п185.слід').read_text(encoding='utf-8')], env).stdout   # той самий власник
    check(got.stdout == '42\n' and ('⚠ λ з 🜔оракул передано у «застосувати» з модуля з мережі: якщо її викличе модуль — '
                                    '«заборонено» (там прав немає') in seal_.stdout
          and 'якщо модуль її поверне, а викличе програма, — діє з правами програми' in seal_.stdout
          and got2.stdout == 'перехоплено\n' and '«заборонено»): 1' in vr_ and 'перехоплено помилок (☂): 1' in vr_,
          'чиста λ у модулі з мережі — так; λ з 🜔 — попередження в --печатка; ☂ у модулі: «заборонено» й «перехоплено» '
          'видно в підсумку сліду (§6.3, §6.4)', got.stdout + got.stderr + seal_.stdout + got2.stdout + vr_)
    # -e і REPL: модуль з мережі не залежить від теки програми (§2.4); --розбір — тіло модуля з sha256 повністю
    rc, ans, tr_ = repl([j(f'🜂\n⊃ 「{addr("tekst.ngr", TEKST)}」 【「слова」】'), j('» слова 「Б В」')])
    ex_ = run(['--розбір', t1_], menv).stdout
    check(rc == 0 and ans[-1].get('вивід') == '【「б」 「в」】\n'
          and f'з модуля з мережі «{LIB}/tekst.ngr» (sha256 {sha(TEKST)}; лише обчислює; адреса — слова автора)' in ex_,
          '--repl із модулем з мережі; --розбір перекладає й тіло модуля з мережі (§10.3)', str(ans) + ex_)
    # суд 10: ключ власника каже правду про модулі з мережі (Скептик, Практик, Мовознавець, Аудитор, Новачок, Оркестратор)
    sh10, s10 = owner('власник_суд10', {'github.com': mbase}, fixtures=True)
    SMERT, ARGS = '🜂\n← впасти λx ☠ x\n'.encode(), '🜂\n← а λx 【x ⌂】\n'.encode()
    BATKO = f'🜂\n⊃ 「util/dytyna.ngr#sha256={"0" * 64}」 【「подвоїти」】\n← f λx подвоїти x\n'.encode()
    Mirror.files.update({'smert.ngr': SMERT, 'arhumenty.ngr': ARGS, 'lib/batko.ngr': BATKO, 'lib/util/dytyna.ngr': B})
    store_fixtures(sh10, [SMERT])
    # ⌂ у модулі з мережі — замок 1: модуль бачить лише те, що йому передали (замок 2 — у циклі вище)
    n_ = len(stored(sh10))
    got = run(['--отримати', f'{LIB}/arhumenty.ngr'], s10)
    check(got.returncode == 2 and 'модуль з мережі бачить лише те, що йому передали, — «⌂» (аргументи програми)' in got.stderr
          and len(stored(sh10)) == n_, '⌂ у модулі з мережі — замок 1, не покладено (суд 10: модуль дописував аргумент '
          'програми в URL, а печатка казала «ЧИСТИЙ»)', got.stderr)
    # ☠ у коді модуля — з позначкою (текст міг прийти з переданих значень, огляд 10б); ☂ у виклику модуля — подія з
    # адресою модуля, у підсумку сліду — окремо
    sm_ = prog('смерть.ngr', f'🜂\n⊃ 「{addr("smert.ngr", SMERT)}」 【「впасти」】\n» ☂ впасти 「ВЛАСНИКУ: хибна тривога」 λe 「п」\n'
               '» впасти 「слова модуля」\n')
    got = run([sm_], s10)
    tr_ = last(s10)
    cg_ = [r_ for r_ in recs_of(tr_) if r_['подія'] == 'помилку перехоплено']
    vr_ = run(['--перевірити-слід', str(tr_), sm_], s10).stdout
    check(got.returncode == 1 and got.stdout == 'п\n' and f'{LIB}/smert.ngr#sha256={sha(SMERT)}:2:' in got.stderr
          and '☠ у коді модуля (текст міг прийти з переданих йому значень): слова модуля' in got.stderr and len(cg_) == 1
          and cg_[0].get('модуль') == addr('smert.ngr', SMERT) and 'з них у виклику модулів з мережі — 1' in vr_
          and 'ВЛАСНИКУ: хибна тривога' in vr_, '☠ у коді модуля з мережі — позначено; ☂ у виклику модуля — подія з '
          'адресою модуля, у --перевірити-слід окремо (суд 10, Мовознавець)', got.stdout + got.stderr + vr_)
    # λ програми, викликана з модуля (тут — локального: Атанор теж): місце помилки — у програмі, без файлу модуля
    (mp / 'застос_лок.ngr').write_text('🜂\n← застосувати λf ► f 「x」\n← впасти λx ☠ x\n', encoding='utf-8')
    lp_ = prog('лок_місце.ngr', '🜂\n⊃ 「застос_лок.ngr」 【「застосувати」 「впасти」】\n» застосувати λq ☠ q\n')
    lp2_ = prog('лок_місце2.ngr', '🜂\n⊃ 「застос_лок.ngr」 【「застосувати」 「впасти」】\n» впасти 「м」\n')
    got, got2 = run([lp_], env), run([lp2_], env)
    check(got.returncode == 1 and got.stderr.startswith('✗ 3:') and 'застос_лок.ngr' not in got.stderr
          and got2.returncode == 1 and got2.stderr.startswith('✗ застос_лок.ngr:3:'),
          'помилка в λ програми, викликаній з модуля, — місце в програмі (було: файл модуля з рядком програми; суд 10); '
          '☠ у функції модуля — файл модуля', got.stderr + got2.stderr)
    # функція, на вигляд гліф, — і в ∘імʼя (Σ … ∘х читалося як «згорнути ×», а додавало)
    got = run(['-e', '🜂\n← х Λa b ＋ a b\n» Σ 【2 3 4】 1 ∘х'], env)
    Mirror.files['dvijnyk.ngr'] = '🜂\n← х Λa b ＋ a b\n'.encode()
    got2 = run(['--отримати', f'{LIB}/dvijnyk.ngr'], s10)
    check(got.returncode == 2 and 'функція «х» на вигляд — гліф «×»: «∘х …» читається як «∘× …»' in got.stderr and got.stdout == ''
          and got2.returncode == 0 and '⚠ функція «х» на вигляд — гліф «×»' in got2.stdout and 'ні «∘х»' in got2.stdout,
          '∘х (двійник ×) — помилка розбору, як і виклик «х …»; --отримати модуля з такою функцією — ⚠ автору (суд 10, '
          'Мовознавець)', got.stdout + got.stderr + got2.stdout + got2.stderr)
    # --отримати: адреса в 「」 (як у ⊃ і підказках); уже у сховищі — «мережу не питали»; файлу немає — JSON
    th_n = len(hits)
    got = run(['--отримати', f'「{addr("tekst.ngr", TEKST)}」'], tenv)
    gj_ = run(['--отримати', '--json', 'немає_такої.ngr'], tenv)
    got3 = run(['--отримати', f'https://github.com/denromvas/ngr-lib/blob/{COMMIT}/tekst.ngr'], tenv)
    check(got.returncode == 0 and got.stdout.startswith(f'✓ уже у сховищі {LIB}/tekst.ngr — мережу не питали')
          and 'чи віддає адреса те саме зараз, не звірено' in got.stdout and len(hits) == th_n and 'збігся' not in got.stdout
          and gj_.returncode == 2 and json.loads(gj_.stdout).get('гаразд') is False
          and got3.returncode == 2 and 'No such file' not in got3.stderr and 'адреса' in got3.stderr,
          '--отримати 「адреса」 — працює; уже у сховищі — «мережу не питали», 0 запитів (було «✓ отримано … збігся»); '
          'файлу немає — JSON; URL сторінки — підказка адреси (суд 10)', got.stdout + got.stderr + gj_.stdout + got3.stderr)
    # адреса модуля, чиї вкладені вже у сховищі, — усі у виводі й сліді «уже було»
    n_ = len(hits)
    got = run(['--отримати', addr('lib/a.ngr', A)], menv)
    fr_ = [r_ for r_ in recs_of(last(menv)) if r_['подія'] == 'модуль отримано']
    check(got.returncode == 0 and got.stdout.startswith('✓ уже у сховищі') and '(3 файл(и)' in got.stdout and len(hits) == n_
          and len(fr_) == 3 and {r_['стан'] for r_ in fr_} == {'уже було'}
          and f'⊃ 「lib/a.ngr#sha256={sha(A)}」 【「обидва」】' in got.stdout,
          '--отримати АДРЕСА: вкладені, що вже були, — у виводі й сліді; рядок закріпленого відносного ⊃ для автора (суд 10)',
          got.stdout + str(fr_))
    # підміна вкладеного: тривога називає саму дитину й того, хто її закріпив; шлях сліду — і без --json
    n_ = len(stored(sh10))
    bt_ = prog('батько.ngr', f'🜂\n⊃ 「{addr("lib/batko.ngr", BATKO)}」 【「f」】\n» f 2\n')
    got = run(['--отримати', bt_], s10)
    gj_ = json.loads(run(['--отримати', '--json', bt_], s10).stdout)
    check(got.returncode == 3 and (f'«{LIB}/lib/util/dytyna.ngr»: сервер віддав вміст із sha256 {sha(B)}, а модуль '
                                   f'«{LIB}/lib/batko.ngr» закріпив {"0" * 64}') in got.stderr
          and '\n  слід: ' in got.stderr and gj_.get('адреса') == f'{LIB}/lib/util/dytyna.ngr' and gj_.get('код') == 3
          and len(stored(sh10)) == n_, 'підміна вкладеного модуля — тривога з адресою дитини й батьком, що закріпив (було: '
          'батько й «програма»); шлях сліду в stderr (суд 10, Аудитор, Оркестратор, Практик)', got.stderr + str(gj_))
    # --з-теки: копія сховища <sha256>.ngr з іншим вмістом — тривога «вміст не збігся», код 3 (було: код 1 без тривоги)
    cp10 = tmp / 'копія_суд10'
    cp10.mkdir()
    (cp10 / f'{sha(TEKST)}.ngr').write_bytes(B)
    zh10, z10 = owner('власник_з_теки_суд10', [])
    got = run(['--отримати', t1_, '--з-теки', str(cp10)], z10)
    vr_ = run(['--перевірити-слід', str(last(z10))], z10).stdout
    check(got.returncode == 3 and 'копію сховища змінено чи підмінено' in got.stderr and 'ВМІСТ НЕ ЗБІГСЯ' in vr_
          and stored(zh10) == [], '--з-теки: копія сховища з іншим вмістом — тривога в сліді, код 3 (суд 10, Мовознавець)',
          got.stderr + vr_)
    # печатка: локальний модуль, чий шлях схожий на адресу, — «ЛОКАЛЬНИЙ» з попередженням; ромб — модуль раз, хто бере
    la_ = tmp / 'схожа_тека'
    (la_ / 'github.com' / 'denromvas' / f'ngr-lib@{COMMIT}').mkdir(parents=True)
    (la_ / 'github.com' / 'denromvas' / f'ngr-lib@{COMMIT}' / 'tekst.ngr').write_text(
        '🜂 【「оракул」】\n← слова λx 🜔оракул x\n', encoding='utf-8')
    (la_ / 'п.ngr').write_text(f'🜂 【「оракул」】\n⊃ 「{LIB}/tekst.ngr」 【「слова」】\n» слова 「А」\n', encoding='utf-8')
    seal_, sj_ = run(['--печатка', str(la_ / 'п.ngr')], menv).stdout, json.loads(run(['--печатка', '--json', str(la_ / 'п.ngr')], menv).stdout)
    fe_ = run(['--отримати', str(la_ / 'п.ngr')], menv)
    lr_ = run([str(la_ / 'п.ngr')], menv)
    lv_ = run(['--перевірити-слід', str(last(menv)), str(la_ / 'п.ngr')], menv).stdout
    lj_ = json.loads(run(['--перевірити-слід', str(last(menv)), str(la_ / 'п.ngr'), '--json'], menv).stdout)
    check(lr_.returncode == 0 and lv_.startswith('✓') and 'з мережі' not in lv_.partition('модулі:')[2].split('\n')[0]
          and '— ЛОКАЛЬНИЙ файл, хоча шлях схожий на адресу' in lv_ and lj_['модулі'][0]['з_мережі'] is False,
          '--перевірити-слід: локальний модуль зі шляхом, схожим на адресу, — не «з мережі», а ⚠ «ЛОКАЛЬНИЙ» (суд 10, '
          'Новачок, раунд 2)', lr_.stderr + lv_)
    rj_ = json.loads(run(['--печатка', '--json', romb], menv).stdout)
    tk_ = [m_ for m_ in rj_['модулі'] if m_.get('адреса') == f'{LIB}/tekst.ngr']
    check(f'— ЛОКАЛЬНИЙ файл 「{la_}/github.com/' in seal_ and '(локальний файл 「' in seal_
          and sj_['модулі'][0].get('з_мережі') is False and sj_['модулі'][0].get('файл', '').endswith('/tekst.ngr')
          and any('ЛОКАЛЬНИЙ файл' in w_ for w_ in sj_['попередження']) and '⚠ модуль 「' in fe_.stdout
          and len(rj_['модулі']) == 3 and len(tk_) == 1 and set(tk_[0]['бере_його']) == {'програма', f'{LIB}/lib/a.ngr'}
          and 'адресу не звірено, це не схвалення' in run(['--печатка', romb], menv).stdout,
          'печатка: локальний модуль зі шляхом, схожим на адресу, — «ЛОКАЛЬНИЙ» з ⚠ (і в --отримати); ромб — модуль раз, '
          'з тим, хто його бере; «у сховищі ✓» — не схвалення (суд 10)', seal_ + json.dumps(rj_, ensure_ascii=False)[:900])
    # MCP: модуля бракує — чесна порада (у MCP отримання немає)
    mreq = {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call', 'params': {'name': 'nigredo_pechatka', 'arguments': {
        'code': f'🜂\n⊃ 「{LIB}/nema.ngr#sha256={"1" * 64}」 【「f」】\n» f 1'}}}
    mg_ = subprocess.run([sys.executable, str(ROOT / 'mcp' / 'nigredo_mcp.py')], input=json.dumps(mreq) + '\n',
                         capture_output=True, text=True, env=dict(s10, NIGREDO_WORKDIR=str(tmp / 'робоча')))
    mt_ = [c_['text'] for c_ in json.loads(mg_.stdout.splitlines()[0])['result']['content']] if mg_.stdout else []
    check(any('через MCP модулі з мережі не отримати' in t_ for t_ in mt_),
          'MCP: модуля з мережі бракує — порада попросити власника (суд 10, Новачок)', mg_.stdout[-600:] + mg_.stderr[-300:])
    # --звірити: справді спитати джерело, чи віддає адреса той самий вміст (навіть коли він уже у сховищі); нічого не класти
    mt_ = {p_.name: p_.stat().st_mtime_ns for p_ in (mh / 'модулі').iterdir()}
    n_ = len(hits)
    got = run(['--отримати', romb, '--звірити'], menv)
    vr_ = run(['--перевірити-слід', str(last(menv))], menv).stdout
    Mirror.files['tekst.ngr'] = B                     # сервер тепер віддає інше за тією самою адресою
    got2 = run(['--отримати', t1_, '--звірити'], menv)
    vr2_ = run(['--перевірити-слід', str(last(menv))], menv).stdout
    nh_ = len(hits)
    Mirror.files['tekst.ngr'] = TEKST
    got3, got4 = run(['--отримати', f'{LIB}/tekst.ngr', '--звірити'], menv), run(['--отримати', romb, '--звірити', '--з-теки',
                                                                                   str(tmp)], menv)
    vh_, venv_ = owner('власник_звірка', {'github.com': mbase})        # модулів ще немає: звірка їх не кладе
    got5 = run(['--отримати', romb, '--звірити'], venv_)
    check(got.returncode == 0 and got.stdout.startswith('✓ --звірити: джерело власника віддає той самий вміст — 3 файл(и)')
          and nh_ == n_ + 4 and 'ЗВІРКА МОДУЛІВ З АДРЕСОЮ: 3 звірено' in vr_
          and got2.returncode == 3 and f'сервер віддав вміст із sha256 {sha(B)}' in got2.stderr and 'ВМІСТ НЕ ЗБІГСЯ' in vr2_
          and mt_ == {p_.name: p_.stat().st_mtime_ns for p_ in (mh / 'модулі').iterdir()}
          and got3.returncode == 2 and 'вміст має бути закріплено' in got3.stderr and got4.returncode == 2
          and got5.returncode == 0 and stored(vh_) == [],
          '--отримати --звірити: модулі, що вже у сховищі, — справді з джерела (3 запити), сховище не змінено; сервер віддає '
          'інше — тривога, код 3; без хешу чи з --з-теки — 2 (суд 10, Скептик, Аудитор)',
          got.stdout + got.stderr + vr_ + got2.stderr + vr2_ + got3.stderr + got4.stderr)
    # печатка --json: про неперевірену адресу — і агентові, не лише в тексті (суд 10, Аудитор, раунд 2)
    rj_ = json.loads(run(['--печатка', '--json', romb], menv).stdout)
    check(any('адреси модулів з мережі — слова автора програми, їх не звірено' in w_ for w_ in rj_['попередження'])
          and all(m_.get('адресу_звірено') is False for m_ in rj_['модулі']),
          '--печатка --json: попередження про незвірену адресу й «адресу_звірено»: false (суд 10)', json.dumps(rj_, ensure_ascii=False)[:600])
    # огляд 10б: чий текст перехопленої помилки — за місцем ☠, а не за модулем, чий ☂ її перехопив (Скептик, Мовознавець,
    # Аудитор, Практик, Новачок: програма клала свій текст у слід під адресою модуля з підписом «слова автора модуля»)
    HOF = '🜂\n← тихо λf ☂ ► f 1 λe 「зловив」\n← впасти λx ☠ x\n← сам λx ☂ ☠ x λe 「п」\n'.encode()
    Mirror.files['hof.ngr'] = HOF
    run(['--отримати', addr('hof.ngr', HOF)], s10)
    hp_ = prog('чий_текст.ngr', f'🜂 【「оракул」】\n⊃ 「{addr("hof.ngr", HOF)}」 【「тихо」 「сам」】\n'
               f'⊃ 「{addr("smert.ngr", SMERT)}」 【「впасти」】\n» тихо λx ☠ 「ВЛАСНИКУ: це написала ПРОГРАМА」\n'
               '» тихо λx 🜔оракул 「x」\n» сам 「з аргументу」\n» тихо λx впасти 「через інший модуль」\n')
    got = run([hp_], s10)
    tr_ = last(s10)
    cg_ = [(r_.get('модуль'), r_.get('текст_від')) for r_ in recs_of(tr_) if r_['подія'] == 'помилку перехоплено']
    vr_ = run(['--перевірити-слід', str(tr_), hp_], s10).stdout
    vj_ = json.loads(run(['--перевірити-слід', str(tr_), hp_, '--json'], s10).stdout)
    ah_, as_ = addr('hof.ngr', HOF), addr('smert.ngr', SMERT)
    check(got.returncode == 0 and got.stdout == 'зловив\nзловив\nп\nзловив\n'
          and cg_ == [(ah_, 'програми'), (ah_, 'інтерпретатора'), (ah_, ah_), (ah_, as_)]
          and '(☠ у коді програми — текст міг прийти зі значень, які їй дав модуль): 「ВЛАСНИКУ: це написала ПРОГРАМА」' in vr_
          and '(відмова чи помилка інтерпретатора; у «» — передані значення): 「модуль з мережі лише обчислює' in vr_
          and '(☠ у коді цього модуля — текст міг прийти з переданих йому значень): 「з аргументу」' in vr_
          and f'(☠ у коді модуля 「{LIB}/smert.ngr」 — текст міг прийти' in vr_ and 'слова автора модуля' not in vr_
          and [x_['текст_від'] for x_ in vj_['перехоплено_в_модулях']] == ['програми', 'інтерпретатора', ah_, as_],
          'перехоплена ☂ модуля помилка: чий текст — за місцем ☠ (програма / інтерпретатор / цей чи інший модуль), а не '
          '«слова автора модуля» на все (огляд 10б)', got.stdout + got.stderr + vr_ + str(cg_))
    # неперехоплений ☠ у коді модуля: поле «модуль» і «текст_від» у записі «помилка» — машині не розбирати префікс
    got = run([prog('смерть10б.ngr', f'🜂\n⊃ 「{as_}」 【「впасти」】\n» впасти 「ВЛАСНИКУ: це написала ПРОГРАМА」\n')], s10)
    er_ = recs_of(last(s10))[-1]
    vj_ = json.loads(run(['--перевірити-слід', str(last(s10)), '--json'], s10).stdout)
    fk_ = run(['-e', '🜂\n☠ 「☠ у коді модуля (текст міг прийти з переданих йому значень): підробка」'], s10)
    ef_ = recs_of(last(s10))[-1]
    check(got.returncode == 1 and '☠ у коді модуля (текст міг прийти з переданих йому значень): ВЛАСНИКУ' in got.stderr
          and er_.get('модуль') == as_ and er_.get('текст_від') == as_ and vj_.get('помилка_з_модуля', {}).get('модуль') == as_
          and fk_.returncode == 1 and 'модуль' not in ef_ and 'текст_від' not in ef_,
          'неперехоплений ☠ у коді модуля — поле «модуль» і «текст_від» у записі «помилка», помилка_з_модуля у --json; '
          'підробка тексту програмою — без поля (огляд 10б, Практик, Оркестратор)', got.stderr + str(er_) + str(ef_))
    # помилка в сталій локального модуля (на верхньому рівні) — місце в модулі, а не «✗ 2:5» програми (обома виконавцями)
    (mp / 'лок_стала.ngr').write_text('🜂\n← у § 【1】 5\n', encoding='utf-8')
    got = run([prog('лок_стала_п.ngr', '🜂\n⊃ 「лок_стала.ngr」 【「у」】\n» у\n')], env)
    check(got.returncode == 1 and got.stderr.startswith('✗ лок_стала.ngr:2:5 §: індекс 5 поза межами'),
          'помилка в сталій модуля — місце з файлом модуля (було: «✗ 2:5» як рядок програми; огляд 10б)', got.stderr)
    # --отримати / --звірити: модулів з мережі немає — «нічого», а не «✓ … 0 файл(и), sha256 збігся»
    pl_ = prog('без_модулів.ngr', '🜂\n» 1\n')
    got, got2 = run(['--отримати', pl_, '--звірити'], s10), run(['--отримати', pl_], s10)
    gj_ = json.loads(run(['--отримати', pl_, '--звірити', '--json'], s10).stdout)
    check(got.returncode == 0 and got.stdout.startswith('--звірити: модулів з мережі в програмі немає — звіряти нічого')
          and '✓' not in got.stdout and got2.stdout.startswith('--отримати: модулів з мережі в програмі немає')
          and gj_.get('звірено') == 0, '--звірити без модулів з мережі — «звіряти нічого», без «✓ … sha256 збігся» '
          '(огляд 10б, Мовознавець, Практик, Оркестратор)', got.stdout + got2.stdout)
    # --звірити: адреса не віддає закріпленого (404) — звірку не пройдено, тривога, код 3 (було: код 1, як збій мережі)
    p404_ = prog('немає404.ngr', f'🜂\n⊃ 「{LIB}/немає_тут.ngr#sha256={"2" * 64}」 【「f」】\n» f 1\n')
    got = run(['--отримати', p404_, '--звірити'], s10)
    vr_ = run(['--перевірити-слід', str(last(s10))], s10).stdout
    got2 = run(['--отримати', p404_], s10)
    check(got.returncode == 3 and 'адреса не віддає закріпленого вмісту — звірку НЕ пройдено' in got.stderr
          and 'ВМІСТ НЕ ЗБІГСЯ: 1' in vr_ and 'HTTP 404, файлу немає' in vr_ and got2.returncode == 1,
          '--звірити: 404 на закріпленій адресі — «звірку НЕ пройдено», тривога, код 3; звичайне --отримати — код 1 '
          '(огляд 10б, Мовознавець)', got.stderr + vr_)
    # у сховищі модуль, покладений за давніших правил (⌂), — не «✓»: --отримати код 2; --звірити питає джерело, а не сховище
    OLD = '🜂\n← а λx 【x ⌂】\n'.encode()
    store_fixtures(sh10, [OLD])
    po_ = prog('старий.ngr', f'🜂\n⊃ 「{addr("stare.ngr", OLD)}」 【「а」】\n» а 1\n')
    got = run(['--отримати', po_], s10)
    gj_ = json.loads(run(['--отримати', po_, '--json'], s10).stdout)
    got2 = run(['--отримати', addr('stare.ngr', OLD)], s10)
    n_ = len(hits)
    Mirror.files['stare.ngr'] = B
    got3 = run(['--отримати', po_, '--звірити'], s10)
    check(got.returncode == 2 and got.stderr.startswith('✗ --отримати: програма не розбирається') and '«⌂»' in got.stderr
          and '✓' not in got.stdout + got.stderr and gj_.get('гаразд') is False and gj_.get('код') == 2
          and got2.returncode == 2 and 'лежить у сховищі (покладено раніше), але не проходить нинішніх перевірок' in got2.stderr
          and got3.returncode == 3 and len(hits) == n_ + 1 and 'звірку НЕ пройдено' in got3.stderr,
          'модуль у сховищі не проходить нинішніх перевірок — --отримати без «✓», код 2; --звірити — з мережі, а не зі сховища '
          '(огляд 10б, Аудитор, Практик, Скептик)', got.stdout + got.stderr + got2.stderr + got3.stderr)
    # --звірити: дерево вкладених — з того, що віддало джерело (батько, потім дитина); розбіжність дитини — хто закріпив
    KID = '🜂\n← потроїти λx × x 3\n'.encode()
    PAR = f'🜂\n⊃ 「util/kid.ngr#sha256={sha(KID)}」 【「потроїти」】\n← g λx потроїти x\n'.encode()
    Mirror.files.update({'lib/par.ngr': PAR, 'lib/util/kid.ngr': KID})
    pp_ = prog('батько10б.ngr', f'🜂\n⊃ 「{addr("lib/par.ngr", PAR)}」 【「g」】\n» g 2\n')
    run(['--отримати', pp_], s10)
    n_ = len(hits)
    got = run(['--отримати', pp_, '--звірити'], s10)
    order_ = [h_.rpartition('/')[2] for h_ in hits[n_:]]
    Mirror.files['lib/util/kid.ngr'] = KID + b' '
    got2 = run(['--отримати', pp_, '--звірити'], s10)
    gj2_ = json.loads(run(['--отримати', pp_, '--звірити', '--json'], s10).stdout)
    Mirror.files['lib/util/kid.ngr'] = KID
    check(got.returncode == 0 and order_ == ['par.ngr', 'kid.ngr'] and got2.returncode == 3
          and f'а модуль «{LIB}/lib/par.ngr» закріпив {sha(KID)} — звірку НЕ пройдено' in got2.stderr
          and 'далі не звіряли (вміст збігся до того: 1 файл(и))' in got2.stderr and gj2_.get('звірено') == 1,
          '--звірити: вкладені — з байтів, які віддало джерело (спершу батько), сховища не читає; тривога називає, хто '
          'закріпив; де звірку зупинено (огляд 10б, Мовознавець, Оркестратор)', got.stdout + got2.stderr + str(order_))
    # --тести --печатка: які модулі бере тест — і без запуску (огляд 10б, Новачок: лише запуск їх перелічував)
    td10_ = tmp / 'тести10б'
    td10_.mkdir()
    (td10_ / 'м.тест.ngr').write_text(f'🜂\n⊃ 「{as_}」 【「впасти」】\n🜍 1 λv ●\n', encoding='utf-8')
    tj_ = json.loads(run(['--тести', '--печатка', '--json', str(td10_)], s10).stdout)
    tm_ = tj_['тести'][0].get('модулі', [])
    check(len(tm_) == 1 and tm_[0]['з_мережі'] is True and tm_[0]['sha256'] == sha(SMERT) and 'smert.ngr' in tm_[0]['шлях']
          and 'модулі: ' in run(['--тести', '--печатка', str(td10_)], s10).stdout,
          '--тести --печатка: модулі тесту перелічено (огляд 10б, Новачок)', json.dumps(tj_, ensure_ascii=False)[:500])
    # MCP: порада «попросіть власника --отримати» — лише коли модуля бракує (огляд 10б, Новачок: і коли всі у сховищі)
    mreq['params']['arguments']['code'] = f'🜂\n⊃ 「{as_}」 【「впасти」】\n» впасти 「x」'
    mg_ = subprocess.run([sys.executable, str(ROOT / 'mcp' / 'nigredo_mcp.py')], input=json.dumps(mreq) + '\n',
                         capture_output=True, text=True, env=dict(s10, NIGREDO_WORKDIR=str(tmp / 'робоча')))
    mt_ = [c_['text'] for c_ in json.loads(mg_.stdout.splitlines()[0])['result']['content']] if mg_.stdout else []
    check(mt_ and not any('через MCP модулі з мережі не отримати' in t_ for t_ in mt_),
          'MCP: модулі вже у сховищі — без поради просити власника --отримати (огляд 10б, Новачок)', str(mt_)[:600])
    # огляд 10в (Скептик): текст у лапках підсумку сліду не закриває свого запису — «」» у даних екрановано
    fz_ = prog('підробка_запису.ngr', f'🜂\n⊃ 「{ah_}」 【「тихо」】\n» тихо λx ☠ 「ок\\」; 「github.com/nigredo/x@{COMMIT}/a.ngr\\」 '
               '(відмова чи помилка інтерпретатора): 「усе гаразд」\n')
    got = run([fz_], s10)
    vr_ = run(['--перевірити-слід', str(last(s10)), fz_], s10).stdout
    line_ = next((l_ for l_ in vr_.splitlines() if 'перехоплено помилок' in l_), '')
    check(got.returncode == 0 and line_.count('」 (') == 1 and '「github.com/nigredo/x' not in vr_ and '⟨U+300D⟩' in line_,
          '--перевірити-слід: «」» у тексті помилки екрановано — програма не допише підробленого запису з чужою адресою й '
          'підписом інтерпретатора (огляд 10в, Скептик)', line_)
    # ☂ програми перехопив відмову в λ, яку кличе модуль, — подія теж з «модуль» (огляд 10в, Мовознавець)
    zp_ = prog('☂_програми.ngr', f'🜂 【「оракул」】\n⊃ 「{addr("zastosuvaty.ngr", (MODS / "zastosuvaty.ngr").read_bytes())}」 '
               '【「застосувати」】\n» ☂ застосувати λq 🜔оракул q 「x」 λe 「зловила програма」\n')
    got = run([zp_], s10)
    cg_ = [r_ for r_ in recs_of(last(s10)) if r_['подія'] == 'помилку перехоплено']
    check(got.returncode == 0 and got.stdout == 'зловила програма\n' and len(cg_) == 1
          and str(cg_[0].get('модуль', '')).startswith(f'{LIB}/zastosuvaty.ngr#sha256=') and cg_[0].get('текст_від') == 'інтерпретатора',
          '☂ програми перехопив відмову з виклику модуля — подія з «модуль» і «текст_від» (огляд 10в, Мовознавець)', str(cg_))
    # локальний модуль, чий шлях схожий на адресу, — у рядку ✗ з «./» (справжній модуль з мережі — завжди з #sha256=)
    lk_ = mp / 'github.com' / 'nigredo' / f'tekst@{COMMIT}'
    lk_.mkdir(parents=True)
    (lk_ / 'smert.ngr').write_text('🜂\n← впасти λx ☠ x\n', encoding='utf-8')
    got = run([prog('лок_схожий.ngr', f'🜂\n⊃ 「./github.com/nigredo/tekst@{COMMIT}/smert.ngr」 【「впасти」】\n» впасти 「ВЛАСНИКУ」\n')], env)
    got2 = run([prog('лок_схожий2.ngr', f'🜂\n⊃ 「github.com/nigredo/tekst@{COMMIT}/smert.ngr」 【「впасти」】\n» впасти 「ВЛАСНИКУ」\n')], env)
    check(got.stderr.startswith(f'✗ ./github.com/nigredo/tekst@{COMMIT}/smert.ngr:2:13 ВЛАСНИКУ')
          and got2.stderr.startswith(f'✗ ./github.com/nigredo/tekst@{COMMIT}/smert.ngr:2:13 ВЛАСНИКУ'),
          'помилка в локальному модулі зі шляхом, схожим на адресу, — «✗ ./github.com/…» (обома; огляд 10в, Мовознавець)',
          got.stderr + got2.stderr)
    # Атанор v1a: кожну програму з модулем з мережі віддає еталону — вивід, код і слід ті самі
    if os.environ.get('NGR_TEST_BIN'):
        got = run([romb], dict(menv, ATHANOR_WHY='1'))
        ev1 = [r_['подія'] for r_ in recs_of(last(menv))]
        ref_ = subprocess.run([sys.executable, str(NGR), romb], capture_output=True, text=True, env=menv)
        ev2 = [r_['подія'] for r_ in recs_of(last(menv))]
        check('атанор → еталон: ⊃ з мережі чи схожий на адресу — еталон (модулі з git, §11)' in got.stderr and got.stdout == ref_.stdout
              and got.returncode == ref_.returncode == 0 and ev1 == ev2,
              'Атанор v1a: програму з модулем з мережі віддано еталону (явна причина), вивід і слід ті самі', got.stderr)
    msrv.shutdown()

    # ------------------------------------------------------------------ фаза 6.1: замок ОС (spec/пропозиції/фаза6.md §1)
    # Чого печатка не просить зовсім (мережа, процеси, запис), те закриває ядро (seccomp), а не лише інтерпретатор.
    oh = tmp / 'власник_замок'
    oh.mkdir()
    ow = tmp / 'замок_вих'
    ow.mkdir()
    (oh / 'дозволи.json').write_text(json.dumps({'дозволено': ['процес:sh -c', f'писати:{ow}', 'взяти:127.0.0.1', 'агент:ніхто',
                                                              f'бд.читати:{ow}']}, ensure_ascii=False), encoding='utf-8')
    oenv = dict(env, NIGREDO_HOME=str(oh), NIGREDO_TRACE_PATH_FILE=str(tmp / 'замок.слід'))
    pj = json.loads(run(['--перевірити-ізоляцію', '--json'], oenv).stdout)
    probe_ = run(['--перевірити-ізоляцію'], oenv)
    has_lock = pj.get('ядро') == 'seccomp'
    check((probe_.returncode == 0 and pj['тримає'] is True and set(pj['групи'].values()) == {'EPERM'}
           and probe_.stdout.count('✓') == 3) if has_lock else (probe_.returncode == 2 and 'замка ОС на цій машині немає' in probe_.stdout),
          '--перевірити-ізоляцію: дочірній процес під замком — socket, запис файлу й exec ядро відмовило (EPERM); замка '
          'немає — так і сказано, код 2 (фаза 6.1)', probe_.stdout + probe_.stderr)

    def iso(code, *extra):
        got_ = run([*extra, '-e', code], oenv)
        ev_ = [r_ for r_ in (json.loads(x) for x in pathlib.Path((tmp / 'замок.слід').read_text(encoding='utf-8'))
                             .read_text(encoding='utf-8').splitlines()) if r_['подія'] == 'ізоляція']
        return got_, ev_
    cases_ = [('🜂\n» 1', [], ['мережа', 'процеси', 'запис']), (f'🜂 【「писати:{ow}」】\n» 1', [], ['мережа', 'процеси']),
              ('🜂 【「процес:sh -c」】\n» 1', [], ['мережа']), ('🜂 【「взяти:127.0.0.1」】\n» 1', [], ['процеси', 'запис']),
              (f'🜂 【「бд.читати:{ow}」】\n» 1', [], ['мережа', 'процеси']), ('🜂 【「агент:ніхто」】\n» 1', [], []),
              (f'🜂 【「писати:{ow}」】\n» 1', ['--сухо'], ['мережа', 'процеси', 'запис'])]
    bad_ = []
    for code_, extra_, want_ in cases_:
        got_, ev_ = iso(code_, *extra_)
        exp_ = ({'ядро': 'seccomp', 'закрито': want_} if want_ and has_lock else {'ядро': 'не потрібне', 'закрито': []}
                if not want_ else None)
        ok_ = got_.returncode == 0 and len(ev_) == 1 and (exp_ is None or {k: ev_[0].get(k) for k in exp_} == exp_)
        if not ok_:
            bad_.append((code_, extra_, ev_, got_.stderr[-200:]))
    check(not bad_, 'замок ОС: подія «ізоляція» одразу після печатки — закрито саме ті групи, яких печатка не просить '
          '(процес відкриває й запис, агент — усе, бд.читати — запис; --сухо — усе) (фаза 6.1)', str(bad_))
    seal_ = run(['--печатка', '--json', '-e', '🜂 【「процес:sh -c」】\n» 1'], oenv)
    check(json.loads(seal_.stdout).get('замок_ОС') == {'закрито': ['мережа']}
          and 'ЗАМОК ОС: ядро закриє мережа' in run(['--печатка', '-e', '🜂 【「процес:sh -c」】\n» 1'], oenv).stdout,
          '--печатка: що закриє ядро (і в --json «замок_ОС») (фаза 6.1)', seal_.stdout[-400:])
    if has_lock:
        # дочірні процеси успадковують замок: команда без 「взяти」 у печатці мережі не має, з ним — має
        netpy_ = 'import socket\ntry:\n    socket.socket().close(); print("мережа: є")\nexcept OSError as e:\n    print("мережа:", e.errno)\n'
        (ow / 'мережа.py').write_text(netpy_, encoding='utf-8')
        call_ = f'» 🜔процес 【「sh」 「-c」 「{sys.executable} {ow}/мережа.py」】'
        got_ = run(['-e', f'🜂 【「процес:sh -c」】\n{call_}'], oenv)
        got2_ = run(['-e', f'🜂 【「процес:sh -c」 「взяти:127.0.0.1」】\n{call_}'], oenv)
        # запис без дозволу — ядро; і програма, і команда (з 「процес」 запис відкрито — тож тут без процесу)
        lk_ = subprocess.run([sys.executable, '-c', 'import sys, os; sys.path.insert(0, sys.argv[1]); import nigredo as n\n'
                              'n.OS_LOCK_PROCESS = True\nprint(n.os_lock(["запис"]))\n'
                              'print(len(open("/etc/hostname").read()) >= 0)\n'
                              'try:\n    open(sys.argv[2], "w")\n    print("запис: є")\nexcept OSError as e:\n    print("запис:", e.errno)\n'
                              'import socket\nsocket.socket().close()\nprint("мережа відкрита")',
                              str(ROOT / 'interpreter'), str(ow / 'не_має_зʼявитися.txt')], capture_output=True, text=True)
        check(got_.stdout == 'мережа: 1\n\n' and got2_.stdout == 'мережа: є\n\n'
              and lk_.stdout.splitlines()[1:] == ['True', 'запис: 1', 'мережа відкрита'] and not (ow / 'не_має_зʼявитися.txt').exists(),
              'замок ОС: команда (🜔процес) успадковує замок — без 「взяти」 у печатці socket() → EPERM, з ним — є; os_lock(«запис») '
              '— читання є, запис EPERM, мережа відкрита (фаза 6.1)', got_.stdout + got_.stderr + got2_.stdout + lk_.stdout + lk_.stderr)
    # main(), викликана іншою програмою, процес того, хто кличе, не замикає
    inproc_ = subprocess.run([sys.executable, '-c', 'import sys, io, contextlib; sys.path.insert(0, sys.argv[1]); import nigredo as n\n'
                              'with contextlib.redirect_stdout(io.StringIO()):\n    n.main(["-e", "🜂\\n» 1"])\n'
                              'import socket\nsocket.socket().close()\nprint("процес не замкнено")', str(ROOT / 'interpreter')],
                             capture_output=True, text=True, env=oenv)
    check(inproc_.stdout.strip() == 'процес не замкнено',
          'замок ОС: main(), викликана іншою програмою (тести, пісочниця), процес того, хто кличе, не замикає (фаза 6.1)',
          inproc_.stdout + inproc_.stderr)

    sheet = (ROOT / 'ДЛЯ_АГЕНТІВ.md').read_text(encoding='utf-8')
    check(sheet.strip() == run(['--памʼятка'], env).stdout.strip(), 'ДЛЯ_АГЕНТІВ.md збігається з інтерпретатором',
          'перегенеруйте: ngr --памʼятка > ДЛЯ_АГЕНТІВ.md')
    programs = [b for b in re.findall(r'```\n(🜂.*?)```', sheet, re.S) if '\n' in b.strip()]
    for i, block in enumerate(programs, 1):
        got = run(['-e', block], env)
        check(got.returncode == 0, f'приклад {i} з памʼятки', got.stderr)
    server.shutdown()
    print(f'\n{"усе гаразд" if not failed else f"провалено: {failed}"}')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
