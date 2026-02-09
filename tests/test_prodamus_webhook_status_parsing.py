from app.payments.prodamus import _extract_webhook


def test_extract_webhook_supports_order_num_and_success_description() -> None:
    webhook = _extract_webhook(
        {
            "order_num": "7788",
            "payment_status": "success",
            "payment_status_description": "Успешная оплата",
            "invoice_id": "inv-7788",
        }
    )

    assert webhook.order_id == 7788
    assert webhook.payment_id == "inv-7788"
    assert webhook.is_paid is True


def test_extract_webhook_supports_localized_success_type() -> None:
    webhook = _extract_webhook({"order_id": "17", "type": "Успешная оплата"})

    assert webhook.order_id == 17
    assert webhook.is_paid is True
