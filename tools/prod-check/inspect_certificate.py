"""Fetch the PUBLIC encryption certificate a SQL Server presents, for inspection only.

    backend\\.venv\\Scripts\\python.exe tools\\prod-check\\inspect_certificate.py HOST [PORT]

Performs the SQL Server pre-login and TLS handshake, saves the certificate, and disconnects.
It does not sign in, sends no credentials and runs no query. Verification is switched off
here on purpose: the goal is to look at the certificate that verification rejects.
"""
from __future__ import annotations

import hashlib
import socket
import ssl
import struct
import sys
from pathlib import Path

PRELOGIN = 0x12


def packet(payload: bytes) -> bytes:
    return struct.pack(">BBHHBB", PRELOGIN, 0x01, len(payload) + 8, 0, 1, 0) + payload


def read_packet(sock: socket.socket) -> bytes:
    def exact(n: int) -> bytes:
        buf = b""
        while len(buf) < n:
            chunk = sock.recv(n - len(buf))
            if not chunk:
                raise ConnectionError("server closed the connection")
            buf += chunk
        return buf

    header = exact(8)
    return exact(struct.unpack(">H", header[2:4])[0] - 8)


def fetch(host: str, port: int) -> bytes:
    # PRELOGIN options: VERSION (6 bytes) and ENCRYPTION (1 byte, 0x01 = on), then terminator
    options = b"\x00" + struct.pack(">HH", 11, 6) + b"\x01" + struct.pack(">HH", 17, 1) + b"\xff"
    prelogin = options + b"\x0f\x00\x00\x00\x00\x00" + b"\x01"
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    ctx.maximum_version = ssl.TLSVersion.TLSv1_2
    incoming, outgoing = ssl.MemoryBIO(), ssl.MemoryBIO()
    tls = ctx.wrap_bio(incoming, outgoing, server_hostname=host)
    with socket.create_connection((host, port), timeout=10) as sock:
        sock.sendall(packet(prelogin))
        read_packet(sock)
        while True:
            try:
                tls.do_handshake()
                break
            except ssl.SSLWantReadError:
                data = outgoing.read()
                if data:
                    sock.sendall(packet(data))
                incoming.write(read_packet(sock))
        return tls.getpeercert(binary_form=True)


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    host, port = sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 1433
    der = fetch(host, port)
    out = Path(__file__).resolve().parent / "reports"
    out.mkdir(exist_ok=True)
    path = out / "server-certificate.cer"
    path.write_bytes(der)
    print(f"certificate saved: {path}")
    print(f"sha1 thumbprint: {hashlib.sha1(der).hexdigest().upper()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
