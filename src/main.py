"""FastAPI + Telegram Jarvis: 24 commands, free-chat, proactive alerts, morning briefing."""

from __future__ import annotations

import asyncio
import functools
import hmac
import io
import logging
import sys
import time
import uuid
from collections import defaultdict
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import AsyncGenerator

import uvicorn
from fastapi import FastAPI, Request, Response, status
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from src.config import get_settings
from src.models.journal_entry import DailyRecord, Goal
from src.services.ai_analyzer import AIAnalyzer
from src.services.charts_service import ChartsService
from src.services.notion_service import NotionService
from src.utils.cache import CacheService
from src.utils.validators import (
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


# ── Auth decorator ──────────────────────────────────────────────────────────

def authorized(func):
    @functools.wraps(func)
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


# ── Safe Markdown sender ─────────────────────────────────────────────────

async def _safe_reply(message, text: str, **kwargs) -> None:
    """Send with Markdown, fallback to plain text if Telegram can't parse it."""
    try:
        await message.reply_text(text, parse_mode="Markdown", **kwargs)
    except Exception:
        # Strip Markdown and resend as plain text
        await message.reply_text(text, **kwargs)


async def _safe_send(chat_id: int, text: str, **kwargs) -> None:
    """Send via bot with Markdown, fallback to plain text."""
    try:
        await bot_app.bot.send_message(chat_id=chat_id, text=text, parse_mode="Markdown", **kwargs)
    except Exception:
        await bot_app.bot.send_message(chat_id=chat_id, text=text, **kwargs)


# ═══════════════════════════════════════════════════════════════════════════
# ORIGINAL COMMANDS (11)
# ═══════════════════════════════════════════════════════════════════════════

@authorized
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    text = (
        "⚡ *Я — твой наставник.*\n\n"
        "Я читаю ВЕСЬ твой Notion-дневник. Каждый день, каждый проёб, каждую серию.\n"
        "Я буду писать тебе сам: утром — приказ на день, вечером — разбор.\n"
        "Не жди похвалы. Жди правду.\n\n"
        "📊 *Аналитика:*\n"
        "/analyze — анализ месяца\n"
        "/compare — сравнить 2 месяца\n"
        "/correlations — матрица корреляций\n"
        "/day\\_types — классификатор дней\n"
        "/report — карточка месяца\n\n"
        "🔮 *Прогнозы:*\n"
        "/predict — burnout риск\n"
        "/tomorrow\\_mood — прогноз завтра\n"
        "/best\\_days — топ-3 дня\n\n"
        "🧠 *Глубокий анализ:*\n"
        "/dashboard — Life Score\n"
        "/formula — формула идеального дня\n"
        "/whatif `<сценарий>` — симулятор\n"
        "/anomalies — аномалии\n"
        "/milestones — вехи жизни\n\n"
        "🏆 *Геймификация:*\n"
        "/streaks — серии\n"
        "/habits `<name>` — тепловая карта\n"
        "/set\\_goal / /goals — цели\n\n"
        "🧪 /optimal\\_hours /kate\\_impact /testik\\_patterns\n"
        "😴 /sleep\\_optimizer /money\\_forecast /weak\\_spots\n\n"
        "💬 *Или просто напиши — я отвечу прямо, без сюсюканья.*"
    )
    await _safe_reply(update.message, text)


@authorized
async def cmd_analyze(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
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

    await _safe_reply(update.message, truncate_text(text))
    if records:
        await update.message.reply_photo(photo=io.BytesIO(charts_service.monthly_overview(records, label)))
        await update.message.reply_photo(photo=io.BytesIO(charts_service.activity_chart(records)))


@authorized
async def cmd_predict(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    await update.message.reply_text("🔮 Оцениваю риск...")
    records = await notion_service.get_recent(90)
    risk = await ai_analyzer.predict_burnout(records)
    emoji = {"low": "🟢", "medium": "🟡", "high": "🟠", "critical": "🔴"}.get(risk.risk_level, "⚪")
    text = f"🔥 *Burnout прогноз*\n\n{emoji} *{risk.risk_level.upper()}* ({risk.risk_score}%)\n\n"
    for f in risk.factors:
        text += f"• {f}\n"
    text += f"\n💡 {risk.recommendation}"
    await _safe_reply(update.message, truncate_text(text))
    if len(records) >= 3:
        await update.message.reply_photo(photo=io.BytesIO(charts_service.burnout_chart(records)))


@authorized
async def cmd_best_days(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
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
    await _safe_reply(update.message, text)


@authorized
async def cmd_optimal_hours(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    await update.message.reply_text("⏰ Анализирую...")
    records = await notion_service.get_recent(180)
    result = await ai_analyzer.optimal_hours(records)
    await _safe_reply(update.message, truncate_text(f"⏰ *Оптимальный режим*\n\n{result}"))


@authorized
async def cmd_kate_impact(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    await update.message.reply_text("💕 Анализирую...")
    records = await notion_service.get_recent(180)
    await _safe_reply(update.message, truncate_text(f"💕 *Kate Impact*\n\n{await ai_analyzer.kate_impact(records)}"))


@authorized
async def cmd_testik_patterns(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    await update.message.reply_text("🧪 Анализирую...")
    records = await notion_service.get_recent(180)
    await _safe_reply(update.message, truncate_text(f"🧪 *TESTIK*\n\n{await ai_analyzer.testik_patterns(records)}"))
    if records:
        await update.message.reply_photo(photo=io.BytesIO(charts_service.testik_chart(records)))


@authorized
async def cmd_sleep_optimizer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    await update.message.reply_text("😴 Анализирую...")
    records = await notion_service.get_recent(180)
    await _safe_reply(update.message, truncate_text(f"😴 *Сон*\n\n{await ai_analyzer.sleep_optimizer(records)}"))
    if records:
        await update.message.reply_photo(photo=io.BytesIO(charts_service.sleep_chart(records)))


@authorized
async def cmd_money_forecast(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    await update.message.reply_text("💼 Анализирую...")
    records = await notion_service.get_recent(180)
    await _safe_reply(update.message, truncate_text(f"💼 *Работа*\n\n{await ai_analyzer.money_forecast(records)}"))


@authorized
async def cmd_weak_spots(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    await update.message.reply_text("🔍 Ищу...")
    records = await notion_service.get_recent(90)
    await _safe_reply(update.message, truncate_text(f"🔍 *Слабые места*\n\n{await ai_analyzer.weak_spots(records)}"))


@authorized
async def cmd_tomorrow_mood(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    await update.message.reply_text("🔮 Предсказываю...")
    records = await notion_service.get_recent(14)
    await _safe_reply(update.message, truncate_text(f"🔮 *Прогноз*\n\n{await ai_analyzer.tomorrow_mood(records)}"))


# ═══════════════════════════════════════════════════════════════════════════
# PHASE 2 COMMANDS (streaks, compare, correlations, day_types, report, habits, goals)
# ═══════════════════════════════════════════════════════════════════════════

@authorized
async def cmd_streaks(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    records = await notion_service.get_recent(90)
    streaks = ai_analyzer.compute_streaks(records)
    if not streaks:
        await update.message.reply_text("📭 Нет данных.")
        return
    text = "🔥 *Текущие серии*\n\n"
    for s in streaks:
        bar = "🟩" * min(s.current, 10) + ("…" if s.current > 10 else "")
        text += f"{s.emoji} *{s.name}:* {s.current} дн. (рекорд: {s.record})\n{bar}\n\n"
    await _safe_reply(update.message, text)


@authorized
async def cmd_compare(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
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
    await _safe_reply(update.message, truncate_text(text))
    await update.message.reply_photo(photo=io.BytesIO(charts_service.compare_chart(comp)))


@authorized
async def cmd_correlations(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    await update.message.reply_text("🔗 Считаю корреляции...")
    records = await notion_service.get_recent(180)
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
    await _safe_reply(update.message, truncate_text(text))
    await update.message.reply_photo(photo=io.BytesIO(charts_service.correlation_chart(corr)))


@authorized
async def cmd_day_types(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    await update.message.reply_text("🏷️ Классифицирую дни...")
    records = await notion_service.get_recent(90)
    result = await ai_analyzer.classify_day_types(records)
    await _safe_reply(update.message, truncate_text(f"🏷️ *Типы дней*\n\n{result}"))


@authorized
async def cmd_report(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
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


@authorized
async def cmd_habits(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    arg = sanitize_command_arg(update.message.text or "").strip()
    if not arg:
        await update.message.reply_text(
            "📅 Укажи привычку:\n/habits gym\n/habits coding\n/habits sleep7\n/habits `<любой тег>`"
        )
        return
    records = await notion_service.get_recent(90)
    chart = charts_service.habit_heatmap(records, arg)
    await update.message.reply_photo(photo=io.BytesIO(chart), caption=f"📅 {arg.upper()} — 3 months")


@authorized
async def cmd_set_goal(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    arg = sanitize_command_arg(update.message.text or "")
    try:
        activity, count, period = parse_goal_arg(arg)
    except ValueError as e:
        await update.message.reply_text(f"❌ {e}")
        return
    uid = update.effective_user.id  # type: ignore
    goal = Goal(
        id=str(uuid.uuid4())[:8], user_id=uid, name=activity,
        target_activity=activity, target_count=count, period=period,
    )
    cache_service.upsert_goal(goal)
    await _safe_reply(update.message, f"✅ Цель: *{activity}* {count}/{period}")


@authorized
async def cmd_goals(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    uid = update.effective_user.id  # type: ignore
    goals = cache_service.get_goals(uid)
    if not goals:
        await _safe_reply(update.message, "📭 Нет целей. /set\\_goal для создания.")
        return
    records = await notion_service.get_recent(30)
    progress_list = ai_analyzer.compute_goal_progress(goals, records)
    text = "🎯 *Цели*\n\n"
    for p in progress_list:
        done = "✅" if p.is_complete else ""
        text += f"{p.bar} *{p.goal.name}* {p.current}/{p.target} ({p.percentage:.0f}%) {done}\n"
    await _safe_reply(update.message, text)


# ═══════════════════════════════════════════════════════════════════════════
# PHASE 3 — JARVIS LEVEL COMMANDS
# ═══════════════════════════════════════════════════════════════════════════

# ── /dashboard — Life Score ─────────────────────────────────────────────────

@authorized
async def cmd_dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    await update.message.reply_text("📊 Считаю Life Score...")
    records = await notion_service.get_recent(90)
    life = ai_analyzer.compute_life_score(records)

    text = f"🎯 *LIFE SCORE: {life.total:.0f}/100*"
    if life.trend_delta != 0:
        arrow = "↑" if life.trend_delta > 0 else "↓"
        text += f" ({arrow} {life.trend_delta:+.1f})"
    text += "\n\n"
    for d in life.dimensions:
        text += f"{d.emoji} {d.name}: {d.bar} {d.score:.0f}% {d.trend}\n"

    await _safe_reply(update.message, text)
    await update.message.reply_photo(photo=io.BytesIO(charts_service.dashboard_chart(life)))


# ── /formula — Perfect Day Formula ─────────────────────────────────────────

@authorized
async def cmd_formula(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    await update.message.reply_text("🧬 Вычисляю формулу...")
    records = await notion_service.get_recent(180)
    result = await ai_analyzer.formula(records)
    await _safe_reply(update.message, truncate_text(f"🧬 *Формула идеального дня*\n\n{result}"))


# ── /whatif — What-If Simulator ─────────────────────────────────────────────

@authorized
async def cmd_whatif(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    arg = sanitize_command_arg(update.message.text or "").strip()
    if not arg:
        await update.message.reply_text(
            "🔮 Примеры:\n"
            "/whatif без gym неделю\n"
            "/whatif testik minus 5 дней\n"
            "/whatif coding 8h/day 2 weeks"
        )
        return
    await update.message.reply_text("🔮 Моделирую сценарий...")
    records = await notion_service.get_recent(180)
    result = await ai_analyzer.whatif(records, arg)
    await _safe_reply(update.message, truncate_text(f"🔮 *What-If: {arg}*\n\n{result}"))


# ── /anomalies — Anomaly Detection ─────────────────────────────────────────

@authorized
async def cmd_anomalies(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    await update.message.reply_text("🔍 Ищу аномалии...")
    records = await notion_service.get_recent(90)
    anomalies = ai_analyzer.detect_anomalies(records)
    if not anomalies:
        await _safe_reply(update.message, "✅ Нет значимых аномалий за последний период.")
        return
    explanation = await ai_analyzer.explain_anomalies(records, anomalies)

    text = f"🔍 *Аномалии*\n\n{explanation}"
    await _safe_reply(update.message, truncate_text(text))
    if records:
        await update.message.reply_photo(photo=io.BytesIO(charts_service.anomaly_chart(records, anomalies)))


# ── /milestones — Life Milestones ───────────────────────────────────────────

@authorized
async def cmd_milestones(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    records = await notion_service.get_recent(365)
    milestones = ai_analyzer.detect_milestones(records)

    # Also load saved ones
    saved = cache_service.get_milestones(datetime.now(timezone.utc).year)
    seen_ids = {m.id for m in milestones}
    for s in saved:
        if s.id not in seen_ids:
            milestones.append(s)

    # Save new milestones
    for m in milestones:
        cache_service.add_milestone(m)

    milestones.sort(key=lambda m: m.entry_date, reverse=True)

    if not milestones:
        await update.message.reply_text("📭 Нет значимых вех пока.")
        return

    text = f"📌 *Milestones {datetime.now(timezone.utc).year}*\n\n"
    for m in milestones[:15]:
        text += f"{m.emoji} *{m.entry_date}* — {m.title}\n"
        if m.description:
            text += f"   {m.description}\n"
    await _safe_reply(update.message, truncate_text(text))


# ═══════════════════════════════════════════════════════════════════════════
# FREE CHAT — handle any text message
# ═══════════════════════════════════════════════════════════════════════════

@authorized
async def handle_free_chat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.text:
        return
    uid = update.effective_user.id  # type: ignore
    user_text = update.message.text.strip()

    if not user_text or user_text.startswith("/"):
        return

    # Save user message
    cache_service.save_message(uid, "user", user_text)

    # Get recent data for context (90 days — fast, enough for most questions)
    records = await notion_service.get_recent(90)
    chat_history = cache_service.get_recent_messages(uid, limit=20)

    # Generate response
    response = await ai_analyzer.free_chat(user_text, records, chat_history)

    # Save bot response
    cache_service.save_message(uid, "assistant", response)
    cache_service.cleanup_messages(uid, keep=50)

    await _safe_reply(update.message, truncate_text(response))


# ── Register all handlers ──────────────────────────────────────────────────

_commands = [
    ("start", cmd_start), ("analyze", cmd_analyze), ("predict", cmd_predict),
    ("best_days", cmd_best_days), ("optimal_hours", cmd_optimal_hours),
    ("kate_impact", cmd_kate_impact), ("testik_patterns", cmd_testik_patterns),
    ("sleep_optimizer", cmd_sleep_optimizer), ("money_forecast", cmd_money_forecast),
    ("weak_spots", cmd_weak_spots), ("tomorrow_mood", cmd_tomorrow_mood),
    ("streaks", cmd_streaks), ("compare", cmd_compare),
    ("correlations", cmd_correlations), ("day_types", cmd_day_types),
    ("report", cmd_report), ("habits", cmd_habits),
    ("set_goal", cmd_set_goal), ("goals", cmd_goals),
    ("dashboard", cmd_dashboard), ("formula", cmd_formula),
    ("whatif", cmd_whatif), ("anomalies", cmd_anomalies),
    ("milestones", cmd_milestones),
]
for name, handler in _commands:
    bot_app.add_handler(CommandHandler(name, handler))

# Free chat handler — catches all text that isn't a command
bot_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_free_chat))


# ═══════════════════════════════════════════════════════════════════════════
# BACKGROUND: Morning briefing + proactive alerts + weekly digest
# ═══════════════════════════════════════════════════════════════════════════

_last_briefing_date: str = ""
_last_evening_date: str = ""
_last_midday_date: str = ""
_last_alert_key: str = ""
_last_digest_date: str = ""


async def _background_loop() -> None:
    """Runs every 15 minutes: auto-sync, morning kick, midday check, evening review, alerts, weekly digest."""
    global _last_briefing_date, _last_evening_date, _last_midday_date, _last_alert_key, _last_digest_date
    await asyncio.sleep(30)

    while True:
        try:
            now = datetime.now(timezone.utc)
            today_str = now.strftime("%Y-%m-%d")
            uids = list(settings.telegram.allowed_user_ids)

            # Auto-sync: refresh RECENT data from Notion every cycle
            try:
                count = await notion_service.sync_recent()
                logger.info("Auto-sync complete: %d recent records", count)
            except Exception as e:
                logger.warning("Auto-sync error: %s", e)

            # ── Morning kick: 6:00-8:00 UTC (9:00-11:00 MSK) ──
            if 6 <= now.hour <= 8 and _last_briefing_date != today_str:
                _last_briefing_date = today_str
                try:
                    records = await notion_service.get_recent(14)
                    briefing = await ai_analyzer.morning_briefing(records)
                    for uid in uids:
                        try:
                            await _safe_send(uid, truncate_text(briefing))
                        except Exception as e:
                            logger.warning("Morning briefing send error: %s", e)
                except Exception as e:
                    logger.error("Morning briefing error: %s", e, exc_info=True)

            # ── Midday check: 11:00-12:00 UTC (14:00-15:00 MSK) ──
            if 11 <= now.hour <= 12 and _last_midday_date != today_str:
                _last_midday_date = today_str
                try:
                    records = await notion_service.get_recent(7)
                    nudge = await ai_analyzer.midday_check(records)
                    if nudge:
                        for uid in uids:
                            try:
                                await _safe_send(uid, truncate_text(nudge))
                            except Exception as e:
                                logger.warning("Midday check send error: %s", e)
                except Exception as e:
                    logger.error("Midday check error: %s", e, exc_info=True)

            # ── Evening review: 19:00-21:00 UTC (22:00-00:00 MSK) ──
            if 19 <= now.hour <= 21 and _last_evening_date != today_str:
                _last_evening_date = today_str
                try:
                    records = await notion_service.get_recent(14)
                    review = await ai_analyzer.evening_review(records)
                    for uid in uids:
                        try:
                            await _safe_send(uid, truncate_text(review))
                        except Exception as e:
                            logger.warning("Evening review send error: %s", e)
                except Exception as e:
                    logger.error("Evening review error: %s", e, exc_info=True)

            # ── Alerts: every 4 hours (deduplicated) ──
            alert_key = f"{today_str}-{now.hour // 4}"
            if now.minute < 20 and _last_alert_key != alert_key:
                _last_alert_key = alert_key
                try:
                    records = await notion_service.get_recent(14)
                    alerts = await ai_analyzer.enhanced_alerts(records)
                    if alerts:
                        alert_text = "⛔ *Наставник:*\n\n" + "\n".join(f"• {a}" for a in alerts)
                        for uid in uids:
                            try:
                                await _safe_send(uid, alert_text)
                            except Exception as e:
                                logger.warning("Alert send error: %s", e)
                except Exception as e:
                    logger.error("Alert loop error: %s", e, exc_info=True)

            # ── Weekly digest: Sunday 18:00 UTC (21:00 MSK) ──
            if now.weekday() == 6 and 17 <= now.hour <= 19 and _last_digest_date != today_str:
                _last_digest_date = today_str
                try:
                    records = await notion_service.get_recent(14)
                    digest = await ai_analyzer.weekly_digest(records)
                    for uid in uids:
                        try:
                            await _safe_send(uid, truncate_text(digest))
                        except Exception as e:
                            logger.warning("Digest send error: %s", e)
                except Exception as e:
                    logger.error("Digest error: %s", e, exc_info=True)

        except Exception as e:
            logger.error("Background loop error: %s", e, exc_info=True)

        await asyncio.sleep(15 * 60)  # check every 15 minutes


# ═══════════════════════════════════════════════════════════════════════════
# FASTAPI
# ═══════════════════════════════════════════════════════════════════════════

_polling_task: asyncio.Task | None = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    global _polling_task

    await bot_app.initialize()
    await bot_app.start()

    webhook_url = settings.telegram.webhook_url
    use_polling = False

    if webhook_url:
        if not webhook_url.startswith("https://") or "/webhook" not in webhook_url:
            logger.error(
                "TELEGRAM_WEBHOOK_URL invalid (must be https://.../.../webhook). "
                "Got: %s — falling back to polling mode.",
                webhook_url,
            )
            use_polling = True
        else:
            try:
                kwargs: dict[str, object] = {"url": webhook_url}
                if settings.telegram.webhook_secret:
                    kwargs["secret_token"] = settings.telegram.webhook_secret
                await bot_app.bot.set_webhook(**kwargs)
                logger.info("Webhook set → %s", webhook_url)
            except Exception as e:
                logger.error(
                    "Failed to set webhook (URL: %s): %s — falling back to polling mode.",
                    webhook_url, e,
                )
                use_polling = True
    else:
        logger.info("TELEGRAM_WEBHOOK_URL not set — using polling mode")
        use_polling = True

    if use_polling:
        # Remove any existing webhook so polling works
        try:
            await bot_app.bot.delete_webhook()
        except Exception:
            pass
        # Start polling in background
        _polling_task = asyncio.create_task(_run_polling())
        logger.info("Polling mode active — bot will pull updates from Telegram")

    # Start sync in background — don't block server startup
    startup_sync_task = asyncio.create_task(_startup_sync())
    bg_task = asyncio.create_task(_background_loop())
    logger.info("Mentor v4 started — 24 commands + free-chat + morning/evening/midday proactive + auto-sync")
    yield

    startup_sync_task.cancel()
    bg_task.cancel()
    if _polling_task:
        _polling_task.cancel()
    await bot_app.stop()
    await bot_app.shutdown()


async def _startup_sync() -> None:
    """Load full history from Notion in background (non-blocking)."""
    try:
        logger.info("Starting background data sync from Notion...")
        count = await notion_service.sync_all()
        logger.info("Startup sync complete: %d records loaded from Notion", count)
    except Exception as e:
        logger.warning("Startup sync failed (will retry in 30 min): %s", e)


async def _run_polling() -> None:
    """Pull updates from Telegram in a loop (fallback when webhook unavailable)."""
    logger.info("Starting polling loop...")
    offset = 0
    while True:
        try:
            updates = await bot_app.bot.get_updates(offset=offset, timeout=30)
            for update in updates:
                offset = update.update_id + 1
                await bot_app.process_update(update)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error("Polling error: %s", e)
            await asyncio.sleep(5)


app = FastAPI(title="Jarvis — Daily Analyst", version="3.0.0", lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "ts": datetime.now(timezone.utc).isoformat()}


@app.post("/webhook")
async def telegram_webhook(request: Request) -> Response:
    # Verify webhook secret if configured
    webhook_secret = settings.telegram.webhook_secret
    if webhook_secret:
        token = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if not hmac.compare_digest(token, webhook_secret):
            logger.warning("Webhook: invalid secret token from %s", request.client)
            return Response(status_code=status.HTTP_403_FORBIDDEN)

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
    return {"synced_days": count, "ts": datetime.now(timezone.utc).isoformat()}


if __name__ == "__main__":
    uvicorn.run("src.main:app", host="0.0.0.0", port=8000,
                reload=not settings.app.is_production, log_level=settings.app.log_level.lower())
