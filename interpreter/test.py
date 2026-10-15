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
    def do_GET(self):
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
    server = http.server.HTTPServer(('127.0.0.1', 0), Redirect)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    (home / 'дозволи.json').write_text(json.dumps({'дозволено': [
        'оракул', 'жереб', 'час', f'файл.читати:{DATA}', f'файл.писати:{DATA / "звіти"}',
        f'мережа.взяти:127.0.0.1:{port}'],
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
