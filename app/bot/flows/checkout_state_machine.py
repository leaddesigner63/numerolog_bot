from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


CheckoutState = Literal[
    "tariff_selected",
    "profile_ready",
    "questionnaire_ready",
    "order_created",
    "payment_pending",
    "payment_confirmed",
    "job_started",
]

CheckoutEvent = Literal[
    "profile_saved",
    "questionnaire_done",
    "payment_start",
    "payment_confirmed_webhook",
    "payment_timeout",
]

PAID_TARIFFS = {"T1", "T2", "T3"}
QUESTIONNAIRE_REQUIRED_TARIFFS = {"T2", "T3"}


@dataclass(frozen=True)
class CheckoutContext:
    tariff: str | None
    profile_ready: bool
    questionnaire_ready: bool
    order_created: bool
    payment_confirmed: bool


@dataclass(frozen=True)
class CheckoutDecision:
    allowed: bool
    next_state: CheckoutState
    next_screen: str
    guard_reason: str | None = None
    should_create_order: bool = False
    should_start_job: bool = False


def resolve_checkout_entry_screen(*, tariff: str | None, reusable_paid_order: bool) -> str:
    if tariff == "T0" or reusable_paid_order:
        return "S4"
    return "S2"


def derive_checkout_state(context: CheckoutContext) -> CheckoutState:
    if context.payment_confirmed:
        return "payment_confirmed"
    if context.order_created:
        return "payment_pending"
    if context.tariff in QUESTIONNAIRE_REQUIRED_TARIFFS and context.questionnaire_ready:
        return "questionnaire_ready"
    if context.profile_ready:
        return "profile_ready"
    return "tariff_selected"


def resolve_checkout_transition(context: CheckoutContext, event: CheckoutEvent) -> CheckoutDecision:
    current_state = derive_checkout_state(context)
    tariff = context.tariff
    questionnaire_required = tariff in QUESTIONNAIRE_REQUIRED_TARIFFS

    if event == "payment_start":
        if tariff not in PAID_TARIFFS:
            return CheckoutDecision(False, current_state, "S1", guard_reason="paid_tariff_required")
        if not context.profile_ready:
            return CheckoutDecision(False, current_state, "S4", guard_reason="profile_required")
        if questionnaire_required and not context.questionnaire_ready:
            return CheckoutDecision(False, current_state, "S5", guard_reason="questionnaire_required")
        return CheckoutDecision(True, "payment_pending", "S3", should_create_order=not context.order_created)

    if event == "questionnaire_done":
        if tariff not in QUESTIONNAIRE_REQUIRED_TARIFFS:
            return CheckoutDecision(False, current_state, "S1", guard_reason="questionnaire_tariff_required")
        if not context.questionnaire_ready:
            return CheckoutDecision(False, current_state, "S5", guard_reason="questionnaire_required")
        return CheckoutDecision(True, "payment_pending", "S3", should_create_order=not context.order_created)

    if event == "profile_saved":
        if not context.profile_ready:
            return CheckoutDecision(False, current_state, "S4", guard_reason="profile_required")
        if tariff == "T1":
            if context.payment_confirmed:
                return CheckoutDecision(True, "job_started", "S6", should_start_job=True)
            return CheckoutDecision(True, "profile_ready", "S3")
        if tariff in QUESTIONNAIRE_REQUIRED_TARIFFS:
            if not context.questionnaire_ready:
                return CheckoutDecision(True, "profile_ready", "S5")
            if context.payment_confirmed:
                return CheckoutDecision(True, "job_started", "S6", should_start_job=True)
            return CheckoutDecision(True, "questionnaire_ready", "S3")
        return CheckoutDecision(True, "profile_ready", "S4")

    if event == "payment_confirmed_webhook":
        if not context.order_created:
            return CheckoutDecision(False, current_state, "S3", guard_reason="order_required")
        if questionnaire_required and not context.questionnaire_ready:
            return CheckoutDecision(True, "payment_confirmed", "S5")
        return CheckoutDecision(True, "payment_confirmed", "S4")

    if event == "payment_timeout":
        if not context.order_created:
            return CheckoutDecision(False, current_state, "S4", guard_reason="order_required")
        return CheckoutDecision(True, "payment_pending", "S3")

    return CheckoutDecision(False, current_state, "S1", guard_reason="unsupported_event")
