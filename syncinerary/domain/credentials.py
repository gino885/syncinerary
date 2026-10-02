"""Private credential projection, never returned as an account API response."""
from datetime import UTC, datetime
from uuid import UUID

from pydantic import BaseModel, Field


class Credentials(BaseModel):
    account_id: UUID
    email: str
    password_hash: str | None
    verified_at: datetime | None


class EncryptedCredential(BaseModel):
    ciphertext: bytes = Field(repr=False)
    nonce: bytes = Field(repr=False)
    key_version: int = Field(ge=1)


class AnthropicCredential(EncryptedCredential):
    account_id: UUID
    last_four: str = Field(min_length=4, max_length=4)
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
