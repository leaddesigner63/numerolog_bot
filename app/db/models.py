import enum
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    BigInteger,
    JSON,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if not hasattr(enum, "StrEnum"):
    class StrEnum(str, enum.Enum):
        pass

    enum.StrEnum = StrEnum


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


class OrderFulfillmentStatus(enum.StrEnum):
    PENDING = "pending"
    COMPLETED = "completed"


class PaymentConfirmationSource(enum.StrEnum):
    PROVIDER_WEBHOOK = "provider_webhook"
    PROVIDER_POLL = "provider_poll"
    ADMIN_MANUAL = "admin_manual"
    SYSTEM = "system"


class ReportModel(enum.StrEnum):
    GEMINI = "gemini"
    CHATGPT = "chatgpt"


class ReportJobStatus(enum.StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    FAILED = "failed"
    COMPLETED = "completed"


class FeedbackStatus(enum.StrEnum):
    SENT = "sent"
    FAILED = "failed"


class SupportMessageDirection(enum.StrEnum):
    USER = "user"
    ADMIN = "admin"


class QuestionnaireStatus(enum.StrEnum):
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"


class ScreenTransitionTriggerType(enum.StrEnum):
    CALLBACK = "callback"
    MESSAGE = "message"
    SYSTEM = "system"
    JOB = "job"
    ADMIN = "admin"
    UNKNOWN = "unknown"


class ScreenTransitionStatus(enum.StrEnum):
    SUCCESS = "success"
    BLOCKED = "blocked"
    ERROR = "error"
    UNKNOWN = "unknown"


class MarketingConsentEventType(enum.StrEnum):
    ACCEPTED = "accepted"
    REVOKED = "revoked"


def _enum_values(enum_cls: type[enum.Enum]) -> list[str]:
    return [member.value for member in enum_cls]


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    telegram_username: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    profile: Mapped["UserProfile"] = relationship(back_populates="user", uselist=False)
    orders: Mapped[list["Order"]] = relationship(back_populates="user")
    reports: Mapped[list["Report"]] = relationship(back_populates="user")
    report_jobs: Mapped[list["ReportJob"]] = relationship(back_populates="user")
    free_limit: Mapped["FreeLimit"] = relationship(back_populates="user", uselist=False)
    feedback_messages: Mapped[list["FeedbackMessage"]] = relationship(
        back_populates="user"
    )
    questionnaire_responses: Mapped[list["QuestionnaireResponse"]] = relationship(
        back_populates="user"
    )
    marketing_consent_events: Mapped[list["MarketingConsentEvent"]] = relationship(
        back_populates="user"
    )
    first_touch_attribution: Mapped["UserFirstTouchAttribution"] = relationship(
        back_populates="user",
        uselist=False,
    )


class UserFirstTouchAttribution(Base):
    __tablename__ = "user_first_touch_attribution"

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.telegram_user_id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    start_payload: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str | None] = mapped_column(Text, nullable=True)
    campaign: Mapped[str | None] = mapped_column(Text, nullable=True)
    placement: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_parts: Mapped[dict[str, Any] | list[Any] | None] = mapped_column(JSON, nullable=True)
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    user: Mapped[User] = relationship(back_populates="first_touch_attribution")


class UserProfile(Base):
    __tablename__ = "user_profile"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    name: Mapped[str] = mapped_column(Text)
    gender: Mapped[str | None] = mapped_column(Text, nullable=True)
    birth_date: Mapped[str] = mapped_column(Text)
    birth_time: Mapped[str | None] = mapped_column(Text, nullable=True)
    birth_place_city: Mapped[str] = mapped_column(Text)
    birth_place_region: Mapped[str | None] = mapped_column(Text, nullable=True)
    birth_place_country: Mapped[str] = mapped_column(Text)
    personal_data_consent_accepted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    personal_data_consent_source: Mapped[str | None] = mapped_column(Text, nullable=True)
    marketing_consent_accepted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    marketing_consent_document_version: Mapped[str | None] = mapped_column(Text, nullable=True)
    marketing_consent_source: Mapped[str | None] = mapped_column(Text, nullable=True)
    marketing_consent_revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    marketing_consent_revoked_source: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    user: Mapped[User] = relationship(back_populates="profile")


class MarketingConsentEvent(Base):
    __tablename__ = "marketing_consent_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
    )
    event_type: Mapped[MarketingConsentEventType] = mapped_column(
        Enum(
            MarketingConsentEventType,
            values_callable=_enum_values,
            name="marketingconsenteventtype",
        ),
        index=True,
    )
    event_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )
    document_version: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    user: Mapped[User] = relationship(back_populates="marketing_consent_events")


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    tariff: Mapped[Tariff] = mapped_column(
        Enum(Tariff, values_callable=_enum_values, name="tariff"), index=True
    )
    amount: Mapped[float] = mapped_column(Numeric(10, 2))
    currency: Mapped[str] = mapped_column(String(3), default="RUB")
    provider: Mapped[PaymentProvider] = mapped_column(
        Enum(PaymentProvider, values_callable=_enum_values, name="paymentprovider")
    )
    provider_payment_id: Mapped[str | None] = mapped_column(String(255), index=True)
    status: Mapped[OrderStatus] = mapped_column(
        Enum(OrderStatus, values_callable=_enum_values, name="orderstatus"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    payment_confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        index=True,
    )
    payment_confirmation_source: Mapped[PaymentConfirmationSource | None] = mapped_column(
        Enum(
            PaymentConfirmationSource,
            values_callable=_enum_values,
            name="paymentconfirmationsource",
        ),
        index=True,
        nullable=True,
    )
    payment_confirmed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    fulfillment_status: Mapped[OrderFulfillmentStatus] = mapped_column(
        Enum(
            OrderFulfillmentStatus,
            values_callable=_enum_values,
            name="orderfulfillmentstatus",
        ),
        index=True,
        default=OrderFulfillmentStatus.PENDING,
    )
    fulfilled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fulfilled_report_id: Mapped[int | None] = mapped_column(
        ForeignKey("reports.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )

    user: Mapped[User] = relationship(back_populates="orders")
    report: Mapped["Report"] = relationship(
        back_populates="order",
        uselist=False,
        foreign_keys="Report.order_id",
    )
    fulfilled_report: Mapped["Report | None"] = relationship(
        foreign_keys=[fulfilled_report_id],
        uselist=False,
    )


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    order_id: Mapped[int | None] = mapped_column(
        ForeignKey("orders.id", ondelete="SET NULL"), index=True
    )
    tariff: Mapped[Tariff] = mapped_column(
        Enum(Tariff, values_callable=_enum_values, name="tariff"), index=True
    )
    report_text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    pdf_storage_key: Mapped[str | None] = mapped_column(String(255))
    model_used: Mapped[ReportModel | None] = mapped_column(
        Enum(ReportModel, values_callable=_enum_values, name="reportmodel")
    )
    safety_flags: Mapped[dict | None] = mapped_column(JSON)

    user: Mapped[User] = relationship(back_populates="reports")
    order: Mapped[Order | None] = relationship(
        back_populates="report",
        foreign_keys=[order_id],
    )


class ReportJob(Base):
    __tablename__ = "report_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    order_id: Mapped[int | None] = mapped_column(
        ForeignKey("orders.id", ondelete="SET NULL"), index=True
    )
    tariff: Mapped[Tariff] = mapped_column(
        Enum(Tariff, values_callable=_enum_values, name="tariff"), index=True
    )
    status: Mapped[ReportJobStatus] = mapped_column(
        Enum(ReportJobStatus, values_callable=_enum_values, name="reportjobstatus"),
        index=True,
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
    chat_id: Mapped[int | None] = mapped_column(BigInteger)
    lock_token: Mapped[str | None] = mapped_column(String(64), index=True)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    user: Mapped[User] = relationship(back_populates="report_jobs")


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
    status: Mapped[FeedbackStatus] = mapped_column(
        Enum(FeedbackStatus, values_callable=_enum_values, name="feedbackstatus")
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    archived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True
    )
    parent_feedback_id: Mapped[int | None] = mapped_column(
        ForeignKey("feedback_messages.id", ondelete="SET NULL"), index=True
    )
    admin_reply: Mapped[str | None] = mapped_column(Text)
    replied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship(back_populates="feedback_messages")


class QuestionnaireResponse(Base):
    __tablename__ = "questionnaire_responses"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    questionnaire_version: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[QuestionnaireStatus] = mapped_column(
        Enum(
            QuestionnaireStatus,
            values_callable=_enum_values,
            name="questionnairestatus",
        ),
        index=True,
    )
    answers: Mapped[dict | None] = mapped_column(JSON)
    current_question_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship(back_populates="questionnaire_responses")


class SupportDialogMessage(Base):
    __tablename__ = "support_dialog_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    thread_feedback_id: Mapped[int] = mapped_column(
        ForeignKey("feedback_messages.id", ondelete="CASCADE"), index=True
    )
    direction: Mapped[SupportMessageDirection] = mapped_column(
        Enum(
            SupportMessageDirection,
            values_callable=_enum_values,
            name="supportmessagedirection",
        ),
        index=True,
    )
    text: Mapped[str] = mapped_column(Text)
    delivered: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True
    )


class AdminNote(Base):
    __tablename__ = "admin_notes"

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    payload: Mapped[dict | None] = mapped_column(JSON)


class AdminFinanceEvent(Base):
    __tablename__ = "admin_finance_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(
        ForeignKey("orders.id", ondelete="CASCADE"),
        index=True,
    )
    action: Mapped[str] = mapped_column(String(64), index=True)
    actor: Mapped[str | None] = mapped_column(String(255), index=True)
    payload_before: Mapped[dict | None] = mapped_column(JSON)
    payload_after: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )


class SystemPrompt(Base):
    __tablename__ = "system_prompts"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(64), index=True)
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class LLMApiKey(Base):
    __tablename__ = "llm_api_keys"

    id: Mapped[int] = mapped_column(primary_key=True)
    provider: Mapped[str] = mapped_column(String(32), index=True)
    key: Mapped[str] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    priority: Mapped[str | None] = mapped_column(String(64), default="100")
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    last_status_code: Mapped[int | None] = mapped_column(Integer)
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    success_count: Mapped[int] = mapped_column(Integer, default=0)
    failure_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class ScreenStateRecord(Base):
    __tablename__ = "screen_states"

    telegram_user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    screen_id: Mapped[str | None] = mapped_column(String(32))
    message_ids: Mapped[list[int] | None] = mapped_column(JSON)
    user_message_ids: Mapped[list[int] | None] = mapped_column(JSON)
    last_question_message_id: Mapped[int | None] = mapped_column(BigInteger)
    data: Mapped[dict | None] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class ScreenTransitionEvent(Base):
    __tablename__ = "screen_transition_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, index=True, default=0)
    from_screen_id: Mapped[str | None] = mapped_column(String(32), index=True)
    to_screen_id: Mapped[str] = mapped_column(String(32), index=True, default="unknown")
    trigger_type: Mapped[ScreenTransitionTriggerType] = mapped_column(
        Enum(
            ScreenTransitionTriggerType,
            values_callable=_enum_values,
            name="screentransitiontriggertype",
        ),
        default=ScreenTransitionTriggerType.UNKNOWN,
    )
    trigger_value: Mapped[str] = mapped_column(String(128), default="unknown")
    transition_status: Mapped[ScreenTransitionStatus] = mapped_column(
        Enum(
            ScreenTransitionStatus,
            values_callable=_enum_values,
            name="screentransitionstatus",
        ),
        default=ScreenTransitionStatus.UNKNOWN,
    )
    metadata_json: Mapped[dict | None] = mapped_column(
        "metadata",
        JSON,
        default=lambda: {
            "tariff": None,
            "report_job_status": None,
            "provider": None,
            "reason": None,
        },
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )


    @classmethod
    def build_fail_safe(
        cls,
        telegram_user_id: int | None = None,
        from_screen_id: str | None = None,
        to_screen_id: str | None = None,
        trigger_type: ScreenTransitionTriggerType | str | None = None,
        trigger_value: str | None = None,
        transition_status: ScreenTransitionStatus | str | None = None,
        metadata_json: dict[str, Any] | None = None,
    ) -> "ScreenTransitionEvent":
        safe_trigger_type = cls._coerce_trigger_type(trigger_type)
        safe_transition_status = cls._coerce_transition_status(transition_status)
        return cls(
            telegram_user_id=telegram_user_id or 0,
            from_screen_id=from_screen_id,
            to_screen_id=to_screen_id or "unknown",
            trigger_type=safe_trigger_type,
            trigger_value=trigger_value or "unknown",
            transition_status=safe_transition_status,
            metadata_json=metadata_json
            or {
                "tariff": None,
                "report_job_status": None,
                "provider": None,
                "reason": None,
            },
        )

    @staticmethod
    def _coerce_trigger_type(
        value: ScreenTransitionTriggerType | str | None,
    ) -> ScreenTransitionTriggerType:
        if isinstance(value, ScreenTransitionTriggerType):
            return value
        if isinstance(value, str):
            try:
                return ScreenTransitionTriggerType(value)
            except ValueError:
                return ScreenTransitionTriggerType.UNKNOWN
        return ScreenTransitionTriggerType.UNKNOWN

    @staticmethod
    def _coerce_transition_status(
        value: ScreenTransitionStatus | str | None,
    ) -> ScreenTransitionStatus:
        if isinstance(value, ScreenTransitionStatus):
            return value
        if isinstance(value, str):
            try:
                return ScreenTransitionStatus(value)
            except ValueError:
                return ScreenTransitionStatus.UNKNOWN
        return ScreenTransitionStatus.UNKNOWN
