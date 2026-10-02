"""Authenticated encryption for account-owned provider credentials."""

from __future__ import annotations

import base64
import binascii
import json
import os
from uuid import UUID

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from pydantic import SecretStr

from syncinerary.config import settings
from syncinerary.domain.credentials import EncryptedCredential


class CredentialConfigurationError(RuntimeError):
    """The deployment credential keyring is absent or malformed."""


class CredentialDecryptionError(RuntimeError):
    """A credential cannot be authenticated with the configured keyring."""


class CredentialCipher:
    """AES-GCM keyring with record-bound authenticated data and rotation."""

    def __init__(self, keys: dict[int, bytes], active_version: int) -> None:
        if active_version not in keys:
            raise CredentialConfigurationError("Active credential key version is unavailable")
        if any(len(key) != 32 for key in keys.values()):
            raise CredentialConfigurationError("Credential encryption keys must be 32 bytes")
        self._keys = keys
        self._active_version = active_version

    @classmethod
    def from_settings(cls) -> CredentialCipher:
        raw = settings.sync_credential_encryption_keys.get_secret_value()
        try:
            encoded = json.loads(raw)
            if not isinstance(encoded, dict) or not encoded:
                raise ValueError
            keys = {
                int(version): base64.urlsafe_b64decode(value.encode())
                for version, value in encoded.items()
            }
        except (binascii.Error, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise CredentialConfigurationError(
                "SYNC_CREDENTIAL_ENCRYPTION_KEYS must be a non-empty JSON keyring"
            ) from exc
        return cls(keys, settings.sync_credential_encryption_active_version)

    @staticmethod
    def _aad(account_id: UUID, key_version: int) -> bytes:
        return f"syncinerary:anthropic:{account_id}:v{key_version}".encode()

    def encrypt(self, account_id: UUID, api_key: SecretStr) -> EncryptedCredential:
        nonce = os.urandom(12)
        plaintext = api_key.get_secret_value().encode()
        version = self._active_version
        ciphertext = AESGCM(self._keys[version]).encrypt(
            nonce,
            plaintext,
            self._aad(account_id, version),
        )
        return EncryptedCredential(
            ciphertext=ciphertext,
            nonce=nonce,
            key_version=version,
        )

    def decrypt(self, account_id: UUID, encrypted: EncryptedCredential) -> SecretStr:
        key = self._keys.get(encrypted.key_version)
        if key is None:
            raise CredentialDecryptionError("Credential key version is unavailable")
        try:
            plaintext = AESGCM(key).decrypt(
                encrypted.nonce,
                encrypted.ciphertext,
                self._aad(account_id, encrypted.key_version),
            )
            return SecretStr(plaintext.decode())
        except (InvalidTag, UnicodeDecodeError, ValueError) as exc:
            raise CredentialDecryptionError("Credential authentication failed") from exc
