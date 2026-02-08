# Аналитика лендинга: UTM, deep-link и KPI

## 1. UTM-стратегия

Цель: передавать атрибуцию из рекламного источника в Telegram-бот через `start` deep-link и собирать единые фронтовые события для воронки `landing -> telegram -> тариф -> оплата`.

### 1.1 Правила

- Канонические UTM-поля: `utm_source`, `utm_medium`, `utm_campaign`, `utm_content`, `utm_term`.
- Для deep-link в Telegram используются только `source` и `campaign` (чтобы уложиться в ограничение `start`-параметра).
- Если `utm_source` / `utm_campaign` отсутствуют, используются fallback-параметры URL `source` / `campaign`.
- При отсутствии значений — подставляется `na`.
- Значения очищаются до `[a-z0-9_-]`, приводятся к нижнему регистру и обрезаются.

### 1.2 Таблица параметров

| Параметр | Откуда берём | Обязателен | Пример | Куда передаётся |
|---|---|---:|---|---|
| `utm_source` | URL лендинга | Да (или fallback `source`) | `instagram` | `start` payload (`src`) |
| `utm_campaign` | URL лендинга | Да (или fallback `campaign`) | `may_launch` | `start` payload (`cmp`) |
| `utm_medium` | URL лендинга | Нет | `cpc` | фронтовое событие |
| `utm_content` | URL лендинга | Нет | `hero_btn_a` | фронтовое событие |
| `utm_term` | URL лендинга | Нет | `self_realization` | фронтовое событие |
| `placement` | data-атрибут CTA на странице | Да для CTA-событий | `hero_primary` | фронтовое событие + `start` payload (`pl`) |
| `tariff` | data-атрибут кнопки тарифа | Да для события тарифа | `t2` | фронтовое событие + `start` payload (`pl`) |

## 2. Формат Telegram deep-link

Ссылка формируется на фронте автоматически:

`https://t.me/<bot_username>?start=lnd.src_<source>.cmp_<campaign>.pl_<placement>`

Где:
- `source` — из `utm_source` или `source`;
- `campaign` — из `utm_campaign` или `campaign`;
- `placement` — место клика (`hero_primary`, `tariff_t2`, `footer_primary`, `sticky_primary` и т.д.).

Ограничения:
- итоговый `start` payload не длиннее 64 символов;
- при превышении лимита части payload обрезаются на фронте.

## 3. События фронта

Список обязательных событий лендинга:

1. `landing_hero_view` — просмотр hero (через `IntersectionObserver`).
2. `landing_cta_click` — клик по CTA в hero/footer/sticky.
3. `landing_tariff_click` — клик по CTA конкретного тарифа.
4. `landing_faq_reach` — доскролл до блока FAQ.

Для отправки используется универсальный трекер:
- `window.dataLayer.push(...)`, если доступен `dataLayer`;
- `window.gtag('event', ...)`, если подключён `gtag`.

## 4. KPI (фиксируем в MVP)

1. **CTR в Telegram**
   - Формула: `unique(landing_cta_click + landing_tariff_click) / unique(landing_sessions)`.
   - Цель MVP: определить baseline по каналам (`source/campaign`) и выйти на стабильный рост по итерациям.

2. **CR start -> выбор тарифа**
   - Формула: `users_with_tariff_click / users_with_bot_start`.
   - Сегменты: `source`, `campaign`, `tariff`.

3. **CR в оплату**
   - Формула: `users_with_paid / users_with_bot_start`.
   - Для продуктовой диагностики дополнительно считать `users_with_paid / users_with_tariff_click`.

## 5. Валидация событий (обязательные параметры)

### 5.1 Общие обязательные поля для каждого события

- `event` — имя события.
- `event_id` — уникальный id события (frontend UUID/токен).
- `ts` — ISO timestamp события.
- `page` — текущий URL.
- `source` — нормализованный источник (`utm_source|source|na`).
- `campaign` — нормализованная кампания (`utm_campaign|campaign|na`).

### 5.2 Обязательные поля по типам

- Для `landing_cta_click`:
  - `placement` (например, `hero_primary`),
  - `target` (полный Telegram URL),
  - `start_payload`.

- Для `landing_tariff_click`:
  - `tariff` (`t0|t1|t2|t3`),
  - `placement` (`tariff_t0` ... `tariff_t3`),
  - `target`,
  - `start_payload`.

- Для `landing_hero_view` и `landing_faq_reach`:
  - `section` (`hero` / `faq`).

### 5.3 Событие считается невалидным, если

- отсутствует любой обязательный параметр для его типа;
- `source` или `campaign` не переданы (должны быть хотя бы `na`);
- `start_payload` длиннее 64 символов;
- `tariff` не входит в список `t0|t1|t2|t3` для тарифного клика.
