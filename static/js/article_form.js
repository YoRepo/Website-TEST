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
  const staticBase = document.body.dataset.static || "/static/";

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
      openPicker((card) => {
        sec.cards.push({ card_id: card.id, caption: "" });
        render();
      });
    });

    const cardsHost = el.querySelector(".asec__cards");
    sec.cards.forEach((c, ci) => cardsHost.appendChild(renderCard(sec, c, ci)));
    return el;
  }

  function renderCard(sec, c, ci) {
    const meta = byId[String(c.card_id)] || { name: "Unknown card #" + c.card_id, type_line: "" };
    const row = document.createElement("div");
    row.className = "acard";
    const hasComment = !!(c.caption && c.caption.trim());
    row.innerHTML = `
      <div class="acard__main">
        <div class="acard__name">${esc(meta.name)}
          <span class="acard__type">${esc(meta.type_line)}</span></div>
        <button type="button" class="acard__addcomment link-gold"${hasComment ? " hidden" : ""}>+ Comment</button>
        <textarea class="acard__caption" rows="2"
                  placeholder="A comment, a tip, lore…"${hasComment ? "" : " hidden"}></textarea>
      </div>
      <div class="acard__bar">
        <button type="button" class="link-gold" data-a="cup">↑</button>
        <button type="button" class="link-gold" data-a="cdown">↓</button>
        <button type="button" class="link-danger" data-a="cdel">✕</button>
      </div>`;
    const caption = row.querySelector(".acard__caption");
    const addComment = row.querySelector(".acard__addcomment");
    caption.value = c.caption || "";
    caption.addEventListener("input", (e) => { c.caption = e.target.value; });
    addComment.addEventListener("click", () => {
      addComment.hidden = true;
      caption.hidden = false;
      caption.focus();
    });
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

  // =====================================================================
  //  VISUAL CARD PICKER
  //  A modal with a search bar and a grid of card images. Tap a card to
  //  pick it. Built once, reused by every section's "+ Add card" button.
  // =====================================================================
  let onPick = null;          // callback for the current open session
  const picker = document.createElement("div");
  picker.className = "cardpicker";
  picker.hidden = true;
  picker.innerHTML = `
    <div class="cardpicker__backdrop" data-close></div>
    <div class="cardpicker__dialog" role="dialog" aria-modal="true" aria-label="Choose a card">
      <div class="cardpicker__head">
        <input type="search" class="cardpicker__search" placeholder="Search cards by name or set…" autocomplete="off">
        <button type="button" class="cardpicker__close" aria-label="Close" data-close>&times;</button>
      </div>
      <div class="cardpicker__grid"></div>
      <p class="cardpicker__empty" hidden>No cards match that search.</p>
    </div>`;
  document.body.appendChild(picker);

  const searchInput = picker.querySelector(".cardpicker__search");
  const grid = picker.querySelector(".cardpicker__grid");
  const emptyMsg = picker.querySelector(".cardpicker__empty");

  function cardImageHTML(c) {
    if (c.render_image) {
      const src = window.CardSVG
        ? window.CardSVG.resolveImageSrc(c.render_image, staticBase)
        : c.render_image;
      return `<img src="${esc(src)}" alt="" loading="lazy" draggable="false">`;
    }
    if (window.CardSVG && c.svg_state) {
      return window.CardSVG.build(c.svg_state, staticBase);
    }
    return `<span class="cardpicker__placeholder">${esc(c.name)}</span>`;
  }

  function renderPicker(filter) {
    const q = (filter || "").trim().toLowerCase();
    const matches = ALL.filter((c) =>
      !q || c.name.toLowerCase().includes(q) || (c.set || "").toLowerCase().includes(q));
    grid.innerHTML = matches.map((c) => `
      <button type="button" class="cardpicker__tile" data-id="${c.id}" title="${esc(c.name)}">
        <span class="cardpicker__img">${cardImageHTML(c)}</span>
        <span class="cardpicker__name">${esc(c.name)}</span>
        ${c.set ? `<span class="cardpicker__set">${esc(c.set)}</span>` : ""}
      </button>`).join("");
    emptyMsg.hidden = matches.length > 0;
  }

  function openPicker(cb) {
    onPick = cb;
    searchInput.value = "";
    renderPicker("");
    picker.hidden = false;
    document.body.classList.add("is-modal-open");
    searchInput.focus();
  }

  function closePicker() {
    picker.hidden = true;
    onPick = null;
    document.body.classList.remove("is-modal-open");
  }

  searchInput.addEventListener("input", () => renderPicker(searchInput.value));
  grid.addEventListener("click", (e) => {
    const tile = e.target.closest(".cardpicker__tile");
    if (!tile) return;
    const card = byId[tile.dataset.id];
    if (card && onPick) onPick(card);
    closePicker();
  });
  picker.addEventListener("click", (e) => { if (e.target.dataset.close !== undefined) closePicker(); });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !picker.hidden) closePicker();
  });

  render();
});