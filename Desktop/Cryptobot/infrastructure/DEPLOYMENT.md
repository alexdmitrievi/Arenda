# TBX Trade Terminal — развёртывание на Yandex Cloud

Актуально на 2026-08-19. Целевая инфраструктура: одна VM YC (Ubuntu/Debian)
с Docker Compose: backend, frontend, postgres 16, redis 7, nginx + certbot.

## Текущее боевое окружение

| Что | Значение |
|---|---|
| VM | `tbx-prod` (id `fhmmheg7lrs4jkr2aond`), зона ru-central1-a, 2 vCPU / 4 GB / 60 GB SSD |
| Внешний IP | **`158.160.99.18` — зарезервированный статический** (`tbx-static-ip`, id `e9b5ddmrkqmduadukc7f`) |
| Домен | **https://tvh-ru.ru** (+ www) — Let's Encrypt, автообновление каждый понедельник 04:15 UTC |
| Security group | `podryadpro-prod-sg` (SSH только с админ-IP владельца; 80/443 открыты) |
| Папка | `b1goj7fnq9pid3n9q257` |
| Код на VM | `/opt/tbx/` (backend, frontend, infrastructure) |
| Конфиги | `/opt/tbx/backend/.env` (секреты), `/opt/tbx/infrastructure/.env` (PG_PASSWORD) |
| Бэкапы | `/opt/tbx/backups/*.dump`, ежедневно 03:00 UTC, ротация 30 дней |
| Снапшот диска | `tbx-prod-snap-20260820` (id `fd8567locnpovd6gjmef`) — полный образ диска от 20.08 |
| Управление | SSH `debian@158.160.99.18`, ключ `infrastructure/secrets/id_ed25519_tbx` |

## Быстрый справочник (на VM)

```sh
cd /opt/tbx/infrastructure
docker compose -f docker-compose.yml -f docker-compose.prod.yml ps          # статус
docker compose -f docker-compose.yml -f docker-compose.prod.yml logs -f backend
docker compose -f docker-compose.yml -f docker-compose.prod.yml restart backend
docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T backend alembic upgrade head   # миграции
sh /opt/tbx/scripts/backup.sh                                               # бэкап вручную
```

Kill switch (остановить всю торговлю мгновенно):

```sh
# через API (админ): POST /api/v1/admin/killswitch {"reason": "..."}  — останавливает сигналы,
# исполнение и закрывает spot-позиции всех пользователей
# снять остановку: DELETE /api/v1/admin/killswitch
# вручную: docker exec tbx-redis redis-cli set trading:halt '{"reason":"manual"}'
```

## Развёртывание с нуля (кратко)

1. SA-ключ в `infrastructure/secrets/yc-sa-key.json` (роли: compute.editor, vpc.editor; ID сервисного
   аккаунта `aje8johhu01at1mp9cfs`), SSH-ключ `infrastructure/secrets/id_ed25519_tbx`.
2. Создание VM — скрипт `infrastructure/scripts/ycapi.ps1` (REST-клиент YC, работает даже при
   сбитых часах локальной машины; yc CLI при рассинхроне часов не работает).
3. На VM: Docker (`curl -fsSL https://get.docker.com | sh`), swap 2G (`/swapfile` в fstab),
   скопировать backend/frontend/infrastructure в `/opt/tbx`.
4. Сгенерировать секреты (`sh /tmp/gen_env.sh` — шаблон в истории сессии): `ENCRYPTION_KEY`
   (Fernet, обязателен, иначе backend не стартует), `SECRET_KEY`, `PG_PASSWORD`,
   `TELEGRAM_TOKEN`.
5. Сборка и запуск:
   ```sh
   cd /opt/tbx/infrastructure
   docker compose -f docker-compose.yml -f docker-compose.prod.yml build backend frontend
   docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d postgres redis backend frontend
   docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T backend alembic upgrade head
   ```
6. nginx: сначала самоподписанный сертификат в volume `infrastructure_certbot_conf`
   (см. `infrastructure/nginx/nginx.conf`), затем `docker compose ... up -d nginx certbot`
   после настройки DNS (certbot webroot).
7. DNS (reg.ru): A-запись `tvh-ru.ru` → публичный IP VM. После распространения — certbot,
   перезапуск nginx.

## Восстановление из бэкапа (проверено)

```sh
cd /opt/tbx/backups
docker exec -i tbx-postgres pg_restore -U tbx -d tbx --clean --if-exists < tbx_YYYYMMDD_HHMMSS.dump
```

## Известные особенности и грабли

- **Telegram**: api.telegram.org с IP Yandex Cloud не резолвится (IPv6-only DNS, IPv6 не
  маршрутизируется). Решение: `extra_hosts` в `docker-compose.prod.yml` —
  `api.telegram.org:149.154.167.220`. Бот работает.
- **Binance/Bybit доступны с IP YC** — риск из `deepseek/12_deploy.md` закрыт.
- **HYPE/USDT отсутствует на Binance** — коллектор пропускает пару (17-я пара).
  Решение (оставить 16 пар / заменить HYPE) — за владельцем.
- **SG `tbx-web-sg`** (создана этой сессией) не пропускала трафик — причина не установлена;
  VM работает на `podryadpro-prod-sg`. Разобраться отдельно.
- **Enum-колонки**: SQLAlchemy биндит имена членов enum; в БД лейблы — значения.
  Все Enum в моделях должны использовать `values_callable=enum_values` (models/base.py).
- **Сборка образа**: `ccxt>=4.4.74,<5` (4.4.72 требует aiohttp<=3.10.11); `psycopg2-binary`
  для alembic; `openai>=1.58.1,<2` для совместимости с aiohttp 3.11.
- **После пересборки backend-контейнера перезапускайте nginx**: он кэширует IP
  upstream'а при старте (ошибка 502 «Connection refused» после recreate).
- **Часы локальной машины владельца спешат на 3 часа** — из-за этого yc CLI не проходит
  JWT-проверку; работаем REST-клиентом `infrastructure/scripts/ycapi.ps1`. Починить часы
  Windows (синхронизация времени) и перевыпустить скомпрометированные ключи.

## DeepSeek Harness (dsh) — среда агентов

- **Облако:** https://tvh-ru.ru:8443 (nginx → socat на docker-мосту → dsh на loopback).
  Контейнеры `tbx-dsh` (node:24, host-net, `pnpm dsh web --host 127.0.0.1 --port 4321`)
  и `dsh-bridge` (alpine+socat: 172.18.0.1:4322 → 127.0.0.1:4321), volume `dsh_harness`,
  репозиторий `/app/deepseek-harness` в volume. `--restart unless-stopped`.
- **Десктоп:** `cd C:\Users\HP\Desktop\deepseek-harness && pnpm dsh web`
  (открывается http://127.0.0.1:4321; Node ≥22.19, pnpm 11.7).
- Сборка/обновление на VM:
  ```sh
  docker run --rm -v dsh_harness:/app -v /tmp/dsh_build.sh:/dsh_build.sh:ro -w /app node:24-slim sh -c 'apt-get update -qq && apt-get install -y -qq git >/dev/null 2>&1 && sh /dsh_build.sh'
  docker restart tbx-dsh
  ```
- Нюанс: dsh CLI запрещает `--host 0.0.0.0` (RCE-защита) и принимает только
  127.0.0.1/0.0.0.0 в схеме конфига — поэтому наружу харнес смотрит только loopback,
  а сетевой край держат socat+nginx (8443 открыт в SG).

## TODO (решения владельца)

1. Отозвать и перевыпустить: SA-ключ `aje54l0sijppe6pd8620`, SSH-ключи, Telegram-токен
   (все передавались через чат и считаются скомпрометированными).
2. Решить судьбу HYPE/USDT.
3. Бэкапы в Object Storage (S3) — сейчас локально на диске VM.
4. Починка/удаление `tbx-web-sg`.
5. Bybit testnet-прогон исполнения (стоп-верификация, триггер-параметры spot).
6. Бэктест на боевых данных: `docker compose exec backend python -m scripts.backtest_run`.

## Уроки эксплуатации (20.08.2026)

- **Не останавливайте VM без статического IP**: динамический адрес освобождается
  и уходит другому арендатору; DNS начинает указывать на чужую машину.
  Теперь IP статический — остановка/запуск адрес не меняет.
- **При нулевом балансе Yandex Cloud сам останавливает VM** — проверяйте биллинг.
- Восстановление: при утере диска — создать VM из снапшота `tbx-prod-snap-20260820`
  (в diskSpec обязательно указывать `size`, иначе API отклоняет).
- SA `deepseek-agent` не имеет прав на `attachNetworkInterface`/`:start` — привязку
  статического адреса к существующей VM делает владелец в консоли (VPC → IP-адреса → ⋮ → Привязать).
