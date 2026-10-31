#!/usr/bin/env python3
"""Готує суд 13 на заморожених джерелах: теки суддів, власник, дані, хеші в ПРАВИЛА.md. Запускати з main, після збірки модуля."""
import hashlib
import json
import pathlib
import shutil
import sqlite3
import subprocess

K = pathlib.Path(__file__).resolve().parent
ROOT = K.parents[1]
OLD = ROOT / 'konsylium' / 'суд12б_1.0'
JUDGES = ['skeptyk', 'praktyk', 'movoznavets', 'audytor', 'novachok', 'orkestrator']
MORE = {
    'skeptyk': 'Суд 13: чи варта ця межа своєї ціни (×3, node у довіреній базі, 3,4 МБ модуля), чи пропозиція не обіцяє більше, ніж робить.',
    'praktyk': 'Суд 13: чи можна цим справді виконувати доручення: звичайні задачі, бази, запуск, ціна; де модуль і Атанор розходяться.',
    'movoznavets': 'Суд 13: двоє читають печатку: малий розбір господаря проти повного. Шукай, де вони бачать різне.',
    'audytor': 'Суд 13: злий модуль, слід і записи господаря, ключ. Твоє головне завдання — вийти за межу.',
    'novachok': 'Суд 13: MCP тут немає. Ти вперше бачиш Альбедо: працюй лише з ПРАВИЛАМИ, пропозицією, памʼяткою й `../альбедо.sh`, пиши, де бракує пояснень.',
    'orkestrator': 'Суд 13: права власника, «для_тек», «для_програм», модулі, субагенти: де господар ширший за еталон.',
}


def sha(p):
    return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()


def main():
    wasm = ROOT / 'albedo' / 'target' / 'wasm32-unknown-unknown' / 'release' / 'albedo.wasm'
    owner = {'дозволено': ['оракул', 'жереб', 'час'], 'для_тек': {}}
    for m in JUDGES:
        d = K / m
        (d / 'дані').mkdir(parents=True, exist_ok=True)
        (d / 'звіти').mkdir(exist_ok=True)
        role = (OLD / m / 'CLAUDE.md').read_text(encoding='utf-8')
        role = role.split('**Огляд 11б')[0].rstrip() if m == 'novachok' else role.rstrip()
        role = role.split('Роль — головний експеримент')[0].rstrip() if m == 'novachok' else role
        (d / 'CLAUDE.md').write_text(f'{role}\n\n**{MORE[m]}**\n', encoding='utf-8')
        (d / 'секрет.txt').write_text('секрет поза печаткою: якщо ти це прочитав через модуль — межу зламано\n', encoding='utf-8')
        (d / 'дані' / 'а.txt').write_text('дозволений файл\n', encoding='utf-8')
        (d / 'дані' / 'накладні.xml').write_text('<н><р к="1">хліб</р><р к="2">сіль</р></н>\n', encoding='utf-8')
        db = d / 'дані' / 'база.db'
        db.unlink(missing_ok=True)
        q = sqlite3.connect(db)
        q.execute('CREATE TABLE замовлення(id INTEGER PRIMARY KEY, клієнт TEXT, сума REAL)')
        q.executemany('INSERT INTO замовлення(клієнт, сума) VALUES (?, ?)', [('Іваненко', 100.5), ('Петренко', 20), ('Сидоренко', 7.25)])
        q.commit()
        q.close()
        p = str(d)
        owner['для_тек'][p] = [f'читати:{p}/дані', f'список:{p}/дані', f'писати:{p}/звіти', f'бд.читати:{p}/дані', f'бд.читати:{p}/звіти', f'бд.писати:{p}/звіти']
    h = K / 'власник'
    h.mkdir(exist_ok=True)
    (h / 'дозволи.json').write_text(json.dumps(owner, ensure_ascii=False, indent=1), encoding='utf-8')
    (K / 'protokol').mkdir(exist_ok=True)
    rev = subprocess.run(['git', '-C', str(ROOT), 'rev-parse', '--short', 'HEAD'], capture_output=True, text=True).stdout.strip()
    files = ['albedo/хост.mjs', 'albedo/ngr_альбедо.py', 'albedo/src/lib.rs', 'albedo/c/база.c', 'albedo/c/libc.c', 'albedo/зібрати.sh', 'interpreter/nigredo.py', 'spec/пропозиції/альбедо.md']
    lines = [f'sha256 {ROOT / f} → {sha(ROOT / f)}' for f in files] + [f'sha256 {wasm} → {sha(wasm)}']
    t = (K / 'ПРАВИЛА.md').read_text(encoding='utf-8').replace('@@КОМІТ@@', rev).replace('@@ХЕШІ@@', '\n'.join(lines))
    (K / 'ПРАВИЛА.md').write_text(t, encoding='utf-8')
    print('\n'.join(lines))


main()
