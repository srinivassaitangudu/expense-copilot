import enum, uuid
from datetime import datetime, date
from decimal import Decimal
from sqlalchemy import String, DateTime, Date, Numeric, ForeignKey, Text, UniqueConstraint, Enum
from sqlalchemy.orm import Mapped, mapped_column
from app.db import Base

def uid(): return str(uuid.uuid4())

class ReviewState(str, enum.Enum):
    UNREVIEWED="unreviewed"; SHARED="shared"; PERSONAL="personal"; IGNORED="ignored"

class SyncState(str, enum.Enum):
    NOT_READY="not_ready"; READY="ready"; SYNCED="synced"; FAILED="failed"

class User(Base):
    __tablename__="users"
    id: Mapped[str]=mapped_column(String, primary_key=True, default=uid)
    email: Mapped[str|None]=mapped_column(String, unique=True, nullable=True)
    created_at: Mapped[datetime]=mapped_column(DateTime, default=datetime.utcnow)

class Connection(Base):
    __tablename__="connections"
    id: Mapped[str]=mapped_column(String, primary_key=True, default=uid)
    user_id: Mapped[str]=mapped_column(ForeignKey("users.id"), index=True)
    provider: Mapped[str]=mapped_column(String, index=True) # teller/splitwise
    external_id: Mapped[str|None]=mapped_column(String, nullable=True)
    secret_ciphertext: Mapped[str]=mapped_column(Text)
    created_at: Mapped[datetime]=mapped_column(DateTime, default=datetime.utcnow)
    __table_args__=(UniqueConstraint("user_id","provider","external_id"),)

class Transaction(Base):
    __tablename__="transactions"
    id: Mapped[str]=mapped_column(String, primary_key=True, default=uid)
    user_id: Mapped[str]=mapped_column(ForeignKey("users.id"), index=True)
    teller_transaction_id: Mapped[str]=mapped_column(String)
    account_id: Mapped[str]=mapped_column(String, index=True)
    amount: Mapped[Decimal]=mapped_column(Numeric(12,2))
    txn_date: Mapped[date]=mapped_column(Date)
    description: Mapped[str]=mapped_column(Text)
    merchant: Mapped[str|None]=mapped_column(String, nullable=True)
    category: Mapped[str|None]=mapped_column(String, nullable=True)
    bank_status: Mapped[str]=mapped_column(String, default="pending")
    review_state: Mapped[ReviewState]=mapped_column(Enum(ReviewState), default=ReviewState.UNREVIEWED)
    sync_state: Mapped[SyncState]=mapped_column(Enum(SyncState), default=SyncState.NOT_READY)
    splitwise_expense_id: Mapped[str|None]=mapped_column(String, nullable=True)
    raw_json: Mapped[str|None]=mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime]=mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    __table_args__=(UniqueConstraint("user_id","teller_transaction_id"),)
