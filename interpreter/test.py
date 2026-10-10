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

ROOT = pathlib.Path(__file__).resolve().parent.parent
NGR = ROOT / 'interpreter' / 'nigredo.py'
DATA = ROOT / 'examples' / 'дані'


def run(args, env):
    return subprocess.run([sys.executable, str(NGR), *args], capture_output=True, text=True, env=env)


def header(src, key):
    for line in src.splitlines():
        if line.startswith(f'※ {key}:'):
            return line.split(':', 1)[1].strip()
    return None


class Redirect(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
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
            recs = [json.loads(line) for line in tfile.read_text(encoding='utf-8').splitlines()]
            ok = ok and run(['--перевірити-слід', str(tfile)], env).returncode == 0
            ok = ok and not any(r['подія'] in ('перевірка', 'інструмент') for r in recs)
        if mode == 'відмова-на-старті':
            recs = [json.loads(line) for line in tfile.read_text(encoding='utf-8').splitlines()]
            ok = ok and len(recs) == 2 and recs[-1]['подія'] == 'відмова'
            ok = ok and run(['--перевірити-слід', str(tfile)], env).returncode == 0
        if mode == 'обрізати-після-заборони':
            lines = tfile.read_text(encoding='utf-8').splitlines()
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
    junk = tmp / 'сміття.jsonl'
    junk.write_bytes(b'\0\0\0 not json\n')
    verdict = run(['--перевірити-слід', str(junk)], env)
    check(verdict.returncode == 1 and 'Traceback' not in verdict.stderr, 'перевірка сміття не падає', verdict.stderr)

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
