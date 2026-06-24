// path: static/js/copy_card.js
// "Copy card as text" buttons on the immersive list/reading view. Each button
// carries the server-formatted plaintext in data-copytext (JSON-encoded). On
// click we write it to the clipboard and briefly confirm. Uses event delegation
// so it covers every showcase on the page, including any added later.

document.addEventListener("DOMContentLoaded", () => {
  function flash(btn, msg, ok) {
    const label = btn.querySelector(".copycard__label");
    if (btn._copyTimer) {
      clearTimeout(btn._copyTimer);
      if (label && btn._copyPrev != null) label.textContent = btn._copyPrev;
    }
    if (label) {
      if (btn._copyPrev == null) btn._copyPrev = label.textContent;
      label.textContent = msg;
    }
    btn.classList.toggle("is-copied", ok !== false);
    btn.classList.toggle("is-copyfail", ok === false);
    btn._copyTimer = setTimeout(() => {
      btn.classList.remove("is-copied", "is-copyfail");
      if (label && btn._copyPrev != null) label.textContent = btn._copyPrev;
      btn._copyPrev = null;
      btn._copyTimer = null;
    }, 1500);
  }

  async function writeClipboard(text) {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text);
      return;
    }
    // Fallback for non-secure contexts / older browsers.
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.setAttribute("readonly", "");
    ta.style.position = "fixed";
    ta.style.top = "-9999px";
    document.body.appendChild(ta);
    ta.select();
    const ok = document.execCommand("copy");
    document.body.removeChild(ta);
    if (!ok) throw new Error("copy command rejected");
  }

  document.addEventListener("click", (e) => {
    const btn = e.target.closest(".copycard");
    if (!btn) return;
    let text = btn.dataset.copytext || "";
    try { text = JSON.parse(text); } catch { /* keep raw string */ }
    writeClipboard(text)
      .then(() => flash(btn, "Copied!", true))
      .catch(() => flash(btn, "Press Ctrl+C", false));
  });
});
