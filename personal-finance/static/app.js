const $ = (sel, el = document) => el.querySelector(sel);
const app = document.getElementById("app");
const MONTHS = ["", "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь", "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"];

const state = {
  me: null,
  year: new Date().getFullYear(),
  month: new Date().getMonth() + 1,
  summary: null,
  review: null,
  reviewId: null,
  view: "home",
  notice: "",
  cashPanel: "",
  cashCat: "",
  cashEdit: null,
  planEdit: null,
  stats: [],
  statSeries: null,
  statMonths: 12,
  statExpand: false,
  statChat: [],
  statChatBusy: false,
  ops: null,
  editOp: null,
  editFrom: "ops",
};

let historyReady = false;
let historyBusy = false;

function snapshotRoute() {
  return {
    view: state.view || "home",
    year: state.year,
    month: state.month,
    opsBucket: state.ops?.bucket || "",
    opsCategory: state.ops?.category || "",
    editOpId: state.editOp?.id != null ? String(state.editOp.id) : "",
    editFrom: state.editFrom || "home",
    reviewId: state.reviewId ? String(state.reviewId) : "",
  };
}

function routeKey(route) {
  return JSON.stringify(route || {});
}

function buildRouteUrl(route) {
  const q = new URLSearchParams();
  if (route.view && route.view !== "home") q.set("v", route.view);
  q.set("y", String(route.year));
  q.set("m", String(route.month));
  if (route.opsBucket) q.set("ops", route.opsBucket);
  if (route.opsCategory) q.set("cat", route.opsCategory);
  if (route.editOpId) {
    q.set("tx", route.editOpId);
    if (route.editFrom && route.editFrom !== "home") q.set("from", route.editFrom);
  }
  if (route.reviewId) q.set("rev", route.reviewId);
  const qs = q.toString();
  return qs ? `${location.pathname}?${qs}` : location.pathname;
}

function routeFromUrl() {
  const q = new URLSearchParams(location.search);
  const view = q.get("v") || "home";
  const year = Number(q.get("y"));
  const month = Number(q.get("m"));
  if (!q.get("v") && !q.get("y") && !q.get("m") && !q.get("ops") && !q.get("tx") && !q.get("rev")) {
    return null;
  }
  return {
    view,
    year: Number.isFinite(year) && year >= 2000 ? year : state.year,
    month: Number.isFinite(month) && month >= 1 && month <= 12 ? month : state.month,
    opsBucket: q.get("ops") || "",
    opsCategory: q.get("cat") || "",
    editOpId: q.get("tx") || "",
    editFrom: q.get("from") || "home",
    reviewId: q.get("rev") || "",
  };
}

function commitRoute({ replace = false } = {}) {
  if (historyBusy || !historyReady) return;
  const route = snapshotRoute();
  const url = buildRouteUrl(route);
  if (replace) {
    history.replaceState({ kassa: 1, route }, "", url);
    return;
  }
  if (routeKey(history.state?.route) === routeKey(route)) return;
  history.pushState({ kassa: 1, route }, "", url);
}

function goBack() {
  if (history.state?.kassa) {
    history.back();
    return;
  }
  if (state.view === "edit-op" && state.editFrom === "ops" && state.ops) {
    state.editOp = null;
    state.view = "ops";
    render();
    return;
  }
  if (state.view === "edit-op" && state.editFrom === "queue") {
    state.editOp = null;
    state.view = "queue";
    render();
    return;
  }
  if (state.view === "review") {
    showQueue({ history: false });
    return;
  }
  goHome({ history: false });
}

async function restoreRoute(route) {
  if (!route) {
    goHome({ history: false });
    return;
  }
  historyBusy = true;
  try {
    state.year = route.year || state.year;
    state.month = route.month || state.month;
    state.reviewId = route.reviewId || null;
    state.editFrom = route.editFrom || "home";
    state.cashPanel = "";
    state.cashEdit = null;
    state.planEdit = null;
    const view = route.view || "home";
    if (view === "ops") {
      await showOps(route.opsBucket || "expense", route.opsCategory || "", { history: false });
    } else if (view === "edit-op" && route.editOpId) {
      if (route.editFrom === "ops" && route.opsBucket) {
        await showOps(route.opsBucket, route.opsCategory || "", { history: false });
      } else if (route.editFrom === "queue") {
        await showQueue({ history: false });
      } else {
        await loadSummary();
      }
      await openEditOp(route.editOpId, { history: false });
    } else if (view === "stats") {
      await showStats({ history: false });
    } else if (view === "queue") {
      await showQueue({ history: false });
    } else if (view === "review") {
      state.view = "review";
      await loadReview();
    } else if (view === "focus-income" || view === "focus-expense") {
      state.view = view;
      state.ops = null;
      state.editOp = null;
      await loadSummary();
      render();
    } else {
      state.view = "home";
      state.ops = null;
      state.editOp = null;
      state.reviewId = null;
      await loadSummary();
    }
  } finally {
    historyBusy = false;
  }
}

const money = (n, signed = false) => {
  const abs = Math.abs(n);
  const body = abs.toLocaleString("ru-RU", { maximumFractionDigits: 0 });
  if (signed) {
    if (n > 0) return `+${body} ₽`;
    if (n < 0) return `−${body} ₽`;
  }
  if (n < 0) return `−${body} ₽`;
  return `${body} ₽`;
};

async function api(path, options = {}) {
  const opts = { credentials: "same-origin", ...options };
  if (opts.body && typeof opts.body === "object" && !(opts.body instanceof FormData)) {
    opts.headers = { "Content-Type": "application/json", ...(opts.headers || {}) };
    opts.body = JSON.stringify(opts.body);
  }
  const res = await fetch(path, opts);
  if (res.status === 401) {
    state.me = { authed: false, auth_required: true };
    throw Object.assign(new Error("unauthorized"), { status: 401 });
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw Object.assign(new Error(data.detail || data.error || "Ошибка"), { status: res.status, data });
  }
  return data;
}

function render() {
  if (!state.me) {
    app.innerHTML = `<div class="app-shell"><p class="empty">Загрузка…</p></div>`;
    return;
  }
  if (state.me.auth_required && !state.me.authed) {
    app.innerHTML = loginView();
    bindLogin();
    return;
  }
  if (state.view === "review") {
    app.innerHTML = reviewView();
    bindReview();
    return;
  }
  if (state.view === "queue") {
    app.innerHTML = queueView();
    bindQueue();
    return;
  }
  if (state.view === "ops") {
    app.innerHTML = opsView();
    bindOps();
    return;
  }
  if (state.view === "edit-op") {
    app.innerHTML = editOpView();
    bindEditOp();
    return;
  }
  if (state.view === "focus-income") {
    app.innerHTML = focusIncomeView();
    bindFocusIncome();
    return;
  }
  if (state.view === "focus-expense") {
    app.innerHTML = focusExpenseView();
    bindFocusExpense();
    return;
  }
  if (state.view === "stats") {
    app.innerHTML = statsView();
    bindStats();
    return;
  }
  app.innerHTML = homeView();
  bindHome();
}

function loginView() {
  return `
    <div class="login-wrap">
      <form class="login-card" id="login-form">
        <div class="brand">Касса</div>
        <h1>Личные финансы</h1>
        <p>Только ваши выписки. Никак не связано с салоном и рабочими чатами.</p>
        <input class="text-input" type="password" name="password" placeholder="Пароль" autocomplete="current-password" />
        <button class="primary" type="submit">Войти</button>
        <div class="error" id="login-error" hidden></div>
      </form>
    </div>`;
}

function expenseCatalog() {
  const rows = [...(state.summary?.summary?.expense_by_category || [])];
  const seen = new Set(rows.map((row) => catKey(row.name)));
  const plans = (state.summary?.summary?.plans || {}).expense || {};
  for (const name of Object.keys(plans)) {
    if (seen.has(catKey(name))) continue;
    rows.push({ name, amount: 0 });
    seen.add(catKey(name));
  }
  const saved = state.summary?.focus?.expenses;
  if (Array.isArray(saved)) {
    for (const name of saved) {
      if (!name || seen.has(catKey(name))) continue;
      rows.push({ name, amount: 0 });
      seen.add(catKey(name));
    }
  }
  return rows;
}

function actualExpense(name) {
  const rows = state.summary?.summary?.expense_by_category || [];
  const hit = rows.find((row) => catKey(row.name) === catKey(name));
  return hit ? Number(hit.amount) || 0 : 0;
}

function saldoArticleAmount(name) {
  const spent = actualExpense(name);
  if (spent > 0) return spent;
  return planAmount("expense", name);
}

function chosenIncome() {
  const value = state.summary?.focus?.income;
  if (value == null || value === "") return null;
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

function chosenExpenseNames() {
  const saved = state.summary?.focus?.expenses;
  if (!Array.isArray(saved)) return expenseCatalog().map((row) => row.name);
  return saved;
}

function chosenExpenseSum() {
  return chosenExpenseNames().reduce((sum, name) => sum + saldoArticleAmount(name), 0);
}

function chosenNet() {
  const income = chosenIncome();
  if (income == null) return null;
  return income - chosenExpenseSum();
}

function homeView() {
  const s = state.summary?.summary;
  const reviewN = s?.unreviewed_count || 0;
  const net = chosenNet();
  const income = chosenIncome();
  const expenseSum = chosenExpenseSum();
  const expenseArticles = (s?.expense_by_category || []).reduce((a, c) => a + (Number(c.amount) || 0), 0);
  const maxExp = Math.max(1, ...(s?.expense_by_category || []).map((c) => c.amount));
  const maxInc = Math.max(1, ...(s?.income_by_category || []).map((c) => c.amount));
  const delta = income == null
    ? "Нажмите «Доходы» и введите сумму. Из неё вычтутся отмеченные статьи: план, пока нет трат, и сами траты, когда они появятся."
    : "Указанный доход минус отмеченные статьи. По статье без трат берётся план, как появятся траты — они. С выпиской это число не сверяется.";
  const showLogout = Boolean(state.me.auth_required);
  return `
    <div class="app-shell">
      ${state.me.demo ? `<p class="demo-ribbon">Демо · цифры выдуманные</p>` : ""}
      <div class="topbar">
        <div class="brand">Касса</div>
        <div class="top-actions">
          <button class="ghost" id="open-stats" type="button">Статистика</button>
          <button class="ghost" id="notify-btn" ${state.me.telegram ? "" : "hidden"}>В Telegram</button>
          <button class="ghost" id="logout-btn" ${showLogout ? "" : "hidden"}>Выйти</button>
        </div>
      </div>
      <div class="month-nav">
        <button class="icon-btn" id="prev-month" aria-label="Предыдущий месяц">←</button>
        <div class="month-title">
          <h1>${esc(MONTHS[state.month] || "")}</h1>
          <div class="year">${state.year}</div>
        </div>
        <button class="icon-btn" id="next-month" aria-label="Следующий месяц">→</button>
      </div>
      <div class="rule"></div>
      ${state.notice ? `<p class="ok">${esc(state.notice)}</p>` : ""}
      ${reviewN ? `
        <div class="banner">
          <p><b>${reviewN}</b> ${plural(reviewN, "перевод", "перевода", "переводов")} без статьи — поясните, куда ушли деньги.</p>
          <button type="button" class="primary" id="go-review" data-nav="queue">Разобрать</button>
        </div>` : ""}
      <section class="hero">
        <div class="label">Сальдо</div>
        <p class="net serif ${net == null ? "" : net >= 0 ? "pos" : "neg"}">${net == null ? "—" : money(net, true)}</p>
        ${renderGoalMeter(s)}
        <div class="split">
          <button type="button" class="kpi in" data-focus="income">
            <div class="k">Доходы</div>
            <div class="v">${income == null ? "Указать" : money(income)}</div>
          </button>
          <button type="button" class="kpi out" data-focus="expense">
            <div class="k">Расходы</div>
            <div class="v">${money(expenseSum)}</div>
          </button>
        </div>
        <div class="delta">${esc(delta)}</div>
        ${cashWallet(s)}
        <div class="cash-actions">
          <button type="button" class="ghost" id="cash-from-card">С карты в наличные</button>
          <button type="button" class="ghost" id="cash-expense">Расход наличными</button>
        </div>
        ${cashPanelForm()}
        ${cashOpsList(s)}
      </section>
      <section class="card">
        <div class="card-head">
          <h2>Цель месяца</h2>
          <span class="muted">${daysLeftLabel()}</span>
        </div>
        <p class="hint">Сальдо, которое хотите видеть по итогам месяца. Отчёт в группу уйдёт после разнесения переводов.</p>
        ${renderGoal(s)}
      </section>
      <section class="card">
        <h2>Загрузить выписку</h2>
        ${state.me.drive ? `<button class="primary" id="pull-drive" style="width:100%;margin-bottom:12px">Забрать с Google Drive</button>` : ""}
        <label class="drop" id="drop">
          <strong>Вложить выписку</strong>
          <p>PDF Альфа, CSV или Excel. На iPhone: Обзор → Загрузки.</p>
          <span class="primary pick-file" id="pick-file">Выбрать файл</span>
          <input id="file" class="file-hidden" type="file" />
        </label>
        <p class="hint">Имя файла не важно — даты беру из операций внутри. Серый файл после обновления страницы больше не должен быть.</p>
        <div class="error" id="upload-error" hidden></div>
      </section>
      <section class="card">
        <button type="button" class="card-head hit" data-ops="expense"${expenseArticles > 0 || (s && s.expense) ? "" : " disabled"}>
          <h2>Расходы</h2>
          <span class="muted">${expenseArticles > 0 || s ? money(expenseArticles || s?.expense || 0) : ""} ›</span>
        </button>
        <p class="hint">По статье списания и поступления складываются, наличные тоже. Сверка с выпиской — только по карте: наличные в шапку PDF не входят.</p>
        ${renderReconcile(s)}
        ${renderBars(expenseCatalog().filter((row) => actualExpense(row.name) > 0 || planAmount("expense", row.name) > 0), maxExp, "expense") || `<p class="empty">Пока пусто</p>`}
        ${renderSpikes()}
      </section>
      <section class="card">
        <button type="button" class="card-head hit" data-ops="income"${s && s.income ? "" : " disabled"}>
          <h2>Доходы</h2>
          <span class="muted">${s ? money(s.income) : ""} ›</span>
        </button>
        ${renderBars(s?.income_by_category, maxInc, "income") || `<p class="empty">Пока пусто</p>`}
      </section>
      ${unlabeledCard(s)}
      ${tabBar()}
    </div>`;
}

function reviewView() {
  const items = state.review?.transactions || [];
  const current = items.find((t) => String(t.id) === String(state.reviewId)) || items[0];
  const left = items.length;
  if (!current) {
    return `
      <div class="app-shell">
        <div class="topbar"><div class="brand">Касса</div></div>
        <div class="card"><h2>Все переводы разобраны</h2><p>Статьи банка и ваши пояснения уже в сводке. Неразмеченные — в разделе «Переводы без разметки».</p></div>
        ${tabBar()}
      </div>`;
  }
  const amtClass = current.amount < 0 ? "neg" : "pos";
  return `
    <div class="app-shell">
      <div class="topbar">
        <div class="brand">Осталось ${left}</div>
        <button type="button" class="ghost" id="review-later" data-nav="queue">Разобрать позже</button>
      </div>
      <section class="hero">
        <div class="label">${fmtDate(current.posted_date)}</div>
        <p class="net serif ${amtClass}">${money(current.amount, true)}</p>
        <p class="desc">${esc(current.description || "Без описания")}</p>
        <p class="sub">Банк: ${esc(current.bank_category || "нет статьи")}${current.card ? " · " + esc(current.card) : ""}</p>
      </section>
      <section class="card" id="review-card" data-id="${current.id}">
        <h2>Куда ушли деньги?</h2>
        <textarea id="note" rows="3" placeholder="Например: перевод маме, на накопительный, за квартиру">${esc(current.user_note)}</textarea>
        <div class="mode-row">
          <button class="ghost" data-mode="transfer">Между своими</button>
          ${Number(current.amount) > 0 ? "" : `<button class="ghost" data-mode="expense">Расход</button>`}
          <button class="ghost" data-mode="income">Доход</button>
        </div>
        ${Number(current.amount) > 0 ? `<p class="hint">Поступление само идёт в доходы. «Между своими» — если это перевод на свой счёт.</p>` : ""}
        <div id="cat-box" hidden>
          <div class="chips" id="chips"></div>
          <input class="text-input" id="custom-cat" placeholder="Своя статья" />
        </div>
        <button class="primary" id="save-review" style="width:100%;margin-top:14px">Сохранить</button>
        ${(current.description || "").trim() ? `<button type="button" class="ghost" id="apply-desc" style="width:100%;margin-top:8px">Добавить в статью все с таким описанием</button>` : ""}
        <button class="ghost" id="leave-unlabeled" style="width:100%;margin-top:8px">Оставить неразмеченным</button>
        ${pendingIncome(items).length ? `<button class="primary income-all" id="accept-income-all" style="width:100%;margin-top:8px">Зачислить все доходы</button>` : ""}
        <div class="error" id="review-error" hidden></div>
      </section>
      ${tabBar()}
    </div>`;
}

function queueView() {
  const pending = state.review?.transactions || [];
  const inflows = pendingIncome(pending);
  const inflowSum = inflows.reduce((acc, t) => acc + Number(t.amount || 0), 0);
  const s = state.summary?.summary;
  return `
    <div class="app-shell">
      <div class="topbar">
        <div class="brand">Касса</div>
      </div>
      <h1 class="queue-title serif">Разобрать позже</h1>
      <p class="hint">${pending.length
        ? "Все неразобранные переводы здесь. Откройте любой или оставьте без статьи."
        : "Очереди нет. Неразмеченные за месяц — ниже, если они есть."}</p>
      ${pending.length ? `
        <div class="queue-actions">
          ${inflows.length ? `<button class="primary income-all" id="accept-income-all">Зачислить все доходы</button>
          <p class="hint">${inflows.length} ${plural(inflows.length, "поступление", "поступления", "поступлений")} · ${money(inflowSum, true)}</p>` : ""}
          <button class="ghost" id="unlabel-all">Оставить все неразмеченными</button>
        </div>
        <section class="card">
          ${pending.map((t) => txRow(t, "open-review")).join("")}
        </section>` : `<p class="empty">Пока нечего разбирать позже</p>`}
      ${unlabeledCard(s)}
      ${tabBar()}
    </div>`;
}

function tabBar() {
  const n = Number(state.review?.count ?? state.summary?.summary?.unreviewed_count ?? 0);
  const onQueue = state.view === "queue" || state.view === "review";
  const onHome = state.view === "home" || state.view === "ops" || state.view === "edit-op"
    || state.view === "focus-income" || state.view === "focus-expense";
  const onStats = state.view === "stats";
  return `
    <nav class="tabbar">
      <button type="button" class="tab ${onHome ? "on" : ""}" id="tab-home" data-nav="home">Сводка</button>
      <button type="button" class="tab ${onStats ? "on" : ""}" id="tab-stats" data-nav="stats">Статистика</button>
      <button type="button" class="tab ${onQueue ? "on" : ""} ${n ? "hot" : ""}" id="tab-queue" data-nav="queue">
        Разобрать позже
        ${n ? `<span class="tab-badge">${n > 99 ? "99+" : n}</span>` : ""}
      </button>
    </nav>`;
}

function pendingIncome(items) {
  return (items || []).filter((t) => Number(t.amount) > 0);
}

function unlabeledCard(s) {
  const rows = s?.unlabeled || [];
  if (!rows.length) return "";
  return `
    <section class="card unlabeled-card">
      <div class="card-head">
        <h2>Переводы без разметки</h2>
        <span class="muted">${money(Math.abs(s.unlabeled_sum || 0))}</span>
      </div>
      <p class="hint">Оставили без статьи. В сальдо входят, в обычные категории — нет. Нажмите — можно задать статью.</p>
      ${rows.map((t) => txRow(t, "edit")).join("")}
    </section>`;
}

function uniqueDescSeeds(rows) {
  const seen = new Map();
  for (const t of rows || []) {
    if (t?.cash) continue;
    const key = String(t.description || "").trim().toLowerCase().replace(/\s+/g, " ");
    if (!key || seen.has(key)) continue;
    seen.set(key, t);
  }
  return [...seen.values()];
}

function shortDesc(text, n = 42) {
  const d = String(text || "").trim();
  return d.length > n ? `${d.slice(0, n)}…` : d;
}

function opsView() {
  const ops = state.ops || {};
  const rows = ops.transactions || [];
  const title = ops.title || "Операции";
  const showCat = !ops.category;
  const seeds = uniqueDescSeeds(rows);
  return `
    <div class="app-shell">
      <div class="topbar">
        <button class="ghost" id="ops-back">Назад</button>
        <div class="brand">Касса</div>
      </div>
      <h1 class="queue-title serif">${esc(title)}</h1>
      <p class="hint">${ops.loading
        ? "Загрузка…"
        : `${rows.length} ${plural(rows.length, "операция", "операции", "операций")} · ${money(ops.sum || 0)}. Нажмите строку — можно сменить статью.`}</p>
      ${ops.category && !ops.loading ? `
        <section class="card">
          <h2>Переименовать статью</h2>
          <p class="hint">Новое имя сразу для всех операций в «${esc(ops.category)}».</p>
          <input class="text-input" id="rename-cat" placeholder="Новое название" value="${esc(ops.category)}" />
          <button class="primary" id="rename-cat-btn" style="width:100%;margin-top:12px">Сохранить название</button>
          <div class="error" id="rename-error" hidden></div>
        </section>` : ""}
      ${ops.category && !ops.loading && seeds.length ? `
        <section class="card">
          <h2>По описанию</h2>
          <p class="hint">Найти все операции с тем же текстом и поставить статью «${esc(ops.category)}» — даже если сейчас они «между своими».</p>
          ${seeds.map((t) => `
            <button type="button" class="ghost" data-apply-desc="${t.id}" style="width:100%;margin-top:8px">
              Добавить в статью все с таким описанием${seeds.length > 1 ? ` · ${esc(shortDesc(t.description))}` : ""}
            </button>`).join("")}
          <div class="error" id="apply-desc-error" hidden></div>
        </section>` : ""}
      ${rows.length ? `
        <section class="card">
          ${rows.map((t) => txRow(t, "edit", showCat)).join("")}
        </section>` : (ops.loading ? "" : `<p class="empty">Операций нет</p>`)}
      ${tabBar()}
    </div>`;
}

function editOpView() {
  const t = state.editOp;
  if (!t) {
    return `
      <div class="app-shell">
        <div class="topbar"><div class="brand">Касса</div></div>
        <p class="empty">Операция не найдена</p>
        ${tabBar()}
      </div>`;
  }
  const amtClass = t.amount < 0 ? "neg" : "pos";
  const cat = currentCat(t);
  const mcc = (t.mcc || "").replace(/\D/g, "").slice(-4);
  const mccLabel = mcc ? `MCC ${mcc}` : "";
  return `
    <div class="app-shell">
      <div class="topbar">
        <button class="ghost" id="edit-back">Назад</button>
        <div class="brand">Касса</div>
      </div>
      <section class="hero">
        <div class="label">${esc(fmtDate(t.posted_date))}</div>
        <p class="net serif ${amtClass}">${money(t.amount, true)}</p>
        <p class="desc">${esc(t.description || "Без описания")}</p>
        <p class="sub">${isHold(t) ? "Операция в обработке · " : ""}${cat ? `Сейчас: ${esc(cat)}` : "Статья не задана"}${mccLabel ? ` · ${mccLabel}` : ""}</p>
      </section>
      <section class="card" id="edit-card" data-id="${t.id}">
        <h2>Статья</h2>
        <p class="hint">Выберите из списка или напишите новое название — так создаётся своя статья.</p>
        <div class="mode-row">
          ${Number(t.amount) > 0 ? "" : `<button type="button" class="ghost" data-mode="expense">Расход</button>`}
          <button type="button" class="ghost" data-mode="income">Доход</button>
        </div>
        ${Number(t.amount) > 0 ? `<p class="hint">Поступление — это доход. В расход его не записать.</p>` : ""}
        <div class="chips" id="edit-chips"></div>
        <input class="text-input" id="edit-cat" placeholder="Название статьи" value="${esc(cat)}" />
        <button class="primary" id="save-cat" style="width:100%;margin-top:14px">Сохранить эту операцию</button>
        ${(t.description || "").trim() ? `<button type="button" class="ghost" id="apply-desc" style="width:100%;margin-top:8px">Добавить в статью все с таким описанием</button>` : ""}
        ${mcc ? `<button class="ghost" id="apply-mcc" style="width:100%;margin-top:8px">Отнести все с этим кодом · MCC ${esc(mcc)}</button>` : ""}
        ${cat && cat !== "Между своими" && cat !== "Не разобрано" ? `<button class="ghost" id="rename-article" style="width:100%;margin-top:8px">Переименовать статью «${esc(cat)}»</button>` : ""}
        <div class="error" id="edit-error" hidden></div>
      </section>
      ${tabBar()}
    </div>`;
}

function isHold(t) {
  return t?.status === "hold" || Boolean(t?.extra?.hold);
}

function currentCat(t) {
  return (t?.user_category || t?.bank_category || "").trim();
}

const EXPENSE_PALETTE = [
  { bg: "#e6eee4", fill: "#9eaf94", border: "#c5d1be" },
  { bg: "#f1e6e0", fill: "#c2a396", border: "#ddcbc3" },
  { bg: "#e4eaf0", fill: "#9aabc0", border: "#c5ced8" },
  { bg: "#eee6da", fill: "#c0ae94", border: "#ddd0be" },
  { bg: "#e6e4ef", fill: "#a39bb8", border: "#ccc8d8" },
  { bg: "#e4eeea", fill: "#94b0a6", border: "#c3d4ce" },
  { bg: "#efe3e8", fill: "#c09aa8", border: "#dbc6ce" },
  { bg: "#ebe4ef", fill: "#b09ab8", border: "#d4c8d8" },
  { bg: "#ece7db", fill: "#b8ab8e", border: "#d8d0be" },
  { bg: "#f0e8dc", fill: "#c4b496", border: "#e0d4c0" },
  { bg: "#e8e6e2", fill: "#b0aaa4", border: "#d4d0ca" },
  { bg: "#ece6e2", fill: "#b8aea6", border: "#d8d0c8" },
  { bg: "#efe6e0", fill: "#c4b0a4", border: "#ddd0c6" },
  { bg: "#e4ece8", fill: "#9eb2aa", border: "#c8d6d0" },
  { bg: "#efe8e4", fill: "#c2b0a6", border: "#dccfc8" },
  { bg: "#e8ece4", fill: "#a8b49a", border: "#cdd4c4" },
];

const EXPENSE_TONE_BY_NAME = {
  "продукты": 0,
  "еда": 0,
  "супермаркеты": 0,
  "кафе": 1,
  "кафе и рестораны": 1,
  "рестораны": 1,
  "транспорт": 2,
  "транспорт и такси": 2,
  "такси": 2,
  "машина": 14,
  "азс": 14,
  "жилье": 3,
  "жильё": 3,
  "дом и ремонт": 3,
  "связь": 4,
  "здоровье": 5,
  "аптеки": 5,
  "одежда": 6,
  "покупки": 6,
  "путешествия": 13,
  "подарки": 7,
  "подписки": 8,
  "накопления": 9,
  "между своими": 10,
  "переводы без разметки": 11,
  "не разобрано": 12,
  "цветы": 6,
  "канцтовары": 8,
  "детское": 7,
  "электроника": 4,
  "авто": 14,
  "услуги": 12,
};

function catKey(name) {
  return String(name || "").trim().toLowerCase().replace(/ё/g, "е");
}

function expenseTone(name) {
  const key = catKey(name);
  let idx = EXPENSE_TONE_BY_NAME[key];
  if (idx == null) {
    let h = 2166136261;
    for (let i = 0; i < key.length; i++) h = Math.imul(h ^ key.charCodeAt(i), 16777619);
    idx = Math.abs(h) % EXPENSE_PALETTE.length;
  }
  return EXPENSE_PALETTE[idx];
}

function catVars(name) {
  const t = expenseTone(name);
  return `--cat-bg:${t.bg};--cat-fill:${t.fill};--cat-border:${t.border}`;
}

function chipHtml(name, chosen, tint) {
  const on = chosen === name ? " on" : "";
  const tinted = tint ? " tinted" : "";
  const style = tint ? ` style="${catVars(name)}"` : "";
  return `<button type="button" class="chip${tinted}${on}" data-cat="${esc(name)}"${style}>${esc(name)}</button>`;
}

function txRow(t, action, showCat) {
  const cls = t.amount < 0 ? "neg" : "pos";
  const isCash = Boolean(t?.cash);
  const open = isCash ? ""
    : action === "open-review" ? ` data-open="${t.id}"`
    : action === "edit" ? ` data-edit="${t.id}"` : "";
  const tag = action && !isCash ? "button" : "div";
  const type = action && !isCash ? ` type="button"` : "";
  const cat = (t.user_category || t.bank_category || "").trim();
  const vars = cat ? ` style="${catVars(cat)}"` : "";
  const sub = [
    fmtDate(t.posted_date),
    showCat && cat ? cat : "",
    isCash ? "оплата наличными" : "",
    isHold(t) ? "в обработке" : "",
  ].filter(Boolean).join(" · ");
  return `
    <${tag} class="tx-row${isCash ? " cash-tx" : ""}"${type}${open}${vars}>
      <div>
        <div class="tx-desc">${cat ? `<span class="cat-swatch" aria-hidden="true"></span>` : ""}${esc(t.description || (isCash ? "Оплата наличными" : "Перевод"))}</div>
        <div class="tx-sub">${esc(sub)}</div>
      </div>
      <div class="tx-amt ${cls}">${money(t.amount, true)}</div>
    </${tag}>`;
}

function renderGoalMeter() {
  const goal = state.summary?.goal;
  const net = chosenNet();
  if (!goal || net == null) return "";
  const pct = Math.max(0, Math.min(100, (net / goal.amount) * 100));
  const cls = net >= goal.amount ? "over" : "under";
  return `
    <div class="meter-wrap">
      <div class="meter" title="До цели"><div class="meter-fill ${cls}" style="width:${pct}%"></div></div>
      <div class="meter-cap">
        <span>${Math.round(pct)}% от цели</span>
        <span>${money(goal.amount)}</span>
      </div>
    </div>`;
}

function renderGoal() {
  const goal = state.summary?.goal;
  const net = chosenNet();
  const amount = goal?.amount ? Math.round(goal.amount) : "";
  let status = "Пока не задана — бот в группе не знает, к чему советовать.";
  if (goal && net == null) {
    status = "Укажите доход на сводке — сальдо считается от него.";
  } else if (goal && net != null) {
    const gap = goal.amount - net;
    status = gap > 0
      ? `Не хватает ${money(gap)}`
      : `Цель выполняется, запас ${money(Math.abs(gap))}`;
  }
  return `
    <div class="goal-row">
      <input class="text-input" id="goal-amount" inputmode="numeric" placeholder="80000" value="${amount}" />
      <button class="primary" id="save-goal">Сохранить</button>
    </div>
    <p class="delta">${esc(status)}</p>
    <p class="hint">В группе: /цель 80000</p>`;
}

function renderSpikes() {
  const spikes = state.summary?.advice?.spikes || [];
  const recs = state.summary?.advice?.recs || [];
  if (!spikes.length && !recs.length) return "";
  let html = "";
  if (spikes.length) {
    html += `<h2 style="margin-top:18px">Сильно выросли</h2>`;
    html += spikes.map((row) => `
      <button type="button" class="ledger-row cat-hit" data-ops="expense" data-cat="${esc(row.name)}">
        <span class="name">${esc(row.name)} <span class="spike-tag">выросло</span></span>
        <span class="dots"></span>
        <span class="amt">+${money(row.diff)}</span>
      </button>`).join("");
  }
  if (recs.length) {
    html += `<h2 style="margin-top:18px">К цели</h2>`;
    html += `<ol class="recs">${recs.map((r) => `<li>${esc(r.text)}</li>`).join("")}</ol>`;
  }
  return html;
}

function renderReconcile(s) {
  const rec = s?.reconcile;
  if (!rec || (rec.stmt_income == null && rec.stmt_expense == null)) return "";
  const ok = rec.matched && s.bars_ok !== false;
  const hold = rec.book_holds ? ` · в обработке ${money(rec.book_holds)}` : "";
  const inc = rec.income_ok
    ? `доходы ${money(rec.stmt_income)}`
    : `доходы ${money(rec.book_income)} вместо ${money(rec.stmt_income)}`;
  const exp = rec.expense_ok
    ? `расходы ${money(rec.stmt_expense)}`
    : `расходы ${money(rec.book_expense)} вместо ${money(rec.stmt_expense)}`;
  const title = ok ? "Сверка с выпиской — совпадает" : "Сверка с выпиской — не сходится";
  return `
    <div class="reconcile ${ok ? "ok" : "bad"}">
      <div class="reconcile-title">${title}</div>
      <div>${inc} · ${exp}${hold}</div>
    </div>`;
}

function planAmount(kind, name) {
  const key = catKey(name);
  const map = (state.summary?.summary?.plans || {})[kind] || {};
  for (const [n, amt] of Object.entries(map)) {
    if (catKey(n) === key) return Number(amt) || 0;
  }
  return 0;
}

function renderBars(rows, max, bucket, total) {
  if (!rows || !rows.length) return "";
  const sum = total || rows.reduce((a, r) => a + r.amount, 0) || 1;
  return rows.map((row) => {
    const share = Math.round((row.amount / sum) * 100);
    const plan = planAmount(bucket, row.name);
    const amt = plan > 0 ? `${money(row.amount)} из ${money(plan)}` : money(row.amount);
    const hot = plan > 0 && row.amount / plan >= 0.8;
    const editing = state.planEdit
      && state.planEdit.kind === bucket
      && catKey(state.planEdit.name) === catKey(row.name);
    return `
    <div class="cat-line${hot ? " hot-plan" : ""}">
      <div class="cat-line-row">
        <button type="button" class="plan-gear${plan > 0 ? " has-plan" : ""}${editing ? " on" : ""}" data-plan="${bucket}" data-cat="${esc(row.name)}" aria-label="План">
          <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true"><path fill="currentColor" d="M19.14 12.94a7.4 7.4 0 0 0 .05-.94 7.4 7.4 0 0 0-.05-.94l2.03-1.58a.5.5 0 0 0 .12-.64l-1.92-3.32a.5.5 0 0 0-.6-.22l-2.39.96a7.2 7.2 0 0 0-1.63-.94l-.36-2.54a.5.5 0 0 0-.5-.42h-3.84a.5.5 0 0 0-.5.42l-.36 2.54c-.58.22-1.13.53-1.63.94l-2.39-.96a.5.5 0 0 0-.6.22L2.71 8.84a.5.5 0 0 0 .12.64l2.03 1.58a7.4 7.4 0 0 0-.05.94c0 .31.02.63.06.94l-2.03 1.58a.5.5 0 0 0-.12.64l1.92 3.32c.13.22.4.31.6.22l2.39-.96c.5.41 1.05.72 1.63.94l.36 2.54c.05.24.26.42.5.42h3.84c.24 0 .45-.18.5-.42l.36-2.54c.58-.22 1.13-.53 1.63-.94l2.39.96c.22.09.47 0 .6-.22l1.92-3.32a.5.5 0 0 0-.12-.64l-2.03-1.58zM12 15.5A3.5 3.5 0 1 1 12 8.5a3.5 3.5 0 0 1 0 7z"/></svg>
        </button>
        <button type="button" class="cat-hit" data-ops="${bucket}" data-cat="${esc(row.name)}" style="${catVars(row.name)}">
          <div class="ledger-row">
            <span class="cat-swatch" aria-hidden="true"></span>
            <span class="name">${esc(row.name)}</span>
            <span class="share">${share}%</span>
          </div>
          <div class="track"><div class="fill ${hot ? "warn" : "cat"}" style="width:${Math.max(6, (row.amount / max) * 100)}%"></div></div>
          <div class="cat-amt">${amt}</div>
        </button>
      </div>
    </div>
    ${editing ? planEditorHtml(bucket, row.name, plan) : ""}`;
  }).join("");
}

function planEditorHtml(kind, name, current) {
  const value = current > 0 ? String(Math.round(current)) : "";
  return `
    <div class="plan-edit">
      <p class="hint">Бюджет на ${esc((MONTHS[state.month] || "").toLowerCase())} · ${esc(name)}</p>
      <input class="text-input" id="plan-amount" inputmode="numeric" placeholder="100000" value="${esc(value)}" />
      <div class="plan-edit-actions">
        <button class="primary" type="button" id="save-plan">Сохранить</button>
        <button class="ghost" type="button" id="clear-plan">${current > 0 ? "Убрать план" : "Отмена"}</button>
      </div>
    </div>`;
}

function daysLeftLabel() {
  const last = new Date(state.year, state.month, 0).getDate();
  const today = new Date();
  if (today.getFullYear() !== state.year || today.getMonth() + 1 !== state.month) {
    return `${last} ${plural(last, "день", "дня", "дней")}`;
  }
  const left = last - today.getDate();
  if (left <= 0) return "последний день";
  return `ещё ${left} ${plural(left, "день", "дня", "дней")}`;
}

function bindLogin() {
  $("#login-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const password = new FormData(e.target).get("password");
    try {
      await api("/api/login", { method: "POST", body: { password } });
      await boot();
    } catch (err) {
      const box = $("#login-error");
      box.hidden = false;
      box.textContent = err.message === "unauthorized" ? "Неверный пароль" : (err.message || "Ошибка входа");
    }
  });
}

function bindHome() {
  $("#prev-month")?.addEventListener("click", () => shiftMonth(-1));
  $("#next-month")?.addEventListener("click", () => shiftMonth(1));
  $("#logout-btn")?.addEventListener("click", async () => { await api("/api/logout", { method: "POST" }); state.me.authed = false; render(); });
  $("#notify-btn")?.addEventListener("click", async () => {
    try {
      await api(`/api/notify?year=${state.year}&month=${state.month}`, { method: "POST" });
      state.notice = "Отчёт ушёл в Telegram-группу";
      render();
    } catch (err) {
      state.notice = "";
      alert(err.data?.detail || err.message || "Не удалось отправить");
    }
  });
  $("#save-goal")?.addEventListener("click", async () => {
    const raw = $("#goal-amount")?.value || "";
    try {
      await api("/api/goal", { method: "POST", body: { amount: raw, kind: "net" } });
      state.notice = "Цель сохранена";
      await loadSummary();
    } catch (err) {
      alert(err.data?.detail || err.message || "Не сохранилось");
    }
  });
  const drop = $("#drop");
  const file = $("#file");
  drop?.addEventListener("dragover", (e) => { e.preventDefault(); drop.classList.add("drag"); });
  drop?.addEventListener("dragleave", () => drop.classList.remove("drag"));
  drop?.addEventListener("drop", (e) => {
    e.preventDefault();
    drop.classList.remove("drag");
    if (e.dataTransfer.files[0]) upload(e.dataTransfer.files[0]);
  });
  file?.addEventListener("change", () => { if (file.files[0]) upload(file.files[0]); });
  $("#pull-drive")?.addEventListener("click", pullDrive);
  $("#open-stats")?.addEventListener("click", () => showStats());
  $("#cash-from-card")?.addEventListener("click", () => {
    state.cashPanel = state.cashPanel === "from-card" ? "" : "from-card";
    render();
  });
  $("#cash-expense")?.addEventListener("click", () => {
    state.cashPanel = state.cashPanel === "expense" ? "" : "expense";
    render();
  });
  $("#save-cash")?.addEventListener("click", saveCash);
  $("#cash-cat")?.addEventListener("input", () => {
    state.cashCat = $("#cash-cat").value;
    paintCashChips($("#cash-cat"));
  });
  document.querySelectorAll("[data-cash-cat]").forEach((el) => {
    el.addEventListener("click", () => {
      const name = el.getAttribute("data-cash-cat") || "";
      const box = el.closest(".cash-form");
      const input = box?.querySelector("#cash-cat, #cash-edit-cat");
      if (input?.id === "cash-cat") state.cashCat = name;
      if (input) input.value = name;
      paintCashChips(input);
    });
  });
  document.querySelectorAll("[data-cash-edit]").forEach((el) => {
    el.addEventListener("click", () => {
      const id = el.getAttribute("data-cash-edit");
      state.cashEdit = String(state.cashEdit) === String(id) ? null : id;
      render();
      $("#cash-edit-cat")?.focus();
    });
  });
  $("#save-cash-edit")?.addEventListener("click", saveCashEdit);
  document.querySelectorAll("[data-cash-del]").forEach((el) => {
    el.addEventListener("click", () => deleteCash(el.getAttribute("data-cash-del")));
  });
  $("#edit-cash")?.addEventListener("click", () => {
    state.cashPanel = state.cashPanel === "balance" ? "" : "balance";
    render();
  });
  $("#save-cash-balance")?.addEventListener("click", saveCashBalance);
  document.querySelectorAll("[data-plan]").forEach((el) => {
    el.addEventListener("click", (event) => {
      event.stopPropagation();
      const kind = el.getAttribute("data-plan");
      const name = el.getAttribute("data-cat");
      const same = state.planEdit && state.planEdit.kind === kind && catKey(state.planEdit.name) === catKey(name);
      state.planEdit = same ? null : { kind, name };
      render();
      $("#plan-amount")?.focus();
    });
  });
  $("#save-plan")?.addEventListener("click", () => savePlan(false));
  $("#clear-plan")?.addEventListener("click", () => savePlan(true));
  document.querySelectorAll("[data-focus]").forEach((el) => {
    el.addEventListener("click", () => {
      state.view = el.getAttribute("data-focus") === "income" ? "focus-income" : "focus-expense";
      render();
      commitRoute();
    });
  });
  bindOpsHits();
  bindEditHits();
}

function focusIncomeView() {
  const current = chosenIncome();
  const shown = current == null ? "" : String(Math.round(current));
  return `
    <div class="app-shell">
      <div class="topbar">
        <button class="ghost" id="focus-back">Назад</button>
        <div class="brand">Касса</div>
      </div>
      <h1 class="queue-title serif">Доход</h1>
      <p class="hint">Сумма, с которой считать сальдо месяца. Это не цифра из выписки.</p>
      <section class="card">
        <input class="text-input" id="focus-income" inputmode="decimal" placeholder="1500000" value="${esc(shown)}" />
        <button class="primary" id="save-focus-income" style="width:100%;margin-top:12px">Сохранить</button>
        <div class="error" id="focus-error" hidden></div>
      </section>
      ${tabBar()}
    </div>`;
}

function focusExpenseView() {
  const picked = chosenExpenseNames();
  const rows = expenseCatalog();
  const list = rows.length
    ? rows.map((row) => {
        const on = picked.some((name) => catKey(name) === catKey(row.name));
        const spent = actualExpense(row.name);
        const plan = planAmount("expense", row.name);
        const shown = spent > 0 ? money(spent) : (plan > 0 ? `план ${money(plan)}` : money(0));
        return `
        <label class="check-row" style="${catVars(row.name)}">
          <input type="checkbox" data-exp="${esc(row.name)}" ${on ? "checked" : ""} />
          <span class="cat-swatch" aria-hidden="true"></span>
          <span class="name">${esc(row.name)}</span>
          <span class="amt">${shown}</span>
        </label>`;
      }).join("")
    : `<p class="empty">В этом месяце нет статей расходов</p>`;
  return `
    <div class="app-shell">
      <div class="topbar">
        <button class="ghost" id="focus-back">Назад</button>
        <div class="brand">Касса</div>
      </div>
      <h1 class="queue-title serif">Расходы в сальдо</h1>
      <p class="hint">Отмеченные статьи переходят на следующий месяц. Пока по статье нет трат, в сумму идёт план. С выпиской эта сумма не сверяется.</p>
      <section class="card">
        ${list}
        <p class="delta" id="focus-exp-sum"></p>
        <button class="primary" id="save-focus-expense" style="width:100%;margin-top:12px">Сохранить</button>
        <div class="error" id="focus-error" hidden></div>
      </section>
      ${tabBar()}
    </div>`;
}

function paintFocusExpenseSum() {
  const box = $("#focus-exp-sum");
  if (!box) return;
  const names = new Set(
    [...document.querySelectorAll("[data-exp]:checked")].map((el) => el.getAttribute("data-exp"))
  );
  const sum = [...names].reduce((acc, name) => acc + saldoArticleAmount(name), 0);
  box.textContent = `В сальдо: ${money(sum)}`;
}

function bindFocusIncome() {
  $("#focus-back")?.addEventListener("click", () => goBack());
  $("#save-focus-income")?.addEventListener("click", async () => {
    const raw = $("#focus-income")?.value || "";
    const box = $("#focus-error");
    try {
      await api("/api/focus", {
        method: "POST",
        body: { year: state.year, month: state.month, income: raw },
      });
      state.notice = "Доход сохранён";
      await goHome({ history: false });
      commitRoute({ replace: true });
    } catch (err) {
      if (box) {
        box.hidden = false;
        box.textContent = err.data?.detail || err.message || "Не сохранилось";
      }
    }
  });
}

function bindFocusExpense() {
  $("#focus-back")?.addEventListener("click", () => goBack());
  paintFocusExpenseSum();
  document.querySelectorAll("[data-exp]").forEach((el) => {
    el.addEventListener("change", paintFocusExpenseSum);
  });
  $("#save-focus-expense")?.addEventListener("click", async () => {
    const expenses = [...document.querySelectorAll("[data-exp]:checked")]
      .map((el) => el.getAttribute("data-exp"))
      .filter(Boolean);
    const box = $("#focus-error");
    try {
      await api("/api/focus", {
        method: "POST",
        body: { year: state.year, month: state.month, expenses },
      });
      state.notice = "Статьи расходов сохранены";
      await goHome({ history: false });
      commitRoute({ replace: true });
    } catch (err) {
      if (box) {
        box.hidden = false;
        box.textContent = err.data?.detail || err.message || "Не сохранилось";
      }
    }
  });
}

function bindOpsHits() {
  document.querySelectorAll("[data-ops]").forEach((el) => {
    el.addEventListener("click", () => {
      if (el.disabled) return;
      showOps(el.getAttribute("data-ops"), el.getAttribute("data-cat") || "");
    });
  });
}

function bindOps() {
  $("#ops-back")?.addEventListener("click", () => goBack());
  bindEditHits();
  document.querySelectorAll("[data-apply-desc]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const cat = (state.ops?.category || "").trim();
      const box = $("#apply-desc-error");
      if (!cat) return;
      const kind = state.ops?.bucket === "income" ? "income" : "expense";
      try {
        const res = await api(`/api/transactions/${btn.getAttribute("data-apply-desc")}/apply-description`, {
          method: "POST",
          body: { user_category: cat, kind },
        });
        state.notice = `«${shortDesc(res.description, 36)}»: ${cat} · ${res.count} ${plural(res.count, "операция", "операции", "операций")}`;
        await loadSummary();
        await showOps(state.ops.bucket, cat);
      } catch (err) {
        if (box) {
          box.hidden = false;
          box.textContent = err.data?.detail || err.message || "Не удалось отнести по описанию";
        }
      }
    });
  });
  $("#rename-cat-btn")?.addEventListener("click", async () => {
    const oldName = state.ops?.category || "";
    const newName = ($("#rename-cat")?.value || "").trim();
    const box = $("#rename-error");
    if (!newName) {
      if (box) { box.hidden = false; box.textContent = "Напишите новое название"; }
      return;
    }
    try {
      const res = await api("/api/categories/rename", {
        method: "POST",
        body: { old_name: oldName, new_name: newName, kind: state.ops?.bucket },
      });
      state.notice = `Статья «${oldName}» → «${newName}» · ${res.count || 0} ${plural(res.count || 0, "операция", "операции", "операций")}`;
      await loadSummary();
      await showOps(state.ops.bucket, newName);
    } catch (err) {
      if (box) {
        box.hidden = false;
        box.textContent = err.data?.detail || err.message || "Не переименовалось";
      }
    }
  });
}

function bindEditHits() {
  document.querySelectorAll("[data-edit]").forEach((el) => {
    el.addEventListener("click", () => openEditOp(el.getAttribute("data-edit")));
  });
}

function opKind(t) {
  if (t?.is_internal || t?.kind === "transfer") return "transfer";
  if (Number(t?.amount) > 0) return "income";
  if (t?.kind === "income") return "income";
  return "expense";
}

async function openEditOp(id, opts = {}) {
  const fromOps = (state.ops?.transactions || []).find((t) => String(t.id) === String(id));
  const fromUnlabeled = (state.summary?.summary?.unlabeled || []).find((t) => String(t.id) === String(id));
  let tx = fromOps || fromUnlabeled;
  state.editFrom = (fromOps || state.view === "ops") ? "ops"
    : (state.view === "queue" || state.view === "review" ? "queue" : "home");
  try {
    if (!tx) {
      const res = await api(`/api/transactions/${id}`);
      tx = res.transaction;
    }
    if (!state.review?.categories) {
      state.review = await api("/api/review");
    }
    state.editOp = tx;
    state.view = "edit-op";
    render();
    if (opts.history !== false) commitRoute();
  } catch (err) {
    alert(err.data?.detail || err.message || "Не удалось открыть операцию");
  }
}

function bindEditOp() {
  $("#edit-back")?.addEventListener("click", () => goBack());
  const t = state.editOp;
  if (!t) return;
  const cats = state.review?.categories || { expense: [], income: [] };
  const chips = $("#edit-chips");
  const input = $("#edit-cat");
  let mode = opKind(t);
  let chosen = currentCat(t);

  const paintChips = () => {
    const list = [...new Set([
      ...(mode === "income" ? cats.income : cats.expense),
      chosen,
    ].filter((name) => name && name !== "Переводы без разметки" && name !== "Не разобрано"))];
    chips.innerHTML = list.map((name) => chipHtml(name, chosen, mode !== "income")).join("");
    chips.querySelectorAll(".chip").forEach((btn) => {
      btn.addEventListener("click", () => {
        chosen = btn.dataset.cat;
        input.value = chosen;
        paintChips();
      });
    });
  };

  const setMode = (next) => {
    mode = next;
    document.querySelectorAll("[data-mode]").forEach((b) => {
      b.className = b.dataset.mode === mode ? "primary" : "ghost";
    });
    paintChips();
  };
  document.querySelectorAll("[data-mode]").forEach((b) => {
    b.addEventListener("click", () => setMode(b.dataset.mode));
  });
  input.addEventListener("input", () => {
    chosen = input.value.trim();
    paintChips();
  });
  setMode(mode);

  const afterEditSave = async (notice) => {
    state.notice = notice;
    const from = state.editFrom;
    const ops = state.ops;
    state.editOp = null;
    const [summary, review] = await Promise.all([
      api(`/api/summary?year=${state.year}&month=${state.month}`),
      api("/api/review"),
    ]);
    state.summary = summary;
    state.review = review;
    if (from === "ops" && ops) {
      const nextCat = (input.value || "").trim() || ops.category;
      await showOps(ops.bucket, nextCat, { history: false });
    } else if (from === "queue") {
      await showQueue({ history: false });
    } else {
      await goHome({ history: false });
    }
    commitRoute({ replace: true });
  };

  $("#save-cat").addEventListener("click", async () => {
    const user_category = input.value.trim() || chosen;
    const box = $("#edit-error");
    if (!user_category) {
      box.hidden = false;
      box.textContent = "Напишите или выберите статью";
      return;
    }
    try {
      await api(`/api/transactions/${t.id}/category`, {
        method: "POST",
        body: { kind: mode, user_category },
      });
      await afterEditSave(`Статья: ${user_category}`);
    } catch (err) {
      box.hidden = false;
      box.textContent = err.data?.detail || err.message || "Не сохранилось";
    }
  });

  $("#apply-mcc")?.addEventListener("click", async () => {
    const user_category = input.value.trim() || chosen;
    const box = $("#edit-error");
    if (!user_category) {
      box.hidden = false;
      box.textContent = "Сначала напишите или выберите статью";
      return;
    }
    try {
      const res = await api(`/api/transactions/${t.id}/apply-mcc`, {
        method: "POST",
        body: { kind: mode, user_category },
      });
      await afterEditSave(`Код MCC ${res.mcc}: ${user_category} · ${res.count} ${plural(res.count, "операция", "операции", "операций")}`);
    } catch (err) {
      box.hidden = false;
      box.textContent = err.data?.detail || err.message || "Не удалось отнести по коду";
    }
  });

  $("#apply-desc")?.addEventListener("click", async () => {
    const user_category = input.value.trim() || chosen;
    const box = $("#edit-error");
    if (!user_category) {
      box.hidden = false;
      box.textContent = "Сначала напишите или выберите статью";
      return;
    }
    try {
      const res = await api(`/api/transactions/${t.id}/apply-description`, {
        method: "POST",
        body: { kind: mode, user_category },
      });
      await afterEditSave(
        `«${res.description}»: ${user_category} · ${res.count} ${plural(res.count, "операция", "операции", "операций")}`
      );
    } catch (err) {
      box.hidden = false;
      box.textContent = err.data?.detail || err.message || "Не удалось отнести по описанию";
    }
  });

  $("#rename-article")?.addEventListener("click", async () => {
    const newName = input.value.trim() || chosen;
    const oldName = currentCat(t);
    const box = $("#edit-error");
    if (!newName) {
      box.hidden = false;
      box.textContent = "Напишите новое название статьи";
      return;
    }
    try {
      const res = await api("/api/categories/rename", {
        method: "POST",
        body: { old_name: oldName, new_name: newName, kind: mode },
      });
      if (state.ops?.category === oldName) state.ops.category = newName;
      await afterEditSave(`Статья «${oldName}» → «${newName}» · ${res.count || 0} ${plural(res.count || 0, "операция", "операции", "операций")}`);
    } catch (err) {
      box.hidden = false;
      box.textContent = err.data?.detail || err.message || "Не переименовалось";
    }
  });
}

async function showOps(bucket, category, opts = {}) {
  const cat = (category || "").trim();
  const title = cat || (bucket === "income" ? "Доходы" : "Расходы");
  state.view = "ops";
  state.editOp = null;
  state.ops = { bucket, category: cat, title, transactions: [], sum: 0, loading: true };
  render();
  if (opts.history !== false) commitRoute();
  const q = new URLSearchParams({
    year: String(state.year),
    month: String(state.month),
    bucket,
    limit: "2000",
  });
  if (cat) q.set("category", cat);
  try {
    const res = await api(`/api/transactions?${q}`);
    state.ops = {
      bucket,
      category: cat,
      title,
      transactions: res.transactions || [],
      sum: res.sum || 0,
      loading: false,
    };
  } catch (err) {
    state.ops = { bucket, category: cat, title, transactions: [], sum: 0, loading: false };
    state.notice = err.data?.detail || err.message || "Не удалось открыть операции";
  }
  if (state.view === "ops") render();
}

async function goHome(opts = {}) {
  state.view = "home";
  state.reviewId = null;
  state.ops = null;
  state.editOp = null;
  render();
  if (opts.history !== false) commitRoute();
  await loadSummary();
}

async function showQueue(opts = {}) {
  state.view = "queue";
  state.reviewId = null;
  state.editOp = null;
  render();
  if (opts.history !== false) commitRoute();
  try {
    await fetchSummary();
  } catch (err) {
    state.notice = err.data?.detail || err.message || "Не удалось открыть очередь";
  }
  if (state.view === "queue") render();
}

function bindAppClicks() {
  if (app.dataset.navBound) return;
  app.dataset.navBound = "1";
  app.addEventListener("click", (e) => {
    const nav = e.target.closest("[data-nav]");
    if (!nav) return;
    e.preventDefault();
    if (nav.getAttribute("data-nav") === "home") goHome();
    else if (nav.getAttribute("data-nav") === "stats") showStats();
    else if (nav.getAttribute("data-nav") === "queue") showQueue();
  });
  window.addEventListener("popstate", (e) => {
    const route = e.state?.route || routeFromUrl() || {
      view: "home",
      year: state.year,
      month: state.month,
      opsBucket: "",
      opsCategory: "",
      editOpId: "",
      editFrom: "home",
      reviewId: "",
    };
    restoreRoute(route);
  });
}

async function acceptAllIncome() {
  const n = pendingIncome(state.review?.transactions).length;
  if (!n) {
    alert("В очереди нет входящих переводов");
    return;
  }
  if (!confirm("Все плюсовые операции станут доходом. Минусовые останутся в очереди.")) return;
  try {
    const res = await api("/api/review/income", { method: "POST" });
    state.notice = res.count
      ? `${res.count} ${plural(res.count, "перевод", "перевода", "переводов")} зачислены в доходы`
      : "Плюсовых в очереди нет";
    if (res.telegram_sent) state.notice += " · отчёт в Telegram";
    state.reviewId = null;
    await showQueue();
  } catch (err) {
    alert(err.data?.detail || err.message || "Не сохранилось");
  }
}

function bindAcceptIncome() {
  $("#accept-income-all")?.addEventListener("click", () => acceptAllIncome());
}

function bindQueue() {
  document.querySelectorAll("[data-open]").forEach((el) => {
    el.addEventListener("click", () => {
      state.reviewId = el.getAttribute("data-open");
      state.view = "review";
      if (state.review?.count) render();
      else loadReview();
      commitRoute();
    });
  });
  $("#unlabel-all")?.addEventListener("click", async () => {
    if (!confirm("Все неразобранные уйдут в «Переводы без разметки»?")) return;
    try {
      const res = await api("/api/review/unlabeled", { method: "POST", body: {} });
      state.notice = res.count
        ? `${res.count} ${plural(res.count, "перевод", "перевода", "переводов")} без разметки`
        : "Очередь уже пуста";
      if (res.telegram_sent) state.notice += " · отчёт в Telegram";
      await showQueue();
    } catch (err) {
      alert(err.data?.detail || err.message || "Не сохранилось");
    }
  });
  bindAcceptIncome();
  bindEditHits();
}

function bindReview() {
  bindAcceptIncome();
  const card = $("#review-card");
  if (!card) return;
  const items = state.review?.transactions || [];
  const current = items.find((t) => String(t.id) === String(card.dataset.id)) || items[0];
  let mode = current?.kind === "income" ? "income"
    : current?.kind === "transfer" || current?.is_internal ? "transfer"
    : "expense";
  const cats = state.review?.categories || { expense: [], income: [] };
  const catBox = $("#cat-box");
  const chips = $("#chips");
  let chosen = "";

  const paintChips = () => {
    const list = (mode === "income" ? cats.income : cats.expense)
      .filter((name) => name !== "Переводы без разметки" && name !== "Не разобрано");
    chips.innerHTML = list.map((name) => chipHtml(name, chosen, mode !== "income")).join("");
    chips.querySelectorAll(".chip").forEach((btn) => {
      btn.addEventListener("click", () => {
        chosen = btn.dataset.cat;
        $("#custom-cat").value = "";
        paintChips();
      });
    });
  };

  const setMode = (next) => {
    mode = next;
    card.querySelectorAll("[data-mode]").forEach((b) => {
      b.className = b.dataset.mode === mode ? "primary" : "ghost";
    });
    catBox.hidden = mode === "transfer";
    if (mode !== "transfer") paintChips();
  };
  card.querySelectorAll("[data-mode]").forEach((b) => b.addEventListener("click", () => setMode(b.dataset.mode)));
  const inflow = Number(current?.amount) > 0;
  if (inflow && mode === "expense") mode = "income";
  setMode(mode);

  $("#save-review").addEventListener("click", async () => {
    const note = $("#note").value.trim();
    const custom = $("#custom-cat")?.value.trim();
    const user_category = mode === "transfer" ? "Между своими" : (custom || chosen);
    if (mode !== "transfer" && !user_category) {
      const box = $("#review-error");
      box.hidden = false;
      box.textContent = "Выберите или введите статью";
      return;
    }
    try {
      const res = await api(`/api/transactions/${card.dataset.id}/review`, {
        method: "POST",
        body: {
          kind: mode,
          is_internal: mode === "transfer",
          user_category,
          user_note: note,
        },
      });
      if (res.telegram_sent) state.notice = "Все переводы разнесены · отчёт в Telegram";
      await loadReview();
    } catch (err) {
      const box = $("#review-error");
      box.hidden = false;
      box.textContent = err.message || "Не сохранилось";
    }
  });
  $("#apply-desc")?.addEventListener("click", async () => {
    const custom = $("#custom-cat")?.value.trim();
    const user_category = custom || chosen;
    const box = $("#review-error");
    if (mode === "transfer") {
      box.hidden = false;
      box.textContent = "Сначала выберите расход или доход";
      return;
    }
    if (!user_category) {
      box.hidden = false;
      box.textContent = "Выберите или введите статью";
      return;
    }
    try {
      const res = await api(`/api/transactions/${card.dataset.id}/apply-description`, {
        method: "POST",
        body: { kind: mode, user_category, user_note: $("#note")?.value.trim() || "" },
      });
      state.notice = `«${res.description}»: ${user_category} · ${res.count} ${plural(res.count, "операция", "операции", "операций")}`;
      state.reviewId = null;
      await loadReview();
    } catch (err) {
      box.hidden = false;
      box.textContent = err.data?.detail || err.message || "Не удалось отнести по описанию";
    }
  });
  $("#leave-unlabeled")?.addEventListener("click", async () => {
    try {
      const res = await api("/api/review/unlabeled", {
        method: "POST",
        body: { id: Number(card.dataset.id) },
      });
      state.reviewId = null;
      if (res.telegram_sent) state.notice = "Очередь пуста · отчёт в Telegram";
      await loadReview();
    } catch (err) {
      const box = $("#review-error");
      box.hidden = false;
      box.textContent = err.message || "Не сохранилось";
    }
  });
}

async function pullDrive() {
  const errBox = $("#upload-error");
  const btn = $("#pull-drive");
  if (btn) btn.disabled = true;
  if (errBox) errBox.hidden = true;
  try {
    const res = await api("/api/pull-drive", { method: "POST" });
    const n = res.new_count ?? 0;
    const dups = res.dup_count ?? 0;
    const newest = res.newest || {};
    state.notice = n
      ? `С Диска: +${n} операций` + (dups ? `, уже были: ${dups}` : "")
      : dups
        ? "На Диске нет новых операций — статьи перепроверены"
        : "В папке пока нет выписок";
    const rec = (res.files || []).map((f) => f.reconcile).find(Boolean) || res.reconcile;
    if (rec && rec.matched === false) {
      state.notice += rec.expense_ok === false
        ? ` · расходы не сходятся на ${money(Math.abs(rec.expense_delta || 0))}`
        : ` · доходы не сходятся на ${money(Math.abs(rec.income_delta || 0))}`;
    } else if (rec && rec.matched) {
      state.notice += " · итоги как в выписке";
    }
    if (newest.period_to) {
      const [y, m] = newest.period_to.split("-");
      state.year = Number(y);
      state.month = Number(m);
    } else if (res.year && res.month) {
      state.year = res.year;
      state.month = res.month;
    }
    if (res.review_count) {
      state.view = "review";
      await loadReview();
      commitRoute();
      return;
    }
    await loadSummary();
    commitRoute({ replace: true });
  } catch (err) {
    if (errBox) {
      errBox.hidden = false;
      errBox.textContent = err.data?.detail || err.message || "Не удалось забрать с Диска";
    }
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function upload(file) {
  const errBox = $("#upload-error");
  if (errBox) { errBox.hidden = true; }
  const body = new FormData();
  body.append("file", file);
  try {
    const res = await api("/api/import", { method: "POST", body });
    const n = res.import?.new_count ?? 0;
    const dups = res.import?.dup_count ?? 0;
    state.notice = `Добавлено ${n} операций` + (dups ? `, уже были и перепроверены: ${dups}` : "");
    if (res.telegram_sent) state.notice += " · отчёт в Telegram";
    const rec = res.import?.reconcile;
    if (rec && rec.matched === false) {
      state.notice += rec.expense_ok === false
        ? ` · расходы не сходятся на ${money(Math.abs(rec.expense_delta || 0))}`
        : ` · доходы не сходятся на ${money(Math.abs(rec.income_delta || 0))}`;
    } else if (rec && rec.matched) {
      state.notice += " · итоги как в выписке";
    }
    if (res.import?.review_count) {
      state.view = "review";
      await loadReview();
      commitRoute();
      return;
    }
    await loadSummary();
    commitRoute({ replace: true });
  } catch (err) {
    if (errBox) {
      errBox.hidden = false;
      errBox.textContent = err.data?.detail || err.message || "Не удалось прочитать файл";
    }
  }
}

async function fetchSummary() {
  const [summary, review] = await Promise.all([
    api(`/api/summary?year=${state.year}&month=${state.month}`),
    api("/api/review"),
  ]);
  state.summary = summary;
  state.review = review;
}

async function loadSummary() {
  try {
    await fetchSummary();
  } catch (err) {
    state.notice = err.data?.detail || err.message || "Не удалось загрузить сводку";
  }
  render();
}

async function loadReview() {
  try {
    state.review = await api("/api/review");
  } catch (err) {
    state.notice = err.data?.detail || err.message || "Не удалось загрузить очередь";
    state.view = "queue";
    render();
    return;
  }
  if (!state.review.count) {
    state.view = "queue";
    await loadSummary();
    return;
  }
  if (state.reviewId && !state.review.transactions.some((t) => String(t.id) === String(state.reviewId))) {
    state.reviewId = null;
  }
  render();
}

async function shiftMonth(delta) {
  const d = new Date(state.year, state.month - 1 + delta, 1);
  state.year = d.getFullYear();
  state.month = d.getMonth() + 1;
  await loadSummary();
  commitRoute();
}

async function boot() {
  try {
    state.me = await api("/api/me");
  } catch (err) {
    if (err.status === 401) {
      state.me = { authed: false, auth_required: true };
      render();
      return;
    }
    throw err;
  }
  if (!state.me.authed) {
    render();
    return;
  }
  const fromUrl = routeFromUrl();
  historyReady = true;
  if (fromUrl) {
    history.replaceState({ kassa: 1, route: fromUrl }, "", buildRouteUrl(fromUrl));
    await restoreRoute(fromUrl);
    return;
  }
  await loadSummary();
  commitRoute({ replace: true });
}

function cmp(cur, prev) {
  const diff = cur - prev;
  if (Math.abs(diff) < 1) return "без изменений";
  return (diff > 0 ? "больше на " : "меньше на ") + money(Math.abs(diff));
}

function plural(n, one, few, many) {
  const n100 = Math.abs(n) % 100;
  if (n100 > 10 && n100 < 20) return many;
  const n10 = n100 % 10;
  if (n10 === 1) return one;
  if (n10 >= 2 && n10 <= 4) return few;
  return many;
}

function fmtDate(iso) {
  const [y, m, d] = iso.split("-");
  const months = ["января","февраля","марта","апреля","мая","июня","июля","августа","сентября","октября","ноября","декабря"];
  return `${Number(d)} ${months[Number(m) - 1]}`;
}

function esc(s) {
  return String(s ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function todayISO() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function cashWallet(s) {
  const cash = s?.wallets?.cash?.amount;
  const cls = cash == null ? "" : (cash >= 0 ? "pos" : "neg");
  const editing = state.cashPanel === "balance";
  return `
    <div class="wallet-row">
      <div>
        <div class="label">Наличные</div>
        <p class="wallet-amt serif ${cls}">${cash == null ? "—" : money(cash)}</p>
      </div>
      <button type="button" class="ghost wallet-edit" id="edit-cash">Изменить</button>
    </div>
    ${editing ? `
      <div class="cash-form">
        <input class="text-input" id="cash-balance" inputmode="decimal" placeholder="Сколько сейчас в кошельке" value="${cash == null ? "" : cash}" />
        <button class="primary" type="button" id="save-cash-balance">Записать остаток</button>
        <p class="hint">Разница спишется или прибавится статьёй «Х.з».</p>
      </div>` : ""}`;
}

function cashCategoryNames() {
  const skip = new Set(["между своими", "не разобрано", "переводы без разметки", "в наличные"]);
  const seen = new Set();
  const names = [];
  const add = (name) => {
    const text = String(name || "").trim();
    const key = catKey(text);
    if (!text || seen.has(key) || skip.has(key)) return;
    seen.add(key);
    names.push(text);
  };
  for (const name of state.summary?.categories?.expense || []) add(name);
  for (const row of expenseCatalog()) add(row.name);
  for (const op of state.summary?.summary?.cash_ops || []) {
    if (op.kind === "expense") add(op.user_category);
  }
  add(state.cashCat);
  return names;
}

function cashCatChips(chosen) {
  return cashCategoryNames().map((name) => {
    const on = catKey(chosen) === catKey(name) ? " on" : "";
    return `<button type="button" class="chip tinted${on}" data-cash-cat="${esc(name)}" style="${catVars(name)}">${esc(name)}</button>`;
  }).join("");
}

function cashPanelForm() {
  const panel = state.cashPanel;
  if (panel !== "from-card" && panel !== "expense") return "";
  const chips = panel === "expense" ? cashCatChips(state.cashCat) : "";
  return `
    <div class="cash-form">
      <input class="text-input" id="cash-amount" inputmode="decimal" placeholder="Сумма" />
      <label class="label" for="cash-date">Дата</label>
      <input class="text-input" id="cash-date" type="date" value="${todayISO()}" />
      ${panel === "expense" ? `
        <label class="label" for="cash-cat">Статья</label>
        <input class="text-input" id="cash-cat" placeholder="Выберите или напишите статью" value="${esc(state.cashCat || "")}" />
        <div class="chips">${chips}</div>
      ` : ""}
      <input class="text-input" id="cash-note" placeholder="Заметка" />
      <button class="primary" id="save-cash" type="button">${panel === "expense" ? "Списать" : "Внести"}</button>
      <div class="error" id="cash-error" hidden></div>
    </div>`;
}

function cashEditForm(t) {
  const cat = t.user_category || "";
  const expense = t.kind === "expense";
  return `
    <div class="cash-form">
      <label class="label" for="cash-edit-date">Дата</label>
      <input class="text-input" id="cash-edit-date" type="date" value="${esc((t.posted_date || todayISO()).slice(0, 10))}" />
      <input class="text-input" id="cash-edit-amount" inputmode="decimal" value="${esc(String(Math.abs(Number(t.amount) || 0)))}" />
      ${expense ? `
        <label class="label" for="cash-edit-cat">Статья</label>
        <input class="text-input" id="cash-edit-cat" placeholder="Статья" value="${esc(cat)}" />
        <div class="chips" id="cash-edit-chips">${cashCatChips(cat)}</div>
      ` : `<p class="hint">Поступление в наличные. Дату можно перенести на другой день.</p>`}
      <input class="text-input" id="cash-edit-note" placeholder="Заметка" value="${esc(t.note || "")}" />
      <button class="primary" id="save-cash-edit" type="button">Сохранить</button>
      <div class="error" id="cash-edit-error" hidden></div>
    </div>`;
}

function cashOpsList(s) {
  const rows = (s?.cash_ops || []).filter((t) => t.kind === "expense" || t.kind === "from_card");
  if (!rows.length) return "";
  return `
    <div class="cash-ops">
      <div class="label">Наличные за месяц</div>
      ${rows.map((t) => {
        const editing = String(state.cashEdit) === String(t.cash_id);
        const open = `<button type="button" class="tx-row" data-cash-edit="${t.cash_id}">`;
        const close = `</button>`;
        return `
        <div class="cash-op">
          <div class="cash-op-head">
            ${open}
              <div>
                <div class="tx-desc">${esc(t.description || (t.kind === "expense" ? "Оплата наличными" : "Наличные"))}</div>
                <div class="tx-sub">${esc([
                  fmtDate(t.posted_date),
                  t.user_category,
                  t.kind === "expense" ? "оплата наличными" : "",
                ].filter(Boolean).join(" · "))}</div>
              </div>
              <div class="tx-amt ${t.amount < 0 ? "neg" : "pos"}">${money(t.amount, true)}</div>
            ${close}
            <button type="button" class="ghost" data-cash-del="${t.cash_id}">×</button>
          </div>
          ${editing ? cashEditForm(t) : ""}
        </div>`;
      }).join("")}
    </div>`;
}

function paintCashChips(input) {
  const box = input?.closest(".cash-form");
  if (!box) return;
  const current = catKey(input.value || "");
  box.querySelectorAll("[data-cash-cat]").forEach((chip) => {
    chip.classList.toggle("on", catKey(chip.getAttribute("data-cash-cat")) === current && current !== "");
  });
}

async function saveCashEdit() {
  const id = state.cashEdit;
  const box = $("#cash-edit-error");
  const amount = $("#cash-edit-amount")?.value || "";
  const posted_date = $("#cash-edit-date")?.value || todayISO();
  const note = $("#cash-edit-note")?.value || "";
  const catInput = $("#cash-edit-cat");
  const category = (catInput?.value || "").trim();
  if (catInput && !category) {
    if (box) {
      box.hidden = false;
      box.textContent = "Выберите или напишите статью";
    }
    return;
  }
  if (!posted_date) {
    if (box) {
      box.hidden = false;
      box.textContent = "Укажите дату";
    }
    return;
  }
  try {
    await api(`/api/cash/${id}`, {
      method: "POST",
      body: { amount, category, posted_date, note },
    });
    state.cashEdit = null;
    state.notice = "Дата сохранена";
    await loadSummary();
  } catch (err) {
    if (box) {
      box.hidden = false;
      box.textContent = err.data?.detail || err.message || "Не сохранилось";
    }
  }
}

async function saveCash() {
  const box = $("#cash-error");
  const amount = $("#cash-amount")?.value || "";
  const posted_date = $("#cash-date")?.value || todayISO();
  const note = $("#cash-note")?.value || "";
  const category = $("#cash-cat")?.value || state.cashCat || "";
  try {
    if (state.cashPanel === "expense") {
      await api("/api/cash/expense", { method: "POST", body: { amount, category, posted_date, note } });
      state.notice = "Расход наличными записан";
    } else {
      await api("/api/cash/from-card", { method: "POST", body: { amount, posted_date, note } });
      state.notice = "Наличные внесены";
    }
    state.cashPanel = "";
    await loadSummary();
  } catch (err) {
    if (box) {
      box.hidden = false;
      box.textContent = err.data?.detail || err.message || "Не сохранилось";
    }
  }
}

async function saveCashBalance() {
  const amount = $("#cash-balance")?.value || "";
  try {
    await api("/api/cash/balance", { method: "POST", body: { amount, dest: "hz", posted_date: todayISO() } });
    state.cashPanel = "";
    state.notice = "Остаток наличных записан";
    await loadSummary();
  } catch (err) {
    alert(err.data?.detail || err.message || "Не сохранилось");
  }
}

async function deleteCash(id) {
  if (!id || !confirm("Удалить эту операцию наличных?")) return;
  try {
    await api(`/api/cash/${id}`, { method: "DELETE" });
    state.notice = "Операция наличных удалена";
    await loadSummary();
  } catch (err) {
    alert(err.data?.detail || err.message || "Не удалось удалить");
  }
}

async function savePlan(clear) {
  const edit = state.planEdit;
  if (!edit) return;
  if (clear && !planAmount(edit.kind, edit.name)) {
    state.planEdit = null;
    render();
    return;
  }
  const amount = clear ? 0 : ($("#plan-amount")?.value || "");
  try {
    const res = await api("/api/plans", {
      method: "POST",
      body: { year: state.year, month: state.month, kind: edit.kind, name: edit.name, amount },
    });
    if (state.summary?.summary) state.summary.summary.plans = res.plans || { expense: {}, income: {} };
    state.planEdit = null;
    state.notice = clear || Number(String(amount).replace(/\s/g, "")) === 0
      ? `План «${edit.name}» убран`
      : `План «${edit.name}» сохранён`;
    render();
  } catch (err) {
    alert(err.data?.detail || err.message || "Не сохранилось");
  }
}

function shortMonth(title, ym) {
  const m = Number(String(ym || "").slice(5, 7));
  const names = ["", "янв", "фев", "мар", "апр", "май", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"];
  return names[m] || String(title || "").slice(0, 3).toLowerCase();
}

function chartMax(values) {
  const nums = values.map(Number).filter((n) => Number.isFinite(n));
  const peak = Math.max(0, ...nums.map(Math.abs), 1);
  return peak;
}

function barChart(points, valueKey, { signed = false, color = "var(--ink)" } = {}) {
  const vals = points.map((p) => Number(p[valueKey] || 0));
  const peak = chartMax(vals);
  const w = Math.max(280, points.length * 28);
  const h = 150;
  const pad = 18;
  const plotH = h - pad * 2;
  const plotW = w - 16;
  const zeroY = pad + plotH / 2;
  const step = plotW / Math.max(points.length, 1);
  const bars = points.map((p, i) => {
    const v = Number(p[valueKey] || 0);
    const bh = (Math.abs(v) / peak) * (plotH / 2);
    const x = 8 + i * step + step * 0.2;
    const bw = Math.max(4, step * 0.6);
    const y = v >= 0 ? zeroY - bh : zeroY;
    const fill = signed ? (v >= 0 ? "var(--in)" : "var(--out)") : color;
    return `<rect x="${x}" y="${y}" width="${bw}" height="${Math.max(1, bh)}" rx="2" fill="${fill}"></rect>`;
  }).join("");
  const labels = points.map((p, i) => {
    const x = 8 + i * step + step / 2;
    return `<text x="${x}" y="${h - 4}" text-anchor="middle" class="chart-label">${esc(shortMonth(p.title, p.ym))}</text>`;
  }).join("");
  return `
    <div class="chart-scroll">
      <svg class="stat-chart" viewBox="0 0 ${w} ${h}" width="${w}" height="${h}" role="img">
        <line x1="8" y1="${zeroY}" x2="${w - 8}" y2="${zeroY}" class="chart-zero"></line>
        ${bars}${labels}
      </svg>
    </div>`;
}

function overlayLines(points) {
  const incomes = points.map((p) => Number(p.income || 0));
  const expenses = points.map((p) => Number(p.expense || 0));
  const peak = chartMax([...incomes, ...expenses]);
  const w = Math.max(280, points.length * 28);
  const h = 160;
  const pad = 18;
  const plotH = h - pad * 2;
  const plotW = w - 16;
  const step = plotW / Math.max(points.length - 1, 1);
  const toY = (v) => pad + plotH - (v / peak) * plotH;
  const path = (vals) => vals.map((v, i) => {
    const x = 8 + i * step;
    const y = toY(v);
    return `${i ? "L" : "M"}${x},${y}`;
  }).join(" ");
  const labels = points.map((p, i) => {
    const x = 8 + i * (plotW / Math.max(points.length - 1, 1));
    return `<text x="${x}" y="${h - 4}" text-anchor="middle" class="chart-label">${esc(shortMonth(p.title, p.ym))}</text>`;
  }).join("");
  return `
    <div class="chart-scroll">
      <svg class="stat-chart" viewBox="0 0 ${w} ${h}" width="${w}" height="${h}" role="img">
        <path d="${path(expenses)}" class="chart-line out" fill="none"></path>
        <path d="${path(incomes)}" class="chart-line in" fill="none"></path>
        ${points.map((p, i) => {
          const x = 8 + i * step;
          return `<circle cx="${x}" cy="${toY(Number(p.expense || 0))}" r="2.5" class="chart-dot out"></circle>
            <circle cx="${x}" cy="${toY(Number(p.income || 0))}" r="2.5" class="chart-dot in"></circle>`;
        }).join("")}
        ${labels}
      </svg>
    </div>
    <div class="chart-legend">
      <span class="leg in">Доходы</span>
      <span class="leg out">Расходы</span>
    </div>`;
}

function articleBars(points, name) {
  const rows = points.map((p) => ({
    ...p,
    amount: Number((p.articles || {})[name] || 0),
  }));
  return barChart(rows, "amount", { color: "var(--out)" });
}

function periodButtons() {
  return [3, 6, 12, 24].map((n) => {
    const label = n === 12 ? "Год" : n === 24 ? "2 года" : `${n} мес`;
    const on = Number(state.statMonths) === n ? " primary" : " ghost";
    return `<button type="button" class="${on.trim()}" data-stat-months="${n}">${label}</button>`;
  }).join("");
}

function statsView() {
  const series = state.statSeries;
  const points = series?.points || [];
  const names = series?.expense_names || chosenExpenseNames();
  const last = points[points.length - 1];
  const income = last ? Number(last.income || 0) : null;
  const expense = last ? Number(last.expense || 0) : null;
  const net = last ? Number(last.net || 0) : null;
  const hasIncome = Boolean(last?.has_income);
  return `
    <div class="app-shell">
      <div class="topbar">
        <button class="ghost" id="stats-back" type="button">Назад</button>
        <div class="brand">Касса</div>
      </div>
      <h1 class="queue-title serif">Статистика</h1>
      <p class="hint">Цифры только из сальдо: указанный доход и отмеченные статьи расходов. По статье без трат берётся план.</p>
      <div class="period-row">${periodButtons()}</div>
      <section class="hero">
        <div class="label">Сальдо последнего месяца</div>
        <p class="net serif ${net == null || !hasIncome ? "" : net >= 0 ? "pos" : "neg"}">${!hasIncome || net == null ? "—" : money(net, true)}</p>
        <div class="split">
          <div class="kpi in"><div class="k">Доходы</div><div class="v">${hasIncome ? money(income) : "Указать"}</div></div>
          <div class="kpi out"><div class="k">Расходы</div><div class="v">${money(expense || 0)}</div></div>
        </div>
      </section>
      <section class="card">
        <h2>Сальдо по месяцам</h2>
        ${points.length ? barChart(points, "net", { signed: true }) : `<p class="empty">Нет данных</p>`}
      </section>
      <section class="card">
        <h2>Доходы и расходы</h2>
        <p class="hint">Зелёный — доходы из сальдо, красный — выбранные расходы.</p>
        ${points.length ? overlayLines(points) : `<p class="empty">Нет данных</p>`}
      </section>
      <button type="button" class="ghost" id="stat-expand" style="width:100%;margin:4px 0 12px">${state.statExpand ? "Свернуть расходы" : "Развернуть расходы"}</button>
      ${state.statExpand ? `
        <section class="card">
          <h2>Расходы по статьям</h2>
          <p class="hint">Статьи из сальдо текущего месяца, помесячно за выбранный период.</p>
          ${names.length ? names.map((name) => `
            <div class="stat-article">
              <div class="stat-article-head" style="${catVars(name)}">
                <span class="cat-swatch" aria-hidden="true"></span>
                <b>${esc(name)}</b>
              </div>
              ${articleBars(points, name)}
            </div>`).join("") : `<p class="empty">В сальдо не отмечены статьи расходов</p>`}
        </section>` : ""}
      <section class="card">
        <h2>Спросить Kie</h2>
        <p class="hint">${esc(state.me.chat ? "Вопрос по сальдо, месяцам и выбранным статьям." : (state.me.chat_error || "Ключ Kie на сервере не включён."))}</p>
        <div class="stat-chat-log" id="stat-chat-log">${(state.statChat || []).map((m) => `<div class="stat-chat-msg ${m.role === "user" ? "me" : "bot"}"><div class="stat-chat-who">${m.role === "user" ? "Вы" : "Kie"}</div><div class="stat-chat-text">${esc(m.text)}</div></div>`).join("") || `<p class="empty">Например: как менялось сальдо?</p>`}</div>
        <form id="stat-chat-form" class="stat-chat-form">
          <textarea id="stat-chat-input" rows="2" placeholder="Как росли расходы?" ${state.statChatBusy ? "disabled" : ""}></textarea>
          <button class="primary" type="submit" id="stat-chat-send">${state.statChatBusy ? "Думаю…" : "Спросить"}</button>
        </form>
        <div class="error" id="stat-chat-error" hidden></div>
      </section>
      ${tabBar()}
    </div>`;
}

async function loadStatSeries() {
  const months = Number(state.statMonths) || 12;
  const res = await api(`/api/stats/series?months=${months}&year=${state.year}&month=${state.month}`);
  state.statSeries = res;
}

async function showStats(opts = {}) {
  state.view = "stats";
  if (!state.statMonths) state.statMonths = 12;
  render();
  if (opts.history !== false) commitRoute();
  try {
    await fetchSummary();
    await loadStatSeries();
  } catch (err) {
    state.notice = err.data?.detail || err.message || "Не удалось открыть статистику";
  }
  if (state.view === "stats") render();
}

function bindStats() {
  $("#stats-back")?.addEventListener("click", () => goBack());
  document.querySelectorAll("[data-stat-months]").forEach((el) => {
    el.addEventListener("click", async () => {
      state.statMonths = Number(el.getAttribute("data-stat-months")) || 12;
      render();
      try {
        await loadStatSeries();
      } catch (err) {
        alert(err.data?.detail || err.message || "Не удалось загрузить период");
      }
      if (state.view === "stats") render();
    });
  });
  $("#stat-expand")?.addEventListener("click", () => {
    state.statExpand = !state.statExpand;
    render();
  });
  $("#stat-chat-form")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const input = $("#stat-chat-input");
    const question = (input?.value || "").trim();
    if (!question || state.statChatBusy) return;
    state.statChat = [...(state.statChat || []), { role: "user", text: question }];
    state.statChatBusy = true;
    if (input) input.value = "";
    render();
    try {
      const res = await api("/api/stats/chat", {
        method: "POST",
        body: {
          question,
          year: state.year,
          month: state.month,
          income_categories: [],
          expense_categories: state.statSeries?.expense_names || chosenExpenseNames(),
          history: state.statChat.slice(0, -1),
        },
      });
      state.statChat = [...state.statChat, { role: "assistant", text: res.answer || "Нет ответа" }];
    } catch (err) {
      state.statChat = [...state.statChat, { role: "assistant", text: err.data?.detail || err.message || "Не удалось спросить" }];
    } finally {
      state.statChatBusy = false;
      render();
    }
  });
}

bindAppClicks();
boot().catch((err) => {
  app.innerHTML = `<div class="app-shell"><p class="error">${esc(err.message)}</p></div>`;
});
