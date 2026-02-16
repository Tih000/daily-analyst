"""Chart generation service using Matplotlib for DailyRecord data."""

from __future__ import annotations

import io
import logging
from collections import Counter, defaultdict

import matplotlib
matplotlib.use("Agg")

import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import numpy as np

from src.models.journal_entry import DailyRecord, DayRating, TestikStatus

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


class ChartsService:
    """Generate inline chart images for Telegram."""

    @staticmethod
    def _fig_to_bytes(fig: plt.Figure) -> bytes:
        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=150, bbox_inches="tight", pad_inches=0.3)
        plt.close(fig)
        buf.seek(0)
        return buf.read()

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

        # Panel 1: Productivity score
        ax1 = axes[0]
        ax1.fill_between(dates, scores, alpha=0.3, color=COLORS["primary"])
        ax1.plot(dates, scores, color=COLORS["primary"], linewidth=2, marker="o", markersize=4)
        ax1.set_ylabel("Productivity Score")
        ax1.set_ylim(0, 100)
        ax1.grid(True)
        avg = np.mean(scores)
        ax1.axhline(y=avg, color=COLORS["accent"], linestyle="--", alpha=0.7, label=f"Avg: {avg:.1f}")
        ax1.legend(loc="upper right")

        # Panel 2: Day rating
        ax2 = axes[1]
        colors = [RATING_COLORS.get(r.rating, COLORS["grid"]) for r in days]
        ax2.bar(dates, ratings, color=colors, alpha=0.8, width=0.8)
        ax2.set_ylabel("Day Rating (1-6)")
        ax2.set_ylim(0, 7)
        ax2.grid(True, axis="y")

        # Panel 3: Sleep + total hours
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
        colors = [COLORS["primary"], COLORS["secondary"], COLORS["accent"]]
        for i, (label, vals) in enumerate(metrics.items()):
            ax.bar(x + i * w, vals, w, label=label, color=colors[i], alpha=0.8)

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
        colors = [RATING_COLORS.get(r.rating, COLORS["grid"]) for r in days]

        fig, ax = plt.subplots(figsize=(10, 6))
        fig.suptitle("Sleep vs Productivity", fontsize=14, fontweight="bold")

        ax.scatter(sleep, scores, c=colors, s=60, alpha=0.7, edgecolors="white", linewidths=0.5)

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

    # ── Helper ──────────────────────────────────────────────────────────────

    def _empty_chart(self, message: str) -> bytes:
        fig, ax = plt.subplots(figsize=(8, 4))
        ax.text(0.5, 0.5, message, ha="center", va="center", fontsize=14, color=COLORS["text"])
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.axis("off")
        return self._fig_to_bytes(fig)
