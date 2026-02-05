from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import (
    AdminNote,
    FeedbackMessage,
    Order,
    OrderStatus,
    Report,
    User,
    UserProfile,
)
from app.db.session import get_session_factory


router = APIRouter(prefix="/admin", tags=["admin"])


def _require_admin(request: Request) -> None:
    if not settings.admin_api_key:
        raise HTTPException(status_code=503, detail="ADMIN_API_KEY is not configured")
    provided_key = request.headers.get("x-admin-api-key")
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


@router.get("", response_class=HTMLResponse)
def admin_ui() -> str:
    return """
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
    }
    th, td {
      text-align: left;
      padding: 6px 8px;
      border-bottom: 1px solid #2a2f3a;
      vertical-align: top;
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
  </header>
  <main>
    <aside class="sidebar">
      <div class="muted">Разделы админки</div>
      <nav>
        <button class="nav-button" data-section="overview">Сводка</button>
        <button class="nav-button" data-section="health">Состояние сервиса</button>
        <button class="nav-button" data-section="orders">Заказы</button>
        <button class="nav-button" data-section="reports">Отчёты</button>
        <button class="nav-button" data-section="users">Пользователи</button>
        <button class="nav-button" data-section="feedback">Обратная связь</button>
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
      <section data-panel="feedback">
        <h2>Обратная связь</h2>
        <div class="row table-controls">
          <input id="feedbackSearch" class="table-search" type="text" placeholder="Поиск по любому столбцу" />
          <button class="secondary" onclick="clearTableFilters('feedback')">Сбросить</button>
          <button class="secondary" onclick="loadFeedback()">Обновить</button>
        </div>
        <div id="feedback" class="muted">Загрузка...</div>
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
  <script>
    const apiKeyInput = document.getElementById("apiKey");
    apiKeyInput.value = localStorage.getItem("adminApiKey") || "";

    function saveKey() {
      localStorage.setItem("adminApiKey", apiKeyInput.value.trim());
      alert("Ключ сохранён локально в браузере.");
    }

    function headers() {
      return {"x-admin-api-key": apiKeyInput.value.trim()};
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

    const tableData = {
      orders: [],
      reports: [],
      users: [],
      feedback: [],
      notes: [],
    };

    const tableStates = {
      orders: {search: "", sortKey: null, sortDir: "asc"},
      reports: {search: "", sortKey: null, sortDir: "asc"},
      users: {search: "", sortKey: null, sortDir: "asc"},
      feedback: {search: "", sortKey: null, sortDir: "asc"},
      notes: {search: "", sortKey: null, sortDir: "asc"},
    };

    const tableConfigs = {
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
          {label: "Действия", key: null, sortable: false, render: (order) => `
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
      feedback: {
        targetId: "feedback",
        columns: [
          {label: "ID", key: "id", sortable: true},
          {label: "Пользователь", key: "telegram_user_id", sortable: true},
          {label: "Статус", key: "status", sortable: true},
          {label: "Сообщение", key: "text", sortable: true},
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
            : normalizeValue(row[column.key] ?? "—");
          return `<td>${cellValue || "—"}</td>`;
        }).join("");
        return `<tr>${cells}</tr>`;
      }).join("");
      target.innerHTML = `<table><thead><tr>${header}</tr></thead><tbody>${body}</tbody></table>`;
    }

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

    async function loadFeedback() {
      try {
        const data = await fetchJson("/feedback");
        tableData.feedback = data.feedback || [];
        renderTableForKey("feedback");
      } catch (error) {
        document.getElementById("feedback").textContent = error.message;
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
      orders: loadOrders,
      reports: loadReports,
      users: loadUsers,
      feedback: loadFeedback,
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

    function showPanel(name) {
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

    showPanel("overview");
  </script>
</body>
</html>
"""


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


@router.get("/api/feedback")
def admin_feedback(limit: int = 50, session: Session = Depends(_get_db_session)) -> dict:
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
    return {"feedback": feedback}


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
