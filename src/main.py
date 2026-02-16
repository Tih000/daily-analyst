"""
Telegram bot for productivity analysis using Notion journal data,
GPT-powered insights, and Matplotlib charts.

Runs in long-polling mode (no webhook, no FastAPI).
"""

from __future__ import annotations

import functools
import io
import logging
import signal
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Callable, Coroutine

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from src.config import get_settings
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

# ── Logging setup ───────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format='{"time":"%(asctime)s","level":"%(levelname)s","module":"%(module)s","message":"%(message)s"}',
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

# ── Rate limiter (in-memory with periodic cleanup) ──────────────────────────

_rate_limits: dict[int, list[float]] = defaultdict(list)
_RATE_LIMIT_CLEANUP_INTERVAL = 300
_last_cleanup: float = 0.0


def _check_rate_limit(user_id: int, max_per_minute: int) -> bool:
    """Return True if request is allowed, False if rate limited."""
    global _last_cleanup
    now = time.time()

    if now - _last_cleanup > _RATE_LIMIT_CLEANUP_INTERVAL:
        stale_users = [
            uid for uid, timestamps in _rate_limits.items()
            if not timestamps or now - timestamps[-1] > 120
        ]
        for uid in stale_users:
            del _rate_limits[uid]
        _last_cleanup = now

    window = [t for t in _rate_limits[user_id] if now - t < 60]
    _rate_limits[user_id] = window
    if len(window) >= max_per_minute:
        return False
    _rate_limits[user_id].append(now)
    return True


# ── Service singletons ─────────────────────────────────────────────────────

cache_service = CacheService()
notion_service = NotionService(cache=cache_service)
ai_analyzer = AIAnalyzer()
charts_service = ChartsService()


# ── Auth & rate limit decorator ─────────────────────────────────────────────

def authorized(func: Callable[..., Coroutine[Any, Any, None]]) -> Callable[..., Coroutine[Any, Any, None]]:
    """Decorator: check user auth + rate limit before running command."""

    @functools.wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user = update.effective_user
        message = update.message or (update.callback_query.message if update.callback_query else None)
        if not user or not message:
            return

        user_id = user.id
        s = get_settings()

        if not validate_user_id(user_id, s.telegram.allowed_user_ids):
            await message.reply_text("🚫 Нет доступа. Обратись к администратору.")
            return

        if not _check_rate_limit(user_id, s.app.rate_limit_per_minute):
            await message.reply_text("⏳ Слишком много запросов. Подожди минутку.")
            return

        try:
            await func(update, context)
        except Exception as e:
            logger.error("Command error for user %s: %s", user_id, e, exc_info=True)
            await message.reply_text("⚠️ Произошла ошибка при обработке команды. Попробуй позже.")

    return wrapper


# ── Inline keyboard helpers ─────────────────────────────────────────────────

def _main_menu_keyboard() -> InlineKeyboardMarkup:
    """Build the main menu inline keyboard."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📊 Анализ месяца", callback_data="menu_analyze"),
            InlineKeyboardButton("🔮 Выгорание", callback_data="menu_predict"),
        ],
        [
            InlineKeyboardButton("🏆 Лучшие дни", callback_data="menu_best_days"),
            InlineKeyboardButton("⏰ Часы работы", callback_data="menu_optimal_hours"),
        ],
        [
            InlineKeyboardButton("💕 Влияние Kate", callback_data="menu_kate_impact"),
            InlineKeyboardButton("🧪 TESTIK", callback_data="menu_testik_patterns"),
        ],
        [
            InlineKeyboardButton("😴 Сон", callback_data="menu_sleep_optimizer"),
            InlineKeyboardButton("💰 Заработок", callback_data="menu_money_forecast"),
        ],
        [
            InlineKeyboardButton("🔍 Слабые места", callback_data="menu_weak_spots"),
            InlineKeyboardButton("🔮 Настроение", callback_data="menu_tomorrow_mood"),
        ],
        [
            InlineKeyboardButton("🔄 Синхронизация", callback_data="menu_sync"),
        ],
    ])


def _month_picker_keyboard(command_prefix: str) -> InlineKeyboardMarkup:
    """Build a month picker for commands that accept a month argument."""
    now = datetime.now(timezone.utc)
    buttons: list[list[InlineKeyboardButton]] = []
    month_names_ru = [
        "", "Янв", "Фев", "Мар", "Апр", "Май", "Июн",
        "Июл", "Авг", "Сен", "Окт", "Ноя", "Дек",
    ]
    row: list[InlineKeyboardButton] = []
    for offset in range(5, -1, -1):
        m = now.month - offset
        y = now.year
        if m <= 0:
            m += 12
            y -= 1
        label = f"{month_names_ru[m]} {y}"
        row.append(InlineKeyboardButton(label, callback_data=f"{command_prefix}_{y}-{m:02d}"))
        if len(row) == 3:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton("« Назад", callback_data="menu_back")])
    return InlineKeyboardMarkup(buttons)


async def _send_typing(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send 'typing' chat action to show bot is processing."""
    chat_id = update.effective_chat.id if update.effective_chat else None
    if chat_id:
        try:
            await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
        except Exception:
            pass  # non-critical, don't break command flow


def _get_message(update: Update):
    """Extract the usable message object from update (command or callback)."""
    return update.message or (update.callback_query.message if update.callback_query else None)


async def _safe_send_chart(
    update: Update, context: ContextTypes.DEFAULT_TYPE,
    chart_fn: Callable[..., bytes], caption: str, *args: Any,
) -> None:
    """Generate and send a chart, catching matplotlib errors gracefully."""
    message = _get_message(update)
    if not message:
        return
    try:
        await _send_typing(update, context)
        chart_bytes = chart_fn(*args)
        await message.reply_photo(photo=io.BytesIO(chart_bytes), caption=caption)
    except Exception as e:
        logger.error("Chart generation failed: %s", e, exc_info=True)
        await message.reply_text("⚠️ Не удалось сгенерировать график.")


# ── Bot commands ────────────────────────────────────────────────────────────

@authorized
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/start — welcome message with main menu."""
    message = _get_message(update)
    if not message:
        return

    text = (
        "👋 *Привет! Я твой Дневник-Аналитик*\n\n"
        "Анализирую твой Notion-дневник с помощью AI.\n\n"
        "Выбери команду из меню ниже или введи вручную:\n"
        "/help — список всех команд"
    )
    await message.reply_text(text, parse_mode="Markdown", reply_markup=_main_menu_keyboard())


@authorized
async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/help — full command list with descriptions."""
    message = _get_message(update)
    if not message:
        return

    text = (
        "📋 *Все команды:*\n\n"
        "/analyze `[месяц]` — анализ месяца с графиками\n"
        "/predict — риск выгорания на 5 дней\n"
        "/best\\_days `[месяц]` — топ-3 продуктивных дня\n"
        "/optimal\\_hours — лучшее время для работы\n"
        "/kate\\_impact — корреляция с отношениями\n"
        "/testik\\_patterns — анализ TESTIK влияния\n"
        "/sleep\\_optimizer — оптимизация сна\n"
        "/money\\_forecast — прогноз заработка\n"
        "/weak\\_spots — слабые места\n"
        "/tomorrow\\_mood — прогноз настроения\n"
        "/sync — синхронизировать данные из Notion\n\n"
        "💡 _Данные кэшируются на 5 минут. "
        "Месяц можно указать как: 2025-01, january, январь, 1_"
    )
    await message.reply_text(text, parse_mode="Markdown", reply_markup=_main_menu_keyboard())


@authorized
async def cmd_analyze(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/analyze [month] — full monthly analysis with charts."""
    if not update.message:
        return

    arg = sanitize_command_arg(update.message.text or "")
    if not arg:
        await update.message.reply_text(
            "📊 *Выбери месяц для анализа:*",
            parse_mode="Markdown",
            reply_markup=_month_picker_keyboard("analyze"),
        )
        return

    await _run_analyze(update, context, arg)


async def _run_analyze(update: Update, context: ContextTypes.DEFAULT_TYPE, arg: str) -> None:
    """Shared logic for /analyze command and callback."""
    message = _get_message(update)
    if not message:
        return

    await _send_typing(update, context)

    try:
        year, month = parse_month_arg(arg)
    except ValueError as e:
        await message.reply_text(f"❌ {e}\nПример: /analyze 2025-01 или /analyze january")
        return

    month_label = f"{year}-{month:02d}"
    await _send_typing(update, context)
    entries = await notion_service.get_entries_for_month(year, month)
    analysis = await ai_analyzer.analyze_month(entries, month_label)

    text = (
        f"📊 *Анализ за {month_label}*\n\n"
        f"📝 Записей: {analysis.total_entries}\n"
        f"😊 Ср. настроение: {analysis.avg_mood_score}/5\n"
        f"⏰ Ср. работа: {analysis.avg_hours_worked}ч/день\n"
        f"😴 Ср. сон: {analysis.avg_sleep_hours}ч\n"
        f"💰 Заработок: ${format_number(analysis.total_earnings)}\n"
        f"✅ Задач: {analysis.total_tasks}\n"
        f"🏋️ Тренировки: {format_percentage(analysis.workout_rate)}\n"
        f"🎓 Универ: {format_percentage(analysis.university_rate)}\n"
    )

    if analysis.best_day:
        b = analysis.best_day
        text += f"\n🏆 Лучший день: {b.entry_date} (score: {b.productivity_score})\n"
    if analysis.worst_day:
        w = analysis.worst_day
        text += f"📉 Худший день: {w.entry_date} (score: {w.productivity_score})\n"

    text += f"\n🤖 *AI Insights:*\n{analysis.ai_insights}"
    await message.reply_text(truncate_text(text), parse_mode="Markdown")

    if entries:
        await _safe_send_chart(
            update, context,
            charts_service.monthly_overview, f"📈 Графики за {month_label}",
            entries, month_label,
        )


@authorized
async def cmd_predict(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/predict — burnout risk for next 5 days."""
    message = _get_message(update)
    if not message:
        return

    await _send_typing(update, context)
    await message.reply_text("🔮 Оцениваю риск выгорания...")

    entries = await notion_service.get_recent(days=30)
    await _send_typing(update, context)
    risk = await ai_analyzer.predict_burnout(entries)

    risk_emoji = {"low": "🟢", "medium": "🟡", "high": "🟠", "critical": "🔴"}.get(risk.risk_level, "⚪")

    text = (
        f"🔥 *Прогноз выгорания (5 дней)*\n\n"
        f"{risk_emoji} Уровень: *{risk.risk_level.upper()}* ({risk.risk_score}%)\n\n"
        f"📋 *Факторы:*\n"
    )
    for f in risk.factors:
        text += f"  • {f}\n"
    text += f"\n💡 *Рекомендации:*\n{risk.recommendation}"
    await message.reply_text(truncate_text(text), parse_mode="Markdown")

    if len(entries) >= 3:
        await _safe_send_chart(
            update, context,
            charts_service.burnout_chart, "📊 Индекс риска выгорания",
            entries,
        )


@authorized
async def cmd_best_days(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/best_days [month] — top 3 productive days."""
    if not update.message:
        return

    arg = sanitize_command_arg(update.message.text or "")
    if not arg:
        await update.message.reply_text(
            "🏆 *Выбери месяц:*",
            parse_mode="Markdown",
            reply_markup=_month_picker_keyboard("best_days"),
        )
        return

    await _run_best_days(update, context, arg)


async def _run_best_days(update: Update, context: ContextTypes.DEFAULT_TYPE, arg: str) -> None:
    """Shared logic for /best_days command and callback."""
    message = _get_message(update)
    if not message:
        return

    await _send_typing(update, context)

    try:
        year, month = parse_month_arg(arg)
    except ValueError as e:
        await message.reply_text(f"❌ {e}")
        return

    entries = await notion_service.get_entries_for_month(year, month)
    best = await ai_analyzer.best_days(entries)

    if not best:
        await message.reply_text("📭 Нет данных за этот период.")
        return

    text = f"🏆 *Топ-3 продуктивных дня ({year}-{month:02d})*\n\n"
    medals = ["🥇", "🥈", "🥉"]
    for i, day in enumerate(best):
        mood_str = day.mood.emoji if day.mood else "❓"
        text += (
            f"{medals[i]} *{day.entry_date}*\n"
            f"   Score: {day.productivity_score} | {mood_str} | "
            f"{day.hours_worked}ч работы | {day.tasks_completed} задач\n\n"
        )

    await message.reply_text(text, parse_mode="Markdown")


@authorized
async def cmd_optimal_hours(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/optimal_hours — best working hours analysis."""
    message = _get_message(update)
    if not message:
        return

    await _send_typing(update, context)
    await message.reply_text("⏰ Анализирую оптимальное время работы...")

    entries = await notion_service.get_recent(days=60)
    await _send_typing(update, context)
    result = await ai_analyzer.optimal_hours(entries)

    await message.reply_text(
        truncate_text(f"⏰ *Оптимальные часы работы*\n\n{result}"), parse_mode="Markdown"
    )


@authorized
async def cmd_kate_impact(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/kate_impact — relationship correlation analysis."""
    message = _get_message(update)
    if not message:
        return

    await _send_typing(update, context)
    await message.reply_text("💕 Анализирую корреляции...")

    entries = await notion_service.get_recent(days=90)
    await _send_typing(update, context)
    result = await ai_analyzer.kate_impact(entries)

    await message.reply_text(
        truncate_text(f"💕 *Влияние отношений*\n\n{result}"), parse_mode="Markdown"
    )


@authorized
async def cmd_testik_patterns(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/testik_patterns — TESTIK influence analysis."""
    message = _get_message(update)
    if not message:
        return

    await _send_typing(update, context)
    await message.reply_text("🧪 Анализирую паттерны TESTIK...")

    entries = await notion_service.get_recent(days=90)
    await _send_typing(update, context)
    result = await ai_analyzer.testik_patterns(entries)

    await message.reply_text(
        truncate_text(f"🧪 *Паттерны TESTIK*\n\n{result}"), parse_mode="Markdown"
    )

    if entries:
        await _safe_send_chart(
            update, context,
            charts_service.testik_chart, "📊 TESTIK vs Метрики",
            entries,
        )


@authorized
async def cmd_sleep_optimizer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/sleep_optimizer — sleep optimization advice."""
    message = _get_message(update)
    if not message:
        return

    await _send_typing(update, context)
    await message.reply_text("😴 Анализирую паттерны сна...")

    entries = await notion_service.get_recent(days=60)
    await _send_typing(update, context)
    result = await ai_analyzer.sleep_optimizer(entries)

    await message.reply_text(
        truncate_text(f"😴 *Оптимизация сна*\n\n{result}"), parse_mode="Markdown"
    )

    if entries:
        await _safe_send_chart(
            update, context,
            charts_service.sleep_chart, "📊 Сон vs Продуктивность",
            entries,
        )


@authorized
async def cmd_money_forecast(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/money_forecast — earnings forecast."""
    message = _get_message(update)
    if not message:
        return

    await _send_typing(update, context)
    await message.reply_text("💰 Строю прогноз заработка...")

    entries = await notion_service.get_recent(days=90)
    await _send_typing(update, context)
    result = await ai_analyzer.money_forecast(entries)

    await message.reply_text(
        truncate_text(f"💰 *Прогноз заработка*\n\n{result}"), parse_mode="Markdown"
    )

    if entries:
        await _safe_send_chart(
            update, context,
            charts_service.earnings_chart, "📊 Динамика заработка",
            entries,
        )


@authorized
async def cmd_weak_spots(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/weak_spots — identify weak productivity areas."""
    message = _get_message(update)
    if not message:
        return

    await _send_typing(update, context)
    await message.reply_text("🔍 Ищу слабые места...")

    entries = await notion_service.get_recent(days=30)
    await _send_typing(update, context)
    result = await ai_analyzer.weak_spots(entries)

    await message.reply_text(
        truncate_text(f"🔍 *Слабые места*\n\n{result}"), parse_mode="Markdown"
    )


@authorized
async def cmd_tomorrow_mood(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/tomorrow_mood — predict tomorrow's mood."""
    message = _get_message(update)
    if not message:
        return

    await _send_typing(update, context)
    await message.reply_text("🔮 Предсказываю завтрашнее настроение...")

    entries = await notion_service.get_recent(days=14)
    await _send_typing(update, context)
    result = await ai_analyzer.tomorrow_mood(entries)

    await message.reply_text(
        truncate_text(f"🔮 *Прогноз настроения*\n\n{result}"), parse_mode="Markdown"
    )


@authorized
async def cmd_sync(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/sync — manually sync Notion data (authorized users only)."""
    message = _get_message(update)
    if not message:
        return

    await _send_typing(update, context)
    await message.reply_text("🔄 Синхронизирую данные из Notion...")

    count = await notion_service.sync_all()
    await message.reply_text(
        f"✅ Синхронизировано записей: *{count}*\n"
        f"🕐 {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        parse_mode="Markdown",
    )


async def cmd_unknown(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle unknown commands with a helpful message."""
    if not update.message:
        return
    await update.message.reply_text(
        "❓ Неизвестная команда. Нажми /help для списка команд.",
        reply_markup=_main_menu_keyboard(),
    )


# ── Callback query handler (inline keyboard) ────────────────────────────────

@authorized
async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle inline keyboard button presses (with auth check)."""
    query = update.callback_query
    if not query or not query.data:
        return

    await query.answer()
    data = query.data

    # Direct command routes (no extra args needed)
    command_map: dict[str, Callable[..., Coroutine[Any, Any, None]]] = {
        "menu_predict": cmd_predict,
        "menu_optimal_hours": cmd_optimal_hours,
        "menu_kate_impact": cmd_kate_impact,
        "menu_testik_patterns": cmd_testik_patterns,
        "menu_sleep_optimizer": cmd_sleep_optimizer,
        "menu_money_forecast": cmd_money_forecast,
        "menu_weak_spots": cmd_weak_spots,
        "menu_tomorrow_mood": cmd_tomorrow_mood,
        "menu_sync": cmd_sync,
    }

    if data in command_map:
        await command_map[data](update, context)
        return

    if data == "menu_analyze":
        await query.message.reply_text(
            "📊 *Выбери месяц для анализа:*",
            parse_mode="Markdown",
            reply_markup=_month_picker_keyboard("analyze"),
        )
        return

    if data == "menu_best_days":
        await query.message.reply_text(
            "🏆 *Выбери месяц:*",
            parse_mode="Markdown",
            reply_markup=_month_picker_keyboard("best_days"),
        )
        return

    if data == "menu_back":
        await query.message.reply_text(
            "📋 *Главное меню:*",
            parse_mode="Markdown",
            reply_markup=_main_menu_keyboard(),
        )
        return

    # Month picker callbacks: analyze_2025-01, best_days_2025-01
    if data.startswith("analyze_"):
        month_arg = data.removeprefix("analyze_")
        await _run_analyze(update, context, month_arg)
        return

    if data.startswith("best_days_"):
        month_arg = data.removeprefix("best_days_")
        await _run_best_days(update, context, month_arg)
        return


# ── Build & run application ─────────────────────────────────────────────────

def _build_app() -> Application:
    """Build the Telegram Application with all handlers registered."""
    settings = get_settings()
    app = Application.builder().token(settings.telegram.bot_token).build()

    # Command handlers
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("analyze", cmd_analyze))
    app.add_handler(CommandHandler("predict", cmd_predict))
    app.add_handler(CommandHandler("best_days", cmd_best_days))
    app.add_handler(CommandHandler("optimal_hours", cmd_optimal_hours))
    app.add_handler(CommandHandler("kate_impact", cmd_kate_impact))
    app.add_handler(CommandHandler("testik_patterns", cmd_testik_patterns))
    app.add_handler(CommandHandler("sleep_optimizer", cmd_sleep_optimizer))
    app.add_handler(CommandHandler("money_forecast", cmd_money_forecast))
    app.add_handler(CommandHandler("weak_spots", cmd_weak_spots))
    app.add_handler(CommandHandler("tomorrow_mood", cmd_tomorrow_mood))
    app.add_handler(CommandHandler("sync", cmd_sync))

    # Callback query handler for inline keyboards
    app.add_handler(CallbackQueryHandler(handle_callback))

    # Unknown command handler (must be last)
    app.add_handler(MessageHandler(filters.COMMAND, cmd_unknown))

    return app


def main() -> None:
    """Entry point: build bot and start polling."""
    logger.info("Starting Daily Analyst bot (polling mode)")

    app = _build_app()

    app.run_polling(
        drop_pending_updates=True,
        allowed_updates=Update.ALL_TYPES,
        close_loop=False,
    )

    logger.info("Bot stopped")


if __name__ == "__main__":
    main()
