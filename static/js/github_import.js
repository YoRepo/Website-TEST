// path: static/js/github_import.js
// "Import .lua from GitHub" widget for the card editor.
//
// A modal browser that lists a user's repositories, walks a repo's folders,
// and drops a chosen .lua file straight into the #script textarea. Every import
// remembers its GitHub *location* (repo + folder) on the user's account, shown
// as quick chips under the script box so the same place is one click away next
// time. All GitHub traffic goes through this site's /github/* proxy — the
// browser never calls GitHub directly.

document.addEventListener("DOMContentLoaded", () => {
  const script = document.getElementById("script");
  const modal = document.getElementById("gh-modal");
  const openBtn = document.getElementById("gh-open");
  if (!script || !modal || !openBtn) return; // only on the card form

  const form = script.closest("form");
  const csrf = form ? (form.querySelector('input[name="csrf_token"]') || {}).value : "";

  const $ = (id) => document.getElementById(id);
  const ownerInput = $("gh-owner");
  const repoInput = $("gh-repo");
  const refInput = $("gh-ref");
  const goBtn = $("gh-go");
  const crumbs = $("gh-crumbs");
  const list = $("gh-list");
  const preview = $("gh-preview");
  const previewName = $("gh-preview-name");
  const previewCode = $("gh-preview-code");
  const importBtn = $("gh-import-btn");
  const statusEl = $("gh-status");
  const recent = $("gh-recent");

  // Current browse location + the .lua file currently previewed (if any).
  const state = { owner: "", repo: "", ref: "", path: "", file: null };

  // --- small helpers -----------------------------------------------------
  const setStatus = (msg, kind) => {
    statusEl.textContent = msg || "";
    statusEl.dataset.kind = kind || "";
  };
  const dirname = (p) => (p.indexOf("/") >= 0 ? p.slice(0, p.lastIndexOf("/")) : "");

  async function api(url, opts) {
    const res = await fetch(url, opts);
    let data = {};
    try { data = await res.json(); } catch { /* non-JSON error */ }
    if (!res.ok) throw new Error(data.error || `Request failed (${res.status}).`);
    return data;
  }
  const qs = (params) =>
    Object.entries(params)
      .filter(([, v]) => v !== "" && v != null)
      .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(v)}`)
      .join("&");

  // --- modal open/close --------------------------------------------------
  let lastFocus = null;
  function openModal() {
    lastFocus = document.activeElement;
    modal.hidden = false;
    document.body.classList.add("is-modal-open");
    ownerInput.focus();
  }
  function closeModal() {
    modal.hidden = true;
    document.body.classList.remove("is-modal-open");
    if (lastFocus && lastFocus.focus) lastFocus.focus();
  }
  openBtn.addEventListener("click", () => {
    openModal();
    if (!ownerInput.value && !list.dataset.loaded) setStatus("");
  });
  modal.querySelectorAll("[data-gh-close]").forEach((el) =>
    el.addEventListener("click", closeModal));
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !modal.hidden) closeModal();
  });

  // --- list rendering ----------------------------------------------------
  function clearList() { list.innerHTML = ""; list.dataset.loaded = "1"; }

  function rowButton(cls, label, sub, onClick, disabled) {
    const li = document.createElement("li");
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = `ghpick__row ${cls}`;
    if (disabled) btn.disabled = true;
    const name = document.createElement("span");
    name.className = "ghpick__row-name";
    name.textContent = label;
    btn.appendChild(name);
    if (sub) {
      const s = document.createElement("span");
      s.className = "ghpick__row-sub";
      s.textContent = sub;
      btn.appendChild(s);
    }
    if (onClick && !disabled) btn.addEventListener("click", onClick);
    li.appendChild(btn);
    return li;
  }

  function hidePreview() { preview.hidden = true; state.file = null; }

  // --- breadcrumbs -------------------------------------------------------
  function renderCrumbs() {
    crumbs.innerHTML = "";
    if (!state.repo) { crumbs.hidden = true; return; }
    crumbs.hidden = false;
    const add = (label, onClick, current) => {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "ghpick__crumb" + (current ? " is-current" : "");
      b.textContent = label;
      if (onClick && !current) b.addEventListener("click", onClick);
      crumbs.appendChild(b);
    };
    add(`${state.owner}/${state.repo}`, () => loadContents(""), state.path === "");
    if (state.path) {
      const parts = state.path.split("/");
      let acc = "";
      parts.forEach((part, i) => {
        const sep = document.createElement("span");
        sep.className = "ghpick__crumb-sep";
        sep.textContent = "/";
        crumbs.appendChild(sep);
        acc = acc ? `${acc}/${part}` : part;
        const here = acc;
        add(part, () => loadContents(here), i === parts.length - 1);
      });
    }
  }

  // --- load: repositories for an owner -----------------------------------
  async function loadRepos(owner) {
    state.owner = owner; state.repo = ""; state.path = "";
    hidePreview(); renderCrumbs();
    setStatus("Loading repositories…", "busy");
    clearList();
    try {
      const { repos } = await api(`/github/repos?${qs({ owner })}`);
      clearList();
      if (!repos.length) { setStatus(`No public repositories found for “${owner}”.`); return; }
      setStatus(`${repos.length} repositor${repos.length === 1 ? "y" : "ies"} · pick one to browse.`);
      repos.forEach((r) => {
        list.appendChild(rowButton("ghpick__row--repo", r.name,
          r.description || (r.private ? "private" : ""), () => {
            repoInput.value = r.name;
            refInput.value = r.default_branch || "";
            state.repo = r.name; state.ref = r.default_branch || "";
            loadContents("");
          }));
      });
    } catch (err) { setStatus(err.message, "error"); }
  }

  // --- load: a directory listing -----------------------------------------
  async function loadContents(path) {
    hidePreview();
    state.path = path || "";
    renderCrumbs();
    setStatus("Loading…", "busy");
    clearList();
    try {
      // Resolve the default branch if the user typed a repo without a branch.
      if (!state.ref) {
        try {
          const { repo } = await api(`/github/repo?${qs({ owner: state.owner, repo: state.repo })}`);
          state.ref = repo.default_branch || "";
          if (state.ref && !refInput.value) refInput.value = state.ref;
        } catch { /* fall back to GitHub's default-branch resolution */ }
      }
      const { entries } = await api(`/github/contents?${qs({
        owner: state.owner, repo: state.repo, ref: state.ref, path: state.path })}`);
      clearList();
      renderCrumbs();
      const luaCount = entries.filter((e) => e.is_lua).length;
      if (!entries.length) setStatus("This folder is empty.");
      else setStatus(luaCount
        ? `${luaCount} .lua file${luaCount === 1 ? "" : "s"} here · click one to preview.`
        : "No .lua files in this folder — open a subfolder.");
      entries.forEach((e) => {
        if (e.type === "dir") {
          list.appendChild(rowButton("ghpick__row--dir", e.name, "folder",
            () => loadContents(e.path)));
        } else if (e.is_lua) {
          list.appendChild(rowButton("ghpick__row--lua", e.name, ".lua",
            () => previewFile(e.path, e.name)));
        } else {
          list.appendChild(rowButton("ghpick__row--other", e.name, "", null, true));
        }
      });
    } catch (err) { setStatus(err.message, "error"); }
  }

  // --- preview a .lua file -----------------------------------------------
  async function previewFile(path, name) {
    setStatus("Fetching file…", "busy");
    try {
      const data = await api(`/github/file?${qs({
        owner: state.owner, repo: state.repo, ref: state.ref, path })}`);
      state.file = { path: data.path, name: data.name, content: data.content };
      previewName.textContent = data.name;
      previewCode.textContent = data.content;
      preview.hidden = false;
      preview.scrollIntoView({ block: "nearest" });
      setStatus(`Previewing ${data.name} (${data.content.split("\n").length} lines).`);
    } catch (err) { setStatus(err.message, "error"); }
  }

  // --- import the previewed file into the script textarea ----------------
  importBtn.addEventListener("click", async () => {
    if (!state.file) return;
    if (script.value.trim() &&
        !window.confirm("Replace the current script with the imported file?")) return;
    script.value = state.file.content;
    // Programmatic edits don't fire "input"; dispatch one so string-reference
    // highlighting and the live preview stay in sync.
    script.dispatchEvent(new Event("input", { bubbles: true }));
    await rememberLocation(dirname(state.file.path));
    closeModal();
    script.scrollIntoView({ block: "center", behavior: "smooth" });
  });

  // --- remembered locations (user memory) --------------------------------
  async function rememberLocation(path) {
    if (!csrf) return;
    const body = { owner: state.owner, repo: state.repo, ref: state.ref, path,
      label: `${state.owner}/${state.repo}${path ? " · " + path : ""}` };
    try {
      const { sources } = await api("/github/sources", {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-CSRFToken": csrf },
        body: JSON.stringify(body),
      });
      renderRecent(sources);
    } catch { /* remembering is best-effort; never block the import */ }
  }

  async function forgetLocation(s) {
    try {
      const { sources } = await api("/github/sources/delete", {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-CSRFToken": csrf },
        body: JSON.stringify(s),
      });
      renderRecent(sources);
    } catch { /* ignore */ }
  }

  function renderRecent(sources) {
    recent.innerHTML = "";
    (sources || []).forEach((s) => {
      const chip = document.createElement("span");
      chip.className = "ghchip";
      const go = document.createElement("button");
      go.type = "button";
      go.className = "ghchip__go";
      go.textContent = s.label || `${s.owner}/${s.repo}`;
      go.title = `Browse ${s.owner}/${s.repo}${s.path ? "/" + s.path : ""}` +
        (s.ref ? ` @ ${s.ref}` : "");
      go.addEventListener("click", () => {
        ownerInput.value = s.owner; repoInput.value = s.repo; refInput.value = s.ref || "";
        state.owner = s.owner; state.repo = s.repo; state.ref = s.ref || "";
        openModal();
        loadContents(s.path || "");
      });
      const del = document.createElement("button");
      del.type = "button";
      del.className = "ghchip__del";
      del.setAttribute("aria-label", "Forget this location");
      del.textContent = "×";
      del.addEventListener("click", () => forgetLocation(s));
      chip.appendChild(go);
      chip.appendChild(del);
      recent.appendChild(chip);
    });
  }

  // --- the "Browse" button: decide repos-list vs file-tree ---------------
  function go() {
    const owner = ownerInput.value.trim();
    const repo = repoInput.value.trim();
    state.ref = refInput.value.trim();
    if (!owner) { setStatus("Enter a GitHub username or organization.", "error"); ownerInput.focus(); return; }
    state.owner = owner;
    if (repo) { state.repo = repo; loadContents(""); }
    else loadRepos(owner);
  }
  goBtn.addEventListener("click", go);
  [ownerInput, repoInput, refInput].forEach((inp) =>
    inp.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); go(); } }));

  // --- initial load of remembered chips ----------------------------------
  if (csrf) {
    api("/github/sources").then((d) => renderRecent(d.sources)).catch(() => {});
  }
});
