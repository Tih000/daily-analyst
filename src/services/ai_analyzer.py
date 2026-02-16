"""GPT-powered analytics engine for journal data."""

from __future__ import annotations

import logging
import statistics
from collections import Counter
from datetime import date, timedelta
from typing import Any, Optional

import openai
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from src.config import get_settings
from src.models.journal_entry import (
    BurnoutRisk,
    CorrelationResult,
    DaySummary,
    ForecastResult,
    JournalEntry,
    MonthAnalysis,
    Mood,
    Testik,
    WeakSpot,
)

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """Ты эксперт по продуктивности. Анализируй дневник разработчика:
- Корреляции сна/работы/настроения/TESTIK
- Предсказания burnout (3+ MINUS TESTIK подряд, <6ч сна)
- Рекомендации по режиму/задачам
- Чёткие метрики и цифры
Отвечай кратко, с эмодзи, actionable insights. На русском языке."""

# Retry on transient OpenAI errors
_RETRY_EXCEPTIONS = (
    openai.RateLimitError,
    openai.APITimeoutError,
    openai.APIConnectionError,
    openai.InternalServerError,
)


class AIAnalyzer:
    """Analyzes journal entries using GPT and local statistics."""

    def __init__(self) -> None:
        settings = get_settings()
        self._client = openai.AsyncOpenAI(api_key=settings.openai.api_key)
        self._model = settings.openai.model

    # ── GPT call helper ─────────────────────────────────────────────────────

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(min=1, max=15),
        retry=retry_if_exception_type(_RETRY_EXCEPTIONS),
        reraise=True,
    )
    async def _ask_gpt(self, user_prompt: str, max_tokens: int = 1500) -> str:
        """Send a prompt to GPT and return the text response (with retry)."""
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
        except _RETRY_EXCEPTIONS:
            raise  # let tenacity handle retries
        except Exception as e:
            logger.error("GPT call failed: %s", e)
            return f"⚠️ AI анализ недоступен: {e}"

    # ── Entries to text ─────────────────────────────────────────────────────

    @staticmethod
    def _entries_to_summary(entries: list[JournalEntry], max_detailed: int = 10) -> str:
        """Convert entries to a compact text summary for GPT context.

        Sends aggregated stats for all entries, plus detailed lines for
        the most recent `max_detailed` entries (with notes) to keep
        token usage manageable.
        """
        if not entries:
            return "Нет данных."

        sorted_entries = sorted(entries, key=lambda x: x.entry_date)

        # Aggregate stats for full period
        mood_scores = [e.mood.score for e in sorted_entries if e.mood]
        sleep_vals = [e.sleep_hours for e in sorted_entries]
        work_vals = [e.hours_worked for e in sorted_entries]
        prod_vals = [e.productivity_score for e in sorted_entries]
        earnings_vals = [e.earnings_usd for e in sorted_entries]
        testik_counter = Counter(e.testik.value if e.testik else "N/A" for e in sorted_entries)
        workout_count = sum(1 for e in sorted_entries if e.workout)
        uni_count = sum(1 for e in sorted_entries if e.university)

        agg_lines = [
            f"Период: {sorted_entries[0].entry_date} — {sorted_entries[-1].entry_date} ({len(sorted_entries)} дней)",
            f"Средние: mood={statistics.mean(mood_scores):.1f}/5, work={statistics.mean(work_vals):.1f}h, "
            f"sleep={statistics.mean(sleep_vals):.1f}h, productivity={statistics.mean(prod_vals):.1f}"
            if mood_scores else "Средние: нет данных о настроении",
            f"Заработок: ${sum(earnings_vals):.0f} total, ${statistics.mean(earnings_vals):.1f}/день",
            f"TESTIK: {dict(testik_counter)}",
            f"Тренировки: {workout_count}/{len(sorted_entries)}, Универ: {uni_count}/{len(sorted_entries)}",
        ]

        # Detailed lines for recent entries (with notes)
        recent = sorted_entries[-max_detailed:]
        detail_lines: list[str] = []
        for e in recent:
            mood_str = e.mood.value if e.mood else "N/A"
            testik_str = e.testik.value if e.testik else "N/A"
            notes_part = ""
            if e.notes and e.notes.strip():
                truncated_note = e.notes.strip()[:120]
                notes_part = f', notes="{truncated_note}"'
            detail_lines.append(
                f"{e.entry_date}: mood={mood_str}, work={e.hours_worked}h, "
                f"tasks={e.tasks_completed}, sleep={e.sleep_hours}h, "
                f"testik={testik_str}, workout={'Y' if e.workout else 'N'}, "
                f"uni={'Y' if e.university else 'N'}, ${e.earnings_usd}, "
                f"score={e.productivity_score}{notes_part}"
            )

        result = "=== Сводка ===\n" + "\n".join(agg_lines)
        if len(sorted_entries) > max_detailed:
            result += f"\n\n=== Последние {max_detailed} дней (детально) ===\n"
        else:
            result += "\n\n=== Детально ===\n"
        result += "\n".join(detail_lines)
        return result

    # ── Analytics commands ──────────────────────────────────────────────────

    async def analyze_month(self, entries: list[JournalEntry], month_label: str) -> MonthAnalysis:
        """Full monthly analysis with AI insights."""
        if not entries:
            return MonthAnalysis(
                month=month_label, total_entries=0, avg_mood_score=0,
                avg_hours_worked=0, avg_sleep_hours=0, total_earnings=0,
                total_tasks=0, workout_rate=0, university_rate=0,
                ai_insights="📭 Нет записей за этот месяц.",
            )

        mood_scores = [e.mood.score for e in entries if e.mood]

        best = max(entries, key=lambda e: e.productivity_score)
        worst = min(entries, key=lambda e: e.productivity_score)

        summary = self._entries_to_summary(entries, max_detailed=15)
        ai_text = await self._ask_gpt(
            f"Проанализируй продуктивность за {month_label}:\n{summary}\n\n"
            "Дай: 1) Главные тренды 2) Что хорошо 3) Что улучшить 4) Конкретные советы"
        )

        return MonthAnalysis(
            month=month_label,
            total_entries=len(entries),
            avg_mood_score=round(statistics.mean(mood_scores), 2) if mood_scores else 0,
            avg_hours_worked=round(statistics.mean([e.hours_worked for e in entries]), 1),
            avg_sleep_hours=round(statistics.mean([e.sleep_hours for e in entries]), 1),
            total_earnings=sum(e.earnings_usd for e in entries),
            total_tasks=sum(e.tasks_completed for e in entries),
            workout_rate=round(sum(1 for e in entries if e.workout) / len(entries), 2),
            university_rate=round(sum(1 for e in entries if e.university) / len(entries), 2),
            best_day=DaySummary(
                entry_date=best.entry_date,
                productivity_score=best.productivity_score,
                mood=best.mood,
                hours_worked=best.hours_worked,
                tasks_completed=best.tasks_completed,
            ),
            worst_day=DaySummary(
                entry_date=worst.entry_date,
                productivity_score=worst.productivity_score,
                mood=worst.mood,
                hours_worked=worst.hours_worked,
                tasks_completed=worst.tasks_completed,
            ),
            ai_insights=ai_text,
        )

    async def predict_burnout(self, entries: list[JournalEntry]) -> BurnoutRisk:
        """Predict burnout risk for next 5 days based on recent patterns."""
        recent = sorted(entries, key=lambda e: e.entry_date, reverse=True)[:14]
        if len(recent) < 3:
            return BurnoutRisk(
                risk_level="unknown",
                risk_score=0,
                factors=["Недостаточно данных (нужно минимум 3 дня)"],
                recommendation="Веди дневник регулярно для точных прогнозов.",
            )

        factors: list[str] = []
        risk = 0.0

        # Factor: consecutive MINUS TESTIK
        last_testiks = [e.testik for e in recent[:7] if e.testik]
        minus_streak = 0
        for t in last_testiks:
            if t in (Testik.MINUS_KATE, Testik.MINUS_SOLO):
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
        avg_sleep = statistics.mean([e.sleep_hours for e in recent[:7]])
        if avg_sleep < 6:
            risk += 25
            factors.append(f"😴 Средний сон: {avg_sleep:.1f}ч (<6ч)")
        elif avg_sleep < 7:
            risk += 10
            factors.append(f"💤 Средний сон: {avg_sleep:.1f}ч (<7ч)")

        # Factor: mood trend
        moods = [e.mood.score for e in recent[:7] if e.mood]
        if len(moods) >= 3:
            mood_trend = moods[0] - statistics.mean(moods)
            if mood_trend < -1:
                risk += 20
                factors.append("📉 Настроение падает")

        # Factor: overwork
        avg_work = statistics.mean([e.hours_worked for e in recent[:7]])
        if avg_work > 10:
            risk += 15
            factors.append(f"⏰ Переработка: {avg_work:.1f}ч/день")

        # Factor: no workout streak
        no_workout = sum(1 for e in recent[:7] if not e.workout)
        if no_workout >= 5:
            risk += 10
            factors.append(f"🏋️ {no_workout}/7 дней без тренировок")

        risk = min(risk, 100)

        if risk >= 70:
            level = "critical"
        elif risk >= 45:
            level = "high"
        elif risk >= 20:
            level = "medium"
        else:
            level = "low"

        summary = self._entries_to_summary(recent[:7])
        ai_rec = await self._ask_gpt(
            f"Риск выгорания: {level} ({risk}%). Факторы: {', '.join(factors)}\n"
            f"Последние 7 дней:\n{summary}\n\n"
            "Дай 3 конкретных совета на ближайшие 5 дней для предотвращения выгорания."
        )

        return BurnoutRisk(
            risk_level=level,
            risk_score=risk,
            factors=factors if factors else ["✅ Нет критичных факторов"],
            recommendation=ai_rec,
        )

    async def best_days(self, entries: list[JournalEntry], top_n: int = 3) -> list[DaySummary]:
        """Return top N most productive days."""
        sorted_entries = sorted(entries, key=lambda e: e.productivity_score, reverse=True)
        return [
            DaySummary(
                entry_date=e.entry_date,
                productivity_score=e.productivity_score,
                mood=e.mood,
                hours_worked=e.hours_worked,
                tasks_completed=e.tasks_completed,
            )
            for e in sorted_entries[:top_n]
        ]

    async def optimal_hours(self, entries: list[JournalEntry]) -> str:
        """Analyze optimal work hours based on productivity patterns."""
        if not entries:
            return "📭 Нет данных для анализа."

        summary = self._entries_to_summary(entries, max_detailed=14)
        return await self._ask_gpt(
            f"Данные дневника:\n{summary}\n\n"
            "Проанализируй: 1) Оптимальное кол-во рабочих часов "
            "2) Связь часов работы и настроения "
            "3) Когда продуктивность максимальна "
            "4) Рекомендация по режиму работы"
        )

    async def kate_impact(self, entries: list[JournalEntry]) -> str:
        """Analyze correlation between relationships (TESTIK) and productivity."""
        if not entries:
            return "📭 Нет данных для анализа."

        with_kate: list[JournalEntry] = []
        minus_kate: list[JournalEntry] = []
        for e in entries:
            if e.testik == Testik.PLUS:
                with_kate.append(e)
            elif e.testik == Testik.MINUS_KATE:
                minus_kate.append(e)

        stats_parts: list[str] = []
        if with_kate:
            avg_prod_plus = statistics.mean([e.productivity_score for e in with_kate])
            avg_mood_plus = statistics.mean([e.mood.score for e in with_kate if e.mood])
            stats_parts.append(
                f"PLUS дни ({len(with_kate)}): avg_productivity={avg_prod_plus:.1f}, "
                f"avg_mood={avg_mood_plus:.1f}"
            )
        if minus_kate:
            avg_prod_mk = statistics.mean([e.productivity_score for e in minus_kate])
            avg_mood_mk = statistics.mean([e.mood.score for e in minus_kate if e.mood])
            stats_parts.append(
                f"MINUS_KATE дни ({len(minus_kate)}): avg_productivity={avg_prod_mk:.1f}, "
                f"avg_mood={avg_mood_mk:.1f}"
            )

        summary = self._entries_to_summary(entries[-30:], max_detailed=14)
        return await self._ask_gpt(
            f"Статистика отношений:\n{chr(10).join(stats_parts)}\n\n"
            f"Полные данные (последние 30 дней):\n{summary}\n\n"
            "Проанализируй влияние отношений (Kate) на продуктивность, "
            "настроение, сон и работу. Дай конкретные цифры и рекомендации."
        )

    async def testik_patterns(self, entries: list[JournalEntry]) -> str:
        """Analyze TESTIK patterns and their impact on all metrics."""
        if not entries:
            return "📭 Нет данных для анализа."

        by_testik: dict[str, list[JournalEntry]] = {"PLUS": [], "MINUS_KATE": [], "MINUS_SOLO": [], "N/A": []}
        for e in entries:
            key = e.testik.value if e.testik else "N/A"
            by_testik[key].append(e)

        stats_lines: list[str] = []
        for label, group in by_testik.items():
            if not group:
                continue
            avg_prod = statistics.mean([e.productivity_score for e in group])
            avg_sleep = statistics.mean([e.sleep_hours for e in group])
            avg_mood = statistics.mean([e.mood.score for e in group if e.mood]) if any(e.mood for e in group) else 0
            stats_lines.append(
                f"{label} ({len(group)} дней): productivity={avg_prod:.1f}, "
                f"mood={avg_mood:.1f}, sleep={avg_sleep:.1f}h"
            )

        summary = self._entries_to_summary(entries[-30:], max_detailed=14)
        return await self._ask_gpt(
            f"TESTIK статистика:\n" + "\n".join(stats_lines) + "\n\n"
            f"Данные:\n{summary}\n\n"
            "Проанализируй паттерны TESTIK: 1) Как каждый тип влияет на метрики "
            "2) Есть ли закономерности по дням недели "
            "3) Что делать для увеличения PLUS дней"
        )

    async def sleep_optimizer(self, entries: list[JournalEntry]) -> str:
        """Analyze sleep patterns and give optimization advice."""
        if not entries:
            return "📭 Нет данных для анализа."

        sleep_data = [(e.sleep_hours, e.productivity_score, e.mood.score if e.mood else 3) for e in entries]
        avg_sleep = statistics.mean([s[0] for s in sleep_data])
        best_sleep_range = [s for s in sleep_data if s[1] > statistics.mean([x[1] for x in sleep_data])]
        optimal_sleep = statistics.mean([s[0] for s in best_sleep_range]) if best_sleep_range else avg_sleep

        summary = self._entries_to_summary(entries[-30:], max_detailed=14)
        return await self._ask_gpt(
            f"Данные сна: avg={avg_sleep:.1f}ч, optimal={optimal_sleep:.1f}ч\n"
            f"Дневник:\n{summary}\n\n"
            "Проанализируй: 1) Оптимальное время сна для макс. продуктивности "
            "2) Влияние недосыпа на TESTIK и настроение "
            "3) Конкретный план улучшения сна"
        )

    async def money_forecast(self, entries: list[JournalEntry]) -> str:
        """Forecast earnings based on historical patterns."""
        if not entries:
            return "📭 Нет данных для прогноза."

        earnings = [(e.entry_date, e.earnings_usd) for e in entries if e.earnings_usd > 0]
        total = sum(e.earnings_usd for e in entries)
        avg_daily = total / len(entries) if entries else 0
        earning_days = len(earnings)

        summary = self._entries_to_summary(entries[-30:], max_detailed=14)
        return await self._ask_gpt(
            f"Заработок: total=${total:.0f}, avg/day=${avg_daily:.1f}, "
            f"earning_days={earning_days}/{len(entries)}\n"
            f"Данные:\n{summary}\n\n"
            "Дай: 1) Прогноз на следующий месяц "
            "2) Связь заработка с продуктивностью/настроением "
            "3) Как увеличить доход на основе паттернов"
        )

    async def weak_spots(self, entries: list[JournalEntry]) -> str:
        """Identify weak spots in productivity patterns."""
        if not entries:
            return "📭 Нет данных для анализа."

        summary = self._entries_to_summary(entries[-30:], max_detailed=14)
        return await self._ask_gpt(
            f"Данные за последний период:\n{summary}\n\n"
            "Найди ТОП-5 слабых мест в продуктивности. Для каждого дай:\n"
            "- Проблема + серьёзность (🔴/🟡/🟢)\n"
            "- Конкретные цифры\n"
            "- Actionable решение"
        )

    async def tomorrow_mood(self, entries: list[JournalEntry]) -> str:
        """Predict tomorrow's mood based on recent patterns."""
        recent = sorted(entries, key=lambda e: e.entry_date, reverse=True)[:7]
        if len(recent) < 3:
            return "📭 Нужно минимум 3 записи для прогноза."

        summary = self._entries_to_summary(recent)
        return await self._ask_gpt(
            f"Последние 7 дней:\n{summary}\n\n"
            "На основе трендов предскажи завтрашнее настроение. Дай:\n"
            "1) Прогноз настроения (PERFECT/GOOD/NORMAL/BAD/VERY_BAD) с вероятностью\n"
            "2) Ключевые факторы прогноза\n"
            "3) Что сделать сегодня для лучшего завтра"
        )
