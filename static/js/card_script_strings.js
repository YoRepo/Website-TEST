// path: static/js/card_script_strings.js
// Ties the Lua script editor to the card-string inputs.
//   • Highlights every string reference — aux.Stringid(id, n) — inside the
//     script editor with a soft amber backdrop, so they're easy to spot.
//   • Under each string input, shows a live note when that string's id (n) is
//     referenced by the script, telling you where, so you know which strings
//     actually need configuring.
// Both react in real time: the script box can be typed in or pasted into, and
// the highlights + notes stay in sync with whatever it currently contains.
(function () {
  // aux.Stringid(id, n)  — also matches a bare Stringid(id, n).
  // The first argument may itself be a call (e.g. c:GetOriginalCode()), so we
  // allow a single nested parenthesised group inside it. We capture n.
  const STRINGID =
    /\b(?:aux\.)?Stringid\s*\(\s*[^,()]*(?:\([^()]*\))?[^,()]*,\s*(\d+)\s*\)/g;

  function escapeHtml(s) {
    return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  // Scan the script for string references. Returns one entry per call with the
  // referenced string id and the 1-based line it sits on.
  function findRefs(text) {
    const refs = [];
    STRINGID.lastIndex = 0;
    let m;
    while ((m = STRINGID.exec(text)) !== null) {
      refs.push({
        start: m.index,
        end: m.index + m[0].length,
        id: parseInt(m[1], 10),
        line: text.slice(0, m.index).split("\n").length,
      });
      // Guard against a zero-width match wedging the loop.
      if (m.index === STRINGID.lastIndex) STRINGID.lastIndex++;
    }
    return refs;
  }

  document.addEventListener("DOMContentLoaded", () => {
    const script = document.getElementById("script");
    if (!script) return;

    // --- Build the highlight backdrop --------------------------------------
    // A mirror <div> sits behind the (now transparent) textarea and paints the
    // matched calls. The textarea's real text renders on top, so the caret and
    // editing behaviour are untouched — we only draw coloured rectangles behind
    // the references. Fonts/metrics are kept identical via CSS so they line up.
    const wrap = document.createElement("div");
    wrap.className = "codewrap";
    script.parentNode.insertBefore(wrap, script);
    const backdrop = document.createElement("div");
    backdrop.className = "codehl";
    backdrop.setAttribute("aria-hidden", "true");
    wrap.appendChild(backdrop);
    wrap.appendChild(script);

    function renderHighlight(text, refs) {
      let html = "";
      let last = 0;
      refs.forEach((r) => {
        html += escapeHtml(text.slice(last, r.start));
        html += '<mark class="codehl__ref">' +
          escapeHtml(text.slice(r.start, r.end)) + "</mark>";
        last = r.end;
      });
      html += escapeHtml(text.slice(last));
      // Trailing newline so the backdrop's scroll height tracks the textarea's.
      backdrop.innerHTML = html + "\n";
    }

    function syncScroll() {
      backdrop.scrollTop = script.scrollTop;
      backdrop.scrollLeft = script.scrollLeft;
    }

    // --- Per-string notes --------------------------------------------------
    // One note element per string row, keyed by the string id (from the input
    // name string_N). Hidden until the script references that id.
    const noteById = {};
    document.querySelectorAll(".strings .strings__row").forEach((row) => {
      const input = row.querySelector(".strings__input");
      const m = input && /string_(\d+)/.exec(input.name);
      if (!m) return;
      const note = document.createElement("p");
      note.className = "strings__note";
      note.hidden = true;
      row.appendChild(note);
      noteById[parseInt(m[1], 10)] = note;
    });

    function updateNotes(refs) {
      const linesById = {};
      refs.forEach((r) => {
        (linesById[r.id] = linesById[r.id] || []).push(r.line);
      });
      Object.keys(noteById).forEach((key) => {
        const note = noteById[key];
        const lines = linesById[key];
        if (lines && lines.length) {
          const uniq = [...new Set(lines)].sort((a, b) => a - b);
          const where = uniq.length === 1
            ? "line " + uniq[0]
            : "lines " + uniq.join(", ");
          const times = lines.length > 1 ? " · " + lines.length + " refs" : "";
          note.textContent = "↑ Referenced in the script — " + where + times;
          note.hidden = false;
        } else {
          note.textContent = "";
          note.hidden = true;
        }
      });
    }

    function refresh() {
      const text = script.value;
      const refs = findRefs(text);
      renderHighlight(text, refs);
      updateNotes(refs);
      syncScroll();
    }

    script.addEventListener("input", refresh);
    script.addEventListener("scroll", syncScroll);
    refresh();
  });
})();
