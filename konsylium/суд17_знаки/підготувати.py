#!/usr/bin/env python3
"""Готує суд 17 на заморожених джерелах: теки суддів, власник, хеші, зміни проти 1.3 і заява в ПРАВИЛА.md."""
import hashlib
import json
import pathlib
import subprocess
import sys

K = pathlib.Path(__file__).resolve().parent
ROOT = K.parents[1]
OLD = ROOT / 'konsylium' / 'суд16_глибина'
JUDGES = ['skeptyk', 'praktyk', 'movoznavets', 'audytor', 'novachok', 'orkestrator']
MORE = {
    'skeptyk': 'Суд 17: чи потрібні мові три нові гліфи, чи NFC Атанора справді дорівнює стандарту (шукай рядок, де виконавці розходяться), і чи не обіцяє пропозиція більше, ніж є в коді.',
    'praktyk': 'Суд 17: справжні задачі агента зі знаками — імена з різних джерел, чистка й перевірка тексту, групування; чи вистачає η ω γ і чого бракує одразу.',
    'movoznavets': 'Суд 17: вибір знаків і слів — η поруч із ν і μ, двобічний ω, «знак» і «категорія»; чи зрозуміє автор програми, що дасть кожен гліф, і крайні випадки значень.',
    'audytor': 'Суд 17: правило §9 «Нові гліфи в 1.x» і обіцянка сумісності; прозорість — чи знак, зроблений ω, ховає щось у виводі, сліді, печатці чи розборі.',
    'novachok': 'Суд 17: MCP тут немає. Працюй лише з ПРАВИЛАМИ, нормою, памʼяткою й інструментами: чи зрозуміє новий користувач з памʼятки, що роблять η ω γ, і чи зрозумілі помилки.',
    'orkestrator': 'Суд 17: однаковість трьох виконавців на нових гліфах (значення, помилки, кроки, слід) і що каже старий виконавець на нову програму.',
}


def sha(p):
    return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()


def main():
    claim = sys.argv[1]
    bin_ = max(ROOT.glob('athanor/target/*/release/athanor'), key=lambda f: f.stat().st_mtime)
    wasm = ROOT / 'albedo' / 'target' / 'wasm32-unknown-unknown' / 'release' / 'albedo.wasm'
    owner = {'дозволено': ['оракул', 'жереб', 'час'], 'для_тек': {}}
    for m in JUDGES:
        d = K / m
        (d / 'дані').mkdir(parents=True, exist_ok=True)
        (d / 'звіти').mkdir(exist_ok=True)
        role = (OLD / m / 'CLAUDE.md').read_text(encoding='utf-8').split('**Суд 16:')[0].rstrip()
        (d / 'CLAUDE.md').write_text(f'{role}\n\n**{MORE[m]}**\n', encoding='utf-8')
        p = str(d)
        owner['для_тек'][p] = [f'читати:{p}/дані', f'список:{p}/дані', f'писати:{p}/звіти']
    h = K / 'власник'
    h.mkdir(exist_ok=True)
    (h / 'дозволи.json').write_text(json.dumps(owner, ensure_ascii=False, indent=1), encoding='utf-8')
    (K / 'protokol').mkdir(exist_ok=True)
    rev = subprocess.run(['git', '-C', str(ROOT), 'rev-parse', '--short', 'HEAD'], capture_output=True, text=True).stdout.strip()
    files = ['interpreter/nigredo.py', 'athanor/src/lang.rs', 'athanor/src/tables.rs', 'athanor/src/uni.rs', 'athanor/src/prims.rs',
             'athanor/gen_tables.py', 'albedo/src/lib.rs', 'albedo/хост.mjs', 'spec/SPEC.md', 'spec/пропозиції/знаки.md', 'ДЛЯ_АГЕНТІВ.md',
             'самохостинг/лексер.ngr', 'самохостинг/парсер.ngr', 'examples/znaky.ngr']
    base = subprocess.run(['git', '-C', str(ROOT), 'merge-base', 'HEAD', 'main'], capture_output=True, text=True).stdout.strip()
    diff = subprocess.run(['git', '-C', str(ROOT), 'diff', base, 'HEAD', '--', 'interpreter/nigredo.py', 'athanor/src', 'athanor/gen_tables.py',
                           'albedo/src', 'spec/SPEC.md', 'самохостинг', ':(exclude)athanor/src/tables.rs', ':(exclude)athanor/src/lang.rs'], capture_output=True, text=True).stdout
    (K / 'зміни.diff').write_text(diff, encoding='utf-8')
    lines = [f'sha256 {ROOT / f} → {sha(ROOT / f)}' for f in files] + [f'sha256 {bin_} → {sha(bin_)}', f'sha256 {wasm} → {sha(wasm)}']
    t = (K / 'ПРАВИЛА.md').read_text(encoding='utf-8').replace('@@КОМІТ@@', rev).replace('@@ХЕШІ@@', '\n'.join(lines)).replace('@@ЗАЯВА@@', claim).replace('@@КОРІНЬ@@', str(ROOT))
    (K / 'ПРАВИЛА.md').write_text(t, encoding='utf-8')
    print('\n'.join(lines))


if __name__ == '__main__':
    main()
