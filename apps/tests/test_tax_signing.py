"""
The tax seal path (apps/tax_invoicing/signing.py + cades.py, deploy/tax_signing_agent/agent.py).

Everything here uses a software RSA key and a fake PKCS#11 session. Nothing in this file has touched
the real USB token, the signing workstation, or ETA. A pass means our logic is right against ETA's
published format document; only the smoke test on the workstation and ETA's preprod can say more.
"""
import base64
import datetime as dt
import hashlib
import importlib.util
import io
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import warnings
from pathlib import Path
from unittest import mock

from asn1crypto import cms, core
from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa, utils
from cryptography.x509.oid import NameOID
from django.conf import settings
from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

from apps.access import public_paths
from apps.tax_invoicing import cades, fiscal, signing
from apps.tax_invoicing.models import TaxSigningCertification, TaxSigningJob
from apps.tests.factories import make_branch, make_user
from apps.users.models import RoleModuleAccess
from core.auth_cookies import ACCESS_COOKIE

AGENT_DIR = Path(settings.BASE_DIR) / 'deploy' / 'tax_signing_agent'
AGENT_TOKEN = 'a' * 40
NEXT_URL = '/api/tax-invoicing/signing-agent/next/'
PIN = 'PIN-canary-731946'
OID_DIGESTED_DATA = '1.2.840.113549.1.7.5'
AGENT_SIGNER = 'apps.tax_invoicing.signing.AgentSigner'
AGENT_USERNAME, AGENT_ROLE = 'tax_signing_agent', 'viewer'
AGENT_PASSWORD = 'Password-canary-55821'
TEXT = '"ISSUER""ADDRESS""الرزيقي"'


def _load_agent():
    """agent.py is a script beside its copy of cades.py, so it is loaded the way Python runs it."""
    with mock.patch.object(sys, 'path', [str(AGENT_DIR), *sys.path]), mock.patch.dict(sys.modules):
        sys.modules.pop('cades', None)
        spec = importlib.util.spec_from_file_location('tax_signing_agent', AGENT_DIR / 'agent.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module


agent_module = _load_agent()


class Seal:
    """A software stand-in for the token's key and certificate."""

    def __init__(self, name='Test Seal', days=30, ca=False, key=None):
        self.key = key or rsa.generate_private_key(public_exponent=65537, key_size=2048)
        subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)])
        now = dt.datetime.now(dt.timezone.utc)
        builder = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject)
                   .public_key(self.key.public_key()).serial_number(x509.random_serial_number())
                   .not_valid_before(now - dt.timedelta(days=60)).not_valid_after(now + dt.timedelta(days=days))
                   .add_extension(x509.BasicConstraints(ca=ca, path_length=None), critical=True))
        self.cert = builder.sign(self.key, hashes.SHA256())
        self.der = self.cert.public_bytes(serialization.Encoding.DER)
        self.thumbprint = hashlib.sha1(self.der, usedforsecurity=False).hexdigest().upper()

    def sign(self, data):
        return self.key.sign(data, padding.PKCS1v15(), hashes.SHA256())

    def cades(self, content):
        return cades.build_cades_bes(content, self.der, self.sign)

    def b64(self, text):
        return base64.b64encode(self.cades(text.encode('utf-8'))).decode()


SEAL = Seal()
OTHER_SEAL = Seal('Other Seal')


# ── CAdES-BES ──────────────────────────────────────────────────────────────────────────────────

class CadesRoundTripTests(SimpleTestCase):
    content = TEXT.encode('utf-8')

    def _parts(self, der=None):
        info = cms.ContentInfo.load(der or SEAL.cades(self.content))
        signed = info['content']
        return info, signed, signed['signer_infos'][0]

    def test_round_trip_returns_the_signers_details(self):
        details = cades.inspect_signature(SEAL.cades(self.content), self.content)
        self.assertEqual(details['subject'], 'CN=Test Seal')
        self.assertEqual(details['thumbprint'], SEAL.thumbprint)
        self.assertEqual(details['not_after'], SEAL.cert.not_valid_after_utc.isoformat())

    def test_signed_attributes_are_hashed_as_a_set_not_as_the_wire_tag(self):
        """RFC 5652 §5.4, checked without inspect_signature: the old attrs.dump(force=True) was the 0xA0 form."""
        signer = self._parts()[2]
        signature = signer['signature'].native
        on_the_wire = signer['signed_attrs'].dump(force=True)
        self.assertEqual(on_the_wire[0], 0xA0)
        with self.assertRaises(InvalidSignature):
            SEAL.key.public_key().verify(signature, on_the_wire, padding.PKCS1v15(), hashes.SHA256())
        SEAL.key.public_key().verify(signature, b'\x31' + on_the_wire[1:], padding.PKCS1v15(), hashes.SHA256())

    def test_structure_is_what_etas_format_document_asks_for(self):
        """Digital Signature Format for E-Invoice System v1.1, the table in §5."""
        info, signed, signer = self._parts()
        self.assertEqual(info['content_type'].dotted, '1.2.840.113549.1.7.2')
        self.assertEqual(signed['version'].native, 'v3')
        self.assertEqual([a['algorithm'].dotted for a in signed['digest_algorithms']], ['2.16.840.1.101.3.4.2.1'])
        self.assertEqual(signed['encap_content_info']['content_type'].dotted, OID_DIGESTED_DATA)
        self.assertIsNone(signed['encap_content_info']['content'].native)
        self.assertEqual(len(signed['certificates']), 1)
        self.assertEqual(signed['certificates'][0].chosen.dump(), SEAL.der)
        self.assertEqual(len(signed['signer_infos']), 1)
        self.assertEqual(signer['version'].native, 'v1')
        self.assertEqual(signer['sid'].name, 'issuer_and_serial_number')
        self.assertEqual(signer['digest_algorithm']['algorithm'].dotted, '2.16.840.1.101.3.4.2.1')
        self.assertEqual(signer['signature_algorithm']['algorithm'].dotted, '1.2.840.113549.1.1.11')
        self.assertIsNone(signer['unsigned_attrs'].native)
        attrs = {a['type'].dotted: a['values'] for a in signer['signed_attrs']}
        self.assertEqual(set(attrs), {'1.2.840.113549.1.9.3', '1.2.840.113549.1.9.4', '1.2.840.113549.1.9.5',
                                      '1.2.840.113549.1.9.16.2.47'})
        self.assertEqual(attrs['1.2.840.113549.1.9.3'][0].dotted, OID_DIGESTED_DATA)
        self.assertEqual(attrs['1.2.840.113549.1.9.4'][0].native, hashlib.sha256(self.content).digest())
        self.assertEqual(attrs['1.2.840.113549.1.9.5'][0].name, 'utc_time')
        cert_id = attrs['1.2.840.113549.1.9.16.2.47'][0]['certs'][0]
        self.assertEqual(cert_id['hash_algorithm']['algorithm'].dotted, '2.16.840.1.101.3.4.2.1')
        self.assertEqual(cert_id['cert_hash'].native, hashlib.sha256(SEAL.der).digest())

    def test_signing_time_is_the_given_time_in_utc(self):
        cairo = dt.timezone(dt.timedelta(hours=2))
        der = cades.build_cades_bes(self.content, SEAL.der, SEAL.sign, signing_time=dt.datetime(2026, 11, 7, 12, 0, tzinfo=cairo))
        attrs = {a['type'].native: a['values'][0] for a in self._parts(der)[2]['signed_attrs']}
        self.assertEqual(attrs['signing_time'].native, dt.datetime(2026, 11, 7, 10, 0, tzinfo=dt.timezone.utc))

    def test_tampered_content_refused(self):
        with self.assertRaisesRegex(cades.SignatureInvalid, 'does not cover'):
            cades.inspect_signature(SEAL.cades(self.content), self.content + b' ')

    def test_tampered_signed_attribute_refused(self):
        der = bytearray(SEAL.cades(self.content))
        position = bytes(der).index(hashlib.sha256(SEAL.der).digest())
        der[position] ^= 0xFF      # inside signing-certificate-v2
        with self.assertRaises(cades.SignatureInvalid):
            cades.inspect_signature(bytes(der), self.content)

    def test_signature_from_the_wrong_key_refused(self):
        """Certificate A, signed by key B."""
        der = cades.build_cades_bes(self.content, SEAL.der, OTHER_SEAL.sign)
        with self.assertRaisesRegex(cades.SignatureInvalid, 'does not verify'):
            cades.inspect_signature(der, self.content)

    def _rebuilt(self, change):
        """A good signature with one thing changed afterwards. The format check must catch it by name."""
        der = SEAL.cades(self.content)
        info = cms.ContentInfo.load(der)
        change(info)
        return info.dump(force=True)

    def test_plain_data_content_type_refused(self):
        """What this file used to build. ETA's format says digestedData."""
        def change(info):
            info['content']['encap_content_info']['content_type'] = 'data'
        with self.assertRaisesRegex(cades.SignatureInvalid, 'digestedData'):
            cades.inspect_signature(self._rebuilt(change), self.content)

    def test_extra_certificate_refused(self):
        def change(info):
            info['content']['certificates'].append(cms.CertificateChoices.load(
                cms.CertificateChoices({'certificate': x509_to_asn1(OTHER_SEAL)}).dump()))
        with self.assertRaisesRegex(cades.SignatureInvalid, 'certificate only'):
            cades.inspect_signature(self._rebuilt(change), self.content)

    def test_embedded_content_refused(self):
        oid = core.ObjectIdentifier(OID_DIGESTED_DATA).dump()
        payload = cms.DigestedData({'version': 'v0', 'digest_algorithm': {'algorithm': 'sha256'},   # asn1crypto parses it
                                    'encap_content_info': {'content_type': 'data'}, 'digest': b'\0' * 32})
        inner = core.OctetString(payload.dump()).dump()
        body = oid + bytes([0xA0, len(inner)]) + inner     # all of it under 128 bytes: short-form lengths
        embedded = cms.EncapsulatedContentInfo.load(bytes([0x30, len(body)]) + body)

        def change(info):
            info['content']['encap_content_info'] = embedded
        with self.assertRaisesRegex(cades.SignatureInvalid, 'detached'):
            cades.inspect_signature(self._rebuilt(change), self.content)

    def test_certificate_swapped_after_signing_refused(self):
        def change(info):
            info['content']['certificates'][0] = cms.CertificateChoices({'certificate': x509_to_asn1(OTHER_SEAL)})
        with self.assertRaises(cades.SignatureInvalid):
            cades.inspect_signature(self._rebuilt(change), self.content)

    def test_non_rsa_certificate_refused_cleanly(self):
        ec_key = ec.generate_private_key(ec.SECP256R1())
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'EC Seal')])
        now = dt.datetime.now(dt.timezone.utc)
        cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(ec_key.public_key())
                .serial_number(5).not_valid_before(now).not_valid_after(now + dt.timedelta(days=1))
                .sign(ec_key, hashes.SHA256()))
        der = cades.build_cades_bes(self.content, cert.public_bytes(serialization.Encoding.DER), lambda b: b'\0' * 64)
        with self.assertRaisesRegex(cades.SignatureInvalid, 'not RSA'):
            cades.inspect_signature(der, self.content)

    def test_negative_serial_like_egypt_trust_signs_and_verifies_quietly(self):
        """The real seal's certificate (Egypt Trust CA G7) encodes serial AB33CB… with no leading zero, so it
        parses as negative. It must sign, verify and identify the same way, without a warning."""
        from asn1crypto import x509 as ax509
        seal = Seal('Negative Serial Seal')
        cert = ax509.Certificate.load(seal.der)
        cert['tbs_certificate']['serial_number'] = int.from_bytes(bytes.fromhex('AB33CBEA34E6BFBAA4D1318B3AAD21DA'),
                                                                  'big', signed=True)
        tbs = cert['tbs_certificate'].dump(force=True)
        cert['signature_value'] = seal.key.sign(tbs, padding.PKCS1v15(), hashes.SHA256())
        seal.der = cert.dump(force=True)
        self.assertIn(bytes.fromhex('0210AB33CBEA'), seal.der)      # really encoded without the zero
        with warnings.catch_warnings():
            warnings.simplefilter('error')
            details = cades.inspect_signature(seal.cades(self.content), self.content)
            parsed = agent_module.parse_certificate(seal.der)
        self.assertEqual(details['thumbprint'], hashlib.sha1(seal.der, usedforsecurity=False).hexdigest().upper())
        self.assertEqual(parsed.serial, 'AB33CBEA34E6BFBAA4D1318B3AAD21DA')

    def test_garbage_refused(self):
        for junk in (b'', b'not a signature', b'\x30\x03\x01\x01\xff'):
            with self.assertRaisesRegex(cades.SignatureInvalid, 'unreadable'):
                cades.inspect_signature(junk, self.content)

    @unittest.skipUnless(shutil.which('openssl'), 'the openssl command is not installed')
    def test_openssl_accepts_it_independently(self):
        """A verifier we did not write. It proves valid CMS, not that ETA accepts it."""
        with tempfile.TemporaryDirectory() as folder:
            sig, data = Path(folder, 'sig.der'), Path(folder, 'data.bin')
            sig.write_bytes(SEAL.cades(self.content))
            data.write_bytes(self.content)
            done = subprocess.run(  # nosec B603 B607 - a fixed command on files this test just wrote
                ['openssl', 'cms', '-verify', '-binary', '-inform', 'DER', '-in', str(sig), '-content', str(data),
                 '-noverify', '-out', os.devnull], capture_output=True, text=True, timeout=30, check=False)
        self.assertEqual(done.returncode, 0, done.stderr)

    def test_the_workstation_copy_is_identical(self):
        def read(path):
            return path.read_bytes().replace(b'\r\n', b'\n')
        self.assertEqual(read(AGENT_DIR / 'cades.py'), read(Path(cades.__file__)),
                         'copy apps/tax_invoicing/cades.py to deploy/tax_signing_agent/cades.py')


def x509_to_asn1(seal):
    from asn1crypto import x509 as ax509
    return ax509.Certificate.load(seal.der)


# ── The live gate ──────────────────────────────────────────────────────────────────────────────

@override_settings(TAX_SIGNER_CLASS=AGENT_SIGNER, TAX_SIGNING_CERT_THUMBPRINT=SEAL.thumbprint)
class ReadyForLiveTests(TestCase):
    def _certification(self, **values):
        fields = {'passed': True, 'thumbprint': SEAL.thumbprint, 'not_after': timezone.now() + dt.timedelta(days=30)}
        fields.update(values)
        return TaxSigningCertification.objects.create(**fields)

    def test_refused_without_a_certification(self):
        with self.assertRaisesRegex(signing.SigningUnavailable, 'لم ينجح اختبار الختم'):
            signing.assert_ready_for_live()

    def test_refused_when_the_latest_smoke_test_failed(self):
        self._certification()
        self._certification(passed=False, thumbprint='', not_after=None, detail='no')
        with self.assertRaisesRegex(signing.SigningUnavailable, 'لم ينجح اختبار الختم'):
            signing.assert_ready_for_live()

    def test_refused_on_thumbprint_mismatch(self):
        self._certification(thumbprint=OTHER_SEAL.thumbprint)
        with self.assertRaisesRegex(signing.SigningUnavailable, 'بصمة'):
            signing.assert_ready_for_live()

    @override_settings(TAX_SIGNING_CERT_THUMBPRINT='')
    def test_refused_when_no_thumbprint_is_configured(self):
        self._certification()
        with self.assertRaisesRegex(signing.SigningUnavailable, 'بصمة'):
            signing.assert_ready_for_live()

    def test_refused_on_expiry(self):
        self._certification(not_after=timezone.now() - dt.timedelta(minutes=1))
        with self.assertRaisesRegex(signing.SigningUnavailable, 'منتهية'):
            signing.assert_ready_for_live()

    def test_ready_with_a_passed_matching_certification(self):
        self._certification()
        signing.assert_ready_for_live()

    def test_thumbprint_copied_from_the_windows_dialog_still_matches(self):
        spaced = ' '.join(SEAL.thumbprint[i:i + 2] for i in range(0, 40, 2)).lower()
        self._certification()
        with override_settings(TAX_SIGNING_CERT_THUMBPRINT='‎' + spaced):
            signing.assert_ready_for_live()

    @override_settings(TAX_SIGNER_CLASS='apps.tax_invoicing.signing.NotConfiguredSigner')
    def test_not_configured_signer_refuses(self):
        with self.assertRaises(signing.SigningUnavailable):
            signing.assert_ready_for_live()
        with self.assertRaises(signing.SigningUnavailable):
            signing.get_signer().sign('x')

    @override_settings(TAX_ALLOW_MOCK_SIGNER=False, TAX_ETA_API_BASE_URL='https://api.preprod.invoicing.eta.gov.eg')
    def test_mock_signer_refused_outside_test_mode(self):
        with self.assertRaisesRegex(signing.SigningUnavailable, 'بيئة الاختبار'):
            signing.assert_ready_for_live(signing.MockSigner())

    @override_settings(TAX_ALLOW_MOCK_SIGNER=True, TAX_ETA_API_BASE_URL=f'https://{signing.PRODUCTION_HOST}/')
    def test_mock_signer_refused_against_the_production_host(self):
        with self.assertRaisesRegex(signing.SigningUnavailable, 'الفعلية'):
            signing.assert_ready_for_live(signing.MockSigner())

    @override_settings(TAX_ALLOW_MOCK_SIGNER=True, TAX_ETA_API_BASE_URL='https://api.preprod.invoicing.eta.gov.eg')
    def test_mock_signer_allowed_in_test_mode_only_and_is_visibly_a_mock(self):
        signing.assert_ready_for_live(signing.MockSigner())
        self.assertIn(b'MOCK-SIGNATURE', base64.b64decode(signing.MockSigner().sign('x')))


# ── Agent endpoints ────────────────────────────────────────────────────────────────────────────

def agent_account():
    """The dedicated account the workstation doc sets up: a non-admin role holding tax_invoicing finalize."""
    user = User.objects.filter(username=AGENT_USERNAME).first()
    if user is None:
        user, _, _ = make_user(AGENT_USERNAME, role=AGENT_ROLE, password=AGENT_PASSWORD)
    RoleModuleAccess.objects.get_or_create(role=AGENT_ROLE, module='tax_invoicing', action='finalize',
                                           defaults={'is_allowed': True})
    return user


def agent_client(token=AGENT_TOKEN, user='agent'):
    """Signed in as the agent account (user='agent'), as another user, or anonymous (user=None)."""
    headers = {}
    if user == 'agent':
        user = agent_account()
    if user is not None:
        headers['HTTP_AUTHORIZATION'] = f'Bearer {AccessToken.for_user(user)}'
    if token is not None:
        headers['HTTP_X_TAX_AGENT_TOKEN'] = token
    client = APIClient()
    client.credentials(**headers)
    return client


def result_url(job):
    return f'/api/tax-invoicing/signing-agent/jobs/{job.pk}/result/'


def make_job(text=TEXT, kind=TaxSigningJob.KIND_DOCUMENT, **values):
    return TaxSigningJob.objects.create(kind=kind, canonical_text=text, canonical_sha256=fiscal.sha256_hex(text), **values)


@override_settings(TAX_SIGNING_AGENT_TOKEN=AGENT_TOKEN)
class AgentEndpointTests(TestCase):
    def test_bad_or_missing_token_is_403_and_claims_nothing(self):
        job = make_job()
        for token in ('wrong', None, ''):
            self.assertEqual(agent_client(token).post(NEXT_URL).status_code, 403, token)
        self.assertEqual(agent_client('wrong').post(result_url(job), {'signature': 'x'}, format='json').status_code, 403)
        job.refresh_from_db()
        self.assertEqual(job.status, TaxSigningJob.PENDING)

    @override_settings(TAX_SIGNING_AGENT_TOKEN='too-short')
    def test_a_short_configured_token_refuses_everyone(self):
        self.assertEqual(agent_client('too-short').post(NEXT_URL).status_code, 403)

    @override_settings(TAX_SIGNING_AGENT_TOKEN='')
    def test_no_configured_token_refuses_everyone(self):
        self.assertEqual(agent_client('').post(NEXT_URL).status_code, 403)

    def test_get_is_not_allowed(self):
        self.assertEqual(agent_client().get(NEXT_URL).status_code, 405)

    def test_next_claims_the_oldest_once(self):
        first, second = make_job(), make_job('"B"')
        body = agent_client().post(NEXT_URL).json()['job']
        self.assertEqual(body, {'id': first.pk, 'kind': 'document', 'canonical_text': TEXT, 'sha256': fiscal.sha256_hex(TEXT)})
        first.refresh_from_db()
        self.assertEqual(first.status, TaxSigningJob.CLAIMED)
        self.assertIsNotNone(first.claimed_at)
        self.assertEqual(agent_client().post(NEXT_URL).json()['job']['id'], second.pk)
        self.assertIsNone(agent_client().post(NEXT_URL).json()['job'])

    def test_result_stores_the_signature_on_a_claimed_job(self):
        job = make_job()
        agent_client().post(NEXT_URL)
        response = agent_client().post(result_url(job), {'signature': SEAL.b64(TEXT)}, format='json')
        self.assertEqual(response.status_code, 200)
        job.refresh_from_db()
        self.assertEqual(job.status, TaxSigningJob.SIGNED)
        self.assertIsNotNone(job.finished_at)

    def test_error_result_fails_the_job(self):
        job = make_job()
        agent_client().post(NEXT_URL)
        agent_client().post(result_url(job), {'error': 'token removed'}, format='json')
        job.refresh_from_db()
        self.assertEqual((job.status, job.error), (TaxSigningJob.FAILED, 'token removed'))

    def test_result_for_a_job_that_is_not_claimed_is_404(self):
        pending = make_job()
        self.assertEqual(agent_client().post(result_url(pending), {'signature': 'x'}, format='json').status_code, 404)
        expired = make_job(status=TaxSigningJob.EXPIRED)
        self.assertEqual(agent_client().post(result_url(expired), {'signature': 'x'}, format='json').status_code, 404)
        pending.refresh_from_db()
        self.assertEqual(pending.status, TaxSigningJob.PENDING)

    def test_a_second_result_cannot_replace_the_first(self):
        job = make_job()
        agent_client().post(NEXT_URL)
        signature = SEAL.b64(TEXT)
        agent_client().post(result_url(job), {'signature': signature}, format='json')
        self.assertEqual(agent_client().post(result_url(job), {'signature': 'other'}, format='json').status_code, 404)
        job.refresh_from_db()
        self.assertEqual(job.signature, signature)

    def test_anonymous_is_refused_even_with_the_token(self):
        job = make_job()
        for mode in ('log', 'enforce'):
            with override_settings(PUBLIC_API_ENFORCEMENT=mode):
                self.assertEqual(agent_client(user=None).post(NEXT_URL).status_code, 401, mode)
                self.assertEqual(agent_client(user=None).post(result_url(job), {'signature': 'x'}, format='json').status_code,
                                 401, mode)
        job.refresh_from_db()
        self.assertEqual(job.status, TaxSigningJob.PENDING)

    def test_a_signed_in_account_without_finalize_is_refused(self):
        """The accountant works on tax documents all day, but only the agent's role holds finalize here."""
        accountant, _, _ = make_user('tax_sig_acct', role='accountant')
        self.assertEqual(agent_client(user=accountant).post(NEXT_URL).status_code, 403)

    def test_the_agent_paths_are_not_public(self):
        for path in (NEXT_URL, '/api/tax-invoicing/signing-agent/jobs/1/result/'):
            for method in ('GET', 'POST'):
                self.assertFalse(public_paths.is_public(path, method), (path, method))

    @override_settings(PUBLIC_API_ENFORCEMENT='enforce', RBAC_ENFORCEMENT='enforce')
    def test_the_signed_in_agent_passes_every_gate_when_enforced(self):
        job = make_job()
        self.assertEqual(agent_client().post(NEXT_URL).json()['job']['id'], job.pk)
        response = agent_client().post(result_url(job), {'signature': SEAL.b64(TEXT)}, format='json')
        self.assertEqual(response.status_code, 200)


@override_settings(TAX_SIGNING_AGENT_TOKEN=AGENT_TOKEN, TAX_SIGNING_WAIT_SECONDS=60)
class StaleJobTests(TestCase):
    """A job left behind when the agent or a web process died must not stay open, or be sealed later."""

    def _aged(self, job, **age):
        TaxSigningJob.objects.filter(pk=job.pk).update(created_at=timezone.now() - dt.timedelta(**age))

    def test_a_document_nobody_waits_for_is_not_handed_to_the_agent(self):
        old, fresh = make_job('"OLD"'), make_job('"NEW"')
        self._aged(old, seconds=121)
        self.assertEqual(agent_client().post(NEXT_URL).json()['job']['id'], fresh.pk)
        old.refresh_from_db()
        self.assertEqual(old.status, TaxSigningJob.EXPIRED)
        self.assertIsNotNone(old.finished_at)
        self.assertEqual(old.signature, '')

    def test_a_document_still_inside_the_wait_is_kept(self):
        job = make_job()
        self._aged(job, seconds=100)
        self.assertEqual(agent_client().post(NEXT_URL).json()['job']['id'], job.pk)

    def test_a_claim_abandoned_by_a_crashed_agent_expires_and_a_late_answer_is_refused(self):
        job = make_job(status=TaxSigningJob.CLAIMED)
        self._aged(job, minutes=5)
        agent_client().post(NEXT_URL)
        job.refresh_from_db()
        self.assertEqual(job.status, TaxSigningJob.EXPIRED)
        self.assertEqual(agent_client().post(result_url(job), {'signature': 'x'}, format='json').status_code, 404)

    def test_a_smoke_test_gets_longer_because_someone_may_be_starting_the_agent(self):
        job = signing.start_smoke_test(None)
        self._aged(job, minutes=14)
        signing.expire_stale_jobs()
        job.refresh_from_db()
        self.assertEqual(job.status, TaxSigningJob.PENDING)
        self._aged(job, minutes=16)
        signing.expire_stale_jobs()
        job.refresh_from_db()
        self.assertEqual(job.status, TaxSigningJob.EXPIRED)

    def test_an_unanswered_smoke_test_says_nothing_about_the_token(self):
        """It expires without a certification, so an earlier pass still stands."""
        passed = TaxSigningCertification.objects.create(passed=True, thumbprint=SEAL.thumbprint)
        self._aged(signing.start_smoke_test(None), minutes=16)
        signing.expire_stale_jobs()
        self.assertEqual(signing.latest_certification(), passed)

    def test_finished_jobs_are_left_alone(self):
        job = make_job(status=TaxSigningJob.SIGNED, signature='s')
        self._aged(job, days=30)
        signing.expire_stale_jobs()
        job.refresh_from_db()
        self.assertEqual((job.status, job.signature), (TaxSigningJob.SIGNED, 's'))


@override_settings(TAX_SIGNING_AGENT_TOKEN=AGENT_TOKEN, TAX_SIGNER_CLASS=AGENT_SIGNER, TAX_SIGNING_CERT_THUMBPRINT=SEAL.thumbprint)
class SmokeTestFlowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        branch = make_branch(softech_id='TSIG')
        cls.admin, _, _ = make_user('tax_sig_admin', role='admin', branch=branch)
        cls.pharmacist, _, _ = make_user('tax_sig_ph', role='pharmacist', branch=branch)

    def _user_client(self, user):
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f'Bearer {AccessToken.for_user(user)}')
        return client

    def _claimed_smoke(self):
        response = self._user_client(self.admin).post('/api/tax-invoicing/signing/smoke-test/')
        self.assertEqual(response.status_code, 201)
        job = agent_client().post(NEXT_URL).json()['job']
        self.assertEqual((job['id'], job['kind']), (response.json()['job_id'], 'smoke'))
        return TaxSigningJob.objects.get(pk=job['id'])

    def test_only_a_sender_may_start_it(self):
        self.assertEqual(APIClient().post('/api/tax-invoicing/signing/smoke-test/').status_code, 401)
        with override_settings(RBAC_ENFORCEMENT='enforce'):
            self.assertEqual(self._user_client(self.pharmacist).post('/api/tax-invoicing/signing/smoke-test/').status_code, 403)
        self.assertFalse(TaxSigningJob.objects.exists())

    def test_the_workstation_docs_browser_fallback_works_with_the_login_cookie(self):
        """The same request the doc's console snippet sends; without the header the cookie is ignored."""
        url = '/api/tax-invoicing/signing/smoke-test/'
        client = APIClient()
        client.cookies[ACCESS_COOKIE] = str(AccessToken.for_user(self.admin))
        self.assertEqual(client.post(url).status_code, 401)
        self.assertEqual(client.post(url, HTTP_X_REQUESTED_WITH='XMLHttpRequest').status_code, 201)
        self.assertEqual(client.get('/api/tax-invoicing/signing/status/').status_code, 200)

    def test_status_closes_a_job_the_agent_never_answered(self):
        """Otherwise pending_jobs stays above zero and the screen polls for ever."""
        job = signing.start_smoke_test(self.admin)
        TaxSigningJob.objects.filter(pk=job.pk).update(created_at=timezone.now() - dt.timedelta(minutes=16))
        body = self._user_client(self.admin).get('/api/tax-invoicing/signing/status/').json()
        self.assertEqual((body['pending_jobs'], body['last_job_status']), (0, 'expired'))

    def test_pass_is_recorded_and_opens_the_gate(self):
        job = self._claimed_smoke()
        agent_client().post(result_url(job), {'signature': SEAL.b64(job.canonical_text)}, format='json')
        row = signing.latest_certification()
        self.assertTrue(row.passed, row.detail)
        self.assertEqual((row.thumbprint, row.subject, row.requested_by), (SEAL.thumbprint, 'CN=Test Seal', self.admin))
        self.assertEqual(row.not_after.date(), SEAL.cert.not_valid_after_utc.date())
        signing.assert_ready_for_live()
        body = self._user_client(self.admin).get('/api/tax-invoicing/signing/status/').json()
        self.assertTrue(body['ready_for_live'], body['why_not'])
        self.assertEqual(body['certification']['thumbprint'], SEAL.thumbprint)

    def _assert_recorded_failure(self, job, body, detail):
        self.assertEqual(agent_client().post(result_url(job), body, format='json').status_code, 200)
        row = signing.latest_certification()
        self.assertFalse(row.passed)
        self.assertIn(detail, row.detail)
        with self.assertRaises(signing.SigningUnavailable):
            signing.assert_ready_for_live()

    def test_agent_error_is_recorded_as_a_failure(self):
        job = self._claimed_smoke()
        self._assert_recorded_failure(job, {'error': 'the token refused the PIN'}, 'the token refused the PIN')

    def test_signature_over_other_text_is_recorded_as_a_failure(self):
        job = self._claimed_smoke()
        self._assert_recorded_failure(job, {'signature': SEAL.b64('"OTHER"')}, 'does not cover')

    def test_junk_signature_is_recorded_as_a_failure(self):
        job = self._claimed_smoke()
        self._assert_recorded_failure(job, {'signature': base64.b64encode(b'junk').decode()}, 'unreadable')

    def test_not_base64_is_recorded_as_a_failure(self):
        job = self._claimed_smoke()
        self.assertEqual(agent_client().post(result_url(job), {'signature': '!!not base64!!'}, format='json').status_code, 200)
        self.assertFalse(signing.latest_certification().passed)

    def test_the_mock_signature_cannot_certify(self):
        job = self._claimed_smoke()
        self._assert_recorded_failure(job, {'signature': signing.MockSigner().sign(job.canonical_text)}, 'unreadable')

    def test_a_document_job_never_creates_a_certification(self):
        job = make_job()
        agent_client().post(NEXT_URL)
        agent_client().post(result_url(job), {'signature': SEAL.b64(TEXT)}, format='json')
        self.assertFalse(TaxSigningCertification.objects.exists())


@override_settings(TAX_SIGNER_CLASS=AGENT_SIGNER, TAX_SIGNING_CERT_THUMBPRINT=SEAL.thumbprint)
class AgentSignerTests(TestCase):
    def _sign_with_agent_acting(self, finish):
        """The agent's reply arrives during AgentSigner's first wait, on this test's connection."""
        def act(_seconds):
            job = TaxSigningJob.objects.get(status=TaxSigningJob.PENDING)
            job.status = TaxSigningJob.CLAIMED
            finish(job)
            job.finished_at = timezone.now()
            job.save()
        with mock.patch.object(signing.time, 'sleep', side_effect=act):
            return signing.AgentSigner().sign(TEXT)

    @override_settings(TAX_SIGNING_WAIT_SECONDS=1)
    def test_times_out_and_expires_the_job(self):
        with self.assertRaisesRegex(signing.SigningUnavailable, 'لم يرد'):
            signing.AgentSigner().sign(TEXT)
        job = TaxSigningJob.objects.get()
        self.assertEqual(job.status, TaxSigningJob.EXPIRED)
        self.assertIsNotNone(job.finished_at)
        self.assertEqual(job.canonical_sha256, hashlib.sha256(TEXT.encode('utf-8')).hexdigest())

    @override_settings(TAX_SIGNING_WAIT_SECONDS=1, TAX_SIGNING_AGENT_TOKEN=AGENT_TOKEN)
    def test_a_late_answer_for_an_expired_job_is_refused(self):
        with self.assertRaises(signing.SigningUnavailable):
            signing.AgentSigner().sign(TEXT)
        job = TaxSigningJob.objects.get()
        self.assertEqual(agent_client().post(result_url(job), {'signature': SEAL.b64(TEXT)}, format='json').status_code, 404)
        job.refresh_from_db()
        self.assertEqual((job.status, job.signature), (TaxSigningJob.EXPIRED, ''))

    def test_returns_a_good_signature(self):
        signature = SEAL.b64(TEXT)

        def finish(job):
            job.status, job.signature = TaxSigningJob.SIGNED, signature
        self.assertEqual(self._sign_with_agent_acting(finish), signature)

    def test_failed_job_raises_with_the_agents_reason(self):
        def finish(job):
            job.status, job.error = TaxSigningJob.FAILED, 'the token is busy'
        with self.assertRaisesRegex(signing.SigningUnavailable, 'the token is busy'):
            self._sign_with_agent_acting(finish)

    def test_a_signature_over_other_text_never_leaves(self):
        def finish(job):
            job.status, job.signature = TaxSigningJob.SIGNED, SEAL.b64('"OTHER"')
        with self.assertRaisesRegex(signing.SigningUnavailable, 'غير صالح'):
            self._sign_with_agent_acting(finish)

    def test_a_signature_from_another_certificate_never_leaves(self):
        """The gate looks at the smoke test; this catches a token swapped afterwards."""
        def finish(job):
            job.status, job.signature = TaxSigningJob.SIGNED, OTHER_SEAL.b64(TEXT)
        with self.assertRaisesRegex(signing.SigningUnavailable, 'غير المسجلة'):
            self._sign_with_agent_acting(finish)


# ── agent.py against a fake PKCS#11 library ────────────────────────────────────────────────────

class FakeP11Error(Exception):
    def __init__(self, value, text=''):
        super().__init__(value)
        self.value, self.text = value, text


class FakeMechanism:
    def __init__(self, mechanism, param=None):
        self.mechanism, self.param = mechanism, param


class FakeTokenInfo:
    def __init__(self, label, flags):
        self.label, self.flags = label.ljust(32), flags
        self.manufacturerID, self.model, self.serialNumber = 'Fake Inc'.ljust(32), 'FakeKey'.ljust(16), '123'.ljust(16)


class FakeSession:
    def __init__(self, lib):
        self.lib = lib

    def _maybe_fail(self, step):
        queue = self.lib.failures.get(step)
        if queue:
            code = queue.pop(0)
            if code is not None:
                raise FakeP11Error(code)

    def login(self, pin, user_type=1):
        self.lib.pins_tried.append(pin)
        self._maybe_fail('login')
        if pin != self.lib.right_pin:
            raise FakeP11Error(0xA0)
        self.lib.logged_in = True

    def logout(self):
        self.lib.calls.append('logout')
        self.lib.logged_in = False

    def closeSession(self):
        self.lib.calls.append('close')
        self.lib.open_sessions -= 1

    def findObjects(self, template=()):
        self._maybe_fail('find')
        kind = dict(template)[FakeP11.CKA_CLASS]
        if kind == FakeP11.CKO_CERTIFICATE:
            return [('cert', i) for i in range(len(self.lib.seals))]
        return [('key', i) for i in range(len(self.lib.seals))] if self.lib.logged_in else []

    def getAttributeValue(self, obj, attr, allAsBinary=False):
        seal = self.lib.seals[obj[1]]
        values = {FakeP11.CKA_VALUE: list(seal.der), FakeP11.CKA_ID: [obj[1] + 1], FakeP11.CKA_LABEL: list(b'seal')}
        return [values[a] for a in attr]

    def sign(self, key, data, mecha):
        self.lib.calls.append('sign')
        self._maybe_fail('sign')
        if not self.lib.logged_in:
            raise FakeP11Error(0x101)
        seal = self.lib.seals[key[1]]
        self.lib.mechanisms_used.append(mecha.mechanism)
        if mecha.mechanism == FakeP11.CKM_SHA256_RSA_PKCS:
            return list(seal.key.sign(bytes(data), padding.PKCS1v15(), hashes.SHA256()))
        return list(seal.key.sign(bytes(data)[-32:], padding.PKCS1v15(), utils.Prehashed(hashes.SHA256())))


class FakeLib:
    def __init__(self, seals=(SEAL,), right_pin=PIN, flags=0, mechanisms=('CKM_SHA256_RSA_PKCS', 'CKM_RSA_PKCS')):
        self.seals, self.right_pin, self.flags, self.mechanisms = list(seals), right_pin, flags, list(mechanisms)
        self.present, self.tokens, self.load_fails = True, 1, False
        self.failures, self.pins_tried, self.calls, self.mechanisms_used = {}, [], [], []
        self.logged_in, self.open_sessions = False, 0

    def load(self, path):
        if self.load_fails:
            raise FakeP11Error(-1, 'cannot load')

    def getSlotList(self, tokenPresent=False):
        self.calls.append('slots')
        return list(range(self.tokens)) if self.present else []

    def getTokenInfo(self, slot):
        return FakeTokenInfo(f'TOKEN{slot}', self.flags)

    def getMechanismList(self, slot):
        return self.mechanisms

    def openSession(self, slot, flags=0):
        self.calls.append('open')
        queue = self.failures.get('open')
        if queue:
            code = queue.pop(0)
            if code is not None:
                raise FakeP11Error(code)
        self.open_sessions += 1
        return FakeSession(self)


class FakeP11:
    """Only what agent.py uses, with the values of the real binding (checked below when it is installed)."""
    PyKCS11Error = FakeP11Error
    Mechanism = FakeMechanism
    CKA_CLASS, CKA_VALUE, CKA_ID, CKA_LABEL = 0x0, 0x11, 0x102, 0x3
    CKO_CERTIFICATE, CKO_PRIVATE_KEY = 0x1, 0x3
    CKM_RSA_PKCS, CKM_SHA256_RSA_PKCS = 0x1, 0x40
    CKR = {0xA0: 'CKR_PIN_INCORRECT', 0x32: 'CKR_DEVICE_REMOVED', 0x30: 'CKR_DEVICE_ERROR'}

    def __init__(self, lib):
        self.lib = lib

    def PyKCS11Lib(self):
        return self.lib


class FakeResponse:
    def __init__(self, status_code, body=None):
        self.status_code, self._body = status_code, body

    def json(self):
        if self._body is None:
            raise ValueError('not json')
        return self._body


class FakeHttp:
    """Answers from a script; a queue entry can be an exception to raise. Sign-in and refresh answer with
    numbered tokens (A1/R1, A2/R2, ...) unless scripted otherwise."""

    def __init__(self, jobs=(), results=(), logins=(), refreshes=()):
        self.jobs, self.results = list(jobs), list(results)
        self.logins, self.refreshes = list(logins), list(refreshes)
        self.calls = []
        self.issued = 0
        self.cookies = {'erp_access': 'set by the last answer'}   # the agent must drop these

    def _tokens(self):
        self.issued += 1
        return FakeResponse(200, {'access': f'A{self.issued}', 'refresh': f'R{self.issued}', 'user': {}})

    def post(self, url, *, headers, json, timeout, allow_redirects, verify):
        self.calls.append({'url': url, 'headers': headers, 'json': json, 'allow_redirects': allow_redirects, 'verify': verify})
        self.cookies['erp_access'] = 'set by the last answer'
        kind = self.kind(url)
        queue = {'login': self.logins, 'refresh': self.refreshes, 'next': self.jobs, 'result': self.results}[kind]
        answer = queue.pop(0) if queue else None
        if isinstance(answer, BaseException):
            raise answer
        if isinstance(answer, FakeResponse):
            return answer
        if kind in ('login', 'refresh'):
            return self._tokens()
        if kind == 'next':
            return FakeResponse(200, {'job': answer})
        return FakeResponse(200, {'ok': True})

    @staticmethod
    def kind(url):
        for suffix, kind in (('/auth/login/', 'login'), ('/auth/refresh/', 'refresh'), ('/next/', 'next')):
            if url.endswith(suffix):
                return kind
        return 'result'

    def of(self, kind):
        return [c for c in self.calls if self.kind(c['url']) == kind]

    def results_sent(self):
        return [c['json'] for c in self.of('result')]

    def nexts(self):
        return len(self.of('next'))


def secrets_env():
    return {agent_module.ENV_PIN: PIN, agent_module.ENV_AGENT_TOKEN: AGENT_TOKEN, agent_module.ENV_PASSWORD: AGENT_PASSWORD}


def job_body(text=TEXT, job_id=7, kind='document'):
    return {'id': job_id, 'kind': kind, 'canonical_text': text, 'sha256': hashlib.sha256(text.encode('utf-8')).hexdigest()}


def server_for(http, url='https://server.test', **options):
    return agent_module.Server(url, AGENT_TOKEN, username=AGENT_USERNAME, password=AGENT_PASSWORD, http=http, **options)


def build(lib=None, http=None, *, thumbprint='', allow_low=False, pin=PIN):
    lib = lib or FakeLib()
    http = http or FakeHttp()
    token = agent_module.Token(FakeP11(lib), 'fake.dll', thumbprint=thumbprint, allow_low_pin_count=allow_low, pin=pin)
    server = server_for(http)
    sleeps = []
    agent = agent_module.Agent(token, server, sleep=sleeps.append, poll_seconds=5)
    return lib, http, token, agent, sleeps


class Stopper:
    """should_stop for run(): goes true after a number of passes through the loop."""

    def __init__(self, passes):
        self.passes = passes

    def __call__(self):
        self.passes -= 1
        return self.passes < 0


class AgentTokenTests(SimpleTestCase):
    def test_sign_content_makes_a_valid_signature_and_closes_up(self):
        lib, _, token, _, _ = build()
        der = token.sign_content(TEXT.encode('utf-8'))
        details = cades.inspect_signature(der, TEXT.encode('utf-8'))
        self.assertEqual(details['thumbprint'], SEAL.thumbprint)
        self.assertEqual(lib.pins_tried, [PIN])
        self.assertEqual(lib.mechanisms_used, [FakeP11.CKM_SHA256_RSA_PKCS])
        self.assertEqual(lib.open_sessions, 0)
        self.assertFalse(lib.logged_in)

    def test_falls_back_to_digest_info_when_the_token_cannot_hash(self):
        lib = FakeLib(mechanisms=('CKM_RSA_PKCS',))
        _, _, token, _, _ = build(lib)
        cades.inspect_signature(token.sign_content(b'x'), b'x')
        self.assertEqual(lib.mechanisms_used, [FakeP11.CKM_RSA_PKCS])

    def test_refuses_a_token_with_no_usable_mechanism(self):
        _, _, token, _, _ = build(FakeLib(mechanisms=('CKM_SHA1_RSA_PKCS',)))
        with self.assertRaisesRegex(agent_module.FatalError, 'CKM_SHA256_RSA_PKCS'):
            token.sign_content(b'x')

    def test_wrong_pin_is_tried_once_and_never_again(self):
        lib, _, token, _, _ = build(FakeLib(right_pin='other'))
        with self.assertRaises(agent_module.PinRefused):
            token.sign_content(b'x')
        with self.assertRaises(agent_module.PinRefused):
            token.sign_content(b'x')
        self.assertEqual(lib.pins_tried, [PIN])

    def test_every_pin_error_stops(self):
        for code in agent_module.PIN_ERRORS:
            lib = FakeLib()
            lib.failures = {'login': [code]}
            _, _, token, _, _ = build(lib)
            with self.assertRaises(agent_module.PinRefused, msg=hex(code)):
                token.sign_content(b'x')

    def test_locked_or_last_try_token_is_never_given_the_pin(self):
        for flag in (agent_module.CKF_USER_PIN_LOCKED, agent_module.CKF_USER_PIN_FINAL_TRY):
            lib = FakeLib(flags=flag)
            _, _, token, _, _ = build(lib, allow_low=True)
            with self.assertRaises(agent_module.PinRefused):
                token.sign_content(b'x')
            self.assertEqual(lib.pins_tried, [])

    def test_low_pin_count_needs_an_explicit_allowance(self):
        lib = FakeLib(flags=agent_module.CKF_USER_PIN_COUNT_LOW)
        _, _, token, _, _ = build(lib)
        with self.assertRaises(agent_module.PinRefused):
            token.sign_content(b'x')
        self.assertEqual(lib.pins_tried, [])
        _, _, allowed, _, _ = build(lib, allow_low=True)
        allowed.sign_content(b'x')
        self.assertEqual(lib.pins_tried, [PIN])

    def test_wrong_certificate_stops_before_the_pin(self):
        lib, _, token, _, _ = build(thumbprint=OTHER_SEAL.thumbprint)
        with self.assertRaisesRegex(agent_module.WrongCertificate, 'The PIN was not tried'):
            token.sign_content(b'x')
        self.assertEqual(lib.pins_tried, [])

    def test_expired_certificate_stops_before_the_pin(self):
        lib = FakeLib(seals=(Seal('Old', days=-1),))
        _, _, token, _, _ = build(lib)
        with self.assertRaisesRegex(agent_module.WrongCertificate, 'expired'):
            token.sign_content(b'x')
        self.assertEqual(lib.pins_tried, [])

    def test_picks_the_seal_beside_a_ca_certificate_and_its_own_key(self):
        ca = Seal('Some CA', ca=True)
        lib = FakeLib(seals=(ca, SEAL))
        _, _, token, _, _ = build(lib)
        self.assertEqual(cades.inspect_signature(token.sign_content(b'x'), b'x')['thumbprint'], SEAL.thumbprint)

    def test_two_possible_certificates_without_a_thumbprint_stop(self):
        _, _, token, _, _ = build(FakeLib(seals=(SEAL, OTHER_SEAL)))
        with self.assertRaisesRegex(agent_module.ConfigError, 'thumbprint'):
            token.sign_content(b'x')

    def test_thumbprint_chooses_among_several(self):
        _, _, token, _, _ = build(FakeLib(seals=(SEAL, OTHER_SEAL)), thumbprint=OTHER_SEAL.thumbprint.lower())
        self.assertEqual(cades.inspect_signature(token.sign_content(b'x'), b'x')['thumbprint'], OTHER_SEAL.thumbprint)

    def test_two_tokens_without_a_label_stop(self):
        lib = FakeLib()
        lib.tokens = 2
        _, _, token, _, _ = build(lib)
        with self.assertRaisesRegex(agent_module.ConfigError, 'label'):
            token.find_slot()

    def test_label_finds_the_token(self):
        lib = FakeLib()
        lib.tokens = 2
        token = agent_module.Token(FakeP11(lib), 'fake.dll', label='TOKEN1', pin=PIN)
        self.assertEqual(token.find_slot(), 1)

    def test_removed_token_is_classified(self):
        lib = FakeLib()
        lib.failures = {'sign': [0x32]}
        _, _, token, _, _ = build(lib)
        with self.assertRaisesRegex(agent_module.TokenAbsent, 'CKR_DEVICE_REMOVED'):
            token.sign_content(b'x')
        self.assertEqual(lib.open_sessions, 0)

    def test_already_logged_in_is_fine(self):
        lib = FakeLib()
        lib.failures = {'login': [agent_module.CKR_USER_ALREADY_LOGGED_IN]}
        lib.logged_in = True
        _, _, token, _, _ = build(lib)
        cades.inspect_signature(token.sign_content(b'x'), b'x')

    def test_module_that_will_not_load_mentions_bitness(self):
        lib = FakeLib()
        lib.load_fails = True
        _, _, token, _, _ = build(lib)
        with self.assertRaisesRegex(agent_module.ConfigError, 'bitness'):
            token.find_slot()


class AgentRunTests(SimpleTestCase):
    def test_once_signs_and_posts_a_signature_the_server_can_verify(self):
        lib, http, _, agent, _ = build(http=FakeHttp(jobs=[job_body()]))
        self.assertEqual(agent.run(once=True), agent_module.EXIT_OK)
        sent = http.results_sent()
        self.assertEqual(len(sent), 1)
        details = cades.inspect_signature(base64.b64decode(sent[0]['signature']), TEXT.encode('utf-8'))
        self.assertEqual(details['thumbprint'], SEAL.thumbprint)
        first = http.of('next')[0]
        self.assertEqual(first['headers'], {'Authorization': 'Bearer A1', 'X-Tax-Agent-Token': AGENT_TOKEN})
        for call in http.calls:
            self.assertIs(call['allow_redirects'], False)
            self.assertIs(call['verify'], True)

    def test_once_with_nothing_to_do(self):
        lib, http, _, agent, _ = build()
        self.assertEqual(agent.run(once=True), agent_module.EXIT_OK)
        self.assertEqual(lib.pins_tried, [])
        self.assertEqual(http.results_sent(), [])

    def test_hash_mismatch_is_refused_without_touching_the_key(self):
        job = job_body()
        job['canonical_text'] = TEXT + ' '
        lib, http, _, agent, _ = build(http=FakeHttp(jobs=[job]))
        self.assertEqual(agent.run(once=True), agent_module.EXIT_FAILED)
        self.assertEqual(lib.pins_tried, [])
        self.assertNotIn('sign', lib.calls)
        self.assertIn('SHA-256', http.results_sent()[0]['error'])
        self.assertNotIn('signature', http.results_sent()[0])

    def test_job_without_text_is_refused(self):
        lib, http, _, agent, _ = build(http=FakeHttp(jobs=[{'id': 7, 'kind': 'document', 'sha256': 'x'}]))
        self.assertEqual(agent.run(once=True), agent_module.EXIT_FAILED)
        self.assertEqual(lib.pins_tried, [])
        self.assertIn('error', http.results_sent()[0])

    def test_wrong_pin_reports_stops_and_claims_nothing_more(self):
        lib, http, _, agent, _ = build(FakeLib(right_pin='other'), FakeHttp(jobs=[job_body(), job_body(job_id=8)]))
        with self.assertRaises(agent_module.PinRefused):
            agent.run()
        self.assertEqual(lib.pins_tried, [PIN])
        self.assertEqual(http.nexts(), 1)
        self.assertIn('refused the PIN', http.results_sent()[0]['error'])

    def test_wrong_certificate_reports_and_stops(self):
        lib, http, _, agent, _ = build(http=FakeHttp(jobs=[job_body()]), thumbprint=OTHER_SEAL.thumbprint)
        with self.assertRaises(agent_module.WrongCertificate):
            agent.run()
        self.assertEqual(lib.pins_tried, [])
        self.assertEqual(len(http.results_sent()), 1)

    def test_busy_token_is_retried_then_signed_once(self):
        lib = FakeLib()
        lib.failures = {'sign': [0x30, 0x30]}
        _, http, _, agent, sleeps = build(lib, FakeHttp(jobs=[job_body()]))
        self.assertEqual(agent.run(once=True), agent_module.EXIT_OK)
        self.assertEqual(sleeps, [2, 4])
        self.assertIn('signature', http.results_sent()[0])

    def test_busy_token_gives_up_inside_the_servers_wait(self):
        lib = FakeLib()
        lib.failures = {'sign': [0x30] * 100}
        _, http, _, agent, sleeps = build(lib, FakeHttp(jobs=[job_body()]))
        self.assertEqual(agent.run(once=True), agent_module.EXIT_FAILED)
        self.assertLessEqual(sum(sleeps), agent.busy_budget_seconds)
        self.assertLess(agent.busy_budget_seconds, 60)  # TAX_SIGNING_WAIT_SECONDS default
        self.assertIn('busy', http.results_sent()[0]['error'])

    def test_a_busy_login_is_not_a_wrong_pin(self):
        lib = FakeLib()
        lib.failures = {'login': [0x30]}
        _, http, _, agent, _ = build(lib, FakeHttp(jobs=[job_body()]))
        self.assertEqual(agent.run(once=True), agent_module.EXIT_OK)
        self.assertEqual(lib.pins_tried, [PIN, PIN])

    def test_token_removed_during_signing_reports_and_keeps_running(self):
        lib = FakeLib()
        lib.failures = {'sign': [0x32]}
        _, http, _, agent, _ = build(lib, FakeHttp(jobs=[job_body()]))
        self.assertEqual(agent.run(should_stop=Stopper(1)), agent_module.EXIT_OK)
        self.assertIn('removed', http.results_sent()[0]['error'])

    def test_no_job_is_claimed_while_the_token_is_out(self):
        lib = FakeLib()
        lib.present = False
        _, http, _, agent, sleeps = build(lib, FakeHttp(jobs=[job_body()]))
        self.assertEqual(agent.run(should_stop=Stopper(4)), agent_module.EXIT_OK)
        self.assertEqual(http.nexts(), 0)
        self.assertEqual(sleeps, [5, 10, 20, 40])
        self.assertEqual(lib.pins_tried, [])

    def test_token_returning_resumes_work(self):
        lib = FakeLib()
        lib.present = False
        _, http, _, agent, _ = build(lib, FakeHttp(jobs=[job_body()]))

        def back(_seconds):
            lib.present = True
        agent.sleep = back
        self.assertEqual(agent.run(should_stop=Stopper(2)), agent_module.EXIT_OK)
        self.assertIn('signature', http.results_sent()[0])

    def test_once_without_a_token_exits_with_its_code(self):
        lib = FakeLib()
        lib.present = False
        _, http, _, agent, _ = build(lib)
        self.assertEqual(agent.run(once=True), agent_module.EXIT_NO_TOKEN)
        self.assertEqual(http.nexts(), 0)

    def test_server_unreachable_backs_off_then_resets(self):
        down = ConnectionError('no route')
        lib, http, _, agent, sleeps = build(http=FakeHttp(jobs=[down, down, down, None, down]))
        self.assertEqual(agent.run(should_stop=Stopper(5)), agent_module.EXIT_OK)
        self.assertEqual(sleeps, [5, 10, 20, 5, 5])
        self.assertEqual(lib.pins_tried, [])

    def test_backoff_has_a_ceiling(self):
        backoff = agent_module.Backoff(5, cap=300)
        delays = [backoff.next_delay() for _ in range(12)]
        self.assertEqual(max(delays), 300)
        self.assertEqual(delays[-1], 300)

    def test_server_500_and_bad_json_back_off(self):
        http = FakeHttp(jobs=[FakeResponse(502), FakeResponse(200)])
        _, _, _, agent, sleeps = build(http=http)
        self.assertEqual(agent.run(should_stop=Stopper(2)), agent_module.EXIT_OK)
        self.assertEqual(sleeps, [5, 10])

    def test_once_without_a_server_exits_with_its_code(self):
        _, _, _, agent, _ = build(http=FakeHttp(jobs=[ConnectionError('x')]))
        self.assertEqual(agent.run(once=True), agent_module.EXIT_NO_SERVER)

    def test_403_stops_rather_than_hammering(self):
        _, http, _, agent, _ = build(http=FakeHttp(jobs=[FakeResponse(403, {})]))
        with self.assertRaisesRegex(agent_module.ServerRefused, 'refused the agent'):
            agent.run()
        self.assertEqual(http.nexts(), 1)

    def test_redirect_stops(self):
        _, _, _, agent, _ = build(http=FakeHttp(jobs=[FakeResponse(302)]))
        with self.assertRaisesRegex(agent_module.ServerRefused, 'redirect'):
            agent.run()

    def test_lost_result_is_resent_without_signing_again(self):
        down = ConnectionError('blip')
        lib, http, _, agent, sleeps = build(http=FakeHttp(jobs=[job_body()], results=[down, down, FakeResponse(200, {'ok': True})]))
        self.assertEqual(agent.run(once=True), agent_module.EXIT_OK)
        self.assertEqual(lib.calls.count('sign'), 1)
        sent = http.results_sent()
        self.assertEqual(len(sent), 3)
        self.assertEqual(sent[0], sent[2])
        self.assertEqual(sleeps, [2, 4])

    def test_expired_job_result_is_dropped_not_resent(self):
        lib, http, _, agent, _ = build(http=FakeHttp(jobs=[job_body()], results=[FakeResponse(404, {})]))
        self.assertEqual(agent.run(once=True), agent_module.EXIT_FAILED)
        self.assertEqual(len(http.results_sent()), 1)

    def test_a_signature_the_local_check_rejects_is_not_sent(self):
        """A token that signs with a key other than its certificate's."""
        def wrong_key(session, key, data, mecha):
            return list(OTHER_SEAL.sign(bytes(data)))
        _, http, _, agent, _ = build(http=FakeHttp(jobs=[job_body()]))
        with mock.patch.object(FakeSession, 'sign', wrong_key):
            self.assertEqual(agent.run(once=True), agent_module.EXIT_FAILED)
        self.assertNotIn('signature', http.results_sent()[0])
        self.assertIn('does not verify', http.results_sent()[0]['error'])


class AgentSecretTests(SimpleTestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.config = Path(self.folder.name, 'config.ini')
        self.config.write_text(f'[server]\nurl = https://server.test\nusername = {AGENT_USERNAME}\n'
                               '[token]\npkcs11_module = fake.dll\n', encoding='utf-8')
        previous = logging.getLogger().handlers[:], logging.getLogger().level
        self.addCleanup(self._restore_logging, previous)

    @staticmethod
    def _restore_logging(previous):
        root = logging.getLogger()
        for handler in root.handlers[:]:
            root.removeHandler(handler)
            handler.close()
        for handler in previous[0]:
            root.addHandler(handler)
        root.setLevel(previous[1])

    def _main(self, *argv, lib=None, http=None, env=None, prompt=None):
        out = io.StringIO()
        lib = lib or FakeLib()
        with mock.patch.object(sys, 'stderr', io.StringIO()) as err:
            code = agent_module.main(['--config', str(self.config), *argv], p11=FakeP11(lib), http=http,
                                     env={} if env is None else env, prompt=prompt, out=out, sleep=lambda s: None)
        return code, out.getvalue() + err.getvalue(), lib

    def test_identify_never_logs_in_and_shows_the_certificate(self):
        code, output, lib = self._main('identify')
        self.assertEqual(code, agent_module.EXIT_OK)
        self.assertEqual(lib.pins_tried, [])
        serial = format(SEAL.cert.serial_number, 'X')
        serial = serial.rjust(len(serial) + len(serial) % 2, '0')   # whole bytes, as Windows shows it
        for expected in (SEAL.thumbprint, 'CN=Test Seal', serial, 'TOKEN0',
                         SEAL.cert.not_valid_after_utc.strftime('%Y-%m-%d')):
            self.assertIn(expected, output)

    def test_identify_warns_about_pin_state(self):
        _, output, _ = self._main('identify', lib=FakeLib(flags=agent_module.CKF_USER_PIN_FINAL_TRY))
        self.assertIn('ONE PIN ATTEMPT LEFT', output)

    def test_identify_works_with_a_module_and_no_config(self):
        self.config.unlink()
        code, output, _ = self._main('identify', '--module', 'fake.dll')
        self.assertEqual(code, agent_module.EXIT_OK)
        self.assertIn(SEAL.thumbprint, output)

    def test_selftest_passes_with_the_right_pin(self):
        code, output, lib = self._main('selftest', prompt=lambda _: PIN)
        self.assertEqual(code, agent_module.EXIT_OK)
        self.assertIn('PASS', output)
        self.assertIn(SEAL.thumbprint, output)
        self.assertIn('does not prove ETA', output)
        self.assertEqual(lib.pins_tried, [PIN])

    def test_selftest_with_a_wrong_pin_stops_after_one_attempt(self):
        lib = FakeLib(right_pin='other')
        code, output, _ = self._main('selftest', '--count', '5', lib=lib, prompt=lambda _: PIN)
        self.assertEqual(code, agent_module.EXIT_FATAL)
        self.assertIn('will not try again', output)
        self.assertEqual(lib.pins_tried, [PIN])

    def test_selftest_rounds_for_the_contention_test_count_failures(self):
        lib = FakeLib()
        lib.failures = {'sign': [None, 0x06]}
        code, output, _ = self._main('selftest', '--count', '3', lib=lib, prompt=lambda _: PIN)
        self.assertEqual(code, agent_module.EXIT_FAILED)
        self.assertEqual(output.count('PASS'), 2)
        self.assertEqual(output.count('FAILED'), 1)

    def test_the_pin_appears_nowhere(self):
        """Not in the logs, the console, the requests, or a repr, on success or on refusal. The password goes
        only into the sign-in request's body, and the agent token only into the agent requests' header."""
        for right_pin in (PIN, 'other'):
            logged = io.StringIO()
            http = FakeHttp(jobs=[job_body(), None])
            env = secrets_env()
            with mock.patch.object(agent_module, 'configure_logging'), \
                    self.assertLogs('tax_agent', level='DEBUG') as captured:
                handler = logging.StreamHandler(logged)
                agent_module.log.addHandler(handler)
                self.addCleanup(agent_module.log.removeHandler, handler)
                agent_module.log.debug('canary so assertLogs always has a record')
                code, output, lib = self._main('run', '--once', lib=FakeLib(right_pin=right_pin), http=http, env=env)
            self.assertIn(PIN, lib.pins_tried)
            printed = output + logged.getvalue() + '\n'.join(captured.output)
            self.assertNotIn(PIN, printed + repr(http.calls))
            for secret in (AGENT_TOKEN, AGENT_PASSWORD, 'Bearer'):
                self.assertNotIn(secret, printed)
            login = http.of('login')
            self.assertEqual([c['json'] for c in login], [{'username': AGENT_USERNAME, 'password': AGENT_PASSWORD}])
            self.assertNotIn(AGENT_TOKEN, repr(login))
            self.assertNotIn(AGENT_PASSWORD, repr([c for c in http.calls if c not in login]))
            self.assertNotIn(PIN, repr(agent_module.Token(FakeP11(lib), 'fake.dll', pin=PIN)))
            server = server_for(http, url='https://x.test')
            self.assertNotIn(AGENT_TOKEN, repr(server))
            self.assertNotIn(AGENT_PASSWORD, repr(server))
            self.assertIn(code, (agent_module.EXIT_OK, agent_module.EXIT_FATAL))

    def test_secrets_are_removed_from_the_environment_after_reading(self):
        env = secrets_env()
        env[agent_module.ENV_USERNAME] = AGENT_USERNAME
        self._main('run', '--once', http=FakeHttp(), env=env)
        self.assertEqual(env, {})

    def test_no_username_is_a_clear_error_before_anything_is_sent(self):
        self.config.write_text('[server]\nurl = https://server.test\n[token]\npkcs11_module = fake.dll\n', encoding='utf-8')
        http = FakeHttp()
        code, output, _ = self._main('run', '--once', http=http, env=secrets_env())
        self.assertEqual(code, agent_module.EXIT_CONFIG)
        self.assertIn('username', output)
        self.assertEqual(http.calls, [])

    def test_no_pin_and_no_console_is_a_clear_error(self):
        lib = FakeLib()
        with mock.patch.object(agent_module, '_console_prompt', return_value=None):
            code, output, _ = self._main('selftest', lib=lib)
        self.assertEqual(code, agent_module.EXIT_CONFIG)
        self.assertIn(agent_module.ENV_PIN, output)
        self.assertEqual(lib.pins_tried, [])

    def test_secrets_in_the_config_file_are_refused(self):
        self.config.write_text('[token]\npkcs11_module = fake.dll\npin = 1234\n', encoding='utf-8')
        code, output, lib = self._main('selftest', prompt=lambda _: PIN)
        self.assertEqual(code, agent_module.EXIT_CONFIG)
        self.assertNotIn('1234', output)
        self.assertEqual(lib.pins_tried, [])

    def test_plain_http_is_refused(self):
        self.config.write_text(f'[server]\nurl = http://server.test\nusername = {AGENT_USERNAME}\n'
                               '[token]\npkcs11_module = fake.dll\n', encoding='utf-8')
        http = FakeHttp()
        code, output, _ = self._main('run', '--once', http=http, env=secrets_env())
        self.assertEqual(code, agent_module.EXIT_CONFIG)
        self.assertIn('https', output)
        self.assertEqual(http.calls, [])

    def test_there_is_no_pin_argument(self):
        with mock.patch.object(sys, 'stderr', io.StringIO()), self.assertRaises(SystemExit):
            agent_module.main(['selftest', '--pin', PIN], p11=FakeP11(FakeLib()))

    def test_the_example_config_loads_and_holds_no_secret(self):
        parser = agent_module.load_config(AGENT_DIR / 'config.example.ini')
        self.assertTrue(parser['server']['url'].startswith('https://'))
        self.assertEqual(parser['token']['pkcs11_module'], '')

    def test_ca_bundle_reaches_the_request(self):
        http = FakeHttp()
        server_for(http, ca_bundle='ca.pem').next_job()
        self.assertEqual({c['verify'] for c in http.calls}, {'ca.pem'})

    def test_real_http_session_ignores_the_machines_proxy_settings(self):
        self.assertIs(server_for(None).http.trust_env, False)


class AgentSignInTests(SimpleTestCase):
    """The agent's own staff account: sign in once, renew quietly, stop at the first refusal."""

    def test_signs_in_once_and_reuses_the_token(self):
        http = FakeHttp()
        server = server_for(http)
        server.next_job()
        server.next_job()
        self.assertEqual(len(http.of('login')), 1)
        self.assertEqual({c['headers']['Authorization'] for c in http.of('next')}, {'Bearer A1'})

    def test_never_looks_like_the_browser_and_keeps_no_cookies(self):
        """X-Requested-With would enrol a device and switch on cookie sign-in for a non-browser client."""
        http = FakeHttp(jobs=[job_body()])
        _, _, _, agent, _ = build(http=http)
        agent.run(once=True)
        for call in http.calls:
            self.assertNotIn('X-Requested-With', call['headers'])
        self.assertEqual(http.cookies, {})

    def test_an_expired_access_token_is_renewed_and_the_request_repeated(self):
        http = FakeHttp(jobs=[FakeResponse(401, {}), None, FakeResponse(401, {}), None])
        server = server_for(http)
        server.next_job()
        self.assertEqual([c['json'] for c in http.of('refresh')], [{'refresh': 'R1'}])
        self.assertEqual([c['headers']['Authorization'] for c in http.of('next')], ['Bearer A1', 'Bearer A2'])
        server.next_job()      # the rotated refresh token is the one used next time
        self.assertEqual([c['json'] for c in http.of('refresh')], [{'refresh': 'R1'}, {'refresh': 'R2'}])
        self.assertEqual(len(http.of('login')), 1)

    def test_a_refused_refresh_falls_back_to_one_new_sign_in(self):
        """Seven days on, after a password change blacklisted it, or past a zone's session cap."""
        http = FakeHttp(jobs=[FakeResponse(401, {}), None], refreshes=[FakeResponse(401, {'detail': 'x'})])
        server_for(http).next_job()
        self.assertEqual(len(http.of('login')), 2)
        self.assertEqual(http.of('next')[-1]['headers']['Authorization'], 'Bearer A2')

    def test_still_refused_after_renewal_stops_without_looping(self):
        http = FakeHttp(jobs=[FakeResponse(401, {}), FakeResponse(401, {})])
        with self.assertRaises(agent_module.ServerRefused):
            server_for(http).next_job()
        self.assertEqual((len(http.of('login')), len(http.of('refresh')), http.nexts()), (1, 1, 2))

    def test_a_wrong_password_stops_after_one_attempt(self):
        http = FakeHttp(logins=[FakeResponse(401, {'error': 'x'})], jobs=[job_body()])
        lib, _, _, agent, _ = build(http=http)
        with self.assertRaisesRegex(agent_module.ServerRefused, 'will not try again'):
            agent.run()
        self.assertEqual((len(http.of('login')), http.nexts(), lib.pins_tried), (1, 0, []))

    def test_two_factor_is_a_clear_stop(self):
        for body in ({'mfa_required': True, 'mfa_token': 'x'}, {'mfa_setup_required': True, 'mfa_token': 'x'}):
            http = FakeHttp(logins=[FakeResponse(200, body)])
            with self.assertRaisesRegex(agent_module.ServerRefused, 'two-factor'):
                server_for(http).next_job()

    def test_locked_and_zone_refusals_stop_and_say_why(self):
        cases = ((FakeResponse(429, {'error': 'locked'}), 'locked or throttled'),
                 (FakeResponse(403, {'error': 'محظور من هذه المنطقة', 'zone': 'Z4'}), 'محظور من هذه المنطقة'))
        for answer, text in cases:
            http = FakeHttp(logins=[answer])
            with self.assertRaisesRegex(agent_module.ServerRefused, text):
                server_for(http).next_job()
            self.assertEqual(len(http.of('login')), 1)

    def test_a_server_that_cannot_be_reached_during_sign_in_is_waited_for(self):
        http = FakeHttp(logins=[ConnectionError('down'), FakeResponse(502)], jobs=[None])
        _, _, _, agent, sleeps = build(http=http)
        self.assertEqual(agent.run(should_stop=Stopper(3)), agent_module.EXIT_OK)
        self.assertEqual((len(http.of('login')), http.nexts()), (3, 1))
        self.assertEqual(sleeps[:2], [5, 10])

    def test_missing_finalize_says_so(self):
        http = FakeHttp(jobs=[FakeResponse(403, {'detail': 'x'})])
        with self.assertRaisesRegex(agent_module.ServerRefused, 'finalize'):
            server_for(http).next_job()

    def test_no_account_is_a_configuration_error(self):
        for username, password in (('', AGENT_PASSWORD), (AGENT_USERNAME, '')):
            with self.assertRaises(agent_module.ConfigError):
                agent_module.Server('https://x.test', AGENT_TOKEN, username=username, password=password, http=FakeHttp())


class DjangoHttp:
    """The agent's HTTP calls, sign-in included, sent to the real views through a fresh test client each
    time (so no cookie carries over), with exactly the headers the agent set."""

    def __init__(self):
        self.calls = []

    def post(self, url, *, headers, json, timeout, allow_redirects, verify):
        path = url.replace('https://server.test', '')
        self.calls.append(path)
        extra = {'HTTP_' + name.upper().replace('-', '_'): value for name, value in headers.items()}
        response = APIClient().post(path, json, format='json', **extra)
        try:
            body = response.json()
        except ValueError:
            body = None
        return FakeResponse(response.status_code, body)


@override_settings(TAX_SIGNING_AGENT_TOKEN=AGENT_TOKEN, TAX_SIGNER_CLASS=AGENT_SIGNER, TAX_SIGNING_CERT_THUMBPRINT=SEAL.thumbprint)
class AgentAgainstRealViewsTests(TestCase):
    def setUp(self):
        cache.clear()          # sign-in throttle and lockout counters live in the cache
        self.account = agent_account()

    def _agent(self, lib=None, token=AGENT_TOKEN, password=AGENT_PASSWORD):
        lib = lib or FakeLib()
        self.http = DjangoHttp()
        server = agent_module.Server('https://server.test', token, username=AGENT_USERNAME, password=password, http=self.http)
        return lib, agent_module.Agent(agent_module.Token(FakeP11(lib), 'fake.dll', thumbprint=SEAL.thumbprint, pin=PIN),
                                       server, sleep=lambda s: None)

    @override_settings(PUBLIC_API_ENFORCEMENT='enforce', RBAC_ENFORCEMENT='enforce')
    def test_real_sign_in_then_smoke_test_with_every_gate_enforced(self):
        signing.start_smoke_test(None)
        _, agent = self._agent()
        self.assertEqual(agent.run(once=True), agent_module.EXIT_OK)
        self.assertEqual(self.http.calls[0], '/api/auth/login/')
        self.assertTrue(signing.latest_certification().passed)

    def test_an_expired_access_token_is_renewed_through_the_real_refresh(self):
        _, agent = self._agent()
        agent.server.next_job()
        agent.server._access = 'expired-or-garbage'
        self.assertIsNone(agent.server.next_job())
        self.assertEqual(self.http.calls, ['/api/auth/login/', NEXT_URL, NEXT_URL, '/api/auth/refresh/', NEXT_URL])

    def test_a_wrong_password_is_tried_once_and_does_not_lock_the_account(self):
        _, agent = self._agent(password='not-the-password')
        with self.assertRaisesRegex(agent_module.ServerRefused, 'will not try again'):
            agent.run(once=True)
        self.assertEqual(self.http.calls, ['/api/auth/login/'])
        _, agent = self._agent()
        self.assertEqual(agent.run(once=True), agent_module.EXIT_OK)

    def test_an_account_with_two_factor_is_refused_clearly(self):
        profile = self.account.staff_profile
        profile.mfa_enabled = True
        profile.save(update_fields=['mfa_enabled'])
        _, agent = self._agent()
        with self.assertRaisesRegex(agent_module.ServerRefused, 'two-factor'):
            agent.run(once=True)

    def test_a_disabled_account_stops_the_agent(self):
        self.account.is_active = False
        self.account.save(update_fields=['is_active'])
        _, agent = self._agent()
        with self.assertRaises(agent_module.ServerRefused):
            agent.run(once=True)

    def test_smoke_test_end_to_end_certifies(self):
        job = signing.start_smoke_test(None)
        _, agent = self._agent()
        self.assertEqual(agent.run(once=True), agent_module.EXIT_OK)
        job.refresh_from_db()
        self.assertEqual(job.status, TaxSigningJob.SIGNED)
        row = signing.latest_certification()
        self.assertTrue(row.passed, row.detail)
        self.assertEqual(row.thumbprint, SEAL.thumbprint)
        signing.assert_ready_for_live()

    def test_wrong_pin_end_to_end_records_a_failed_smoke_test(self):
        signing.start_smoke_test(None)
        lib, agent = self._agent(FakeLib(right_pin='other'))
        with self.assertRaises(agent_module.PinRefused):
            agent.run(once=True)
        self.assertEqual(lib.pins_tried, [PIN])
        row = signing.latest_certification()
        self.assertFalse(row.passed)
        self.assertIn('refused the PIN', row.detail)
        self.assertNotIn(PIN, row.detail)

    def test_document_job_end_to_end_returns_through_agent_signer(self):
        lib, agent = self._agent()

        def agent_runs_during_the_wait(_seconds):
            self.assertEqual(agent.run(once=True), agent_module.EXIT_OK)
        with mock.patch.object(signing.time, 'sleep', side_effect=agent_runs_during_the_wait):
            signature = signing.AgentSigner().sign(TEXT)
        details = cades.inspect_signature(base64.b64decode(signature), TEXT.encode('utf-8'))
        self.assertEqual(details['thumbprint'], SEAL.thumbprint)

    def test_wrong_agent_token_stops_the_agent_end_to_end(self):
        make_job()
        _, agent = self._agent(token='b' * 40)
        with self.assertRaises(agent_module.ServerRefused):
            agent.run()
        self.assertEqual(TaxSigningJob.objects.get().status, TaxSigningJob.PENDING)


try:
    import PyKCS11 as RealPyKCS11
except ImportError:
    RealPyKCS11 = None


@unittest.skipUnless(RealPyKCS11, 'PyKCS11 is a workstation requirement, not in requirements-ci.txt')
class FakeMatchesTheRealBindingTests(SimpleTestCase):
    """The fake is only worth something if it has the real binding's shape. No token or DLL is used."""

    def test_constants(self):
        for name in ('CKA_CLASS', 'CKA_VALUE', 'CKA_ID', 'CKA_LABEL', 'CKO_CERTIFICATE', 'CKO_PRIVATE_KEY',
                     'CKM_RSA_PKCS', 'CKM_SHA256_RSA_PKCS'):
            self.assertEqual(getattr(FakeP11, name), getattr(RealPyKCS11, name), name)
        self.assertEqual(agent_module.CKF_USER_PIN_COUNT_LOW, RealPyKCS11.CKF_USER_PIN_COUNT_LOW)
        self.assertEqual(agent_module.CKF_USER_PIN_FINAL_TRY, RealPyKCS11.CKF_USER_PIN_FINAL_TRY)
        self.assertEqual(agent_module.CKF_USER_PIN_LOCKED, RealPyKCS11.CKF_USER_PIN_LOCKED)

    def test_error_codes_are_the_ones_we_think(self):
        names = {0xA0: 'CKR_PIN_INCORRECT', 0xA1: 'CKR_PIN_INVALID', 0xA2: 'CKR_PIN_LEN_RANGE', 0xA3: 'CKR_PIN_EXPIRED',
                 0xA4: 'CKR_PIN_LOCKED', 0x102: 'CKR_USER_PIN_NOT_INITIALIZED', 0x100: 'CKR_USER_ALREADY_LOGGED_IN',
                 0x32: 'CKR_DEVICE_REMOVED', 0xE0: 'CKR_TOKEN_NOT_PRESENT', 0xE1: 'CKR_TOKEN_NOT_RECOGNIZED',
                 0x30: 'CKR_DEVICE_ERROR', 0xB3: 'CKR_SESSION_HANDLE_INVALID', 0x101: 'CKR_USER_NOT_LOGGED_IN',
                 0x104: 'CKR_USER_ANOTHER_ALREADY_LOGGED_IN', 0xB1: 'CKR_SESSION_COUNT', 0x90: 'CKR_OPERATION_ACTIVE'}
        for code, name in names.items():
            self.assertEqual(RealPyKCS11.CKR[code], name)

    def test_methods_the_agent_calls_exist_with_these_arguments(self):
        import inspect
        for cls, method, arguments in ((RealPyKCS11.Session, 'sign', ('key', 'data', 'mecha')),
                                       (RealPyKCS11.Session, 'login', ('pin',)),
                                       (RealPyKCS11.Session, 'findObjects', ('template',)),
                                       (RealPyKCS11.Session, 'getAttributeValue', ('obj_id', 'attr', 'allAsBinary')),
                                       (RealPyKCS11.Session, 'logout', ()), (RealPyKCS11.Session, 'closeSession', ()),
                                       (RealPyKCS11.PyKCS11Lib, 'load', ()), (RealPyKCS11.PyKCS11Lib, 'getSlotList', ('tokenPresent',)),
                                       (RealPyKCS11.PyKCS11Lib, 'getTokenInfo', ('slot',)),
                                       (RealPyKCS11.PyKCS11Lib, 'getMechanismList', ('slot',)),
                                       (RealPyKCS11.PyKCS11Lib, 'openSession', ('slot',))):
            parameters = inspect.signature(getattr(cls, method)).parameters
            for argument in arguments:
                self.assertIn(argument, parameters, f'{cls.__name__}.{method}')

    def test_a_module_that_cannot_load_gives_our_message(self):
        token = agent_module.Token(RealPyKCS11, str(AGENT_DIR / 'no-such-module.dll'), pin=PIN)
        with self.assertRaisesRegex(agent_module.ConfigError, 'bitness'):
            token.find_slot()
