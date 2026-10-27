"""
apps/tests/security/baseline.py

The ratchet behind every security sweep and static guard.

A sweep reports what it finds (leaks, unsafe SQL sites, unregistered SOFTECH
writes …). Whatever existed when the suite was written is listed in a tracked
file under baselines/<name>.txt, so the suite is green on day one. From then on
a test fails on:

  NEW   — something found that isn't listed: a fresh hole. Fix it; only a
          reviewed, deliberate exception may be added to the file by hand.
  STALE — something listed that is no longer found: the hole was fixed, so the
          line must go (otherwise the hole could quietly come back).

SECURITY_BASELINE_PRUNE=1 deletes STALE lines in place. It never adds lines —
new entries are always a human edit.

Tests waiting on an owner decision use @pending('<X>-<n>') (an expectedFailure)
and are listed in PENDING.md; a guard test keeps the two in step.
"""
import os
import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
BASELINE_DIR = Path(__file__).resolve().parent / 'baselines'
PENDING_FILE = Path(__file__).resolve().parent / 'PENDING.md'


def norm(path) -> str:
    """Repo-relative posix path (baselines must match on Windows and in CI)."""
    p = Path(str(path).replace('\\', '/'))
    try:
        p = p.resolve().relative_to(REPO_ROOT) if p.is_absolute() else p
    except ValueError:
        pass
    return p.as_posix()


def _entries(lines):
    return {ln.strip() for ln in lines if ln.strip() and not ln.strip().startswith('#')}


def load_baseline(name: str) -> set:
    f = BASELINE_DIR / f'{name}.txt'
    if not f.exists():
        return set()
    return _entries(f.read_text(encoding='utf-8').splitlines())


def _prune(name: str, stale: set):
    f = BASELINE_DIR / f'{name}.txt'
    kept = [ln for ln in f.read_text(encoding='utf-8').splitlines() if ln.strip() not in stale]
    f.write_text('\n'.join(kept) + '\n', encoding='utf-8')


def assert_matches_baseline(testcase, name: str, found) -> None:
    found = {str(x) for x in found}
    listed = load_baseline(name)
    new = sorted(found - listed)
    stale = sorted(listed - found)
    if stale and os.environ.get('SECURITY_BASELINE_PRUNE') == '1':
        _prune(name, set(stale))
        stale = []
    if not new and not stale:
        return
    parts = []
    if new:
        parts.append(f'NEW (fix it or, if reviewed, add it to baselines/{name}.txt) — {len(new)}:\n'
                     + '\n'.join(new))
    if stale:
        parts.append(f'STALE (fixed — delete from baselines/{name}.txt, or run with '
                     f'SECURITY_BASELINE_PRUNE=1) — {len(stale)}:\n' + '\n'.join(stale))
    testcase.fail('\n\n'.join(parts))


_PENDING_LINE = re.compile(r'^\s*-\s*([A-Z]-\d+)\s*:')    # P-<n> Batch 2, A-<n> Batch 3, …


def pending_ids() -> set:
    if not PENDING_FILE.exists():
        return set()
    return {m.group(1) for ln in PENDING_FILE.read_text(encoding='utf-8').splitlines()
            if (m := _PENDING_LINE.match(ln))}


def pending(decision_id: str):
    """Mark a test that exposes a hole whose fix awaits the owner's decision."""
    def deco(fn):
        fn = unittest.expectedFailure(fn)
        fn.__pending__ = decision_id
        return fn
    return deco
