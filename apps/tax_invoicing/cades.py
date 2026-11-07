"""
apps/tax_invoicing/cades.py — CAdES-BES detached signature, as ETA asks for over a canonical document.

The format follows "Digital Signature Format for E-Invoice System" v1.1 (ITIDA, 2020-11-10), §5:
SignedData version 3; eContentType and the content-type attribute are digestedData
(1.2.840.113549.1.7.5, not plain data); no eContent; the signer's certificate only; one SignerInfo,
version 1, by issuer and serial; four signed attributes; no unsigned attributes;
sha256WithRSAEncryption.

No Django here: deploy/tax_signing_agent/ carries an exact copy of this file for the signing
workstation (a test keeps the two identical). `sign_digest` is any function that takes the bytes to
sign and returns an RSA-SHA256 signature, so the same code runs against a software key in tests and
against the USB token on the workstation.
"""
import datetime as dt
import hashlib

from asn1crypto import algos, cms, core, tsp, x509

CONTENT_TYPE = 'digested_data'   # 1.2.840.113549.1.7.5, what ETA's format names
REQUIRED_ATTRIBUTES = {'content_type', 'message_digest', 'signing_time', 'signing_certificate_v2'}


def _signing_certificate_v2(cert):
    return tsp.SigningCertificateV2({
        'certs': [tsp.ESSCertIDv2({
            'hash_algorithm': algos.DigestAlgorithm({'algorithm': 'sha256'}),
            'cert_hash': hashlib.sha256(cert.dump()).digest(),
            'issuer_serial': tsp.IssuerSerial({
                'issuer': [x509.GeneralName({'directory_name': cert.issuer})],
                'serial_number': cert.serial_number}),
        })]})


def build_cades_bes(content, cert_der, sign_digest, *, signing_time=None):
    """A base64-free DER CMS over `content` (bytes), detached, with the four signed attributes."""
    cert = x509.Certificate.load(cert_der)
    digest = hashlib.sha256(content).digest()
    when = signing_time or dt.datetime.now(dt.timezone.utc)
    signed_attrs = cms.CMSAttributes([
        cms.CMSAttribute({'type': 'content_type', 'values': [CONTENT_TYPE]}),
        cms.CMSAttribute({'type': 'signing_time', 'values': [cms.Time({'utc_time': core.UTCTime(when)})]}),
        cms.CMSAttribute({'type': 'message_digest', 'values': [core.OctetString(digest)]}),
        cms.CMSAttribute({'type': 'signing_certificate_v2', 'values': [_signing_certificate_v2(cert)]}),
    ])
    signature = sign_digest(signed_attrs.dump())
    signer = cms.SignerInfo({
        'version': 'v1',
        'sid': cms.SignerIdentifier({'issuer_and_serial_number': cms.IssuerAndSerialNumber({
            'issuer': cert.issuer, 'serial_number': cert.serial_number})}),
        'digest_algorithm': algos.DigestAlgorithm({'algorithm': 'sha256'}),
        'signed_attrs': signed_attrs,
        'signature_algorithm': algos.SignedDigestAlgorithm({'algorithm': 'sha256_rsa'}),
        'signature': signature,
    })
    return cms.ContentInfo({'content_type': 'signed_data', 'content': cms.SignedData({
        'version': 'v3',
        'digest_algorithms': [algos.DigestAlgorithm({'algorithm': 'sha256'})],
        'encap_content_info': cms.EncapsulatedContentInfo({'content_type': CONTENT_TYPE}),
        'certificates': [cms.CertificateChoices({'certificate': cert})],
        'signer_infos': [signer],
    })}).dump()


class SignatureInvalid(Exception):
    pass


def _signed_bytes(attrs):
    """RFC 5652 §5.4: the signature covers the attributes as a SET (tag 0x31), although they travel
    with the implicit [0] tag (0xA0). Only the tag octet differs, so the bytes on the wire are kept
    as they are rather than re-encoded."""
    return b'\x31' + attrs.dump()[1:]


def _check_format(signed, signer, cert, attrs):
    """Raises SignatureInvalid where this is not the structure ETA's format document describes."""
    if signed['version'].native != 'v3':
        raise SignatureInvalid('SignedData version is not 3')
    encap = signed['encap_content_info']
    if encap['content_type'].native != CONTENT_TYPE or encap['content'].native is not None:
        raise SignatureInvalid('the content must be digestedData and detached')
    if len(signed['certificates']) != 1 or len(signed['signer_infos']) != 1:
        raise SignatureInvalid('expected the signer certificate only, and one signer')
    if signer['digest_algorithm']['algorithm'].native != 'sha256' \
            or signer['signature_algorithm']['algorithm'].native != 'sha256_rsa':
        raise SignatureInvalid('the signature must be sha256WithRSAEncryption')
    if signer['unsigned_attrs'].native is not None:
        raise SignatureInvalid('unsigned attributes are not allowed')
    sid = signer['sid'].chosen
    if signer['sid'].name != 'issuer_and_serial_number' or sid['serial_number'].native != cert.serial_number \
            or sid['issuer'].dump() != cert.issuer.dump():
        raise SignatureInvalid('the signer identifier does not name this certificate')
    found = {a['type'].native for a in attrs}
    missing = REQUIRED_ATTRIBUTES - found
    if missing:
        raise SignatureInvalid(f'missing signed attributes: {", ".join(sorted(missing))}')
    if found - REQUIRED_ATTRIBUTES:
        raise SignatureInvalid('unexpected signed attributes')
    values = {a['type'].native: a['values'][0] for a in attrs}
    if values['content_type'].native != CONTENT_TYPE:
        raise SignatureInvalid('the content-type attribute must be digestedData')
    cert_id = values['signing_certificate_v2']['certs'][0]
    if cert_id['hash_algorithm']['algorithm'].native != 'sha256' \
            or cert_id['cert_hash'].native != hashlib.sha256(cert.dump()).digest():
        raise SignatureInvalid('signing-certificate-v2 does not match the certificate')


def inspect_signature(der, content):
    """Check a signature against `content`; returns the signer's details. Raises SignatureInvalid."""
    from cryptography import x509 as cx509
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding, rsa

    try:
        signed = cms.ContentInfo.load(der)['content']
        cert = signed['certificates'][0].chosen
        signer = signed['signer_infos'][0]
        attrs = signer['signed_attrs']
        _check_format(signed, signer, cert, attrs)
        digest = next(a['values'][0].native for a in attrs if a['type'].native == 'message_digest')
        signed_bytes = _signed_bytes(attrs)
        signature = signer['signature'].native
        loaded = cx509.load_der_x509_certificate(cert.dump())
        public_key = loaded.public_key()
    except SignatureInvalid:
        raise
    except Exception as exc:
        raise SignatureInvalid(f'unreadable signature: {type(exc).__name__}') from exc
    if digest != hashlib.sha256(content).digest():
        raise SignatureInvalid('the signature does not cover this content')
    if not isinstance(public_key, rsa.RSAPublicKey):
        raise SignatureInvalid('the certificate key is not RSA')
    try:
        public_key.verify(signature, signed_bytes, padding.PKCS1v15(), hashes.SHA256())
    except InvalidSignature as exc:
        raise SignatureInvalid('the signature does not verify') from exc
    return {'subject': loaded.subject.rfc4514_string(), 'issuer': loaded.issuer.rfc4514_string(),
            'thumbprint': hashlib.sha1(cert.dump()).hexdigest().upper(),  # nosec B324 - Windows certificate thumbprint
            'not_after': loaded.not_valid_after_utc.isoformat()}
