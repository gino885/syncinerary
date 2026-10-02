"""Private account credentials; public account models exclude all secrets."""
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from pydantic import SecretStr
from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert

from syncinerary.domain.credentials import AnthropicCredential, Credentials
from syncinerary.security.credentials import CredentialCipher
from syncinerary.store import tables
from syncinerary.store.repositories.base import BaseRepository
from syncinerary.store.repositories.group import AccountRepository


class EmailAccountRepository(AccountRepository):
    @staticmethod
    def _credentials(row) -> Credentials | None:
        if row is None or row.email is None:
            return None
        return Credentials(
            account_id=row.id,
            email=row.email,
            password_hash=row.password_hash,
            verified_at=row.verified_at,
        )

    async def credentials(self, email: str, *, lock: bool = False) -> Credentials | None:
        stmt = select(tables.Account).where(tables.Account.email == email)
        if lock:
            stmt = stmt.with_for_update()
        row = (await self.session.scalars(stmt.execution_options(populate_existing=True))).one_or_none()
        return self._credentials(row)

    async def credentials_for_account(
        self,
        account_id: UUID,
        *,
        lock: bool = False,
    ) -> Credentials | None:
        stmt = select(tables.Account).where(tables.Account.id == account_id)
        if lock:
            stmt = stmt.with_for_update()
        row = (
            await self.session.scalars(
                stmt.execution_options(populate_existing=True)
            )
        ).one_or_none()
        return self._credentials(row)

    async def register(self, email: str, display_name: str) -> None:
        account_id = uuid4()
        await self.session.execute(insert(tables.Account).values(
            id=account_id, email=email, display_name=display_name,
            handle=f"traveler-{account_id.hex[:16]}",
        ).on_conflict_do_nothing(index_elements=[tables.Account.email]))

    async def create_password_account(self, email: str, display_name: str,
                                      password_hash: str):
        account_id = uuid4()
        found = await self.session.scalar(insert(tables.Account).values(
            id=account_id, email=email, display_name=display_name,
            handle=f"traveler-{account_id.hex[:16]}", password_hash=password_hash,
        ).on_conflict_do_nothing(index_elements=[tables.Account.email])
          .returning(tables.Account.id))
        return await self.get(found) if found else None

    async def set_code(self, email: str, purpose: str, digest: str) -> bool:
        is_reset = purpose == "reset"
        stmt = update(tables.Account).where(
            tables.Account.email == email,
            tables.Account.auth_provider == "email" if is_reset else tables.Account.verified_at.is_(None),
        ).values(**{
            f"{purpose}_digest": digest,
            f"{purpose}_expires_at": datetime.now(UTC) + timedelta(minutes=15),
        }).returning(tables.Account.id)
        return (await self.session.scalar(stmt)) is not None

    async def active_code(self, email: str, purpose: str) -> str | None:
        return await self.session.scalar(select(getattr(tables.Account, f"{purpose}_digest")).where(
            tables.Account.email == email,
            getattr(tables.Account, f"{purpose}_expires_at") > datetime.now(UTC),
        ))

    async def consume_code(self, email: str, purpose: str, digest: str,
                           password_hash: str) -> Credentials | None:
        now = datetime.now(UTC)
        # The conditional UPDATE locks and consumes atomically. A concurrent
        # replay cannot change the password or issue a second valid result.
        stmt = update(tables.Account).where(
            tables.Account.email == email,
            getattr(tables.Account, f"{purpose}_digest") == digest,
            getattr(tables.Account, f"{purpose}_expires_at") > now,
            tables.Account.auth_provider == "email" if purpose == "reset" else tables.Account.verified_at.is_(None),
        ).values(password_hash=password_hash, verified_at=now,
                 verify_digest=None, verify_expires_at=None,
                 reset_digest=None, reset_expires_at=None).returning(tables.Account.id)
        found = await self.session.scalar(stmt)
        return await self.credentials(email) if found else None


class AnthropicCredentialRepository(
    BaseRepository[tables.AnthropicCredential, AnthropicCredential]
):
    table = tables.AnthropicCredential
    model = AnthropicCredential

    async def save(self, account_id: UUID, api_key: SecretStr) -> AnthropicCredential:
        encrypted = CredentialCipher.from_settings().encrypt(account_id, api_key)
        now = datetime.now(UTC)
        raw = api_key.get_secret_value()
        statement = (
            insert(self.table)
            .values(
                account_id=account_id,
                ciphertext=encrypted.ciphertext,
                nonce=encrypted.nonce,
                key_version=encrypted.key_version,
                last_four=raw[-4:],
                updated_at=now,
            )
            .on_conflict_do_update(
                index_elements=[self.table.account_id],
                set_={
                    "ciphertext": encrypted.ciphertext,
                    "nonce": encrypted.nonce,
                    "key_version": encrypted.key_version,
                    "last_four": raw[-4:],
                    "updated_at": now,
                },
            )
            .returning(self.table)
        )
        row = (await self.session.scalars(statement)).one()
        return self.to_model(row)

    async def reveal(self, account_id: UUID) -> SecretStr | None:
        stored = await self.get(account_id)
        if stored is None:
            return None
        return CredentialCipher.from_settings().decrypt(account_id, stored)

    async def remove(self, account_id: UUID) -> None:
        await self.session.execute(
            delete(self.table).where(self.table.account_id == account_id)
        )

    async def account_for_trip_creator(self, trip_id: UUID) -> UUID | None:
        return await self.session.scalar(
            select(tables.Traveler.account_id)
            .join(tables.Trip, tables.Trip.created_by == tables.Traveler.id)
            .where(tables.Trip.id == trip_id)
        )
