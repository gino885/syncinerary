"""Provider subjects are identities. An email claim never links accounts."""
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from syncinerary.domain.models import Account
from syncinerary.store import tables
from syncinerary.store.repositories.group import AccountRepository


class SocialAccountRepository(AccountRepository):
    async def sign_in(self, provider: str, subject: str, display_name: str) -> Account:
        account_id = uuid4()
        await self.session.execute(insert(tables.Account).values(
            id=account_id, handle=f"traveler-{account_id.hex[:16]}",
            display_name=display_name, auth_provider=provider, provider_subject=subject,
        ).on_conflict_do_nothing(constraint="uq_account_provider_subject"))
        row = (await self.session.scalars(select(tables.Account).where(
            tables.Account.auth_provider == provider, tables.Account.provider_subject == subject,
        ))).one()
        return self.to_model(row)

    async def matches(self, account_id: UUID, provider: str, subject: str) -> bool:
        return await self.session.scalar(select(tables.Account.id).where(
            tables.Account.id == account_id,
            tables.Account.auth_provider == provider,
            tables.Account.provider_subject == subject,
        ).with_for_update()) is not None
