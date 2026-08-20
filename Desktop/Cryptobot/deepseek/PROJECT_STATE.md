# PROJECT_STATE.md — TBX Trade Terminal

Состояние проекта, проверенное по коду 2026-08-19 (сессия «рекон» + hardening).
Код — источник истины, этот файл — его отражение.

## Верификация состояния

| Проверка | Результат |
|---|---|
| `cd backend && python -m pytest tests/ -q` | 84 passed (48 базовых + 36 новых после hardening) |
| `python -c "from app.main import app"` | импортируется чисто |
| `alembic heads` | 007_trade_execution_hardening (head) |
| Миграции | 001_create_users … 007_trade_execution_hardening (добавлена этой сессией) |

## Пять вопросов рекон и ответы (до изменений сессии)

1. **Где размещается ордер и может ли позиция оказаться без стопа.**
   `app/api/v1/signals.py:316-318` — `exchange.create_order(symbol, "market", side, size, None, order_params)`,
   `stopLoss` прикрепляется в том же вызове (`signals.py:311`). Отказ биржи → CANCELLED + 502
   (`signals.py:319-323`). **Дыра:** после fill не проверялось, что стоп реально привязан на бирже.
   Исправлено этой сессией (`app/services/trading/execution.py::ensure_stop_attached`).

2. **Что происходит в БД при срабатывании стопа на бирже.**
   Ничего не происходило: синка с биржей не было, Trade оставался OPEN навсегда.
   Исправлено этой сессией: `position_sync_loop` в `app/services/scheduler.py` + `app/services/trading/sync.py`.

3. **Могут ли быть подключены ключи с правом вывода.**
   Могли: `app/api/v1/users.py:62-81` сохранял ключи без проверки прав.
   Исправлено этой сессией: проверка `GET /v5/user/query-api` при сохранении, ключи с
   Withdrawal/Transfer отвергаются (`app/services/trading/key_permissions.py`).

4. **Есть ли способ мгновенно остановить торговлю.**
   Не было: `emergency_close_all` (`app/services/trading/engine.py:153-178`) — мёртвый код без вызовов;
   флаг `Strategy.is_active` не влиял на генерацию сигналов.
   Исправлено этой сессией: глобальный halt-флаг в Redis (`trading:halt`) + админ-эндпоинты
   `/api/v1/admin/killswitch` (GET/POST/DELETE), при включении — закрытие всех spot-позиций.

5. **Измерялась ли доходность стратегии.**
   Не измерялась: `backtest()` вызывался только из юнит-тестов на синтетике
   (`tests/test_smc_strategy.py:142,302,312`).
   Исправлено этой сессией: `backend/scripts/backtest_run.py` — честный бэктест на реальных
   1h-данных Binance по 17 парам, отчёт в `backend/reports/backtest_report.md`.

## Расхождения с AGENTS.md, найденные в коде

1. **П.8 «PnL and fees on close»** — до сессии работало только при ручном закрытии; автосинка
   SL-закрытий с биржей не было. Исправлено (position_sync_loop).
2. **Инвариант «позиция не существует без стопа»** — держался только на доверии к параметру
   `stopLoss`; постверификация отсутствовала. Исправлено (ensure_stop_attached + аварийное
   закрытие позиции, если стоп не удалось привязать).
3. **Сверка PENDING** слепо переводила зависшие сделки в CANCELLED без проверки биржи.
   Исправлено: проверка по `clientOrderId` на бирже перед решением.

Остальное в AGENTS.md соответствует коду: 17 пар, 48 тестов, миграции, бот не торгует сам,
гейты CHOP/BTC/macro на месте.

## Изменения этой сессии (hardening)

- Миграция `007_trade_execution_hardening`: `trades.client_order_id`, `trades.stop_order_id`, `trades.tp_order_id`, `trades.stop_loss`, `trades.take_profit`.
- Исполнение: clientOrderId для сверки, принудительный RR ≥ 3 и риск 2% (настраиваемый
  0.1–10% на пользователя), проверка стопа после fill с fallback-размещением и аварийным
  закрытием позиции при неудаче.
- Позиции: цикл синхронизации с биржей (60с), закрытие Trade по реальным fill и комиссиям.
- Kill switch: Redis-флаг + админ-эндпоинты + закрытие всех spot-позиций.
- Ключи: проверка прав Bybit при сохранении (fail-closed).
- Бэктест: скрипт прогона на реальных данных.

## Изменения сессии «фьючерсы + стиль канала» (2026-08-20)

- **Исполнение переведено на USDT-M бессрочные фьючерсы Bybit** (`app/services/trading/bybit.py`):
  маппинг `BTC/USDT` → `BTC/USDT:USDT`, `BYBIT_TESTNET`/`BYBIT_LEVERAGE`/`BYBIT_MARGIN_MODE`
  (cross, 1x по умолчанию), установка плеча/маржи перед ордером, reduceOnly-закрытия.
- Решения владельца: **только BUY** в реальном исполнении (SELL — только paper),
  риск 2%, пары пока прежние (16 на Binance), лимит ширины стопа — нет.
- **Процентная формула позиции из калькулятора риска** (`position_metrics`):
  объём$ = депозит × риск% / стоп-зона% (пример владельца: $1000 × 2% / 7% = $285.71 ✓),
  плечо в формуле не участвует; блок метрик (депозит, риск$, зона стопа %, объём $, RR,
  маржа) отдаётся в ответе исполнения и paper-режиме.
- **Volume Profile фактор** в SMC-движке (`detect_volume_profile`): POC/VAH/VAL за 120 баров,
  цена в зоне объёма → +8 confidence + причина (аналог «плотки» из @CryptoSizeRU).
- Telegram-сообщение сигнала: добавлены «Стоп-зона: N%» и «RR: 1:X».
- Права ключей: принимаются ContractTrade (Order/Position) для фьючерсов, Wallet-права
  по-прежнему отвергаются.
- Kill switch: закрытие открытых фьючерсных позиций (reduceOnly, включая шорты).
- Читалки канала: `backend/scripts/channel_web.py` (t.me web-preview через socks-прокси —
  MTProto с домашней сети/VM заблокирован ТСПУ) + `channel_reader.py` (telethon, сессия).
- Анализ 50 постов @CryptoSizeRU: `deepseek/cryptosize_analysis.md`.

## Изменения сессии «ликвидность + 5m + ИИ + UI» (2026-08-20, вечер)

- **RR-мандат понижен до 2:1** (решение владельца) — движок (`min_rr_ratio=2.0`),
  исполнение (`MIN_RR_RATIO=2.0`), AGENTS.md и тесты обновлены.
- **Фильтр ликвидности**: тикер-поток Binance пишет `quoteVolume` в Redis;
  сигнал публикуется только при 24ч-объёме ≥ **$300M** (`MIN_DAILY_VOLUME_USD`,
  fail-closed: нет данных — нет сигнала).
- **5m arm-refine**: коллектор подписан на свечи 5m; 1h-сигнал вооружается и
  публикуется только после 5m-подтверждения (BOS/свип) в окне **6 часов**;
  вход уточняется по 5m-структуре; RR < 2 или таймаут → сброс
  (`app/services/market_data/m5_trigger.py`).
- **DeepSeek-аналитик (Вариант A)**: `app/services/ai/analyst.py` — свечи 1h/5m +
  факторы движка → текстовая аналитика в metadata сигнала, Telegram и UI; никогда
  не предлагает уровни; fail-open (ошибка API не блокирует сигнал). Ключ в `backend/.env`.
- **UI**: только BUY-сигналы, русские подписи, крупный инструмент, блок риска
  (зона стопа %, RR, TP1-3), кнопки «Бумажно»/«Реально», раскрываемая «Аналитика ИИ».
- **SW-фикс**: кэш service worker'а `tbx-v2` + network-first для чанков (лечит
  «Failed to fetch» после деплоев).
- Тесты: **114 passed**. README.md создан (текущее состояние зафиксировано).

## Что осталось непроверенным

- Реальное поведение Bybit spot с параметрами триггеров (`triggerPrice`, `stopLoss` в
  create_order): покрыто моками, живой прогон требует тестнет-ключей владельца.
- Бэктест ещё не запущен на боевых данных — на VM: `docker compose -f docker-compose.yml -f docker-compose.prod.yml exec backend python -m scripts.backtest_run` (скрипт не попал в образ текущего деплоя — добавить при следующей сборке).
- Результаты kill switch на живом аккаунте.

## Развёртывание в Yandex Cloud (2026-08-19 → 20)

VM `tbx-prod` (2 vCPU / 4 GB / 60 GB), **статический IP `158.160.99.18`**, зона ru-central1-a.
Стек: backend (uvicorn) + frontend (Next.js) + postgres 16 + redis 7 + nginx.
**Сайт в проде: https://tvh-ru.ru (+www), сертификат Let's Encrypt, автопродление (cron еженедельно).**
Миграции 001–007 применены, Telegram-бот в polling (extra_hosts api.telegram.org→149.154.167.220),
сигнальный движок работает (16/17 пар, HYPE/USDT нет на Binance), Binance/Bybit доступны с IP VM.
Бэкапы: ежедневный pg_dump, ротация 30 дней, восстановление протестировано.
Снапшот диска `tbx-prod-snap-20260820` — точка восстановления. Подробности: `infrastructure/DEPLOYMENT.md`.

Открытые вопросы владельцу: ротация скомпрометированных ключей (SA/SSH/Telegram), судьба
HYPE/USDT, разбор неработающей SG `tbx-web-sg`, пополнение биллинга YC (VM останавливались
при нулевом балансе), права SA на привязку адресов.
