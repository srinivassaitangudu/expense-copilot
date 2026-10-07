"""Additive sync bookkeeping; existing transaction schema is preserved."""
from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column
from app.db import Base


class BankSyncState(Base):
    __tablename__ = 'bank_sync_states'
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'), primary_key=True)
    provider: Mapped[str] = mapped_column(String, primary_key=True)
    successful_through: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_attempt: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
