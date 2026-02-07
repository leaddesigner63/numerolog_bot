from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import (
    AdminNote,
    FeedbackMessage,
    LLMApiKey,
    Order,
    OrderStatus,
    Report,
    SystemPrompt,
    User,
    UserProfile,
)
from app.db.session import get_session_factory


router = APIRouter(prefix="/admin", tags=["admin"])


def _extract_admin_key(request: Request) -> str | None:
    provided_key = request.headers.get("x-admin-api-key")
    if not provided_key:
        auth_header = request.headers.get("authorization")
        if auth_header:
            if auth_header.lower().startswith("bearer "):
                provided_key = auth_header[7:]
            else:
                provided_key = auth_header
    if not provided_key:
        provided_key = request.cookies.get("admin_api_key")
    if not provided_key:
        provided_key = request.query_params.get("key")
    return provided_key


def _require_admin(request: Request) -> None:
    if not settings.admin_api_key:
        raise HTTPException(status_code=503, detail="ADMIN_API_KEY is not configured")
    provided_key = _extract_admin_key(request)
    if not provided_key:
        raise HTTPException(status_code=401, detail="Missing admin API key")
    if provided_key != settings.admin_api_key:
        raise HTTPException(status_code=403, detail="Invalid admin API key")


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
    <p>Введите ADMIN_API_KEY, чтобы открыть панель управления.</p>
    {alert}
    <input id="adminKey" type="password" placeholder="ADMIN_API_KEY" autocomplete="off"/>
    <button id="submitKey">Открыть</button>
  </div>
  <script>
    const input = document.getElementById("adminKey");
    const button = document.getElementById("submitKey");
    function submitKey() {{
      const key = input.value.trim();
      if (!key) {{
        return;
      }}
      const url = new URL(window.location.href);
      url.searchParams.set("key", key);
      window.location.replace(url.toString());
    }}
    button.addEventListener("click", submitKey);
    input.addEventListener("keydown", (event) => {{
      if (event.key === "Enter") {{
        submitKey();
      }}
    }});
  </script>
</body>
</html>
"""


@router.get("", response_class=HTMLResponse)
def admin_ui(request: Request) -> HTMLResponse:
    if not settings.admin_api_key:
        return HTMLResponse(
            _admin_login_html("ADMIN_API_KEY не настроен на сервере."),
            status_code=503,
        )
    provided_key = _extract_admin_key(request)
    if not provided_key:
        return HTMLResponse(_admin_login_html(), status_code=401)
    if provided_key != settings.admin_api_key:
        return HTMLResponse(_admin_login_html("Неверный ключ доступа."), status_code=403)
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
    section[data-panel] {
      display: none;
    }
    section[data-panel].active {
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
    }
    .table-search {
      min-width: 240px;
      flex: 1 1 240px;
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
      font-size: 13px;
      table-layout: fixed;
    }
    th, td {
      text-align: left;
      padding: 6px 8px;
      border-bottom: 1px solid #2a2f3a;
      vertical-align: top;
      word-break: break-word;
    }
    td.copyable-cell {
      cursor: copy;
      transition: background 0.15s ease-in-out;
    }
    td.copyable-cell:hover {
      background: rgba(59, 130, 246, 0.12);
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
    .feedback-text {
      max-height: 220px;
      overflow-y: auto;
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
  </style>
</head>
<body>
  <header>
    <h1>Админка Numerolog Bot</h1>
    <div class="row">
      <div class="field">
        <label for="apiKey">ADMIN_API_KEY</label>
        <input id="apiKey" type="password" placeholder="Введите ключ" />
      </div>
      <div class="field" style="align-self: flex-end;">
        <button class="secondary" onclick="saveKey()">Сохранить ключ</button>
      </div>
    </div>
    <div id="apiKeyStatus" class="api-key-status"></div>
  </header>
  <main>
    <aside class="sidebar">
      <div class="muted">Разделы админки</div>
      <nav>
        <button class="nav-button" data-section="overview">Сводка</button>
        <button class="nav-button" data-section="health">Состояние сервиса</button>
        <button class="nav-button" data-section="llm-keys">LLM ключи</button>
        <button class="nav-button" data-section="orders">Заказы</button>
        <button class="nav-button" data-section="reports">Отчёты</button>
        <button class="nav-button" data-section="users">Пользователи</button>
        <button class="nav-button" data-section="feedback-inbox">Обратная связь</button>
        <button class="nav-button" data-section="system-prompts">Системные промпты</button>
        <button class="nav-button" data-section="notes">Админ-заметки</button>
      </nav>
    </aside>
    <div class="content">
      <section data-panel="overview">
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
          <div id="llmKeysActive" class="muted">Загрузка...</div>
        </div>
        <div class="tab-panel" data-llm-panel="inactive">
          <div class="row table-controls">
            <input id="llmKeysInactiveSearch" class="table-search" type="text" placeholder="Поиск по неактивным ключам" />
            <button class="secondary" onclick="clearTableFilters('llmKeysInactive')">Сбросить</button>
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
        <div class="row table-controls">
          <input id="feedbackInboxSearch" class="table-search" type="text" placeholder="Поиск по любому столбцу" />
          <button class="secondary" onclick="clearTableFilters('feedbackInbox')">Сбросить</button>
          <button class="secondary" onclick="loadFeedbackInbox()">Обновить</button>
        </div>
        <div id="feedbackInbox" class="muted">Загрузка...</div>
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
        <div id="notes" class="muted">Загрузка...</div>
      </section>
    </div>
  </main>
  <div id="copyToast" class="copy-toast">Скопировано в буфер обмена</div>
  <script>
    const autoRefreshSeconds = Number("__ADMIN_AUTO_REFRESH_SECONDS__") || 0;
    const apiKeyInput = document.getElementById("apiKey");
    const apiKeyStatus = document.getElementById("apiKeyStatus");

    function readStoredAdminKey() {
      try {
        return localStorage.getItem("adminApiKey") || "";
      } catch (error) {
        return "";
      }
    }

    function storeAdminKey(value) {
      try {
        localStorage.setItem("adminApiKey", value);
        return true;
      } catch (error) {
        return false;
      }
    }

    function setApiKeyStatus(message, tone = "") {
      if (!apiKeyStatus) {
        return;
      }
      apiKeyStatus.textContent = message || "";
      apiKeyStatus.classList.remove("ok", "danger");
      if (tone) {
        apiKeyStatus.classList.add(tone);
      }
    }

    apiKeyInput.value = readStoredAdminKey();

    function saveKey() {
      const keyValue = apiKeyInput.value.trim();
      const stored = storeAdminKey(keyValue);
      if (stored) {
        setApiKeyStatus("Ключ сохранён. Данные обновлены.", "ok");
      } else {
        setApiKeyStatus("Не удалось сохранить ключ в localStorage. Ключ действует до перезагрузки.", "danger");
      }
      const loader = loaders[activePanel] || loadOverview;
      if (loader) {
        loader();
      }
    }

    function headers() {
      const key = apiKeyInput.value.trim();
      if (!key) {
        return {};
      }
      return {
        "x-admin-api-key": key,
        "Authorization": `Bearer ${key}`,
      };
    }

    async function fetchJson(path, options = {}) {
      const response = await fetch(`/admin/api${path}`, {
        ...options,
        headers: {
          "Content-Type": "application/json",
          ...headers(),
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
          ...headers(),
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
          <div class="message">ENV: ${data.env} • Admin API: ${data.admin_api_enabled}</div>
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

    async function deleteLlmKey(keyId) {
      if (!confirm("Удалить ключ?")) {
        return;
      }
      try {
        await fetchJson(`/llm-keys/${keyId}`, {method: "DELETE"});
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
      systemPrompts: {search: "", sortKey: null, sortDir: "asc"},
      notes: {search: "", sortKey: null, sortDir: "asc"},
    };

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
          {
            label: "Сумма",
            key: "amount",
            sortable: true,
            sortValue: (order) => order.amount,
            render: (order) => `${normalizeValue(order.amount)} ${normalizeValue(order.currency)}`.trim(),
          },
          {label: "Действия", key: null, sortable: false, copyable: false, render: (order) => `
            <button class="secondary" onclick="markOrder(${order.id}, 'paid')">Оплачен</button>
            <button class="secondary" onclick="markOrder(${order.id}, 'failed')">Ошибка</button>
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
          {label: "ID", key: "id", sortable: true},
          {label: "Пользователь", key: "telegram_user_id", sortable: true},
          {label: "User ID", key: "user_id", sortable: true},
          {label: "Статус", key: "status", sortable: true},
          {label: "Сообщение", key: "text", sortable: true, render: renderFeedbackText},
          {label: "Отправлено", key: "sent_at", sortable: true},
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
            render: (prompt) => `<pre class="muted prompt-preview">${escapeHtml(prompt.content)}</pre>`,
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
            <pre class="muted">${escapeHtml(note.payload)}</pre>
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

    function escapeHtml(value) {
      return normalizeValue(value)
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll("\"", "&quot;")
        .replaceAll("'", "&#39;");
    }

    function renderFeedbackText(row) {
      const text = normalizeValue(row.text);
      if (!text) {
        return "—";
      }
      return `<pre class="muted feedback-text">${escapeHtml(text)}</pre>`;
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
      const header = config.columns.map((column) => {
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
      const body = filteredRows.map((row) => {
        const cells = config.columns.map((column) => {
          const cellValue = column.render
            ? column.render(row)
            : escapeHtml(row[column.key] ?? "—");
          const isCopyable = column.copyable !== false;
          const cellClass = isCopyable ? "copyable-cell" : "";
          return `<td class="${cellClass}">${cellValue || "—"}</td>`;
        }).join("");
        return `<tr>${cells}</tr>`;
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
    const promptKeyOptions = new Set(["PROMPT_T0", "PROMPT_T1", "PROMPT_T2", "PROMPT_T3"]);
    let promptEditingId = null;

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
      document.getElementById("promptContent").value = "";
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
      document.getElementById("promptContent").value = normalizeValue(prompt.content);
      showPanel("system-prompts");
    }

    async function saveSystemPrompt() {
      const key = promptKeySelect.value === "CUSTOM" ? promptKeyCustom.value : promptKeySelect.value;
      const content = document.getElementById("promptContent").value;
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

    async function loadNotes() {
      try {
        const data = await fetchJson("/notes");
        tableData.notes = data.notes || [];
        renderTableForKey("notes");
      } catch (error) {
        document.getElementById("notes").textContent = error.message;
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

    const sectionButtons = document.querySelectorAll("[data-section]");
    const panels = document.querySelectorAll("[data-panel]");
    const loaders = {
      overview: loadOverview,
      health: loadHealth,
      "llm-keys": loadLlmKeys,
      orders: loadOrders,
      reports: loadReports,
      users: loadUsers,
      "feedback-inbox": loadFeedbackInbox,
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
    if request.query_params.get("key"):
        response.set_cookie("admin_api_key", provided_key, httponly=True, samesite="Lax")
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
        "admin_api_enabled": bool(settings.admin_api_key),
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }


def _mask_key(value: str | None) -> str:
    if not value:
        return ""
    if len(value) <= 6:
        return "*" * len(value)
    return f"{value[:2]}***{value[-4:]}"


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
    orders = []
    for order, user in rows:
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
                "birth_date": profile.birth_date if profile else None,
            }
        )
    return {"users": users}


def _load_feedback_messages(session: Session, *, limit: int) -> list[dict]:
    rows = session.execute(
        select(FeedbackMessage, User)
        .join(User, User.id == FeedbackMessage.user_id)
        .order_by(FeedbackMessage.sent_at.desc())
        .limit(limit)
    ).all()
    feedback = []
    for message, user in rows:
        feedback.append(
            {
                "id": message.id,
                "user_id": message.user_id,
                "telegram_user_id": user.telegram_user_id if user else None,
                "text": message.text,
                "status": message.status.value,
                "sent_at": message.sent_at.isoformat() if message.sent_at else None,
            }
        )
    return feedback


@router.get("/api/feedback")
def admin_feedback(limit: int = 50, session: Session = Depends(_get_db_session)) -> dict:
    return {"feedback": _load_feedback_messages(session, limit=limit)}


@router.get("/api/feedback/inbox")
def admin_feedback_inbox(limit: int = 50, session: Session = Depends(_get_db_session)) -> dict:
    return {"feedback": _load_feedback_messages(session, limit=limit)}


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
