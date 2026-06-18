// path: static/js/article_form.js
// State-driven article editor. Reads the initial structure + card list from
// inline JSON, lets you add/reorder sections and cards (with captions), and
// serialises everything into the hidden #structure field on submit.

document.addEventListener("DOMContentLoaded", () => {
  const root = document.getElementById("article-editor");
  if (!root) return;

  const form = document.getElementById("article-form");
  const hidden = document.getElementById("structure");
  const host = document.getElementById("sections-host");
  const addSectionBtn = document.getElementById("add-section");

  const ALL = JSON.parse(document.getElementById("all-cards").textContent || "[]");
  const byId = Object.fromEntries(ALL.map((c) => [String(c.id), c]));
  const options =
    `<option value="">— Choose a card —</option>` +
    ALL.map((c) => `<option value="${c.id}">${esc(c.name)} — ${esc(c.type_line)}</option>`).join("");

  let state;
  try { state = JSON.parse(document.getElementById("article-structure").textContent || "{}"); }
  catch { state = { sections: [] }; }
  if (!state.sections || !state.sections.length) {
    state.sections = [{ heading: "", body: "", cards: [] }];
  }

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g,
      (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  function render() {
    host.innerHTML = "";
    state.sections.forEach((sec, si) => host.appendChild(renderSection(sec, si)));
  }

  function renderSection(sec, si) {
    const el = document.createElement("fieldset");
    el.className = "block asec";
    el.innerHTML = `
      <legend>Section ${si + 1}</legend>
      <div class="asec__bar">
        <button type="button" class="link-gold" data-a="up">↑</button>
        <button type="button" class="link-gold" data-a="down">↓</button>
        <button type="button" class="link-danger" data-a="del">Remove section</button>
      </div>
      <div class="field">
        <label>Heading <span class="field__hint">(optional)</span></label>
        <input type="text" class="asec__heading" maxlength="200">
      </div>
      <div class="field">
        <label>Section text <span class="field__hint">(optional)</span></label>
        <textarea class="asec__body" rows="3" data-autocircle></textarea>
      </div>
      <div class="asec__cards"></div>
      <div class="asec__add">
        <select class="asec__picker">${options}</select>
        <button type="button" class="btn btn--ghost asec__addcard">+ Add card</button>
      </div>`;

    el.querySelector(".asec__heading").value = sec.heading || "";
    el.querySelector(".asec__body").value = sec.body || "";
    el.querySelector(".asec__heading").addEventListener("input", (e) => { sec.heading = e.target.value; });
    el.querySelector(".asec__body").addEventListener("input", (e) => { sec.body = e.target.value; });

    el.querySelector('[data-a="up"]').addEventListener("click", () => moveSection(si, -1));
    el.querySelector('[data-a="down"]').addEventListener("click", () => moveSection(si, 1));
    el.querySelector('[data-a="del"]').addEventListener("click", () => {
      state.sections.splice(si, 1);
      if (!state.sections.length) state.sections.push({ heading: "", body: "", cards: [] });
      render();
    });
    el.querySelector(".asec__addcard").addEventListener("click", () => {
      const id = el.querySelector(".asec__picker").value;
      if (!id) return;
      sec.cards.push({ card_id: parseInt(id, 10), caption: "" });
      render();
    });

    const cardsHost = el.querySelector(".asec__cards");
    sec.cards.forEach((c, ci) => cardsHost.appendChild(renderCard(sec, c, ci)));
    return el;
  }

  function renderCard(sec, c, ci) {
    const meta = byId[String(c.card_id)] || { name: "Unknown card #" + c.card_id, type_line: "" };
    const row = document.createElement("div");
    row.className = "acard";
    row.innerHTML = `
      <div class="acard__main">
        <div class="acard__name">${esc(meta.name)}
          <span class="acard__type">${esc(meta.type_line)}</span></div>
        <input type="text" class="acard__caption" maxlength="400"
               placeholder="Caption — lore, a tip, a comment…">
      </div>
      <div class="acard__bar">
        <button type="button" class="link-gold" data-a="cup">↑</button>
        <button type="button" class="link-gold" data-a="cdown">↓</button>
        <button type="button" class="link-danger" data-a="cdel">✕</button>
      </div>`;
    row.querySelector(".acard__caption").value = c.caption || "";
    row.querySelector(".acard__caption").addEventListener("input", (e) => { c.caption = e.target.value; });
    row.querySelector('[data-a="cup"]').addEventListener("click", () => moveCard(sec, ci, -1));
    row.querySelector('[data-a="cdown"]').addEventListener("click", () => moveCard(sec, ci, 1));
    row.querySelector('[data-a="cdel"]').addEventListener("click", () => { sec.cards.splice(ci, 1); render(); });
    return row;
  }

  function moveSection(i, d) {
    const j = i + d;
    if (j < 0 || j >= state.sections.length) return;
    [state.sections[i], state.sections[j]] = [state.sections[j], state.sections[i]];
    render();
  }
  function moveCard(sec, i, d) {
    const j = i + d;
    if (j < 0 || j >= sec.cards.length) return;
    [sec.cards[i], sec.cards[j]] = [sec.cards[j], sec.cards[i]];
    render();
  }

  addSectionBtn.addEventListener("click", () => {
    state.sections.push({ heading: "", body: "", cards: [] });
    render();
  });

  form.addEventListener("submit", () => { hidden.value = JSON.stringify(state); });

  render();
});