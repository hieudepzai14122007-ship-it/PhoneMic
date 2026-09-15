"""Create a per-computer local CA and short-lived server certificate."""
from datetime import datetime, timedelta, timezone
import ipaddress
import os
from pathlib import Path
import plistlib
import uuid
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID, ExtendedKeyUsageOID


def private_write(path, data):
    # Windows data is under the current user's LocalAppData, never web-served.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'wb') as f:
        f.write(data)


def save_key(path, key):
    private_write(path, key.private_bytes(serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))


def prepare(directory, address):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    now = datetime.now(timezone.utc)
    ca_path, key_path = directory / 'root.pem', directory / 'root-key.pem'
    if ca_path.exists() and key_path.exists():
        ca = x509.load_pem_x509_certificate(ca_path.read_bytes())
        key = serialization.load_pem_private_key(key_path.read_bytes(), password=None)
        if ca.not_valid_after_utc < now + timedelta(days=2):
            raise RuntimeError('Chứng chỉ đã hết hạn. Xem mục Đặt lại chứng chỉ trong hướng dẫn.')
    else:
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,
            'PhoneMic Local ' + uuid.uuid4().hex[:8])])
        ca = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=5))
            .not_valid_after(now + timedelta(days=3650))
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
            .add_extension(x509.KeyUsage(digital_signature=True, content_commitment=False,
                key_encipherment=False, data_encipherment=False, key_agreement=False,
                key_cert_sign=True, crl_sign=True, encipher_only=False, decipher_only=False), critical=True)
            .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
            .sign(key, hashes.SHA256()))
        save_key(key_path, key)
        private_write(ca_path, ca.public_bytes(serialization.Encoding.PEM))
    leaf_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    leaf = (x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, address)]))
        .issuer_name(ca.subject).public_key(leaf_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(min(now + timedelta(days=30), ca.not_valid_after_utc))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address(address))]), critical=False)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .add_extension(x509.KeyUsage(digital_signature=True, content_commitment=False,
            key_encipherment=True, data_encipherment=False, key_agreement=False,
            key_cert_sign=False, crl_sign=False, encipher_only=False, decipher_only=False), critical=True)
        .sign(key, hashes.SHA256()))
    save_key(directory / 'server-key.pem', leaf_key)
    # Supply the CA in the chain so native clients can pin its fingerprint.
    private_write(directory / 'server.pem', leaf.public_bytes(serialization.Encoding.PEM)
                  + ca.public_bytes(serialization.Encoding.PEM))
    name = ca.subject.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value
    fingerprint = ca.fingerprint(hashes.SHA256()).hex().upper()
    fingerprint = ':'.join(fingerprint[i:i+2] for i in range(0, len(fingerprint), 2))
    # This is a certificate-only profile: no MDM, VPN, proxy or other settings.
    identifier = 'local.phonemic.' + ca.fingerprint(hashes.SHA256()).hex()[:16]
    payload = {'PayloadType': 'Configuration', 'PayloadVersion': 1,
        'PayloadIdentifier': identifier, 'PayloadUUID': str(uuid.uuid5(uuid.NAMESPACE_DNS, identifier)),
        'PayloadDisplayName': name, 'PayloadRemovalDisallowed': False,
        'PayloadDescription': 'Chứng chỉ HTTPS cho PhoneMic trên laptop của bạn. Không có MDM/VPN.',
        'PayloadContent': [{'PayloadType': 'com.apple.security.root', 'PayloadVersion': 1,
            'PayloadIdentifier': identifier + '.root', 'PayloadUUID': str(uuid.uuid5(uuid.NAMESPACE_DNS, identifier + '.root')),
            'PayloadDisplayName': name, 'PayloadContent': ca.public_bytes(serialization.Encoding.DER)}]}
    return {'profile': plistlib.dumps(payload), 'name': name, 'fingerprint': fingerprint,
        'cert': directory / 'server.pem', 'key': directory / 'server-key.pem'}
