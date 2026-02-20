from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

from app.bot.handlers import screens


class ScreensConsentCallbacksRoutingTests(IsolatedAsyncioTestCase):
    async def test_profile_consent_accept_is_delegated(self) -> None:
        callback = SimpleNamespace(
            data="profile:consent:accept",
            from_user=SimpleNamespace(id=1),
            message=SimpleNamespace(),
        )

        with (
            patch.object(screens, "_safe_callback_processing", new=AsyncMock()),
            patch.object(screens.screen_manager, "update_state", return_value=SimpleNamespace(data={})),
            patch.object(screens, "accept_profile_consent", new=AsyncMock()) as accept_profile_consent,
        ):
            await screens.handle_callbacks(callback, state=SimpleNamespace())

        accept_profile_consent.assert_awaited_once_with(callback)

    async def test_profile_consent_accept_without_marketing_is_delegated(self) -> None:
        callback = SimpleNamespace(
            data="profile:consent:accept_without_marketing",
            from_user=SimpleNamespace(id=1),
            message=SimpleNamespace(),
        )

        with (
            patch.object(screens, "_safe_callback_processing", new=AsyncMock()),
            patch.object(screens.screen_manager, "update_state", return_value=SimpleNamespace(data={})),
            patch.object(screens, "accept_profile_consent_without_marketing", new=AsyncMock()) as accept_without_marketing,
        ):
            await screens.handle_callbacks(callback, state=SimpleNamespace())

        accept_without_marketing.assert_awaited_once_with(callback)

    async def test_marketing_prompt_callbacks_are_delegated(self) -> None:
        accept_callback = SimpleNamespace(
            data="marketing:consent:accept",
            from_user=SimpleNamespace(id=1),
            message=SimpleNamespace(),
        )
        skip_callback = SimpleNamespace(
            data="marketing:consent:skip",
            from_user=SimpleNamespace(id=1),
            message=SimpleNamespace(),
        )

        with (
            patch.object(screens, "_safe_callback_processing", new=AsyncMock()),
            patch.object(screens.screen_manager, "update_state", return_value=SimpleNamespace(data={})),
            patch.object(screens, "accept_marketing_consent_prompt", new=AsyncMock()) as accept_marketing,
            patch.object(screens, "skip_marketing_consent_prompt", new=AsyncMock()) as skip_marketing,
        ):
            await screens.handle_callbacks(accept_callback, state=SimpleNamespace())
            await screens.handle_callbacks(skip_callback, state=SimpleNamespace())

        accept_marketing.assert_awaited_once_with(accept_callback)
        skip_marketing.assert_awaited_once_with(skip_callback)
