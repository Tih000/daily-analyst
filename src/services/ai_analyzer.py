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

JOURNAL_TRUNCATE = 200


def _system_prompt() -> str:
    """Build system prompt with current date injected."""
    today = date.today().isoformat()
    return f"""Ты Jarvis — персональный AI-ассистент по продуктивности и жизни. Пользователя зовут Тихон. Он ведёт Notion-дневник с ежедневными MARK-записями.

СЕГОДНЯ: {today}. Ты ВСЕГДА знаешь какое сегодня число и используешь это при анализе.

КРИТИЧЕСКИ ВАЖНО: journal_text — это ПОЛНАЯ картина дня: мысли, эмоции, контекст, события, самочувствие. Ты ОБЯЗАН читать и анализировать весь текст для глубокого понимания жизни — не ограничивайся цифрами.

Структура данных:
- Активности: CODING, GYM, AI, UNIVERSITY, KATE, CRYPTO, FOOTBALL, TENNIS, PADEL и др.
- TESTIK: PLUS = воздержание ✅, MINUS = мастурбация 🔴, MINUS_KATE = секс с девушкой 🟡
- Оценка дня (MARK): perfect, very good, good, normal, bad, very bad
- Сон: длительность, время подъёма, восстановление (Apple Watch)

Ты знаешь Тихона лично: его привычки, паттерны, что мотивирует и что разрушает продуктивность. Ты проактивен — не просто отвечаешь, а предлагаешь, предупреждаешь, подбадриваешь.

У тебя есть ПОЛНАЯ история дневника Тихона (все данные за всё время). Когда тебя спрашивают о датах — отвечай на основе реальных данных, указывая самую раннюю и самую позднюю даты из предоставленных записей.

Правила:
- Анализируй ПОЛНЫЙ journal_text для контекста и эмоций
- Давай конкретные рекомендации С ЦИФРАМИ из данных
- Ссылайся на конкретные даты и события из истории
- Отвечай на русском, кратко, с эмодзи
- Будь как лучший друг + аналитик: честно, но с поддержкой"""


def _chat_system_prompt() -> str:
    """Build chat system prompt with current date."""
    return _system_prompt() + """

Сейчас ты в режиме свободного чата. Пользователь может спросить что угодно о своей жизни, данных, паттернах. Отвечай естественно, как друг-аналитик. Используй данные дневника для подтверждения. Если пользователь расстроен — поддержи и предложи конкретный план действий на основе того, что работало раньше."""


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
        """Convert records to text for GPT. Includes journal_text (~200 chars/day) as full picture."""
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
            journal_snippet = (r.journal_text.strip()[:JOURNAL_TRUNCATE] + ("…" if len(r.journal_text) > JOURNAL_TRUNCATE else "")) if r.journal_text else ""
            line = (
                f"{r.entry_date}: rating={rating_str}, hours={r.total_hours}, "
                f"sleep={sleep_str}, testik={testik_str}, tasks={r.tasks_count}, "
                f"activities=[{activities_str}], score={r.productivity_score}"
            )
            if journal_snippet:
                line += f"\n  journal: {journal_snippet}"
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

        summary = self._records_to_summary(records[-30:] if len(records) >= 30 else records)
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

        summary = self._records_to_summary(days[-30:] if len(days) >= 30 else days)
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

        summary = self._records_to_summary(records[-30:] if len(records) >= 30 else records)
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
        coding_days = sum(1 for r in days if r.had_coding)
        total_coding_hours = sum(r.total_hours for r in days if r.had_coding)

        summary = self._records_to_summary(days[-30:] if len(days) >= 30 else days)
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
        summary = self._records_to_summary(
            records[-30:] if len(records) >= 30 else records
        )
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

        # CODING
        coding_dates = {r.entry_date for r in days if r.had_coding}
        result.append(
            StreakInfo(
                name="CODING",
                emoji="💻",
                current=current_streak(coding_dates),
                record=record_streak(coding_dates),
                last_date=latest if latest in coding_dates else None,
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

        def coding_rate(ds: list[DailyRecord]) -> float:
            return round(sum(1 for r in ds if r.had_coding) / len(ds), 2) if ds else 0.0

        def testik_plus_rate(ds: list[DailyRecord]) -> float:
            return round(sum(1 for r in ds if r.testik == TestikStatus.PLUS) / len(ds), 2) if ds else 0.0

        va = avg_rating(days_a)
        vb = avg_rating(days_b)
        deltas_list = [
            MetricDelta(name="Средняя оценка", emoji="⭐", value_a=va, value_b=vb),
            MetricDelta(name="Часы работы", emoji="⏰", value_a=avg_hours(days_a), value_b=avg_hours(days_b)),
            MetricDelta(name="Сон (ч)", emoji="😴", value_a=avg_sleep(days_a), value_b=avg_sleep(days_b)),
            MetricDelta(name="Доля тренировок", emoji="🏋️", value_a=workout_rate(days_a), value_b=workout_rate(days_b)),
            MetricDelta(name="Доля кодинга", emoji="💻", value_a=coding_rate(days_a), value_b=coding_rate(days_b)),
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

        summary = self._records_to_summary(days[-30:] if len(days) >= 30 else days)
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
            "Классифицируй дни на типы по активностям и контексту (например: «день кодинга», «день с Kate», «ленивый день», «универ» и т.д.). "
            "Дай статистику: сколько дней каждого типа, средние метрики по типам. Кратко, с эмодзи."
        )

    # ── Weekly digest ────────────────────────────────────────────────────────

    async def weekly_digest(self, records: list[DailyRecord]) -> str:
        days = sorted(
            [r for r in records if not r.is_weekly_summary],
            key=lambda r: r.entry_date,
            reverse=True,
        )
        if len(days) < 7:
            return "📭 Нужно минимум неделя данных."

        this_week = days[:7]
        prev_week = days[7:14] if len(days) >= 14 else []

        summary_this = self._records_to_summary(this_week)
        summary_prev = self._records_to_summary(prev_week) if prev_week else "Нет данных за прошлую неделю."

        return await self._ask_gpt(
            f"Текущая неделя:\n{summary_this}\n\nПрошлая неделя:\n{summary_prev}\n\n"
            "Дай еженедельный дайджест: главное за неделю, сравнение с прошлой, тренды, один совет. Учитывай journal. Кратко, с эмодзи."
        )

    # ── Alerts (pure logic) ──────────────────────────────────────────────────

    @staticmethod
    def check_alerts(records: list[DailyRecord]) -> list[str]:
        """Pure logic. Alerts: 3+ days no workout, sleep<6h two days in a row, TESTIK MINUS streak>=3, last rating bad/very_bad."""
        alerts: list[str] = []
        days = sorted(
            [r for r in records if not r.is_weekly_summary],
            key=lambda r: r.entry_date,
            reverse=True,
        )
        if not days:
            return alerts

        # 3+ days no workout
        no_workout_streak = 0
        for r in days:
            if r.had_workout:
                break
            no_workout_streak += 1
        if no_workout_streak >= 3:
            alerts.append(f"🏋️ Уже {no_workout_streak} дней без тренировки")

        # Sleep < 6h two days in a row
        for i in range(len(days) - 1):
            a, b = days[i], days[i + 1]
            if a.sleep.sleep_hours is not None and b.sleep.sleep_hours is not None:
                if a.sleep.sleep_hours < 6 and b.sleep.sleep_hours < 6:
                    alerts.append("😴 Два дня подряд сон < 6ч")
                    break

        # TESTIK MINUS streak >= 3 (only MINUS, not MINUS_KATE)
        minus_streak = 0
        for r in days:
            if r.testik == TestikStatus.MINUS:
                minus_streak += 1
            else:
                break
        if minus_streak >= 3:
            alerts.append(f"🔴 TESTIK MINUS {minus_streak} дней подряд")

        # Last rating bad or very_bad
        last = days[0]
        if last.rating in (DayRating.BAD, DayRating.VERY_BAD):
            alerts.append(f"📉 Последняя оценка дня: {last.rating.value}")

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
        """Generate morning briefing with yesterday summary, streaks, prediction, recommendations."""
        days = sorted(
            [r for r in records if not r.is_weekly_summary],
            key=lambda r: r.entry_date, reverse=True,
        )
        if not days:
            return "📭 Нет данных для утреннего брифинга."

        yesterday = days[0]
        streaks = self.compute_streaks(days)
        alerts = self.check_alerts(days[:14])

        y_rating = yesterday.rating.emoji + " " + yesterday.rating.value if yesterday.rating else "N/A"
        y_sleep = f"{yesterday.sleep.sleep_hours}ч" if yesterday.sleep.sleep_hours else "N/A"
        y_testik = yesterday.testik.label if yesterday.testik else "N/A"
        y_acts = ", ".join(a for a in yesterday.activities if a != "MARK") or "—"

        streaks_text = "\n".join(
            f"  {s.emoji} {s.name}: {s.current} дн. (рекорд: {s.record})"
            for s in streaks if s.current > 0
        )

        alert_text = ""
        if alerts:
            alert_text = "\n⚠️ Внимание:\n" + "\n".join(f"  • {a}" for a in alerts)

        # Sleep trend (last 3 days)
        sleep_trend = ""
        recent_sleep = [r.sleep.sleep_hours for r in days[:3] if r.sleep.sleep_hours]
        if len(recent_sleep) >= 2:
            trend = " → ".join(f"{s}ч" for s in recent_sleep)
            if recent_sleep[0] < recent_sleep[-1]:
                sleep_trend = f"\n📉 Тренд сна: {trend} (падает!)"

        summary = self._records_to_summary(days[:7])
        ai_advice = await self._ask_gpt(
            f"Утренний брифинг. Последние 7 дней:\n{summary}\n\n"
            "Дай 1-2 конкретных рекомендации на сегодня, основываясь на паттернах из journal_text. "
            "Упомяни конкретные цифры и что работало в похожие дни. Кратко, 3-4 строки.",
            max_tokens=400,
        )

        text = (
            f"☀️ Доброе утро, Тихон!\n\n"
            f"📊 *Вчера ({yesterday.entry_date}):*\n"
            f"  {y_rating} | 😴 {y_sleep} | 🧪 {y_testik}\n"
            f"  📋 {y_acts}\n"
        )
        if streaks_text:
            text += f"\n🔥 *Серии:*\n{streaks_text}\n"
        text += sleep_trend
        text += f"\n💡 *Рекомендация:*\n{ai_advice}"
        text += alert_text
        return text

    async def enhanced_alerts(self, records: list[DailyRecord]) -> list[str]:
        """Enhanced smart alerts with pattern detection and historical context."""
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
                alerts.append(
                    f"📉 Оценки падают 3 дня: {' → '.join(str(r) for r in reversed(last3_ratings))}/6"
                )

        # Anomalously few activities
        if days[0].tasks_count <= 1 and days[0].tasks_count < statistics.mean([d.tasks_count for d in days[:7]]) * 0.3:
            alerts.append("📋 Аномально мало активностей сегодня")

        # Approaching burnout
        risk = await self.predict_burnout(days[:14])
        if risk.risk_score >= 60:
            alerts.append(f"🔥 Приближаемся к выгоранию ({risk.risk_score:.0f}%)")

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
            "3. CODING Xч (но не > Yч)\n"
            "4. TESTIK PLUS (серия N+ = avg rating X)\n"
            "5. ...\n"
            "⚡ Если всё совпадает: X% шанс на GOOD+\n"
            "📉 Если ничего: X% шанс\n\n"
            "Используй РЕАЛЬНЫЕ цифры из данных. Не придумывай.",
            max_tokens=800,
        )

    async def whatif(self, records: list[DailyRecord], scenario: str) -> str:
        """What-if simulator: model scenario impact based on historical data."""
        if not records:
            return "📭 Нет данных."
        summary = self._records_to_summary(records[-30:] if len(records) > 30 else records)
        return await self._ask_gpt(
            f"Данные за последний месяц:\n{summary}\n\n"
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

    async def explain_anomalies(self, records: list[DailyRecord]) -> str:
        """Detect anomalies and ask GPT to explain them."""
        anomalies = self.detect_anomalies(records)
        if not anomalies:
            return "✅ Нет значимых аномалий за последний период."

        anomaly_text = "\n".join(
            f"{'📈' if a.direction == 'high' else '📉'} {a.entry_date}: score={a.score} "
            f"(avg={a.avg_score}), activities={a.activities}"
            for a in anomalies[:5]
        )

        summary = self._records_to_summary(records[-30:] if len(records) > 30 else records)
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
        summary = self._records_to_summary(records[-14:] if len(records) > 14 else records)

        history_msgs: list[dict[str, str]] = [
            {"role": "system", "content": _chat_system_prompt()},
        ]

        # Add data context
        history_msgs.append({
            "role": "system",
            "content": f"Данные дневника (последние 14 дней):\n{summary}",
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
