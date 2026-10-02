"""Authenticated lifecycle for account-owned Anthropic API credentials."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, Field, SecretStr, field_validator

from syncinerary.api.deps import CurrentAccount, Session
from syncinerary.domain.credentials import AnthropicCredential
from syncinerary.domain.models import Account
from syncinerary.security.credentials import CredentialConfigurationError
from syncinerary.store.repositories import AccountRepository, AnthropicCredentialRepository

router = APIRouter(prefix="/accounts/me/anthropic-key", tags=["accounts"])
consent_router = APIRouter(prefix="/accounts/me/ai-consent", tags=["accounts"])


class AnthropicCredentialIn(BaseModel):
    api_key: SecretStr = Field(min_length=20, max_length=300)
    consent_to_anthropic: Literal[True]

    @field_validator("api_key", mode="before")
    @classmethod
    def trim_api_key(cls, value: object) -> object:
        if isinstance(value, SecretStr):
            return SecretStr(value.get_secret_value().strip())
        return value.strip() if isinstance(value, str) else value

    @field_validator("api_key")
    @classmethod
    def validate_api_key(cls, value: SecretStr) -> SecretStr:
        raw = value.get_secret_value()
        if not raw.startswith("sk-ant-") or any(character.isspace() for character in raw):
            raise ValueError("Enter an Anthropic API key without spaces")
        return value


class AnthropicCredentialOut(BaseModel):
    configured: bool
    last_four: str | None = None
    updated_at: datetime | None = None

    @classmethod
    def of(cls, credential: AnthropicCredential | None) -> AnthropicCredentialOut:
        if credential is None:
            return cls(configured=False)
        return cls(
            configured=True,
            last_four=credential.last_four,
            updated_at=credential.updated_at,
        )


class AnthropicConsentIn(BaseModel):
    consent_to_anthropic: Literal[True]


class AnthropicConsentOut(BaseModel):
    anthropic: bool
    policy_version: str | None
    granted_at: datetime | None

    @classmethod
    def of(cls, account: Account) -> AnthropicConsentOut:
        return cls(
            anthropic=(
                account.anthropic_consent_version is not None
                and account.anthropic_consent_at is not None
            ),
            policy_version=account.anthropic_consent_version,
            granted_at=account.anthropic_consent_at,
        )


@router.get("")
async def credential_status(
    account: CurrentAccount,
    session: Session,
) -> AnthropicCredentialOut:
    credential = await AnthropicCredentialRepository(session).get(account.id)
    return AnthropicCredentialOut.of(credential)


@router.put("")
async def save_credential(
    payload: AnthropicCredentialIn,
    account: CurrentAccount,
    session: Session,
) -> AnthropicCredentialOut:
    try:
        saved = await AnthropicCredentialRepository(session).save(account.id, payload.api_key)
    except CredentialConfigurationError as exc:
        raise HTTPException(503, "Secure credential storage is not configured") from exc
    await AccountRepository(session).grant_anthropic_consent(account.id)
    return AnthropicCredentialOut.of(saved)


@router.delete("", status_code=204)
async def remove_credential(
    account: CurrentAccount,
    session: Session,
) -> Response:
    await AnthropicCredentialRepository(session).remove(account.id)
    return Response(status_code=204)


@consent_router.get("")
async def consent_status(
    account: CurrentAccount,
) -> AnthropicConsentOut:
    return AnthropicConsentOut.of(account)


@consent_router.put("")
async def grant_consent(
    payload: AnthropicConsentIn,
    account: CurrentAccount,
    session: Session,
) -> AnthropicConsentOut:
    saved = await AccountRepository(session).grant_anthropic_consent(account.id)
    return AnthropicConsentOut.of(saved)


@consent_router.delete("", status_code=204)
async def revoke_consent(
    account: CurrentAccount,
    session: Session,
) -> Response:
    await AccountRepository(session).revoke_anthropic_consent(account.id)
    return Response(status_code=204)
