"""Repository base: the single crossing point between SQLAlchemy rows and
pydantic domain models.

Why the two shapes are separate at all: store/tables.py answers to Postgres
(column names like `profile_json`, native enums, JSONB), while
domain/models.py answers to the LangGraph state and the API (CLAUDE.md §14:
no untyped dicts cross a node boundary). Collapsing them would drag Postgres
naming into the graph, or drag the graph's shape into the migrations.

Subclasses declare three things:

- `table` / `model`: the pair being mapped.
- `column_aliases`: domain field -> column name, only where they differ.
- `jsonb_fields`: domain fields stored in a JSONB column. These are dumped
  with mode="json" so nested pydantic models and UUIDs inside them become
  JSON scalars; every other field is dumped in python mode so SQLAlchemy
  receives native UUID, datetime and enum objects.
"""
from __future__ import annotations

from typing import Any, ClassVar
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import delete as sa_delete
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from syncinerary.store.tables import Base


class BaseRepository[RowT: Base, ModelT: BaseModel]:
    table: ClassVar[type[Base]]
    model: ClassVar[type[BaseModel]]
    column_aliases: ClassVar[dict[str, str]] = {}
    jsonb_fields: ClassVar[frozenset[str]] = frozenset()

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ----- mapping -----

    @classmethod
    def _column_for(cls, field: str) -> str:
        return cls.column_aliases.get(field, field)

    @classmethod
    def to_row_values(cls, obj: ModelT) -> dict[str, Any]:
        """Domain model -> a dict of column values."""
        python = obj.model_dump(mode="python")
        # Only computed when needed: mode="json" is what makes a nested
        # Source or a UUID inside a JSONB list serializable.
        json_dump = obj.model_dump(mode="json") if cls.jsonb_fields else {}
        values: dict[str, Any] = {}
        for field in type(obj).model_fields:
            source = json_dump if field in cls.jsonb_fields else python
            values[cls._column_for(field)] = source[field]
        return values

    @classmethod
    def to_model(cls, row: RowT) -> ModelT:
        """Row -> domain model. pydantic coerces the JSONB scalars back, so a
        uuid that went into JSONB as a string returns as a UUID."""
        data = {field: getattr(row, cls._column_for(field)) for field in cls.model.model_fields}
        return cls.model.model_validate(data)  # type: ignore[return-value]

    # ----- CRUD -----

    async def add(self, obj: ModelT) -> ModelT:
        row = self.table(**self.to_row_values(obj))
        self.session.add(row)
        await self.session.flush()
        return self.to_model(row)  # type: ignore[arg-type]

    async def add_many(self, objs: list[ModelT]) -> list[ModelT]:
        """Bulk insert. One flush for the whole batch, not one per row."""
        if not objs:
            return []
        rows = [self.table(**self.to_row_values(o)) for o in objs]
        self.session.add_all(rows)
        await self.session.flush()
        return [self.to_model(r) for r in rows]  # type: ignore[arg-type]

    async def get(self, obj_id: UUID) -> ModelT | None:
        row = await self.session.get(self.table, obj_id)
        return self.to_model(row) if row is not None else None  # type: ignore[arg-type]

    async def list_where(self, *criteria: Any, order_by: Any = None) -> list[ModelT]:
        stmt = select(self.table).where(*criteria)
        if order_by is not None:
            stmt = stmt.order_by(order_by)
        result = await self.session.scalars(stmt)
        return [self.to_model(row) for row in result.all()]  # type: ignore[arg-type]

    async def delete(self, obj_id: UUID) -> int:
        """Return the number of rows removed."""
        result = await self.session.execute(
            sa_delete(self.table).where(self.table.id == obj_id)  # type: ignore[attr-defined]
        )
        return result.rowcount or 0
