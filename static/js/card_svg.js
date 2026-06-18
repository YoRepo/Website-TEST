// path: static/js/card_svg.js
// Framework-free card renderer. Builds a full card as an inline SVG string
// from a normalised "state" object (see Card.svg_state on the server and
// readState() in card_form.js — both produce the same shape). Exposed as
// window.CardSVG so the editor preview AND the rest of the site share one
// renderer.
(function () {
  const CARD_W = 590, CARD_H = 860, M = 28;

  const FRAME = {
    normal:"#C8A85A", effect:"#B05A38", ritual:"#5A77B0", fusion:"#8A5BA8",
    synchro:"#DADAD0", xyz:"#26262B", link:"#2E5A82", spell:"#1F8E7E", trap:"#B0497F",
  };

  const _mc = document.createElement("canvas").getContext("2d");

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, (c) =>
      ({ "&":"&amp;", "<":"&lt;", ">":"&gt;", "\"":"&quot;", "'":"&#39;" }[c]));
  }

  function resolveImageSrc(path, staticBase) {
    path = (path || "").trim();
    if (!path) return "";
    if (/^(https?:)?\/\//i.test(path) || path.startsWith("data:") || path.startsWith("blob:")) return path;
    return (staticBase || "/static/") + path.replace(/^\/+/, "");
  }

  function measure(text, px, family, weight) {
    _mc.font = `${weight || 400} ${px}px ${family}`;
    return _mc.measureText(text).width;
  }

  function fitOneLine(text, maxW, family, maxPx, minPx, weight) {
    let px = maxPx;
    while (px > minPx && measure(text, px, family, weight) > maxW) px -= 1;
    return px;
  }

  function wrap(text, maxW, px, family, weight) {
    const out = [];
    for (const para of String(text).split("\n")) {
      if (!para.trim()) { out.push(""); continue; }
      let line = "";
      for (const word of para.split(/\s+/)) {
        const test = line ? line + " " + word : word;
        if (line && measure(test, px, family, weight) > maxW) { out.push(line); line = word; }
        else line = test;
      }
      if (line) out.push(line);
    }
    return out;
  }

  function fitText(text, maxW, maxH, family, maxPx, minPx, weight) {
    text = (text || "").trim();
    if (!text) return { px: maxPx, lh: maxPx * 1.18, lines: [] };
    for (let px = maxPx; px >= minPx; px -= 1) {
      const lines = wrap(text, maxW, px, family, weight);
      const lh = px * 1.18;
      if (lines.length * lh <= maxH) return { px, lh, lines };
    }
    const px = minPx, lh = px * 1.18;
    const lines = wrap(text, maxW, px, family, weight);
    return { px, lh, lines: lines.slice(0, Math.max(1, Math.floor(maxH / lh))) };
  }

  function star(cx, cy, r, fill) {
    let p = [];
    for (let i = 0; i < 10; i++) {
      const a = -Math.PI / 2 + (i * Math.PI) / 5;
      const rad = i % 2 ? r * 0.45 : r;
      p.push(`${(cx + Math.cos(a) * rad).toFixed(1)},${(cy + Math.sin(a) * rad).toFixed(1)}`);
    }
    return `<polygon points="${p.join(" ")}" fill="${fill}" stroke="#0008" stroke-width="0.5"/>`;
  }

  function frameKey(st) {
    if (st.isSpell) return "spell";
    if (st.isTrap) return "trap";
    if (st.summonType) return st.summonType.toLowerCase();
    return st.isEffect ? "effect" : "normal";
  }
  function attrLabel(st) {
    if (st.isSpell) return "SPELL";
    if (st.isTrap) return "TRAP";
    return st.attribute || "";
  }
  function monsterTypeLine(st) {
    const b = [];
    if (st.race) b.push(st.race);
    if (st.summonLabel) b.push(st.summonLabel);
    if (st.ability) b.push(st.ability);
    if (st.isPendulum) b.push("Pendulum");
    if (st.isTuner) b.push("Tuner");
    b.push(st.isEffect ? "Effect" : "Normal");
    return "[ " + b.join(" / ") + " ]";
  }
  function monsterBody(st) {
    const p = [];
    if (st.isExtra && st.materials) p.push(st.materials);
    if (st.monsterConditions) p.push(st.monsterConditions);
    if (st.monsterEffect) p.push(st.monsterEffect);
    return p.join("\n");
  }
  function effectBody(st) {
    return [st.effectConditions, st.effectText].filter(Boolean).join("\n");
  }
  function linkArrowsSVG(arrows, x, y, w, h) {
    const on = new Set(arrows);
    const cx = x + w / 2, cy = y + h / 2;
    const pos = { T:[cx,y], TR:[x+w,y], R:[x+w,cy], BR:[x+w,y+h], B:[cx,y+h], BL:[x,y+h], L:[x,cy], TL:[x,y] };
    const rot = { T:0, TR:45, R:90, BR:135, B:180, BL:225, L:270, TL:315 };
    let o = ['<g data-region="link-arrows">'];
    for (const k of ["T","TR","R","BR","B","BL","L","TL"]) {
      const [px, py] = pos[k], lit = on.has(k);
      o.push(`<g transform="translate(${px},${py}) rotate(${rot[k]})"><polygon points="0,-14 10,6 -10,6" fill="${lit?"#e3b341":"#ffffff14"}" stroke="${lit?"#fff3c4":"#ffffff33"}" stroke-width="1.2"/></g>`);
    }
    o.push("</g>");
    return o.join("");
  }

  function build(st, staticBase) {
    const fk = frameKey(st), frame = FRAME[fk] || FRAME.normal;
    const dark = fk === "xyz" || fk === "link";
    const nameFont = "Fraunces, Georgia, serif";
    const bodyFont = "Inter, system-ui, sans-serif";
    const labelFont = "Cinzel, Georgia, serif";
    const ink = dark ? "#F4ECD8" : "#1a1208";
    const p = [];

    p.push(`<svg viewBox="0 0 ${CARD_W} ${CARD_H}" xmlns="http://www.w3.org/2000/svg" class="cardpreview__svg" role="img" aria-label="Card preview">`);

    p.push(`<g data-region="frame"><rect x="6" y="6" width="${CARD_W-12}" height="${CARD_H-12}" rx="20" fill="${frame}" stroke="#000" stroke-width="3"/></g>`);

    const al = attrLabel(st);
    let attrW = 0;
    if (al) {
      attrW = 14 + al.length * 9.5;
      p.push(`<g data-region="attribute"><rect x="${CARD_W-M-attrW}" y="28" width="${attrW}" height="34" rx="17" fill="#0e0e12" stroke="#d8c089" stroke-width="1.5"/><text x="${CARD_W-M-attrW/2}" y="50" text-anchor="middle" font-family="${labelFont}" font-weight="700" font-size="14" letter-spacing="1" fill="#e3b341">${esc(al)}</text></g>`);
    }

    const nameTxt = st.name || "Card Name";
    const namePx = fitOneLine(nameTxt, CARD_W - M - attrW - 18, nameFont, 44, 18, "700");
    p.push(`<text data-region="name" x="${M}" y="56" font-family="${nameFont}" font-weight="700" font-size="${namePx}" fill="${ink}">${esc(nameTxt)}</text>`);

    if (st.isMonster && !st.isLink) {
      const n = Math.max(0, Math.min(13, st.level)), rank = st.isXyz, col = rank ? "#bcd2f0" : "#e3b341";
      p.push('<g data-region="level">');
      for (let i = 0; i < n; i++) {
        const x = rank ? (M + 14 + i * 30) : ((CARD_W - M - 14) - i * 30);
        p.push(star(x, 120, 13, col));
      }
      p.push("</g>");
    } else if (st.isLink) {
      p.push(`<text data-region="linkrating" x="${CARD_W-M}" y="126" text-anchor="end" font-family="${labelFont}" font-weight="700" font-size="22" fill="${ink}">LINK-${st.arrows.length}</text>`);
    }

    const ax = 70, aw = CARD_W - 140, ay = 140, ah = aw;
    p.push('<g data-region="art">');
    p.push(`<rect x="${ax}" y="${ay}" width="${aw}" height="${ah}" fill="#0d0d10" stroke="#000" stroke-width="2"/>`);
    const src = resolveImageSrc(st.artImage, staticBase);
    if (src) p.push(`<image href="${esc(src)}" x="${ax}" y="${ay}" width="${aw}" height="${ah}" preserveAspectRatio="xMidYMid slice"/>`);
    else p.push(`<text x="${ax+aw/2}" y="${ay+ah/2}" text-anchor="middle" dominant-baseline="middle" font-family="${nameFont}" font-size="22" fill="#54545e">Artwork</text>`);
    p.push("</g>");

    if (st.isLink) p.push(linkArrowsSVG(st.arrows, ax, ay, aw, ah));

    let textTop = ay + ah + 14;

    if (st.isMonster && st.isPendulum) {
      const ps = Number.isFinite(st.pendScale) ? String(st.pendScale) : "";
      p.push(`<g data-region="pendulum-scales" font-family="${labelFont}" font-weight="700" font-size="24" fill="#e3b341"><text x="${ax+16}" y="${ay+ah-14}" text-anchor="start">${esc(ps)}</text><text x="${ax+aw-16}" y="${ay+ah-14}" text-anchor="end">${esc(ps)}</text></g>`);
      const pY = textTop, pH = 86;
      p.push(`<rect data-region="pendulum-box" x="${M}" y="${pY}" width="${CARD_W-2*M}" height="${pH}" rx="4" fill="#ece6d6" opacity="0.9"/>`);
      const f = fitText(effectBody(st), CARD_W - 2*(M+10), pH - 12, bodyFont, 18, 8, "400");
      let yy = pY + 8 + f.px;
      p.push(`<g data-region="pendulum-text" font-family="${bodyFont}" font-size="${f.px}" fill="#15110a">`);
      for (const ln of f.lines) { p.push(`<text x="${M+10}" y="${yy.toFixed(1)}">${esc(ln)}</text>`); yy += f.lh; }
      p.push("</g>");
      textTop = pY + pH + 12;
    }

    const body = st.isMonster ? monsterBody(st) : effectBody(st);
    const boxBottom = st.isMonster ? 796 : 824;
    const boxTop = textTop;
    const innerX = M + 10;
    const innerW = CARD_W - 2 * (M + 10);
    p.push(`<rect data-region="textbox-bg" x="${M}" y="${boxTop}" width="${CARD_W-2*M}" height="${boxBottom-boxTop}" rx="4" fill="#ece6d6" opacity="0.92"/>`);

    let textTopInner = boxTop + 8;
    if (st.isMonster) {
      const headPx = 15;
      p.push(`<text data-region="typeline" x="${innerX}" y="${(textTopInner + headPx).toFixed(1)}" font-family="${labelFont}" font-weight="700" font-size="${headPx}" fill="#15110a">${esc(monsterTypeLine(st))}</text>`);
      textTopInner += headPx + 6;
    }

    const tf = fitText(body, innerW, boxBottom - textTopInner - 8, bodyFont, 22, 9, "400");
    let ty = textTopInner + tf.px;
    p.push(`<g data-region="effect-text" font-family="${bodyFont}" font-size="${tf.px}" fill="#15110a">`);
    for (const ln of tf.lines) { p.push(`<text x="${innerX}" y="${ty.toFixed(1)}">${esc(ln)}</text>`); ty += tf.lh; }
    p.push("</g>");

    if (st.isMonster) {
      const atk = st.atk !== "" ? st.atk : "?";
      const txt = st.isLink ? `ATK/${atk}` : `ATK/${atk}   DEF/${st.def !== "" ? st.def : "?"}`;
      p.push(`<text data-region="stats" x="${CARD_W-M}" y="828" text-anchor="end" font-family="${labelFont}" font-weight="700" font-size="22" fill="${ink}">${esc(txt)}</text>`);
    }

    p.push("</svg>");
    return p.join("");
  }

  window.CardSVG = { build, resolveImageSrc };
})();