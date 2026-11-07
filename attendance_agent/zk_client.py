"""Read-only client for ZKTeco fingerprint machines over TCP.

Punches are evidence in employee disputes, so this client can only read. Every
packet leaves through `ZkClient._send`, which refuses anything outside the
allow-list before touching the socket. There is deliberately no code here for
clearing logs, pausing the machine, changing its clock, or reading or writing
users' templates.

Wire format. Each packet is an 8-byte TCP header (magic + payload length) and a
payload of command, checksum, session, reply number, then data, all little-endian.
"""
import socket
import struct
import time
from datetime import date, datetime
from datetime import time as clock_time
from typing import NamedTuple

CMD_CONNECT = 1000
CMD_EXIT = 1001
CMD_OPTIONS_READ = 11
CMD_FREE_SIZES = 50
CMD_GET_TIME = 201
CMD_PREPARE_BUFFER = 1503
CMD_READ_BUFFER = 1504
CMD_FREE_DATA = 1502
CMD_AUTH = 1102  # allowed per client, only when a comm key is configured

ACK_OK = 2000
ACK_UNAUTH = 2005
PREPARE_DATA = 1500
DATA = 1501

ALLOWED_COMMANDS = frozenset({
    CMD_CONNECT,
    CMD_EXIT,
    CMD_OPTIONS_READ,
    CMD_FREE_SIZES,
    CMD_GET_TIME,
    CMD_PREPARE_BUFFER,
    CMD_READ_BUFFER,
    CMD_FREE_DATA,
})

# CMD_PREPARE_BUFFER wraps an inner read command, and the same wrapper can fetch
# fingerprint templates. So its payload is allow-listed too: user table and
# attendance log only.
_USER_TABLE_REQUEST = struct.pack('<bhii', 1, 9, 5, 0)
_LOG_TABLE_REQUEST = struct.pack('<bhii', 1, 13, 0, 0)
_ALLOWED_TABLE_REQUESTS = frozenset({_USER_TABLE_REQUEST, _LOG_TABLE_REQUEST})
_SERIAL_OPTION = b'~SerialNumber\0'

_MAGIC = b'\x50\x50\x82\x7d'
_USHRT_MAX = 65535
_CHUNK = 0xFFC0
_MAX_FRAME = 1024 * 1024
_MAX_TABLE = 64 * 1024 * 1024
_READ_ATTEMPTS = 3
_SESSION_SECONDS = 600  # recv timeouts can't stop a machine that trickles bytes
_NO_DATA_COMMANDS = frozenset({CMD_CONNECT, CMD_EXIT, CMD_FREE_SIZES, CMD_GET_TIME, CMD_FREE_DATA})


class ZkError(Exception):
    """Base class for anything this client refuses or can't understand."""


class ForbiddenCommand(ZkError):
    """A command outside the allow-list. Raised before any socket write."""


class CommKeyRequired(ZkError):
    """The machine asks for a comm key and none is configured."""


class CommKeyRejected(ZkError):
    """The machine refused the configured comm key."""


class ZkProtocolError(ZkError):
    """The machine sent something we can't trust.

    `raw_table` holds the undecoded attendance log when decoding it failed, so the
    caller can keep the evidence. It is never set for a user table, which holds
    passwords and card numbers.
    """

    raw_table = None


class ClockInvalid(ZkProtocolError):
    """The machine's clock holds an impossible date. Its logs are still readable."""


class TableTruncated(ZkProtocolError):
    """A table is shorter than its own length prefix."""


class UnexpectedRecordSize(ZkProtocolError):
    """A table's size matches no known record format. Never guess a format."""


class Sizes(NamedTuple):
    users: int
    records: int
    users_capacity: int
    records_capacity: int


class DeviceUserRow(NamedTuple):
    user_code: str
    name: str
    is_admin: bool


class LogRow(NamedTuple):
    user_code: str
    raw_stamp: int
    date: date | None
    time: clock_time | None
    state: int
    verify_mode: int


def decode_stamp(raw: int) -> tuple[date | None, clock_time | None]:
    """Decode the device's timestamp; an impossible date gives (None, None)."""
    rest, second = divmod(raw, 60)
    rest, minute = divmod(rest, 60)
    rest, hour = divmod(rest, 24)
    rest, day = divmod(rest, 31)
    year, month = divmod(rest, 12)
    try:
        return date(year + 2000, month + 1, day + 1), clock_time(hour, minute, second)
    except ValueError:
        return None, None


def _table_records(table: bytes, count: int, record_sizes: tuple[int, ...]):
    """Return (record_size, body), or (None, b'') for an empty table.

    The count must match exactly, and exactly one size can then fit. A near match
    could be a wrong format, whose decoded rows would become permanent punches.
    """
    total = struct.unpack('<I', table[:4])[0] if len(table) >= 4 else 0
    body = table[4:]
    if len(body) < total:
        raise TableTruncated(f'table has {len(body)} of {total} bytes')
    if len(body) > total:
        raise UnexpectedRecordSize(f'{len(body) - total} bytes past the stated length')
    if total == 0:
        if count > 0:
            raise TableTruncated(f'empty table for {count} records')
        return None, b''
    for size in record_sizes:
        if total == size * count:
            return size, body
    raise UnexpectedRecordSize(f'{total} bytes for {count} records')


def _text(raw: bytes) -> str:
    return raw.split(b'\0')[0].decode('utf-8', errors='ignore').strip()


def _code_or_slot(raw: bytes, uid: int) -> str:
    """An identity must be clean: dropping one bad byte could turn it into another
    employee's number. Anything else becomes a slot code, which never resolves."""
    try:
        code = raw.split(b'\0')[0].decode('ascii').strip()
    except UnicodeDecodeError:
        code = ''
    return code if code and code.isprintable() else f'uid-{uid}'


def parse_users(table: bytes, count: int) -> list[DeviceUserRow]:
    """Decode the user table. Password and card bytes are never touched."""
    size, body = _table_records(table, count, (72, 28))
    rows = []
    for offset in range(0, len(body), size or 1):
        record = body[offset:offset + size]
        uid = struct.unpack('<H', record[:2])[0]
        if size == 72:
            name, code = _text(record[11:35]), _code_or_slot(record[48:72], uid)
        else:
            name = _text(record[8:16])
            code = str(struct.unpack('<I', record[24:28])[0])
        rows.append(DeviceUserRow(code, name, bool(record[2] & 14)))
    return rows


def parse_logs(table: bytes, count: int) -> list[LogRow]:
    """Decode the log table. An undecodable date is kept, never dropped.

    The 8-byte format holds the machine's internal slot, not the HR number. A slot
    can be reused, so a roster lookup could pin an old punch on a new person, and
    store one punch under two codes across runs. It stays `uid-<slot>`, which is
    stable and can never resolve to an employee.
    """
    size, body = _table_records(table, count, (40, 16, 8))
    rows = []
    for offset in range(0, len(body), size or 1):
        record = body[offset:offset + size]
        if size == 40:
            uid = struct.unpack('<H', record[:2])[0]
            code = _code_or_slot(record[2:26], uid)
            verify, stamp, state = record[26], record[27:31], record[31]
        elif size == 16:
            code = str(struct.unpack('<I', record[:4])[0])
            stamp, verify, state = record[4:8], record[8], record[9]
        else:
            code = f"uid-{struct.unpack('<H', record[:2])[0]}"
            verify, stamp, state = record[2], record[3:7], record[7]
        raw = struct.unpack('<I', stamp)[0]
        punch_date, punch_time = decode_stamp(raw)
        rows.append(LogRow(code, raw, punch_date, punch_time, state, verify))
    return rows


def _checksum(packet: bytes) -> int:
    total = 0
    for index in range(0, len(packet) - 1, 2):
        total += packet[index] | packet[index + 1] << 8
        if total > _USHRT_MAX:
            total -= _USHRT_MAX
    if len(packet) % 2:
        total += packet[-1]
    while total > _USHRT_MAX:
        total -= _USHRT_MAX
    total = ~total
    while total < 0:
        total += _USHRT_MAX
    return total


def _comm_key_bytes(key: int, session: int, ticks: int = 50) -> bytes:
    mirrored = 0
    for bit in range(32):
        mirrored = mirrored << 1 | (1 if key & (1 << bit) else 0)
    value = (mirrored + session) & 0xFFFFFFFF
    b0, b1, b2, b3 = struct.pack('<I', value)
    swapped = bytes((b2 ^ ord('S'), b3 ^ ord('O'), b0 ^ ord('Z'), b1 ^ ord('K')))
    tick = ticks & 0xFF
    return bytes((swapped[0] ^ tick, swapped[1] ^ tick, tick, swapped[3] ^ tick))


class ZkClient:
    """Context manager around one read session with one machine."""

    def __init__(self, ip, port=4370, timeout=30, comm_key=None):
        self.ip = ip
        self.port = port
        self.timeout = timeout
        self._comm_key = None
        if comm_key not in (None, ''):
            try:
                self._comm_key = int(comm_key)
            except (TypeError, ValueError):
                raise ValueError('comm_key must be a number') from None
        self._allowed = ALLOWED_COMMANDS
        if self._comm_key is not None:
            self._allowed = ALLOWED_COMMANDS | {CMD_AUTH}
        self._sock = None
        self._session = 0
        self._reply = _USHRT_MAX - 1
        self._deadline = None

    def __enter__(self):
        self._deadline = time.monotonic() + _SESSION_SECONDS
        self._sock = socket.create_connection((self.ip, self.port), timeout=self.timeout)
        try:
            self._connect()
        except BaseException:
            self._close()
            raise
        return self

    def __exit__(self, exc_type, exc, tb):
        # A failed goodbye must never hide data already read.
        try:
            self._exchange(CMD_EXIT)
        except (OSError, ZkError):
            pass
        self._close()
        return False

    def _close(self):
        sock, self._sock = self._sock, None
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass

    def _connect(self):
        code, _data = self._exchange(CMD_CONNECT)
        if code == ACK_UNAUTH:
            if self._comm_key is None:
                raise CommKeyRequired('this machine needs a comm key')
            key = _comm_key_bytes(self._comm_key, self._session)
            code, _data = self._exchange(CMD_AUTH, key)
            if code != ACK_OK:
                raise CommKeyRejected('this machine refused the comm key')
        elif code != ACK_OK:
            raise ZkProtocolError(f'connect answered {code}')

    def _send(self, command, data=b''):
        """The single gate. Every packet to a machine leaves through here."""
        if command not in self._allowed:
            raise ForbiddenCommand(f'command {command} is not allowed')
        if command == CMD_PREPARE_BUFFER and data not in _ALLOWED_TABLE_REQUESTS:
            raise ForbiddenCommand('this table read is not allowed')
        if command == CMD_OPTIONS_READ and data != _SERIAL_OPTION:
            raise ForbiddenCommand('this option read is not allowed')
        if command == CMD_READ_BUFFER and len(data) != 8:
            raise ForbiddenCommand('bad buffer read')
        if command in _NO_DATA_COMMANDS and data:
            raise ForbiddenCommand(f'command {command} carries no data')
        if self._sock is None:
            raise ZkProtocolError('not connected')
        self._sock.sendall(self._packet(command, data))

    def _packet(self, command, data):
        # The checksum covers the reply number before it is incremented. The
        # machine-side implementations expect exactly this.
        unsigned = struct.pack('<4H', command, 0, self._session, self._reply) + data
        checksum = _checksum(unsigned)
        self._reply = (self._reply + 1) % _USHRT_MAX
        payload = struct.pack('<4H', command, checksum, self._session, self._reply) + data
        return _MAGIC + struct.pack('<I', len(payload)) + payload

    def _recv_exact(self, size):
        chunks = []
        remaining = size
        while remaining:
            if self._deadline is not None and time.monotonic() > self._deadline:
                raise ZkProtocolError('the machine took too long to answer')
            chunk = self._sock.recv(min(remaining, 65536))
            if not chunk:
                raise ZkProtocolError('connection closed by the machine')
            chunks.append(chunk)
            remaining -= len(chunk)
        return b''.join(chunks)

    def _read_frame(self):
        header = self._recv_exact(8)
        if header[:4] != _MAGIC:
            raise ZkProtocolError('bad frame header')
        length = struct.unpack('<I', header[4:])[0]
        if not 8 <= length <= _MAX_FRAME:
            raise ZkProtocolError(f'bad frame length {length}')
        payload = self._recv_exact(length)
        code, _checksum_field, session, reply = struct.unpack('<4H', payload[:8])
        return code, session, reply, payload[8:]

    def _exchange(self, command, data=b''):
        self._send(command, data)
        code, session, reply, body = self._read_frame()
        if command == CMD_CONNECT:
            self._session = session
        self._reply = reply
        return code, body

    def read_serial(self) -> str | None:
        """The machine's own serial, or None if this firmware doesn't answer."""
        code, data = self._exchange(CMD_OPTIONS_READ, _SERIAL_OPTION)
        if code != ACK_OK or b'=' not in data:
            return None
        return _text(data.split(b'=', 1)[1]) or None

    def read_time(self) -> datetime:
        code, data = self._exchange(CMD_GET_TIME)
        if code != ACK_OK or len(data) < 4:
            raise ZkProtocolError(f'clock read answered {code}')
        day, clock = decode_stamp(struct.unpack('<I', data[:4])[0])
        if day is None:
            raise ClockInvalid('the machine clock holds an impossible date')
        return datetime.combine(day, clock)

    def read_sizes(self) -> Sizes:
        code, data = self._exchange(CMD_FREE_SIZES)
        if code != ACK_OK or len(data) < 80:
            raise ZkProtocolError(f'sizes read answered {code}')
        fields = struct.unpack('<20i', data[:80])
        return Sizes(
            users=fields[4], records=fields[8],
            users_capacity=fields[15], records_capacity=fields[16],
        )

    def read_users(self) -> list[DeviceUserRow]:
        return self._read_counted(_USER_TABLE_REQUEST, 'users', parse_users, False)

    def read_logs(self) -> list[LogRow]:
        return self._read_counted(_LOG_TABLE_REQUEST, 'records', parse_logs, True)

    def _read_counted(self, request, count_field, parse, keep_raw):
        """Read a table whose size stayed still, so its count can be matched exactly.

        Staff keep punching during a read. If the count moved, or a read fails to
        decode, read again; the machine's log is unchanged by reading.
        """
        error = None
        table = None
        for _attempt in range(_READ_ATTEMPTS):
            count = getattr(self.read_sizes(), count_field)
            if count == 0:
                return []
            try:
                table = self._read_table(request)
                if getattr(self.read_sizes(), count_field) != count:
                    error = ZkProtocolError('the count changed during every read')
                    continue
                return parse(table, count)
            except ZkProtocolError as exc:
                error = exc
        if keep_raw:
            error.raw_table = table
        raise error

    def _read_table(self, request):
        code, data = self._exchange(CMD_PREPARE_BUFFER, request)
        if code == DATA:
            return data
        if code not in (ACK_OK, PREPARE_DATA) or len(data) < 5:
            raise ZkProtocolError(f'table read answered {code}')
        size = struct.unpack('<I', data[1:5])[0]
        if size > _MAX_TABLE:
            raise ZkProtocolError(f'table of {size} bytes is too large')
        parts = []
        start = 0
        while start < size:
            want = min(_CHUNK, size - start)
            part = self._read_chunk(start, want)
            if len(part) != want:
                raise ZkProtocolError(f'chunk gave {len(part)} of {want} bytes')
            parts.append(part)
            start += want
        try:
            self._exchange(CMD_FREE_DATA)
        except (OSError, ZkError):
            pass  # the table is already complete; closing the session frees it too
        return b''.join(parts)

    def _read_chunk(self, start, size):
        code, data = self._exchange(CMD_READ_BUFFER, struct.pack('<ii', start, size))
        if code == DATA:
            return data
        if code != PREPARE_DATA:
            raise ZkProtocolError(f'chunk read answered {code}')
        parts = []
        while True:
            code, _session, _reply, data = self._read_frame()
            if code == DATA:
                parts.append(data)
            elif code == ACK_OK:
                return b''.join(parts)
            else:
                raise ZkProtocolError(f'chunk stream answered {code}')
