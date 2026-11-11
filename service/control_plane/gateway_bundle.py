"""Build the Ubuntu node package from an explicit file list."""
from io import BytesIO
from pathlib import Path
import json
import ssl
import tarfile

BUNDLE_NAME = "regional-vpn-gateway.tar.gz"
ROOT = Path(__file__).resolve().parents[2]
SOURCE_FILES = (
    "scripts/setup-wireguard-gateway.sh",
    "scripts/install-wireguard-agent.sh",
    "service/control_plane/__init__.py",
    "service/control_plane/security.py",
    "service/gateway_agent/__init__.py",
    "service/gateway_agent/agent.py",
    "service/gateway_agent/regional-gateway.service",
)


def build_gateway_bundle(public_certificate: Path | None, *, enrollment: dict[str, str] | None = None) -> bytes:
    data = BytesIO()
    with tarfile.open(fileobj=data, mode="w:gz") as archive:
        for name in SOURCE_FILES:
            add_file(archive, name, (ROOT / name).read_bytes())
        if public_certificate is not None:
            # Parse and re-encode only the certificate. Never archive adjacent TLS files.
            der = ssl.PEM_cert_to_DER_cert(public_certificate.read_text())
            pem = ssl.DER_cert_to_PEM_cert(der)
            ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT).load_verify_locations(cadata=pem)
            add_file(archive, "control.crt", pem.encode("ascii"))
        if enrollment is not None:
            add_file(archive, "gateway.json", json.dumps(enrollment).encode("ascii"), mode=0o600)
    return data.getvalue()


def add_file(archive: tarfile.TarFile, name: str, content: bytes, mode: int = 0o644) -> None:
    member = tarfile.TarInfo(name)
    member.size = len(content)
    member.mode = mode
    archive.addfile(member, BytesIO(content))
