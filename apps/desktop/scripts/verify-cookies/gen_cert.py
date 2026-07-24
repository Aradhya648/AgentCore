"""Generate a throwaway self-signed TLS cert for the local cookie-verify backend.

The verifier needs the API served over **HTTPS** (browsers only store ``Secure``
cookies from a secure response) while staying **cross-site** to the renderer's
``app://agentcore`` origin — exactly the production topology, minus the public
internet. A self-signed cert on ``https://127.0.0.1:8443`` reproduces that without
any external tunnel (cloudflared's public hostname is unreachable from some
networks). The Electron harness force-trusts this cert for the API host only.

Writes ``cert.pem`` + ``key.pem`` into the directory given as argv[1] (default:
``<repo>/.tools/tls``). Short validity — it's a one-off test artifact.

Run via the server venv (has ``cryptography``)::

    uv run python scripts/verify-cookies/gen_cert.py <out_dir>
"""

from __future__ import annotations

import datetime as dt
import ipaddress
import sys
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID


def main() -> None:
    out_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".tools/tls")
    out_dir.mkdir(parents=True, exist_ok=True)

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = dt.datetime.now(dt.UTC)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "127.0.0.1")])
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(minutes=5))
        .not_valid_after(now + dt.timedelta(days=2))
        .add_extension(
            x509.SubjectAlternativeName(
                [
                    x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
                    x509.DNSName("localhost"),
                ]
            ),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )

    (out_dir / "key.pem").write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    (out_dir / "cert.pem").write_bytes(
        cert.public_bytes(serialization.Encoding.PEM)
    )
    print(f"wrote {out_dir / 'cert.pem'} and {out_dir / 'key.pem'}")


if __name__ == "__main__":
    main()
