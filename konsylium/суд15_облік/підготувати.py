#!/usr/bin/env python3
"""Готує суд 15 на заморожених джерелах: теки суддів, власник, хеші, зміни проти 1.1 і заява в ПРАВИЛА.md."""
import hashlib
import json
import pathlib
import subprocess
import sys

K = pathlib.Path(__file__).resolve().parent
ROOT = K.parents[1]
OLD = ROOT / 'konsylium' / 'суд14_вартість'
JUDGES = ['skeptyk', 'praktyk', 'movoznavets', 'audytor', 'novachok', 'orkestrator']
MORE = {
    'skeptyk': 'Суд 15: що в пропозиції обіцяно більше, ніж є в коді, і чи не відкрило здешевлення нового дешевого обходу.',
    'praktyk': 'Суд 15: звичайні задачі з функціями-значеннями, μ φ ⇅, памʼяттю агента й субагентами — що стало дешевшим, що дорожчим, що зламається.',
    'movoznavets': 'Суд 15: чи таблиця цін тепер одна й передбачувана для автора програми («одна ціна за одну роботу»).',
    'audytor': 'Суд 15: виняток безпеки §9 — три умови, перелік, повтор слідів 1.0 і 1.1; чи чесно це названо.',
    'novachok': 'Суд 15: MCP тут немає. Працюй лише з ПРАВИЛАМИ, нормою, памʼяткою й інструментами.',
    'orkestrator': 'Суд 15: чи може агент до запуску оцінити ціну програми (кроки як міра роботи), і однаковість Атанора й еталона.',
}


def sha(p):
    return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()


def main():
    claim = sys.argv[1]
    bin_ = max(ROOT.glob('athanor/target/*/release/athanor'), key=lambda f: f.stat().st_mtime)
    owner = {'дозволено': ['оракул', 'жереб', 'час'], 'для_тек': {}}
    for m in JUDGES:
        d = K / m
        (d / 'дані').mkdir(parents=True, exist_ok=True)
        (d / 'звіти').mkdir(exist_ok=True)
        role = (OLD / m / 'CLAUDE.md').read_text(encoding='utf-8').split('**Суд 14:')[0].rstrip()
        (d / 'CLAUDE.md').write_text(f'{role}\n\n**{MORE[m]}**\n', encoding='utf-8')
        p = str(d)
        owner['для_тек'][p] = [f'читати:{p}/дані', f'список:{p}/дані', f'писати:{p}/звіти']
    h = K / 'власник'
    h.mkdir(exist_ok=True)
    (h / 'дозволи.json').write_text(json.dumps(owner, ensure_ascii=False, indent=1), encoding='utf-8')
    (K / 'protokol').mkdir(exist_ok=True)
    rev = subprocess.run(['git', '-C', str(ROOT), 'rev-parse', '--short', 'HEAD'], capture_output=True, text=True).stdout.strip()
    files = ['interpreter/nigredo.py', 'athanor/src/interp.rs', 'athanor/src/prims.rs', 'spec/SPEC.md', 'spec/пропозиції/облік.md',
             'ДЛЯ_АГЕНТІВ.md']
    base = subprocess.run(['git', '-C', str(ROOT), 'merge-base', 'HEAD', 'main'], capture_output=True, text=True).stdout.strip()
    diff = subprocess.run(['git', '-C', str(ROOT), 'diff', base, 'HEAD', '--', 'interpreter/nigredo.py', 'athanor/src', 'albedo/src'],
                          capture_output=True, text=True).stdout
    (K / 'зміни.diff').write_text(diff, encoding='utf-8')
    lines = [f'sha256 {ROOT / f} → {sha(ROOT / f)}' for f in files] + [f'sha256 {bin_} → {sha(bin_)}']
    t = (K / 'ПРАВИЛА.md').read_text(encoding='utf-8').replace('@@КОМІТ@@', rev).replace('@@ХЕШІ@@', '\n'.join(lines)).replace('@@ЗАЯВА@@', claim).replace('@@КОРІНЬ@@', str(ROOT))
    (K / 'ПРАВИЛА.md').write_text(t, encoding='utf-8')
    print('\n'.join(lines))


if __name__ == '__main__':
    main()
