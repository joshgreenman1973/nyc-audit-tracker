/* Browser-side collector for the Citizens Budget Commission listing.
 *
 * CBC sits behind Cloudflare, which blocks scripted fetches with a 403, but the
 * pages render normally in a real browser. This runs in the page context: it
 * walks https://cbcny.org/research/listing?page=N and returns the items.
 *
 * Usage: paste into the browser tool's javascript_exec with a page number, or
 * call collectPage(n) after navigating to the listing.
 * Output rows: {kind, topic, title, url, issued}
 */
(function () {
  const MONTHS = { january: 1, february: 2, march: 3, april: 4, may: 5, june: 6,
                   july: 7, august: 8, september: 9, october: 10, november: 11, december: 12 };

  function isoDate(text) {
    const m = (text || "").match(/([A-Za-z]+)\s+(\d{1,2}),\s*(\d{4})/);
    if (!m) return null;
    const mo = MONTHS[m[1].toLowerCase()];
    if (!mo) return null;
    return `${m[3]}-${String(mo).padStart(2, "0")}-${String(+m[2]).padStart(2, "0")}`;
  }

  window.collectCBC = function () {
    return [...document.querySelectorAll("article.node--display-mode-teaser, article.card")].map(el => {
      const link = el.querySelector("h2 a, a.card__link, a[href]");
      const info = [...el.querySelectorAll(".post-info__item")].map(s => s.textContent.trim());
      const kind = (el.querySelector(".card__type")?.textContent || info[0] || "").trim();
      const topic = (info[1] || "").trim();
      const title = (el.querySelector(".node__title, .card__title")?.textContent || link?.textContent || "")
        .replace(/\s+/g, " ").trim();
      const dateText = (el.querySelector(".card__date, .post-info__date, time")?.textContent || el.textContent);
      let href = link?.getAttribute("href") || "";
      if (href.startsWith("/")) href = "https://cbcny.org" + href;
      return { kind, topic, title, url: href, issued: isoDate(dateText) };
    }).filter(r => r.url && r.title);
  };

  return window.collectCBC();
})();
