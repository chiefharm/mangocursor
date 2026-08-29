/**
 * Кнопка «Примерка SOCO AI» на основных сайтах.
 * Перед переходом на primerka забирает ClientID Яндекс.Метрики и UTM.
 *
 * 1) Поставьте data-metrika-counter на ссылку (см. ниже).
 * 2) Подключите этот скрипт после счётчика Метрики на странице.
 *
 * Счётчики:
 *   soco-salon.ru  → 64069270
 *   soco-moscow.ru → 95469576
 *   soco-kras.ru   → 64069270 (как soco-salon.ru)
 */
(function () {
  const PRIMERKA = "https://primerka.soco-salon.ru/";
  const UTM_KEYS = ["utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term", "yclid"];

  function buildUrl(clientId) {
    const u = new URL(PRIMERKA);
    if (clientId) u.searchParams.set("ym_cid", String(clientId).slice(0, 64));
    const pageParams = new URLSearchParams(window.location.search);
    UTM_KEYS.forEach((key) => {
      const v = pageParams.get(key);
      if (v) u.searchParams.set(key, v);
    });
    u.searchParams.set("from", window.location.href);
    return u.toString();
  }

  function bindLink(link) {
    const counterId = Number(link.getAttribute("data-metrika-counter") || "0");
    if (!counterId) return;

    link.addEventListener("click", function (ev) {
      ev.preventDefault();
      const go = (id) => {
        window.location.href = buildUrl(id);
      };
      if (typeof ym === "function") {
        let done = false;
        const t = setTimeout(() => {
          if (!done) {
            done = true;
            go("");
          }
        }, 1200);
        try {
          ym(counterId, "getClientID", (clientID) => {
            if (done) return;
            done = true;
            clearTimeout(t);
            go(clientID);
          });
        } catch (_) {
          clearTimeout(t);
          go("");
        }
      } else {
        go("");
      }
    });
  }

  document.querySelectorAll("a[data-soco-tryon]").forEach(bindLink);
})();

/*
HTML example (soco-moscow.ru):

<a
  href="https://primerka.soco-salon.ru/"
  data-soco-tryon
  data-metrika-counter="95469576"
>
  Сделать примерку образа с помощью SOCO AI
</a>
<script src="/path/to/embed_tryon_link.js"></script>
*/
