(() => {
  const MAX_REFS = 2;
  const MAX_IMAGE_SIDE = 1024;
  const JPEG_QUALITY = 0.85;

  const loginPanel = document.getElementById("staff-login-panel");
  const workspace = document.getElementById("staff-workspace");
  const loginForm = document.getElementById("staff-login-form");
  const loginError = document.getElementById("staff-login-error");
  const userLabel = document.getElementById("staff-user-label");
  const logoutBtn = document.getElementById("staff-logout");
  const tryonError = document.getElementById("staff-tryon-error");
  const jobsList = document.getElementById("staff-jobs-list");
  const refreshBtn = document.getElementById("staff-refresh");
  const searchInput = document.getElementById("staff-search");
  const statusInput = document.getElementById("staff-status");
  const dateFromInput = document.getElementById("staff-date-from");
  const dateToInput = document.getElementById("staff-date-to");
  const lastResult = document.getElementById("staff-last-result");
  const stepAfter = document.getElementById("step-after");
  const afterLead = document.getElementById("after-lead");

  const beforeInput = document.getElementById("before-file");
  const beforeCamera = document.getElementById("before-camera");
  const beforePreviewWrap = document.getElementById("before-preview-wrap");
  const beforePreview = document.getElementById("before-preview");
  const btnClearBefore = document.getElementById("btn-clear-before");
  const refInput = document.getElementById("ref-file");
  const refsGrid = document.getElementById("refs-grid");
  const refsHint = document.getElementById("refs-hint");
  const btnRun = document.getElementById("btn-run");
  const btnPortfolio = document.getElementById("btn-portfolio");
  const progress = document.getElementById("progress");
  const progressText = document.getElementById("progress-text");
  const progressFill = document.getElementById("progress-fill");
  const progressPct = document.getElementById("progress-pct");
  const clientNameInput = document.getElementById("client-name");

  const portfolioModal = document.getElementById("portfolio-modal");
  const portfolioTabs = document.getElementById("portfolio-tabs");
  const portfolioGrid = document.getElementById("portfolio-grid");
  const btnClosePortfolio = document.getElementById("btn-close-portfolio");
  const btnApplyPortfolio = document.getElementById("btn-apply-portfolio");

  let beforeFile = null;
  /** @type {{kind:'file'|'portfolio', file?:File, id?:string, src?:string}[]} */
  let refItems = [];
  let portfolioManifest = null;
  let activeCategory = "";
  let selectedPortfolio = new Set();
  let running = false;
  let progressTimer = null;

  function showError(el, msg) {
    el.textContent = msg || "";
    el.classList.toggle("hidden", !msg);
  }

  function setAuthView(me) {
    const logged = !!me;
    loginPanel.classList.toggle("hidden", logged);
    workspace.classList.toggle("hidden", !logged);
    userLabel.textContent = logged ? `Сотрудник: ${me.name || me.phone}` : "";
  }

  async function api(url, opts = {}) {
    const resp = await fetch(url, opts);
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) {
      const detail = data.detail || `Ошибка ${resp.status}`;
      throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
    }
    return data;
  }

  function setProgress(pct, label) {
    const value = Math.max(0, Math.min(100, Math.round(pct)));
    if (progressFill) progressFill.style.width = `${value}%`;
    if (progressPct) progressPct.textContent = `${value}%`;
    if (label) progressText.textContent = label;
  }

  function startMagicProgress() {
    stopMagicProgress();
    progress.classList.remove("hidden");
    setProgress(3, "Делается магия…");
    let pct = 3;
    progressTimer = setInterval(() => {
      if (pct < 40) pct += 2.2;
      else if (pct < 70) pct += 1.1;
      else if (pct < 88) pct += 0.45;
      else if (pct < 92) pct += 0.15;
      setProgress(pct, "Делается магия…");
    }, 280);
  }

  function stopMagicProgress() {
    if (progressTimer) {
      clearInterval(progressTimer);
      progressTimer = null;
    }
  }

  function sync() {
    const nameOk = (clientNameInput.value || "").trim().length >= 2;
    btnRun.disabled = running || !(beforeFile && refItems.length > 0 && nameOk);
    refsHint.textContent = `Выбрано: ${refItems.length} из ${MAX_REFS}`;
  }

  function setBefore(file) {
    beforeFile = file;
    beforePreview.src = URL.createObjectURL(file);
    beforePreview.classList.remove("mirror-x");
    beforePreviewWrap.classList.remove("hidden");
    btnClearBefore.classList.remove("hidden");
    sync();
  }

  function clearBefore() {
    beforeFile = null;
    beforePreview.removeAttribute("src");
    beforePreview.classList.remove("mirror-x");
    beforePreviewWrap.classList.add("hidden");
    btnClearBefore.classList.add("hidden");
    sync();
  }

  async function compressImageFile(file, { mirror = false, name = "photo.jpg" } = {}) {
    const url = URL.createObjectURL(file);
    try {
      const img = await new Promise((resolve, reject) => {
        const el = new Image();
        el.onload = () => resolve(el);
        el.onerror = () => reject(new Error("Не удалось открыть фото"));
        el.src = url;
      });
      let w = img.naturalWidth || img.width;
      let h = img.naturalHeight || img.height;
      if (!w || !h) throw new Error("Пустое фото");
      if (Math.max(w, h) > MAX_IMAGE_SIDE) {
        const scale = MAX_IMAGE_SIDE / Math.max(w, h);
        w = Math.max(1, Math.round(w * scale));
        h = Math.max(1, Math.round(h * scale));
      }
      const canvas = document.createElement("canvas");
      canvas.width = w;
      canvas.height = h;
      const ctx = canvas.getContext("2d");
      if (mirror) {
        ctx.translate(w, 0);
        ctx.scale(-1, 1);
      }
      ctx.drawImage(img, 0, 0, w, h);
      const blob = await new Promise((resolve, reject) => {
        canvas.toBlob(
          (b) => (b ? resolve(b) : reject(new Error("Не удалось сжать фото"))),
          "image/jpeg",
          JPEG_QUALITY
        );
      });
      return new File([blob], name, { type: "image/jpeg" });
    } finally {
      URL.revokeObjectURL(url);
    }
  }

  async function setBeforeFromFile(file, { mirror = false } = {}) {
    const name = mirror ? "before_mirror.jpg" : "before.jpg";
    try {
      const compressed = await compressImageFile(file, { mirror, name });
      setBefore(compressed);
    } catch (err) {
      showError(tryonError, err.message || "Не удалось обработать фото");
      setBefore(file);
    }
  }

  function renderRefs() {
    refsGrid.innerHTML = "";
    refItems.forEach((item, idx) => {
      const card = document.createElement("div");
      card.className = "ref-card";
      const img = document.createElement("img");
      img.alt = `Референс ${idx + 1}`;
      img.src = item.src || (item.file ? URL.createObjectURL(item.file) : "");
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "ref-remove";
      btn.textContent = "×";
      btn.addEventListener("click", () => {
        refItems.splice(idx, 1);
        renderRefs();
        sync();
      });
      card.append(img, btn);
      refsGrid.appendChild(card);
    });
  }

  async function loadPortfolio() {
    if (portfolioManifest) return portfolioManifest;
    const resp = await fetch("/api/portfolio");
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.detail || "Не удалось загрузить портфолио");
    portfolioManifest = data;
    return data;
  }

  function syncPortfolioApplyBtn() {
    const n = selectedPortfolio.size;
    btnApplyPortfolio.textContent = `Добавить выбранные · ${n} из ${MAX_REFS}`;
    btnApplyPortfolio.disabled = n === 0;
  }

  function renderPortfolio() {
    if (!portfolioManifest) return;
    portfolioTabs.innerHTML = "";
    portfolioGrid.innerHTML = "";
    (portfolioManifest.categories || []).forEach((cat) => {
      const tab = document.createElement("button");
      tab.type = "button";
      tab.className = "portfolio-tab" + (cat.id === activeCategory ? " active" : "");
      tab.textContent = cat.title;
      tab.addEventListener("click", () => {
        activeCategory = cat.id;
        renderPortfolio();
      });
      portfolioTabs.appendChild(tab);
    });
    const cat =
      (portfolioManifest.categories || []).find((c) => c.id === activeCategory) ||
      (portfolioManifest.categories || [])[0];
    if (!cat) {
      syncPortfolioApplyBtn();
      return;
    }
    activeCategory = cat.id;
    cat.items.forEach((item) => {
      const card = document.createElement("button");
      card.type = "button";
      card.className = "portfolio-item" + (selectedPortfolio.has(item.id) ? " selected" : "");
      const img = document.createElement("img");
      img.src = item.thumb || item.src;
      img.alt = item.id;
      img.loading = "lazy";
      img.decoding = "async";
      card.appendChild(img);
      card.addEventListener("click", () => {
        if (selectedPortfolio.has(item.id)) selectedPortfolio.delete(item.id);
        else {
          if (selectedPortfolio.size >= MAX_REFS) return;
          selectedPortfolio.add(item.id);
        }
        renderPortfolio();
      });
      portfolioGrid.appendChild(card);
    });
    syncPortfolioApplyBtn();
  }

  function renderResult(data) {
    lastResult.innerHTML = "";
    stepAfter.classList.remove("hidden");
    if (!data) return;
    afterLead.textContent = "Готово — сохранено в базу на 30 дней.";
    if (data.before_url) {
      const before = document.createElement("article");
      before.className = "result-card";
      before.innerHTML = `<img alt="До" src="${data.before_url}"><div class="label">До</div>`;
      lastResult.appendChild(before);
    }
    (data.results || []).forEach((src, i) => {
      const card = document.createElement("article");
      card.className = "result-card";
      card.innerHTML = `<img alt="После ${i + 1}" src="${src}"><div class="label">После ${i + 1}</div>`;
      lastResult.appendChild(card);
    });
    stepAfter.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  async function loadMe() {
    try {
      const me = await api("/api/staff/me");
      setAuthView(me);
      await loadJobs();
    } catch (_) {
      setAuthView(null);
    }
  }

  loginForm.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    showError(loginError, "");
    const fd = new FormData();
    fd.append("phone", document.getElementById("staff-phone").value.trim());
    fd.append("password", document.getElementById("staff-password").value);
    try {
      const me = await api("/api/staff/login", { method: "POST", body: fd });
      setAuthView(me);
      await loadJobs();
    } catch (err) {
      showError(loginError, err.message || String(err));
    }
  });

  logoutBtn.addEventListener("click", async () => {
    try {
      await api("/api/staff/logout", { method: "POST" });
    } catch (_) {
      // ignore
    }
    setAuthView(null);
  });

  beforeInput.addEventListener("change", async () => {
    const file = beforeInput.files && beforeInput.files[0];
    beforeInput.value = "";
    if (file) await setBeforeFromFile(file, { mirror: false });
  });
  beforeCamera.addEventListener("change", async () => {
    const file = beforeCamera.files && beforeCamera.files[0];
    beforeCamera.value = "";
    if (file) await setBeforeFromFile(file, { mirror: true });
  });
  btnClearBefore.addEventListener("click", clearBefore);
  clientNameInput.addEventListener("input", sync);

  refInput.addEventListener("change", async () => {
    const files = Array.from(refInput.files || []);
    refInput.value = "";
    for (const file of files) {
      if (refItems.length >= MAX_REFS) break;
      try {
        const compressed = await compressImageFile(file, {
          mirror: false,
          name: `ref_${refItems.length + 1}.jpg`,
        });
        refItems.push({ kind: "file", file: compressed });
      } catch (err) {
        showError(tryonError, err.message || "Не удалось сжать референс");
      }
    }
    renderRefs();
    sync();
  });

  btnPortfolio.addEventListener("click", async () => {
    try {
      await loadPortfolio();
      selectedPortfolio = new Set(refItems.filter((r) => r.kind === "portfolio").map((r) => r.id));
      activeCategory = (portfolioManifest.categories[0] || {}).id || "";
      portfolioModal.classList.remove("hidden");
      renderPortfolio();
    } catch (err) {
      showError(tryonError, err.message || String(err));
    }
  });
  btnClosePortfolio.addEventListener("click", () => portfolioModal.classList.add("hidden"));
  btnApplyPortfolio.addEventListener("click", () => {
    const filesOnly = refItems.filter((r) => r.kind === "file");
    const portfolioItems = [];
    for (const cat of portfolioManifest.categories || []) {
      for (const item of cat.items || []) {
        if (selectedPortfolio.has(item.id)) {
          portfolioItems.push({ kind: "portfolio", id: item.id, src: item.src });
        }
      }
    }
    refItems = [...filesOnly, ...portfolioItems].slice(0, MAX_REFS);
    renderRefs();
    sync();
    portfolioModal.classList.add("hidden");
  });

  btnRun.addEventListener("click", async () => {
    showError(tryonError, "");
    const name = (clientNameInput.value || "").trim();
    if (!name || name.length < 2) {
      showError(tryonError, "Укажите имя клиента.");
      return;
    }
    if (!beforeFile || !refItems.length || running) return;

    running = true;
    sync();
    startMagicProgress();
    stepAfter.classList.add("hidden");
    lastResult.innerHTML = "";

    const fd = new FormData();
    fd.append("client_name", name);
    fd.append("before", beforeFile, beforeFile.name);
    refItems.forEach((item, i) => {
      if (item.kind === "file" && item.file) {
        fd.append("refs", item.file, item.file.name || `ref_${i + 1}.jpg`);
      }
    });
    const portfolioIds = refItems.filter((r) => r.kind === "portfolio").map((r) => r.id);
    if (portfolioIds.length) fd.append("portfolio_ids", portfolioIds.join(","));

    try {
      const data = await api("/api/staff/tryon", { method: "POST", body: fd });
      stopMagicProgress();
      setProgress(100, "Готово");
      renderResult(data);
      await loadJobs();
    } catch (err) {
      stopMagicProgress();
      showError(tryonError, err.message || String(err));
      setProgress(0, "Не удалось выполнить примерку");
    } finally {
      stopMagicProgress();
      setTimeout(() => progress.classList.add("hidden"), 400);
      running = false;
      sync();
    }
  });

  function renderJobs(items) {
    jobsList.innerHTML = "";
    if (!items.length) {
      jobsList.textContent = "Пока нет генераций.";
      return;
    }
    items.forEach((it) => {
      const row = document.createElement("div");
      row.className = "panel";
      const images = [];
      if (it.before_url) images.push(`<a href="${it.before_url}" target="_blank" rel="noopener">до</a>`);
      (it.result_urls || []).forEach((u, i) =>
        images.push(`<a href="${u}" target="_blank" rel="noopener">после ${i + 1}</a>`)
      );
      const when = (it.created_at || "").replace("T", " ").replace("Z", " UTC");
      row.innerHTML = `
        <p><strong>${it.client_name || "Без имени"}</strong></p>
        <p>${when} · статус: ${it.status}</p>
        <p>job_id: ${it.job_id}</p>
        <p>${images.join(" · ") || "фото недоступны"}</p>
      `;
      jobsList.appendChild(row);
    });
  }

  async function loadJobs() {
    const q = (searchInput.value || "").trim();
    const status = (statusInput.value || "").trim();
    const dateFrom = (dateFromInput.value || "").trim();
    const dateTo = (dateToInput.value || "").trim();
    const params = new URLSearchParams();
    params.set("limit", "100");
    params.set("offset", "0");
    if (q) params.set("q", q);
    if (status) params.set("status", status);
    if (dateFrom) params.set("date_from", dateFrom);
    if (dateTo) params.set("date_to", dateTo);
    const data = await api(`/api/staff/generations?${params.toString()}`);
    renderJobs(data.items || []);
  }

  refreshBtn.addEventListener("click", () => {
    loadJobs().catch((e) => showError(tryonError, e.message || String(e)));
  });
  for (const el of [searchInput, statusInput, dateFromInput, dateToInput]) {
    el.addEventListener("change", () => {
      loadJobs().catch((e) => showError(tryonError, e.message || String(e)));
    });
  }

  sync();
  loadMe();
})();
