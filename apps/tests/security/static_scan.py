"""
apps/tests/security/static_scan.py

AST / text scanners behind test_static_guards.py. Every scanner returns a set of
stable entries — "path::Qualname" for code sites, "path:pattern" for text hits —
so they can be compared with a baseline (see baseline.py).
"""
import ast
import re
import subprocess

from .baseline import REPO_ROOT, norm

SCAN_ROOTS = ('apps', 'core', 'config', 'scripts')
_SKIP_PARTS = ('apps/tests/', '/migrations/', '__pycache__')


def python_files(roots=SCAN_ROOTS):
    for root in roots:
        for p in sorted((REPO_ROOT / root).rglob('*.py')):
            rel = norm(p)
            if not any(s in rel or rel.startswith(s) for s in _SKIP_PARTS):
                yield p


def parse_file(path):
    """ast for a source file; utf-8-sig because several files carry a BOM."""
    return ast.parse(path.read_text(encoding='utf-8-sig'))


def repo_sites(scanner) -> set:
    """Run a (tree, path) scanner over every scanned Python file.

    A file that can't be parsed raises: an unscannable file is a hole in every guard."""
    found = set()
    for p in python_files():
        found |= scanner(parse_file(p), norm(p))
    return found


class _Scoped(ast.NodeVisitor):
    """NodeVisitor that knows the qualified name of the enclosing def/class."""

    def __init__(self):
        self.stack = []

    @property
    def qualname(self):
        return '.'.join(self.stack) or '<module>'

    def _scope(self, node):
        self.stack.append(node.name)
        self.enter_scope(node)
        self.generic_visit(node)
        self.leave_scope(node)
        self.stack.pop()

    visit_FunctionDef = visit_AsyncFunctionDef = visit_ClassDef = _scope

    def enter_scope(self, node):
        pass

    def leave_scope(self, node):
        pass


# ── SQL built from text ──────────────────────────────────────────────────────
#
# A site is a call that receives SQL assembled from text (f-string interpolation,
# %, .format, + with a non-literal part) instead of bound parameters:
#   * a known execute-style sink, or a same-module helper whose parameter reaches one
#     (found by fixed point), with a built argument at the SQL position; or
#   * ANY call given a built argument whose literal text has SQL statement structure
#     ("insert into x", "update x set", "select … from", "exec p" …) — catches helpers
#     defined elsewhere (_exec, _run_batch_lastrow, execute_query …).

_SQL_SINKS = {name: {0} for name in (
    'execute', 'executemany', 'executeQuery', 'executeUpdate', 'executeLargeUpdate',
    'prepareStatement', 'addBatch', 'raw', '_run', 'execute_query', 'execute_update',
    'executescript')}
_SQL_STRUCT = re.compile(
    r'(?is)\b(select\b.+?\bfrom\b|insert\s+(into\s+)?[\w.\[\]#{}%]+'
    r'|update\s+[\w.\[\]{}%]+\s+set\b|delete\s+(from\s+)?[\w.\[\]{}%]+\s+where\b|delete\s+from\b'
    r'|exec(ute)?\s+[\w.{}%]+|truncate\s+table\b|merge\s+into\b)')
_PASSTHROUGH = {'strip', 'lstrip', 'rstrip', 'replace', 'upper', 'lower', 'encode',
                'decode', 'dedent', 'str'}
_MARK_HELPERS = {'_marks', 'marks', '_placeholders', 'placeholders'}


def _is_const(node):
    return isinstance(node, ast.Constant)


def _call_name(f):
    return f.attr if isinstance(f, ast.Attribute) else f.id if isinstance(f, ast.Name) else None


def _target_key(t):
    if isinstance(t, ast.Name):
        return t.id
    if isinstance(t, ast.Attribute) and isinstance(t.value, ast.Name):
        return f'{t.value.id}.{t.attr}'
    return None


def _module_strings(tree):
    """Module-level NAME = "literal" assignments (SQL templates live there)."""
    out = {}
    for n in tree.body:
        if isinstance(n, ast.Assign) and isinstance(n.value, ast.Constant) \
                and isinstance(n.value.value, str):
            for t in n.targets:
                if isinstance(t, ast.Name):
                    out[t.id] = n.value.value
    return out


def _param_sinks(tree, sinks):
    """Same-module functions whose parameter is handed straight to a sink → sinks too."""
    sinks = {k: set(v) for k, v in sinks.items()}
    for _ in range(6):
        changed = False
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            params = [a.arg for a in fn.args.args if a.arg not in ('self', 'cls')]
            for call in ast.walk(fn):
                if not isinstance(call, ast.Call):
                    continue
                for pos in list(sinks.get(_call_name(call.func), ())):
                    arg = call.args[pos] if pos < len(call.args) else None
                    if isinstance(arg, ast.Name) and arg.id in params:
                        idx = params.index(arg.id)
                        if idx not in sinks.setdefault(fn.name, set()):
                            sinks[fn.name].add(idx)
                            changed = True
        if not changed:
            break
    return sinks


class _SqlTaint(_Scoped):
    """Per scope: `tainted` = names holding text-built SQL; `safe` = names only ever bound
    to code-constant text (fixed clauses); `poisoned` = names that once got anything else."""

    def __init__(self, path, sinks, consts):
        super().__init__()
        self.path, self.sites, self.sinks, self.consts = path, set(), sinks, consts
        self.tainted, self.safe, self.poisoned = [{}], [{}], [set()]

    def enter_scope(self, node):
        # closures see the outer names — except where a parameter shadows them
        self.tainted.append(dict(self.tainted[-1]))
        self.safe.append(dict(self.safe[-1]))
        self.poisoned.append(set(self.poisoned[-1]))
        args = getattr(node, 'args', None)
        if isinstance(args, ast.arguments):
            for a in args.posonlyargs + args.args + args.kwonlyargs + [args.vararg, args.kwarg]:
                if a is not None:
                    self._poison_name(a.arg)

    def _poison_name(self, name):
        self.safe[-1].pop(name, None)
        self.tainted[-1].pop(name, None)
        self.poisoned[-1].add(name)

    def _poison(self, target):
        """Names bound by a for / with / := / comprehension / except: value unknown."""
        for n in ast.walk(target):
            key = _target_key(n)
            if key:
                self._poison_name(key)

    def visit_For(self, node):
        self._poison(node.target)
        self.generic_visit(node)

    visit_AsyncFor = visit_For

    def visit_With(self, node):
        for item in node.items:
            if item.optional_vars is not None:
                self._poison(item.optional_vars)
        self.generic_visit(node)

    visit_AsyncWith = visit_With

    def visit_NamedExpr(self, node):
        self._mark([node.target], node.value)
        self.generic_visit(node)

    def visit_comprehension(self, node):
        self._poison(node.target)
        self.generic_visit(node)

    def _visit_comp(self, node):
        # The tree lists elt before the `for` clauses; bind the loop names first.
        for g in node.generators:
            self.visit(g)
        for field in ('elt', 'key', 'value'):
            if getattr(node, field, None) is not None:
                self.visit(getattr(node, field))

    visit_ListComp = visit_SetComp = visit_GeneratorExp = visit_DictComp = _visit_comp

    def visit_ExceptHandler(self, node):
        if node.name:
            self._poison_name(node.name)
        self.generic_visit(node)

    def leave_scope(self, node):
        self.tainted.pop()
        self.safe.pop()
        self.poisoned.pop()

    def _is_safe(self, node) -> bool:
        """True when the value can only be code-constant text or '?' markers."""
        if isinstance(node, ast.Constant):
            return True
        if isinstance(node, ast.JoinedStr):
            return all(self._is_safe(v.value) for v in node.values
                       if isinstance(v, ast.FormattedValue))
        key = _target_key(node)
        if key is not None:
            return key in self.consts or key in self.safe[-1]
        if isinstance(node, ast.IfExp):
            return self._is_safe(node.body) and self._is_safe(node.orelse)
        if isinstance(node, ast.BoolOp):
            return all(self._is_safe(v) for v in node.values)
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Mod)):
            return self._is_safe(node.left) and self._is_safe(node.right)
        if isinstance(node, ast.Tuple):
            return all(self._is_safe(e) for e in node.elts)
        if isinstance(node, ast.Call):
            name = _call_name(node.func) or ''
            if isinstance(node.func, ast.Name) and name in _MARK_HELPERS:
                return True                       # _marks(codes) → '?, ?, ?'
            if isinstance(node.func, ast.Attribute) and name == 'isoformat' and not node.args:
                return True                       # date.isoformat() → digits and dashes
            if (isinstance(node.func, ast.Attribute) and name == 'strftime'
                    and len(node.args) == 1 and isinstance(node.args[0], ast.Constant)):
                return True                       # d.strftime('%Y-%m-%d') with a fixed format
            if isinstance(node.func, ast.Name) and name in ('int', 'float', 'len', 'abs', 'round'):
                return True                       # always a number — can't carry SQL
            if isinstance(node.func, ast.Name) and name in ('max', 'min'):
                return all(self._is_safe(a) for a in node.args)
            if (isinstance(node.func, ast.Attribute) and node.func.attr == 'join'
                    and isinstance(node.func.value, ast.Constant) and len(node.args) == 1):
                return self._only_question_marks(node.args[0])
        return False

    def _only_question_marks(self, arg) -> bool:
        """','.join(<arg>) yields only '?' markers: ('?' for _ in x) / ['?' for …] /
        '?' * n / ['?'] * n, with n a number."""
        q = lambda n: isinstance(n, ast.Constant) and n.value == '?'   # noqa: E731
        if isinstance(arg, (ast.GeneratorExp, ast.ListComp)):
            return q(arg.elt)
        if isinstance(arg, ast.BinOp) and isinstance(arg.op, ast.Mult):
            seq, n = (arg.left, arg.right) if not _is_const(arg.right) or q(arg.left) or                 isinstance(arg.left, ast.List) else (arg.right, arg.left)
            ok_seq = q(seq) or (isinstance(seq, ast.List) and len(seq.elts) == 1 and q(seq.elts[0]))
            return ok_seq and self._is_safe(n)
        return False

    def _info(self, node):
        """(built, literal_text, opaque) for an expression."""
        if isinstance(node, ast.Constant):
            return False, node.value if isinstance(node.value, str) else '', False
        if isinstance(node, ast.JoinedStr):
            # built only when something interpolated isn't code-constant text / '?' markers
            text = ''.join(v.value if isinstance(v, ast.Constant) else 'X' for v in node.values)
            return (any(isinstance(v, ast.FormattedValue) and not self._is_safe(v.value)
                        for v in node.values), text, False)
        key = _target_key(node)
        if key is not None:
            if key in self.tainted[-1]:
                return True, self.tainted[-1][key], False
            if key in self.consts:
                return False, self.consts[key], False
            if key in self.safe[-1]:
                return False, self.safe[-1][key], False
            return False, '', True
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            lb, lt, lo = self._info(node.left)
            rb, rt, ro = self._info(node.right)
            return lb or rb or lo or ro, lt + rt, False
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod):
            lb, lt, _ = self._info(node.left)
            return lb or not self._is_safe(node.right), lt, False
        if isinstance(node, (ast.IfExp, ast.BoolOp)):
            parts = [node.body, node.orelse] if isinstance(node, ast.IfExp) else node.values
            infos = [self._info(p) for p in parts]
            return (any(i[0] for i in infos), ' '.join(i[1] for i in infos),
                    any(i[2] for i in infos))
        if isinstance(node, ast.Call):
            f = node.func
            if isinstance(f, ast.Attribute) and f.attr == 'format':
                bb, bt, _ = self._info(f.value)
                fillers = list(node.args) + [k.value for k in node.keywords]
                return bb or not all(self._is_safe(a) for a in fillers), bt, False
            if isinstance(f, ast.Attribute) and f.attr == 'replace' and len(node.args) >= 2:
                bb, bt, bo = self._info(f.value)          # TEMPLATE.replace('{b}', value)
                return bb or not self._is_safe(node.args[1]), bt, False
            if _call_name(f) in _PASSTHROUGH:
                if isinstance(f, ast.Attribute) and f.attr != 'dedent':
                    return self._info(f.value)          # x.strip() / x.upper()
                if node.args:
                    return self._info(node.args[0])     # dedent(x) / str(x)
            if self._is_safe(node):
                return False, '', False
        return False, '', True

    def _mark(self, targets, value):
        for t in targets:
            if isinstance(t, ast.Tuple) and isinstance(value, ast.Tuple)                     and len(t.elts) == len(value.elts):
                self._mark_pairs(zip(t.elts, value.elts))     # sql, n = f"...", 1
            else:
                els = t.elts if isinstance(t, ast.Tuple) else [t]
                self._mark_pairs((el, value) for el in els)

    def _mark_pairs(self, pairs):
        for target, value in pairs:
            key = _target_key(target)
            if not key:
                continue
            built, text, opaque = self._info(value)
            if built:
                self.tainted[-1][key] = text
            else:
                self.tainted[-1].pop(key, None)
            # safe = not built and fully understood (constants, '?' markers, safe .format)
            if not built and (not opaque or self._is_safe(value)) and key not in self.poisoned[-1]:
                self.safe[-1][key] = text
            else:
                self.safe[-1].pop(key, None)
                self.poisoned[-1].add(key)

    def visit_Assign(self, node):
        self._mark(node.targets, node.value)
        self.generic_visit(node)

    def visit_AnnAssign(self, node):
        if node.value is not None:
            self._mark([node.target], node.value)
        self.generic_visit(node)

    def visit_AugAssign(self, node):
        # sql += f"... {x}"  /  sql += user_value  → the whole statement is text-built
        key = _target_key(node.target)
        if key and isinstance(node.op, ast.Add):
            built, text, opaque = self._info(node.value)
            if built or (opaque and not self._is_safe(node.value)):
                base = self.tainted[-1].get(key, self.consts.get(key, ''))
                self.tainted[-1][key] = base + text
                self.safe[-1].pop(key, None)
                self.poisoned[-1].add(key)
            elif key in self.safe[-1]:
                self.safe[-1][key] += text
        self.generic_visit(node)

    def visit_Call(self, node):
        positions = self.sinks.get(_call_name(node.func), ())
        hit = any(pos < len(node.args) and self._info(node.args[pos])[0] for pos in positions)
        if not hit:
            for a in list(node.args) + [k.value for k in node.keywords]:
                built, text, _ = self._info(a)
                if built and _SQL_STRUCT.search(text):
                    hit = True
                    break
        if hit:
            self.sites.add(f'{self.path}::{self.qualname}')
        self.generic_visit(node)


def sql_from_text_sites(tree, path) -> set:
    v = _SqlTaint(path, _param_sinks(tree, _SQL_SINKS), _module_strings(tree))
    v.visit(tree)
    return v.sites


# ── Raw SOFTECH connections ──────────────────────────────────────────────────

_GUARDED_CONNECTORS = {
    'config/sybase.py': {'get_sybase_connection', 'get_branch_connection',
                         'probe_connection', 'SoftechConnector.connect'},
}


class _RawConnect(_Scoped):

    def __init__(self, path):
        super().__init__()
        self.path, self.sites = path, set()

    def visit_Call(self, node):
        f = node.func
        hit = (
            (isinstance(f, ast.Name) and f.id == 'SybDriver')
            or (isinstance(f, ast.Attribute) and f.attr == 'SybDriver')
            or (isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and (
                (f.value.id == 'DriverManager' and f.attr == 'getConnection')
                or (f.value.id in ('jaydebeapi', 'pyodbc') and f.attr == 'connect')))
        )
        if hit and self.qualname not in _GUARDED_CONNECTORS.get(self.path, set()):
            self.sites.add(f'{self.path}::{self.qualname}')
        self.generic_visit(node)


def raw_connect_sites(tree, path) -> set:
    v = _RawConnect(path)
    v.visit(tree)
    return v.sites


# ── SOFTECH write statements ─────────────────────────────────────────────────

# T-SQL lets INTO / FROM be omitted; table tokens may be %s / {} placeholders.
_WRITE_SQL = re.compile(
    r'(?is)\b(insert\s+into\b|insert\s+[\w.\[\]{}%]+\s*(\([\w\s,]+\)\s*)?(values|select)\b'
    r'|update\s+[\w.\[\]{}%]+\s+set\b|delete\s+from\b|delete\s+[\w.\[\]{}%]+\s+where\b'
    r'|truncate\s+table\b|select\b[^;]*?\binto\s+#?\w+\s+from\b)')
_SOFTECH_MARKERS = {'get_sybase_connection', 'get_branch_connection', 'SoftechConnector',
                    'createStatement'}


def _talks_to_softech(tree) -> bool:
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom) and (
                n.module == 'config.sybase'
                or (n.module == 'config' and any(a.name == 'sybase' for a in n.names))):
            return True
        if isinstance(n, ast.Import) and any(a.name == 'config.sybase' for a in n.names):
            return True
        if isinstance(n, ast.Name) and n.id in _SOFTECH_MARKERS:
            return True
        if isinstance(n, ast.Attribute) and n.attr in _SOFTECH_MARKERS:
            return True
    return False


class _WriteSql(_Scoped):

    def visit_Expr(self, node):
        if isinstance(node.value, (ast.Constant, ast.JoinedStr)):
            return          # docstrings / bare strings are prose, not SQL
        self.generic_visit(node)

    def __init__(self, path, any_module):
        super().__init__()
        self.path, self.sites, self.any_module = path, set(), any_module

    def _check(self, text):
        if _WRITE_SQL.search(text) and (self.any_module or 'SOFTECHDB' in text.upper()):
            self.sites.add(f'{self.path}::{self.qualname}')

    def visit_JoinedStr(self, node):
        # f"UPDATE {table} SET …" — judge the whole statement, interpolations as X
        self._check(''.join(v.value if isinstance(v, ast.Constant) else 'X' for v in node.values))

    def visit_BinOp(self, node):
        # "UPDATE t " + "SET a = ?" — judge statements split across + as one string
        if isinstance(node.op, ast.Add):
            self._check(self._joined(node))
        self.generic_visit(node)

    def _joined(self, node):
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            return self._joined(node.left) + self._joined(node.right)
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, ast.JoinedStr):
            return ''.join(v.value if isinstance(v, ast.Constant) else 'X' for v in node.values)
        return 'X'

    def visit_Constant(self, node):
        if isinstance(node.value, str):
            self._check(node.value)


def softech_write_sites(tree, path) -> set:
    """Write SQL in a module that connects to SOFTECH, or any write SQL naming SOFTECHDB."""
    v = _WriteSql(path, any_module=_talks_to_softech(tree))
    v.visit(tree)
    return v.sites


# ── Write switches defaulting to ON (config/settings.py) ─────────────────────

_FLAG_NAME = re.compile(r'(_ENABLED|_WRITE|_WRITER|_AUTO_APPROVE|_AUTO_TOPUP|_UPDATE_PATIENTDATA|_NOTIFY)$')


def default_true_flags(tree) -> set:
    found = set()
    for n in ast.walk(tree):
        if (isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == 'config'
                and n.args and isinstance(n.args[0], ast.Constant)
                and isinstance(n.args[0].value, str) and _FLAG_NAME.search(n.args[0].value)):
            for kw in n.keywords:
                if kw.arg == 'default' and isinstance(kw.value, ast.Constant) and kw.value.value is True:
                    found.add(n.args[0].value)
    return found


# ── Secrets in tracked files ─────────────────────────────────────────────────

_SECRET_PATTERNS = {
    'password-literal': re.compile(
        r'''(?i)\b\w*(pass(word|wd)?|secret|token|api[_-]?key)\w*['"]?\s*[:=]\s*['"][^'"\s]{6,}['"]'''),
    'private-key': re.compile(r'-----BEGIN [A-Z ]*PRIVATE KEY-----'),
    'google-api-key': re.compile(r'AIza[0-9A-Za-z_\-]{35}'),
    'jwt': re.compile(r'eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.'),
}
_TEXT_SKIP_PREFIX = ('apps/tests/', 'docs/', '.github/')
_TEXT_SKIP_SUFFIX = ('.example', 'package-lock.json', '.png', '.jpg', '.jpeg', '.gif', '.ico',
                     '.pdf', '.xlsx', '.xls', '.jar', '.woff', '.woff2', '.ttf', '.otf', '.zip',
                     '.mp3', '.wav', '.traineddata')


def secret_hits(text: str) -> set:
    return {name for name, rx in _SECRET_PATTERNS.items() if rx.search(text)}


def tracked_files():
    try:
        out = subprocess.run(['git', 'ls-files', '-z'], cwd=REPO_ROOT, capture_output=True,
                             check=True)
    except (OSError, subprocess.CalledProcessError):
        return None
    return [f for f in out.stdout.decode('utf-8', 'replace').split('\0') if f]


_TEST_MODULE = re.compile(r'(^|/)tests?(_\w+)?\.py$')


def skip_for_secrets(rel: str) -> bool:
    """Test modules hold fixture passwords by design; binaries/docs aren't code."""
    rel = rel.replace('\\', '/')
    return (rel.startswith(_TEXT_SKIP_PREFIX) or rel.lower().endswith(_TEXT_SKIP_SUFFIX)
            or bool(_TEST_MODULE.search(rel)))


def tracked_secret_sites(files) -> set:
    found = set()
    for rel in files:
        rel = rel.replace('\\', '/')
        if skip_for_secrets(rel):
            continue
        p = REPO_ROOT / rel
        try:
            if not p.is_file() or p.stat().st_size > 1_000_000:
                continue
            text = p.read_text(encoding='utf-8', errors='ignore')
        except OSError:
            continue
        found |= {f'{rel}:{name}' for name in secret_hits(text)}
    return found
