/**
 * SOCO analytics embed (не блокирует основной сайт).
 *
 * На soco-moscow.ru / soco-salon.ru / soco-kras.ru НЕ подключайте так:
 *   <script src="https://primerka.soco-salon.ru/static/embed_tryon_link.js"></script>
 * — если primerka лежит, страница-хозяин будет зависать.
 *
 * Подключайте через неблокирующий сниппет:
 *   tryon-web/deploy/embed_tryon_loader.snippet.html
 * (грузят скрипт после window.load; при ошибке сайт работает как обычно).
 *
 * Ловит: primerka, salon1c, mrqz, t.me/wa.me/max.ru,
 * #popup:marquiz_*, /taplink, /taplink2gisloyality (kras), виджет Marquiz Pop.
 */
(function () {
  const PRIMERKA_HOST = "primerka.soco-salon.ru";
  const UTM_KEYS = ["utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term", "yclid"];
  const HOST_COUNTERS = {
    "soco-salon.ru": 64069270,
    "www.soco-salon.ru": 64069270,
    "soco-moscow.ru": 95469576,
    "www.soco-moscow.ru": 95469576,
    "soco-kras.ru": 64069270,
    "www.soco-kras.ru": 64069270,
  };
  const BOOKING_HOST_RE =
    /(^|\.)((salon1c\.ru)|(mrqz\.me)|(t\.me)|(telegram\.me)|(wa\.me)|(api\.whatsapp\.com)|(max\.ru))$/i;
  const MARQUIZ_HASH_RE = /#popup:marquiz_([a-f0-9]+)/i;
  const TAPLINK_PATHS = ["/taplink", "/taplink2gisloyality", "/taplink2gisloyalty"];
  const DEFAULT_QUIZ = {
    "soco-salon.ru": "6a2bb00a0b0b620019381f83",
    "www.soco-salon.ru": "6a2bb00a0b0b620019381f83",
    "soco-kras.ru": "6a2bb00a0b0b620019381f83",
    "www.soco-kras.ru": "6a2bb00a0b0b620019381f83",
    "soco-moscow.ru": "6a32cb2ef8f81d00199756d7",
    "www.soco-moscow.ru": "6a32cb2ef8f81d00199756d7",
  };

  let cachedCid = "";

  function host() {
    return (window.location.hostname || "").toLowerCase();
  }

  function hostCounter() {
    return HOST_COUNTERS[host()] || 0;
  }

  function pageYmCid() {
    try {
      const p = new URLSearchParams(window.location.search);
      return (p.get("ym_cid") || p.get("yandex_client_id") || p.get("clientID") || p.get("client_id") || "")
        .trim()
        .slice(0, 64);
    } catch (_) {
      return "";
    }
  }

  function copyUtm(u) {
    const pageParams = new URLSearchParams(window.location.search);
    UTM_KEYS.forEach((key) => {
      const v = pageParams.get(key);
      if (v && !u.searchParams.has(key)) u.searchParams.set(key, v);
    });
  }

  function withYmCid(u, clientId) {
    const cid = String(clientId || cachedCid || "").trim().slice(0, 64);
    if (cid) u.searchParams.set("ym_cid", cid);
    copyUtm(u);
    return cid;
  }

  function quizIdFromPage() {
    const a = document.querySelector('a[href*="#popup:marquiz_"]');
    if (a) {
      const m = String(a.getAttribute("href") || "").match(MARQUIZ_HASH_RE);
      if (m) return m[1];
    }
    return DEFAULT_QUIZ[host()] || "";
  }

  function fetchClientId(cb) {
    if (cachedCid) return cb(cachedCid);
    const fromUrl = pageYmCid();
    if (fromUrl) {
      cachedCid = fromUrl;
      return cb(cachedCid);
    }

    const counterId = hostCounter();
    const tryGet = (attempt) => {
      if (typeof ym !== "function" || !counterId) {
        if (attempt < 20) return setTimeout(() => tryGet(attempt + 1), 250);
        return cb("");
      }
      let done = false;
      const t = setTimeout(() => {
        if (done) return;
        done = true;
        if (attempt < 20) tryGet(attempt + 1);
        else cb(cachedCid || "");
      }, 1200);
      try {
        ym(counterId, "getClientID", (id) => {
          if (done) return;
          const val = String(id || "").slice(0, 64);
          if (!val) {
            // ещё рано — повторим
            return;
          }
          done = true;
          clearTimeout(t);
          cachedCid = val;
          cb(cachedCid);
        });
      } catch (_) {
        clearTimeout(t);
        if (attempt < 20) setTimeout(() => tryGet(attempt + 1), 250);
        else cb("");
      }
    };
    tryGet(0);
  }

  function isTaplinkPath(pathname) {
    const path = String(pathname || "").toLowerCase();
    if (TAPLINK_PATHS.some((p) => path === p || path.indexOf(p) !== -1)) return true;
    return path.indexOf("taplink") !== -1;
  }

  function isOwnHost(hostname) {
    const h = String(hostname || "").toLowerCase();
    if (!h || h === host()) return true;
    return !!HOST_COUNTERS[h];
  }

  function marquizIdFromHref(href) {
    const m = String(href || "").match(MARQUIZ_HASH_RE);
    return m ? m[1] : "";
  }

  function classify(link) {
    const hrefAttr = link.getAttribute("href") || "";
    if (link.hasAttribute("data-soco-tryon")) return { kind: "primerka", href: hrefAttr };
    const mq = marquizIdFromHref(hrefAttr);
    if (mq) return { kind: "marquiz", href: hrefAttr, quizId: mq };

    if (!hrefAttr || hrefAttr.startsWith("tel:") || hrefAttr.startsWith("mailto:")) return null;
    try {
      const u = new URL(hrefAttr, window.location.href);
      if (u.hostname === PRIMERKA_HOST) return { kind: "primerka", href: hrefAttr };
      if (BOOKING_HOST_RE.test(u.hostname)) return { kind: "booking", href: hrefAttr };
      if (isOwnHost(u.hostname) && isTaplinkPath(u.pathname)) {
        return { kind: "taplink", href: hrefAttr };
      }
    } catch (_) {
      if (hrefAttr.indexOf(PRIMERKA_HOST) !== -1) return { kind: "primerka", href: hrefAttr };
      if (isTaplinkPath(hrefAttr)) return { kind: "taplink", href: hrefAttr };
    }
    return null;
  }

  function isMarquizWidget(el) {
    if (!el || !el.closest) return false;
    return !!(
      el.closest("[class*='marquiz']") ||
      el.closest("#marquiz") ||
      el.closest("[id*='marquiz']")
    );
  }

  function buildUrl(info, clientId, link) {
    const cid = clientId || cachedCid || "";
    if (info.kind === "primerka") {
      let u;
      try {
        u = new URL(info.href || "https://" + PRIMERKA_HOST + "/", window.location.href);
      } catch (_) {
        u = new URL("https://" + PRIMERKA_HOST + "/");
      }
      withYmCid(u, cid);
      if (!u.searchParams.get("return_url") && !u.searchParams.get("from")) {
        u.searchParams.set("from", window.location.href);
      }
      return u.toString();
    }
    if (info.kind === "marquiz") {
      const quizId = info.quizId || quizIdFromPage();
      const u = new URL("https://mrqz.me/" + quizId);
      withYmCid(u, cid);
      return u.toString();
    }
    if (info.kind === "taplink" || info.kind === "booking") {
      let u;
      try {
        u = new URL(info.href, window.location.href);
      } catch (_) {
        return info.href;
      }
      withYmCid(u, cid);
      if (info.kind === "booking") {
        const h = u.hostname.toLowerCase();
        if (
          h === "t.me" ||
          h.endsWith(".t.me") ||
          h === "telegram.me" ||
          h === "wa.me" ||
          h === "api.whatsapp.com" ||
          h === "max.ru" ||
          h.endsWith(".max.ru")
        ) {
          if (cid) {
            const marker = "ym_cid:" + cid;
            const prev = u.searchParams.get("text") || "";
            if (prev && prev.indexOf(cid) === -1) u.searchParams.set("text", prev + "\n" + marker);
            else if (!prev) u.searchParams.set("text", "Здравствуйте! Хочу записаться\n" + marker);
          }
        }
      }
      return u.toString();
    }
    return info.href;
  }

  function patchHrefs(clientId) {
    if (!clientId) return;
    document.querySelectorAll("a[href], a[data-soco-tryon]").forEach((link) => {
      const info = classify(link);
      if (!info) return;
      const next = buildUrl(info, clientId, link);
      const prev = link.getAttribute("href") || "";
      if (next && next !== prev) {
        link.setAttribute("href", next);
        if (info.kind === "taplink") {
          link.classList.remove("js--link-to-page");
          link.removeAttribute("data-page");
          link.setAttribute("data-type", "goToLink");
        }
      }
    });
  }

  function navigate(url, link, ev) {
    const blank =
      (link && (link.getAttribute("target") || "").toLowerCase() === "_blank") ||
      (ev && (ev.ctrlKey || ev.metaKey));
    if (blank) window.open(url, "_blank", "noopener");
    else window.location.assign(url);
  }

  function handleEvent(ev) {
    const t = ev.target;
    if (!t) return;

    // Виджет Marquiz Pop (не <a #popup...>)
    if (isMarquizWidget(t) && !t.closest("a[href]")) {
      const quizId = quizIdFromPage();
      if (!quizId) return;
      ev.preventDefault();
      ev.stopPropagation();
      if (ev.stopImmediatePropagation) ev.stopImmediatePropagation();
      fetchClientId((id) => {
        const u = new URL("https://mrqz.me/" + quizId);
        withYmCid(u, id);
        window.open(u.toString(), "_blank", "noopener");
      });
      return;
    }

    const link = t.closest ? t.closest("a[href], a[data-soco-tryon]") : null;
    if (!link) return;
    const info = classify(link);
    if (!info) return;
    if (!hostCounter() && !pageYmCid() && !cachedCid) return;

    ev.preventDefault();
    ev.stopPropagation();
    if (ev.stopImmediatePropagation) ev.stopImmediatePropagation();

    fetchClientId((id) => navigate(buildUrl(info, id, link), link, ev));
  }

  // capture на document — раньше Vigbo js--link-to-page
  document.addEventListener("click", handleEvent, true);
  document.addEventListener("auxclick", handleEvent, true);

  function boot() {
    fetchClientId((id) => {
      patchHrefs(id);
      // повторные попытки: Метрика/кнопки могут появиться позже
      [500, 1500, 3000, 6000].forEach((ms) => {
        setTimeout(() => fetchClientId(patchHrefs), ms);
      });
    });
    try {
      const mo = new MutationObserver(() => {
        if (cachedCid) patchHrefs(cachedCid);
      });
      mo.observe(document.documentElement, { childList: true, subtree: true });
    } catch (_) {}
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
})();
