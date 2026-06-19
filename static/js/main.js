// path: static/js/main.js
// TheCustomDuelist — front-end behaviour.
//
// Display switches. A `.view-toggle` is a group of buttons/links that flip a
// target container between named views (e.g. grid/list on search, reading/grid
// inside an article). Both views are rendered by the server and the buttons are
// real links (so the choice works without JS); here we upgrade them to flip
// views instantly, no reload. A toggle declares its target + URL param via
// data attributes; if omitted it defaults to the search results container.
document.addEventListener("DOMContentLoaded", () => {
  const toggles = Array.from(document.querySelectorAll(".view-toggle"));
  if (!toggles.length) return;

  toggles.forEach((toggle) => {
    const sel = toggle.dataset.target;
    const target = sel
      ? document.querySelector(sel)
      : document.getElementById("search-results");
    if (!target) return;

    const param = toggle.dataset.param || "view";
    const buttons = Array.from(toggle.querySelectorAll(".view-toggle__btn"));

    const setView = (view) => {
      target.dataset.view = view;
      buttons.forEach((btn) => {
        const active = btn.dataset.view === view;
        btn.classList.toggle("is-active", active);
        btn.setAttribute("aria-pressed", active ? "true" : "false");
      });
      // Keep the URL shareable/reload-safe without adding history entries.
      const url = new URL(window.location.href);
      url.searchParams.set(param, view);
      window.history.replaceState({}, "", url);
    };

    buttons.forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.preventDefault();
        setView(btn.dataset.view);
      });
    });
  });
});
