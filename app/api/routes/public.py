from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import HTMLResponse
from sqlalchemy import select

from app.core.config import settings
from app.core.newsletter_unsubscribe import verify_unsubscribe_token
from app.core.timezone import now_app_timezone
from app.db.models import MarketingConsentEvent, MarketingConsentEventType, UserProfile
from app.db.session import get_session

router = APIRouter(tags=["public"])


def _safe_price(value: object, *, default: int = 0) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    return default


def _unsubscribe_html_page(*, title: str, message: str) -> str:
    metrika_id = settings.yandex_metrika_counter_id
    metrika_snippet = ""
    if metrika_id:
        metrika_snippet = f"""<!-- Yandex.Metrika counter -->
<script type=\"text/javascript\" >
   (function(m,e,t,r,i,k,a){{
      m[i]=m[i]||function(){{(m[i].a=m[i].a||[]).push(arguments)}};
      m[i].l=1*new Date();
      for (var j = 0; j < document.scripts.length; j++) {{if (document.scripts[j].src === r) {{ return; }}}}
      k=e.createElement(t),a=e.getElementsByTagName(t)[0],k.async=1,k.src=r,a.parentNode.insertBefore(k,a);
   }})(window, document, \"script\", \"https://mc.yandex.ru/metrika/tag.js\", \"ym\");

   ym({metrika_id}, \"init\", {{
        clickmap:true,
        trackLinks:true,
        accurateTrackBounce:true,
        webvisor:true
   }});
</script>
<noscript><div><img src=\"https://mc.yandex.ru/watch/{metrika_id}\" style=\"position:absolute; left:-9999px;\" alt=\"\" /></div></noscript>
<!-- /Yandex.Metrika counter -->"""

    return f"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  {metrika_snippet}
  <style>
    body {{
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      background: #f7f7fb;
      color: #222;
      margin: 0;
      display: grid;
      min-height: 100vh;
      place-items: center;
      padding: 24px;
    }}
    .card {{
      max-width: 560px;
      width: 100%;
      background: #fff;
      border-radius: 14px;
      padding: 24px;
      box-shadow: 0 10px 30px rgba(17, 24, 39, 0.08);
    }}
    h1 {{ margin-top: 0; font-size: 24px; }}
    p {{ line-height: 1.5; margin-bottom: 0; }}
  </style>
</head>
<body>
  <main class="card">
    <h1>{title}</h1>
    <p>{message}</p>
  </main>
</body>
</html>"""


@router.get("/api/public/tariffs")
async def public_tariffs() -> dict[str, object]:
    prices = settings.tariff_prices_rub
    payload = {
        "currency": "RUB",
        "tariffs": {
            "T0": _safe_price(prices.get("T0"), default=0),
            "T1": _safe_price(prices.get("T1"), default=0),
            "T2": _safe_price(prices.get("T2"), default=0),
            "T3": _safe_price(prices.get("T3"), default=0),
        },
    }
    return payload


@router.get("/newsletter/unsubscribe", response_class=HTMLResponse)
async def newsletter_unsubscribe(token: str = "") -> HTMLResponse:
    secret = settings.newsletter_unsubscribe_secret or ""
    payload = verify_unsubscribe_token(token, secret=secret)
    if payload is None:
        html = _unsubscribe_html_page(
            title="Ссылка недействительна",
            message="Не удалось подтвердить ссылку для отписки. Проверьте ссылку и попробуйте снова.",
        )
        return HTMLResponse(content=html, status_code=400)

    user_id = payload.get("user_id")
    revoked_at = now_app_timezone()

    with get_session() as session:
        profile = session.execute(
            select(UserProfile).where(UserProfile.user_id == user_id)
        ).scalar_one_or_none()

        if profile is not None:
            already_revoked = profile.marketing_consent_revoked_at is not None
            profile.marketing_consent_accepted_at = None
            if not profile.marketing_consent_document_version:
                profile.marketing_consent_document_version = settings.newsletter_consent_document_version

            if not already_revoked:
                profile.marketing_consent_revoked_at = revoked_at
                profile.marketing_consent_revoked_source = "unsubscribe_link"
                session.add(
                    MarketingConsentEvent(
                        user_id=profile.user_id,
                        event_type=MarketingConsentEventType.REVOKED,
                        event_at=revoked_at,
                        document_version=profile.marketing_consent_document_version
                        or settings.newsletter_consent_document_version,
                        source="unsubscribe_link",
                        metadata_json={
                            "issued_at": payload.get("issued_at"),
                            "token_user_id": user_id,
                            "route": "newsletter_unsubscribe",
                        },
                    )
                )
            session.commit()

    html = _unsubscribe_html_page(
        title="Вы отписаны от рассылки",
        message="Подписка на маркетинговые сообщения отключена.",
    )
    return HTMLResponse(content=html)
