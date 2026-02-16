"""FastAPI + Telegram bot with 19 commands, proactive alerts, and weekly digest."""

from __future__ import annotations

import asyncio
import io
import logging
import sys
import time
import uuid
from collections import defaultdict
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import AsyncGenerator

import uvicorn
from fastapi import FastAPI, Request, Response, status
from telegram import Bot, Update
from telegram.ext import Application, CommandHandler, ContextTypes

from src.config import get_settings
from src.models.journal_entry import DailyRecord, Goal
from src.services.ai_analyzer import AIAnalyzer
from src.services.charts_service import ChartsService
from src.services.notion_service import NotionService
from src.utils.cache import CacheService
from src.utils.validators import (
    format_number,
    format_percentage,
    parse_compare_args,
    parse_goal_arg,
    parse_month_arg,
    sanitize_command_arg,
    truncate_text,
    validate_user_id,
)

# ── Logging ─────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format='{"time":"%(asctime)s","level":"%(levelname)s","module":"%(module)s","msg":"%(message)s"}',
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

# ── Rate limiter ────────────────────────────────────────────────────────────

_rate_limits: dict[int, list[float]] = defaultdict(list)


def _check_rate_limit(user_id: int, limit: int) -> bool:
    now = time.time()
    _rate_limits[user_id] = [t for t in _rate_limits[user_id] if now - t < 60]
    if len(_rate_limits[user_id]) >= limit:
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


# ── Auth ────────────────────────────────────────────────────────────────────

def authorized(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.effective_user or not update.message:
            return
        uid = update.effective_user.id
        s = get_settings()
        if not validate_user_id(uid, s.telegram.allowed_user_ids):
            await update.message.reply_text("🚫 Нет доступа.")
            return
        if not _check_rate_limit(uid, s.app.rate_limit_per_minute):
            await update.message.reply_text("⏳ Слишком много запросов.")
            return
        try:
            await func(update, context)
        except Exception as e:
            logger.error("Error user %s: %s", uid, e, exc_info=True)
            await update.message.reply_text(f"⚠️ Ошибка: {e}")
    return wrapper


# ═══════════════════════════════════════════════════════════════════════════
# COMMANDS
# ═══════════════════════════════════════════════════════════════════════════

@authorized
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    assert update.message
    text = (
        "👋 *Привет! Я твой AI Дневник-Аналитик*\n\n"
        "Читаю весь твой Notion-дневник и даю глубокий анализ жизни.\n\n"
        "📊 *Аналитика:*\n"
        "/analyze `[месяц]` — анализ месяца\n"
        "/compare `[мес1] [мес2]` — сравнить 2 месяца\n"
        "/correlations — матрица корреляций\n"
        "/day\\_types — классификатор дней\n"
        "/report `[месяц]` — карточка месяца\n\n"
        "🔮 *Прогнозы:*\n"
        "/predict — риск выгорания\n"
        "/tomorrow\\_mood — прогноз завтра\n"
        "/best\\_days `[месяц]` — топ-3 дня\n\n"
        "🧠 *Глубокий анализ:*\n"
        "/optimal\\_hours — оптимальный режим\n"
        "/kate\\_impact — влияние Kate\n"
        "/testik\\_patterns — TESTIK паттерны\n"
        "/sleep\\_optimizer — оптимизация сна\n"
        "/money\\_forecast — рабочие паттерны\n"
        "/weak\\_spots — слабые места\n\n"
        "🏆 *Геймификация:*\n"
        "/streaks — текущие серии\n"
        "/habits `<name>` — тепловая карта привычки\n"
        "/set\\_goal `<act> <n/period>` — поставить цель\n"
        "/goals — прогресс целей\n"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


# ── Monthly analysis ────────────────────────────────────────────────────────

@authorized
async def cmd_analyze(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    assert update.message
    await update.message.reply_text("🔄 Загружаю данные из Notion...")
    arg = sanitize_command_arg(update.message.text or "")
    try:
        year, month = parse_month_arg(arg)
    except ValueError as e:
        await update.message.reply_text(f"❌ {e}")
        return

    label = f"{year}-{month:02d}"
    records = await notion_service.get_daily_for_month(year, month)
    analysis = await ai_analyzer.analyze_month(records, label)

    text = (
        f"📊 *Анализ за {label}*\n\n"
        f"📝 Дней: {analysis.total_days}\n"
        f"⭐ Ср. оценка: {analysis.avg_rating_score}/6\n"
        f"⏰ Ср. часы: {analysis.avg_hours}ч\n"
    )
    if analysis.avg_sleep_hours:
        text += f"😴 Ср. сон: {analysis.avg_sleep_hours}ч\n"
    text += (
        f"📋 Задач: {analysis.total_tasks}\n"
        f"🏋️ GYM: {format_percentage(analysis.workout_rate)}\n"
        f"💻 Код: {format_percentage(analysis.coding_rate)}\n"
        f"🎓 Универ: {format_percentage(analysis.university_rate)}\n"
        f"💕 Kate: {format_percentage(analysis.kate_rate)}\n"
    )
    if analysis.activity_breakdown:
        text += "\n📈 *Топ активностей:*\n"
        for name, count in list(analysis.activity_breakdown.items())[:5]:
            text += f"  • {name}: {count}д\n"
    if analysis.best_day:
        text += f"\n🏆 Лучший: {analysis.best_day.entry_date} ({analysis.best_day.productivity_score})\n"
    if analysis.worst_day:
        text += f"📉 Худший: {analysis.worst_day.entry_date} ({analysis.worst_day.productivity_score})\n"
    text += f"\n🤖 *AI:*\n{analysis.ai_insights}"

    await update.message.reply_text(truncate_text(text), parse_mode="Markdown")
    if records:
        await update.message.reply_photo(photo=io.BytesIO(charts_service.monthly_overview(records, label)))
        await update.message.reply_photo(photo=io.BytesIO(charts_service.activity_chart(records)))


# ── Predict burnout ─────────────────────────────────────────────────────────

@authorized
async def cmd_predict(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    assert update.message
    await update.message.reply_text("🔮 Оцениваю риск...")
    records = await notion_service.get_recent(30)
    risk = await ai_analyzer.predict_burnout(records)
    emoji = {"low": "🟢", "medium": "🟡", "high": "🟠", "critical": "🔴"}.get(risk.risk_level, "⚪")
    text = f"🔥 *Burnout прогноз*\n\n{emoji} *{risk.risk_level.upper()}* ({risk.risk_score}%)\n\n"
    for f in risk.factors:
        text += f"• {f}\n"
    text += f"\n💡 {risk.recommendation}"
    await update.message.reply_text(truncate_text(text), parse_mode="Markdown")
    if len(records) >= 3:
        await update.message.reply_photo(photo=io.BytesIO(charts_service.burnout_chart(records)))


# ── Best days ───────────────────────────────────────────────────────────────

@authorized
async def cmd_best_days(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    assert update.message
    arg = sanitize_command_arg(update.message.text or "")
    try:
        y, m = parse_month_arg(arg)
    except ValueError as e:
        await update.message.reply_text(f"❌ {e}")
        return
    records = await notion_service.get_daily_for_month(y, m)
    best = await ai_analyzer.best_days(records)
    if not best:
        await update.message.reply_text("📭 Нет данных.")
        return
    medals = ["🥇", "🥈", "🥉"]
    text = f"🏆 *Топ-3 ({y}-{m:02d})*\n\n"
    for i, d in enumerate(best):
        r = d.rating.emoji if d.rating else "❓"
        acts = ", ".join(d.activities[:5]) or "—"
        text += f"{medals[i]} *{d.entry_date}* — {d.productivity_score}pt {r}\n   {acts}\n\n"
    await update.message.reply_text(text, parse_mode="Markdown")


# ── Optimal hours ───────────────────────────────────────────────────────────

@authorized
async def cmd_optimal_hours(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    assert update.message
    await update.message.reply_text("⏰ Анализирую...")
    records = await notion_service.get_recent(60)
    await update.message.reply_text(truncate_text(f"⏰ *Оптимальный режим*\n\n{await ai_analyzer.optimal_hours(records)}"), parse_mode="Markdown")


@authorized
async def cmd_kate_impact(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    assert update.message
    await update.message.reply_text("💕 Анализирую...")
    records = await notion_service.get_recent(90)
    await update.message.reply_text(truncate_text(f"💕 *Kate Impact*\n\n{await ai_analyzer.kate_impact(records)}"), parse_mode="Markdown")


@authorized
async def cmd_testik_patterns(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    assert update.message
    await update.message.reply_text("🧪 Анализирую...")
    records = await notion_service.get_recent(90)
    await update.message.reply_text(truncate_text(f"🧪 *TESTIK*\n\n{await ai_analyzer.testik_patterns(records)}"), parse_mode="Markdown")
    if records:
        await update.message.reply_photo(photo=io.BytesIO(charts_service.testik_chart(records)))


@authorized
async def cmd_sleep_optimizer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    assert update.message
    await update.message.reply_text("😴 Анализирую...")
    records = await notion_service.get_recent(60)
    await update.message.reply_text(truncate_text(f"😴 *Сон*\n\n{await ai_analyzer.sleep_optimizer(records)}"), parse_mode="Markdown")
    if records:
        await update.message.reply_photo(photo=io.BytesIO(charts_service.sleep_chart(records)))


@authorized
async def cmd_money_forecast(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    assert update.message
    await update.message.reply_text("💼 Анализирую...")
    records = await notion_service.get_recent(90)
    await update.message.reply_text(truncate_text(f"💼 *Работа*\n\n{await ai_analyzer.money_forecast(records)}"), parse_mode="Markdown")


@authorized
async def cmd_weak_spots(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    assert update.message
    await update.message.reply_text("🔍 Ищу...")
    records = await notion_service.get_recent(30)
    await update.message.reply_text(truncate_text(f"🔍 *Слабые места*\n\n{await ai_analyzer.weak_spots(records)}"), parse_mode="Markdown")


@authorized
async def cmd_tomorrow_mood(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    assert update.message
    await update.message.reply_text("🔮 Предсказываю...")
    records = await notion_service.get_recent(14)
    await update.message.reply_text(truncate_text(f"🔮 *Прогноз*\n\n{await ai_analyzer.tomorrow_mood(records)}"), parse_mode="Markdown")


# ── NEW: Streaks ────────────────────────────────────────────────────────────

@authorized
async def cmd_streaks(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    assert update.message
    records = await notion_service.get_recent(90)
    streaks = ai_analyzer.compute_streaks(records)
    if not streaks:
        await update.message.reply_text("📭 Нет данных.")
        return
    text = "🔥 *Текущие серии*\n\n"
    for s in streaks:
        bar = "🟩" * min(s.current, 10) + ("…" if s.current > 10 else "")
        text += f"{s.emoji} *{s.name}:* {s.current} дн. (рекорд: {s.record})\n{bar}\n\n"
    await update.message.reply_text(text, parse_mode="Markdown")


# ── NEW: Compare months ────────────────────────────────────────────────────

@authorized
async def cmd_compare(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    assert update.message
    arg = sanitize_command_arg(update.message.text or "")
    try:
        (y1, m1), (y2, m2) = parse_compare_args(arg)
    except ValueError as e:
        await update.message.reply_text(f"❌ {e}\nПример: /compare январь февраль")
        return
    await update.message.reply_text("📊 Сравниваю...")
    rec_a = await notion_service.get_daily_for_month(y1, m1)
    rec_b = await notion_service.get_daily_for_month(y2, m2)
    la, lb = f"{y1}-{m1:02d}", f"{y2}-{m2:02d}"
    comp = await ai_analyzer.compare_months(rec_a, rec_b, la, lb)

    text = f"📊 *{la} vs {lb}*\n\n"
    for d in comp.deltas:
        text += f"{d.emoji} {d.name}: {d.value_a:.1f} → {d.value_b:.1f} ({d.trend_emoji} {d.arrow}{abs(d.delta):.1f})\n"
    text += f"\n🤖 *AI:*\n{comp.ai_insights}"
    await update.message.reply_text(truncate_text(text), parse_mode="Markdown")
    await update.message.reply_photo(photo=io.BytesIO(charts_service.compare_chart(comp)))


# ── NEW: Correlations ───────────────────────────────────────────────────────

@authorized
async def cmd_correlations(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    assert update.message
    await update.message.reply_text("🔗 Считаю корреляции...")
    records = await notion_service.get_recent(90)
    corr = await ai_analyzer.compute_correlations(records)
    text = f"🔗 *Корреляции с оценкой дня*\n(baseline: {corr.baseline_rating:.1f}/6)\n\n"
    for c in sorted(corr.correlations, key=lambda x: x.vs_baseline, reverse=True):
        arrow = "🟢" if c.vs_baseline >= 0 else "🔴"
        text += f"{arrow} *{c.activity}*: {c.avg_rating:.1f}/6 ({c.count}д, {c.vs_baseline:+.1f})\n"
    if corr.combo_insights:
        text += "\n🔀 *Комбо:*\n"
        for ci in corr.combo_insights[:5]:
            text += f"  • {ci}\n"
    text += f"\n🤖 {corr.ai_insights}"
    await update.message.reply_text(truncate_text(text), parse_mode="Markdown")
    await update.message.reply_photo(photo=io.BytesIO(charts_service.correlation_chart(corr)))


# ── NEW: Day types ──────────────────────────────────────────────────────────

@authorized
async def cmd_day_types(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    assert update.message
    await update.message.reply_text("🏷️ Классифицирую дни...")
    records = await notion_service.get_recent(90)
    result = await ai_analyzer.classify_day_types(records)
    await update.message.reply_text(truncate_text(f"🏷️ *Типы дней*\n\n{result}"), parse_mode="Markdown")


# ── NEW: Report card ────────────────────────────────────────────────────────

@authorized
async def cmd_report(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    assert update.message
    arg = sanitize_command_arg(update.message.text or "")
    try:
        y, m = parse_month_arg(arg)
    except ValueError as e:
        await update.message.reply_text(f"❌ {e}")
        return
    await update.message.reply_text("🎴 Генерирую карточку...")
    label = f"{y}-{m:02d}"
    records = await notion_service.get_daily_for_month(y, m)
    streaks = ai_analyzer.compute_streaks(records)
    chart = charts_service.report_card(records, label, streaks)
    await update.message.reply_photo(photo=io.BytesIO(chart), caption=f"📋 Report Card: {label}")


# ── NEW: Habits heatmap ─────────────────────────────────────────────────────

@authorized
async def cmd_habits(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    assert update.message
    arg = sanitize_command_arg(update.message.text or "").strip()
    if not arg:
        await update.message.reply_text(
            "📅 Укажи привычку:\n"
            "/habits gym\n/habits coding\n/habits university\n"
            "/habits kate\n/habits sleep7\n/habits `<любой тег>`"
        )
        return
    records = await notion_service.get_recent(90)
    chart = charts_service.habit_heatmap(records, arg)
    await update.message.reply_photo(photo=io.BytesIO(chart), caption=f"📅 {arg.upper()} — 3 months")


# ── NEW: Goals ──────────────────────────────────────────────────────────────

@authorized
async def cmd_set_goal(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    assert update.message
    arg = sanitize_command_arg(update.message.text or "")
    try:
        activity, count, period = parse_goal_arg(arg)
    except ValueError as e:
        await update.message.reply_text(f"❌ {e}")
        return
    uid = update.effective_user.id  # type: ignore
    goal = Goal(
        id=str(uuid.uuid4())[:8],
        user_id=uid,
        name=activity,
        target_activity=activity,
        target_count=count,
        period=period,
    )
    cache_service.upsert_goal(goal)
    await update.message.reply_text(f"✅ Цель установлена: *{activity}* {count}/{period}", parse_mode="Markdown")


@authorized
async def cmd_goals(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    assert update.message
    uid = update.effective_user.id  # type: ignore
    goals = cache_service.get_goals(uid)
    if not goals:
        await update.message.reply_text("📭 Нет целей. Используй /set\\_goal для создания.", parse_mode="Markdown")
        return
    records = await notion_service.get_recent(30)
    progress_list = ai_analyzer.compute_goal_progress(goals, records)
    text = "🎯 *Цели*\n\n"
    for p in progress_list:
        done = "✅" if p.is_complete else ""
        text += f"{p.bar} *{p.goal.name}* {p.current}/{p.target} ({p.percentage:.0f}%) {done}\n"
    await update.message.reply_text(text, parse_mode="Markdown")


# ── Register all handlers ──────────────────────────────────────────────────

for name, handler in [
    ("start", cmd_start), ("analyze", cmd_analyze), ("predict", cmd_predict),
    ("best_days", cmd_best_days), ("optimal_hours", cmd_optimal_hours),
    ("kate_impact", cmd_kate_impact), ("testik_patterns", cmd_testik_patterns),
    ("sleep_optimizer", cmd_sleep_optimizer), ("money_forecast", cmd_money_forecast),
    ("weak_spots", cmd_weak_spots), ("tomorrow_mood", cmd_tomorrow_mood),
    ("streaks", cmd_streaks), ("compare", cmd_compare),
    ("correlations", cmd_correlations), ("day_types", cmd_day_types),
    ("report", cmd_report), ("habits", cmd_habits),
    ("set_goal", cmd_set_goal), ("goals", cmd_goals),
]:
    bot_app.add_handler(CommandHandler(name, handler))


# ═══════════════════════════════════════════════════════════════════════════
# BACKGROUND: Proactive alerts + weekly digest
# ═══════════════════════════════════════════════════════════════════════════

async def _background_alerts_loop() -> None:
    """Check for alerts every 6 hours and send weekly digest on Sundays."""
    await asyncio.sleep(30)  # let bot start
    while True:
        try:
            records = await notion_service.get_recent(14, force_refresh=True)
            alerts = ai_analyzer.check_alerts(records)

            if alerts and settings.telegram.allowed_user_ids:
                alert_text = "⚡ *Proactive Alert*\n\n" + "\n".join(f"• {a}" for a in alerts)
                for uid in settings.telegram.allowed_user_ids:
                    try:
                        await bot_app.bot.send_message(chat_id=uid, text=alert_text, parse_mode="Markdown")
                    except Exception as e:
                        logger.warning("Failed to send alert to %s: %s", uid, e)

            # Weekly digest on Sundays at ~18:00 check
            now = datetime.utcnow()
            if now.weekday() == 6 and 15 <= now.hour <= 18:
                week_records = await notion_service.get_recent(14)
                digest = await ai_analyzer.weekly_digest(week_records)
                digest_text = f"📋 *Еженедельный дайджест*\n\n{digest}"
                for uid in settings.telegram.allowed_user_ids:
                    try:
                        await bot_app.bot.send_message(
                            chat_id=uid, text=truncate_text(digest_text), parse_mode="Markdown"
                        )
                    except Exception as e:
                        logger.warning("Failed to send digest to %s: %s", uid, e)

        except Exception as e:
            logger.error("Background loop error: %s", e, exc_info=True)

        await asyncio.sleep(6 * 3600)  # every 6 hours


# ═══════════════════════════════════════════════════════════════════════════
# FASTAPI
# ═══════════════════════════════════════════════════════════════════════════

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    await bot_app.initialize()
    await bot_app.start()

    webhook_url = settings.telegram.webhook_url
    if webhook_url:
        await bot_app.bot.set_webhook(url=webhook_url)
        logger.info("Webhook → %s", webhook_url)

    # Start background alerts
    alert_task = asyncio.create_task(_background_alerts_loop())

    logger.info("Daily Analyst v2 started — 19 commands + alerts")
    yield

    alert_task.cancel()
    await bot_app.stop()
    await bot_app.shutdown()


app = FastAPI(title="Daily Analyst Bot", version="2.0.0", lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "ts": datetime.utcnow().isoformat()}


@app.post("/webhook")
async def telegram_webhook(request: Request) -> Response:
    try:
        data = await request.json()
        update = Update.de_json(data, bot_app.bot)
        await bot_app.process_update(update)
    except Exception as e:
        logger.error("Webhook: %s", e, exc_info=True)
    return Response(status_code=status.HTTP_200_OK)


@app.get("/sync")
async def manual_sync() -> dict[str, object]:
    count = await notion_service.sync_all()
    return {"synced_days": count, "ts": datetime.utcnow().isoformat()}


if __name__ == "__main__":
    uvicorn.run("src.main:app", host="0.0.0.0", port=8000,
                reload=not settings.app.is_production, log_level=settings.app.log_level.lower())
