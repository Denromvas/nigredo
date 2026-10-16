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
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse

ROOT = pathlib.Path(__file__).resolve().parent.parent
NGR = ROOT / 'interpreter' / 'ngr.py'
DATA = ROOT / 'examples' / 'дані'


def run(args, env):
    return subprocess.run([sys.executable, str(NGR), *args], capture_output=True, text=True, env=env)


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
    def do_POST(self):
        body = self.rfile.read(int(self.headers.get('Content-Length', 0)))
        self.send_response(200)
        self.send_header('Content-Type', 'text/plain; charset=utf-8')
        self.end_headers()
        self.wfile.write(b'got ' + self.headers.get('Content-Type', '').encode() + b' ' + body)

    def do_GET(self):
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
    check(got.returncode == 1 and 'елемент №1' in got.stderr and evs == ['інструмент', 'заборонено', 'інструмент', 'інструмент'],
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
    # суд 7 (Новачок)
    got = run(['-e', bseal + f'» ☂ ρ 🜔бд.читати 「{bd}/a.db」 「SELECT group_concat(hex(zeroblob(200000000))) AS z」 【】 λe 「межа」'], benv)
    check(got.stdout == 'межа\n', 'бд.читати: памʼять SQLite обмежено — помилка програми, не код 4', got.stdout + got.stderr[-300:])
    got = run(['--перевірити', '-e', '🜂\n» ‖ 【1】 λx x\n» ‖ 【1】 λx ＋ x 1'], env)
    check(got.stdout.count('‖ список') == 2, '--перевірити: усі помилки ‖, а не лише перша', got.stdout)
    short = run(['--памʼятка-коротка'], env).stdout
    check('бд.читати:тека' in short and 'процес:git status' in short and '‖ список' in short and 'Шлях' in short,
          'коротка памʼятка (MCP): дозволи бд/процес, правило шляхів, обмеження ‖', short[:500])
    got = run(['-e', '🜂 「лише намір」\n» 1'], env)
    check(got.returncode == 0, 'печатка лише з наміром (без 【】) — без дозволів')
    seal = run(['--печатка', str(ROOT / 'examples' / 'ahent.ngr')], env).stdout
    check('права теки: немає' in seal and 'намір (слова автора): 「' in seal and 'необхідно, але не досить' in seal,
          '--печатка: слова автора в 「」, «права теки: немає», «необхідно, але не досить»', seal)
    p = subprocess.Popen([sys.executable, str(NGR), '-e', '🜂 「багато рядків」 【】\n∀ …1 100000 λi » i'],
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    p.stdout.readline()
    p.stdout.close()
    err = p.stderr.read().decode()
    p.wait()
    check(p.returncode != 4 and 'внутрішня' not in err and 'Exception' not in err, 'обірвана труба — тихо, не «вада мови»', err)
    got = subprocess.run([sys.executable, str(NGR), '-e', '🜂 「а」 【】\n» ⌂', '--', os.fsdecode(b'\xff')],
                         capture_output=True, text=True, env=penv)
    tr = pathf.read_text(encoding='utf-8')
    check(got.returncode == 2 and 'не UTF-8' in got.stderr and 'Traceback' not in got.stderr
          and run(['--перевірити-слід', tr], env).returncode == 0, 'аргумент не UTF-8 — відмова зі слідом', got.stderr)
    mcp = ROOT / 'mcp' / 'nigredo_mcp.py'
    work = tmp / 'робоча'
    work.mkdir()
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
    os.environ.setdefault('NIGREDO_HOME', str(home))
    spec = importlib.util.spec_from_file_location('nigredo_тест', ROOT / 'interpreter' / 'nigredo.py')
    M = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(M)
    import decimal
    decimal.setcontext(M.DEC_CTX.copy())
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
