const state = {
  config: null,
  entries: [],
  annotations: {},
  annotators: {},
  currentIndex: 0,
  useProxy: false,
  isSaving: false,
  autoProxyActive: false,
  pendingFrameEntryId: null,
  frameWatchdog: null,
  panelHeight: 360,
  resizing: false,
  resizeStartY: 0,
  resizeStartHeight: 360,
  resizerInitialized: false,
  annotatorName: "",
  annotatorColumn: null,
  resumeApplied: false,
  autoSaveEnabled: true,
  autoSaveInterval: 6,
  autoSaveTimer: null,
  hasUnsavedChanges: false,
  entryProxyPrefs: {},
  viewerWindow: null,
  pywebviewDetected: typeof window !== "undefined" && typeof window.pywebview !== "undefined",
  pywebviewReady: false,
  pendingViewerPayload: null,
  fullPanelMode: false,
  lastSearchQuery: "",
};

const dom = {};
const STORAGE_KEYS = {
  annotator: "pageAnnotatorName",
};

function getAppOrigin() {
  if (window.location.origin) {
    return window.location.origin;
  }
  return `${window.location.protocol}//${window.location.host}`;
}

function makeAbsoluteUrl(path) {
  if (!path) return "";
  if (/^https?:/i.test(path)) {
    return path;
  }
  if (path.startsWith("/")) {
    return `${getAppOrigin()}${path}`;
  }
  return `${getAppOrigin()}/${path}`;
}

function isLikelyPdfUrl(url) {
  if (!url) return false;
  const normalized = url.split("?")[0].toLowerCase();
  return normalized.endsWith(".pdf");
}

function isPyWebViewEnvironment() {
  if (state.pywebviewDetected) return true;
  if (typeof window !== "undefined" && typeof window.pywebview !== "undefined") {
    state.pywebviewDetected = true;
    return true;
  }
  return false;
}

function isPyWebViewBridgeReady() {
  return (
    state.pywebviewReady &&
    window.pywebview &&
    window.pywebview.api &&
    typeof window.pywebview.api.show_entry === "function"
  );
}

function shouldUsePyWebViewBridge() {
  return Boolean(state.config?.viewer?.detached_window) && isPyWebViewEnvironment();
}

function queuePyWebViewPayload(payload) {
  state.pendingViewerPayload = payload;
  flushPendingPyWebViewPayload();
}

function flushPendingPyWebViewPayload() {
  if (!state.pendingViewerPayload) return;
  if (!isPyWebViewBridgeReady()) return;
  const payload = state.pendingViewerPayload;
  state.pendingViewerPayload = null;
  window.pywebview.api
    .show_entry(payload)
    .catch((err) => {
      console.debug("pywebview bridge failed", err);
      state.pendingViewerPayload = payload;
    });
}

function maybeEnableFullPanelMode() {
  if (state.fullPanelMode) return;
  if (!state.config?.viewer?.detached_window) return;
  if (!isPyWebViewEnvironment()) return;
  state.fullPanelMode = true;
  document.body?.classList.add("pywebview-mode");
  dom.resizer?.classList.add("hidden");
  applyPanelHeight(window.innerHeight || state.panelHeight);
  configureViewerControls();
}

document.addEventListener("DOMContentLoaded", () => {
  cacheDom();
  attachEvents();
  initializePyWebViewBridge();
  bootstrap();
});

function cacheDom() {
  dom.frame = document.getElementById("page-frame");
  dom.infoFields = document.getElementById("info-fields");
  dom.form = document.getElementById("annotation-form");
  dom.counter = document.getElementById("entry-counter");
  dom.status = document.getElementById("status-message");
  dom.proxyIndicator = document.getElementById("proxy-indicator");
  dom.entryAnnotator = document.getElementById("entry-annotator");
  dom.annotatorDisplay = document.getElementById("annotator-display");
  dom.prevBtn = document.getElementById("prev-entry");
  dom.nextBtn = document.getElementById("next-entry");
  dom.openOriginal = document.getElementById("open-original");
  dom.toggleProxy = document.getElementById("toggle-proxy");
  dom.saveBtn = document.getElementById("save-entry");
  dom.resizer = document.getElementById("panel-resizer");
  dom.changeAnnotator = document.getElementById("change-annotator");
  dom.annotatorModal = document.getElementById("annotator-modal");
  dom.annotatorForm = document.getElementById("annotator-form");
  dom.annotatorInput = document.getElementById("annotator-input");
  dom.detachedPlaceholder = document.getElementById("detached-placeholder");
  dom.reopenDetached = document.getElementById("reopen-detached");
  dom.viewerControls = document.getElementById("viewer-controls");
  dom.viewerBack = document.getElementById("viewer-back");
  dom.viewerForward = document.getElementById("viewer-forward");
}

function attachEvents() {
  dom.nextBtn.addEventListener("click", () => navigate(1));
  dom.prevBtn.addEventListener("click", () => navigate(-1));
  dom.openOriginal.addEventListener("click", () => openOriginal());
  dom.toggleProxy.addEventListener("click", () => toggleProxy());
  dom.saveBtn.addEventListener("click", () => saveCurrent());
  dom.frame.addEventListener("load", handleFrameLoad);
  dom.frame.addEventListener("error", () => handleFrameFailure(getFrameEntryId(), "error"));
  if (dom.form) {
    dom.form.addEventListener("input", handleFormInput);
    dom.form.addEventListener("change", handleFormInput);
  }
  if (dom.annotatorForm) {
    dom.annotatorForm.addEventListener("submit", handleAnnotatorSubmit);
  }
  if (dom.changeAnnotator) {
    dom.changeAnnotator.addEventListener("click", () => showAnnotatorModal(true));
  }
  if (dom.reopenDetached) {
    dom.reopenDetached.addEventListener("click", reopenDetachedViewer);
  }
  if (dom.viewerBack) {
    dom.viewerBack.addEventListener("click", viewerBack);
  }
  if (dom.viewerForward) {
    dom.viewerForward.addEventListener("click", viewerForward);
  }
  document.addEventListener("click", handleViewerLinkClicks);
  setupKeyboardShortcuts();
  window.addEventListener("beforeunload", () => {
    if (state.viewerWindow && !state.viewerWindow.closed) {
      state.viewerWindow.close();
    }
  });
  window.addEventListener("resize", () => {
    if (state.fullPanelMode) {
      applyPanelHeight(window.innerHeight || state.panelHeight);
    }
  });
}

function initializePyWebViewBridge() {
  const handleReady = () => {
    if (state.pywebviewReady) return;
    state.pywebviewReady = true;
    state.pywebviewDetected = true;
    maybeEnableFullPanelMode();
    configureViewerControls();
    flushPendingPyWebViewPayload();
  };
  window.addEventListener("pywebviewready", handleReady);
  document.addEventListener("pywebviewready", handleReady);
}

async function bootstrap() {
  try {
    const response = await fetch("/api/state");
    if (!response.ok) {
      throw new Error(await response.text());
    }
    const payload = await response.json();
    state.config = payload.config;
    state.entries = payload.entries || [];
    state.annotations = payload.annotations || {};
    state.annotators = payload.annotators || {};
    state.useProxy = Boolean(state.config.viewer?.prefer_proxy);
    state.annotatorColumn = state.config.annotatorColumn || null;
    maybeEnableFullPanelMode();
    configurePanel();
    configureProxyControls();
    configureAutoSave();
    configureAnnotatorControls();
    configureViewerContainer();
    configureViewerControls();
    if (!state.entries.length) {
      dom.counter.textContent = "No entries";
      setStatus("The dataset is empty.");
      disableNavigation(true);
      return;
    }
    buildFormSkeleton();
    loadEntry(0);
    initializeAnnotatorFlow();
  } catch (err) {
    console.error(err);
    setStatus(`Unable to load initial data: ${err}`);
    disableNavigation(true);
  }
}

function configurePanel() {
  const panel = state.config.panel || {};
  if (state.fullPanelMode) {
    dom.resizer?.classList.add("hidden");
    applyPanelHeight(window.innerHeight || state.panelHeight);
    return;
  }
  const initialHeight = Number(panel.initial_height) || state.panelHeight;
  state.panelHeight = initialHeight;
  state.resizeStartHeight = initialHeight;
  applyPanelHeight(initialHeight);
  if (panel.resizable && dom.resizer) {
    dom.resizer.classList.remove("hidden");
    dom.resizer.setAttribute("tabindex", "0");
    if (!state.resizerInitialized) {
      initializeResizerEvents();
      state.resizerInitialized = true;
    }
  } else if (dom.resizer) {
    dom.resizer.classList.add("hidden");
  }
}

function configureProxyControls() {
  const allowToggle = state.config.viewer?.allow_proxy_toggle !== false;
  if (dom.toggleProxy) {
    dom.toggleProxy.classList.toggle("hidden", !allowToggle);
  }
  const allowOriginal = state.config.viewer?.open_original_in_new_tab !== false;
  if (dom.openOriginal) {
    dom.openOriginal.classList.toggle("hidden", !allowOriginal);
  }
}

function configureAutoSave() {
  const autosave = state.config.autosave || {};
  state.autoSaveEnabled = autosave.enabled !== false;
  const interval = Number(autosave.interval_seconds || autosave.intervalSeconds || 0);
  state.autoSaveInterval = !Number.isNaN(interval) && interval >= 2 ? interval : 6;
}

function configureAnnotatorControls() {
  const enabled = Boolean(state.config.annotatorColumn);
  if (!enabled) {
    dom.changeAnnotator?.classList.add("hidden");
    dom.annotatorDisplay?.classList.add("hidden");
  }
}

function configureViewerControls() {
  const enabled = state.fullPanelMode && shouldUsePyWebViewBridge();
  dom.viewerControls?.classList.toggle("hidden", !enabled);
}

function configureViewerContainer() {
  const detached = state.config.viewer?.detached_window;
  if (!detached) {
    dom.detachedPlaceholder?.classList.add("hidden");
    dom.frame?.classList.remove("hidden");
    return;
  }
  dom.detachedPlaceholder?.classList.remove("hidden");
  dom.frame?.classList.add("hidden");
}

function applyPanelHeight(height) {
  const sourceHeight = typeof height === "number" && !Number.isNaN(height) ? height : state.panelHeight;
  const normalized = Math.max(150, Math.round(state.fullPanelMode ? window.innerHeight || sourceHeight : sourceHeight));
  document.documentElement.style.setProperty("--panel-height", `${normalized}px`);
  state.panelHeight = normalized;
}

function initializeResizerEvents() {
  if (!dom.resizer) return;
  dom.resizer.addEventListener("mousedown", startResize);
  dom.resizer.addEventListener("touchstart", startResize, { passive: false });
  window.addEventListener("mousemove", handlePointerMove);
  window.addEventListener("mouseup", stopResize);
  window.addEventListener("touchmove", handlePointerMove, { passive: false });
  window.addEventListener("touchend", stopResize);
}

function startResize(evt) {
  if (state.config.panel?.resizable !== true) {
    return;
  }
  const clientY = getPointerY(evt);
  if (clientY == null) return;
  evt.preventDefault();
  state.resizing = true;
  state.resizeStartY = clientY;
  state.resizeStartHeight = state.panelHeight;
  document.body.classList.add("resizing");
}

function handlePointerMove(evt) {
  if (!state.resizing) return;
  const clientY = getPointerY(evt);
  if (clientY == null) return;
  evt.preventDefault();
  updatePanelHeightFromPointer(clientY);
}

function stopResize() {
  if (!state.resizing) return;
  state.resizing = false;
  document.body.classList.remove("resizing");
}

function updatePanelHeightFromPointer(clientY) {
  const bounds = getPanelBounds();
  const delta = state.resizeStartY - clientY;
  let nextHeight = state.resizeStartHeight + delta;
  nextHeight = Math.max(bounds.min, Math.min(bounds.max, nextHeight));
  applyPanelHeight(nextHeight);
}

function getPanelBounds() {
  const panel = state.config.panel || {};
  const min = Number(panel.min_height) || 200;
  let max = Number(panel.max_height);
  const viewport = window.innerHeight;
  if (!max || Number.isNaN(max)) {
    max = Math.max(min + 100, Math.round(viewport * 0.9));
  }
  const cappedMax = Math.min(max, viewport - 80);
  return { min, max: Math.max(min + 10, cappedMax) };
}

function getPointerY(evt) {
  if (typeof evt.clientY === "number") {
    return evt.clientY;
  }
  if (evt.touches && evt.touches.length) {
    return evt.touches[0].clientY;
  }
  if (evt.changedTouches && evt.changedTouches.length) {
    return evt.changedTouches[0].clientY;
  }
  return null;
}

function buildFormSkeleton() {
  dom.form.innerHTML = "";
  state.config.annotationFields.forEach((field) => {
    const wrapper = document.createElement("div");
    wrapper.className = "form-field";

    const label = document.createElement("label");
    label.setAttribute("for", field.name);
    label.textContent = field.label + (field.required ? " *" : "");
    wrapper.appendChild(label);

    let input;
    switch (field.type) {
      case "textarea":
      case "list":
        input = document.createElement("textarea");
        break;
      case "select":
      case "multiselect":
        input = document.createElement("select");
        if (field.type === "multiselect") {
          input.multiple = true;
          input.size = Math.min(6, (field.options || []).length || 4);
        }
        (field.options || []).forEach((option) => {
          const opt = document.createElement("option");
          opt.value = option;
          opt.textContent = option;
          input.appendChild(opt);
        });
        break;
      case "number":
        input = document.createElement("input");
        input.type = "number";
        break;
      case "checkbox":
        input = document.createElement("input");
        input.type = "checkbox";
        break;
      default:
        input = document.createElement("input");
        input.type = "text";
    }
    input.id = field.name;
    input.name = field.name;
    if (field.placeholder && field.type !== "checkbox") {
      input.placeholder = field.placeholder;
    }
    if (field.required) {
      input.required = true;
    }
    wrapper.appendChild(input);

    if (field.help) {
      const help = document.createElement("small");
      help.textContent = field.help;
      wrapper.appendChild(help);
    } else if (field.type === "list") {
      const help = document.createElement("small");
      help.textContent = `Separate items with '${getSeparator(field)}'`;
      wrapper.appendChild(help);
    }

    dom.form.appendChild(wrapper);
  });
}

function initializeAnnotatorFlow() {
  if (!state.config.annotatorColumn) {
    return;
  }
  const stored = safeStorageGet(STORAGE_KEYS.annotator) || "";
  if (stored) {
    setAnnotatorName(stored);
    state.resumeApplied = true;
    jumpToResumePosition();
  } else {
    showAnnotatorModal();
  }
}

function showAnnotatorModal(focusExisting = false) {
  if (!dom.annotatorModal) return;
  dom.annotatorModal.classList.remove("hidden");
  if (dom.annotatorInput) {
    dom.annotatorInput.value = focusExisting && state.annotatorName ? state.annotatorName : "";
    setTimeout(() => dom.annotatorInput?.focus(), 50);
  }
}

function hideAnnotatorModal() {
  if (dom.annotatorModal) {
    dom.annotatorModal.classList.add("hidden");
  }
}

function handleAnnotatorSubmit(evt) {
  evt.preventDefault();
  if (!dom.annotatorInput) return;
  const value = dom.annotatorInput.value.trim();
  if (!value) {
    dom.annotatorInput.focus();
    return;
  }
  setAnnotatorName(value);
  safeStorageSet(STORAGE_KEYS.annotator, value);
  hideAnnotatorModal();
  state.resumeApplied = true;
  jumpToResumePosition();
}

function setAnnotatorName(name) {
  state.annotatorName = name;
  updateAnnotatorDisplay();
}

function updateAnnotatorDisplay() {
  if (!dom.annotatorDisplay) return;
  if (!state.annotatorName) {
    dom.annotatorDisplay.classList.add("hidden");
    dom.annotatorDisplay.textContent = "";
  } else {
    dom.annotatorDisplay.classList.remove("hidden");
    dom.annotatorDisplay.textContent = `Annotator: ${state.annotatorName}`;
  }
}

function jumpToResumePosition() {
  if (!state.entries.length) return;
  const idx = computeResumeIndex();
  if (Number.isInteger(idx) && idx >= 0 && idx < state.entries.length) {
    if (idx !== state.currentIndex) {
      loadEntry(idx);
    }
  }
}

function computeResumeIndex() {
  const name = state.annotatorName;
  if (!name) return 0;
  let lastIndex = -1;
  state.entries.forEach((entry, idx) => {
    const annotator = state.annotators[String(entry.id)];
    if (annotator && annotator.toLowerCase() === name.toLowerCase()) {
      lastIndex = idx;
    }
  });
  if (lastIndex >= 0 && lastIndex < state.entries.length - 1) {
    return lastIndex + 1;
  }
  const firstUnclaimed = state.entries.findIndex((entry) => !state.annotators[String(entry.id)]);
  if (firstUnclaimed >= 0) {
    return firstUnclaimed;
  }
  return 0;
}

function loadEntry(index) {
  if (!state.entries.length) return;
  cancelAutoSave();
  state.currentIndex = Math.max(0, Math.min(index, state.entries.length - 1));
  const entry = state.entries[state.currentIndex];
  dom.counter.textContent = `Entry ${state.currentIndex + 1} / ${state.entries.length}`;
  disableNavigation(false);
  if (state.currentIndex === 0) dom.prevBtn.disabled = true;
  if (state.currentIndex === state.entries.length - 1) dom.nextBtn.disabled = true;
  renderInfo(entry);
  loadAnnotationValues(entry.id);
  state.autoProxyActive = false;
  state.hasUnsavedChanges = false;
  state.useProxy = getEntryProxyPreference(entry.id);
  updateFrameSource(entry);
  updateEntryAnnotatorBadge(entry.id);
  setStatus("");
}

function renderInfo(entry) {
  dom.infoFields.innerHTML = "";
  const row = entry.data || {};
  state.config.displayFields.forEach((field) => {
    const wrapper = document.createElement("div");
    wrapper.className = "info-field";

    const label = document.createElement("label");
    label.textContent = field.label;
    wrapper.appendChild(label);

    const valueEl = document.createElement("div");
    valueEl.className = "value";

    const rawValue = row[field.column] ?? "";
    switch (field.type) {
      case "list": {
        renderTextList(valueEl, rawValue, field);
        break;
      }
      case "link_list": {
        renderLinkList(valueEl, rawValue, field);
        break;
      }
      case "scroll_list": {
        renderScrollableList(valueEl, rawValue, field);
        break;
      }
      default: {
        valueEl.textContent = rawValue || "—";
        if (field.type === "textarea") {
          valueEl.classList.add("multiline");
        }
      }
    }
    wrapper.appendChild(valueEl);
    dom.infoFields.appendChild(wrapper);
  });
}

function renderTextList(container, rawValue, field) {
  const items = splitList(rawValue, getSeparator(field));
  if (!items.length) {
    container.textContent = "—";
    return;
  }
  const ul = document.createElement("ul");
  items.forEach((item) => {
    const li = document.createElement("li");
    li.textContent = item;
    ul.appendChild(li);
  });
  container.appendChild(ul);
}

function renderLinkList(container, rawValue, field) {
  const items = splitList(rawValue, getSeparator(field));
  if (!items.length) {
    container.textContent = "—";
    return;
  }
  const ul = document.createElement("ul");
  ul.className = "link-list";
  items.forEach((url) => {
    const trimmed = url.trim();
    if (!trimmed) return;
    const li = document.createElement("li");
    const anchor = document.createElement("a");
    anchor.href = trimmed;
    anchor.textContent = trimmed;
    anchor.rel = "noopener noreferrer";
    if (state.fullPanelMode && shouldUsePyWebViewBridge()) {
      anchor.dataset.viewerLink = "true";
      anchor.target = "_self";
      if (isLikelyPdfUrl(trimmed)) {
        anchor.dataset.pdfLink = "true";
      }
    } else {
      anchor.target = "_blank";
    }
    li.appendChild(anchor);
    ul.appendChild(li);
  });
  container.appendChild(ul);
}

function renderScrollableList(container, rawValue, field) {
  const items = splitList(rawValue, getSeparator(field));
  if (!items.length) {
    container.textContent = "—";
    return;
  }
  const strip = document.createElement("div");
  strip.className = "scroll-strip";
  items.forEach((value) => {
    if (!value) return;
    const pill = document.createElement("span");
    pill.className = "pill";
    pill.textContent = value.trim();
    strip.appendChild(pill);
  });
  container.appendChild(strip);
}

function updateFrameSource(entry) {
  if (!entry) return;
  if (state.config.viewer?.detached_window) {
    openDetachedWindow(entry);
    setProxyIndicator();
    return;
  }
  dom.frame.dataset.entryId = entry.id;
  dom.frame.src = state.useProxy ? `/api/proxy/${entry.id}` : entry.url;
  if (dom.toggleProxy) {
    dom.toggleProxy.textContent = state.useProxy ? "Show live page" : "Use proxy";
  }
  const autoProxyEnabled = state.config.viewer?.auto_proxy_on_block !== false;
  if (!state.useProxy && autoProxyEnabled) {
    startFrameWatchdog(entry.id);
    probeEmbeddingHeaders(entry.id);
  } else {
    clearFrameWatchdog();
  }
  setProxyIndicator();
}

function loadAnnotationValues(entryId) {
  const saved = state.annotations[String(entryId)] || {};
  state.config.annotationFields.forEach((field) => {
    const element = dom.form.elements[field.name];
    if (!element) return;
    const defaultValue = saved[field.name] ?? field.default ?? (field.type === "checkbox" ? "false" : "");
    switch (field.type) {
      case "checkbox":
        element.checked = defaultValue === true || String(defaultValue).toLowerCase() === "true";
        break;
      case "multiselect":
        const values = splitList(defaultValue, getSeparator(field));
        Array.from(element.options).forEach((option) => {
          option.selected = values.includes(option.value);
        });
        break;
      case "list":
        const listValues = Array.isArray(defaultValue)
          ? defaultValue
          : splitList(defaultValue, getSeparator(field));
        element.value = listValues.join(getSeparator(field));
        break;
      default:
        element.value = defaultValue ?? "";
    }
  });
}

function disableNavigation(flag) {
  dom.prevBtn.disabled = flag;
  dom.nextBtn.disabled = flag;
}

function openOriginal() {
  if (state.config.viewer?.open_original_in_new_tab === false) {
    return;
  }
  const entry = state.entries[state.currentIndex];
  if (entry && entry.url) {
    window.open(entry.url, "_blank");
  }
}

function viewerBack() {
  if (!shouldUsePyWebViewBridge() || !isPyWebViewBridgeReady()) {
    return;
  }
  const api = window.pywebview?.api;
  if (!api || typeof api.browser_back !== "function") return;
  try {
    const result = api.browser_back();
    if (result && typeof result.catch === "function") {
      result.catch((err) => console.debug("pywebview back failed", err));
    }
  } catch (err) {
    console.debug("pywebview back failed", err);
  }
}

function viewerForward() {
  if (!shouldUsePyWebViewBridge() || !isPyWebViewBridgeReady()) {
    return;
  }
  const api = window.pywebview?.api;
  if (!api || typeof api.browser_forward !== "function") return;
  try {
    const result = api.browser_forward();
    if (result && typeof result.catch === "function") {
      result.catch((err) => console.debug("pywebview forward failed", err));
    }
  } catch (err) {
    console.debug("pywebview forward failed", err);
  }
}

function toggleProxy() {
  if (state.config.viewer?.allow_proxy_toggle === false) {
    return;
  }
  state.useProxy = !state.useProxy;
  if (!state.useProxy) {
    state.autoProxyActive = false;
  }
  const entry = state.entries[state.currentIndex];
  if (entry) {
    setEntryProxyPreference(entry.id, state.useProxy);
    updateFrameSource(entry);
  }
}

async function navigate(delta) {
  const target = state.currentIndex + delta;
  if (target < 0 || target >= state.entries.length) {
    return;
  }
  if (state.hasUnsavedChanges) {
    await saveCurrent({ silent: true, reason: "navigate" });
  }
  loadEntry(target);
}

async function saveCurrent(options = {}) {
  const reason = options.reason || "manual";
  if (state.config.annotatorColumn && !state.annotatorName) {
    setStatus("Enter your name before saving.", 2500);
    showAnnotatorModal(true);
    return;
  }
  if (state.isSaving) return;
  const entry = state.entries[state.currentIndex];
  if (!entry) return;
  const values = collectFormValues();
  state.isSaving = true;
  dom.saveBtn.disabled = true;
  cancelAutoSave();
  if (!options.silent) {
    setStatus(reason === "autosave" ? "Auto-saving..." : "Saving...");
  }
  try {
    const response = await fetch(`/api/annotation/${entry.id}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ values, annotator: state.annotatorName }),
    });
    if (!response.ok) {
      throw new Error(await response.text());
    }
    const payload = await response.json();
    state.annotations[String(entry.id)] = payload.values || values;
    if (payload.annotator !== undefined) {
      state.annotators[String(entry.id)] = payload.annotator;
    } else {
      state.annotators[String(entry.id)] = state.annotatorName;
    }
    updateEntryAnnotatorBadge(entry.id);
    state.hasUnsavedChanges = false;
    const successLabel = reason === "autosave" ? "Auto-saved" : "Saved";
    const duration = reason === "autosave" ? 1500 : 2200;
    setStatus(successLabel, duration);
  } catch (err) {
    console.error(err);
    setStatus(`Save failed: ${err}`);
  } finally {
    state.isSaving = false;
    dom.saveBtn.disabled = false;
    state.autoSaveTimer = null;
  }
}

function collectFormValues() {
  const values = {};
  state.config.annotationFields.forEach((field) => {
    const element = dom.form.elements[field.name];
    if (!element) return;
    switch (field.type) {
      case "checkbox":
        values[field.name] = element.checked ? "true" : "false";
        break;
      case "multiselect":
        values[field.name] = Array.from(element.selectedOptions).map((option) => option.value);
        break;
      case "list":
        values[field.name] = splitList(element.value, getSeparator(field));
        break;
      default:
        values[field.name] = element.value;
    }
  });
  return values;
}

function handleFormInput() {
  state.hasUnsavedChanges = true;
  scheduleAutoSave();
}

function scheduleAutoSave() {
  if (!state.autoSaveEnabled || !state.annotatorName) {
    return;
  }
  if (state.autoSaveTimer) {
    clearTimeout(state.autoSaveTimer);
  }
  state.autoSaveTimer = window.setTimeout(() => {
    saveCurrent({ silent: true, reason: "autosave" });
  }, state.autoSaveInterval * 1000);
}

function cancelAutoSave() {
  if (state.autoSaveTimer) {
    clearTimeout(state.autoSaveTimer);
    state.autoSaveTimer = null;
  }
}

function splitList(value, separator = ";") {
  if (!value) return [];
  if (Array.isArray(value)) return value;
  return String(value)
    .split(separator)
    .map((item) => item.trim())
    .filter(Boolean);
}

function getSeparator(field) {
  return field.separator || state.config.defaultListSeparator || ";";
}

function handleFrameLoad() {
  const entryId = getFrameEntryId();
  if (entryId === state.pendingFrameEntryId) {
    clearFrameWatchdog();
  }
  if (!state.useProxy) {
    state.autoProxyActive = false;
  }
  setProxyIndicator();
}

function handleFrameFailure(entryId, reason) {
  if (entryId !== state.entries[state.currentIndex]?.id) {
    return;
  }
  if (state.useProxy) {
    setStatus(`Proxy failed to load (${reason}). Try opening the original link.`);
    return;
  }
  const autoProxyEnabled = state.config.viewer?.auto_proxy_on_block !== false;
  if (!autoProxyEnabled) {
    setStatus("The page refused iframe embedding. Enable the proxy or open the original link.");
    return;
  }
  clearFrameWatchdog();
  state.autoProxyActive = true;
  state.useProxy = true;
  const entry = state.entries[state.currentIndex];
  if (entry) {
    setEntryProxyPreference(entry.id, true);
    setStatus("Live page blocked. Using proxied HTML.", 4000);
    updateFrameSource(entry);
  }
}

function startFrameWatchdog(entryId) {
  clearFrameWatchdog();
  state.pendingFrameEntryId = entryId;
  state.frameWatchdog = window.setTimeout(() => {
    handleFrameFailure(entryId, "timeout");
  }, 4500);
}

function clearFrameWatchdog() {
  if (state.frameWatchdog) {
    window.clearTimeout(state.frameWatchdog);
    state.frameWatchdog = null;
  }
  state.pendingFrameEntryId = null;
}

function getFrameEntryId() {
  if (!dom.frame) return -1;
  return Number(dom.frame.dataset.entryId || "-1");
}

function setProxyIndicator() {
  if (!dom.proxyIndicator) return;
  if (!state.useProxy) {
    dom.proxyIndicator.classList.add("hidden");
    dom.proxyIndicator.textContent = "";
    return;
  }
  dom.proxyIndicator.classList.remove("hidden");
  dom.proxyIndicator.textContent = state.autoProxyActive ? "Proxy mode (blocked)" : "Proxy mode";
}

function getEntryProxyPreference(entryId) {
  const key = String(entryId);
  if (Object.prototype.hasOwnProperty.call(state.entryProxyPrefs, key)) {
    return Boolean(state.entryProxyPrefs[key]);
  }
  return Boolean(state.config.viewer?.prefer_proxy);
}

function setEntryProxyPreference(entryId, value) {
  state.entryProxyPrefs[String(entryId)] = Boolean(value);
}

function updateEntryAnnotatorBadge(entryId) {
  if (!dom.entryAnnotator) return;
  const owner = state.annotators[String(entryId)];
  if (!owner) {
    dom.entryAnnotator.classList.add("hidden");
    dom.entryAnnotator.textContent = "";
    return;
  }
  dom.entryAnnotator.classList.remove("hidden");
  dom.entryAnnotator.textContent = `Annotated by ${owner}`;
  if (state.annotatorName && owner && owner.toLowerCase() !== state.annotatorName.toLowerCase()) {
    setStatus(`This entry was annotated by ${owner}. Saving will update the owner.`, 5000);
  }
}

function openDetachedWindow(entry) {
  const target = state.useProxy ? `/api/proxy/${entry.id}` : entry.url;
  if (!target) return;
  const windowName = "annotator-detached-viewer";
  if (shouldUsePyWebViewBridge()) {
    const absoluteTarget = state.useProxy ? makeAbsoluteUrl(`/api/proxy/${entry.id}`) : entry.url;
    const payload = {
      id: entry.id,
      url: absoluteTarget,
      proxyUrl: makeAbsoluteUrl(`/api/proxy/${entry.id}`),
      originalUrl: entry.url,
      useProxy: state.useProxy,
      title: entry.data?.title || entry.url || `Entry ${entry.id}`,
    };
    queuePyWebViewPayload(payload);
    return;
  }
  try {
    if (!state.viewerWindow || state.viewerWindow.closed) {
      state.viewerWindow = window.open(target, windowName);
    } else {
      state.viewerWindow.location.href = target;
      state.viewerWindow.focus();
    }
  } catch (err) {
    state.viewerWindow = window.open(target, windowName);
  }
}

function reopenDetachedViewer() {
  const entry = state.entries[state.currentIndex];
  if (entry) {
    openDetachedWindow(entry);
  }
}

function handleViewerLinkClicks(evt) {
  if (!state.fullPanelMode || !shouldUsePyWebViewBridge()) {
    return;
  }
  const anchor = evt.target.closest("a[data-viewer-link='true']");
  if (!anchor) return;
  const url = anchor.href || anchor.dataset.url;
  if (!url) return;
  evt.preventDefault();
  const label = anchor.dataset.title || anchor.textContent?.trim() || url;
  openLinkInViewer(url, label);
}

function openLinkInViewer(url, title) {
  if (!url) return;
  if (!shouldUsePyWebViewBridge()) {
    window.open(url, "_blank");
    return;
  }
  if (isLikelyPdfUrl(url)) {
    openPdfExternally(url);
    return;
  }
  queuePyWebViewPayload({
    id: `link-${Date.now()}`,
    url,
    proxyUrl: url,
    originalUrl: url,
    useProxy: false,
    title: title || url,
  });
}

function openPdfExternally(url) {
  if (!url) return;
  if (!isPyWebViewBridgeReady()) {
    window.open(url, "_blank");
    return;
  }
  const api = window.pywebview?.api;
  if (!api || typeof api.open_external !== "function") {
    window.open(url, "_blank");
    return;
  }
  try {
    const result = api.open_external(url);
    if (result && typeof result.catch === "function") {
      result.catch((err) => {
        console.debug("open_external failed", err);
        window.open(url, "_blank");
      });
    }
  } catch (err) {
    console.debug("open_external failed", err);
    window.open(url, "_blank");
  }
}

function setupKeyboardShortcuts() {
  document.addEventListener("keydown", (evt) => {
    if (!shouldUsePyWebViewBridge()) return;
    const modifier = evt.metaKey || evt.ctrlKey;
    if (!modifier) return;
    const key = (evt.key || "").toLowerCase();
    if (key === "f") {
      evt.preventDefault();
      requestViewerSearch();
    } else if (key === "g") {
      if (!state.lastSearchQuery) return;
      evt.preventDefault();
      repeatViewerSearch(!evt.shiftKey);
    }
  });
}

function requestViewerSearch() {
  const initial = state.lastSearchQuery || "";
  const term = window.prompt("Search within the page:", initial);
  if (!term) return;
  state.lastSearchQuery = term;
  sendViewerSearch(term, true);
}

function repeatViewerSearch(forward = true) {
  if (!state.lastSearchQuery) return;
  sendViewerSearch(state.lastSearchQuery, forward);
}

function sendViewerSearch(query, forward = true) {
  if (!query || !isPyWebViewBridgeReady()) return;
  const api = window.pywebview?.api;
  if (!api || typeof api.search_page !== "function") return;
  try {
    const result = api.search_page(query, forward);
    if (result && typeof result.catch === "function") {
      result.catch((err) => console.debug("search_page failed", err));
    }
  } catch (err) {
    console.debug("search_page failed", err);
  }
}

async function probeEmbeddingHeaders(entryId) {
  if (state.config.viewer?.auto_proxy_on_block === false) return;
  const currentEntry = state.entries[state.currentIndex];
  if (!currentEntry || entryId !== currentEntry.id) return;
  try {
    const response = await fetch(`/api/frame-check/${entryId}`);
    if (!response.ok) {
      return;
    }
    const payload = await response.json();
    if (entryId !== state.entries[state.currentIndex]?.id) return;
    if (!state.useProxy && payload.blocked) {
      handleFrameFailure(entryId, payload.reason || "blocked");
    }
  } catch (err) {
    console.debug("Frame header probe failed", err);
  }
}

let statusTimeout;
function setStatus(message, timeout) {
  dom.status.textContent = message || "";
  if (statusTimeout) {
    clearTimeout(statusTimeout);
  }
  if (timeout) {
    statusTimeout = setTimeout(() => {
      dom.status.textContent = "";
    }, timeout);
  }
}

function safeStorageGet(key) {
  try {
    return window.localStorage.getItem(key);
  } catch (err) {
    console.debug("localStorage get failed", err);
    return null;
  }
}

function safeStorageSet(key, value) {
  try {
    window.localStorage.setItem(key, value);
  } catch (err) {
    console.debug("localStorage set failed", err);
  }
}
