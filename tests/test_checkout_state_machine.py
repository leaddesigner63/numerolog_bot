import pytest

from app.bot.flows.checkout_state_machine import (
    CheckoutContext,
    resolve_checkout_entry_screen,
    resolve_checkout_transition,
)


@pytest.mark.parametrize("tariff", ["T1", "T2", "T3"])
@pytest.mark.parametrize(
    "case",
    [
        {
            "name": "payment_start_requires_profile",
            "event": "payment_start",
            "context": {
                "profile_ready": False,
                "questionnaire_ready": False,
                "order_created": False,
                "payment_confirmed": False,
            },
            "expected_allowed": False,
            "expected_screen": "S4",
            "expected_guard": "profile_required",
        },
        {
            "name": "payment_start_ready",
            "event": "payment_start",
            "context": {
                "profile_ready": True,
                "questionnaire_ready": True,
                "order_created": False,
                "payment_confirmed": False,
            },
            "expected_allowed": True,
            "expected_screen": "S3",
            "expected_guard": None,
        },
        {
            "name": "payment_confirmed_webhook",
            "event": "payment_confirmed_webhook",
            "context": {
                "profile_ready": True,
                "questionnaire_ready": True,
                "order_created": True,
                "payment_confirmed": True,
            },
            "expected_allowed": True,
            "expected_screen": "S4",
            "expected_guard": None,
        },
        {
            "name": "payment_timeout_without_order",
            "event": "payment_timeout",
            "context": {
                "profile_ready": True,
                "questionnaire_ready": True,
                "order_created": False,
                "payment_confirmed": False,
            },
            "expected_allowed": False,
            "expected_screen": "S4",
            "expected_guard": "order_required",
        },
    ],
    ids=lambda case: case["name"],
)
def test_checkout_transition_table_for_paid_tariffs(tariff: str, case: dict) -> None:
    context_data = dict(case["context"])
    if tariff in {"T2", "T3"} and case["name"] == "payment_start_requires_profile":
        context_data["questionnaire_ready"] = False

    context = CheckoutContext(tariff=tariff, **context_data)
    decision = resolve_checkout_transition(context, case["event"])

    expected_guard = case["expected_guard"]
    expected_screen = case["expected_screen"]
    if (
        case["name"] == "payment_start_ready"
        and tariff in {"T2", "T3"}
        and not context.questionnaire_ready
    ):
        expected_guard = "questionnaire_required"
        expected_screen = "S5"

    assert decision.allowed is case["expected_allowed"]
    assert decision.next_screen == expected_screen
    assert decision.guard_reason == expected_guard


@pytest.mark.parametrize(
    ("tariff", "reusable_paid_order", "expected_screen"),
    [
        ("T0", False, "S4"),
        ("T1", True, "S4"),
        ("T1", False, "S2"),
    ],
)
def test_checkout_entry_screen(tariff: str, reusable_paid_order: bool, expected_screen: str) -> None:
    assert (
        resolve_checkout_entry_screen(
            tariff=tariff,
            reusable_paid_order=reusable_paid_order,
        )
        == expected_screen
    )
