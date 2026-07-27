#!/usr/bin/env python3
"""Daily revenue reports from Yandex Disk Excel -> Telegram (owner DM).

Fetches live workbooks each run (no local cache of source files).
Krasnoyarsk: 3 messages (Дубров / Новосиб / Весны).
Moscow: 1 message (Фили).
"""

from __future__ import annotations

import argparse
import calendar
import json
import os
import re
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterable
from zoneinfo import ZoneInfo

from openpyxl import load_workbook

from telegram_notify import tg_send_message

MSK = ZoneInfo("Europe/Moscow")

MONTH_ALIASES: dict[int, tuple[str, ...]] = {
    1: ("январ",),
    2: ("феврал",),
    3: ("март",),
    4: ("апрел",),
    5: ("май", "мая"),
    6: ("июн",),
    7: ("июл",),
    8: ("август",),
    9: ("сентябр",),
    10: ("октябр",),
    11: ("ноябр",),
    12: ("декабр",),
}

# (plan_col, fact_col, pct_col, label)
KRAS_BRANCHES = (
    (2, 3, 4, "Дубровинского"),
    (6, 7, 8, "Новосибирская"),
    (10, 11, 12, "Весны"),
)
MSK_BRANCH = (2, 3, 4, "Фили")


@dataclass
class DayRow:
    day: date
    plan: float | None
    fact: float | None


@dataclass
class MonthSheet:
    year: int
    month: int
    title: str
    days: list[DayRow]
    month_plan: float | None
    month_fact: float | None
    month_pct: float | None


@dataclass
class Forecast:
    mtd: float
    month_plan: float | None
    plan_pct: float | None
    avg_daily: float
    remaining_days: int
    pace_tail: float
    hist_tails: list[float]
    avg_tail: float
    forecast_total: float
    will_hit_plan: bool | None


def load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        key, val = key.strip(), val.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = val


def _num(v) -> float | None:
    if v is None or v == "" or v == " ":
        return None
    if isinstance(v, str) and v.strip().startswith("#"):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _as_date(v) -> date | None:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    return None


def download_yadisk_public(public_url: str, dest: Path, *, timeout: int = 120) -> None:
    api = (
        "https://cloud-api.yandex.net/v1/disk/public/resources/download"
        f"?public_key={urllib.parse.quote(public_url, safe='')}"
    )
    with urllib.request.urlopen(api, timeout=timeout) as resp:
        meta = json.loads(resp.read().decode("utf-8"))
    href = meta.get("href")
    if not href:
        raise RuntimeError(f"YaDisk: no download href for {public_url}: {meta}")
    with urllib.request.urlopen(href, timeout=timeout) as resp:
        dest.write_bytes(resp.read())


def _normalize_sheet_name(name: str) -> str:
    return re.sub(r"\s+", " ", name.strip().lower().replace("ь", ""))


def parse_sheet_year_month(title: str) -> tuple[int, int] | None:
    """Parse 'ИЮЛЬ26', 'июль 2025', 'Июль 2026' -> (year, month)."""
    raw = _normalize_sheet_name(title)
    if "эффективн" in raw:
        return None
    year: int | None = None
    m = re.search(r"(20\d{2})", raw)
    if m:
        year = int(m.group(1))
    else:
        m2 = re.search(r"(?<!\d)(\d{2})(?!\d)", raw)
        if m2:
            yy = int(m2.group(1))
            year = 2000 + yy if yy < 80 else 1900 + yy
    month: int | None = None
    for num, aliases in MONTH_ALIASES.items():
        if any(a in raw for a in aliases):
            month = num
            break
    if year is None or month is None:
        return None
    return year, month


def _is_summary_row(ws, r: int, plan_col: int, fact_col: int) -> bool:
    """Bottom total row or duplicate summary with a date."""
    day = _as_date(ws.cell(r, 1).value)
    plan = _num(ws.cell(r, plan_col).value)
    fact = _num(ws.cell(r, fact_col).value)
    if day is None:
        # no date + monthly-scale plan = итоговая строка
        return plan is not None and plan >= 50_000
    if plan is not None and plan >= 200_000:
        return True
    if fact is not None and fact >= 400_000:
        return True
    return False


def _find_bottom_summary(
    ws, plan_col: int, fact_col: int
) -> tuple[float | None, float | None, int | None]:
    """Итог внизу: строка без даты в колонке A."""
    for r in range(ws.max_row or 1, 1, -1):
        if _as_date(ws.cell(r, 1).value) is not None:
            continue
        plan = _num(ws.cell(r, plan_col).value)
        fact = _num(ws.cell(r, fact_col).value)
        if plan is not None:
            return plan, fact, r
    return None, None, None


def _pct_matches(plan: float | None, fact: float | None, pct_raw) -> bool:
    pct = _num(pct_raw)
    if pct is None or plan is None or fact is None or plan == 0:
        return True
    expected = fact / plan
    return abs(pct - expected) < 0.05


def _score_columns(ws, year: int, month: int, plan_col: int, fact_col: int, pct_col: int) -> int:
    """Higher = more likely correct branch columns (pct ≈ fact/plan, plans non-decreasing)."""
    score = 0
    prev_plan: float | None = None
    for r in range(2, min((ws.max_row or 1) + 1, 36)):
        if _is_summary_row(ws, r, plan_col, fact_col):
            continue
        d = _as_date(ws.cell(r, 1).value)
        if d is None:
            continue
        plan = _num(ws.cell(r, plan_col).value)
        fact = _num(ws.cell(r, fact_col).value)
        pct_raw = ws.cell(r, pct_col).value
        if plan is None and fact is None:
            continue
        if plan is not None and prev_plan is not None:
            if plan >= prev_plan:
                score += 2
            else:
                score -= 5
        if plan is not None:
            prev_plan = plan
        if _pct_matches(plan, fact, pct_raw):
            score += 3
        if plan is not None and 5_000 <= plan <= 200_000:
            score += 1
        if fact is not None and fact > 0:
            score += 1
    return score


def _resolve_columns(
    ws,
    year: int,
    month: int,
    plan_col: int,
    fact_col: int,
    pct_col: int,
    label: str,
) -> tuple[int, int, int, list[str]]:
    warnings: list[str] = []
    candidates = [(plan_col, fact_col, pct_col)]
    for delta in (-1, 1):
        pc, fc, cc = plan_col + delta, fact_col + delta, pct_col + delta
        if pc >= 2 and cc <= (ws.max_column or 1):
            candidates.append((pc, fc, cc))

    best = max(candidates, key=lambda c: _score_columns(ws, year, month, *c))
    if best != (plan_col, fact_col, pct_col):
        warnings.append(
            f"{label}: колонки сдвинуты {plan_col}/{fact_col} → {best[0]}/{best[1]} (проверка % и роста плана)"
        )
    return best[0], best[1], best[2], warnings


def _read_daily_rows(
    ws,
    year: int,
    month: int,
    plan_col: int,
    fact_col: int,
    label: str,
    *,
    warn: bool,
) -> tuple[list[DayRow], list[str]]:
    days: list[DayRow] = []
    warnings: list[str] = []
    prev_day: int | None = None
    cum_plan = 0.0
    prev_cum = 0.0

    for r in range(2, (ws.max_row or 1) + 1):
        if _is_summary_row(ws, r, plan_col, fact_col):
            continue
        d = _as_date(ws.cell(r, 1).value)
        if d is None:
            continue
        try:
            d = date(year, month, d.day)
        except ValueError:
            if warn:
                warnings.append(f"{label}: некорректная дата в строке {r}")
            continue

        if prev_day is not None and d.day < prev_day and warn:
            warnings.append(f"{label}: дата {d.day} раньше предыдущей ({prev_day}), строка {r}")

        plan = _num(ws.cell(r, plan_col).value)
        fact = _num(ws.cell(r, fact_col).value)

        if plan is not None:
            cum_plan += plan
            if warn and cum_plan < prev_cum:
                warnings.append(f"{label}: накопительный план уменьшился на {d:%d.%m}")
            prev_cum = cum_plan
            # дневной план не должен быть похож на месячный итог (ошибка колонки)
            if warn and plan >= 500_000:
                warnings.append(
                    f"{label}: подозрительно большой дневной план {int(plan)} на {d:%d.%m} (стр. {r})"
                )

        prev_day = d.day
        days.append(DayRow(day=d, plan=plan, fact=fact))

    return days, warnings


def read_branch_month(
    ws,
    year: int,
    month: int,
    title: str,
    plan_col: int,
    fact_col: int,
    pct_col: int,
    label: str = "",
    *,
    warn: bool = False,
) -> MonthSheet:
    branch = label or f"col{plan_col}"
    plan_col, fact_col, pct_col, col_warnings = _resolve_columns(
        ws, year, month, plan_col, fact_col, pct_col, branch
    )
    if not warn:
        col_warnings = []

    days, day_warnings = _read_daily_rows(ws, year, month, plan_col, fact_col, branch, warn=warn)
    warnings = col_warnings + day_warnings

    sum_plan = sum(d.plan or 0 for d in days)
    sum_fact = sum(d.fact or 0 for d in days)
    bottom_plan, bottom_fact, bottom_row = _find_bottom_summary(ws, plan_col, fact_col)

    # План месяца = сумма дневных планов (основной источник)
    month_plan = sum_plan if sum_plan > 0 else bottom_plan

    if bottom_plan is not None and sum_plan > 0:
        tol = max(100.0, sum_plan * 0.001)
        if abs(bottom_plan - sum_plan) > tol:
            warnings.append(
                f"{branch}: итог внизу (стр. {bottom_row}) план {int(bottom_plan)} "
                f"≠ сумма дней {int(sum_plan)} — берём сумму дней"
            )
            month_plan = sum_plan
        elif month_plan is None:
            month_plan = bottom_plan

    # Факт месяца: итог внизу, если сходится с суммой дней
    if bottom_fact is not None and sum_fact > 0:
        tol = max(500.0, sum_fact * 0.02)
        if abs(bottom_fact - sum_fact) <= tol:
            month_fact = bottom_fact
        else:
            month_fact = sum_fact
            warnings.append(
                f"{branch}: итог внизу факт {int(bottom_fact)} "
                f"≠ сумма дней {int(sum_fact)} — берём сумму дней"
            )
    elif bottom_fact is not None:
        month_fact = bottom_fact
    else:
        month_fact = sum_fact if sum_fact > 0 else None

    month_pct = (month_fact / month_plan) if month_plan and month_fact is not None else None

    for w in warnings:
        if warn:
            print(f"[WARN] {w}")

    return MonthSheet(
        year=year,
        month=month,
        title=title,
        days=days,
        month_plan=month_plan,
        month_fact=month_fact,
        month_pct=month_pct,
    )


def load_workbook_months(
    path: Path,
    branches: Iterable[tuple[int, int, int, str]],
    *,
    warn_month: tuple[int, int] | None = None,
) -> dict[str, dict[tuple[int, int], MonthSheet]]:
    """branch_label -> {(year, month): MonthSheet}"""
    wb = load_workbook(path, data_only=True)
    out: dict[str, dict[tuple[int, int], MonthSheet]] = {label: {} for *_, label in branches}
    for title in wb.sheetnames:
        ym = parse_sheet_year_month(title)
        if ym is None:
            continue
        year, month = ym
        ws = wb[title]
        do_warn = warn_month == (year, month)
        for plan_col, fact_col, pct_col, label in branches:
            sheet = read_branch_month(
                ws,
                year,
                month,
                title,
                plan_col,
                fact_col,
                pct_col,
                label,
                warn=do_warn,
            )
            out[label].setdefault((year, month), sheet)
    return out


def _shift_month(y: int, m: int, delta: int) -> tuple[int, int]:
    idx = y * 12 + (m - 1) + delta
    return idx // 12, idx % 12 + 1


def mtd_fact(sheet: MonthSheet, as_of: date) -> float:
    total = 0.0
    for row in sheet.days:
        if row.day.day <= as_of.day and row.fact is not None:
            total += row.fact
    return total


def fact_on_days(sheet: MonthSheet, from_day: int, to_day: int) -> float:
    total = 0.0
    for row in sheet.days:
        if from_day <= row.day.day <= to_day and row.fact is not None:
            total += row.fact
    return total


def days_with_fact(sheet: MonthSheet, as_of: date) -> int:
    return sum(1 for row in sheet.days if row.day.day <= as_of.day and row.fact is not None)


def build_forecast(current: MonthSheet, hist: list[MonthSheet], as_of: date) -> Forecast:
    last_day = calendar.monthrange(current.year, current.month)[1]
    mtd = mtd_fact(current, as_of)
    n = days_with_fact(current, as_of)
    avg_daily = (mtd / n) if n else 0.0
    remaining = max(0, last_day - as_of.day)
    pace_tail = avg_daily * remaining

    hist_tails: list[float] = []
    for h in hist:
        h_last = calendar.monthrange(h.year, h.month)[1]
        # same remaining window: days (as_of.day+1) .. end (clipped to that month length)
        start = as_of.day + 1
        if start <= h_last:
            hist_tails.append(fact_on_days(h, start, h_last))
        else:
            hist_tails.append(0.0)

    parts = [pace_tail, *hist_tails]
    avg_tail = sum(parts) / len(parts) if parts else 0.0
    forecast_total = mtd + avg_tail

    plan = current.month_plan
    plan_pct = (mtd / plan) if plan else None
    will = None if not plan else forecast_total >= plan

    return Forecast(
        mtd=mtd,
        month_plan=plan,
        plan_pct=plan_pct,
        avg_daily=avg_daily,
        remaining_days=remaining,
        pace_tail=pace_tail,
        hist_tails=hist_tails,
        avg_tail=avg_tail,
        forecast_total=forecast_total,
        will_hit_plan=will,
    )


def b(text: str) -> str:
    return f"<b>{text}</b>"


def num(v: float | None) -> str:
    if v is None:
        return "—"
    return b(f"{int(round(v)):,}".replace(",", " "))


def pct(v: float | None) -> str:
    if v is None:
        return "—"
    return b(f"{v * 100:.0f}%")


def pct_delta(ours: float, theirs: float) -> str:
    if theirs == 0:
        return "—"
    d = (ours - theirs) / theirs * 100
    sign = "+" if d >= 0 else ""
    return b(f"{sign}{d:.0f}%")


MONTH_NAMES_RU = (
    "",
    "январь",
    "февраль",
    "март",
    "апрель",
    "май",
    "июнь",
    "июль",
    "август",
    "сентябрь",
    "октябрь",
    "ноябрь",
    "декабрь",
)

MONTH_PREP_RU = (
    "",
    "январе",
    "феврале",
    "марте",
    "апреле",
    "мае",
    "июне",
    "июле",
    "августе",
    "сентябре",
    "октябре",
    "ноябре",
    "декабре",
)


def month_title_ru(y: int, m: int) -> str:
    return f"{MONTH_NAMES_RU[m]} {y}"


def month_short_ru(y: int, m: int, *, with_year: bool = False) -> str:
    name = MONTH_NAMES_RU[m]
    return f"{name} {y}" if with_year else name


def spoiler(text: str) -> str:
    return f'<span class="tg-spoiler">{text}</span>'


def format_branch_block(
    *,
    branch: str,
    as_of: date,
    current: MonthSheet,
    fc: Forecast,
    prev1: MonthSheet | None,
    prev2: MonthSheet | None,
    yoy: MonthSheet | None,
) -> str:
    hit = fc.will_hit_plan
    if hit is True:
        verdict = "план по прогнозу выполним"
    elif hit is False:
        gap = (fc.month_plan or 0) - fc.forecast_total
        verdict = f"план под угрозой (недобор ~{num(gap)})"
    else:
        verdict = "план на месяц не указан"

    plan_fact = (
        f"План/факт: {num(fc.month_plan)} / {num(fc.mtd)} ({pct(fc.plan_pct)})"
        if fc.month_plan is not None
        else f"Факт: {num(fc.mtd)}"
    )

    hist_lines: list[str] = []
    for i, tail in enumerate(fc.hist_tails, start=1):
        _py, pm = _shift_month(current.year, current.month, -i)
        hist_lines.append(f"в {MONTH_PREP_RU[pm]} за тот же период было {num(tail)}")
    hist_lines.append(f"среднее по хвосту: {num(fc.avg_tail)}")

    compare_lines = ["Сравнение (итог / на ту же дату):"]
    if prev1 is not None:
        then_mtd = mtd_fact(prev1, as_of)
        compare_lines.append(
            f"{month_short_ru(prev1.year, prev1.month)}: "
            f"{num(prev1.month_fact)} / {num(then_mtd)} ({pct_delta(fc.mtd, then_mtd)})"
        )
    if prev2 is not None:
        then_mtd = mtd_fact(prev2, as_of)
        compare_lines.append(
            f"{month_short_ru(prev2.year, prev2.month)}: "
            f"{num(prev2.month_fact)} / {num(then_mtd)} ({pct_delta(fc.mtd, then_mtd)})"
        )
    if yoy is not None:
        then_mtd = mtd_fact(yoy, as_of)
        compare_lines.append(
            f"с прошлым годом: {num(yoy.month_fact)} / {num(then_mtd)} "
            f"({pct_delta(fc.mtd, then_mtd)})"
        )

    lines = [
        b(branch),
        plan_fact,
        "",
        "Прогноз:",
        f"по текущему темпу сделаем ещё {num(fc.pace_tail)}",
        spoiler("\n".join(hist_lines)),
        f"ожидаемая выручка за месяц: {num(fc.forecast_total)}",
        f"→ {verdict}",
        "",
        spoiler("\n".join(compare_lines)),
    ]
    return "\n".join(lines)


def format_network_total(
    *,
    city: str,
    as_of: date,
    mtd_total: float,
    yoy_mtd_total: float | None,
) -> str:
    lines = [
        "",
        b(f"Итого сеть {city}"),
        f"выручка за период: {num(mtd_total)}",
    ]
    if yoy_mtd_total is None:
        lines.append("с прошлым годом за тот же период: нет данных")
    else:
        lines.append(
            f"с прошлым годом за тот же период: {num(yoy_mtd_total)} "
            f"({pct_delta(mtd_total, yoy_mtd_total)})"
        )
    return "\n".join(lines)


def resolve_as_of(months: dict[tuple[int, int], MonthSheet], today: date) -> tuple[date, MonthSheet]:
    """Current calendar month sheet; as_of = last day with fact (not after today)."""
    key = (today.year, today.month)
    sheet = months.get(key)
    if sheet is None:
        filled = [k for k, s in months.items() if any(d.fact is not None for d in s.days)]
        if not filled:
            raise RuntimeError("No month sheets with facts found")
        key = max(filled)
        sheet = months[key]
        today = date(key[0], key[1], min(today.day, calendar.monthrange(key[0], key[1])[1]))

    facts = [d.day for d in sheet.days if d.fact is not None]
    if not facts:
        return today, sheet
    return min(max(facts), today), sheet


def build_branch_payload(
    months: dict[tuple[int, int], MonthSheet], today: date
) -> dict:
    as_of, current = resolve_as_of(months, today)
    p1 = months.get(_shift_month(current.year, current.month, -1))
    p2 = months.get(_shift_month(current.year, current.month, -2))
    yoy = months.get((current.year - 1, current.month))
    hist = [s for s in (p1, p2) if s is not None]
    fc = build_forecast(current, hist, as_of)
    yoy_mtd = mtd_fact(yoy, as_of) if yoy is not None else None
    return {
        "as_of": as_of,
        "current": current,
        "fc": fc,
        "prev1": p1,
        "prev2": p2,
        "yoy": yoy,
        "yoy_mtd": yoy_mtd,
    }


def reports_for_file(
    path: Path,
    *,
    city: str,
    branches: tuple[tuple[int, int, int, str], ...],
    today: date,
    combine: bool = False,
) -> list[str]:
    data = load_workbook_months(
        path, branches, warn_month=(today.year, today.month)
    )
    payloads: list[tuple[str, dict]] = []
    for *_, label in branches:
        payloads.append((label, build_branch_payload(data[label], today)))

    if not combine:
        messages: list[str] = []
        for label, p in payloads:
            date_line = (
                f"на {p['as_of'].strftime('%d.%m.%Y')} · "
                f"{month_title_ru(p['current'].year, p['current'].month)}"
            )
            block = format_branch_block(
                branch=f"{city} · {label}",
                as_of=p["as_of"],
                current=p["current"],
                fc=p["fc"],
                prev1=p["prev1"],
                prev2=p["prev2"],
                yoy=p["yoy"],
            )
            title, _, rest = block.partition("\n")
            messages.append(f"{title}\n{date_line}\n{rest}" if rest else f"{title}\n{date_line}")
        return messages

    # Combined city message (Krasnoyarsk)
    as_of = max(p["as_of"] for _, p in payloads)
    year = payloads[0][1]["current"].year
    month = payloads[0][1]["current"].month
    chunks = [
        b(city),
        f"на {as_of.strftime('%d.%m.%Y')} · {month_title_ru(year, month)}",
        "",
    ]
    mtd_total = 0.0
    yoy_parts: list[float] = []
    for i, (label, p) in enumerate(payloads):
        if i:
            chunks.append("")
        chunks.append(
            format_branch_block(
                branch=label,
                as_of=p["as_of"],
                current=p["current"],
                fc=p["fc"],
                prev1=p["prev1"],
                prev2=p["prev2"],
                yoy=p["yoy"],
            )
        )
        mtd_total += p["fc"].mtd
        if p["yoy_mtd"] is not None:
            yoy_parts.append(p["yoy_mtd"])
    yoy_total = sum(yoy_parts) if len(yoy_parts) == len(payloads) else None
    chunks.append(
        format_network_total(
            city=city, as_of=as_of, mtd_total=mtd_total, yoy_mtd_total=yoy_total
        )
    )
    return ["\n".join(chunks)]


def main() -> None:
    parser = argparse.ArgumentParser(description="Revenue daily Telegram report")
    parser.add_argument("--env", default=".env", help="Path to .env")
    parser.add_argument("--dry-run", action="store_true", help="Print messages, do not send")
    parser.add_argument("--date", default="", help="Override as-of date YYYY-MM-DD (calendar)")
    args = parser.parse_args()

    load_dotenv(Path(args.env))

    kras_url = os.getenv("REVENUE_YADISK_KRAS", "").strip()
    msk_url = os.getenv("REVENUE_YADISK_MSK", "").strip()
    if not kras_url or not msk_url:
        raise SystemExit("Set REVENUE_YADISK_KRAS and REVENUE_YADISK_MSK in .env")

    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not args.dry_run and (not token or not chat_id):
        raise SystemExit("Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID")

    if args.date:
        today = date.fromisoformat(args.date)
    else:
        today = datetime.now(MSK).date()

    messages: list[str] = []
    with tempfile.TemporaryDirectory(prefix="revenue_") as tmp:
        tmp_path = Path(tmp)
        kras_path = tmp_path / "kras.xlsx"
        msk_path = tmp_path / "msk.xlsx"
        print(f"[INFO] downloading Krasnoyarsk from YaDisk…")
        download_yadisk_public(kras_url, kras_path)
        print(f"[INFO] downloading Moscow from YaDisk…")
        download_yadisk_public(msk_url, msk_path)

        messages.extend(
            reports_for_file(
                kras_path,
                city="Красноярск",
                branches=KRAS_BRANCHES,
                today=today,
                combine=True,
            )
        )
        messages.extend(
            reports_for_file(
                msk_path,
                city="Москва",
                branches=(MSK_BRANCH,),
                today=today,
                combine=False,
            )
        )

    # Telegram limit 4096
    for msg in messages:
        if len(msg) > 4000:
            print(f"[WARN] message length {len(msg)} near Telegram limit")

    if args.dry_run:
        for i, msg in enumerate(messages, 1):
            print("=" * 40, f"MSG {i}", "=" * 40)
            print(msg)
            print()
        return

    for msg in messages:
        tg_send_message(token, chat_id, msg, parse_mode="HTML")
        print(f"[OK] sent {len(msg)} chars to {chat_id}")


if __name__ == "__main__":
    main()
