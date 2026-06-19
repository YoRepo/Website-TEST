// path: static/js/enclosed.js
// Type "(1)" and it becomes "①" (1–20). Also "(a)" → "ⓐ", "(A)" → "Ⓐ",
// and "(*)" → "•" (a bullet point).
// Pure front-end convenience; the real Unicode character is what gets saved.
(function () {
  function circled(token) {
    const m = /^\((\d{1,2}|[a-zA-Z]|\*)\)$/.exec(token);
    if (!m) return null;
    const v = m[1];
    if (v === "*") return "•";                  // •
    if (/^\d+$/.test(v)) {
      const n = parseInt(v, 10);
      if (n === 0) return "\u24EA";                  // ⓪
      if (n >= 1 && n <= 20) return String.fromCharCode(0x245F + n); // ①–⑳
      return null;
    }
    const lower = v.toLowerCase();
    const base = lower === v ? 0x24D0 : 0x24B6;      // ⓐ.. or Ⓐ..
    return String.fromCharCode(base + (lower.charCodeAt(0) - 97));
  }

  // Match either a "(x)" token OR a single already-circled glyph, so we can
  // both create markers and undo them.
  const CIRCLED = "[\\u2460-\\u2473\\u24ea\\u24d0-\\u24e9\\u24b6-\\u24cf\\u2022]";
  const SCAN = new RegExp("\\((?:\\d{1,2}|[a-zA-Z]|\\*)\\)|" + CIRCLED, "g");
  const isLetter = (ch) => ch != null && /[a-zA-Z]/.test(ch);

  // Inverse of circled(): turn a glyph back into its "(x)" source token.
  function uncircle(ch) {
    const code = ch.codePointAt(0);
    if (code === 0x2022) return "(*)";                                  // •
    if (code === 0x24ea) return "(0)";                                  // ⓪
    if (code >= 0x2460 && code <= 0x2473) return "(" + (code - 0x245f) + ")"; // ①–⑳
    if (code >= 0x24d0 && code <= 0x24e9)                               // ⓐ–ⓩ
      return "(" + String.fromCharCode(97 + code - 0x24d0) + ")";
    if (code >= 0x24b6 && code <= 0x24cf)                               // Ⓐ–Ⓩ
      return "(" + String.fromCharCode(65 + code - 0x24b6) + ")";
    return null;
  }

  function apply(el) {
    const before = el.value;
    const caret = el.selectionStart;
    let after = "";
    let newCaret = caret;
    let last = 0;
    let m;
    SCAN.lastIndex = 0;
    while ((m = SCAN.exec(before)) !== null) {
      const tok = m[0];
      const start = m.index;
      const end = start + tok.length;
      // "touching a letter" = a letter immediately before "(" or after ")".
      const touches = isLetter(before[start - 1]) || isLetter(before[end]);

      let repl = tok;
      if (tok[0] === "(") {
        // "(x)" → glyph ONLY when it isn't glued to a letter (so "card(s)" stays).
        if (!touches) repl = circled(tok) || tok;
      } else {
        // A glyph that's now glued to a letter reverts back to "(x)".
        if (touches) repl = uncircle(tok) || tok;
      }

      after += before.slice(last, start) + repl;
      last = end;

      if (repl !== tok) {
        const d = repl.length - tok.length;
        if (end <= caret) newCaret += d;          // token fully before caret
        else if (start < caret) newCaret = after.length; // caret inside token
        // start >= caret: token is after the caret, no shift
      }
    }
    after += before.slice(last);

    if (after !== before) {
      el.value = after;
      const pos = Math.max(0, Math.min(after.length, newCaret));
      el.setSelectionRange(pos, pos);
    }
  }

  document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll("textarea[data-autocircle]").forEach((el) => {
      el.addEventListener("input", () => apply(el));
    });
  });
})();