"""Goal gap, category spikes, and concrete next steps."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

from .report import money

MIN_ABS = 3000.0
ALWAYS_ABS = 8000.0
MIN_PCT = 0.25


@dataclass
class Spike:
    name: str
    current: float
    previous: float
    diff: float


@dataclass
class Recommendation:
    text: str
    category: str = ""


@dataclass
class Digest:
    period_from: str
    period_to: str
    income: float
    expense: float
    net: float
    goal_kind: str | None
    goal_amount: float | None
    gap: float | None
    spikes: list[Spike] = field(default_factory=list)
    recs: list[Recommendation] = field(default_factory=list)
    unreviewed_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Digest":
        spikes = [Spike(**s) if not isinstance(s, Spike) else s for s in data.get("spikes") or []]
        recs = [
            Recommendation(**r) if not isinstance(r, Recommendation) else r
            for r in data.get("recs") or []
        ]
        return cls(
            period_from=data["period_from"],
            period_to=data["period_to"],
            income=float(data["income"]),
            expense=float(data["expense"]),
            net=float(data["net"]),
            goal_kind=data.get("goal_kind"),
            goal_amount=data.get("goal_amount"),
            gap=data.get("gap"),
            spikes=spikes,
            recs=recs,
            unreviewed_count=int(data.get("unreviewed_count") or 0),
        )


def cat_map(rows: list[dict[str, Any]] | None) -> dict[str, float]:
    out: dict[str, float] = {}
    for row in rows or []:
        name = str(row.get("name") or "").strip()
        if name:
            out[name] = float(row.get("amount") or 0)
    return out


def find_spikes(
    current: list[dict[str, Any]] | None,
    previous: list[dict[str, Any]] | None,
) -> list[Spike]:
    now = cat_map(current)
    was = cat_map(previous)
    spikes: list[Spike] = []
    for name, amount in now.items():
        prev = was.get(name, 0.0)
        diff = amount - prev
        if diff < MIN_ABS:
            continue
        if prev <= 0:
            spikes.append(Spike(name=name, current=amount, previous=prev, diff=diff))
            continue
        pct = diff / prev
        if pct >= MIN_PCT or diff >= ALWAYS_ABS:
            spikes.append(Spike(name=name, current=amount, previous=prev, diff=diff))
    spikes.sort(key=lambda s: s.diff, reverse=True)
    return spikes


def build_digest(
    summary: dict[str, Any],
    previous: dict[str, Any] | None,
    *,
    goal: dict[str, Any] | None,
    stances: dict[str, str] | None = None,
) -> Digest:
    stances = stances or {}
    period = summary.get("period") or {}
    prev_ok = bool(previous and previous.get("tx_count"))
    prev_cats = (previous or {}).get("expense_by_category") if prev_ok else None
    spikes = find_spikes(summary.get("expense_by_category"), prev_cats) if prev_ok else []
    goal_kind = (goal or {}).get("kind") if goal else None
    goal_amount = float(goal["amount"]) if goal and goal.get("amount") is not None else None
    net = float(summary.get("net") or 0)
    gap = None
    if goal_amount is not None:
        gap = round(goal_amount - net, 2)
    recs = make_recommendations(spikes, gap, stances)
    return Digest(
        period_from=str(period.get("from") or ""),
        period_to=str(period.get("to") or ""),
        income=float(summary.get("income") or 0),
        expense=float(summary.get("expense") or 0),
        net=net,
        goal_kind=goal_kind,
        goal_amount=goal_amount,
        gap=gap,
        spikes=spikes[:8],
        recs=recs[:3],
        unreviewed_count=int(summary.get("unreviewed_count") or 0),
    )


def make_recommendations(
    spikes: list[Spike],
    gap: float | None,
    stances: dict[str, str],
) -> list[Recommendation]:
    recs: list[Recommendation] = []
    actionable = [
        s
        for s in spikes
        if stances.get(s.name.casefold()) not in {"normal", "not_expense"}
    ]
    if gap is None:
        if actionable:
            top = actionable[0]
            recs.append(
                Recommendation(
                    f"Сильнее всего выросли «{top.name}»: {money(top.diff)} к прошлому периоду. "
                    "Задайте цель: /цель 80000",
                    top.name,
                )
            )
        return recs
    if gap <= 0:
        recs.append(
            Recommendation(
                f"Цель по сальдо уже выполняется (запас {money(abs(gap))}).",
                "",
            )
        )
        return recs

    remaining = gap
    for spike in actionable:
        save = spike.diff
        if save < 1000:
            continue
        after = max(0.0, remaining - save)
        cut = stances.get(spike.name.casefold()) == "cut"
        prefix = "Вы сами отметили сократить. " if cut else ""
        recs.append(
            Recommendation(
                prefix
                + f"«{spike.name}» +{money(spike.diff)} к прошлому месяцу. "
                f"Вернуть к прошлому уровню — до цели останется {money(after)} "
                f"вместо {money(remaining)}.",
                spike.name,
            )
        )
        remaining = after
        if len(recs) >= 3:
            break
    if not recs:
        recs.append(
            Recommendation(
                f"До цели не хватает {money(gap)}, но отдельных всплесков нет — "
                "режет общий уровень расходов, не одна статья.",
                "",
            )
        )
    return recs


def parse_goal_amount(text: str) -> float | None:
    t = (text or "").lower().replace("\xa0", " ")
    t = t.replace("₽", " ").replace("руб.", " ").replace("руб", " ")
    m = re.search(r"(\d[\d\s]*)\s*(к|тыс|тысяч)?", t)
    if not m:
        return None
    raw = m.group(1).replace(" ", "").replace(",", ".")
    try:
        num = float(raw)
    except ValueError:
        return None
    if m.group(2):
        num *= 1000
    if num <= 0 or num > 1_000_000_000:
        return None
    return round(num, 2)


def stance_label(stance: str) -> str:
    return {
        "normal": "норма",
        "cut": "сократить",
        "not_expense": "не расход",
    }.get(stance, stance)
