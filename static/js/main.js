// path: static/js/main.js
// TheCustomDuelist — front-end behaviour.
// Progressive enhancement: the search form works without JS (it GETs /search).
// With JS, we filter the already-rendered grid instantly as you type.

document.addEventListener("DOMContentLoaded", () => {
  const input = document.getElementById("site-search");
  const grid = document.getElementById("article-grid");
  if (!input || !grid) return; // not on the homepage

  const cards = Array.from(grid.querySelectorAll(".article-card"));
  const note = document.getElementById("results-note");
  const empty = document.getElementById("empty-state");
  const form = input.closest("form");

  // With JS available, don't reload the page on submit — filtering is live.
  if (form) form.addEventListener("submit", (e) => e.preventDefault());

  const apply = () => {
    const q = input.value.trim().toLowerCase();
    let shown = 0;

    cards.forEach((card) => {
      const haystack = card.getAttribute("data-search") || "";
      const match = q === "" || haystack.includes(q);
      card.hidden = !match;
      if (match) shown += 1;
    });

    if (empty) empty.hidden = shown !== 0;

    if (note) {
      if (q === "") {
        note.hidden = true;
      } else {
        note.hidden = false;
        note.textContent = `${shown} result${shown === 1 ? "" : "s"} for “${input.value.trim()}”.`;
      }
    }
  };

  input.addEventListener("input", apply);
  apply(); // run once in case the field is pre-filled
});