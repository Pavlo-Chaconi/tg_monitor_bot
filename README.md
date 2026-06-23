# tg_monitor_bot

Telegram-бот для планового мониторинга инфраструктуры. Собирает метрики с **Prometheus** (CPU, RAM, диски, сеть) и **TrueNAS** (ZFS-пулы, температуры дисков, алерты), отправляет HTML-отчёты по расписанию.

---

## Содержание

1. [Требования](#требования)
2. [Быстрый старт](#быстрый-старт)
3. [Настройка .env](#настройка-env)
4. [Развёртывание Prometheus и node\_exporter](#развёртывание-prometheus-и-node_exporter)
5. [Установка node\_exporter на серверы](#установка-node_exporter-на-серверы)
6. [Управление контейнером](#управление-контейнером)
7. [Структура проекта](#структура-проекта)

---

## Требования

| Компонент | Версия |
|---|---|
| Docker | 24+ |
| Docker Compose | v2 (плагин, `docker compose`) |
| Telegram Bot Token | от @BotFather |
| Prometheus | уже развёрнут, доступен по сети |
| TrueNAS SCALE / CORE | REST API v2 доступен |

---

## Быстрый старт

```bash
# 1. Клонировать репозиторий
git clone https://github.com/ВАШ_АККАУНТ/tg_monitor_bot.git
cd tg_monitor_bot

# 2. Создать .env из шаблона и заполнить (см. раздел ниже)
cp .env.example .env
nano .env   # или любой редактор

# 3. Запустить бота
docker compose up -d

# 4. Проверить логи
docker compose logs -f
```

Бот отправит первый отчёт сразу при старте, затем — по расписанию из `.env`.

---

## Настройка .env

Скопируйте `.env.example` в `.env` и заполните следующие поля:

### Обязательные

```env
# Токен от @BotFather
TELEGRAM_BOT_TOKEN=7123456789:AABBCCDDEEFFaabbccddeeff

# ID чата куда слать отчёты (узнать у @userinfobot)
# Личные сообщения: числовой ID, например 123456789
# Группа / канал:   -1001234567890
TELEGRAM_CHAT_ID=123456789

# Адрес Prometheus
PROMETHEUS_URL=http://192.168.1.10:9090

# Адрес TrueNAS
TRUENAS_URL=http://192.168.1.20

# API-ключ TrueNAS (Credentials → API Keys → Add)
TRUENAS_API_KEY=1-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

### Опциональные

```env
# Авторизация Prometheus (если включена Basic Auth)
PROMETHEUS_USERNAME=
PROMETHEUS_PASSWORD=

# Вместо API-ключа TrueNAS можно использовать логин/пароль
TRUENAS_USERNAME=
TRUENAS_PASSWORD=

# Расписание отчётов (cron-формат)
# Каждый час в :00         → REPORT_HOUR=*   REPORT_MINUTE=0
# В 8:00 и 20:00           → REPORT_HOUR=8,20 REPORT_MINUTE=0
# Каждые 30 минут          → REPORT_HOUR=*   REPORT_MINUTE=0,30
REPORT_HOUR=*
REPORT_MINUTE=0

TIMEZONE=Europe/Moscow
```

> **Важно:** файл `.env` добавлен в `.gitignore` и никогда не попадёт в репозиторий.

---

## Развёртывание Prometheus и node\_exporter

> Пропустите этот раздел, если Prometheus у вас уже работает.

В репозитории есть готовый `docker-compose.monitoring.yml` с Prometheus и node\_exporter.

### 1. Отредактируйте список серверов

Откройте `prometheus/prometheus.yml` и добавьте IP:порт каждого сервера:

```yaml
scrape_configs:
  - job_name: "node"
    static_configs:
      - targets:
          - "localhost:9100"      # сам хост с Prometheus
          - "192.168.1.11:9100"  # сервер 2
          - "192.168.1.12:9100"  # сервер 3
          - "truenas.local:9100" # TrueNAS (если установлен node_exporter)
```

### 2. Запустите стек мониторинга

```bash
docker compose -f docker-compose.monitoring.yml up -d
```

Prometheus будет доступен на `http://localhost:9090`.

### 3. Укажите адрес в .env

```env
PROMETHEUS_URL=http://localhost:9090
```

---

## Установка node\_exporter на серверы

node\_exporter нужно установить на **каждый Linux-сервер**, который должен попасть в отчёт.

### Вариант A — systemd (рекомендуется для продакшна)

```bash
# Скачать последнюю версию
wget https://github.com/prometheus/node_exporter/releases/latest/download/node_exporter-1.8.2.linux-amd64.tar.gz
tar xzf node_exporter-*.tar.gz
sudo mv node_exporter-*/node_exporter /usr/local/bin/

# Создать systemd-сервис
sudo tee /etc/systemd/system/node_exporter.service > /dev/null <<EOF
[Unit]
Description=Prometheus Node Exporter
After=network.target

[Service]
User=nobody
ExecStart=/usr/local/bin/node_exporter
Restart=always

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now node_exporter

# Проверить
curl http://localhost:9100/metrics | head -5
```

### Вариант B — пакетный менеджер

```bash
# Debian / Ubuntu
sudo apt install prometheus-node-exporter

# RHEL / CentOS / Fedora
sudo dnf install golang-github-prometheus-node-exporter
sudo systemctl enable --now node_exporter
```

### Вариант C — Docker (если сервер уже с Docker)

```bash
docker run -d \
  --name node_exporter \
  --restart unless-stopped \
  --network host \
  --pid host \
  -v /proc:/host/proc:ro \
  -v /sys:/host/sys:ro \
  -v /:/rootfs:ro \
  prom/node-exporter \
  --path.procfs=/host/proc \
  --path.sysfs=/host/sys \
  --collector.filesystem.mount-points-exclude='^/(sys|proc|dev|host|etc)($|/)'
```

После установки откройте порт 9100 в файрволе:

```bash
# ufw
sudo ufw allow 9100/tcp

# firewalld
sudo firewall-cmd --permanent --add-port=9100/tcp && sudo firewall-cmd --reload
```

---

## Управление контейнером

```bash
# Запустить
docker compose up -d

# Остановить
docker compose down

# Перезапустить (после изменения .env)
docker compose restart

# Пересобрать образ (после изменения кода)
docker compose up -d --build

# Логи в реальном времени
docker compose logs -f

# Запустить smoke-тест вручную
docker run --rm tg_monitor_bot:test python test_smoke.py
```

---

## Структура проекта

```
tg_monitor_bot/
├── Dockerfile
├── docker-compose.yml              # бот
├── docker-compose.monitoring.yml   # Prometheus + node_exporter (опционально)
├── prometheus/
│   └── prometheus.yml              # список scrape-таргетов
├── .env.example                    # шаблон конфига
├── .gitignore
├── .dockerignore
├── requirements.txt
├── config.py                       # загрузка переменных окружения
├── collector.py                    # параллельный сбор данных
├── main.py                         # точка входа, планировщик
├── test_smoke.py                   # smoke-тест (без реальных серверов)
├── clients/
│   ├── prometheus.py               # HTTP API Prometheus (PromQL)
│   └── truenas.py                  # REST API TrueNAS v2
└── reports/
    └── formatter.py                # форматирование HTML-сообщений
```
