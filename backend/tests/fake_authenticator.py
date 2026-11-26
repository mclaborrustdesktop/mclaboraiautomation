"""A software WebAuthn authenticator for tests: an ES256 key pair that answers registration (attestation "none") and
authentication challenges exactly like a platform authenticator would, so the server-side verification in app/devices.py
is exercised for real. Never used outside the tests."""
from __future__ import annotations

import hashlib
import json
import os
import struct

import cbor2
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature, encode_dss_signature  # noqa: F401
from webauthn.helpers import bytes_to_base64url


class FakeAuthenticator:
    def __init__(self, rp_id: str, origin: str):
        self.rp_id = rp_id
        self.origin = origin
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.credential_id = os.urandom(32)
        self.sign_count = 0
        self.aaguid = b"\x00" * 16

    # -- helpers
    def _cose_public_key(self) -> bytes:
        nums = self.key.public_key().public_numbers()
        return cbor2.dumps({1: 2, 3: -7, -1: 1, -2: nums.x.to_bytes(32, "big"), -3: nums.y.to_bytes(32, "big")})

    def _auth_data(self, with_credential: bool) -> bytes:
        flags = 0x01 | 0x04  # user present + user verified
        if with_credential:
            flags |= 0x40
        data = hashlib.sha256(self.rp_id.encode()).digest() + bytes([flags]) + struct.pack(">I", self.sign_count)
        if with_credential:
            data += self.aaguid + struct.pack(">H", len(self.credential_id)) + self.credential_id + self._cose_public_key()
        return data

    def _client_data(self, typ: str, challenge_b64url: str) -> bytes:
        return json.dumps({"type": typ, "challenge": challenge_b64url, "origin": self.origin, "crossOrigin": False}).encode()

    # -- the two ceremonies, taking the options JSON the server produced
    def create(self, options_json: str) -> dict:
        opts = json.loads(options_json)
        client_data = self._client_data("webauthn.create", opts["challenge"])
        att_obj = cbor2.dumps({"fmt": "none", "attStmt": {}, "authData": self._auth_data(True)})
        return {"id": bytes_to_base64url(self.credential_id), "rawId": bytes_to_base64url(self.credential_id), "type": "public-key",
                "response": {"clientDataJSON": bytes_to_base64url(client_data), "attestationObject": bytes_to_base64url(att_obj), "transports": ["internal"]},
                "clientExtensionResults": {}, "authenticatorAttachment": "platform"}

    def get(self, options_json: str, tamper: bool = False) -> dict:
        opts = json.loads(options_json)
        self.sign_count += 1
        client_data = self._client_data("webauthn.get", opts["challenge"])
        auth_data = self._auth_data(False)
        signed = auth_data + hashlib.sha256(client_data).digest()
        signature = self.key.sign(signed, ec.ECDSA(hashes.SHA256()))
        if tamper:
            signature = bytes([signature[0] ^ 0xFF]) + signature[1:]
        return {"id": bytes_to_base64url(self.credential_id), "rawId": bytes_to_base64url(self.credential_id), "type": "public-key",
                "response": {"clientDataJSON": bytes_to_base64url(client_data), "authenticatorData": bytes_to_base64url(auth_data),
                             "signature": bytes_to_base64url(signature), "userHandle": None},
                "clientExtensionResults": {}, "authenticatorAttachment": "platform"}
