"""Ask a question about the cashbook. Kie.ai GPT-5.2, OpenAI, or YandexGPT."""

from __future__ import annotations

import os
import threading
from typing import Any

import httpx

from calendar import monthrange
from datetime import date

from .report import format_period, money, month_title, signed_money
from .store import (
    CASH_IN_CATEGORY,
    INTERNAL_CATEGORY,
    UNLABELED_CATEGORY,
    UNREVIEWED_CATEGORY,
    FinanceStore,
    cash_pnl_bucket,
    classify_pnl,
)

_SKIP_TREND = {
    INTERNAL_CATEGORY.casefold(),
    UNLABELED_CATEGORY.casefold(),
    UNREVIEWED_CATEGORY.casefold(),
    CASH_IN_CATEGORY.casefold(),
    "трансферные движения денег",
}

SYSTEM = (
    "Ты помощник по личной кассе Егора. Отвечай по-русски, по цифрам, можно подробно. "
    "Опирайся только на справку ниже. Не выдумывай операции и суммы. "
    "Если в справке нет данных — так и скажи. Не упоминай салоны, Mango и рабочие чаты. "
    "Пиши обычным текстом, без markdown и без звёздочек. "
    "Не ограничивайся месяцем на экране: сравнивай другие месяцы из справки и все статьи расходов. "
    "Если статья есть в нескольких месяцах — скажи, как она менялась, и приведи операции. "
    "Переводы «между своими», неразобранное и трансферные движения — не обычные траты, "
    "отделяй их от покупок, кафе, детей и остальных статей. "
    "Если спрашивают про зависимость или динамику — смотри ряды статей по месяцам и дни месяца."
)

NO_KEY = "Нейросеть не подключена: в .env нужен ключ Kie (KIE_API_KEY), OpenAI или YandexGPT"


class LlmError(RuntimeError):
    pass


_probe_ok: bool | None = None
_probe_error = ""


def configured() -> bool:
    return bool(_kie_key() or _openai_key() or (_yandex_key() and _yandex_folder()))


def reset_probe() -> None:
    global _probe_ok, _probe_error
    _probe_ok = None
    _probe_error = ""


def friendly_error(msg: str) -> str:
    low = (msg or "").lower()
    if "402" in msg or "credit" in low or "кредит" in low:
        return "У Kie закончились кредиты. Пополните на https://kie.ai/billing"
    if "401" in msg or "ключ не принят" in low:
        return "Ключ Kie не принят. Новый ключ: https://kie.ai/api-key"
    if "403" in msg or "permission denied" in low or "forbidden" in low:
        return (
            "Ключ Яндекса есть, но это ключ распознавания речи — GPT он вызывать не умеет. "
            "Нужен ключ Kie (KIE_API_KEY) или OpenAI."
        )
    return msg or "Нейросеть не ответила"


def peek_status() -> tuple[bool, str]:
    """Non-blocking: optimistic True until the background probe finishes."""
    if not configured():
        return False, NO_KEY
    if _probe_ok is None:
        return True, ""
    return _probe_ok, _probe_error


def start_probe() -> None:
    if not configured():
        return
    threading.Thread(target=status, daemon=True, name="llm-probe").start()


def status() -> tuple[bool, str]:
    if not configured():
        return False, NO_KEY
    global _probe_ok, _probe_error
    if _probe_ok is not None:
        return _probe_ok, _probe_error
    try:
        answer("ок", brief="Проверка связи. Все доходы: 0. Все расходы: 0. Операций: 0.")
        _probe_ok = True
        _probe_error = ""
    except LlmError as exc:
        _probe_ok = False
        _probe_error = friendly_error(str(exc))
    return _probe_ok, _probe_error


def _kie_key() -> str:
    return (
        os.getenv("KIE_API_KEY", "").strip()
        or os.getenv("FINANCE_KIE_API_KEY", "").strip()
    )


def _kie_model() -> str:
    return (
        os.getenv("FINANCE_LLM_MODEL", "").strip()
        or os.getenv("KIE_CHAT_MODEL", "").strip()
        or "gpt-5-2"
    )


def _kie_url() -> str:
    explicit = (os.getenv("FINANCE_LLM_URL") or "").strip()
    if explicit and "kie.ai" in explicit.lower():
        return explicit
    base = (os.getenv("KIE_BASE_URL") or "https://api.kie.ai").rstrip("/")
    return f"{base}/{_kie_model()}/v1/chat/completions"


def _openai_key() -> str:
    return (
        os.getenv("FINANCE_LLM_API_KEY", "").strip()
        or os.getenv("OPENAI_API_KEY", "").strip()
    )


def _openai_url() -> str:
    return (os.getenv("FINANCE_LLM_URL") or "https://api.openai.com/v1/chat/completions").strip()


def _openai_model() -> str:
    return (os.getenv("FINANCE_LLM_MODEL") or "gpt-4o-mini").strip()


def _yandex_key() -> str:
    return (
        os.getenv("FINANCE_YANDEX_API_KEY", "").strip()
        or os.getenv("YANDEX_SPEECHKIT_API_KEY", "").strip()
    )


def _yandex_folder() -> str:
    return (
        os.getenv("FINANCE_YANDEX_FOLDER_ID", "").strip()
        or os.getenv("YANDEX_FOLDER_ID", "").strip()
    )


def _yandex_model() -> str:
    return (os.getenv("FINANCE_YANDEX_MODEL") or "yandexgpt/latest").strip()


def _using_kie() -> bool:
    if _kie_key():
        return True
    return "kie.ai" in _openai_url().lower()


def _norm(text: str) -> str:
    return (text or "").casefold().replace("ё", "е")


def _is_transfer_cat(name: str) -> bool:
    return _norm(name) in _SKIP_TREND


def _month_bounds(year: int, month: int) -> tuple[str, str]:
    last = monthrange(year, month)[1]
    return f"{year:04d}-{month:02d}-01", f"{year:04d}-{month:02d}-{last:02d}"


def _shift_month(year: int, month: int, delta: int) -> tuple[int, int]:
    m = month + delta
    y = year
    while m < 1:
        m += 12
        y -= 1
    while m > 12:
        m -= 12
        y += 1
    return y, m


def _cat_blob(rows: list[dict[str, Any]] | None, limit: int = 12) -> str:
    return ", ".join(
        f"{r['name']} {money(r['amount'])}" for r in (rows or [])[:limit]
    )


def _op_line(row: dict[str, Any]) -> str:
    desc = str(row.get("description") or row.get("user_note") or "без описания").strip()
    desc = " ".join(desc.split())[:80]
    bucket, cat = _row_class(row)
    if not cat:
        cat = str(row.get("user_category") or row.get("category") or "").strip() or "без статьи"
    day = str(row.get("posted_date") or "")[:10]
    amt = abs(float(row.get("amount") or 0))
    sign = "+" if bucket == "income" else "−"
    return f"{day} {desc} · {cat} {sign}{money(amt)}"


def _row_class(row: dict[str, Any]) -> tuple[str | None, str]:
    if row.get("cash"):
        bucket = cash_pnl_bucket(row)
        name = str(row.get("user_category") or row.get("category") or "").strip()
        return bucket, name
    try:
        return classify_pnl(row)
    except Exception:
        return None, str(row.get("user_category") or "")


def _empty_month() -> dict[str, Any]:
    return {"income": 0.0, "expense": 0.0, "net": 0.0, "tx_count": 0, "income_cats": {}, "expense_cats": {}}


def _add_hist_row(by: dict[str, dict[str, Any]], row: dict[str, Any], *, cash: bool) -> None:
    day = str(row.get("posted_date") or "")[:10]
    if len(day) < 7:
        return
    ym = day[:7]
    slot = by.setdefault(ym, _empty_month())
    if cash:
        bucket = cash_pnl_bucket(row)
        cat = str(row.get("category") or row.get("user_category") or "").strip()
    else:
        bucket, cat = _row_class(row)
    amt = abs(float(row.get("amount") or 0))
    if not bucket or amt < 0.0001:
        return
    slot["tx_count"] += 1
    if bucket == "income":
        slot["income"] += amt
        if cat:
            slot["income_cats"][cat] = slot["income_cats"].get(cat, 0.0) + amt
    else:
        slot["expense"] += amt
        if cat:
            slot["expense_cats"][cat] = slot["expense_cats"].get(cat, 0.0) + amt
    slot["net"] = slot["income"] - slot["expense"]


def _history_months(store: FinanceStore, date_from: str, date_to: str, *, back: int = 24) -> list[dict[str, Any]]:
    start = date.fromisoformat(date_from[:10])
    y0, m0 = _shift_month(start.year, start.month, -(back - 1))
    hist_from, _ = _month_bounds(y0, m0)
    by: dict[str, dict[str, Any]] = {}
    try:
        txs = store.list_transactions(date_from=hist_from, date_to=date_to, limit=20000)
    except Exception:
        txs = []
    try:
        cash = store.list_cash_ops(hist_from, date_to)
    except Exception:
        cash = []
    for row in txs:
        _add_hist_row(by, row, cash=False)
    for op in cash:
        _add_hist_row(by, op, cash=True)
    out = []
    y, m = start.year, start.month
    for _ in range(back):
        ym = f"{y:04d}-{m:02d}"
        slot = by.get(ym)
        if slot and slot["tx_count"]:
            out.append({"ym": ym, "title": month_title(y, m), **slot})
        y, m = _shift_month(y, m, -1)
    return out


_ASK_STOP = {
    "как", "что", "это", "или", "для", "про", "есть", "были", "было", "менялось",
    "покажи", "сколько", "куда", "ушло", "связь", "крупных", "расходов", "расходы",
    "расход", "статей", "статьи", "статья", "месяцам", "месяца", "месяцы", "месяц",
    "прошлым", "других", "другие", "этом", "месяце", "сравни", "сравнить", "анализ",
    "глубже", "все", "всех", "любые",
}


def _mentioned_names(question: str, names: list[str]) -> list[str]:
    q = _norm(question)
    if not q:
        return []
    words = [w for w in q.replace("?", " ").replace(",", " ").split() if len(w) >= 3 and w not in _ASK_STOP]
    hits = []
    for name in names:
        key = _norm(name)
        if len(key) < 3:
            continue
        if key in q or any(w in key for w in words):
            hits.append(name)
    return hits


def finance_brief(
    store: FinanceStore,
    *,
    date_from: str,
    date_to: str,
    income_categories: list[str] | None = None,
    expense_categories: list[str] | None = None,
    question: str = "",
) -> str:
    summary = store.summary(date_from, date_to)
    selected = store.compute_stat(
        date_from, date_to, income_categories or [], expense_categories or []
    )
    snaps = store.list_stat_snapshots()
    goal = store.get_goal()
    history = _history_months(store, date_from, date_to, back=24)
    lines = [
        f"Период на экране: {format_period(date_from, date_to)} ({date_from}…{date_to})",
        f"Все доходы: {money(summary.get('income') or 0)}",
        f"Все расходы: {money(summary.get('expense') or 0)}",
        f"Сальдо счёта: {signed_money(summary.get('net') or 0)}",
        f"Операций: {summary.get('tx_count') or 0}",
        f"Без статьи в очереди: {summary.get('unreviewed_count') or 0}",
    ]
    wallets = summary.get("wallets") or {}
    if wallets:
        card = (wallets.get("card") or {}).get("amount")
        cash = (wallets.get("cash") or {}).get("amount")
        savings = (wallets.get("savings") or {}).get("amount")
        if card is not None:
            lines.append(f"На карте: {money(card)}")
        if cash is not None:
            lines.append(f"Наличные: {money(cash)}")
        if savings is not None:
            lines.append(f"Накопления на карте: {money(savings)}")
    if goal and goal.get("amount"):
        lines.append(f"Цель месяца: {money(float(goal['amount']))} ({goal.get('kind') or 'net'})")
    inc = _cat_blob(summary.get("income_by_category"), 16)
    exp = _cat_blob(summary.get("expense_by_category"), 80)
    if inc:
        lines.append(f"Доходы по статьям: {inc}")
    if exp:
        lines.append(f"Расходы по статьям: {exp}")
    plans = summary.get("plans") or {}
    exp_plans = plans.get("expense") or {}
    inc_plans = plans.get("income") or {}
    if exp_plans:
        lines.append(
            "Планы расходов: "
            + ", ".join(f"{name} {money(amt)}" for name, amt in list(exp_plans.items())[:20])
        )
    if inc_plans:
        lines.append(
            "Планы доходов: "
            + ", ".join(f"{name} {money(amt)}" for name, amt in list(inc_plans.items())[:12])
        )
    if selected["income_categories"] or selected["expense_categories"]:
        lines.append(
            "Сейчас выбрано для сальдо: доходы "
            + (", ".join(selected["income_categories"]) or "—")
            + "; расходы "
            + (", ".join(selected["expense_categories"]) or "—")
            + f". Сумма доходов {money(selected['income'])}, расходов {money(selected['expense'])}, "
            f"сальдо {signed_money(selected['net'])}."
        )
    else:
        lines.append("Статьи для сальдо пока не отмечены.")
    if snaps:
        bits = []
        for snap in snaps[-12:]:
            bits.append(
                f"{snap['period_from']}…{snap['period_to']}: "
                f"доходы {money(snap['income_total'])}, "
                f"расходы {money(snap['expense_total'])}, "
                f"сальдо {signed_money(snap['net'])}"
            )
        lines.append("Сохранённые записи статистики: " + "; ".join(bits))
    if history:
        bits = []
        for slot in history:
            exp_all = ", ".join(
                f"{name} {money(amt)}"
                for name, amt in sorted(slot["expense_cats"].items(), key=lambda kv: kv[1], reverse=True)
                if not _is_transfer_cat(name)
            )
            inc_top = ", ".join(
                f"{name} {money(amt)}"
                for name, amt in sorted(slot["income_cats"].items(), key=lambda kv: kv[1], reverse=True)[:8]
            )
            y, m = (int(x) for x in slot["ym"].split("-"))
            try:
                month_plans = store.effective_plans(y, m)
            except Exception:
                month_plans = {}
            plan_bits = ", ".join(
                f"{name} план {money(amt)}"
                for name, amt in (month_plans.get("expense") or {}).items()
            )
            real_exp = sum(
                amt for name, amt in slot["expense_cats"].items() if not _is_transfer_cat(name)
            )
            piece = (
                f"{slot['title']} ({slot['ym']}): доходы {money(slot['income'])}, "
                f"расходы {money(slot['expense'])}, "
                f"расходы без переводов {money(real_exp)}, "
                f"сальдо {signed_money(slot['net'])}"
            )
            if exp_all:
                piece += f". Все статьи расходов: {exp_all}"
            if inc_top:
                piece += f". Доходы: {inc_top}"
            if plan_bits:
                piece += f". Планы: {plan_bits}"
            bits.append(piece)
        lines.append("История месяцев (новые сверху): " + " | ".join(bits))
        if len(history) >= 2:
            now, was = history[0], history[1]
            d_exp = now["expense"] - was["expense"]
            d_inc = now["income"] - was["income"]
            lines.append(
                f"К прошлому месяцу ({was['title']}): доходы {signed_money(d_inc)}, "
                f"расходы {signed_money(d_exp)}."
            )
        seen_exp: dict[str, str] = {}
        for slot in history:
            for name in slot["expense_cats"]:
                if _is_transfer_cat(name):
                    continue
                seen_exp.setdefault(_norm(name), name)
        trend_names = sorted(
            seen_exp.values(),
            key=lambda name: sum(float(slot["expense_cats"].get(name) or 0) for slot in history),
            reverse=True,
        )
        if trend_names and history:
            series = []
            for name in trend_names:
                pts = []
                for slot in reversed(history):
                    amt = float((slot["expense_cats"] or {}).get(name) or 0)
                    pts.append(f"{slot['ym']} {money(amt)}")
                series.append(f"{name}: " + ", ".join(pts))
            lines.append("Все статьи расходов по месяцам (старые слева): " + "; ".join(series))
    try:
        expenses = store.list_ledger(date_from, date_to, bucket="expense", limit=800)
    except Exception:
        expenses = []
    try:
        incomes = store.list_ledger(date_from, date_to, bucket="income", limit=400)
    except Exception:
        incomes = []
    if expenses:
        ranked = sorted(expenses, key=lambda row: abs(float(row.get("amount") or 0)), reverse=True)
        lines.append("Крупные расходы периода: " + "; ".join(_op_line(r) for r in ranked[:40]))
        by_day: dict[str, float] = {}
        for row in expenses:
            _, cat = _row_class(row)
            if _is_transfer_cat(cat):
                continue
            day = str(row.get("posted_date") or "")[:10]
            if not day:
                continue
            by_day[day] = by_day.get(day, 0.0) + abs(float(row.get("amount") or 0))
        if by_day:
            days = sorted(by_day)
            lines.append(
                "Расходы по дням (без переводов между своими): "
                + ", ".join(f"{d[8:10]}.{d[5:7]} {money(by_day[d])}" for d in days)
            )
    if incomes:
        ranked_in = sorted(incomes, key=lambda row: abs(float(row.get("amount") or 0)), reverse=True)
        lines.append("Крупные доходы периода: " + "; ".join(_op_line(r) for r in ranked_in[:20]))
    names = [str(r.get("name") or "") for r in (summary.get("expense_by_category") or [])]
    names += [str(r.get("name") or "") for r in (summary.get("income_by_category") or [])]
    for slot in history:
        names.extend(slot["expense_cats"])
        names.extend(slot["income_cats"])
    screen_ym = date_from[:7]
    span_from = (history[-1]["ym"] + "-01") if history else date_from
    try:
        span_txs = store.list_transactions(date_from=span_from, date_to=date_to, limit=20000)
    except Exception:
        span_txs = []
    try:
        span_cash = [dict(op, cash=True) for op in store.list_cash_ops(span_from, date_to)]
    except Exception:
        span_cash = []
    pool = list(span_txs) + list(span_cash)
    other_ops: dict[str, list[dict[str, Any]]] = {}
    for row in pool:
        bucket, cat = _row_class(row)
        if bucket != "expense" or _is_transfer_cat(cat):
            continue
        ym = str(row.get("posted_date") or "")[:7]
        if not ym or ym == screen_ym:
            continue
        other_ops.setdefault(ym, []).append(row)
    other_bits = []
    for ym in sorted(other_ops, reverse=True)[:18]:
        ranked_other = sorted(other_ops[ym], key=lambda row: abs(float(row.get("amount") or 0)), reverse=True)[:12]
        if ranked_other:
            other_bits.append(f"{ym}: " + "; ".join(_op_line(r) for r in ranked_other))
    if other_bits:
        lines.append("Крупные расходы других месяцев: " + " | ".join(other_bits))
    want = _mentioned_names(question, names)
    for cat in want[:6]:
        extra = []
        seen_ids: set[tuple[str, str, str]] = set()
        for row in pool:
            _, row_cat = _row_class(row)
            if _norm(row_cat) != _norm(cat):
                continue
            key = (
                str(row.get("posted_date")),
                str(row.get("amount")),
                str(row.get("description") or row.get("user_note") or row.get("note") or ""),
            )
            if key in seen_ids:
                continue
            seen_ids.add(key)
            extra.append(row)
        extra = sorted(extra, key=lambda row: str(row.get("posted_date") or ""), reverse=True)[:40]
        if extra:
            lines.append(f"Операции «{cat}» за все месяцы справки: " + "; ".join(_op_line(r) for r in extra))
    return "\n".join(lines)


def _clean_history(raw: Any) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    if not isinstance(raw, list):
        return out
    for item in raw[-16:]:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "").strip()
        text = str(item.get("text") or item.get("content") or "").strip()
        if role not in {"user", "assistant"} or not text:
            continue
        out.append({"role": role, "text": text[:2500]})
    return out


def answer(
    question: str,
    *,
    brief: str,
    history: list[dict[str, str]] | None = None,
) -> str:
    q = (question or "").strip()
    if not q:
        raise LlmError("Напишите вопрос")
    if not configured():
        raise LlmError(NO_KEY)
    hist = history or []
    if _using_kie() and (_kie_key() or _openai_key()):
        return _complete_kie(q, brief, hist)
    if _openai_key():
        return _complete_openai(q, brief, hist)
    return _complete_yandex(q, brief, hist)


def _kie_message(role: str, text: str) -> dict[str, Any]:
    return {"role": role, "content": [{"type": "text", "text": text}]}


def _message_text(content: Any) -> str:
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                parts.append(str(item.get("text") or item.get("content") or ""))
            else:
                parts.append(str(item))
        return "".join(parts).strip()
    return str(content or "").strip()


def _plain(text: str) -> str:
    return (text or "").replace("**", "").replace("__", "").strip()


def _complete_kie(question: str, brief: str, history: list[dict[str, str]]) -> str:
    messages = [
        _kie_message("developer", SYSTEM + "\n\nСправка по кассе:\n" + brief),
    ]
    for item in history:
        role = "assistant" if item["role"] == "assistant" else "user"
        messages.append(_kie_message(role, item["text"]))
    messages.append(_kie_message("user", question[:2000]))
    key = _kie_key() or _openai_key()
    with httpx.Client(timeout=90.0) as http:
        res = http.post(
            _kie_url(),
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            },
            json={
                "model": _kie_model(),
                "messages": messages,
                "reasoning_effort": "medium",
            },
        )
    if res.status_code >= 400:
        raise LlmError(_http_detail(res))
    data = res.json()
    text = _plain(_message_text(((data.get("choices") or [{}])[0].get("message") or {}).get("content")))
    if not text:
        raise LlmError("Пустой ответ модели")
    return text


def _complete_openai(question: str, brief: str, history: list[dict[str, str]]) -> str:
    messages = [
        {"role": "system", "content": SYSTEM + "\n\nСправка по кассе:\n" + brief},
    ]
    for item in history:
        messages.append({"role": item["role"], "content": item["text"]})
    messages.append({"role": "user", "content": question[:2000]})
    with httpx.Client(timeout=45.0) as http:
        res = http.post(
            _openai_url(),
            headers={
                "Authorization": f"Bearer {_openai_key()}",
                "Content-Type": "application/json",
            },
            json={
                "model": _openai_model(),
                "temperature": 0.3,
                "max_tokens": 700,
                "messages": messages,
            },
        )
    if res.status_code >= 400:
        raise LlmError(_http_detail(res))
    data = res.json()
    text = _plain(_message_text(((data.get("choices") or [{}])[0].get("message") or {}).get("content")))
    if not text:
        raise LlmError("Пустой ответ модели")
    return text


def _complete_yandex(question: str, brief: str, history: list[dict[str, str]]) -> str:
    folder = _yandex_folder()
    model_uri = f"gpt://{folder}/{_yandex_model()}"
    messages = [
        {"role": "system", "text": SYSTEM + "\n\nСправка по кассе:\n" + brief},
    ]
    for item in history:
        role = "assistant" if item["role"] == "assistant" else "user"
        messages.append({"role": role, "text": item["text"]})
    messages.append({"role": "user", "text": question[:2000]})
    with httpx.Client(timeout=45.0) as http:
        res = http.post(
            "https://llm.api.cloud.yandex.net/foundationModels/v1/completion",
            headers={
                "Authorization": f"Api-Key {_yandex_key()}",
                "Content-Type": "application/json",
            },
            json={
                "modelUri": model_uri,
                "completionOptions": {
                    "stream": False,
                    "temperature": 0.3,
                    "maxTokens": "700",
                },
                "messages": messages,
            },
        )
    if res.status_code >= 400:
        raise LlmError(_http_detail(res))
    data = res.json()
    alts = (data.get("result") or {}).get("alternatives") or []
    text = ((alts[0].get("message") or {}).get("text") if alts else "") or ""
    text = str(text).strip()
    if not text:
        raise LlmError("Пустой ответ модели")
    return text


def _http_detail(res: httpx.Response) -> str:
    try:
        payload = res.json()
        err = payload.get("error") or payload.get("message") or payload
        return f"Нейросеть: HTTP {res.status_code} · {err}"
    except Exception:
        return f"Нейросеть: HTTP {res.status_code} · {res.text[:240]}"
