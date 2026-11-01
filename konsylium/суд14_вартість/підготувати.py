#!/usr/bin/env python3
"""Готує суд 14 на заморожених джерелах: теки суддів, власник, хеші й заява в ПРАВИЛА.md."""
import hashlib
import json
import pathlib
import subprocess
import sys

K = pathlib.Path(__file__).resolve().parent
ROOT = K.parents[1]
OLD = ROOT / 'konsylium' / 'суд12б_1.0'
JUDGES = ['skeptyk', 'praktyk', 'movoznavets', 'audytor', 'novachok', 'orkestrator']
MORE = {
    'skeptyk': 'Суд 14: що в пропозиції обіцяно більше, ніж є в коді, і де Б дає дешевий обхід.',
    'praktyk': 'Суд 14: звичайні задачі, цикли зі станом, чи стало зручніше й що зламається в наявних програмах.',
    'movoznavets': 'Суд 14: чи модель вартості лишається простою й передбачуваною для автора програми.',
    'audytor': 'Суд 14: обіцянка «захист не слабшає», §9, і чи чесно це названо.',
    'novachok': 'Суд 14: MCP тут немає. Працюй лише з ПРАВИЛАМИ, нормою, памʼяткою й інструментами.',
    'orkestrator': 'Суд 14: чи може агент до запуску оцінити ціну програми, і однаковість Атанора й еталона.',
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
        role = (OLD / m / 'CLAUDE.md').read_text(encoding='utf-8')
        role = role.split('**Огляд 11б')[0].rstrip() if m == 'novachok' else role.rstrip()
        role = role.split('Роль — головний експеримент')[0].rstrip() if m == 'novachok' else role
        (d / 'CLAUDE.md').write_text(f'{role}\n\n**{MORE[m]}**\n', encoding='utf-8')
        p = str(d)
        owner['для_тек'][p] = [f'читати:{p}/дані', f'список:{p}/дані', f'писати:{p}/звіти']
    h = K / 'власник'
    h.mkdir(exist_ok=True)
    (h / 'дозволи.json').write_text(json.dumps(owner, ensure_ascii=False, indent=1), encoding='utf-8')
    (K / 'protokol').mkdir(exist_ok=True)
    rev = subprocess.run(['git', '-C', str(ROOT), 'rev-parse', '--short', 'HEAD'], capture_output=True, text=True).stdout.strip()
    files = ['interpreter/nigredo.py', 'athanor/src/interp.rs', 'spec/SPEC.md', 'spec/пропозиції/вартість.md', 'ДЛЯ_АГЕНТІВ.md']
    lines = [f'sha256 {ROOT / f} → {sha(ROOT / f)}' for f in files] + [f'sha256 {bin_} → {sha(bin_)}']
    t = (K / 'ПРАВИЛА.md').read_text(encoding='utf-8').replace('@@КОМІТ@@', rev).replace('@@ХЕШІ@@', '\n'.join(lines)).replace('@@ЗАЯВА@@', claim).replace('@@КОРІНЬ@@', str(ROOT))
    (K / 'ПРАВИЛА.md').write_text(t, encoding='utf-8')
    print('\n'.join(lines))


if __name__ == '__main__':
    main()
