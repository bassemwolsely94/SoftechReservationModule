"""
apps/tax_invoicing/cades.py — CAdES-BES detached signature, as ETA asks for over a canonical document.

No Django here: deploy/tax_signing_agent/ copies this file to the signing workstation. `sign_digest`
is any function that takes the bytes to sign and returns an RSA-SHA256 signature, so the same code
runs against a software key in tests and against the USB token on the workstation.
"""
import datetime as dt
import hashlib

from asn1crypto import algos, cms, core, tsp, x509


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
    """A base64-free DER CMS over `content` (bytes), detached, with the three signed attributes."""
    cert = x509.Certificate.load(cert_der)
    digest = hashlib.sha256(content).digest()
    when = signing_time or dt.datetime.now(dt.timezone.utc)
    signed_attrs = cms.CMSAttributes([
        cms.CMSAttribute({'type': 'content_type', 'values': ['data']}),
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
        'version': 'v1',
        'digest_algorithms': [algos.DigestAlgorithm({'algorithm': 'sha256'})],
        'encap_content_info': cms.EncapsulatedContentInfo({'content_type': 'data'}),
        'certificates': [cms.CertificateChoices({'certificate': cert})],
        'signer_infos': [signer],
    })}).dump()


class SignatureInvalid(Exception):
    pass


def inspect_signature(der, content):
    """Check a signature against `content`; returns the signer's details. Raises SignatureInvalid."""
    from cryptography import x509 as cx509
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding

    try:
        info = cms.ContentInfo.load(der)
        signed = info['content']
        cert = signed['certificates'][0].chosen
        signer = signed['signer_infos'][0]
        attrs = signer['signed_attrs']
        digest = next(a['values'][0].native for a in attrs if a['type'].native == 'message_digest')
        has_v2 = any(a['type'].native == 'signing_certificate_v2' for a in attrs)
        signed_bytes = attrs.untag().dump() if False else attrs.dump(force=True)
        signature = signer['signature'].native
    except Exception as exc:
        raise SignatureInvalid(f'unreadable signature: {type(exc).__name__}') from exc
    if digest != hashlib.sha256(content).digest():
        raise SignatureInvalid('the signature does not cover this content')
    if not has_v2:
        raise SignatureInvalid('missing signing-certificate-v2')
    loaded = cx509.load_der_x509_certificate(cert.dump())
    try:
        loaded.public_key().verify(signature, signed_bytes, padding.PKCS1v15(), hashes.SHA256())
    except InvalidSignature as exc:
        raise SignatureInvalid('the signature does not verify') from exc
    return {'subject': loaded.subject.rfc4514_string(), 'issuer': loaded.issuer.rfc4514_string(),
            'thumbprint': hashlib.sha1(cert.dump()).hexdigest().upper(),  # nosec B324 - Windows certificate thumbprint
            'not_after': loaded.not_valid_after_utc.isoformat()}
