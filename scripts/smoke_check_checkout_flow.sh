#!/usr/bin/env bash
set -euo pipefail

# Smoke-check для checkout-at-end флоу.
# Запускает только регрессионные тесты, критичные для новой позиции оплаты.

pytest -q \
  tests/test_payment_screen_transitions.py \
  tests/test_payment_screen_s3.py \
  tests/test_report_job_requires_paid_order.py \
  tests/test_profile_questionnaire_access_guards.py \
  tests/test_start_payload_routing.py \
  tests/test_payment_waiter_restore.py \
  tests/test_screen_s2_checkout_flow.py \
  tests/test_questionnaire_done_refresh.py
