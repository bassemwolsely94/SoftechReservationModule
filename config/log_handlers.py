"""
config/log_handlers.py

Logging handlers hardened for our Windows + OneDrive + multi-process setup
(dev server and management commands running at the same time).
"""
import time
import logging.handlers


class SafeTimedRotatingFileHandler(logging.handlers.TimedRotatingFileHandler):
    """TimedRotatingFileHandler that never crashes when the log file can't be
    rotated because another process holds it open (Windows `WinError 32`) or
    OneDrive is syncing it.

    On a failed rollover it keeps appending to the current file and postpones the
    next rotation attempt, instead of raising and retrying on every record.
    """

    def doRollover(self):
        try:
            super().doRollover()
        except (PermissionError, OSError):
            # Rotation failed (file locked / sync in progress). Make sure we still
            # have an open stream to write to, and push the next attempt forward
            # so we don't hammer os.rename on every emit.
            try:
                if self.stream is None:
                    self.stream = self._open()
            except Exception:
                self.stream = None
            self.rolloverAt = self.computeRollover(int(time.time()))
