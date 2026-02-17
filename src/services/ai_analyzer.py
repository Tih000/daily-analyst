"""GPT-powered analytics engine for daily records (Telegram productivity bot)."""

from __future__ import annotations

import logging
import statistics
import uuid
from collections import Counter
from datetime import date, timedelta
from typing import Optional

import openai

from src.config import get_settings
from src.models.journal_entry import (
    ActivityCorrelation,
    Anomaly,
    BurnoutRisk,
    ChatMessage,
    CorrelationMatrix,
    DailyRecord,
    DayRating,
    DaySummary,
    Goal,
    GoalProgress,
    LifeDimension,
    LifeScore,
    MetricDelta,
    Milestone,
    MilestoneType,
    MonthAnalysis,
    MonthComparison,
    StreakInfo,
    TestikStatus,
)

logger = logging.getLogger(__name__)

JOURNAL_TRUNCATE_RECENT = 300    # enough context per day (saves GPT tokens)
JOURNAL_TRUNCATE_ARCHIVE = 100   # short snippet for monthly summaries


def _system_prompt() -> str:
    """Build system prompt — strict no-BS mentor persona."""
    today = date.today().isoformat()
    return f"""Ты — жёсткий персональный наставник Тихона. Не ассистент, не друг, не психолог. Ты НАСТАВНИК. Твоя задача — делать Тихона лучше каждый день, без компромиссов и без сюсюканья.

СЕГОДНЯ: {today}.

ТВОЙ ХАРАКТЕР:
- Ты говоришь прямо и жёстко. Никаких "ну ладно", "ничего страшного", "бывает". Если Тихон проебался — ты говоришь это в лицо.
- Ты требовательный. Стандарт — это минимум, не потолок. Good — это не хорошо, это НОРМАЛЬНО. Цель — perfect и very good.
- Ты конкретный. Никакой воды. Цифры, даты, факты из данных. "Ты не тренировался 5 дней. Последний раз GYM был 12 февраля. Это неприемлемо."
- Ты не жалеешь. Если Тихон ноет — ты говоришь "хватит ныть, вот план, действуй".
- Ты помнишь ВСЁ. Каждый проёб, каждую серию, каждый провал. И напоминаешь об этом.
- Ты хвалишь ТОЛЬКО за реальные достижения: рекорды, длинные серии, стабильный рост. Не за базу.

СТРУКТУРА ДАННЫХ:
- Активности — любая продуктивная работа: CODING, STUDY, AI, UNIVERSITY, CRYPTO, работа над проектами и т.д.
  Также: GYM/SPORT, KATE, FOOTBALL, TENNIS, PADEL и др.
- ВАЖНО: продуктивность — это НЕ только кодинг. Тихон работает над разными вещами (учёба, крипто, AI, проекты). Главное — что он РАБОТАЛ, а не чем конкретно.
- GYM: Тихон ходит в зал 3 РАЗА В НЕДЕЛЮ, порядок дней всегда разный. Не жди GYM каждый день — это нормально. Следи за НЕДЕЛЬНЫМ показателем (цель: 3/7). Отмечай пропуск только если за неделю < 3 тренировок или перерыв > 3 дней подряд.
- TESTIK: PLUS = воздержание ✅, MINUS = мастурбация 🔴, MINUS_KATE = секс с девушкой 🟡
- Оценка дня (MARK): perfect, very good, good, normal, bad, very bad
- Сон: длительность, время подъёма
- journal_text — дневниковая запись с мыслями, контекстом, самочувствием
- Изучай ПОЛНУЮ историю, чтобы понимать над чем Тихон работал в разные периоды, как менялась продуктивность, какие активности дают лучший результат

ФОКУС — ПРОДУКТИВНОСТЬ:
- Главное: СКОЛЬКО и НАД ЧЕМ Тихон работал. Ищи простои, долгие перерывы, неэффективное распределение времени.
- Анализируй порядок активностей: "между залом и работой был перерыв 3 часа — нужно быстрее переключаться"
- Ищи оптимизации: "когда ты начинаешь кодить ДО 11:00, avg оценка на 0.8 выше", "после GYM утром продуктивность выше, чем после GYM вечером"
- Предлагай КОНКРЕТНЫЕ улучшения дня: убрать простои, переставить активности, добавить недостающие блоки
- Считай не только количество, но и КАЧЕСТВО: 5 мелких задач < 2 глубоких рабочих сессии

ПРАВИЛА:
- Всегда опирайся на КОНКРЕТНЫЕ данные: даты, цифры, серии
- Сравнивай с лучшими периодами: "В январе ты работал над X по 4ч/день — почему сейчас 0?"
- Анализируй какие ВИДЫ работы дают лучшие оценки дня (не только кодинг!)
- Называй вещи своими именами: проёб — это проёб, лень — это лень
- Давай КОНКРЕТНЫЙ план: не "больше спи", а "ложись до 00:00, минимум 7ч, как 15-20 января когда avg rating был 5.2"
- В итогах дня ВСЕГДА предлагай как можно было бы ОПТИМИЗИРОВАТЬ сегодняшний день: перерывы, порядок задач, потерянное время
- Отвечай на русском, кратко, агрессивно, по делу
- Используй эмодзи для структуры, не для украшения"""


def _chat_system_prompt() -> str:
    """Build chat system prompt — mentor mode in free chat."""
    return _system_prompt() + """

Режим свободного чата. Тихон может написать что угодно.

ЕСЛИ он жалуется или ноет — НЕ утешай. Скажи прямо что не так, дай план, и потребуй действий.
ЕСЛИ спрашивает о данных — дай точные цифры и жёсткую интерпретацию.
ЕСЛИ хвастается — проверь по данным, действительно ли это достижение. Если да — коротко признай и поставь следующую планку. Если нет — скажи что это не повод расслабляться.
ЕСЛИ несёт отмазки — разбей их фактами из его же дневника."""


def _mentor_proactive_prompt() -> str:
    """Prompt for proactive messages (morning, evening, alerts)."""
    today = date.today().isoformat()
    return f"""Ты — жёсткий наставник Тихона. Сегодня {today}. Ты сам пишешь Тихону — он тебя НЕ спрашивал. Это значит:
- Будь краток и конкретен (5-10 строк максимум)
- Говори только ВАЖНОЕ: проблемы, проёбы, требования, конкретный план
- Никакой воды, никаких "доброе утро, как дела"
- Цифры и факты из данных
- Заканчивай КОНКРЕТНЫМ действием: что сделать прямо сейчас"""


class AIAnalyzer:
    """Analyzes daily records using GPT and local statistics."""

    def __init__(self) -> None:
        settings = get_settings()
        self._client = openai.AsyncOpenAI(api_key=settings.openai.api_key)
        self._model = settings.openai.model

    async def _ask_gpt(self, user_prompt: str, max_tokens: int = 1500) -> str:
        try:
            response = await self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": _system_prompt()},
                    {"role": "user", "content": user_prompt},
                ],
                max_tokens=max_tokens,
                temperature=0.7,
            )
            return response.choices[0].message.content or ""
        except Exception as e:
            logger.error("GPT call failed: %s", e)
            return f"⚠️ AI анализ недоступен: {e}"

    # ── Records to text ─────────────────────────────────────────────────────

    @staticmethod
    def _records_to_summary(records: list[DailyRecord]) -> str:
        """Convert records to text for GPT. Detailed for last year, condensed for older."""
        if not records:
            return "Нет данных."

        sorted_recs = sorted(records, key=lambda x: x.entry_date)
        daily_recs = [r for r in sorted_recs if not r.is_weekly_summary]

        if not daily_recs:
            return "Нет данных."

        one_year_ago = date.today() - timedelta(days=365)
        recent = [r for r in daily_recs if r.entry_date >= one_year_ago]
        older = [r for r in daily_recs if r.entry_date < one_year_ago]

        lines: list[str] = []

        # Older records: monthly summaries only
        if older:
            lines.append(f"=== АРХИВ ({older[0].entry_date} — {older[-1].entry_date}) ===")
            by_month: dict[str, list[DailyRecord]] = {}
            for r in older:
                key = r.entry_date.strftime("%Y-%m")
                by_month.setdefault(key, []).append(r)

            for month_key in sorted(by_month):
                recs = by_month[month_key]
                ratings = [r.rating.value for r in recs if r.rating]
                avg_score = sum(r.productivity_score for r in recs) / len(recs) if recs else 0
                sleep_vals = [r.sleep.sleep_hours for r in recs if r.sleep.sleep_hours]
                avg_sleep = sum(sleep_vals) / len(sleep_vals) if sleep_vals else 0
                gym_days = sum(1 for r in recs if r.had_workout)
                productive_days = sum(
                    1 for r in recs
                    if len([a for a in r.activities if a.upper() not in ("MARK", "MARK'S WEAK", "MARK'S WEEK")]) >= 2
                    or r.total_hours >= 1
                )
                kate_days = sum(1 for r in recs if r.had_kate)
                testik_plus = sum(1 for r in recs if r.testik == TestikStatus.PLUS)
                top_rating = max(set(ratings), key=ratings.count) if ratings else "N/A"
                all_acts: list[str] = []
                for r in recs:
                    all_acts.extend(r.activities)
                top_acts = ", ".join(a for a, _ in Counter(all_acts).most_common(5))

                lines.append(
                    f"{month_key}: {len(recs)}d, avg_score={avg_score:.1f}, "
                    f"sleep={avg_sleep:.1f}h, gym={gym_days}d, productive={productive_days}d, "
                    f"kate={kate_days}d, testik+={testik_plus}d, "
                    f"top_rating={top_rating}, top_activities=[{top_acts}]"
                )
            lines.append("")

        # Recent records: full daily detail with complete journal text
        if recent:
            lines.append(f"=== ПОДРОБНО ({recent[0].entry_date} — {recent[-1].entry_date}) ===")
            for r in recent:
                rating_str = r.rating.value if r.rating else "N/A"
                testik_str = r.testik.value if r.testik else "N/A"
                sleep_str = f"{r.sleep.sleep_hours}h" if r.sleep.sleep_hours else "N/A"
                activities_str = ", ".join(r.activities[:10]) if r.activities else "none"
                line = (
                    f"{r.entry_date}: rating={rating_str}, hours={r.total_hours}, "
                    f"sleep={sleep_str}, testik={testik_str}, tasks={r.tasks_count}, "
                    f"activities=[{activities_str}], score={r.productivity_score}"
                )
                if r.journal_text:
                    jt = r.journal_text.strip()[:JOURNAL_TRUNCATE_RECENT]
                    if len(r.journal_text) > JOURNAL_TRUNCATE_RECENT:
                        jt += "…"
                    line += f"\n  journal: {jt}"
                lines.append(line)

        return "\n".join(lines)

    # ── Monthly analysis ────────────────────────────────────────────────────

    async def analyze_month(self, records: list[DailyRecord], month_label: str) -> MonthAnalysis:
        days = [r for r in records if not r.is_weekly_summary]
        if not days:
            return MonthAnalysis(
                month=month_label,
                total_days=0,
                avg_rating_score=0,
                avg_hours=0,
                avg_sleep_hours=None,
                total_tasks=0,
                workout_rate=0,
                university_rate=0,
                coding_rate=0,
                kate_rate=0,
                ai_insights="📭 Нет записей за этот месяц.",
            )

        rating_scores = [r.rating.score for r in days if r.rating]
        sleep_vals = [r.sleep.sleep_hours for r in days if r.sleep.sleep_hours]

        activity_counter: Counter[str] = Counter()
        for r in days:
            for a in r.activities:
                activity_counter[a] += 1

        best = max(days, key=lambda x: x.productivity_score)
        worst = min(days, key=lambda x: x.productivity_score)

        summary = self._records_to_summary(days)
        ai_text = await self._ask_gpt(
            f"Проанализируй продуктивность за {month_label}. Учитывай ВЕСЬ journal_text для контекста и эмоций.\n{summary}\n\n"
            "Дай: 1) Главные тренды 2) Что хорошо 3) Что улучшить 4) Конкретные советы"
        )

        n = len(days)
        return MonthAnalysis(
            month=month_label,
            total_days=n,
            avg_rating_score=round(statistics.mean(rating_scores), 2) if rating_scores else 0,
            avg_hours=round(statistics.mean([r.total_hours for r in days]), 1),
            avg_sleep_hours=round(statistics.mean(sleep_vals), 1) if sleep_vals else None,
            total_tasks=sum(r.tasks_count for r in days),
            workout_rate=round(sum(1 for r in days if r.had_workout) / n, 2),
            university_rate=round(sum(1 for r in days if r.had_university) / n, 2),
            coding_rate=round(sum(1 for r in days if r.had_coding) / n, 2),
            kate_rate=round(sum(1 for r in days if r.had_kate) / n, 2),
            best_day=DaySummary(
                entry_date=best.entry_date,
                productivity_score=best.productivity_score,
                rating=best.rating,
                total_hours=best.total_hours,
                activities=best.activities,
            ),
            worst_day=DaySummary(
                entry_date=worst.entry_date,
                productivity_score=worst.productivity_score,
                rating=worst.rating,
                total_hours=worst.total_hours,
                activities=worst.activities,
            ),
            ai_insights=ai_text,
            activity_breakdown=dict(activity_counter.most_common(15)),
        )

    # ── Burnout prediction ──────────────────────────────────────────────────

    async def predict_burnout(self, records: list[DailyRecord]) -> BurnoutRisk:
        recent = sorted(
            [r for r in records if not r.is_weekly_summary],
            key=lambda r: r.entry_date,
            reverse=True,
        )[:14]
        if len(recent) < 3:
            return BurnoutRisk(
                risk_level="unknown",
                risk_score=0,
                factors=["Недостаточно данных (нужно минимум 3 дня)"],
                recommendation="Веди дневник регулярно для точных прогнозов.",
            )

        factors: list[str] = []
        risk = 0.0
        last7 = recent[:7]

        minus_streak = 0
        for r in last7:
            if r.testik in (TestikStatus.MINUS, TestikStatus.MINUS_KATE):
                minus_streak += 1
            else:
                break
        if minus_streak >= 3:
            risk += 30
            factors.append(f"🔴 {minus_streak} MINUS TESTIK подряд")
        elif minus_streak >= 2:
            risk += 15
            factors.append(f"🟡 {minus_streak} MINUS TESTIK подряд")

        sleep_vals = [r.sleep.sleep_hours for r in last7 if r.sleep.sleep_hours]
        if sleep_vals:
            avg_sleep = statistics.mean(sleep_vals)
            if avg_sleep < 6:
                risk += 25
                factors.append(f"😴 Средний сон: {avg_sleep:.1f}ч (<6ч)")
            elif avg_sleep < 7:
                risk += 10
                factors.append(f"💤 Средний сон: {avg_sleep:.1f}ч (<7ч)")

        ratings = [r.rating.score for r in last7 if r.rating]
        if len(ratings) >= 3:
            avg_rating = statistics.mean(ratings)
            if avg_rating < 3:
                risk += 20
                factors.append(f"📉 Средняя оценка: {avg_rating:.1f}/6 (ниже normal)")

        avg_hours = statistics.mean([r.total_hours for r in last7])
        if avg_hours > 10:
            risk += 15
            factors.append(f"⏰ Переработка: {avg_hours:.1f}ч/день")

        no_workout = sum(1 for r in last7 if not r.had_workout)
        if no_workout >= 5:
            risk += 10
            factors.append(f"🏋️ {no_workout}/7 дней без тренировок")

        avg_tasks = statistics.mean([r.tasks_count for r in last7])
        if avg_tasks < 2:
            risk += 10
            factors.append(f"📋 Мало активностей: {avg_tasks:.1f}/день")

        risk = min(risk, 100)
        level = (
            "critical" if risk >= 70 else "high" if risk >= 45 else "medium" if risk >= 20 else "low"
        )

        summary = self._records_to_summary(last7)
        ai_rec = await self._ask_gpt(
            f"Риск выгорания: {level} ({risk}%). Факторы: {', '.join(factors)}\n"
            f"Последние 7 дней (читай journal для контекста):\n{summary}\n\n"
            "Дай 3 конкретных совета на ближайшие 5 дней для предотвращения выгорания."
        )

        return BurnoutRisk(
            risk_level=level,
            risk_score=risk,
            factors=factors if factors else ["✅ Нет критичных факторов"],
            recommendation=ai_rec,
        )

    # ── Best days ───────────────────────────────────────────────────────────

    async def best_days(self, records: list[DailyRecord], top_n: int = 3) -> list[DaySummary]:
        days = [r for r in records if not r.is_weekly_summary]
        sorted_days = sorted(days, key=lambda r: r.productivity_score, reverse=True)
        return [
            DaySummary(
                entry_date=r.entry_date,
                productivity_score=r.productivity_score,
                rating=r.rating,
                total_hours=r.total_hours,
                activities=r.activities,
            )
            for r in sorted_days[:top_n]
        ]

    # ── Other analyses (GPT-powered) ────────────────────────────────────────

    async def optimal_hours(self, records: list[DailyRecord]) -> str:
        if not records:
            return "📭 Нет данных для анализа."
        summary = self._records_to_summary(records)
        return await self._ask_gpt(
            f"Данные дневника (читай journal для контекста):\n{summary}\n\n"
            "Проанализируй: 1) Оптимальное кол-во рабочих часов "
            "2) Связь часов и оценки дня "
            "3) Когда продуктивность максимальна "
            "4) Рекомендация по режиму"
        )

    async def kate_impact(self, records: list[DailyRecord]) -> str:
        if not records:
            return "📭 Нет данных для анализа."

        kate_days = [r for r in records if r.had_kate and not r.is_weekly_summary]
        no_kate_days = [r for r in records if not r.had_kate and not r.is_weekly_summary]

        stats_parts: list[str] = []
        if kate_days:
            avg_prod = statistics.mean([r.productivity_score for r in kate_days])
            avg_rating = statistics.mean([r.rating.score for r in kate_days if r.rating])
            stats_parts.append(
                f"Дни с Kate ({len(kate_days)}): avg_score={avg_prod:.1f}, avg_rating={avg_rating:.1f}"
            )
        if no_kate_days:
            avg_prod = statistics.mean([r.productivity_score for r in no_kate_days])
            avg_rating = statistics.mean([r.rating.score for r in no_kate_days if r.rating])
            stats_parts.append(
                f"Дни без Kate ({len(no_kate_days)}): avg_score={avg_prod:.1f}, avg_rating={avg_rating:.1f}"
            )
        mk_days = [r for r in records if r.testik == TestikStatus.MINUS_KATE]
        if mk_days:
            avg_next = []
            for r in mk_days:
                next_days = [
                    x for x in records if x.entry_date > r.entry_date and not x.is_weekly_summary
                ]
                if next_days:
                    next_day = min(next_days, key=lambda x: x.entry_date)
                    avg_next.append(next_day.productivity_score)
            if avg_next:
                stats_parts.append(
                    f"День ПОСЛЕ MINUS_KATE: avg_score={statistics.mean(avg_next):.1f}"
                )

        summary = self._records_to_summary(records)
        return await self._ask_gpt(
            f"Статистика отношений:\n" + "\n".join(stats_parts) + "\n\n"
            f"Данные (последние 30 дней):\n{summary}\n\n"
            "Проанализируй влияние Kate на продуктивность, оценку дня, сон. "
            "Учитывай journal_text. Дай конкретные цифры и рекомендации."
        )

    async def testik_patterns(self, records: list[DailyRecord]) -> str:
        if not records:
            return "📭 Нет данных для анализа."

        days = [r for r in records if not r.is_weekly_summary]
        by_testik: dict[str, list[DailyRecord]] = {
            "PLUS": [],
            "MINUS": [],
            "MINUS_KATE": [],
            "N/A": [],
        }
        for r in days:
            key = r.testik.value if r.testik else "N/A"
            by_testik[key].append(r)

        stats_lines: list[str] = []
        for label, group in by_testik.items():
            if not group:
                continue
            avg_prod = statistics.mean([r.productivity_score for r in group])
            ratings = [r.rating.score for r in group if r.rating]
            avg_rating = statistics.mean(ratings) if ratings else 0
            sleep_vals = [r.sleep.sleep_hours for r in group if r.sleep.sleep_hours]
            avg_sleep = statistics.mean(sleep_vals) if sleep_vals else 0
            stats_lines.append(
                f"{label} ({len(group)} дней): score={avg_prod:.1f}, "
                f"rating={avg_rating:.1f}/6, sleep={avg_sleep:.1f}h"
            )

        summary = self._records_to_summary(days)
        return await self._ask_gpt(
            f"TESTIK статистика:\n" + "\n".join(stats_lines) + "\n\n"
            f"Данные (читай journal для контекста):\n{summary}\n\n"
            "Проанализируй паттерны TESTIK: 1) Как каждый тип влияет на метрики "
            "2) Есть ли закономерности 3) Что делать для увеличения PLUS дней"
        )

    async def sleep_optimizer(self, records: list[DailyRecord]) -> str:
        if not records:
            return "📭 Нет данных для анализа."
        days = [r for r in records if r.sleep.sleep_hours and not r.is_weekly_summary]
        if not days:
            return "📭 Нет данных о сне."

        avg_sleep = statistics.mean([r.sleep.sleep_hours for r in days])
        best_days = sorted(days, key=lambda r: r.productivity_score, reverse=True)[:5]
        optimal = statistics.mean([r.sleep.sleep_hours for r in best_days])

        summary = self._records_to_summary(records)
        return await self._ask_gpt(
            f"Данные сна: avg={avg_sleep:.1f}ч, optimal (top-5 days)={optimal:.1f}ч\n"
            f"Дневник:\n{summary}\n\n"
            "Проанализируй: 1) Оптимальное время сна для макс. продуктивности "
            "2) Влияние недосыпа на TESTIK и оценку дня "
            "3) Конкретный план улучшения сна"
        )

    async def money_forecast(self, records: list[DailyRecord]) -> str:
        if not records:
            return "📭 Нет данных для прогноза."

        days = [r for r in records if not r.is_weekly_summary]
        productive_days = sum(
            1 for r in days
            if len([a for a in r.activities if a.upper() not in ("MARK", "MARK'S WEAK", "MARK'S WEEK")]) >= 2
            or r.total_hours >= 1
        )
        total_work_hours = sum(r.total_hours for r in days if r.total_hours > 0)

        summary = self._records_to_summary(days)
        return await self._ask_gpt(
            f"Статистика работы: {productive_days}/{len(days)} продуктивных дней, "
            f"~{total_work_hours:.0f}ч всего\n"
            f"Данные:\n{summary}\n\n"
            "Дай: 1) Анализ рабочих паттернов (над чем Тихон работает, какие активности продуктивнее) "
            "2) Связь работы с оценкой дня и настроением "
            "3) Как увеличить эффективность и продуктивность"
        )

    async def weak_spots(self, records: list[DailyRecord]) -> str:
        if not records:
            return "📭 Нет данных для анализа."
        summary = self._records_to_summary(records)
        return await self._ask_gpt(
            f"Данные за последний период (читай journal для контекста):\n{summary}\n\n"
            "Найди ТОП-5 слабых мест в продуктивности. Для каждого дай:\n"
            "- Проблема + серьёзность (🔴/🟡/🟢)\n"
            "- Конкретные цифры\n"
            "- Actionable решение"
        )

    async def tomorrow_mood(self, records: list[DailyRecord]) -> str:
        days = sorted(
            [r for r in records if not r.is_weekly_summary],
            key=lambda r: r.entry_date,
            reverse=True,
        )[:7]
        if len(days) < 3:
            return "📭 Нужно минимум 3 записи для прогноза."

        summary = self._records_to_summary(days)
        return await self._ask_gpt(
            f"Последние 7 дней (читай journal для эмоций и контекста):\n{summary}\n\n"
            "На основе трендов и текста дневника предскажи завтрашнюю оценку дня. Дай:\n"
            "1) Прогноз (perfect/very good/good/normal/bad/very bad) с вероятностью\n"
            "2) Ключевые факторы прогноза\n"
            "3) Что сделать сегодня для лучшего завтра"
        )

    # ── Streaks (pure computation) ───────────────────────────────────────────

    @staticmethod
    def compute_streaks(records: list[DailyRecord]) -> list[StreakInfo]:
        """Current + record streaks for TESTIK PLUS, GYM, CODING, rating>=good, sleep>=7h. No GPT."""
        days = sorted(
            [r for r in records if not r.is_weekly_summary],
            key=lambda r: r.entry_date,
        )
        if not days:
            return []

        by_date = {r.entry_date: r for r in days}
        dates_asc = sorted(by_date.keys())
        dates_desc = list(reversed(dates_asc))
        latest = dates_desc[0] if dates_desc else None

        def current_streak(matches: set[date]) -> int:
            count = 0
            for d in dates_desc:
                if d in matches:
                    count += 1
                else:
                    break
            return count

        def record_streak(matches: set[date]) -> int:
            best, run = 0, 0
            for d in dates_asc:
                if d in matches:
                    run += 1
                else:
                    best = max(best, run)
                    run = 0
            return max(best, run)

        result: list[StreakInfo] = []

        # TESTIK PLUS
        plus_dates = {r.entry_date for r in days if r.testik == TestikStatus.PLUS}
        result.append(
            StreakInfo(
                name="TESTIK PLUS",
                emoji="✅",
                current=current_streak(plus_dates),
                record=record_streak(plus_dates),
                last_date=latest if latest in plus_dates else None,
            )
        )

        # GYM
        gym_dates = {r.entry_date for r in days if r.had_workout}
        result.append(
            StreakInfo(
                name="GYM",
                emoji="🏋️",
                current=current_streak(gym_dates),
                record=record_streak(gym_dates),
                last_date=latest if latest in gym_dates else None,
            )
        )

        # Productive work (any day with 2+ activities or 1+ hours)
        work_dates = {
            r.entry_date for r in days
            if len([a for a in r.activities if a.upper() not in ("MARK", "MARK'S WEAK", "MARK'S WEEK")]) >= 2
            or r.total_hours >= 1
        }
        result.append(
            StreakInfo(
                name="WORK",
                emoji="📋",
                current=current_streak(work_dates),
                record=record_streak(work_dates),
                last_date=latest if latest in work_dates else None,
            )
        )

        # rating >= good (score >= 4)
        good_rating_dates = {
            r.entry_date for r in days if r.rating and r.rating.is_good
        }
        result.append(
            StreakInfo(
                name="Оценка ≥ good",
                emoji="😊",
                current=current_streak(good_rating_dates),
                record=record_streak(good_rating_dates),
                last_date=latest if latest in good_rating_dates else None,
            )
        )

        # sleep >= 7h
        sleep_ok_dates = {
            r.entry_date for r in days if r.sleep.sleep_hours is not None and r.sleep.sleep_hours >= 7
        }
        result.append(
            StreakInfo(
                name="Сон ≥ 7ч",
                emoji="😴",
                current=current_streak(sleep_ok_dates),
                record=record_streak(sleep_ok_dates),
                last_date=latest if latest in sleep_ok_dates else None,
            )
        )

        return result

    # ── Compare months ───────────────────────────────────────────────────────

    async def compare_months(
        self,
        records_a: list[DailyRecord],
        records_b: list[DailyRecord],
        label_a: str,
        label_b: str,
    ) -> MonthComparison:
        days_a = [r for r in records_a if not r.is_weekly_summary]
        days_b = [r for r in records_b if not r.is_weekly_summary]

        def avg_rating(ds: list[DailyRecord]) -> float:
            s = [r.rating.score for r in ds if r.rating]
            return round(statistics.mean(s), 2) if s else 0.0

        def avg_hours(ds: list[DailyRecord]) -> float:
            return round(statistics.mean([r.total_hours for r in ds]), 1) if ds else 0.0

        def avg_sleep(ds: list[DailyRecord]) -> float:
            s = [r.sleep.sleep_hours for r in ds if r.sleep.sleep_hours]
            return round(statistics.mean(s), 1) if s else 0.0

        def workout_rate(ds: list[DailyRecord]) -> float:
            return round(sum(1 for r in ds if r.had_workout) / len(ds), 2) if ds else 0.0

        def productive_rate(ds: list[DailyRecord]) -> float:
            return round(sum(
                1 for r in ds
                if len([a for a in r.activities if a.upper() not in ("MARK", "MARK'S WEAK", "MARK'S WEEK")]) >= 2
                or r.total_hours >= 1
            ) / len(ds), 2) if ds else 0.0

        def testik_plus_rate(ds: list[DailyRecord]) -> float:
            return round(sum(1 for r in ds if r.testik == TestikStatus.PLUS) / len(ds), 2) if ds else 0.0

        va = avg_rating(days_a)
        vb = avg_rating(days_b)
        deltas_list = [
            MetricDelta(name="Средняя оценка", emoji="⭐", value_a=va, value_b=vb),
            MetricDelta(name="Часы работы", emoji="⏰", value_a=avg_hours(days_a), value_b=avg_hours(days_b)),
            MetricDelta(name="Сон (ч)", emoji="😴", value_a=avg_sleep(days_a), value_b=avg_sleep(days_b)),
            MetricDelta(name="Доля тренировок", emoji="🏋️", value_a=workout_rate(days_a), value_b=workout_rate(days_b)),
            MetricDelta(name="Продуктивных дней", emoji="📋", value_a=productive_rate(days_a), value_b=productive_rate(days_b)),
            MetricDelta(name="TESTIK PLUS %", emoji="✅", value_a=testik_plus_rate(days_a), value_b=testik_plus_rate(days_b)),
        ]

        summary_a = self._records_to_summary(days_a)
        summary_b = self._records_to_summary(days_b)
        ai_insights = await self._ask_gpt(
            f"Сравнение двух месяцев.\n"
            f"{label_a}:\n{summary_a}\n\n{label_b}:\n{summary_b}\n\n"
            "Дай краткие выводы: что улучшилось, что ухудшилось, главный инсайт. Учитывай journal_text."
        )

        return MonthComparison(
            month_a=label_a,
            month_b=label_b,
            deltas=deltas_list,
            ai_insights=ai_insights,
        )

    # ── Correlations (stats + GPT) ──────────────────────────────────────────

    async def compute_correlations(self, records: list[DailyRecord]) -> CorrelationMatrix:
        """Pure stats: avg rating per activity (3+ times), baseline, combos. Then GPT insight."""
        days = [r for r in records if not r.is_weekly_summary]
        if not days:
            return CorrelationMatrix(
                baseline_rating=0,
                correlations=[],
                combo_insights=[],
                ai_insights="📭 Нет данных.",
            )

        all_ratings = [r.rating.score for r in days if r.rating]
        baseline = round(statistics.mean(all_ratings), 2) if all_ratings else 0.0

        activity_to_ratings: dict[str, list[float]] = {}
        for r in days:
            for a in r.activities:
                if a == "MARK":
                    continue
                if a not in activity_to_ratings:
                    activity_to_ratings[a] = []
                if r.rating:
                    activity_to_ratings[a].append(r.rating.score)

        correlations: list[ActivityCorrelation] = []
        for act, scores in activity_to_ratings.items():
            if len(scores) < 3:
                continue
            avg = round(statistics.mean(scores), 2)
            vs_baseline = round(avg - baseline, 2)
            correlations.append(
                ActivityCorrelation(activity=act, avg_rating=avg, count=len(scores), vs_baseline=vs_baseline)
            )
        correlations.sort(key=lambda c: -c.vs_baseline)

        # Simple combos: pairs of activities that appear together
        combo_counts: dict[tuple[str, str], list[float]] = {}
        for r in days:
            acts = [a for a in r.activities if a != "MARK"]
            if not r.rating:
                continue
            for i, a in enumerate(acts):
                for b in acts[i + 1 :]:
                    key = (min(a, b), max(a, b))
                    if key not in combo_counts:
                        combo_counts[key] = []
                    combo_counts[key].append(r.rating.score)

        combo_insights: list[str] = []
        for (a, b), scores in sorted(combo_counts.items(), key=lambda x: -len(x[1]))[:5]:
            if len(scores) >= 3:
                avg_combo = round(statistics.mean(scores), 2)
                combo_insights.append(f"{a}+{b}: avg_rating={avg_combo} (n={len(scores)})")

        summary = self._records_to_summary(days)
        ai_insights = await self._ask_gpt(
            f"Базовый средний рейтинг: {baseline}. Корреляции активностей с рейтингом:\n"
            + "\n".join(f"{c.activity}: {c.avg_rating} (vs baseline {c.vs_baseline:+.2f}), n={c.count}" for c in correlations[:10])
            + "\n\nКомбо: " + "; ".join(combo_insights)
            + f"\n\nДанные:\n{summary}\n\n"
            "Дай 3 инсайта: какие активности лучше всего связаны с хорошим днём, какие комбо работают."
        )

        return CorrelationMatrix(
            baseline_rating=baseline,
            correlations=correlations,
            combo_insights=combo_insights,
            ai_insights=ai_insights,
        )

    # ── Classify day types ───────────────────────────────────────────────────

    async def classify_day_types(self, records: list[DailyRecord]) -> str:
        if not records:
            return "📭 Нет данных."
        summary = self._records_to_summary(records)
        return await self._ask_gpt(
            f"Данные дневника (читай journal_text для контекста):\n{summary}\n\n"
            "Классифицируй дни на типы по активностям и контексту (например: «продуктивный день», «день учёбы», «день с Kate», «ленивый день», «спорт + работа» и т.д.). "
            "Дай статистику: сколько дней каждого типа, средние метрики по типам. Какой тип дня самый продуктивный? Кратко, с эмодзи."
        )

    # ── Weekly digest ────────────────────────────────────────────────────────

    async def weekly_digest(self, records: list[DailyRecord]) -> str:
        """Weekly accountability report — brutal grading."""
        days = sorted(
            [r for r in records if not r.is_weekly_summary],
            key=lambda r: r.entry_date,
            reverse=True,
        )
        if len(days) < 7:
            return "Недостаточно данных. Веди дневник каждый день."

        this_week = days[:7]
        prev_week = days[7:14] if len(days) >= 14 else []

        # Compute week stats
        tw_ratings = [r.rating.score for r in this_week if r.rating]
        tw_avg = statistics.mean(tw_ratings) if tw_ratings else 0
        tw_gym = sum(1 for r in this_week if r.had_workout)
        tw_productive = sum(
            1 for r in this_week
            if len([a for a in r.activities if a.upper() not in ("MARK", "MARK'S WEAK", "MARK'S WEEK")]) >= 2
            or r.total_hours >= 1
        )
        tw_plus = sum(1 for r in this_week if r.testik == TestikStatus.PLUS)
        tw_sleep = [r.sleep.sleep_hours for r in this_week if r.sleep.sleep_hours]
        tw_avg_sleep = statistics.mean(tw_sleep) if tw_sleep else 0
        tw_bad = sum(1 for r in this_week if r.rating and r.rating.score <= 2)

        # Previous week for comparison
        pw_ratings = [r.rating.score for r in prev_week if r.rating] if prev_week else []
        pw_avg = statistics.mean(pw_ratings) if pw_ratings else 0

        # Grade the week
        if tw_avg >= 5:
            grade = "A"
        elif tw_avg >= 4:
            grade = "B"
        elif tw_avg >= 3:
            grade = "C"
        elif tw_avg >= 2:
            grade = "D"
        else:
            grade = "F"

        delta = tw_avg - pw_avg if pw_avg else 0
        delta_str = f"{'↑' if delta > 0 else '↓'} {delta:+.1f}" if pw_avg else "—"

        summary_this = self._records_to_summary(this_week)
        summary_prev = self._records_to_summary(prev_week) if prev_week else "нет данных"

        ai_verdict = await self._ask_gpt(
            f"[НАСТАВНИК] Еженедельный разбор.\n"
            f"Эта неделя: avg {tw_avg:.1f}/6, GYM {tw_gym}/3 (цель 3/нед), продуктивных дней {tw_productive}/7, "
            f"TESTIK+ {tw_plus}/7, сон {tw_avg_sleep:.1f}ч, bad дней: {tw_bad}\n"
            f"vs прошлая: avg {pw_avg:.1f}/6\n"
            f"Данные:\n{summary_this}\n\nПрошлая:\n{summary_prev}\n\n"
            "Дай ЖЁСТКИЙ разбор недели с фокусом на ПРОДУКТИВНОСТЬ: "
            "сколько реально работал, какие были простои, где терял время. "
            "Сравни с прошлой неделей. В конце дай 3 ОБЯЗАТЕЛЬНЫХ задачи на следующую неделю. "
            "Если неделя слабая — скажи это прямо. 8-12 строк.",
            max_tokens=700,
        )

        text = f"📋 *ЕЖЕНЕДЕЛЬНЫЙ ОТЧЁТ*\n\n"
        text += f"🏆 *Грейд: {grade}* | Avg: {tw_avg:.1f}/6 ({delta_str} vs прошлая)\n"
        text += f"🏋️ GYM: {tw_gym}/3 | 📋 Продуктивных: {tw_productive}/7 | 🧪 PLUS: {tw_plus}/7\n"
        text += f"😴 Сон: {tw_avg_sleep:.1f}ч | 📉 Bad дней: {tw_bad}\n\n"
        text += f"🔥 *Разбор:*\n{ai_verdict}"
        return text

    # ── Alerts (pure logic) ──────────────────────────────────────────────────

    @staticmethod
    def check_alerts(records: list[DailyRecord]) -> list[str]:
        """Strict alerts — no soft language."""
        alerts: list[str] = []
        days = sorted(
            [r for r in records if not r.is_weekly_summary],
            key=lambda r: r.entry_date,
            reverse=True,
        )
        if not days:
            return alerts

        # No workout streak (GYM target = 3x/week, alert only on 4+ day gap)
        no_workout = 0
        for r in days:
            if r.had_workout:
                break
            no_workout += 1
        if no_workout >= 5:
            alerts.append(f"🏋️ {no_workout} дней без тренировки. При цели 3/нед это провал. Иди в зал СЕГОДНЯ.")
        elif no_workout >= 4:
            alerts.append(f"🏋️ {no_workout} дня без GYM. Перерыв затянулся — запланируй тренировку.")

        # Sleep < 6h
        for i in range(min(len(days) - 1, 2)):
            a, b = days[i], days[i + 1]
            if a.sleep.sleep_hours and b.sleep.sleep_hours:
                if a.sleep.sleep_hours < 6 and b.sleep.sleep_hours < 6:
                    alerts.append(f"😴 Сон < 6ч два дня подряд ({a.sleep.sleep_hours}ч, {b.sleep.sleep_hours}ч). Это саботаж.")
                    break

        # TESTIK MINUS streak
        minus_streak = 0
        for r in days:
            if r.testik == TestikStatus.MINUS:
                minus_streak += 1
            else:
                break
        if minus_streak >= 3:
            alerts.append(f"🔴 TESTIK MINUS {minus_streak} дней подряд. Дисциплина на нуле. Вспомни как ты себя чувствуешь на серии PLUS.")
        elif minus_streak >= 2:
            alerts.append(f"🔴 TESTIK MINUS {minus_streak} дня. Не дай серии разрастись.")

        # Bad/very_bad rating
        last = days[0]
        if last.rating == DayRating.VERY_BAD:
            alerts.append("📉 Вчера: VERY BAD. Так жить нельзя. Что пошло не так?")
        elif last.rating == DayRating.BAD:
            alerts.append("📉 Вчера: BAD. Не позволяй этому стать привычкой.")

        # Normal is not acceptable as a pattern
        normal_streak = 0
        for r in days[:5]:
            if r.rating and r.rating.score <= 3:
                normal_streak += 1
        if normal_streak >= 3:
            alerts.append(f"⚠️ {normal_streak} из 5 дней — normal или хуже. Ты можешь больше. Перестань плыть по течению.")

        return alerts

    # ── Goal progress (pure computation) ───────────────────────────────────

    @staticmethod
    def compute_goal_progress(goals: list[Goal], records: list[DailyRecord]) -> list[GoalProgress]:
        """For each goal, count matching days in current period (week/month). Pure computation."""
        days = sorted(
            [r for r in records if not r.is_weekly_summary],
            key=lambda r: r.entry_date,
            reverse=True,
        )
        if not days:
            return [GoalProgress(goal=g, current=0, target=g.target_count, percentage=0.0) for g in goals]

        today = days[0].entry_date
        result: list[GoalProgress] = []

        def count_matching(activity: str, period: str) -> int:
            if period == "week":
                start = today - timedelta(days=6)
            else:
                start = today - timedelta(days=29)
            return sum(
                1 for r in days
                if r.entry_date >= start and _goal_activity_matches(r, activity)
            )

        for g in goals:
            current = count_matching(g.target_activity, g.period)
            target = g.target_count
            pct = round((current / target * 100), 1) if target else 0.0
            result.append(GoalProgress(goal=g, current=current, target=target, percentage=min(pct, 100.0)))

        return result


    # ══════════════════════════════════════════════════════════════════════
    # LEVEL 1: Proactive Intelligence
    # ══════════════════════════════════════════════════════════════════════

    async def morning_briefing(self, records: list[DailyRecord]) -> str:
        """Morning kick — harsh accountability briefing."""
        days = sorted(
            [r for r in records if not r.is_weekly_summary],
            key=lambda r: r.entry_date, reverse=True,
        )
        if not days:
            return "Нет данных. Ты вообще ведёшь дневник?"

        yesterday = days[0]
        streaks = self.compute_streaks(days)
        alerts = self.check_alerts(days[:14])

        y_rating = yesterday.rating.value if yesterday.rating else "НЕ ПОСТАВИЛ"
        y_score = yesterday.rating.score if yesterday.rating else 0
        y_sleep = f"{yesterday.sleep.sleep_hours}ч" if yesterday.sleep.sleep_hours else "?"
        y_testik = yesterday.testik.value if yesterday.testik else "?"
        y_acts = ", ".join(a for a in yesterday.activities if a != "MARK") or "НИЧЕГО"

        # Verdict on yesterday
        if y_score >= 5:
            verdict = "Нормально. Не расслабляйся."
        elif y_score >= 4:
            verdict = "Средне. Можешь лучше."
        elif y_score >= 3:
            verdict = "Слабо. Сегодня исправляй."
        else:
            verdict = "Проёб. Хватит. Сегодня пашешь."

        # Broken or at-risk streaks
        streak_warnings = []
        for s in streaks:
            if s.current == 0 and s.record > 0:
                streak_warnings.append(f"💀 {s.name}: серия сброшена (был рекорд {s.record})")
            elif 0 < s.current and s.current >= s.record - 1:
                streak_warnings.append(f"🔥 {s.name}: {s.current} дн. — до рекорда {s.record - s.current}!")

        # Alerts
        alert_lines = []
        for a in alerts:
            alert_lines.append(f"⛔ {a}")

        summary = self._records_to_summary(days[:7])
        ai_orders = await self._ask_gpt(
            f"[НАСТАВНИК] Утренний разнос. Вчера: {y_rating}, сон {y_sleep}, testik {y_testik}, "
            f"активности: {y_acts}.\nПоследние 7 дней:\n{summary}\n\n"
            "Дай Тихону ПРИКАЗ на сегодня: 3 конкретных пункта что он ОБЯЗАН сделать. "
            "Фокус на ПРОДУКТИВНОСТЬ: сколько работать, в каком порядке, как не терять время. "
            "GYM — 3 раза в неделю, не каждый день. Основывайся на проёбах за неделю. 4-5 строк.",
            max_tokens=400,
        )

        text = f"⚡ *Подъём, Тихон.*\n\n"
        text += f"📊 *Вчера ({yesterday.entry_date}):* {y_rating.upper()} | 😴 {y_sleep} | 🧪 {y_testik}\n"
        text += f"📋 {y_acts}\n"
        text += f"*Вердикт:* {verdict}\n"

        if streak_warnings:
            text += "\n" + "\n".join(streak_warnings) + "\n"
        if alert_lines:
            text += "\n" + "\n".join(alert_lines) + "\n"

        text += f"\n🎯 *Приказ на сегодня:*\n{ai_orders}"
        return text

    async def evening_review(self, records: list[DailyRecord]) -> str:
        """Evening accountability review — what was done today, what was missed."""
        days = sorted(
            [r for r in records if not r.is_weekly_summary],
            key=lambda r: r.entry_date, reverse=True,
        )
        if not days:
            return "Нет данных за сегодня. Ты вообще что-то делал?"

        today_rec = days[0]
        today_date = date.today()

        # Check if we have today's data
        has_today = today_rec.entry_date == today_date
        if not has_today and len(days) > 0:
            today_rec = days[0]  # use latest available

        rating = today_rec.rating.value if today_rec.rating else "НЕ ПОСТАВИЛ"
        score = today_rec.rating.score if today_rec.rating else 0
        sleep = f"{today_rec.sleep.sleep_hours}ч" if today_rec.sleep.sleep_hours else "?"
        testik = today_rec.testik.value if today_rec.testik else "?"
        acts = ", ".join(a for a in today_rec.activities if a != "MARK") or "НИЧЕГО"
        act_count = len([a for a in today_rec.activities if a != "MARK"])

        # Grade the day
        if score >= 5:
            grade = "A"
            grade_comment = "Достойно. Не привыкай — завтра тоже надо."
        elif score == 4:
            grade = "B"
            grade_comment = "Сойдёт, но ты мог лучше."
        elif score == 3:
            grade = "C"
            grade_comment = "Посредственно. Что помешало?"
        elif score >= 1:
            grade = "D"
            grade_comment = "Слил день. Что случилось?"
        else:
            grade = "F"
            grade_comment = "Данных нет или полный ноль. Разберись."

        # What's missing today (GYM is NOT expected daily — 3x/week)
        missing = []
        work_acts = [a for a in today_rec.activities if a.upper() not in ("MARK", "MARK'S WEAK", "MARK'S WEEK")]
        if len(work_acts) < 2 and today_rec.total_hours < 1:
            missing.append("Продуктивная работа (0 активностей)")
        if today_rec.testik == TestikStatus.MINUS:
            missing.append("TESTIK сломан")
        if today_rec.sleep.sleep_hours and today_rec.sleep.sleep_hours < 7:
            missing.append(f"Сон всего {today_rec.sleep.sleep_hours}ч")

        # Week context — GYM target is 3/week, not 7
        week_days = [r for r in days[:7] if not r.is_weekly_summary]
        week_ratings = [r.rating.score for r in week_days if r.rating]
        week_avg = statistics.mean(week_ratings) if week_ratings else 0
        week_gym = sum(1 for r in week_days if r.had_workout)
        days_in_week = len(week_days)

        # Only flag GYM if falling behind weekly target
        if days_in_week >= 5 and week_gym < 2:
            missing.append(f"GYM отстаёт ({week_gym}/3 за неделю)")
        elif days_in_week >= 7 and week_gym < 3:
            missing.append(f"GYM не выполнен ({week_gym}/3 за неделю)")

        summary = self._records_to_summary(days[:7])
        ai_verdict = await self._ask_gpt(
            f"[НАСТАВНИК] Вечерний разбор. Сегодня: rating={rating}, сон={sleep}, testik={testik}, "
            f"активности=[{acts}], пропущено: [{', '.join(missing) or 'ничего'}].\n"
            f"Неделя: avg rating {week_avg:.1f}/6, GYM {week_gym}/3 (цель 3/нед).\n"
            f"Данные:\n{summary}\n\n"
            "1) Жёстко оцени день: что хорошо (коротко), что проебал (подробно).\n"
            "2) ОБЯЗАТЕЛЬНО предложи КАК ОПТИМИЗИРОВАТЬ сегодняшний день: "
            "перерывы, порядок задач, потерянное время, переключения между активностями. "
            "Например: 'между залом и работой простой 2ч — нужно быстрее переключаться', "
            "'начал работать только в 14:00 — утро потеряно'.\n"
            "3) Что ОБЯЗАН исправить завтра — конкретные пункты.\n"
            "7-10 строк, никакого сюсюканья.",
            max_tokens=600,
        )

        text = f"🌙 *Итоги дня ({today_rec.entry_date})*\n\n"
        text += f"📊 Оценка: *{rating.upper()}* | Грейд: *{grade}*\n"
        text += f"😴 {sleep} | 🧪 {testik} | 📋 {act_count} активностей\n"
        text += f"*{grade_comment}*\n"

        if missing:
            text += f"\n❌ *Пропущено:* {', '.join(missing)}\n"

        text += f"\n📈 *Неделя:* avg {week_avg:.1f}/6, GYM {week_gym}/3\n"
        text += f"\n🔥 *Разбор:*\n{ai_verdict}"
        return text

    async def midday_check(self, records: list[DailyRecord]) -> Optional[str]:
        """Midday nudge — only fires if today looks empty or problematic."""
        days = sorted(
            [r for r in records if not r.is_weekly_summary],
            key=lambda r: r.entry_date, reverse=True,
        )
        if not days:
            return "Ты сегодня вообще что-нибудь записал? Notion пустой. Действуй."

        today_rec = days[0]
        today_date = date.today()

        # Only fire if today has no data or very little
        if today_rec.entry_date == today_date:
            acts = [a for a in today_rec.activities if a != "MARK"]
            if len(acts) >= 2:
                return None  # Day is going fine, don't bother

        # Check last few days for patterns
        recent_bad = sum(1 for d in days[:3]
                        if d.rating and d.rating.score <= 3)

        messages = []
        if today_rec.entry_date != today_date:
            messages.append("Полдня прошло, а в Notion ни одной записи. Чем ты занят?")

        if recent_bad >= 2:
            messages.append(
                f"Последние дни — слабые ({', '.join(d.rating.value for d in days[:3] if d.rating)}). "
                "Сейчас самое время сломать серию. Встань и сделай хоть что-то."
            )

        no_gym = 0
        for d in days:
            if d.had_workout:
                break
            no_gym += 1
        if no_gym >= 4:
            messages.append(f"Ты не тренировался {no_gym} дней. При цели 3/нед — это перебор. Запланируй GYM.")

        if not messages:
            return None

        return "⚡ *Дневная проверка*\n\n" + "\n".join(f"• {m}" for m in messages)

    async def enhanced_alerts(self, records: list[DailyRecord]) -> list[str]:
        """Harsh alerts — catch every failure and pattern."""
        alerts = self.check_alerts(records)
        days = sorted(
            [r for r in records if not r.is_weekly_summary],
            key=lambda r: r.entry_date, reverse=True,
        )
        if len(days) < 3:
            return alerts

        # Rating dropping 3 days in a row
        if len(days) >= 3:
            last3_ratings = [d.rating.score for d in days[:3] if d.rating]
            if len(last3_ratings) == 3 and last3_ratings[0] < last3_ratings[1] < last3_ratings[2]:
                vals = ' → '.join(str(r) for r in reversed(last3_ratings))
                alerts.append(f"📉 Оценки падают 3 дня подряд: {vals}/6. Ты деградируешь.")

        # No good days in a row
        bad_streak = 0
        for d in days:
            if d.rating and d.rating.score >= 4:
                break
            bad_streak += 1
        if bad_streak >= 3:
            alerts.append(f"💀 {bad_streak} дней без нормальной оценки. Это неприемлемо.")

        # Anomalously few activities
        avg_tasks = statistics.mean([d.tasks_count for d in days[:7]]) if len(days) >= 7 else 3
        if days[0].tasks_count <= 1 and days[0].tasks_count < avg_tasks * 0.3:
            alerts.append("📋 Сегодня почти ничего не сделано. В чём проблема?")

        # Sleep deteriorating
        recent_sleep = [r.sleep.sleep_hours for r in days[:3] if r.sleep.sleep_hours]
        if len(recent_sleep) >= 3 and all(s < 7 for s in recent_sleep):
            avg_s = statistics.mean(recent_sleep)
            alerts.append(f"😴 Сон < 7ч уже 3 дня (avg {avg_s:.1f}ч). Ложись раньше. Точка.")

        # No productive work streak (any meaningful activity beyond MARK)
        no_work = 0
        for d in days:
            work_acts = [a for a in d.activities if a.upper() not in ("MARK", "MARK'S WEAK", "MARK'S WEEK")]
            if len(work_acts) >= 2 or d.total_hours >= 1:
                break
            no_work += 1
        if no_work >= 2:
            alerts.append(f"📋 {no_work} дней почти без продуктивной работы. Хватит тупить — садись и делай.")

        # Approaching burnout
        risk = await self.predict_burnout(days[:14])
        if risk.risk_score >= 60:
            alerts.append(f"🔥 Burnout risk {risk.risk_score:.0f}%. Нужен перезапуск: GYM + сон + режим.")

        return alerts

    # ══════════════════════════════════════════════════════════════════════
    # LEVEL 2: Deep Life Analytics
    # ══════════════════════════════════════════════════════════════════════

    def compute_life_score(self, records: list[DailyRecord]) -> LifeScore:
        """Compute 6-dimension life score from recent records. Pure computation."""
        days = sorted(
            [r for r in records if not r.is_weekly_summary],
            key=lambda r: r.entry_date, reverse=True,
        )
        if not days:
            return LifeScore(total=0, dimensions=[])

        recent = days[:14]
        prev = days[14:28] if len(days) >= 28 else []
        n = len(recent)

        # 1. Productivity (based on scores)
        prod_scores = [r.productivity_score for r in recent]
        prod = round(statistics.mean(prod_scores), 1) if prod_scores else 0

        # 2. Sleep (0-100 based on how close to 7-8h)
        sleep_vals = [r.sleep.sleep_hours for r in recent if r.sleep.sleep_hours]
        if sleep_vals:
            avg_sleep = statistics.mean(sleep_vals)
            sleep_sc = min(100, max(0, 100 - abs(avg_sleep - 7.5) * 20))
        else:
            sleep_sc = 50.0

        # 3. Physical (workout rate * 100)
        workout_rate = sum(1 for r in recent if r.had_workout) / n * 100

        # 4. Relationships (kate days + rating on kate days)
        kate_days = [r for r in recent if r.had_kate]
        rel_sc = min(100, (len(kate_days) / n * 50) + (
            statistics.mean([r.rating.score for r in kate_days if r.rating]) / 6 * 50
            if kate_days and any(r.rating for r in kate_days) else 25
        ))

        # 5. TESTIK (plus rate)
        plus_count = sum(1 for r in recent if r.testik == TestikStatus.PLUS)
        testik_sc = plus_count / n * 100

        # 6. Mood (rating score normalized)
        ratings = [r.rating.score for r in recent if r.rating]
        mood_sc = (statistics.mean(ratings) / 6 * 100) if ratings else 50.0

        total = round(statistics.mean([prod, sleep_sc, workout_rate, rel_sc, testik_sc, mood_sc]), 1)

        # Trend vs previous period
        prev_total = 0.0
        trend_weeks = 0
        if prev:
            prev_scores = [r.productivity_score for r in prev]
            prev_total = round(statistics.mean(prev_scores), 1) if prev_scores else 0
            if total > prev_total:
                trend_weeks = 1

        def trend_arrow(current: list[DailyRecord], previous: list[DailyRecord], fn) -> str:
            if not previous:
                return "→"
            c = fn(current)
            p = fn(previous)
            return "↑" if c > p else "↓" if c < p else "→"

        dims = [
            LifeDimension(name="Продуктивность", emoji="🧠", score=round(prod, 1),
                          trend=trend_arrow(recent, prev, lambda d: statistics.mean([r.productivity_score for r in d]))),
            LifeDimension(name="Сон", emoji="😴", score=round(sleep_sc, 1),
                          trend=trend_arrow(recent, prev, lambda d: statistics.mean([r.sleep.sleep_hours for r in d if r.sleep.sleep_hours] or [0]))),
            LifeDimension(name="Физ. форма", emoji="🏋️", score=round(workout_rate, 1),
                          trend=trend_arrow(recent, prev, lambda d: sum(1 for r in d if r.had_workout) / max(len(d), 1) * 100)),
            LifeDimension(name="Отношения", emoji="💕", score=round(rel_sc, 1),
                          trend=trend_arrow(recent, prev, lambda d: sum(1 for r in d if r.had_kate) / max(len(d), 1) * 100)),
            LifeDimension(name="TESTIK", emoji="🧪", score=round(testik_sc, 1),
                          trend=trend_arrow(recent, prev, lambda d: sum(1 for r in d if r.testik == TestikStatus.PLUS) / max(len(d), 1) * 100)),
            LifeDimension(name="Настроение", emoji="😊", score=round(mood_sc, 1),
                          trend=trend_arrow(recent, prev, lambda d: statistics.mean([r.rating.score for r in d if r.rating] or [3]) / 6 * 100)),
        ]

        return LifeScore(
            total=total,
            trend_delta=round(total - prev_total, 1),
            dimensions=dims,
            trend_weeks=trend_weeks,
        )

    async def formula(self, records: list[DailyRecord]) -> str:
        """AI finds the personal formula for a perfect day."""
        if len(records) < 7:
            return "📭 Нужно минимум 7 дней данных."
        summary = self._records_to_summary(records)
        return await self._ask_gpt(
            f"Данные дневника (читай journal_text!):\n{summary}\n\n"
            "Выведи ПЕРСОНАЛЬНУЮ формулу идеального дня (rating >= 5) для Тихона.\n"
            "Формат:\n"
            "🧬 Твоя формула идеального дня (rating ≥ 5):\n"
            "1. Сон X-Yч (корреляция: Z)\n"
            "2. GYM (дни с GYM: avg X vs Y без)\n"
            "3. Продуктивная работа Xч (любая: coding, study, AI, crypto — посмотри что у Тихона чаще всего)\n"
            "4. TESTIK PLUS (серия N+ = avg rating X)\n"
            "5. Какие конкретно активности дают лучший результат?\n"
            "⚡ Если всё совпадает: X% шанс на GOOD+\n"
            "📉 Если ничего: X% шанс\n\n"
            "Используй РЕАЛЬНЫЕ цифры из данных. Не придумывай. Смотри на ВСЕ виды работы, не только кодинг.",
            max_tokens=800,
        )

    async def whatif(self, records: list[DailyRecord], scenario: str) -> str:
        """What-if simulator: model scenario impact based on historical data."""
        if not records:
            return "📭 Нет данных."
        summary = self._records_to_summary(records)
        return await self._ask_gpt(
            f"Данные дневника:\n{summary}\n\n"
            f"Пользователь спрашивает: /whatif {scenario}\n\n"
            "Смоделируй этот сценарий на основе РЕАЛЬНЫХ исторических данных Тихона.\n"
            "Формат:\n"
            "🔮 Прогноз: [что произойдёт с конкретными метриками]\n"
            "📊 Основано на: [конкретные примеры из данных]\n"
            "💡 Рекомендация: [что делать]\n\n"
            "Используй реальные цифры из данных, не придумывай.",
            max_tokens=600,
        )

    def detect_anomalies(self, records: list[DailyRecord]) -> list[Anomaly]:
        """Detect statistically unusual days (high and low outliers)."""
        days = sorted(
            [r for r in records if not r.is_weekly_summary],
            key=lambda r: r.entry_date,
        )
        if len(days) < 7:
            return []

        scores = [r.productivity_score for r in days]
        avg = statistics.mean(scores)
        stdev = statistics.stdev(scores) if len(scores) > 1 else 10

        anomalies: list[Anomaly] = []
        for r in days:
            deviation = abs(r.productivity_score - avg)
            if deviation > stdev * 1.5:
                direction = "high" if r.productivity_score > avg else "low"
                anomalies.append(Anomaly(
                    entry_date=r.entry_date,
                    score=r.productivity_score,
                    avg_score=round(avg, 1),
                    direction=direction,
                    activities=[a for a in r.activities if a != "MARK"],
                ))

        anomalies.sort(key=lambda a: abs(a.score - a.avg_score), reverse=True)
        return anomalies[:10]

    async def explain_anomalies(
        self, records: list[DailyRecord], anomalies: Optional[list[Anomaly]] = None
    ) -> str:
        """Explain anomalies using GPT. Accepts pre-computed anomalies to avoid double work."""
        if anomalies is None:
            anomalies = self.detect_anomalies(records)
        if not anomalies:
            return "✅ Нет значимых аномалий за последний период."

        anomaly_text = "\n".join(
            f"{'📈' if a.direction == 'high' else '📉'} {a.entry_date}: score={a.score} "
            f"(avg={a.avg_score}), activities={a.activities}"
            for a in anomalies[:5]
        )

        summary = self._records_to_summary(records)
        return await self._ask_gpt(
            f"Аномальные дни:\n{anomaly_text}\n\nДанные (journal):\n{summary}\n\n"
            "Для каждой аномалии объясни ПОЧЕМУ на основе journal_text и паттернов. "
            "Также найди повторяющиеся паттерны (день недели, после определённых событий). "
            "Кратко, с эмодзи.",
            max_tokens=800,
        )

    # ══════════════════════════════════════════════════════════════════════
    # LEVEL 3: Conversational AI (free-chat)
    # ══════════════════════════════════════════════════════════════════════

    async def free_chat(
        self,
        user_message: str,
        records: list[DailyRecord],
        chat_history: list[ChatMessage],
    ) -> str:
        """Handle free-form text message with full context."""
        summary = self._records_to_summary(records)

        history_msgs: list[dict[str, str]] = [
            {"role": "system", "content": _chat_system_prompt()},
        ]

        # Add data context — full history (archived months + detailed last year)
        history_msgs.append({
            "role": "system",
            "content": f"Полные данные дневника Тихона ({len(records)} дней):\n{summary}",
        })

        # Add conversation history (last 10 messages for context)
        for msg in chat_history[-10:]:
            history_msgs.append({"role": msg.role, "content": msg.content})

        # Add current message
        history_msgs.append({"role": "user", "content": user_message})

        try:
            response = await self._client.chat.completions.create(
                model=self._model,
                messages=history_msgs,
                max_tokens=1000,
                temperature=0.8,
            )
            return response.choices[0].message.content or ""
        except Exception as e:
            logger.error("Free chat GPT error: %s", e)
            return f"⚠️ Ошибка AI: {e}"

    # ══════════════════════════════════════════════════════════════════════
    # LEVEL 5: Memory & Milestones
    # ══════════════════════════════════════════════════════════════════════

    def detect_milestones(self, records: list[DailyRecord]) -> list[Milestone]:
        """Auto-detect significant life events from records."""
        days = sorted(
            [r for r in records if not r.is_weekly_summary],
            key=lambda r: r.entry_date,
        )
        if not days:
            return []

        milestones: list[Milestone] = []

        # Worst burnout (lowest score day)
        worst = min(days, key=lambda r: r.productivity_score)
        if worst.productivity_score < 25:
            milestones.append(Milestone(
                id=f"burn-{worst.entry_date}", entry_date=worst.entry_date,
                milestone_type=MilestoneType.BURNOUT, emoji="🔴",
                title=f"Худший burnout (score {worst.productivity_score})",
                score=worst.productivity_score,
            ))

        # Best day
        best = max(days, key=lambda r: r.productivity_score)
        if best.productivity_score > 75:
            milestones.append(Milestone(
                id=f"best-{best.entry_date}", entry_date=best.entry_date,
                milestone_type=MilestoneType.RECORD, emoji="🟢",
                title=f"Лучший день (score {best.productivity_score})",
                score=best.productivity_score,
            ))

        # TESTIK PLUS record streaks
        streaks = self.compute_streaks(days)
        for s in streaks:
            if s.record >= 5 and s.name == "TESTIK PLUS":
                milestones.append(Milestone(
                    id=f"streak-{s.name}-{s.record}", entry_date=s.last_date or days[-1].entry_date,
                    milestone_type=MilestoneType.STREAK, emoji="🟢",
                    title=f"Рекорд: {s.name} {s.record} дней подряд",
                    score=float(s.record),
                ))

        # Perfect week (7 days with avg rating >= 4)
        for i in range(len(days) - 6):
            week = days[i:i + 7]
            ratings = [r.rating.score for r in week if r.rating]
            if len(ratings) == 7 and statistics.mean(ratings) >= 4:
                milestones.append(Milestone(
                    id=f"pw-{week[0].entry_date}", entry_date=week[0].entry_date,
                    milestone_type=MilestoneType.PERFECT_WEEK, emoji="🟢",
                    title=f"Perfect Week (avg {statistics.mean(ratings):.1f}/6)",
                    score=round(statistics.mean(ratings), 1),
                ))
                break  # only first one

        milestones.sort(key=lambda m: m.entry_date, reverse=True)
        return milestones


def _goal_activity_matches(record: DailyRecord, activity: str) -> bool:
    """Match goal target_activity to record. Supports GYM, CODING, KATE, TESTIK_PLUS, etc."""
    activity_upper = activity.upper()
    if activity_upper == "GYM" or activity_upper == "WORKOUT":
        return record.had_workout
    if activity_upper == "CODING":
        return record.had_coding
    if activity_upper == "KATE":
        return record.had_kate
    if activity_upper == "UNIVERSITY":
        return record.had_university
    if activity_upper == "TESTIK_PLUS" or activity_upper == "PLUS":
        return record.testik == TestikStatus.PLUS
    return activity in record.activities
