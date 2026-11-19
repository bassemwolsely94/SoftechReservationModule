"""config.log_handlers: the platform log handler makes its own folder (logs/ is not in git)."""
import logging
import os
import tempfile

from django.test import SimpleTestCase

from config.log_handlers import SafeTimedRotatingFileHandler


class LogFolderTests(SimpleTestCase):

    def test_first_record_creates_the_missing_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'logs', 'nested', 'platform.log')
            handler = SafeTimedRotatingFileHandler(path, when='midnight', backupCount=1,
                                                   encoding='utf-8', delay=True)
            try:
                handler.emit(logging.LogRecord('t', logging.WARNING, __file__, 1, 'hello', None, None))
            finally:
                handler.close()
            with open(path, encoding='utf-8') as f:
                self.assertIn('hello', f.read())
