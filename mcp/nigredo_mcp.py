#!/usr/bin/env python3
"""MCP-сервер Nigredo (stdio, JSON-RPC 2.0, без залежностей).

Дає будь-якому агентові з підтримкою MCP мову Nigredo без встановлення й без читання документації:
стисла памʼятка вбудована в опис інструментів.

  claude mcp add nigredo -- python3 /шлях/до/Nigredo/mcp/nigredo_mcp.py

Програми виконуються еталонним інтерпретатором як програми з робочої теки ($NIGREDO_WORKDIR, типово
~/nigredo-робоча — поза текою власника) з дозволами власника для цієї теки (~/.nigredo/дозволи.json,
«для_тек») — сервер нічого не дозволяє понад них. Кожен запуск лишає підписаний слід у $NIGREDO_HOME/сліди/.
"""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.realpath(__file__))
NGR = os.path.join(HERE, '..', 'interpreter', 'nigredo.py')
WORKDIR = os.path.realpath(os.path.expanduser(os.environ.get('NIGREDO_WORKDIR', '~/nigredo-робоча')))
OWNER_HOME = os.path.realpath(os.path.expanduser(os.environ.get('NIGREDO_HOME', '~/.nigredo')))
TRACES = os.path.join(OWNER_HOME, 'сліди')
PROTOCOL = '2024-11-05'


def ngr(*args, timeout=120):
    try:
        p = subprocess.run([sys.executable, NGR, *args], capture_output=True, text=True, cwd=WORKDIR,
                           timeout=timeout, stdin=subprocess.DEVNULL, env=dict(os.environ, NIGREDO_SHOW_TRACE='1'))
        return p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired:
        return 124, '', f'✗ перевищено час ({timeout} с)'


def sheet():
    return ngr('--памʼятка-коротка')[1]


def tools():
    short = sheet()
    code = {'type': 'string', 'description': 'Програма на Nigredo (перший рядок — печатка 🜂).'}
    return [
        {'name': 'nigredo_pamyatka',
         'description': 'Стисла памʼятка мови Nigredo: синтаксис, усі гліфи з арністю, інструменти, приклад.',
         'inputSchema': {'type': 'object', 'properties': {}}},
        {'name': 'nigredo_pechatka',
         'description': 'Що програмі дозволено (печатка) і чи вкладається вона в дозволи власника — БЕЗ виконання. '
                        'Для отриманої від іншого агента програми — цього досить, щоб вирішити, чи її запускати.',
         'inputSchema': {'type': 'object', 'properties': {'code': code}, 'required': ['code']}},
        {'name': 'nigredo_rozbir',
         'description': 'Переклад програми українським псевдокодом — без виконання.',
         'inputSchema': {'type': 'object', 'properties': {'code': code}, 'required': ['code']}},
        {'name': 'nigredo_vykonaty',
         'description': 'Виконати програму на Nigredo. Повертає вивід, помилки, код виходу і шлях до підписаного сліду. '
                        'Дії — лише в межах печатки і дозволів власника. ВАЖЛИВО: клієнт може нормалізувати '
                        'гліфи в цьому описі (повноширинні ＋ － ＝ стають + - =) — точні гліфи бери з результату '
                        'nigredo_pamyatka, виклич її першою.\n\n' + short,
         'inputSchema': {'type': 'object', 'properties': {
             'code': code,
             'args': {'type': 'array', 'items': {'type': 'string'}, 'description': 'Аргументи програми (⌂).'}},
             'required': ['code']}},
        {'name': 'nigredo_pereviryty_slid',
         'description': 'Перевірити підписаний слід виконання: цілість, підписи, чи не обрізано.',
         'inputSchema': {'type': 'object', 'properties': {'path': {'type': 'string'}}, 'required': ['path']}},
    ]


def call(name, a):
    if name == 'nigredo_pamyatka':
        return sheet(), False
    if name == 'nigredo_pechatka':
        rc, out, err = ngr('--печатка', '--тека', WORKDIR, '-e', a['code'])
        return (out or err).strip(), rc != 0
    if name == 'nigredo_rozbir':
        rc, out, err = ngr('--розбір', '--тека', WORKDIR, '-e', a['code'])
        return (out or err).strip(), rc != 0
    if name == 'nigredo_vykonaty':
        args = [str(x) for x in a.get('args', [])]
        rc, out, err = ngr('--тека', WORKDIR, '-e', a['code'], *(['--', *args] if args else []))
        trace = None
        lines = []
        for line in err.splitlines():           # шлях до сліду дає сам інтерпретатор — не вгадуємо
            if line.startswith('слід: ') and trace is None:
                trace = line[len('слід: '):]
            else:
                lines.append(line)
        err = '\n'.join(lines)
        text = f'код виходу: {rc}\n--- вивід ---\n{out}'
        if err.strip():
            text += f'--- помилки ---\n{err}\n'
        if trace:
            text += f'--- слід ---\n{trace}'
        return text, rc != 0
    if name == 'nigredo_pereviryty_slid':
        real = os.path.realpath(os.path.join(TRACES, a['path']))
        if not (real.startswith(TRACES + os.sep) and real.endswith('.jsonl')):
            return '✗ перевіряю лише сліди з теки слідів власника', True
        rc, out, err = ngr('--перевірити-слід', real)
        return (out or err).strip(), rc != 0
    raise KeyError(name)


def reply(id_, result=None, error=None):
    msg = {'jsonrpc': '2.0', 'id': id_}
    if error:
        msg['error'] = error
    else:
        msg['result'] = result
    sys.stdout.write(json.dumps(msg, ensure_ascii=False) + '\n')
    sys.stdout.flush()


def main():
    os.makedirs(WORKDIR, exist_ok=True)
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            reply(None, error={'code': -32700, 'message': 'parse error'})
            continue
        method, id_ = msg.get('method'), msg.get('id')
        if id_ is None:                     # сповіщення (notifications/initialized тощо)
            continue
        try:
            if method == 'initialize':
                reply(id_, {'protocolVersion': PROTOCOL, 'capabilities': {'tools': {}},
                            'serverInfo': {'name': 'nigredo', 'version': '0.4.1'}})
            elif method == 'tools/list':
                reply(id_, {'tools': tools()})
            elif method == 'tools/call':
                p = msg.get('params', {})
                text, is_err = call(p.get('name'), p.get('arguments') or {})
                reply(id_, {'content': [{'type': 'text', 'text': text}], 'isError': is_err})
            elif method == 'ping':
                reply(id_, {})
            else:
                reply(id_, error={'code': -32601, 'message': f'невідомий метод {method}'})
        except KeyError as e:
            reply(id_, error={'code': -32602, 'message': f'невідомий інструмент {e}'})
        except Exception as e:      # noqa: BLE001 — сервер не має падати від одного запиту
            reply(id_, error={'code': -32603, 'message': f'{type(e).__name__}: {e}'})


if __name__ == '__main__':
    main()
