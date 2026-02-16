# Daily Analyst — Telegram AI-Agent

Telegram-бот для анализа продуктивности на основе Notion-дневника. Использует GPT-4o-mini для инсайтов и Matplotlib для графиков.

---

## Быстрый старт

### 1. Клонируй и установи

```bash
git clone https://github.com/Tih000/daily-analyst.git
cd daily-analyst

python -m venv venv
source venv/bin/activate     # Linux / macOS
# venv\Scripts\activate      # Windows

pip install -r requirements.txt
```

### 2. Настрой `.env`

```bash
cp .env.example .env
nano .env                    # заполни все переменные (гайд ниже)
```

### 3. Запусти

```bash
python -m src.main
```

Бот будет доступен на `http://localhost:8000`.

---

## Где взять все переменные `.env`

### `TELEGRAM_BOT_TOKEN`

Токен Telegram-бота для отправки и получения сообщений.

1. Открой Telegram, найди **[@BotFather](https://t.me/BotFather)**
2. Отправь `/newbot`
3. Придумай имя бота (например: `Daily Analyst`) и username (например: `my_daily_analyst_bot`)
4. BotFather ответит сообщением с токеном вида `7123456789:AAF...` — скопируй его

```
TELEGRAM_BOT_TOKEN=7123456789:AAFxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

### `TELEGRAM_WEBHOOK_URL`

URL, на который Telegram будет отправлять обновления. Это адрес твоего VPS + `/webhook`.

- Нужен **HTTPS** (Telegram не шлёт webhook на голый HTTP)
- Если у тебя домен `example.com`, то:

```
TELEGRAM_WEBHOOK_URL=https://example.com/webhook
```

- Если домена нет — можно использовать IP с self-signed сертификатом, но проще привязать домен

### `TELEGRAM_WEBHOOK_SECRET`

Секретная строка для проверки, что webhook приходит именно от Telegram, а не от кого-то другого.

Сгенерируй любую случайную строку:

```bash
# Linux / macOS:
openssl rand -hex 32

# Или Python:
python -c "import secrets; print(secrets.token_hex(32))"
```

```
TELEGRAM_WEBHOOK_SECRET=a1b2c3d4e5f6...любая_длинная_случайная_строка
```

### `ALLOWED_USER_IDS`

Telegram ID пользователей, которым разрешено использовать бота. Если оставить пустым — доступ будет у всех.

**Как узнать свой Telegram ID:**
1. Открой **[@userinfobot](https://t.me/userinfobot)** в Telegram
2. Отправь `/start`
3. Бот ответит твоим ID (число вида `123456789`)

Несколько ID через запятую:

```
ALLOWED_USER_IDS=123456789,987654321
```

---

### `OPENAI_API_KEY`

Ключ API для GPT-4o-mini, который используется для анализа данных.

1. Зайди на **[platform.openai.com](https://platform.openai.com/)**
2. Зарегистрируйся / войди
3. Перейди в **[API Keys](https://platform.openai.com/api-keys)**
4. Нажми **Create new secret key**
5. Скопируй ключ (начинается с `sk-`)

**Важно:** Нужен баланс на аккаунте. GPT-4o-mini стоит ~$0.15 / 1M input tokens — очень дёшево, ~$1-2 в месяц при активном использовании.

```
OPENAI_API_KEY=sk-proj-xxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

### `OPENAI_MODEL`

Модель OpenAI для анализа. По умолчанию `gpt-4o-mini` — лучшее соотношение цены и качества.

```
OPENAI_MODEL=gpt-4o-mini
```

Другие варианты: `gpt-4o` (дороже, умнее), `gpt-3.5-turbo` (дешевле, проще).

---

### `NOTION_TOKEN`

Токен интеграции Notion для чтения базы данных дневника.

1. Зайди на **[notion.so/my-integrations](https://www.notion.so/my-integrations)**
2. Нажми **New integration**
3. Заполни:
   - **Name:** `Daily Analyst` (или любое)
   - **Associated workspace:** выбери свой workspace
   - **Capabilities:** отметь **Read content**
4. Нажми **Submit** → скопируй **Internal Integration Secret** (начинается с `secret_`)

```
NOTION_TOKEN=secret_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

### `NOTION_DATABASE_ID`

ID базы данных Notion, откуда бот будет читать записи дневника.

**Как найти:**
1. Открой нужную базу данных в Notion **в браузере**
2. URL будет выглядеть так:
   ```
   https://www.notion.so/myworkspace/a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4?v=...
   ```
3. **Database ID** — это длинная часть между последним `/` и `?`:
   ```
   a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4
   ```

**Важно — подключи интеграцию к базе:**
1. Открой базу данных в Notion
2. Нажми **...** (три точки справа вверху) → **Connections** → **Connect to** → выбери `Daily Analyst`

Без этого шага бот не сможет прочитать данные.

```
NOTION_DATABASE_ID=a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4
```

#### Структура базы данных Notion (Tasks)

Бот работает с базой данных **Tasks** со следующими полями:

| Поле | Тип | Описание |
|---|---|---|
| **Title** | Title | Название задачи/категории (`MARK`, `CODING`, `GYM`, ...) |
| **Date** | Date | Дата |
| **Tags** | Multi-select | Категории (динамические: `MARK`, `CODING`, `GYM`, `AI`, `UNIVERSITY`, `KATE`, ...) |
| **Checkbox** | Checkbox | Выполнено или нет |
| **It took (hours)** | Number | Сколько часов заняло |

**Запись MARK** — это дневниковая запись дня. В теле страницы пиши:
- Сон: `Woke up at 12:30. Sleep time 8:54. Recovery 81 by Apple Watch`
- TESTIK: `PLUS TESTIK` / `MINUS TESTIK` / `MINUS TESTIK KATE`
- Оценка дня: `MARK: perfect` / `very good` / `good` / `normal` / `bad` / `very bad`

**MARK's WEAK** — недельный обзор (автоматически фильтруется из ежедневной аналитики).

---

### `APP_ENV`

Режим работы приложения. Влияет на авто-перезагрузку при изменениях.

```
APP_ENV=production       # для VPS (без hot reload)
APP_ENV=development      # для локальной разработки (с hot reload)
```

### `LOG_LEVEL`

Уровень логирования.

```
LOG_LEVEL=INFO           # стандартный (рекомендуется)
LOG_LEVEL=DEBUG          # подробный (для отладки)
LOG_LEVEL=WARNING        # только предупреждения и ошибки
```

### `RATE_LIMIT_PER_MINUTE`

Максимальное количество команд от одного пользователя в минуту. Защита от спама.

```
RATE_LIMIT_PER_MINUTE=20
```

### `CACHE_TTL_SECONDS`

Время жизни кэша в секундах. Бот кэширует данные из Notion в SQLite, чтобы не дёргать API при каждом запросе.

```
CACHE_TTL_SECONDS=300    # 5 минут (рекомендуется)
```

### `APP_PORT`

Порт, на котором приложение слушает внутри Docker. Используется в `docker-compose.yml`.

```
APP_PORT=8000
```

### `DOMAIN`

Твой домен. Используется в nginx конфиге для SSL-сертификата.

```
DOMAIN=example.com
```

---

## Деплой на VPS

### Требования

- VPS с Ubuntu 22.04+ (или любой Linux)
- Docker + Docker Compose
- Домен, направленный на IP сервера (A-запись в DNS)

### Шаг 1: Подготовка сервера

```bash
# Установи Docker (если нет)
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER

# Установи Docker Compose
sudo apt install docker-compose-plugin -y

# Перезайди для применения группы docker
exit
```

### Шаг 2: Клонируй проект

```bash
git clone https://github.com/Tih000/daily-analyst.git
cd daily-analyst
```

### Шаг 3: Настрой `.env`

```bash
cp .env.example .env
nano .env
# Заполни ВСЕ переменные по гайду выше
```

### Шаг 4: Замени домен в nginx конфиге

Открой `nginx/nginx.conf` и замени все `${DOMAIN}` на свой домен:

```bash
sed -i 's/${DOMAIN}/example.com/g' nginx/nginx.conf
```

### Шаг 5: Получи SSL-сертификат

**Первый запуск** — нужно получить сертификат перед запуском nginx с SSL.

Временно запусти nginx только на HTTP для прохождения ACME-challenge:

```bash
# Создай директории для certbot
mkdir -p nginx/certbot/conf nginx/certbot/www

# Получи сертификат
docker run --rm \
  -v $(pwd)/nginx/certbot/conf:/etc/letsencrypt \
  -v $(pwd)/nginx/certbot/www:/var/www/certbot \
  -p 80:80 \
  certbot/certbot certonly \
    --standalone \
    --email your@email.com \
    --agree-tos \
    --no-eff-email \
    -d example.com
```

### Шаг 6: Запусти всё

```bash
docker compose up -d --build
```

Проверь, что всё работает:

```bash
# Логи бота
docker compose logs -f bot

# Health check
curl https://example.com/health

# Статус контейнеров
docker compose ps
```

### Шаг 7: Установи webhook

Webhook устанавливается автоматически при старте бота (если `TELEGRAM_WEBHOOK_URL` заполнен в `.env`).

Проверить текущий webhook:

```bash
curl "https://api.telegram.org/bot<YOUR_TOKEN>/getWebhookInfo"
```

---

### Управление на VPS

```bash
# Перезапустить
docker compose restart bot

# Обновить код
git pull
docker compose up -d --build

# Посмотреть логи
docker compose logs -f bot --tail=100

# Остановить
docker compose down

# Ручная синхронизация Notion
curl https://example.com/sync
```

---

### Без Docker (systemd)

Если не хочешь Docker — можно запустить напрямую через systemd:

```bash
# Установи зависимости
python3.11 -m venv /opt/daily-analyst/venv
source /opt/daily-analyst/venv/bin/activate
pip install -r requirements.txt
```

Создай systemd-сервис `/etc/systemd/system/daily-analyst.service`:

```ini
[Unit]
Description=Daily Analyst Telegram Bot
After=network.target

[Service]
Type=exec
User=www-data
WorkingDirectory=/opt/daily-analyst
EnvironmentFile=/opt/daily-analyst/.env
ExecStart=/opt/daily-analyst/venv/bin/uvicorn src.main:app --host 127.0.0.1 --port 8000
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now daily-analyst
sudo systemctl status daily-analyst
```

В этом случае nginx настраивай отдельно как обычный reverse proxy на `127.0.0.1:8000`.

---

## Команды бота (19 команд)

### Аналитика

| Команда | Описание |
|---|---|
| `/start` | Приветствие + список команд |
| `/analyze [месяц]` | Полный анализ месяца с графиками |
| `/compare [мес1] [мес2]` | Сравнение двух месяцев бок о бок |
| `/correlations` | Матрица корреляций активностей |
| `/day_types` | AI классификация типов дней |
| `/report [месяц]` | Карточка месяца (Spotify Wrapped стиль) |

### Прогнозы

| Команда | Описание |
|---|---|
| `/predict` | Прогноз риска выгорания на 5 дней |
| `/tomorrow_mood` | Прогноз завтрашнего настроения |
| `/best_days [месяц]` | Топ-3 продуктивных дня |

### Глубокий анализ

| Команда | Описание |
|---|---|
| `/optimal_hours` | Анализ оптимального режима работы |
| `/kate_impact` | Корреляция отношений и продуктивности |
| `/testik_patterns` | Паттерны TESTIK и влияние на метрики |
| `/sleep_optimizer` | Анализ сна и рекомендации |
| `/money_forecast` | Анализ рабочих паттернов |
| `/weak_spots` | Слабые места в продуктивности |

### Геймификация

| Команда | Описание |
|---|---|
| `/streaks` | Текущие серии (TESTIK PLUS, GYM, CODING, оценка, сон) |
| `/habits <name>` | GitHub-style тепловая карта привычки (gym, coding, sleep7...) |
| `/set_goal <act> <n/period>` | Установить цель (gym 4/week, coding 5/week) |
| `/goals` | Прогресс целей с визуальными полосками |

### Автоматические функции

- **Proactive Alerts** — бот сам пишет, если обнаруживает проблему (3+ дня без тренировки, плохой сон, TESTIK MINUS streak)
- **Weekly Digest** — еженедельная сводка по воскресеньям со сравнением с прошлой неделей

### Примеры использования

```
/analyze              → анализ текущего месяца
/analyze 2025-01      → анализ января 2025
/analyze январь       → то же самое по-русски
/compare jan feb      → сравнение январь vs февраль
/correlations         → какие активности дают лучшие оценки
/report               → красивая карточка текущего месяца
/streaks              → серии подряд (с рекордами)
/habits gym           → тепловая карта тренировок за 3 месяца
/habits sleep7        → дни когда спал ≥ 7 часов
/set_goal gym 4/week  → цель: 4 тренировки в неделю
/goals                → прогресс всех целей
/predict              → риск выгорания с графиком
/day_types            → типы дней с метриками
```

---

## Разработка

### Тесты

```bash
pytest -v
pytest tests/test_cache.py   # один модуль
pytest --tb=short            # краткий вывод
```

### Линтинг

```bash
ruff check src/ tests/
ruff format src/ tests/
mypy src/
```

### API endpoints

| Метод | URL | Описание |
|---|---|---|
| GET | `/health` | Health check |
| POST | `/webhook` | Telegram webhook |
| GET | `/sync` | Ручная синхронизация Notion → кэш |

---

## Архитектура

```
src/
├── main.py              # FastAPI + Telegram handlers (19 команд + alerts)
├── config.py            # Env variables (dataclass-based)
├── services/
│   ├── notion_service.py  # Notion DB + Blocks API, парсинг MARK entries
│   ├── ai_analyzer.py     # GPT analysis + local stats + streaks + goals
│   └── charts_service.py  # Matplotlib charts (9 типов: overview, burnout,
│                          #   testik, sleep, activity, heatmap, correlation,
│                          #   report card, compare)
├── models/
│   └── journal_entry.py   # TaskEntry, DailyRecord, Goal, StreakInfo,
│                          #   MetricDelta, CorrelationMatrix, GoalProgress
└── utils/
    ├── cache.py           # SQLite: task_entries + daily_records + goals
    └── validators.py      # Парсинг sleep/testik/rating + compare/goal args
```

**Ключевая особенность:** GPT получает ПОЛНЫЙ текст дневника (`journal_text`) из MARK записей — не только структурированные метрики. Это позволяет анализировать эмоции, контекст и паттерны жизни.

**Поток данных:**

```
Notion Tasks DB
  ↓ (query database API + fetch page blocks for MARK entries)
TaskEntry[] (raw pages)
  ↓ (group by date, parse MARK body text — sleep, testik, rating)
DailyRecord[] (aggregated: rating, testik, sleep, activities, journal_text)
  ↓ (cache in SQLite + goals table)
  ↓
Telegram command → AIAnalyzer → GPT-4o-mini (с полным journal_text) → insights
                 → ChartsService → PNG charts (heatmaps, reports, correlations)
                 → reply + photos → Telegram
  ↓
Background loop → check_alerts() → proactive messages
               → weekly_digest() → Sunday summaries
```

---

## Лицензия

MIT
