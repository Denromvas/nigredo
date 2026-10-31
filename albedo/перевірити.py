#!/usr/bin/env python3
"""Альбедо, М1: перевірка межі. Значення 1.0, програма з файлами й слід через незмінний --перевірити-слід, і злий модуль
(albedo/зло), який прямо кличе імпорти господаря: межа мусить тримати без нього самого. Потрібні node і
`./зібрати.sh` в albedo/ і `cargo build --release` в albedo/зло/."""
import hashlib
import json
import os
import pathlib
import shutil
import sqlite3
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
    (p / 'сусід.ngr').write_text('🜂 「сусід」 【】\n» 1\n', encoding='utf-8')
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
    c2 = subprocess.run([*REF, '--перевірити-слід', str(t / 'с.jsonl'), str(p / 'програма.ngr')], capture_output=True, text=True, env=env)
    check('межа: модуль WebAssembly' in c2.stdout and 'замок ОС' not in c2.stdout, 'текст перевірки слідів каже про межу WebAssembly, а не про замок ОС', c2.stdout[-400:])
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
    check(len(denied) == 12 and all('відмова' in got[k] for k in denied), 'злий модуль: секрет, сусідня програма, ключ, дозволи, .., посилання, системний файл, '
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
    check(sum(x['подія'] == 'господар відмовив' for x in rec) == 11, 'кожну відмову записав сам господар: модуль її не прибере', str(rec)[:400])
    # база: SQLite живе в модулі, тож сторож у sqlite.rs для межі не рахується — лише файли в господарі
    b, c = p / 'дані' / 'б.db', p / 'дані' / 'в.db'
    q = sqlite3.connect(b)
    q.execute('CREATE TABLE т(а)')
    q.execute('INSERT INTO т VALUES (1), (2)')
    q.commit()
    q.close()
    q = sqlite3.connect(c)
    q.execute('CREATE TABLE т(а)')
    q.commit()
    q.close()
    (p / 'дані' / 'пиши').mkdir()
    (p / 'дані' / 'пиши' / 'текст.txt').write_text('не база')
    (p / 'дані' / 'посилання.db').symlink_to('../секрет.txt')
    env2 = dict(env, NIGREDO_HOME=str(t / 'власник2'))
    (t / 'власник2').mkdir()
    (t / 'власник2' / 'дозволи.json').write_text(json.dumps({'дозволено': [f'бд.читати:{p}/дані', f'бд.писати:{p}/дані/в.db', f'бд.писати:{p}/дані/пиши']}, ensure_ascii=False), encoding='utf-8')
    prog2 = p / 'зла_база.ngr'
    prog2.write_text('🜂 「база」 【「бд.читати:дані」 「бд.писати:дані/в.db」 「бд.писати:дані/пиши」】\n» 1\n', encoding='utf-8')
    before = (b.read_bytes(), (p / 'секрет.txt').read_bytes())
    before_c = c.read_bytes()
    y = host(env2, Z, prog2, '--слід', str(p / 'дані' / 'з.jsonl'), '--бд-запис', '1000')
    got = {x.rsplit(':', 1)[0]: x.rsplit(':', 1)[1].strip() for x in y.stdout.splitlines() if ':' in x}
    check(got.get('контроль читання', '').startswith('15 SQLite format') and got.get('контроль запису') == '600', 'контроль: дозволена база читається, дозволена пишеться', y.stdout + y.stderr)
    refused = [k for k in got if not k.startswith(('контроль', 'чужий файл у теці печатки як база'))]
    check(got.get('чужий файл у теці печатки як база') == '8 ' + '00' * 8, 'печатка «бд.читати:дані» — право на бази: чужий файл у теці модуль бачить нулями', y.stdout)
    check(len(refused) == 18 and got['чужий номер файлу'] == '-9' and got['чи є системний файл'] == '0'
          and all(got[k] == '-13' for k in refused if k not in ('чужий номер файлу', 'чи є системний файл')),
          'злий модуль без сторожа: чужий файл, ключ, .., посилання, журнал чужого, нова база, слід, запис і обрізання лише для читання, чужий файл у теці, видалення, понад межу — відмова',
          y.stdout + y.stderr)
    check(before == (b.read_bytes(), (p / 'секрет.txt').read_bytes()) and not (p / 'дані' / 'нова.db').exists() and c.stat().st_size >= 600
          and c.read_bytes()[600:] == before_c[600:] and (p / 'дані' / 'пиши' / 'текст.txt').read_text() == 'не база' and (p / 'дані' / 'пиши' / 'нова.db').stat().st_size == 0,
          'файли після атаки цілі: база лише для читання, секрет; нової бази немає; дозволену не стерто, запис понад межу не дійшов', '')
    rec = [json.loads(x) for x in (p / 'дані' / 'з.jsonl').read_text(encoding='utf-8').splitlines()]
    check(sum(x['подія'] == 'господар відмовив' and x['інструмент'].startswith('бд.') for x in rec) == 16, 'кожну відмову бази записав сам господар', str(rec)[:600])
    # звичайна програма: SQLite і expat працюють у модулі, а файл бази читає звичайний SQLite ззовні; сторож у модулі теж на місці
    ok = p / 'база.ngr'
    (p / 'дані' / 'пиши' / 'нова.db').unlink()
    ok.write_text('''🜂 「база й XML у модулі」 【「бд.читати бд.писати:дані/пиши」】
» 🜔бд.писати 「дані/пиши/нова.db」 「CREATE TABLE т(а INTEGER, б TEXT)」 【】
» 🜔бд.писати 「дані/пиши/нова.db」 「INSERT INTO т VALUES (?, ?), (2, 'два')」 【1 「один」】
» 🜔бд.читати 「дані/пиши/нова.db」 「SELECT а, sqrt(16) AS к FROM т ORDER BY а」 【】
» ☂ 🜔бд.писати 「дані/пиши/нова.db」 「ATTACH 'дані/б.db' AS х」 【】 λe e
» ↘ χ 「<а><б к="1">т</б></а>」 「б」
''', encoding='utf-8')
    o = host(env2, W, ok)
    lines = o.stdout.splitlines()
    check(o.returncode == 0 and lines[:2] == ['0', '2'] and '「к」 4' in lines[2] and 'attach' in lines[3].lower() and '「к」 「1」' in lines[4], 'SQLite і expat у модулі: запити, sqrt, відмова ATTACH, XML', o.stdout + o.stderr)
    q = sqlite3.connect(p / 'дані' / 'пиши' / 'нова.db')
    check(q.execute('PRAGMA integrity_check').fetchall() == [('ok',)] and q.execute('SELECT б FROM т ORDER BY а').fetchall() == [('один',), ('два',)], 'базу з модуля читає звичайний SQLite: цілісність і дані', '')
    q.close()
    check(not list((p / 'дані' / 'пиши').glob('*-journal')), 'журнал після запису прибрано')
    # WAL: чиста база, база з незлитим WAL (другий запис живе лише в -wal) і запис; спільної памʼяті модуль не створює
    wl = p / 'дані' / 'пиши' / 'wal.db'
    live = sqlite3.connect(wl)
    live.execute('PRAGMA journal_mode=WAL')
    live.execute('CREATE TABLE т(а)')
    live.execute('INSERT INTO т VALUES (1)')
    live.commit()
    live.close()
    (p / 'дані' / 'w_r.db').write_bytes(wl.read_bytes())
    live = sqlite3.connect(p / 'дані' / 'w_r.db')
    live.execute('PRAGMA wal_autocheckpoint=0')
    live.execute('INSERT INTO т VALUES (2)')
    live.commit()
    pw = p / 'wal.ngr'
    pw.write_text('''🜂 「WAL」 【「бд.читати:дані」 「бд.писати:дані/пиши」】
» 🜔бд.читати 「дані/w_r.db」 「SELECT count(*) AS н FROM т」 【】
» 🜔бд.читати 「дані/пиши/wal.db」 「SELECT count(*) AS н FROM т」 【】
» 🜔бд.писати 「дані/пиши/wal.db」 「INSERT INTO т VALUES (5)」 【】
» 🜔бд.читати 「дані/пиши/wal.db」 「SELECT sum(а) AS н FROM т」 【】
''', encoding='utf-8')
    wr = host(env2, W, pw, '--слід', str(t / 'wal.jsonl'))
    live.close()
    wlines = wr.stdout.splitlines()
    check(wr.returncode == 0 and '「н」 2' in wlines[0] and '「н」 1' in wlines[1] and wlines[2] == '1' and '「н」 6' in wlines[3], 'база WAL: читання разом із незлитим -wal, чиста WAL, запис', wr.stdout + wr.stderr)
    check(not list((p / 'дані').glob('*-shm')) and not (p / 'дані' / 'пиши' / 'wal.db-wal').exists(), 'спільної памʼяті немає, -wal після запису злито', str(list((p / 'дані').glob('*'))))
    q = sqlite3.connect(wl)
    check(q.execute('SELECT sum(а) FROM т').fetchall() == [(6,)] and q.execute('PRAGMA integrity_check').fetchall() == [('ok',)], 'WAL-базу з модуля читає звичайний SQLite', '')
    q.close()
    check(not any(x.get('подія') == 'господар відмовив' for x in map(json.loads, (t / 'wal.jsonl').read_text(encoding='utf-8').splitlines())), 'законна робота з WAL не дає жодної відмови господаря', '')
    # права власника: господар не ширший за еталон (seal.rs); кожен випадок — окрема тека власника
    def owner(rights, name='власник3'):
        o = t / name
        shutil.rmtree(o, ignore_errors=True)
        o.mkdir()
        (o / 'дозволи.json').write_text(json.dumps(rights, ensure_ascii=False), encoding='utf-8')
        return dict(env, NIGREDO_HOME=str(o))
    ask = p / 'права.ngr'
    ask.write_text('🜂 「права」 【「читати:дані」】\n» 🜔читати 「дані/а.txt」\n', encoding='utf-8')
    check(host(owner({'дозволено': ['файл.читати']}), W, ask).returncode == 3, 'запис власника без теки не покриває теки з печатки')
    check(host(owner({'дозволено': [f'читати:{p}/дані']}), W, ask).returncode == 0, 'контроль: запис власника з текою дає права')
    check(host(owner({'для_тек': {str(p): [f'читати:{p}/дані']}}), W, ask).returncode == 0, 'контроль: «для_тек» дає права')
    x = host(owner({'для_тек': {str(p): [f'читати:{p}/дані']}, 'дозволено': [f'писати:{p}']}), W, ask)
    check(x.returncode == 3, '«для_тек» не діє на програму там, куди можна писати: її могла написати інша програма', x.stderr)
    sha = hashlib.sha256(ask.read_bytes()).hexdigest()
    x = host(owner({'для_програм': {sha: [f'читати:{p}/дані']}}), W, ask)
    check(x.returncode == 0 and 'схвалено' not in x.stderr, 'контроль: «для_програм» за sha дає права саме цій програмі', x.stderr)
    check(host(owner({'для_програм': {'0' * 64: [f'читати:{p}/дані']}}), W, ask).returncode == 3, 'чужий sha у «для_програм» прав не дає')
    inside_home = owner({'дозволено': [f'читати:{t}']})
    home_seal = p / 'до_власника.ngr'
    home_seal.write_text(f'🜂 「х」 【「читати:{inside_home["NIGREDO_HOME"]}」】\n» 1\n', encoding='utf-8')
    check(host(inside_home, W, home_seal).returncode == 3, 'печатка на теку власника не проходить, навіть якщо запис власника її накриває')
    (p / 'модулі').mkdir()
    (p / 'модулі' / 'м.ngr').write_text('🜂 「модуль」 【】\n⊢ ф λх ＋ х 1\n', encoding='utf-8')
    use = p / 'з_модулем.ngr'
    use.write_text('🜂 「з модулем」 【】\n⊃ 「модулі/м.ngr」\n» 1\n', encoding='utf-8')
    x = host(owner({'дозволено': [f'писати:{p}/модулі']}), W, use)
    check(x.returncode == 3 and 'модуль лежить' in x.stderr, 'модуль з теки, куди можуть писати програми, не запускається', x.stdout + x.stderr)
    sg = p / 'підписана.ngr'
    sg.write_text('🜂 「х」 【】\n» 1\n※ підпис ed25519:' + 'a' * 64 + ':' + 'b' * 128 + '\n', encoding='utf-8')
    x = host(owner({'дозволено': []}), W, sg)
    check(x.returncode == 120, 'підписану програму модуль не виконує: підпис перевіряє лише еталон', x.stdout + x.stderr)
    ar = p / 'аргументи.ngr'
    ar.write_text('🜂 「аргументи」 【】\n» ⌂\n', encoding='utf-8')
    x = subprocess.run(['node', str(HOST), str(W), str(ar), '--', 'а б', '--зерно', 'в\nг'], capture_output=True, text=True, env=owner({'дозволено': []}))
    check(x.returncode == 0 and x.stdout == '【「а б」 「--зерно」 「в\\nг」】\n', 'аргументи програми доходять цілими, прапорці після «--» — не господаря', x.stdout + x.stderr)
print('\nусе гаразд' if not bad else f'\nпровалено: {bad}')
sys.exit(1 if bad else 0)
