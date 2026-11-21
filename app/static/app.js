/* Paprika Web — Client SPA */
(() => {
  "use strict";

  const state = {
    recipes: [],
    categories: [],
    totalRecipes: 0,
    uncategorizedCount: 0,
    selectedCategory: "",
    searchQuery: "",
    sort: localStorage.getItem("paprika_sort") || "name",
    currentRecipe: null,
    scale: 1,
    fontScale: parseFloat(localStorage.getItem("paprika_font_scale") || "1"),
    wakeLock: null,
    selectedFile: null,
    uploading: false,
  };

  const els = {
    brandCount: document.getElementById("totalCountBadge"),
    searchWrap: document.getElementById("searchWrap"),
    searchInput: document.getElementById("searchInput"),
    clearSearchBtn: document.getElementById("clearSearchBtn"),
    filterBar: document.getElementById("filterBar"),
    categoryPills: document.getElementById("categoryPills"),
    sortSelect: document.getElementById("sortSelect"),
    themeToggleBtn: document.getElementById("themeToggleBtn"),
    themeIcon: document.getElementById("themeIcon"),
    openImportBtn: document.getElementById("openImportBtn"),
    loadingView: document.getElementById("loadingView"),
    emptyView: document.getElementById("emptyView"),
    emptyDropzone: document.getElementById("emptyDropzone"),
    listView: document.getElementById("listView"),
    resultsMeta: document.getElementById("resultsMeta"),
    recipeGrid: document.getElementById("recipeGrid"),
    noMatches: document.getElementById("noMatches"),
    resetFiltersBtn: document.getElementById("resetFiltersBtn"),
    detailView: document.getElementById("detailView"),
    hiddenFileInput: document.getElementById("hiddenFileInput"),
    importModal: document.getElementById("importModal"),
    closeImportBtn: document.getElementById("closeImportBtn"),
    cancelImportBtn: document.getElementById("cancelImportBtn"),
    modalDropzone: document.getElementById("modalDropzone"),
    selectedFileLabel: document.getElementById("selectedFileLabel"),
    startImportBtn: document.getElementById("startImportBtn"),
    clearLibraryBtn: document.getElementById("clearLibraryBtn"),
    uploadProgress: document.getElementById("uploadProgress"),
    progressFill: document.getElementById("progressFill"),
    progressText: document.getElementById("progressText"),
    importStatus: document.getElementById("importStatus"),
    toast: document.getElementById("toast"),
  };

  const PLACEHOLDER_COLORS = [
    "linear-gradient(135deg, #C84B31, #8B2F1D)",
    "linear-gradient(135deg, #3B6E5C, #24473B)",
    "linear-gradient(135deg, #B57B2C, #7A4F16)",
    "linear-gradient(135deg, #525B88, #323859)",
    "linear-gradient(135deg, #8E4A62, #5C2B3D)",
    "linear-gradient(135deg, #4B7482, #2C4B57)",
  ];

  const UNICODE_FRACTIONS = {
    "¼": 0.25,
    "½": 0.5,
    "¾": 0.75,
    "⅓": 1 / 3,
    "⅔": 2 / 3,
    "⅛": 0.125,
    "⅜": 0.375,
    "⅝": 0.625,
    "⅞": 0.875,
  };

  function escapeHtml(str) {
    if (!str) return "";
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function safeUrl(url) {
    if (!url) return "";
    try {
      const parsed = new URL(url);
      if (parsed.protocol === "http:" || parsed.protocol === "https:") {
        return parsed.href;
      }
    } catch (_) {
      return "";
    }
    return "";
  }

  function hashColor(text) {
    let h = 0;
    for (let i = 0; i < text.length; i++) {
      h = (h * 31 + text.charCodeAt(i)) >>> 0;
    }
    return PLACEHOLDER_COLORS[h % PLACEHOLDER_COLORS.length];
  }

  function renderStars(rating) {
    const r = Math.max(0, Math.min(5, Number(rating) || 0));
    if (r === 0) return "";
    return `<span class="stars" aria-label="${r} out of 5 stars">${"★".repeat(r)}${"☆".repeat(5 - r)}</span>`;
  }

  let toastTimer = null;
  function showToast(msg) {
    els.toast.textContent = msg;
    els.toast.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => {
      els.toast.hidden = true;
    }, 3200);
  }

  /* Theme handling */
  function initTheme() {
    const saved = localStorage.getItem("paprika_theme");
    if (saved === "light" || saved === "dark") {
      document.documentElement.setAttribute("data-theme", saved);
    }
    updateThemeIcon();
  }

  function isDarkActive() {
    const attr = document.documentElement.getAttribute("data-theme");
    if (attr === "dark") return true;
    if (attr === "light") return false;
    return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
  }

  function updateThemeIcon() {
    els.themeIcon.innerHTML = isDarkActive() ? "&#9728;" : "&#9790;";
  }

  function toggleTheme() {
    const next = isDarkActive() ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", next);
    localStorage.setItem("paprika_theme", next);
    updateThemeIcon();
  }

  /* Font scale */
  function applyFontScale() {
    document.documentElement.style.setProperty("--recipe-font-scale", String(state.fontScale));
    localStorage.setItem("paprika_font_scale", String(state.fontScale));
  }

  /* Wake Lock for cooking */
  async function toggleWakeLock() {
    if (!("wakeLock" in navigator)) return;
    if (state.wakeLock) {
      try {
        await state.wakeLock.release();
      } catch (_) {}
      state.wakeLock = null;
      updateWakeLockButton();
      return;
    }
    try {
      state.wakeLock = await navigator.wakeLock.request("screen");
      state.wakeLock.addEventListener("release", () => {
        state.wakeLock = null;
        updateWakeLockButton();
      });
      updateWakeLockButton();
      showToast("Screen will stay awake while cooking");
    } catch (_) {
      showToast("Could not enable screen wake lock");
    }
  }

  function updateWakeLockButton() {
    const btn = document.getElementById("wakeLockBtn");
    if (!btn) return;
    btn.classList.toggle("active", Boolean(state.wakeLock));
    btn.textContent = state.wakeLock ? "Awake: On" : "Keep Awake";
  }

  /* API helpers */
  async function fetchJson(url, options) {
    const res = await fetch(url, options);
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      throw new Error(data.error || `Request failed (${res.status})`);
    }
    return data;
  }

  async function loadCategories() {
    const data = await fetchJson("/api/categories");
    state.totalRecipes = data.total || 0;
    state.uncategorizedCount = data.uncategorized || 0;
    state.categories = data.categories || [];
    els.brandCount.textContent = String(state.totalRecipes);
    els.brandCount.hidden = state.totalRecipes === 0;
    els.clearLibraryBtn.hidden = state.totalRecipes === 0;
    renderCategoryPills();
  }

  async function loadRecipes() {
    const params = new URLSearchParams();
    if (state.searchQuery.trim()) params.set("q", state.searchQuery.trim());
    if (state.selectedCategory) params.set("category", state.selectedCategory);
    if (state.sort) params.set("sort", state.sort);

    const data = await fetchJson(`/api/recipes?${params.toString()}`);
    state.recipes = data.recipes || [];
    renderRecipeList();
  }

  async function refreshAll() {
    try {
      await loadCategories();
      if (state.totalRecipes === 0) {
        showView("empty");
        return;
      }
      const route = getRoute();
      if (route.view === "recipe") {
        await openRecipeDetail(route.uid);
      } else {
        await loadRecipes();
        showView("list");
      }
    } catch (err) {
      showToast(err.message || "Failed to load recipes");
      els.loadingView.hidden = true;
    }
  }

  /* Routing */
  function getRoute() {
    const hash = window.location.hash || "#/";
    const match = hash.match(/^#\/recipe\/(.+)$/);
    if (match) {
      return { view: "recipe", uid: decodeURIComponent(match[1]) };
    }
    return { view: "list" };
  }

  function showView(view) {
    els.loadingView.hidden = view !== "loading";
    els.emptyView.hidden = view !== "empty";
    els.listView.hidden = view !== "list";
    els.detailView.hidden = view !== "detail";
    els.filterBar.hidden = view !== "list" || state.totalRecipes === 0;
    els.searchWrap.hidden = state.totalRecipes === 0;

    if (view !== "detail" && state.wakeLock) {
      state.wakeLock.release().catch(() => {});
      state.wakeLock = null;
    }
  }

  /* Render categories */
  function renderCategoryPills() {
    const pills = [
      { key: "", label: "All", count: state.totalRecipes },
      ...state.categories.map((c) => ({ key: c.name, label: c.name, count: c.count })),
    ];
    if (state.uncategorizedCount > 0 && state.categories.length > 0) {
      pills.push({ key: "__uncategorized__", label: "Uncategorized", count: state.uncategorizedCount });
    }

    els.categoryPills.innerHTML = pills
      .map((p) => {
        const active = state.selectedCategory === p.key ? " active" : "";
        return `<button type="button" class="pill${active}" data-category="${escapeHtml(p.key)}" role="tab" aria-selected="${state.selectedCategory === p.key}">
          <span>${escapeHtml(p.label)}</span>
          <span class="pill-count">${p.count}</span>
        </button>`;
      })
      .join("");
  }

  /* Render recipe grid */
  function renderRecipeList() {
    const count = state.recipes.length;
    const isFiltered = Boolean(state.searchQuery.trim() || state.selectedCategory);
    els.resultsMeta.textContent = isFiltered
      ? `Showing ${count} of ${state.totalRecipes} recipes`
      : `${count} ${count === 1 ? "recipe" : "recipes"}`;

    els.noMatches.hidden = count > 0;
    els.recipeGrid.hidden = count === 0;

    els.recipeGrid.innerHTML = state.recipes
      .map((r) => {
        const timeStr = r.total_time || r.cook_time || r.prep_time || "";
        const imgSrc = r.photo_url || safeUrl(r.image_url);
        const initial = (r.name || "R").trim().charAt(0).toUpperCase();
        const mediaHtml = imgSrc
          ? `<img src="${escapeHtml(imgSrc)}" alt="${escapeHtml(r.name)}" loading="lazy" decoding="async">`
          : `<div class="card-placeholder" style="background:${hashColor(r.name)}">${escapeHtml(initial)}</div>`;

        const metaParts = [];
        if (r.rating > 0) metaParts.push(renderStars(r.rating));
        if (timeStr) metaParts.push(`<span>${escapeHtml(timeStr)}</span>`);
        if (r.servings) metaParts.push(`<span>${escapeHtml(r.servings)}</span>`);

        const tagsHtml = (r.categories || [])
          .slice(0, 3)
          .map((cat) => `<span class="tag">${escapeHtml(cat)}</span>`)
          .join("");

        return `<a class="recipe-card" href="#/recipe/${encodeURIComponent(r.uid)}">
          <div class="card-media">${mediaHtml}</div>
          <div class="card-body">
            <h2 class="card-title">${escapeHtml(r.name)}</h2>
            ${metaParts.length ? `<div class="card-meta">${metaParts.join("")}</div>` : ""}
            ${tagsHtml ? `<div class="card-tags">${tagsHtml}</div>` : ""}
          </div>
        </a>`;
      })
      .join("");
  }

  /* Quantity scaling helpers */
  function parseQtyToken(token) {
    if (UNICODE_FRACTIONS[token]) return UNICODE_FRACTIONS[token];
    if (token.includes("/")) {
      const [n, d] = token.split("/").map(Number);
      if (Number.isFinite(n) && Number.isFinite(d) && d !== 0) return n / d;
    }
    const val = Number(token);
    return Number.isFinite(val) ? val : NaN;
  }

  function formatScaledNumber(num) {
    const whole = Math.floor(num + 1e-6);
    const frac = num - whole;
    const fractions = [
      [0, ""],
      [0.125, "⅛"],
      [0.25, "¼"],
      [1 / 3, "⅓"],
      [0.375, "⅜"],
      [0.5, "½"],
      [0.625, "⅝"],
      [2 / 3, "⅔"],
      [0.75, "¾"],
      [0.875, "⅞"],
      [1, "1"],
    ];
    for (const [val, sym] of fractions) {
      if (Math.abs(frac - val) < 0.04) {
        if (sym === "1") return String(whole + 1);
        if (whole === 0) return sym || "0";
        return sym ? `${whole} ${sym}` : String(whole);
      }
    }
    return Number(num.toFixed(2)).toString();
  }

  function scaleIngredientLine(line, factor) {
    if (factor === 1) return line;
    const match = line.match(
      /^(\s*)(\d+\s+\d+\/\d+|\d+\s*[¼½¾⅓⅔⅛⅜⅝⅞]|\d+\/\d+|\d+(?:\.\d+)?|[¼½¾⅓⅔⅛⅜⅝⅞])(\s*[-–]\s*(\d+\s+\d+\/\d+|\d+\/\d+|\d+(?:\.\d+)?|[¼½¾⅓⅔⅛⅜⅝⅞]))?/
    );
    if (!match) return line;

    const parseCompound = (str) => {
      const trimmed = str.trim();
      const unicodeMatch = trimmed.match(/^(\d+)\s*([¼½¾⅓⅔⅛⅜⅝⅞])$/);
      if (unicodeMatch) {
        return Number(unicodeMatch[1]) + UNICODE_FRACTIONS[unicodeMatch[2]];
      }
      const parts = trimmed.split(/\s+/);
      if (parts.length === 2) {
        return parseQtyToken(parts[0]) + parseQtyToken(parts[1]);
      }
      return parseQtyToken(trimmed);
    };

    const first = parseCompound(match[2]);
    if (!Number.isFinite(first)) return line;

    let replacement = match[1] + formatScaledNumber(first * factor);
    if (match[4]) {
      const second = parseCompound(match[4]);
      if (Number.isFinite(second)) {
        replacement += "–" + formatScaledNumber(second * factor);
      }
    }
    return replacement + line.slice(match[0].length);
  }

  function isSectionHeading(line) {
    const trimmed = line.trim();
    if (!trimmed) return false;
    if (trimmed.endsWith(":") && trimmed.length <= 64) return true;
    if (/^[A-Z0-9\s,&'/-]{4,48}$/.test(trimmed) && /[A-Z]/.test(trimmed)) return true;
    return false;
  }

  function getCheckedSet(uid) {
    try {
      const raw = sessionStorage.getItem(`paprika_checked_${uid}`);
      return new Set(raw ? JSON.parse(raw) : []);
    } catch (_) {
      return new Set();
    }
  }

  function saveCheckedSet(uid, set) {
    try {
      sessionStorage.setItem(`paprika_checked_${uid}`, JSON.stringify([...set]));
    } catch (_) {}
  }

  /* Recipe detail view */
  async function openRecipeDetail(uid) {
    showView("loading");
    try {
      const recipe = await fetchJson(`/api/recipes/${encodeURIComponent(uid)}`);
      state.currentRecipe = recipe;
      state.scale = 1;
      renderRecipeDetail(recipe);
      showView("detail");
      window.scrollTo({ top: 0, behavior: "instant" });
    } catch (err) {
      showToast(err.message || "Recipe not found");
      window.location.hash = "#/";
    }
  }

  function renderIngredientsHtml(recipe) {
    const lines = (recipe.ingredients || "")
      .split("\n")
      .map((l) => l.trim())
      .filter(Boolean);
    if (!lines.length) {
      return `<p class="extra-text" style="color:var(--text-muted)">No ingredients listed.</p>`;
    }

    const checkedSet = getCheckedSet(recipe.uid);
    let idx = 0;
    const items = lines
      .map((line) => {
        if (isSectionHeading(line)) {
          return `<li class="ingredient-heading">${escapeHtml(line.replace(/:$/, ""))}</li>`;
        }
        const itemIdx = idx++;
        const checked = checkedSet.has(itemIdx);
        const scaled = scaleIngredientLine(line, state.scale);
        return `<li class="ingredient-item${checked ? " checked" : ""}" data-ing-idx="${itemIdx}">
          <span class="ingredient-check" aria-hidden="true">${checked ? "&#10003;" : ""}</span>
          <span class="ingredient-text">${escapeHtml(scaled)}</span>
        </li>`;
      })
      .join("");

    return `<ul class="ingredient-list">${items}</ul>`;
  }

  function renderDirectionsHtml(recipe) {
    const raw = (recipe.directions || "").trim();
    if (!raw) {
      return `<p class="extra-text" style="color:var(--text-muted)">No directions listed.</p>`;
    }

    const blocks = raw
      .split(/\n+/)
      .map((b) => b.trim())
      .filter(Boolean);

    let stepNum = 0;
    const items = blocks
      .map((block) => {
        if (isSectionHeading(block)) {
          return `<li class="direction-heading">${escapeHtml(block.replace(/:$/, ""))}</li>`;
        }
        stepNum += 1;
        const cleaned = block.replace(/^\d+[\.\)]\s+/, "");
        return `<li class="direction-step" data-step="${stepNum}">
          <span class="step-num">${stepNum}</span>
          <span>${escapeHtml(cleaned)}</span>
        </li>`;
      })
      .join("");

    return `<ol class="direction-list">${items}</ol>`;
  }

  function renderRecipeDetail(recipe) {
    const imgSrc = recipe.photo_url || safeUrl(recipe.image_url);
    const sourceHref = safeUrl(recipe.source_url);
    const sourceLabel = recipe.source || (sourceHref ? new URL(sourceHref).hostname.replace(/^www\./, "") : "");

    const metaItems = [
      ["Prep", recipe.prep_time],
      ["Cook", recipe.cook_time],
      ["Total", recipe.total_time],
      ["Servings", recipe.servings],
      ["Difficulty", recipe.difficulty],
    ].filter(([, val]) => Boolean(val));

    const wakeLockSupported = "wakeLock" in navigator;

    els.detailView.innerHTML = `
      <div class="detail-nav">
        <a href="#/" class="btn btn-secondary">&larr; All Recipes</a>
        <div class="detail-tools">
          <button type="button" class="tool-chip" id="fontDecBtn" title="Smaller text" aria-label="Decrease text size">A&minus;</button>
          <button type="button" class="tool-chip" id="fontIncBtn" title="Larger text" aria-label="Increase text size">A+</button>
          ${wakeLockSupported ? `<button type="button" class="tool-chip" id="wakeLockBtn">Keep Awake</button>` : ""}
          <button type="button" class="tool-chip" id="printRecipeBtn">Print</button>
          <button type="button" class="tool-chip" id="deleteRecipeBtn" style="color:var(--danger)">Delete</button>
        </div>
      </div>

      <section class="detail-hero${imgSrc ? "" : " no-photo"}">
        <div class="detail-hero-text">
          ${
            recipe.categories && recipe.categories.length
              ? `<div class="detail-categories">${recipe.categories
                  .map((c) => `<span class="tag">${escapeHtml(c)}</span>`)
                  .join("")}</div>`
              : ""
          }
          <h1 class="detail-title">${escapeHtml(recipe.name)}</h1>
          ${recipe.rating > 0 ? `<div>${renderStars(recipe.rating)}</div>` : ""}
          ${recipe.description ? `<p class="detail-description">${escapeHtml(recipe.description)}</p>` : ""}
          ${
            sourceLabel
              ? `<div class="detail-source">Source: ${
                  sourceHref
                    ? `<a href="${escapeHtml(sourceHref)}" target="_blank" rel="noopener noreferrer">${escapeHtml(sourceLabel)}</a>`
                    : escapeHtml(sourceLabel)
                }</div>`
              : ""
          }
          ${
            metaItems.length
              ? `<div class="meta-grid">${metaItems
                  .map(
                    ([label, val]) => `<div class="meta-box">
                      <span class="meta-label">${escapeHtml(label)}</span>
                      <span class="meta-value">${escapeHtml(val)}</span>
                    </div>`
                  )
                  .join("")}</div>`
              : ""
          }
        </div>
        ${
          imgSrc
            ? `<div class="detail-hero-photo"><img src="${escapeHtml(imgSrc)}" alt="${escapeHtml(recipe.name)}"></div>`
            : ""
        }
      </section>

      <div class="detail-columns">
        <section class="detail-panel">
          <div class="panel-header">
            <h2 class="panel-title">Ingredients</h2>
            <div class="scale-group" role="group" aria-label="Scale servings">
              ${[0.5, 1, 2, 3]
                .map(
                  (f) => `<button type="button" class="scale-btn${state.scale === f ? " active" : ""}" data-scale="${f}">${
                    f === 0.5 ? "½×" : `${f}×`
                  }</button>`
                )
                .join("")}
            </div>
          </div>
          <div id="ingredientsContainer">${renderIngredientsHtml(recipe)}</div>
        </section>

        <section class="detail-panel">
          <div class="panel-header">
            <h2 class="panel-title">Directions</h2>
          </div>
          <div id="directionsContainer">${renderDirectionsHtml(recipe)}</div>
        </section>
      </div>

      ${
        recipe.notes || recipe.nutritional_info
          ? `<div class="extra-sections">
              ${
                recipe.notes
                  ? `<section class="detail-panel">
                      <div class="panel-header"><h2 class="panel-title">Notes</h2></div>
                      <p class="extra-text">${escapeHtml(recipe.notes)}</p>
                    </section>`
                  : ""
              }
              ${
                recipe.nutritional_info
                  ? `<section class="detail-panel">
                      <div class="panel-header"><h2 class="panel-title">Nutrition</h2></div>
                      <p class="extra-text">${escapeHtml(recipe.nutritional_info)}</p>
                    </section>`
                  : ""
              }
            </div>`
          : ""
      }
    `;

    bindDetailEvents(recipe);
  }

  function bindDetailEvents(recipe) {
    const ingContainer = document.getElementById("ingredientsContainer");
    ingContainer.addEventListener("click", (e) => {
      const item = e.target.closest(".ingredient-item");
      if (!item) return;
      const idx = Number(item.dataset.ingIdx);
      const checkedSet = getCheckedSet(recipe.uid);
      if (checkedSet.has(idx)) {
        checkedSet.delete(idx);
        item.classList.remove("checked");
        item.querySelector(".ingredient-check").innerHTML = "";
      } else {
        checkedSet.add(idx);
        item.classList.add("checked");
        item.querySelector(".ingredient-check").innerHTML = "&#10003;";
      }
      saveCheckedSet(recipe.uid, checkedSet);
    });

    const dirContainer = document.getElementById("directionsContainer");
    dirContainer.addEventListener("click", (e) => {
      const step = e.target.closest(".direction-step");
      if (!step) return;
      const wasActive = step.classList.contains("active-step");
      dirContainer.querySelectorAll(".direction-step.active-step").forEach((el) => {
        el.classList.remove("active-step");
      });
      if (!wasActive) {
        step.classList.add("active-step");
      }
    });

    els.detailView.querySelectorAll(".scale-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        state.scale = Number(btn.dataset.scale);
        els.detailView.querySelectorAll(".scale-btn").forEach((b) => {
          b.classList.toggle("active", b === btn);
        });
        ingContainer.innerHTML = renderIngredientsHtml(recipe);
      });
    });

    document.getElementById("fontDecBtn").addEventListener("click", () => {
      state.fontScale = Math.max(0.85, Number((state.fontScale - 0.1).toFixed(2)));
      applyFontScale();
    });

    document.getElementById("fontIncBtn").addEventListener("click", () => {
      state.fontScale = Math.min(1.5, Number((state.fontScale + 0.1).toFixed(2)));
      applyFontScale();
    });

    const wakeBtn = document.getElementById("wakeLockBtn");
    if (wakeBtn) {
      wakeBtn.addEventListener("click", toggleWakeLock);
      updateWakeLockButton();
    }

    document.getElementById("printRecipeBtn").addEventListener("click", () => {
      window.print();
    });

    document.getElementById("deleteRecipeBtn").addEventListener("click", async () => {
      if (!window.confirm(`Delete "${recipe.name}"?`)) return;
      try {
        await fetchJson(`/api/recipes/${encodeURIComponent(recipe.uid)}`, { method: "DELETE" });
        showToast("Recipe deleted");
        window.location.hash = "#/";
        await refreshAll();
      } catch (err) {
        showToast(err.message || "Failed to delete recipe");
      }
    });
  }

  /* Import modal & upload */
  function openImportModal(preselectedFile) {
    state.selectedFile = preselectedFile || null;
    els.importStatus.hidden = true;
    els.uploadProgress.hidden = true;
    els.progressFill.style.width = "0%";
    updateSelectedFileUI();
    els.importModal.hidden = false;
  }

  function closeImportModal() {
    if (state.uploading) return;
    els.importModal.hidden = true;
    state.selectedFile = null;
    els.hiddenFileInput.value = "";
  }

  function updateSelectedFileUI() {
    if (state.selectedFile) {
      const mb = (state.selectedFile.size / (1024 * 1024)).toFixed(2);
      els.selectedFileLabel.innerHTML = `Selected: <strong>${escapeHtml(state.selectedFile.name)}</strong> (${mb} MB)`;
      els.startImportBtn.disabled = false;
    } else {
      els.selectedFileLabel.innerHTML = `Drop <strong>.paprikarecipes</strong> or <strong>.paprikarecipe</strong>`;
      els.startImportBtn.disabled = true;
    }
  }

  function handleFilePicked(file) {
    if (!file) return;
    state.selectedFile = file;
    if (els.importModal.hidden) {
      openImportModal(file);
    } else {
      updateSelectedFileUI();
    }
  }

  function wireDropzone(zoneEl) {
    zoneEl.addEventListener("click", () => els.hiddenFileInput.click());
    zoneEl.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        els.hiddenFileInput.click();
      }
    });
    ["dragenter", "dragover"].forEach((evt) => {
      zoneEl.addEventListener(evt, (e) => {
        e.preventDefault();
        zoneEl.classList.add("dragover");
      });
    });
    ["dragleave", "drop"].forEach((evt) => {
      zoneEl.addEventListener(evt, (e) => {
        e.preventDefault();
        zoneEl.classList.remove("dragover");
      });
    });
    zoneEl.addEventListener("drop", (e) => {
      const file = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
      if (file) handleFilePicked(file);
    });
  }

  function startImport() {
    if (!state.selectedFile || state.uploading) return;
    const modeInput = document.querySelector('input[name="importMode"]:checked');
    const mode = modeInput ? modeInput.value : "merge";

    state.uploading = true;
    els.startImportBtn.disabled = true;
    els.cancelImportBtn.disabled = true;
    els.clearLibraryBtn.disabled = true;
    els.importStatus.hidden = true;
    els.uploadProgress.hidden = false;
    els.progressFill.style.width = "0%";
    els.progressText.textContent = "Uploading export…";

    const xhr = new XMLHttpRequest();
    xhr.open("POST", `/api/import?mode=${encodeURIComponent(mode)}`);
    xhr.setRequestHeader("Content-Type", "application/octet-stream");
    xhr.setRequestHeader("X-Filename", encodeURIComponent(state.selectedFile.name));

    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) {
        const pct = Math.round((e.loaded / e.total) * 100);
        els.progressFill.style.width = `${pct}%`;
        els.progressText.textContent = pct < 100 ? `Uploading… ${pct}%` : "Parsing & importing recipes…";
      }
    };

    xhr.onload = async () => {
      state.uploading = false;
      els.cancelImportBtn.disabled = false;
      els.clearLibraryBtn.disabled = false;

      let data = {};
      try {
        data = JSON.parse(xhr.responseText || "{}");
      } catch (_) {}

      if (xhr.status >= 200 && xhr.status < 300) {
        els.progressFill.style.width = "100%";
        els.progressText.textContent = "Done!";
        const summary = `Imported ${data.imported} recipes (${data.added} added, ${data.updated} updated).`;
        els.importStatus.className = "status-banner success";
        els.importStatus.textContent = summary;
        els.importStatus.hidden = false;
        showToast(summary);
        state.selectedCategory = "";
        state.searchQuery = "";
        els.searchInput.value = "";
        els.clearSearchBtn.hidden = true;
        window.location.hash = "#/";
        await refreshAll();
        setTimeout(() => {
          if (!state.uploading) closeImportModal();
        }, 900);
      } else {
        els.startImportBtn.disabled = false;
        els.uploadProgress.hidden = true;
        els.importStatus.className = "status-banner error";
        els.importStatus.textContent = data.error || `Upload failed (${xhr.status})`;
        els.importStatus.hidden = false;
      }
    };

    xhr.onerror = () => {
      state.uploading = false;
      els.startImportBtn.disabled = false;
      els.cancelImportBtn.disabled = false;
      els.clearLibraryBtn.disabled = false;
      els.uploadProgress.hidden = true;
      els.importStatus.className = "status-banner error";
      els.importStatus.textContent = "Network error while uploading file.";
      els.importStatus.hidden = false;
    };

    xhr.send(state.selectedFile);
  }

  /* Event listeners */
  function initEvents() {
    els.themeToggleBtn.addEventListener("click", toggleTheme);
    els.openImportBtn.addEventListener("click", () => openImportModal(null));
    els.closeImportBtn.addEventListener("click", closeImportModal);
    els.cancelImportBtn.addEventListener("click", closeImportModal);
    els.startImportBtn.addEventListener("click", startImport);

    els.importModal.addEventListener("click", (e) => {
      if (e.target === els.importModal) closeImportModal();
    });

    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && !els.importModal.hidden) {
        closeImportModal();
      }
    });

    els.hiddenFileInput.addEventListener("change", (e) => {
      const file = e.target.files && e.target.files[0];
      if (file) handleFilePicked(file);
    });

    wireDropzone(els.emptyDropzone);
    wireDropzone(els.modalDropzone);

    els.clearLibraryBtn.addEventListener("click", async () => {
      if (!window.confirm("Remove all recipes from Paprika Web?")) return;
      try {
        await fetchJson("/api/recipes", { method: "DELETE" });
        closeImportModal();
        showToast("Library cleared");
        window.location.hash = "#/";
        await refreshAll();
      } catch (err) {
        showToast(err.message || "Failed to clear library");
      }
    });

    let searchTimer = null;
    els.searchInput.addEventListener("input", () => {
      state.searchQuery = els.searchInput.value;
      els.clearSearchBtn.hidden = !state.searchQuery;
      clearTimeout(searchTimer);
      searchTimer = setTimeout(async () => {
        if (getRoute().view !== "list") {
          window.location.hash = "#/";
        }
        await loadRecipes();
        showView("list");
      }, 150);
    });

    els.clearSearchBtn.addEventListener("click", async () => {
      els.searchInput.value = "";
      state.searchQuery = "";
      els.clearSearchBtn.hidden = true;
      await loadRecipes();
      els.searchInput.focus();
    });

    els.categoryPills.addEventListener("click", async (e) => {
      const pill = e.target.closest(".pill");
      if (!pill) return;
      state.selectedCategory = pill.dataset.category || "";
      renderCategoryPills();
      await loadRecipes();
    });

    els.sortSelect.value = state.sort;
    els.sortSelect.addEventListener("change", async () => {
      state.sort = els.sortSelect.value;
      localStorage.setItem("paprika_sort", state.sort);
      await loadRecipes();
    });

    els.resetFiltersBtn.addEventListener("click", async () => {
      state.selectedCategory = "";
      state.searchQuery = "";
      els.searchInput.value = "";
      els.clearSearchBtn.hidden = true;
      renderCategoryPills();
      await loadRecipes();
    });

    window.addEventListener("hashchange", async () => {
      if (state.totalRecipes === 0) {
        showView("empty");
        return;
      }
      const route = getRoute();
      if (route.view === "recipe") {
        await openRecipeDetail(route.uid);
      } else {
        await loadRecipes();
        showView("list");
      }
    });
  }

  /* Boot */
  initTheme();
  applyFontScale();
  initEvents();
  refreshAll();
})();
