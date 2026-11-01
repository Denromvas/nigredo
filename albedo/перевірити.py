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
    check(m.returncode == 4 and 64 <= held < 256, f'модуль, що їсть памʼять: стеля господаря (--памʼять 256) справді діє: дістав {held} МБ і зупинився', m.stdout[-200:] + m.stderr[-300:])
    for mark, what in (('', 'подія'), (' поле', 'поле «від_господаря»')):
        fg = p / 'підміна.ngr'
        fg.write_text(f'🜂 「підміна{mark}」 【「читати:дані」】\n» 1\n', encoding='utf-8')
        fx = host(env, Z, fg)
        check(fx.returncode == 4 and 'за запис господаря' in fx.stderr and 'ДІЙШОВ' not in fx.stdout, f'модуль не видасть свій запис за запис господаря: {what}', fx.stdout + fx.stderr)
    fl = p / 'повінь.ngr'
    fl.write_text('🜂 「повінь」 【「читати:дані」】\n» 1\n', encoding='utf-8')
    w = host(env, Z, fl, '--слід-розмір', '100000', '--слід', str(t / 'ф.jsonl'))
    fr = [json.loads(x) for x in (t / 'ф.jsonl').read_text(encoding='utf-8').splitlines()]
    check(w.returncode == 1 and 'слід перевищив' in w.stderr and fr[-1].get('від_господаря') is True and (t / 'ф.jsonl.дані').stat().st_size < 3 << 20,
          'модуль, що заливає сховище сліду: межу тримає господар', w.stderr[-300:])
    rec = [json.loads(x) for x in (t / 'з.jsonl').read_text(encoding='utf-8').splitlines()]
    check(sum(x['подія'] == 'дія господаря' and x['інструмент'] == 'файл.читати' for x in rec) == 1, 'дозволене читання господар записав сам, хоч злий модуль про нього змовчав', str(rec)[:400])
    check(sum(x['подія'] == 'господар відмовив' for x in rec) == 12, 'кожну відмову записав сам господар: модуль її не прибере', str(rec)[:400])
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
    (p / 'дані' / 'пиши' / 'висяче').symlink_to('../../вибито.txt')
    (p / 'дані' / 'пиши' / 'тека-посилання').symlink_to('../..')
    env2 = dict(env, NIGREDO_HOME=str(t / 'власник2'))
    (t / 'власник2').mkdir()
    (t / 'власник2' / 'дозволи.json').write_text(json.dumps({'дозволено': [f'бд.читати:{p}/дані', f'бд.писати:{p}/дані/в.db', f'бд.писати:{p}/дані/пиши', f'писати:{p}/дані/пиши']}, ensure_ascii=False), encoding='utf-8')
    prog2 = p / 'зла_база.ngr'
    prog2.write_text('🜂 「база」 【「бд.читати:дані」 「бд.писати:дані/в.db」 「бд.писати:дані/пиши」 「писати:дані/пиши」】\n» 1\n', encoding='utf-8')
    before = (b.read_bytes(), (p / 'секрет.txt').read_bytes())
    before_c = c.read_bytes()
    y = host(env2, Z, prog2, '--слід', str(p / 'дані' / 'з.jsonl'), '--бд-запис', '1000')
    got = {x.rsplit(':', 1)[0]: x.rsplit(':', 1)[1].strip() for x in y.stdout.splitlines() if ':' in x}
    check(got.get('контроль читання', '').startswith('15 SQLite format') and got.get('контроль запису') == '600', 'контроль: дозволена база читається, дозволена пишеться', y.stdout + y.stderr)
    refused = [k for k in got if not k.startswith(('контроль', 'чужий файл у теці печатки як база'))]
    check(got.get('чужий файл у теці печатки як база') == '8 ' + '00' * 8, 'печатка «бд.читати:дані» — право на бази: чужий файл у теці модуль бачить нулями', y.stdout)
    check(not (p / 'вибито.txt').exists(), 'запис через висяче посилання й посилання на теку не вийшов за теку', y.stdout)
    check(len(refused) == 20 and got['чужий номер файлу'] == '-9' and got['чи є системний файл'] == '0'
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
    wrec = [json.loads(x) for x in (t / 'wal.jsonl').read_text(encoding='utf-8').splitlines()]
    check(not any(x.get('подія') == 'господар відмовив' for x in wrec), 'законна робота з WAL не дає жодної відмови господаря', '')
    seen_ = [(x['інструмент'], x['шлях'].rsplit('/', 1)[1]) for x in wrec if x['подія'] == 'дія господаря']
    check(('бд.читати', 'w_r.db') in seen_ and ('бд.писати', 'wal.db') in seen_, 'господар сам записав, які бази відкрито й куди писано', str(seen_))
    c3 = subprocess.run([*REF, '--перевірити-слід', str(t / 'wal.jsonl'), str(pw)], capture_output=True, text=True, env=env2)
    check(c3.returncode == 0 and c3.stdout.startswith('✓'), 'слід із записами господаря проходить --перевірити-слід', c3.stdout + c3.stderr)
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
    odd = p / 'дивна.ngr'
    odd.write_text('🜂 「х」 【】\n» 「⊃ 〔модулі/м.ngr〕 — лише рядок」\n※ ⊃ 「модулі/м.ngr」 — лише коментар\n', encoding='utf-8')
    x = host(owner({'дозволено': [f'писати:{p}/модулі']}), W, odd)
    check('Error' not in x.stderr and x.returncode == 0, '«⊃» у рядку чи коментарі — не імпорт', x.stdout + x.stderr)
    sg = p / 'підписана.ngr'
    sg.write_text('🜂 「х」 【】\n» 1\n※ підпис ed25519:' + 'a' * 64 + ':' + 'b' * 128 + '\n', encoding='utf-8')
    x = host(owner({'дозволено': []}), W, sg)
    check(x.returncode == 120, 'підписану програму модуль не виконує: підпис перевіряє лише еталон', x.stdout + x.stderr)
    dup = owner({'дозволено': []})
    (pathlib.Path(dup['NIGREDO_HOME']) / 'дозволи.json').write_text('{"дозволено": [], "дозволено": ["файл.читати:' + str(p) + '/дані"]}', encoding='utf-8')
    x = host(dup, W, ask)
    check(x.returncode == 3 and 'двічі' in x.stderr, 'той самий ключ двічі у файлі власника — відмова, як в еталона', x.stdout + x.stderr)
    # обгортка: повз модуль нічого не йде мовчки, а межі задаються звичайним запуском
    WRAP = [sys.executable, str(D / 'ngr_альбедо.py')]
    wenv = owner({'дозволено': ['жереб', f'читати:{p}/дані']}, 'власник-обгортки')
    for flags in (['--сухо', str(ask)], ['-e', '🜂 【】\n» 1'], ['--тека', str(p), str(ask)]):
        x = subprocess.run([*WRAP, *flags], capture_output=True, text=True, env=wenv)
        check(x.returncode == 120 and x.stdout == '', f'обгортка: {flags[0]} ще немає в модулі — відмова, а не тихий запуск еталоном', x.stdout + x.stderr)
    x = subprocess.run([*WRAP, '--строк', '5', '--памʼять', '1500', str(ask)], capture_output=True, text=True, env=wenv)
    check(x.returncode == 0 and x.stderr == '', 'обгортка: --строк і --памʼять доходять до господаря', x.stdout + x.stderr)
    x = subprocess.run([*WRAP, '--памʼять', '512', str(ask)], capture_output=True, text=True, env=wenv)
    check(x.returncode == 2 and 'стек ядра' in x.stderr and 'упав' not in x.stderr, 'стеля памʼяті менша за стек модуля — зрозуміла відмова, а не падіння', x.stdout + x.stderr)
    x = subprocess.run([*WRAP, '--печатка', '--json', str(ask)], capture_output=True, text=True, env=wenv)
    check(x.returncode == 0 and json.loads(x.stdout or '{}').get('в_межах') is True, 'обгортка: --печатка нічого не виконує й далі йде до еталона', x.stdout + x.stderr)
    # поле «програма» — як задано, тобто той самий слід, що в Атанора, і з відносним шляхом
    rel = subprocess.run(['node', str(HOST), str(W), ask.name, '--слід', str(t / 'відн.jsonl')], capture_output=True, text=True, env=wenv, cwd=p)
    first = json.loads((t / 'відн.jsonl').read_text(encoding='utf-8').splitlines()[0])
    check(rel.returncode == 0 and first['програма'] == ask.name, 'відносний шлях у сліді — як задано, а не абсолютний', str(first)[:200] + rel.stderr)
    ar = p / 'аргументи.ngr'
    ar.write_text('🜂 「аргументи」 【】\n» ⌂\n', encoding='utf-8')
    x = subprocess.run(['node', str(HOST), str(W), str(ar), '--', 'а б', '--зерно', 'в\nг'], capture_output=True, text=True, env=owner({'дозволено': []}))
    check(x.returncode == 0 and x.stdout == '【「а б」 「--зерно」 「в\\nг」】\n', 'аргументи програми доходять цілими, прапорці після «--» — не господаря', x.stdout + x.stderr)
    # ---- огляд 13б: читання тексту. Усі проби — про звичайні тексти програм; модуль тут чесний, а питання одне: що господар вважає печаткою
    def reading(text, raw=None):
        f = p / 'читання.ngr'
        f.write_bytes(raw if raw is not None else text.encode('utf-8'))
        r = subprocess.run(['node', str(HOST), '--читання'], input=str(f) + '\n', capture_output=True, text=True)
        return json.loads(r.stdout)
    tools = lambda text: [(g['tool'], g['scope'], g['quota']) for g in reading(text)['печатка']]
    check(tools('🜂 「х」\n【「читати:/」】\n» 1\n') == [], 'кінець рядка закінчує печатку: перелік на наступному рядку — не права')
    check(tools('🜂 「х」 ※ коментар\n【「читати:/」】\n') == [], 'те саме після коментаря')
    check(tools('🜂 「х」 【\n「читати:а」\n「читати:б」\n】\n» 1\n') == [('файл.читати', 'а', None), ('файл.читати', 'б', None)], 'перелік у кількох рядках — той самий перелік')
    check(tools('¦🜂 【「читати:а」】 ¦ » 1') == [('файл.читати', 'а', None)], '«¦» як кінець рядка і перед печаткою, і після неї')
    check(tools('🜂 「а\\」 【」 【「читати:а」】\n') == [('файл.читати', 'а', None)], 'екранована лапка не закриває намір')
    check(tools('🜂 【「читати:а\\qб」】\n') == [('файл.читати', 'а\\qб', None)], 'невідоме екранування лишається, як у лексері')
    check(tools('🜂 【「читати:а ≤ 3」 「писати список:б≤2」】\n') == [('файл.читати', 'а', 3), ('файл.писати', 'б', 2), ('файл.список', 'б', 2)], 'квота: пробіли навколо ≤ і кілька інструментів, як split_quota')
    for bad_seal, what in (('🜂 【「читати:а≤0」】\n', 'квота ≤0'), ('🜂 【「читати:а≤1≤2」】\n', 'дві квоти'), ('🜂 【「читати:а≤1б」】\n', 'квота не в кінці'),
                           ('🜂 「х」 】\n', 'після наміру не перелік'), ('🜂 【「а」 ⊢】\n', 'у переліку не рядок'), ('🜂 【「а」】 ⊢\n', 'щось після переліку'),
                           ('🜂 「х\n', 'незакритий рядок'), ('🜂 【「а」\r】\n', 'сам по собі \\r')):
        check('відмова' in reading(bad_seal), f'господар відмовляється читати: {what}', str(reading(bad_seal)))
    check(reading('\ufeff🜂 【「читати:а」】\n')['печатка'] is None, 'мітка порядку байтів перед печаткою: печатки немає, як у мові')
    check(reading('※ 🜂 【「читати:а」】\n🜂 「б」 【】\n')['печатка'] == [], 'коментар не печатка')
    check(reading('🜂 【】\n» 「\n※ підпис ed25519:」\n»1\n')['підпис'] is False and reading('🜂 【】\n※ підпис ed25519:а\n')['підпис'] is True, 'рядок підпису — лише коментар, а не текст у рядку')
    multi = p / 'багаторядковий.ngr'
    multi.write_text('🜂 「х」 【】\n» 「а\n※ підпис ed25519:б\nв」\n» 1\n', encoding='utf-8')
    x = subprocess.run([*WRAP, str(multi)], capture_output=True, text=True, env=owner({'дозволено': []}))
    check(x.returncode == 0 and '※ підпис' in x.stdout, 'текст, схожий на підпис, у рядку не заважає запуску', x.stdout + x.stderr)
    guard = p / 'гард.ngr'
    guard.write_text('🜂 「х」 【】\n» ‖ 【λ _ 1 λ _ 2】\n', encoding='utf-8')
    x = subprocess.run([*WRAP, str(guard)], capture_output=True, text=True, env=owner({'дозволено': []}))
    check('— еталон' not in x.stdout + x.stderr, 'відмова модуля не обіцяє еталона: запасного шляху немає', x.stdout + x.stderr)
    imports = lambda text: reading(text)['імпорти']
    check(imports('🜂 【】\n» 「⊃ 「а.ngr」\n') == [] and imports('🜂 【】\n» 〔⊃ 「а.ngr」〕\n') == [] and imports('🜂 【】\n※ ⊃ 「а.ngr」\n') == [],
          'імпорт у рядку, тексті шаблону чи коментарі — не імпорт')
    check(imports('🜂 【】\n» 〔{⊃ 「а.ngr」 【「ф」】}〕\n') == ['а.ngr'], 'дірка шаблону — код: імпорт у ній господар бачить, як лексер')
    check('відмова' in reading('🜂 【】\n» 〔{1\n}〕\n'), 'дірка шаблону — в одному рядку')
    check(imports('🜂 【】\n» 〔а\\{⊃ 「а.ngr」\\}〕\n') == [], 'екрановані дужки шаблону — лише текст')
    nonutf = p / 'не_utf.ngr'
    nonutf.write_bytes('🜂 【】\n» 「'.encode() + b'\xff' + '」\n'.encode())
    x = host(owner({'дозволено': []}), W, nonutf)
    check(x.returncode == 2 and 'UTF-8' in x.stderr, 'текст не в UTF-8 господар не читає: заміна байтів дала б іншу програму', x.stdout + x.stderr)
    # «~» розгортається лише в записах власника: у печатці це ім'я теки, як у мові
    tilde = p / 'тільда.ngr'
    tilde.write_text('🜂 「х」 【「читати:~/дані」】\n» 1\n', encoding='utf-8')
    plain_seal = p / 'без_тільди.ngr'
    plain_seal.write_text('🜂 「х」 【「читати:дані」】\n» 1\n', encoding='utf-8')
    home_env = dict(owner({'дозволено': ['читати:~/дані']}), HOME=str(p))
    x, x0 = host(home_env, W, tilde), host(home_env, W, plain_seal)
    check(x.returncode == 3 and x0.returncode == 0, '«~» у печатці — не дім, а в записі власника — дім', x.stderr + x0.stderr)
    lang = subprocess.run([*REF, '--печатка', '--json', str(tilde)], capture_output=True, text=True, env=home_env)
    check(json.loads(lang.stdout or '{}').get('в_межах') is False, 'контроль: мова читає так само', lang.stdout[:300])
    # файл власника: те, що еталон відкидає, не дає прав і тут
    for rights, what in (({'дозволено': ['файл.читати≤0']}, 'квота ≤0'), ({'дозволено': ['файл.читати≤1≤2']}, 'дві квоти'), ({'дозволено': 'файл.читати'}, 'рядок замість списку'),
                         ({'дозволено': [1]}, 'не рядок у списку'), ({'для_тек': [f'{p}']}, '«для_тек» — не словник'), ({'для_тек': {str(p): 'файл.читати'}}, '«для_тек»: рядок замість списку'),
                         ({'для_програм': {'а' * 64: ['жереб'], 'А' * 64: ['час']}}, 'той самий відбиток двічі'), ({'для_авторів': {'ключ': {'дозволи': []}}}, 'ключ автора не простої форми'),
                         ({'для_авторів': {'ed25519:' + 'a' * 64: {}}}, 'автор без дозволів'),
                         ({'для_авторів': {'ed25519:' + 'a' * 64: {'дозволи': [], 'ще': 1}}}, 'зайве поле автора'),
                         ({'джерела_модулів': ['example.com']}, 'джерело не github.com'), ({'джерела_модулів': 'github.com'}, 'джерела — рядок')):
        x = host(owner(rights), W, ask)
        check(x.returncode == 3 and 'дозволи власника' in x.stderr, f'файл власника відкинуто: {what}', x.stdout + x.stderr)
    broken = owner({})
    (pathlib.Path(broken['NIGREDO_HOME']) / 'дозволи.json').write_bytes(b'{"\xff": []}')
    x = host(broken, W, ask)
    check(x.returncode == 3 and 'UTF-8' in x.stderr and 'Error' not in x.stderr, 'файл власника не в UTF-8 — відмова, а не падіння', x.stderr)
    # «для_програм» із модулями: той самий відбиток, що друкує --схвалити, і повторний імпорт теж рахується
    (p / 'чисті').mkdir()
    (p / 'чисті' / 'м.ngr').write_text('🜂 「перший」 【】\n← додай λх ＋ х 1\n', encoding='utf-8')
    (p / 'чисті' / 'другий.ngr').write_text('🜂 「другий」 【】\n⊃ 「м.ngr」 【「додай」】\n← ще λх додай х\n', encoding='utf-8')
    both = p / 'обидва.ngr'
    both.write_text('🜂 「обидва」 【「читати:дані」】\n⊃ 「чисті/м.ngr」 【「додай」】\n⊃ 「чисті/другий.ngr」 【「ще」】\n» 🜔читати 「дані/а.txt」\n', encoding='utf-8')
    plain_owner = owner({'дозволено': []})
    ap = subprocess.run([*REF, '--схвалити', str(both)], capture_output=True, text=True, env=plain_owner)
    entry = {ap.stdout.split()[1]: [f'читати:{p}/дані']}
    x = host(owner({'для_програм': entry}), W, both)
    check(ap.returncode == 0 and x.returncode == 0, 'запис --схвалити для програми з модулями діє в господарі так само', ap.stdout + ap.stderr + x.stderr)
    (p / 'чисті' / 'другий.ngr').write_text('🜂 「другий 2」 【】\n⊃ 「м.ngr」 【「додай」】\n← ще λх додай х\n', encoding='utf-8')
    check(host(owner({'для_програм': entry}), W, both).returncode == 3, 'змінено модуль — схвалення більше не діє')
    # модуль читає господар один раз, а записує, що саме читав
    one = p / 'один.ngr'
    one.write_text('🜂 「один」 【】\n⊃ 「чисті/м.ngr」 【「додай」】\n» додай 1\n', encoding='utf-8')
    x = host(owner({'дозволено': []}), W, one, '--слід', str(t / 'мод.jsonl'))
    mrec = [json.loads(z) for z in (t / 'мод.jsonl').read_text(encoding='utf-8').splitlines()]
    seen_mod = [z for z in mrec if z['подія'] == 'дія господаря' and z['інструмент'] == 'модуль']
    check(x.returncode == 0 and mrec[0]['подія'] == 'початок' and len(seen_mod) == 1 and seen_mod[0]['шлях'].endswith('чисті/м.ngr'),
          'читання модуля в сліді від господаря, а перший запис лишається «початок»', str(mrec)[:600])
    # свідка читає --перевірити-слід: відмову господаря не пропустить той, хто дивиться лише на «заборонено»
    # чесне ядро теж доходить до відмови господаря: файл із назвою журналу, що журналом не є. Програма впаде помилкою, тож слід цілий, і читач мусить побачити відмову
    jd = p / 'дані' / 'пиши' / 'ч.db'
    q = sqlite3.connect(jd)
    q.execute('CREATE TABLE т(а)')
    q.commit()
    q.close()
    fake = jd.with_name('ч.db-journal')
    fake.write_bytes(b'tse ne zhurnal')
    pj = p / 'журнал.ngr'
    pj.write_text('🜂 「журнал」 【「бд.читати бд.писати:дані/пиши」】\n» 🜔бд.писати 「дані/пиши/ч.db」 「INSERT INTO т VALUES (1)」 【】\n', encoding='utf-8')
    x = host(env2, W, pj, '--слід', str(t / 'ж.jsonl'))
    v = subprocess.run([*REF, '--перевірити-слід', str(t / 'ж.jsonl'), str(pj), '--json'], capture_output=True, text=True, env=env2)
    vj = json.loads(v.stdout or '{}')
    check(x.returncode == 1 and fake.read_bytes() == b'tse ne zhurnal', 'чужий файл із назвою журналу цілий, програма дістала помилку', x.stdout + x.stderr)
    check(vj.get('цілий') is True and (vj.get('господар') or {}).get('відмов', 0) >= 1 and any(z.startswith('господар: ') for z in vj.get('заборонено', [])),
          '--перевірити-слід показує відмову господаря серед «заборонено» й рахує його записи', v.stdout[:900])
    v = subprocess.run([*REF, '--перевірити-слід', str(t / 'ж.jsonl'), str(pj)], capture_output=True, text=True, env=env2)
    check('записів господаря' in v.stdout and 'господар: ' in v.stdout, 'те саме в тексті для людини', v.stdout[:900])
    fake.unlink()
    x = host(env2, W, pj, '--слід', str(t / 'ж2.jsonl'), '--бд-запис', '100')
    v = subprocess.run([*REF, '--перевірити-слід', str(t / 'ж2.jsonl'), str(pj), '--json'], capture_output=True, text=True, env=env2)
    vj = json.loads(v.stdout or '{}')
    check(x.returncode == 1 and vj.get('цілий') is True and not vj.get('заборонено') and any('понад межу запису' in z for z in vj.get('квоту_вичерпано', [])),
          'межа --бд-запис — оголошена межа, а не «заборонено»', x.stderr + v.stdout[:900])
    # прапорці: значення перевіряються, бо NaN вимикав межу мовчки
    for args, what in ((['--бд-запис', 'abc'], 'число'), (['--строк', 'abc'], 'число'), (['--памʼять', 'abc'], 'число'), (['--строк', '0'], 'межі'), (['--строк', '3000000'], 'межі'),
                       (['--памʼять', '5000'], 'межі'), (['--кроки', '-1'], 'межі'), (['--зерно', 'x'], 'ціле')):
        x = subprocess.run(['node', str(HOST), *args, str(W), str(ask)], capture_output=True, text=True, env=wenv)
        check(x.returncode == 2 and x.stdout == '' and args[0] in x.stderr and 'Error' not in x.stderr, f'прапорець {" ".join(args)}: відмова до запуску', x.stdout + x.stderr)
    x = subprocess.run(['node', str(HOST), str(W), str(ask), '--строк'], capture_output=True, text=True, env=wenv)
    check(x.returncode == 2 and 'бракує значення' in x.stderr, 'прапорець без значення — відмова', x.stderr)
    x = subprocess.run(['node', str(HOST), '--памʼять', '1100', str(W), str(ask)], capture_output=True, text=True, env=wenv)
    check(x.returncode == 0 and 'упав' not in x.stderr, '--памʼять трохи більша за стек ядра: працює', x.stdout + x.stderr)
    cwd2 = t / 'порожня'
    cwd2.mkdir()
    x = subprocess.run(['node', str(HOST), str(W), str(ask), '--слід', '-'], capture_output=True, text=True, env=wenv, cwd=cwd2)
    check(x.returncode == 0 and not list(cwd2.iterdir()) and '"подія": "початок"' in x.stderr, '--слід - друкує слід, а не створює файл «-»', x.stderr[:300])
    huge = p / 'зерно.ngr'
    huge.write_text('🜂 「зерно」 【「жереб」】\n» 🜔жереб 1000000\n» 🜔жереб 1000000\n', encoding='utf-8')
    big = '1' + '0' * 40
    x, y2 = (subprocess.run(c, capture_output=True, text=True, env=wenv) for c in (['node', str(HOST), str(W), str(huge), '--зерно', big], [*REF, '--зерно', big, str(huge)]))
    z2 = subprocess.run(['node', str(HOST), str(W), str(huge), '--зерно', '0'], capture_output=True, text=True, env=wenv)
    check(x.returncode == 0 and x.stdout == y2.stdout, 'зерно більше за i64: той самий вивід, що в еталона', x.stdout + y2.stdout + x.stderr)
    check(z2.stdout != x.stdout, 'контроль: зерно 0 дає інше: велике не стало нулем')
    long_ = p / 'довгий.ngr'
    long_.write_text( '🜂 「довгий」 【】\n' + '» 「рядок」\n' * 20000, encoding='utf-8')
    pipe = subprocess.run(f'node {HOST} {W} {long_} | head -1 >/dev/null; echo ${{PIPESTATUS[0]}}', shell=True, executable='/bin/bash', capture_output=True, text=True, env=wenv)
    check('упав' not in pipe.stderr and pipe.stdout.strip() in ('0', '1'), 'читач закрив трубу: це не падіння модуля', pipe.stdout + pipe.stderr[-300:])
    # обгортка: перше слово вирішує, що це за запуск; виконавця не обходить жодне сполучення
    for flags, what in ((['--печатка', '--repl'], 'службове з REPL'), (['--перевірити', '--тести', str(ask)], 'службове з тестами'), (['--печатка', str(ask), '--сухо'], 'службове із сухим'), (['--repl'], 'REPL'),
                        ([str(ask), '--печатка'], 'службове слово після програми')):
        x = subprocess.run([*WRAP, *flags], capture_output=True, text=True, env=wenv, stdin=subprocess.DEVNULL)
        check(x.returncode == 120 and x.stdout == '', f'обгортка: {what} — відмова, а не тихий запуск еталона', x.stdout + x.stderr)
    tr = t / 'значення-прапорця'
    tr.mkdir()
    x = subprocess.run([*WRAP, '--слід', '--печатка', str(ask)], capture_output=True, text=True, env=wenv, cwd=tr)
    check(x.returncode == 0 and (tr / '--печатка').exists(), '«--печатка» як значення --слід — ім\'я файлу: запуск іде через модуль, а не еталон', x.stdout + x.stderr)
print('\nусе гаразд' if not bad else f'\nпровалено: {bad}')
sys.exit(1 if bad else 0)
