"""
apps/tests/security/role_literals.py

Scanners behind test_role_literal_guard.py: hard-coded permission-role lists and single-role
checks, which should come from the registry (apps/users/roles.py) or the RBAC matrix instead.

Python (AST):
  (a) a tuple / list / set literal of >= 2 strings, ALL of them role keys, anywhere;
  (b) a comparison, or a keyword argument whose name contains "role", that pairs a role-ish
      expression (its source text contains "role") with ONE role key other than 'admin'.
  Test modules (tests.py, tests_*.py, test_*.py) and the registry itself are skipped.
  Entry: "path::Qualname::k1,k2" (keys sorted, no line numbers so entries stay stable).
JS (regex over frontend/src/**/*.js|jsx, *.test.* skipped):
  array literals whose quoted strings are >= 2 role keys and nothing else;
  `role === '<key>'` / `'<key>' !== role` with key != 'admin'.
  Entry: "path::k1,k2".

ROLE_KEYS is read from the registry at scan time, so a new role is covered automatically.
"""
import ast
import re

from apps.users.roles import ROLE_KEYS

from .baseline import REPO_ROOT, norm
from .static_scan import _Scoped, parse_file, python_files

REGISTRY_PATH = 'apps/users/roles.py'
JS_ROOT = 'frontend/src'
OPEN_KEY = 'admin'      # `role == 'admin'` is the superuser short-circuit, not a role list


def _keys():
    return frozenset(ROLE_KEYS)


def _entry(path, *parts):
    return '::'.join((path,) + parts)


# ── Python ───────────────────────────────────────────────────────────────────

def _role_key(node, keys):
    if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value in keys:
        return node.value
    return None


def _roleish(node):
    return 'role' in ast.unparse(node).lower()


class _RoleLiteralVisitor(_Scoped):

    def __init__(self, path, keys):
        super().__init__()
        self.path, self.keys, self.found = path, keys, set()

    def _add(self, keys):
        self.found.add(_entry(self.path, self.qualname, ','.join(sorted(set(keys)))))

    def _collection(self, node):
        elts = node.elts
        if len(elts) >= 2 and all(_role_key(e, self.keys) for e in elts):
            self._add(e.value for e in elts)
        self.generic_visit(node)

    visit_Tuple = visit_List = visit_Set = _collection

    def visit_Compare(self, node):
        sides = [node.left] + list(node.comparators)
        for a, b in zip(sides, sides[1:]):
            for key_side, other in ((a, b), (b, a)):
                key = _role_key(key_side, self.keys)
                if key and key != OPEN_KEY and _roleish(other):
                    self._add([key])
        self.generic_visit(node)

    def visit_keyword(self, node):
        key = _role_key(node.value, self.keys)
        if key and key != OPEN_KEY and node.arg and 'role' in node.arg.lower():
            self._add([key])
        self.generic_visit(node)


def py_role_literal_sites(tree, path) -> set:
    v = _RoleLiteralVisitor(path, _keys())
    v.visit(tree)
    return v.found


def _is_test_module(p, rel):
    """Test fixtures set roles on purpose (role='viewer'); management commands named test_* are not tests."""
    name = p.name
    return name == 'tests.py' or name.startswith('tests_') or (
        name.startswith('test_') and '/management/commands/' not in rel)


def repo_py_sites() -> set:
    found = set()
    for p in python_files():
        rel = norm(p)
        if rel == REGISTRY_PATH or _is_test_module(p, rel):
            continue
        found |= py_role_literal_sites(parse_file(p), rel)
    return found


# ── JS ───────────────────────────────────────────────────────────────────────

_JS_ARRAY = re.compile(r'\[([^\[\]]*)\]')
_JS_STRING = re.compile(r"'([^'\n]*)'|\"([^\"\n]*)\"")
_JS_CMP = re.compile(r"""[\w$]*role[\w$]*\s*[!=]==?\s*(['"])(\w+)\1""", re.IGNORECASE)
_JS_CMP_REV = re.compile(r"""(['"])(\w+)\1\s*[!=]==?\s*[\w$.?]*role""", re.IGNORECASE)


def js_role_literal_sites(text, path) -> set:
    keys = _keys()
    found = set()
    for m in _JS_ARRAY.finditer(text):
        strings = [a or b for a, b in _JS_STRING.findall(m.group(1))]
        if len(strings) >= 2 and all(s in keys for s in strings):
            found.add(_entry(path, ','.join(sorted(set(strings)))))
    for rx in (_JS_CMP, _JS_CMP_REV):
        for m in rx.finditer(text):
            key = m.group(2)
            if key in keys and key != OPEN_KEY:
                found.add(_entry(path, key))
    return found


def js_files():
    for ext in ('*.js', '*.jsx'):
        for p in sorted((REPO_ROOT / JS_ROOT).rglob(ext)):
            rel = norm(p)
            if 'node_modules' in rel or '.test.' in p.name:
                continue
            yield p


def repo_js_sites() -> set:
    found = set()
    for p in js_files():
        found |= js_role_literal_sites(p.read_text(encoding='utf-8-sig'), norm(p))
    return found
