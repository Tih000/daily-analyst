"""Chart generation service using Matplotlib for DailyRecord data."""

from __future__ import annotations

import io
import logging
from collections import Counter, defaultdict
from datetime import date, timedelta

import matplotlib
matplotlib.use("Agg")

import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import numpy as np

from src.models.journal_entry import (
    Anomaly,
    CorrelationMatrix,
    DailyRecord,
    DayRating,
    LifeScore,
    MonthComparison,
    StreakInfo,
    TestikStatus,
)

logger = logging.getLogger(__name__)

COLORS = {
    "primary": "#6366f1",
    "secondary": "#22d3ee",
    "accent": "#f59e0b",
    "danger": "#ef4444",
    "success": "#10b981",
    "bg": "#1e1e2e",
    "text": "#cdd6f4",
    "grid": "#313244",
}

RATING_COLORS = {
    DayRating.PERFECT: "#10b981",
    DayRating.VERY_GOOD: "#22d3ee",
    DayRating.GOOD: "#6366f1",
    DayRating.NORMAL: "#f59e0b",
    DayRating.BAD: "#f97316",
    DayRating.VERY_BAD: "#ef4444",
}

plt.rcParams.update({
    "figure.facecolor": COLORS["bg"],
    "axes.facecolor": COLORS["bg"],
    "axes.edgecolor": COLORS["grid"],
    "axes.labelcolor": COLORS["text"],
    "text.color": COLORS["text"],
    "xtick.color": COLORS["text"],
    "ytick.color": COLORS["text"],
    "grid.color": COLORS["grid"],
    "grid.alpha": 0.3,
    "font.size": 10,
})

DPI = 150


class ChartsService:
    """Generate inline chart images for Telegram."""

    @staticmethod
    def _fig_to_bytes(fig: plt.Figure) -> bytes:
        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=DPI, bbox_inches="tight", pad_inches=0.3)
        plt.close(fig)
        buf.seek(0)
        return buf.read()

    def _empty_chart(self, message: str) -> bytes:
        fig, ax = plt.subplots(figsize=(8, 4))
        ax.text(0.5, 0.5, message, ha="center", va="center", fontsize=14, color=COLORS["text"])
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.axis("off")
        return self._fig_to_bytes(fig)

    # ── Habit presence for heatmap ───────────────────────────────────────────

    def _habit_present(self, record: DailyRecord, habit_name: str) -> bool:
        name = habit_name.strip().lower()
        if name in ("gym", "workout"):
            return record.had_workout
        if name == "coding":
            return record.had_coding
        if name == "university":
            return record.had_university
        if name == "kate":
            return record.had_kate
        if name == "sleep7":
            return (record.sleep.sleep_hours or 0) >= 7
        return any(a.strip().lower() == name for a in record.activities)

    # ── Monthly Overview ────────────────────────────────────────────────────

    def monthly_overview(self, records: list[DailyRecord], month_label: str) -> bytes:
        days = sorted([r for r in records if not r.is_weekly_summary], key=lambda r: r.entry_date)
        if not days:
            return self._empty_chart("No data for " + month_label)

        dates = [r.entry_date for r in days]
        scores = [r.productivity_score for r in days]
        ratings = [r.rating.score if r.rating else 3 for r in days]
        sleep = [r.sleep.sleep_hours or 0 for r in days]
        hours = [r.total_hours for r in days]

        fig, axes = plt.subplots(3, 1, figsize=(12, 10), sharex=True)
        fig.suptitle(f"Monthly Overview: {month_label}", fontsize=16, fontweight="bold")

        ax1 = axes[0]
        ax1.fill_between(dates, scores, alpha=0.3, color=COLORS["primary"])
        ax1.plot(dates, scores, color=COLORS["primary"], linewidth=2, marker="o", markersize=4)
        ax1.set_ylabel("Productivity Score")
        ax1.set_ylim(0, 100)
        ax1.grid(True)
        avg = np.mean(scores)
        ax1.axhline(y=avg, color=COLORS["accent"], linestyle="--", alpha=0.7, label=f"Avg: {avg:.1f}")
        ax1.legend(loc="upper right")

        ax2 = axes[1]
        colors_list = [RATING_COLORS.get(r.rating, COLORS["grid"]) for r in days]
        ax2.bar(dates, ratings, color=colors_list, alpha=0.8, width=0.8)
        ax2.set_ylabel("Day Rating (1-6)")
        ax2.set_ylim(0, 7)
        ax2.grid(True, axis="y")

        ax3 = axes[2]
        x = np.arange(len(dates))
        w = 0.35
        ax3.bar(x - w / 2, sleep, w, label="Sleep", color=COLORS["secondary"], alpha=0.8)
        ax3.bar(x + w / 2, hours, w, label="Work hours", color=COLORS["accent"], alpha=0.8)
        ax3.set_ylabel("Hours")
        step = max(1, len(x) // 10)
        ax3.set_xticks(x[::step])
        ax3.set_xticklabels([d.strftime("%d") for d in dates][::step], rotation=45)
        ax3.legend(loc="upper right")
        ax3.grid(True, axis="y")

        fig.tight_layout()
        return self._fig_to_bytes(fig)

    # ── Burnout Risk ────────────────────────────────────────────────────────

    def burnout_chart(self, records: list[DailyRecord]) -> bytes:
        days = sorted([r for r in records if not r.is_weekly_summary], key=lambda r: r.entry_date)
        if len(days) < 3:
            return self._empty_chart("Need at least 3 days")

        dates = [r.entry_date for r in days]
        risk_scores: list[float] = []
        for i in range(len(days)):
            window = days[max(0, i - 2): i + 1]
            risk = 0.0
            sleep_vals = [r.sleep.sleep_hours for r in window if r.sleep.sleep_hours]
            if sleep_vals and np.mean(sleep_vals) < 6:
                risk += 35
            elif sleep_vals and np.mean(sleep_vals) < 7:
                risk += 15
            minus_count = sum(
                1 for r in window
                if r.testik in (TestikStatus.MINUS, TestikStatus.MINUS_KATE)
            )
            risk += minus_count * 15
            ratings = [r.rating.score for r in window if r.rating]
            if ratings and np.mean(ratings) < 2.5:
                risk += 20
            if np.mean([r.total_hours for r in window]) > 10:
                risk += 15
            risk_scores.append(min(risk, 100))

        fig, ax = plt.subplots(figsize=(12, 5))
        fig.suptitle("Burnout Risk Index", fontsize=14, fontweight="bold")

        ax.axhspan(0, 20, alpha=0.1, color=COLORS["success"])
        ax.axhspan(20, 45, alpha=0.1, color=COLORS["accent"])
        ax.axhspan(45, 70, alpha=0.1, color="#f97316")
        ax.axhspan(70, 100, alpha=0.1, color=COLORS["danger"])

        ax.fill_between(dates, risk_scores, alpha=0.3, color=COLORS["danger"])
        ax.plot(dates, risk_scores, color=COLORS["danger"], linewidth=2, marker="o", markersize=3)
        ax.set_ylabel("Burnout Risk (%)")
        ax.set_ylim(0, 100)
        ax.grid(True)

        ax.text(dates[0], 10, "Low", fontsize=8, color=COLORS["success"], alpha=0.7)
        ax.text(dates[0], 32, "Medium", fontsize=8, color=COLORS["accent"], alpha=0.7)
        ax.text(dates[0], 57, "High", fontsize=8, color="#f97316", alpha=0.7)
        ax.text(dates[0], 85, "Critical", fontsize=8, color=COLORS["danger"], alpha=0.7)

        ax.xaxis.set_major_formatter(mdates.DateFormatter("%d.%m"))
        fig.autofmt_xdate()
        fig.tight_layout()
        return self._fig_to_bytes(fig)

    # ── TESTIK Impact ───────────────────────────────────────────────────────

    def testik_chart(self, records: list[DailyRecord]) -> bytes:
        days = [r for r in records if not r.is_weekly_summary]
        groups: dict[str, list[DailyRecord]] = defaultdict(list)
        for r in days:
            key = r.testik.value if r.testik else "N/A"
            groups[key].append(r)

        if len(groups) < 2:
            return self._empty_chart("Not enough TESTIK data")

        categories = list(groups.keys())
        metrics = {
            "Score": [np.mean([r.productivity_score for r in groups[c]]) for c in categories],
            "Rating x15": [
                np.mean([r.rating.score for r in groups[c] if r.rating]) * 15
                if any(r.rating for r in groups[c]) else 0
                for c in categories
            ],
            "Sleep x10": [
                np.mean([r.sleep.sleep_hours for r in groups[c] if r.sleep.sleep_hours]) * 10
                if any(r.sleep.sleep_hours for r in groups[c]) else 0
                for c in categories
            ],
        }

        fig, ax = plt.subplots(figsize=(10, 6))
        fig.suptitle("TESTIK Impact on Metrics", fontsize=14, fontweight="bold")

        x = np.arange(len(categories))
        w = 0.25
        bar_colors = [COLORS["primary"], COLORS["secondary"], COLORS["accent"]]
        for i, (label, vals) in enumerate(metrics.items()):
            ax.bar(x + i * w, vals, w, label=label, color=bar_colors[i], alpha=0.8)

        ax.set_xticks(x + w)
        ax.set_xticklabels(categories)
        ax.legend()
        ax.grid(True, axis="y")
        fig.tight_layout()
        return self._fig_to_bytes(fig)

    # ── Sleep vs Productivity ───────────────────────────────────────────────

    def sleep_chart(self, records: list[DailyRecord]) -> bytes:
        days = [r for r in records if r.sleep.sleep_hours and not r.is_weekly_summary]
        if not days:
            return self._empty_chart("No sleep data")

        sleep = [r.sleep.sleep_hours for r in days]
        scores = [r.productivity_score for r in days]
        colors_list = [RATING_COLORS.get(r.rating, COLORS["grid"]) for r in days]

        fig, ax = plt.subplots(figsize=(10, 6))
        fig.suptitle("Sleep vs Productivity", fontsize=14, fontweight="bold")

        ax.scatter(sleep, scores, c=colors_list, s=60, alpha=0.7, edgecolors="white", linewidths=0.5)

        if len(sleep) > 2:
            z = np.polyfit(sleep, scores, 1)
            p = np.poly1d(z)
            x_line = np.linspace(min(sleep), max(sleep), 100)
            ax.plot(x_line, p(x_line), "--", color=COLORS["accent"], alpha=0.7,
                    label=f"Trend: y={z[0]:.1f}x+{z[1]:.1f}")
            ax.legend()

        ax.set_xlabel("Sleep Hours")
        ax.set_ylabel("Productivity Score")
        ax.grid(True)
        fig.tight_layout()
        return self._fig_to_bytes(fig)

    # ── Activity Breakdown ──────────────────────────────────────────────────

    def activity_chart(self, records: list[DailyRecord]) -> bytes:
        days = [r for r in records if not r.is_weekly_summary]
        if not days:
            return self._empty_chart("No data")

        counter: Counter[str] = Counter()
        for r in days:
            for a in r.activities:
                if a.upper() != "MARK":
                    counter[a] += 1

        top = counter.most_common(10)
        if not top:
            return self._empty_chart("No activities found")

        labels = [t[0] for t in top]
        values = [t[1] for t in top]

        fig, ax = plt.subplots(figsize=(10, 6))
        fig.suptitle("Activity Frequency", fontsize=14, fontweight="bold")

        bars = ax.barh(labels[::-1], values[::-1], color=COLORS["primary"], alpha=0.8)
        ax.set_xlabel("Days")
        ax.grid(True, axis="x")

        for bar, val in zip(bars, values[::-1]):
            ax.text(bar.get_width() + 0.3, bar.get_y() + bar.get_height() / 2,
                    str(val), va="center", fontsize=9, color=COLORS["text"])

        fig.tight_layout()
        return self._fig_to_bytes(fig)

    # ── Habit Heatmap (GitHub-style) ─────────────────────────────────────────

    def habit_heatmap(
        self,
        records: list[DailyRecord],
        habit_name: str,
        months: int = 3,
    ) -> bytes:
        if not habit_name or not habit_name.strip():
            return self._empty_chart("Habit name required")

        today = date.today()
        start = today - timedelta(days=months * 31)
        start = start.replace(day=1)
        start_monday = start - timedelta(days=start.weekday())

        by_date: dict[date, DailyRecord] = {}
        for r in records:
            if r.is_weekly_summary:
                continue
            by_date[r.entry_date] = r

        n_weeks = max((today - start_monday).days // 7 + 1, 1)
        cell_size = 0.9
        gap = 0.05

        fig, ax = plt.subplots(figsize=(max(6, n_weeks * 0.5), 2.5))
        ax.set_facecolor(COLORS["bg"])
        fig.suptitle(f"Habit: {habit_name.strip()}", fontsize=14, fontweight="bold")

        # Rows: 0 = Mon .. 6 = Sun. Columns: weeks from start_monday.
        for row in range(7):
            for col in range(n_weeks):
                day_d = start_monday + timedelta(days=col * 7 + row)
                if day_d > today or day_d < start:
                    continue
                x = col
                y = row
                rec = by_date.get(day_d)
                if rec is None:
                    color = "#45475a"
                elif self._habit_present(rec, habit_name):
                    color = COLORS["success"]
                else:
                    color = COLORS["grid"]
                rect = plt.Rectangle(
                    (x * (cell_size + gap), y * (cell_size + gap)),
                    cell_size,
                    cell_size,
                    facecolor=color,
                    edgecolor=COLORS["bg"],
                    linewidth=0,
                )
                ax.add_patch(rect)

        ax.set_xlim(-0.5, n_weeks * (cell_size + gap) + 0.1)
        ax.set_ylim(-0.5, 7 * (cell_size + gap) + 0.1)
        ax.set_aspect("equal")
        ax.set_yticks([i * (cell_size + gap) + (cell_size + gap) / 2 for i in range(7)])
        ax.set_yticklabels(["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"], fontsize=8)
        ax.set_xticks([i * (cell_size + gap) + (cell_size + gap) / 2 for i in range(n_weeks)])
        ax.set_xticklabels([str(i + 1) for i in range(n_weeks)], fontsize=7)
        ax.invert_yaxis()
        ax.set_xlabel("Week")
        fig.tight_layout()
        return self._fig_to_bytes(fig)

    # ── Correlation Chart ───────────────────────────────────────────────────

    def correlation_chart(self, correlations: CorrelationMatrix) -> bytes:
        if not correlations.correlations:
            return self._empty_chart("No correlation data")

        activities = [c.activity for c in correlations.correlations]
        deltas = [c.vs_baseline for c in correlations.correlations]
        baseline = correlations.baseline_rating

        fig, ax = plt.subplots(figsize=(10, max(4, len(activities) * 0.4)))
        fig.suptitle("Activity vs Baseline Rating (Δ)", fontsize=14, fontweight="bold")

        colors_list = [COLORS["success"] if d >= 0 else COLORS["danger"] for d in deltas]
        y_pos = np.arange(len(activities))
        bars = ax.barh(y_pos, deltas, color=colors_list, alpha=0.8)
        ax.axvline(x=0, color=COLORS["text"], linestyle="--", linewidth=1.5, alpha=0.8)
        ax.set_yticks(y_pos)
        ax.set_yticklabels(activities)
        ax.set_xlabel("Δ from baseline (avg rating)")
        ax.grid(True, axis="x")

        for bar, d in zip(bars, deltas):
            off = 0.02 if d >= 0 else -0.02
            ax.text(d + off, bar.get_y() + bar.get_height() / 2,
                    f"{d:+.2f}", va="center", ha="left" if d >= 0 else "right",
                    fontsize=9, color=COLORS["text"])

        fig.tight_layout()
        return self._fig_to_bytes(fig)

    # ── Report Card ─────────────────────────────────────────────────────────

    def _grade_from_avg_score(self, avg: float) -> tuple[str, str]:
        if avg >= 80:
            return "A", COLORS["success"]
        if avg >= 65:
            return "B", COLORS["secondary"]
        if avg >= 50:
            return "C", COLORS["accent"]
        if avg >= 35:
            return "D", "#f97316"
        return "F", COLORS["danger"]

    def report_card(
        self,
        records: list[DailyRecord],
        month_label: str,
        streaks: list[StreakInfo] | None = None,
    ) -> bytes:
        days = [r for r in records if not r.is_weekly_summary]
        if not days:
            return self._empty_chart(f"No data for {month_label}")

        days_sorted = sorted(days, key=lambda r: r.entry_date)
        scores = [r.productivity_score for r in days_sorted]
        avg_score = float(np.mean(scores))
        grade, grade_color = self._grade_from_avg_score(avg_score)

        ratings_num = [r.rating.score for r in days_sorted if r.rating]
        avg_rating = float(np.mean(ratings_num)) if ratings_num else 0.0
        sleep_vals = [r.sleep.sleep_hours for r in days_sorted if r.sleep.sleep_hours]
        avg_sleep = float(np.mean(sleep_vals)) if sleep_vals else 0.0
        workout_days = sum(1 for r in days_sorted if r.had_workout)
        coding_days = sum(1 for r in days_sorted if r.had_coding)
        n = len(days_sorted)
        workout_rate = (workout_days / n * 100) if n else 0
        coding_rate = (coding_days / n * 100) if n else 0

        best_idx = int(np.argmax(scores))
        worst_idx = int(np.argmin(scores))
        best_day = days_sorted[best_idx]
        worst_day = days_sorted[worst_idx]
        best_str = best_day.entry_date.strftime("%d.%m") if best_day else "—"
        worst_str = worst_day.entry_date.strftime("%d.%m") if worst_day else "—"

        fig = plt.figure(figsize=(10, 14))
        fig.suptitle(f"Monthly Report Card — {month_label}", fontsize=16, fontweight="bold", y=0.98)

        # Big letter grade
        ax_grade = fig.add_axes([0.35, 0.82, 0.3, 0.12])
        ax_grade.set_facecolor(COLORS["bg"])
        ax_grade.text(0.5, 0.5, grade, fontsize=72, fontweight="bold", ha="center", va="center", color=grade_color)
        ax_grade.set_xlim(0, 1)
        ax_grade.set_ylim(0, 1)
        ax_grade.axis("off")

        # Metrics grid
        metrics_text = (
            f"Total days: {n}\n"
            f"Avg rating: {avg_rating:.1f}/6\n"
            f"Avg sleep: {avg_sleep:.1f}h\n"
            f"Workout rate: {workout_rate:.0f}%\n"
            f"Coding rate: {coding_rate:.0f}%\n"
            f"Best day: {best_str} ({scores[best_idx]:.1f})\n"
            f"Worst day: {worst_str} ({scores[worst_idx]:.1f})\n"
        )
        if streaks:
            for s in streaks[:5]:
                metrics_text += f"{s.emoji} {s.name}: current {s.current}, record {s.record}\n"
        else:
            metrics_text += "Streaks: —\n"

        ax_meta = fig.add_axes([0.1, 0.45, 0.8, 0.32])
        ax_meta.set_facecolor(COLORS["bg"])
        ax_meta.text(0.05, 0.95, metrics_text, transform=ax_meta.transAxes,
                     fontsize=11, va="top", fontfamily="monospace", color=COLORS["text"])
        ax_meta.set_xlim(0, 1)
        ax_meta.set_ylim(0, 1)
        ax_meta.axis("off")

        # Mini sparkline: rating trend
        ax_spark = fig.add_axes([0.1, 0.08, 0.8, 0.28])
        ax_spark.set_facecolor(COLORS["bg"])
        x = np.arange(len(scores))
        ax_spark.fill_between(x, scores, alpha=0.3, color=COLORS["primary"])
        ax_spark.plot(x, scores, color=COLORS["primary"], linewidth=2)
        ax_spark.axhline(y=avg_score, color=COLORS["accent"], linestyle="--", alpha=0.7)
        ax_spark.set_ylabel("Productivity")
        ax_spark.set_ylim(0, 100)
        ax_spark.grid(True, alpha=0.3)
        if len(x) > 10:
            step = max(1, len(x) // 8)
            ax_spark.set_xticks(x[::step])
            ax_spark.set_xticklabels([days_sorted[i].entry_date.strftime("%d.%m") for i in range(0, len(x), step)])
        else:
            ax_spark.set_xticks(x)
            ax_spark.set_xticklabels([d.entry_date.strftime("%d.%m") for d in days_sorted])
        fig.tight_layout(rect=[0, 0, 1, 0.96])
        return self._fig_to_bytes(fig)

    # ── Compare Chart (month A vs month B) ───────────────────────────────────

    def compare_chart(self, comparison: MonthComparison) -> bytes:
        if not comparison.deltas:
            return self._empty_chart("No comparison data")

        names = [d.name for d in comparison.deltas]
        vals_a = [d.value_a for d in comparison.deltas]
        vals_b = [d.value_b for d in comparison.deltas]
        deltas = [d.delta for d in comparison.deltas]

        n = len(names)
        fig, ax = plt.subplots(figsize=(10, max(4, n * 0.5)))
        fig.suptitle(f"{comparison.month_a}  vs  {comparison.month_b}", fontsize=14, fontweight="bold")

        y = np.arange(n)
        w = 0.35
        ax.barh(y - w / 2, vals_a, w, label=comparison.month_a, color=COLORS["primary"], alpha=0.8)
        ax.barh(y + w / 2, vals_b, w, label=comparison.month_b, color=COLORS["secondary"], alpha=0.8)

        for i, (va, vb, d) in enumerate(zip(vals_a, vals_b, deltas)):
            arrow_color = COLORS["success"] if d > 0 else COLORS["danger"] if d < 0 else COLORS["grid"]
            arrow = "↑" if d > 0 else "↓" if d < 0 else "→"
            max_x = max(va, vb)
            ax.text(max_x + 0.5, i, f" {arrow} {d:+.2f}", va="center", fontsize=9, color=arrow_color)

        ax.set_yticks(y)
        ax.set_yticklabels(names)
        ax.legend(loc="lower right")
        ax.grid(True, axis="x")
        fig.tight_layout()
        return self._fig_to_bytes(fig)

    # ── Life Score Dashboard ─────────────────────────────────────────────────

    def dashboard_chart(self, life_score: LifeScore) -> bytes:
        if not life_score.dimensions:
            return self._empty_chart("No data for dashboard")

        fig = plt.figure(figsize=(10, 8))
        fig.suptitle("LIFE SCORE DASHBOARD", fontsize=18, fontweight="bold")

        # Big score in center
        ax_score = fig.add_axes([0.3, 0.72, 0.4, 0.2])
        ax_score.set_facecolor(COLORS["bg"])
        trend_str = f"({'↑' if life_score.trend_delta > 0 else '↓' if life_score.trend_delta < 0 else '→'} {life_score.trend_delta:+.1f})"
        score_color = COLORS["success"] if life_score.total >= 70 else COLORS["accent"] if life_score.total >= 50 else COLORS["danger"]
        ax_score.text(0.5, 0.6, f"{life_score.total:.0f}/100", fontsize=48, fontweight="bold",
                      ha="center", va="center", color=score_color)
        ax_score.text(0.5, 0.15, trend_str, fontsize=16, ha="center", va="center",
                      color=COLORS["success"] if life_score.trend_delta > 0 else COLORS["danger"] if life_score.trend_delta < 0 else COLORS["text"])
        ax_score.set_xlim(0, 1)
        ax_score.set_ylim(0, 1)
        ax_score.axis("off")

        # Dimension bars
        ax_dims = fig.add_axes([0.1, 0.08, 0.8, 0.58])
        ax_dims.set_facecolor(COLORS["bg"])

        dims = life_score.dimensions
        n = len(dims)
        y_pos = np.arange(n)
        scores = [d.score for d in dims]
        bar_colors = [COLORS["success"] if s >= 70 else COLORS["accent"] if s >= 50 else COLORS["danger"] for s in scores]

        bars = ax_dims.barh(y_pos, scores, color=bar_colors, alpha=0.8, height=0.6)
        ax_dims.set_yticks(y_pos)
        ax_dims.set_yticklabels([f"{d.emoji} {d.name}" for d in dims], fontsize=11)
        ax_dims.set_xlim(0, 110)
        ax_dims.invert_yaxis()

        for i, (bar, dim) in enumerate(zip(bars, dims)):
            ax_dims.text(bar.get_width() + 1, bar.get_y() + bar.get_height() / 2,
                         f" {dim.score:.0f}% {dim.trend}", va="center", fontsize=10, color=COLORS["text"])

        ax_dims.axvline(x=50, color=COLORS["grid"], linestyle="--", alpha=0.5)
        ax_dims.grid(True, axis="x", alpha=0.2)
        ax_dims.set_xlabel("Score (%)")

        fig.tight_layout(rect=[0, 0, 1, 0.95])
        return self._fig_to_bytes(fig)

    # ── Anomaly Chart ────────────────────────────────────────────────────────

    def anomaly_chart(self, records: list[DailyRecord], anomalies: list[Anomaly]) -> bytes:
        days = sorted([r for r in records if not r.is_weekly_summary], key=lambda r: r.entry_date)
        if not days:
            return self._empty_chart("No data")

        dates = [r.entry_date for r in days]
        scores = [r.productivity_score for r in days]
        avg = float(np.mean(scores))
        stdev = float(np.std(scores)) if len(scores) > 1 else 10

        fig, ax = plt.subplots(figsize=(12, 6))
        fig.suptitle("Anomaly Detection", fontsize=14, fontweight="bold")

        ax.fill_between(dates, scores, alpha=0.2, color=COLORS["primary"])
        ax.plot(dates, scores, color=COLORS["primary"], linewidth=1.5, alpha=0.7)

        # Highlight bands
        ax.axhline(y=avg, color=COLORS["accent"], linestyle="--", alpha=0.7, label=f"Avg: {avg:.1f}")
        ax.axhspan(avg + stdev * 1.5, 100, alpha=0.05, color=COLORS["success"])
        ax.axhspan(0, avg - stdev * 1.5, alpha=0.05, color=COLORS["danger"])

        # Mark anomalies
        anomaly_dates = {a.entry_date for a in anomalies}
        for r in days:
            if r.entry_date in anomaly_dates:
                color = COLORS["success"] if r.productivity_score > avg else COLORS["danger"]
                ax.scatter([r.entry_date], [r.productivity_score], color=color, s=100,
                           zorder=5, edgecolors="white", linewidths=1.5)
                ax.annotate(r.entry_date.strftime("%d.%m"), (r.entry_date, r.productivity_score),
                            textcoords="offset points", xytext=(0, 12), ha="center",
                            fontsize=8, color=color)

        ax.set_ylabel("Productivity Score")
        ax.set_ylim(0, 100)
        ax.legend()
        ax.grid(True, alpha=0.3)
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%d.%m"))
        fig.autofmt_xdate()
        fig.tight_layout()
        return self._fig_to_bytes(fig)
