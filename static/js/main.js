// path: static/js/main.js
// TheCustomDuelist — front-end behaviour.
//
// Search results page: a Grid/List display switch. Both views are rendered by
// the server; the buttons are real links (so the choice works without JS), and
// here we upgrade them to flip between the two views instantly, no reload.
document.addEventListener("DOMContentLoaded", () => {
  const results = document.getElementById("search-results");
  const toggle = document.querySelector(".view-toggle");
  if (!results || !toggle) return; // not on the search results page

  const buttons = Array.from(toggle.querySelectorAll(".view-toggle__btn"));

  const setView = (view) => {
    results.dataset.view = view;
    buttons.forEach((btn) => {
      const active = btn.dataset.view === view;
      btn.classList.toggle("is-active", active);
      btn.setAttribute("aria-pressed", active ? "true" : "false");
    });
    // Keep the URL shareable/reload-safe without adding history entries.
    const url = new URL(window.location.href);
    url.searchParams.set("view", view);
    window.history.replaceState({}, "", url);
  };

  buttons.forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.preventDefault();
      setView(btn.dataset.view);
    });
  });
});
