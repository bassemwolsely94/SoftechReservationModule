"""Task 4: the attendance agent's read-only ZK client.

No real machine is ever contacted. A scripted fake device speaks the TCP framing
over a fake socket, and hands the bytes back in awkward pieces, as a real
network does.
"""
import ast
import struct
import sys
from datetime import date, datetime, time
from pathlib import Path
from unittest import mock

from django.test import SimpleTestCase

from attendance_agent import zk_client
from attendance_agent.zk_client import (
    ALLOWED_COMMANDS,
    ClockInvalid,
    CommKeyRejected,
    CommKeyRequired,
    ForbiddenCommand,
    TableTruncated,
    UnexpectedRecordSize,
    ZkClient,
    ZkProtocolError,
    decode_stamp,
    parse_logs,
    parse_users,
)

MAGIC = b'\x50\x50\x82\x7d'
ACK_OK, ACK_ERROR, ACK_UNAUTH = 2000, 2001, 2005
PREPARE_DATA, DATA = 1500, 1501


def encode_stamp(y, mo, d, h=0, mi=0, s=0):
    """The ZK formula, written out here so the test doesn't trust the code."""
    return ((y % 100) * 12 * 31 + (mo - 1) * 31 + d - 1) * 86400 + (h * 60 + mi) * 60 + s


def frame(code, data=b'', session=7, reply=0):
    payload = struct.pack('<4H', code, 0, session, reply) + data
    return MAGIC + struct.pack('<I', len(payload)) + payload


def user_28(uid, code, name=b'', privilege=0, password=b'SECRET', card=987654321):
    return struct.pack(
        '<HB5s8sIxBhI', uid, privilege, password, name, card, 1, 0, code,
    )


def user_72(uid, code, name=b'', privilege=0, password=b'SECRET', card=987654321):
    return struct.pack(
        '<HB8s24sIx7sx24s', uid, privilege, password, name, card, b'1', code,
    )


def log_8(uid, stamp, verify=1, state=0):
    return struct.pack('<HBIB', uid, verify, stamp, state)


def log_16(code, stamp, verify=1, state=0):
    return struct.pack('<IIBB2sI', code, stamp, verify, state, b'\0\0', 0)


def log_40(uid, code, stamp, verify=1, state=0):
    return struct.pack('<H24sBIB8s', uid, code, verify, stamp, state, b'\0' * 8)


def table(records):
    body = b''.join(records)
    return struct.pack('<I', len(body)) + body


def sizes_payload(users=2, records=2):
    fields = [0] * 20
    fields[4], fields[8], fields[15], fields[16] = users, records, 1000, 100000
    return struct.pack('<20i', *fields)


class FakeDevice:
    """A fake socket with a scripted machine behind it.

    Replies are queued as a stream of bytes and handed out `piece` bytes at a
    time, so a frame boundary never lines up with a recv() boundary.
    """

    def __init__(self, tables=None, piece=3, unauthorised=False, accept_key=True,
                 clock=b'', serial=b'~SerialNumber=SN1\0'):
        self.tables = tables or {}
        self.piece = piece
        self.unauthorised = unauthorised
        self.accept_key = accept_key
        self.clock = clock
        self.serial = serial
        self.sent = []
        self.packets = []
        self.requests = []
        self.stream = b''
        self.closed = False

    def sendall(self, packet):
        self.packets.append(packet)
        assert packet[:4] == MAGIC
        length = struct.unpack('<I', packet[4:8])[0]
        payload = packet[8:]
        assert len(payload) == length
        code, _sum, _session, reply = struct.unpack('<4H', payload[:8])
        self.sent.append(code)
        self._respond(code, payload[8:], reply)

    def _respond(self, code, data, reply):
        if code == 1000:
            self.stream += frame(ACK_UNAUTH if self.unauthorised else ACK_OK, reply=reply)
        elif code == 1102:
            self.stream += frame(ACK_OK if self.accept_key else ACK_UNAUTH, reply=reply)
        elif code == 50:
            self.stream += frame(ACK_OK, sizes_payload(*self.tables.get('sizes', (2, 2))), reply=reply)
        elif code == 201:
            self.stream += frame(ACK_OK, self.clock, reply=reply)
        elif code == 11:
            self.stream += frame(ACK_OK, self.serial, reply=reply)
        elif code == 1503:
            self.requests.append(data.hex())
            _flag, inner, _fct, _ext = struct.unpack('<bhii', data)
            self.current = self.tables[inner]
            self.stream += frame(
                ACK_OK, b'\0' + struct.pack('<I', len(self.current)), reply=reply,
            )
        elif code == 1504:
            start, size = struct.unpack('<ii', data)
            chunk = self.current[start:start + size]
            middle = len(chunk) // 2
            self.stream += frame(PREPARE_DATA, struct.pack('<I', len(chunk)), reply=reply)
            self.stream += frame(DATA, chunk[:middle], reply=reply)
            self.stream += frame(DATA, chunk[middle:], reply=reply)
            self.stream += frame(ACK_OK, reply=reply)
        else:  # 1502 free buffer, 1001 exit
            self.stream += frame(ACK_OK, reply=reply)

    def recv(self, size):
        if not self.stream:
            raise TimeoutError('nothing more to read')
        take = min(size, self.piece)
        out, self.stream = self.stream[:take], self.stream[take:]
        return out

    def close(self):
        self.closed = True


def connected_to(device):
    return mock.patch.object(zk_client.socket, 'create_connection', return_value=device)


class AllowListTests(SimpleTestCase):
    def test_allowed_commands_are_exactly_the_approved_list(self):
        self.assertEqual(
            ALLOWED_COMMANDS,
            frozenset({1000, 1001, 11, 50, 201, 1503, 1504, 1502}),
        )

    def test_forbidden_command_raises(self):
        # 2004 is named as CMD_CLEAR_ATTLOG in the plan; the protocol's clear-log
        # code is 15. Both are listed, along with the other destructive codes.
        forbidden = [
            2004, 15, 14, 20, 1002, 1003, 1004, 1005, 8, 18, 19, 12, 202, 88, 9, 7, 13,
        ]
        for command in forbidden:
            with self.subTest(command=command):
                client = ZkClient('192.0.2.1')
                client._sock = mock.Mock()
                with self.assertRaises(ForbiddenCommand):
                    client._send(command)
                client._sock.sendall.assert_not_called()

    def test_auth_is_refused_without_a_comm_key(self):
        client = ZkClient('192.0.2.1')
        client._sock = mock.Mock()
        with self.assertRaises(ForbiddenCommand):
            client._send(1102)
        client._sock.sendall.assert_not_called()

    def test_auth_does_not_widen_the_shared_list(self):
        ZkClient('192.0.2.1', comm_key='1234')
        self.assertNotIn(1102, ALLOWED_COMMANDS)

    def test_buffer_command_cannot_carry_a_template_read(self):
        # 1503 wraps an inner command, so allowing the outer code alone would let
        # fingerprint templates through.
        for inner, fct in [(9, 2), (7, 2), (88, 0), (9, 0), (13, 2), (15, 0)]:
            with self.subTest(inner=inner, fct=fct):
                client = ZkClient('192.0.2.1')
                client._sock = mock.Mock()
                with self.assertRaises(ForbiddenCommand):
                    client._send(1503, struct.pack('<bhii', 1, inner, fct, 0))
                client._sock.sendall.assert_not_called()

    def test_option_read_is_limited_to_the_serial(self):
        client = ZkClient('192.0.2.1')
        client._sock = mock.Mock()
        with self.assertRaises(ForbiddenCommand):
            client._send(11, b'~SomethingElse\0')
        client._sock.sendall.assert_not_called()

    def test_forbidden_command_also_refused_on_a_client_with_a_comm_key(self):
        client = ZkClient('192.0.2.1', comm_key='1234')
        client._sock = mock.Mock()
        for command in (2004, 15, 1003, 88, 202):
            with self.assertRaises(ForbiddenCommand):
                client._send(command)
        client._sock.sendall.assert_not_called()

    def test_gate_checks_every_payload(self):
        cases = [
            (1000, b'x'), (1001, b'x'), (50, b'x'), (201, b'\1\2\3\4'), (1502, b'x'),
            (1504, b'short'), (1504, b'\0' * 9),
        ]
        for command, data in cases:
            with self.subTest(command=command):
                client = ZkClient('192.0.2.1')
                client._sock = mock.Mock()
                with self.assertRaises(ForbiddenCommand):
                    client._send(command, data)
                client._sock.sendall.assert_not_called()

    def test_one_socket_write_in_the_source(self):
        tree = ast.parse(Path(zk_client.__file__).read_text(encoding='utf-8'))
        writes = [
            node for node in ast.walk(tree)
            if isinstance(node, ast.Attribute) and node.attr in ('send', 'sendall', 'sendto')
        ]
        self.assertEqual(len(writes), 1)

    def test_source_has_no_public_write_methods(self):
        banned = ('clear', 'delete', 'set_', 'write', 'disable', 'restart', 'template')
        for name in dir(ZkClient):
            for word in banned:
                self.assertNotIn(word, name.lower(), name)

    def test_comm_key_error_does_not_echo_the_key(self):
        with self.assertRaises(zk_client.ZkError) as caught:
            ZkClient('192.0.2.1', comm_key='not-a-number')
        self.assertNotIn('not-a-number', str(caught.exception))


class StampTests(SimpleTestCase):
    def test_decode_stamp(self):
        raw = encode_stamp(2026, 11, 7, 9, 30, 15)
        self.assertEqual(decode_stamp(raw), (date(2026, 11, 7), time(9, 30, 15)))

    def test_known_value(self):
        # 2018-01-01 00:00:00 = 18 * 12 * 31 * 86400, worked by hand.
        self.assertEqual(decode_stamp(578534400), (date(2018, 1, 1), time(0, 0, 0)))

    def test_feb_31_gives_none(self):
        self.assertEqual(decode_stamp(encode_stamp(2026, 2, 31, 8, 0, 0)), (None, None))

    def test_largest_stamp_decodes_to_2133(self):
        decoded, _clock = decode_stamp(0xFFFFFFFF - 86400 * 31 * 3)
        self.assertEqual(decoded.year, 2133)


class ParseUsersTests(SimpleTestCase):
    def test_parse_users_72_and_28_byte_records_keep_no_password(self):
        for label, rows in {
            '72': [user_72(1, b'1001', b'SamerSami', privilege=14),
                   user_72(2, b'1002', b'')],
            '28': [user_28(1, 1001, b'Samer', privilege=14),
                   user_28(2, 1002, b'')],
        }.items():
            with self.subTest(size=label):
                parsed = parse_users(table(rows), 2)
                self.assertEqual([r.user_code for r in parsed], ['1001', '1002'])
                self.assertTrue(parsed[0].is_admin)
                self.assertFalse(parsed[1].is_admin)
                self.assertEqual(parsed[1].name, '')
                self.assertNotIn('SECRET', repr(parsed))
                self.assertNotIn('987654321', repr(parsed))

    def test_row_has_only_the_approved_fields(self):
        row = parse_users(table([user_72(1, b'1001')]), 1)[0]
        self.assertEqual(set(row._fields), {'user_code', 'name', 'is_admin'})

    def test_count_that_does_not_match_raises(self):
        rows = [user_72(i, str(1000 + i).encode()) for i in range(3)]
        with self.assertRaises(UnexpectedRecordSize):
            parse_users(table(rows), 2)

    def test_blank_code_uses_the_slot(self):
        self.assertEqual(parse_users(table([user_72(5, b'')]), 1)[0].user_code, 'uid-5')

    def test_empty_table(self):
        self.assertEqual(parse_users(b'', 0), [])
        self.assertEqual(parse_users(table([]), 0), [])

    def test_unknown_record_size_raises_rather_than_guessing(self):
        body = struct.pack('<I', 50) + b'\0' * 50
        with self.assertRaises(UnexpectedRecordSize):
            parse_users(body, 1)

    def test_unknown_multiple_of_a_known_size_raises(self):
        # A 144-byte record would be two 72s if the count were not exact.
        with self.assertRaises(UnexpectedRecordSize):
            parse_users(struct.pack('<I', 144) + b'\0' * 144, 1)


class ParseLogsTests(SimpleTestCase):
    def test_parse_logs_40_16_8_byte_records(self):
        raw = encode_stamp(2026, 11, 7, 9, 0, 1)
        cases = {
            '40': table([log_40(5, b'1001', raw, verify=1, state=4),
                         log_40(6, b'1002', raw, verify=1, state=4)]),
            '16': table([log_16(1001, raw, verify=1, state=4),
                         log_16(1002, raw, verify=1, state=4)]),
            '8': table([log_8(5, raw, verify=1, state=4),
                        log_8(6, raw, verify=1, state=4)]),
        }
        codes = {'40': ['1001', '1002'], '16': ['1001', '1002'], '8': ['uid-5', 'uid-6']}
        for label, data in cases.items():
            with self.subTest(size=label):
                rows = parse_logs(data, 2)
                self.assertEqual([r.user_code for r in rows], codes[label])
                first = rows[0]
                self.assertEqual(first.raw_stamp, raw)
                self.assertEqual(first.date, date(2026, 11, 7))
                self.assertEqual(first.time, time(9, 0, 1))
                self.assertEqual(first.state, 4)
                self.assertEqual(first.verify_mode, 1)

    def test_impossible_date_is_kept_not_dropped(self):
        raw = encode_stamp(2026, 2, 31, 8, 0, 0)
        rows = parse_logs(table([log_40(5, b'1001', raw)]), 1)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].raw_stamp, raw)
        self.assertIsNone(rows[0].date)
        self.assertIsNone(rows[0].time)

    def test_8_byte_record_always_reports_the_slot(self):
        # The 8-byte format holds the machine's internal slot, not the HR number. A
        # slot can be reused, so a roster lookup could pin an old punch on a new
        # person, and one punch could be stored under two codes across runs.
        rows = parse_logs(table([log_8(5, 100)]), 1)
        self.assertEqual(rows[0].user_code, 'uid-5')

    def test_blank_or_dirty_code_in_40_byte_record_uses_the_slot(self):
        for raw_code in (b'', b'10\xff01', b'\x11\x11'):
            with self.subTest(code=raw_code):
                rows = parse_logs(table([log_40(5, raw_code, 100)]), 1)
                self.assertEqual(rows[0].user_code, 'uid-5')

    def test_truncated_table_raises(self):
        whole = table([log_40(5, b'1001', 100), log_40(6, b'1002', 100)])
        with self.assertRaises(TableTruncated):
            parse_logs(whole[:-10], 2)

    def test_count_above_the_table_raises(self):
        # 2,950 of 3,000 must never pass as a complete read.
        rows = [log_40(5, b'1001', 100 + i) for i in range(2950)]
        with self.assertRaises(UnexpectedRecordSize):
            parse_logs(table(rows), 3000)

    def test_count_below_the_table_raises(self):
        rows = [log_40(5, b'1001', 100 + i) for i in range(101)]
        with self.assertRaises(UnexpectedRecordSize):
            parse_logs(table(rows), 100)

    def test_empty_table_with_records_expected_raises(self):
        for empty in (b'', b'\0\0\0', struct.pack('<I', 0)):
            with self.subTest(table=empty):
                with self.assertRaises(TableTruncated):
                    parse_logs(empty, 3000)

    def test_zero_prefix_with_bytes_behind_it_raises(self):
        with self.assertRaises(ZkProtocolError):
            parse_logs(struct.pack('<I', 0) + log_40(5, b'1001', 100), 0)

    def test_bytes_past_the_prefix_raise(self):
        whole = table([log_40(5, b'1001', 100)]) + log_40(6, b'1002', 100)
        with self.assertRaises(ZkProtocolError):
            parse_logs(whole, 1)

    def test_unknown_record_size_raises(self):
        # 32-byte records would pass as 8-byte ones without an exact count.
        with self.assertRaises(UnexpectedRecordSize):
            parse_logs(struct.pack('<I', 1600) + b'\0' * 1600, 50)


class OverSocketTests(SimpleTestCase):
    def users_table(self):
        return table([user_72(1, b'1001', b'SamerSami'), user_72(2, b'1002')])

    def test_first_packet_matches_the_known_connect_bytes(self):
        # The widely published CMD_CONNECT packet. It pins the framing, the checksum
        # and the rule that the checksum covers the pre-increment reply number.
        device = FakeDevice()
        with connected_to(device), ZkClient('192.0.2.1'):
            first = device.packets[0]
        self.assertEqual(first, bytes.fromhex('5050827d08000000e80317fc00000000'))

    def test_read_users_over_fake_socket_chunked(self):
        device = FakeDevice(tables={9: self.users_table()})
        with connected_to(device), ZkClient('192.0.2.1') as client:
            rows = client.read_users()
        self.assertEqual([r.user_code for r in rows], ['1001', '1002'])
        self.assertEqual(rows[0].name, 'SamerSami')
        self.assertTrue(device.closed)
        self.assertEqual(device.sent, [1000, 50, 1503, 1504, 1502, 50, 1001])
        self.assertEqual(device.requests, ['0109000500000000000000'])

    def test_every_packet_sent_is_on_the_allowed_list(self):
        raw = encode_stamp(2026, 11, 7, 9, 0, 1)
        device = FakeDevice(
            tables={
                9: self.users_table(),
                13: table([log_40(1, b'1001', raw), log_40(2, b'1002', raw)]),
            },
            clock=struct.pack('<I', raw),
        )
        with connected_to(device), ZkClient('192.0.2.1') as client:
            client.read_serial()
            client.read_time()
            client.read_sizes()
            client.read_users()
            client.read_logs()
        self.assertTrue(set(device.sent) <= ALLOWED_COMMANDS, device.sent)

    def test_read_logs_large_table_spans_many_chunks(self):
        rows = [log_40(1, b'1001', 1000 + i) for i in range(3000)]  # 120,000 bytes
        device = FakeDevice(
            tables={9: self.users_table(), 13: table(rows), 'sizes': (2, 3000)},
            piece=4096,
        )
        with connected_to(device), ZkClient('192.0.2.1') as client:
            parsed = client.read_logs()
        self.assertEqual(len(parsed), 3000)
        self.assertEqual(parsed[-1].raw_stamp, 3999)
        self.assertGreaterEqual(device.sent.count(1504), 2)

    def test_log_request_bytes_are_pinned(self):
        device = FakeDevice(tables={13: table([log_40(1, b'1', 1), log_40(2, b'2', 2)])})
        with connected_to(device), ZkClient('192.0.2.1') as client:
            client.read_logs()
        self.assertEqual(device.requests, ['010d000000000000000000'])

    def test_odd_length_packet_checksums(self):
        # Computed independently of this code, for session 7, reply number 3.
        client = ZkClient('192.0.2.1')
        for command, data, expected in [
            (1503, bytes.fromhex('0109000500000000000000'), 0xec14),
            (1503, bytes.fromhex('010d000000000000000000'), 0xed14),
            (11, b'~SerialNumber\0', 0xb6e6),
            (1504, struct.pack('<ii', 0, 0xFFC0), 0xfa53),
        ]:
            with self.subTest(command=command, data=data):
                client._session, client._reply = 7, 3
                packet = client._packet(command, data)
                self.assertEqual(struct.unpack('<H', packet[10:12])[0], expected)

    def test_all_formats_over_the_socket(self):
        raw = encode_stamp(2026, 11, 7, 9, 0, 1)
        for label, users, logs, code in [
            ('72/40', user_72(1, b'1001'), log_40(1, b'1001', raw), '1001'),
            ('28/16', user_28(1, 1001), log_16(1001, raw), '1001'),
            ('28/8', user_28(1, 1001), log_8(1, raw), 'uid-1'),
        ]:
            with self.subTest(formats=label):
                device = FakeDevice(tables={
                    9: table([users]), 13: table([logs]), 'sizes': (1, 1),
                })
                with connected_to(device), ZkClient('192.0.2.1') as client:
                    self.assertEqual(client.read_users()[0].user_code, '1001')
                    self.assertEqual(client.read_logs()[0].user_code, code)

    def test_buffer_read_answered_with_prepare_data_is_accepted(self):
        # Published clients treat 1500 and 2000 alike here: the size is at [1:5].
        class PrepareAnswer(FakeDevice):
            def _respond(self, code, data, reply):
                if code == 1503:
                    self.current = self.tables[13]
                    self.stream += frame(
                        PREPARE_DATA, b'\0' + struct.pack('<I', len(self.current)), reply=reply,
                    )
                else:
                    super()._respond(code, data, reply)

        device = PrepareAnswer(tables={13: table([log_40(1, b'1', 1), log_40(2, b'2', 2)])})
        with connected_to(device), ZkClient('192.0.2.1') as client:
            self.assertEqual(len(client.read_logs()), 2)

    def test_small_table_answered_directly_with_data(self):
        class Direct(FakeDevice):
            def _respond(self, code, data, reply):
                if code == 1503:
                    self.stream += frame(DATA, self.tables[13], reply=reply)
                else:
                    super()._respond(code, data, reply)

        device = Direct(tables={13: table([log_40(1, b'1', 1), log_40(2, b'2', 2)])})
        with connected_to(device), ZkClient('192.0.2.1') as client:
            self.assertEqual(len(client.read_logs()), 2)
        self.assertNotIn(1504, device.sent)

    def test_chunk_answered_directly_with_data(self):
        class Direct(FakeDevice):
            def _respond(self, code, data, reply):
                if code == 1504:
                    start, size = struct.unpack('<ii', data)
                    self.stream += frame(DATA, self.current[start:start + size], reply=reply)
                else:
                    super()._respond(code, data, reply)

        device = Direct(tables={13: table([log_40(1, b'1', 1), log_40(2, b'2', 2)])})
        with connected_to(device), ZkClient('192.0.2.1') as client:
            self.assertEqual(len(client.read_logs()), 2)

    def test_punch_during_read_triggers_a_clean_reread(self):
        # A staff member punches during the first read. The second read is whole.
        class Growing(FakeDevice):
            def __init__(self):
                super().__init__()
                self.logs = [log_40(1, b'1001', 100 + i) for i in range(2)]
                self.size_reads = 0

            def _respond(self, code, data, reply):
                if code == 50:
                    self.size_reads += 1
                    if self.size_reads == 2:
                        self.logs.append(log_40(1, b'1001', 200))
                    self.stream += frame(ACK_OK, sizes_payload(0, len(self.logs)), reply=reply)
                elif code == 1503:
                    self.current = table(self.logs)
                    self.requests.append(data.hex())
                    self.stream += frame(
                        ACK_OK, b'\0' + struct.pack('<I', len(self.current)), reply=reply,
                    )
                else:
                    super()._respond(code, data, reply)

        device = Growing()
        with connected_to(device), ZkClient('192.0.2.1') as client:
            rows = client.read_logs()
        self.assertEqual(len(rows), 3)
        self.assertEqual(len(device.requests), 2)

    def test_low_count_race_cannot_pick_the_wrong_size(self):
        # Two 8-byte records with a stated count of 1 fit one 16-byte record exactly,
        # so only the second sizes read can catch this.
        class Race(FakeDevice):
            def __init__(self):
                super().__init__()
                self.logs = [log_8(5, 100)]
                self.size_reads = 0

            def _respond(self, code, data, reply):
                if code == 50:
                    self.size_reads += 1
                    stated = 1 if self.size_reads == 1 else 2
                    self.stream += frame(ACK_OK, sizes_payload(0, stated), reply=reply)
                elif code == 1503:
                    self.logs = [log_8(5, 100), log_8(6, 101)]
                    self.current = table(self.logs)
                    self.stream += frame(
                        ACK_OK, b'\0' + struct.pack('<I', len(self.current)), reply=reply,
                    )
                else:
                    super()._respond(code, data, reply)

        with connected_to(Race()), ZkClient('192.0.2.1') as client:
            rows = client.read_logs()
        self.assertEqual([r.user_code for r in rows], ['uid-5', 'uid-6'])

    def scripted_counts(self, counts, tables, base=None):
        """A machine whose stated count and table follow a script, one entry per read."""
        class Scripted(FakeDevice):
            def _respond(self, code, data, reply):
                if code == 50:
                    stated = counts.pop(0) if counts else 0
                    self.stream += frame(ACK_OK, sizes_payload(0, stated), reply=reply)
                elif code == 1503:
                    self.current = tables.pop(0)
                    self.requests.append(data.hex())
                    self.stream += frame(
                        ACK_OK, b'\0' + struct.pack('<I', len(self.current)), reply=reply,
                    )
                else:
                    super()._respond(code, data, reply)

        return Scripted()

    def test_log_cleared_during_the_read_keeps_the_table_in_hand(self):
        # The table may be the last copy. The count falls to 0 after a whole read.
        whole = table([log_40(1, b'1001', 100 + i) for i in range(3)])
        device = self.scripted_counts([3, 0], [whole])
        with connected_to(device), ZkClient('192.0.2.1') as client:
            rows = client.read_logs()
        self.assertEqual([r.raw_stamp for r in rows], [100, 101, 102])
        self.assertEqual(len(device.requests), 1)

    def test_log_cleared_then_one_new_punch_keeps_the_table_in_hand(self):
        whole = table([log_40(1, b'1001', 100 + i) for i in range(3)])
        device = self.scripted_counts([3, 1], [whole])
        with connected_to(device), ZkClient('192.0.2.1') as client:
            self.assertEqual(len(client.read_logs()), 3)

    def test_log_cleared_between_attempts_keeps_the_earlier_table(self):
        # Attempt 1 is whole but the count grew, so it re-reads; then the log is gone.
        whole = table([log_40(1, b'1001', 100 + i) for i in range(3)])
        device = self.scripted_counts([3, 4, 0], [whole])
        with connected_to(device), ZkClient('192.0.2.1') as client:
            with self.assertRaises(ZkProtocolError) as caught:
                client.read_logs()
        self.assertEqual(caught.exception.raw_table, whole)

    def test_undecodable_table_kept_when_the_retry_loses_the_connection(self):
        class Drops(FakeDevice):
            size_reads = 0

            def _respond(self, code, data, reply):
                if code == 50:
                    self.size_reads += 1
                    if self.size_reads == 3:
                        return  # recv then raises TimeoutError
                super()._respond(code, data, reply)

        device = Drops(tables={13: self.undecodable()})
        with connected_to(device), ZkClient('192.0.2.1') as client:
            with self.assertRaises(TimeoutError) as caught:
                client.read_logs()
        self.assertEqual(caught.exception.raw_table, self.undecodable())

    def undecodable(self):
        return struct.pack('<I', 64) + b'\xAB' * 64  # 32-byte records, count 2

    def test_undecodable_log_keeps_the_raw_bytes_on_the_error(self):
        device = FakeDevice(tables={13: self.undecodable()})
        with connected_to(device), ZkClient('192.0.2.1') as client:
            with self.assertRaises(UnexpectedRecordSize) as caught:
                client.read_logs()
        self.assertEqual(caught.exception.raw_table, self.undecodable())
        self.assertEqual(len(device.requests), 3, 'tried three times')

    def test_log_that_keeps_changing_keeps_the_raw_bytes_on_the_error(self):
        class Busy(FakeDevice):
            count = 0

            def _respond(self, code, data, reply):
                if code == 50:
                    Busy.count += 1
                    self.stream += frame(ACK_OK, sizes_payload(0, Busy.count), reply=reply)
                else:
                    super()._respond(code, data, reply)

        device = Busy(tables={13: table([log_40(1, b'1', 1)])})
        with connected_to(device), ZkClient('192.0.2.1') as client:
            with self.assertRaises(ZkProtocolError) as caught:
                client.read_logs()
        self.assertEqual(caught.exception.raw_table, table([log_40(1, b'1', 1)]))

    def test_undecodable_user_table_is_never_kept(self):
        # User tables hold passwords and card numbers.
        device = FakeDevice(tables={9: struct.pack('<I', 100) + b'SECRET'.ljust(100, b'x')})
        with connected_to(device), ZkClient('192.0.2.1') as client:
            with self.assertRaises(UnexpectedRecordSize) as caught:
                client.read_users()
        self.assertIsNone(caught.exception.raw_table)
        self.assertNotIn('SECRET', repr(caught.exception))

    def test_machine_answering_nothing_for_records_expected_raises(self):
        device = FakeDevice(tables={13: b''})
        with connected_to(device), ZkClient('192.0.2.1') as client:
            with self.assertRaises(TableTruncated):
                client.read_logs()

    def test_session_deadline_stops_a_trickling_machine(self):
        # Each recv succeeds, so only an overall limit can stop it.
        device = FakeDevice(piece=1)
        with connected_to(device), ZkClient('192.0.2.1') as client:
            client._deadline = zk_client.time.monotonic() - 1
            with self.assertRaises(ZkProtocolError):
                client.read_sizes()

    def test_impossible_clock_raises_clock_invalid(self):
        raw = encode_stamp(2026, 2, 31, 8, 0, 0)
        device = FakeDevice(clock=struct.pack('<I', raw))
        with connected_to(device), ZkClient('192.0.2.1') as client:
            with self.assertRaises(ClockInvalid):
                client.read_time()

    def test_empty_machine_reads_no_table(self):
        device = FakeDevice(tables={'sizes': (0, 0)})
        with connected_to(device), ZkClient('192.0.2.1') as client:
            self.assertEqual(client.read_users(), [])
            self.assertEqual(client.read_logs(), [])
        self.assertNotIn(1503, device.sent)

    def test_short_chunk_raises_instead_of_returning_part_of_the_log(self):
        class ShortDevice(FakeDevice):
            def _respond(self, code, data, reply):
                if code == 1504:
                    self.stream += frame(PREPARE_DATA, struct.pack('<I', 100), reply=reply)
                    self.stream += frame(DATA, b'\0' * 40, reply=reply)
                    self.stream += frame(ACK_OK, reply=reply)
                else:
                    super()._respond(code, data, reply)

        device = ShortDevice(tables={9: self.users_table()})
        with connected_to(device), ZkClient('192.0.2.1') as client:
            with self.assertRaises(ZkProtocolError):
                client.read_users()
        self.assertTrue(device.closed)

    def test_connection_closed_midway_raises(self):
        class ClosingDevice(FakeDevice):
            def recv(self, size):
                return b''

        device = ClosingDevice()
        with connected_to(device):
            with self.assertRaises(ZkProtocolError):
                ZkClient('192.0.2.1').__enter__()
        self.assertTrue(device.closed)

    def test_bad_frame_magic_raises(self):
        class BadMagic(FakeDevice):
            def _respond(self, code, data, reply):
                self.stream += b'XXXX' + b'\0' * 12

        with connected_to(BadMagic()):
            with self.assertRaises(ZkProtocolError):
                ZkClient('192.0.2.1').__enter__()

    def test_oversized_frame_is_refused(self):
        class Huge(FakeDevice):
            def _respond(self, code, data, reply):
                self.stream += MAGIC + struct.pack('<I', 0x7FFFFFFF)

        with connected_to(Huge()):
            with self.assertRaises(ZkProtocolError):
                ZkClient('192.0.2.1').__enter__()

    def test_device_error_on_clock_read_raises(self):
        class ClockError(FakeDevice):
            def _respond(self, code, data, reply):
                if code == 201:
                    self.stream += frame(ACK_ERROR, reply=reply)
                else:
                    super()._respond(code, data, reply)

        with connected_to(ClockError()), ZkClient('192.0.2.1') as client:
            with self.assertRaises(ZkProtocolError):
                client.read_time()

    def test_read_time(self):
        raw = encode_stamp(2026, 11, 7, 9, 30, 15)
        device = FakeDevice(clock=struct.pack('<I', raw))
        with connected_to(device), ZkClient('192.0.2.1') as client:
            self.assertEqual(client.read_time(), datetime(2026, 11, 7, 9, 30, 15))

    def test_read_sizes(self):
        device = FakeDevice(tables={'sizes': (23, 2241)})
        with connected_to(device), ZkClient('192.0.2.1') as client:
            sizes = client.read_sizes()
        self.assertEqual((sizes.users, sizes.records), (23, 2241))
        self.assertEqual(sizes.records_capacity, 100000)

    def test_read_serial(self):
        device = FakeDevice(serial=b'~SerialNumber=A2ML173860738\0')
        with connected_to(device), ZkClient('192.0.2.1') as client:
            self.assertEqual(client.read_serial(), 'A2ML173860738')

    def test_read_serial_unanswered_is_none(self):
        device = FakeDevice(serial=b'')
        with connected_to(device), ZkClient('192.0.2.1') as client:
            self.assertIsNone(client.read_serial())

    def test_unauthorised_without_key_raises_comm_key_required(self):
        device = FakeDevice(unauthorised=True)
        with connected_to(device):
            with self.assertRaises(CommKeyRequired):
                ZkClient('192.0.2.1').__enter__()
        self.assertNotIn(1102, device.sent)
        self.assertTrue(device.closed)

    def test_comm_key_sent_only_when_configured(self):
        device = FakeDevice(unauthorised=True)
        with connected_to(device), ZkClient('192.0.2.1', comm_key='1234'):
            pass
        self.assertEqual(device.sent, [1000, 1102, 1001])

    def test_comm_key_bytes_on_the_wire(self):
        # Key 1, session 7, ticks 50, worked by hand from the published algorithm.
        device = FakeDevice(unauthorised=True)
        with connected_to(device), ZkClient('192.0.2.1', comm_key='1'):
            auth_packet = device.packets[1]
        self.assertEqual(auth_packet[16:], bytes.fromhex('61fd3279'))

    def test_session_from_connect_is_used_afterwards(self):
        device = FakeDevice()
        with connected_to(device), ZkClient('192.0.2.1') as client:
            client.read_sizes()
            sizes_packet = device.packets[1]
        self.assertEqual(struct.unpack('<H', sizes_packet[12:14])[0], 7)

    def test_no_auth_packet_when_device_does_not_ask(self):
        device = FakeDevice()
        with connected_to(device), ZkClient('192.0.2.1', comm_key='1234'):
            pass
        self.assertNotIn(1102, device.sent)

    def test_wrong_comm_key_raises(self):
        device = FakeDevice(unauthorised=True, accept_key=False)
        with connected_to(device):
            with self.assertRaises(CommKeyRejected):
                ZkClient('192.0.2.1', comm_key='1234').__enter__()
        self.assertTrue(device.closed)

    def test_failed_disconnect_does_not_hide_a_good_read(self):
        class NoExit(FakeDevice):
            def sendall(self, packet):
                if struct.unpack('<H', packet[8:10])[0] == 1001:
                    raise OSError('gone')
                super().sendall(packet)

        device = NoExit(tables={9: self.users_table()})
        with connected_to(device), ZkClient('192.0.2.1') as client:
            rows = client.read_users()
        self.assertEqual(len(rows), 2)
        self.assertTrue(device.closed)


class StandaloneTests(SimpleTestCase):
    def test_agent_imports_only_the_standard_library(self):
        package = Path(zk_client.__file__).parent
        for source in package.glob('*.py'):
            tree = ast.parse(source.read_text(encoding='utf-8'))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.level == 0:
                    names = [node.module]
                else:
                    continue
                for name in names:
                    self.assertIn(
                        name.split('.')[0], sys.stdlib_module_names,
                        f'{source.name} imports {name}',
                    )
