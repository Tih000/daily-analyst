"""Chart generation service using Matplotlib (+ optional Google Sheets)."""

from __future__ import annotations

import io
import logging
from collections import defaultdict
from datetime import date
from typing import Optional

import matplotlib
matplotlib.use("Agg")  # Non-interactive backend for server

import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import numpy as np

from src.models.journal_entry import JournalEntry, Mood, Testik

logger = logging.getLogger(__name__)

# ── Style constants ─────────────────────────────────────────────────────────

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

MOOD_COLORS = {
    Mood.PERFECT: "#10b981",
    Mood.GOOD: "#22d3ee",
    Mood.NORMAL: "#f59e0b",
    Mood.BAD: "#f97316",
    Mood.VERY_BAD: "#ef4444",
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
    """Generate inline chart images for Telegram messages."""

    @staticmethod
    def _fig_to_bytes(fig: plt.Figure) -> bytes:
        """Convert matplotlib Figure to PNG bytes."""
        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=150, bbox_inches="tight", pad_inches=0.3)
        plt.close(fig)
        buf.seek(0)
        return buf.read()

    # ── Monthly Overview Chart ──────────────────────────────────────────────

    def monthly_overview(self, entries: list[JournalEntry], month_label: str) -> bytes:
        """
        Multi-panel monthly overview chart:
        - Productivity score line
        - Mood bar chart
        - Sleep & work hours dual axis
        """
        if not entries:
            return self._empty_chart("Нет данных за " + month_label)

        entries = sorted(entries, key=lambda e: e.entry_date)
        dates = [e.entry_date for e in entries]
        prod_scores = [e.productivity_score for e in entries]
        mood_scores = [e.mood.score if e.mood else 3 for e in entries]
        sleep_hours = [e.sleep_hours for e in entries]
        work_hours = [e.hours_worked for e in entries]

        fig, axes = plt.subplots(3, 1, figsize=(12, 10), sharex=True)
        fig.suptitle(f"📊 Обзор: {month_label}", fontsize=16, fontweight="bold")

        # Panel 1: Productivity
        ax1 = axes[0]
        ax1.fill_between(dates, prod_scores, alpha=0.3, color=COLORS["primary"])
        ax1.plot(dates, prod_scores, color=COLORS["primary"], linewidth=2, marker="o", markersize=4)
        ax1.set_ylabel("Продуктивность")
        ax1.set_ylim(0, 100)
        ax1.grid(True)
        avg_prod = np.mean(prod_scores)
        ax1.axhline(y=avg_prod, color=COLORS["accent"], linestyle="--", alpha=0.7, label=f"Avg: {avg_prod:.1f}")
        ax1.legend(loc="upper right")

        # Panel 2: Mood
        ax2 = axes[1]
        mood_colors = [MOOD_COLORS.get(e.mood, COLORS["grid"]) for e in entries]
        ax2.bar(dates, mood_scores, color=mood_colors, alpha=0.8, width=0.8)
        ax2.set_ylabel("Настроение (1-5)")
        ax2.set_ylim(0, 6)
        ax2.grid(True, axis="y")

        # Panel 3: Sleep & Work hours
        ax3 = axes[2]
        width = 0.35
        x = np.arange(len(dates))
        ax3.bar(x - width / 2, sleep_hours, width, label="Сон", color=COLORS["secondary"], alpha=0.8)
        ax3.bar(x + width / 2, work_hours, width, label="Работа", color=COLORS["accent"], alpha=0.8)
        ax3.set_ylabel("Часы")
        ax3.set_xticks(x[::max(1, len(x) // 10)])
        ax3.set_xticklabels([d.strftime("%d") for d in dates][::max(1, len(x) // 10)], rotation=45)
        ax3.legend(loc="upper right")
        ax3.grid(True, axis="y")

        fig.tight_layout()
        return self._fig_to_bytes(fig)

    # ── Burnout Risk Chart ──────────────────────────────────────────────────

    def burnout_chart(self, entries: list[JournalEntry]) -> bytes:
        """Burnout risk indicators over time."""
        if len(entries) < 3:
            return self._empty_chart("Нужно минимум 3 записи")

        entries = sorted(entries, key=lambda e: e.entry_date)
        dates = [e.entry_date for e in entries]

        # Calculate rolling risk score (3-day window)
        risk_scores: list[float] = []
        for i in range(len(entries)):
            window = entries[max(0, i - 2): i + 1]
            risk = 0.0
            avg_sleep = np.mean([e.sleep_hours for e in window])
            if avg_sleep < 6:
                risk += 35
            elif avg_sleep < 7:
                risk += 15
            minus_count = sum(
                1 for e in window
                if e.testik in (Testik.MINUS_KATE, Testik.MINUS_SOLO)
            )
            risk += minus_count * 15
            moods = [e.mood.score for e in window if e.mood]
            if moods and np.mean(moods) < 2.5:
                risk += 20
            if np.mean([e.hours_worked for e in window]) > 10:
                risk += 15
            risk_scores.append(min(risk, 100))

        fig, ax = plt.subplots(figsize=(12, 5))
        fig.suptitle("🔥 Индекс риска выгорания", fontsize=14, fontweight="bold")

        # Color zones
        ax.axhspan(0, 20, alpha=0.1, color=COLORS["success"])
        ax.axhspan(20, 45, alpha=0.1, color=COLORS["accent"])
        ax.axhspan(45, 70, alpha=0.1, color="#f97316")
        ax.axhspan(70, 100, alpha=0.1, color=COLORS["danger"])

        ax.fill_between(dates, risk_scores, alpha=0.3, color=COLORS["danger"])
        ax.plot(dates, risk_scores, color=COLORS["danger"], linewidth=2, marker="o", markersize=3)

        ax.set_ylabel("Риск выгорания (%)")
        ax.set_ylim(0, 100)
        ax.grid(True)

        # Zone labels
        ax.text(dates[0], 10, "Низкий", fontsize=8, color=COLORS["success"], alpha=0.7)
        ax.text(dates[0], 32, "Средний", fontsize=8, color=COLORS["accent"], alpha=0.7)
        ax.text(dates[0], 57, "Высокий", fontsize=8, color="#f97316", alpha=0.7)
        ax.text(dates[0], 85, "Критичный", fontsize=8, color=COLORS["danger"], alpha=0.7)

        ax.xaxis.set_major_formatter(mdates.DateFormatter("%d.%m"))
        fig.autofmt_xdate()
        fig.tight_layout()
        return self._fig_to_bytes(fig)

    # ── TESTIK Impact Chart ─────────────────────────────────────────────────

    def testik_chart(self, entries: list[JournalEntry]) -> bytes:
        """Bar chart comparing metrics across TESTIK categories."""
        groups: dict[str, list[JournalEntry]] = defaultdict(list)
        for e in entries:
            key = e.testik.value if e.testik else "N/A"
            groups[key].append(e)

        if len(groups) < 2:
            return self._empty_chart("Недостаточно разнообразных TESTIK данных")

        categories = list(groups.keys())
        metrics = {
            "Продуктивность": [np.mean([e.productivity_score for e in groups[c]]) for c in categories],
            "Настроение": [np.mean([e.mood.score for e in groups[c] if e.mood]) * 20 if any(e.mood for e in groups[c]) else 0 for c in categories],
            "Сон (ч)": [np.mean([e.sleep_hours for e in groups[c]]) * 10 for c in categories],
        }

        fig, ax = plt.subplots(figsize=(10, 6))
        fig.suptitle("🧪 Влияние TESTIK на метрики", fontsize=14, fontweight="bold")

        x = np.arange(len(categories))
        width = 0.25
        colors = [COLORS["primary"], COLORS["secondary"], COLORS["accent"]]

        for i, (label, values) in enumerate(metrics.items()):
            ax.bar(x + i * width, values, width, label=label, color=colors[i], alpha=0.8)

        ax.set_xticks(x + width)
        ax.set_xticklabels(categories)
        ax.legend()
        ax.grid(True, axis="y")

        fig.tight_layout()
        return self._fig_to_bytes(fig)

    # ── Sleep vs Productivity ───────────────────────────────────────────────

    def sleep_chart(self, entries: list[JournalEntry]) -> bytes:
        """Scatter plot: sleep hours vs productivity score."""
        if not entries:
            return self._empty_chart("Нет данных")

        sleep = [e.sleep_hours for e in entries]
        prod = [e.productivity_score for e in entries]
        moods = [e.mood for e in entries]

        fig, ax = plt.subplots(figsize=(10, 6))
        fig.suptitle("😴 Сон vs Продуктивность", fontsize=14, fontweight="bold")

        colors = [MOOD_COLORS.get(m, COLORS["grid"]) for m in moods]
        ax.scatter(sleep, prod, c=colors, s=60, alpha=0.7, edgecolors="white", linewidths=0.5)

        # Trend line
        if len(sleep) > 2:
            z = np.polyfit(sleep, prod, 1)
            p = np.poly1d(z)
            x_line = np.linspace(min(sleep), max(sleep), 100)
            ax.plot(x_line, p(x_line), "--", color=COLORS["accent"], alpha=0.7, label=f"Тренд: y={z[0]:.1f}x+{z[1]:.1f}")
            ax.legend()

        ax.set_xlabel("Часы сна")
        ax.set_ylabel("Продуктивность")
        ax.grid(True)

        fig.tight_layout()
        return self._fig_to_bytes(fig)

    # ── Earnings Chart ──────────────────────────────────────────────────────

    def earnings_chart(self, entries: list[JournalEntry]) -> bytes:
        """Cumulative earnings chart with daily bars."""
        earning_entries = [e for e in entries if e.earnings_usd > 0]
        if not earning_entries:
            return self._empty_chart("Нет данных о заработке")

        entries_sorted = sorted(entries, key=lambda e: e.entry_date)
        dates = [e.entry_date for e in entries_sorted]
        daily = [e.earnings_usd for e in entries_sorted]
        cumulative = np.cumsum(daily)

        fig, ax1 = plt.subplots(figsize=(12, 6))
        fig.suptitle("💰 Заработок", fontsize=14, fontweight="bold")

        ax1.bar(dates, daily, color=COLORS["success"], alpha=0.6, label="Ежедневно")
        ax1.set_ylabel("$ / день")
        ax1.set_xlabel("")

        ax2 = ax1.twinx()
        ax2.plot(dates, cumulative, color=COLORS["accent"], linewidth=2, marker="o", markersize=3, label="Накопительно")
        ax2.set_ylabel("$ всего")

        lines1, labels1 = ax1.get_legend_handles_labels()
        lines2, labels2 = ax2.get_legend_handles_labels()
        ax1.legend(lines1 + lines2, labels1 + labels2, loc="upper left")

        ax1.xaxis.set_major_formatter(mdates.DateFormatter("%d.%m"))
        fig.autofmt_xdate()
        ax1.grid(True, axis="y")

        fig.tight_layout()
        return self._fig_to_bytes(fig)

    # ── Helper ──────────────────────────────────────────────────────────────

    def _empty_chart(self, message: str) -> bytes:
        """Generate a placeholder chart with a message."""
        fig, ax = plt.subplots(figsize=(8, 4))
        ax.text(0.5, 0.5, message, ha="center", va="center", fontsize=14, color=COLORS["text"])
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.axis("off")
        return self._fig_to_bytes(fig)
