#!/usr/bin/env python3
"""Готує суд 16 на заморожених джерелах: теки суддів, власник, хеші, зміни проти 1.2 і заява в ПРАВИЛА.md."""
import hashlib
import json
import pathlib
import subprocess
import sys

K = pathlib.Path(__file__).resolve().parent
ROOT = K.parents[1]
OLD = ROOT / 'konsylium' / 'суд15_облік'
JUDGES = ['skeptyk', 'praktyk', 'movoznavets', 'audytor', 'novachok', 'orkestrator']
MORE = {
    'skeptyk': 'Суд 16: чи справді більше викликів нічого не додає до стека — шукай форму рекурсії, якої автор не міряв і яка важча за виміряні.',
    'praktyk': 'Суд 16: рекурсивні задачі, які агент справді пише (обхід дерева, розбір вкладеного тексту, пошук із поверненням), — що з них упиралось у 2000 викликів і чи досить 20 000.',
    'movoznavets': 'Суд 16: дві межі глибини (виклики й рівні) — чи зрозуміло авторові програми, яка спрацює і чому; чи правило тепер простіше чи складніше.',
    'audytor': 'Суд 16: обіцянка §9 — повтор слідів 1.0–1.2, поле «ліміти.виклики», слід 1.3 у старому виконавці; чи чесно названо, що лишилось.',
    'novachok': 'Суд 16: MCP тут немає. Працюй лише з ПРАВИЛАМИ, нормою, памʼяткою й інструментами: чи зрозуміє новий користувач, чому програма зупинилась на глибині.',
    'orkestrator': 'Суд 16: однаковість трьох виконавців на межі глибини (код, текст і місце зупинки, слід) і Альбедо з його стеком у модулі.',
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
        role = (OLD / m / 'CLAUDE.md').read_text(encoding='utf-8').split('**Суд 15:')[0].rstrip()
        (d / 'CLAUDE.md').write_text(f'{role}\n\n**{MORE[m]}**\n', encoding='utf-8')
        p = str(d)
        owner['для_тек'][p] = [f'читати:{p}/дані', f'список:{p}/дані', f'писати:{p}/звіти']
    h = K / 'власник'
    h.mkdir(exist_ok=True)
    (h / 'дозволи.json').write_text(json.dumps(owner, ensure_ascii=False, indent=1), encoding='utf-8')
    (K / 'protokol').mkdir(exist_ok=True)
    rev = subprocess.run(['git', '-C', str(ROOT), 'rev-parse', '--short', 'HEAD'], capture_output=True, text=True).stdout.strip()
    files = ['interpreter/nigredo.py', 'athanor/src/lang.rs', 'athanor/src/interp.rs', 'athanor/src/main.rs', 'albedo/src/lib.rs',
             'albedo/хост.mjs', 'spec/SPEC.md', 'spec/пропозиції/глибина.md', 'ДЛЯ_АГЕНТІВ.md']
    base = subprocess.run(['git', '-C', str(ROOT), 'merge-base', 'HEAD', 'main'], capture_output=True, text=True).stdout.strip()
    diff = subprocess.run(['git', '-C', str(ROOT), 'diff', base, 'HEAD', '--', 'interpreter/nigredo.py', 'athanor/src', 'albedo/src',
                           'spec/SPEC.md'], capture_output=True, text=True).stdout
    (K / 'зміни.diff').write_text(diff, encoding='utf-8')
    lines = [f'sha256 {ROOT / f} → {sha(ROOT / f)}' for f in files] + [f'sha256 {bin_} → {sha(bin_)}', f'sha256 {wasm} → {sha(wasm)}']
    t = (K / 'ПРАВИЛА.md').read_text(encoding='utf-8').replace('@@КОМІТ@@', rev).replace('@@ХЕШІ@@', '\n'.join(lines)).replace('@@ЗАЯВА@@', claim).replace('@@КОРІНЬ@@', str(ROOT))
    (K / 'ПРАВИЛА.md').write_text(t, encoding='utf-8')
    print('\n'.join(lines))


if __name__ == '__main__':
    main()
