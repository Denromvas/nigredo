#!/usr/bin/env python3
"""ngrpy — Python-обгортка з тими самими гарантіями, що й Nigredo 0.3 (наскільки Python це дозволяє).

Створено для третього суду як найсильніший чесний суперник Nigredo, а не опудало:
  печатка       seal("намір", ["оракул", "файл.читати:дані"]) — перший рядок скрипту;
                до запуску: печатка звіряється з дозволами власника (той самий ~/.nigredo/дозволи.json),
                а в коді шукаються всі tool("…") — назва має бути буквальною і бути в печатці;
  інструменти   tool("файл.читати", "дані/x.json") — ті самі реалізації, що в Nigredo;
                права перевіряються під час кожного виклику за поточним агентом;
  делегування   with delegate("імʼя", "намір", ["оракул"]): … — підмножина прав, власна памʼять;
  памʼять       remember(k, v), recall(k);  перевірка  check(v, lambda x: …);
  впевненість   U(значення, c); арифметика й порівняння U дають мінімум; conf(x); sift(список, поріг);
                set_conf(x, c) — явно, у слід;
  слід          той самий формат і ключ, що в Nigredo (перевіряє `ngr --перевірити-слід`);
  межі          sys.addaudithook: заборонено відкривати файли, мережу, процеси, ctypes, gc-обхід,
                sys._getframe, settrace — поза інструментами.

Запуск:  python3 ngrpy.py скрипт.py [--дозволи F] [--слід F] [-- аргументи]
Чесно: документація Python прямо каже, що audit hooks — не пісочниця. Перевірити, наскільки, — завдання суду.
"""
import ast
import builtins
import hashlib
import importlib.util
import os
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.realpath(__file__))
_spec = importlib.util.spec_from_file_location('nigredo', os.path.join(HERE, '..', 'interpreter', 'nigredo.py'))
ngr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ngr)

__all__ = ['seal', 'tool', 'delegate', 'remember', 'recall', 'check', 'U', 'conf', 'sift', 'set_conf', 'value', 'ARGS']


# ------------------------------------------------------------------ впевненість

class U:
    """Значення з впевненістю. Операції з U дають мінімум упевненостей."""
    __slots__ = ('v', 'c')

    def __init__(self, v, c=1.0):
        object.__setattr__(self, 'v', v.v if isinstance(v, U) else v)
        object.__setattr__(self, 'c', min(c, v.c) if isinstance(v, U) else c)

    def __setattr__(self, *a):
        raise AttributeError('U незмінне')

    def _op(self, other, f):
        oc = other.c if isinstance(other, U) else 1.0
        ov = other.v if isinstance(other, U) else other
        return U(f(self.v, ov), min(self.c, oc))

    def __add__(self, o): return self._op(o, lambda a, b: a + b)
    def __radd__(self, o): return self._op(o, lambda a, b: b + a)
    def __sub__(self, o): return self._op(o, lambda a, b: a - b)
    def __mul__(self, o): return self._op(o, lambda a, b: a * b)
    def __truediv__(self, o): return self._op(o, lambda a, b: a / b)
    def __mod__(self, o): return self._op(o, lambda a, b: a % b)
    def __eq__(self, o): return self._op(o, lambda a, b: a == b)
    def __ne__(self, o): return self._op(o, lambda a, b: a != b)
    def __lt__(self, o): return self._op(o, lambda a, b: a < b)
    def __le__(self, o): return self._op(o, lambda a, b: a <= b)
    def __gt__(self, o): return self._op(o, lambda a, b: a > b)
    def __ge__(self, o): return self._op(o, lambda a, b: a >= b)
    def __getitem__(self, k): return U(self.v[k.v if isinstance(k, U) else k], self.c)
    def __hash__(self): return hash((self.v, self.c))
    def __repr__(self): return f'U({self.v!r}, {self.c})'

    def __str__(self): return str(self.v)

    def __bool__(self):
        raise TypeError('bool(U) губить впевненість — використайте value(x) явно або порівняння U')


def conf(x):
    """Впевненість: U — її c; список/словник — мінімум вмісту; інше — 1."""
    if isinstance(x, U):
        return min(x.c, conf(x.v))
    if isinstance(x, (list, tuple)):
        return min([1.0] + [conf(e) for e in x])
    if isinstance(x, dict):
        return min([1.0] + [conf(e) for e in x.values()])
    return 1.0


def value(x):
    return x.v if isinstance(x, U) else x


# ------------------------------------------------------------------ стан (у замиканні, не в атрибутах модуля)

def _make_runtime():
    st = {'trusted': 0, 'caps': [], 'agents': ['головний'], 'memory': [{}], 'trace': None, 'it': None,
          'allowed_read': (), 'sealed': False}

    class It:            # те, що очікують реалізації інструментів Nigredo
        pass

    def trusted(fn):
        def wrapper(*a, **k):
            st['trusted'] += 1
            try:
                return fn(*a, **k)
            finally:
                st['trusted'] -= 1
        return wrapper

    def deny(event, msg):
        st['trusted'] += 1
        try:
            st['trace']('відмова', агент=st['agents'][-1], подія_python=event, причина=msg)
        finally:
            st['trusted'] -= 1
        raise PermissionError(msg)

    def hook(event, args):
        if st['trusted'] or not st['sealed']:
            return
        if event == 'open':
            path, mode = args[0], args[1] if len(args) > 1 else 'r'
            if isinstance(path, int):
                deny(event, 'ngrpy: відкривати дескриптори напряму заборонено')
            real = os.path.realpath(path)
            if (mode in (None, 'r', 'rb') or (isinstance(mode, str) and 'w' not in mode and 'a' not in mode
                                               and '+' not in mode and 'x' not in mode)) \
                    and any(real == p or real.startswith(p + os.sep) for p in st['allowed_read']):
                return              # стандартна бібліотека й сам скрипт — лише читання
            deny(event, f'ngrpy: файл «{path}» лише через tool(...) з печатки')
        blocked = ('socket.', 'subprocess.', 'os.system', 'os.exec', 'os.posix_spawn', 'os.spawn', 'os.fork',
                   'os.kill', 'os.remove', 'os.rename', 'os.rmdir', 'os.mkdir', 'os.chmod', 'os.chown',
                   'os.link', 'os.symlink', 'os.truncate', 'os.utime', 'os.listdir', 'os.scandir', 'os.walk',
                   'shutil.', 'ctypes.', 'gc.get_', 'sys._getframe', 'sys.settrace', 'sys.setprofile',
                   'sys._current_frames', 'sys.addaudithook', 'urllib.', 'http.', 'ftplib.', 'smtplib.',
                   'webbrowser.', 'pty.', 'os.putenv', 'os.unsetenv', 'code.__new__', 'function.__new__',
                   'object.__setattr__', 'object.__delattr__', 'mmap.', 'resource.', 'signal.',
                   'sys.set_asyncgen_hooks', 'sys.setrecursionlimit', 'builtins.input', 'cpython.')
        if event.startswith(blocked) or event == 'import' and args[0] in ('ctypes', '_ctypes', 'gc', 'inspect'):
            deny(event, f'ngrpy: «{event}» заборонено (лише інструменти з печатки)')

    def cur_caps():
        return st['caps'][-1] if st['caps'] else {}

    @trusted
    def seal_(intent, caps):
        if st['sealed']:
            raise RuntimeError('печатка — лише одна')
        st['sealed'] = True
        st['caps'].append(caps_dict(caps))
        st['trace']('печатка', агент='головний', намір=str(intent), дозволи=st['caps'][-1])

    @trusted
    def tool_(name, *args):
        agent = st['agents'][-1]
        caps = cur_caps()
        vals = [a if isinstance(a, U) else U(a) for a in args]
        targs = [ngr.trace_val(ngr.V(value(a)), name in ('агент', 'мережа.взяти')) for a in vals]
        if name not in caps:
            st['trace']('відмова', агент=agent, назва=name, аргументи=targs, причина='немає в дозволах агента')
            raise PermissionError(f'агент «{agent}» не має дозволу «{name}»')
        if name not in ngr.TOOLS or ngr.TOOLS[name][0] != len(args):
            raise TypeError(f'інструмент «{name}»: невідомий або не та кількість аргументів')
        it = st['it']
        it.caps, it.agent = caps, agent
        try:
            res = ngr.TOOLS[name][5](it, None, *[ngr.V(value(a)) for a in vals])
        except ngr.NgrError as e:
            st['trace']('інструмент', агент=agent, назва=name, аргументи=targs, помилка=e.msg)
            raise RuntimeError(e.msg) from None
        c = min([res.c] + [a.c for a in vals])
        st['trace']('інструмент', агент=agent, назва=name, аргументи=targs, результат=ngr.trace_val(res), впевненість=c)
        return U(ngr.plain(res), c)

    class Delegate:
        def __init__(self, name, intent, caps):
            self.name, self.intent, self.caps = name, intent, caps_dict(caps, inherit=True)

        @trusted
        def __enter__(self):
            parent = cur_caps()
            for t, sc in self.caps.items():
                if t not in parent or any(s not in parent[t] for s in sc):
                    raise PermissionError(f'субагент «{self.name}» просить «{t}», якого немає в батька')
                if not sc:
                    self.caps[t] = list(parent[t])
            st['trace']('делегування', агент=st['agents'][-1], субагент=self.name, намір=self.intent, дозволи=self.caps)
            st['caps'].append(self.caps)
            st['agents'].append(f'{st["agents"][-1]}/{self.name}')
            st['memory'].append({})
            return self

        @trusted
        def __exit__(self, et, ev, tb):
            st['caps'].pop()
            agent = st['agents'].pop()
            st['memory'].pop()
            st['trace']('субагент впав' if et else 'субагент повернув', агент=agent, субагент=self.name,
                        **({'помилка': str(ev)} if et else {}))
            return False

    @trusted
    def remember_(key, val):
        st['memory'][-1][key] = val
        st['trace']('памʼять', агент=st['agents'][-1], дія='запамʼятати', ключ=str(key),
                    значення=ngr.trace_val(ngr.V(str(value(val)))), впевненість=conf(val))

    @trusted
    def recall_(key):
        val = st['memory'][-1].get(key)
        st['trace']('памʼять', агент=st['agents'][-1], дія='пригадати', ключ=str(key),
                    значення=ngr.trace_val(ngr.V(str(value(val)))))
        return val

    @trusted
    def check_(val, pred):
        r = pred(val)
        ok = value(r)
        if not isinstance(ok, bool):
            raise TypeError('check: умова має дати bool')
        st['trace']('перевірка', агент=st['agents'][-1], значення=ngr.trace_val(ngr.V(str(value(val)))),
                    результат='пройдена' if ok else 'НЕ пройдена')
        if not ok:
            raise AssertionError(f'перевірку не пройдено для {value(val)!r}')
        return val

    @trusted
    def sift_(items, threshold):
        kept = []
        for x in items:
            ok = conf(x) >= threshold
            st['trace']('відсів', агент=st['agents'][-1], значення=ngr.trace_val(ngr.V(str(value(x)))),
                        впевненість=conf(x), поріг=threshold, рішення='лишено' if ok else 'відкинуто')
            if ok:
                kept.append(x)
        return kept

    @trusted
    def set_conf_(x, c):
        st['trace']('впевненість', агент=st['agents'][-1], значення=ngr.trace_val(ngr.V(str(value(x)))),
                    було=conf(x), стало=c)
        return U(value(x), c)

    real_print = builtins.print

    @trusted
    def print_(*a, **k):
        text = ' '.join(str(x) for x in a)
        st['trace']('вивід', агент=st['agents'][-1], текст=ngr.trace_val(ngr.V(text)))
        real_print(*a, **k)

    return st, It, hook, dict(seal=seal_, tool=tool_, delegate=Delegate, remember=remember_, recall=recall_,
                              check=check_, sift=sift_, set_conf=set_conf_, print=print_)


def caps_dict(caps, inherit=False):
    out = {}
    for entry in caps:
        name, _, scope = str(entry).partition(':')
        name = name.strip()
        if name not in ngr.TOOLS:
            raise ValueError(f'невідомий інструмент у дозволах: «{name}»')
        if ngr.TOOLS[name][3] and not scope.strip() and not inherit:
            raise ValueError(f'«{name}» потребує обмеження')
        out.setdefault(name, []).extend([scope.strip()] if scope.strip() else [])
    return out


_ST, _It, _HOOK, _API = _make_runtime()
seal, tool, delegate = _API['seal'], _API['tool'], _API['delegate']
remember, recall, check = _API['remember'], _API['recall'], _API['check']
sift, set_conf = _API['sift'], _API['set_conf']
ARGS = []
del _make_runtime


# ------------------------------------------------------------------ статична перевірка й запуск

def static_seal(src, path):
    """Печатка — перший вираз seal("…", [буквальні рядки]); кожен tool(...) — з буквальною назвою з печатки."""
    tree = ast.parse(src, path)
    body = [n for n in tree.body if not isinstance(n, (ast.Import, ast.ImportFrom))]   # імпорти — до печатки
    first = body[0] if body else None
    ok = (isinstance(first, ast.Expr) and isinstance(first.value, ast.Call) and getattr(first.value.func, 'id', '') == 'seal'
          and len(first.value.args) == 2 and isinstance(first.value.args[0], ast.Constant)
          and isinstance(first.value.args[1], ast.List)
          and all(isinstance(e, ast.Constant) and isinstance(e.value, str) for e in first.value.args[1].elts))
    if not ok:
        raise SyntaxError('ngrpy: перший вираз — seal("намір", ["дозвіл", …]) з буквальними рядками')
    caps = caps_dict([e.value for e in first.value.args[1].elts])
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, 'id', '') == 'tool':
            if not node.args or not isinstance(node.args[0], ast.Constant):
                raise SyntaxError(f'ngrpy: рядок {node.lineno}: назва інструмента має бути буквальною')
            if node.args[0].value not in caps:
                raise SyntaxError(f'ngrpy: рядок {node.lineno}: інструмента «{node.args[0].value}» немає в печатці')
    return first.value.args[0].value, caps


def main(argv):
    narrow = trace_copy = None
    rest = []
    it = iter(argv)
    for a in it:
        if a == '--дозволи':
            narrow = next(it)
        elif a == '--слід':
            trace_copy = next(it)
        elif a == '--':
            ARGS.extend(it)
        else:
            rest.append(a)
    if len(rest) != 1:
        print(__doc__, file=sys.stderr)
        return 2
    path = os.path.realpath(rest[0])
    src = open(path, encoding='utf-8').read()
    try:
        intent, caps = static_seal(src, path)
    except SyntaxError as e:
        print(f'✗ {e}', file=sys.stderr)
        return 2
    cwd = os.path.dirname(path)
    allowed, source = ngr.load_allowlist(narrow)
    missing = ngr.check_allowlist(caps, allowed, cwd)
    sha = hashlib.sha256(src.encode()).hexdigest()
    os.makedirs(os.path.join(ngr.OWNER_HOME, 'сліди'), mode=0o700, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')
    main_trace = os.path.join(ngr.OWNER_HOME, 'сліди', f'{stamp}-{sha[:8]}-{os.getpid()}-py.jsonl')
    paths = [main_trace] + ([os.path.realpath(trace_copy)] if trace_copy else [])
    outs = [open(p, 'x', encoding='utf-8') for p in paths]
    trace = ngr.Trace(outs, ngr.owner_key())
    _ST['trace'] = trace
    trace('початок', версія='ngrpy', програма=path, sha256=sha[:16], аргументи=ARGS, дозволи_власника=source, дозволено=allowed)
    if missing:
        trace('відмова', бракує=missing)
        print(f'✗ печатка просить більше, ніж дозволив власник: {", ".join(missing)}', file=sys.stderr)
        return 3
    it_ = _It()
    it_.cwd, it_.rng, it_.protected = cwd, __import__('random').Random(0), set(paths)
    _ST['it'] = it_
    stdlib = {os.path.realpath(p) for p in sys.path if p and os.path.isdir(p) and p != cwd}
    _ST['allowed_read'] = tuple(stdlib | {path, HERE, os.path.realpath(os.path.join(HERE, '..', 'interpreter'))})
    sys.modules['ngrpy'] = sys.modules[__name__]
    builtins.print = _API['print']
    sys.addaudithook(_HOOK)
    code = compile(src, path, 'exec')
    glb = {'__name__': '__main__', '__file__': path, '__builtins__': builtins}
    try:
        exec(code, glb)
        trace('кінець')
        return 0
    except BaseException as e:   # noqa: BLE001 — будь-яка помилка скрипту фіксується в сліді
        trace('помилка', повідомлення=f'{type(e).__name__}: {e}')
        sys.stderr.write(f'✗ {type(e).__name__}: {e}\n')
        return 1
    finally:
        for o in outs:
            o.close()


if __name__ == '__main__':
    sys.modules.setdefault('ngrpy', sys.modules['__main__'])
    sys.exit(main(sys.argv[1:]))
