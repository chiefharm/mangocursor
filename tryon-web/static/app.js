(() => {
  const MAX_REFS = 2;
  const MAX_IMAGE_SIDE = 1024;
  const JPEG_QUALITY = 0.85;
  const METRIKA_COUNTER_ID = 64069270;
  const ATTR_KEYS = ["yclid", "utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term"];
  const RETURN_URL_KEYS = ["return_url", "from", "site"];
  const RETURN_SITE_HOSTS = [
    "soco-moscow.ru",
    "soco-salon.ru",
    "soco-kras.ru",
    "primerka.soco-salon.ru",
  ];

  function isAllowedReturnHost(hostname) {
    const host = String(hostname || "").toLowerCase();
    if (!host) return false;
    return RETURN_SITE_HOSTS.some((h) => host === h || host.endsWith("." + h));
  }

  function normalizeReturnUrl(raw) {
    let value = String(raw || "").trim();
    if (!value) return "";
    if (!/^https?:\/\//i.test(value) && !value.startsWith("//")) {
      value = `https://${value.replace(/^\/+/, "")}`;
    }
    try {
      const parsed = new URL(value);
      if (!isAllowedReturnHost(parsed.hostname)) return "";
      return parsed.toString();
    } catch (_) {
      return "";
    }
  }

  function captureReturnUrl() {
    const params = new URLSearchParams(window.location.search);
    for (const key of RETURN_URL_KEYS) {
      const value = normalizeReturnUrl(params.get(key));
      if (value) {
        sessionStorage.setItem("tryon_return_url", value);
        return;
      }
    }
    if (getReturnUrl()) return;
    try {
      const ref = normalizeReturnUrl(document.referrer);
      if (ref) {
        sessionStorage.setItem("tryon_return_url", ref);
        return;
      }
    } catch (_) {}
    const here = normalizeReturnUrl(window.location.origin + "/");
    if (here) sessionStorage.setItem("tryon_return_url", here);
  }

  function getReturnUrl() {
    return sessionStorage.getItem("tryon_return_url") || "";
  }

  function captureAttribution() {
    const params = new URLSearchParams(window.location.search);
    for (const key of ATTR_KEYS) {
      const value = params.get(key);
      if (value) sessionStorage.setItem(`tryon_${key}`, value);
    }
    const yid =
      params.get("ym_cid") ||
      params.get("yandex_client_id") ||
      params.get("clientID") ||
      params.get("client_id") ||
      "";
    if (yid.trim()) {
      sessionStorage.setItem("tryon_ym_cid", yid.trim().slice(0, 64));
      return;
    }
    // Cookie с основного сайта (если кнопка не успела дописать URL)
    try {
      const m = document.cookie.match(/(?:^|;\s*)ym_cid=([^;]+)/);
      if (m && m[1]) sessionStorage.setItem("tryon_ym_cid", decodeURIComponent(m[1]).slice(0, 64));
    } catch (_) {}
  }

  function getAttribution() {
    const out = {};
    for (const key of ATTR_KEYS) out[key] = sessionStorage.getItem(`tryon_${key}`) || "";
    return out;
  }

  function getStoredYmCid() {
    return (
      sessionStorage.getItem("tryon_ym_cid") ||
      sessionStorage.getItem("tryon_yandex_client_id") ||
      ""
    );
  }

  function getYmCid() {
    const fromSite = getStoredYmCid();
    if (fromSite) return Promise.resolve(fromSite);
    return new Promise((resolve) => {
      if (typeof ym !== "function") return resolve("");
      let done = false;
      const timer = setTimeout(() => {
        if (!done) {
          done = true;
          resolve("");
        }
      }, 1500);
      try {
        ym(METRIKA_COUNTER_ID, "getClientID", (id) => {
          if (done) return;
          done = true;
          clearTimeout(timer);
          const value = String(id || "");
          if (value) sessionStorage.setItem("tryon_ym_cid", value);
          resolve(value);
        });
      } catch (_) {
        clearTimeout(timer);
        resolve("");
      }
    });
  }

  captureAttribution();
  captureReturnUrl();

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
  const errorEl = document.getElementById("error");

  const stepAfter = document.getElementById("step-after");
  const afterLead = document.getElementById("after-lead");
  const realizeBlock = document.getElementById("realize-block");
  const ctaMain = document.getElementById("cta-main");
  const ctaCity = document.getElementById("cta-city");
  const ctaMessenger = document.getElementById("cta-messenger");
  const ctaOk = document.getElementById("cta-ok");
  const ctaError = document.getElementById("cta-error");
  const linkMax = document.getElementById("link-max");
  const linkTg = document.getElementById("link-tg");
  const btnQrMax = document.getElementById("btn-qr-max");
  const btnQrTg = document.getElementById("btn-qr-tg");
  const qrModal = document.getElementById("qr-modal");
  const qrImage = document.getElementById("qr-image");
  const qrModalTitle = document.getElementById("qr-modal-title");
  const btnCloseQr = document.getElementById("btn-close-qr");

  const portfolioModal = document.getElementById("portfolio-modal");
  const portfolioTabs = document.getElementById("portfolio-tabs");
  const portfolioGrid = document.getElementById("portfolio-grid");
  const btnClosePortfolio = document.getElementById("btn-close-portfolio");
  const btnApplyPortfolio = document.getElementById("btn-apply-portfolio");

  let beforeFile = null;
  let refItems = [];
  let running = false;
  let portfolioManifest = null;
  let activeCategory = "";
  let selectedPortfolio = new Set();
  let maxLink = "";
  let tgLink = "";

  function openQrModal(title, url) {
    if (!url || url === "#") return;
    qrModalTitle.textContent = title;
    qrImage.src = `/api/qr.png?url=${encodeURIComponent(url)}`;
    qrModal.classList.remove("hidden");
  }

  function closeQrModal() {
    qrModal.classList.add("hidden");
    qrImage.removeAttribute("src");
  }

  function setProgress(pct, label) {
    const value = Math.max(0, Math.min(100, Math.round(pct)));
    if (progressFill) progressFill.style.width = `${value}%`;
    if (progressPct) progressPct.textContent = `${value}%`;
    if (label) progressText.textContent = label;
  }

  let progressTimer = null;
  function startProgress() {
    if (progressTimer) clearInterval(progressTimer);
    progress.classList.remove("hidden");
    setProgress(3, "Подготавливаем примерку...");
    let pct = 3;
    progressTimer = setInterval(() => {
      if (pct < 85) pct += pct < 40 ? 2.2 : 0.9;
      setProgress(pct, "Подготавливаем примерку...");
    }, 280);
  }

  function stopProgress(finalLabel = "") {
    if (progressTimer) {
      clearInterval(progressTimer);
      progressTimer = null;
    }
    if (finalLabel) setProgress(100, finalLabel);
    setTimeout(() => progress.classList.add("hidden"), 500);
  }

  function showError(msg) {
    errorEl.textContent = msg || "";
    errorEl.classList.toggle("hidden", !msg);
  }

  function showCtaError(msg) {
    ctaError.textContent = msg || "";
    ctaError.classList.toggle("hidden", !msg);
  }

  function showCtaPanel(which) {
    if (ctaMain) ctaMain.classList.toggle("hidden", which !== "main");
    if (ctaCity) ctaCity.classList.toggle("hidden", which !== "city");
    if (ctaMessenger) ctaMessenger.classList.toggle("hidden", which !== "messenger");
    ctaOk.classList.add("hidden");
    showCtaError("");
  }

  function sync() {
    btnRun.disabled = running || !(beforeFile && refItems.length > 0);
    refsHint.textContent = `Выбрано: ${refItems.length} из ${MAX_REFS}`;
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
      const scale = Math.max(w, h) > MAX_IMAGE_SIDE ? MAX_IMAGE_SIDE / Math.max(w, h) : 1;
      w = Math.max(1, Math.round(w * scale));
      h = Math.max(1, Math.round(h * scale));
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
        canvas.toBlob((b) => (b ? resolve(b) : reject(new Error("Не удалось сжать фото"))), "image/jpeg", JPEG_QUALITY);
      });
      return new File([blob], name, { type: "image/jpeg" });
    } finally {
      URL.revokeObjectURL(url);
    }
  }

  function setBefore(file) {
    beforeFile = file;
    beforePreview.src = URL.createObjectURL(file);
    beforePreview.classList.remove("mirror-x");
    beforePreviewWrap.classList.remove("hidden");
    btnClearBefore.classList.remove("hidden");
    sync();
  }

  async function setBeforeFromFile(file, { mirror = false } = {}) {
    try {
      const compressed = await compressImageFile(file, { mirror, name: mirror ? "before_mirror.jpg" : "before.jpg" });
      setBefore(compressed);
    } catch (err) {
      showError(err.message || "Не удалось обработать фото");
      setBefore(file);
    }
  }

  function clearBefore() {
    beforeFile = null;
    beforePreview.removeAttribute("src");
    beforePreviewWrap.classList.add("hidden");
    btnClearBefore.classList.add("hidden");
    sync();
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

    const cat = (portfolioManifest.categories || []).find((c) => c.id === activeCategory) || (portfolioManifest.categories || [])[0];
    if (!cat) {
      syncPortfolioApplyBtn();
      return;
    }
    activeCategory = cat.id;

    (cat.items || []).forEach((item) => {
      const card = document.createElement("button");
      card.type = "button";
      card.className = "portfolio-item" + (selectedPortfolio.has(item.id) ? " selected" : "");
      const img = document.createElement("img");
      img.src = item.thumb || item.src;
      img.alt = item.id;
      img.loading = "lazy";
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

  async function runTryon() {
    showError("");
    if (!beforeFile || !refItems.length) return;
    running = true;
    sync();
    startProgress();

    const form = new FormData();
    form.append("name", "");
    form.append("phone", "");
    form.append("consent", "1");
    form.append("before", beforeFile, beforeFile.name);

    refItems.forEach((item, i) => {
      if (item.kind === "file" && item.file) {
        form.append("refs", item.file, item.file.name || `ref_${i + 1}.jpg`);
      }
    });

    const portfolioIds = refItems.filter((r) => r.kind === "portfolio").map((r) => r.id);
    if (portfolioIds.length) form.append("portfolio_ids", portfolioIds.join(","));

    const ymCid = await getYmCid();
    const attr = getAttribution();
    if (ymCid) form.append("ym_cid", ymCid);
    for (const key of ATTR_KEYS) if (attr[key]) form.append(key, attr[key]);
    const returnUrl = getReturnUrl();
    if (returnUrl) form.append("return_url", returnUrl);

    try {
      const resp = await fetch("/api/tryon", { method: "POST", body: form });
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok) {
        const detail = data.detail || data.error || `Ошибка сервера (${resp.status})`;
        throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
      }

      stopProgress("Готово");
      afterLead.textContent = data.message || "Активируйте бота в MAX или Telegram: после запустим генерацию и отправим результат в мессенджер.";
      maxLink = data.max_link || "";
      tgLink = data.telegram_link || "";
      linkMax.href = maxLink || "#";
      linkTg.href = tgLink || "#";
      stepAfter.classList.remove("hidden");
      realizeBlock.classList.remove("hidden");
      showCtaPanel("messenger");
      stepAfter.scrollIntoView({ behavior: "smooth", block: "start" });
    } catch (err) {
      stopProgress();
      showError(err.message || String(err));
      setProgress(0, "Не удалось подготовить примерку");
    } finally {
      running = false;
      sync();
    }
  }

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

  refInput.addEventListener("change", async () => {
    const files = Array.from(refInput.files || []);
    refInput.value = "";
    for (const file of files) {
      if (refItems.length >= MAX_REFS) break;
      try {
        const compressed = await compressImageFile(file, { mirror: false, name: `ref_${refItems.length + 1}.jpg` });
        refItems.push({ kind: "file", file: compressed });
      } catch (err) {
        showError(err.message || "Не удалось сжать референс");
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
      showError(err.message || String(err));
    }
  });

  btnClosePortfolio.addEventListener("click", () => portfolioModal.classList.add("hidden"));

  btnQrMax.addEventListener("click", () => openQrModal("Зайти в бота MAX по QR-коду", maxLink));
  btnQrTg.addEventListener("click", () => openQrModal("Зайти в бота Telegram по QR-коду", tgLink));
  btnCloseQr.addEventListener("click", closeQrModal);
  qrModal.addEventListener("click", (e) => {
    if (e.target === qrModal) closeQrModal();
  });

  btnApplyPortfolio.addEventListener("click", () => {
    const filesOnly = refItems.filter((r) => r.kind === "file");
    const selected = [];
    for (const cat of portfolioManifest.categories || []) {
      for (const item of cat.items || []) {
        if (selectedPortfolio.has(item.id)) selected.push({ kind: "portfolio", id: item.id, src: item.src });
      }
    }
    refItems = [...filesOnly, ...selected].slice(0, MAX_REFS);
    renderRefs();
    sync();
    portfolioModal.classList.add("hidden");
  });

  btnRun.addEventListener("click", () => {
    if (!running) runTryon();
  });

  sync();
})();
