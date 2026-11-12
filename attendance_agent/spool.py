"""Disk spool. Data reaches disk before any send, and leaves only after an ack."""
import hashlib
import json
import os
import re
import time
import uuid
from pathlib import Path

_ENTRY_NAME = re.compile(r'^\d{12}-[a-z]+-[0-9a-f]{8}\.json$')
_RENAME_ATTEMPTS = 5
_RENAME_WAIT_SECONDS = 0.2


def _replace_with_retry(source, target):
    """Antivirus and indexers often hold a just-closed file for a moment on Windows."""
    for attempt in range(_RENAME_ATTEMPTS):
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if attempt == _RENAME_ATTEMPTS - 1:
                raise
            time.sleep(_RENAME_WAIT_SECONDS)


class Spool:
    def __init__(self, path):
        self.path = Path(path)
        self.path.mkdir(parents=True, exist_ok=True)
        existing = self.pending()
        self._sequence = int(existing[-1].name.split('-')[0]) if existing else 0

    def put(self, kind, payload) -> Path:
        """Write atomically: a crash leaves a .tmp file, never a half-written entry."""
        self._sequence += 1
        # The random part means two copies of the agent can never overwrite a file.
        name = f'{self._sequence:012d}-{kind}-{uuid.uuid4().hex[:8]}.json'
        final = self.path / name
        temporary = self.path / f'{name}.tmp'
        try:
            with open(temporary, 'w', encoding='utf-8') as handle:
                json.dump({'kind': kind, 'payload': payload}, handle)
                handle.flush()
                os.fsync(handle.fileno())
            _replace_with_retry(temporary, final)
        except BaseException:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass  # the original error is the one worth reporting
            raise
        return final

    def pending(self) -> list[Path]:
        """Oldest first. Numbered names, so a changed PC clock can't reorder them."""
        entries = [p for p in self.path.glob('*.json') if _ENTRY_NAME.match(p.name)]
        return sorted(entries, key=lambda path: path.name)

    def read(self, path) -> tuple[str, dict]:
        with open(path, encoding='utf-8') as handle:
            entry = json.load(handle)
        return entry['kind'], entry['payload']

    def ack(self, path) -> None:
        os.unlink(path)

    def quarantine(self, serial, raw: bytes) -> Path:
        """Keep a log that couldn't be decoded, because the machine's copy may be
        cleared. Never deleted here. Attendance logs only: user tables hold passwords
        and card numbers, and must never come here. Unchanged bytes are kept once."""
        folder = self.path / 'quarantine'
        folder.mkdir(exist_ok=True)
        safe_serial = re.sub(r'[^A-Za-z0-9_-]', '_', serial)
        final = folder / f'{safe_serial}-{hashlib.sha256(raw).hexdigest()[:16]}.bin'
        if not final.exists():
            temporary = final.with_name(f'{final.name}.tmp')
            with open(temporary, 'wb') as handle:
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())
            _replace_with_retry(temporary, final)
        return final
