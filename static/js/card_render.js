// path: static/js/card_render.js
// Wherever a card has no finished render image, the server emits an empty host
// carrying the card's state in data-card-svg. Turn each into the same inline
// SVG the editor previews. No-ops on pages without any such hosts.
document.addEventListener("DOMContentLoaded", () => {
  const staticBase = document.body.dataset.static || "/static/";
  const hosts = document.querySelectorAll("[data-card-svg]");
  if (!hosts.length || !window.CardSVG) return;

  const draw = (el) => {
    let state;
    try { state = JSON.parse(el.getAttribute("data-card-svg")); }
    catch { return; }
    el.innerHTML = window.CardSVG.build(state, staticBase);
    const im = el.querySelector("image");
    if (im) im.addEventListener("error", () => { im.style.display = "none"; }, { once: true });
  };

  hosts.forEach(draw);
  // Re-draw once web fonts load so text fitting uses real metrics.
  if (document.fonts && document.fonts.ready) {
    document.fonts.ready.then(() => hosts.forEach(draw));
  }
});