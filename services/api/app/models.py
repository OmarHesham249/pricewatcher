from datetime import datetime, timezone
from sqlalchemy import String, Numeric, ForeignKey, Boolean, DateTime, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


def utcnow():
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    telegram_chat_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    url: Mapped[str] = mapped_column(String(1024), unique=True, nullable=False)
    store: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    last_price: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0.0)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    watches: Mapped[list["Watch"]] = relationship(back_populates="product", cascade="all, delete-orphan")
    history: Mapped[list["PriceHistory"]] = relationship(
        back_populates="product",
        cascade="all, delete-orphan",
        order_by="PriceHistory.checked_at.asc()",
    )


class Watch(Base):
    __tablename__ = "watches"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), nullable=False)
    target_price: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_alerted_price: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)

    product: Mapped["Product"] = relationship(back_populates="watches")


class PriceHistory(Base):
    __tablename__ = "price_history"
    __table_args__ = (
        Index("ix_price_history_product_checked", "product_id", "checked_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), nullable=False)
    price: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    product: Mapped["Product"] = relationship(back_populates="history")
