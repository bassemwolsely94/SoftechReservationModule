"""
apps/purchasing/background.py — run the dashboard's engine buttons in their OWN process.

Why (owner 2026-10-26): «▶ تشغيل», «🔄 مزامنة كاملة» and «⟳ تعويض المبيعات» used to run as a
thread inside the web server. The dev server (runserver) restarts on every code change and
took the thread with it — the run stayed «running» until the watchdog failed it 20 minutes
later, while the screen kept showing the morning's run. A detached `manage.py run_engine_job`
outlives any web-server restart.

The view creates the DemandCalculationRun first (so the banner sees it at once), then
launch() starts the job; the job drives that same run to success / failed.
"""
import json
import logging
import subprocess
import sys

from django.conf import settings

logger = logging.getLogger('elrezeiky.purchasing')

MODES = ('quick', 'full', 'catchup')
JOB_LOG = 'engine_jobs.log'        # under logs/ — the child's stdout/stderr (crashes before logging)


def _creationflags():
    # A hidden console, NOT DETACHED_PROCESS: the venv python.exe is a launcher that starts
    # the real interpreter as a child; with no console to inherit that child opens a NEW,
    # visible one (a black window on the server's screen for the whole run). CREATE_NO_WINDOW
    # gives the launcher a hidden console the child inherits — measured: 2 windows → 0.
    if sys.platform != 'win32':
        return 0
    return subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW


def launch(mode, run_id, params=None):
    """Start `manage.py run_engine_job` detached from this process. Returns the child pid."""
    if mode not in MODES:
        raise ValueError(f'unknown engine job mode: {mode}')
    base = settings.BASE_DIR
    cmd = [sys.executable, str(base / 'manage.py'), 'run_engine_job', '--mode', mode, '--run', str(run_id)]
    if params:
        cmd += ['--params', json.dumps(params)]
    log_dir = base / 'logs'
    log_dir.mkdir(exist_ok=True)
    with open(log_dir / JOB_LOG, 'ab') as out:
        kw = dict(cwd=str(base), stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT,
                  close_fds=True)
        if sys.platform == 'win32':
            try:   # also leave a job object (a launcher that kills its process tree)
                proc = subprocess.Popen(cmd, creationflags=_creationflags()
                                        | subprocess.CREATE_BREAKAWAY_FROM_JOB, **kw)
            except OSError:   # the job does not allow breakaway
                proc = subprocess.Popen(cmd, creationflags=_creationflags(), **kw)
        else:
            proc = subprocess.Popen(cmd, start_new_session=True, **kw)
    logger.info('[engine-job] %s run %s started as pid %s', mode, run_id, proc.pid)
    return proc.pid


def start(run, mode, params=None):
    """launch() for a just-created run; a launch failure fails the run instead of leaving it
    «running» for the watchdog. Returns True when the job started."""
    from django.utils import timezone
    try:
        launch(mode, run.pk, params)
        return True
    except Exception as exc:
        logger.exception('[engine-job] could not start %s run %s', mode, run.pk)
        run.status = 'failed'
        run.error_message = f'تعذّر بدء التشغيل: {exc}'[:500]
        run.finished_at = timezone.now()
        run.save(update_fields=['status', 'error_message', 'finished_at'])
        return False
