# План миграции AI News Digest Bot на Oracle Cloud Free Tier

## Содержание

1. [Обзор и предпосылки](#1-обзор-и-предпосылки)
2. [Настройка VM в Oracle Cloud](#2-настройка-vm-в-oracle-cloud)
3. [Деплой приложения](#3-деплой-приложения)
4. [Telethon сессия](#4-telethon-сессия)
5. [SQLite и данные](#5-sqlite-и-данные)
6. [Режим работы: polling + scheduler](#6-режим-работы-polling--scheduler)
7. [Мониторинг и логи](#7-мониторинг-и-логи)
8. [Обновление кода](#8-обновление-кода)
9. [Сравнение с GitHub Actions](#9-сравнение-с-github-actions)
10. [Риски и fallback](#10-риски-и-fallback)

---

## 1. Обзор и предпосылки

**Что мигрируем:** Python 3.12+ async бот (`ai-news-digest`), который:
- Скрапит Telegram-каналы через Telethon (MTProto, нужна persistent сессия)
- Хранит данные в SQLite (`data/digest.db`)
- Скачивает изображения в `data/media/`
- Делает HTTP-запросы к OpenRouter для LLM-суммаризации
- Работает в двух режимах: интерактивный бот (polling + APScheduler) или one-shot CLI

**Откуда мигрируем:** GitHub Actions (cron `10 6 * * *` / `10 16 * * *`, одноразовый запуск `run-slot`, нет persistent state)

**Куда мигрируем:** Oracle Cloud Always Free Tier, ARM VM.Standard.A1.Flex

**Целевой режим работы:** Interactive bot mode (polling + встроенный scheduler). Один процесс, systemd unit, без webhook, без ingress-портов.

---

## 2. Настройка VM в Oracle Cloud

### 2.1. Создание аккаунта

1. Зарегистрироваться на [cloud.oracle.com](https://cloud.oracle.com/)
2. Выбрать Home Region (ближайший к серверам Telegram, например Frankfurt `eu-frankfurt-1` или Amsterdam `eu-amsterdam-1`)
3. Always Free включается автоматически после создания аккаунта

> **Важно:** Home Region нельзя изменить после создания аккаунта. ARM Free Tier доступен не во всех регионах. Frankfurt и Amsterdam обычно работают.

### 2.2. Настройка сети (VCN)

```
OCI Console → Networking → Virtual Cloud Networks → Start VCN Wizard → Create VCN with Internet Connectivity
```

Параметры:
- **VCN Name:** `digest-bot-vcn`
- **CIDR Block:** `10.0.0.0/16` (по умолчанию)
- Wizard создаст public subnet + private subnet + Internet Gateway + NAT Gateway

#### Security List для public subnet

Оставить **только**:
- **Ingress:** TCP port 22 (SSH) — ограничить Source CIDR до домашнего IP или VPN (`YOUR_IP/32`)
- **Egress:** All Protocols, 0.0.0.0/0 (бот ходит наружу к Telegram API, OpenRouter, RSS-фидам)

Никакого ingress кроме SSH — бот использует polling, не webhook.

```
OCI Console → Networking → Virtual Cloud Networks → digest-bot-vcn → Public Subnet → Security Lists → Default Security List
```

Удалить все ingress-правила кроме SSH. Egress оставить `0.0.0.0/0 All Protocols`.

### 2.3. Создание инстанса

```
OCI Console → Compute → Instances → Create Instance
```

| Параметр | Значение |
|----------|----------|
| **Name** | `digest-bot` |
| **Availability Domain** | любой из доступных (если один выдаёт "Out of capacity", попробовать другой) |
| **Shape** | VM.Standard.A1.Flex (Ampere ARM) |
| **OCPUs** | 1 (достаточно; Free Tier даёт до 4) |
| **Memory** | 6 GB (достаточно; Free Tier даёт до 24 GB) |
| **Image** | Canonical Ubuntu 24.04 (aarch64) |
| **VCN** | `digest-bot-vcn` |
| **Subnet** | Public subnet |
| **Public IP** | Assign a public IPv4 address |
| **SSH Key** | Вставить свой `~/.ssh/id_ed25519.pub` |
| **Boot Volume** | 50 GB (Free Tier — до 200 GB total) |

> **"Out of capacity" error:** ARM инстансы на Free Tier часто недоступны. Решения:
> - Попробовать другой Availability Domain
> - Попробовать минимальную конфигурацию (1 OCPU / 6 GB)
> - Повторять попытку через 15-30 минут (скрипт ниже)
> - Использовать OCI CLI для автоматизации:
> ```bash
> # Повторяющаяся попытка создания (запустить на локальной машине)
> while true; do
>   oci compute instance launch \
>     --availability-domain "XXXX:EU-FRANKFURT-1-AD-1" \
>     --compartment-id "ocid1.compartment.oc1..XXXX" \
>     --shape "VM.Standard.A1.Flex" \
>     --shape-config '{"ocpus": 1, "memoryInGBs": 6}' \
>     --image-id "ocid1.image.oc1.eu-frankfurt-1.XXXX" \
>     --subnet-id "ocid1.subnet.oc1.eu-frankfurt-1.XXXX" \
>     --assign-public-ip true \
>     --ssh-authorized-keys-file ~/.ssh/id_ed25519.pub \
>     && break
>   echo "Out of capacity, retrying in 60s..."
>   sleep 60
> done
> ```

### 2.4. Первое подключение

```bash
ssh -i ~/.ssh/id_ed25519 ubuntu@<PUBLIC_IP>
```

### 2.5. Первоначальная настройка сервера

```bash
# Обновление системы
sudo apt update && sudo apt upgrade -y

# Установка Python 3.12+ и зависимостей
sudo apt install -y python3 python3-venv python3-pip git sqlite3

# Проверка версии
python3 --version  # Должно быть >= 3.12

# Настройка firewall (iptables на Oracle Ubuntu уже есть)
# Oracle Linux по умолчанию блокирует всё кроме SSH через iptables.
# На Ubuntu minimal image правила уже настроены через iptables.
# Убедиться, что egress открыт:
sudo iptables -L -n  # Проверить текущие правила

# Если используется Ubuntu 24.04, iptables может быть пустым —
# защита обеспечивается Security List на уровне OCI VCN.

# Настройка swap (опционально, для 6 GB RAM не критично, но полезно)
sudo fallocate -l 2G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab

# Настройка timezone
sudo timedatectl set-timezone Europe/Moscow
```

---

## 3. Деплой приложения

### 3.1. Клонирование репозитория

```bash
# Создать директорию
sudo mkdir -p /opt/ai-news-digest-bot
sudo chown ubuntu:ubuntu /opt/ai-news-digest-bot

# Клонировать (если приватный репо — настроить deploy key или HTTPS token)
git clone https://github.com/<YOUR_USER>/ai-news-digest-bot.git /opt/ai-news-digest-bot

# Если приватный репо — через SSH deploy key:
# 1. Сгенерировать ключ на сервере:
ssh-keygen -t ed25519 -f ~/.ssh/github_deploy -N ""
# 2. Добавить публичный ключ в GitHub → Settings → Deploy Keys
# 3. Настроить SSH config:
cat >> ~/.ssh/config << 'EOF'
Host github.com
    IdentityFile ~/.ssh/github_deploy
    IdentitiesOnly yes
EOF
# 4. Клонировать:
git clone git@github.com:<YOUR_USER>/ai-news-digest-bot.git /opt/ai-news-digest-bot
```

### 3.2. Установка в venv

```bash
cd /opt/ai-news-digest-bot
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e .
```

Проверка:
```bash
.venv/bin/ai-news-digest --help
```

### 3.3. Файл .env с секретами

```bash
# Создать .env (не коммитить в git!)
cat > /opt/ai-news-digest-bot/.env << 'ENVEOF'
BOT_TOKEN=123456789:AAxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
ADMIN_CHAT_ID=123456789
TG_API_ID=12345678
TG_API_HASH=abcdef1234567890abcdef1234567890
TG_PHONE=+79999999999

# StringSession — рекомендуемый способ для VPS (см. раздел 4)
TG_SESSION_STRING=1BVtsOHxxxxxxxxxxxxxxxxxx...

INTERACTIVE_BOT=true
TIMEZONE=Europe/Moscow
MORNING_HOUR=9
EVENING_HOUR=19

DB_PATH=data/digest.db
MEDIA_DIR=data/media
SOURCES_PATH=config/default_sources.yaml
MAX_IMAGES_PER_DIGEST=10
DEFAULT_DIGEST_PARAGRAPHS=5

LLM_BACKEND=openrouter
OPENROUTER_API_KEY=sk-or-v1-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
OPENROUTER_MODEL=stepfun/step-3.5-flash:free
LLM_FALLBACK_MODELS=meta-llama/llama-3.3-70b-instruct:free,mistralai/mistral-small-3.1-24b-instruct:free
ENVEOF

# Ограничить права доступа
chmod 600 /opt/ai-news-digest-bot/.env
```

### 3.4. Создание директорий для данных

```bash
mkdir -p /opt/ai-news-digest-bot/data/media
```

### 3.5. Systemd unit

В репозитории уже есть шаблон `deploy/systemd/ai-news-digest.service`. Установка:

```bash
# Вариант 1: использовать готовый скрипт
cd /opt/ai-news-digest-bot
sudo APP_DIR=/opt/ai-news-digest-bot SERVICE_USER=ubuntu bash scripts/install_systemd_service.sh

# Вариант 2: вручную
sudo tee /etc/systemd/system/ai-news-digest.service << 'EOF'
[Unit]
Description=AI News Digest Telegram Bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=ubuntu
Group=ubuntu
WorkingDirectory=/opt/ai-news-digest-bot
EnvironmentFile=/opt/ai-news-digest-bot/.env
ExecStart=/opt/ai-news-digest-bot/.venv/bin/ai-news-digest bot
Restart=always
RestartSec=5
TimeoutStopSec=20

# Hardening (опционально, но рекомендуется)
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=yes
ReadWritePaths=/opt/ai-news-digest-bot/data
PrivateTmp=yes

# Watchdog: systemd перезапустит сервис, если он завис
WatchdogSec=300

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable ai-news-digest
sudo systemctl start ai-news-digest
```

Проверка:
```bash
sudo systemctl status ai-news-digest
sudo journalctl -u ai-news-digest -f --no-pager
```

> **Примечание по ReadWritePaths:** Если используется `ProtectSystem=strict`, нужно явно разрешить запись в `data/`. Пути относительно WorkingDirectory не работают, поэтому указан абсолютный путь.

### 3.6. Первый запуск — что происходит

При старте `ai-news-digest bot`:
1. `load_settings()` читает `.env`
2. `DigestService.__init__()` инициализирует SQLite (создаёт таблицы если нет), seed sources из `config/default_sources.yaml`
3. `DigestScheduler.start()` регистрирует cron-задачи (утро `MORNING_HOUR:00`, вечер `EVENING_HOUR:00`)
4. `dispatcher.start_polling()` начинает long polling к Telegram Bot API
5. Бот отвечает на команды из `handlers.py`

---

## 4. Telethon сессия

### 4.1. StringSession vs файловая сессия

| | StringSession | Файловая сессия (.session) |
|---|---|---|
| **Хранение** | Строка в .env / переменной окружения | SQLite файл на диске |
| **Портабельность** | Легко переносить между машинами | Нужно копировать файл |
| **Concurrent access** | Нет проблем с блокировками | SQLite lock при двух процессах |
| **Безопасность** | Строка = полный доступ к аккаунту | Файл = полный доступ к аккаунту |

**Рекомендация: StringSession** — уже поддерживается кодом (`TG_SESSION_STRING` в `.env`). Нет проблем с sqlite-файлом сессии, проще мигрировать.

### 4.2. Генерация StringSession на локальной машине

```bash
# На локальной машине (где есть доступ к Telegram)
cd /path/to/ai-news-digest-bot

# Если сессия ещё не создана — авторизация:
.venv/bin/ai-news-digest auth-telegram
# Введёт номер телефона, код из Telegram, опционально 2FA пароль

# Экспорт в StringSession:
.venv/bin/ai-news-digest export-telegram-session
# Выведет строку типа: 1BVtsOHxxxxxxxxxxxxxxxxxxxxxxxxx...
```

Скопировать эту строку в `.env` на сервере:
```
TG_SESSION_STRING=1BVtsOHxxxxxxxxxxxxxxxxxxxxxxxxx...
```

### 4.3. Генерация StringSession прямо на сервере

Если нет локальной машины с авторизованной сессией:

```bash
cd /opt/ai-news-digest-bot

# Убедиться, что .env содержит TG_API_ID, TG_API_HASH, TG_PHONE
# Временно убрать TG_SESSION_STRING из .env (или оставить пустым)

# Запустить интерактивную авторизацию
.venv/bin/ai-news-digest auth-telegram
# Ввести код из Telegram (придёт в приложение)

# Экспортировать строку
.venv/bin/ai-news-digest export-telegram-session
# Скопировать результат в .env как TG_SESSION_STRING
```

### 4.4. Миграция существующей файловой сессии

Если на локальной машине уже есть `ai_news_digest.session`:

```bash
# На локальной машине:
scp ai_news_digest.session ubuntu@<SERVER_IP>:/opt/ai-news-digest-bot/

# На сервере — конвертировать в StringSession:
cd /opt/ai-news-digest-bot
.venv/bin/ai-news-digest export-telegram-session
# Добавить результат в .env
# Удалить файл .session:
rm /opt/ai-news-digest-bot/ai_news_digest.session
```

### 4.5. Что делать при session revoke

Telegram может отозвать сессию если:
- Вы вышли из "Active Sessions" в настройках Telegram
- Сменили пароль двухфакторки
- Telegram заподозрил подозрительную активность

**Симптомы:** бот падает с ошибками типа `AuthKeyUnregisteredError` или `SessionRevokedError`.

**Решение:**
```bash
# Остановить бот
sudo systemctl stop ai-news-digest

# Заново авторизоваться
cd /opt/ai-news-digest-bot
.venv/bin/ai-news-digest auth-telegram

# Экспортировать новую StringSession
.venv/bin/ai-news-digest export-telegram-session

# Обновить TG_SESSION_STRING в .env
nano /opt/ai-news-digest-bot/.env

# Запустить бот
sudo systemctl start ai-news-digest
```

### 4.6. Безопасность сессии

- Файл `.env` с `TG_SESSION_STRING` имеет права `600` (только владелец)
- `TG_SESSION_STRING` даёт полный доступ к Telegram-аккаунту — обращаться как с паролем
- Не коммитить `.env` в git (уже в `.gitignore`)
- Если сервер скомпрометирован — немедленно отозвать сессию через Telegram Settings → Privacy → Active Sessions

---

## 5. SQLite и данные

### 5.1. WAL mode

SQLite WAL (Write-Ahead Logging) улучшает concurrent read/write. В данном боте один процесс, но APScheduler может запускать задачи параллельно с обработкой команд (через asyncio lock в `DigestService`, но sqlite3 connections открываются/закрываются на каждый `_connect()`).

Включить WAL при первом запуске или вручную:

```bash
cd /opt/ai-news-digest-bot
sqlite3 data/digest.db "PRAGMA journal_mode=WAL;"
# Должно вернуть: wal
```

Или добавить в `Repository._init_db()` (если захотите закоммитить):
```python
conn.execute("PRAGMA journal_mode=WAL")
```

WAL создаёт дополнительные файлы: `digest.db-wal` и `digest.db-shm`. При бэкапе нужно копировать все три или использовать `.backup`.

### 5.2. Backup strategy

#### Oracle Object Storage (Free Tier: 10 GB Standard, 20 GB Archive)

Создать bucket:
```
OCI Console → Storage → Object Storage → Create Bucket
Name: digest-bot-backups
Default Storage Tier: Standard
```

#### Установить OCI CLI на сервер

```bash
# Установка OCI CLI
bash -c "$(curl -L https://raw.githubusercontent.com/oracle/oci-cli/master/scripts/install/install.sh)" -- --accept-all-defaults

# Настройка (потребуется OCID пользователя, tenancy, region, API key)
oci setup config
# Следовать инструкциям — сгенерирует API key, нужно загрузить public key в OCI Console

# Проверка
oci os bucket list --compartment-id <COMPARTMENT_OCID>
```

#### Скрипт бэкапа

```bash
cat > /opt/ai-news-digest-bot/scripts/backup.sh << 'BACKUPEOF'
#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/opt/ai-news-digest-bot"
DB_PATH="${APP_DIR}/data/digest.db"
BACKUP_DIR="${APP_DIR}/data/backups"
BUCKET_NAME="digest-bot-backups"
# Получить через: oci iam compartment list
OCI_NAMESPACE="$(oci os ns get --query data --raw-output)"
MAX_LOCAL_BACKUPS=7

mkdir -p "$BACKUP_DIR"

TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP_FILE="${BACKUP_DIR}/digest-${TIMESTAMP}.db"

# Безопасный бэкап SQLite (корректно работает с WAL)
sqlite3 "$DB_PATH" ".backup '${BACKUP_FILE}'"

# Сжать
gzip "$BACKUP_FILE"
BACKUP_GZ="${BACKUP_FILE}.gz"

# Загрузить в Object Storage
oci os object put \
  --bucket-name "$BUCKET_NAME" \
  --file "$BACKUP_GZ" \
  --name "backups/digest-${TIMESTAMP}.db.gz" \
  --no-retry

# Удалить старые локальные бэкапы (оставить последние N)
ls -1t "${BACKUP_DIR}"/digest-*.db.gz 2>/dev/null | tail -n +$((MAX_LOCAL_BACKUPS + 1)) | xargs -r rm -f

echo "Backup completed: digest-${TIMESTAMP}.db.gz"
BACKUPEOF

chmod +x /opt/ai-news-digest-bot/scripts/backup.sh
```

#### Cron для ежедневного бэкапа

```bash
# Бэкап каждый день в 03:00 MSK
(crontab -l 2>/dev/null; echo "0 3 * * * /opt/ai-news-digest-bot/scripts/backup.sh >> /opt/ai-news-digest-bot/data/backups/backup.log 2>&1") | crontab -
```

#### Альтернатива: rclone (проще настраивается)

```bash
# Установка rclone
sudo apt install -y rclone

# Настройка remote для OCI Object Storage (S3-compatible)
# OCI Object Storage поддерживает S3-compatible API
rclone config
# Тип: s3
# Provider: Other
# Endpoint: https://<NAMESPACE>.compat.objectstorage.<REGION>.oraclecloud.com
# Access key / Secret key: создать в OCI Console → Identity → Users → Customer Secret Keys

# Использование в скрипте:
# rclone copy "$BACKUP_GZ" oci-s3:digest-bot-backups/backups/
```

### 5.3. Восстановление из бэкапа

```bash
# Остановить бот
sudo systemctl stop ai-news-digest

# Скачать последний бэкап из Object Storage
oci os object get \
  --bucket-name digest-bot-backups \
  --name "backups/digest-20260312-030000.db.gz" \
  --file /tmp/restore.db.gz

# Или найти последний:
oci os object list --bucket-name digest-bot-backups --prefix "backups/" \
  --query 'sort_by(data, &"time-created")[-1].name' --raw-output

# Распаковать и заменить
gunzip /tmp/restore.db.gz
cp /opt/ai-news-digest-bot/data/digest.db /opt/ai-news-digest-bot/data/digest.db.old
mv /tmp/restore.db /opt/ai-news-digest-bot/data/digest.db

# Удалить WAL-файлы (они привязаны к старой БД)
rm -f /opt/ai-news-digest-bot/data/digest.db-wal /opt/ai-news-digest-bot/data/digest.db-shm

# Включить WAL заново
sqlite3 /opt/ai-news-digest-bot/data/digest.db "PRAGMA journal_mode=WAL;"

# Запустить бот
sudo systemctl start ai-news-digest
```

### 5.4. Очистка медиафайлов

Медиафайлы в `data/media/` накапливаются. Добавить ротацию:

```bash
# Добавить в crontab — удалять media старше 7 дней
(crontab -l 2>/dev/null; echo "30 3 * * * find /opt/ai-news-digest-bot/data/media -type f -mtime +7 -delete") | crontab -
```

---

## 6. Режим работы: polling + scheduler

### 6.1. Как это работает

При `INTERACTIVE_BOT=true` и запуске `ai-news-digest bot`:

1. **aiogram Dispatcher** запускает long polling к Telegram Bot API (`api.telegram.org`)
   - Исходящие HTTPS-запросы, никакого ingress не нужно
   - Polling = бот спрашивает "есть новые сообщения?" каждые несколько секунд
2. **APScheduler** (`DigestScheduler`) регистрирует два cron-задания:
   - `MORNING_HOUR:00` → `run_scheduled_digest("morning")` — sync + build + send
   - `EVENING_HOUR:00` → `run_scheduled_digest("evening")` — sync + build + send
3. **Inline commands** — бот реагирует на `/digest_now`, `/digest_today`, `/digest_month`, кнопки "Сейчас", "За сегодня", "За месяц"

### 6.2. Преимущества перед GitHub Actions

- Scheduler работает **внутри процесса** — не нужен внешний cron
- Telethon-сессия **живёт постоянно** — не нужно каждый раз подключаться
- SQLite **всегда доступен** — нет потери данных между запусками
- Бот **отвечает на команды** в реальном времени
- Нет cold start (GitHub Actions: ~30с на checkout + install)

### 6.3. Нет webhook, нет открытых портов

Бот использует **polling** — только исходящие HTTPS-запросы. Не нужно:
- Открывать порты в Security List
- Настраивать SSL-сертификат
- Настраивать reverse proxy (nginx)
- Настраивать домен

Единственный открытый порт — SSH (22), и тот ограничен по IP в Security List.

---

## 7. Мониторинг и логи

### 7.1. journalctl для systemd unit

```bash
# Последние 100 строк
sudo journalctl -u ai-news-digest -n 100 --no-pager

# Логи в реальном времени
sudo journalctl -u ai-news-digest -f

# Логи с определённого времени
sudo journalctl -u ai-news-digest --since "2026-03-12 09:00" --until "2026-03-12 10:00"

# Только ошибки
sudo journalctl -u ai-news-digest -p err

# Размер логов
sudo journalctl --disk-usage

# Ротация (оставить 500 МБ)
sudo journalctl --vacuum-size=500M
```

### 7.2. Healthcheck: /status команда

Добавить простую команду `/status` в хэндлеры бота. Бот уже отвечает на `/start` — если бот отвечает, значит polling работает.

Для внешнего мониторинга без изменения кода можно проверять systemd:

```bash
# Простой healthcheck скрипт
cat > /opt/ai-news-digest-bot/scripts/healthcheck.sh << 'HCEOF'
#!/usr/bin/env bash
set -euo pipefail

SERVICE="ai-news-digest"

if ! systemctl is-active --quiet "$SERVICE"; then
  echo "CRITICAL: $SERVICE is not running"
  exit 2
fi

# Проверить, что процесс не завис (есть активность в последние 10 минут)
LAST_LOG=$(journalctl -u "$SERVICE" --since "10 minutes ago" -q --no-pager | wc -l)
if [[ "$LAST_LOG" -eq 0 ]]; then
  echo "WARNING: No log output in last 10 minutes"
  exit 1
fi

echo "OK: $SERVICE is running"
exit 0
HCEOF
chmod +x /opt/ai-news-digest-bot/scripts/healthcheck.sh
```

### 7.3. Алерты при падении

#### Вариант 1: systemd OnFailure (отправка в Telegram)

```bash
# Создать notification unit
sudo tee /etc/systemd/system/ai-news-digest-notify@.service << 'EOF'
[Unit]
Description=Send Telegram alert on %i failure

[Service]
Type=oneshot
# Подставить реальные BOT_TOKEN и ADMIN_CHAT_ID
ExecStart=/usr/bin/bash -c '\
  curl -s -X POST "https://api.telegram.org/bot${BOT_TOKEN}/sendMessage" \
    -d chat_id="${ADMIN_CHAT_ID}" \
    -d text="⚠ Сервис %i упал на сервере $(hostname). Автоперезапуск через 5 секунд." \
    -d parse_mode=HTML'
EnvironmentFile=/opt/ai-news-digest-bot/.env
EOF

sudo systemctl daemon-reload
```

Добавить в основной unit:
```ini
[Unit]
# ... существующие строки ...
OnFailure=ai-news-digest-notify@%n.service
```

Обновить:
```bash
# Отредактировать unit
sudo systemctl edit ai-news-digest --force
# Добавить в секцию [Unit]:
# OnFailure=ai-news-digest-notify@%n.service

sudo systemctl daemon-reload
sudo systemctl restart ai-news-digest
```

#### Вариант 2: systemd Watchdog

Уже добавлен `WatchdogSec=300` в unit-файле выше. Если процесс не отвечает 300 секунд, systemd убьёт и перезапустит его.

Для полноценного watchdog нужно, чтобы приложение периодически вызывало `sd_notify("WATCHDOG=1")`. Без этого watchdog сработает как "убить если процесс завис", что тоже полезно. Для простого бота достаточно `Restart=always` + `RestartSec=5`.

### 7.4. Мониторинг диска

```bash
# Cron — алерт если диск заполнен более чем на 85%
cat > /opt/ai-news-digest-bot/scripts/disk-check.sh << 'DCEOF'
#!/usr/bin/env bash
set -euo pipefail
THRESHOLD=85
USAGE=$(df / --output=pcent | tail -1 | tr -d ' %')
if [[ "$USAGE" -ge "$THRESHOLD" ]]; then
  source /opt/ai-news-digest-bot/.env
  curl -s -X POST "https://api.telegram.org/bot${BOT_TOKEN}/sendMessage" \
    -d chat_id="${ADMIN_CHAT_ID}" \
    -d text="Диск заполнен на ${USAGE}% на $(hostname)"
fi
DCEOF
chmod +x /opt/ai-news-digest-bot/scripts/disk-check.sh

(crontab -l 2>/dev/null; echo "0 */6 * * * /opt/ai-news-digest-bot/scripts/disk-check.sh") | crontab -
```

---

## 8. Обновление кода

### 8.1. Ручное обновление

```bash
cd /opt/ai-news-digest-bot
git pull origin main
.venv/bin/python -m pip install -e .
sudo systemctl restart ai-news-digest

# Проверить что запустился
sudo systemctl status ai-news-digest
sudo journalctl -u ai-news-digest -n 20 --no-pager
```

### 8.2. Deploy script

```bash
cat > /opt/ai-news-digest-bot/scripts/deploy.sh << 'DEPLOYEOF'
#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/opt/ai-news-digest-bot"
SERVICE="ai-news-digest"

cd "$APP_DIR"

echo "=== Pulling latest code ==="
git pull origin main

echo "=== Installing dependencies ==="
.venv/bin/python -m pip install -e . --quiet

echo "=== Running quick test ==="
.venv/bin/python -m pytest tests/ -x --quiet 2>/dev/null || {
  echo "WARNING: Tests failed. Deploy continues, but check manually."
}

echo "=== Restarting service ==="
sudo systemctl restart "$SERVICE"

sleep 2

if systemctl is-active --quiet "$SERVICE"; then
  echo "=== Deploy successful ==="
  sudo journalctl -u "$SERVICE" -n 5 --no-pager
else
  echo "=== Deploy FAILED: service is not running ==="
  sudo journalctl -u "$SERVICE" -n 30 --no-pager
  exit 1
fi
DEPLOYEOF

chmod +x /opt/ai-news-digest-bot/scripts/deploy.sh
```

Использование:
```bash
/opt/ai-news-digest-bot/scripts/deploy.sh
```

### 8.3. Deploy из GitHub Actions (опционально)

Если хочется автодеплой при push в main:

```yaml
# .github/workflows/deploy.yml
name: Deploy to Oracle Cloud
on:
  push:
    branches: [main]
  workflow_dispatch:

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - name: Deploy via SSH
        uses: appleboy/ssh-action@v1
        with:
          host: ${{ secrets.ORACLE_HOST }}
          username: ubuntu
          key: ${{ secrets.ORACLE_SSH_KEY }}
          script: /opt/ai-news-digest-bot/scripts/deploy.sh
```

---

## 9. Сравнение с GitHub Actions

### Что выигрываем

| Аспект | GitHub Actions | Oracle Cloud VM |
|--------|---------------|-----------------|
| **Persistent state** | Нет. БД и медиа теряются после каждого запуска | БД и медиа живут на диске постоянно |
| **Telethon сессия** | StringSession, подключение/отключение каждый запуск | Живая сессия, постоянное соединение с MTProto |
| **Cold start** | ~30с (checkout + pip install) | Нет. Процесс уже запущен |
| **Интерактивность** | Нет. Только scheduled sender | Полноценный бот: команды, кнопки, callback'и |
| **Scheduler** | GitHub cron (минимум ±5 мин точность, иногда задержки до 15 мин) | APScheduler в процессе, точность до секунды |
| **Стоимость** | Free для public repo, 2000 мин/мес для private | Free Tier (Always Free) |
| **SQLite** | Пересоздаётся каждый раз | Всегда доступна, данные накапливаются |
| **Дедупликация** | Не работает (нет истории) | Работает полноценно (dedup_key в БД) |
| **Скорость дайджеста** | ~2-5 мин (install + sync + build + send) | ~30с (sync + build + send, всё уже в памяти) |

### Что теряем

| Аспект | GitHub Actions | Oracle Cloud VM |
|--------|---------------|-----------------|
| **Managed infra** | GitHub управляет средой, обновлениями, uptime | Self-managed: обновления OS, мониторинг, бэкапы — на тебе |
| **Отказоустойчивость** | GitHub гарантирует запуск (в рамках SLA) | VM может пропасть, Oracle может изменить Free Tier |
| **Без SSH** | Не нужно управлять сервером | Нужен SSH-доступ, базовое sysadmin-знание |
| **Git-triggered** | Автоматически при push | Нужно настроить CD самому (или деплоить руками) |
| **Изоляция** | Чистая среда каждый раз | Нужно следить за дисковым пространством, зависимостями |

### Вывод

Для этого бота VM однозначно лучше: persistent SQLite, живая Telethon-сессия, интерактивные команды, нет cold start. GitHub Actions можно оставить как fallback (см. раздел 10).

---

## 10. Риски и fallback

### 10.1. Oracle отменит/изменит Free Tier

**Риск:** Oracle уже ужесточал условия Free Tier (в 2023 начали удалять idle инстансы, потом откатили решение).

**Митигация:**
- **Ежедневные бэкапы** в Object Storage (раздел 5.2)
- **Хранить копию бэкапа вне Oracle** — скачивать на локальную машину или в другое облако:
  ```bash
  # На локальной машине — cron раз в неделю
  scp ubuntu@<ORACLE_IP>:/opt/ai-news-digest-bot/data/backups/$(ls -t1 | head -1) ~/backups/digest-bot/
  ```
- **GitHub Actions workflow оставить в репо** — можно мгновенно вернуться к scheduled sender режиму, просто включив Actions (потеряется интерактивность и persistent state, но дайджесты будут приходить)
- **TG_SESSION_STRING хранить в менеджере паролей** — не привязан к конкретному серверу

### 10.2. VM пропала / сервер недоступен

**Восстановление (30-60 минут):**
1. Создать новый инстанс (раздел 2.3)
2. Развернуть приложение (раздел 3)
3. Восстановить БД из бэкапа (раздел 5.3)
4. StringSession уже в менеджере паролей — вставить в .env

**Быстрый fallback (5 минут):**
1. Включить GitHub Actions workflow (`ai-digest.yml`)
2. Бот вернётся в scheduled sender режим
3. Данные потеряны (SQLite пуста), но новые накопятся

### 10.3. Telethon flood wait / ban

**Риск:** Telegram может временно заблокировать аккаунт за слишком частый скрапинг.

**Митигация:**
- Не увеличивать `max_items` сверх разумного (300 на источник — текущее значение)
- Не запускать sync чаще чем раз в 6 часов
- Telethon автоматически обрабатывает `FloodWaitError` (ждёт и повторяет)
- Если бан — дождаться, обычно 1-24 часа

### 10.4. Диск заполнился

**Риск:** медиафайлы и БД могут заполнить 50 ГБ boot volume.

**Митигация:**
- Ротация медиа через cron (раздел 5.4)
- Мониторинг диска с алертом (раздел 7.4)
- При необходимости — увеличить boot volume (Free Tier позволяет до 200 ГБ total)
- Периодически чистить старые дайджесты:
  ```bash
  sqlite3 /opt/ai-news-digest-bot/data/digest.db \
    "DELETE FROM digests WHERE created_at < datetime('now', '-90 days');"
  sqlite3 /opt/ai-news-digest-bot/data/digest.db "VACUUM;"
  ```

### 10.5. Idle Instance Reclamation

Oracle может пометить Always Free инстанс как idle и удалить через 7 дней если:
- CPU utilization < 10% за последние 7 дней
- Network traffic < 10% за последние 7 дней

**Для нашего бота это маловероятно:** polling генерирует постоянный network traffic, а sync/build периодически нагружает CPU. Но на всякий случай:

```bash
# Если Oracle прислал email "Your instance will be reclaimed" —
# любая активность (SSH, перезапуск) сбрасывает таймер
ssh ubuntu@<ORACLE_IP> "uptime"

# Для гарантии — добавить минимальную cron-задачу
(crontab -l 2>/dev/null; echo "*/30 * * * * curl -s https://api.telegram.org > /dev/null 2>&1") | crontab -
```

---

## Чеклист миграции

- [ ] Создать Oracle Cloud аккаунт (Home Region: Frankfurt)
- [ ] Настроить VCN + Security List (SSH only ingress)
- [ ] Создать ARM A1.Flex инстанс (1 OCPU, 6 GB RAM, Ubuntu 24.04)
- [ ] SSH на сервер, обновить систему, установить Python 3.12+
- [ ] Клонировать репозиторий в `/opt/ai-news-digest-bot`
- [ ] Создать venv, установить зависимости
- [ ] Экспортировать TG_SESSION_STRING с локальной машины
- [ ] Создать `.env` на сервере с секретами
- [ ] Установить systemd unit
- [ ] Запустить сервис, проверить логи
- [ ] Отправить `/start` боту — убедиться что отвечает
- [ ] Подождать scheduled digest (утренний или вечерний)
- [ ] Настроить Object Storage bucket для бэкапов
- [ ] Настроить cron для бэкапов и ротации медиа
- [ ] Настроить алерт при падении (OnFailure unit)
- [ ] Сохранить TG_SESSION_STRING в менеджере паролей
- [ ] Сохранить deploy.sh
- [ ] (Опционально) Отключить GitHub Actions schedule (оставить workflow_dispatch для fallback)
