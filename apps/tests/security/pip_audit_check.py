"""
Run pip-audit on the INSTALLED environment (in CI: exactly what requirements-ci.txt
installed), ignoring only the advisories listed (with their owner) in
pip-audit-ignore.txt. Any other advisory fails CI.

Not `-r requirements.txt`: that re-resolves the unpinned production set (torch/CUDA
wheels on Linux) — heavy, and a different set from the one the ignore list was built on.
Production-only packages are covered when this is run inside the production venv.

    python apps/tests/security/pip_audit_check.py
"""
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

ids = []
for line in (HERE / 'pip-audit-ignore.txt').read_text(encoding='utf-8').splitlines():
    m = re.match(r'^\s*([A-Za-z0-9][A-Za-z0-9-]+)', line)
    if m:
        ids.append(m.group(1))

cmd = [sys.executable, '-m', 'pip_audit', '--progress-spinner', 'off']
for vid in ids:
    cmd += ['--ignore-vuln', vid]
sys.exit(subprocess.call(cmd))
