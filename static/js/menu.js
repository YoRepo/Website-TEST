// path: static/js/menu.js
// Toolbar <details> menus: close on outside-click or Escape, and only allow
// one open at a time. Pure enhancement — native <details> works without this.
document.addEventListener("DOMContentLoaded", () => {
  const menus = Array.from(document.querySelectorAll(".menu"));
  if (!menus.length) return;

  menus.forEach((m) => {
    m.addEventListener("toggle", () => {
      if (m.open) menus.forEach((o) => { if (o !== m) o.open = false; });
    });
  });

  document.addEventListener("click", (e) => {
    menus.forEach((m) => { if (m.open && !m.contains(e.target)) m.open = false; });
  });

  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape") return;
    menus.forEach((m) => {
      if (m.open) { m.open = false; const s = m.querySelector("summary"); if (s) s.focus(); }
    });
  });
});