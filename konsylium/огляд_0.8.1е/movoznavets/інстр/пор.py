"""Порівняти Атанор (ngr) і еталон на програмах: вивід, stderr, код, слід (без полів часу/запуску/хешів)."""
import json, os, subprocess, sys, time

ETALON = ['python3', '/root/ai-agents/Nigredo/interpreter/ngr.py']
ATANOR = ['/root/.local/bin/ngr']
TEKA = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SLIDY = os.path.join(TEKA, 'сліди')
MINLYVI = {'час', 'запуск', 'хеш', 'попередній', 'інтерпретатор', 'мс', 'тривалість'}


def чистий_слід(шлях):
    if not os.path.exists(шлях):
        return None
    out = []
    with open(шлях, encoding='utf-8', errors='replace') as f:
        for рядок in f:
            try:
                з = json.loads(рядок)
            except Exception:
                out.append(('НЕ-JSON', рядок))
                continue
            for k in list(з):
                if k in MINLYVI:
                    del з[k]
            out.append(з)
    return out


def запуск(cmd, args, env, stdin):
    t = time.time()
    p = subprocess.run(cmd + args, capture_output=True, env=env, input=stdin, timeout=300)
    return p.returncode, p.stdout.decode('utf-8', 'replace'), p.stderr.decode('utf-8', 'replace'), time.time() - t


def один(назва, args, stdin=None, слід=True, why=False):
    env = dict(os.environ)
    if why:
        env['ATHANOR_WHY'] = '1'
    рез = {}
    for мітка, cmd in (('А', ATANOR), ('Е', ETALON)):
        a = list(args)
        sp = None
        if слід:
            sp = os.path.join(SLIDY, f'{назва}.{мітка}.{os.getpid()}.слід')
            if os.path.exists(sp):
                os.remove(sp)
            a = a + ['--слід', sp]
        код, out, err, dt = запуск(cmd, a, env, stdin)
        рез[мітка] = (код, out, err, dt, чистий_слід(sp) if sp else None, sp)
    return рез


def main():
    argv = sys.argv[1:]
    why = False
    if argv and argv[0] == '--why':
        why = True
        argv = argv[1:]
    stdin = None
    if argv and argv[0].startswith('--stdin='):
        stdin = open(argv[0][8:], 'rb').read()
        argv = argv[1:]
    без_сліду = False
    if argv and argv[0] == '--без-сліду':
        без_сліду = True
        argv = argv[1:]
    # кожен аргумент без «--» — окремий файл; решта після «::» — спільні опції
    if '::' in argv:
        i = argv.index('::')
        файли, опції = argv[:i], argv[i + 1:]
    else:
        файли, опції = argv, []
    for f in файли:
        назва = os.path.basename(f).replace('.ngr', '')
        рез = один(назва, опції + [f], stdin, слід=not без_сліду, why=why)
        a, e = рез['А'], рез['Е']
        різне = []
        if a[0] != e[0]:
            різне.append(f'код {a[0]}≠{e[0]}')
        if a[1] != e[1]:
            різне.append('stdout')
        if a[2].replace('атанор → еталон', '') != e[2]:
            різне.append('stderr')
        if a[4] != e[4]:
            різне.append('слід')
        print(f'=== {f}: код А={a[0]} Е={e[0]}  час А={a[3]:.2f}с Е={e[3]:.2f}с  ' + ('ЗБІГ' if not різне else 'РІЗНЕ: ' + ', '.join(різне)))
        print('--- stdout А:')
        print(a[1][:3000], end='' if a[1].endswith('\n') else '\n')
        if a[1] != e[1]:
            print('--- stdout Е:')
            print(e[1][:3000], end='' if e[1].endswith('\n') else '\n')
        if a[2]:
            print('--- stderr А:')
            print(a[2][:3000], end='' if a[2].endswith('\n') else '\n')
        if a[2] != e[2]:
            print('--- stderr Е:')
            print(e[2][:3000], end='' if e[2].endswith('\n') else '\n')
        if a[4] != e[4] and a[4] is not None and e[4] is not None:
            for i, (x, y) in enumerate(zip(a[4], e[4])):
                if x != y:
                    print(f'--- слід, запис {i + 1}:\n  А: {json.dumps(x, ensure_ascii=False)[:1500]}\n  Е: {json.dumps(y, ensure_ascii=False)[:1500]}')
                    break
            if len(a[4]) != len(e[4]):
                print(f'--- слід: записів А={len(a[4])} Е={len(e[4])}')
        for мітка in 'АЕ':
            sp = рез[мітка][5]
            if sp and os.path.exists(sp):
                os.remove(sp)
                if os.path.exists(sp + '.дані'):
                    os.remove(sp + '.дані')


main()
