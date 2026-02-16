"""
FastAPI application with Telegram bot webhook integration.

Adapted for the real Notion 'Tasks' database structure:
- Multiple task entries per day (MARK, CODING, GYM, etc.)
- MARK entry body contains sleep info, TESTIK status, and day rating
"""

from __future__ import annotations

import io
import logging
import sys
import time
from collections import Counter, defaultdict
from contextlib import asynccontextmanager
from datetime import datetime
from typing import AsyncGenerator

import uvicorn
from fastapi import FastAPI, Request, Response, status
from telegram import Bot, Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)

from src.config import get_settings
from src.models.journal_entry import DailyRecord
from src.services.ai_analyzer import AIAnalyzer
from src.services.charts_service import ChartsService
from src.services.notion_service import NotionService
from src.utils.cache import CacheService
from src.utils.validators import (
    format_number,
    format_percentage,
    parse_month_arg,
    sanitize_command_arg,
    truncate_text,
    validate_user_id,
)

# ── Logging ─────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format='{"time":"%(asctime)s","level":"%(levelname)s","module":"%(module)s","message":"%(message)s"}',
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

# ── Rate limiter ────────────────────────────────────────────────────────────

_rate_limits: dict[int, list[float]] = defaultdict(list)


def _check_rate_limit(user_id: int, max_per_minute: int) -> bool:
    now = time.time()
    window = [t for t in _rate_limits[user_id] if now - t < 60]
    _rate_limits[user_id] = window
    if len(window) >= max_per_minute:
        return False
    _rate_limits[user_id].append(now)
    return True


# ── Services ────────────────────────────────────────────────────────────────

cache_service = CacheService()
notion_service = NotionService(cache=cache_service)
ai_analyzer = AIAnalyzer()
charts_service = ChartsService()

settings = get_settings()
bot_app = Application.builder().token(settings.telegram.bot_token).build()


# ── Auth decorator ──────────────────────────────────────────────────────────

def authorized(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.effective_user or not update.message:
            return
        user_id = update.effective_user.id
        s = get_settings()
        if not validate_user_id(user_id, s.telegram.allowed_user_ids):
            await update.message.reply_text("🚫 Нет доступа.")
            return
        if not _check_rate_limit(user_id, s.app.rate_limit_per_minute):
            await update.message.reply_text("⏳ Слишком много запросов. Подожди минутку.")
            return
        try:
            await func(update, context)
        except Exception as e:
            logger.error("Command error for user %s: %s", user_id, e, exc_info=True)
            await update.message.reply_text(f"⚠️ Ошибка: {e}")
    return wrapper


# ── Bot commands ────────────────────────────────────────────────────────────

@authorized
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    assert update.message
    text = (
        "👋 *Привет! Я твой Дневник-Аналитик*\n\n"
        "Анализирую твой Notion-дневник (Tasks) с помощью AI.\n\n"
        "📋 *Команды:*\n"
        "/analyze `[месяц]` — анализ месяца с графиками\n"
        "/predict — риск выгорания на 5 дней\n"
        "/best\\_days `[месяц]` — топ-3 продуктивных дня\n"
        "/optimal\\_hours — лучшее время для работы\n"
        "/kate\\_impact — корреляция с Kate\n"
        "/testik\\_patterns — анализ TESTIK влияния\n"
        "/sleep\\_optimizer — оптимизация сна\n"
        "/money\\_forecast — анализ рабочих паттернов\n"
        "/weak\\_spots — слабые места\n"
        "/tomorrow\\_mood — прогноз завтрашней оценки\n\n"
        "💡 _Данные из Notion кэшируются на 5 мин._"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


@authorized
async def cmd_analyze(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    assert update.message
    await update.message.reply_text("🔄 Загружаю данные из Notion...")

    arg = sanitize_command_arg(update.message.text or "")
    try:
        year, month = parse_month_arg(arg)
    except ValueError as e:
        await update.message.reply_text(f"❌ {e}\nПример: /analyze 2025-01 или /analyze january")
        return

    month_label = f"{year}-{month:02d}"
    records = await notion_service.get_daily_for_month(year, month)
    analysis = await ai_analyzer.analyze_month(records, month_label)

    text = (
        f"📊 *Анализ за {month_label}*\n\n"
        f"📝 Дней с записями: {analysis.total_days}\n"
        f"⭐ Ср. оценка дня: {analysis.avg_rating_score}/6\n"
        f"⏰ Ср. часы: {analysis.avg_hours}ч/день\n"
    )
    if analysis.avg_sleep_hours is not None:
        text += f"😴 Ср. сон: {analysis.avg_sleep_hours}ч\n"
    text += (
        f"📋 Всего задач: {analysis.total_tasks}\n"
        f"🏋️ Тренировки: {format_percentage(analysis.workout_rate)}\n"
        f"🎓 Универ: {format_percentage(analysis.university_rate)}\n"
        f"💻 Кодинг: {format_percentage(analysis.coding_rate)}\n"
        f"💕 Kate: {format_percentage(analysis.kate_rate)}\n"
    )

    if analysis.activity_breakdown:
        top5 = list(analysis.activity_breakdown.items())[:5]
        text += "\n📈 *Топ активностей:*\n"
        for name, count in top5:
            text += f"  • {name}: {count} дней\n"

    if analysis.best_day:
        b = analysis.best_day
        text += f"\n🏆 Лучший день: {b.entry_date} (score: {b.productivity_score})\n"
    if analysis.worst_day:
        w = analysis.worst_day
        text += f"📉 Худший день: {w.entry_date} (score: {w.productivity_score})\n"

    text += f"\n🤖 *AI Insights:*\n{analysis.ai_insights}"

    await update.message.reply_text(truncate_text(text), parse_mode="Markdown")

    if records:
        chart = charts_service.monthly_overview(records, month_label)
        await update.message.reply_photo(photo=io.BytesIO(chart), caption=f"Charts: {month_label}")

        act_chart = charts_service.activity_chart(records)
        await update.message.reply_photo(photo=io.BytesIO(act_chart), caption="Activity breakdown")


@authorized
async def cmd_predict(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    assert update.message
    await update.message.reply_text("🔮 Оцениваю риск выгорания...")

    records = await notion_service.get_recent(days=30)
    risk = await ai_analyzer.predict_burnout(records)

    emoji = {"low": "🟢", "medium": "🟡", "high": "🟠", "critical": "🔴"}.get(risk.risk_level, "⚪")

    text = (
        f"🔥 *Прогноз выгорания (5 дней)*\n\n"
        f"{emoji} Уровень: *{risk.risk_level.upper()}* ({risk.risk_score}%)\n\n"
        f"📋 *Факторы:*\n"
    )
    for f in risk.factors:
        text += f"  • {f}\n"
    text += f"\n💡 *Рекомендации:*\n{risk.recommendation}"

    await update.message.reply_text(truncate_text(text), parse_mode="Markdown")

    if len(records) >= 3:
        chart = charts_service.burnout_chart(records)
        await update.message.reply_photo(photo=io.BytesIO(chart), caption="Burnout risk index")


@authorized
async def cmd_best_days(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    assert update.message
    arg = sanitize_command_arg(update.message.text or "")
    try:
        year, month = parse_month_arg(arg)
    except ValueError as e:
        await update.message.reply_text(f"❌ {e}")
        return

    records = await notion_service.get_daily_for_month(year, month)
    best = await ai_analyzer.best_days(records)

    if not best:
        await update.message.reply_text("📭 Нет данных за этот период.")
        return

    text = f"🏆 *Топ-3 продуктивных дня ({year}-{month:02d})*\n\n"
    medals = ["🥇", "🥈", "🥉"]
    for i, day in enumerate(best):
        rating_str = day.rating.emoji if day.rating else "❓"
        acts = ", ".join(day.activities[:5]) if day.activities else "—"
        text += (
            f"{medals[i]} *{day.entry_date}*\n"
            f"   Score: {day.productivity_score} | {rating_str} | {day.total_hours}ч\n"
            f"   Activities: {acts}\n\n"
        )

    await update.message.reply_text(text, parse_mode="Markdown")


@authorized
async def cmd_optimal_hours(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    assert update.message
    await update.message.reply_text("⏰ Анализирую оптимальное время работы...")
    records = await notion_service.get_recent(days=60)
    result = await ai_analyzer.optimal_hours(records)
    await update.message.reply_text(f"⏰ *Оптимальные часы работы*\n\n{result}", parse_mode="Markdown")


@authorized
async def cmd_kate_impact(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    assert update.message
    await update.message.reply_text("💕 Анализирую корреляции...")
    records = await notion_service.get_recent(days=90)
    result = await ai_analyzer.kate_impact(records)
    await update.message.reply_text(f"💕 *Влияние Kate*\n\n{result}", parse_mode="Markdown")


@authorized
async def cmd_testik_patterns(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    assert update.message
    await update.message.reply_text("🧪 Анализирую паттерны TESTIK...")
    records = await notion_service.get_recent(days=90)
    result = await ai_analyzer.testik_patterns(records)
    await update.message.reply_text(truncate_text(f"🧪 *Паттерны TESTIK*\n\n{result}"), parse_mode="Markdown")

    if records:
        chart = charts_service.testik_chart(records)
        await update.message.reply_photo(photo=io.BytesIO(chart), caption="TESTIK vs Metrics")


@authorized
async def cmd_sleep_optimizer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    assert update.message
    await update.message.reply_text("😴 Анализирую паттерны сна...")
    records = await notion_service.get_recent(days=60)
    result = await ai_analyzer.sleep_optimizer(records)
    await update.message.reply_text(truncate_text(f"😴 *Оптимизация сна*\n\n{result}"), parse_mode="Markdown")

    if records:
        chart = charts_service.sleep_chart(records)
        await update.message.reply_photo(photo=io.BytesIO(chart), caption="Sleep vs Productivity")


@authorized
async def cmd_money_forecast(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    assert update.message
    await update.message.reply_text("💼 Анализирую рабочие паттерны...")
    records = await notion_service.get_recent(days=90)
    result = await ai_analyzer.money_forecast(records)
    await update.message.reply_text(truncate_text(f"💼 *Рабочие паттерны*\n\n{result}"), parse_mode="Markdown")


@authorized
async def cmd_weak_spots(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    assert update.message
    await update.message.reply_text("🔍 Ищу слабые места...")
    records = await notion_service.get_recent(days=30)
    result = await ai_analyzer.weak_spots(records)
    await update.message.reply_text(truncate_text(f"🔍 *Слабые места*\n\n{result}"), parse_mode="Markdown")


@authorized
async def cmd_tomorrow_mood(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    assert update.message
    await update.message.reply_text("🔮 Предсказываю завтрашний день...")
    records = await notion_service.get_recent(days=14)
    result = await ai_analyzer.tomorrow_mood(records)
    await update.message.reply_text(truncate_text(f"🔮 *Прогноз завтра*\n\n{result}"), parse_mode="Markdown")


# ── Register handlers ───────────────────────────────────────────────────────

bot_app.add_handler(CommandHandler("start", cmd_start))
bot_app.add_handler(CommandHandler("analyze", cmd_analyze))
bot_app.add_handler(CommandHandler("predict", cmd_predict))
bot_app.add_handler(CommandHandler("best_days", cmd_best_days))
bot_app.add_handler(CommandHandler("optimal_hours", cmd_optimal_hours))
bot_app.add_handler(CommandHandler("kate_impact", cmd_kate_impact))
bot_app.add_handler(CommandHandler("testik_patterns", cmd_testik_patterns))
bot_app.add_handler(CommandHandler("sleep_optimizer", cmd_sleep_optimizer))
bot_app.add_handler(CommandHandler("money_forecast", cmd_money_forecast))
bot_app.add_handler(CommandHandler("weak_spots", cmd_weak_spots))
bot_app.add_handler(CommandHandler("tomorrow_mood", cmd_tomorrow_mood))


# ── FastAPI ─────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    await bot_app.initialize()
    await bot_app.start()

    webhook_url = settings.telegram.webhook_url
    if webhook_url:
        await bot_app.bot.set_webhook(url=webhook_url)
        logger.info("Webhook set to %s", webhook_url)
    else:
        logger.warning("No TELEGRAM_WEBHOOK_URL — webhook not configured")

    logger.info("Daily Analyst bot started")
    yield

    await bot_app.stop()
    await bot_app.shutdown()
    logger.info("Bot stopped")


app = FastAPI(title="Daily Analyst Bot", version="2.0.0", lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}


@app.post("/webhook")
async def telegram_webhook(request: Request) -> Response:
    try:
        data = await request.json()
        update = Update.de_json(data, bot_app.bot)
        await bot_app.process_update(update)
        return Response(status_code=status.HTTP_200_OK)
    except Exception as e:
        logger.error("Webhook error: %s", e, exc_info=True)
        return Response(status_code=status.HTTP_200_OK)


@app.get("/sync")
async def manual_sync() -> dict[str, object]:
    count = await notion_service.sync_all()
    return {"synced_days": count, "timestamp": datetime.utcnow().isoformat()}


if __name__ == "__main__":
    uvicorn.run(
        "src.main:app",
        host="0.0.0.0",
        port=8000,
        reload=not settings.app.is_production,
        log_level=settings.app.log_level.lower(),
    )
