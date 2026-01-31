import enum
from datetime import datetime

from sqlalchemy import (
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Tariff(enum.StrEnum):
    T0 = "T0"
    T1 = "T1"
    T2 = "T2"
    T3 = "T3"


class PaymentProvider(enum.StrEnum):
    NONE = "none"
    PRODAMUS = "prodamus"
    CLOUDPAYMENTS = "cloudpayments"


class OrderStatus(enum.StrEnum):
    CREATED = "created"
    PENDING = "pending"
    PAID = "paid"
    FAILED = "failed"
    CANCELED = "canceled"


class ReportModel(enum.StrEnum):
    GEMINI = "gemini"
    CHATGPT = "chatgpt"


class FeedbackStatus(enum.StrEnum):
    SENT = "sent"
    FAILED = "failed"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_user_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow
    )

    profile: Mapped["UserProfile"] = relationship(back_populates="user", uselist=False)
    orders: Mapped[list["Order"]] = relationship(back_populates="user")
    reports: Mapped[list["Report"]] = relationship(back_populates="user")
    free_limit: Mapped["FreeLimit"] = relationship(back_populates="user", uselist=False)
    feedback_messages: Mapped[list["FeedbackMessage"]] = relationship(
        back_populates="user"
    )


class UserProfile(Base):
    __tablename__ = "user_profile"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    name: Mapped[str] = mapped_column(String(255))
    birth_date: Mapped[datetime] = mapped_column(Date)
    birth_time: Mapped[str | None] = mapped_column(String(5), nullable=True)
    birth_place_city: Mapped[str] = mapped_column(String(255))
    birth_place_region: Mapped[str | None] = mapped_column(String(255), nullable=True)
    birth_place_country: Mapped[str] = mapped_column(String(255))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow
    )

    user: Mapped[User] = relationship(back_populates="profile")


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    tariff: Mapped[Tariff] = mapped_column(Enum(Tariff), index=True)
    amount: Mapped[float] = mapped_column(Numeric(10, 2))
    currency: Mapped[str] = mapped_column(String(3), default="RUB")
    provider: Mapped[PaymentProvider] = mapped_column(Enum(PaymentProvider))
    provider_payment_id: Mapped[str | None] = mapped_column(String(255), index=True)
    status: Mapped[OrderStatus] = mapped_column(Enum(OrderStatus), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship(back_populates="orders")
    report: Mapped["Report"] = relationship(back_populates="order", uselist=False)


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    order_id: Mapped[int | None] = mapped_column(
        ForeignKey("orders.id", ondelete="SET NULL"), index=True
    )
    tariff: Mapped[Tariff] = mapped_column(Enum(Tariff), index=True)
    report_text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )
    pdf_storage_key: Mapped[str | None] = mapped_column(String(255))
    model_used: Mapped[ReportModel | None] = mapped_column(Enum(ReportModel))
    safety_flags: Mapped[dict | None] = mapped_column(JSON)

    user: Mapped[User] = relationship(back_populates="reports")
    order: Mapped[Order | None] = relationship(back_populates="report")


class FreeLimit(Base):
    __tablename__ = "free_limits"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    last_t0_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship(back_populates="free_limit")


class FeedbackMessage(Base):
    __tablename__ = "feedback_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    text: Mapped[str] = mapped_column(Text)
    status: Mapped[FeedbackStatus] = mapped_column(Enum(FeedbackStatus))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship(back_populates="feedback_messages")
