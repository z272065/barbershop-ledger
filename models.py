from sqlalchemy import String, ForeignKey
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from datetime import datetime, timezone, timedelta


def now_bj():
    return datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")


class Base(DeclarativeBase):
    pass


class Member(Base):
    __tablename__ = "members"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str | None] = mapped_column(String(50))
    phone: Mapped[str | None] = mapped_column(String(20))
    note: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[str | None] = mapped_column(String(30))
    legacy_card_no: Mapped[str | None] = mapped_column(String(30), unique=True)


class Service(Base):
    __tablename__ = "services"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(50))
    price: Mapped[int] = mapped_column()


class TxType(Base):
    __tablename__ = "tx_types"
    name: Mapped[str] = mapped_column(String(50), primary_key=True)


class Setting(Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(50), primary_key=True)
    value: Mapped[str] = mapped_column(String(50))


class Transaction(Base):
    __tablename__ = "transactions"
    id: Mapped[int] = mapped_column(primary_key=True)
    type: Mapped[str] = mapped_column(String(10), ForeignKey("tx_types.name"))
    member_id: Mapped[int] = mapped_column(ForeignKey("members.id"))
    service_id: Mapped[int | None] = mapped_column(ForeignKey("services.id"))
    price_snapshot: Mapped[int | None] = mapped_column()
    amount: Mapped[int] = mapped_column()
    balance_delta: Mapped[int] = mapped_column()
    request_id: Mapped[str] = mapped_column(String(50), unique=True)
    reverses_id: Mapped[int | None] = mapped_column(ForeignKey("transactions.id"))
    occurred_at: Mapped[str] = mapped_column(String(50))
    recorded_at: Mapped[str] = mapped_column(String(50), default=now_bj)
