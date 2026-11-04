#!/usr/bin/env bash
# Release main to production (runbook §13.5). Install once:
#   sudo install -o root -g root -m 700 /opt/elrezeiky/app/deploy/release.sh /opt/elrezeiky/release.sh
# Run: sudo /opt/elrezeiky/release.sh
# Re-install after a release that changed this file (it is not run from the repo, so a pull can't
# change what root executes mid-run).
set -euo pipefail
APP=/opt/elrezeiky/app; PY=/opt/elrezeiky/venv/bin/python; U="sudo -u elrezeiky"
cd $APP
OLD=$($U git rev-parse HEAD)
echo "== backup before release"
$U pg_dump -h localhost -U elrezeiky -Fc elrezeiky_db -f /opt/elrezeiky/backups/pre_release_$(date +%F_%H%M).dump
echo "== pull main"
$U git fetch origin && $U git checkout main && $U git pull --ff-only
NEW=$($U git rev-parse HEAD)
if [[ $OLD == "$NEW" ]]; then echo "Nothing new on main."; exit 0; fi
$U git log --oneline $OLD..$NEW
# units, nginx and this script are copied out of the repo by hand (runbook §9.1/§9.2, header above)
if ! $U git diff --quiet $OLD $NEW -- deploy/; then
  echo "!! deploy/ changed in this release — re-apply by hand where needed (this run does NOT):"
  $U git diff --stat $OLD $NEW -- deploy/
fi
# torch from the CPU index first: requirements.txt has a torch security floor, and if pip had to
# satisfy it from PyPI it would pull the ~3 GB CUDA build. No-op when the installed torch is new enough.
echo "== python deps (app)";  $U /opt/elrezeiky/venv/bin/pip install -q "torch>=2.13.0" --index-url https://download.pytorch.org/whl/cpu
$U /opt/elrezeiky/venv/bin/pip install -q -r requirements.txt
if ! $U git diff --quiet $OLD $NEW -- ocr_sidecar/requirements.txt; then
  echo "== python deps (OCR sidecar)"; $U /opt/elrezeiky/ocr-venv/bin/pip install -q -r ocr_sidecar/requirements.txt
fi
echo "== migrations to apply:"; $U $PY manage.py migrate --plan | tail -25
read -p "Apply these migrations and restart production? [y/N] " a
if [[ $a != y ]]; then echo "Stopped. Code is pulled but NOT live. Undo: sudo -u elrezeiky git checkout $OLD"; exit 1; fi
$U $PY manage.py migrate
# P-56: EVERY process restarts after migrate (below). A process started before a migration
# inserts with the old column set — that caused the 2026-10 schema-mismatch sync failures.
echo "== frontend";           (cd frontend && $U npm ci --silent && $U npm run build)
$U $PY manage.py collectstatic --noinput
$U $PY manage.py check --deploy
echo "== writer role (P-54)"; $U $PY manage.py writer_status | tail -1
echo "== restart"
systemctl restart elrezeiky-web
systemctl restart elrezeiky-scheduler
$U git diff --quiet $OLD $NEW -- ocr_sidecar || systemctl restart elrezeiky-ocr
echo "== health"
for i in $(seq 1 30); do
  if curl -fsS http://127.0.0.1:8000/api/public/health/ >/dev/null 2>&1; then ok=1; break; fi
  sleep 2
done
if [[ ${ok:-0} != 1 ]]; then
  echo "!! /api/public/health/ did not answer 200 within 60 s — journalctl -u elrezeiky-web -n 100"
  echo "   Rollback: sudo -u elrezeiky git checkout ${OLD:0:8}, rebuild the frontend if it changed, restart."
  exit 1
fi
systemctl --no-pager status elrezeiky-web elrezeiky-scheduler elrezeiky-ocr | grep -E "●|Active"
echo "== live: $($U git log -1 --oneline)   (previous: ${OLD:0:8})"
