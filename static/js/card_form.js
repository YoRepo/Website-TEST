// path: static/js/card_form.js
// Card maker interactions:
//   • show only the sections/fields relevant to the chosen card type
//   • Level/Rank number <-> clickable stars stay in sync
//   • Link rating shows as "LINK-N"; Link arrows are a clickable pad
//   • live type-line preview + image preview
//   • controls inside hidden sections are disabled so they never submit
// The server still normalises everything, so the form also works without JS.

document.addEventListener("DOMContentLoaded", () => {
  const form = document.querySelector(".cardform");
  if (!form) return;

  const $ = (s) => form.querySelector(s);
  const category = $("#category");
  const pendulum = $("#is_pendulum");
  const summon = $("#summon_type");
  const spellSel = $("#spell_subtype");
  const trapSel = $("#trap_subtype");
  const levelInput = $("#level");
  const levelStars = $("#level-stars");
  const levelLabel = $("#level-label");
  const levelPrefix = $("#level-prefix");
  const artInput = $("#art_image");
  const renderInput = $("#render_image");
  const preview = document.getElementById("art-preview");
  const artFile = $("#art_image_file");
  const renderFile = $("#render_image_file");
  let artObjURL = "";
  let renderObjURL = "";

  function fileURL(input, prev) {
    if (prev) URL.revokeObjectURL(prev);
    const f = input && input.files && input.files[0];
    return f ? URL.createObjectURL(f) : "";
  }
  function refreshFileURLs() {
    artObjURL = fileURL(artFile, artObjURL);
    renderObjURL = fileURL(renderFile, renderObjURL);
  }
  if (artFile) artFile.addEventListener("change", refreshFileURLs);
  if (renderFile) renderFile.addEventListener("change", refreshFileURLs);
  const boxALabel = document.getElementById("boxA-label");
  const typeline = document.getElementById("typeline");
  const staticBase = form.dataset.static || "/static/";

  const sections = {
    monster: form.querySelector('[data-section="monster"]'),
    spell: form.querySelector('[data-section="spell"]'),
    trap: form.querySelector('[data-section="trap"]'),
    boxA: form.querySelector('[data-section="boxA"]'),
    boxB: form.querySelector('[data-section="boxB"]'),
  };
  const fields = {
    level: form.querySelector('[data-field="level"]'),
    pendScale: form.querySelector('[data-field="pendulum_scale"]'),
    def: form.querySelector('[data-field="def"]'),
    arrows: form.querySelector('[data-field="link_arrows"]'),
    materials: form.querySelector('[data-field="materials"]'),
  };

  const EXTRA = ["FUSION", "SYNCHRO", "XYZ", "LINK"];
  const show = (el, on) => { if (el) el.classList.toggle("cf-hidden", !on); };

  // --- Level/Rank stars --------------------------------------------------
  function paintStars() {
    const v = parseInt(levelInput.value, 10) || 0;
    levelStars.querySelectorAll(".star").forEach((s) => {
      s.classList.toggle("is-on", parseInt(s.dataset.value, 10) <= v);
    });
  }
  levelStars.querySelectorAll(".star").forEach((s) => {
    s.addEventListener("click", () => {
      const v = parseInt(s.dataset.value, 10);
      // click the current top star again to step down, else set to it
      levelInput.value = (parseInt(levelInput.value, 10) || 0) === v ? v - 1 : v;
      update();
    });
  });

  // --- Link arrows -------------------------------------------------------
  function paintArrows() {
    form.querySelectorAll(".arrow").forEach((a) => {
      const cb = a.querySelector("input");
      a.classList.toggle("is-on", cb.checked);
    });
  }

  // --- Image preview -----------------------------------------------------
  function paintPreview() {
    const src = artObjURL || window.CardSVG.resolveImageSrc(artInput.value, staticBase);
    if (src) {
      preview.innerHTML = "";
      const img = new Image();
      img.alt = "preview";
      img.onerror = () => { preview.innerHTML = "<span>Not found</span>"; };
      img.src = src;
      preview.appendChild(img);
    } else {
      preview.innerHTML = "<span>No image</span>";
    }
  }

  // --- Type-line preview -------------------------------------------------
  function optText(sel) {
    return sel && sel.selectedIndex >= 0 ? sel.options[sel.selectedIndex].text : "";
  }
  function renderTypeline() {
    const cat = category.value;
    if (cat !== "MONSTER") {
      const sub = cat === "SPELL" ? optText(spellSel) : optText(trapSel);
      const st = sub && sub !== "—" ? sub : "Normal";
      typeline.textContent = `${st} ${cat === "SPELL" ? "Spell" : "Trap"}`;
      return;
    }
    const s = summon.value;
    const attr = $("#attribute").value || "—";
    const race = $("#race").selectedIndex > 0 ? optText($("#race")) : "—";
    const arrowCount = form.querySelectorAll('input[name="link_arrows"]:checked').length;
    const n = s === "LINK" ? arrowCount : (levelInput.value || "?");
    const lbl = s === "LINK" ? "LINK" : (s === "XYZ" ? "Rank" : "Level");
    const tags = [];
    if (s) tags.push(optText(summon));
    if (pendulum.checked) tags.push("Pendulum");
    if ($("#is_tuner").checked) tags.push("Tuner");
    tags.push($("#is_effect").checked ? "Effect" : "Normal");
    const atk = $("#atk").value || "?";
    const stats = s === "LINK"
      ? `ATK ${atk}`
      : `ATK ${atk} / DEF ${$("#def_").value || "?"}`;
    const lvl = s === "LINK" ? `LINK-${n}` : `${lbl} ${n}`;
    typeline.textContent = `[${attr}] ${lvl} · ${race} / ${tags.join(" / ")} · ${stats}`;
  }

  // =====================================================================
  //  LIVE SVG PREVIEW
  //  Builds the card as an inline SVG string from the current form state
  //  and re-renders on every input. Each <g data-region="..."> is one
  //  swappable piece — replace any block with your own template art later.
  // =====================================================================
  const previewHost = document.getElementById("card-preview");

  // --- read the whole form into a normalised object ---
  function readState() {
    const cat = category.value, s = summon.value;
    const opt = (sel) => (sel && sel.selectedIndex > 0 ? sel.options[sel.selectedIndex].text : "");
    return {
      name: $("#name").value.trim(),
      isMonster: cat === "MONSTER", isSpell: cat === "SPELL", isTrap: cat === "TRAP",
      summonType: s, summonLabel: opt(summon),
      isLink: s === "LINK", isXyz: s === "XYZ", isExtra: EXTRA.includes(s),
      isEffect: $("#is_effect").checked, isPendulum: pendulum.checked, isTuner: $("#is_tuner").checked,
      attribute: $("#attribute").value,
      race: opt($("#race")), ability: opt($("#ability")),
      level: parseInt(levelInput.value, 10) || 0,
      pendScale: parseInt($("#pendulum_scale").value, 10),
      atk: $("#atk").value.trim(), def: $("#def_").value.trim(),
      arrows: Array.from(form.querySelectorAll('input[name="link_arrows"]:checked')).map((c) => c.value),
      artImage: artObjURL || artInput.value,
      effectConditions: $("#effect_conditions").value.trim(),
      effectText: $("#effect_text").value.trim(),
      materials: $("#materials").value.trim(),
      monsterConditions: $("#monster_conditions").value.trim(),
      monsterEffect: $("#monster_effect").value.trim(),
    };
  }

  // If a finalized render image is set, show that. Otherwise fall back to the
  // live SVG built from the form (useful while you're still designing).
  function renderPreview() {
    if (!previewHost) return;
    const finalSrc = renderObjURL || window.CardSVG.resolveImageSrc(renderInput ? renderInput.value : "", staticBase);
    if (finalSrc) {
      previewHost.innerHTML = '<img class="cardpreview__svg" alt="Card render preview">';
      const im = previewHost.querySelector("img");
      // If the render path is broken, drop back to the SVG so you're never
      // left staring at a broken-image icon.
      im.onerror = () => { renderSVGPreview(); };
      im.src = finalSrc;
      return;
    }
    renderSVGPreview();
  }

  function renderSVGPreview() {
    previewHost.innerHTML = window.CardSVG.build(readState(), staticBase);
    const im = previewHost.querySelector("image");
    if (im) im.addEventListener("error", () => { im.style.display = "none"; }, { once: true });
  }

  // Re-render once web fonts load so measured widths are accurate.
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(renderPreview);

  // --- Master update -----------------------------------------------------
  function update() {
    const cat = category.value;
    const isMonster = cat === "MONSTER";
    const isPend = pendulum.checked;
    const s = summon.value;
    const isLink = s === "LINK";
    const isXyz = s === "XYZ";
    const isExtra = EXTRA.includes(s);

    show(sections.monster, isMonster);
    show(sections.spell, cat === "SPELL");
    show(sections.trap, cat === "TRAP");
    show(sections.boxB, isMonster);
    show(sections.boxA, !isMonster || (isMonster && isPend));

    // Links have no Level/Rank — the rating equals the arrow count, so hide
    // the whole widget for them rather than collecting a meaningless number.
    show(fields.level, isMonster && !isLink);
    if (!isLink) {
      levelPrefix.hidden = true;
      show(levelStars, true);
      levelLabel.textContent = isXyz ? "Rank" : "Level";
      levelStars.classList.toggle("stars--rank", isXyz);
    }

    show(fields.pendScale, isMonster && isPend);
    show(fields.def, isMonster && !isLink);
    show(fields.arrows, isMonster && isLink);
    show(fields.materials, isMonster && isExtra);

    boxALabel.textContent = isMonster
      ? "Pendulum effect"
      : (cat === "SPELL" ? "Spell effect" : "Trap effect");

    // Disable controls inside hidden sections so they never submit
    form.querySelectorAll("input, select, textarea").forEach((el) => {
      el.disabled = !!el.closest(".cf-hidden");
    });

    paintStars();
    paintArrows();
    paintPreview();
    renderTypeline();
    renderPreview();
  }

  form.addEventListener("input", update);
  form.addEventListener("change", update);
  update();
});