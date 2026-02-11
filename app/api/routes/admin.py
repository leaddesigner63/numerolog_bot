from __future__ import annotations

import base64
import hashlib
import json
import logging
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError, TimeoutError as SQLAlchemyTimeoutError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.services.admin_analytics import (
    AnalyticsFilters,
    build_screen_transition_analytics,
    parse_trigger_type,
)
from pydantic import BaseModel
from app.db.models import (
    AdminNote,
    FeedbackMessage,
    FeedbackStatus,
    LLMApiKey,
    Order,
    OrderFulfillmentStatus,
    OrderStatus,
    Report,
    SystemPrompt,
    User,
    UserProfile,
    SupportDialogMessage,
    SupportMessageDirection,
)
from app.db.session import get_session_factory


router = APIRouter(prefix="/admin", tags=["admin"])
logger = logging.getLogger(__name__)


def _admin_credentials_ready() -> bool:
    return bool(settings.admin_login) and bool(settings.admin_password)


def _admin_session_token() -> str | None:
    if not _admin_credentials_ready():
        return None
    raw = f"{settings.admin_login}:{settings.admin_password}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _extract_basic_auth(request: Request) -> tuple[str | None, str | None]:
    auth_header = request.headers.get("authorization")
    if not auth_header:
        return None, None
    if not auth_header.lower().startswith("basic "):
        return None, None
    payload = auth_header[6:]
    try:
        decoded = base64.b64decode(payload).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return None, None
    if ":" not in decoded:
        return None, None
    login, password = decoded.split(":", 1)
    return login, password


def _is_valid_admin_credentials(login: str | None, password: str | None) -> bool:
    if not _admin_credentials_ready():
        return False
    if login is None or password is None:
        return False
    return login == settings.admin_login and password == settings.admin_password


def _require_admin(request: Request) -> None:
    if not _admin_credentials_ready():
        raise HTTPException(status_code=503, detail="ADMIN_LOGIN or ADMIN_PASSWORD is not configured")
    expected_token = _admin_session_token()
    if expected_token:
        provided_token = request.cookies.get("admin_session")
        if provided_token and provided_token == expected_token:
            return
    login, password = _extract_basic_auth(request)
    if _is_valid_admin_credentials(login, password):
        return
    raise HTTPException(status_code=401, detail="Missing admin credentials")


def _get_db_session(request: Request) -> Session:
    _require_admin(request)
    try:
        session_factory = get_session_factory()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    session = session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _admin_login_html(message: str | None = None) -> str:
    alert = f"<div class='alert'>{message}</div>" if message else ""
    return f"""
<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>Numerolog Bot Admin</title>
  <style>
    body {{
      margin: 0;
      font-family: "Inter", system-ui, sans-serif;
      background: #0f1115;
      color: #e6e9ef;
      display: flex;
      align-items: center;
      justify-content: center;
      min-height: 100vh;
      padding: 24px;
    }}
    .card {{
      background: #1a1d24;
      padding: 24px;
      border-radius: 16px;
      max-width: 420px;
      width: 100%;
      box-shadow: 0 10px 30px rgba(0,0,0,0.25);
    }}
    h1 {{
      margin: 0 0 12px;
      font-size: 20px;
    }}
    p {{
      margin: 0 0 16px;
      color: #94a3b8;
      line-height: 1.4;
    }}
    input {{
      width: 100%;
      border-radius: 10px;
      border: 1px solid #2a2f3a;
      background: #11151c;
      color: #e6e9ef;
      padding: 10px 12px;
      font-size: 14px;
      margin-bottom: 12px;
    }}
    button {{
      width: 100%;
      border-radius: 10px;
      border: none;
      background: #3b82f6;
      color: white;
      padding: 10px 12px;
      font-size: 14px;
      cursor: pointer;
    }}
    .alert {{
      background: rgba(239, 68, 68, 0.12);
      border: 1px solid rgba(239, 68, 68, 0.4);
      color: #fecaca;
      padding: 10px 12px;
      border-radius: 10px;
      margin-bottom: 12px;
      font-size: 13px;
    }}
  </style>
</head>
<body>
  <div class="card">
    <h1>Доступ к админке</h1>
    <p>Введите логин и пароль для доступа к панели управления.</p>
    {alert}
    <form method="post" action="/admin/login">
      <input id="adminLogin" name="login" type="text" placeholder="Логин" autocomplete="off"/>
      <input id="adminPassword" name="password" type="password" placeholder="Пароль" autocomplete="off"/>
      <button type="submit">Открыть</button>
    </form>
  </div>
</body>
</html>
"""


@router.get("", response_class=HTMLResponse)
def admin_ui(request: Request) -> HTMLResponse:
    if not _admin_credentials_ready():
        return HTMLResponse(
            _admin_login_html("ADMIN_LOGIN или ADMIN_PASSWORD не настроены на сервере."),
            status_code=503,
        )
    expected_token = _admin_session_token()
    if not expected_token:
        return HTMLResponse(_admin_login_html(), status_code=401)
    provided_token = request.cookies.get("admin_session")
    if provided_token != expected_token:
        return HTMLResponse(_admin_login_html(), status_code=401)
    auto_refresh_seconds = settings.admin_auto_refresh_seconds or 0
    html = """
<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>Numerolog Bot Admin</title>
  <style>
    :root {
      color-scheme: light dark;
      --bg: #0f1115;
      --card: #1a1d24;
      --accent: #3b82f6;
      --text: #e6e9ef;
      --muted: #94a3b8;
      --danger: #ef4444;
      --ok: #22c55e;
      --table-font-size: 12px;
      --table-cell-padding-y: 4px;
      --table-cell-padding-x: 6px;
    }
    body {
      margin: 0;
      font-family: "Inter", system-ui, sans-serif;
      background: var(--bg);
      color: var(--text);
    }
    header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 24px;
      border-bottom: 1px solid #2a2f3a;
      flex-wrap: wrap;
      gap: 12px;
    }
    header h1 {
      margin: 0;
      font-size: 20px;
    }
    main {
      display: grid;
      grid-template-columns: 240px 1fr;
      gap: 16px;
      padding: 24px;
      min-height: calc(100vh - 96px);
    }
    .sidebar {
      background: var(--card);
      border-radius: 12px;
      padding: 16px;
      height: fit-content;
      position: sticky;
      top: 24px;
    }
    .content {
      display: flex;
      flex-direction: column;
      gap: 16px;
    }
    section {
      background: var(--card);
      border-radius: 12px;
      padding: 16px;
      min-height: 200px;
    }
    .js-ready section[data-panel] {
      display: none;
    }
    .js-ready section[data-panel].active {
      display: block;
    }
    section h2 {
      margin: 0 0 12px;
      font-size: 16px;
    }
    nav {
      display: flex;
      flex-direction: column;
      gap: 8px;
      margin-top: 8px;
    }
    .nav-button {
      text-align: left;
      background: transparent;
      border: 1px solid transparent;
      color: var(--text);
      padding: 10px 12px;
      border-radius: 10px;
      cursor: pointer;
    }
    .nav-button.active {
      background: rgba(59, 130, 246, 0.15);
      border-color: rgba(59, 130, 246, 0.4);
      color: #dbeafe;
    }
    .nav-button:hover {
      border-color: #3a4150;
    }
    .row {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      margin-bottom: 8px;
    }
    .table-controls {
      align-items: center;
      gap: 6px;
      margin-bottom: 6px;
    }
    .table-search {
      min-width: 180px;
      flex: 1 1 180px;
      max-width: 340px;
    }
    .field {
      display: flex;
      flex-direction: column;
      gap: 4px;
    }
    input, textarea, select, button {
      border-radius: 8px;
      border: 1px solid #2a2f3a;
      background: #11151c;
      color: var(--text);
      padding: 8px 10px;
      font-size: 14px;
    }
    textarea {
      min-height: 90px;
    }
    button {
      cursor: pointer;
      background: var(--accent);
      border-color: transparent;
      color: white;
    }
    button.secondary {
      background: transparent;
      border: 1px solid #3a4150;
      color: var(--text);
    }
    table {
      width: 100%;
      border-collapse: collapse;
      font-size: var(--table-font-size);
      table-layout: fixed;
    }
    th, td {
      text-align: left;
      padding: var(--table-cell-padding-y) var(--table-cell-padding-x);
      border-bottom: 1px solid #2a2f3a;
      vertical-align: top;
      word-break: break-word;
      line-height: 1.3;
    }
    th {
      font-weight: 600;
    }
    td.copyable-cell {
      cursor: copy;
      transition: background 0.15s ease-in-out;
    }
    td.copyable-cell:hover {
      background: rgba(59, 130, 246, 0.12);
    }
    td.copyable-cell .cell-content {
      display: -webkit-box;
      -webkit-box-orient: vertical;
      -webkit-line-clamp: 3;
      overflow: hidden;
      white-space: pre-wrap;
      word-break: break-word;
      line-height: 1.3;
      max-height: calc(1.3em * 3);
    }
    .copy-toast {
      position: fixed;
      right: 24px;
      bottom: 24px;
      background: rgba(15, 23, 42, 0.92);
      color: var(--text);
      border: 1px solid #2a2f3a;
      padding: 8px 12px;
      border-radius: 10px;
      font-size: 12px;
      opacity: 0;
      pointer-events: none;
      transform: translateY(8px);
      transition: opacity 0.2s ease, transform 0.2s ease;
      z-index: 20;
    }
    .copy-toast.visible {
      opacity: 1;
      transform: translateY(0);
    }
    pre {
      white-space: pre-wrap;
      word-break: break-word;
      overflow-wrap: anywhere;
      margin: 0;
    }
    .prompt-preview {
      max-height: 240px;
      overflow-y: auto;
    }
    th.sortable {
      cursor: pointer;
      user-select: none;
    }
    th.sortable:hover {
      color: #dbeafe;
    }
    .sort-indicator {
      opacity: 0.6;
      margin-left: 4px;
      font-size: 11px;
    }
    .muted {
      color: var(--muted);
      font-size: 12px;
    }
    .status {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      font-size: 12px;
      padding: 2px 8px;
      border-radius: 999px;
      background: #1f2937;
    }
    .status.ok {
      background: rgba(34, 197, 94, 0.2);
      color: var(--ok);
    }
    .status.bad {
      background: rgba(239, 68, 68, 0.2);
      color: var(--danger);
    }
    .wide {
      grid-column: 1 / -1;
    }
    .message {
      margin-top: 6px;
      font-size: 12px;
      color: var(--muted);
    }
    .prompt-danger-zone {
      margin-top: 10px;
      border: 1px solid rgba(239, 68, 68, 0.45);
      border-radius: 10px;
      background: rgba(239, 68, 68, 0.12);
      padding: 10px 12px;
      font-size: 12px;
      line-height: 1.35;
    }
    .prompt-danger-zone.safe {
      border-color: rgba(34, 197, 94, 0.45);
      background: rgba(34, 197, 94, 0.12);
    }
    .prompt-danger-zone-title {
      font-weight: 600;
      margin-bottom: 6px;
    }
    .prompt-danger-zone ul {
      margin: 0;
      padding-left: 18px;
      display: flex;
      flex-direction: column;
      gap: 4px;
    }
    .prompt-danger-fragment {
      color: #fecaca;
    }
    .api-key-status {
      margin-top: 6px;
      font-size: 12px;
      color: var(--muted);
    }
    .api-key-status.ok {
      color: var(--ok);
    }
    .api-key-status.danger {
      color: var(--danger);
    }
    .tabs {
      display: flex;
      gap: 8px;
      margin-top: 12px;
      flex-wrap: wrap;
    }
    .tab-button {
      background: transparent;
      border: 1px solid #3a4150;
      color: var(--text);
      padding: 8px 12px;
      border-radius: 999px;
      cursor: pointer;
      font-size: 13px;
    }
    .tab-button.active {
      background: rgba(59, 130, 246, 0.2);
      border-color: rgba(59, 130, 246, 0.6);
      color: #dbeafe;
    }
    .tab-panel {
      display: none;
      margin-top: 12px;
    }
    .tab-panel.active {
      display: block;
    }
    .select-col {
      width: 38px;
      text-align: center;
    }
    .row-checkbox,
    .select-all-checkbox {
      width: 16px;
      height: 16px;
      cursor: pointer;
      accent-color: var(--accent);
    }
    .bulk-actions {
      margin-top: 10px;
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      align-items: center;
    }
    .thread-history {
      margin-top: 12px;
      border: 1px solid #2a2f3a;
      border-radius: 10px;
      padding: 10px;
      background: #11151c;
    }
    .thread-history-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 8px;
      margin-bottom: 10px;
      flex-wrap: wrap;
    }
    .thread-history-list {
      display: flex;
      flex-direction: column;
      gap: 8px;
      max-height: 360px;
      overflow-y: auto;
      padding-right: 4px;
    }
    .thread-history-item {
      border: 1px solid #2a2f3a;
      border-radius: 8px;
      padding: 8px;
      background: #0f1115;
      white-space: pre-wrap;
      word-break: break-word;
    }
    .thread-history-item.user {
      border-left: 3px solid #3b82f6;
    }
    .thread-history-item.admin {
      border-left: 3px solid #22c55e;
    }
    .thread-history-meta {
      color: #94a3b8;
      font-size: 12px;
      margin-bottom: 4px;
    }
    .analytics-filters {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
      gap: 8px;
      margin-bottom: 12px;
    }
    .kpi-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 10px;
      margin-bottom: 12px;
    }
    .kpi-card {
      border: 1px solid #2a2f3a;
      border-radius: 10px;
      padding: 10px;
      background: #11151c;
    }
    .kpi-card h3 {
      margin: 0;
      font-size: 12px;
      color: var(--muted);
    }
    .kpi-card .value {
      margin-top: 6px;
      font-size: 22px;
      font-weight: 600;
    }
    .kpi-card.problem {
      border-color: rgba(239, 68, 68, 0.65);
      background: rgba(127, 29, 29, 0.2);
    }
    .analytics-block {
      border: 1px solid #2a2f3a;
      border-radius: 10px;
      padding: 10px;
      margin-top: 10px;
      background: #11151c;
    }
    .analytics-title {
      font-size: 13px;
      margin-bottom: 8px;
      color: #cbd5e1;
    }
    .funnel-chart {
      display: flex;
      flex-direction: column;
      gap: 8px;
    }
    .funnel-step {
      display: grid;
      grid-template-columns: 110px 1fr 55px;
      gap: 8px;
      align-items: center;
      font-size: 12px;
    }
    .funnel-bar-wrap {
      width: 100%;
      height: 14px;
      border-radius: 999px;
      background: #0f1115;
      border: 1px solid #2a2f3a;
      overflow: hidden;
    }
    .funnel-bar {
      height: 100%;
      background: linear-gradient(90deg, #22c55e, #3b82f6);
    }
    .problem-cell {
      background: rgba(239, 68, 68, 0.16);
      color: #fecaca;
    }
    .analytics-state {
      font-size: 13px;
      color: var(--muted);
    }
  </style>
</head>
<body>
  <header>
    <h1>Админка Numerolog Bot</h1>
    <div class="row" style="align-items: center;">
      <div class="muted">Доступ по логину и паролю</div>
      <button class="secondary" onclick="logout()">Выйти</button>
    </div>
  </header>
  <main>
    <aside class="sidebar">
      <div class="muted">Разделы админки</div>
      <nav>
        <button class="nav-button active" data-section="overview">Сводка</button>
        <button class="nav-button" data-section="health">Состояние сервиса</button>
        <button class="nav-button" data-section="llm-keys">LLM ключи</button>
        <button class="nav-button" data-section="orders">Заказы</button>
        <button class="nav-button" data-section="reports">Отчёты</button>
        <button class="nav-button" data-section="users">Пользователи</button>
        <button class="nav-button" data-section="feedback-inbox">Обратная связь</button>
        <button class="nav-button" data-section="analytics">Analytics</button>
        <button class="nav-button" data-section="system-prompts">Системные промпты</button>
        <button class="nav-button" data-section="notes">Админ-заметки</button>
      </nav>
    </aside>
    <div class="content">
      <section data-panel="overview" class="active">
        <h2>Сводка</h2>
        <div id="overview" class="muted">Загрузка...</div>
        <div class="row" style="margin-top: 12px;">
          <button class="secondary" onclick="loadOverview()">Обновить</button>
        </div>
      </section>
      <section data-panel="health">
        <h2>Состояние сервиса</h2>
        <div id="health" class="muted">Загрузка...</div>
        <div class="row" style="margin-top: 12px;">
          <button class="secondary" onclick="loadHealth()">Обновить</button>
        </div>
      </section>
      <section data-panel="llm-keys">
        <h2>LLM ключи</h2>
        <div class="muted">
          Ключи из админки имеют приоритет над переменными окружения.
          Если ключи не добавлены, используются значения из .env.
        </div>
        <div class="row" style="margin-top: 12px; align-items: flex-end;">
          <div class="field" style="min-width: 220px;">
            <label for="llmProviderSelect">Провайдер</label>
            <select id="llmProviderSelect" onchange="syncLlmProviderInput()">
              <option value="">Выберите провайдера</option>
              <option value="gemini">Gemini</option>
              <option value="openai">OpenAI</option>
              <option value="custom">Другой</option>
            </select>
          </div>
          <div class="field" style="min-width: 220px;">
            <label for="llmProviderInput">Свой провайдер</label>
            <input id="llmProviderInput" type="text" placeholder="Введите провайдера в любом виде" />
          </div>
          <div class="field" style="flex: 1 1 320px;">
            <label for="llmKeyInput">API-ключ</label>
            <input id="llmKeyInput" type="text" placeholder="Введите ключ без ограничений" />
          </div>
          <div class="field" style="min-width: 140px;">
            <label for="llmPriorityInput">Приоритет</label>
            <input id="llmPriorityInput" type="text" placeholder="100" />
          </div>
          <div class="field" style="min-width: 140px;">
            <label for="llmActiveInput">Активен</label>
            <select id="llmActiveInput">
              <option value="true">Да</option>
              <option value="false">Нет</option>
            </select>
          </div>
          <div class="field">
            <button onclick="saveLlmKey()">Сохранить</button>
            <button class="secondary" style="margin-top: 6px;" onclick="resetLlmKeyForm()">Очистить</button>
          </div>
        </div>
        <div class="row" style="margin-top: 12px; align-items: flex-end;">
          <div class="field" style="flex: 1 1 360px;">
            <label for="llmBulkFile">Файл с ключами</label>
            <input id="llmBulkFile" type="file" />
            <div class="message">
              Формат файла: одна строка = один ключ. Провайдер выбирается ниже
              и применяется ко всем строкам файла. Любые значения сохраняются как есть.
              Пример строки: <code>AIza...</code>
            </div>
          </div>
          <div class="field" style="min-width: 220px;">
            <label for="llmBulkProviderSelect">Провайдер для файла</label>
            <select id="llmBulkProviderSelect" onchange="syncLlmBulkProviderInput()">
              <option value="">Выберите провайдера</option>
              <option value="gemini">Gemini</option>
              <option value="openai">OpenAI</option>
              <option value="custom">Другой</option>
            </select>
          </div>
          <div class="field" style="min-width: 220px;">
            <label for="llmBulkProviderInput">Свой провайдер</label>
            <input id="llmBulkProviderInput" type="text" placeholder="Введите провайдера в любом виде" />
          </div>
          <div class="field">
            <button class="secondary" onclick="uploadLlmKeysBulk()">Загрузить файл</button>
          </div>
        </div>
        <div class="row table-controls">
          <button class="secondary" onclick="loadLlmKeys()">Обновить</button>
        </div>
        <div class="tabs">
          <button class="tab-button active" data-llm-tab="active">Активные</button>
          <button class="tab-button" data-llm-tab="inactive">Неактивные</button>
        </div>
        <div class="tab-panel active" data-llm-panel="active">
          <div class="row table-controls">
            <input id="llmKeysActiveSearch" class="table-search" type="text" placeholder="Поиск по активным ключам" />
            <button class="secondary" onclick="clearTableFilters('llmKeysActive')">Сбросить</button>
          </div>
          <div class="bulk-actions">
            <button class="secondary" onclick="bulkToggleLlmKeys(true)">Включить выбранные</button>
            <button class="secondary" onclick="bulkToggleLlmKeys(false)">Выключить выбранные</button>
            <button class="secondary" onclick="bulkDeleteLlmKeys()">Удалить выбранные</button>
          </div>
          <div id="llmKeysActive" class="muted">Загрузка...</div>
        </div>
        <div class="tab-panel" data-llm-panel="inactive">
          <div class="row table-controls">
            <input id="llmKeysInactiveSearch" class="table-search" type="text" placeholder="Поиск по неактивным ключам" />
            <button class="secondary" onclick="clearTableFilters('llmKeysInactive')">Сбросить</button>
          </div>
          <div class="bulk-actions">
            <button class="secondary" onclick="bulkToggleLlmKeys(true)">Включить выбранные</button>
            <button class="secondary" onclick="bulkToggleLlmKeys(false)">Выключить выбранные</button>
            <button class="secondary" onclick="bulkDeleteLlmKeys()">Удалить выбранные</button>
          </div>
          <div id="llmKeysInactive" class="muted">Загрузка...</div>
        </div>
      </section>
      <section data-panel="orders">
        <h2>Заказы</h2>
        <div class="row table-controls">
          <input id="ordersSearch" class="table-search" type="text" placeholder="Поиск по любому столбцу" />
          <button class="secondary" onclick="clearTableFilters('orders')">Сбросить</button>
          <button class="secondary" onclick="loadOrders()">Обновить</button>
        </div>
        <div class="bulk-actions">
          <button class="secondary" onclick="bulkMarkOrders('paid')">Отметить выбранные как оплаченные</button>
          <button class="secondary" onclick="bulkMarkOrders('completed')">Отметить выбранные как исполненные</button>
          <button class="secondary danger" onclick="bulkDeleteOrders()">Удалить выбранные</button>
        </div>
        <div id="orders" class="muted">Загрузка...</div>
      </section>
      <section data-panel="reports">
        <h2>Отчёты</h2>
        <div class="row table-controls">
          <input id="reportsSearch" class="table-search" type="text" placeholder="Поиск по любому столбцу" />
          <button class="secondary" onclick="clearTableFilters('reports')">Сбросить</button>
          <button class="secondary" onclick="loadReports()">Обновить</button>
        </div>
        <div id="reports" class="muted">Загрузка...</div>
      </section>
      <section data-panel="users">
        <h2>Пользователи</h2>
        <div class="row table-controls">
          <input id="usersSearch" class="table-search" type="text" placeholder="Поиск по любому столбцу" />
          <button class="secondary" onclick="clearTableFilters('users')">Сбросить</button>
          <button class="secondary" onclick="loadUsers()">Обновить</button>
        </div>
        <div id="users" class="muted">Загрузка...</div>
      </section>
      <section data-panel="feedback-inbox">
        <h2>Обратная связь</h2>
        <div class="tabs">
          <button class="tab-button active" data-feedback-tab="current">Текущие</button>
          <button class="tab-button" data-feedback-tab="archive">Архив</button>
        </div>
        <div class="tab-panel active" data-feedback-panel="current">
          <div class="row table-controls">
            <input id="feedbackInboxSearch" class="table-search" type="text" placeholder="Поиск по текущим обращениям" />
            <button class="secondary" onclick="clearTableFilters('feedbackInbox')">Сбросить</button>
            <button class="secondary" onclick="loadFeedbackInbox()">Обновить</button>
          </div>
          <div class="bulk-actions">
            <button class="secondary" onclick="bulkArchiveFeedback(false)">Архивировать выбранные</button>
          </div>
          <div id="feedbackInbox" class="muted">Загрузка...</div>
        </div>
        <div class="tab-panel" data-feedback-panel="archive">
          <div class="row table-controls">
            <input id="feedbackArchiveSearch" class="table-search" type="text" placeholder="Поиск по архиву" />
            <button class="secondary" onclick="clearTableFilters('feedbackArchive')">Сбросить</button>
            <button class="secondary" onclick="loadFeedbackArchive()">Обновить</button>
          </div>
          <div class="bulk-actions">
            <button class="secondary" onclick="bulkArchiveFeedback(true)">Вернуть выбранные в текущие</button>
          </div>
          <div id="feedbackArchive" class="muted">Загрузка...</div>
        </div>
        <div id="feedbackThreadViewer" class="thread-history" style="display: none;">
          <div class="thread-history-header">
            <strong id="feedbackThreadTitle">История треда</strong>
            <div class="row" style="margin: 0;">
              <button class="secondary" onclick="refreshFeedbackThread()">Обновить</button>
              <button class="secondary" onclick="closeFeedbackThread()">Закрыть</button>
            </div>
          </div>
          <div id="feedbackThreadBody" class="thread-history-list muted">Выберите обращение и нажмите «История треда».</div>
        </div>
      </section>
      <section data-panel="analytics">
        <h2>Analytics: переходы и воронка</h2>
        <div class="analytics-filters">
          <div class="field">
            <label for="analyticsFrom">Период c</label>
            <input id="analyticsFrom" type="datetime-local" />
          </div>
          <div class="field">
            <label for="analyticsTo">Период по</label>
            <input id="analyticsTo" type="datetime-local" />
          </div>
          <div class="field">
            <label for="analyticsTariff">Тариф</label>
            <select id="analyticsTariff">
              <option value="">Все</option>
              <option value="T0">T0</option>
              <option value="T1">T1</option>
              <option value="T2">T2</option>
              <option value="T3">T3</option>
            </select>
          </div>
          <div class="field">
            <label for="analyticsDropoffWindow">Drop-off окно, мин</label>
            <input id="analyticsDropoffWindow" type="number" min="1" max="1440" value="60" />
          </div>
          <div class="field">
            <label for="analyticsTopN">Top N</label>
            <input id="analyticsTopN" type="number" min="3" max="500" value="50" />
          </div>
          <div class="field" style="justify-content: flex-end;">
            <label>&nbsp;</label>
            <button class="secondary" onclick="loadAnalytics()">Обновить аналитику</button>
          </div>
        </div>
        <div id="analyticsState" class="analytics-state">Загрузка...</div>
        <div id="analyticsKpi" class="kpi-grid"></div>
        <div class="analytics-block">
          <div class="analytics-title">Воронка по шагам</div>
          <div id="analyticsFunnel" class="muted">Нет данных</div>
        </div>
        <div class="analytics-block">
          <div class="analytics-title">Матрица переходов</div>
          <div id="analyticsMatrix" class="muted">Нет данных</div>
        </div>
        <div class="analytics-block">
          <div class="analytics-title">Узкие места (высокий отвал / долгое время)</div>
          <div id="analyticsBottlenecks" class="muted">Нет данных</div>
        </div>
      </section>
      <section data-panel="system-prompts">
        <h2>Системные промпты</h2>
        <div class="muted">
          Промпты из админки имеют приоритет. При наличии хотя бы одного промпта
          в базе файл <code>.env.prompts</code> игнорируется.
        </div>
        <div class="row" style="margin-top: 12px; align-items: flex-end;">
          <div class="field" style="min-width: 220px;">
            <label for="promptKeySelect">Ключ промпта</label>
            <select id="promptKeySelect">
              <option value="PROMPT_T0">PROMPT_T0</option>
              <option value="PROMPT_T1">PROMPT_T1</option>
              <option value="PROMPT_T2">PROMPT_T2</option>
              <option value="PROMPT_T3">PROMPT_T3</option>
              <option value="CUSTOM">Свой ключ</option>
            </select>
            <input id="promptKeyCustom" type="text" placeholder="Введите свой ключ" style="margin-top: 6px; display: none;" />
          </div>
          <div class="field" style="flex: 1 1 320px;">
            <label for="promptContent">Текст промпта</label>
            <textarea id="promptContent" placeholder="Введите системный промпт"></textarea>
            <div id="promptDangerZone" class="prompt-danger-zone safe">
              <div class="prompt-danger-zone-title">Опасные зоны не найдены</div>
              <div class="muted">Подсветка выполняется автоматически при вводе, редактировании и после сохранения.</div>
            </div>
          </div>
          <div class="field">
            <button onclick="saveSystemPrompt()">Сохранить</button>
            <button class="secondary" style="margin-top: 6px;" onclick="resetSystemPromptForm()">Очистить</button>
          </div>
        </div>
        <div class="row table-controls">
          <input id="systemPromptsSearch" class="table-search" type="text" placeholder="Поиск по ключу и тексту" />
          <button class="secondary" onclick="clearTableFilters('systemPrompts')">Сбросить</button>
          <button class="secondary" onclick="loadSystemPrompts()">Обновить</button>
        </div>
        <div class="bulk-actions">
          <button class="secondary" onclick="bulkDeleteSystemPrompts()">Удалить выбранные промпты</button>
        </div>
        <div id="systemPrompts" class="muted">Загрузка...</div>
      </section>
      <section data-panel="notes">
        <h2>Админ-заметки</h2>
        <div class="row">
          <textarea id="noteInput" placeholder="Введите заметку или JSON-объект"></textarea>
          <button onclick="createNote()">Добавить</button>
        </div>
        <div class="row table-controls">
          <input id="notesSearch" class="table-search" type="text" placeholder="Поиск по любому столбцу" />
          <button class="secondary" onclick="clearTableFilters('notes')">Сбросить</button>
          <button class="secondary" onclick="loadNotes()">Обновить</button>
        </div>
        <div class="bulk-actions">
          <button class="secondary" onclick="bulkDeleteNotes()">Удалить выбранные заметки</button>
        </div>
        <div id="notes" class="muted">Загрузка...</div>
      </section>
    </div>
  </main>
  <div id="copyToast" class="copy-toast">Скопировано в буфер обмена</div>
  <script>
    document.body.classList.add("js-ready");
    const autoRefreshSeconds = Number("__ADMIN_AUTO_REFRESH_SECONDS__") || 0;
    async function logout() {
      await fetch("/admin/logout", { method: "POST" });
      window.location.reload();
    }

    async function fetchJson(path, options = {}) {
      const response = await fetch(`/admin/api${path}`, {
        ...options,
        headers: {
          "Content-Type": "application/json",
          ...(options.headers || {})
        }
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(data.detail || "Ошибка запроса");
      }
      return data;
    }

    async function fetchForm(path, formData, options = {}) {
      const response = await fetch(`/admin/api${path}`, {
        ...options,
        method: options.method || "POST",
        body: formData,
        headers: {
          ...(options.headers || {})
        }
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(data.detail || "Ошибка запроса");
      }
      return data;
    }

    function renderKeyValue(targetId, data) {
      const target = document.getElementById(targetId);
      const rows = Object.entries(data).map(([key, value]) => {
        return `<div><strong>${key}</strong>: ${value}</div>`;
      });
      target.innerHTML = rows.join("") || "Нет данных";
    }

    async function loadOverview() {
      try {
        const data = await fetchJson("/overview");
        renderKeyValue("overview", data);
      } catch (error) {
        document.getElementById("overview").textContent = error.message;
      }
    }

    async function loadHealth() {
      try {
        const data = await fetchJson("/health");
        const status = data.database_ok ? "ok" : "bad";
        document.getElementById("health").innerHTML = `
          <div class="status ${status}">База данных: ${data.database_ok ? "OK" : "ошибка"}</div>
          <div class="message">ENV: ${data.env} • Админ-доступ: ${data.admin_auth_enabled}</div>
          <div class="message">Последняя проверка: ${data.checked_at}</div>
        `;
      } catch (error) {
        document.getElementById("health").textContent = error.message;
      }
    }

    async function loadLlmKeys() {
      try {
        const data = await fetchJson("/llm-keys?limit=0");
        tableData.llmKeysAll = data.keys || [];
        tableData.llmKeysActive = tableData.llmKeysAll.filter((row) => row.is_active);
        tableData.llmKeysInactive = tableData.llmKeysAll.filter((row) => !row.is_active);
        renderTableForKey("llmKeysActive");
        renderTableForKey("llmKeysInactive");
      } catch (error) {
        document.getElementById("llmKeysActive").textContent = error.message;
        document.getElementById("llmKeysInactive").textContent = error.message;
      }
    }

    let llmKeyEditingId = null;

    function resetLlmKeyForm() {
      llmKeyEditingId = null;
      document.getElementById("llmProviderSelect").value = "";
      document.getElementById("llmProviderInput").value = "";
      document.getElementById("llmKeyInput").value = "";
      document.getElementById("llmPriorityInput").value = "";
      document.getElementById("llmActiveInput").value = "true";
      syncLlmProviderInput();
    }

    function editLlmKey(keyId) {
      const record = (tableData.llmKeysAll || []).find((item) => item.id === keyId);
      if (!record) {
        return;
      }
      llmKeyEditingId = record.id;
      const providerValue = normalizeValue(record.provider);
      const providerSelect = document.getElementById("llmProviderSelect");
      const providerLower = providerValue.toLowerCase();
      if (providerLower === "gemini" || providerLower === "openai") {
        providerSelect.value = providerLower;
        document.getElementById("llmProviderInput").value = "";
      } else {
        providerSelect.value = "custom";
        document.getElementById("llmProviderInput").value = providerValue;
      }
      document.getElementById("llmKeyInput").value = "";
      document.getElementById("llmPriorityInput").value = normalizeValue(record.priority);
      document.getElementById("llmActiveInput").value = record.is_active ? "true" : "false";
      syncLlmProviderInput();
      showPanel("llm-keys");
    }

    function syncLlmProviderInput() {
      const selectValue = document.getElementById("llmProviderSelect").value;
      const input = document.getElementById("llmProviderInput");
      const isCustom = selectValue === "custom" || selectValue === "";
      input.disabled = !isCustom;
      input.style.opacity = isCustom ? "1" : "0.6";
      if (!isCustom) {
        input.value = "";
      }
    }

    function getLlmProviderValue() {
      const selectValue = document.getElementById("llmProviderSelect").value;
      if (selectValue && selectValue !== "custom") {
        return selectValue;
      }
      return document.getElementById("llmProviderInput").value;
    }

    function syncLlmBulkProviderInput() {
      const selectValue = document.getElementById("llmBulkProviderSelect").value;
      const input = document.getElementById("llmBulkProviderInput");
      const isCustom = selectValue === "custom" || selectValue === "";
      input.disabled = !isCustom;
      input.style.opacity = isCustom ? "1" : "0.6";
      if (!isCustom) {
        input.value = "";
      }
    }

    function getLlmBulkProviderValue() {
      const selectValue = document.getElementById("llmBulkProviderSelect").value;
      if (selectValue && selectValue !== "custom") {
        return selectValue;
      }
      return document.getElementById("llmBulkProviderInput").value;
    }

    async function saveLlmKey() {
      const provider = getLlmProviderValue();
      const key = document.getElementById("llmKeyInput").value;
      const priority = document.getElementById("llmPriorityInput").value;
      const is_active = document.getElementById("llmActiveInput").value;
      const payload = {provider, key, priority, is_active};
      try {
        if (llmKeyEditingId) {
          await fetchJson(`/llm-keys/${llmKeyEditingId}`, {
            method: "PATCH",
            body: JSON.stringify(payload)
          });
        } else {
          await fetchJson("/llm-keys", {
            method: "POST",
            body: JSON.stringify(payload)
          });
        }
        resetLlmKeyForm();
        await loadLlmKeys();
      } catch (error) {
        alert(error.message);
      }
    }

    async function uploadLlmKeysBulk() {
      const fileInput = document.getElementById("llmBulkFile");
      const file = fileInput.files && fileInput.files[0];
      if (!file) {
        alert("Выберите файл с ключами.");
        return;
      }
      const formData = new FormData();
      formData.append("file", file);
      formData.append("provider", getLlmBulkProviderValue());
      try {
        const result = await fetchForm("/llm-keys/bulk", formData);
        fileInput.value = "";
        await loadLlmKeys();
        alert(`Загружено строк: ${result.lines || 0}. Создано ключей: ${result.created || 0}.`);
      } catch (error) {
        alert(error.message);
      }
    }

    async function toggleLlmKey(keyId, nextState) {
      try {
        await fetchJson(`/llm-keys/${keyId}`, {
          method: "PATCH",
          body: JSON.stringify({is_active: nextState})
        });
        await loadLlmKeys();
      } catch (error) {
        alert(error.message);
      }
    }

    async function bulkToggleLlmKeys(nextState) {
      const ids = getSelectedIds("llmKeysActive").concat(getSelectedIds("llmKeysInactive"));
      if (!ids.length) {
        alert("Выберите хотя бы одну строку.");
        return;
      }
      try {
        await fetchJson("/llm-keys/bulk-update", {
          method: "POST",
          body: JSON.stringify({ids, is_active: nextState})
        });
        selectedRows.llmKeysActive.clear();
        selectedRows.llmKeysInactive.clear();
        await loadLlmKeys();
      } catch (error) {
        alert(error.message);
      }
    }

    async function bulkDeleteLlmKeys() {
      const ids = getSelectedIds("llmKeysActive").concat(getSelectedIds("llmKeysInactive"));
      if (!ids.length) {
        alert("Выберите хотя бы одну строку.");
        return;
      }
      if (!confirm(`Удалить выбранные ключи: ${ids.length} шт.?`)) {
        return;
      }
      try {
        await fetchJson("/llm-keys/bulk-delete", {
          method: "POST",
          body: JSON.stringify({ids})
        });
        selectedRows.llmKeysActive.clear();
        selectedRows.llmKeysInactive.clear();
        await loadLlmKeys();
      } catch (error) {
        alert(error.message);
      }
    }

    const tableData = {
      llmKeysAll: [],
      llmKeysActive: [],
      llmKeysInactive: [],
      orders: [],
      reports: [],
      users: [],
      feedbackInbox: [],
      feedbackArchive: [],
      systemPrompts: [],
      notes: [],
    };

    const tableStates = {
      llmKeysActive: {search: "", sortKey: null, sortDir: "asc"},
      llmKeysInactive: {search: "", sortKey: null, sortDir: "asc"},
      orders: {search: "", sortKey: null, sortDir: "asc"},
      reports: {search: "", sortKey: null, sortDir: "asc"},
      users: {search: "", sortKey: null, sortDir: "asc"},
      feedbackInbox: {search: "", sortKey: null, sortDir: "asc"},
      feedbackArchive: {search: "", sortKey: null, sortDir: "asc"},
      systemPrompts: {search: "", sortKey: null, sortDir: "asc"},
      notes: {search: "", sortKey: null, sortDir: "asc"},
    };
    const selectedRows = {
      llmKeysActive: new Set(),
      llmKeysInactive: new Set(),
      orders: new Set(),
      reports: new Set(),
      users: new Set(),
      feedbackInbox: new Set(),
      feedbackArchive: new Set(),
      systemPrompts: new Set(),
      notes: new Set(),
    };
    let currentFeedbackThreadId = null;


    const tableConfigs = {
      llmKeysActive: {
        targetId: "llmKeysActive",
        columns: [
          {label: "ID", key: "id", sortable: true},
          {label: "Провайдер", key: "provider", sortable: true},
          {label: "Приоритет", key: "priority", sortable: true},
          {label: "Активен", key: "is_active", sortable: true, render: (row) => row.is_active ? "Да" : "Нет"},
          {
            label: "В отключке",
            key: "disabled_at",
            sortable: true,
            sortValue: (row) => {
              const durationMs = getDisabledDurationMs(row);
              return durationMs === null ? -1 : durationMs;
            },
            searchValue: (row) => renderDisabledDuration(row),
            render: (row) => renderDisabledDuration(row),
          },
          {label: "Ключ", key: "masked_key", sortable: true},
          {label: "Последнее использование", key: "last_used_at", sortable: true},
          {label: "Последний успех", key: "last_success_at", sortable: true},
          {label: "Статус", key: "last_status_code", sortable: true},
          {label: "Успехи", key: "success_count", sortable: true},
          {label: "Ошибки", key: "failure_count", sortable: true},
          {label: "Ошибка", key: "last_error", sortable: true},
          {
            label: "Действия",
            key: null,
            sortable: false,
            copyable: false,
            render: (row) => `
              <button class="secondary" onclick="editLlmKey(${row.id})">Изменить</button>
              <button class="secondary" onclick="toggleLlmKey(${row.id}, ${row.is_active ? "false" : "true"})">
                ${row.is_active ? "Выключить" : "Включить"}
              </button>
              <button class="secondary" onclick="deleteLlmKey(${row.id})">Удалить</button>
            `,
          },
        ],
      },
      llmKeysInactive: {
        targetId: "llmKeysInactive",
        columns: [
          {label: "ID", key: "id", sortable: true},
          {label: "Провайдер", key: "provider", sortable: true},
          {label: "Приоритет", key: "priority", sortable: true},
          {label: "Активен", key: "is_active", sortable: true, render: (row) => row.is_active ? "Да" : "Нет"},
          {
            label: "В отключке",
            key: "disabled_at",
            sortable: true,
            sortValue: (row) => {
              const durationMs = getDisabledDurationMs(row);
              return durationMs === null ? -1 : durationMs;
            },
            searchValue: (row) => renderDisabledDuration(row),
            render: (row) => renderDisabledDuration(row),
          },
          {label: "Ключ", key: "masked_key", sortable: true},
          {label: "Последнее использование", key: "last_used_at", sortable: true},
          {label: "Последний успех", key: "last_success_at", sortable: true},
          {label: "Статус", key: "last_status_code", sortable: true},
          {label: "Успехи", key: "success_count", sortable: true},
          {label: "Ошибки", key: "failure_count", sortable: true},
          {label: "Ошибка", key: "last_error", sortable: true},
          {
            label: "Действия",
            key: null,
            sortable: false,
            copyable: false,
            render: (row) => `
              <button class="secondary" onclick="editLlmKey(${row.id})">Изменить</button>
              <button class="secondary" onclick="toggleLlmKey(${row.id}, ${row.is_active ? "false" : "true"})">
                ${row.is_active ? "Выключить" : "Включить"}
              </button>
              <button class="secondary" onclick="deleteLlmKey(${row.id})">Удалить</button>
            `,
          },
        ],
      },
      orders: {
        targetId: "orders",
        columns: [
          {label: "ID", key: "id", sortable: true},
          {label: "Пользователь", key: "telegram_user_id", sortable: true},
          {label: "Тариф", key: "tariff", sortable: true},
          {label: "Статус", key: "status", sortable: true},
          {label: "Выполнение", key: "fulfillment_status", sortable: true},
          {label: "Отчёт #", key: "report_id", sortable: true},
          {
            label: "Сумма",
            key: "amount",
            sortable: true,
            sortValue: (order) => order.amount,
            render: (order) => `${normalizeValue(order.amount)} ${normalizeValue(order.currency)}`.trim(),
          },
          {label: "Действия", key: null, sortable: false, copyable: false, render: (order) => `
            <button class="secondary" onclick="markOrder(${order.id}, 'paid')">Оплачен</button>
            <button class="secondary" onclick="markOrder(${order.id}, 'completed')">Исполнен</button>
          `},
        ],
      },
      reports: {
        targetId: "reports",
        columns: [
          {label: "ID", key: "id", sortable: true},
          {label: "Пользователь", key: "telegram_user_id", sortable: true},
          {label: "Тариф", key: "tariff", sortable: true},
          {label: "Создан", key: "created_at", sortable: true},
          {label: "Модель", key: "model_used", sortable: true},
        ],
      },
      users: {
        targetId: "users",
        columns: [
          {label: "ID", key: "id", sortable: true},
          {label: "Telegram", key: "telegram_user_id", sortable: true},
          {label: "Имя", key: "name", sortable: true},
          {label: "Дата рождения", key: "birth_date", sortable: true},
        ],
      },
      feedbackInbox: {
        targetId: "feedbackInbox",
        columns: [
          {label: "Тред", key: "thread_feedback_id", sortable: true},
          {label: "Пользователь", key: "telegram_user_id", sortable: true},
          {label: "User ID", key: "user_id", sortable: true},
          {label: "Сообщений", key: "message_count", sortable: true},
          {label: "Последний статус", key: "status", sortable: true},
          {label: "Последнее сообщение", key: "text", sortable: true},
          {label: "Последняя активность", key: "sent_at", sortable: true},
          {label: "Ответ админа", key: "admin_reply", sortable: true},
          {label: "Ответ отправлен", key: "replied_at", sortable: true},
          {
            label: "Действия",
            key: null,
            sortable: false,
            copyable: false,
            render: (row) => `
              <button class="secondary" onclick="replyToFeedback(${row.last_feedback_id || row.thread_feedback_id || row.id})">Ответить</button>
              <button class="secondary" onclick="showFeedbackThread(${row.thread_feedback_id || row.id})">История треда</button>
              <button class="secondary" onclick="toggleFeedbackArchive(${row.id}, true)">В архив</button>
            `,
          },
        ],
      },
      feedbackArchive: {
        targetId: "feedbackArchive",
        columns: [
          {label: "Тред", key: "thread_feedback_id", sortable: true},
          {label: "Пользователь", key: "telegram_user_id", sortable: true},
          {label: "User ID", key: "user_id", sortable: true},
          {label: "Сообщений", key: "message_count", sortable: true},
          {label: "Последний статус", key: "status", sortable: true},
          {label: "Последнее сообщение", key: "text", sortable: true},
          {label: "Последняя активность", key: "sent_at", sortable: true},
          {label: "Ответ админа", key: "admin_reply", sortable: true},
          {label: "Ответ отправлен", key: "replied_at", sortable: true},
          {label: "Архивировано", key: "archived_at", sortable: true},
          {
            label: "Действия",
            key: null,
            sortable: false,
            copyable: false,
            render: (row) => `
              <button class="secondary" onclick="replyToFeedback(${row.last_feedback_id || row.thread_feedback_id || row.id})">Ответить</button>
              <button class="secondary" onclick="showFeedbackThread(${row.thread_feedback_id || row.id})">История треда</button>
              <button class="secondary" onclick="toggleFeedbackArchive(${row.id}, false)">В текущие</button>
            `,
          },
        ],
      },
      systemPrompts: {
        targetId: "systemPrompts",
        columns: [
          {label: "ID", key: "id", sortable: true},
          {label: "Ключ", key: "key", sortable: true},
          {label: "Обновлено", key: "updated_at", sortable: true},
          {
            label: "Промпт",
            key: "content",
            sortable: true,
            render: (prompt) => `<pre class="muted prompt-preview">${normalizeValue(prompt.content)}</pre>`,
          },
          {
            label: "Действия",
            key: null,
            sortable: false,
            copyable: false,
            render: (prompt) => `
              <button class="secondary" onclick="editSystemPrompt(${prompt.id})">Изменить</button>
              <button class="secondary" onclick="deleteSystemPrompt(${prompt.id})">Удалить</button>
            `,
          },
        ],
      },
      notes: {
        targetId: "notes",
        columns: [
          {label: "ID", key: "id", sortable: true},
          {label: "Создано", key: "created_at", sortable: true},
          {label: "Содержимое", key: "payload", sortable: true, render: (note) => `
            <pre class="muted">${note.payload}</pre>
          `},
        ],
      },
    };

    function normalizeValue(value) {
      if (value === null || value === undefined) {
        return "";
      }
      return String(value);
    }

    function parseDate(value) {
      if (!value) {
        return null;
      }
      const date = new Date(value);
      if (Number.isNaN(date.getTime())) {
        return null;
      }
      return date;
    }

    function formatDuration(ms) {
      if (ms <= 0) {
        return "только что";
      }
      const totalMinutes = Math.floor(ms / 60000);
      const days = Math.floor(totalMinutes / 1440);
      const hours = Math.floor((totalMinutes % 1440) / 60);
      const minutes = totalMinutes % 60;
      const parts = [];
      if (days) {
        parts.push(`${days}д`);
      }
      if (hours) {
        parts.push(`${hours}ч`);
      }
      if (minutes || !parts.length) {
        parts.push(`${minutes}м`);
      }
      return parts.join(" ");
    }

    function getDisabledDurationMs(row) {
      if (row.is_active) {
        return null;
      }
      const disabledAt = row.disabled_at || row.updated_at;
      const disabledDate = parseDate(disabledAt);
      if (!disabledDate) {
        return null;
      }
      return Date.now() - disabledDate.getTime();
    }

    function renderDisabledDuration(row) {
      const durationMs = getDisabledDurationMs(row);
      if (durationMs === null) {
        return "—";
      }
      return formatDuration(durationMs);
    }

    function compareValues(aValue, bValue) {
      const aText = normalizeValue(aValue);
      const bText = normalizeValue(bValue);
      const aNumber = Number(aText);
      const bNumber = Number(bText);
      if (!Number.isNaN(aNumber) && !Number.isNaN(bNumber) && aText.trim() !== "" && bText.trim() !== "") {
        return aNumber - bNumber;
      }
      return aText.localeCompare(bText, "ru", {numeric: true, sensitivity: "base"});
    }

    function rowIdentifier(row) {
      if (row && row.id !== undefined && row.id !== null) {
        return String(row.id);
      }
      return "";
    }

    function toggleRowSelection(tableKey, rowId, checked) {
      const selected = selectedRows[tableKey];
      if (!selected) {
        return;
      }
      if (checked) {
        selected.add(String(rowId));
      } else {
        selected.delete(String(rowId));
      }
    }

    function toggleSelectAll(tableKey, checked) {
      const config = tableConfigs[tableKey];
      if (!config) {
        return;
      }
      const selected = selectedRows[tableKey];
      selected.clear();
      if (checked) {
        (tableData[tableKey] || []).forEach((row) => {
          const rowId = rowIdentifier(row);
          if (rowId) {
            selected.add(rowId);
          }
        });
      }
      renderTableForKey(tableKey);
    }

    function getSelectedIds(tableKey) {
      return Array.from(selectedRows[tableKey] || []);
    }

    function clearSelection(tableKey) {
      const selected = selectedRows[tableKey];
      if (!selected) {
        return;
      }
      selected.clear();
      renderTableForKey(tableKey);
    }

    function collectSearchableText(columns, row) {
      const parts = columns.map((column) => {
        if (column.searchValue) {
          return normalizeValue(column.searchValue(row));
        }
        if (column.key) {
          return normalizeValue(row[column.key]);
        }
        return "";
      });
      return parts.join(" ").toLowerCase();
    }

    function renderTableForKey(tableKey) {
      const config = tableConfigs[tableKey];
      const target = document.getElementById(config.targetId);
      const rows = tableData[tableKey] || [];
      const state = tableStates[tableKey];
      const searchTerm = state.search.trim().toLowerCase();
      let filteredRows = rows;
      if (searchTerm) {
        filteredRows = rows.filter((row) => collectSearchableText(config.columns, row).includes(searchTerm));
      }
      if (state.sortKey) {
        const column = config.columns.find((col) => col.key === state.sortKey);
        if (column) {
          filteredRows = [...filteredRows].sort((a, b) => {
            const valueA = column.sortValue ? column.sortValue(a) : a[state.sortKey];
            const valueB = column.sortValue ? column.sortValue(b) : b[state.sortKey];
            const result = compareValues(valueA, valueB);
            return state.sortDir === "asc" ? result : -result;
          });
        }
      }
      if (!filteredRows.length) {
        target.textContent = "Нет данных";
        return;
      }
      const selected = selectedRows[tableKey] || new Set();
      const selectableRows = filteredRows.filter((row) => rowIdentifier(row));
      const allSelected = selectableRows.length > 0 && selectableRows.every((row) => selected.has(rowIdentifier(row)));
      const headerCells = config.columns.map((column) => {
        const sortable = column.sortable && column.key;
        const isActive = sortable && state.sortKey === column.key;
        const indicator = isActive ? (state.sortDir === "asc" ? "▲" : "▼") : "⇅";
        if (sortable) {
          return `
            <th class="sortable" onclick="toggleSort('${tableKey}', '${column.key}')">
              ${column.label}
              <span class="sort-indicator">${indicator}</span>
            </th>
          `;
        }
        return `<th>${column.label}</th>`;
      }).join("");
      const header = `<th class="select-col"><input type="checkbox" class="select-all-checkbox" ${allSelected ? "checked" : ""} onchange="toggleSelectAll('${tableKey}', this.checked)" /></th>${headerCells}`;
      const body = filteredRows.map((row) => {
        const cells = config.columns.map((column) => {
          const cellValue = column.render
            ? column.render(row)
            : normalizeValue(row[column.key] ?? "—");
          const isCopyable = column.copyable !== false;
          const cellClass = isCopyable ? "copyable-cell" : "";
          if (isCopyable) {
            return `<td class="${cellClass}"><div class="cell-content">${cellValue || "—"}</div></td>`;
          }
          return `<td class="${cellClass}">${cellValue || "—"}</td>`;
        }).join("");
        const rowId = rowIdentifier(row);
        const checked = rowId && selected.has(rowId) ? "checked" : "";
        const selectCell = `<td class="select-col"><input type="checkbox" class="row-checkbox" ${checked} onchange="toggleRowSelection('${tableKey}', '${rowId}', this.checked)" /></td>`;
        return `<tr>${selectCell}${cells}</tr>`;
      }).join("");
      target.innerHTML = `<table><thead><tr>${header}</tr></thead><tbody>${body}</tbody></table>`;
    }

    const copyToast = document.getElementById("copyToast");
    let copyToastTimer = null;

    function showCopyToast() {
      if (!copyToast) {
        return;
      }
      copyToast.classList.add("visible");
      if (copyToastTimer) {
        clearTimeout(copyToastTimer);
      }
      copyToastTimer = setTimeout(() => {
        copyToast.classList.remove("visible");
      }, 1400);
    }

    async function copyTextToClipboard(text) {
      if (text === undefined || text === null) {
        return false;
      }
      const value = String(text);
      if (navigator.clipboard && window.isSecureContext) {
        try {
          await navigator.clipboard.writeText(value);
          return true;
        } catch (error) {
          return false;
        }
      }
      const textarea = document.createElement("textarea");
      textarea.value = value;
      textarea.style.position = "fixed";
      textarea.style.top = "-9999px";
      textarea.setAttribute("readonly", "");
      document.body.appendChild(textarea);
      textarea.select();
      let copied = false;
      try {
        copied = document.execCommand("copy");
      } catch (error) {
        copied = false;
      }
      document.body.removeChild(textarea);
      return copied;
    }

    document.addEventListener("click", async (event) => {
      const target = event.target;
      if (!(target instanceof Element)) {
        return;
      }
      if (target.closest("button, a, input, select, textarea, label")) {
        return;
      }
      const cell = target.closest("td.copyable-cell");
      if (!cell) {
        return;
      }
      const text = cell.textContent;
      const copied = await copyTextToClipboard(text);
      if (copied) {
        showCopyToast();
      }
    });

    function toggleSort(tableKey, columnKey) {
      const state = tableStates[tableKey];
      if (state.sortKey === columnKey) {
        state.sortDir = state.sortDir === "asc" ? "desc" : "asc";
      } else {
        state.sortKey = columnKey;
        state.sortDir = "asc";
      }
      renderTableForKey(tableKey);
    }

    function clearTableFilters(tableKey) {
      tableStates[tableKey] = {search: "", sortKey: null, sortDir: "asc"};
      const input = document.getElementById(`${tableKey}Search`);
      if (input) {
        input.value = "";
      }
      renderTableForKey(tableKey);
    }

    async function loadOrders() {
      try {
        const data = await fetchJson("/orders");
        tableData.orders = data.orders || [];
        renderTableForKey("orders");
      } catch (error) {
        document.getElementById("orders").textContent = error.message;
      }
    }

    async function markOrder(orderId, status) {
      try {
        await fetchJson(`/orders/${orderId}/status`, {
          method: "POST",
          body: JSON.stringify({status})
        });
        await loadOrders();
      } catch (error) {
        alert(error.message);
      }
    }

    async function bulkMarkOrders(status) {
      const ids = getSelectedIds("orders");
      if (!ids.length) {
        alert("Выберите хотя бы один заказ.");
        return;
      }
      try {
        await fetchJson("/orders/bulk-status", {
          method: "POST",
          body: JSON.stringify({ids, status})
        });
        selectedRows.orders.clear();
        await loadOrders();
      } catch (error) {
        alert(error.message);
      }
    }

    async function bulkDeleteOrders() {
      const ids = getSelectedIds("orders");
      if (!ids.length) {
        alert("Выберите хотя бы один заказ.");
        return;
      }
      const confirmed = confirm(`Удалить выбранные заказы (${ids.length})?`);
      if (!confirmed) {
        return;
      }
      try {
        await fetchJson("/orders/bulk-delete", {
          method: "POST",
          body: JSON.stringify({ids})
        });
        selectedRows.orders.clear();
        await loadOrders();
        await loadOverview();
      } catch (error) {
        alert(error.message);
      }
    }

    async function loadReports() {
      try {
        const data = await fetchJson("/reports");
        tableData.reports = data.reports || [];
        renderTableForKey("reports");
      } catch (error) {
        document.getElementById("reports").textContent = error.message;
      }
    }

    async function loadUsers() {
      try {
        const data = await fetchJson("/users");
        tableData.users = data.users || [];
        renderTableForKey("users");
      } catch (error) {
        document.getElementById("users").textContent = error.message;
      }
    }

    async function loadFeedbackInbox() {
      try {
        const data = await fetchJson("/feedback/inbox");
        tableData.feedbackInbox = data.feedback || [];
        renderTableForKey("feedbackInbox");
      } catch (error) {
        document.getElementById("feedbackInbox").textContent = error.message;
      }
    }

    async function loadFeedbackArchive() {
      try {
        const data = await fetchJson("/feedback/archive");
        tableData.feedbackArchive = data.feedback || [];
        renderTableForKey("feedbackArchive");
      } catch (error) {
        document.getElementById("feedbackArchive").textContent = error.message;
      }
    }

    async function toggleFeedbackArchive(feedbackId, archive) {
      try {
        await fetchJson(`/feedback/${feedbackId}/archive`, {
          method: "POST",
          body: JSON.stringify({archive})
        });
        await loadFeedbackInbox();
        await loadFeedbackArchive();
      } catch (error) {
        alert(error.message);
      }
    }

    function closeFeedbackThread() {
      currentFeedbackThreadId = null;
      const viewer = document.getElementById("feedbackThreadViewer");
      const body = document.getElementById("feedbackThreadBody");
      const title = document.getElementById("feedbackThreadTitle");
      if (viewer) {
        viewer.style.display = "none";
      }
      if (body) {
        body.className = "thread-history-list muted";
        body.textContent = "Выберите обращение и нажмите «История треда».";
      }
      if (title) {
        title.textContent = "История треда";
      }
    }

    function renderFeedbackThread(messages) {
      const body = document.getElementById("feedbackThreadBody");
      if (!body) {
        return;
      }
      if (!Array.isArray(messages) || !messages.length) {
        body.className = "thread-history-list muted";
        body.textContent = "Сообщения в этом треде пока не найдены.";
        return;
      }
      body.className = "thread-history-list";
      body.innerHTML = messages.map((item) => {
        const direction = item.direction === "admin" ? "admin" : "user";
        const label = direction === "admin" ? "Поддержка" : "Пользователь";
        const createdAt = normalizeValue(item.created_at || item.sent_at || "—");
        const delivered = item.delivered === false ? " • не доставлено" : "";
        return `
          <div class="thread-history-item ${direction}">
            <div class="thread-history-meta">${label} • ${createdAt}${delivered}</div>
            <div>${normalizeValue(item.text)}</div>
          </div>
        `;
      }).join("");
    }

    async function showFeedbackThread(threadFeedbackId) {
      const normalizedId = Number(threadFeedbackId);
      if (!Number.isInteger(normalizedId) || normalizedId <= 0) {
        alert("Некорректный идентификатор треда.");
        return;
      }
      currentFeedbackThreadId = normalizedId;
      const viewer = document.getElementById("feedbackThreadViewer");
      const title = document.getElementById("feedbackThreadTitle");
      const body = document.getElementById("feedbackThreadBody");
      if (viewer) {
        viewer.style.display = "block";
      }
      if (title) {
        title.textContent = `История треда #${normalizedId}`;
      }
      if (body) {
        body.className = "thread-history-list muted";
        body.textContent = "Загрузка...";
      }
      try {
        const data = await fetchJson(`/feedback/thread/${normalizedId}`);
        renderFeedbackThread(data.messages || []);
      } catch (error) {
        if (body) {
          body.className = "thread-history-list muted";
          body.textContent = error.message;
        }
      }
    }

    async function refreshFeedbackThread() {
      if (!currentFeedbackThreadId) {
        alert("Сначала выберите тред.");
        return;
      }
      await showFeedbackThread(currentFeedbackThreadId);
    }

    async function replyToFeedback(feedbackId) {
      const replyText = window.prompt("Введите ответ пользователю");
      if (replyText === null) {
        return;
      }
      const normalizedReply = String(replyText || "").trim();
      if (!normalizedReply) {
        alert("Ответ не может быть пустым.");
        return;
      }
      try {
        const result = await fetchJson(`/feedback/${feedbackId}/reply`, {
          method: "POST",
          body: JSON.stringify({reply_text: normalizedReply})
        });
        alert(result.delivered ? "Ответ отправлен пользователю." : "Ответ сохранён, но отправить пользователю не удалось.");
        await loadFeedbackInbox();
        await loadFeedbackArchive();
        if (result.thread_feedback_id) {
          await showFeedbackThread(result.thread_feedback_id);
        }
      } catch (error) {
        alert(error.message);
      }
    }

    async function bulkArchiveFeedback(restore) {
      const tableKey = restore ? "feedbackArchive" : "feedbackInbox";
      const ids = getSelectedIds(tableKey);
      if (!ids.length) {
        alert("Выберите хотя бы одно обращение.");
        return;
      }
      try {
        await fetchJson("/feedback/bulk-archive", {
          method: "POST",
          body: JSON.stringify({ids, archive: !restore})
        });
        selectedRows.feedbackInbox.clear();
        selectedRows.feedbackArchive.clear();
        await loadFeedbackInbox();
        await loadFeedbackArchive();
      } catch (error) {
        alert(error.message);
      }
    }

    async function loadSystemPrompts() {
      try {
        const data = await fetchJson("/system-prompts");
        tableData.systemPrompts = data.prompts || [];
        renderTableForKey("systemPrompts");
      } catch (error) {
        document.getElementById("systemPrompts").textContent = error.message;
      }
    }

    const promptKeySelect = document.getElementById("promptKeySelect");
    const promptKeyCustom = document.getElementById("promptKeyCustom");
    const promptContentInput = document.getElementById("promptContent");
    const promptDangerZone = document.getElementById("promptDangerZone");
    const promptKeyOptions = new Set(["PROMPT_T0", "PROMPT_T1", "PROMPT_T2", "PROMPT_T3"]);
    let promptEditingId = null;

    const promptDangerRules = [
      {
        key: "raw-angle-brackets",
        title: "Сырые угловые скобки",
        pattern: /<[^\n>]*>|<|>/g,
        recommendation: "Уберите символы < и > из текста промпта.",
      },
      {
        key: "html-entities",
        title: "HTML-сущности",
        pattern: /&lt;|&gt;|&amp;|&#\\d+;|&#x[0-9a-f]+;/gi,
        recommendation: "Замените HTML-сущности на обычный текст без служебных кодов.",
      },
      {
        key: "tag-like-close",
        title: "Тегоподобные закрывающие конструкции",
        pattern: /<\/[a-z][a-z0-9-]*>|&lt;\/[a-z][a-z0-9-]*&gt;/gi,
        recommendation: "Уберите конструкции, похожие на закрывающие теги.",
      },
    ];

    function escapeHtml(value) {
      return String(value || "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/\"/g, "&quot;")
        .replace(/'/g, "&#39;");
    }

    function buildLineStarts(content) {
      const starts = [0];
      for (let idx = 0; idx < content.length; idx += 1) {
        if (content[idx] === "\n") {
          starts.push(idx + 1);
        }
      }
      return starts;
    }

    function resolveLineByIndex(starts, index) {
      let line = 1;
      for (let idx = 0; idx < starts.length; idx += 1) {
        if (starts[idx] <= index) {
          line = idx + 1;
          continue;
        }
        break;
      }
      return line;
    }

    function detectPromptDangerZones(content) {
      const text = normalizeValue(content);
      const lineStarts = buildLineStarts(text);
      const findings = [];
      promptDangerRules.forEach((rule) => {
        const matches = [...text.matchAll(rule.pattern)].slice(0, 5);
        if (!matches.length) {
          return;
        }
        findings.push({
          key: rule.key,
          title: rule.title,
          recommendation: rule.recommendation,
          matches: matches.map((match) => {
            const offset = match.index || 0;
            return {
              value: match[0],
              line: resolveLineByIndex(lineStarts, offset),
            };
          }),
        });
      });
      return findings;
    }

    function renderPromptDangerZones(content) {
      const findings = detectPromptDangerZones(content);
      if (!promptDangerZone) {
        return findings;
      }
      if (!findings.length) {
        promptDangerZone.classList.add("safe");
        promptDangerZone.innerHTML = `
          <div class="prompt-danger-zone-title">Опасные зоны не найдены</div>
          <div class="muted">Подсветка выполняется автоматически при вводе, редактировании и после сохранения.</div>
        `;
        return findings;
      }
      promptDangerZone.classList.remove("safe");
      const itemsHtml = findings.map((finding) => {
        const fragments = finding.matches.map((entry) => {
          const fragment = escapeHtml(entry.value);
          return `<li>Строка ${entry.line}: <code class="prompt-danger-fragment">${fragment}</code></li>`;
        }).join("");
        return `
          <li>
            <div><strong>${escapeHtml(finding.title)}</strong></div>
            <div class="muted">${escapeHtml(finding.recommendation)}</div>
            <ul>${fragments}</ul>
          </li>
        `;
      }).join("");
      promptDangerZone.innerHTML = `
        <div class="prompt-danger-zone-title">Найдены опасные зоны (${findings.length})</div>
        <ul>${itemsHtml}</ul>
      `;
      return findings;
    }

    function updatePromptKeyVisibility() {
      const showCustom = promptKeySelect.value === "CUSTOM";
      promptKeyCustom.style.display = showCustom ? "block" : "none";
    }

    promptKeySelect.addEventListener("change", updatePromptKeyVisibility);
    updatePromptKeyVisibility();

    function resetSystemPromptForm() {
      promptEditingId = null;
      promptKeySelect.value = "PROMPT_T0";
      promptKeyCustom.value = "";
      updatePromptKeyVisibility();
      promptContentInput.value = "";
      renderPromptDangerZones("");
    }

    function editSystemPrompt(promptId) {
      const prompt = (tableData.systemPrompts || []).find((item) => item.id === promptId);
      if (!prompt) {
        return;
      }
      promptEditingId = prompt.id;
      const promptKey = normalizeValue(prompt.key);
      if (promptKeyOptions.has(promptKey)) {
        promptKeySelect.value = promptKey;
        promptKeyCustom.value = "";
      } else {
        promptKeySelect.value = "CUSTOM";
        promptKeyCustom.value = promptKey;
      }
      updatePromptKeyVisibility();
      promptContentInput.value = normalizeValue(prompt.content);
      renderPromptDangerZones(promptContentInput.value);
      showPanel("system-prompts");
    }

    async function saveSystemPrompt() {
      const key = promptKeySelect.value === "CUSTOM" ? promptKeyCustom.value : promptKeySelect.value;
      const content = promptContentInput.value;
      renderPromptDangerZones(content);
      try {
        if (promptEditingId) {
          await fetchJson(`/system-prompts/${promptEditingId}`, {
            method: "PATCH",
            body: JSON.stringify({key, content})
          });
        } else {
          await fetchJson("/system-prompts", {
            method: "POST",
            body: JSON.stringify({key, content})
          });
        }
        resetSystemPromptForm();
        await loadSystemPrompts();
      } catch (error) {
        alert(error.message);
      }
    }

    promptContentInput.addEventListener("input", () => {
      renderPromptDangerZones(promptContentInput.value);
    });
    renderPromptDangerZones(promptContentInput.value);

    async function deleteSystemPrompt(promptId) {
      if (!confirm("Удалить промпт?")) {
        return;
      }
      try {
        await fetchJson(`/system-prompts/${promptId}`, {method: "DELETE"});
        await loadSystemPrompts();
      } catch (error) {
        alert(error.message);
      }
    }

    async function bulkDeleteSystemPrompts() {
      const ids = getSelectedIds("systemPrompts");
      if (!ids.length) {
        alert("Выберите хотя бы один промпт.");
        return;
      }
      if (!confirm(`Удалить выбранные промпты: ${ids.length} шт.?`)) {
        return;
      }
      try {
        await fetchJson("/system-prompts/bulk-delete", {
          method: "POST",
          body: JSON.stringify({ids})
        });
        selectedRows.systemPrompts.clear();
        await loadSystemPrompts();
      } catch (error) {
        alert(error.message);
      }
    }

    async function loadNotes() {
      try {
        const data = await fetchJson("/notes");
        tableData.notes = data.notes || [];
        renderTableForKey("notes");
      } catch (error) {
        document.getElementById("notes").textContent = error.message;
      }
    }

    const analyticsThresholds = {
      lowCr: 0.35,
      highDropoff: 0.45,
      longDurationSec: 1800,
    };

    const analyticsScreenDescriptions = {
      S0: "Старт и первый оффер",
      S1: "Выбор тарифа",
      S2: "Оферта перед оплатой",
      S3: "Оплата тарифа",
      S4: "Форма «Мои данные»",
      S5: "Расширенная анкета",
      S6: "Ожидание готовности отчёта",
      S7: "Готовый отчёт",
      S6_OR_S7: "Получение результата (ожидание/отчёт)",
      S8: "Экран обратной связи",
      S9: "Ввод сообщения в поддержку",
      S10: "Подтверждение отправки",
      S11: "Сообщение об ошибке",
      S12: "Повторная оплата/проверка",
      S13: "Поддержка: список диалогов",
      S14: "Поддержка: диалог с пользователем",
      UNKNOWN: "Неизвестный экран",
    };

    function screenLabel(screenId) {
      const raw = (screenId || "").toString().trim().toUpperCase();
      if (!raw) {
        return "—";
      }
      const baseId = raw.split("_")[0];
      const description = analyticsScreenDescriptions[raw] || analyticsScreenDescriptions[baseId];
      if (!description) {
        return raw;
      }
      if (raw === baseId) {
        return `${raw} — ${description}`;
      }
      return `${raw} — ${description} (${baseId})`;
    }

    function toIsoFromLocal(value) {
      if (!value) {
        return null;
      }
      const parsed = new Date(value);
      if (Number.isNaN(parsed.getTime())) {
        return null;
      }
      return parsed.toISOString();
    }

    function formatPercent(value) {
      const num = Number(value) || 0;
      return `${(num * 100).toFixed(1)}%`;
    }

    function renderAnalyticsTable(targetId, headers, rows) {
      const target = document.getElementById(targetId);
      if (!target) {
        return;
      }
      if (!rows.length) {
        target.innerHTML = '<div class="muted">Нет данных за выбранный период.</div>';
        return;
      }
      target.innerHTML = `
        <table>
          <thead>
            <tr>${headers.map((header) => `<th>${header}</th>`).join("")}</tr>
          </thead>
          <tbody>
            ${rows.map((row) => `<tr>${row.map((cell) => `<td class="${cell.className || ""}">${cell.value}</td>`).join("")}</tr>`).join("")}
          </tbody>
        </table>
      `;
    }

    function renderFunnelChart(funnelRows) {
      const target = document.getElementById("analyticsFunnel");
      if (!target) {
        return;
      }
      if (!funnelRows.length) {
        target.innerHTML = '<div class="muted">Нет данных по воронке.</div>';
        return;
      }
      target.innerHTML = `
        <div class="funnel-chart">
          ${funnelRows.map((row) => {
            const width = Math.max(0, Math.min(100, (Number(row.conversion_from_start) || 0) * 100));
            const stepCr = Number(row.conversion_from_previous) || 0;
            const isProblem = stepCr > 0 && stepCr < analyticsThresholds.lowCr;
            return `
              <div class="funnel-step ${isProblem ? "problem-cell" : ""}">
                <div>${screenLabel(row.step)}</div>
                <div class="funnel-bar-wrap"><div class="funnel-bar" style="width: ${width}%;"></div></div>
                <div>${formatPercent(stepCr)}</div>
              </div>
            `;
          }).join("")}
        </div>
      `;
    }

    function renderKpis(summary, funnelRows, dropoffRows) {
      const target = document.getElementById("analyticsKpi");
      if (!target) {
        return;
      }
      const users = Number(summary?.users) || 0;
      const startStep = funnelRows.find((row) => row.step === "S0") || funnelRows[0];
      const endStep = funnelRows[funnelRows.length - 1];
      const startUsers = Number(startStep?.users) || 0;
      const endUsers = Number(endStep?.users) || 0;
      const conversion = startUsers ? endUsers / startUsers : 0;
      const topDropoff = dropoffRows.slice(0, 3).map((row) => `${screenLabel(row.screen)}: ${formatPercent(row.share)}`).join(" • ") || "Нет данных";

      target.innerHTML = `
        <div class="kpi-card">
          <h3>Уникальные пользователи воронки</h3>
          <div class="value">${users}</div>
        </div>
        <div class="kpi-card ${conversion < analyticsThresholds.lowCr ? "problem" : ""}">
          <h3>Общая конверсия воронки</h3>
          <div class="value">${formatPercent(conversion)}</div>
        </div>
        <div class="kpi-card ${(dropoffRows[0]?.share || 0) > analyticsThresholds.highDropoff ? "problem" : ""}">
          <h3>Drop-off top-3</h3>
          <div class="value" style="font-size: 14px; line-height: 1.35;">${topDropoff}</div>
        </div>
      `;
    }

    function buildAnalyticsQuery() {
      const query = new URLSearchParams();
      const fromIso = toIsoFromLocal(document.getElementById("analyticsFrom")?.value || "");
      const toIso = toIsoFromLocal(document.getElementById("analyticsTo")?.value || "");
      const tariff = document.getElementById("analyticsTariff")?.value || "";
      const dropoffWindow = Number(document.getElementById("analyticsDropoffWindow")?.value || "60");
      const topN = Number(document.getElementById("analyticsTopN")?.value || "50");
      if (fromIso) {
        query.set("from", fromIso);
      }
      if (toIso) {
        query.set("to", toIso);
      }
      if (tariff) {
        query.set("tariff", tariff);
      }
      query.set("dropoff_window_minutes", String(Math.min(1440, Math.max(1, dropoffWindow || 60))));
      query.set("top_n", String(Math.min(500, Math.max(3, topN || 50))));
      return query.toString();
    }

    async function loadAnalytics() {
      const stateNode = document.getElementById("analyticsState");
      if (!stateNode) {
        return;
      }
      stateNode.textContent = "Загрузка аналитики...";
      try {
        const query = buildAnalyticsQuery();
        const [summaryRes, matrixRes, funnelRes, timingRes, fullRes] = await Promise.all([
          fetchJson(`/analytics/transitions/summary?${query}`),
          fetchJson(`/analytics/transitions/matrix?${query}`),
          fetchJson(`/analytics/transitions/funnel?${query}`),
          fetchJson(`/analytics/transitions/timing?${query}`),
          fetchJson(`/analytics/screen-transitions?${query}`),
        ]);

        const summary = summaryRes?.data?.summary || {};
        const matrixRows = matrixRes?.data?.transition_matrix || [];
        const funnelRows = funnelRes?.data?.funnel || [];
        const timingRows = timingRes?.data?.transition_timing || [];
        const dropoffRows = fullRes?.data?.dropoff || [];

        const isEmpty = !matrixRows.length && !funnelRows.length && !dropoffRows.length;
        if (isEmpty) {
          stateNode.textContent = "Нет данных за выбранный период.";
          renderKpis({}, [], []);
          renderFunnelChart([]);
          renderAnalyticsTable("analyticsMatrix", ["from", "to", "count", "share"], []);
          renderAnalyticsTable("analyticsBottlenecks", ["Переход", "CR", "Drop-off", "Медиана времени"], []);
          return;
        }

        renderKpis(summary, funnelRows, dropoffRows);
        renderFunnelChart(funnelRows);

        renderAnalyticsTable(
          "analyticsMatrix",
          ["From", "To", "Переходов", "Доля"],
          matrixRows.map((row) => [
            {value: screenLabel(row.from_screen)},
            {value: screenLabel(row.to_screen)},
            {value: Number(row.count) || 0},
            {value: formatPercent(row.share)},
          ])
        );

        const timingByPair = new Map(
          timingRows.map((row) => [`${row.from_screen}->${row.to_screen}`, row])
        );
        const bottlenecks = matrixRows.slice(0, 20).map((row) => {
          const key = `${row.from_screen}->${row.to_screen}`;
          const timing = timingByPair.get(key);
          const cr = Number(row.share) || 0;
          const dropoffShare = Number((dropoffRows.find((drop) => drop.screen === row.to_screen) || {}).share) || 0;
          const medianSec = Number(timing?.median_seconds) || 0;
          const isProblem = cr < analyticsThresholds.lowCr || dropoffShare > analyticsThresholds.highDropoff || medianSec > analyticsThresholds.longDurationSec;
          return {
            transition: `${screenLabel(row.from_screen)} → ${screenLabel(row.to_screen)}`,
            cr,
            dropoffShare,
            medianSec,
            isProblem,
          };
        }).filter((row) => row.isProblem).sort((a, b) => (b.dropoffShare + b.medianSec / 10000) - (a.dropoffShare + a.medianSec / 10000));

        renderAnalyticsTable(
          "analyticsBottlenecks",
          ["Переход", "CR", "Drop-off", "Медиана времени"],
          bottlenecks.map((row) => [
            {value: row.transition, className: row.isProblem ? "problem-cell" : ""},
            {value: formatPercent(row.cr), className: row.cr < analyticsThresholds.lowCr ? "problem-cell" : ""},
            {value: formatPercent(row.dropoffShare), className: row.dropoffShare > analyticsThresholds.highDropoff ? "problem-cell" : ""},
            {value: row.medianSec ? `${Math.round(row.medianSec)} сек` : "—", className: row.medianSec > analyticsThresholds.longDurationSec ? "problem-cell" : ""},
          ])
        );
        stateNode.textContent = `Обновлено: ${new Date().toLocaleString()}`;
      } catch (error) {
        stateNode.textContent = `Ошибка загрузки аналитики: ${error.message}`;
      }
    }

    async function createNote() {
      const input = document.getElementById("noteInput");
      const value = input.value;
      let payload = value;
      try {
        payload = JSON.parse(value);
      } catch (error) {
        payload = value;
      }
      try {
        await fetchJson("/notes", {
          method: "POST",
          body: JSON.stringify(payload)
        });
        input.value = "";
        await loadNotes();
      } catch (error) {
        alert(error.message);
      }
    }


    async function bulkDeleteNotes() {
      const ids = getSelectedIds("notes");
      if (!ids.length) {
        alert("Выберите хотя бы одну заметку.");
        return;
      }
      if (!confirm(`Удалить выбранные заметки: ${ids.length} шт.?`)) {
        return;
      }
      try {
        await fetchJson("/notes/bulk-delete", {
          method: "POST",
          body: JSON.stringify({ids})
        });
        selectedRows.notes.clear();
        await loadNotes();
      } catch (error) {
        alert(error.message);
      }
    }

    const sectionButtons = document.querySelectorAll("[data-section]");
    const panels = document.querySelectorAll("[data-panel]");
    const loaders = {
      overview: loadOverview,
      health: loadHealth,
      "llm-keys": loadLlmKeys,
      orders: loadOrders,
      reports: loadReports,
      users: loadUsers,
      "feedback-inbox": async () => { await loadFeedbackInbox(); await loadFeedbackArchive(); },
      analytics: loadAnalytics,
      "system-prompts": loadSystemPrompts,
      notes: loadNotes,
    };

    Object.keys(tableStates).forEach((tableKey) => {
      const input = document.getElementById(`${tableKey}Search`);
      if (input) {
        input.addEventListener("input", (event) => {
          tableStates[tableKey].search = event.target.value || "";
          renderTableForKey(tableKey);
        });
      }
    });

    const llmTabButtons = document.querySelectorAll("[data-llm-tab]");
    const llmTabPanels = document.querySelectorAll("[data-llm-panel]");
    let activeLlmTab = "active";

    function showLlmTab(name) {
      activeLlmTab = name;
      llmTabPanels.forEach((panel) => {
        panel.classList.toggle("active", panel.dataset.llmPanel === name);
      });
      llmTabButtons.forEach((button) => {
        button.classList.toggle("active", button.dataset.llmTab === name);
      });
    }

    llmTabButtons.forEach((button) => {
      button.addEventListener("click", () => showLlmTab(button.dataset.llmTab));
    });

    const feedbackTabButtons = document.querySelectorAll("[data-feedback-tab]");
    const feedbackTabPanels = document.querySelectorAll("[data-feedback-panel]");

    function showFeedbackTab(name) {
      feedbackTabPanels.forEach((panel) => {
        panel.classList.toggle("active", panel.dataset.feedbackPanel === name);
      });
      feedbackTabButtons.forEach((button) => {
        button.classList.toggle("active", button.dataset.feedbackTab === name);
      });
    }

    feedbackTabButtons.forEach((button) => {
      button.addEventListener("click", () => showFeedbackTab(button.dataset.feedbackTab));
    });

    let activePanel = "overview";
    let autoRefreshTimer = null;

    function startAutoRefresh() {
      if (autoRefreshTimer) {
        clearInterval(autoRefreshTimer);
        autoRefreshTimer = null;
      }
      if (!autoRefreshSeconds) {
        return;
      }
      autoRefreshTimer = setInterval(() => {
        if (document.hidden) {
          return;
        }
        const loader = loaders[activePanel];
        if (loader) {
          loader();
        }
      }, autoRefreshSeconds * 1000);
    }

    function showPanel(name) {
      activePanel = name;
      panels.forEach((panel) => {
        panel.classList.toggle("active", panel.dataset.panel === name);
      });
      sectionButtons.forEach((button) => {
        button.classList.toggle("active", button.dataset.section === name);
      });
      const loader = loaders[name];
      if (loader) {
        loader();
      }
    }

    sectionButtons.forEach((button) => {
      button.addEventListener("click", () => showPanel(button.dataset.section));
    });

    syncLlmProviderInput();
    showLlmTab(activeLlmTab);
    showPanel("overview");
    startAutoRefresh();
  </script>
</body>
</html>
"""
    response = HTMLResponse(html.replace("__ADMIN_AUTO_REFRESH_SECONDS__", str(auto_refresh_seconds)))
    return response


@router.post("/login")
async def admin_login(login: str = Form(...), password: str = Form(...)) -> HTMLResponse:
    if not _admin_credentials_ready():
        return HTMLResponse(
            _admin_login_html("ADMIN_LOGIN или ADMIN_PASSWORD не настроены на сервере."),
            status_code=503,
        )
    if not _is_valid_admin_credentials(login, password):
        return HTMLResponse(_admin_login_html("Неверный логин или пароль."), status_code=403)
    response = RedirectResponse(url="/admin", status_code=303)
    session_token = _admin_session_token()
    if session_token:
        response.set_cookie("admin_session", session_token, httponly=True, samesite="Lax")
    return response


@router.post("/logout")
async def admin_logout() -> RedirectResponse:
    response = RedirectResponse(url="/admin", status_code=303)
    response.delete_cookie("admin_session")
    return response


@router.get("/api/overview")
def admin_overview(session: Session = Depends(_get_db_session)) -> dict:
    users_count = session.scalar(select(func.count()).select_from(User)) or 0
    orders_count = session.scalar(select(func.count()).select_from(Order)) or 0
    reports_count = session.scalar(select(func.count()).select_from(Report)) or 0
    feedback_count = session.scalar(select(func.count()).select_from(FeedbackMessage)) or 0
    paid_count = session.scalar(
        select(func.count()).select_from(Order).where(Order.status == OrderStatus.PAID)
    ) or 0
    return {
        "users": users_count,
        "orders": orders_count,
        "paid_orders": paid_count,
        "reports": reports_count,
        "feedback_messages": feedback_count,
    }


@router.get("/api/health")
def admin_health(request: Request) -> dict:
    _require_admin(request)
    database_ok = False
    error_detail = None
    try:
        session_factory = get_session_factory()
        session = session_factory()
        session.execute(select(1))
        session.close()
        database_ok = True
    except Exception as exc:
        error_detail = str(exc)
    return {
        "env": settings.env,
        "database_ok": database_ok,
        "database_error": error_detail,
        "admin_auth_enabled": _admin_credentials_ready(),
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }


class TransitionSummaryItem(BaseModel):
    events: int
    users: int


class TransitionMatrixItem(BaseModel):
    from_screen: str
    to_screen: str
    count: int
    share: float


class TransitionFunnelItem(BaseModel):
    step: str
    users: int
    conversion_from_start: float
    conversion_from_previous: float


class TransitionTimingItem(BaseModel):
    from_screen: str
    to_screen: str
    samples: int
    median_seconds: float
    p95_seconds: float


class TransitionFiltersApplied(BaseModel):
    from_dt: datetime | None
    to_dt: datetime | None
    tariff: str | None
    trigger_type: str | None
    unique_users_only: bool
    dropoff_window_minutes: int
    limit: int
    top_n: int
    screen_ids: list[str]


class TransitionAnalyticsEnvelope(BaseModel):
    generated_at: datetime
    filters_applied: TransitionFiltersApplied
    data: dict
    warnings: list[str]


_TRANSITION_SCREEN_WHITELIST: frozenset[str] = frozenset(
    {
        "S0",
        "S1",
        "S2",
        "S3",
        "S4",
        "S5",
        "S6",
        "S7",
        "S8",
        "S9",
        "S10",
        "S11",
        "S12",
        "S13",
        "S14",
    }
)
_TRANSITION_TIMING_MIN_SAMPLES = 2


def _normalize_screen_filter(screen_ids: list[str] | None) -> tuple[list[str], frozenset[str] | None]:
    if not screen_ids:
        return [], None
    cleaned: list[str] = []
    for raw in screen_ids:
        candidate = str(raw or "").strip().upper()
        if not candidate:
            continue
        if candidate not in _TRANSITION_SCREEN_WHITELIST:
            raise HTTPException(status_code=422, detail=f"screen_id '{candidate}' is not allowed")
        if candidate not in cleaned:
            cleaned.append(candidate)
    return cleaned, (frozenset(cleaned) if cleaned else None)


def _build_transition_filters(
    *,
    from_dt: datetime | None,
    to_dt: datetime | None,
    tariff: str | None,
    trigger_type: str | None,
    unique_users_only: bool,
    dropoff_window_minutes: int,
    limit: int,
    screen_ids: list[str] | None,
) -> tuple[AnalyticsFilters, TransitionFiltersApplied]:
    if from_dt and to_dt and from_dt > to_dt:
        raise HTTPException(status_code=422, detail="Parameter 'from' must be less than or equal to 'to'")

    normalized_trigger_type = parse_trigger_type(trigger_type)
    normalized_screen_ids, screen_set = _normalize_screen_filter(screen_ids)

    filters = AnalyticsFilters(
        from_dt=from_dt,
        to_dt=to_dt,
        tariff=tariff,
        trigger_type=normalized_trigger_type,
        unique_users_only=unique_users_only,
        dropoff_window_minutes=dropoff_window_minutes,
        limit=limit,
        screen_ids=screen_set,
    )
    filters_applied = TransitionFiltersApplied(
        from_dt=from_dt,
        to_dt=to_dt,
        tariff=tariff,
        trigger_type=normalized_trigger_type,
        unique_users_only=unique_users_only,
        dropoff_window_minutes=dropoff_window_minutes,
        limit=limit,
        top_n=0,
        screen_ids=normalized_screen_ids,
    )
    return filters, filters_applied


def _build_transition_envelope(
    *,
    data: dict,
    filters_applied: TransitionFiltersApplied,
    top_n: int,
) -> dict:
    warnings: list[str] = []
    if data.get("summary", {}).get("events", 0) < 5:
        warnings.append("Недостаточно данных за период")

    filters_payload = filters_applied.model_copy(update={"top_n": top_n})
    return TransitionAnalyticsEnvelope(
        generated_at=datetime.now(timezone.utc),
        filters_applied=filters_payload,
        data=data,
        warnings=warnings,
    ).model_dump(mode="json")


def _safe_build_transition_analytics(session: Session, filters: AnalyticsFilters) -> dict:
    try:
        return build_screen_transition_analytics(session, filters)
    except (OperationalError, SQLAlchemyTimeoutError) as exc:
        logger.exception("admin_transition_analytics_db_unavailable")
        raise HTTPException(
            status_code=503,
            detail="База данных временно перегружена. Попробуйте повторить запрос позже.",
        ) from exc


def _slice_top_n(items: list[dict], top_n: int) -> list[dict]:
    if top_n <= 0:
        return items
    return items[:top_n]


@router.get("/api/analytics/screen-transitions")
def admin_screen_transition_analytics(
    from_dt: datetime | None = Query(default=None, alias="from"),
    to_dt: datetime | None = Query(default=None, alias="to"),
    tariff: str | None = Query(default=None),
    trigger_type: str | None = Query(default=None),
    unique_users_only: bool = Query(default=False),
    dropoff_window_minutes: int = Query(default=60, ge=1, le=1440),
    limit: int = Query(default=5000, ge=1, le=50000),
    top_n: int = Query(default=50, ge=1, le=500),
    screen_ids: list[str] | None = Query(default=None, alias="screen_id"),
    session: Session = Depends(_get_db_session),
) -> dict:
    filters, filters_applied = _build_transition_filters(
        from_dt=from_dt,
        to_dt=to_dt,
        tariff=tariff,
        trigger_type=trigger_type,
        unique_users_only=unique_users_only,
        dropoff_window_minutes=dropoff_window_minutes,
        limit=limit,
        screen_ids=screen_ids,
    )
    result = _safe_build_transition_analytics(session, filters)
    payload = {
        "summary": result["summary"],
        "transition_matrix": _slice_top_n(result["transition_matrix"], top_n),
        "funnel": _slice_top_n(result["funnel"], top_n),
        "dropoff": _slice_top_n(result["dropoff"], top_n),
        "transition_durations": _slice_top_n(result["transition_durations"], top_n),
    }
    return _build_transition_envelope(data=payload, filters_applied=filters_applied, top_n=top_n)


@router.get("/api/analytics/transitions/summary")
def admin_transitions_summary(
    from_dt: datetime | None = Query(default=None, alias="from"),
    to_dt: datetime | None = Query(default=None, alias="to"),
    tariff: str | None = Query(default=None),
    trigger_type: str | None = Query(default=None),
    unique_users_only: bool = Query(default=False),
    dropoff_window_minutes: int = Query(default=60, ge=1, le=1440),
    limit: int = Query(default=5000, ge=1, le=50000),
    screen_ids: list[str] | None = Query(default=None, alias="screen_id"),
    session: Session = Depends(_get_db_session),
) -> dict:
    filters, filters_applied = _build_transition_filters(
        from_dt=from_dt,
        to_dt=to_dt,
        tariff=tariff,
        trigger_type=trigger_type,
        unique_users_only=unique_users_only,
        dropoff_window_minutes=dropoff_window_minutes,
        limit=limit,
        screen_ids=screen_ids,
    )
    result = _safe_build_transition_analytics(session, filters)
    summary = TransitionSummaryItem.model_validate(result["summary"]).model_dump(mode="json")
    return _build_transition_envelope(data={"summary": summary}, filters_applied=filters_applied, top_n=0)


@router.get("/api/analytics/transitions/matrix")
def admin_transitions_matrix(
    from_dt: datetime | None = Query(default=None, alias="from"),
    to_dt: datetime | None = Query(default=None, alias="to"),
    tariff: str | None = Query(default=None),
    trigger_type: str | None = Query(default=None),
    unique_users_only: bool = Query(default=False),
    dropoff_window_minutes: int = Query(default=60, ge=1, le=1440),
    limit: int = Query(default=5000, ge=1, le=50000),
    top_n: int = Query(default=50, ge=1, le=500),
    screen_ids: list[str] | None = Query(default=None, alias="screen_id"),
    session: Session = Depends(_get_db_session),
) -> dict:
    filters, filters_applied = _build_transition_filters(
        from_dt=from_dt,
        to_dt=to_dt,
        tariff=tariff,
        trigger_type=trigger_type,
        unique_users_only=unique_users_only,
        dropoff_window_minutes=dropoff_window_minutes,
        limit=limit,
        screen_ids=screen_ids,
    )
    result = _safe_build_transition_analytics(session, filters)
    matrix_items = [
        TransitionMatrixItem.model_validate(item).model_dump(mode="json")
        for item in _slice_top_n(result["transition_matrix"], top_n)
    ]
    return _build_transition_envelope(data={"transition_matrix": matrix_items}, filters_applied=filters_applied, top_n=top_n)


@router.get("/api/analytics/transitions/funnel")
def admin_transitions_funnel(
    from_dt: datetime | None = Query(default=None, alias="from"),
    to_dt: datetime | None = Query(default=None, alias="to"),
    tariff: str | None = Query(default=None),
    trigger_type: str | None = Query(default=None),
    unique_users_only: bool = Query(default=False),
    dropoff_window_minutes: int = Query(default=60, ge=1, le=1440),
    limit: int = Query(default=5000, ge=1, le=50000),
    top_n: int = Query(default=50, ge=1, le=500),
    screen_ids: list[str] | None = Query(default=None, alias="screen_id"),
    session: Session = Depends(_get_db_session),
) -> dict:
    filters, filters_applied = _build_transition_filters(
        from_dt=from_dt,
        to_dt=to_dt,
        tariff=tariff,
        trigger_type=trigger_type,
        unique_users_only=unique_users_only,
        dropoff_window_minutes=dropoff_window_minutes,
        limit=limit,
        screen_ids=screen_ids,
    )
    result = _safe_build_transition_analytics(session, filters)
    funnel_items = [
        TransitionFunnelItem.model_validate(item).model_dump(mode="json")
        for item in _slice_top_n(result["funnel"], top_n)
    ]
    return _build_transition_envelope(data={"funnel": funnel_items}, filters_applied=filters_applied, top_n=top_n)


@router.get("/api/analytics/transitions/timing")
def admin_transitions_timing(
    from_dt: datetime | None = Query(default=None, alias="from"),
    to_dt: datetime | None = Query(default=None, alias="to"),
    tariff: str | None = Query(default=None),
    trigger_type: str | None = Query(default=None),
    unique_users_only: bool = Query(default=False),
    dropoff_window_minutes: int = Query(default=60, ge=1, le=1440),
    limit: int = Query(default=5000, ge=1, le=50000),
    top_n: int = Query(default=50, ge=1, le=500),
    screen_ids: list[str] | None = Query(default=None, alias="screen_id"),
    session: Session = Depends(_get_db_session),
) -> dict:
    filters, filters_applied = _build_transition_filters(
        from_dt=from_dt,
        to_dt=to_dt,
        tariff=tariff,
        trigger_type=trigger_type,
        unique_users_only=unique_users_only,
        dropoff_window_minutes=dropoff_window_minutes,
        limit=limit,
        screen_ids=screen_ids,
    )
    result = _safe_build_transition_analytics(session, filters)
    timing_raw = [row for row in result["transition_durations"] if int(row.get("samples", 0)) >= _TRANSITION_TIMING_MIN_SAMPLES]
    timing_items = [
        TransitionTimingItem.model_validate(item).model_dump(mode="json")
        for item in _slice_top_n(timing_raw, top_n)
    ]
    envelope = _build_transition_envelope(data={"transition_timing": timing_items}, filters_applied=filters_applied, top_n=top_n)
    if not timing_items:
        envelope["warnings"].append("Недостаточно данных за период")
    return envelope


def _mask_key(value: str | None) -> str:
    if not value:
        return ""
    if len(value) <= 6:
        return "*" * len(value)
    return f"{value[:2]}***{value[-4:]}"




def _parse_json_payload(payload: object) -> dict:
    return payload if isinstance(payload, dict) else {}


def _parse_ids(payload: dict, *, field: str = "ids") -> list[int]:
    raw_ids = payload.get(field)
    if not isinstance(raw_ids, list):
        return []
    parsed: list[int] = []
    for raw_id in raw_ids:
        try:
            parsed.append(int(raw_id))
        except (TypeError, ValueError):
            continue
    return parsed
def _coerce_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() == "true"
    if isinstance(value, (int, float)):
        return bool(value)
    return bool(value)


@router.get("/api/llm-keys")
def admin_llm_keys(limit: int | None = 0, session: Session = Depends(_get_db_session)) -> dict:
    query = select(LLMApiKey).order_by(
        LLMApiKey.provider.asc(),
        LLMApiKey.priority.asc(),
        LLMApiKey.created_at.desc(),
    )
    if limit is not None and limit > 0:
        query = query.limit(limit)
    rows = session.execute(query).scalars()
    keys = []
    for key in rows:
        keys.append(
            {
                "id": key.id,
                "provider": key.provider,
                "priority": key.priority,
                "is_active": key.is_active,
                "masked_key": _mask_key(key.key),
                "key_length": len(key.key) if key.key else 0,
                "last_used_at": key.last_used_at.isoformat() if key.last_used_at else None,
                "last_success_at": key.last_success_at.isoformat() if key.last_success_at else None,
                "last_error": key.last_error,
                "last_status_code": key.last_status_code,
                "disabled_at": key.disabled_at.isoformat() if key.disabled_at else None,
                "success_count": key.success_count,
                "failure_count": key.failure_count,
                "created_at": key.created_at.isoformat(),
                "updated_at": key.updated_at.isoformat(),
            }
        )
    return {"keys": keys}


@router.post("/api/llm-keys")
async def admin_create_llm_key(
    request: Request, session: Session = Depends(_get_db_session)
) -> dict:
    payload: dict | None = None
    body = await request.body()
    if body:
        try:
            payload = await request.json()
        except Exception:
            payload = None
    payload = payload if isinstance(payload, dict) else {}
    provider = payload.get("provider")
    key_value = payload.get("key")
    priority = payload.get("priority")
    is_active = payload.get("is_active")
    is_active_value = _coerce_bool(is_active) if is_active is not None else True
    disabled_at = datetime.now(timezone.utc) if is_active is not None and not is_active_value else None
    record = LLMApiKey(
        provider="" if provider is None else str(provider),
        key="" if key_value is None else (key_value if isinstance(key_value, str) else str(key_value)),
        priority=None if priority is None else str(priority),
        is_active=is_active_value,
        disabled_at=disabled_at,
    )
    session.add(record)
    session.flush()
    return {
        "id": record.id,
        "created_at": record.created_at.isoformat(),
        "updated_at": record.updated_at.isoformat(),
    }


@router.post("/api/llm-keys/bulk")
async def admin_bulk_llm_keys(
    request: Request,
    file: UploadFile | None = File(default=None),
    provider: str | None = Form(default=None),
    session: Session = Depends(_get_db_session),
) -> dict:
    _require_admin(request)
    if file is None:
        return {"created": 0, "lines": 0}
    payload_bytes = await file.read()
    payload_text = payload_bytes.decode("utf-8", errors="replace")
    lines = payload_text.splitlines() if payload_text else []
    created = 0
    provider_value = "" if provider is None else str(provider)
    for line in lines:
        key_value = line
        if key_value == "":
            continue
        record = LLMApiKey(
            provider=provider_value,
            key="" if key_value is None else (key_value if isinstance(key_value, str) else str(key_value)),
            priority=None,
            is_active=True,
        )
        session.add(record)
        created += 1
    session.flush()
    return {"created": created, "lines": len(lines)}


@router.post("/api/llm-keys/bulk-update")
async def admin_bulk_update_llm_keys(
    request: Request, session: Session = Depends(_get_db_session)
) -> dict:
    try:
        payload = _parse_json_payload(await request.json())
    except Exception:
        payload = {}
    ids = _parse_ids(payload)
    if not ids:
        return {"updated": 0}
    records = session.execute(select(LLMApiKey).where(LLMApiKey.id.in_(ids))).scalars().all()
    if "is_active" in payload:
        next_state = _coerce_bool(payload.get("is_active"))
        now = datetime.now(timezone.utc)
        for record in records:
            if next_state:
                record.disabled_at = None
            elif record.is_active or record.disabled_at is None:
                record.disabled_at = now
            record.is_active = next_state
    if "priority" in payload:
        value = payload.get("priority")
        for record in records:
            record.priority = None if value is None else str(value)
    session.flush()
    return {"updated": len(records)}


@router.post("/api/llm-keys/bulk-delete")
async def admin_bulk_delete_llm_keys(
    request: Request, session: Session = Depends(_get_db_session)
) -> dict:
    try:
        payload = _parse_json_payload(await request.json())
    except Exception:
        payload = {}
    ids = _parse_ids(payload)
    if not ids:
        return {"deleted": 0}
    records = session.execute(select(LLMApiKey).where(LLMApiKey.id.in_(ids))).scalars().all()
    deleted = len(records)
    for record in records:
        session.delete(record)
    return {"deleted": deleted}


@router.patch("/api/llm-keys/{key_id}")
async def admin_update_llm_key(
    key_id: int, request: Request, session: Session = Depends(_get_db_session)
) -> dict:
    payload: dict | None = None
    body = await request.body()
    if body:
        try:
            payload = await request.json()
        except Exception:
            payload = None
    payload = payload if isinstance(payload, dict) else {}
    record = session.get(LLMApiKey, key_id)
    if not record:
        raise HTTPException(status_code=404, detail="LLM key not found")
    if "provider" in payload:
        value = payload.get("provider")
        record.provider = "" if value is None else str(value)
    if "key" in payload:
        value = payload.get("key")
        record.key = "" if value is None else (value if isinstance(value, str) else str(value))
    if "priority" in payload:
        value = payload.get("priority")
        record.priority = None if value is None else str(value)
    if "is_active" in payload:
        next_state = _coerce_bool(payload.get("is_active"))
        if next_state:
            record.disabled_at = None
        elif record.is_active or record.disabled_at is None:
            record.disabled_at = datetime.now(timezone.utc)
        record.is_active = next_state
    session.flush()
    return {"id": record.id, "updated_at": record.updated_at.isoformat()}


@router.delete("/api/llm-keys/{key_id}")
def admin_delete_llm_key(
    key_id: int, session: Session = Depends(_get_db_session)
) -> dict:
    record = session.get(LLMApiKey, key_id)
    if not record:
        raise HTTPException(status_code=404, detail="LLM key not found")
    session.delete(record)
    return {"deleted": True}


@router.get("/api/orders")
def admin_orders(limit: int = 50, session: Session = Depends(_get_db_session)) -> dict:
    rows = session.execute(
        select(Order, User)
        .join(User, User.id == Order.user_id)
        .order_by(Order.created_at.desc())
        .limit(limit)
    ).all()
    order_ids = [order.id for order, _ in rows]
    report_ids_by_order: dict[int, int] = {}
    if order_ids:
        report_rows = session.execute(
            select(Report.order_id, func.min(Report.id)).where(Report.order_id.in_(order_ids)).group_by(Report.order_id)
        ).all()
        report_ids_by_order = {
            report_order_id: report_id
            for report_order_id, report_id in report_rows
            if report_order_id is not None and report_id is not None
        }
    orders = []
    for order, user in rows:
        report_id = order.fulfilled_report_id or report_ids_by_order.get(order.id)
        orders.append(
            {
                "id": order.id,
                "user_id": order.user_id,
                "telegram_user_id": user.telegram_user_id if user else None,
                "tariff": order.tariff.value,
                "amount": float(order.amount),
                "currency": order.currency,
                "provider": order.provider.value,
                "status": order.status.value,
                "fulfillment_status": order.fulfillment_status.value,
                "fulfilled_at": order.fulfilled_at.isoformat() if order.fulfilled_at else None,
                "report_id": report_id,
                "created_at": order.created_at.isoformat(),
                "paid_at": order.paid_at.isoformat() if order.paid_at else None,
            }
        )
    return {"orders": orders}


@router.post("/api/orders/{order_id}/status")
async def admin_order_status(
    order_id: int,
    request: Request,
    session: Session = Depends(_get_db_session),
) -> dict:
    payload = {}
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    new_status = payload.get("status")
    order = session.get(Order, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    previous = order.status.value
    updated = False
    if isinstance(new_status, str):
        if new_status == OrderFulfillmentStatus.COMPLETED.value:
            order.fulfillment_status = OrderFulfillmentStatus.COMPLETED
            if not order.fulfilled_at:
                order.fulfilled_at = datetime.now(timezone.utc)
            updated = True
        else:
            try:
                order.status = OrderStatus(new_status)
                updated = True
                if order.status == OrderStatus.PAID and not order.paid_at:
                    order.paid_at = datetime.now(timezone.utc)
            except ValueError:
                updated = False
    return {
        "order_id": order.id,
        "previous_status": previous,
        "current_status": order.status.value,
        "updated": updated,
    }


@router.post("/api/orders/bulk-status")
async def admin_orders_bulk_status(
    request: Request,
    session: Session = Depends(_get_db_session),
) -> dict:
    try:
        payload = _parse_json_payload(await request.json())
    except Exception:
        payload = {}
    ids = _parse_ids(payload)
    status_value = payload.get("status")
    if not ids or not isinstance(status_value, str):
        return {"updated": 0}
    status_update: OrderStatus | None = None
    fulfillment_update: OrderFulfillmentStatus | None = None
    if status_value == OrderFulfillmentStatus.COMPLETED.value:
        fulfillment_update = OrderFulfillmentStatus.COMPLETED
    else:
        try:
            status_update = OrderStatus(status_value)
        except ValueError:
            return {"updated": 0}
    orders = session.execute(select(Order).where(Order.id.in_(ids))).scalars().all()
    updated = 0
    now = datetime.now(timezone.utc)
    for order in orders:
        if fulfillment_update is not None:
            order.fulfillment_status = fulfillment_update
            if fulfillment_update == OrderFulfillmentStatus.COMPLETED and not order.fulfilled_at:
                order.fulfilled_at = now
        if status_update is not None:
            order.status = status_update
            if status_update == OrderStatus.PAID and not order.paid_at:
                order.paid_at = now
        updated += 1
    return {"updated": updated}


@router.post("/api/orders/bulk-delete")
async def admin_orders_bulk_delete(
    request: Request,
    session: Session = Depends(_get_db_session),
) -> dict:
    try:
        payload = _parse_json_payload(await request.json())
    except Exception:
        payload = {}
    ids = _parse_ids(payload)
    if not ids:
        return {"deleted": 0}
    orders = session.execute(select(Order).where(Order.id.in_(ids))).scalars().all()
    deleted = len(orders)
    for order in orders:
        session.delete(order)
    return {"deleted": deleted}


@router.get("/api/reports")
def admin_reports(limit: int = 50, session: Session = Depends(_get_db_session)) -> dict:
    rows = session.execute(
        select(Report, User)
        .join(User, User.id == Report.user_id)
        .order_by(Report.created_at.desc())
        .limit(limit)
    ).all()
    reports = []
    for report, user in rows:
        reports.append(
            {
                "id": report.id,
                "user_id": report.user_id,
                "telegram_user_id": user.telegram_user_id if user else None,
                "order_id": report.order_id,
                "tariff": report.tariff.value,
                "model_used": report.model_used.value if report.model_used else None,
                "created_at": report.created_at.isoformat(),
                "pdf_storage_key": report.pdf_storage_key,
            }
        )
    return {"reports": reports}


@router.get("/api/users")
def admin_users(limit: int = 50, session: Session = Depends(_get_db_session)) -> dict:
    rows = session.execute(
        select(User, UserProfile)
        .outerjoin(UserProfile, UserProfile.user_id == User.id)
        .order_by(User.created_at.desc())
        .limit(limit)
    ).all()
    users = []
    for user, profile in rows:
        users.append(
            {
                "id": user.id,
                "telegram_user_id": user.telegram_user_id,
                "created_at": user.created_at.isoformat(),
                "name": profile.name if profile else None,
                "gender": profile.gender if profile else None,
                "birth_date": profile.birth_date if profile else None,
            }
        )
    return {"users": users}


def _resolve_thread_feedback_id(feedback: FeedbackMessage) -> int:
    return feedback.parent_feedback_id or feedback.id


def _load_feedback_threads(session: Session, *, limit: int, archived: bool) -> list[dict]:
    root_alias = FeedbackMessage
    latest_sent_at_subquery = (
        select(
            func.coalesce(FeedbackMessage.parent_feedback_id, FeedbackMessage.id).label("thread_feedback_id"),
            func.max(FeedbackMessage.sent_at).label("latest_sent_at"),
        )
        .group_by(func.coalesce(FeedbackMessage.parent_feedback_id, FeedbackMessage.id))
        .subquery()
    )
    latest_message_subquery = (
        select(
            FeedbackMessage.id.label("id"),
            FeedbackMessage.user_id.label("user_id"),
            FeedbackMessage.text.label("text"),
            FeedbackMessage.status.label("status"),
            FeedbackMessage.sent_at.label("sent_at"),
            FeedbackMessage.admin_reply.label("admin_reply"),
            FeedbackMessage.replied_at.label("replied_at"),
            func.coalesce(FeedbackMessage.parent_feedback_id, FeedbackMessage.id).label("thread_feedback_id"),
        )
        .join(
            latest_sent_at_subquery,
            (func.coalesce(FeedbackMessage.parent_feedback_id, FeedbackMessage.id) == latest_sent_at_subquery.c.thread_feedback_id)
            & (FeedbackMessage.sent_at == latest_sent_at_subquery.c.latest_sent_at),
        )
        .subquery()
    )
    thread_stats_subquery = (
        select(
            func.coalesce(FeedbackMessage.parent_feedback_id, FeedbackMessage.id).label("thread_feedback_id"),
            func.count(FeedbackMessage.id).label("message_count"),
        )
        .group_by(func.coalesce(FeedbackMessage.parent_feedback_id, FeedbackMessage.id))
        .subquery()
    )

    query = (
        select(
            root_alias,
            User,
            thread_stats_subquery.c.message_count,
            latest_message_subquery.c.id.label("last_feedback_id"),
            latest_message_subquery.c.status.label("last_status"),
            latest_message_subquery.c.text.label("last_text"),
            latest_message_subquery.c.sent_at.label("last_sent_at"),
            latest_message_subquery.c.admin_reply.label("last_admin_reply"),
            latest_message_subquery.c.replied_at.label("last_replied_at"),
        )
        .join(User, User.id == root_alias.user_id)
        .join(
            latest_message_subquery,
            latest_message_subquery.c.thread_feedback_id == root_alias.id,
        )
        .join(
            thread_stats_subquery,
            thread_stats_subquery.c.thread_feedback_id == root_alias.id,
        )
        .where(
            root_alias.parent_feedback_id.is_(None),
            root_alias.archived_at.is_not(None) if archived else root_alias.archived_at.is_(None),
        )
        .order_by(
            latest_message_subquery.c.sent_at.desc(),
            latest_message_subquery.c.id.desc(),
        )
    )
    if limit > 0:
        query = query.limit(limit)
    rows = session.execute(query).all()
    feedback = []
    for (
        thread_root,
        user,
        message_count,
        last_feedback_id,
        last_status,
        last_text,
        last_sent_at,
        last_admin_reply,
        last_replied_at,
    ) in rows:
        feedback.append(
            {
                "id": thread_root.id,
                "user_id": thread_root.user_id,
                "telegram_user_id": user.telegram_user_id if user else None,
                "status": last_status.value,
                "text": last_text,
                "sent_at": last_sent_at.isoformat() if last_sent_at else None,
                "archived_at": thread_root.archived_at.isoformat() if thread_root.archived_at else None,
                "admin_reply": last_admin_reply,
                "replied_at": last_replied_at.isoformat() if last_replied_at else None,
                "thread_feedback_id": thread_root.id,
                "last_feedback_id": last_feedback_id,
                "message_count": int(message_count or 0),
            }
        )
    return feedback


def _load_feedback_thread_history(
    session: Session,
    *,
    thread_feedback_id: int,
    limit: int,
) -> list[dict]:
    query = (
        select(SupportDialogMessage)
        .where(SupportDialogMessage.thread_feedback_id == thread_feedback_id)
        .order_by(SupportDialogMessage.created_at.asc(), SupportDialogMessage.id.asc())
    )
    if limit > 0:
        query = query.limit(limit)
    rows = session.execute(query).scalars().all()
    if rows:
        return [
            {
                "id": row.id,
                "direction": row.direction.value,
                "text": row.text,
                "delivered": row.delivered,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in rows
        ]

    fallback_rows = session.execute(
        select(FeedbackMessage)
        .where(
            (FeedbackMessage.id == thread_feedback_id)
            | (FeedbackMessage.parent_feedback_id == thread_feedback_id)
        )
        .order_by(FeedbackMessage.sent_at.asc(), FeedbackMessage.id.asc())
    ).scalars().all()
    history: list[dict] = []
    for row in fallback_rows:
        history.append(
            {
                "id": row.id,
                "direction": "user",
                "text": row.text,
                "delivered": row.status == FeedbackStatus.SENT,
                "created_at": row.sent_at.isoformat() if row.sent_at else None,
            }
        )
        if row.admin_reply:
            history.append(
                {
                    "id": row.id,
                    "direction": "admin",
                    "text": row.admin_reply,
                    "delivered": True,
                    "created_at": row.replied_at.isoformat() if row.replied_at else None,
                }
            )
    return history


@router.get("/api/feedback")
def admin_feedback(limit: int = 50, session: Session = Depends(_get_db_session)) -> dict:
    return {"feedback": _load_feedback_threads(session, limit=limit, archived=False)}


@router.get("/api/feedback/inbox")
def admin_feedback_inbox(limit: int = 50, session: Session = Depends(_get_db_session)) -> dict:
    return {"feedback": _load_feedback_threads(session, limit=limit, archived=False)}




@router.get("/api/feedback/archive")
def admin_feedback_archive(limit: int = 50, session: Session = Depends(_get_db_session)) -> dict:
    return {"feedback": _load_feedback_threads(session, limit=limit, archived=True)}


@router.get("/api/feedback/thread/{thread_feedback_id}")
def admin_feedback_thread(
    thread_feedback_id: int,
    limit: int = 200,
    session: Session = Depends(_get_db_session),
) -> dict:
    if thread_feedback_id <= 0:
        raise HTTPException(status_code=400, detail="thread_feedback_id must be positive")
    normalized_limit = max(1, min(limit, 1000))
    messages = _load_feedback_thread_history(
        session,
        thread_feedback_id=thread_feedback_id,
        limit=normalized_limit,
    )
    return {
        "thread_feedback_id": thread_feedback_id,
        "messages": messages,
    }


@router.post("/api/feedback/{feedback_id}/archive")
async def admin_feedback_toggle_archive(
    feedback_id: int,
    request: Request,
    session: Session = Depends(_get_db_session),
) -> dict:
    payload: dict = {}
    body = await request.body()
    if body:
        try:
            candidate = await request.json()
            if isinstance(candidate, dict):
                payload = candidate
        except Exception:
            payload = {}
    archive = bool(payload.get("archive", True))
    feedback = session.get(FeedbackMessage, feedback_id)
    if not feedback:
        raise HTTPException(status_code=404, detail="Feedback message not found")
    thread_feedback_id = _resolve_thread_feedback_id(feedback)
    thread_rows = session.execute(
        select(FeedbackMessage).where(
            (FeedbackMessage.id == thread_feedback_id)
            | (FeedbackMessage.parent_feedback_id == thread_feedback_id)
        )
    ).scalars().all()
    archived_at = datetime.now(timezone.utc) if archive else None
    for row in thread_rows:
        row.archived_at = archived_at
    return {
        "id": thread_feedback_id,
        "archived": archived_at is not None,
        "archived_at": archived_at.isoformat() if archived_at else None,
    }


async def _deliver_feedback_reply(telegram_user_id: int, reply_text: str, thread_feedback_id: int) -> bool:
    if not settings.bot_token:
        return False
    try:
        bot = Bot(token=settings.bot_token)
    except Exception as exc:
        logger.warning("feedback_reply_bot_init_failed", extra={"error": str(exc)})
        return False
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Ответить поддержке",
                    callback_data=f"feedback:quick_reply:{thread_feedback_id}",
                )
            ]
        ]
    )
    try:
        await bot.send_message(
            chat_id=telegram_user_id,
            text=f"Ответ от поддержки\n\n{reply_text}",
            reply_markup=keyboard,
        )
        return True
    except Exception as exc:
        logger.warning(
            "feedback_reply_send_failed",
            extra={"telegram_user_id": telegram_user_id, "error": str(exc)},
        )
        return False
    finally:
        await bot.session.close()


@router.post("/api/feedback/{feedback_id}/reply")
async def admin_feedback_reply(
    feedback_id: int,
    request: Request,
    session: Session = Depends(_get_db_session),
) -> dict:
    payload: dict = {}
    body = await request.body()
    if body:
        try:
            candidate = await request.json()
            if isinstance(candidate, dict):
                payload = candidate
        except Exception:
            payload = {}

    raw_reply = payload.get("reply_text")
    reply_text = str(raw_reply or "").strip()
    if not reply_text:
        raise HTTPException(status_code=400, detail="Reply text is required")

    feedback = session.get(FeedbackMessage, feedback_id)
    if not feedback:
        raise HTTPException(status_code=404, detail="Feedback message not found")

    user = session.get(User, feedback.user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User for feedback message not found")

    thread_feedback_id = _resolve_thread_feedback_id(feedback)
    delivered = await _deliver_feedback_reply(user.telegram_user_id, reply_text, thread_feedback_id)
    feedback.admin_reply = reply_text
    feedback.replied_at = datetime.now(timezone.utc)
    session.add(
        SupportDialogMessage(
            user_id=user.id,
            thread_feedback_id=thread_feedback_id,
            direction=SupportMessageDirection.ADMIN,
            text=reply_text,
            delivered=delivered,
        )
    )

    return {
        "id": feedback.id,
        "delivered": delivered,
        "admin_reply": feedback.admin_reply,
        "replied_at": feedback.replied_at.isoformat() if feedback.replied_at else None,
        "thread_feedback_id": thread_feedback_id,
    }


@router.post("/api/feedback/bulk-archive")
async def admin_feedback_bulk_archive(
    request: Request,
    session: Session = Depends(_get_db_session),
) -> dict:
    payload: dict = {}
    body = await request.body()
    if body:
        try:
            candidate = await request.json()
            if isinstance(candidate, dict):
                payload = candidate
        except Exception:
            payload = {}
    raw_ids = payload.get("ids")
    ids = [int(item) for item in raw_ids if str(item).strip().isdigit()] if isinstance(raw_ids, list) else []
    if not ids:
        raise HTTPException(status_code=400, detail="No feedback ids provided")
    archive = bool(payload.get("archive", True))
    now = datetime.now(timezone.utc)
    thread_ids_subquery = (
        select(func.coalesce(FeedbackMessage.parent_feedback_id, FeedbackMessage.id).label("thread_feedback_id"))
        .where(FeedbackMessage.id.in_(ids))
        .subquery()
    )
    rows = session.execute(
        select(FeedbackMessage).where(
            func.coalesce(FeedbackMessage.parent_feedback_id, FeedbackMessage.id).in_(
                select(thread_ids_subquery.c.thread_feedback_id)
            )
        )
    ).scalars().all()
    updated = 0
    for feedback in rows:
        feedback.archived_at = now if archive else None
        updated += 1
    return {"updated": updated}

@router.get("/api/system-prompts")
def admin_system_prompts(
    limit: int = 200, session: Session = Depends(_get_db_session)
) -> dict:
    rows = session.execute(
        select(SystemPrompt).order_by(SystemPrompt.updated_at.desc()).limit(limit)
    ).scalars()
    prompts = []
    for prompt in rows:
        prompts.append(
            {
                "id": prompt.id,
                "key": prompt.key,
                "content": prompt.content,
                "created_at": prompt.created_at.isoformat(),
                "updated_at": prompt.updated_at.isoformat(),
            }
        )
    return {"prompts": prompts}


@router.post("/api/system-prompts")
async def admin_create_system_prompt(
    request: Request, session: Session = Depends(_get_db_session)
) -> dict:
    body = await request.body()
    payload: dict | None = None
    if body:
        try:
            payload = await request.json()
        except Exception:
            payload = None
    payload = payload if isinstance(payload, dict) else {}
    key = payload.get("key")
    content = payload.get("content")
    prompt = SystemPrompt(
        key="" if key is None else str(key),
        content="" if content is None else (content if isinstance(content, str) else str(content)),
    )
    session.add(prompt)
    session.flush()
    return {
        "id": prompt.id,
        "created_at": prompt.created_at.isoformat(),
        "updated_at": prompt.updated_at.isoformat(),
    }


@router.patch("/api/system-prompts/{prompt_id}")
async def admin_update_system_prompt(
    prompt_id: int, request: Request, session: Session = Depends(_get_db_session)
) -> dict:
    body = await request.body()
    payload: dict | None = None
    if body:
        try:
            payload = await request.json()
        except Exception:
            payload = None
    payload = payload if isinstance(payload, dict) else {}
    prompt = session.get(SystemPrompt, prompt_id)
    if not prompt:
        raise HTTPException(status_code=404, detail="Prompt not found")
    if "key" in payload:
        value = payload.get("key")
        prompt.key = "" if value is None else str(value)
    if "content" in payload:
        value = payload.get("content")
        prompt.content = "" if value is None else (value if isinstance(value, str) else str(value))
    session.flush()
    return {
        "id": prompt.id,
        "updated_at": prompt.updated_at.isoformat(),
    }


@router.delete("/api/system-prompts/{prompt_id}")
def admin_delete_system_prompt(
    prompt_id: int, session: Session = Depends(_get_db_session)
) -> dict:
    prompt = session.get(SystemPrompt, prompt_id)
    if not prompt:
        raise HTTPException(status_code=404, detail="Prompt not found")
    session.delete(prompt)
    return {"deleted": True}


@router.post("/api/system-prompts/bulk-delete")
async def admin_bulk_delete_system_prompts(
    request: Request, session: Session = Depends(_get_db_session)
) -> dict:
    try:
        payload = _parse_json_payload(await request.json())
    except Exception:
        payload = {}
    ids = _parse_ids(payload)
    if not ids:
        return {"deleted": 0}
    prompts = session.execute(select(SystemPrompt).where(SystemPrompt.id.in_(ids))).scalars().all()
    deleted = len(prompts)
    for prompt in prompts:
        session.delete(prompt)
    return {"deleted": deleted}


@router.post("/api/notes/bulk-delete")
async def admin_bulk_delete_notes(
    request: Request, session: Session = Depends(_get_db_session)
) -> dict:
    try:
        payload = _parse_json_payload(await request.json())
    except Exception:
        payload = {}
    ids = _parse_ids(payload)
    if not ids:
        return {"deleted": 0}
    notes = session.execute(select(AdminNote).where(AdminNote.id.in_(ids))).scalars().all()
    deleted = len(notes)
    for note in notes:
        session.delete(note)
    return {"deleted": deleted}


@router.get("/api/notes")
def admin_notes(limit: int = 50, session: Session = Depends(_get_db_session)) -> dict:
    rows = session.execute(
        select(AdminNote).order_by(AdminNote.created_at.desc()).limit(limit)
    ).scalars()
    notes = []
    for note in rows:
        notes.append(
            {
                "id": note.id,
                "created_at": note.created_at.isoformat(),
                "payload": json.dumps(note.payload, ensure_ascii=False),
            }
        )
    return {"notes": notes}


@router.post("/api/notes")
async def admin_create_note(
    request: Request,
    session: Session = Depends(_get_db_session),
) -> dict:
    raw_payload = None
    body = await request.body()
    if body:
        try:
            raw_payload = await request.json()
        except Exception:
            raw_payload = body.decode("utf-8", errors="ignore")
    payload = raw_payload if isinstance(raw_payload, dict) else {"raw": raw_payload}
    note = AdminNote(payload=payload)
    session.add(note)
    session.flush()
    return {
        "id": note.id,
        "created_at": note.created_at.isoformat(),
    }
