"""GPT-powered analytics engine for daily records."""

from __future__ import annotations

import logging
import statistics
from collections import Counter
from typing import Optional

import openai

from src.config import get_settings
from src.models.journal_entry import (
    BurnoutRisk,
    DailyRecord,
    DaySummary,
    DayRating,
    MonthAnalysis,
    TestikStatus,
)

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """Ты эксперт по продуктивности. Анализируй дневник разработчика.
Контекст: пользователь ведёт Notion-дневник, где каждый день содержит задачи
(CODING, GYM, AI, UNIVERSITY, CRYPTO, KATE и др.), оценку дня (MARK: perfect/good/normal/bad),
данные сна и статус TESTIK (PLUS = воздержание, MINUS = мастурбация, MINUS_KATE = секс с девушкой).

Твоя задача:
- Находить корреляции между сном, активностями, TESTIK и настроением
- Предсказывать выгорание (3+ MINUS TESTIK подряд, <6ч сна, падение оценок)
- Давать конкретные рекомендации с цифрами
- Отвечай кратко, с эмодзи, actionable insights
- На русском языке"""


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
                    {"role": "system", "content": SYSTEM_PROMPT},
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
        if not records:
            return "Нет данных."

        lines: list[str] = []
        for r in sorted(records, key=lambda x: x.entry_date):
            if r.is_weekly_summary:
                continue
            rating_str = r.rating.value if r.rating else "N/A"
            testik_str = r.testik.value if r.testik else "N/A"
            sleep_str = f"{r.sleep.sleep_hours}h" if r.sleep.sleep_hours else "N/A"
            activities_str = ", ".join(r.activities[:8]) if r.activities else "none"
            lines.append(
                f"{r.entry_date}: rating={rating_str}, hours={r.total_hours}, "
                f"sleep={sleep_str}, testik={testik_str}, tasks={r.tasks_count}, "
                f"activities=[{activities_str}], score={r.productivity_score}"
            )
        return "\n".join(lines)

    # ── Monthly analysis ────────────────────────────────────────────────────

    async def analyze_month(self, records: list[DailyRecord], month_label: str) -> MonthAnalysis:
        days = [r for r in records if not r.is_weekly_summary]
        if not days:
            return MonthAnalysis(
                month=month_label, total_days=0, avg_rating_score=0,
                avg_hours=0, avg_sleep_hours=None, total_tasks=0,
                workout_rate=0, university_rate=0, coding_rate=0, kate_rate=0,
                ai_insights="📭 Нет записей за этот месяц.",
            )

        rating_scores = [r.rating.score for r in days if r.rating]
        sleep_vals = [r.sleep.sleep_hours for r in days if r.sleep.sleep_hours]

        # Activity breakdown
        activity_counter: Counter[str] = Counter()
        for r in days:
            for a in r.activities:
                activity_counter[a] += 1

        best = max(days, key=lambda r: r.productivity_score)
        worst = min(days, key=lambda r: r.productivity_score)

        summary = self._records_to_summary(days)
        ai_text = await self._ask_gpt(
            f"Проанализируй продуктивность за {month_label}:\n{summary}\n\n"
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
                entry_date=best.entry_date, productivity_score=best.productivity_score,
                rating=best.rating, total_hours=best.total_hours, activities=best.activities,
            ),
            worst_day=DaySummary(
                entry_date=worst.entry_date, productivity_score=worst.productivity_score,
                rating=worst.rating, total_hours=worst.total_hours, activities=worst.activities,
            ),
            ai_insights=ai_text,
            activity_breakdown=dict(activity_counter.most_common(15)),
        )

    # ── Burnout prediction ──────────────────────────────────────────────────

    async def predict_burnout(self, records: list[DailyRecord]) -> BurnoutRisk:
        recent = sorted(
            [r for r in records if not r.is_weekly_summary],
            key=lambda r: r.entry_date, reverse=True,
        )[:14]
        if len(recent) < 3:
            return BurnoutRisk(
                risk_level="unknown", risk_score=0,
                factors=["Недостаточно данных (нужно минимум 3 дня)"],
                recommendation="Веди дневник регулярно для точных прогнозов.",
            )

        factors: list[str] = []
        risk = 0.0
        last7 = recent[:7]

        # Factor: consecutive MINUS TESTIK
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

        # Factor: low sleep
        sleep_vals = [r.sleep.sleep_hours for r in last7 if r.sleep.sleep_hours]
        if sleep_vals:
            avg_sleep = statistics.mean(sleep_vals)
            if avg_sleep < 6:
                risk += 25
                factors.append(f"😴 Средний сон: {avg_sleep:.1f}ч (<6ч)")
            elif avg_sleep < 7:
                risk += 10
                factors.append(f"💤 Средний сон: {avg_sleep:.1f}ч (<7ч)")

        # Factor: rating trend
        ratings = [r.rating.score for r in last7 if r.rating]
        if len(ratings) >= 3:
            avg_rating = statistics.mean(ratings)
            if avg_rating < 3:
                risk += 20
                factors.append(f"📉 Средняя оценка: {avg_rating:.1f}/6 (ниже normal)")

        # Factor: overwork
        avg_hours = statistics.mean([r.total_hours for r in last7])
        if avg_hours > 10:
            risk += 15
            factors.append(f"⏰ Переработка: {avg_hours:.1f}ч/день")

        # Factor: no workout streak
        no_workout = sum(1 for r in last7 if not r.had_workout)
        if no_workout >= 5:
            risk += 10
            factors.append(f"🏋️ {no_workout}/7 дней без тренировок")

        # Factor: low activity count
        avg_tasks = statistics.mean([r.tasks_count for r in last7])
        if avg_tasks < 2:
            risk += 10
            factors.append(f"📋 Мало активностей: {avg_tasks:.1f}/день")

        risk = min(risk, 100)
        level = (
            "critical" if risk >= 70 else
            "high" if risk >= 45 else
            "medium" if risk >= 20 else
            "low"
        )

        summary = self._records_to_summary(last7)
        ai_rec = await self._ask_gpt(
            f"Риск выгорания: {level} ({risk}%). Факторы: {', '.join(factors)}\n"
            f"Последние 7 дней:\n{summary}\n\n"
            "Дай 3 конкретных совета на ближайшие 5 дней для предотвращения выгорания."
        )

        return BurnoutRisk(
            risk_level=level, risk_score=risk,
            factors=factors if factors else ["✅ Нет критичных факторов"],
            recommendation=ai_rec,
        )

    # ── Best days ───────────────────────────────────────────────────────────

    async def best_days(self, records: list[DailyRecord], top_n: int = 3) -> list[DaySummary]:
        days = [r for r in records if not r.is_weekly_summary]
        sorted_days = sorted(days, key=lambda r: r.productivity_score, reverse=True)
        return [
            DaySummary(
                entry_date=r.entry_date, productivity_score=r.productivity_score,
                rating=r.rating, total_hours=r.total_hours, activities=r.activities,
            )
            for r in sorted_days[:top_n]
        ]

    # ── Other analyses (GPT-powered) ────────────────────────────────────────

    async def optimal_hours(self, records: list[DailyRecord]) -> str:
        if not records:
            return "📭 Нет данных для анализа."
        summary = self._records_to_summary(records)
        return await self._ask_gpt(
            f"Данные дневника:\n{summary}\n\n"
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
            stats_parts.append(f"Дни с Kate ({len(kate_days)}): avg_score={avg_prod:.1f}, avg_rating={avg_rating:.1f}")
        if no_kate_days:
            avg_prod = statistics.mean([r.productivity_score for r in no_kate_days])
            avg_rating = statistics.mean([r.rating.score for r in no_kate_days if r.rating])
            stats_parts.append(f"Дни без Kate ({len(no_kate_days)}): avg_score={avg_prod:.1f}, avg_rating={avg_rating:.1f}")

        # Also check TESTIK MINUS_KATE correlation
        mk_days = [r for r in records if r.testik == TestikStatus.MINUS_KATE]
        if mk_days:
            avg_next = []
            for r in mk_days:
                next_days = [x for x in records if x.entry_date > r.entry_date and not x.is_weekly_summary]
                if next_days:
                    next_day = min(next_days, key=lambda x: x.entry_date)
                    avg_next.append(next_day.productivity_score)
            if avg_next:
                stats_parts.append(f"День ПОСЛЕ MINUS_KATE: avg_score={statistics.mean(avg_next):.1f}")

        summary = self._records_to_summary(records[-30:])
        return await self._ask_gpt(
            f"Статистика отношений:\n" + "\n".join(stats_parts) + "\n\n"
            f"Данные (последние 30 дней):\n{summary}\n\n"
            "Проанализируй влияние Kate на продуктивность, оценку дня, сон. "
            "Дай конкретные цифры и рекомендации."
        )

    async def testik_patterns(self, records: list[DailyRecord]) -> str:
        if not records:
            return "📭 Нет данных для анализа."

        days = [r for r in records if not r.is_weekly_summary]
        by_testik: dict[str, list[DailyRecord]] = {"PLUS": [], "MINUS": [], "MINUS_KATE": [], "N/A": []}
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

        summary = self._records_to_summary(days[-30:])
        return await self._ask_gpt(
            f"TESTIK статистика:\n" + "\n".join(stats_lines) + "\n\n"
            f"Данные:\n{summary}\n\n"
            "Проанализируй паттерны TESTIK: 1) Как каждый тип влияет на метрики "
            "2) Есть ли закономерности 3) Что делать для увеличения PLUS дней"
        )

    async def sleep_optimizer(self, records: list[DailyRecord]) -> str:
        if not records:
            return "📭 Нет данных для анализа."
        days = [r for r in records if r.sleep.sleep_hours and not r.is_weekly_summary]
        if not days:
            return "📭 Нет данных о сне."

        avg_sleep = statistics.mean([r.sleep.sleep_hours for r in days])  # type: ignore
        best_days = sorted(days, key=lambda r: r.productivity_score, reverse=True)[:5]
        optimal = statistics.mean([r.sleep.sleep_hours for r in best_days])  # type: ignore

        summary = self._records_to_summary(records[-30:])
        return await self._ask_gpt(
            f"Данные сна: avg={avg_sleep:.1f}ч, optimal (top-5 days)={optimal:.1f}ч\n"
            f"Дневник:\n{summary}\n\n"
            "Проанализируй: 1) Оптимальное время сна для макс. продуктивности "
            "2) Влияние недосыпа на TESTIK и оценку дня "
            "3) Конкретный план улучшения сна"
        )

    async def money_forecast(self, records: list[DailyRecord]) -> str:
        """Analyze productivity/coding patterns for earnings potential."""
        if not records:
            return "📭 Нет данных для прогноза."

        days = [r for r in records if not r.is_weekly_summary]
        coding_days = sum(1 for r in days if r.had_coding)
        total_coding_hours = sum(r.total_hours for r in days if r.had_coding)

        summary = self._records_to_summary(days[-30:])
        return await self._ask_gpt(
            f"Статистика кодинга: {coding_days}/{len(days)} дней, "
            f"~{total_coding_hours:.0f}ч всего\n"
            f"Данные:\n{summary}\n\n"
            "Дай: 1) Анализ рабочих паттернов "
            "2) Связь кодинга с продуктивностью и настроением "
            "3) Как увеличить эффективность рабочего времени"
        )

    async def weak_spots(self, records: list[DailyRecord]) -> str:
        if not records:
            return "📭 Нет данных для анализа."
        summary = self._records_to_summary(records[-30:])
        return await self._ask_gpt(
            f"Данные за последний период:\n{summary}\n\n"
            "Найди ТОП-5 слабых мест в продуктивности. Для каждого дай:\n"
            "- Проблема + серьёзность (🔴/🟡/🟢)\n"
            "- Конкретные цифры\n"
            "- Actionable решение"
        )

    async def tomorrow_mood(self, records: list[DailyRecord]) -> str:
        days = sorted(
            [r for r in records if not r.is_weekly_summary],
            key=lambda r: r.entry_date, reverse=True,
        )[:7]
        if len(days) < 3:
            return "📭 Нужно минимум 3 записи для прогноза."

        summary = self._records_to_summary(days)
        return await self._ask_gpt(
            f"Последние 7 дней:\n{summary}\n\n"
            "На основе трендов предскажи завтрашнюю оценку дня. Дай:\n"
            "1) Прогноз (perfect/very good/good/normal/bad/very bad) с вероятностью\n"
            "2) Ключевые факторы прогноза\n"
            "3) Что сделать сегодня для лучшего завтра"
        )
