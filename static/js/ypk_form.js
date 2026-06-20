// path: static/js/ypk_form.js
// State-driven .ypk pack builder. A flat list of cards; each one contributes
// its Card ID, Lua script, and render image (all set in the card editor), so
// there's nothing to type per card. Per-card badges flag a missing script or
// image before you generate. On submit the list is serialised into the hidden
// #structure field and the server streams back a downloadable .ypk.

document.addEventListener("DOMContentLoaded", () => {
  const root = document.getElementById("ypk-editor");
  if (!root) return;

  const form = document.getElementById("ypk-form");
  const hidden = document.getElementById("structure");
  const host = document.getElementById("ypk-cards");
  const addCardBtn = document.getElementById("ypk-addcard");

  const ALL = JSON.parse(document.getElementById("all-cards").textContent || "[]");
  const byId = Object.fromEntries(ALL.map((c) => [String(c.id), c]));
  const staticBase = document.body.dataset.static || "/static/";

  let state;
  try { state = JSON.parse(document.getElementById("ypk-structure").textContent || "{}"); }
  catch { state = { cards: [] }; }
  if (!state.cards) state.cards = [];

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g,
      (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  function render() {
    host.innerHTML = "";
    if (!state.cards.length) {
      const empty = document.createElement("p");
      empty.className = "field__hint";
      empty.textContent = "No cards yet — use “+ Add card” to choose some.";
      host.appendChild(empty);
      return;
    }
    state.cards.forEach((c, ci) => host.appendChild(renderCard(c, ci)));
  }

  function badge(ok, okText, missText) {
    const cls = ok ? "ypk-badge ypk-badge--ok" : "ypk-badge ypk-badge--warn";
    return `<span class="${cls}">${ok ? "✓" : "!"} ${esc(ok ? okText : missText)}</span>`;
  }

  function renderCard(c, ci) {
    const meta = byId[String(c.card_id)] ||
      { name: "Unknown card #" + c.card_id, type_line: "", cdb_id: "", has_script: false, has_image: false };
    const idText = (meta.cdb_id === 0 || meta.cdb_id) ? String(meta.cdb_id) : "— no Card ID —";
    const row = document.createElement("div");
    row.className = "acard";
    row.innerHTML = `
      <div class="acard__main">
        <div class="acard__name">${esc(meta.name)}
          <span class="acard__type">${esc(meta.type_line)}</span></div>
        <div class="ypk-badges">
          <span class="ypk-badge ${meta.cdb_id ? "ypk-badge--ok" : "ypk-badge--warn"}">id ${esc(idText)}</span>
          ${badge(meta.has_script, "script", "no script")}
          ${badge(meta.has_image, "image", "no image")}
        </div>
      </div>
      <div class="acard__bar">
        <button type="button" class="link-gold" data-a="cup">↑</button>
        <button type="button" class="link-gold" data-a="cdown">↓</button>
        <button type="button" class="link-danger" data-a="cdel">✕</button>
      </div>`;
    row.querySelector('[data-a="cup"]').addEventListener("click", () => moveCard(ci, -1));
    row.querySelector('[data-a="cdown"]').addEventListener("click", () => moveCard(ci, 1));
    row.querySelector('[data-a="cdel"]').addEventListener("click", () => {
      state.cards.splice(ci, 1); render();
    });
    return row;
  }

  function moveCard(i, d) {
    const j = i + d;
    if (j < 0 || j >= state.cards.length) return;
    [state.cards[i], state.cards[j]] = [state.cards[j], state.cards[i]];
    render();
  }

  addCardBtn.addEventListener("click", () => {
    openPicker((card) => {
      state.cards.push({ card_id: card.id });
      render();
    });
  });

  form.addEventListener("submit", () => { hidden.value = JSON.stringify(state); });

  // =====================================================================
  //  VISUAL CARD PICKER  (same widget as the article editor)
  // =====================================================================
  let onPick = null;
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
