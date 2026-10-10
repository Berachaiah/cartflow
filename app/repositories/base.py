"""
Generic repository base class.

Domain repositories subclass this for the common CRUD + pagination case,
then add domain-specific query methods on top:

    class ProductRepository(BaseRepository[Product]):
        def __init__(self, db: AsyncSession):
            super().__init__(db, Product)

        async def list_by_business(self, business_id: uuid.UUID) -> list[Product]:
            stmt = select(Product).where(Product.business_id == business_id)
            result = await self.db.execute(stmt)
            return list(result.scalars().all())

Soft-delete awareness: if the model has a `deleted_at` column
(SoftDeleteMixin), `get`/`list` exclude soft-deleted rows by default.
"""

import uuid
from datetime import datetime, timezone
from typing import Generic, TypeVar

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.base import Base

ModelType = TypeVar("ModelType", bound=Base)


class BaseRepository(Generic[ModelType]):
    def __init__(self, db: AsyncSession, model: type[ModelType]):
        self.db = db
        self.model = model
        self._has_soft_delete = hasattr(model, "deleted_at")

    def _base_query(self, *, include_deleted: bool = False):
        stmt = select(self.model)
        if self._has_soft_delete and not include_deleted:
            stmt = stmt.where(self.model.deleted_at.is_(None))
        return stmt

    async def get(self, id: uuid.UUID, *, include_deleted: bool = False) -> ModelType | None:
        stmt = self._base_query(include_deleted=include_deleted).where(self.model.id == id)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def list(
        self,
        *,
        limit: int = 20,
        offset: int = 0,
        include_deleted: bool = False,
    ) -> list[ModelType]:
        stmt = self._base_query(include_deleted=include_deleted).limit(limit).offset(offset)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def count(self, *, include_deleted: bool = False) -> int:
        stmt = select(func.count()).select_from(self.model)
        if self._has_soft_delete and not include_deleted:
            stmt = stmt.where(self.model.deleted_at.is_(None))
        result = await self.db.execute(stmt)
        return result.scalar_one()

    async def create(self, **fields) -> ModelType:
        instance = self.model(**fields)
        self.db.add(instance)
        await self.db.flush()  # populate defaults (id, timestamps) without committing
        return instance

    async def update(self, instance: ModelType, **fields) -> ModelType:
        for key, value in fields.items():
            setattr(instance, key, value)
        await self.db.flush()
        return instance

    async def soft_delete(self, instance: ModelType) -> ModelType:
        if not self._has_soft_delete:
            raise TypeError(f"{self.model.__name__} does not support soft delete")
        instance.deleted_at = datetime.now(timezone.utc)
        await self.db.flush()
        return instance

    async def hard_delete(self, instance: ModelType) -> None:
        await self.db.delete(instance)
        await self.db.flush()
