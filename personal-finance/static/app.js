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
};

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

function homeView() {
  const s = state.summary?.summary;
  const prev = state.summary?.previous;
  const reviewN = s?.unreviewed_count || 0;
  const net = s ? s.net : 0;
  const maxExp = Math.max(1, ...(s?.expense_by_category || []).map((c) => c.amount));
  const maxInc = Math.max(1, ...(s?.income_by_category || []).map((c) => c.amount));
  const delta = prev && prev.tx_count
    ? `К прошлому месяцу: доходы ${cmp(s.income, prev.income)}, расходы ${cmp(s.expense, prev.expense)}`
    : "Загрузите выписку — посчитаю доходы, расходы и статьи банка.";
  const showLogout = Boolean(state.me.auth_required);
  return `
    <div class="app-shell">
      ${state.me.demo ? `<p class="demo-ribbon">Демо · цифры выдуманные</p>` : ""}
      <div class="topbar">
        <div class="brand">Касса</div>
        <div class="top-actions">
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
          <button class="primary" id="go-review">Разобрать</button>
        </div>` : ""}
      <section class="hero">
        <div class="label">Сальдо за месяц</div>
        <p class="net serif ${net >= 0 ? "pos" : "neg"}">${s ? money(net, true) : "—"}</p>
        ${renderGoalMeter(s)}
        <div class="split">
          <div class="kpi in"><div class="k">Доходы</div><div class="v">${s ? money(s.income) : "—"}</div></div>
          <div class="kpi out"><div class="k">Расходы</div><div class="v">${s ? money(s.expense) : "—"}</div></div>
        </div>
        <div class="delta">${esc(delta)}</div>
        ${s && s.unreviewed_count ? `<div class="delta">Не разнесено: ${money(Math.abs(s.unreviewed_sum))} (${s.unreviewed_count})</div>` : ""}
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
        <div class="drop" id="drop">
          <label class="drop-hit" for="file">
            <strong>Вложить выписку</strong>
            <p>PDF Альфа, CSV или Excel. На iPhone: Обзор → Загрузки.</p>
          </label>
          <label class="primary pick-file" for="file">Выбрать файл</label>
          <input id="file" class="file-hidden" type="file" />
        </div>
        <p class="hint">Имя файла не важно — даты беру из операций внутри. Серый файл после обновления страницы больше не должен быть.</p>
        <div class="error" id="upload-error" hidden></div>
      </section>
      <section class="card">
        <div class="card-head">
          <h2>Расходы</h2>
          <span class="muted">${s ? money(s.expense) : ""}</span>
        </div>
        ${renderBars(s?.expense_by_category, maxExp, "out", s?.expense) || `<p class="empty">Пока пусто</p>`}
        ${renderSpikes()}
      </section>
      <section class="card">
        <div class="card-head">
          <h2>Доходы</h2>
          <span class="muted">${s ? money(s.income) : ""}</span>
        </div>
        ${renderBars(s?.income_by_category, maxInc, "in", s?.income) || `<p class="empty">Пока пусто</p>`}
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
        <button class="ghost" id="review-later">Разобрать позже</button>
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
          <button class="ghost" data-mode="expense">Расход</button>
          <button class="ghost" data-mode="income">Доход</button>
        </div>
        <div id="cat-box" hidden>
          <div class="chips" id="chips"></div>
          <input class="text-input" id="custom-cat" placeholder="Своя статья" />
        </div>
        <button class="primary" id="save-review" style="width:100%;margin-top:14px">Сохранить</button>
        <button class="ghost" id="leave-unlabeled" style="width:100%;margin-top:8px">Оставить неразмеченным</button>
        <div class="error" id="review-error" hidden></div>
      </section>
      ${tabBar()}
    </div>`;
}

function queueView() {
  const pending = state.review?.transactions || [];
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
        <button class="ghost" id="unlabel-all" style="width:100%;margin:8px 0 12px">Оставить все неразмеченными</button>
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
  return `
    <nav class="tabbar">
      <button type="button" class="tab ${state.view === "home" ? "on" : ""}" id="tab-home">Сводка</button>
      <button type="button" class="tab ${onQueue ? "on" : ""} ${n ? "hot" : ""}" id="tab-queue">
        Разобрать позже
        ${n ? `<span class="tab-badge">${n > 99 ? "99+" : n}</span>` : ""}
      </button>
    </nav>`;
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
      <p class="hint">Оставили без статьи. В сальдо входят, в обычные категории — нет.</p>
      ${rows.map((t) => txRow(t)).join("")}
    </section>`;
}

function txRow(t, action) {
  const cls = t.amount < 0 ? "neg" : "pos";
  const open = action ? ` data-open="${t.id}"` : "";
  const tag = action ? "button" : "div";
  const type = action ? ` type="button"` : "";
  return `
    <${tag} class="tx-row"${type}${open}>
      <div>
        <div class="tx-desc">${esc(t.description || "Перевод")}</div>
        <div class="tx-sub">${esc(fmtDate(t.posted_date))}</div>
      </div>
      <div class="tx-amt ${cls}">${money(t.amount, true)}</div>
    </${tag}>`;
}

function renderGoalMeter(s) {
  const goal = state.summary?.goal;
  if (!goal || !s) return "";
  const pct = Math.max(0, Math.min(100, (s.net / goal.amount) * 100));
  const cls = s.net >= goal.amount ? "over" : "under";
  return `
    <div class="meter-wrap">
      <div class="meter" title="До цели"><div class="meter-fill ${cls}" style="width:${pct}%"></div></div>
      <div class="meter-cap">
        <span>${Math.round(pct)}% от цели</span>
        <span>${money(goal.amount)}</span>
      </div>
    </div>`;
}

function renderGoal(s) {
  const goal = state.summary?.goal;
  const gap = state.summary?.advice?.gap;
  const amount = goal?.amount ? Math.round(goal.amount) : "";
  const status = !goal
    ? "Пока не задана — бот в группе не знает, к чему советовать."
    : s
      ? (gap > 0 ? `Не хватает ${money(gap)}` : `Цель выполняется, запас ${money(Math.abs(gap || 0))}`)
      : "";
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
      <div class="ledger-row">
        <span class="name">${esc(row.name)} <span class="spike-tag">выросло</span></span>
        <span class="dots"></span>
        <span class="amt">+${money(row.diff)}</span>
      </div>`).join("");
  }
  if (recs.length) {
    html += `<h2 style="margin-top:18px">К цели</h2>`;
    html += `<ol class="recs">${recs.map((r) => `<li>${esc(r.text)}</li>`).join("")}</ol>`;
  }
  return html;
}

function renderBars(rows, max, kind, total) {
  if (!rows || !rows.length) return "";
  const sum = total || rows.reduce((a, r) => a + r.amount, 0) || 1;
  return rows.map((row) => {
    const share = Math.round((row.amount / sum) * 100);
    return `
    <div>
      <div class="ledger-row">
        <span class="name">${esc(row.name)}</span>
        <span class="dots"></span>
        <span class="share">${share}%</span>
        <span class="amt">${money(row.amount)}</span>
      </div>
      <div class="track"><div class="fill ${kind}" style="width:${Math.max(6, (row.amount / max) * 100)}%"></div></div>
    </div>`;
  }).join("");
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
  $("#go-review")?.addEventListener("click", () => showQueue());
  bindTabs();
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
}

function bindTabs() {
  $("#tab-home")?.addEventListener("click", () => {
    state.view = "home";
    state.reviewId = null;
    loadSummary();
  });
  $("#tab-queue")?.addEventListener("click", () => showQueue());
}

async function showQueue() {
  state.view = "queue";
  state.reviewId = null;
  state.review = await api("/api/review");
  await loadSummary();
}

function bindQueue() {
  bindTabs();
  document.querySelectorAll("[data-open]").forEach((el) => {
    el.addEventListener("click", () => {
      state.reviewId = el.getAttribute("data-open");
      state.view = "review";
      if (state.review?.count) render();
      else loadReview();
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
}

function bindReview() {
  bindTabs();
  $("#review-later")?.addEventListener("click", () => {
    state.reviewId = null;
    showQueue();
  });
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
      .filter((name) => name !== "Переводы без разметки");
    chips.innerHTML = list.map((name) =>
      `<button type="button" class="chip ${chosen === name ? "on" : ""}" data-cat="${esc(name)}">${esc(name)}</button>`
    ).join("");
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
  setMode("expense");

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
        ? "На Диске нет новых операций — эти даты уже в кассе"
        : "В папке пока нет выписок";
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
      return;
    }
    await loadSummary();
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
    state.notice = `Добавлено ${n} операций` + (dups ? `, пропущено дубликатов: ${dups}` : "");
    if (res.telegram_sent) state.notice += " · отчёт в Telegram";
    if (res.import?.review_count) {
      state.view = "review";
      await loadReview();
      return;
    }
    await loadSummary();
  } catch (err) {
    if (errBox) {
      errBox.hidden = false;
      errBox.textContent = err.data?.detail || err.message || "Не удалось прочитать файл";
    }
  }
}

async function loadSummary() {
  const [summary, review] = await Promise.all([
    api(`/api/summary?year=${state.year}&month=${state.month}`),
    api("/api/review"),
  ]);
  state.summary = summary;
  state.review = review;
  render();
}

async function loadReview() {
  state.review = await api("/api/review");
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
  if (state.me.authed) await loadSummary();
  else render();
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

boot().catch((err) => {
  app.innerHTML = `<div class="app-shell"><p class="error">${esc(err.message)}</p></div>`;
});
