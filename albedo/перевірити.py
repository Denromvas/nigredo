#!/usr/bin/env python3
"""Альбедо, М1: перевірка межі. Значення 1.0, програма з файлами й слід через незмінний --перевірити-слід, і злий модуль
(albedo/зло), який прямо кличе імпорти господаря: межа мусить тримати без нього самого. Потрібні node і
`cargo build --release` у albedo/ та albedo/зло/."""
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

D = pathlib.Path(__file__).resolve().parent
ROOT = D.parent
REL = 'target/wasm32-unknown-unknown/release'
W, Z = D / REL / 'albedo.wasm', D / 'зло' / REL / 'zlo.wasm'
HOST = D / 'хост.mjs'
REF = [sys.executable, str(ROOT / 'interpreter' / 'ngr.py')]
bad = 0


def check(ok, what, detail=''):
    global bad
    bad += not ok
    print(('✓ ' if ok else '✗ ') + what + ('' if ok else f'\n{detail}'))


def host(env, wasm, prog, *args):
    return subprocess.run(['node', str(HOST), str(wasm), str(prog), *args], capture_output=True, text=True, env=env)


with tempfile.TemporaryDirectory(prefix='альбедо-') as t:
    t = pathlib.Path(os.path.realpath(t))
    h, p = t / 'власник', t / 'програма'
    h.mkdir()
    shutil.copytree(ROOT / 'tests' / 'сумісність' / 'слід-атанор', p, ignore=shutil.ignore_patterns('слід*', 'перевірка.json'))
    (p / 'дані' / 'посилання').symlink_to('../секрет.txt')
    (h / 'дозволи.json').write_text(json.dumps({'дозволено': ['жереб', f'читати:{p}/дані']}, ensure_ascii=False), encoding='utf-8')
    env = dict(os.environ, NIGREDO_HOME=str(h))
    v = host(env, W, ROOT / 'tests' / 'сумісність' / 'значення' / 'програма.ngr')
    check(v.returncode == 0 and v.stdout == (ROOT / 'tests' / 'сумісність' / 'значення' / 'вивід.txt').read_text(encoding='utf-8'),
          'значення 1.0: вивід побайтно як у набору сумісності', v.stdout[-300:] + v.stderr[-300:])
    r = host(env, W, p / 'програма.ngr', '--зерно', '7', '--слід', str(t / 'с.jsonl'))
    check(r.returncode == 0 and r.stdout == (p / 'вивід.txt').read_text(encoding='utf-8'),
          'файли й квота через господаря: той самий вивід, що в Атанора', r.stdout[-300:] + r.stderr[-300:])
    c = subprocess.run([*REF, '--перевірити-слід', str(t / 'с.jsonl'), str(p / 'програма.ngr'), '--json'], capture_output=True, text=True, env=env)
    j = json.loads(c.stdout or '{}')
    check(c.returncode == 0 and j.get('цілий') is True and j.get('виконавець') == 'Альбедо' and (j.get('ізоляція') or {}).get('ядро') == 'wasm'
          and len(j.get('заборонено', [])) == 1 and len(j.get('квоту_вичерпано', [])) == 1,
          'слід господаря приймає незмінний --перевірити-слід: ланцюжок, HMAC, «заборонено», квота', c.stdout[:600] + c.stderr[-200:])
    wider = p / 'ширша.ngr'
    wider.write_text('🜂 【「читати:секрет.txt」】\n» 1\n', encoding='utf-8')
    g = host(env, W, wider)
    check(g.returncode == 3 and 'печатка просить більше' in g.stderr, 'печатка ширша за дозволи власника — господар не запускає модуль', g.stderr[-200:])
    prog = p / 'зла.ngr'
    prog.write_text('🜂 「невинна на вигляд」 【「читати:дані」】\n» 1\n', encoding='utf-8')
    z = host(env, Z, prog, '--слід', str(t / 'з.jsonl'))
    lines = [x for x in z.stdout.splitlines() if x]
    got = {x.split(':')[0]: x for x in lines}
    denied = [k for k in got if k not in ('контроль', 'годинник без права', 'чи є файл поза печаткою', 'справжній шлях поза печаткою')]
    check(len(denied) == 11 and all('відмова' in got[k] for k in denied), 'злий модуль: секрет, ключ, дозволи, .., посилання, системний файл, '
          'запис, список, невідома операція — відмова', z.stdout)
    check('ОТРИМАНО' in got.get('контроль', '') and 'секретний' not in z.stdout and 'не для програми' not in z.stdout,
          'контроль: дозволене читається; вмісту поза печаткою модуль не бачив', z.stdout)
    check(got.get('чи є файл поза печаткою', '').endswith(' \x00') and got.get('справжній шлях поза печаткою', '').endswith('/etc/hostname')
          and got.get('годинник без права', '').endswith('-1'), 'поза печаткою модуль не дізнається навіть, чи є файл; годинника без права немає', z.stdout)
    check(z.returncode == 4 and 'ДІЙШОВ ДО КІНЦЯ' not in z.stdout, 'підроблений номер запису сліду зупиняє модуль (код 4)', z.stdout[-200:] + z.stderr[-200:])
    check(not (p / 'зло.txt').exists() and not (h / 'зло.txt').exists(), 'запису поза печаткою не сталося')
    # ліміти тримає господар: модуль, що крутиться вічно, і модуль, що їсть памʼять, себе не зупинять
    loop = p / 'вічно.ngr'
    loop.write_text('🜂 「вічно」 【「читати:дані」】\n» 1\n', encoding='utf-8')
    k = host(env, Z, loop, '--строк', '2', '--слід', str(t / 'в.jsonl'))
    kr = [json.loads(x) for x in (t / 'в.jsonl').read_text(encoding='utf-8').splitlines()]
    check(k.returncode == 1 and 'строк 2 с' in k.stderr and kr[-1].get('від_господаря') is True, 'модуль, що крутиться вічно: господар зупиняє за строком, запис — його',
          k.stdout[-200:] + k.stderr[-300:] + str(kr)[-300:])
    hog = p / 'памʼять.ngr'
    hog.write_text('🜂 「памʼять」 【「читати:дані」】\n» 1\n', encoding='utf-8')
    m = host(env, Z, hog, '--памʼять', '256', '--слід', str(t / 'п.jsonl'))
    held = max([int(x.split()[1]) for x in m.stdout.splitlines() if x.startswith('тримаю')] or [0])
    check(m.returncode == 4 and held < 256, f'модуль, що їсть памʼять: стеля господаря (--памʼять 256), дістав {held} МБ', m.stdout[-200:] + m.stderr[-300:])
    rec = [json.loads(x) for x in (t / 'з.jsonl').read_text(encoding='utf-8').splitlines()]
    check(sum(x['подія'] == 'господар відмовив' for x in rec) == 10, 'кожну відмову записав сам господар: модуль її не прибере', str(rec)[:400])
print('\nусе гаразд' if not bad else f'\nпровалено: {bad}')
sys.exit(1 if bad else 0)
