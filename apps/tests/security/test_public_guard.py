"""N6 / Task 2 - self-hosted form guard: proof of work, honeypot, fill time, per-phone limit."""
import hashlib
from unittest import mock

from django.core.cache import cache
from django.test import SimpleTestCase, TestCase, override_settings
from rest_framework.test import APIClient

from core import public_guard
from core.public_guard import GUARD_MESSAGES, GuardError, check_submission, issue_challenge

CHALLENGE_URL = '/api/public/challenge/'


def solve(challenge, difficulty, limit=1 << 20):
    """Test-only solver: the same search the browser does in frontend/src/utils/publicGuard.js."""
    for nonce in range(limit):
        if public_guard.leading_zero_bits(
                hashlib.sha256(f'{challenge}:{nonce}'.encode()).digest()) >= difficulty:
            return str(nonce)
    return None


class _Clock:
    """Patches core.public_guard's clock; .now moves forward by hand."""

    def __init__(self, test, start=1_800_000_000.0):
        self.now = start
        p = mock.patch.object(public_guard.time, 'time', side_effect=lambda: self.now)
        p.start()
        test.addCleanup(p.stop)


@override_settings(PUBLIC_POW_DIFFICULTY=8, PUBLIC_POW_TTL_SECONDS=600, PUBLIC_MIN_FILL_SECONDS=3,
                   PUBLIC_PHONE_DAILY_MAX=3)
class PublicGuardTests(SimpleTestCase):

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.clock = _Clock(self)

    def _solved(self, form='notify', **extra):
        ch = issue_challenge(form)
        data = {'challenge': ch['challenge'], 'nonce': solve(ch['challenge'], ch['difficulty'])}
        data.update(extra)
        return data

    def _code(self, data, form='notify', phone=None):
        with self.assertRaises(GuardError) as cm:
            check_submission(data, form, phone=phone)
        return cm.exception.code

    def test_issue_challenge_shape(self):
        ch = issue_challenge('notify')
        self.assertEqual(set(ch), {'challenge', 'difficulty'})
        self.assertEqual(ch['difficulty'], 8)

    def test_valid_submission_passes(self):
        data = self._solved()
        self.clock.now += 5
        self.assertIsNone(check_submission(data, 'notify'))

    def test_honeypot_flags_bot(self):
        data = self._solved(website='http://spam.example')
        self.clock.now += 5
        self.assertEqual(self._code(data), 'bot')

    def test_expired_challenge(self):
        data = self._solved()
        self.clock.now += 601
        self.assertEqual(self._code(data), 'expired')

    def test_tampered_or_missing_challenge_is_expired(self):
        data = self._solved()
        self.clock.now += 5
        self.assertEqual(self._code({**data, 'challenge': data['challenge'] + 'x'}), 'expired')
        self.assertEqual(self._code({'nonce': '1'}), 'expired')

    def test_too_fast(self):
        data = self._solved()
        self.clock.now += 1
        self.assertEqual(self._code(data), 'too_fast')

    def test_bad_solution(self):
        ch = issue_challenge('notify')
        self.clock.now += 5
        bad = next(str(n) for n in range(10_000) if public_guard.leading_zero_bits(
            hashlib.sha256(f"{ch['challenge']}:{n}".encode()).digest()) < 8)
        self.assertEqual(self._code({'challenge': ch['challenge'], 'nonce': bad}), 'bad_solution')
        self.assertEqual(self._code({'challenge': ch['challenge']}), 'bad_solution')

    def test_solution_is_single_use(self):
        data = self._solved()
        self.clock.now += 5
        check_submission(data, 'notify')
        self.assertEqual(self._code(data), 'replayed')

    def test_challenge_bound_to_form(self):
        data = self._solved('portal_link')
        self.clock.now += 5
        self.assertEqual(self._code(data, form='notify'), 'wrong_form')

    def test_phone_daily_limit(self):
        for _ in range(3):
            data = self._solved()
            self.clock.now += 5
            check_submission(data, 'notify', phone='01012345678')
        data = self._solved()
        self.clock.now += 5
        self.assertEqual(self._code(data, phone='01012345678'), 'phone_limit')
        data = self._solved()
        self.clock.now += 5
        self.assertIsNone(check_submission(data, 'notify', phone='01099999999'))
        # the counter is per form: the same phone on another form still passes
        data = self._solved('portal_link')
        self.clock.now += 5
        self.assertIsNone(check_submission(data, 'portal_link', phone='01012345678'))

    def test_phone_reformatting_shares_one_counter(self):
        variants = ['01012345678', '+201012345678', '0101 234 5678', '201012345678',
                    '00201012345678']
        for v in variants:
            self.assertEqual(public_guard.normalize_phone(v), '01012345678', v)
        for v in variants[:3]:
            data = self._solved()
            self.clock.now += 5
            check_submission(data, 'notify', phone=v)
        data = self._solved()
        self.clock.now += 5
        self.assertEqual(self._code(data, phone=variants[3]), 'phone_limit')
        data = self._solved()
        self.clock.now += 5
        self.assertEqual(self._code(data, phone=variants[4]), 'phone_limit')

    def test_refusal_logged_with_real_code_and_masked_phone(self):
        data = self._solved(website='x')
        self.clock.now += 5
        with self.assertLogs('elrezeiky.public_guard', 'INFO') as logs:
            self._code(data, phone='01012345678')
        self.assertEqual(len(logs.output), 1)
        self.assertIn('code=bot', logs.output[0])
        self.assertIn('form=notify', logs.output[0])
        self.assertIn('***5678', logs.output[0])
        self.assertNotIn('01012345678', logs.output[0])

    def test_bot_and_phone_limit_look_like_success(self):
        self.assertEqual(GUARD_MESSAGES['bot'], GUARD_MESSAGES['phone_limit'])
        self.assertEqual(GUARD_MESSAGES['bot'], public_guard.PUBLIC_OK_MESSAGE)
        for code in ('bot', 'expired', 'replayed', 'too_fast', 'bad_solution', 'wrong_form',
                     'phone_limit'):
            self.assertTrue(GUARD_MESSAGES[code])


class LeadingZeroBitsTests(SimpleTestCase):
    """Fixed vectors: frontend/src/utils/publicGuard.js must count bits exactly like this."""

    def test_fixed_vectors(self):
        for nonce, hexdigest, bits in (
                (492, '0008f27acf63eeb62f76145f053bb344d75500f5d063f591090fa372b9130632', 12),
                (3450, '0001ca5195e401ccb6cf44a007851b79d7c22a378eb3d5d803061c4bf7556655', 15),
                (56938, '0000fb91781b7adc284967b5cab7c0474c487973b0060d8836fb10dcc71748ac', 16)):
            digest = hashlib.sha256(f'vector-challenge:{nonce}'.encode()).digest()
            self.assertEqual(digest.hex(), hexdigest)
            self.assertEqual(public_guard.leading_zero_bits(digest), bits)
        self.assertEqual(public_guard.leading_zero_bits(bytes(32)), 256)
        self.assertEqual(public_guard.leading_zero_bits(b'\x80' + bytes(31)), 0)


class DifficultyTests(SimpleTestCase):

    def setUp(self):
        cache.clear()

    @override_settings(PUBLIC_POW_DIFFICULTY=16)
    def test_challenge_is_solvable_at_configured_difficulty(self):
        ch = issue_challenge('notify')
        self.assertEqual(ch['difficulty'], 16)
        self.assertIsNotNone(solve(ch['challenge'], 16, limit=1 << 20))

    def test_defaults(self):
        from django.conf import settings
        self.assertEqual(settings.PUBLIC_POW_TTL_SECONDS, 600)
        self.assertEqual(settings.PUBLIC_POW_DIFFICULTY, 16)
        self.assertEqual(settings.PUBLIC_MIN_FILL_SECONDS, 3)
        self.assertEqual(settings.PUBLIC_PHONE_DAILY_MAX, 3)


class ChallengeEndpointTests(TestCase):

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.client = APIClient()

    def test_challenge_endpoint_returns_challenge(self):
        for form in ('notify', 'portal_link'):
            r = self.client.get(CHALLENGE_URL, {'form': form})
            self.assertEqual(r.status_code, 200, r.content)
            self.assertEqual(set(r.json()), {'challenge', 'difficulty', 'min_fill_seconds'})

    @override_settings(PUBLIC_MIN_FILL_SECONDS=5)
    def test_challenge_endpoint_returns_min_fill_seconds(self):
        r = self.client.get(CHALLENGE_URL, {'form': 'notify'})
        self.assertEqual(r.json()['min_fill_seconds'], 5)

    def test_challenge_endpoint_unknown_form_400(self):
        self.assertEqual(self.client.get(CHALLENGE_URL, {'form': 'nope'}).status_code, 400)
        self.assertEqual(self.client.get(CHALLENGE_URL).status_code, 400)

    def test_challenge_endpoint_throttled_per_ip(self):
        from apps.access.public_views import ChallengeThrottle
        self.assertEqual(ChallengeThrottle().get_rate(), '60/hour')
        with mock.patch.object(ChallengeThrottle, 'get_rate', return_value='2/hour'):
            codes = [self.client.get(CHALLENGE_URL, {'form': 'notify'}).status_code for _ in range(3)]
        self.assertEqual(codes, [200, 200, 429])
