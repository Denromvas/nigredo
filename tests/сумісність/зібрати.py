#!/usr/bin/env python3
"""Набір сумісності 1.0 (spec/пропозиції/1.0.md §5, SPEC §9): зразки, які кожна 1.x мусить прийняти так само, як 1.0.

Запускається ОДИН раз — при оголошенні 1.0 (кандидата — `1.0-rc`, після суду 12); після оголошення зразки не
перегенеровують: інакше набір перевіряв би сам себе. `--заново` — лише до оголошення 1.0.

- `слід/` — програма з модулями (локальним і з мережі — з дзеркала на 127.0.0.1), файлами (`читати`, `список`,
  `писати`), базою (`бд.писати`, `бд.читати`) і мережею (`взяти`, `‖` понад квоту), її дані, слід і СЛІД.дані з тестовим
  ключем сліду `власник/ключ` (ключ лише для тестів, не секрет), очікуваний вивід і стабільні поля
  `--перевірити-слід --json`. У сліді — «заборонено», «квоту вичерпано», «скасовано», «модуль» (і текст модуля з мережі в
  СЛІД.дані), субагент, памʼять, «впевненість», «відсів», перехоплені помилки. Кожна 1.x мусить перевірити слід «✓» з тими самими
  полями й повторити його з тим самим виводом — і в іншій теці, без сховища й мережі.
- `слід-атанор/` — слід, записаний Атанором (поле «інтерпретатор» — `атанор:…`), і його вивід: те саме.
- `значення/` — програма, чиї значення заморожено (частка `÷`, ключі `⇅` з `●`, порядок рядків, впевненість `§` і `⚗`,
  округлення, `Δ`, `⊢`, тексти помилок виконання), і її вивід: кожна 1.x і обидва виконавці дають той самий вивід.
- `підпис/` — програма, підписана ключем «зразок 1.0» (насіння знищено одразу після підпису), відкритий ключ і вивід:
  кожна 1.x мусить сказати «підпис цілий» і з правами ключа дати той самий вивід.
- `печатка/` — програми й стабільні поля `--печатка --json` (тека — `<тека>`, шляхи власника відкинуто): кожна 1.x
  мусить мати ці поля з тими самими значеннями (нові поля — можна).
"""
import hashlib
import http.server
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import threading
import urllib.parse

D = pathlib.Path(__file__).resolve().parent
ROOT = D.parent.parent
NGR = [sys.executable, str(ROOT / 'interpreter' / 'ngr.py')]
ATH = sorted(ROOT.glob('athanor/target/*/release/athanor'))
DROP = ('тека', 'програма', 'дозволи_власника')
CHECK_DROP = ('повідомлення', 'джерело')   # --перевірити-слід --json: текст для людей і звідки взято модуль — не заморожено
TRACE_KEY = hashlib.sha256('nigredo 1.0 — тестовий ключ сліду набору сумісності'.encode()).hexdigest()
COMMIT = '4b825dc642cb6eb9a060e54bf8d69288fbee4904'      # вигаданий коміт: тотожність модуля — sha256 вмісту
SLOVA = '🜂 「слова з тексту」\n← слова λт φ ✂ ⇣ т 「 」 λс ≠ с 「」\n'.encode()
LIB = f'github.com/zrazok/ngr-lib@{COMMIT}/слова.ngr#sha256={hashlib.sha256(SLOVA).hexdigest()}'

VALUES = (                                 # значення, які 1.x не змінить (суд 12: частка, порядок, впевненість…)
    '🜂 「зразок значень 1.0」\n'
    '» ÷ 1 3\n» ÷ 10 3\n» ÷ 1 7000\n» ÷ ¯2 3\n» ÷ 100000000000000000000000000000000 3\n» ÷ 6 3\n'
    '» ≅ ¯2.5 0\n» ≅ 2.675 2\n» ⌗ ¯0.004 2\n» ‰ ¯7 3\n» ＋ 0.1 0.2\n'
    '» ↑ 【「я」 「ant」 「ґава」 「Ґ」 「б」 「а б」 「аа」】\n'
    '» 【‹ 「ґ」 「д」 ‹ 「я」 「a」 ‹ 「А」 「а」】\n'
    '← р δ 「[{"н": "А-1", "оплачено": true}, {"н": "А-2", "оплачено": false}, {"н": "А-3", "оплачено": true}]」\n'
    '» μ ⇅ р λr § r 「оплачено」 λr § r 「н」\n'
    '» ⇅ 【1 2 3 4】 λx ¿ ＝ x 1 ∅ ¿ ＝ x 2 「a」 ¿ ＝ x 3 ● 5\n'
    '← x § 【1 ≈ 2 0.5】 0\n» ± x\n» ± ⚗ 【≈ 1 0.46 ≈ 2 0.82】 0.6\n» ± 1\n'
    '» Δ 『「б」 【1 2.50 ∅ ●】 「а」 「ї」』\n» Δ ⊢ δ 「"\\\\u2060 a b\\\\u200d\\\\n"」\n'
    '» ☂ Δ 【λx x】 λe e\n» ☂ ÷ 1 ν 「0」 λe e\n» ＝ 1 1.0\n» ＝ ● 1\n'
)


def norm(v, base, drop=DROP):
    """Стабільна форма відповіді: тека програми → «<тека>», поля зі шляхами власника — геть."""
    if isinstance(v, dict):
        return {k: norm(x, base, drop) for k, x in v.items() if k not in drop}
    if isinstance(v, list):
        return [norm(x, base, drop) for x in v]
    if isinstance(v, str):
        return v.replace(base, '<тека>') if base else v
    return v


TEMP = []


def home(perms):
    # власник — поруч із зразками (і видаляється): слід записує шлях його дозволів, а тимчасова тека ОС — внутрішня
    h = pathlib.Path(tempfile.mkdtemp(prefix='.власник-', dir=D))
    TEMP.append(h)
    (h / 'ключ').write_text(TRACE_KEY + '\n', encoding='utf-8')
    (h / 'дозволи.json').write_text(json.dumps(perms, ensure_ascii=False), encoding='utf-8')
    return h


def run(args, h, cwd, cmd=None, env_extra=None):
    env = dict(os.environ, NIGREDO_HOME=str(h), **(env_extra or {}))
    env.pop('NIGREDO_TRACE_PATH_FILE', None)
    p = subprocess.run([*(cmd or NGR), *args], capture_output=True, text=True, env=env, cwd=cwd)
    if p.returncode != 0:
        sys.exit(f'✗ ngr {" ".join(args)}: код {p.returncode}\n{p.stdout}\n{p.stderr}')
    return p.stdout


class Mirror(http.server.BaseHTTPRequestHandler):
    """Дзеркало github на 127.0.0.1: /власник/репо/коміт/шлях → модуль (у справжню мережу генератор не ходить)."""

    def do_GET(self):
        path = urllib.parse.unquote(self.path)
        body = SLOVA if path.endswith('/слова.ngr') else f'сторінка {path}'.encode() if path in ('/а', '/б', '/в') else None
        self.send_response(200 if body else 404)
        self.end_headers()
        if body:
            self.wfile.write(body)

    def log_message(self, *a):
        pass


def main():
    if (D / 'слід' / 'слід.jsonl').exists() and '--заново' not in sys.argv:
        sys.exit('зразки вже є — після оголошення 1.0 їх не перегенеровують (до нього — --заново)')
    if not ATH:
        sys.exit('✗ немає зібраного Атанора (sh athanor/зібрати.sh): слід-атанор/ записує він')
    for sub in ('слід', 'слід-атанор', 'значення', 'підпис', 'печатка', 'власник'):
        shutil.rmtree(D / sub, ignore_errors=True)
        (D / sub).mkdir()
    (D / 'власник' / 'ключ').write_text(TRACE_KEY + '\n', encoding='utf-8')
    srv = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Mirror)
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    # слід: модулі (локальний і з мережі), заборонено, квота, субагент, памʼять, впевненість, відсів, щит
    s = D / 'слід'
    (s / 'дані').mkdir()
    (s / 'дані' / 'рядки.txt').write_text('Агент читає програму.\nПечатка каже, що можна.\n', encoding='utf-8')
    (s / 'секрет.txt').write_text('не для програми\n', encoding='utf-8')
    (s / 'бібліотека.ngr').write_text('🜂 「локальна бібліотека」\n← подвоїти λx × x 2\n', encoding='utf-8')
    port = srv.server_address[1]
    (s / 'програма.ngr').write_text(
        '🜂 「зразок сліду 1.0: модулі, файли, база, мережа з ‖ і квотою, регулярка, субагент, жереб і квота, памʼять, '
        'впевненість, відсів, щит, заборонено」 【「читати:дані」 「список:дані」 「писати:вихід」 「бд.писати:вихід」 '
        f'「бд.читати:вихід」 「взяти:127.0.0.1:{port}≤2」 「жереб≤3」 「оракул」】\n'
        '⊃ 「бібліотека.ngr」 【「подвоїти」】\n'
        f'⊃ 「{LIB}」 【「слова」】\n'
        '🜄 「поріг」 0.6\n'
        '← текст 🜔читати 「дані/рядки.txt」\n'
        '← знайдено ⌕ ⇣ текст 「\\w+」\n'
        '» ＋ 「слів: 」 σρзнайдено\n'
        '» ＋ 「подвоєно: 」 σ подвоїти ρ слова текст\n'
        '» ＋ 「файлів: 」 σ ρ 🜔список 「дані」\n'
        '🜔писати 「вихід/звіт.txt」 ＋ 「слів: 」 σ ρ знайдено\n'
        '» 🜔бд.писати 「вихід/база.db」 「CREATE TABLE т(слово)」 【】\n'
        '» 🜔бд.писати 「вихід/база.db」 「INSERT INTO т(слово) VALUES (?), (?)」 【§ знайдено 0 § знайдено 1】\n'
        '» Δ 🜔бд.читати 「вихід/база.db」 「SELECT count(*) AS n, min(слово) AS перше FROM т」 【】\n'
        f'» ☂ ‖ 【「/а」 「/б」 「/в」】 λu 🜔взяти ＋ 「http://127.0.0.1:{port}」 u λe 「‖ понад квоту — скасовано」\n'
        f'» 🜔взяти 「http://127.0.0.1:{port}/а」\n'
        '← кістка 🜔жереб 6\n'
        '» ＋ 「кістка: 」 σкістка\n'
        '» ☂ μ … 1 3 λi 🜔жереб 6 λe 「квоту вичерпано — перехоплено」\n'
        '» ☂ 🜔читати ＋ 「секрет」 「.txt」 λe 「заборонено — перехоплено」\n'
        '← спитати λq 🜁 「провидець」 「спитати оракула」 【「оракул」】 🜔оракул q\n'
        '» спитати 「чи світ чорніє?」\n'
        '← відповіді ⚗ 【≈ 「так」 0.9 ≈ 「ні」 0.3】 🜃「поріг」\n'
        '» ＋ 「лишилось: 」 σ ρ відповіді\n'
        '» ☂ 🜍 「ртуть」 λx ›ρx 10 λe ＋ 「щит: 」 e\n'
        '» ＋ 「поріг: 」 σ🜃「поріг」\n', encoding='utf-8')
    h = home({'дозволено': [f'читати:{s}/дані', f'список:{s}/дані', f'писати:{s}/вихід', f'бд.писати:{s}/вихід',
                            f'бд.читати:{s}/вихід', f'взяти:127.0.0.1:{port}', 'жереб', 'оракул'],
              'джерела_модулів': {'github.com': f'http://127.0.0.1:{port}/'}})
    run(['--отримати', str(s / 'програма.ngr')], h, s)
    out = run(['--зерно', '7', '--слід', str(s / 'слід.jsonl'), str(s / 'програма.ngr')], h, s)
    (s / 'вивід.txt').write_text(out, encoding='utf-8')
    chk = json.loads(run(['--перевірити-слід', str(s / 'слід.jsonl'), str(s / 'програма.ngr'), '--json'], h, s))
    (s / 'перевірка.json').write_text(json.dumps(norm(chk, '', CHECK_DROP), ensure_ascii=False, indent=1) + '\n',
                                      encoding='utf-8')
    srv.shutdown()
    shutil.rmtree(s / 'вихід')                       # що записала програма — не зразок: повтор бере записане зі сліду

    # слід-атанор: той самий формат сліду, записаний нативним виконавцем
    a = D / 'слід-атанор'
    (a / 'програма.ngr').write_text('🜂 「зразок сліду Атанора 1.0」 【「жереб≤2」】\n← xs 【3 1 2】\n» ↑ xs\n» ÷ 1 3\n'
                                    '» 🜔жереб 6\n» ⇅ 【「ґ」 「a」 「д」】 λx x\n', encoding='utf-8')
    h = home({'дозволено': ['жереб']})
    out = run(['--зерно', '7', '--слід', str(a / 'слід.jsonl'), str(a / 'програма.ngr')], h, a, cmd=[str(ATH[-1])],
              env_extra={'ATHANOR_NO_FALLBACK': '1'})
    (a / 'вивід.txt').write_text(out, encoding='utf-8')
    first = json.loads((a / 'слід.jsonl').read_text(encoding='utf-8').splitlines()[0])
    if not first['інтерпретатор'].startswith('атанор:'):
        sys.exit('✗ слід-атанор записав не Атанор')

    # значення
    v = D / 'значення'
    (v / 'програма.ngr').write_text(VALUES, encoding='utf-8')
    h = home({'дозволено': []})
    (v / 'вивід.txt').write_text(run([str(v / 'програма.ngr')], h, v), encoding='utf-8')

    # підпис
    p = D / 'підпис'
    (p / 'дані').mkdir()
    (p / 'дані' / 'а.txt').write_text('підписано 1.0\n', encoding='utf-8')
    prog = p / 'програма.ngr'
    prog.write_text('🜂 「зразок підпису 1.0」 【「читати:дані」】\n» 🜔читати 「дані/а.txt」\n', encoding='utf-8')
    kf = pathlib.Path(tempfile.mkdtemp(prefix='сумісність-ключ-')) / 'зразок.ключ'
    h = home({'дозволено': []})
    pub = run(['--ключ-автора', str(kf)], h, p).split()[0]
    run(['--підписати', str(prog), '--ключ', str(kf)], h, p)
    shutil.rmtree(kf.parent)                         # насіння знищено: підписати ще раз не може ніхто
    (p / 'ключ.txt').write_text(pub + '\n', encoding='utf-8')
    h = home({'дозволено': [], 'для_авторів': {pub: {'імʼя': 'зразок 1.0', 'дозволи': [f'читати:{p}/дані']}}})
    (p / 'вивід.txt').write_text(run([str(prog)], h, p), encoding='utf-8')

    # печатка
    q = D / 'печатка'
    progs = {
        'проста.ngr': '🜂 「проста」 【】\n» ＋ 1 2\n',
        'квоти.ngr': '🜂 「квоти й субагент」 【「читати:.」 「жереб≤2」】\n'
                     '» 🜁 「лічильник」 「кинути раз」 【「жереб≤1」】 🜔жереб 6\n',
        'міст.ngr': '🜂 「міст до Python」 【「python:statistics.median≤2」】\n» 🜔python 「statistics.median」 【【3 1 2】】\n',
    }
    h = home({'дозволено': [f'читати:{q}', 'жереб', 'python:statistics.median']})
    for name, text in progs.items():
        (q / name).write_text(text, encoding='utf-8')
        info = json.loads(run(['--печатка', '--json', str(q / name)], h, q))
        (q / (name[:-4] + '.json')).write_text(json.dumps(norm(info, str(q)), ensure_ascii=False, indent=1) + '\n',
                                               encoding='utf-8')
    for t in TEMP:
        shutil.rmtree(t, ignore_errors=True)
    print(f'зібрано: {D}')


if __name__ == '__main__':
    main()
