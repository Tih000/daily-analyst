# Daily Analyst — Telegram AI-Agent

Telegram-бот для анализа продуктивности на основе Notion-дневника. Использует GPT-4o-mini для инсайтов и Matplotlib для графиков.

## Быстрый старт (2 минуты)

### 1. Клонируй и установи

```bash
cd daily_analyst
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # macOS/Linux

pip install -r requirements.txt
```

### 2. Настрой .env

```bash
copy .env.example .env       # Windows
# cp .env.example .env       # macOS/Linux
```

Заполни переменные:

| Переменная | Где взять |
|---|---|
| `TELEGRAM_BOT_TOKEN` | [@BotFather](https://t.me/BotFather) → /newbot |
| `OPENAI_API_KEY` | [platform.openai.com/api-keys](https://platform.openai.com/api-keys) |
| `NOTION_TOKEN` | [notion.so/my-integrations](https://www.notion.so/my-integrations) → New integration |
| `NOTION_DATABASE_ID` | URL вашей базы данных: `notion.so/{workspace}/{DATABASE_ID}?v=...` |
| `ALLOWED_USER_IDS` | Ваш Telegram ID (узнать: [@userinfobot](https://t.me/userinfobot)) |

### 3. Настрой Notion Database

Создай базу данных в Notion с полями:

| Поле | Тип | Значения |
|---|---|---|
| Date | Date | — |
| Mood | Select | PERFECT, GOOD, NORMAL, BAD, VERY_BAD |
| Hours Worked | Number | — |
| Tasks Completed | Number | — |
| TESTIK | Select | PLUS, MINUS_KATE, MINUS_SOLO |
| Workout | Checkbox | — |
| University | Checkbox | — |
| Earnings USD | Number | — |
| Sleep Hours | Number | — |
| Notes | Rich Text | — |

**Важно:** Подключи интеграцию к базе данных (Share → Invite → выбери интеграцию).

### 4. Запусти

```bash
python -m src.main
```

Бот доступен по адресу `http://localhost:8000`. Для разработки используйте [ngrok](https://ngrok.com/) для туннелирования webhook.

---

## Команды бота

| Команда | Описание |
|---|---|
| `/start` | Приветствие + список команд |
| `/analyze [месяц]` | Полный анализ месяца с графиками |
| `/predict` | Прогноз риска выгорания на 5 дней |
| `/best_days [месяц]` | Топ-3 продуктивных дня |
| `/optimal_hours` | Анализ оптимального времени работы |
| `/kate_impact` | Корреляция отношений и продуктивности |
| `/testik_patterns` | Паттерны TESTIK и влияние на метрики |
| `/sleep_optimizer` | Анализ сна и рекомендации |
| `/money_forecast` | Прогноз заработка |
| `/weak_spots` | Слабые места в продуктивности |
| `/tomorrow_mood` | Прогноз завтрашнего настроения |

### Примеры

```
/analyze              → анализ текущего месяца
/analyze 2025-01      → анализ января 2025
/analyze january      → анализ января текущего года
/best_days 3          → топ-3 дня за март
/predict              → риск выгорания с графиком
```

**Пример ответа `/analyze`:**

```
📊 Анализ за 2025-01

📝 Записей: 28
😊 Ср. настроение: 3.7/5
⏰ Ср. работа: 7.2ч/день
😴 Ср. сон: 7.1ч
💰 Заработок: $2,450
✅ Задач: 142
🏋️ Тренировки: 57.1%

🏆 Лучший день: 2025-01-15 (score: 92.5)
📉 Худший день: 2025-01-03 (score: 21.0)

🤖 AI Insights:
📈 Тренды: Продуктивность растёт к середине месяца...
✅ Хорошо: Стабильный сон 7+ часов...
⚠️ Улучшить: 3 дня с MINUS_KATE снижают score на 40%...
💡 Совет: Добавь утренние тренировки в дни с MINUS...
```

---

## Деплой на Railway

```bash
# 1. Установи Railway CLI
npm install -g @railway/cli

# 2. Авторизуйся
railway login

# 3. Инициализируй проект
railway init

# 4. Добавь переменные окружения
railway variables set TELEGRAM_BOT_TOKEN=...
railway variables set OPENAI_API_KEY=...
railway variables set NOTION_TOKEN=...
railway variables set NOTION_DATABASE_ID=...
railway variables set TELEGRAM_WEBHOOK_URL=https://your-app.railway.app/webhook

# 5. Деплой
railway up
```

### Docker (локально)

```bash
docker build -t daily-analyst .
docker run -p 8000:8000 --env-file .env daily-analyst
```

---

## Разработка

### Тесты

```bash
pytest -v                    # все тесты
pytest tests/test_cache.py   # только кэш
pytest --tb=short            # краткий вывод ошибок
```

### Линтинг

```bash
ruff check src/ tests/       # линтер
ruff format src/ tests/      # форматирование
mypy src/                    # типизация
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
├── main.py              # FastAPI + Telegram handlers (11 команд)
├── config.py            # Env variables (dataclass-based)
├── services/
│   ├── notion_service.py  # Notion API + retry + pagination
│   ├── ai_analyzer.py     # GPT analysis + local stats
│   └── charts_service.py  # Matplotlib charts (5 типов)
├── models/
│   └── journal_entry.py   # Pydantic models + enums
└── utils/
    ├── cache.py           # SQLite cache (30-day window)
    └── validators.py      # Input parsing + formatting
```

### Потоки данных

```
Telegram → /webhook → FastAPI → CommandHandler → NotionService → Cache
                                                              ↓
                                                  AIAnalyzer ← entries
                                                       ↓
                                               GPT-4o-mini → insights
                                                       ↓
                                              ChartsService → PNG
                                                       ↓
                                               Telegram ← reply + photo
```

---

## Лицензия

MIT
