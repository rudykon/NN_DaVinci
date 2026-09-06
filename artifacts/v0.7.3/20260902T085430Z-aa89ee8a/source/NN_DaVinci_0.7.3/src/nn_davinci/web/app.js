const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const clone = (value) => JSON.parse(JSON.stringify(value));
const TRIAL_RUNTIME_STORAGE = "nndv-active-trial-state";
const SCENE_TEMPLATE_FAMILIES = Object.freeze([
  "cnn",
  "resnet",
  "unet",
  "transformer",
  "moe",
  "multimodal-fusion",
  "diffusion-unet",
]);
const toolbarMenuState = {
  menu: null,
  trigger: null,
  returnFocus: null,
};
const sceneUiState = {
  gizmoMode: "move",
  gizmoAxis: "x",
  gizmoSpace: "world",
  treeQuery: "",
  treeFilter: "all",
  startFilter: "all",
};
const surfaceState = {
  drawer: null,
  drawerReturnFocus: null,
  dialog: null,
  dialogReturnFocus: null,
  compactWorkspace: null,
};
const suppressedDialogFocus = new WeakSet();
const controlBusyCounts = new WeakMap();
const autoFramedScenes = new WeakSet();
let composerInitialization = null;
let textEntryRequest = null;
let sourceGeneration = 0;
let graphRenderSequence = 0;
let sceneRenderer = null;
let sceneInteractions = null;
let sceneRenderSequence = 0;
let commandRegistry = null;
let sceneBatchController = null;
const uiPreferences = window.NNDVState.applyPreferences(
  window.NNDVState.readPreferences(),
);
const workspaceMachine = new window.NNDVState.WorkspaceStateMachine();

const state = {
  graph: null,
  graphId: null,
  viewGraph: null,
  layout: null,
  capabilities: null,
  theme: "neurips",
  page: "auto",
  algorithm: "auto",
  direction: "LR",
  collapsed: new Set(),
  focus: new Set(),
  selection: new Set(),
  history: [],
  future: [],
  analysis: null,
  zoom: 1,
  viewBox: null,
  busy: false,
  busyMessages: [],
  metric: "",
  animate: false,
  perspective: false,
  comments: [],
  projectMeta: {},
  themeOverrides: {},
  layoutOptions: { rank_gap: 88, node_gap: 34 },
  semanticLevel: null,
  semanticView: "faithful",
  semanticData: null,
  breadcrumbs: [],
  sourceSelection: new Set(),
  viewMemory: {},
  lazy: false,
  lazySummary: null,
  pendingImport: null,
  tasks: [],
  paperSuggestions: [],
  fixedLayout: false,
  composer: null,
  composerProof: null,
  workspaceMode: "graph",
  figure: null,
  figureProof: null,
  figureSelection: new Set(),
  figureActivePage: null,
  figureActiveLayer: null,
  figureIncludeGuides: false,
  figureCatalog: [],
  figureLensResult: null,
  figureLastInteractionMs: null,
  figureNeedsRebuild: false,
  scene: null,
  sceneSelection: new Set(),
  sceneNeedsRebuild: false,
  sceneFallbackReason: null,
  autosaveBlockedByInvalidProject: false,
  pendingAutosaveConflict: null,
  issues: [],
  initialized: false,
  inspectorHintShown: false,
  workflowMetrics: null,
  trial: {
    enabled: false,
    activeSessionId: null,
    startedAt: null,
    firstViewRecorded: false,
    paperReadyRecorded: false,
    participantImportPending: false,
    participantImportStarted: false,
    edits: {
      semantic_changes: 0,
      node_changes: 0,
      edge_changes: 0,
      label_changes: 0,
    },
  },
};

const paletteItems = [
  ["Input", "Input", "input"],
  ["Conv", "Conv2D", "convolution"],
  ["Norm", "BatchNorm", "normalization"],
  ["ReLU", "ReLU", "activation"],
  ["Pool", "MaxPool", "pooling"],
  ["Residual", "ResidualBlock", "convolution"],
  ["Attention", "MultiHeadAttention", "attention"],
  ["Embedding", "Embedding", "embedding"],
  ["Linear", "Linear", "linear"],
  ["Add", "Add", "merge"],
  ["Concat", "Concat", "merge"],
  ["Router", "MoERouter", "routing"],
  ["Expert", "Expert", "routing"],
  ["LSTM", "LSTM", "operation"],
  ["Output", "Output", "output"],
];

function focusableItems(root) {
  if (!root) return [];
  return $$(
    [
      "button:not(:disabled)",
      '[href]:not([tabindex="-1"])',
      'input:not([type="hidden"]):not(:disabled)',
      "select:not(:disabled)",
      "textarea:not(:disabled)",
      '[tabindex]:not([tabindex="-1"])',
    ].join(", "),
    root,
  ).filter(
    (item) => item.getClientRects().length > 0 && !item.closest("[inert]"),
  );
}

function toolbarMenuItems(menu) {
  return focusableItems(menu).filter(
    (item) => !item.classList.contains("hidden"),
  );
}

function isCompactWorkspace() {
  return window.matchMedia("(max-width: 800px)").matches;
}

function updateDrawerTriggerState(drawerId, expanded) {
  $$(`[aria-controls="${drawerId}"]`).forEach((trigger) => {
    if (
      trigger.matches("[data-open-responsive-drawer]") ||
      trigger.matches("[data-open-workflow-drawer]")
    )
      trigger.setAttribute("aria-expanded", String(expanded));
  });
}

function closeDrawer({ restoreFocus = false } = {}) {
  const drawer = surfaceState.drawer;
  if (!drawer) return;
  const returnFocus = surfaceState.drawerReturnFocus;
  if (drawer.matches("[data-responsive-drawer]")) {
    drawer.classList.remove("drawer-open");
    if (isCompactWorkspace()) {
      drawer.setAttribute("aria-hidden", "true");
      drawer.inert = true;
    }
  } else {
    drawer.classList.add("hidden");
    drawer.setAttribute("aria-hidden", "true");
    drawer.inert = true;
  }
  updateDrawerTriggerState(drawer.id, false);
  surfaceState.drawer = null;
  surfaceState.drawerReturnFocus = null;
  $("#surface-backdrop")?.classList.add("hidden");
  if (restoreFocus && returnFocus?.getClientRects().length) returnFocus.focus();
}

function closeOpenDialogs({ except = null, restoreFocus = false } = {}) {
  const returnFocus = surfaceState.dialogReturnFocus;
  $$("dialog[open]").forEach((dialog) => {
    if (dialog === except) return;
    if (!restoreFocus) suppressedDialogFocus.add(dialog);
    dialog.close();
  });
  if (surfaceState.dialog !== except) {
    surfaceState.dialog = null;
    surfaceState.dialogReturnFocus = null;
  }
  if (restoreFocus && returnFocus?.getClientRects().length) returnFocus.focus();
}

function openDialog(
  dialog,
  { trigger = document.activeElement, focusSelector = null } = {},
) {
  if (!dialog) throw new Error("要打开的工作流窗口不存在。");
  closeToolbarMenus();
  closeDrawer();
  closeOpenDialogs({ except: dialog });
  surfaceState.dialog = dialog;
  surfaceState.dialogReturnFocus =
    trigger instanceof window.HTMLElement ? trigger : null;
  if (!dialog.open) dialog.showModal();
  window.requestAnimationFrame(() => {
    const target = focusSelector
      ? $(focusSelector, dialog)
      : focusableItems(dialog)[0];
    target?.focus({ preventScroll: true });
  });
  return dialog;
}

function activateWorkspaceTab(name) {
  const tab = $(`.tab[data-tab="${name}"]`);
  if (!tab) return;
  $$(".tab,.tab-body").forEach((item) => item.classList.remove("active"));
  tab.classList.add("active");
  $(`#tab-${name}`)?.classList.add("active");
}

function openDrawerSurface(drawer, trigger = document.activeElement) {
  if (!drawer) throw new Error("要打开的抽屉不存在。");
  closeToolbarMenus();
  closeOpenDialogs();
  closeDrawer();
  if (drawer.matches("[data-responsive-drawer]")) {
    if (!isCompactWorkspace()) return drawer;
    drawer.classList.add("drawer-open");
  } else {
    drawer.classList.remove("hidden");
  }
  drawer.inert = false;
  drawer.setAttribute("aria-hidden", "false");
  surfaceState.drawer = drawer;
  surfaceState.drawerReturnFocus =
    trigger instanceof window.HTMLElement ? trigger : null;
  updateDrawerTriggerState(drawer.id, true);
  $("#surface-backdrop")?.classList.remove("hidden");
  window.requestAnimationFrame(() => {
    const target =
      $("[data-close-drawer]", drawer) || focusableItems(drawer)[0] || drawer;
    target.focus?.({ preventScroll: true });
  });
  return drawer;
}

function syncResponsiveWorkspace() {
  const compact = isCompactWorkspace();
  const breakpointChanged =
    surfaceState.compactWorkspace !== null &&
    surfaceState.compactWorkspace !== compact;
  if (breakpointChanged) closeDrawer();
  surfaceState.compactWorkspace = compact;
  $$("[data-responsive-drawer]").forEach((drawer) => {
    const open =
      surfaceState.drawer === drawer &&
      drawer.classList.contains("drawer-open");
    if (compact) {
      drawer.inert = !open;
      drawer.setAttribute("aria-hidden", String(!open));
    } else {
      drawer.classList.remove("drawer-open");
      drawer.inert = false;
      drawer.setAttribute("aria-hidden", "false");
      updateDrawerTriggerState(drawer.id, false);
    }
  });
}

function trapSurfaceTab(event, root) {
  const items = focusableItems(root);
  if (!items.length) return;
  const first = items[0];
  const last = items.at(-1);
  if (
    event.shiftKey &&
    (document.activeElement === first || !root.contains(document.activeElement))
  ) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault();
    first.focus();
  }
}

function initializeSurfaceManager() {
  $$("[data-workflow-drawer]").forEach((drawer) => {
    drawer.inert = true;
    drawer.setAttribute("aria-hidden", "true");
  });
  $$("[data-open-responsive-drawer]").forEach((trigger) => {
    trigger.addEventListener("click", () => {
      const tab = trigger.dataset.panelTab;
      if (tab) activateWorkspaceTab(tab);
      openDrawerSurface($(`#${trigger.dataset.openResponsiveDrawer}`), trigger);
    });
  });
  $$("[data-close-drawer]").forEach((button) => {
    button.addEventListener("click", () => closeDrawer({ restoreFocus: true }));
  });
  $("#surface-backdrop")?.addEventListener("click", () =>
    closeDrawer({ restoreFocus: true }),
  );
  $$("dialog").forEach((dialog) => {
    dialog.addEventListener("close", () => {
      const shouldRestore = !suppressedDialogFocus.has(dialog);
      suppressedDialogFocus.delete(dialog);
      if (surfaceState.dialog !== dialog) return;
      const returnFocus = surfaceState.dialogReturnFocus;
      surfaceState.dialog = null;
      surfaceState.dialogReturnFocus = null;
      if (shouldRestore && returnFocus?.getClientRects().length)
        window.requestAnimationFrame(() => returnFocus.focus());
    });
    dialog.addEventListener("click", (event) => {
      if (event.target !== dialog) return;
      const rect = dialog.getBoundingClientRect();
      const outside =
        event.clientX < rect.left ||
        event.clientX > rect.right ||
        event.clientY < rect.top ||
        event.clientY > rect.bottom;
      if (outside) dialog.close();
    });
  });
  document.addEventListener(
    "keydown",
    (event) => {
      if (surfaceState.drawer) {
        if (event.key === "Escape") {
          event.preventDefault();
          event.stopImmediatePropagation();
          closeDrawer({ restoreFocus: true });
        } else if (event.key === "Tab") {
          trapSurfaceTab(event, surfaceState.drawer);
        }
        return;
      }
      if (surfaceState.dialog && event.key === "Tab")
        trapSurfaceTab(event, surfaceState.dialog);
    },
    true,
  );
  const compactQuery = window.matchMedia("(max-width: 800px)");
  compactQuery.addEventListener?.("change", syncResponsiveWorkspace);
  window.addEventListener("resize", syncResponsiveWorkspace);
  syncResponsiveWorkspace();
}

function closeToolbarMenus({ restoreFocus = false } = {}) {
  $$("[data-toolbar-menu]").forEach((menu) => menu.classList.add("hidden"));
  $$('[data-menu-trigger][aria-expanded="true"]').forEach((trigger) =>
    trigger.setAttribute("aria-expanded", "false"),
  );
  const returnFocus = toolbarMenuState.returnFocus;
  toolbarMenuState.menu = null;
  toolbarMenuState.trigger = null;
  toolbarMenuState.returnFocus = null;
  if (restoreFocus && returnFocus?.getClientRects().length) returnFocus.focus();
}

function positionToolbarMenu(menu, anchorRect) {
  const margin = 8;
  menu.style.visibility = "hidden";
  menu.classList.remove("hidden");
  const menuRect = menu.getBoundingClientRect();
  let left = anchorRect.right - menuRect.width;
  let top = anchorRect.bottom + 7;
  if (left < margin) left = margin;
  if (left + menuRect.width > window.innerWidth - margin)
    left = window.innerWidth - menuRect.width - margin;
  if (top + menuRect.height > window.innerHeight - margin)
    top = anchorRect.top - menuRect.height - 7;
  left = Math.max(margin, left);
  top = Math.max(
    margin,
    Math.min(top, window.innerHeight - menuRect.height - margin),
  );
  menu.style.left = `${Math.round(left)}px`;
  menu.style.top = `${Math.round(top)}px`;
  menu.style.visibility = "visible";
}

function openToolbarMenu(
  menu,
  anchor,
  { focusFirst = false, focusLast = false } = {},
) {
  if (!menu || !anchor) return;
  const anchorRect = anchor.getBoundingClientRect();
  const owner = $(`[data-menu-trigger][aria-controls="${menu.id}"]`) || anchor;
  const returnFocus = anchor.closest("#more-menu")
    ? $("#more-menu-button")
    : owner;
  closeToolbarMenus();
  closeDrawer();
  closeOpenDialogs();
  positionToolbarMenu(menu, anchorRect);
  owner.setAttribute("aria-expanded", "true");
  toolbarMenuState.menu = menu;
  toolbarMenuState.trigger = owner;
  toolbarMenuState.returnFocus = returnFocus;
  const items = toolbarMenuItems(menu);
  if (focusLast) items.at(-1)?.focus();
  else if (focusFirst) items[0]?.focus();
}

function toggleToolbarMenu(
  trigger,
  { focusFirst = false, focusLast = false } = {},
) {
  const menu = $(`#${trigger.dataset.menuTarget}`);
  if (toolbarMenuState.menu === menu) {
    closeToolbarMenus({ restoreFocus: true });
    return;
  }
  openToolbarMenu(menu, trigger, { focusFirst, focusLast });
}

function initializeToolbarMenus() {
  $$("[data-menu-trigger]").forEach((trigger) => {
    trigger.addEventListener("click", (event) => {
      event.stopPropagation();
      toggleToolbarMenu(trigger);
    });
    trigger.addEventListener("keydown", (event) => {
      if (!["ArrowDown", "ArrowUp"].includes(event.key)) return;
      event.preventDefault();
      event.stopPropagation();
      toggleToolbarMenu(trigger, {
        focusFirst: event.key === "ArrowDown",
        focusLast: event.key === "ArrowUp",
      });
    });
  });
  $$("[data-open-toolbar-menu]").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      openToolbarMenu($(`#${button.dataset.openToolbarMenu}`), button, {
        focusFirst: true,
      });
    });
  });
  $$("[data-toolbar-action]").forEach((button) => {
    button.addEventListener("click", () => {
      const target = $(button.dataset.toolbarAction);
      if (target && !target.disabled) target.click();
    });
  });
  $$(".menu-file-item").forEach((label) => {
    label.addEventListener("keydown", (event) => {
      if (!["Enter", " "].includes(event.key)) return;
      event.preventDefault();
      $("input[type=file]", label)?.click();
    });
  });
  document.addEventListener("click", (event) => {
    if (state.workflowMetrics && event.isTrusted)
      state.workflowMetrics.clicks += 1;
    const menu = event.target.closest("[data-toolbar-menu]");
    if (!menu) {
      closeToolbarMenus();
      return;
    }
    const action = event.target.closest("button");
    if (action && !action.hasAttribute("data-menu-stay-open"))
      closeToolbarMenus();
  });
  document.addEventListener("keydown", (event) => {
    const menu = toolbarMenuState.menu;
    if (!menu) return;
    if (event.key === "Escape") {
      event.preventDefault();
      event.stopImmediatePropagation();
      closeToolbarMenus({ restoreFocus: true });
      return;
    }
    if (event.key === "Tab") {
      const items = toolbarMenuItems(menu);
      if (!items.length) return;
      const first = items[0];
      const last = items.at(-1);
      if (
        event.shiftKey &&
        (document.activeElement === first ||
          !menu.contains(document.activeElement))
      ) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
      return;
    }
    if (/INPUT|SELECT|TEXTAREA/.test(event.target.tagName)) return;
    if (!["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) return;
    const items = toolbarMenuItems(menu);
    if (!items.length) return;
    event.preventDefault();
    const current = items.indexOf(document.activeElement);
    let next = 0;
    if (event.key === "End") next = items.length - 1;
    else if (event.key === "ArrowUp")
      next = current <= 0 ? items.length - 1 : current - 1;
    else if (event.key === "ArrowDown") next = (current + 1) % items.length;
    items[next].focus();
  });
  window.addEventListener("resize", () => closeToolbarMenus());
}

function updateToolbarStatusBadge() {
  const badge = $("#more-badge");
  if (!badge) return;
  const total =
    Number($("#task-badge")?.textContent || 0) +
    Number($("#issue-badge")?.textContent || 0);
  badge.textContent = total > 99 ? "99+" : String(total);
  badge.classList.toggle("hidden", total === 0);
}

async function api(path, payload) {
  const response = await fetch(path, {
    method: payload === undefined ? "GET" : "POST",
    headers:
      payload === undefined ? {} : { "Content-Type": "application/json" },
    body: payload === undefined ? undefined : JSON.stringify(payload),
  });
  let body;
  try {
    body = await response.json();
  } catch {
    body = { message: await response.text() };
  }
  if (!response.ok) {
    const error = new Error(
      body.hint
        ? `${body.message} — ${body.hint}`
        : body.message || response.statusText,
    );
    error.code = body.error || "unknown";
    error.recovery = body.details?.recovery_actions || [];
    throw error;
  }
  return body;
}

function setBusy(value, message = "处理中…") {
  if (value) state.busyMessages.push(message);
  else state.busyMessages.pop();
  state.busy = state.busyMessages.length > 0;
  const currentMessage = state.busyMessages.at(-1);
  $("#status").textContent = state.busy
    ? currentMessage
    : `${state.viewGraph?.nodes.length || 0} 个节点 · ${state.viewGraph?.edges.length || 0} 条连接 · ${state.algorithm} / ${state.direction}`;
  $("#status").setAttribute("aria-live", "polite");
  $("#canvas-shell").setAttribute("aria-busy", String(state.busy));
  document.body.classList.toggle("app-busy", state.busy);
}

function setControlBusy(controlOrSelector, busy) {
  const control =
    typeof controlOrSelector === "string"
      ? $(controlOrSelector)
      : controlOrSelector;
  if (!control) return;
  const count = controlBusyCounts.get(control) || 0;
  if (busy) {
    if (count === 0)
      control.dataset.busyPreviouslyDisabled = String(control.disabled);
    controlBusyCounts.set(control, count + 1);
    control.disabled = true;
    control.setAttribute("aria-busy", "true");
    control.classList.add("is-busy");
    return;
  }
  const next = Math.max(0, count - 1);
  if (next) {
    controlBusyCounts.set(control, next);
    return;
  }
  controlBusyCounts.delete(control);
  control.disabled = control.dataset.busyPreviouslyDisabled === "true";
  delete control.dataset.busyPreviouslyDisabled;
  control.removeAttribute("aria-busy");
  control.classList.remove("is-busy");
}

function toast(message, type = "success") {
  const element = $("#toast");
  const normalized =
    type === true ? "error" : type === false ? "success" : type;
  element.textContent = message;
  element.classList.remove("success", "warning", "error");
  element.classList.add(
    ["success", "warning", "error"].includes(normalized)
      ? normalized
      : "success",
  );
  element.setAttribute("role", normalized === "error" ? "alert" : "status");
  element.setAttribute(
    "aria-live",
    normalized === "error" ? "assertive" : "polite",
  );
  element.classList.remove("hidden");
  try {
    if (!element.matches(":popover-open")) element.showPopover();
  } catch {}
  clearTimeout(toast.timer);
  toast.timer = setTimeout(
    () => {
      try {
        if (element.matches(":popover-open")) element.hidePopover();
      } catch {}
      element.classList.add("hidden");
    },
    normalized === "error" ? 5000 : 3200,
  );
}

function initializeTextEntryDialog() {
  const dialog = $("#text-entry-dialog");
  $("#text-entry-cancel").onclick = () => dialog.close();
  $("#text-entry-confirm").onclick = () => finishTextEntry(true);
  dialog.addEventListener("close", () => {
    if (!textEntryRequest) return;
    const resolve = textEntryRequest.resolve;
    textEntryRequest = null;
    resolve(null);
  });
  dialog.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" || event.target.tagName === "TEXTAREA") return;
    event.preventDefault();
    finishTextEntry(true);
  });
}

function requestTextEntries({ title, description = "", fields }) {
  if (textEntryRequest) {
    textEntryRequest.resolve(null);
    textEntryRequest = null;
  }
  $("#text-entry-title").textContent = title;
  $("#text-entry-description").textContent = description;
  const container = $("#text-entry-fields");
  container.replaceChildren();
  fields.forEach((field) => {
    const label = document.createElement("label");
    label.textContent = field.label;
    const input = document.createElement(
      field.multiline ? "textarea" : "input",
    );
    input.dataset.entryField = field.name;
    input.value = field.value || "";
    input.placeholder = field.placeholder || "";
    input.required = field.required !== false;
    if (field.type) input.type = field.type;
    label.append(input);
    container.append(label);
  });
  return new Promise((resolve) => {
    textEntryRequest = { resolve, fields };
    openDialog($("#text-entry-dialog"), {
      trigger: document.activeElement,
      focusSelector: "[data-entry-field]",
    });
  });
}

function finishTextEntry(confirm) {
  if (!textEntryRequest) return;
  if (!confirm) {
    $("#text-entry-dialog").close();
    return;
  }
  const values = {};
  for (const input of $$("[data-entry-field]", $("#text-entry-fields"))) {
    const value = input.value.trim();
    if (input.required && !value) {
      toast(
        `请填写${input.closest("label").firstChild.textContent}。`,
        "warning",
      );
      input.focus();
      return;
    }
    values[input.dataset.entryField] = value;
  }
  const resolve = textEntryRequest.resolve;
  textEntryRequest = null;
  $("#text-entry-dialog").close();
  resolve(values);
}

function cancelTextEntryRequest() {
  if (!textEntryRequest) return;
  const resolve = textEntryRequest.resolve;
  textEntryRequest = null;
  const dialog = $("#text-entry-dialog");
  if (dialog?.open) {
    suppressedDialogFocus.add(dialog);
    dialog.close();
  }
  resolve(null);
}

function snapshot() {
  state.history.push({
    graph: clone(state.graph),
    graphId: state.graphId,
    semanticData: clone(state.semanticData),
    projectMeta: clone(state.projectMeta),
    lazy: state.lazy,
    lazySummary: clone(state.lazySummary),
    layout: clone(state.layout),
    collapsed: [...state.collapsed],
    focus: [...state.focus],
    theme: state.theme,
    page: state.page,
    algorithm: state.algorithm,
    direction: state.direction,
    comments: clone(state.comments),
    themeOverrides: clone(state.themeOverrides),
    layoutOptions: clone(state.layoutOptions),
    perspective: state.perspective,
    animate: state.animate,
    semanticLevel: state.semanticLevel,
    semanticView: state.semanticView,
    sourceSelection: [...state.sourceSelection],
    viewMemory: clone(state.viewMemory),
    viewBox: clone(state.viewBox),
    composer: clone(state.composer),
    fixedLayout: state.fixedLayout,
    workspaceMode: state.workspaceMode,
    figure: clone(state.figure),
    figureSelection: [...state.figureSelection],
    figureActivePage: state.figureActivePage,
    figureActiveLayer: state.figureActiveLayer,
    figureIncludeGuides: state.figureIncludeGuides,
    figureNeedsRebuild: state.figureNeedsRebuild,
    scene: clone(state.scene),
    sceneSelection: [...state.sceneSelection],
    sceneNeedsRebuild: state.sceneNeedsRebuild,
  });
  if (state.history.length > 100) state.history.shift();
  state.future = [];
  updateHistoryButtons();
}
function restore(data) {
  invalidateSourceBoundWork();
  state.graph = data.graph;
  state.graphId = data.graphId ?? null;
  state.semanticData = clone(data.semanticData || null);
  state.projectMeta = clone(data.projectMeta || {});
  state.lazy = !!data.lazy;
  state.lazySummary = clone(data.lazySummary || null);
  state.viewGraph = null;
  state.layout = data.layout;
  state.collapsed = new Set(data.collapsed);
  state.focus = new Set(data.focus || []);
  state.theme = data.theme;
  state.page = data.page || "auto";
  state.algorithm = data.algorithm;
  state.direction = data.direction;
  state.comments = data.comments || [];
  state.themeOverrides = data.themeOverrides || {};
  state.layoutOptions = data.layoutOptions || { rank_gap: 88, node_gap: 34 };
  state.perspective = !!data.perspective;
  state.animate = !!data.animate;
  state.semanticLevel = authorSemanticLevel(data.semanticLevel) || null;
  state.semanticView = data.semanticView || "faithful";
  state.sourceSelection = new Set(data.sourceSelection || []);
  state.viewMemory = data.viewMemory || {};
  state.viewBox = data.viewBox || null;
  state.composer = normalizeComposerState(data.composer);
  state.composerProof = null;
  state.projectMeta.figure_composer = state.composer || {};
  state.fixedLayout = !!data.fixedLayout;
  state.workspaceMode = data.workspaceMode || "graph";
  state.figure = data.figure || null;
  state.figureProof = null;
  state.figureSelection = new Set(data.figureSelection || []);
  state.figureActivePage =
    data.figureActivePage || state.figure?.pages?.[0]?.id || null;
  state.figureActiveLayer = data.figureActiveLayer || null;
  state.figureIncludeGuides = !!data.figureIncludeGuides;
  state.figureNeedsRebuild = !!data.figureNeedsRebuild;
  state.scene = data.scene || null;
  state.sceneSelection = new Set(data.sceneSelection || []);
  state.sceneNeedsRebuild = !!data.sceneNeedsRebuild;
  state.projectMeta.scene_ir = state.sceneNeedsRebuild ? {} : state.scene || {};
  state.projectMeta.figure_ir = state.figureNeedsRebuild
    ? {}
    : state.figure || {};
  applyWorkspaceMode();
  syncControls();
  refresh(state.workspaceMode === "graph" ? !state.fixedLayout : false);
}
function undo() {
  if (!state.history.length) return;
  state.future.push(currentSnapshot());
  restore(state.history.pop());
  updateHistoryButtons();
}
function redo() {
  if (!state.future.length) return;
  state.history.push(currentSnapshot());
  restore(state.future.pop());
  updateHistoryButtons();
}
function currentSnapshot() {
  return {
    graph: clone(state.graph),
    graphId: state.graphId,
    semanticData: clone(state.semanticData),
    projectMeta: clone(state.projectMeta),
    lazy: state.lazy,
    lazySummary: clone(state.lazySummary),
    layout: clone(state.layout),
    collapsed: [...state.collapsed],
    focus: [...state.focus],
    theme: state.theme,
    page: state.page,
    algorithm: state.algorithm,
    direction: state.direction,
    comments: clone(state.comments),
    themeOverrides: clone(state.themeOverrides),
    layoutOptions: clone(state.layoutOptions),
    perspective: state.perspective,
    animate: state.animate,
    semanticLevel: state.semanticLevel,
    semanticView: state.semanticView,
    sourceSelection: [...state.sourceSelection],
    viewMemory: clone(state.viewMemory),
    viewBox: clone(state.viewBox),
    composer: clone(state.composer),
    fixedLayout: state.fixedLayout,
    workspaceMode: state.workspaceMode,
    figure: clone(state.figure),
    figureSelection: [...state.figureSelection],
    figureActivePage: state.figureActivePage,
    figureActiveLayer: state.figureActiveLayer,
    figureIncludeGuides: state.figureIncludeGuides,
    figureNeedsRebuild: state.figureNeedsRebuild,
    scene: clone(state.scene),
    sceneSelection: [...state.sceneSelection],
    sceneNeedsRebuild: state.sceneNeedsRebuild,
  };
}
function updateHistoryButtons() {
  $("#undo-button").disabled = !state.history.length;
  $("#redo-button").disabled = !state.future.length;
}

async function refresh(recompute = true) {
  if (state.workspaceMode === "figure") return refreshFigureStudio();
  if (state.workspaceMode === "scene") return refreshSceneStudio();
  if (!state.graph) return false;
  const generation = sourceGeneration,
    sequence = ++graphRenderSequence,
    isCurrent = () =>
      generation === sourceGeneration &&
      sequence === graphRenderSequence &&
      state.workspaceMode === "graph";
  let succeeded = false;
  setBusy(true, state.lazy ? "正在更新按需视口…" : "正在布局和渲染…");
  try {
    let view = state.viewGraph || state.graph;
    let useLayout = !!state.fixedLayout;
    if (state.semanticLevel && state.lazy) {
      const viewport = state.viewBox || {
        x: 0,
        y: 0,
        width: 960,
        height: 540,
      };
      const response = await api("/api/viewport", {
        graph_id: state.graphId,
        graph: state.graphId ? undefined : state.graph,
        level: state.semanticLevel,
        view: state.semanticView,
        viewport,
        include: [...state.sourceSelection],
        maximum_nodes: 500,
        maximum_dom_objects: 2000,
      });
      if (!isCurrent()) return false;
      view = response.graph;
      state.layout = response.layout;
      state.viewGraph = view;
      useLayout = true;
      $("#lazy-stats").textContent =
        `${response.rendered_node_count}/500 节点 · DOM≈${response.dom_object_estimate}/2000 · ${response.elapsed_ms} ms`;
    } else if (state.semanticLevel && (recompute || !state.viewGraph)) {
      const semantic = await api("/api/semantic", {
        graph_id: state.graphId,
        graph: state.graphId ? undefined : state.graph,
        level: state.semanticLevel,
        view: state.semanticView,
        target: [...state.selection][0],
      });
      if (!isCurrent()) return false;
      view = semantic.graph;
      state.viewGraph = view;
      state.semanticData = semantic.semantic;
      state.breadcrumbs = semantic.breadcrumbs || [];
      restoreSemanticSelection();
      renderBreadcrumbs();
    } else if (!state.semanticLevel) {
      view = state.graph;
      state.viewGraph = view;
      $("#lazy-stats").textContent = "";
    }
    if (!useLayout && (recompute || !state.layout)) {
      const response = await api("/api/layout", {
        graph: view,
        collapsed: [...state.collapsed],
        focus: [...state.focus],
        focus_hops: 1,
        theme: state.theme,
        page: state.page,
        theme_overrides: state.themeOverrides,
        algorithm: state.algorithm,
        direction: state.direction,
        layout_options: state.layoutOptions,
        previous: state.layout,
      });
      if (!isCurrent()) return false;
      view = response.graph;
      state.layout = response.layout;
    }
    state.viewGraph = view;
    const response = await api("/api/render", {
      graph: view,
      theme: state.theme,
      page: state.page,
      theme_overrides: state.themeOverrides,
      algorithm: state.algorithm,
      direction: state.direction,
      layout_options: state.layoutOptions,
      layout: state.layout,
      use_layout: useLayout,
      options: displayOptions(),
    });
    if (!isCurrent()) return false;
    state.layout = response.layout;
    $("#canvas").innerHTML = response.svg;
    attachCanvasEvents();
    renderTree();
    renderInspector();
    syncNodeIcon();
    renderBreadcrumbs();
    applyViewBox(!state.viewBox);
    succeeded = true;
  } catch (error) {
    if (isCurrent()) toast(error.message, true);
  } finally {
    setBusy(false);
    if (isCurrent()) scheduleAutosave();
  }
  return succeeded;
}

function displayOptions() {
  return {
    show_shapes: $("#show-shapes").checked,
    show_parameters: $("#show-parameters").checked,
    show_flops: $("#show-flops").checked,
    show_legend: $("#show-legend").checked,
    transparent: $("#transparent").checked,
    analysis_metric: state.metric || null,
  };
}

function attachCanvasEvents() {
  const svg = $("#canvas svg");
  if (!svg) return;
  svg.classList.toggle("flowing", state.animate);
  $("#canvas-shell").classList.toggle("perspective-mode", state.perspective);
  svg.addEventListener("click", (event) => {
    const node = event.target.closest(".node"),
      edge = event.target.closest(".edge");
    if (node) {
      select(node.dataset.nodeId, event.shiftKey || event.ctrlKey);
      event.stopPropagation();
    } else if (edge) {
      select(edge.id.replace(/^edge-/, ""), event.shiftKey || event.ctrlKey);
      event.stopPropagation();
    } else select(null, false);
  });
  $$(".node", svg).forEach((element) => {
    element.addEventListener("pointerdown", beginNodeDrag);
    element.addEventListener("dblclick", () => {
      if (state.semanticLevel) drillSemantic(element.dataset.nodeId);
      else toggleNodeGroup(element.dataset.nodeId);
    });
  });
  $$(".edge", svg).forEach((element) => {
    const visiblePath = $("path[data-nndv-role='edge']", element);
    if (visiblePath) {
      const hitTarget = visiblePath.cloneNode(false);
      hitTarget.classList.add("edge-hit-target");
      hitTarget.removeAttribute("marker-start");
      hitTarget.removeAttribute("marker-end");
      hitTarget.setAttribute("stroke", "transparent");
      hitTarget.setAttribute("stroke-width", "18");
      hitTarget.setAttribute("pointer-events", "stroke");
      hitTarget.removeAttribute("data-nndv-role");
      element.prepend(hitTarget);
    }
    element.addEventListener("pointerdown", beginEdgeDrag);
  });
  svg.addEventListener("pointerdown", beginPan);
  svg.addEventListener("wheel", wheelZoom, { passive: false });
  applySelection();
}

function select(id, additive = false) {
  if (!additive) state.selection.clear();
  if (id) {
    if (additive && state.selection.has(id)) state.selection.delete(id);
    else state.selection.add(id);
  }
  const selectedNode = state.viewGraph?.nodes.find((node) => node.id === id);
  if (!additive) state.sourceSelection.clear();
  (selectedNode?.attributes?.source_nodes || (id ? [id] : [])).forEach(
    (sourceId) => state.sourceSelection.add(sourceId),
  );
  applySelection();
  renderInspector();
  renderTree();
  syncNodeIcon();
  syncSceneSelectionFrom2D("graph", [...state.sourceSelection]);
}
function applySelection() {
  $$(".node,.edge", $("#canvas")).forEach((el) =>
    el.classList.remove("selected"),
  );
  state.selection.forEach((id) => {
    $(`#node-${CSS.escape(id)}`)?.classList.add("selected");
    $(`#edge-${CSS.escape(id)}`)?.classList.add("selected");
  });
  $("#selection-count").textContent = state.selection.size
    ? `${state.selection.size} 项`
    : "未选择";
  updateResponsiveInspectorHint();
}

function updateResponsiveInspectorHint() {
  const toggle = $("#inspector-toggle"),
    badge = $("#inspector-selection-badge"),
    count = state.selection.size;
  if (!toggle || !badge) return;
  badge.textContent = String(count);
  badge.classList.toggle("hidden", count === 0);
  toggle.classList.toggle("has-selection", count > 0);
  toggle.setAttribute(
    "aria-label",
    count ? `打开检查器，当前选择 ${count} 项` : "打开检查器",
  );
  if (count && isCompactWorkspace() && !state.inspectorHintShown) {
    state.inspectorHintShown = true;
    toast("已选中图元素；可从底部“检查器”继续编辑属性。", "warning");
  }
}

let drag = null;
function beginNodeDrag(event) {
  if (event.button !== 0) return;
  event.stopPropagation();
  const id = event.currentTarget.dataset.nodeId;
  if (!state.selection.has(id)) select(id, event.shiftKey);
  const svg = $("#canvas svg"),
    point = svgPoint(svg, event);
  drag = { id, start: point, positions: {}, moved: false };
  state.selection.forEach((nodeId) => {
    const p = state.layout.nodes[nodeId];
    if (p) drag.positions[nodeId] = { x: p.x, y: p.y };
  });
  event.currentTarget.setPointerCapture(event.pointerId);
  event.currentTarget.addEventListener("pointermove", moveNodeDrag);
  event.currentTarget.addEventListener("pointerup", endNodeDrag, {
    once: true,
  });
}
function moveNodeDrag(event) {
  if (!drag) return;
  if (!drag.moved) {
    snapshot();
    drag.moved = true;
  }
  const svg = $("#canvas svg"),
    point = svgPoint(svg, event),
    dx = point.x - drag.start.x,
    dy = point.y - drag.start.y,
    snap = event.altKey ? 1 : 10;
  Object.entries(drag.positions).forEach(([id, p]) => {
    const placement = state.layout.nodes[id];
    placement.x = Math.round((p.x + dx) / snap) * snap;
    placement.y = Math.round((p.y + dy) / snap) * snap;
    const el = $(`#node-${CSS.escape(id)}`);
    if (el)
      el.setAttribute("transform", `translate(${placement.x},${placement.y})`);
  });
}
function endNodeDrag(event) {
  event.currentTarget.removeEventListener("pointermove", moveNodeDrag);
  if (!drag) return;
  const moved = drag.moved,
    changedNodeCount = Object.keys(drag.positions).length;
  if (moved)
    Object.keys(drag.positions).forEach((id) => {
      state.layout.nodes[id].locked = true;
      setPositionConstraint(
        id,
        state.layout.nodes[id].x,
        state.layout.nodes[id].y,
      );
    });
  drag = null;
  if (moved) {
    recordTrialEdit("node_changes", changedNodeCount);
    state.fixedLayout = Boolean(state.composer);
    refresh(!state.composer);
  }
}
function setPositionConstraint(id, x, y) {
  const proxy = state.viewGraph?.nodes.find((node) => node.id === id),
    target = state.graph.nodes.some((node) => node.id === id)
      ? id
      : proxy?.attributes?.collapsed_group ||
        (proxy?.attributes?.source_nodes?.length === 1
          ? proxy.attributes.source_nodes[0]
          : null);
  if (!target) return false;
  state.graph.constraints = state.graph.constraints.filter(
    (c) => !(c.kind === "position" && c.target_ids.includes(target)),
  );
  state.graph.constraints.push({
    target_ids: [target],
    kind: "position",
    value: { x, y },
    locked: true,
  });
  syncComposerNodePosition(id, x, y);
  return true;
}
function beginEdgeDrag(event) {
  if (event.button !== 0) return;
  event.stopPropagation();
  const id = event.currentTarget.id.replace(/^edge-/, "");
  select(id, event.shiftKey || event.ctrlKey);
  const route = state.layout.edges[id];
  if (!route) return;
  const svg = $("#canvas svg");
  const original = clone(route.points);
  let editablePoints = original;
  if (original.length === 2) {
    const [start, end] = original;
    if (Math.abs(end[0] - start[0]) >= Math.abs(end[1] - start[1])) {
      const middle = (start[0] + end[0]) / 2;
      editablePoints = [start, [middle, start[1]], [middle, end[1]], end];
    } else {
      const middle = (start[1] + end[1]) / 2;
      editablePoints = [start, [start[0], middle], [end[0], middle], end];
    }
  }
  edgeDrag = {
    id,
    start: svgPoint(svg, event),
    points: editablePoints,
    moved: false,
  };
  event.currentTarget.setPointerCapture(event.pointerId);
  event.currentTarget.addEventListener("pointermove", moveEdgeDrag);
  event.currentTarget.addEventListener("pointerup", endEdgeDrag, {
    once: true,
  });
}
let edgeDrag = null;
function moveEdgeDrag(event) {
  if (!edgeDrag) return;
  if (!edgeDrag.moved) {
    snapshot();
    edgeDrag.moved = true;
  }
  const point = svgPoint($("#canvas svg"), event),
    dx = point.x - edgeDrag.start.x,
    dy = point.y - edgeDrag.start.y,
    snap = event.altKey ? 1 : 10;
  const points = edgeDrag.points.map((value, index) =>
    index === 0 || index === edgeDrag.points.length - 1
      ? value
      : [
          Math.round((value[0] + dx) / snap) * snap,
          Math.round((value[1] + dy) / snap) * snap,
        ],
  );
  state.layout.edges[edgeDrag.id].points = points;
  const path = $(
    `#edge-${CSS.escape(edgeDrag.id)} path[data-nndv-role='edge']`,
  );
  if (path)
    path.setAttribute(
      "d",
      points
        .map((value, index) => `${index ? "L" : "M"} ${value[0]} ${value[1]}`)
        .join(" "),
    );
  const hitTarget = $(`#edge-${CSS.escape(edgeDrag.id)} .edge-hit-target`);
  if (hitTarget) hitTarget.setAttribute("d", path?.getAttribute("d") || "");
}
function endEdgeDrag(event) {
  event.currentTarget.removeEventListener("pointermove", moveEdgeDrag);
  if (!edgeDrag) return;
  const moved = edgeDrag.moved,
    id = edgeDrag.id;
  if (moved && !setEdgeRouteConstraint(id, state.layout.edges[id].points))
    toast("该局部边界连线只能在完整视图中持久编辑", true);
  edgeDrag = null;
  if (moved) {
    recordTrialEdit("edge_changes");
    state.fixedLayout = Boolean(state.composer);
    refresh(!state.composer);
  }
}
function setEdgeRouteConstraint(id, points) {
  const edge = state.viewGraph?.edges.find((item) => item.id === id),
    targets = state.graph.edges.some((item) => item.id === id)
      ? [id]
      : (edge?.attributes?.source_edges || []).filter((source) =>
          state.graph.edges.some((item) => item.id === source),
        );
  if (!targets.length) return false;
  state.graph.constraints = state.graph.constraints.filter(
    (c) =>
      !(
        c.kind === "edge-route" &&
        c.target_ids.some((target) => targets.includes(target))
      ),
  );
  state.graph.constraints.push({
    target_ids: targets,
    kind: "edge-route",
    value: { points: clone(points) },
    locked: true,
  });
  syncComposerEdgeRoute(id, points);
  return true;
}

function syncComposerNodePosition(id, x, y) {
  if (!state.composer) return;
  const node = state.graph.nodes.find((item) => item.id === id),
    panelId = node?.attributes?.figure_panel,
    sourceId = node?.attributes?.panel_source_node,
    panel = state.composer.panels.find((item) => item.id === panelId),
    transform = state.layout.metadata?.panel_transforms?.[panelId];
  if (!panel || !sourceId || !transform || !panel.layout?.nodes?.[sourceId])
    return;
  const placement = panel.layout.nodes[sourceId];
  placement.x = (x - transform.x) / transform.scale;
  placement.y = (y - transform.y) / transform.scale;
  placement.locked = true;
  if (!panel.locked_node_ids.includes(sourceId))
    panel.locked_node_ids.push(sourceId);
  state.projectMeta.figure_composer = state.composer;
}

function syncComposerEdgeRoute(id, points) {
  if (!state.composer) return;
  const edge = state.graph.edges.find((item) => item.id === id),
    panelId = edge?.attributes?.figure_panel,
    sourceId = edge?.attributes?.panel_source_edge,
    panel = state.composer.panels.find((item) => item.id === panelId),
    transform = state.layout.metadata?.panel_transforms?.[panelId];
  if (!panel || !sourceId || !transform) return;
  panel.manual_routes[sourceId] = points.map(([x, y]) => [
    (x - transform.x) / transform.scale,
    (y - transform.y) / transform.scale,
  ]);
  if (panel.layout?.edges?.[sourceId])
    panel.layout.edges[sourceId].points = clone(panel.manual_routes[sourceId]);
  state.projectMeta.figure_composer = state.composer;
}
function svgPoint(svg, event) {
  const point = svg.createSVGPoint();
  point.x = event.clientX;
  point.y = event.clientY;
  return point.matrixTransform(svg.getScreenCTM().inverse());
}

let pan = null;
function beginPan(event) {
  if (event.target.closest(".node,.edge") || event.button !== 0) return;
  pan = { x: event.clientX, y: event.clientY, box: currentViewBox() };
  $("#canvas").classList.add("panning");
  event.currentTarget.setPointerCapture(event.pointerId);
  event.currentTarget.addEventListener("pointermove", movePan);
  event.currentTarget.addEventListener("pointerup", endPan, { once: true });
}
function movePan(event) {
  if (!pan) return;
  const svg = $("#canvas svg"),
    scale = pan.box.width / svg.clientWidth;
  state.viewBox = {
    ...pan.box,
    x: pan.box.x - (event.clientX - pan.x) * scale,
    y: pan.box.y - (event.clientY - pan.y) * scale,
  };
  applyViewBox();
}
function endPan(event) {
  event.currentTarget.removeEventListener("pointermove", movePan);
  pan = null;
  $("#canvas").classList.remove("panning");
  if (state.lazy) scheduleViewportRefresh();
  scheduleAutosave();
}
function currentViewBox() {
  const svg = $("#canvas svg");
  if (state.viewBox) return { ...state.viewBox };
  const raw = svg.viewBox.baseVal;
  return { x: raw.x, y: raw.y, width: raw.width, height: raw.height };
}
function wheelZoom(event) {
  event.preventDefault();
  zoomBy(event.deltaY < 0 ? 1.12 : 0.89, event.clientX, event.clientY);
}
function zoomBy(factor, cx, cy) {
  const svg = $("#canvas svg");
  if (!svg) return;
  const old = currentViewBox(),
    rect = svg.getBoundingClientRect(),
    px = cx ?? rect.left + rect.width / 2,
    py = cy ?? rect.top + rect.height / 2,
    rx = (px - rect.left) / rect.width,
    ry = (py - rect.top) / rect.height;
  const width = old.width / factor,
    height = old.height / factor;
  state.viewBox = {
    x: old.x + (old.width - width) * rx,
    y: old.y + (old.height - height) * ry,
    width,
    height,
  };
  state.zoom *= factor;
  applyViewBox();
  if (state.lazy) scheduleViewportRefresh();
  scheduleAutosave();
}
function applyViewBox(reset = false) {
  const svg = $("#canvas svg");
  if (!svg) return;
  if (reset || !state.viewBox) {
    const width = Number(svg.getAttribute("width")) || 960,
      height = Number(svg.getAttribute("height")) || 540;
    state.viewBox = { x: 0, y: 0, width, height };
    state.zoom = 1;
  }
  svg.setAttribute(
    "viewBox",
    `${state.viewBox.x} ${state.viewBox.y} ${state.viewBox.width} ${state.viewBox.height}`,
  );
  $("#zoom-label").textContent = `${Math.round(state.zoom * 100)}%`;
}

function semanticKey(level = state.semanticLevel, view = state.semanticView) {
  return `${view}:${persistedSemanticLevel(level) || "raw"}`;
}
function persistedSemanticLevel(level) {
  if (level === "framework") return "model";
  if (level === "module") return "layer";
  return level;
}
function authorSemanticLevel(level) {
  if (level === "model") return "framework";
  if (level === "layer") return "module";
  return level;
}
function rememberSemanticView() {
  if (!state.layout) return;
  state.viewMemory[semanticKey()] = {
    layout: clone(state.layout),
    viewBox: state.viewBox ? { ...state.viewBox } : null,
    selection: [...state.sourceSelection],
  };
}
function restoreSemanticSelection() {
  if (!state.semanticData || !state.semanticLevel) return;
  const mapping =
    state.semanticData.source_to_semantic?.[
      persistedSemanticLevel(state.semanticLevel)
    ] || {};
  state.selection = new Set(
    [...state.sourceSelection]
      .flatMap((sourceId) => mapping[sourceId] || [])
      .filter((id) => state.viewGraph?.nodes.some((node) => node.id === id)),
  );
}
async function switchSemantic(level, view = state.semanticView, target = null) {
  const requestedLevel = level === "raw" ? null : authorSemanticLevel(level);
  if (
    state.trial.activeSessionId &&
    (state.semanticLevel !== requestedLevel || state.semanticView !== view)
  )
    recordTrialEdit("semantic_changes");
  rememberSemanticView();
  state.semanticLevel = requestedLevel;
  state.semanticView = view;
  state.viewGraph = null;
  const memory = state.viewMemory[semanticKey()];
  state.layout = memory?.layout || null;
  state.viewBox = memory?.viewBox || null;
  if (memory?.selection) state.sourceSelection = new Set(memory.selection);
  $("#semantic-level").value = state.semanticLevel || "raw";
  $("#semantic-view").value = state.semanticView;
  await refresh(true);
  if (target) select(target, false);
}
function drillSemantic(id) {
  const levels = ["framework", "stage", "block", "module", "operation"],
    index = levels.indexOf(authorSemanticLevel(state.semanticLevel));
  if (index < 0 || index === levels.length - 1) return;
  const node = state.viewGraph?.nodes.find((item) => item.id === id);
  state.sourceSelection = new Set(node?.attributes?.source_nodes || []);
  switchSemantic(levels[index + 1]);
}
function semanticUp() {
  const levels = ["framework", "stage", "block", "module", "operation"],
    index = levels.indexOf(authorSemanticLevel(state.semanticLevel));
  switchSemantic(index > 0 ? levels[index - 1] : "raw");
}
function renderBreadcrumbs() {
  const target = $("#breadcrumbs");
  if (!target) return;
  const levels = ["framework", "stage", "block", "module", "operation"];
  target.innerHTML = `<button data-level="raw" class="${state.semanticLevel ? "" : "active"}">原始图</button>${levels
    .map(
      (level) =>
        `<button data-level="${level}" class="${authorSemanticLevel(state.semanticLevel) === level ? "active" : ""}">${level}</button>`,
    )
    .join("")}`;
  $$("button", target).forEach(
    (button) => (button.onclick = () => switchSemantic(button.dataset.level)),
  );
  window.requestAnimationFrame(() => {
    $("button.active", target)?.scrollIntoView({
      block: "nearest",
      inline: "nearest",
      behavior: "auto",
    });
  });
}
function scheduleViewportRefresh() {
  clearTimeout(scheduleViewportRefresh.timer);
  scheduleViewportRefresh.timer = setTimeout(() => refresh(true), 90);
}

function renderPalette(filter = "") {
  const target = $("#palette");
  target.innerHTML = "";
  paletteItems
    .filter((item) =>
      item.join(" ").toLowerCase().includes(filter.toLowerCase()),
    )
    .forEach((item) => {
      const element = document.createElement("div");
      element.className = "palette-item";
      element.draggable = true;
      element.innerHTML = `<strong>${item[0]}</strong><span>${item[1]}</span>`;
      element.addEventListener("dragstart", (event) =>
        event.dataTransfer.setData("application/x-nndv", JSON.stringify(item)),
      );
      target.append(element);
    });
}
function addPaletteNode(item, x, y) {
  snapshot();
  const id = `node_manual_${Date.now().toString(36)}`;
  const node = {
    id,
    name: item[0],
    op_type: item[1],
    category: item[2],
    path: `manual.${id}`,
    namespace: "manual",
    inputs: [],
    outputs: [],
    parent: null,
    level: "operation",
    parameters: 0,
    trainable_parameters: 0,
    buffers: 0,
    shared_weights: [],
    attributes: {},
    source: { format: "manual" },
    analysis: {},
    tags: [],
    visible: true,
  };
  state.graph.nodes.push(node);
  const previous = [...state.selection].find((key) =>
    state.graph.nodes.some((n) => n.id === key),
  );
  if (previous) state.graph.edges.push(makeEdge(previous, id));
  state.graph.constraints.push({
    target_ids: [id],
    kind: "position",
    value: { x, y },
    locked: true,
  });
  markGraphModelModified();
  state.selection = new Set([id]);
  refresh(true);
}
function makeEdge(source, target) {
  return {
    id: `edge_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 6)}`,
    source,
    target,
    source_port: null,
    target_port: null,
    tensor: null,
    kind: "data",
    label: "",
    attributes: {},
    visible: true,
  };
}

function renderTree() {
  if (!state.graph) return;
  const query = $("#graph-search").value.toLowerCase();
  if (state.lazy && state.graphId && !state.graph.nodes.length) {
    renderLazyTree(query);
    return;
  }
  const groups = new Map(state.graph.subgraphs.map((g) => [g.id, g])),
    grouped = new Set(state.graph.subgraphs.flatMap((g) => g.node_ids));
  let html = "";
  state.graph.subgraphs.forEach((group) => {
    html += `<div class="tree-item tree-group" data-group="${escapeAttr(group.id)}">${group.collapsed ? "⊞" : "⊟"} ${escapeHtml(group.name)}<span class="tree-type">${group.node_ids.length}</span></div>`;
    group.node_ids.forEach((id) => {
      const n = state.graph.nodes.find((v) => v.id === id);
      if (n && matches(n, query)) html += treeNode(n, true);
    });
  });
  state.graph.nodes
    .filter((n) => !grouped.has(n.id) && matches(n, query))
    .forEach((n) => (html += treeNode(n, false)));
  $("#structure-tree").innerHTML = html || '<p class="empty">没有匹配节点</p>';
  $$(".tree-item[data-node]").forEach(
    (el) => (el.onclick = () => locateSourceNode(el.dataset.node)),
  );
  $$(".tree-item[data-group]").forEach(
    (el) => (el.onclick = () => toggleGroup(el.dataset.group)),
  );
  markSearch(query);
}
async function renderLazyTree(query) {
  clearTimeout(renderLazyTree.timer);
  renderLazyTree.timer = setTimeout(async () => {
    const generation = sourceGeneration;
    if (!query) {
      $("#structure-tree").innerHTML =
        '<p class="empty">大图结构索引在服务端；输入名称、类型或路径搜索。</p>';
      return;
    }
    try {
      const result = await api("/api/search", {
        graph_id: state.graphId,
        query,
        limit: 100,
      });
      if (generation !== sourceGeneration) return;
      $("#structure-tree").innerHTML =
        result.matches
          .map(
            (node) =>
              `<div class="tree-item" data-node="${escapeAttr(node.id)}"><span>◆</span><span>${escapeHtml(node.name)}</span><span class="tree-type">${escapeHtml(node.op_type)}</span></div>`,
          )
          .join("") || '<p class="empty">没有匹配节点</p>';
      $$(".tree-item[data-node]", $("#structure-tree")).forEach(
        (element) =>
          (element.onclick = () => locateSourceNode(element.dataset.node)),
      );
    } catch (error) {
      if (generation === sourceGeneration) toast(error.message, true);
    }
  }, 80);
}
function locateSourceNode(sourceId) {
  state.sourceSelection = new Set([sourceId]);
  if (!state.semanticLevel) return select(sourceId, false);
  if (state.lazy) return refresh(true);
  const semanticId =
    state.semanticData?.source_to_semantic?.[
      persistedSemanticLevel(state.semanticLevel)
    ]?.[sourceId]?.[0];
  if (semanticId) select(semanticId, false);
}
function treeNode(node, child) {
  return `<div class="tree-item ${child ? "tree-child" : ""} ${state.selection.has(node.id) ? "selected" : ""}" data-node="${escapeAttr(node.id)}"><span>${node.visible ? "◆" : "◇"}</span><span>${escapeHtml(node.name)}</span><span class="tree-type">${escapeHtml(node.op_type)}</span></div>`;
}
function matches(node, q) {
  return (
    !q || `${node.name} ${node.op_type} ${node.path}`.toLowerCase().includes(q)
  );
}
function markSearch(q) {
  $$(".node", $("#canvas")).forEach((el) =>
    el.classList.toggle(
      "search-match",
      !!q &&
        matches(
          state.viewGraph.nodes.find((n) => n.id === el.dataset.nodeId) || {},
          q,
        ),
    ),
  );
}

function renderInspector() {
  const target = $("#inspector"),
    ids = [...state.selection],
    nodes = ids
      .map(
        (id) =>
          state.graph?.nodes.find((n) => n.id === id) ||
          state.viewGraph?.nodes.find((n) => n.id === id),
      )
      .filter(Boolean),
    edges = ids
      .map(
        (id) =>
          state.graph?.edges.find((edge) => edge.id === id) ||
          state.viewGraph?.edges.find((edge) => edge.id === id),
      )
      .filter(Boolean);
  if (!nodes.length && edges.length === 1) {
    const edge = edges[0],
      options = (selected) =>
        state.graph.nodes
          .map(
            (node) =>
              `<option value="${escapeAttr(node.id)}" ${node.id === selected ? "selected" : ""}>${escapeHtml(node.name)}</option>`,
          )
          .join(""),
      attributes = edge.attributes || {};
    target.innerHTML = `<label>来源<select data-edge-field="source">${options(edge.source)}</select></label><label>目标<select data-edge-field="target">${options(edge.target)}</select></label><label>标签<input data-edge-field="label" value="${escapeAttr(edge.label || "")}"></label><label>边类型<select data-edge-field="kind">${["data", "control", "recurrent", "annotation"].map((value) => `<option ${value === edge.kind ? "selected" : ""}>${value}</option>`).join("")}</select></label><div class="row"><label>颜色<input data-edge-field="color" type="color" value="${escapeAttr(attributes.color || "#64748b")}"></label><label>线宽<input data-edge-field="line_width" type="number" min="0.25" max="12" step="0.25" value="${Number(attributes.line_width) || 1.5}"></label></div><label>箭头<select data-edge-field="arrow">${[
      ["end", "末端"],
      ["start", "起点"],
      ["both", "两端"],
      ["none", "无"],
    ]
      .map(
        ([value, label]) =>
          `<option value="${value}" ${value === (attributes.arrow || "end") ? "selected" : ""}>${label}</option>`,
      )
      .join(
        "",
      )}</select></label><label><input data-edge-field="dashed" type="checkbox" ${attributes.dashed ? "checked" : ""}> 虚线</label><p class="hint">在画布上拖动连线可移动中间折点；按住 Alt 可关闭网格吸附。</p><p class="path">${escapeHtml(edge.id)}</p>${commentHtml(ids)}`;
    $$("[data-edge-field]", target).forEach(
      (input) =>
        (input.onchange = () =>
          editEdge(
            edge.id,
            input.dataset.edgeField,
            input.type === "checkbox" ? input.checked : input.value,
          )),
    );
    bindCommentButtons();
    return;
  }
  if (!nodes.length) {
    target.innerHTML = edges.length
      ? `<p><strong>${edges.length} 条连线</strong></p><p class="empty">可按 Delete 删除，或单选一条连线编辑路径和样式。</p>${commentHtml(ids)}`
      : '<p class="empty">选择节点、连线或分组以查看和编辑属性。</p>';
    bindCommentButtons();
    return;
  }
  if (nodes.length > 1) {
    target.innerHTML = `<p><strong>${nodes.length} 个节点</strong></p><p class="empty">可使用画布工具栏进行对齐、分布、成组、复制、锁定、隐藏或评论。</p>${commentHtml(ids)}`;
    bindCommentButtons();
    return;
  }
  const node = nodes[0],
    shape =
      node.outputs?.[0]?.tensor?.shape || node.inputs?.[0]?.tensor?.shape || [],
    attributes = node.attributes || {};
  const provenance = attributes.source_nodes?.length
    ? `<section class="provenance"><h3>语义识别</h3><p><strong>${escapeHtml(attributes.semantic_type || "unknown")}</strong> · confidence ${Number(attributes.confidence || 0).toFixed(2)}</p><p>${escapeHtml((attributes.recognition_reasons || []).join(" "))}</p>${attributes.unknown_semantics || attributes.semantic_type === "unknown" ? '<p class="hint">Unknown 表示 Graph IR 中没有足够结构证据；该区域保持忠实且不会依模型名猜测。双击钻取可审查原始 operation。</p>' : ""}<p class="path">${attributes.source_nodes.length} source nodes · ${(attributes.source_edges || []).length} source edges</p></section>`
    : "";
  const analysisProvenance = Object.keys(node.analysis || {}).length
    ? `<section class="provenance"><h3>分析与 provenance</h3><pre>${escapeHtml(JSON.stringify(node.analysis, null, 2))}</pre></section>`
    : "";
  target.innerHTML = `<label>显示名称<input data-field="name" value="${escapeAttr(node.name)}"></label><label>算子类型<input data-field="op_type" value="${escapeAttr(node.op_type)}"></label><label>语义类别<select data-field="category">${["input", "output", "convolution", "normalization", "activation", "pooling", "attention", "embedding", "linear", "merge", "routing", "operation"].map((v) => `<option ${v === node.category ? "selected" : ""}>${v}</option>`).join("")}</select></label><div class="row"><label>填充色<input data-field="fill" type="color" value="${escapeAttr(attributes.fill || "#dbeafe")}"></label><label>透明度<input data-field="opacity" type="number" min="0" max="1" step="0.05" value="${attributes.opacity ?? 1}"></label></div><div class="row"><label>参数量<input data-field="parameters" type="number" value="${node.parameters || 0}"></label><label>可训练<input data-field="trainable_parameters" type="number" value="${node.trainable_parameters || 0}"></label></div><label>主要张量形状<input data-field="shape" value="${shape.join(",")}"></label><label>标签<input data-field="tags" value="${(node.tags || []).join(", ")}"></label><p class="path">${escapeHtml(node.path || node.id)}</p>${provenance}${analysisProvenance}${commentHtml(ids)}`;
  $$("[data-field]", target).forEach(
    (input) =>
      (input.onchange = () =>
        editNode(node.id, input.dataset.field, input.value)),
  );
  bindCommentButtons();
}
function commentHtml(ids) {
  const targets = new Set([...ids, ...state.sourceSelection]);
  const comments = state.comments.filter((c) =>
    (c.target_ids || []).some((id) => targets.has(id)),
  );
  if (!comments.length) return "";
  return `<h3>评论</h3>${comments.map((c) => `<div class="metric-card"><b>${escapeHtml(c.author)}</b><p>${escapeHtml(c.text)}</p><button data-resolve-comment="${escapeAttr(c.id)}">${c.resolved ? "重新打开" : "解决"}</button></div>`).join("")}`;
}
function bindCommentButtons() {
  $$("[data-resolve-comment]").forEach(
    (button) =>
      (button.onclick = () => {
        snapshot();
        const comment = state.comments.find(
          (c) => c.id === button.dataset.resolveComment,
        );
        comment.resolved = !comment.resolved;
        renderInspector();
      }),
  );
}
function editNode(id, field, value) {
  snapshot();
  const viewNode = state.viewGraph?.nodes.find((n) => n.id === id),
    sourceId = viewNode?.attributes?.source_nodes?.[0],
    node = state.graph.nodes.find((n) => n.id === id || n.id === sourceId);
  if (!node)
    return toast("聚合语义节点不能直接改写；请双击钻取后编辑源节点。", true);
  if (state.trial.activeSessionId) {
    recordTrialEdit("node_changes");
    if (["name", "tags"].includes(field)) recordTrialEdit("label_changes");
  }
  node.attributes = node.attributes || {};
  if (field === "parameters" || field === "trainable_parameters")
    node[field] = Number(value) || 0;
  else if (field === "fill") node.attributes.fill = value;
  else if (field === "opacity")
    node.attributes.opacity = Math.max(0, Math.min(1, Number(value)));
  else if (field === "tags")
    node.tags = value
      .split(",")
      .map((v) => v.trim())
      .filter(Boolean);
  else if (field === "shape") {
    const shape = value
      .split(",")
      .map((v) => v.trim())
      .filter(Boolean)
      .map((v) => (/^\d+$/.test(v) ? Number(v) : v));
    const port = node.outputs?.[0] || node.inputs?.[0];
    if (port) {
      port.tensor = port.tensor || {
        name: port.name,
        shape: [],
        dtype: "unknown",
        semantic: null,
        size_bytes: null,
        dynamic_axes: {},
      };
      port.tensor.shape = shape;
    }
  } else node[field] = value;
  markGraphModelModified();
  refresh(true);
}
function editEdge(id, field, value) {
  snapshot();
  const viewEdge = state.viewGraph?.edges.find((item) => item.id === id),
    sourceId = viewEdge?.attributes?.source_edges?.[0],
    edge = state.graph.edges.find(
      (item) => item.id === id || item.id === sourceId,
    );
  if (!edge)
    return toast("聚合语义连线不能直接改写；请钻取后编辑源连线。", true);
  recordTrialEdit("edge_changes");
  edge.attributes = edge.attributes || {};
  if (
    field === "source" ||
    field === "target" ||
    field === "label" ||
    field === "kind"
  )
    edge[field] = value;
  else if (field === "line_width")
    edge.attributes[field] = Math.max(0.25, Number(value) || 1.5);
  else edge.attributes[field] = value;
  if (field === "source" || field === "target") state.layout = null;
  markGraphModelModified();
  refresh(true);
}

async function analyze() {
  if (!requireGraphNodes("分析")) return null;
  const generation = sourceGeneration;
  snapshot();
  return submitTask("analyze", { graph: state.graph }, async (result) => {
    if (generation !== sourceGeneration) return;
    state.graph = result.graph;
    state.analysis = result.summary;
    renderAnalysis();
    await refresh(true);
  });
}

function requireGraphNodes(action) {
  if (state.graph?.nodes?.length) return true;
  toast(
    `${action}需要已载入的模型。请从 Start Center 打开示例，或使用“导入模型”。`,
    "warning",
  );
  return false;
}

function taskLabel(kind) {
  return (
    {
      analyze: "分析",
      layout: "自动布局",
      export: "导出",
      import: "导入",
      runtime: "运行时分析",
    }[kind] || kind
  );
}

function taskControls(kind) {
  const selectors = {
    analyze: ["#analyze-button"],
    layout: ["#layout-button"],
    export: ["#export-button"],
  }[kind];
  return (selectors || []).map((selector) => $(selector)).filter(Boolean);
}

async function submitTask(kind, payload, onSuccess, onFailure = null) {
  const existing = state.tasks.find(
    (task) => task.kind === kind && ["queued", "running"].includes(task.status),
  );
  if (existing) {
    toast(`${taskLabel(kind)}已在运行，可从任务中心查看进度。`, "warning");
    return existing;
  }
  const controls = taskControls(kind);
  controls.forEach((control) => setControlBusy(control, true));
  let submitted = false;
  try {
    const record = await api("/api/tasks", { kind, ...payload });
    submitted = true;
    state.tasks.unshift(record);
    renderTasks();
    toast(`${taskLabel(kind)}已开始；关闭菜单后仍可在任务中心查看。`);
    void pollTask(record.id, onSuccess, onFailure, controls);
    return record;
  } catch (error) {
    toast(error.message, true);
    return null;
  } finally {
    if (!submitted)
      controls.forEach((control) => setControlBusy(control, false));
  }
}
async function pollTask(id, onSuccess, onFailure = null, controls = []) {
  for (;;) {
    await new Promise((resolve) => setTimeout(resolve, 120));
    let task;
    try {
      task = await api(`/api/tasks/${id}?result=1`);
    } catch (error) {
      toast(error.message, true);
      controls.forEach((control) => setControlBusy(control, false));
      return;
    }
    const index = state.tasks.findIndex((item) => item.id === id);
    if (index >= 0) state.tasks[index] = task;
    else state.tasks.unshift(task);
    renderTasks();
    if (["succeeded", "failed", "cancelled"].includes(task.status)) {
      try {
        if (task.status === "succeeded" && onSuccess)
          await onSuccess(task.result, task);
        if (task.status === "succeeded") toast(`${taskLabel(task.kind)}完成。`);
        if (task.status === "failed")
          toast(task.error?.message || `${taskLabel(task.kind)}失败。`, true);
        if (task.status === "cancelled")
          toast(`${taskLabel(task.kind)}已取消。`, "warning");
        if (task.status !== "succeeded" && onFailure) await onFailure(task);
      } catch (error) {
        toast(`${taskLabel(task.kind)}完成处理失败：${error.message}`, true);
      } finally {
        controls.forEach((control) => setControlBusy(control, false));
      }
      return;
    }
  }
}
async function refreshTasks() {
  try {
    state.tasks = (await api("/api/tasks")).tasks;
    renderTasks();
  } catch (error) {
    toast(`任务中心刷新失败：${error.message}`, true);
  }
}
function renderTasks() {
  const active = state.tasks.filter((item) =>
    ["queued", "running"].includes(item.status),
  ).length;
  $("#task-badge").textContent = active;
  updateToolbarStatusBadge();
  $("#task-list").innerHTML =
    state.tasks
      .map(
        (task) =>
          `<article class="task-card" data-task="${escapeAttr(task.id)}"><header><strong>${escapeHtml(task.kind)}</strong><span>${escapeHtml(task.status)}</span></header><progress max="1" value="${Number(task.progress || 0)}"></progress><div class="task-meta"><span>${escapeHtml(task.stage)}</span><span>${Number(task.elapsed_seconds || 0).toFixed(2)} s</span></div><p class="path">${escapeHtml(JSON.stringify(task.input_size || {}))} · budget ${escapeHtml(JSON.stringify(task.resource_budget || {}))}</p>${task.error ? `<p class="error">${escapeHtml(task.error.message)}</p>` : ""}<div>${["queued", "running"].includes(task.status) ? '<button data-task-action="cancel">取消</button>' : ""}${["failed", "cancelled"].includes(task.status) ? (task.recovery_actions || [{ id: "retry", label: "Retry" }]).map((action) => `<button data-task-recovery="${escapeAttr(action.id)}">${escapeHtml(action.label)}</button>`).join("") : ""}</div></article>`,
      )
      .join("") || '<p class="empty">尚无任务</p>';
  $$("[data-task-action]", $("#task-list")).forEach(
    (button) =>
      (button.onclick = async () => {
        const id = button.closest("[data-task]").dataset.task,
          action = button.dataset.taskAction;
        try {
          const result = await api(`/api/tasks/${id}/${action}`, {});
          if (action === "retry") void pollTask(result.id);
          await refreshTasks();
          toast(
            action === "cancel" ? "已请求取消任务。" : "任务操作已提交。",
            "warning",
          );
        } catch (error) {
          toast(`任务操作失败：${error.message}`, true);
        }
      }),
  );
  $$("[data-task-recovery]", $("#task-list")).forEach(
    (button) =>
      (button.onclick = () =>
        applyTaskRecovery(
          button.closest("[data-task]").dataset.task,
          button.dataset.taskRecovery,
        )),
  );
  updateIssues();
}

async function applyTaskRecovery(taskId, action) {
  const trialActions = {
    "sample-input": "sample_input",
    "module-view": "module_view",
    summary: "semantic_summary",
    focus: "reduce_focus",
    page: "switch_page",
    retry: "retry",
  };
  let succeeded = true;
  try {
    if (action === "retry") {
      const result = await api(`/api/tasks/${taskId}/retry`, {});
      pollTask(result.id);
    } else if (action === "sample-input") $("#file-input").click();
    else if (action === "module-view")
      await switchSemantic("framework", "faithful");
    else if (action === "summary") await switchSemantic("stage", "paper");
    else if (action === "focus") {
      state.focus.clear();
      await switchSemantic("block", state.semanticView);
    } else if (action === "page") {
      state.page = "double-column";
      state.layout = null;
      syncControls();
      await refresh(true);
    }
  } catch (error) {
    succeeded = false;
    toast(error.message, true);
  }
  if (trialActions[action])
    await trialRecord("recovery", {
      action: trialActions[action],
      succeeded,
    });
  await refreshTasks();
}
function human(value, bytes = false) {
  if (value == null) return "—";
  let n = Number(value),
    units = bytes ? ["B", "KB", "MB", "GB", "TB"] : ["", "K", "M", "G", "T"],
    i = 0;
  while (Math.abs(n) >= 1000 && i < units.length - 1) {
    n /= 1000;
    i++;
  }
  return `${n.toPrecision(3)} ${units[i]}`.trim();
}
function renderAnalysis() {
  const a = state.analysis,
    target = $("#analysis-summary");
  if (!a) {
    target.innerHTML =
      '<p class="empty">点击“分析”计算参数量、FLOPs、显存、深度与瓶颈。</p>';
    return;
  }
  const percent = (value) => `${(Number(value) * 100).toFixed(1)}%`;
  const limitations = (a.limitations || [])
    .map((item) => `<li>${escapeHtml(item)}</li>`)
    .join("");
  const flopName = a.flops_complete ? "FLOPs" : "FLOPs 已覆盖小计";
  const activationName = a.activation_memory_complete
    ? "激活显存"
    : "激活显存已覆盖小计";
  target.innerHTML = `<div class="metric-card">总参数量<strong>${human(a.total_parameters)}</strong><small>${escapeHtml(a.parameters_label)} · 覆盖率 ${percent(a.parameter_coverage)}</small></div><table><tr><td>可训练参数</td><td>${human(a.trainable_parameters)}</td></tr><tr><td>${flopName}</td><td>${human(a.flops)} · ${percent(a.flops_coverage)}</td></tr><tr><td>MACs 已覆盖小计</td><td>${human(a.macs_estimate)} · ${percent(a.macs_coverage)}</td></tr><tr><td>${activationName}</td><td>${human(a.activation_bytes, true)} · ${percent(a.activation_memory_coverage)}</td></tr><tr><td>网络深度</td><td>${a.depth} · ${escapeHtml(a.depth_label)}</td></tr><tr><td>感受野覆盖率</td><td>${percent(a.receptive_field_coverage)}</td></tr><tr><td>节点 / 边</td><td>${a.node_count} / ${a.edge_count}</td></tr></table><p class="hint">${escapeHtml(a.multiply_add_convention)}</p><h4>参数瓶颈</h4>${
    a.bottlenecks.parameters
      .slice(0, 5)
      .map((v) => `<p>${escapeHtml(v.name)} · ${human(v.value)}</p>`)
      .join("") || '<p class="empty">无参数记录</p>'
  }<h4>限制</h4><ul class="limitations">${limitations}</ul>`;
}

async function addRichAnnotation(action) {
  const generation = sourceGeneration,
    ids = selectedNodeIds();
  const values = await requestTextEntries(
    action === "image"
      ? {
          title: "添加图片标注",
          description: "支持 data: URL 或可访问的本地/HTTPS 资源。",
          fields: [
            {
              name: "text",
              label: "图片 URL",
              type: "url",
              placeholder: "data:image/... 或 https://...",
            },
          ],
        }
      : {
          title: action === "zoom" ? "添加放大框" : "添加指示箭头",
          description: "说明文字会作为可编辑矢量文字保留。",
          fields: [
            {
              name: "text",
              label: action === "zoom" ? "放大框标题" : "箭头说明",
              required: false,
            },
          ],
        },
  );
  if (!values || generation !== sourceGeneration) return;
  snapshot();
  if (action === "image") {
    state.graph.annotations.push({
      id: `annotation_${Date.now().toString(36)}`,
      kind: "image",
      text: "",
      target_ids: ids,
      geometry: { x: 55, y: 75, width: 180, height: 120 },
      style: { href: values.text },
      panel: null,
    });
  } else {
    state.graph.annotations.push({
      id: `annotation_${Date.now().toString(36)}`,
      kind: action,
      text: values.text,
      target_ids: ids,
      geometry:
        action === "arrow"
          ? { x: 55, y: 75, x2: 220, y2: 75 }
          : { x: 55, y: 75, width: 220, height: 120 },
      style: {},
      panel: null,
    });
  }
  await refresh(true);
  toast("标注已添加。", "success");
}
function syncNodeIcon() {
  const node = state.graph?.nodes.find((item) => state.selection.has(item.id)),
    input = $("#style-node-icon");
  if (!input) return;
  input.disabled = !node;
  input.value =
    node?.attributes?.icon_href || node?.attributes?.image_href || "";
}
function selectedNodeIds() {
  if (state.semanticLevel)
    return [...state.sourceSelection].filter((id) =>
      state.graph.nodes.some((node) => node.id === id),
    );
  return [...state.selection].filter((id) =>
    state.graph.nodes.some((n) => n.id === id),
  );
}
function selectedEdgeIds() {
  if (state.semanticLevel)
    return [...state.selection]
      .flatMap(
        (id) =>
          state.viewGraph?.edges.find((edge) => edge.id === id)?.attributes
            ?.source_edges || [],
      )
      .filter((id) => state.graph.edges.some((edge) => edge.id === id));
  return [...state.selection].filter((id) =>
    state.graph.edges.some((edge) => edge.id === id),
  );
}
async function canvasAction(action) {
  const generation = sourceGeneration,
    ids = selectedNodeIds();
  if (
    ["connect", "group", "align-x", "align-y"].includes(action) &&
    ids.length < 2
  ) {
    toast("该操作没有可执行对象：请至少选择两个节点。", "warning");
    return;
  }
  if (action === "distribute" && ids.length < 3) {
    toast("该操作没有可执行对象：均匀分布需要至少三个节点。", "warning");
    return;
  }
  if (action === "focus" && !ids.length) {
    toast("该操作没有可执行对象：请选择要聚焦的节点。", "warning");
    return;
  }
  let values = null;
  if (action === "group") {
    values = await requestTextEntries({
      title: "创建节点分组",
      fields: [{ name: "name", label: "分组名称", value: "Module" }],
    });
  } else if (["text", "formula", "region", "panel"].includes(action)) {
    values = await requestTextEntries({
      title: action === "panel" ? "添加 Panel 标注" : "添加论文标注",
      fields: [
        {
          name: "text",
          label: action === "formula" ? "公式文字" : "标注内容",
          value: action === "panel" ? "Panel A" : "",
        },
      ],
    });
  } else if (action === "comment") {
    values = await requestTextEntries({
      title: "添加项目评论",
      description: "评论将保存在可移植项目元数据中。",
      fields: [
        {
          name: "author",
          label: "评论者",
          value: state.projectMeta?.collaboration?.author || "local",
        },
        { name: "text", label: "评论内容", multiline: true },
      ],
    });
  }
  if (generation !== sourceGeneration) return;
  if (
    ["group", "text", "formula", "region", "panel", "comment"].includes(
      action,
    ) &&
    !values
  )
    return;
  snapshot();
  if (action === "connect") {
    state.graph.edges.push(makeEdge(ids[0], ids[1]));
  } else if (action === "group") {
    state.graph.subgraphs.push({
      id: `group_${Date.now().toString(36)}`,
      name: values.name,
      node_ids: ids,
      parent: null,
      level: "module",
      collapsed: false,
      locked: false,
      attributes: {},
    });
  } else if (action === "collapse") {
    const groups = state.graph.subgraphs.filter((g) =>
      ids.some((id) => g.node_ids.includes(id)),
    );
    groups.forEach((g) => {
      g.collapsed = !g.collapsed;
      g.collapsed ? state.collapsed.add(g.id) : state.collapsed.delete(g.id);
    });
  } else if (action === "focus") {
    state.focus = new Set(ids);
  } else if (action === "clear-focus") {
    state.focus.clear();
  } else if (action === "lock") {
    ids.forEach((id) => {
      const p = state.layout.nodes[id];
      if (p) {
        p.locked = !p.locked;
        setPositionConstraint(id, p.x, p.y);
        state.graph.constraints.at(-1).locked = p.locked;
      }
    });
  } else if (action === "hide") {
    ids.forEach(
      (id) => (state.graph.nodes.find((n) => n.id === id).visible = false),
    );
    state.selection.clear();
  } else if (action === "duplicate") {
    duplicate(ids);
  } else if (action === "align-x" || action === "align-y") {
    const key = action === "align-x" ? "x" : "y",
      avg =
        ids.reduce((s, id) => s + (state.layout.nodes[id]?.[key] || 0), 0) /
        ids.length;
    ids.forEach((id) => {
      const p = state.layout.nodes[id];
      if (p) {
        p[key] = avg;
        p.locked = true;
        setPositionConstraint(id, p.x, p.y);
      }
    });
  } else if (action === "distribute") {
    const sorted = ids
        .map((id) => [id, state.layout.nodes[id]])
        .filter((v) => v[1])
        .sort((a, b) => a[1].x - b[1].x),
      first = sorted[0][1].x,
      last = sorted.at(-1)[1].x;
    sorted.forEach(([id, p], i) => {
      p.x = first + ((last - first) * i) / (sorted.length - 1);
      p.locked = true;
      setPositionConstraint(id, p.x, p.y);
    });
  } else if (["text", "formula", "region", "panel"].includes(action)) {
    state.graph.annotations.push({
      id: `annotation_${Date.now().toString(36)}`,
      kind: action === "panel" ? "panel-label" : action,
      text: values.text,
      target_ids: ids,
      geometry: { x: 55, y: 75, width: 220, height: 120 },
      style: {},
      panel: action === "panel" ? values.text : null,
    });
    if (action === "panel")
      state.graph.constraints.push({
        target_ids: ids,
        kind: "panel",
        value: values.text,
        locked: true,
      });
  } else if (action === "comment") {
    state.projectMeta.collaboration = {
      ...(state.projectMeta.collaboration || {}),
      author: values.author,
    };
    state.comments.push({
      id: `comment_${Date.now().toString(36)}`,
      author: values.author || "local",
      text: values.text,
      target_ids: ids,
      resolved: false,
      created_at: new Date().toISOString(),
    });
  }
  if (["connect", "group", "collapse", "hide", "duplicate"].includes(action))
    markGraphModelModified();
  await refresh(true);
}
function duplicate(ids) {
  const mapping = {},
    ports = {};
  ids.forEach((id) => {
    const old = state.graph.nodes.find((n) => n.id === id),
      node = clone(old),
      newId = `node_copy_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 5)}`;
    mapping[id] = newId;
    node.id = newId;
    node.name += " copy";
    node.path += ".copy";
    ["inputs", "outputs"].forEach((k) =>
      (node[k] || []).forEach((p, i) => {
        const oldPort = p.id;
        p.id = `${newId}:${k}:${i}`;
        ports[oldPort] = p.id;
      }),
    );
    state.graph.nodes.push(node);
    const p = state.layout.nodes[id];
    if (p)
      state.graph.constraints.push({
        target_ids: [newId],
        kind: "position",
        value: { x: p.x + 28, y: p.y + 28 },
        locked: true,
      });
  });
  state.graph.edges
    .filter((e) => ids.includes(e.source) && ids.includes(e.target))
    .forEach((e) =>
      state.graph.edges.push({
        ...clone(e),
        id: `edge_copy_${Math.random().toString(36).slice(2)}`,
        source: mapping[e.source],
        target: mapping[e.target],
        source_port: ports[e.source_port] || e.source_port,
        target_port: ports[e.target_port] || e.target_port,
      }),
    );
  state.selection = new Set(Object.values(mapping));
}
function toggleNodeGroup(id) {
  const group = state.graph.subgraphs.find((g) => g.node_ids.includes(id));
  if (group) toggleGroup(group.id);
}
function toggleGroup(id) {
  snapshot();
  const group = state.graph.subgraphs.find((g) => g.id === id);
  if (!group) return;
  group.collapsed = !group.collapsed;
  group.collapsed ? state.collapsed.add(id) : state.collapsed.delete(id);
  markGraphModelModified();
  refresh(true);
}

async function importFile(file) {
  let generation = invalidateSourceBoundWork();
  setBusy(true, `正在导入 ${file.name}…`);
  try {
    if (/\.(json|nndv)$/i.test(file.name)) {
      let raw = null;
      try {
        const text = await file.text();
        if (generation !== sourceGeneration) return;
        raw = JSON.parse(text);
      } catch (error) {
        if (/\.nndv$/i.test(file.name))
          throw new Error(`项目 JSON 无法解析：${error.message}`);
      }
      if (raw?.project_version && raw.graph) {
        if (
          state.trial.participantImportPending &&
          !state.trial.participantImportStarted
        ) {
          await trialRecord("import_started", {
            format: "project",
            safety_level: "safe-data",
          });
          if (generation !== sourceGeneration) return;
          state.trial.participantImportStarted = true;
          persistTrialRuntimeState();
        }
        const validated = await validatePersistedProject(raw);
        if (generation !== sourceGeneration) return;
        snapshot();
        const restored = await restoreProjectDraft(validated, {
          alreadyValidated: true,
        });
        if (!restored) return;
        generation = sourceGeneration;
        await recordParticipantImportSuccess(validated.graph, "project", 0);
        if (generation !== sourceGeneration) return;
        toast(`已导入项目 ${file.name}`);
        return;
      }
    }
    const inspectForm = new FormData();
    inspectForm.append("model", file);
    const inspection = await fetch("/api/import/inspect", {
      method: "POST",
      body: inspectForm,
    });
    const inspectionBody = await inspection.json();
    if (generation !== sourceGeneration) return;
    if (!inspection.ok)
      throw new Error(inspectionBody.hint || inspectionBody.message);
    if (
      state.trial.participantImportPending &&
      !state.trial.participantImportStarted
    ) {
      await trialRecord("import_started", {
        format: trialImportFormat(inspectionBody.plan.detected_format),
        safety_level: trialSafetyLevel(inspectionBody.plan),
      });
      if (generation !== sourceGeneration) return;
      state.trial.participantImportStarted = true;
      persistTrialRuntimeState();
    }
    state.pendingImport = { file, plan: inspectionBody.plan };
    renderImportPlan(inspectionBody.plan);
    openDialog($("#import-wizard"), { trigger: document.activeElement });
  } catch (error) {
    if (generation === sourceGeneration && state.trial.participantImportPending)
      await trialRecord("import_failed", {
        format: "unknown",
        error_code:
          error.code === "optional_dependency_missing"
            ? "optional_dependency"
            : "validation",
      });
    if (generation === sourceGeneration) toast(error.message, true);
  } finally {
    setBusy(false);
  }
}
function renderImportPlan(plan) {
  const recommendation = plan.recommendation,
    estimate = plan.estimate,
    safety = plan.safety;
  $("#import-plan").innerHTML =
    `<div class="import-grid"><article class="import-card"><strong>格式</strong><span>${escapeHtml(plan.detected_format)} · confidence ${Number(plan.confidence).toFixed(2)}</span><p>${escapeHtml(plan.reasons.join(" "))}</p></article><article class="import-card"><strong class="safety-${escapeAttr(safety.level)}">安全等级：${escapeHtml(safety.level)}</strong><p>${escapeHtml(safety.message)}</p></article><article class="import-card"><strong>Sample input</strong><p>${escapeHtml(plan.sample_input.reason)}</p><label>shape<input id="wizard-shape" placeholder="1,3,224,224"></label><label>dtype<input id="wizard-dtype" value="float32"></label><label>动态维<input id="wizard-dynamic" placeholder="batch,height,width"></label><label>多输入 JSON<textarea id="wizard-multi-input" placeholder='[{"name":"image","shape":[1,3,224,224],"dtype":"float32"}]'></textarea></label></article><article class="import-card"><strong>规模预估</strong><p>${estimate.nodes} nodes / ${estimate.edges} edges · ${escapeHtml(estimate.basis)}</p><p>建议 ${escapeHtml(recommendation.framework_view)} → ${escapeHtml(recommendation.semantic_level)} / ${escapeHtml(recommendation.semantic_view)}</p><p>${escapeHtml(recommendation.page)} · ${escapeHtml(recommendation.label_density)}</p></article></div>${plan.topology_available ? "" : '<p class="error">state_dict 只能恢复权重分组，不能恢复拓扑。</p>'}${plan.dynamic_sampling_boundary ? `<p class="hint">${escapeHtml(plan.dynamic_sampling_boundary)}</p>` : ""}`;
  $("#trust-confirm").classList.toggle("hidden", !safety.confirmation_required);
  $("#trust-confirm input").checked = false;
  $("#wizard-import").disabled = safety.confirmation_required;
}
async function confirmImport() {
  const pending = state.pendingImport;
  if (!pending) return;
  const trust = $("#trust-confirm input").checked;
  if (pending.plan.safety.confirmation_required && !trust)
    return toast("请先显式确认可信代码/pickle 来源。", "warning");
  let generation = invalidateSourceBoundWork();
  setControlBusy("#wizard-import", true);
  setBusy(true, `正在导入 ${pending.file.name}…`);
  try {
    const form = new FormData();
    form.append("model", pending.file);
    form.append("allow_code", trust ? "1" : "0");
    form.append("allow_pickle", trust ? "1" : "0");
    const response = await fetch("/api/import", { method: "POST", body: form });
    const body = await response.json();
    if (generation !== sourceGeneration) return;
    if (!response.ok)
      throw new Error(
        body.hint ? `${body.message} — ${body.hint}` : body.message,
      );
    snapshot();
    state.graph = body.graph;
    state.graphId = body.graph_id;
    state.viewGraph = null;
    state.comments = [];
    resetComposerForNewSource();
    generation = sourceGeneration;
    const shape = $("#wizard-shape")
      .value.split(",")
      .map((item) => item.trim())
      .filter(Boolean)
      .map((item) => (/^\d+$/.test(item) ? Number(item) : item));
    let multiInputs = [];
    try {
      multiInputs = JSON.parse($("#wizard-multi-input").value || "[]");
    } catch {}
    state.projectMeta = {
      model_source: { filename: pending.file.name },
      sample_inputs: multiInputs.length
        ? multiInputs
        : shape.length
          ? [{ shape, dtype: $("#wizard-dtype").value }]
          : [],
      dynamic_dimensions: $("#wizard-dynamic")
        .value.split(",")
        .map((item) => item.trim())
        .filter(Boolean)
        .reduce((result, item) => ({ ...result, [item]: null }), {}),
      import_configurations: [
        {
          config_version: pending.plan.plan_version,
          source: {
            filename: pending.file.name,
            detected_format: pending.plan.detected_format,
          },
          safety_confirmation_required:
            pending.plan.safety.confirmation_required,
          recommendation: pending.plan.recommendation,
        },
      ],
    };
    state.layout = null;
    state.collapsed.clear();
    state.focus.clear();
    state.selection.clear();
    state.sourceSelection.clear();
    state.lazy =
      !!body.lazy || Number(body.node_count || body.graph.nodes.length) > 2000;
    state.lazySummary = body.semantic_summary;
    state.semanticLevel = authorSemanticLevel(
      pending.plan.recommendation.semantic_level,
    );
    state.semanticView = pending.plan.recommendation.semantic_view;
    state.page = ["wide-two-column", "multi-panel"].includes(
      pending.plan.recommendation.page,
    )
      ? pending.plan.recommendation.page
      : pending.plan.recommendation.page;
    state.pendingImport = null;
    syncControls();
    await refresh(true);
    if (generation !== sourceGeneration) return;
    if (!state.lazy) await analyze();
    else toast("已先打开语义摘要；大图分析可从任务中心按需启动。");
    await recordParticipantImportSuccess(
      body.graph,
      trialImportFormat(pending.plan.detected_format),
      body.diagnostics?.unknown_semantics || 0,
      Number(body.node_count || body.graph.nodes.length),
      Number(body.edge_count || body.graph.edges.length),
    );
    if (generation !== sourceGeneration) return;
    // Keep the wizard open until the automatic analysis task is registered.
    // This gives both the task badge and subsequent semantic navigation one
    // coherent completion boundary instead of racing a late analysis refresh.
    $("#import-wizard").close();
    toast(`已导入 ${pending.file.name}`);
  } catch (error) {
    if (generation === sourceGeneration && state.trial.participantImportPending)
      await trialRecord("import_failed", {
        format: trialImportFormat(pending.plan.detected_format),
        error_code:
          error.code === "optional_dependency_missing"
            ? "optional_dependency"
            : "validation",
      });
    if (generation === sourceGeneration) toast(error.message, true);
  } finally {
    setBusy(false);
    setControlBusy("#wizard-import", false);
  }
}
async function compareFile(file) {
  let generation = invalidateSourceBoundWork();
  setControlBusy("#compare-input", true);
  setBusy(true, "正在生成版本对比图…");
  try {
    const source = await file.text();
    if (generation !== sourceGeneration) return;
    const raw = JSON.parse(source),
      other =
        raw.graph && raw.project_version
          ? raw.graph
          : raw.ir_version
            ? raw
            : (await api("/api/import", { source: raw, adapter: "manual" }))
                .graph;
    if (generation !== sourceGeneration) return;
    const result = await api("/api/diff", {
      before: state.graph,
      after: other,
    });
    if (generation !== sourceGeneration) return;
    snapshot();
    state.graph = result.visual_graph;
    state.graphId = null;
    state.viewGraph = null;
    state.layout = null;
    resetComposerForNewSource();
    generation = sourceGeneration;
    state.analysis = null;
    state.selection.clear();
    await refresh(true);
    if (generation !== sourceGeneration) return;
    $("#analysis-summary").innerHTML =
      `<div class="metric-card">模型差异<strong>+${result.summary.added} / −${result.summary.removed} / ~${result.summary.changed}</strong></div><table><tr><td>新增连接</td><td>${result.summary.connections_added}</td></tr><tr><td>删除连接</td><td>${result.summary.connections_removed}</td></tr></table>`;
    toast("版本对比图已生成：绿=新增，红=删除，橙=变更");
  } catch (error) {
    if (generation === sourceGeneration) toast(error.message, true);
  } finally {
    setBusy(false);
    setControlBusy("#compare-input", false);
  }
}
async function generatePaperSuggestions(readability = false) {
  if (!state.layout || !state.viewGraph)
    return toast(
      "没有可优化的布局：请先打开模型并完成当前视图布局。",
      "warning",
    );
  setControlBusy("#generate-suggestions", true);
  setControlBusy("#fix-readability", true);
  setBusy(true, readability ? "正在修复可读性…" : "正在生成可审查建议…");
  const generation = sourceGeneration;
  try {
    const endpoint = readability
        ? "/api/paper/readability"
        : "/api/paper/suggestions",
      result = await api(endpoint, {
        graph: state.viewGraph,
        layout: state.layout,
        theme: state.theme,
        theme_overrides: state.themeOverrides,
        page: state.page,
        preset: $("#paper-preset").value,
        maximum_candidates: 3,
      });
    if (generation !== sourceGeneration) return;
    state.paperSuggestions = readability
      ? [result.suggestion]
      : result.suggestions;
    renderPaperSuggestions(
      readability ? { [result.suggestion.id]: result.proof } : result.proofs,
    );
  } catch (error) {
    if (generation === sourceGeneration) toast(error.message, true);
  } finally {
    setBusy(false);
    setControlBusy("#generate-suggestions", false);
    setControlBusy("#fix-readability", false);
  }
}
function renderPaperSuggestions(proofs = {}) {
  const metrics = [
    "node_overlap",
    "edge_node_collision",
    "crossing",
    "bend_count",
    "path_length",
    "symmetry",
    "whitespace_balance",
    "label_overflow",
    "minimum_font",
    "critical_edge_salience",
  ];
  const target = $("#paper-suggestions");
  if (!state.paperSuggestions.length) {
    target.innerHTML =
      '<p class="empty">建议以 diff 展示，选择后才会应用。锁定节点、手工路由、评论和 annotation 保持不变。</p>';
    return;
  }
  target.innerHTML = state.paperSuggestions
    .map((suggestion) => {
      const proof = proofs[suggestion.id] || {};
      return `<article class="suggestion-card" data-suggestion="${escapeAttr(suggestion.id)}"><header><div><strong>${escapeHtml(suggestion.title)}</strong><p>${escapeHtml(suggestion.rationale)}</p></div><span>score Δ ${Number(suggestion.score_delta).toFixed(2)}</span></header><table class="metric-diff"><thead><tr><th>目标</th><th>before</th><th>after</th></tr></thead><tbody>${metrics.map((key) => `<tr><td>${key}</td><td>${suggestion.before[key]}</td><td>${suggestion.after[key]}</td></tr>`).join("")}</tbody></table><div><span class="proof-chip">${escapeHtml(proof.page || "proof")}</span><span class="proof-chip">${Number(proof.body_font_pt || suggestion.after.minimum_font).toFixed(2)} pt</span><span class="proof-chip">${Object.keys(suggestion.diff.moved_nodes || {}).length} moves</span><span class="proof-chip">${Object.keys(suggestion.diff.rerouted_edges || {}).length} routes</span></div>${suggestion.warnings.map((warning) => `<p class="error">${escapeHtml(warning)}</p>`).join("")}<button data-apply-suggestion class="primary">应用该 diff</button></article>`;
    })
    .join("");
  $$("[data-apply-suggestion]", $("#paper-suggestions")).forEach(
    (button) =>
      (button.onclick = async () => {
        const id = button.closest("[data-suggestion]").dataset.suggestion,
          suggestion = state.paperSuggestions.find((item) => item.id === id),
          generation = sourceGeneration;
        setControlBusy(button, true);
        try {
          const result = await api("/api/paper/apply", {
            current_layout: state.layout,
            suggestion,
          });
          if (generation !== sourceGeneration) return;
          snapshot();
          state.layout = result.layout;
          state.fixedLayout = true;
          // A paper candidate can move every node.  Fit its new physical extent
          // instead of retaining a viewBox from the pre-optimization geometry.
          state.viewBox = null;
          state.projectMeta.paper_workflow = {
            ...(state.projectMeta.paper_workflow || {}),
            preset: $("#paper-preset").value,
            suggestions: state.paperSuggestions.map((item) => ({
              id: item.id,
              before: item.before,
              after: item.after,
              score_delta: item.score_delta,
            })),
            applied: id,
          };
          if (!(await refresh(false))) {
            if (generation !== sourceGeneration) return;
            throw new Error("建议已计算，但画布更新失败。");
          }
          toast("已应用建议；可使用撤销恢复。", "success");
        } catch (error) {
          if (generation === sourceGeneration)
            toast(`应用论文建议失败：${error.message}`, true);
        } finally {
          setControlBusy(button, false);
        }
      }),
  );
}
async function exportFormat(format) {
  closeToolbarMenus();
  if (
    format !== "project" &&
    state.workspaceMode !== "scene" &&
    !requireGraphNodes(`导出 ${format.toUpperCase()}`)
  )
    return;
  if (
    format !== "project" &&
    state.workspaceMode === "scene" &&
    !sceneObjects().length
  )
    return toast(
      "Scene is empty. Add or generate objects before export.",
      "warning",
    );
  const localProject = format === "project",
    sceneExport = !localProject && state.workspaceMode === "scene";
  if (localProject) {
    setControlBusy("#export-button", true);
    setBusy(true, "正在保存可恢复项目…");
    workspaceMachine.setSaveState("saving", { message: "Saving project…" });
  }
  if (sceneExport)
    workspaceMachine.setAction("scene-export", "busy", {
      message: `Exporting Scene ${format.toUpperCase()}…`,
    });
  try {
    await performExportFormat(format);
    if (sceneExport)
      workspaceMachine.setAction("scene-export", "success", {
        message: `Scene ${format.toUpperCase()} downloaded`,
      });
  } catch (error) {
    if (localProject)
      workspaceMachine.setSaveState("error", {
        message: `Save failed: ${error.message}`,
        retry: () => exportFormat("project"),
      });
    if (sceneExport)
      workspaceMachine.setAction("scene-export", "error", {
        message: `Scene ${format.toUpperCase()} export failed: ${error.message}`,
        retry: () => exportFormat(format),
      });
    await trialRecord("export", {
      format,
      succeeded: false,
      error_code: "task_failed",
    });
    toast(
      `${format === "project" ? "项目保存" : "导出"}失败：${error.message}`,
      true,
    );
  } finally {
    if (localProject) {
      setBusy(false);
      setControlBusy("#export-button", false);
    }
  }
}

async function performExportFormat(format) {
  if (format === "project") {
    const generation = sourceGeneration;
    synchronizeModelFigureProvenanceIndex();
    const presentation = {
      ...(state.projectMeta.presentation || {}),
      teaching_animation: state.animate,
      perspective_mode: state.perspective,
    };
    delete presentation.three_dimensional;
    const body = await api("/api/project", {
      ...state.projectMeta,
      project_version: "1.4",
      name:
        state.workspaceMode === "figure" && state.figure?.name
          ? state.figure.name
          : state.workspaceMode === "scene" && state.scene?.name
            ? state.scene.name
            : state.graph.name,
      graph: state.graph,
      graph_id: state.graphId,
      theme: state.theme,
      theme_overrides: state.themeOverrides,
      layout: state.layout,
      layout_options: state.layoutOptions,
      algorithm: state.algorithm,
      direction: state.direction,
      focus: [...state.focus],
      focus_hops: 1,
      comments: state.comments,
      presentation,
      semantic_view: projectSemanticViewPayload(),
      canvas_state: {
        search: $("#graph-search").value,
        selection: [...state.sourceSelection],
        focus: [...state.focus],
        analysis_metric: state.metric,
        breadcrumbs: state.breadcrumbs,
        viewports: state.viewMemory,
        view_box: state.viewBox,
        zoom: state.zoom,
        fixed_layout: state.fixedLayout,
        workspace_mode: state.workspaceMode,
        figure_selection: [...state.figureSelection],
        figure_active_page: state.figureActivePage,
        figure_active_layer: state.figureActiveLayer,
        figure_include_guides: state.figureIncludeGuides,
        scene_selection: [...state.sceneSelection],
        scene_camera_id: state.scene?.active_camera_id || null,
        workspace_contexts: workspaceMachine.serialize().contexts,
        ui_preferences: clone(uiPreferences),
        positions_by_view: {},
        routes_by_view: {},
      },
      import_configurations: state.projectMeta.import_configurations || [],
      task_history: state.tasks.map((task) => ({
        id: task.id,
        kind: task.kind,
        status: task.status,
        result_id: task.result_id,
      })),
      paper_workflow: state.projectMeta.paper_workflow || {},
      figure_composer:
        normalizeComposerState(state.composer) ||
        normalizeComposerState(state.projectMeta.figure_composer) ||
        {},
      figure_ir: state.figureNeedsRebuild
        ? {}
        : state.figure || state.projectMeta.figure_ir || {},
      scene_ir: state.sceneNeedsRebuild
        ? {}
        : state.scene || state.projectMeta.scene_ir || {},
      export: { ...(state.projectMeta.export || {}), page: state.page },
    });
    if (generation !== sourceGeneration) return;
    try {
      window.localStorage.setItem(
        "nndv-autosaved-project",
        JSON.stringify(body),
      );
      scheduleAutosave.lastPersistedRevision = autosaveRevision(body);
      state.autosaveBlockedByInvalidProject = false;
    } catch {
      toast(
        "项目已下载；浏览器本地草稿空间不足，刷新恢复将依赖下载文件。",
        true,
      );
    }
    downloadBlob(
      new Blob([JSON.stringify(body, null, 2)], { type: "application/json" }),
      `${safeName(state.graph.name)}.nndv.json`,
    );
    await trialRecord("export", {
      format: "project",
      succeeded: true,
      error_code: "none",
    });
    toast("项目已保存，可用于刷新恢复或重新打开。", "success");
    workspaceMachine.setSaveState("saved", {
      message: "Saved",
      revision: body.updated_at || body.revision || null,
      retry: null,
    });
    return;
  }
  if (state.workspaceMode === "scene") {
    await performSceneExport(format);
    return;
  }
  await submitTask(
    "export",
    {
      graph: state.viewGraph,
      format,
      theme: state.theme,
      page: state.page,
      theme_overrides: state.themeOverrides,
      algorithm: state.algorithm,
      direction: state.direction,
      layout: state.layout,
      options: displayOptions(),
    },
    async (_result, task) => {
      const response = await fetch(`/api/tasks/${task.id}/artifact`);
      if (!response.ok) throw new Error((await response.json()).message);
      downloadBlob(
        await response.blob(),
        `${safeName(state.graph.name)}.${format === "tikz" ? "tex" : format}`,
      );
      await trialRecord("export", {
        format,
        succeeded: true,
        error_code: "none",
      });
    },
    async () =>
      trialRecord("export", {
        format,
        succeeded: false,
        error_code: "task_failed",
      }),
  );
}
function downloadBlob(blob, name) {
  const url = URL.createObjectURL(blob),
    a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
function safeName(name) {
  return (name || "diagram").replace(/[^\w\u4e00-\u9fff-]+/g, "_");
}

function emptyTrialEdits() {
  return {
    semantic_changes: 0,
    node_changes: 0,
    edge_changes: 0,
    label_changes: 0,
  };
}

function persistTrialRuntimeState() {
  try {
    if (!state.trial.activeSessionId) {
      window.localStorage.removeItem(TRIAL_RUNTIME_STORAGE);
      return;
    }
    window.localStorage.setItem(
      TRIAL_RUNTIME_STORAGE,
      JSON.stringify({
        schema_version: "0.5.1-trial-runtime-1",
        session_id: state.trial.activeSessionId,
        edits: state.trial.edits,
        first_view_recorded: state.trial.firstViewRecorded,
        paper_ready_recorded: state.trial.paperReadyRecorded,
        participant_import_pending: state.trial.participantImportPending,
        participant_import_started: state.trial.participantImportStarted,
      }),
    );
  } catch {
    // The server-side event log remains authoritative when browser storage is
    // unavailable; the UI must continue rather than interrupt the trial.
  }
}

function restoreTrialRuntimeState(sessionId) {
  try {
    const saved = JSON.parse(
      window.localStorage.getItem(TRIAL_RUNTIME_STORAGE) || "null",
    );
    if (!saved || saved.session_id !== sessionId) {
      window.localStorage.removeItem(TRIAL_RUNTIME_STORAGE);
      return false;
    }
    const edits = emptyTrialEdits();
    Object.keys(edits).forEach((key) => {
      const value = Number(saved.edits?.[key]);
      edits[key] = Number.isFinite(value) && value >= 0 ? Math.floor(value) : 0;
    });
    state.trial.edits = edits;
    state.trial.firstViewRecorded = saved.first_view_recorded === true;
    state.trial.paperReadyRecorded = saved.paper_ready_recorded === true;
    state.trial.participantImportPending =
      saved.participant_import_pending === true;
    state.trial.participantImportStarted =
      saved.participant_import_started === true;
    return true;
  } catch {
    return false;
  }
}

function recordTrialEdit(kind, amount = 1) {
  if (!state.trial.activeSessionId || !(kind in state.trial.edits)) return;
  const increment = Number(amount);
  if (!Number.isFinite(increment) || increment <= 0) return;
  state.trial.edits[kind] += Math.floor(increment);
  persistTrialRuntimeState();
}

function resetTrialCounters() {
  state.trial.startedAt = window.performance.now();
  state.trial.firstViewRecorded = false;
  state.trial.paperReadyRecorded = false;
  state.trial.edits = emptyTrialEdits();
}

function updateTrialStatus(status) {
  state.trial.enabled = status.enabled === true;
  state.trial.activeSessionId = status.active_session_id || null;
  if (state.trial.activeSessionId) {
    restoreTrialRuntimeState(state.trial.activeSessionId);
    if (state.trial.startedAt === null)
      state.trial.startedAt =
        window.performance.now() - Number(status.active_elapsed_ms || 0);
    persistTrialRuntimeState();
  } else {
    state.trial.startedAt = null;
    window.localStorage.removeItem(TRIAL_RUNTIME_STORAGE);
  }
  $("#trial-indicator").textContent = state.trial.enabled ? "开" : "关";
  $("#trial-button").classList.toggle("active", state.trial.enabled);
  $("#trial-consent").checked = state.trial.enabled;
  $("#trial-status").textContent = state.trial.enabled
    ? state.trial.activeSessionId
      ? "本地记录已启用；当前任务进行中。刷新后可继续。"
      : "本地记录已启用；尚未开始任务。"
    : "Trial Mode 未启用，不会创建试用记录。";
}

async function trialRecord(eventType, payload) {
  if (!state.trial.enabled || !state.trial.activeSessionId) return null;
  try {
    return await api("/api/trial/events", {
      event_type: eventType,
      ...payload,
    });
  } catch (error) {
    toast(`Trial Mode 本地记录失败：${error.message}`, true);
    return null;
  }
}

async function openTrialMode() {
  const dialog = $("#trial-workflow");
  openDialog(dialog, { trigger: document.activeElement });
  dialog.setAttribute("aria-busy", "true");
  setControlBusy("#trial-button", true);
  try {
    const [status, corpus] = await Promise.all([
      api("/api/trial/status"),
      api("/api/trial-cases"),
    ]);
    updateTrialStatus(status);
    $("#trial-case-list").innerHTML = corpus.cases
      .map(
        (item) =>
          `<button data-trial-case="${escapeAttr(item.key)}"><strong>${escapeHtml(item.display_name)}</strong><span>${escapeHtml(item.framework)} · ${escapeHtml(item.coverage.join(" / "))}</span></button>`,
      )
      .join("");
    $$("[data-trial-case]", $("#trial-case-list")).forEach(
      (button) =>
        (button.onclick = () => startTrialCase(button.dataset.trialCase)),
    );
  } catch (error) {
    $("#trial-case-list").innerHTML =
      `<p class="error">${escapeHtml(error.message)}</p>`;
    toast(`Trial Mode 打开失败：${error.message}`, true);
  } finally {
    dialog.setAttribute("aria-busy", "false");
    setControlBusy("#trial-button", false);
  }
}

async function applyTrialConsent(accepted) {
  const control = accepted ? "#trial-consent-apply" : "#trial-consent-revoke";
  setControlBusy(control, true);
  $("#trial-workflow").setAttribute("aria-busy", "true");
  try {
    const status = await api("/api/trial/consent", {
      accepted,
      protocol_version: "1.0",
      explicit_confirmation: accepted && $("#trial-consent").checked,
    });
    updateTrialStatus(status);
    toast(
      accepted
        ? "Trial Mode 已启用：数据仅保存在本机 JSON。"
        : "同意已撤回，当前任务已结束。",
    );
  } catch (error) {
    toast(error.message, true);
  } finally {
    $("#trial-workflow").setAttribute("aria-busy", "false");
    setControlBusy(control, false);
  }
}

async function startTrialCase(caseKey) {
  if (!state.trial.enabled)
    return toast("请先勾选并启用本地 Trial Mode。", "warning");
  const control = $(`[data-trial-case="${CSS.escape(caseKey)}"]`);
  setControlBusy(control, true);
  setBusy(true, "正在从 Web 导入独立模型用例…");
  resetTrialCounters();
  let generation = invalidateSourceBoundWork();
  let format = caseKey === "onnx_multi_io" ? "onnx" : "pytorch";
  try {
    const started = await api("/api/trial/sessions", {
      case_key: caseKey,
      workflow: "guided-web",
    });
    if (generation !== sourceGeneration) return;
    updateTrialStatus(started.status);
    await trialRecord("import_started", {
      format,
      safety_level: "local-fixture",
    });
    if (generation !== sourceGeneration) return;
    const response = await api(`/api/trial-cases/${caseKey}`, {});
    if (generation !== sourceGeneration) return;
    snapshot();
    state.graph = response.graph;
    state.graphId = response.graph_id;
    state.viewGraph = null;
    resetComposerForNewSource();
    generation = sourceGeneration;
    state.semanticLevel = authorSemanticLevel(
      response.paper_recommendation.semantic_level,
    );
    state.semanticView = "paper";
    state.page = response.paper_recommendation.page_preset;
    state.algorithm = response.paper_recommendation.layout;
    state.semanticData = { detections: response.diagnostics.detections };
    state.projectMeta = {
      trial_case: caseKey,
      paper_workflow: { recommendation: response.paper_recommendation },
    };
    state.layout = null;
    state.fixedLayout = false;
    $("#trial-workflow").close();
    await trialRecord("import_succeeded", {
      format,
      node_count: response.graph.nodes.length,
      edge_count: response.graph.edges.length,
      unknown_count: response.diagnostics.unknown_semantics,
    });
    if (generation !== sourceGeneration) return;
    await refresh(true);
    if (generation !== sourceGeneration) return;
    const elapsed = Math.round(
      window.performance.now() - state.trial.startedAt,
    );
    const svg = $("#canvas svg");
    await trialRecord("first_interactive_view", {
      elapsed_ms: elapsed,
      visible_nodes: state.viewGraph?.nodes.length || 0,
      dom_objects: svg ? svg.querySelectorAll("*").length : 0,
      semantic_level: persistedSemanticLevel(state.semanticLevel || "raw"),
    });
    if (generation !== sourceGeneration) return;
    state.trial.firstViewRecorded = true;
    persistTrialRuntimeState();
    updateIssues();
    toast("用例已导入；请审查 unknown/provenance 并继续 Paper View。");
  } catch (error) {
    if (generation === sourceGeneration && state.trial.activeSessionId)
      await trialRecord("import_failed", {
        format,
        error_code:
          error.code === "optional_dependency_missing"
            ? "optional_dependency"
            : "unknown",
      });
    if (generation === sourceGeneration) toast(error.message, true);
  } finally {
    setBusy(false);
    setControlBusy(control, false);
  }
}

function trialImportFormat(detected) {
  if (["pytorch-factory", "pytorch-pickle"].includes(detected))
    return "pytorch";
  if (detected === "pytorch-state-dict") return "state_dict";
  if (detected === "graph-ir" || detected === "manual-config") return "json";
  if (detected === "tensorflow-savedmodel") return "tensorflow";
  return [
    "torchscript",
    "onnx",
    "keras",
    "tensorflow",
    "jax",
    "mlir",
    "project",
  ].includes(detected)
    ? detected
    : "unknown";
}

function trialSafetyLevel(plan) {
  if (plan.safety.level !== "restricted") return "safe-data";
  return ["pytorch-pickle", "pytorch-state-dict"].includes(plan.detected_format)
    ? "restricted-pickle"
    : "trusted-code";
}

async function startParticipantTrial() {
  if (!state.trial.enabled)
    return toast("请先勾选并启用本地 Trial Mode。", "warning");
  setControlBusy("#trial-own-model", true);
  try {
    resetTrialCounters();
    const started = await api("/api/trial/sessions", {
      case_key: "participant_model",
      workflow: "participant-owned",
    });
    updateTrialStatus(started.status);
    state.trial.participantImportPending = true;
    state.trial.participantImportStarted = false;
    persistTrialRuntimeState();
    $("#trial-workflow").close();
    $("#file-input").click();
  } catch (error) {
    toast(error.message, true);
  } finally {
    setControlBusy("#trial-own-model", false);
  }
}

async function recordParticipantImportSuccess(
  graph,
  format,
  unknownCount = 0,
  nodeCount = graph.nodes.length,
  edgeCount = graph.edges.length,
) {
  if (!state.trial.participantImportPending) return;
  await trialRecord("import_succeeded", {
    format,
    node_count: nodeCount,
    edge_count: edgeCount,
    unknown_count: Math.max(0, Number(unknownCount || 0)),
  });
  const svg = $("#canvas svg");
  await trialRecord("first_interactive_view", {
    elapsed_ms: Math.round(window.performance.now() - state.trial.startedAt),
    visible_nodes: state.viewGraph?.nodes.length || 0,
    dom_objects: svg ? svg.querySelectorAll("*").length : 0,
    semantic_level: persistedSemanticLevel(state.semanticLevel || "raw"),
  });
  state.trial.participantImportPending = false;
  state.trial.firstViewRecorded = true;
  persistTrialRuntimeState();
}

async function finishTrial(status = "completed") {
  if (!state.trial.activeSessionId)
    return toast("当前没有进行中的试用任务。", "warning");
  const control = status === "completed" ? "#trial-finish" : "#trial-abandon";
  setControlBusy(control, true);
  await trialRecord("edit_summary", state.trial.edits);
  try {
    const result = await api("/api/trial/finish", { status });
    state.trial.activeSessionId = null;
    state.trial.participantImportPending = false;
    state.trial.participantImportStarted = false;
    persistTrialRuntimeState();
    updateTrialStatus(await api("/api/trial/status"));
    toast(
      result.summary.core_task_success
        ? "试用任务已完成，四种必需导出已记录。"
        : "试用任务已保存；报告会如实标记未完成步骤。",
    );
  } catch (error) {
    toast(error.message, true);
  } finally {
    setControlBusy(control, false);
  }
}

async function downloadTrialJson() {
  setControlBusy("#trial-download", true);
  try {
    const response = await fetch("/api/trial/export");
    if (!response.ok) throw new Error((await response.json()).message);
    downloadBlob(await response.blob(), "nn-davinci-local-trial.json");
    toast("Trial JSON 已下载到本机。", "success");
  } catch (error) {
    toast(`Trial JSON 下载失败：${error.message}`, true);
  } finally {
    setControlBusy("#trial-download", false);
  }
}

async function openStartCenter() {
  const dialog = $("#start-center");
  openDialog(dialog, { trigger: document.activeElement });
  dialog.setAttribute("aria-busy", "true");
  setControlBusy("#start-button", true);
  beginWorkflow("start-center-paper-draft");
  $("#real-model-list").innerHTML = '<p class="empty">正在读取本地语料…</p>';
  $("#scene-template-list").innerHTML =
    '<p class="empty">正在读取本地 3D Scene 模板…</p>';
  try {
    const [corpusResult, sceneTemplateResult] = await Promise.allSettled([
      api("/api/real-models"),
      api("/api/scene/templates"),
    ]);
    if (corpusResult.status === "fulfilled") {
      const corpus = corpusResult.value;
      if (!Array.isArray(corpus.models))
        throw new Error("真实模型目录响应无效。");
      $("#real-model-list").innerHTML = corpus.models
        .map(
          (model) =>
            `<button data-real-model="${escapeAttr(model.key)}" data-start-category="model"><strong>${escapeHtml(model.name)}</strong><span>${escapeHtml(model.family)} · ${human(model.parameters)} parameters · local CPU</span></button>`,
        )
        .join("");
      $$("[data-real-model]").forEach(
        (button) =>
          (button.onclick = () => loadRealModel(button.dataset.realModel)),
      );
    } else {
      $("#real-model-list").innerHTML =
        `<p class="error">${escapeHtml(corpusResult.reason.message)}</p>`;
      toast(`真实模型目录读取失败：${corpusResult.reason.message}`, true);
    }
    if (sceneTemplateResult.status === "fulfilled") {
      renderSceneTemplateCatalog(sceneTemplateResult.value);
    } else {
      $("#scene-template-list").innerHTML =
        `<p class="error">${escapeHtml(sceneTemplateResult.reason.message)}</p>`;
      toast(
        `3D Scene 模板目录读取失败：${sceneTemplateResult.reason.message}`,
        true,
      );
    }
  } catch (error) {
    toast(`Start Center 读取失败：${error.message}`, true);
  } finally {
    dialog.setAttribute("aria-busy", "false");
    setControlBusy("#start-button", false);
  }
  const templates = state.capabilities?.paper_templates || {};
  $("#template-list").innerHTML = Object.entries(templates)
    .map(
      ([key, value]) =>
        `<button data-paper-template="${escapeAttr(key)}"><strong>${escapeHtml(key)}</strong><span>${escapeHtml(value.level)} · ${escapeHtml(value.page)} · ${escapeHtml(value.layout)}</span></button>`,
    )
    .join("");
  $$("[data-paper-template]").forEach(
    (button) =>
      (button.onclick = () => {
        state.projectMeta.paper_workflow = {
          ...(state.projectMeta.paper_workflow || {}),
          requested_template: button.dataset.paperTemplate,
        };
        dialog.close();
        generatePaperDraft();
      }),
  );
  renderRecentProject();
  bindStartCenterDiscovery();
  applyStartCenterFilter();
}

function bindStartCenterDiscovery() {
  const search = $("#start-search");
  search.oninput = () => {
    applyStartCenterFilter();
  };
  $$("[data-start-filter]").forEach((button) => {
    button.onclick = () => {
      sceneUiState.startFilter = button.dataset.startFilter;
      $$("[data-start-filter]").forEach((item) => {
        const active = item === button;
        item.classList.toggle("active", active);
        item.setAttribute("aria-pressed", String(active));
      });
      applyStartCenterFilter();
    };
  });
}

function applyStartCenterFilter() {
  const root = $("#start-center"),
    query = $("#start-search")?.value.trim().toLowerCase() || "",
    category = sceneUiState.startFilter;
  if (!root) return;
  $$(
    [
      "button[data-start-action]",
      "button[data-real-model]",
      "button[data-scene-template]",
      "button[data-paper-template]",
    ].join(","),
    root,
  ).forEach((button) => {
    const ownCategory =
        button.dataset.startCategory ||
        button.closest("[data-start-category]")?.dataset.startCategory ||
        "all",
      categoryMatch =
        category === "all" || ownCategory === "all" || ownCategory === category,
      queryMatch = !query || button.textContent.toLowerCase().includes(query);
    button.dataset.startFiltered = String(!(categoryMatch && queryMatch));
  });
}

function renderSceneTemplateCatalog(catalog) {
  const templates = Array.isArray(catalog?.templates) ? catalog.templates : [],
    families = templates.map((item) => item?.family);
  if (
    catalog?.version !== "1.0" ||
    catalog?.network_required !== false ||
    families.length !== SCENE_TEMPLATE_FAMILIES.length ||
    families.some((family, index) => family !== SCENE_TEMPLATE_FAMILIES[index])
  )
    throw new Error("3D Scene 模板目录不是预期的七种本地架构。");
  $("#scene-template-list").innerHTML = templates
    .map((item) => {
      const count = Number(item.object_count);
      if (!item.name || !Number.isInteger(count) || count < 1 || !item.digest)
        throw new Error(`3D Scene 模板 ${item.family} 的目录记录无效。`);
      return `<button class="scene-template-card" data-scene-template="${escapeAttr(item.family)}" data-start-category="scene" data-template-digest="${escapeAttr(item.digest)}" aria-label="打开 ${escapeAttr(item.family)} 可编辑 3D Scene 模板"><strong>${escapeHtml(item.name)}</strong><span>${escapeHtml(item.family)} · ${count} 个可编辑对象</span><span>仅模板来源 · 不包含模型声明</span></button>`;
    })
    .join("");
  $$("[data-scene-template]", $("#scene-template-list")).forEach(
    (button) =>
      (button.onclick = () =>
        openSceneTemplate(
          button.dataset.sceneTemplate,
          button.dataset.templateDigest,
        )),
  );
}

function validateOpenedSceneTemplate(response, family, expectedDigest) {
  const scene = response?.scene,
    metadata = scene?.metadata,
    objects = (scene?.layers || []).flatMap((layer) => layer.objects || []),
    provenanceIndex = metadata?.provenance_index,
    emptyIndex = [
      "graph_to_scene",
      "semantic_to_scene",
      "figure_to_scene",
      "scene_to_source",
    ].every(
      (key) =>
        provenanceIndex?.[key] &&
        Object.keys(provenanceIndex[key]).length === 0,
    ),
    templateOnly = objects.every((object) => {
      const provenance = object?.provenance;
      return (
        provenance?.kind === "template" &&
        provenance.author_annotation === false &&
        typeof provenance.source_id === "string" &&
        provenance.source_id.length > 0 &&
        [
          provenance.graph_ir_ids,
          provenance.semantic_view_ids,
          provenance.figure_ir_ids,
        ].every((ids) => Array.isArray(ids) && ids.length === 0)
      );
    });
  if (
    response?.family !== family ||
    response?.digest !== expectedDigest ||
    scene?.schema_version !== "1.0" ||
    !Array.isArray(scene.layers) ||
    !Array.isArray(scene.cameras) ||
    objects.length < 1 ||
    metadata?.architecture_family !== family ||
    metadata?.evidenced_architecture_family !== "template" ||
    metadata?.template_provenance_only !== true ||
    metadata?.contains_model_evidence !== false ||
    metadata?.model_scene_pipeline?.mode !== "explicit-template" ||
    metadata?.model_scene_pipeline?.architecture_was_not_inferred !== true ||
    !emptyIndex ||
    !templateOnly
  )
    throw new Error(
      `3D Scene 模板 ${family} 没有通过 template-only provenance 校验。`,
    );
  return clone(scene);
}

function emptyGraphDocument(name = "Untitled") {
  return {
    name,
    nodes: [],
    edges: [],
    subgraphs: [],
    annotations: [],
    constraints: [],
    inputs: [],
    outputs: [],
    metadata: {
      source_format: "manual",
      contains_model_evidence: false,
    },
    analysis: {},
    ir_version: "1.0",
  };
}

async function openSceneTemplate(family, expectedDigest) {
  if (!SCENE_TEMPLATE_FAMILIES.includes(family))
    return toast(`未知 3D Scene 模板：${family}`, "error");
  const control = $(`[data-scene-template="${CSS.escape(family)}"]`),
    requestGeneration = invalidateSourceBoundWork();
  setControlBusy(control, true);
  setBusy(true, `正在打开 ${family} 3D Scene 模板…`);
  try {
    const response = await api(
      `/api/scene/templates/${encodeURIComponent(family)}`,
      {},
    );
    if (requestGeneration !== sourceGeneration) return;
    const scene = validateOpenedSceneTemplate(response, family, expectedDigest);
    snapshot();
    state.graph = emptyGraphDocument(`${scene.name} · Empty Graph`);
    state.graphId = null;
    state.viewGraph = null;
    state.layout = null;
    state.comments = [];
    resetComposerForNewSource();
    state.layout = null;
    state.page = "auto";
    state.algorithm = "auto";
    state.direction = "LR";
    state.perspective = false;
    state.animate = false;
    state.themeOverrides = {};
    state.layoutOptions = { rank_gap: 88, node_gap: 34 };
    state.semanticLevel = null;
    state.semanticView = "faithful";
    state.semanticData = null;
    state.scene = scene;
    state.sceneSelection = new Set(scene.selection_ids || []);
    state.sceneNeedsRebuild = false;
    state.projectMeta = {
      figure_ir: {},
      figure_composer: {},
      scene_ir: scene,
      semantic_view: {},
    };
    workspaceMachine.setContext("graph", {
      selection: [],
      view_box: null,
      semantic_level: null,
      semantic_view: "faithful",
    });
    workspaceMachine.setContext("figure", {});
    workspaceMachine.setContext("scene", {
      selection: [...state.sceneSelection],
      camera_id: scene.active_camera_id,
      camera: null,
    });
    workspaceMachine.transition("graph");
    state.workspaceMode = "scene";
    workspaceMachine.transition("scene");
    $("#start-center").close();
    syncControls();
    applyWorkspaceMode();
    initializeSceneStudio();
    await refreshSceneStudio();
    recordWorkflowStep(`scene-template-${family}`);
    toast(`${scene.name} 已作为可编辑 template-only Scene 打开。`, "success");
  } catch (error) {
    toast(`3D Scene 模板打开失败：${error.message}`, "error");
  } finally {
    setBusy(false);
    setControlBusy(control, false);
  }
}

function beginWorkflow(name) {
  state.workflowMetrics = {
    name,
    started_at: window.performance.now(),
    clicks: 0,
    steps: [],
    recoveries: 0,
    first_figure_ms: null,
  };
}

function recordWorkflowStep(step) {
  if (!state.workflowMetrics) return;
  if (!state.workflowMetrics.steps.includes(step))
    state.workflowMetrics.steps.push(step);
}

function renderRecentProject() {
  let draft = null;
  try {
    draft = JSON.parse(
      window.localStorage.getItem("nndv-autosaved-project") || "null",
    );
  } catch {}
  $("#recent-projects").innerHTML = draft?.graph
    ? `<button id="recover-project"><strong>${escapeHtml(draft.name || draft.graph.name)}</strong><span>自动保存 · ${escapeHtml(draft.updated_at || "本地草稿")}</span></button>`
    : '<p class="empty">暂无最近项目</p>';
  if ($("#recover-project"))
    $("#recover-project").onclick = async () => {
      try {
        state.workflowMetrics && (state.workflowMetrics.recoveries += 1);
        const restored = await restoreProjectDraft(draft);
        if (!restored) return;
        await trialRecord("recovery", {
          action: "autosave_restore",
          succeeded: true,
        });
        $("#start-center").close();
        toast("已恢复自动保存项目");
      } catch (error) {
        await trialRecord("recovery", {
          action: "autosave_restore",
          succeeded: false,
        });
        toast(`自动保存项目未通过校验，未恢复：${error.message}`, true);
      }
    };
}

function normalizeComposerState(value) {
  if (!value || typeof value !== "object" || !Array.isArray(value.panels))
    return null;
  if (value.panels.length < 1 || value.panels.length > 8) return null;
  const ids = value.panels.map((panel) => panel?.id);
  if (
    new Set(ids).size !== ids.length ||
    ids.some((id) => ![..."ABCDEFGH"].includes(id)) ||
    value.panels.some(
      (panel) =>
        !panel?.graph ||
        !Array.isArray(panel.graph.nodes) ||
        !Array.isArray(panel.graph.edges),
    )
  )
    return null;
  return value;
}

function resetComposerForNewSource() {
  state.composer = null;
  state.composerProof = null;
  state.fixedLayout = false;
  state.viewBox = null;
  state.projectMeta = {};
  resetFigureForNewSource();
  state.comments = [];
}

function invalidateSourceBoundWork() {
  sourceGeneration += 1;
  graphRenderSequence += 1;
  cancelTextEntryRequest();
  clearTimeout(scheduleViewportRefresh.timer);
  clearTimeout(renderLazyTree.timer);
  lensAbortController?.abort();
  lensAbortController = null;
  clearStructureLensResult();
  studioRenderSequence += 1;
  sceneRenderSequence += 1;
  return sourceGeneration;
}

function resetFigureForNewSource() {
  invalidateSourceBoundWork();
  state.figure = null;
  state.figureProof = null;
  state.figureSelection.clear();
  state.figureActivePage = null;
  state.figureActiveLayer = null;
  state.figureLensResult = null;
  state.figureNeedsRebuild = false;
  state.scene = null;
  state.sceneSelection.clear();
  state.sceneNeedsRebuild = false;
  state.semanticData = null;
  state.collapsed.clear();
  state.focus.clear();
  state.selection.clear();
  state.sourceSelection.clear();
  state.viewMemory = {};
  state.breadcrumbs = [];
  state.comments = state.comments.filter(
    (comment) => !(comment.target_ids || []).length,
  );
  state.analysis = null;
  state.paperSuggestions = [];
  state.lazy = Number(state.graph?.nodes?.length || 0) > 2_000;
  state.lazySummary = null;
  state.issues = [];
  renderAnalysis();
  renderPaperSuggestions();
  state.workspaceMode = "graph";
  state.autosaveBlockedByInvalidProject = false;
  if (state.projectMeta) {
    state.projectMeta.figure_ir = {};
    state.projectMeta.scene_ir = {};
    state.projectMeta.semantic_view = {};
  }
}

function markGraphModelModified() {
  invalidateSourceBoundWork();
  state.graphId = null;
  state.semanticData = null;
  state.viewGraph = null;
  state.figureNeedsRebuild = Boolean(state.figure);
  state.sceneNeedsRebuild = Boolean(state.scene);
  markProjectDirty(
    "Graph changed; Figure and Scene projections may need rebuild",
  );
  state.autosaveBlockedByInvalidProject = false;
  if (state.projectMeta) state.projectMeta.semantic_view = {};
}

function normalizeViewBox(value) {
  if (!value || typeof value !== "object") return null;
  const result = Object.fromEntries(
    ["x", "y", "width", "height"].map((key) => [key, Number(value[key])]),
  );
  if (
    Object.values(result).some((item) => !Number.isFinite(item)) ||
    result.width <= 0 ||
    result.height <= 0
  )
    return null;
  return result;
}

function isComposedCanvasDraft(draft, composer, layout) {
  if (!composer || !layout) return false;
  const graphComposer = draft.graph?.metadata?.figure_composer,
    digests = layout.metadata?.panel_layout_digests,
    transforms = layout.metadata?.panel_transforms,
    panelIds = composer.panels.map((panel) => panel.id);
  return Boolean(
    graphComposer?.panel_count === panelIds.length &&
      digests &&
      transforms &&
      panelIds.every(
        (id) =>
          Object.prototype.hasOwnProperty.call(digests, id) &&
          Object.prototype.hasOwnProperty.call(transforms, id),
      ),
  );
}

function hydrateProjectDraft(draft) {
  if (!draft?.graph) throw new Error("项目缺少 Graph IR，无法恢复。");
  scheduleAutosave.lastPersistedRevision = draft.updated_at || null;
  // A validated project is a complete replacement for the current Figure
  // session.  Cancel work tied to the previous document before installing it,
  // otherwise a stale Lens/render response could repopulate transient state.
  invalidateSourceBoundWork();
  const composer = normalizeComposerState(draft.figure_composer),
    nestedLayout = draft.layout?.result,
    legacyLayout =
      draft.layout?.nodes && draft.layout?.edges ? draft.layout : null,
    layout = nestedLayout || legacyLayout || null,
    composedCanvas = isComposedCanvasDraft(draft, composer, layout);
  state.graph = draft.graph;
  state.graphId = null;
  state.comments = draft.comments || [];
  state.projectMeta = draft;
  state.projectMeta.figure_composer = composer || {};
  state.theme = draft.theme || "neurips";
  state.page = draft.export?.page || "auto";
  state.themeOverrides = draft.theme_overrides || {};
  state.layout = layout;
  state.layoutOptions = draft.layout?.layout_options || {
    rank_gap: 88,
    node_gap: 34,
  };
  state.algorithm = draft.layout?.algorithm || "auto";
  state.direction = draft.layout?.direction || "LR";
  state.focus = new Set(draft.layout?.focus || draft.canvas_state?.focus || []);
  state.perspective = !!(
    draft.presentation?.perspective_mode ??
    draft.presentation?.three_dimensional
  );
  state.animate = !!draft.presentation?.teaching_animation;
  state.semanticLevel = composedCanvas
    ? null
    : authorSemanticLevel(draft.semantic_view?.level) || null;
  state.semanticView = draft.semantic_view?.view || "faithful";
  state.sourceSelection = new Set(draft.canvas_state?.selection || []);
  state.viewMemory = draft.canvas_state?.viewports || {};
  state.metric = draft.canvas_state?.analysis_metric || "";
  state.breadcrumbs = draft.canvas_state?.breadcrumbs || [];
  state.viewBox = normalizeViewBox(draft.canvas_state?.view_box);
  state.zoom =
    Number.isFinite(Number(draft.canvas_state?.zoom)) &&
    Number(draft.canvas_state?.zoom) > 0
      ? Number(draft.canvas_state.zoom)
      : 1;
  state.composer = composer;
  state.composerProof = null;
  state.figure =
    Array.isArray(draft.figure_ir?.pages) && draft.figure_ir.pages.length
      ? draft.figure_ir
      : null;
  state.figureProof = null;
  state.figureLensResult = null;
  state.figureLastInteractionMs = null;
  state.figureNeedsRebuild = false;
  state.scene =
    Array.isArray(draft.scene_ir?.layers) && draft.scene_ir.layers.length
      ? draft.scene_ir
      : null;
  state.sceneNeedsRebuild = false;
  state.workspaceMode =
    draft.canvas_state?.workspace_mode === "figure" && state.figure
      ? "figure"
      : draft.canvas_state?.workspace_mode === "scene" && state.scene
        ? "scene"
        : "graph";
  state.figureSelection = new Set(draft.canvas_state?.figure_selection || []);
  state.figureActivePage =
    draft.canvas_state?.figure_active_page ||
    state.figure?.pages?.[0]?.id ||
    null;
  state.figureActiveLayer = draft.canvas_state?.figure_active_layer || null;
  state.figureIncludeGuides = !!draft.canvas_state?.figure_include_guides;
  state.sceneSelection = new Set(
    draft.canvas_state?.scene_selection || state.scene?.selection_ids || [],
  );
  if (state.scene && draft.canvas_state?.scene_camera_id)
    state.scene.active_camera_id = draft.canvas_state.scene_camera_id;
  if (state.scene && draft.canvas_state?.scene_camera_id) {
    const savedCamera = state.scene.cameras?.find(
      (camera) => camera.id === draft.canvas_state.scene_camera_id,
    );
    if (savedCamera) {
      savedCamera.metadata = savedCamera.metadata || {};
      savedCamera.metadata.user_saved_camera = true;
    }
  }
  if (draft.canvas_state?.workspace_contexts)
    workspaceMachine.hydrate({
      workspace: state.workspaceMode,
      contexts: draft.canvas_state.workspace_contexts,
    });
  const persistedUiPreferences =
    draft.canvas_state?.ui_preferences || draft.ui_preferences;
  if (persistedUiPreferences) {
    Object.assign(uiPreferences, persistedUiPreferences);
    uiPreferences.sidebars = {
      ...uiPreferences.sidebars,
      ...(persistedUiPreferences.sidebars || {}),
    };
    window.NNDVState.applyPreferences(uiPreferences);
  }
  state.fixedLayout = composedCanvas;
  state.viewGraph = composedCanvas ? state.graph : null;
  state.lazy = !composedCanvas && state.graph.nodes.length > 2000;
  state.collapsed = new Set(
    (state.graph.subgraphs || [])
      .filter((group) => group.collapsed)
      .map((group) => group.id),
  );
  state.selection.clear();
  const persistedSemantic = semanticDocumentFromEnvelope(draft.semantic_view);
  state.semanticData = persistedSemantic ? clone(persistedSemantic) : null;
  return composedCanvas;
}

async function validatePersistedProject(draft) {
  return api("/api/project", { project: draft });
}

async function restoreProjectDraft(draft, { alreadyValidated = false } = {}) {
  let generation = invalidateSourceBoundWork();
  const validated = alreadyValidated
    ? draft
    : await validatePersistedProject(draft);
  if (generation !== sourceGeneration) return null;
  hydrateProjectDraft(validated);
  generation = sourceGeneration;
  state.autosaveBlockedByInvalidProject = false;
  syncControls();
  await refresh(!state.fixedLayout);
  if (generation !== sourceGeneration) return null;
  return validated;
}

async function loadRealModel(name) {
  const control = $(`[data-real-model="${CSS.escape(name)}"]`);
  let generation = invalidateSourceBoundWork();
  setControlBusy(control, true);
  setBusy(true, "正在构造本地真实模型…");
  const started = window.performance.now();
  try {
    const response = await api(`/api/real-models/${name}`, {
      view: "operation",
    });
    if (generation !== sourceGeneration) return;
    snapshot();
    state.graph = response.graph;
    state.graphId = response.graph_id;
    state.viewGraph = null;
    resetComposerForNewSource();
    generation = sourceGeneration;
    state.semanticLevel = authorSemanticLevel(
      response.paper_recommendation.semantic_level,
    );
    state.semanticView = "paper";
    state.page = response.paper_recommendation.page_preset;
    state.algorithm = response.paper_recommendation.layout;
    state.projectMeta = {
      model_source: {
        real_model: name,
        seed: response.graph.metadata.random_seed,
      },
      paper_workflow: { recommendation: response.paper_recommendation },
    };
    state.layout = null;
    state.fixedLayout = false;
    $("#start-center").close();
    recordWorkflowStep("real-model-opened");
    await refresh(true);
    if (generation !== sourceGeneration) return;
    state.workflowMetrics.first_figure_ms = Math.round(
      window.performance.now() - started,
    );
    updateIssues();
    toast("真实模型已打开；未下载权重。可继续生成论文图。");
  } catch (error) {
    if (generation === sourceGeneration) {
      if (state.workflowMetrics) state.workflowMetrics.recoveries += 1;
      toast(error.message, true);
    }
  } finally {
    setBusy(false);
    setControlBusy(control, false);
  }
}

async function generatePaperDraft() {
  if (!requireGraphNodes("生成论文图")) return;
  setControlBusy("#generate-paper-button", true);
  setBusy(true, "正在生成三个可审查论文图候选…");
  const generation = sourceGeneration;
  try {
    const response = await api("/api/paper/generate", {
      graph: state.graph,
      graph_id: state.graphId,
      maximum_candidates: 3,
    });
    if (generation !== sourceGeneration) return;
    state.projectMeta.paper_workflow = {
      version: response.version,
      recommendation: response.recommendation,
      caption: response.caption,
      automation_metrics: state.workflowMetrics,
    };
    state.viewGraph = response.paper_graph;
    state.layout = response.initial_layout;
    state.fixedLayout = true;
    state.semanticLevel = authorSemanticLevel(
      response.recommendation.semantic_level,
    );
    state.semanticView = "paper";
    state.paperSuggestions = response.candidates.map((candidate) => ({
      ...candidate,
      after: candidate.metrics,
      score_delta: 0,
      rationale: response.recommendation.reasons.join(" "),
    }));
    recordWorkflowStep("paper-candidates-generated");
    renderPaperSuggestions();
    openDialog($("#paper-workflow"), { trigger: document.activeElement });
    if (!(await refresh(false))) {
      if (generation !== sourceGeneration) return;
      throw new Error("论文候选已生成，但画布渲染失败。请在优化器中重试。");
    }
    updateIssues();
  } catch (error) {
    if (generation === sourceGeneration) {
      if (state.workflowMetrics) state.workflowMetrics.recoveries += 1;
      toast(error.message, true);
    }
  } finally {
    setBusy(false);
    setControlBusy("#generate-paper-button", false);
  }
}

function defaultComposer() {
  const source = state.composer?.panels?.[0]?.graph || state.graph;
  return {
    composer_version: "1.2",
    title: `${source.name} paper figure`,
    panels: [
      composerPanel("A", "Semantic blocks", source, "block"),
      composerPanel("B", "Operation evidence", source, "operation"),
    ],
    page_preset: "double-column",
    arrangement: "horizontal",
    alignment: "baseline",
    equal_width: true,
    equal_height: true,
    gap: 28,
    shared_legend: true,
    shared_colors: true,
    shared_font: "Inter, Arial, sans-serif",
    number_format: "human",
    theme: state.theme,
    connections: [],
  };
}

function composerPanel(id, title, graph, semanticLevel) {
  return {
    id,
    title,
    graph: clone(graph),
    semantic_level: semanticLevel,
    semantic_view: "paper",
    layout: {},
    layout_algorithm: "auto",
    label_density: "paper",
    locked_node_ids: [],
    manual_routes: {},
    annotations: [],
    source_reference: {
      graph_name: graph.name,
      source_level: state.semanticLevel || "raw",
      source_view: state.semanticView,
    },
    mode: "schematic",
    locked: false,
    geometry: {},
  };
}

function setComposerStatus(mode, message) {
  const status = $("#composer-status");
  status.classList.remove("ready", "error");
  if (mode !== "busy") status.classList.add(mode);
  status.setAttribute("aria-busy", String(mode === "busy"));
  $("#composer-status-text").textContent = message;
}

function setComposerAvailability(available) {
  $("#composer-content").classList.toggle("hidden", !available);
  for (const selector of [
    "#composer-add-panel",
    "#composer-preview",
    "#composer-export",
  ]) {
    const control = $(selector);
    control.disabled = !available;
  }
}

function composerPaperState() {
  if (!state.composerProof) return "待生成 proof";
  return state.composerProof.paper_ready ? "Paper-ready" : "需继续调整";
}

function renderComposerSummary() {
  const target = $("#composer-summary");
  if (!state.composer) {
    target.replaceChildren();
    return;
  }
  const sourceNames = [
    ...new Set(
      state.composer.panels.map(
        (panel) =>
          panel.source_reference?.graph_name || panel.graph?.name || "当前图",
      ),
    ),
  ];
  const chips = [
    `${state.composer.panels.length} 个 Panel`,
    `来源：${sourceNames.join(" / ")}`,
    ...state.composer.panels.map(
      (panel) =>
        `${panel.id} · ${panel.semantic_view}/${authorSemanticLevel(panel.semantic_level)}`,
    ),
    composerPaperState(),
  ];
  target.innerHTML = chips
    .map(
      (value, index) =>
        `<span class="status-chip ${index === chips.length - 1 && state.composerProof?.paper_ready ? "paper-ready" : ""}">${escapeHtml(value)}</span>`,
    )
    .join("");
}

function bindComposerRecoveryActions() {
  $$("[data-composer-recovery]", $("#composer-empty")).forEach((button) => {
    button.onclick = () => {
      const action = button.dataset.composerRecovery;
      $("#composer-workflow").close();
      if (action === "start") void openStartCenter();
      else if (action === "import") $("#file-input").click();
      else if (action === "retry") {
        state.composer = null;
        void openComposer();
      }
    };
  });
}

function renderComposerEmpty(kind, detail = "") {
  const target = $("#composer-empty");
  const unavailable = kind === "empty";
  target.innerHTML = `<h3>${unavailable ? "当前画布没有可组合的模型" : "Figure Composer 初始化失败"}</h3><p>${escapeHtml(
    unavailable
      ? "请先打开本地示例或导入模型；现有空白 Graph IR 不会被伪造成论文 Panel。"
      : detail || "Composer 状态无法建立，请重试或重新打开模型。",
  )}</p><div class="inline-actions"><button data-composer-recovery="start">打开 Start Center</button><button data-composer-recovery="import">导入模型</button>${unavailable ? "" : '<button data-composer-recovery="retry" class="primary">重试初始化</button>'}</div>`;
  target.classList.remove("hidden");
  setComposerAvailability(false);
  renderComposerSummary();
  bindComposerRecoveryActions();
}

async function openComposer() {
  const dialog = $("#composer-workflow");
  openDialog(dialog, { trigger: document.activeElement });
  if (composerInitialization) {
    setComposerStatus("busy", "Figure Composer 正在初始化，请稍候…");
    toast("Figure Composer 已在初始化，不会重复创建 Panel。", "warning");
    return composerInitialization;
  }
  const restored =
    normalizeComposerState(state.composer) ||
    normalizeComposerState(state.projectMeta.figure_composer);
  if (restored) {
    state.composer = restored;
    state.projectMeta.figure_composer = restored;
    $("#composer-empty").classList.add("hidden");
    setComposerAvailability(true);
    syncComposerDialogControls();
    renderComposerPanels();
    setComposerStatus(
      "ready",
      `已恢复 ${restored.panels.length} 个 Panel 及其独立布局状态。`,
    );
    return restored;
  }
  setComposerStatus("busy", "正在准备 Panel A/B 与来源语义状态…");
  $("#composer-empty").classList.add("hidden");
  setComposerAvailability(false);
  if (!state.graph?.nodes?.length) {
    renderComposerEmpty("empty");
    setComposerStatus("error", "没有已载入模型，Composer 未创建空白 Panel。 ");
    return null;
  }
  setControlBusy("#composer-button", true);
  composerInitialization = Promise.resolve(null);
  try {
    state.composer = defaultComposer();
    state.composerProof = null;
    state.projectMeta.figure_composer = state.composer;
    syncComposerDialogControls();
    setComposerAvailability(true);
    renderComposerPanels();
    persistComposerState();
    setComposerStatus(
      "ready",
      "已创建 Panel A（Semantic blocks / block）和 Panel B（Operation evidence / operation）。",
    );
    toast("Figure Composer 已创建 A/B 两个 Panel。", "success");
    return state.composer;
  } catch (error) {
    state.composer = null;
    renderComposerEmpty("error", error.message);
    setComposerStatus("error", "Composer 初始化失败，可在此重试。 ");
    toast(`Figure Composer 初始化失败：${error.message}`, true);
    return null;
  } finally {
    setControlBusy("#composer-button", false);
    composerInitialization = null;
  }
}

function syncComposerDialogControls() {
  $("#composer-title").value = state.composer.title;
  $("#composer-page").value = state.composer.page_preset;
  $("#composer-arrangement").value = state.composer.arrangement;
}

function persistComposerState() {
  if (!state.composer) return;
  state.projectMeta.figure_composer = state.composer;
  scheduleAutosave();
}

function updateComposerControlsFromDialog() {
  if (!state.composer) return;
  state.composer.title = $("#composer-title").value;
  state.composer.page_preset = $("#composer-page").value;
  state.composer.arrangement = $("#composer-arrangement").value;
  state.composerProof = null;
  renderComposerSummary();
  persistComposerState();
}

function renderComposerPanels() {
  if (!state.composer) return;
  const semanticLevels = [
    ["model", "Framework"],
    ["stage", "Stage"],
    ["block", "Block"],
    ["layer", "Module"],
    ["operation", "Operation"],
  ];
  $("#composer-panels").innerHTML = state.composer.panels
    .map(
      (panel) =>
        `<article class="composer-panel" data-panel="${panel.id}" data-paper-ready="${Boolean(state.composerProof?.paper_ready)}"><strong>${panel.id}</strong><label>标题<input data-panel-field="title" value="${escapeAttr(panel.title)}"></label><label>层级<select data-panel-field="semantic_level">${semanticLevels.map(([value, label]) => `<option value="${value}" ${value === panel.semantic_level ? "selected" : ""}>${label}</option>`).join("")}</select></label><label>视图<select data-panel-field="semantic_view"><option value="paper" ${panel.semantic_view === "paper" ? "selected" : ""}>Paper</option><option value="faithful" ${panel.semantic_view === "faithful" ? "selected" : ""}>Faithful</option></select></label><button data-remove-panel ${state.composer.panels.length === 1 ? "disabled" : ""}>移除</button><span class="panel-state">来源：${escapeHtml(panel.source_reference?.graph_name || panel.graph?.name || "当前图")} · ${escapeHtml(panel.semantic_view)}/${escapeHtml(authorSemanticLevel(panel.semantic_level))} · ${escapeHtml(composerPaperState())}</span></article>`,
    )
    .join("");
  $$("[data-panel-field]", $("#composer-panels")).forEach(
    (input) =>
      (input.onchange = () => {
        const panel = state.composer.panels.find(
          (item) => item.id === input.closest("[data-panel]").dataset.panel,
        );
        panel[input.dataset.panelField] = input.value;
        panel.layout = {};
        state.composerProof = null;
        persistComposerState();
        renderComposerPanels();
      }),
  );
  $$("[data-remove-panel]", $("#composer-panels")).forEach(
    (button) =>
      (button.onclick = () => {
        const id = button.closest("[data-panel]").dataset.panel;
        state.composer.panels = state.composer.panels.filter(
          (panel) => panel.id !== id,
        );
        state.composer.connections = state.composer.connections.filter(
          (edge) => edge.source_panel !== id && edge.target_panel !== id,
        );
        state.composerProof = null;
        persistComposerState();
        renderComposerPanels();
      }),
  );
  renderComposerSummary();
}

async function previewComposer() {
  if (!state.composer?.panels?.length) {
    renderComposerEmpty("empty");
    return;
  }
  updateComposerControlsFromDialog();
  let generation = invalidateSourceBoundWork();
  setControlBusy("#composer-preview", true);
  setControlBusy("#composer-export", true);
  $("#composer-workflow").setAttribute("aria-busy", "true");
  setComposerStatus("busy", "正在仅重排发生变化的 Panel…");
  setBusy(true, "仅重排变更的 Panel…");
  try {
    const response = await api("/api/composer/compose", {
      composer: state.composer,
    });
    if (generation !== sourceGeneration) return;
    snapshot();
    state.composer = response.composer;
    state.composerProof = response.proof;
    persistComposerState();
    state.graph = response.graph;
    state.graphId = null;
    resetFigureForNewSource();
    generation = sourceGeneration;
    state.viewGraph = response.graph;
    state.layout = response.layout;
    state.semanticLevel = null;
    state.fixedLayout = true;
    // Composition replaces the semantic graph with a physical multi-panel
    // page; a stale operation-view viewport can leave every editable edge
    // outside the browser hit-test region.
    state.viewBox = null;
    recordWorkflowStep("multi-panel-composed");
    $("#composer-proof").innerHTML =
      [
        `${response.proof.width_mm} × ${response.proof.height_mm} mm`,
        `${response.proof.minimum_font_pt} pt 最小字号`,
        `${response.proof.minimum_line_width_pt} pt 最小线宽`,
        `${(response.proof.page_occupancy * 100).toFixed(1)}% 页面占用`,
      ]
        .map((value) => `<span class="proof-chip">${escapeHtml(value)}</span>`)
        .join("") +
      (response.proof.readability_explanation
        ? `<p class="error">${escapeHtml(response.proof.readability_explanation)}</p>`
        : "");
    renderComposerPanels();
    if (!(await refresh(false))) {
      if (generation !== sourceGeneration) return;
      throw new Error("组合状态已生成，但画布渲染失败。请保留 Panel 后重试。");
    }
    if (
      response.proof.paper_ready &&
      state.trial.activeSessionId &&
      !state.trial.paperReadyRecorded
    ) {
      await trialRecord("paper_ready", {
        elapsed_ms: Math.round(
          window.performance.now() - state.trial.startedAt,
        ),
        minimum_font_pt: Number(response.proof.minimum_font_pt),
        panel_count: response.composer.panels.length,
      });
      state.trial.paperReadyRecorded = true;
      persistTrialRuntimeState();
    }
    scheduleAutosave();
    setComposerStatus(
      "ready",
      response.proof.paper_ready
        ? `组合预览完成：${response.composer.panels.length} 个 Panel 已达到 paper-ready。`
        : "组合预览完成，但可读性 proof 仍需调整。",
    );
    toast(
      response.proof.paper_ready
        ? "Figure Composer 预览已达到 paper-ready。"
        : "预览已生成；请按 proof 提示继续调整。",
      response.proof.paper_ready ? "success" : "warning",
    );
  } catch (error) {
    if (generation === sourceGeneration) {
      setComposerStatus(
        "error",
        `预览失败：${error.message}。可保留当前 Panel 后重试。`,
      );
      toast(error.message, true);
    }
  } finally {
    setBusy(false);
    $("#composer-workflow").setAttribute("aria-busy", "false");
    setControlBusy("#composer-preview", false);
    setControlBusy("#composer-export", false);
  }
}

async function exportComposerBundle() {
  if (!state.composer?.panels?.length) {
    toast("没有可导出的 Composer Panel。", "warning");
    return;
  }
  setControlBusy("#composer-export", true);
  setControlBusy("#composer-preview", true);
  $("#composer-workflow").setAttribute("aria-busy", "true");
  setComposerStatus("busy", "正在打包完整 Figure、分 Panel TikZ 与矢量产物…");
  setBusy(true, "正在导出 Figure Composer 产物…");
  try {
    const response = await fetch("/api/composer/export", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        composer: state.composer,
        formats: ["svg", "pdf", "tikz", "png", "eps", "pptx"],
        tikz_panels: true,
      }),
    });
    if (!response.ok) {
      const body = await response.json();
      throw new Error(
        body.hint ? `${body.message} — ${body.hint}` : body.message,
      );
    }
    downloadBlob(
      await response.blob(),
      `${safeName(state.composer.title)}.zip`,
    );
    for (const format of ["svg", "pdf", "tikz", "png", "eps", "pptx"])
      await trialRecord("export", {
        format,
        succeeded: true,
        error_code: "none",
      });
    recordWorkflowStep("seven-format-bundle-exported");
    setComposerStatus("ready", "完整 Figure 与分 Panel TikZ 已打包导出。 ");
    toast("完整 Figure 与分 Panel TikZ 已打包导出。", "success");
  } catch (error) {
    for (const format of ["svg", "pdf", "tikz", "png", "eps", "pptx"])
      await trialRecord("export", {
        format,
        succeeded: false,
        error_code: "task_failed",
      });
    setComposerStatus(
      "error",
      `导出失败：${error.message}。请保留 Panel 状态后重试。`,
    );
    toast(`Figure Composer 导出失败：${error.message}`, true);
  } finally {
    setBusy(false);
    $("#composer-workflow").setAttribute("aria-busy", "false");
    setControlBusy("#composer-export", false);
    setControlBusy("#composer-preview", false);
  }
}

function sceneObjects() {
  return window.NNDVSceneRenderer.flattenObjects(state.scene);
}

function blankScene(name = "Untitled 3D Scene") {
  const axis = (id, position, dimensions, color) => ({
    id,
    kind: "cuboid",
    name: id.toUpperCase(),
    transform: { position, rotation: [0, 0, 0], scale: [1, 1, 1] },
    geometry: { primitive: "box", size: dimensions },
    material: {
      base_color: color,
      opacity: 1,
      metallic: 0,
      roughness: 1,
      unlit: true,
    },
    provenance: {
      kind: "author_annotation",
      graph_ir_ids: [],
      semantic_view_ids: [],
      figure_ir_ids: [],
      evidence: { source: "Scene Studio world-axis helper" },
      reason: "Explicit author-created orientation reference",
      author_annotation: true,
    },
    visible: true,
    locked: true,
    selected: false,
    parent_group_id: null,
    metadata: { helper: true },
    order: 0,
  });
  return {
    schema_version: "1.0",
    id: `scene-${Date.now().toString(36)}`,
    name,
    cameras: [
      {
        id: "camera-main",
        name: "Main camera",
        projection: "perspective",
        position: [10, 8, 12],
        target: [0, 0, 0],
        up: [0, 1, 0],
        rotation: [0, 0, 0],
        fov_y_deg: 45,
        ortho_height: 14,
        near: 0.01,
        far: 10000,
        aspect: 16 / 9,
        locked: false,
        metadata: {},
      },
    ],
    active_camera_id: "camera-main",
    lights: [
      {
        id: "light-key",
        name: "Key light",
        kind: "directional",
        position: [8, 10, 12],
        direction: [-0.45, -0.8, -0.35],
        color: "#ffffff",
        intensity: 1,
        visible: true,
        locked: false,
        metadata: {},
      },
    ],
    layers: [
      {
        id: "layer-world",
        name: "World helpers",
        objects: [
          axis("axis-x", [1.5, 0, 0], [3, 0.045, 0.045], "#ef4444"),
          axis("axis-y", [0, 1.5, 0], [0.045, 3, 0.045], "#22c55e"),
          axis("axis-z", [0, 0, 1.5], [0.045, 0.045, 3], "#3b82f6"),
        ],
        groups: [],
        visible: true,
        locked: false,
        order: 0,
        metadata: { role: "world-helpers" },
      },
      {
        id: "layer-model",
        name: "Model",
        objects: [],
        groups: [],
        visible: true,
        locked: false,
        order: 1,
        metadata: { role: "model" },
      },
    ],
    selection_ids: [],
    metadata: {
      generator: "NN_DaVinci Scene Studio",
      source: "author",
      auto_frame_on_open: true,
      units: "scene-unit",
      up_axis: "Y",
      background: "#111827",
      viewport: [1200, 800],
    },
    migrations: [],
  };
}

function localGraphScene(graph) {
  const objectBudget = 500,
    allNodes = graph?.nodes || [],
    allEdges = graph?.edges || [],
    scene = blankScene(`${graph?.name || "Graph"} 3D Scene`),
    layer = scene.layers.find((item) => item.id === "layer-model"),
    helperObjects = scene.layers
      .filter((item) => item !== layer)
      .reduce((count, item) => count + (item.objects || []).length, 0),
    modelObjectBudget = Math.max(0, objectBudget - helperObjects),
    nodes = allNodes.slice(0, modelObjectBudget),
    columns = Math.max(1, Math.ceil(Math.sqrt(nodes.length)));
  layer.objects = nodes.map((node, index) => {
    const column = index % columns,
      row = Math.floor(index / columns),
      stage = Number(
        node.attributes?.stage_index ?? node.attributes?.depth ?? 0,
      ),
      kind = String(node.op_type || node.kind || "operator").toLowerCase(),
      primitive = /attention|router|merge|add/.test(kind)
        ? "sphere"
        : /norm|activation|relu/.test(kind)
          ? "cylinder"
          : "box";
    return {
      id: `scene-${node.id}`,
      kind: "operation-block",
      name: node.name || node.id,
      transform: {
        position: [
          (column - (columns - 1) / 2) * 2.1,
          -row * 1.65,
          stage * 1.25,
        ],
        rotation: [0, 0, 0],
        scale: [1, 1, 1],
      },
      geometry: {
        primitive,
        size: primitive === "box" ? [1.6, 0.85, 0.7] : [1, 1, 1],
      },
      material: {
        base_color: /attention/.test(kind)
          ? "#8b5cf6"
          : /conv/.test(kind)
            ? "#2563eb"
            : /output/.test(kind)
              ? "#16a34a"
              : "#64748b",
        opacity: 1,
        metallic: 0,
        roughness: 0.86,
        unlit: false,
      },
      provenance: {
        kind: "graph_ir",
        source_id: node.id,
        graph_ir_ids: [node.id],
        semantic_view_ids: node.attributes?.semantic_entity_ids || [],
        figure_ir_ids: [],
        evidence: {
          source: "Graph IR node projected by deterministic browser fallback",
        },
        reason:
          "Backend Scene generator unavailable; no semantics were invented",
        author_annotation: false,
      },
      visible: true,
      locked: false,
      selected: false,
      parent_group_id: null,
      metadata: { op_type: node.op_type, browser_fallback: true },
      order: index,
    };
  });
  const positions = new Map(
    layer.objects.map((object) => [
      object.provenance.source_id,
      object.transform.position,
    ]),
  );
  const eligibleEdges = allEdges.filter(
      (edge) => positions.has(edge.source) && positions.has(edge.target),
    ),
    connectorBudget = Math.max(0, modelObjectBudget - layer.objects.length),
    connectors = eligibleEdges.slice(0, connectorBudget).map((edge, index) => {
      const source = positions.get(edge.source),
        target = positions.get(edge.target),
        delta = target.map((value, axis) => value - source[axis]),
        horizontal = Math.hypot(delta[0], delta[1]),
        distance = Math.max(0.05, Math.hypot(...delta));
      return {
        id: `scene-edge-${edge.id}`,
        kind: "cuboid",
        name: edge.name || `${edge.source} → ${edge.target}`,
        transform: {
          position: source.map((value, axis) => (value + target[axis]) / 2),
          rotation: [
            0,
            (-Math.atan2(delta[2], horizontal) * 180) / Math.PI,
            (Math.atan2(delta[1], delta[0]) * 180) / Math.PI,
          ],
          scale: [1, 1, 1],
        },
        geometry: { primitive: "box", size: [distance, 0.07, 0.07] },
        material: {
          base_color: "#94a3b8",
          opacity: 0.72,
          metallic: 0,
          roughness: 1,
          unlit: true,
        },
        provenance: {
          kind: "graph_ir",
          source_id: edge.id,
          graph_ir_ids: [edge.id, edge.source, edge.target],
          semantic_view_ids: [],
          figure_ir_ids: [],
          evidence: {
            source: "Graph IR edge projected between endpoint world positions",
          },
          reason: "Deterministic browser Scene connection",
          author_annotation: false,
        },
        visible: true,
        locked: false,
        selected: false,
        parent_group_id: null,
        metadata: { connector: true, browser_fallback: true },
        order: nodes.length + index,
      };
    });
  layer.objects.push(...connectors);
  scene.metadata.source = "graph-ir";
  scene.metadata.browser_fallback = true;
  scene.metadata.generation_summary = {
    source_nodes: allNodes.length,
    source_edges: allEdges.length,
    emitted_nodes: nodes.length,
    emitted_edges: connectors.length,
    emitted_model_objects: layer.objects.length,
    emitted_helper_objects: helperObjects,
    emitted_objects: layer.objects.length + helperObjects,
    object_budget: objectBudget,
  };
  scene.metadata.truncation = {
    applied:
      nodes.length < allNodes.length || connectors.length < allEdges.length,
    object_budget: objectBudget,
    omitted_nodes: Math.max(0, allNodes.length - nodes.length),
    omitted_edges: Math.max(0, allEdges.length - connectors.length),
    reason:
      "Deterministic browser fallback enforces a 500-object Scene budget; use the backend generator for semantic large-graph summarization.",
  };
  return scene;
}

async function requestGeneratedScene() {
  const lensNodeIds = (state.figureLensResult?.node_ids || []).slice(0, 250),
    focusIds = lensNodeIds.length
      ? lensNodeIds
      : [...state.sourceSelection].slice(0, 250),
    generationContext = {
      semantic_level: state.semanticLevel || "operation",
      semantic_view: state.semanticView || "faithful",
      focus_source: lensNodeIds.length
        ? "structure-lens"
        : focusIds.length
          ? "selection"
          : "full-graph",
      focus_ids: focusIds,
      ...(lensNodeIds.length
        ? {
            structure_lens: {
              operation: state.figureLensResult.operation,
              status: state.figureLensResult.status,
              node_ids: lensNodeIds,
              edge_ids: (state.figureLensResult.edge_ids || []).slice(0, 500),
              bounded: true,
            },
          }
        : {}),
    },
    annotateContext = (scene) => {
      scene.metadata = {
        ...(scene.metadata || {}),
        generation_context: generationContext,
        auto_frame_on_open: true,
      };
      return scene;
    };
  const payload = {
    graph: state.graph,
    graph_id: state.graphId,
    architecture: state.graph?.metadata?.architecture || null,
    level: state.semanticLevel || "operation",
    view: state.semanticView || "faithful",
    semantic_view: projectSemanticViewPayload(),
    figure_ir: state.figure || undefined,
    focus_ids: focusIds,
    focus_hops: 1,
    maximum_objects: 250,
  };
  const failures = [];
  for (const path of ["/api/scene/from-graph", "/api/scene/generate"]) {
    try {
      const response = await api(path, payload);
      const scene = response.scene || response.scene_ir || response;
      if (Array.isArray(scene.layers) && Array.isArray(scene.cameras))
        return annotateContext(scene);
      failures.push(`${path}: invalid response`);
    } catch (error) {
      failures.push(`${path}: ${error.message}`);
    }
  }
  const scene = localGraphScene(state.graph);
  scene.metadata.backend_failures = failures;
  toast(
    "Scene backend is unavailable; opened the deterministic local Scene IR projection.",
    "warning",
  );
  return annotateContext(scene);
}

async function enterSceneStudio({ rebuild = false, blank = false } = {}) {
  closeToolbarMenus();
  const generation = ++sceneRenderSequence;
  snapshot();
  workspaceMachine.setContext(state.workspaceMode, currentWorkspaceContext());
  setBusy(true, blank ? "Creating blank 3D Scene…" : "Building Scene IR…");
  try {
    if (blank) state.scene = blankScene();
    else if (!state.scene || rebuild || state.sceneNeedsRebuild)
      state.scene = await requestGeneratedScene();
    if (generation !== sceneRenderSequence) return;
    state.sceneNeedsRebuild = false;
    state.projectMeta.scene_ir = state.scene;
    state.workspaceMode = "scene";
    workspaceMachine.transition("scene", currentWorkspaceContext());
    state.sceneSelection = new Set(state.scene.selection_ids || []);
    applyWorkspaceMode();
    initializeSceneStudio();
    await refreshSceneStudio();
    toast("3D Scene Studio opened with an independent Scene IR.", "success");
  } catch (error) {
    if (generation !== sceneRenderSequence) return;
    state.workspaceMode = "graph";
    workspaceMachine.transition("graph");
    applyWorkspaceMode();
    toast(`Scene Studio could not open: ${error.message}`, "error");
  } finally {
    setBusy(false);
  }
}

async function switchWorkspace(name) {
  if (!["graph", "figure", "scene"].includes(name)) return;
  if (name === state.workspaceMode) return;
  workspaceMachine.setContext(state.workspaceMode, currentWorkspaceContext());
  if (name === "figure") return enterFigureStudio();
  if (name === "scene") return enterSceneStudio();
  if (state.workspaceMode === "figure") return leaveFigureStudio();
  state.workspaceMode = "graph";
  workspaceMachine.transition("graph", currentWorkspaceContext());
  applyWorkspaceMode();
  await refresh(!state.fixedLayout);
}

function currentWorkspaceContext() {
  if (state.workspaceMode === "scene")
    return {
      selection: [...state.sceneSelection],
      camera_id: state.scene?.active_camera_id || null,
      camera: sceneRenderer?.getCameraState() || null,
    };
  if (state.workspaceMode === "figure")
    return {
      selection: [...state.figureSelection],
      page: state.figureActivePage,
      layer: state.figureActiveLayer,
    };
  return {
    selection: [...state.sourceSelection],
    view_box: clone(state.viewBox),
    semantic_level: state.semanticLevel,
    semantic_view: state.semanticView,
  };
}

async function refreshSceneStudio() {
  if (!state.scene || state.workspaceMode !== "scene") return false;
  initializeSceneStudio();
  const started = window.performance.now();
  sceneRenderer.setScene(state.scene, state.scene.active_camera_id);
  sceneInteractions.setScene(state.scene);
  sceneInteractions.setSelection(state.sceneSelection, { notify: false });
  const activeCamera = state.scene.cameras?.find(
      (camera) => camera.id === state.scene.active_camera_id,
    ),
    validSavedCamera =
      activeCamera?.metadata?.user_saved_camera === true &&
      [activeCamera.position, activeCamera.target, activeCamera.up].every(
        (vector) =>
          Array.isArray(vector) &&
          vector.length === 3 &&
          vector.every((value) => Number.isFinite(Number(value))),
      );
  if (
    !autoFramedScenes.has(state.scene) &&
    state.scene.metadata?.auto_frame_on_open !== false &&
    !validSavedCamera
  ) {
    autoFramedScenes.add(state.scene);
    if (sceneRenderer.frameObjects())
      sceneInteractions.commitCamera("initial-auto-frame");
  }
  renderSceneTree();
  renderSceneCameras();
  renderSceneInspector();
  const elapsed = Math.round((window.performance.now() - started) * 100) / 100;
  $("#status").textContent =
    `${sceneObjects().length} Scene objects · ${state.scene.cameras?.length || 0} cameras · ${sceneRenderer.mode} · ${elapsed} ms`;
  scheduleAutosave();
  return true;
}

function initializeSceneStudio() {
  if (sceneRenderer) return;
  sceneRenderer = new window.NNDVSceneRenderer.SceneRenderer(
    $("#scene-webgl"),
    {
      fallbackElement: $("#scene-cpu-fallback"),
      labelElement: $("#scene-label-layer"),
    },
  );
  sceneInteractions = new window.NNDVSceneInteractions.SceneInteractions(
    sceneRenderer,
    {
      fallbackElement: $("#scene-cpu-fallback"),
      marqueeElement: $("#scene-marquee"),
      beforeChange: () => snapshot(),
      onChange: () => {
        state.projectMeta.scene_ir = state.scene;
        markProjectDirty("Scene changed");
        scheduleAutosave();
        renderSceneTree();
        renderSceneInspector();
      },
      onSelectionChange: (ids, provenance) => {
        state.sceneSelection = new Set(ids);
        state.scene.selection_ids = ids;
        state.sourceSelection = new Set(provenance.graph);
        state.selection = new Set(
          (state.viewGraph?.nodes || [])
            .filter(
              (node) =>
                provenance.graph.includes(node.id) ||
                (node.attributes?.source_nodes || []).some((id) =>
                  provenance.graph.includes(id),
                ),
            )
            .map((node) => node.id),
        );
        state.figureSelection = new Set(provenance.figure);
        renderSceneTree();
        renderSceneInspector();
        updateSceneContextToolbar();
      },
      onCameraChange: (camera) => {
        const stored = state.scene?.cameras?.find(
          (item) => item.id === camera?.id,
        );
        if (stored) Object.assign(stored, camera);
        scheduleAutosave();
        renderSceneCameras();
      },
    },
  );
  sceneRenderer.addEventListener("fallbackrequired", (event) =>
    renderCpuSceneFallback(event.detail.reason),
  );
  if (sceneRenderer.mode === "cpu-svg")
    void renderCpuSceneFallback("WebGL2 is unavailable");
  sceneRenderer.addEventListener("modechange", (event) => {
    $("#scene-render-mode").textContent =
      event.detail.mode === "webgl2"
        ? "WebGL2 · depth on"
        : "CPU SVG · vector fallback";
  });
  sceneInteractions.addEventListener("warning", (event) =>
    toast(event.detail.message, "warning"),
  );
  bindSceneControls();
}

function bindSceneControls() {
  $$("button[data-scene-tool]").forEach((button) => {
    button.onclick = () => {
      sceneInteractions.setTool(button.dataset.sceneTool);
      $$("button[data-scene-tool]").forEach((item) =>
        item.setAttribute(
          "aria-pressed",
          String(item.dataset.sceneTool === button.dataset.sceneTool),
        ),
      );
    };
  });
  $$("[data-scene-action]").forEach((button) => {
    button.onclick = () => handleSceneAction(button.dataset.sceneAction);
  });
  $$("[data-scene-overflow-action]").forEach((button) => {
    button.onclick = () => {
      handleSceneAction(button.dataset.sceneOverflowAction);
      button.closest("details")?.removeAttribute("open");
    };
  });
  $$("[data-scene-insert]").forEach((button) => {
    button.onclick = () => addScenePrimitive(button.dataset.sceneInsert);
  });
  $$("[data-scene-camera-action]").forEach((button) => {
    button.onclick = () =>
      handleSceneCameraAction(button.dataset.sceneCameraAction);
  });
  $("#scene-projection").onchange = (event) => {
    setSceneProjection(event.target.value);
  };
  $("#scene-view-preset").onchange = (event) => {
    setSceneViewPreset(event.target.value);
  };
  $$("[data-scene-projection-mirror]").forEach((select) => {
    select.onchange = () => setSceneProjection(select.value);
  });
  $$("[data-scene-view-mirror]").forEach((select) => {
    select.onchange = () => setSceneViewPreset(select.value);
  });
  $("#scene-frame").onclick = () => sceneInteractions.focus();
  $("#scene-camera-lock").onclick = () => {
    const locked = sceneInteractions.toggleCameraLock();
    $("#scene-camera-lock").setAttribute("aria-pressed", String(locked));
  };
  $("#scene-generate-from-graph").onclick = () =>
    enterSceneStudio({ rebuild: true });
  $("#scene-new-blank").onclick = () => enterSceneStudio({ blank: true });
  $("#scene-snap-enabled").onchange = () =>
    sceneInteractions.setSnapping(
      $("#scene-snap-enabled").checked,
      $("#scene-snap-grid").value,
    );
  $("#scene-snap-grid").onchange = () =>
    sceneInteractions.setSnapping(
      $("#scene-snap-enabled").checked,
      $("#scene-snap-grid").value,
    );
  $("#scene-opacity").onchange = (event) =>
    sceneInteractions.setOpacity(event.target.value);
  $("#scene-base-color").onchange = (event) =>
    setSceneMaterialColor(event.target.value);
  $("#scene-content-density").onchange = (event) => {
    snapshot();
    sceneRenderer.setContentDensity(event.target.value);
    state.scene.metadata = state.scene.metadata || {};
    state.scene.metadata.content_density = event.target.value;
    if (!sceneRenderer.getCameraState()?.locked && sceneRenderer.frameObjects())
      sceneInteractions.commitCamera("density-frame");
    state.projectMeta.scene_ir = state.scene;
    scheduleAutosave();
  };
  $("#scene-apply-depth").onclick = () =>
    sceneInteractions.setDepthSpacing($("#scene-depth-spacing").value);
  $$("[data-scene-transform]").forEach((input) => {
    input.onchange = () =>
      setSceneTransform(
        input.dataset.sceneTransform,
        input.dataset.axis,
        Number(input.value),
      );
  });
  $("#scene-object-visible").onchange = (event) =>
    setSceneObjectState("visible", event.target.checked);
  $("#scene-object-locked").onchange = (event) =>
    setSceneObjectState("locked", event.target.checked);
  $$("[data-scene-property-pin]").forEach((button) => {
    button.onclick = () => toggleScenePropertyPin(button);
  });
  try {
    const pins = new Set(
      JSON.parse(
        window.localStorage.getItem("nndv-scene-property-pins") || "[]",
      ),
    );
    $$("[data-scene-property-pin]").forEach((button) => {
      const active = pins.has(button.dataset.scenePropertyPin);
      button.setAttribute("aria-pressed", String(active));
      button.textContent = active ? "Pinned" : "Pin";
    });
  } catch {}
  $("#scene-tree-search").oninput = (event) => {
    sceneUiState.treeQuery = event.target.value;
    renderSceneTree();
  };
  $("#scene-tree-filter").onchange = (event) => {
    sceneUiState.treeFilter = event.target.value;
    renderSceneTree();
  };
  $("#scene-object-tree").onclick = (event) => {
    const action = event.target.closest("[data-scene-tree-action]");
    if (action) {
      event.stopPropagation();
      handleSceneTreeAction(
        action.dataset.sceneTreeObjectId,
        action.dataset.sceneTreeAction,
      );
      return;
    }
    const row = event.target.closest("[data-scene-object-id]");
    if (row)
      sceneInteractions.select(
        row.dataset.sceneObjectId,
        event.shiftKey || event.ctrlKey || event.metaKey,
      );
  };
  $("#scene-object-tree").addEventListener(
    "toggle",
    (event) => {
      const details = event.target.closest?.("[data-scene-group-id]");
      if (!details) return;
      const group = (state.scene?.layers || [])
        .flatMap((layer) => layer.groups || [])
        .find((item) => item.id === details.dataset.sceneGroupId);
      if (group) {
        group.metadata = group.metadata || {};
        group.metadata.collapsed = !details.open;
        scheduleAutosave();
      }
    },
    true,
  );
  $("#scene-camera-list").onclick = (event) => {
    const row = event.target.closest("[data-scene-camera-id]");
    if (!row) return;
    state.scene.active_camera_id = row.dataset.sceneCameraId;
    sceneRenderer.setCamera(
      state.scene.cameras.find(
        (camera) => camera.id === row.dataset.sceneCameraId,
      ),
    );
    renderSceneCameras();
    scheduleAutosave();
  };
  document.addEventListener(
    "keydown",
    (event) => {
      if (
        state.workspaceMode !== "scene" ||
        /INPUT|SELECT|TEXTAREA/.test(event.target.tagName)
      )
        return;
      const key = event.key.toLowerCase();
      if (["w", "e", "r"].includes(key))
        setSceneGizmoMode({ w: "move", e: "rotate", r: "scale" }[key]);
      else if (["x", "y", "z"].includes(key)) setSceneGizmoAxis(key);
      else if (event.key === "ArrowLeft" || event.key === "ArrowDown")
        nudgeSceneGizmo(-1, event.shiftKey);
      else if (event.key === "ArrowRight" || event.key === "ArrowUp")
        nudgeSceneGizmo(1, event.shiftKey);
      else if (key === "v") sceneInteractions.setTool("select");
      else if (key === "o") sceneInteractions.setTool("orbit");
      else if (key === "h") sceneInteractions.setTool("pan");
      else if (key === "f") sceneInteractions.focus();
      else if (key === "escape") sceneInteractions.select(null);
      else return;
      event.preventDefault();
      $$("button[data-scene-tool]").forEach((item) =>
        item.setAttribute(
          "aria-pressed",
          String(item.dataset.sceneTool === sceneInteractions.tool),
        ),
      );
    },
    true,
  );
  bindSceneGizmo();
}

function setSceneProjection(value) {
  snapshot();
  sceneRenderer.setProjection(value);
  const camera = sceneRenderer.getCameraState(),
    stored = state.scene.cameras.find((item) => item.id === camera.id);
  if (stored) Object.assign(stored, camera);
  $("#scene-projection").value = value;
  $$("[data-scene-projection-mirror]").forEach((select) => {
    select.value = value;
  });
  scheduleAutosave();
}

function setSceneViewPreset(value) {
  snapshot();
  sceneRenderer.setViewPreset(value);
  $("#scene-view-preset").value = value;
  $$("[data-scene-view-mirror]").forEach((select) => {
    select.value = value;
  });
  sceneInteractions.commitCamera("view-preset");
}

function renderSceneTree() {
  const root = $("#scene-object-tree");
  if (!state.scene?.layers?.length) {
    root.innerHTML = '<p class="empty">No Scene layers.</p>';
    return;
  }
  const query = sceneUiState.treeQuery.trim().toLowerCase(),
    filter = sceneUiState.treeFilter,
    matches = (object) => {
      const text =
          `${object.name || ""} ${object.kind || ""} ${object.geometry?.primitive || ""}`.toLowerCase(),
        filterMatch =
          filter === "all" ||
          (filter === "visible" && object.visible !== false) ||
          (filter === "hidden" && object.visible === false) ||
          (filter === "locked" && !!object.locked) ||
          (filter === "selected" && state.sceneSelection.has(object.id));
      return (!query || text.includes(query)) && filterMatch;
    };
  root.innerHTML = state.scene.layers
    .map((layer) => {
      const objects = layer.objects || [],
        groups = layer.groups || [],
        groupedIds = new Set(groups.flatMap((group) => group.object_ids || [])),
        groupRows = groups
          .map((group) => {
            const members = objects.filter(
              (object) =>
                (group.object_ids || []).includes(object.id) && matches(object),
            );
            if (!members.length && query) return "";
            const open = group.metadata?.collapsed !== true;
            return `<details class="scene-tree-group" data-scene-group-id="${escapeAttr(group.id)}" ${open ? "open" : ""}><summary><span>${escapeHtml(group.name || group.id)}</span><small>${members.length}/${group.object_ids?.length || 0}</small><small>${group.visible === false ? "hidden" : group.locked ? "locked" : "visible"}</small></summary>${members.map(sceneTreeObjectRow).join("") || '<p class="empty">No matching objects.</p>'}</details>`;
          })
          .join(""),
        ungrouped = objects
          .filter((object) => !groupedIds.has(object.id) && matches(object))
          .map(sceneTreeObjectRow)
          .join("");
      if (!groupRows && !ungrouped && query) return "";
      return `<section class="scene-layer-list"><h3>${escapeHtml(layer.name)} · ${objects.length}</h3>${groupRows}${ungrouped || (!groupRows ? '<p class="empty">No matching objects.</p>' : "")}</section>`;
    })
    .join("");
  if (!root.innerHTML)
    root.innerHTML = '<p class="empty">No matching Scene objects.</p>';
}

function sceneTreeObjectRow(object) {
  return `<div class="scene-tree-row" role="option" tabindex="0" data-scene-object-id="${escapeAttr(object.id)}" aria-selected="${state.sceneSelection.has(object.id)}"><span aria-hidden="true">${object.visible === false ? "◇" : object.locked ? "◆" : "◈"}</span><span title="${escapeAttr(object.name)}">${escapeHtml(object.name)}<small>${escapeHtml(object.geometry?.primitive || object.kind)}</small></span><span class="scene-tree-state"><button data-scene-tree-action="visible" data-scene-tree-object-id="${escapeAttr(object.id)}" aria-label="${object.visible === false ? "Show" : "Hide"} ${escapeAttr(object.name)}" title="Toggle visibility">${object.visible === false ? "○" : "●"}</button><button data-scene-tree-action="locked" data-scene-tree-object-id="${escapeAttr(object.id)}" aria-label="${object.locked ? "Unlock" : "Lock"} ${escapeAttr(object.name)}" title="Toggle lock">${object.locked ? "◆" : "◇"}</button></span></div>`;
}

function handleSceneTreeAction(id, property) {
  const object = sceneObjects().find((item) => item.id === id);
  if (!object || !["visible", "locked"].includes(property)) return;
  snapshot();
  object[property] =
    property === "visible" ? object.visible === false : !object.locked;
  sceneRenderer.setScene(state.scene, state.scene.active_camera_id);
  sceneRenderer.setSelection(state.sceneSelection);
  state.projectMeta.scene_ir = state.scene;
  renderSceneTree();
  renderSceneInspector();
  scheduleAutosave();
}

function renderSceneCameras() {
  $("#scene-camera-list").innerHTML = (state.scene?.cameras || [])
    .map(
      (camera) =>
        `<button class="scene-tree-row" data-scene-camera-id="${escapeAttr(
          camera.id,
        )}" aria-selected="${camera.id === state.scene.active_camera_id}"><span aria-hidden="true">${
          camera.locked ? "◆" : "◇"
        }</span><span>${escapeHtml(camera.name || camera.id)}</span><small>${escapeHtml(
          camera.projection,
        )}</small></button>`,
    )
    .join("");
  const camera = sceneRenderer?.getCameraState();
  if (camera) {
    $("#scene-projection").value = camera.projection;
    $$("[data-scene-projection-mirror]").forEach((select) => {
      select.value = camera.projection;
    });
    $("#scene-camera-lock").setAttribute("aria-pressed", String(camera.locked));
  }
}

function renderSceneInspector() {
  const selected = [...state.sceneSelection]
      .map((id) => sceneObjects().find((object) => object.id === id))
      .filter(Boolean),
    first = selected[0];
  $("#scene-selection-summary").textContent = selected.length
    ? `${selected.length} selected · ${first.name}${first.locked ? " · locked" : ""}`
    : "Select an object to inspect its world transform.";
  $$("[data-scene-transform]").forEach((input) => {
    const axis = "xyz".indexOf(input.dataset.axis),
      defaults =
        input.dataset.sceneTransform === "scale" ? [1, 1, 1] : [0, 0, 0],
      values = first?.transform?.[input.dataset.sceneTransform] || defaults;
    input.value = first ? Number(values[axis] ?? defaults[axis]) : "";
    input.disabled = !first || first.locked;
  });
  $("#scene-opacity").value = Number(first?.material?.opacity ?? 1);
  $("#scene-opacity").disabled = !first || first.locked;
  $("#scene-base-color").value = normalizeSceneColor(
    first?.material?.base_color || first?.material?.color || "#2563eb",
  );
  $("#scene-base-color").disabled = !first || first.locked;
  $("#scene-geometry-kind").value = first?.kind || "";
  $("#scene-geometry-primitive").value = first?.geometry?.primitive || "";
  const dimensions = first?.geometry?.dimensions || first?.geometry?.size;
  $("#scene-geometry-size").value = Array.isArray(dimensions)
    ? dimensions.join(" × ")
    : dimensions
      ? Object.values(dimensions).join(" × ")
      : "";
  $("#scene-semantic-role").value =
    first?.metadata?.architecture_role ||
    first?.metadata?.semantic_role ||
    first?.provenance?.kind ||
    "";
  $("#scene-content-density").value =
    state.scene?.metadata?.content_density || "paper";
  $("#scene-object-visible").checked = !!first && first.visible !== false;
  $("#scene-object-visible").disabled = !first;
  $("#scene-object-locked").checked = !!first?.locked;
  $("#scene-object-locked").disabled = !first;
  const provenance = first?.provenance;
  $("#scene-provenance").innerHTML = provenance
    ? [
        ["Kind", provenance.kind],
        ["Graph IR", (provenance.graph_ir_ids || []).join(", ") || "—"],
        [
          "Semantic View",
          (provenance.semantic_view_ids || []).join(", ") || "—",
        ],
        ["Figure IR", (provenance.figure_ir_ids || []).join(", ") || "—"],
        ["Reason", provenance.reason || "—"],
      ]
        .map(
          ([label, value]) =>
            `<li><strong>${escapeHtml(label)}</strong>${escapeHtml(value)}</li>`,
        )
        .join("")
    : "<li>No Scene object selected.</li>";
  $("#scene-transform-gizmo").dataset.selectionEmpty = String(!selected.length);
  updateSceneContextToolbar();
}

function normalizeSceneColor(value) {
  const match = String(value || "").match(/^#[0-9a-f]{6}$/i);
  return match ? match[0] : "#2563eb";
}

function setSceneMaterialColor(value) {
  const objects = sceneInteractions.selectedObjects();
  if (!objects.length) return;
  snapshot();
  objects.forEach((object) => {
    object.material = object.material || {};
    object.material.base_color = normalizeSceneColor(value);
  });
  sceneRenderer.setScene(state.scene, state.scene.active_camera_id);
  sceneRenderer.setSelection(state.sceneSelection);
  state.projectMeta.scene_ir = state.scene;
  scheduleAutosave();
}

function setSceneObjectState(property, value) {
  const objects = sceneInteractions.selectedObjects({ includeLocked: true });
  if (!objects.length) return;
  snapshot();
  objects.forEach((object) => {
    object[property] = !!value;
  });
  sceneRenderer.setScene(state.scene, state.scene.active_camera_id);
  sceneRenderer.setSelection(state.sceneSelection);
  state.projectMeta.scene_ir = state.scene;
  renderSceneTree();
  renderSceneInspector();
  scheduleAutosave();
}

function toggleScenePropertyPin(button) {
  const key = button.dataset.scenePropertyPin,
    active = button.getAttribute("aria-pressed") !== "true";
  button.setAttribute("aria-pressed", String(active));
  button.textContent = active ? "Pinned" : "Pin";
  try {
    const stored = JSON.parse(
      window.localStorage.getItem("nndv-scene-property-pins") || "[]",
    );
    const pins = new Set(Array.isArray(stored) ? stored : []);
    active ? pins.add(key) : pins.delete(key);
    window.localStorage.setItem(
      "nndv-scene-property-pins",
      JSON.stringify([...pins]),
    );
  } catch {}
}

function updateSceneContextToolbar() {
  const toolbar = $("#scene-selection-toolbar"),
    count = state.sceneSelection.size;
  toolbar.classList.toggle("hidden", !count || state.workspaceMode !== "scene");
  $("#scene-context-count").textContent = `${count} selected`;
  $$("[data-scene-action],[data-scene-overflow-action]", toolbar).forEach(
    (button) => {
      const action =
          button.dataset.sceneAction || button.dataset.sceneOverflowAction,
        needsThree = action.startsWith("distribute-"),
        needsTwo = action === "group" || action.startsWith("align-"),
        needsGroup = action === "ungroup",
        grouped = needsGroup
          ? sceneObjects().some(
              (object) =>
                state.sceneSelection.has(object.id) && object.parent_group_id,
            )
          : true,
        enabled =
          (!needsThree || count >= 3) && (!needsTwo || count >= 2) && grouped;
      button.disabled = !enabled;
      button.title = enabled
        ? ""
        : needsThree
          ? "Select at least three Scene objects"
          : needsTwo
            ? "Select at least two Scene objects"
            : "Select an object that belongs to a group";
    },
  );
}

function setSceneTransform(kind, axis, value) {
  const objects = sceneInteractions.selectedObjects();
  if (!objects.length || !Number.isFinite(value)) return;
  snapshot();
  const index = Math.max(0, "xyz".indexOf(axis));
  objects.forEach((object) => {
    object.transform = object.transform || {};
    const defaults = kind === "scale" ? [1, 1, 1] : [0, 0, 0];
    object.transform[kind] = (object.transform[kind] || defaults).map(Number);
    object.transform[kind][index] =
      kind === "position" ? sceneInteractions.snapValue(value) : value;
  });
  sceneRenderer.setScene(state.scene, state.scene.active_camera_id);
  sceneRenderer.setSelection(state.sceneSelection);
  renderSceneInspector();
  scheduleAutosave();
}

function handleSceneAction(action) {
  const actions = {
    group: () => sceneInteractions.group(),
    ungroup: () => sceneInteractions.ungroup(),
    lock: () => sceneInteractions.toggleLock(),
    hide: () => sceneInteractions.toggleHidden(),
    isolate: () => sceneInteractions.isolate(),
    focus: () => sceneInteractions.focus(),
    collapse: () => sceneInteractions.collapseOrExplode(false),
    explode: () => sceneInteractions.collapseOrExplode(true),
    "show-all": () => sceneInteractions.showAll(),
    "align-x": () => sceneInteractions.align("x"),
    "align-y": () => sceneInteractions.align("y"),
    "align-z": () => sceneInteractions.align("z"),
    "distribute-x": () => sceneInteractions.distribute("x"),
    "distribute-y": () => sceneInteractions.distribute("y"),
    "distribute-z": () => sceneInteractions.distribute("z"),
    "frame-scene": () => {
      if (sceneRenderer.getCameraState()?.locked)
        return toast("Camera is locked", "warning");
      snapshot();
      if (sceneRenderer.frameObjects())
        sceneInteractions.commitCamera("frame-scene");
    },
    "reset-camera": () => {
      if (sceneRenderer.getCameraState()?.locked)
        return toast("Camera is locked", "warning");
      snapshot();
      sceneRenderer.setViewPreset("isometric");
      if (!sceneRenderer.frameObjects()) return;
      $("#scene-view-preset").value = "isometric";
      $$("[data-scene-view-mirror]").forEach((select) => {
        select.value = "isometric";
      });
      sceneInteractions.commitCamera("reset-camera");
    },
    "toggle-camera-lock": () => {
      const locked = sceneInteractions.toggleCameraLock();
      $("#scene-camera-lock").setAttribute("aria-pressed", String(locked));
    },
  };
  if (!actions[action]) return;
  actions[action]();
  renderSceneInspector();
  renderSceneTree();
}

function bindSceneGizmo() {
  $$("[data-scene-gizmo-mode]").forEach((button) => {
    button.onclick = () => setSceneGizmoMode(button.dataset.sceneGizmoMode);
  });
  $("#scene-gizmo-space").onclick = () => {
    sceneUiState.gizmoSpace =
      sceneUiState.gizmoSpace === "world" ? "local" : "world";
    $("#scene-gizmo-space").textContent =
      sceneUiState.gizmoSpace === "world" ? "World" : "Local";
    $("#scene-gizmo-space").setAttribute(
      "aria-pressed",
      String(sceneUiState.gizmoSpace === "local"),
    );
  };
  $("#scene-gizmo-snap").onclick = () => {
    const enabled =
      $("#scene-gizmo-snap").getAttribute("aria-pressed") !== "true";
    $("#scene-gizmo-snap").setAttribute("aria-pressed", String(enabled));
    $("#scene-snap-enabled").checked = enabled;
    sceneInteractions.setSnapping(enabled, $("#scene-snap-grid").value);
  };
  $$("[data-scene-gizmo-axis]").forEach((button) => {
    button.onpointerdown = (event) => beginSceneGizmoDrag(event, button);
  });
  updateSceneGizmoControls();
}

function setSceneGizmoMode(mode) {
  if (!["move", "rotate", "scale"].includes(mode)) return;
  sceneUiState.gizmoMode = mode;
  updateSceneGizmoControls();
}

function setSceneGizmoAxis(axis) {
  if (!"xyz".includes(axis)) return;
  sceneUiState.gizmoAxis = axis;
  updateSceneGizmoControls();
}

function updateSceneGizmoControls() {
  $$("[data-scene-gizmo-mode]").forEach((button) =>
    button.setAttribute(
      "aria-pressed",
      String(button.dataset.sceneGizmoMode === sceneUiState.gizmoMode),
    ),
  );
  $$("[data-scene-gizmo-axis]").forEach((button) => {
    button.dataset.active = String(
      button.dataset.sceneGizmoAxis === sceneUiState.gizmoAxis,
    );
  });
}

function sceneLocalAxis(rotation = [0, 0, 0], axis = "x") {
  const radians = rotation.map((value) => (Number(value) * Math.PI) / 180),
    [rx, ry, rz] = radians,
    source = {
      x: [1, 0, 0],
      y: [0, 1, 0],
      z: [0, 0, 1],
    }[axis],
    afterX = [
      source[0],
      source[1] * Math.cos(rx) - source[2] * Math.sin(rx),
      source[1] * Math.sin(rx) + source[2] * Math.cos(rx),
    ],
    afterY = [
      afterX[0] * Math.cos(ry) + afterX[2] * Math.sin(ry),
      afterX[1],
      -afterX[0] * Math.sin(ry) + afterX[2] * Math.cos(ry),
    ];
  return [
    afterY[0] * Math.cos(rz) - afterY[1] * Math.sin(rz),
    afterY[0] * Math.sin(rz) + afterY[1] * Math.cos(rz),
    afterY[2],
  ];
}

function applySceneGizmoDelta(objects, originals, delta, fine = false) {
  const axis = sceneUiState.gizmoAxis,
    index = "xyz".indexOf(axis),
    snap = sceneInteractions.snap.enabled && !fine;
  objects.forEach((object, objectIndex) => {
    const original = originals[objectIndex],
      transform = (object.transform = object.transform || {});
    if (sceneUiState.gizmoMode === "move") {
      const vector =
        sceneUiState.gizmoSpace === "local"
          ? sceneLocalAxis(original.rotation, axis)
          : [0, 1, 2].map((item) => (item === index ? 1 : 0));
      transform.position = original.position.map((value, item) => {
        const next = value + vector[item] * delta;
        return snap ? sceneInteractions.snapValue(next) : next;
      });
    } else if (sceneUiState.gizmoMode === "rotate") {
      transform.rotation = [...original.rotation];
      transform.rotation[index] = original.rotation[index] + delta * 15;
    } else {
      transform.scale = [...original.scale];
      transform.scale[index] = Math.max(
        0.001,
        original.scale[index] * (1 + delta * 0.15),
      );
    }
  });
  sceneRenderer.setScene(state.scene, state.scene.active_camera_id);
  sceneRenderer.setSelection(state.sceneSelection);
}

function beginSceneGizmoDrag(event, button) {
  const objects = sceneInteractions.selectedObjects();
  if (!objects.length) return;
  event.preventDefault();
  setSceneGizmoAxis(button.dataset.sceneGizmoAxis);
  snapshot();
  const startX = event.clientX,
    startY = event.clientY,
    originals = objects.map((object) => ({
      position: [...(object.transform?.position || [0, 0, 0])].map(Number),
      rotation: [...(object.transform?.rotation || [0, 0, 0])].map(Number),
      scale: [...(object.transform?.scale || [1, 1, 1])].map(Number),
    })),
    move = (moveEvent) => {
      const delta =
        (moveEvent.clientX - startX - (moveEvent.clientY - startY)) * 0.015;
      applySceneGizmoDelta(objects, originals, delta, moveEvent.shiftKey);
    },
    up = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      state.projectMeta.scene_ir = state.scene;
      markProjectDirty("Scene transform changed");
      renderSceneTree();
      renderSceneInspector();
      scheduleAutosave();
    };
  window.addEventListener("pointermove", move);
  window.addEventListener("pointerup", up, { once: true });
}

function nudgeSceneGizmo(direction, fine = false) {
  const objects = sceneInteractions.selectedObjects();
  if (!objects.length) return;
  snapshot();
  const originals = objects.map((object) => ({
      position: [...(object.transform?.position || [0, 0, 0])].map(Number),
      rotation: [...(object.transform?.rotation || [0, 0, 0])].map(Number),
      scale: [...(object.transform?.scale || [1, 1, 1])].map(Number),
    })),
    base =
      sceneUiState.gizmoMode === "move"
        ? Number($("#scene-snap-grid").value) || 0.25
        : 1 / 3;
  applySceneGizmoDelta(
    objects,
    originals,
    direction * base * (fine ? 0.2 : 1),
    fine,
  );
  state.projectMeta.scene_ir = state.scene;
  markProjectDirty("Scene transform changed");
  renderSceneInspector();
  scheduleAutosave();
}

function addScenePrimitive(kind) {
  if (!state.scene) return;
  snapshot();
  let layer = state.scene.layers.find(
    (item) => item.metadata?.role === "model" && !item.locked,
  );
  if (!layer) {
    layer = {
      id: `layer-${Date.now().toString(36)}`,
      name: "Author objects",
      objects: [],
      groups: [],
      visible: true,
      locked: false,
      order: state.scene.layers.length,
      metadata: { role: "author" },
    };
    state.scene.layers.push(layer);
  }
  const id = `object-${Date.now().toString(36)}`,
    index = layer.objects.length,
    primitive = kind === "tensor" ? "box" : kind;
  const object = {
    id,
    kind: kind === "tensor" ? "tensor-volume" : "operation-block",
    name: `${kind[0].toUpperCase()}${kind.slice(1)} ${index + 1}`,
    transform: {
      position: [(index % 4) * 2 - 3, -Math.floor(index / 4) * 1.7, 0],
      rotation: [0, 0, 0],
      scale: [1, 1, 1],
    },
    geometry: {
      primitive,
      size: kind === "tensor" ? [2.2, 1.2, 0.65] : [1, 1, 1],
      tensor_shape: kind === "tensor" ? ["B", "T", "D"] : undefined,
    },
    material: {
      base_color: kind === "tensor" ? "#7c3aed" : "#2563eb",
      opacity: 1,
      metallic: 0,
      roughness: 0.82,
      unlit: false,
    },
    provenance: {
      kind: "author_annotation",
      source_id: "",
      graph_ir_ids: [],
      semantic_view_ids: [],
      figure_ir_ids: [],
      evidence: { source: "Created explicitly in Scene Studio" },
      reason: "Author-created Scene object",
      author_annotation: true,
    },
    visible: true,
    locked: false,
    selected: true,
    parent_group_id: null,
    metadata: {},
    order: index,
  };
  layer.objects.push(object);
  state.sceneSelection = new Set([id]);
  state.scene.selection_ids = [id];
  sceneRenderer.setScene(state.scene, state.scene.active_camera_id);
  sceneInteractions.setScene(state.scene);
  sceneInteractions.setSelection([id]);
  renderSceneTree();
  renderSceneInspector();
  scheduleAutosave();
}

function handleSceneCameraAction(action) {
  if (!state.scene) return;
  snapshot();
  const current =
    state.scene.cameras.find(
      (camera) => camera.id === state.scene.active_camera_id,
    ) || state.scene.cameras[0];
  if (!current) return;
  if (action === "add" || action === "duplicate") {
    const camera = clone(current);
    camera.id = `camera-${Date.now().toString(36)}`;
    camera.name =
      action === "add"
        ? `Camera ${state.scene.cameras.length + 1}`
        : `${current.name} copy`;
    camera.locked = false;
    if (action === "add") {
      camera.position = [8, 6, 10];
      camera.target = [0, 0, 0];
    }
    state.scene.cameras.push(camera);
    state.scene.active_camera_id = camera.id;
    sceneRenderer.setCamera(camera);
    renderSceneCameras();
    scheduleAutosave();
  }
}

function syncSceneSelectionFrom2D(kind, ids) {
  if (!state.scene || !sceneInteractions) return;
  const wanted = new Set(ids || []),
    key =
      kind === "figure"
        ? "figure_ir_ids"
        : kind === "semantic"
          ? "semantic_view_ids"
          : "graph_ir_ids";
  const matches = sceneObjects()
    .filter((object) =>
      (object.provenance?.[key] || []).some((id) => wanted.has(id)),
    )
    .map((object) => object.id);
  state.sceneSelection = new Set(matches);
  state.scene.selection_ids = matches;
  sceneInteractions.setSelection(matches, { notify: false });
}

async function renderCpuSceneFallback(reason = "WebGL2 unavailable") {
  if (!state.scene) return;
  state.sceneFallbackReason = reason;
  let svg = null,
    detail = reason;
  for (const path of ["/api/scene/project"]) {
    try {
      const response = await fetch(path, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Accept: "image/svg+xml, application/json",
        },
        body: JSON.stringify({
          scene: state.scene,
          camera_id: state.scene.active_camera_id,
          format: "svg",
          projection_options: {
            width_mm: 178,
            height_mm: 118,
          },
        }),
      });
      if (!response.ok)
        throw new Error(`${response.status} ${response.statusText}`);
      const type = response.headers.get("content-type") || "";
      if (type.includes("svg")) svg = await response.text();
      else {
        const body = await response.json();
        svg = body.svg || projectionToSvg(body.projection || body);
      }
      if (svg) {
        detail = `${reason}; server CPU vector projector active`;
        break;
      }
    } catch (error) {
      detail = `${reason}; ${path} unavailable (${error.message})`;
    }
  }
  if (!svg) {
    svg = localCpuSceneSvg(state.scene);
    detail = `${detail}; deterministic browser CPU projection active`;
  }
  sceneRenderer.showCpuFallback(svg, detail);
  $("#scene-fallback-notice").textContent = `CPU SVG fallback: ${detail}`;
  $("#scene-fallback-notice").classList.remove("hidden");
  $("#scene-render-mode").textContent = "CPU SVG · vector fallback";
}

function projectionToSvg(projection) {
  const width = Number(projection.width_mm || 178),
    height = Number(projection.height_mm || 118),
    primitives = projection.primitives || [];
  const elements = primitives
    .map((primitive) => {
      const points = (primitive.points || [])
        .map(
          (point) =>
            `${Number(point[0]).toFixed(3)},${Number(point[1]).toFixed(3)}`,
        )
        .join(" ");
      const fill = primitive.style?.fill || "#94a3b8",
        stroke = primitive.style?.stroke || "#334155",
        id = escapeAttr(primitive.object_id || "");
      if (primitive.kind === "text")
        return `<text data-scene-object-id="${id}" x="${Number(primitive.points?.[0]?.[0] || 0)}" y="${Number(primitive.points?.[0]?.[1] || 0)}" fill="${escapeAttr(fill)}">${escapeHtml(primitive.text || "")}</text>`;
      return `<polygon data-scene-object-id="${id}" points="${points}" fill="${escapeAttr(fill)}" stroke="${escapeAttr(stroke)}"/>`;
    })
    .join("");
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${width} ${height}" width="${width}mm" height="${height}mm" role="img" aria-label="CPU projected Scene">${elements}</svg>`;
}

function localCpuSceneSvg(scene) {
  const width = 960,
    height = 640,
    scale = 32,
    objects = window.NNDVSceneRenderer.flattenObjects(scene)
      .filter((object) => object.visible !== false)
      .map((object) => {
        const [x, y, z] = object.transform?.position || [0, 0, 0];
        return {
          object,
          x: width / 2 + (x - z * 0.62) * scale,
          y: height / 2 + (-y + z * 0.38) * scale,
          depth: x + y + z,
        };
      })
      .sort((a, b) => a.depth - b.depth);
  const shapes = objects
    .map(({ object, x, y }) => {
      const dimensions = object.geometry?.dimensions || [1, 1, 1],
        objectWidth = Math.max(5, Number(dimensions[0] || 1) * scale),
        objectHeight = Math.max(5, Number(dimensions[1] || 1) * scale),
        fill = object.material?.base_color || "#64748b";
      return `<g data-scene-object-id="${escapeAttr(object.id)}" opacity="${Number(
        object.material?.opacity ?? 1,
      )}"><rect x="${x - objectWidth / 2}" y="${y - objectHeight / 2}" width="${objectWidth}" height="${objectHeight}" rx="4" fill="${escapeAttr(fill)}" stroke="#e2e8f0"/><text x="${x}" y="${y + 3}" text-anchor="middle" font-size="10" fill="#fff">${escapeHtml(object.name)}</text></g>`;
    })
    .join("");
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${width} ${height}" role="img" aria-label="Deterministic CPU Scene projection"><rect width="100%" height="100%" fill="#111827"/>${shapes}</svg>`;
}

async function performSceneExport(format, { signal } = {}) {
  if (signal?.aborted) throw new window.DOMException("Cancelled", "AbortError");
  if (format === "json") {
    downloadBlob(
      new Blob([JSON.stringify(state.scene, null, 2)], {
        type: "application/json",
      }),
      `${safeName(state.scene.name)}.scene.json`,
    );
    return;
  }
  const payload = {
    scene: state.scene,
    camera_id: state.scene.active_camera_id,
    format,
    projection_options: { width_mm: 178, height_mm: 118 },
  };
  let lastError = null;
  for (const path of [`/api/scene/export/${format}`]) {
    try {
      const response = await fetch(path, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
        signal,
      });
      if (!response.ok)
        throw new Error(`${response.status} ${response.statusText}`);
      const type = response.headers.get("content-type") || "";
      // `model/gltf+json` is the glTF artifact itself, not the JSON envelope
      // used by asynchronous exporters. Only plain API JSON should be parsed
      // as an envelope here.
      if (!type.includes("application/json")) {
        downloadBlob(
          await response.blob(),
          `${safeName(state.scene.name)}.${format === "tikz" ? "tex" : format}`,
        );
        return;
      }
      const body = await response.json();
      if (body.artifact_url) {
        const artifact = await fetch(body.artifact_url, { signal });
        if (!artifact.ok) throw new Error("Scene artifact download failed");
        downloadBlob(
          await artifact.blob(),
          body.filename || `${safeName(state.scene.name)}.${format}`,
        );
        return;
      }
      if (body.svg && format === "svg") {
        downloadBlob(
          new Blob([body.svg], { type: "image/svg+xml" }),
          `${safeName(state.scene.name)}.svg`,
        );
        return;
      }
      throw new Error("Scene export response did not include an artifact");
    } catch (error) {
      if (signal?.aborted) throw error;
      lastError = error;
    }
  }
  if (signal?.aborted) throw new window.DOMException("Cancelled", "AbortError");
  if (format === "svg") {
    downloadBlob(
      new Blob([localCpuSceneSvg(state.scene)], { type: "image/svg+xml" }),
      `${safeName(state.scene.name)}.svg`,
    );
    toast(
      "Backend export unavailable; saved explicit CPU SVG projection.",
      "warning",
    );
    return;
  }
  throw new Error(
    `${lastError?.message || "Scene export unavailable"}. Retry after the Scene export backend is ready.`,
  );
}

function renderSceneBatchStatus(record, completed = []) {
  const records = new Map(completed.map((item) => [item.format, item]));
  if (record) records.set(record.format, record);
  $("#scene-batch-status").innerHTML = [...records.values()]
    .map(
      (item) =>
        `<li data-scene-batch-result="${escapeAttr(item.status)}"><strong>${escapeHtml(
          item.format.toUpperCase(),
        )}</strong><span>${escapeHtml(
          item.status === "success"
            ? "完成"
            : item.status === "failed"
              ? `失败：${item.error}`
              : item.status === "cancelled"
                ? "已取消"
                : "正在导出…",
        )}</span></li>`,
    )
    .join("");
}

function openSceneBatchDialog() {
  closeToolbarMenus();
  if (state.workspaceMode !== "scene" || !sceneObjects().length) {
    toast("请先打开包含对象的 Scene。", "warning");
    return;
  }
  $("#scene-batch-status").innerHTML =
    '<li class="empty">选择格式后开始导出。</li>';
  openDialog($("#scene-batch-dialog"), { trigger: $("#scene-batch-export") });
}

async function startSceneBatchExport() {
  const formats = $$(
    'input[type="checkbox"]:checked',
    $("#scene-batch-formats"),
  ).map((input) => input.value);
  if (!formats.length) {
    toast("至少选择一种 Scene 导出格式。", "warning");
    return;
  }
  sceneBatchController?.abort();
  sceneBatchController = new window.AbortController();
  $("#scene-batch-start").disabled = true;
  $("#scene-batch-cancel").disabled = false;
  workspaceMachine.setAction("scene-batch", "busy", {
    message: `Batch exporting ${formats.length} Scene formats…`,
  });
  try {
    const result = await window.NNDVSceneBatch.run({
      formats,
      signal: sceneBatchController.signal,
      task: (format, options) => performSceneExport(format, options),
      onProgress: renderSceneBatchStatus,
    });
    const message = `${result.successes.length} 完成 · ${result.failures.length} 失败 · ${result.cancelled.length} 取消`;
    workspaceMachine.setAction(
      "scene-batch",
      result.failures.length ? "error" : "success",
      { message },
    );
    toast(message, result.failures.length ? "warning" : "success");
  } finally {
    sceneBatchController = null;
    $("#scene-batch-start").disabled = false;
    $("#scene-batch-cancel").disabled = true;
  }
}

function initializeCommandRegistry() {
  if (commandRegistry) return commandRegistry;
  commandRegistry = new window.NNDVCommands.CommandRegistry({
    context: () => ({
      workspace: state.workspaceMode,
      graph: state.graph,
      figure: state.figure,
      scene: state.scene,
      graphSelection: [...state.selection],
      figureSelection: [...state.figureSelection],
      sceneSelection: [...state.sceneSelection],
    }),
    onAnnounce: toast,
  });
  const graphRequired = () =>
      state.graph?.nodes?.length
        ? true
        : "Open or import a graph before running this command",
    sceneRequired = () =>
      state.workspaceMode === "scene" && state.scene
        ? true
        : "This command is available in Scene Studio",
    sceneSelectionRequired = () =>
      state.workspaceMode === "scene" && state.sceneSelection.size
        ? true
        : "Select at least one Scene object",
    sceneTwoSelectionRequired = () =>
      state.workspaceMode === "scene" && state.sceneSelection.size >= 2
        ? true
        : "Select at least two Scene objects",
    sceneThreeSelectionRequired = () =>
      state.workspaceMode === "scene" && state.sceneSelection.size >= 3
        ? true
        : "Select at least three Scene objects",
    sceneGroupedSelectionRequired = () => {
      if (state.workspaceMode !== "scene" || !state.sceneSelection.size)
        return "Select an object that belongs to a Scene group";
      return sceneObjects().some(
        (object) =>
          state.sceneSelection.has(object.id) && object.parent_group_id,
      )
        ? true
        : "The current selection does not belong to a Scene group";
    };
  commandRegistry.registerAll([
    {
      id: "app.commands",
      label: "Commands and global search",
      category: "Application",
      shortcut: "Ctrl+K",
      keywords: ["palette", "search"],
      run: openCommandPalette,
    },
    {
      id: "app.start",
      label: "Open Start Center",
      category: "Application",
      description: "Blank 2D/3D, import, templates, and recovery",
      run: openStartCenter,
    },
    {
      id: "project.blank-2d",
      label: "Create blank 2D graph",
      category: "Project",
      shortcut: "Ctrl+Alt+2",
      run: () => $("#new-button").click(),
    },
    {
      id: "project.blank-3d",
      label: "Create blank 3D Scene",
      category: "Project",
      shortcut: "Ctrl+Alt+3",
      run: () => enterSceneStudio({ blank: true }),
    },
    {
      id: "project.import",
      label: "Import model or project",
      category: "Project",
      run: () => $("#file-input").click(),
    },
    {
      id: "project.save",
      label: "Save project",
      category: "Project",
      shortcut: "Ctrl+S",
      run: () => exportFormat("project"),
    },
    {
      id: "workspace.graph",
      label: "Switch to Graph workspace",
      category: "Workspace",
      shortcut: "Ctrl+1",
      run: () => switchWorkspace("graph"),
    },
    {
      id: "workspace.figure",
      label: "Switch to Figure workspace",
      category: "Workspace",
      shortcut: "Ctrl+2",
      available: graphRequired,
      run: () => switchWorkspace("figure"),
    },
    {
      id: "workspace.scene",
      label: "Switch to Scene workspace",
      category: "Workspace",
      shortcut: "Ctrl+3",
      run: () => switchWorkspace("scene"),
    },
    {
      id: "graph.analyze",
      label: "Analyze current model",
      category: "Graph",
      available: graphRequired,
      run: analyze,
    },
    {
      id: "figure.generate",
      label: "Generate paper figure",
      category: "Figure",
      available: graphRequired,
      run: generatePaperDraft,
    },
    {
      id: "figure.composer",
      label: "Open Figure Composer",
      category: "Figure",
      available: graphRequired,
      run: openComposer,
    },
    {
      id: "scene.generate",
      label: "Regenerate Scene from Graph IR",
      category: "Scene",
      available: graphRequired,
      run: () => enterSceneStudio({ rebuild: true }),
    },
    {
      id: "scene.frame",
      label: "Frame Scene selection",
      category: "Scene",
      shortcut: "F",
      available: sceneSelectionRequired,
      run: () => sceneInteractions.focus(),
    },
    {
      id: "scene.frame-all",
      label: "Frame complete Scene",
      category: "Scene",
      available: sceneRequired,
      run: () => handleSceneAction("frame-scene"),
    },
    {
      id: "scene.reset-camera",
      label: "Reset Scene camera",
      category: "Scene",
      available: sceneRequired,
      run: () => handleSceneAction("reset-camera"),
    },
    {
      id: "scene.group",
      label: "Group Scene selection",
      category: "Scene",
      shortcut: "Ctrl+G",
      available: sceneTwoSelectionRequired,
      run: () => sceneInteractions.group(),
    },
    {
      id: "scene.ungroup",
      label: "Ungroup Scene selection",
      category: "Scene",
      shortcut: "Ctrl+Shift+G",
      available: sceneGroupedSelectionRequired,
      run: () => handleSceneAction("ungroup"),
    },
    {
      id: "scene.lock",
      label: "Lock or unlock Scene selection",
      category: "Scene",
      available: sceneSelectionRequired,
      run: () => handleSceneAction("lock"),
    },
    {
      id: "scene.hide",
      label: "Hide Scene selection",
      category: "Scene",
      available: sceneSelectionRequired,
      run: () => handleSceneAction("hide"),
    },
    {
      id: "scene.isolate",
      label: "Isolate Scene selection",
      category: "Scene",
      available: sceneSelectionRequired,
      run: () => sceneInteractions.isolate(),
    },
    {
      id: "scene.show-all",
      label: "Show all Scene objects",
      category: "Scene",
      available: sceneRequired,
      run: () => handleSceneAction("show-all"),
    },
    {
      id: "scene.collapse",
      label: "Collapse Scene selection",
      category: "Scene",
      available: sceneSelectionRequired,
      run: () => handleSceneAction("collapse"),
    },
    {
      id: "scene.explode",
      label: "Explode Scene selection",
      category: "Scene",
      available: sceneSelectionRequired,
      run: () => handleSceneAction("explode"),
    },
    ...["x", "y", "z"].map((axis) => ({
      id: `scene.align-${axis}`,
      label: `Align Scene selection on ${axis.toUpperCase()}`,
      category: "Scene",
      available: sceneTwoSelectionRequired,
      run: () => handleSceneAction(`align-${axis}`),
    })),
    ...["x", "y", "z"].map((axis) => ({
      id: `scene.distribute-${axis}`,
      label: `Distribute Scene selection on ${axis.toUpperCase()}`,
      category: "Scene",
      available: sceneThreeSelectionRequired,
      run: () => handleSceneAction(`distribute-${axis}`),
    })),
    ...[
      ["move", "W"],
      ["rotate", "E"],
      ["scale", "R"],
    ].map(([mode, shortcut]) => ({
      id: `scene.gizmo-${mode}`,
      label: `Use Scene ${mode} gizmo`,
      category: "Scene",
      shortcut,
      available: sceneRequired,
      run: () => setSceneGizmoMode(mode),
    })),
    {
      id: "scene.projection",
      label: "Toggle orthographic / perspective",
      category: "Scene",
      available: sceneRequired,
      run: () => {
        const next =
          sceneRenderer.getCameraState()?.projection === "orthographic"
            ? "perspective"
            : "orthographic";
        sceneRenderer.setProjection(next);
        $("#scene-projection").value = next;
        sceneInteractions.commitCamera("projection");
      },
    },
    {
      id: "view.fit",
      label: "Fit active workspace",
      category: "View",
      run: () =>
        state.workspaceMode === "scene"
          ? sceneRenderer.frameObjects()
          : applyViewBox(true),
    },
    {
      id: "app.issues",
      label: "Open issues",
      category: "Application",
      run: () => openDrawer("issue-center"),
    },
    {
      id: "app.shortcuts",
      label: "Show keyboard shortcuts",
      category: "Application",
      run: () =>
        openDialog($("#shortcuts-dialog"), {
          trigger: document.activeElement,
        }),
    },
    {
      id: "app.trial",
      label: "Open Researcher Trial Mode",
      category: "Application",
      run: openTrialMode,
    },
  ]);
  commandRegistry.bind({
    dialog: $("#command-palette"),
    input: $("#command-search"),
    results: $("#command-results"),
    searchProvider: (query) => {
      const normalized = query.toLowerCase();
      const graphResults = (state.graph?.nodes || [])
        .filter((node) =>
          `${node.name} ${node.op_type} ${node.path}`
            .toLowerCase()
            .includes(normalized),
        )
        .slice(0, 12)
        .map((node) => ({
          label: `Locate graph node: ${node.name}`,
          description: node.op_type,
          run: () => locateSourceNode(node.id),
        }));
      const sceneResults = sceneObjects()
        .filter((object) =>
          `${object.name} ${object.kind}`.toLowerCase().includes(normalized),
        )
        .slice(0, 12)
        .map((object) => ({
          label: `Select Scene object: ${object.name}`,
          description: object.kind,
          run: async () => {
            await switchWorkspace("scene");
            sceneInteractions.select(object.id);
            sceneInteractions.focus();
          },
        }));
      return graphResults.concat(sceneResults);
    },
  });
  return commandRegistry;
}

function openCommandPalette() {
  initializeCommandRegistry().open(document.activeElement);
}

function renderCommandResults(query) {
  initializeCommandRegistry().render(query);
}

function openDrawer(id) {
  openDrawerSurface($(`#${id}`), document.activeElement);
  if (id === "issue-center") updateIssues();
}

function updateIssues() {
  const issues = [];
  const detections = state.semanticData?.detections || [];
  detections
    .filter((item) => item.unknown)
    .forEach((item) =>
      issues.push({
        kind: "unknown",
        title: "未知语义",
        message: item.reasons?.join(" ") || "该区域没有足够证据进行分类。",
        node: item.provenance?.source_node_ids?.[0],
      }),
    );
  state.paperSuggestions
    .flatMap((item) => item.warnings || [])
    .forEach((warning) =>
      issues.push({
        kind: "readability",
        title: "论文可读性",
        message: warning,
      }),
    );
  state.tasks
    .filter((task) => task.status === "failed")
    .forEach((task) =>
      issues.push({
        kind: "task",
        title: `${task.kind} 失败`,
        message: task.error?.message || "查看任务中心并重试。",
      }),
    );
  if (["error", "conflict"].includes(workspaceMachine.save.state))
    issues.push({
      kind: "save",
      title:
        workspaceMachine.save.state === "conflict"
          ? "Autosave conflict"
          : "Autosave failed",
      message: workspaceMachine.save.message,
    });
  if (state.sceneFallbackReason)
    issues.push({
      kind: "scene-fallback",
      title: "Scene CPU fallback active",
      message: state.sceneFallbackReason,
    });
  state.issues = issues;
  $("#issue-badge").textContent = issues.length;
  updateToolbarStatusBadge();
  $("#issue-list").innerHTML =
    issues
      .map(
        (issue, index) =>
          `<article class="issue-card"><strong>${escapeHtml(issue.title)}</strong><p>${escapeHtml(issue.message)}</p><button data-locate-issue="${index}">${issue.node ? "定位" : issue.kind === "task" ? "打开任务中心" : issue.kind === "save" ? "Retry save" : issue.kind === "scene-fallback" ? "Open Scene" : "打开论文建议"}</button></article>`,
      )
      .join("") || '<p class="empty">当前未发现需要处理的问题。</p>';
  $$("[data-locate-issue]", $("#issue-list")).forEach(
    (button) =>
      (button.onclick = () => {
        const issue = issues[Number(button.dataset.locateIssue)];
        if (issue.node) locateSourceNode(issue.node);
        else if (issue.kind === "task") openDrawer("task-center");
        else if (issue.kind === "save") workspaceMachine.save.retry?.();
        else if (issue.kind === "scene-fallback") void switchWorkspace("scene");
        else openDialog($("#paper-workflow"), { trigger: button });
      }),
  );
}

function localProjectDraft() {
  synchronizeModelFigureProvenanceIndex();
  return {
    project_version: "1.4",
    name:
      state.workspaceMode === "figure" && state.figure?.name
        ? state.figure.name
        : state.workspaceMode === "scene" && state.scene?.name
          ? state.scene.name
          : state.graph.name,
    graph: state.graph,
    theme: state.theme,
    theme_overrides: state.themeOverrides,
    layout: {
      algorithm: state.algorithm,
      direction: state.direction,
      result: state.layout,
      layout_options: state.layoutOptions,
      focus: [...state.focus],
    },
    export: { page: state.page, formats: ["svg"] },
    comments: state.comments,
    semantic_view: projectSemanticViewPayload(),
    canvas_state: {
      search: $("#graph-search").value,
      selection: [...state.sourceSelection],
      focus: [...state.focus],
      analysis_metric: state.metric,
      breadcrumbs: state.breadcrumbs,
      viewports: state.viewMemory,
      view_box: state.viewBox,
      zoom: state.zoom,
      fixed_layout: state.fixedLayout,
      workspace_mode: state.workspaceMode,
      figure_selection: [...state.figureSelection],
      figure_active_page: state.figureActivePage,
      figure_active_layer: state.figureActiveLayer,
      figure_include_guides: state.figureIncludeGuides,
      scene_selection: [...state.sceneSelection],
      scene_camera_id: state.scene?.active_camera_id || null,
      workspace_contexts: workspaceMachine.serialize().contexts,
      ui_preferences: clone(uiPreferences),
    },
    paper_workflow: state.projectMeta.paper_workflow || {},
    figure_composer:
      normalizeComposerState(state.composer) ||
      normalizeComposerState(state.projectMeta.figure_composer) ||
      {},
    figure_ir: state.figureNeedsRebuild
      ? {}
      : state.figure || state.projectMeta.figure_ir || {},
    scene_ir: state.sceneNeedsRebuild
      ? {}
      : state.scene || state.projectMeta.scene_ir || {},
    updated_at: new Date().toISOString(),
  };
}

function semanticDocumentFromEnvelope(envelope) {
  const candidate = envelope?.document?.entities
    ? envelope.document
    : envelope?.entities
      ? envelope
      : null;
  if (!candidate) return null;
  const semantic = clone(candidate);
  delete semantic.version;
  delete semantic.level;
  delete semantic.view;
  delete semantic.document;
  return semantic;
}

function projectSemanticViewPayload() {
  const persistedDocument = state.semanticData?.entities
    ? semanticDocumentFromEnvelope(state.semanticData)
    : semanticDocumentFromEnvelope(state.projectMeta.semantic_view);
  return {
    version: state.projectMeta.semantic_view?.version || "1.0",
    level: persistedSemanticLevel(state.semanticLevel),
    view: state.semanticView,
    ...(persistedDocument ? { document: persistedDocument } : {}),
  };
}

function autosaveRevision(draft) {
  return draft?.updated_at || draft?.revision || null;
}

function autosaveRevisionLabel(draft) {
  const revision = autosaveRevision(draft);
  if (!revision) return "No revision timestamp";
  const timestamp = new Date(revision);
  return Number.isNaN(timestamp.getTime())
    ? String(revision)
    : timestamp.toLocaleString();
}

function autosaveDraftSummary(draft) {
  const sceneLayers = draft?.scene_ir?.layers || [],
    sceneObjects = sceneLayers.reduce(
      (count, layer) => count + (layer.objects?.length || 0),
      0,
    );
  return [
    ["Project", draft?.name || draft?.graph?.name || "Untitled"],
    ["Workspace", draft?.canvas_state?.workspace_mode || "graph"],
    [
      "Graph",
      `${draft?.graph?.nodes?.length || 0} nodes · ${draft?.graph?.edges?.length || 0} edges`,
    ],
    ["Scene", `${sceneObjects} objects`],
  ];
}

function renderAutosaveDraftSummary(target, draft) {
  target.innerHTML = autosaveDraftSummary(draft)
    .map(
      ([term, value]) =>
        `<dt>${escapeHtml(term)}</dt><dd>${escapeHtml(value)}</dd>`,
    )
    .join("");
}

function openAutosaveConflictDialog(note = "") {
  const conflict = state.pendingAutosaveConflict;
  if (!conflict) return;
  $("#autosave-current-revision").textContent = autosaveRevisionLabel(
    conflict.localDraft,
  );
  $("#autosave-stored-revision").textContent = autosaveRevisionLabel(
    conflict.remoteDraft,
  );
  renderAutosaveDraftSummary(
    $("#autosave-current-summary"),
    conflict.localDraft,
  );
  renderAutosaveDraftSummary(
    $("#autosave-stored-summary"),
    conflict.remoteDraft,
  );
  $("#autosave-conflict-note").textContent = note;
  $("#autosave-keep-stored").disabled = !conflict.remoteDraft?.graph;
  openDialog($("#autosave-conflict-dialog"), {
    trigger: document.activeElement,
    focusSelector: "#autosave-overwrite-stored",
  });
}

async function resolveAutosaveConflict(resolution) {
  const conflict = state.pendingAutosaveConflict;
  if (!conflict) return;
  const keepStored = $("#autosave-keep-stored"),
    overwriteStored = $("#autosave-overwrite-stored"),
    note = $("#autosave-conflict-note");
  keepStored.disabled = true;
  overwriteStored.disabled = true;
  try {
    if (resolution === "stored") {
      note.textContent = "Validating the stored revision…";
      const restored = await restoreProjectDraft(conflict.remoteDraft);
      if (!restored)
        throw new Error("The stored revision changed during load.");
      clearTimeout(scheduleAutosave.timer);
      state.pendingAutosaveConflict = null;
      $("#autosave-conflict-dialog").close();
      workspaceMachine.setSaveState("saved", {
        message: "Stored revision loaded",
        revision: autosaveRevision(restored),
        localRevision: autosaveRevision(restored),
        retry: null,
      });
      updateIssues();
      toast("Stored autosave loaded after revision comparison.", "success");
      return;
    }

    const liveDraft = JSON.parse(
        window.localStorage.getItem("nndv-autosaved-project") || "null",
      ),
      liveRevision = autosaveRevision(liveDraft);
    if (liveRevision !== conflict.expectedRemoteRevision) {
      state.pendingAutosaveConflict = {
        ...conflict,
        remoteDraft: liveDraft,
        expectedRemoteRevision: liveRevision,
      };
      workspaceMachine.markConflict(liveRevision, openAutosaveConflictDialog);
      openAutosaveConflictDialog(
        "The stored autosave changed again. The comparison has been refreshed; review it before choosing overwrite.",
      );
      return;
    }
    const acceptedDraft = clone(conflict.localDraft);
    acceptedDraft.updated_at = new Date().toISOString();
    window.localStorage.setItem(
      "nndv-autosaved-project",
      JSON.stringify(acceptedDraft),
    );
    window.localStorage.setItem("nndv-last-autosave", acceptedDraft.updated_at);
    scheduleAutosave.lastPersistedRevision = acceptedDraft.updated_at;
    state.pendingAutosaveConflict = null;
    $("#autosave-conflict-dialog").close();
    workspaceMachine.setSaveState("saved", {
      message: "Current revision saved after comparison",
      revision: acceptedDraft.updated_at,
      localRevision: acceptedDraft.updated_at,
      retry: null,
    });
    updateIssues();
    toast(
      "Current workspace replaced the reviewed stored autosave.",
      "success",
    );
  } catch (error) {
    note.textContent = `${error.message} Nothing was overwritten.`;
    workspaceMachine.markConflict(
      state.pendingAutosaveConflict?.expectedRemoteRevision,
      openAutosaveConflictDialog,
    );
  } finally {
    if (state.pendingAutosaveConflict) {
      keepStored.disabled = !state.pendingAutosaveConflict.remoteDraft?.graph;
      overwriteStored.disabled = false;
    }
  }
}

function scheduleAutosave() {
  if (
    !state.initialized ||
    !state.graph ||
    state.autosaveBlockedByInvalidProject
  )
    return;
  markProjectDirty();
  clearTimeout(scheduleAutosave.timer);
  scheduleAutosave.timer = setTimeout(() => {
    const save = () => {
      try {
        const previous = JSON.parse(
          window.localStorage.getItem("nndv-autosaved-project") || "null",
        );
        const previousRevision = previous?.updated_at || null;
        if (
          scheduleAutosave.lastPersistedRevision &&
          previousRevision &&
          previousRevision !== scheduleAutosave.lastPersistedRevision
        ) {
          state.pendingAutosaveConflict = {
            localDraft: localProjectDraft(),
            remoteDraft: previous,
            expectedRemoteRevision: previousRevision,
          };
          workspaceMachine.markConflict(
            previousRevision,
            openAutosaveConflictDialog,
          );
          updateIssues();
          openAutosaveConflictDialog();
          return;
        }
        workspaceMachine.setSaveState("saving", {
          message: "Autosaving…",
        });
        const draft = localProjectDraft();
        window.localStorage.setItem(
          "nndv-autosaved-project",
          JSON.stringify(draft),
        );
        window.localStorage.setItem(
          "nndv-last-autosave",
          new Date().toISOString(),
        );
        scheduleAutosave.lastPersistedRevision = draft.updated_at;
        workspaceMachine.setSaveState("saved", {
          message: "Autosaved",
          localRevision: draft.updated_at,
          retry: null,
        });
      } catch (error) {
        workspaceMachine.setSaveState("error", {
          message: `Autosave failed: ${error.message}`,
          retry: scheduleAutosave,
        });
        updateIssues();
      }
    };
    // Autosave is a correctness boundary, not optional background polish.
    // Keep a short idle opportunity while guaranteeing persistence well
    // inside the documented 900 ms interaction-to-durable-draft window.
    if (window.requestIdleCallback)
      window.requestIdleCallback(save, { timeout: 250 });
    else setTimeout(save, 0);
  }, 350);
}

function markProjectDirty(message = "Unsaved changes") {
  if (!state.initialized) return;
  workspaceMachine.markDirty(message);
}

function syncControls() {
  const defaults = state.capabilities?.theme_values?.[state.theme] || {},
    value = (key, fallback) =>
      state.themeOverrides[key] ?? defaults[key] ?? fallback;
  $("#theme-select").value = state.theme;
  $("#page-select").value = state.page;
  $("#layout-select").value = state.algorithm;
  $("#direction-select").value = state.direction;
  $("#semantic-level").value = state.semanticLevel || "raw";
  $("#semantic-view").value = state.semanticView;
  $("#style-font").value = value("font_family", "Inter, Arial, sans-serif");
  $("#style-font-size").value = value("font_size", 12);
  $("#style-font-weight").value = value("font_weight", 600);
  $("#style-radius").value = value("node_radius", 8);
  $("#style-node-opacity").value = value("node_opacity", 1);
  $("#style-background").value = value("background", "#ffffff");
  $("#style-node-fill").value = value("node_fill", "#f8fafc");
  $("#style-border").value = value("border", "#334155");
  $("#style-edge").value = value("edge", "#64748b");
  $("#style-accent").value = value("accent", "#2563eb");
  $("#style-edge-width").value = value("edge_width", 1.5);
  $("#style-edge-arrow").value = value("edge_arrow", "end");
  $("#style-edge-dashed").checked = Boolean(value("edge_dash", ""));
  $("#style-parameter-format").value = value("parameter_format", "human");
  $("#style-flops-format").value = value("flops_format", "human");
  $("#style-shape-brackets").checked = Boolean(value("shape_brackets", false));
  $("#style-rank-gap").value = state.layoutOptions.rank_gap;
  $("#style-node-gap").value = state.layoutOptions.node_gap;
  $("#canvas-shell").classList.toggle("perspective-mode", state.perspective);
  $("#perspective-button").classList.toggle("primary", state.perspective);
  $("#animate-button").classList.toggle("primary", state.animate);
  const level =
    $("#semantic-level").selectedOptions[0]?.textContent || "原始图";
  const page = $("#page-select").selectedOptions[0]?.textContent || "自动页面";
  $("#view-menu-summary").textContent = `${level} · ${page}`;
}
function escapeHtml(value) {
  const div = document.createElement("div");
  div.textContent = value ?? "";
  return div.innerHTML;
}
function escapeAttr(value) {
  return escapeHtml(value).replace(/"/g, "&quot;");
}

function studioId(kind) {
  const value =
    globalThis.crypto?.randomUUID?.() ||
    `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
  return `${kind}_${value.replaceAll("-", "_")}`;
}

function studioAuthorProvenance(
  reason = "Author-created Figure Studio annotation.",
) {
  return {
    kind: "author_annotation",
    source_id: "",
    graph_ir_ids: [],
    source_locator: {},
    evidence: {},
    reason,
    author_annotation: true,
  };
}

function studioDefaultLayers(panelId) {
  return [
    ["model-data", "Model data"],
    ["semantic-annotation", "Semantic annotation"],
    ["author-annotation", "Author annotation"],
    ["legend-caption", "Legend / Caption"],
  ].map(([role, name], order) => ({
    id: studioId(`layer_${panelId}_${role}`),
    name,
    role,
    objects: [],
    groups: [],
    visible: true,
    locked: false,
    order,
  }));
}

function studioPages() {
  return state.figure?.pages || [];
}

function studioActivePage() {
  const pages = studioPages();
  const active = pages.find((page) => page.id === state.figureActivePage);
  if (active) return active;
  state.figureActivePage = pages[0]?.id || null;
  return pages[0] || null;
}

function studioPanels() {
  return studioPages().flatMap((page) => page.panels || []);
}

function studioLayers() {
  return studioPanels().flatMap((panel) => panel.layers || []);
}

function studioObjects() {
  return studioLayers().flatMap((layer) => layer.objects || []);
}

function synchronizeModelFigureProvenanceIndex() {
  if (state.figureNeedsRebuild) return;
  const metadata = state.figure?.metadata;
  if (!metadata) return;
  const evidenceObjects = studioObjects().filter((object) =>
    ["graph_ir", "semantic_view"].includes(object.provenance?.kind),
  );
  if (
    typeof metadata.provenance_index !== "object" &&
    evidenceObjects.length === 0
  )
    return;
  const portIds = new Set(
      (state.graph?.nodes || [])
        .flatMap((node) => [...(node.inputs || []), ...(node.outputs || [])])
        .map((port) => String(port.id)),
    ),
    graphToFigure = new Map(),
    semanticToFigure = new Map(),
    figureToSource = {},
    previousReverse = metadata.provenance_index?.figure_to_source || {},
    uniqueStrings = (values) => [
      ...new Set(
        (Array.isArray(values) ? values : []).filter(Boolean).map(String),
      ),
    ],
    addForward = (index, sourceId, objectId) => {
      if (!index.has(sourceId)) index.set(sourceId, new Set());
      index.get(sourceId).add(objectId);
    },
    sortedForward = (index) =>
      Object.fromEntries(
        [...index.entries()]
          .sort(([left], [right]) => left.localeCompare(right))
          .map(([sourceId, objectIds]) => [
            sourceId,
            [...objectIds].sort((left, right) => left.localeCompare(right)),
          ]),
      );

  for (const object of evidenceObjects) {
    const provenance = object.provenance || {};
    if (!["graph_ir", "semantic_view"].includes(provenance.kind)) continue;
    const objectId = String(object.id),
      graphIds = uniqueStrings(provenance.graph_ir_ids),
      graphPortIds = graphIds.filter((id) => portIds.has(id)),
      entry = {
        graph_ir_ids: graphIds,
        graph_port_ids: graphPortIds,
      };
    graphIds.forEach((id) => addForward(graphToFigure, id, objectId));
    const previousPortId = previousReverse[objectId]?.port_id;
    if (previousPortId && graphPortIds.includes(String(previousPortId)))
      entry.port_id = String(previousPortId);
    if (provenance.kind === "semantic_view") {
      const semanticIds = uniqueStrings(
          provenance.evidence?.semantic_entity_ids,
        ),
        primaryId = provenance.source_id ? String(provenance.source_id) : "";
      if (primaryId && !semanticIds.includes(primaryId))
        semanticIds.unshift(primaryId);
      semanticIds.forEach((id) => addForward(semanticToFigure, id, objectId));
      entry.semantic_id = primaryId;
      entry.semantic_ids = semanticIds;
      entry.semantic_connection_ids = uniqueStrings(
        provenance.evidence?.semantic_connection_ids,
      );
    }
    figureToSource[objectId] = entry;
  }
  metadata.provenance_index = {
    graph_to_figure: sortedForward(graphToFigure),
    semantic_to_figure: sortedForward(semanticToFigure),
    figure_to_source: Object.fromEntries(
      Object.entries(figureToSource).sort(([left], [right]) =>
        left.localeCompare(right),
      ),
    ),
  };
}

function studioFindObject(id) {
  for (const page of studioPages())
    for (const panel of page.panels || [])
      for (const layer of panel.layers || []) {
        const object = (layer.objects || []).find((item) => item.id === id);
        if (object) return { page, panel, layer, object };
      }
  return null;
}

function studioFindLayer(id) {
  for (const page of studioPages())
    for (const panel of page.panels || []) {
      const layer = (panel.layers || []).find((item) => item.id === id);
      if (layer) return { page, panel, layer };
    }
  return null;
}

function studioSelectedObjects() {
  return [...state.figureSelection].map(studioFindObject).filter(Boolean);
}

function applyWorkspaceMode() {
  const figureActive = state.workspaceMode === "figure",
    sceneActive = state.workspaceMode === "scene";
  document.body.classList.toggle("figure-studio-active", figureActive);
  document.body.classList.toggle("scene-studio-active", sceneActive);
  $(".toolbar")?.classList.toggle("hidden", figureActive);
  $("#studio-menubar")?.classList.toggle("hidden", !figureActive);
  $("#figure-studio-left")?.classList.toggle("hidden", !figureActive);
  $("#figure-studio-right")?.classList.toggle("hidden", !figureActive);
  $("#figure-studio-toolbar")?.classList.toggle("hidden", !figureActive);
  $("#scene-studio-left")?.classList.toggle("hidden", !sceneActive);
  $("#scene-studio-right")?.classList.toggle("hidden", !sceneActive);
  $("#scene-canvas-toolbar")?.classList.toggle("hidden", !sceneActive);
  $("#scene-render-surface")?.classList.toggle("hidden", !sceneActive);
  $$(".scene-export-only").forEach((control) =>
    control.classList.toggle("hidden", !sceneActive),
  );
  if (!sceneActive) $("#scene-selection-toolbar")?.classList.add("hidden");
  else updateSceneContextToolbar();
  $$("[data-workspace]").forEach((button) =>
    button.setAttribute(
      "aria-pressed",
      String(button.dataset.workspace === state.workspaceMode),
    ),
  );
  if (figureActive && state.figure)
    $("#studio-document-title").textContent = state.figure.name;
  if (!figureActive) {
    $("#canvas")?.classList.remove("grayscale-check");
    closeDrawer({ restoreFocus: false });
  }
  if (sceneActive) sceneRenderer?.resize();
}

async function loadStudioCatalog() {
  if (!state.figureCatalog.length) {
    const body = await api("/api/figure/templates");
    state.figureCatalog = body.templates || [];
  }
  $("#studio-template-list").innerHTML = state.figureCatalog
    .map(
      (item) =>
        `<button class="studio-template-card" data-studio-template="${escapeAttr(item.slug)}"><strong>${escapeHtml(item.title)}</strong><small>${escapeHtml(item.description)}</small><small>schematic · tensor geometry · mixed</small></button>`,
    )
    .join("");
  $$("[data-studio-template]", $("#studio-template-list")).forEach(
    (button) =>
      (button.onclick = () =>
        openStudioTemplate(button.dataset.studioTemplate)),
  );
}

async function enterFigureStudio({ rebuild = false } = {}) {
  closeToolbarMenus();
  graphRenderSequence += 1;
  const shouldRebuild = rebuild || state.figureNeedsRebuild,
    existingFigure = shouldRebuild && state.figure ? clone(state.figure) : null,
    needsReplacement = !state.figure || shouldRebuild;
  const generation = ++studioRenderSequence;
  snapshot();
  setBusy(true, "正在建立独立 Figure IR…");
  try {
    if (needsReplacement) {
      if (state.graph?.nodes?.length) {
        const response = await api("/api/figure/from-graph", {
          graph: state.graph,
          graph_id: state.graphId,
          level: state.semanticLevel || "operation",
          view: state.semanticView || "faithful",
          mode: "mixed",
          page_preset: "double-column",
          focus_ids: [...state.focus],
          focus_hops: 1,
          viewport: state.lazy && state.viewBox ? state.viewBox : null,
          existing_figure: existingFigure,
        });
        if (generation !== studioRenderSequence) return;
        state.figure = response.figure;
        state.figureProof = response.proof;
        state.semanticData = response.semantic_view || null;
        state.projectMeta.semantic_view = projectSemanticViewPayload();
      } else {
        const response = await api(
          "/api/figure/templates/cnn-feature-pipeline",
          {
            page_preset: "double-column",
          },
        );
        if (generation !== studioRenderSequence) return;
        state.figure = response.figure;
        state.figureProof = response.proof;
      }
    }
    state.workspaceMode = "figure";
    workspaceMachine.transition("figure", currentWorkspaceContext());
    state.figureNeedsRebuild = false;
    state.selection.clear();
    state.figureSelection.clear();
    state.figureActivePage = studioPages()[0]?.id || null;
    state.figureActiveLayer =
      studioLayers().find((layer) => layer.role === "author-annotation")?.id ||
      studioLayers()[0]?.id ||
      null;
    state.projectMeta.figure_ir = state.figure;
    applyWorkspaceMode();
    await loadStudioCatalog();
    if (generation !== studioRenderSequence) return;
    if (!(await refreshFigureStudio())) return;
    toast(
      "Scientific Figure Studio 已打开；Figure IR 与 Graph IR 保持独立。",
      "success",
    );
  } catch (error) {
    if (generation !== studioRenderSequence) return;
    if (existingFigure) state.figure = existingFigure;
    state.workspaceMode = "graph";
    workspaceMachine.transition("graph");
    applyWorkspaceMode();
    toast(error.message, true);
  } finally {
    setBusy(false);
  }
}

async function leaveFigureStudio() {
  studioRenderSequence += 1;
  state.workspaceMode = "graph";
  workspaceMachine.transition("graph", currentWorkspaceContext());
  state.projectMeta.figure_ir = state.figure || {};
  state.figureSelection.clear();
  applyWorkspaceMode();
  await refresh(!state.fixedLayout);
}

async function openStudioTemplate(slug) {
  let generation = invalidateSourceBoundWork();
  snapshot();
  setBusy(true, "正在打开本地可编辑模板…");
  try {
    const response = await api(`/api/figure/templates/${slug}`, {
      page_preset: $("#studio-template-page").value,
    });
    if (generation !== sourceGeneration) return;
    state.graph = response.graph;
    state.graphId = response.graph_id;
    state.viewGraph = null;
    resetComposerForNewSource();
    generation = sourceGeneration;
    state.figure = response.figure;
    state.figureProof = response.proof;
    state.figureSelection.clear();
    state.figureActivePage = studioPages()[0]?.id || null;
    state.figureActiveLayer = studioLayers()[0]?.id || null;
    state.projectMeta = response.project;
    state.semanticData = null;
    state.projectMeta.figure_ir = state.figure;
    state.workspaceMode = "figure";
    applyWorkspaceMode();
    if (!(await refreshFigureStudio())) return;
    if (generation !== sourceGeneration) return;
    toast("模板已在本地打开；符号 shape 不代表具体模型实例。", "success");
  } catch (error) {
    if (generation === sourceGeneration) toast(error.message, true);
  } finally {
    setBusy(false);
  }
}

let studioRenderSequence = 0;
async function refreshFigureStudio() {
  if (!state.figure) return false;
  synchronizeModelFigureProvenanceIndex();
  const sequence = ++studioRenderSequence,
    generation = sourceGeneration;
  const started = window.performance.now();
  setBusy(true, "正在渲染 Figure IR 矢量对象…");
  try {
    const response = await api("/api/figure/render", {
      figure: state.figure,
      include_guides: state.figureIncludeGuides,
    });
    if (sequence !== studioRenderSequence || generation !== sourceGeneration)
      return false;
    state.figure = response.figure;
    state.figureProof = response.proof;
    state.projectMeta.figure_ir = state.figure;
    $("#canvas").innerHTML = response.svg;
    attachStudioCanvasEvents();
    renderStudioPageTree();
    renderStudioLayerTree();
    renderStudioInspector();
    renderStudioProof();
    state.figureLastInteractionMs =
      Math.round((window.performance.now() - started) * 100) / 100;
    $("#studio-document-title").textContent = state.figure.name;
    scheduleAutosave();
    return true;
  } catch (error) {
    if (sequence === studioRenderSequence && generation === sourceGeneration)
      toast(error.message, true);
    return false;
  } finally {
    setBusy(false);
    if (
      sequence === studioRenderSequence &&
      generation === sourceGeneration &&
      state.workspaceMode === "figure"
    ) {
      const count = studioObjects().length;
      $("#status").textContent =
        `${studioPages().length} Page · ${studioPanels().length} Panel · ${count} Figure IR 对象 · 最近渲染 ${state.figureLastInteractionMs ?? "—"} ms`;
    }
  }
}

function applyStudioSelection({
  syncObjectRows = true,
  inspector = true,
} = {}) {
  $$("#canvas [data-figure-object-id]").forEach((element) =>
    element.classList.toggle(
      "studio-selected",
      state.figureSelection.has(element.dataset.figureObjectId),
    ),
  );
  if (syncObjectRows)
    $$(".studio-object-row").forEach((element) =>
      element.classList.toggle(
        "selected",
        state.figureSelection.has(element.dataset.objectId),
      ),
    );
  if (inspector) renderStudioInspector();
}

function selectStudioObject(id, additive = false) {
  if (!additive) state.figureSelection.clear();
  if (id) {
    if (additive && state.figureSelection.has(id))
      state.figureSelection.delete(id);
    else state.figureSelection.add(id);
    const found = studioFindObject(id);
    if (found) state.figureActiveLayer = found.layer.id;
  }
  applyStudioSelection();
  renderStudioLayerTree();
  const graphIds = studioSelectedObjects().flatMap(
    (item) =>
      item.object?.provenance?.graph_ir_ids ||
      item.object?.provenance?.source_ids ||
      [],
  );
  syncSceneSelectionFrom2D(
    graphIds.length ? "graph" : "figure",
    graphIds.length ? graphIds : [...state.figureSelection],
  );
}

function attachStudioCanvasEvents() {
  const svg = $("#canvas svg");
  if (!svg) return;
  svg.addEventListener("click", (event) => {
    const object = event.target.closest("[data-figure-object-id]");
    if (object) {
      selectStudioObject(
        object.dataset.figureObjectId,
        event.shiftKey || event.ctrlKey || event.metaKey,
      );
      event.stopPropagation();
    } else selectStudioObject(null);
  });
  $$("[data-figure-object-id]", svg).forEach((element) =>
    element.addEventListener("pointerdown", beginStudioObjectDrag),
  );
  applyStudioSelection({ syncObjectRows: false, inspector: false });
  applyStudioLensHighlight();
}

function studioPoint(event, svg) {
  const point = svg.createSVGPoint();
  point.x = event.clientX;
  point.y = event.clientY;
  const transformed = point.matrixTransform(svg.getScreenCTM().inverse());
  return [transformed.x, transformed.y];
}

function beginStudioObjectDrag(event) {
  if (event.button !== 0 || state.workspaceMode !== "figure") return;
  const id = event.currentTarget.dataset.figureObjectId;
  const found = studioFindObject(id);
  if (
    !found ||
    found.object.locked ||
    found.layer.locked ||
    found.panel.locked
  ) {
    toast("该对象、Layer 或 Panel 已锁定。", "warning");
    return;
  }
  if (!state.figureSelection.has(id)) selectStudioObject(id, event.shiftKey);
  const movable = studioSelectedObjects().filter(
    (item) => !item.object.locked && !item.layer.locked && !item.panel.locked,
  );
  if (!movable.length) return;
  snapshot();
  const svg = $("#canvas svg"),
    start = studioPoint(event, svg),
    originals = new Map(
      movable.map((item) => [
        item.object.id,
        {
          geometry: clone(item.object.geometry),
          route: clone(item.object.manual_route || []),
        },
      ]),
    );
  let lastComputation = 0;
  const move = (pointerEvent) => {
    const operationStarted = window.performance.now(),
      current = studioPoint(pointerEvent, svg),
      dx = current[0] - start[0],
      dy = current[1] - start[1];
    for (const item of movable) {
      const original = originals.get(item.object.id),
        originalX = Number(original.geometry.x),
        originalY = Number(original.geometry.y),
        snappedX = Number.isFinite(originalX)
          ? Math.round((originalX + dx) * 2) / 2
          : null,
        snappedY = Number.isFinite(originalY)
          ? Math.round((originalY + dy) * 2) / 2
          : null,
        translatedX = snappedX == null ? dx : snappedX - originalX,
        translatedY = snappedY == null ? dy : snappedY - originalY;
      if (snappedX != null) item.object.geometry.x = snappedX;
      if (snappedY != null) item.object.geometry.y = snappedY;
      if (original.route.length)
        item.object.manual_route = original.route.map(([x, y]) => [
          x + translatedX,
          y + translatedY,
        ]);
      $$(
        `[data-figure-object-id="${CSS.escape(item.object.id)}"]`,
        svg,
      ).forEach((element) =>
        element.setAttribute(
          "transform",
          `translate(${translatedX} ${translatedY})`,
        ),
      );
    }
    lastComputation = window.performance.now() - operationStarted;
    pointerEvent.preventDefault();
  };
  const finish = async () => {
    window.removeEventListener("pointermove", move);
    window.removeEventListener("pointerup", finish);
    window.removeEventListener("pointercancel", cancel);
    state.figureLastInteractionMs = Math.round(lastComputation * 100) / 100;
    for (const item of movable) {
      item.object.constraints = (item.object.constraints || []).filter(
        (constraint) => constraint.kind !== "snap-baseline",
      );
      item.object.constraints.push({
        kind: "snap-baseline",
        target_ids: [item.object.id],
        value: { grid_mm: 0.5, source: "figure-studio-drag" },
        locked: false,
      });
    }
    await refreshFigureStudio();
  };
  const cancel = async () => {
    for (const item of movable) {
      const original = originals.get(item.object.id);
      item.object.geometry = original.geometry;
      item.object.manual_route = original.route;
    }
    window.removeEventListener("pointermove", move);
    window.removeEventListener("pointerup", finish);
    window.removeEventListener("pointercancel", cancel);
    await refreshFigureStudio();
  };
  window.addEventListener("pointermove", move);
  window.addEventListener("pointerup", finish, { once: true });
  window.addEventListener("pointercancel", cancel, { once: true });
  event.preventDefault();
  event.stopPropagation();
}

function studioObjectRow(object, groupId = "") {
  return `<div class="studio-object-row ${state.figureSelection.has(object.id) ? "selected" : ""}" draggable="true" data-object-id="${escapeAttr(object.id)}" data-group-id="${escapeAttr(groupId)}"><span>${object.locked ? "◆" : "◇"}</span><span>${escapeHtml(object.name)}</span><span class="object-kind">${escapeHtml(object.kind)}</span></div>`;
}

function reindexStudioPages() {
  studioPages().forEach((page, index) => {
    page.order = index;
    (page.panels || []).forEach(
      (panel, panelIndex) => (panel.order = panelIndex),
    );
  });
}

function studioPageHasLocks(page) {
  return (page.panels || []).some(
    (panel) =>
      panel.locked ||
      (panel.layers || []).some(
        (layer) =>
          layer.locked || (layer.objects || []).some((object) => object.locked),
      ),
  );
}

function cloneStudioPageWithFreshIds(source) {
  const page = clone(source),
    idMap = new Map(),
    remember = (oldId, kind) => {
      const fresh = studioId(kind);
      idMap.set(oldId, fresh);
      return fresh;
    };
  page.id = remember(page.id, "figure_page");
  for (const panel of page.panels || []) {
    panel.id = remember(panel.id, "figure_panel");
    for (const layer of panel.layers || []) {
      layer.id = remember(layer.id, "figure_layer");
      for (const group of layer.groups || [])
        group.id = remember(group.id, "figure_group");
      for (const object of layer.objects || [])
        object.id = remember(object.id, "figure_object");
    }
  }
  const remapTargets = (constraint) => {
    constraint.target_ids = (constraint.target_ids || []).map(
      (id) => idMap.get(id) || id,
    );
  };
  for (const panel of page.panels || []) {
    (panel.constraints || []).forEach(remapTargets);
    for (const layer of panel.layers || []) {
      for (const group of layer.groups || [])
        group.object_ids = (group.object_ids || []).map(
          (id) => idMap.get(id) || id,
        );
      for (const object of layer.objects || []) {
        (object.constraints || []).forEach(remapTargets);
        if (object.metadata?.endpoint_object_ids)
          object.metadata.endpoint_object_ids =
            object.metadata.endpoint_object_ids.map(
              (id) => idMap.get(id) || id,
            );
      }
    }
  }
  page.title = `${source.title} copy`;
  return page;
}

function selectStudioPage(pageId, { scroll = true } = {}) {
  const page = studioPages().find((candidate) => candidate.id === pageId);
  if (!page) return;
  state.figureActivePage = page.id;
  state.figureSelection.clear();
  state.figureActiveLayer =
    (page.panels || [])
      .flatMap((panel) => panel.layers || [])
      .find((layer) => layer.role === "author-annotation")?.id ||
    page.panels?.[0]?.layers?.[0]?.id ||
    null;
  renderStudioPageTree();
  renderStudioLayerTree();
  renderStudioInspector();
  if (scroll)
    $(
      `#canvas g.figure-page[data-page-id="${CSS.escape(page.id)}"]`,
    )?.scrollIntoView({
      block: "nearest",
      inline: "nearest",
      behavior: "smooth",
    });
}

function renderStudioPageTree() {
  const target = $("#studio-page-tree"),
    select = $("#studio-page-select"),
    pages = studioPages();
  if (!target || !select) return;
  const active = studioActivePage();
  select.innerHTML = pages
    .map(
      (page, index) =>
        `<option value="${escapeAttr(page.id)}"${page.id === active?.id ? " selected" : ""}>Page ${index + 1} · ${Number(page.width_mm).toFixed(1)}×${Number(page.height_mm).toFixed(1)} mm</option>`,
    )
    .join("");
  target.innerHTML = pages
    .map(
      (page, index) =>
        `<details class="studio-panel-tree${page.id === active?.id ? " selected" : ""}" open data-studio-page-id="${escapeAttr(page.id)}"><summary>Page ${index + 1} · ${escapeHtml(page.title)} · ${Number(page.width_mm).toFixed(1)}×${Number(page.height_mm).toFixed(1)} mm</summary><div class="studio-panel-controls"><button data-page-tree-action="select">Activate</button><button data-page-tree-action="up"${index === 0 ? " disabled" : ""}>↑</button><button data-page-tree-action="down"${index === pages.length - 1 ? " disabled" : ""}>↓</button><button data-page-tree-action="duplicate">Duplicate</button><button data-page-tree-action="delete"${pages.length === 1 ? " disabled" : ""}>Delete</button></div>${(
          page.panels || []
        )
          .map(
            (panel, panelIndex) =>
              `<div class="studio-object-row" data-page-panel-id="${escapeAttr(panel.id)}"><span>${panel.locked ? "◆" : "◇"}</span><span>Panel ${escapeHtml(panel.label)} · ${escapeHtml(panel.mode)}</span><span><button data-panel-page-action="up"${panelIndex === 0 ? " disabled" : ""}>↑</button><button data-panel-page-action="down"${panelIndex === page.panels.length - 1 ? " disabled" : ""}>↓</button><button data-panel-page-action="previous"${index === 0 || page.panels.length === 1 ? " disabled" : ""}>← Page</button><button data-panel-page-action="next"${index === pages.length - 1 || page.panels.length === 1 ? " disabled" : ""}>Page →</button></span></div>`,
          )
          .join("")}</details>`,
    )
    .join("");
  if (active) {
    $("#studio-page-width").value = Number(active.width_mm);
    $("#studio-page-height").value = Number(active.height_mm);
    $("#studio-page-title").value = active.title || "";
    $("#studio-page-margin").value = Number(active.margin_mm ?? 4);
    $("#studio-page-columns").value = Number(active.columns ?? 1);
    $("#studio-page-column-gap").value = Number(active.column_gap_mm ?? 4);
    $("#studio-page-baseline").value = Number(active.baseline_grid_pt ?? 4);
    const preset =
      active.width_mm === 88 && active.height_mm === 118
        ? "single-column"
        : active.width_mm === 178 && active.height_mm === 118
          ? "double-column"
          : active.width_mm === 210 && active.height_mm === 297
            ? "a4-portrait"
            : active.width_mm === 297 && active.height_mm === 210
              ? "a4-landscape"
              : "custom";
    $("#studio-page-preset").value = preset;
  }
  $$("[data-page-tree-action]", target).forEach((button) => {
    button.onclick = () => {
      const pageId = button.closest("[data-studio-page-id]").dataset
        .studioPageId;
      if (button.dataset.pageTreeAction === "select") selectStudioPage(pageId);
      else void handleStudioPageAction(button.dataset.pageTreeAction, pageId);
    };
  });
  $$("[data-panel-page-action]", target).forEach((button) => {
    button.onclick = () => {
      const pageId = button.closest("[data-studio-page-id]").dataset
          .studioPageId,
        panelId = button.closest("[data-page-panel-id]").dataset.pagePanelId;
      void moveStudioPanel(pageId, panelId, button.dataset.panelPageAction);
    };
  });
}

async function handleStudioPageAction(action, explicitPageId = null) {
  const pages = studioPages(),
    active =
      pages.find((page) => page.id === explicitPageId) || studioActivePage(),
    index = pages.indexOf(active);
  if (!active && action !== "add") return;
  if (action === "add") {
    if (pages.length >= 64) return toast("Figure 最多支持 64 页。", "warning");
    snapshot();
    const source = active || pages[0],
      pageId = studioId("figure_page"),
      panelId = studioId("figure_panel"),
      margin = Number(source?.margin_mm ?? 4),
      width = Number(source?.width_mm ?? 178),
      height = Number(source?.height_mm ?? 118);
    pages.push({
      id: pageId,
      title: `Page ${pages.length + 1}`,
      width_mm: width,
      height_mm: height,
      panels: [
        {
          id: panelId,
          label: "A",
          title: "Panel A",
          mode: "mixed",
          geometry: {
            x: margin,
            y: margin,
            width: width - 2 * margin,
            height: height - 2 * margin,
          },
          layers: studioDefaultLayers(panelId),
          constraints: [],
          locked: false,
          layout_mode: "grid",
          order: 0,
        },
      ],
      margin_mm: margin,
      columns: 1,
      column_gap_mm: Number(source?.column_gap_mm ?? 4),
      baseline_grid_pt: Number(source?.baseline_grid_pt ?? 4),
      order: pages.length,
    });
    state.figureActivePage = pageId;
  } else if (action === "duplicate") {
    snapshot();
    const duplicated = cloneStudioPageWithFreshIds(active);
    pages.splice(index + 1, 0, duplicated);
    state.figureActivePage = duplicated.id;
  } else if (action === "delete") {
    if (pages.length === 1)
      return toast("至少保留一个 Figure Page。", "warning");
    if (studioPageHasLocks(active))
      return toast("页面包含锁定 Panel/Layer/Object，不能删除。", "warning");
    snapshot();
    pages.splice(index, 1);
    state.figureActivePage = pages[Math.min(index, pages.length - 1)].id;
  } else if (action === "up" || action === "down") {
    const nextIndex = action === "up" ? index - 1 : index + 1;
    if (nextIndex < 0 || nextIndex >= pages.length) return;
    snapshot();
    [pages[index], pages[nextIndex]] = [pages[nextIndex], pages[index]];
  } else if (action === "resize") {
    const width = Number($("#studio-page-width").value),
      height = Number($("#studio-page-height").value);
    if (
      !Number.isFinite(width) ||
      !Number.isFinite(height) ||
      width < 20 ||
      height < 20 ||
      width > 1000 ||
      height > 1000
    )
      return toast("页面宽高必须在 20–1000 mm 之间。", "warning");
    if (studioPageHasLocks(active))
      return toast("解锁页内对象后再调整页面尺寸。", "warning");
    snapshot();
    const scaleX = width / active.width_mm,
      scaleY = height / active.height_mm;
    for (const panel of active.panels || [])
      transformStudioPanel(panel, {
        x: panel.geometry.x * scaleX,
        y: panel.geometry.y * scaleY,
        width: panel.geometry.width * scaleX,
        height: panel.geometry.height * scaleY,
      });
    active.width_mm = width;
    active.height_mm = height;
  } else if (action === "settings") {
    const title = $("#studio-page-title").value.trim(),
      margin = Number($("#studio-page-margin").value),
      columns = Number($("#studio-page-columns").value),
      columnGap = Number($("#studio-page-column-gap").value),
      baseline = Number($("#studio-page-baseline").value);
    if (!title) return toast("Page title 不能为空。", "warning");
    if (
      !Number.isFinite(margin) ||
      margin < 0 ||
      margin * 2 >= Math.min(active.width_mm, active.height_mm)
    )
      return toast("页边距必须为非负数，且小于页面短边的一半。", "warning");
    if (!Number.isInteger(columns) || columns < 1 || columns > 12)
      return toast("列数必须为 1–12 的整数。", "warning");
    if (!Number.isFinite(columnGap) || columnGap < 0 || columnGap > 100)
      return toast("列间距必须为 0–100 mm。", "warning");
    if (!Number.isFinite(baseline) || baseline < 1 || baseline > 72)
      return toast("Baseline 必须为 1–72 pt。", "warning");
    snapshot();
    active.title = title;
    active.margin_mm = margin;
    active.columns = columns;
    active.column_gap_mm = columnGap;
    active.baseline_grid_pt = baseline;
  } else return;
  reindexStudioPages();
  await refreshFigureStudio();
}

async function moveStudioPanel(pageId, panelId, action) {
  const pages = studioPages(),
    pageIndex = pages.findIndex((page) => page.id === pageId),
    sourcePage = pages[pageIndex],
    panelIndex =
      sourcePage?.panels?.findIndex((panel) => panel.id === panelId) ?? -1;
  if (!sourcePage || panelIndex < 0) return;
  const panel = sourcePage.panels[panelIndex];
  if (panel.locked) return toast("锁定 Panel 不能移动或重排。", "warning");
  snapshot();
  if (action === "up" || action === "down") {
    const nextIndex = action === "up" ? panelIndex - 1 : panelIndex + 1;
    if (nextIndex < 0 || nextIndex >= sourcePage.panels.length) return;
    [sourcePage.panels[panelIndex], sourcePage.panels[nextIndex]] = [
      sourcePage.panels[nextIndex],
      sourcePage.panels[panelIndex],
    ];
    arrangeStudioPagePanels(
      sourcePage,
      sourcePage.panels[0]?.layout_mode || "grid",
    );
  } else {
    if (sourcePage.panels.length === 1)
      return toast("每页至少保留一个 Panel；先在源页添加 Panel。", "warning");
    const targetPage = pages[pageIndex + (action === "previous" ? -1 : 1)];
    if (!targetPage || targetPage.panels.length >= 8)
      return toast("目标页不存在或已有 A–H 八个 Panel。", "warning");
    sourcePage.panels.splice(panelIndex, 1);
    panel.label = [..."ABCDEFGH"].find(
      (candidate) =>
        !targetPage.panels.some((item) => item.label === candidate),
    );
    panel.order = targetPage.panels.length;
    targetPage.panels.push(panel);
    arrangeStudioPagePanels(
      sourcePage,
      sourcePage.panels[0]?.layout_mode || "grid",
    );
    arrangeStudioPagePanels(
      targetPage,
      targetPage.panels[0]?.layout_mode || "grid",
    );
    state.figureActivePage = targetPage.id;
  }
  reindexStudioPages();
  await refreshFigureStudio();
}

function renderStudioLayerTree() {
  const target = $("#studio-layer-tree");
  if (!state.figure) {
    target.innerHTML = '<p class="empty">尚无 Figure IR。</p>';
    return;
  }
  const activePage = studioActivePage();
  target.innerHTML = (activePage?.panels || [])
    .map(
      (panel) =>
        `<details class="studio-panel-tree" open data-panel-id="${escapeAttr(panel.id)}"><summary>${panel.locked ? "◆" : "◇"} Panel ${escapeHtml(panel.label)} · ${escapeHtml(panel.mode)}</summary><div class="studio-panel-controls"><label>Mode<select data-panel-mode><option value="schematic"${panel.mode === "schematic" ? " selected" : ""}>schematic</option><option value="tensor-geometry"${panel.mode === "tensor-geometry" ? " selected" : ""}>tensor geometry</option><option value="mixed"${panel.mode === "mixed" ? " selected" : ""}>mixed</option></select></label><button data-panel-action="lock">${panel.locked ? "解锁 Panel" : "锁定 Panel"}</button></div>${(
          panel.layers || []
        )
          .slice()
          .sort((a, b) => a.order - b.order)
          .map((layer) => {
            const grouped = new Set(
              (layer.groups || []).flatMap((group) => group.object_ids || []),
            );
            const groups = (layer.groups || [])
              .map(
                (group) =>
                  `<details class="studio-group-row" open data-group-id="${escapeAttr(group.id)}"><summary>${group.locked ? "◆" : "▦"} ${escapeHtml(group.name)}</summary>${(
                    group.object_ids || []
                  )
                    .map((id) =>
                      (layer.objects || []).find((item) => item.id === id),
                    )
                    .filter(Boolean)
                    .map((item) => studioObjectRow(item, group.id))
                    .join("")}</details>`,
              )
              .join("");
            const ungrouped = (layer.objects || [])
              .filter((item) => !grouped.has(item.id))
              .map((item) => studioObjectRow(item))
              .join("");
            return `<details class="studio-layer-row" open data-layer-id="${escapeAttr(layer.id)}"><summary>${layer.visible ? "◉" : "○"} ${layer.locked ? "◆" : "◇"} ${escapeHtml(layer.name)}</summary><div class="studio-layer-controls"><button data-layer-action="visible">${layer.visible ? "隐藏" : "显示"}</button><button data-layer-action="lock">${layer.locked ? "解锁" : "锁定"}</button><button data-layer-action="rename">重命名</button><small>${escapeHtml(layer.role)}</small></div>${groups}${ungrouped || (!groups ? '<p class="empty">空 Layer</p>' : "")}</details>`;
          })
          .join("")}</details>`,
    )
    .join("");
  $$(".studio-layer-row", target).forEach((element) => {
    const activate = () => (state.figureActiveLayer = element.dataset.layerId);
    $("summary", element).addEventListener("click", activate);
    element.addEventListener("dragover", (event) => event.preventDefault());
    element.addEventListener("drop", async (event) => {
      event.preventDefault();
      await moveStudioObjectToLayer(
        event.dataTransfer.getData("application/x-nndv-figure-object"),
        element.dataset.layerId,
      );
    });
  });
  $$("[data-panel-mode]", target).forEach((select) => {
    select.onchange = async () => {
      const panel = studioPanels().find(
        (item) => item.id === select.closest("[data-panel-id]").dataset.panelId,
      );
      if (!panel || panel.locked) {
        select.value = panel?.mode || "mixed";
        return toast("锁定 Panel 不能改变模式。", "warning");
      }
      snapshot();
      panel.mode = select.value;
      await refreshFigureStudio();
    };
  });
  $$('[data-panel-action="lock"]', target).forEach((button) => {
    button.onclick = async () => {
      const panel = studioPanels().find(
        (item) => item.id === button.closest("[data-panel-id]").dataset.panelId,
      );
      if (!panel) return;
      snapshot();
      panel.locked = !panel.locked;
      await refreshFigureStudio();
    };
  });
  $$(".studio-object-row", target).forEach((element) => {
    element.onclick = (event) =>
      selectStudioObject(
        element.dataset.objectId,
        event.shiftKey || event.ctrlKey || event.metaKey,
      );
    element.ondragstart = (event) =>
      event.dataTransfer.setData(
        "application/x-nndv-figure-object",
        element.dataset.objectId,
      );
  });
  $$("[data-layer-action]", target).forEach((button) => {
    button.onclick = async (event) => {
      event.preventDefault();
      const layerId = button.closest("[data-layer-id]").dataset.layerId;
      await studioLayerAction(layerId, button.dataset.layerAction);
    };
  });
}

async function moveStudioObjectToLayer(objectId, targetLayerId) {
  const source = studioFindObject(objectId),
    destination = studioFindLayer(targetLayerId);
  if (!source || !destination) return;
  if (source.panel.id !== destination.panel.id)
    return toast(
      "跨 Panel 移动须移动 Panel 对象；Layer 拖放仅限同一 Panel。",
      "warning",
    );
  if (source.object.locked || source.layer.locked || destination.layer.locked)
    return toast("锁定对象或 Layer 不能移动。", "warning");
  snapshot();
  source.layer.objects = source.layer.objects.filter(
    (item) => item.id !== objectId,
  );
  (source.layer.groups || []).forEach(
    (group) =>
      (group.object_ids = (group.object_ids || []).filter(
        (id) => id !== objectId,
      )),
  );
  source.object.order = destination.layer.objects.length;
  destination.layer.objects.push(source.object);
  state.figureActiveLayer = destination.layer.id;
  await refreshFigureStudio();
}

async function studioLayerAction(layerId, action) {
  const found = studioFindLayer(layerId);
  if (!found) return;
  if (action === "rename") {
    const values = await requestTextEntries({
      title: "重命名 Layer",
      fields: [{ name: "name", label: "Layer 名称", value: found.layer.name }],
    });
    if (!values) return;
    snapshot();
    found.layer.name = values.name;
  } else {
    snapshot();
    if (action === "visible") found.layer.visible = !found.layer.visible;
    else if (action === "lock") found.layer.locked = !found.layer.locked;
  }
  state.figureActiveLayer = found.layer.id;
  await refreshFigureStudio();
}

function renderStudioInspector() {
  const selected = studioSelectedObjects(),
    summary = $("#studio-selection-summary"),
    form = $("#studio-object-properties"),
    provenance = $("#studio-provenance-view");
  if (!selected.length) {
    summary.textContent = "选择 Figure 对象以编辑属性。";
    summary.classList.remove("hidden");
    form.classList.add("hidden");
    provenance.innerHTML =
      '<p class="empty">选择对象后显示 Graph IR、Semantic View 或 author annotation 来源。</p>';
    return;
  }
  summary.textContent = `${selected.length} 个对象已选择`;
  summary.classList.remove("hidden");
  form.classList.toggle("hidden", selected.length !== 1);
  if (selected.length === 1) {
    const item = selected[0].object,
      geometry = item.geometry || {};
    $("#studio-prop-name").value = item.name || "";
    $("#studio-prop-x").value = geometry.x ?? 0;
    $("#studio-prop-y").value = geometry.y ?? 0;
    $("#studio-prop-width").value = geometry.width ?? 1;
    $("#studio-prop-height").value = geometry.height ?? 1;
    $("#studio-prop-fill").value =
      item.style?.overrides?.front_fill ||
      item.style?.overrides?.fill ||
      "#dbeafe";
    $("#studio-prop-font-size").value =
      item.style?.overrides?.font_size ||
      state.figure.design_tokens["font.size.pt"];
    $("#studio-prop-locked").checked = !!item.locked;
    const isTensor = item.kind === "tensor-glyph";
    $("#studio-tensor-shape-field").classList.toggle("hidden", !isTensor);
    $("#studio-tensor-scale-field").classList.toggle("hidden", !isTensor);
    if (isTensor) {
      $("#studio-prop-shape").value = (
        item.metadata.author_shape_override ||
        item.metadata.tensor_shape ||
        []
      )
        .map((value) => (value == null ? "?" : value))
        .join(",");
      $("#studio-prop-scale").value =
        item.metadata.geometry_scale || "normalized";
    }
  }
  provenance.innerHTML = selected
    .map(
      ({ object }) =>
        `<article class="provenance-card"><strong>${escapeHtml(object.name)}</strong><p>${escapeHtml(object.provenance.kind)}</p><p>${escapeHtml(object.provenance.reason || "Evidence linked below.")}</p>${object.metadata?.author_shape_override ? `<p><strong>Author shape override:</strong> ${escapeHtml(object.metadata.author_shape_override_label)}; source model shape remains ${escapeHtml(object.metadata.shape_label || "unknown")}.</p>` : ""}<code>${escapeHtml(JSON.stringify({ source_id: object.provenance.source_id, graph_ir_ids: object.provenance.graph_ir_ids, source_locator: object.provenance.source_locator }, null, 2))}</code><p>author annotation = ${String(object.provenance.author_annotation)}</p></article>`,
    )
    .join("");
  $("#studio-token-font").value = state.figure.design_tokens["font.family"];
  $("#studio-token-line-width").value =
    state.figure.design_tokens["line.width.pt"];
}

function renderStudioProof() {
  const target = $("#studio-proof-view"),
    proof = state.figureProof;
  if (!proof) {
    target.innerHTML = '<p class="empty">尚未运行 Figure proof。</p>';
    return;
  }
  const entries = [
    ["overflow", proof.overflow],
    ["node/tensor overlap", proof.node_tensor_overlap],
    ["edge-node collision", proof.edge_node_collision],
    ["clipping", proof.clipping],
    ["unexplained crossing", proof.unexplained_crossing],
    ["minimum font", `${proof.minimum_font_pt} pt`, proof.minimum_font_pt >= 7],
    [
      "horizontal text",
      proof.horizontal_text_scale ?? "strict SVG oracle required",
      proof.final_output_verified && proof.horizontal_text_scale === 1,
    ],
    [
      "transform text",
      proof.transform_text_scale ?? "strict SVG oracle required",
      proof.final_output_verified && proof.transform_text_scale === 1,
    ],
  ];
  const headline = proof.final_output_verified
    ? proof.pass
      ? "FINAL SVG PASS"
      : "FINAL SVG NEEDS ATTENTION"
    : proof.pass
      ? "PROVISIONAL PASS · FINAL SVG PENDING"
      : "PROVISIONAL CHECK NEEDS ATTENTION";
  target.innerHTML = `<article class="proof-card"><strong>${headline}</strong><p>Figure digest ${escapeHtml(proof.figure_digest)}</p><p>Measurement source: ${escapeHtml(proof.measurement_source || "compiled Figure IR preflight")}</p><div class="proof-grid">${entries
    .map(([name, value, explicit]) => {
      const pass = explicit ?? Number(value) === 0;
      return `<div class="proof-value ${pass ? "pass" : "fail"}"><strong>${escapeHtml(name)}</strong><br>${escapeHtml(value)}</div>`;
    })
    .join("")}</div></article>`;
}

async function updateStudioProperty(kind, value) {
  const selected = studioSelectedObjects();
  if (selected.length !== 1) return;
  const item = selected[0].object;
  snapshot();
  if (kind === "name") item.name = value || item.name;
  else if (["x", "y", "width", "height"].includes(kind))
    item.geometry[kind] = Math.max(
      kind === "width" || kind === "height" ? 0.1 : -10_000,
      Number(value),
    );
  else if (kind === "fill") {
    item.style = item.style || { token_refs: {}, overrides: {} };
    item.style.overrides = item.style.overrides || {};
    item.style.overrides[item.kind === "tensor-glyph" ? "front_fill" : "fill"] =
      value;
  } else if (kind === "font_size") {
    item.style = item.style || { token_refs: {}, overrides: {} };
    item.style.overrides = item.style.overrides || {};
    item.style.overrides.font_size = Math.max(7, Number(value));
  } else if (kind === "locked") item.locked = !!value;
  else if (kind === "shape") {
    const shape = String(value)
      .split(",")
      .map((entry) => entry.trim())
      .filter((entry) => entry.length)
      .map((entry) =>
        entry === "?" ? null : /^\d+$/.test(entry) ? Number(entry) : entry,
      );
    const label = `[${shape.map((entry) => (entry == null ? "?" : entry)).join(", ")}]`;
    if (["graph_ir", "semantic_view"].includes(item.provenance?.kind)) {
      item.metadata.author_shape_override = shape;
      item.metadata.author_shape_override_label = label;
      item.metadata.shape_label_origin = "author_override";
    } else {
      item.metadata.tensor_shape = shape;
      item.metadata.shape_label = label;
      item.metadata.shape_label_origin = "author_annotation";
    }
  } else if (kind === "scale") item.metadata.geometry_scale = value;
  await refreshFigureStudio();
}

function studioInsertionTarget(role) {
  const active = studioFindLayer(state.figureActiveLayer);
  if (active && (!role || active.layer.role === role)) return active;
  const layer =
    studioLayers().find((item) => item.role === role) || studioLayers()[0];
  return layer ? studioFindLayer(layer.id) : null;
}

async function insertStudioObject(kind) {
  if (!state.figure) return;
  if (kind === "edge") return insertStudioEdge();
  const annotationKinds = new Set([
      "annotation",
      "equation",
      "callout",
      "region",
      "legend",
    ]),
    target = studioInsertionTarget(
      kind === "legend"
        ? "legend-caption"
        : annotationKinds.has(kind)
          ? "author-annotation"
          : "model-data",
    );
  if (!target || target.layer.locked || target.panel.locked)
    return toast("请选择一个未锁定的目标 Layer。", "warning");
  let name =
    {
      "tensor-glyph": "Tensor",
      "operator-glyph": "Operator",
      annotation: "Annotation",
      equation: "y = f(x)",
      callout: "Callout",
      region: "Region",
      legend: "Legend",
    }[kind] || kind;
  let shape = [null, "T", "D"];
  if (kind === "tensor-glyph") {
    const values = await requestTextEntries({
      title: "创建 Tensor Geometry glyph",
      description:
        "请输入真实 shape；动态/未知维使用符号或 ?。几何缩放不会改变标签。",
      fields: [
        { name: "name", label: "名称", value: "Tensor" },
        { name: "shape", label: "真实 shape", value: "B,T,D" },
      ],
    });
    if (!values) return;
    name = values.name;
    shape = values.shape.split(",").map((entry) => {
      const clean = entry.trim();
      return clean === "?" ? null : /^\d+$/.test(clean) ? Number(clean) : clean;
    });
  } else if (
    ["operator-glyph", "annotation", "equation", "callout", "legend"].includes(
      kind,
    )
  ) {
    const values = await requestTextEntries({
      title: `创建 ${kind}`,
      fields: [{ name: "name", label: "文本 / 名称", value: name }],
    });
    if (!values) return;
    name = values.name;
  }
  snapshot();
  const index = target.layer.objects.length,
    x = target.panel.geometry.x + 10 + (index % 4) * 18,
    y = target.panel.geometry.y + 18 + Math.floor(index / 4) * 16,
    object = {
      id: studioId("figure_object"),
      kind,
      name,
      geometry:
        kind === "callout"
          ? { x, y, x2: x + 18, y2: y + 8, width: 18, height: 8 }
          : kind === "annotation" || kind === "equation" || kind === "legend"
            ? { x, y }
            : {
                x,
                y,
                width: kind === "region" ? 28 : 12,
                height: kind === "region" ? 18 : 9,
                depth: 3,
              },
      provenance: studioAuthorProvenance(
        "User-authored Figure Studio object; it is not Graph IR provenance.",
      ),
      style: { token_refs: {}, overrides: { font_size: 7 } },
      locked: false,
      visible: true,
      manual_route:
        kind === "callout"
          ? [
              [x, y],
              [x + 18, y + 8],
            ]
          : [],
      constraints: [],
      metadata: {
        text: annotationKinds.has(kind) ? name : undefined,
        tensor_shape: kind === "tensor-glyph" ? shape : undefined,
        shape_label:
          kind === "tensor-glyph"
            ? `[${shape.map((entry) => (entry == null ? "?" : entry)).join(", ")}]`
            : undefined,
        layout: kind === "tensor-glyph" ? "auto" : undefined,
        geometry_scale: kind === "tensor-glyph" ? "normalized" : undefined,
        operator_family: kind === "operator-glyph" ? "generic" : undefined,
      },
      order: index,
    };
  Object.keys(object.metadata).forEach(
    (key) => object.metadata[key] === undefined && delete object.metadata[key],
  );
  target.layer.objects.push(object);
  state.figureSelection = new Set([object.id]);
  state.figureActiveLayer = target.layer.id;
  await refreshFigureStudio();
}

async function insertStudioEdge() {
  const selected = studioSelectedObjects();
  if (selected.length !== 2)
    return toast("创建连线前请选择同一 Panel 的两个对象。", "warning");
  if (selected[0].panel.id !== selected[1].panel.id)
    return toast("跨 Panel 关系请使用语义 annotation edge。", "warning");
  const target = studioInsertionTarget("author-annotation"),
    [source, destination] = selected.map((item) => item.object),
    sx = Number(source.geometry.x || 0) + Number(source.geometry.width || 0),
    sy =
      Number(source.geometry.y || 0) + Number(source.geometry.height || 0) / 2,
    tx = Number(destination.geometry.x || 0),
    ty =
      Number(destination.geometry.y || 0) +
      Number(destination.geometry.height || 0) / 2,
    id = studioId("figure_edge");
  snapshot();
  target.layer.objects.push({
    id,
    kind: "edge",
    name: `${source.name} → ${destination.name}`,
    geometry: { x: sx, y: sy, x2: tx, y2: ty },
    provenance: studioAuthorProvenance(
      "Author-created relationship; not asserted as a Graph IR model data edge.",
    ),
    style: { token_refs: {}, overrides: { dash: "4 3" } },
    locked: false,
    visible: true,
    manual_route: [
      [sx, sy],
      [(sx + tx) / 2, sy],
      [(sx + tx) / 2, ty],
      [tx, ty],
    ],
    constraints: [],
    metadata: {
      edge_semantics: "author-annotation",
      not_model_data_edge: true,
      endpoint_object_ids: [source.id, destination.id],
    },
    order: target.layer.objects.length,
  });
  state.figureSelection = new Set([id]);
  await refreshFigureStudio();
}

async function addStudioLayer() {
  const panel = studioSelectedObjects()[0]?.panel || studioPanels()[0];
  if (!panel) return;
  const values = await requestTextEntries({
    title: "新建 Layer",
    fields: [{ name: "name", label: "Layer 名称", value: "Author layer" }],
  });
  if (!values) return;
  snapshot();
  const layer = {
    id: studioId("figure_layer"),
    name: values.name,
    role: "author-annotation",
    objects: [],
    groups: [],
    visible: true,
    locked: false,
    order: panel.layers.length,
  };
  panel.layers.push(layer);
  state.figureActiveLayer = layer.id;
  await refreshFigureStudio();
}

async function reorderStudioLayer(delta) {
  const found = studioFindLayer(state.figureActiveLayer);
  if (!found || found.layer.locked) return;
  const ordered = found.panel.layers.slice().sort((a, b) => a.order - b.order),
    index = ordered.findIndex((item) => item.id === found.layer.id),
    targetIndex = Math.max(0, Math.min(ordered.length - 1, index + delta));
  if (targetIndex === index) return;
  snapshot();
  [ordered[index], ordered[targetIndex]] = [
    ordered[targetIndex],
    ordered[index],
  ];
  ordered.forEach((item, order) => (item.order = order));
  found.panel.layers = ordered;
  await refreshFigureStudio();
}

async function groupStudioObjects(ungroup = false) {
  const selected = studioSelectedObjects();
  if (!selected.length) return;
  const layer = selected[0].layer;
  if (selected.some((item) => item.layer.id !== layer.id))
    return toast("分组对象必须位于同一 Layer。", "warning");
  snapshot();
  if (ungroup) {
    (layer.groups || []).forEach(
      (group) =>
        (group.object_ids = group.object_ids.filter(
          (id) => !state.figureSelection.has(id),
        )),
    );
    layer.groups = layer.groups.filter((group) => group.object_ids.length);
  } else {
    (layer.groups || []).forEach(
      (group) =>
        (group.object_ids = group.object_ids.filter(
          (id) => !state.figureSelection.has(id),
        )),
    );
    layer.groups.push({
      id: studioId("figure_group"),
      name: `Group ${layer.groups.length + 1}`,
      object_ids: selected.map((item) => item.object.id),
      provenance: studioAuthorProvenance("Author-created visual group."),
      locked: false,
      visible: true,
      order: layer.groups.length,
    });
  }
  await refreshFigureStudio();
}

async function addStudioPanel() {
  const page = studioActivePage();
  if (!page || page.panels.length >= 8)
    return toast("Figure Studio 最多支持 A–H 八个 Panel。", "warning");
  snapshot();
  const label = [..."ABCDEFGH"].find(
      (candidate) => !page.panels.some((panel) => panel.label === candidate),
    ),
    id = studioId("figure_panel");
  page.panels.push({
    id,
    label,
    title: `Panel ${label}`,
    mode: "tensor-geometry",
    geometry: { x: page.margin_mm, y: page.margin_mm, width: 36, height: 36 },
    layers: studioDefaultLayers(id),
    constraints: [],
    locked: false,
    layout_mode: "grid",
    order: page.panels.length,
  });
  await layoutStudioPanels("grid", false);
}

async function layoutStudioPanels(mode, takeSnapshot = true) {
  const page = studioActivePage();
  if (!page) return;
  if (takeSnapshot) snapshot();
  arrangeStudioPagePanels(page, mode);
  await refreshFigureStudio();
}

function arrangeStudioPagePanels(page, mode) {
  if (mode === "free") {
    page.panels.forEach((panel) => (panel.layout_mode = "free"));
    return;
  }
  const count = page.panels.length,
    columns =
      mode === "horizontal"
        ? count
        : mode === "vertical"
          ? 1
          : Math.min(4, Math.ceil(Math.sqrt(count))),
    rows = Math.ceil(count / columns),
    margin = Number(page.margin_mm || 4),
    gap = Number(page.column_gap_mm || 4),
    width = (page.width_mm - 2 * margin - (columns - 1) * gap) / columns,
    height = (page.height_mm - 2 * margin - (rows - 1) * gap) / rows;
  page.panels.forEach((panel, index) => {
    panel.layout_mode = mode;
    const containsLockedContent = (panel.layers || []).some(
      (layer) =>
        (layer.locked && (layer.objects || []).length > 0) ||
        (layer.objects || []).some((object) => object.locked),
    );
    if (panel.locked || containsLockedContent) return;
    const row = Math.floor(index / columns),
      column = index % columns;
    transformStudioPanel(panel, {
      x: margin + column * (width + gap),
      y: margin + row * (height + gap),
      width,
      height,
    });
  });
}

function transformStudioPanel(panel, nextGeometry) {
  const previous = panel.geometry,
    scaleX = nextGeometry.width / Math.max(0.001, previous.width),
    scaleY = nextGeometry.height / Math.max(0.001, previous.height),
    mapX = (value) => nextGeometry.x + (Number(value) - previous.x) * scaleX,
    mapY = (value) => nextGeometry.y + (Number(value) - previous.y) * scaleY;
  for (const layer of panel.layers || [])
    for (const object of layer.objects || []) {
      const geometry = object.geometry || {};
      if (Number.isFinite(Number(geometry.x))) geometry.x = mapX(geometry.x);
      if (Number.isFinite(Number(geometry.y))) geometry.y = mapY(geometry.y);
      if (Number.isFinite(Number(geometry.x2))) geometry.x2 = mapX(geometry.x2);
      if (Number.isFinite(Number(geometry.y2))) geometry.y2 = mapY(geometry.y2);
      if (Number.isFinite(Number(geometry.width)))
        geometry.width = Number(geometry.width) * scaleX;
      if (Number.isFinite(Number(geometry.height)))
        geometry.height = Number(geometry.height) * scaleY;
      if ((object.manual_route || []).length)
        object.manual_route = object.manual_route.map(([x, y]) => [
          mapX(x),
          mapY(y),
        ]);
    }
  panel.geometry = nextGeometry;
}

async function alignStudioObjects(kind) {
  const selected = studioSelectedObjects().filter(
    (item) => !item.object.locked && !item.layer.locked && !item.panel.locked,
  );
  if (selected.length < 2) return toast("至少选择两个未锁定对象。", "warning");
  snapshot();
  if (kind === "align-left") {
    const x = Math.min(
      ...selected.map((item) => Number(item.object.geometry.x || 0)),
    );
    selected.forEach((item) => (item.object.geometry.x = x));
  } else {
    const ordered = selected
        .slice()
        .sort(
          (a, b) =>
            Number(a.object.geometry.x || 0) - Number(b.object.geometry.x || 0),
        ),
      first = Number(ordered[0].object.geometry.x || 0),
      last = Number(ordered.at(-1).object.geometry.x || 0),
      gap = (last - first) / Math.max(1, ordered.length - 1);
    ordered.forEach(
      (item, index) => (item.object.geometry.x = first + index * gap),
    );
  }
  const constraintKind = kind === "align-left" ? "align-left" : "equal-gap-x",
    targetIds = selected.map((item) => item.object.id),
    ownerPanel = selected[0].panel;
  ownerPanel.constraints = (ownerPanel.constraints || []).filter(
    (constraint) =>
      constraint.kind !== constraintKind ||
      !constraint.target_ids.some((id) => targetIds.includes(id)),
  );
  ownerPanel.constraints.push({
    kind: constraintKind,
    target_ids: targetIds,
    value: {
      scope:
        new Set(selected.map((item) => item.panel.id)).size > 1
          ? "cross-panel"
          : "panel",
    },
    locked: false,
  });
  await refreshFigureStudio();
}

async function toggleStudioLock() {
  const selected = studioSelectedObjects();
  if (!selected.length) return;
  snapshot();
  const next = !selected.every((item) => item.object.locked);
  selected.forEach((item) => (item.object.locked = next));
  await refreshFigureStudio();
}

async function applyStudioPreset(name) {
  const presets = {
    neurips: {
      "font.family": "DejaVu Sans, Arial, sans-serif",
      "line.data.color": "#334155",
      "color.tensor.front": "#dbeafe",
    },
    icml: {
      "font.family": "DejaVu Sans, Arial, sans-serif",
      "line.data.color": "#1f2937",
      "color.tensor.front": "#dcfce7",
    },
    ieee: {
      "font.family": "Times New Roman, DejaVu Serif, serif",
      "line.data.color": "#111827",
      "color.tensor.front": "#e5e7eb",
    },
    acm: {
      "font.family": "Libertinus Serif, DejaVu Serif, serif",
      "line.data.color": "#27272a",
      "color.tensor.front": "#fef3c7",
    },
    colorblind: {
      "line.data.color": "#0072b2",
      "line.annotation.color": "#d55e00",
      "color.tensor.front": "#56b4e9",
      "color.tensor.top": "#f0e442",
      "color.tensor.side": "#009e73",
    },
    grayscale: {
      "line.data.color": "#222222",
      "line.annotation.color": "#666666",
      "color.tensor.front": "#dddddd",
      "color.tensor.top": "#bbbbbb",
      "color.tensor.side": "#888888",
    },
  };
  snapshot();
  Object.assign(state.figure.design_tokens, presets[name] || presets.neurips);
  state.figure.theme = name;
  await refreshFigureStudio();
}

async function runStudioProof() {
  const sequence = ++studioRenderSequence,
    generation = sourceGeneration;
  const response = await api("/api/figure/validate", { figure: state.figure });
  if (sequence !== studioRenderSequence || generation !== sourceGeneration)
    return;
  state.figure = response.figure;
  state.figureProof = response.proof;
  renderStudioProof();
  activateStudioRightTab("proof");
  toast(
    response.proof.pass
      ? "Figure IR 预检通过；仍需最终 SVG Chrome oracle 严格验收。"
      : "Figure IR 预检发现需要处理的项目。",
    response.proof.pass ? "success" : "warning",
  );
}

function activateStudioLeftTab(name) {
  $$("[data-studio-left-tab]").forEach((button) =>
    button.classList.toggle("active", button.dataset.studioLeftTab === name),
  );
  $$("#figure-studio-left .studio-tab-body").forEach((body) =>
    body.classList.toggle("active", body.id === `studio-tab-${name}`),
  );
}

function activateStudioRightTab(name) {
  $$("[data-studio-right-tab]").forEach((button) =>
    button.classList.toggle("active", button.dataset.studioRightTab === name),
  );
  $$("#figure-studio-right > .studio-tab-body").forEach((body) =>
    body.classList.toggle("active", body.id === `studio-right-${name}`),
  );
}

async function importStudioSvg(file) {
  const generation = sourceGeneration;
  let sequence = ++studioRenderSequence;
  setBusy(true, "正在检查 SVG metadata…");
  try {
    const svg = await file.text();
    if (sequence !== studioRenderSequence || generation !== sourceGeneration)
      return;
    const body = await api("/api/figure/import-svg", {
      name: file.name.replace(/\.svg$/i, ""),
      svg,
    });
    if (sequence !== studioRenderSequence || generation !== sourceGeneration)
      return;
    snapshot();
    state.figure = body.figure;
    state.figureProof = body.proof;
    state.figureSelection.clear();
    sequence = studioRenderSequence;
    if (!(await refreshFigureStudio())) return;
    if (generation !== sourceGeneration) return;
    toast(
      body.native_roundtrip
        ? "已恢复 NN_DaVinci Panel、Layer、shape、样式与路由 metadata。"
        : "第三方 SVG 已作为 external vector group 导入；未声称恢复模型语义。",
      body.native_roundtrip ? "success" : "warning",
    );
  } catch (error) {
    if (sequence === studioRenderSequence && generation === sourceGeneration)
      toast(error.message, true);
  } finally {
    setBusy(false);
    $("#studio-svg-input").value = "";
  }
}

async function studioExport(format) {
  setBusy(true, `正在导出 Figure ${format.toUpperCase()}…`);
  try {
    synchronizeModelFigureProvenanceIndex();
    const response = await fetch(`/api/figure/export/${format}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ figure: state.figure }),
    });
    if (!response.ok) {
      const body = await response.json();
      throw new Error(
        body.hint ? `${body.message} — ${body.hint}` : body.message,
      );
    }
    const extension = format === "tikz" ? "tex" : format,
      disposition = response.headers.get("Content-Disposition") || "",
      serverName = disposition.match(/filename="?([^";]+)"?/i)?.[1],
      filename = serverName?.endsWith(".zip")
        ? `${safeName(state.figure.name)}-${format}-pages.zip`
        : `${safeName(state.figure.name)}.${extension}`;
    downloadBlob(await response.blob(), filename);
    toast(`${format.toUpperCase()} 已导出。`, "success");
  } catch (error) {
    toast(error.message, true);
  } finally {
    setBusy(false);
  }
}

async function exportStudioSubmissionPackage() {
  setBusy(true, "正在生成七格式投稿包…");
  try {
    synchronizeModelFigureProvenanceIndex();
    const project = localProjectDraft(),
      response = await fetch("/api/figure/submission-package", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ figure: state.figure, project }),
      });
    if (!response.ok) {
      const body = await response.json();
      throw new Error(
        body.hint ? `${body.message} — ${body.hint}` : body.message,
      );
    }
    downloadBlob(
      await response.blob(),
      `${safeName(state.figure.name)}-submission-package.zip`,
    );
    toast(
      "投稿包已导出：SVG/PDF/TikZ/PPTX/PNG/EPS/HTML，以及 project/caption/provenance/proof/policy。",
      "success",
    );
  } catch (error) {
    toast(error.message, true);
  } finally {
    setBusy(false);
  }
}

let lensAbortController = null;
function openStructureLens() {
  const nodes = state.graph?.nodes || [],
    renderedNodes = nodes.slice(0, 2_000),
    options = renderedNodes
      .map(
        (node) =>
          `<option value="${escapeAttr(node.id)}">${escapeHtml(node.name)} · ${escapeHtml(node.op_type)}</option>`,
      )
      .join("");
  $("#lens-source").innerHTML = options;
  $("#lens-target").innerHTML = options;
  if (renderedNodes.length > 1)
    $("#lens-target").selectedIndex = renderedNodes.length - 1;
  openDialog($("#structure-lens-dialog"), { trigger: document.activeElement });
}

async function runStructureLens(operation) {
  lensAbortController?.abort();
  const controller = new window.AbortController();
  lensAbortController = controller;
  const source = $("#lens-source").value,
    target = $("#lens-target").value,
    mapped = ["residual", "attention", "moe-routing"].includes(operation)
      ? "pathway"
      : operation,
    payload = {
      graph_id: state.graphId,
      graph: state.graphId ? undefined : state.graph,
      semantic_view: state.semanticData?.entities
        ? state.semanticData
        : undefined,
      node_id: operation === "upstream" ? target : source,
      source_id: source,
      target_id: target,
      kind: ["residual", "attention", "moe-routing"].includes(operation)
        ? operation
        : undefined,
      preview_panel: true,
      page_preset: state.figure?.metadata?.page_preset || "double-column",
      budget: {
        maximum_paths: Number($("#lens-max-paths").value),
        maximum_depth: Number($("#lens-max-depth").value),
        maximum_visits: 10_000,
        maximum_queue_entries: 10_000,
        maximum_generated_states: 50_000,
        maximum_memory_bytes: 64 * 1024 * 1024,
        timeout_seconds: 1,
      },
    };
  $("#structure-lens-results").innerHTML =
    '<p class="empty">正在执行有界查询…</p>';
  try {
    const response = await fetch(`/api/structure-lens/${mapped}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      signal: controller.signal,
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.message || response.statusText);
    if (controller.signal.aborted || lensAbortController !== controller) return;
    state.figureLensResult = result;
    renderStructureLensResult(result);
    applyStudioLensHighlight();
  } catch (error) {
    if (lensAbortController !== controller) return;
    if (error.name === "AbortError")
      $("#structure-lens-results").innerHTML =
        '<p class="empty">查询已取消；没有生成肯定性结论。</p>';
    else toast(error.message, true);
  } finally {
    if (lensAbortController === controller) lensAbortController = null;
  }
}

function renderStructureLensResult(result) {
  const preview = result.figure_panel_preview;
  $("#structure-lens-results").innerHTML =
    `<article class="lens-result-card"><strong>${escapeHtml(result.operation)} · ${escapeHtml(result.status)}</strong><p>${result.node_ids.length} nodes · ${result.edge_ids.length} edges · ${(result.paths || []).length} bounded paths</p>${result.metadata?.terminated_by ? `<p>terminated by ${escapeHtml(result.metadata.terminated_by)}</p>` : ""}${(result.paths || []).map((path) => `<code>${escapeHtml(path.join(" → "))}</code>`).join("<br>")}${(result.warnings || []).map((warning) => `<p class="error">${escapeHtml(warning.message)}</p>`).join("")}${preview?.available ? '<div class="inline-actions"><button id="lens-add-panel" class="primary">Add preview as Figure Panel</button></div><p><small>Preview only: the Figure is unchanged until Add is clicked.</small></p>' : `<p><small>${escapeHtml(preview?.reason || "No panel preview is available for this result.")}</small></p>`}<details><summary>Graph IR / source evidence</summary><pre>${escapeHtml(JSON.stringify(result.evidence, null, 2))}</pre></details></article>`;
  const addButton = $("#lens-add-panel");
  if (addButton) addButton.onclick = addStructureLensPreviewPanel;
}

function clearStructureLensResult() {
  state.figureLensResult = null;
  const results = $("#structure-lens-results");
  if (results)
    results.innerHTML =
      '<p class="empty">选择查询；不会枚举任意大图的全部简单路径。</p>';
  applyStudioLensHighlight();
}

async function addStructureLensPreviewPanel() {
  const preview = state.figureLensResult?.figure_panel_preview;
  if (!preview?.available || !preview.panel)
    return toast(
      "当前 Structure Lens 结果没有可添加的 Panel 预览。",
      "warning",
    );
  if (!state.figure)
    return toast("请先进入 Figure Studio，再显式添加该 Panel。", "warning");
  if ((state.figure.pages || []).length >= 64)
    return toast("Figure 已达到 64 页的有界上限。", "warning");

  snapshot();
  const panel = JSON.parse(JSON.stringify(preview.panel));
  const idMap = new Map();
  const remember = (oldId, kind) => {
    const fresh = studioId(kind);
    idMap.set(oldId, fresh);
    return fresh;
  };
  panel.id = remember(panel.id, "lens_panel");
  panel.label = "A";
  panel.order = 0;
  for (const layer of panel.layers || []) {
    layer.id = remember(layer.id, "lens_layer");
    for (const group of layer.groups || [])
      group.id = remember(group.id, "lens_group");
    for (const object of layer.objects || [])
      object.id = remember(object.id, "lens_object");
  }
  const remapTargets = (constraint) => {
    constraint.target_ids = (constraint.target_ids || []).map(
      (id) => idMap.get(id) || id,
    );
  };
  (panel.constraints || []).forEach(remapTargets);
  for (const layer of panel.layers || []) {
    for (const group of layer.groups || [])
      group.object_ids = (group.object_ids || []).map(
        (id) => idMap.get(id) || id,
      );
    for (const object of layer.objects || []) {
      (object.constraints || []).forEach(remapTargets);
      if (object.metadata?.endpoint_object_ids)
        object.metadata.endpoint_object_ids =
          object.metadata.endpoint_object_ids.map((id) => idMap.get(id) || id);
    }
  }
  const pageSpec = preview.page || {};
  const pageNumber = state.figure.pages.length + 1;
  const lensPageId = studioId("lens_page");
  state.figure.pages.push({
    id: lensPageId,
    title: `Structure Lens · ${state.figureLensResult.operation || "result"}`,
    width_mm: Number(pageSpec.width_mm || state.figure.pages[0].width_mm),
    height_mm: Number(pageSpec.height_mm || state.figure.pages[0].height_mm),
    panels: [panel],
    margin_mm: Number(pageSpec.margin_mm ?? 4),
    columns: 1,
    column_gap_mm: Number(pageSpec.column_gap_mm ?? 4),
    baseline_grid_pt: Number(pageSpec.baseline_grid_pt ?? 4),
    order: pageNumber - 1,
  });
  state.figureActivePage = lensPageId;
  state.projectMeta.figure_ir = state.figure;
  state.workspaceMode = "figure";
  state.figureSelection.clear();
  state.figureActiveLayer =
    (panel.layers || []).find((layer) => layer.role === "author-annotation")
      ?.id ||
    panel.layers?.[0]?.id ||
    null;
  applyWorkspaceMode();
  await refreshFigureStudio();
  toast(
    `Structure Lens 预览已通过显式 Add 添加为第 ${pageNumber} 页 Panel。`,
    "success",
  );
}

function applyStudioLensHighlight() {
  const result = state.figureLensResult;
  $$("#canvas [data-figure-object-id]").forEach((element) =>
    element.classList.remove("studio-lens-highlight"),
  );
  if (!result) return;
  const evidence = new Set([
    ...(result.node_ids || []),
    ...(result.edge_ids || []),
  ]);
  for (const item of studioObjects()) {
    const ids = [
      item.provenance?.source_id,
      ...(item.provenance?.graph_ir_ids || []),
    ];
    if (ids.some((id) => evidence.has(id)))
      $$(`[data-figure-object-id="${CSS.escape(item.id)}"]`).forEach(
        (element) => element.classList.add("studio-lens-highlight"),
      );
  }
}

async function runStructureWarnings() {
  const generation = sourceGeneration;
  try {
    const result = await api("/api/structure-lens/warnings", {
      graph: state.graph,
    });
    if (generation !== sourceGeneration) return;
    state.figureLensResult = result;
    openStructureLens();
    renderStructureLensResult(result);
    applyStudioLensHighlight();
  } catch (error) {
    if (generation === sourceGeneration) toast(error.message, true);
  }
}

function deleteStudioSelection() {
  const selected = new Set(state.figureSelection);
  if (!selected.size) return;
  const locked = studioSelectedObjects().some(
    (item) => item.object.locked || item.layer.locked || item.panel.locked,
  );
  if (locked) return toast("选择中包含锁定对象，删除被阻止。", "warning");
  snapshot();
  for (const layer of studioLayers()) {
    layer.objects = layer.objects.filter((item) => !selected.has(item.id));
    (layer.groups || []).forEach(
      (group) =>
        (group.object_ids = group.object_ids.filter((id) => !selected.has(id))),
    );
    layer.groups = (layer.groups || []).filter(
      (group) => group.object_ids.length,
    );
  }
  state.figureSelection.clear();
  void refreshFigureStudio();
}

async function handleStudioAction(action) {
  if (action === "new-from-graph") return enterFigureStudio({ rebuild: true });
  if (action === "save-project") return performExportFormat("project");
  if (action === "undo") return undo();
  if (action === "redo") return redo();
  if (action === "group") return groupStudioObjects(false);
  if (action === "ungroup") return groupStudioObjects(true);
  if (action === "toggle-guides") {
    state.figureIncludeGuides = !state.figureIncludeGuides;
    return refreshFigureStudio();
  }
  if (action === "grayscale") {
    $("#canvas").classList.toggle("grayscale-check");
    return toast(
      "灰度预览已切换；Proof 中的 shape/line semantics 保持不变。",
      "success",
    );
  }
  if (action === "contrast") return runStudioProof();
  if (action === "add-panel") return addStudioPanel();
  if (action.startsWith("layout-")) return layoutStudioPanels(action.slice(7));
  if (action === "align-left" || action === "distribute-x")
    return alignStudioObjects(action);
  if (action === "toggle-lock") return toggleStudioLock();
  if (action === "structure-lens") return openStructureLens();
  if (action === "structure-warnings") return runStructureWarnings();
  if (action === "proof") return runStudioProof();
  if (action === "submission-package") return exportStudioSubmissionPackage();
}

function initializeFigureStudio() {
  $("#figure-studio-button").onclick = () => enterFigureStudio();
  $("#studio-exit").onclick = leaveFigureStudio;
  $$("[data-studio-left-tab]").forEach(
    (button) =>
      (button.onclick = () =>
        activateStudioLeftTab(button.dataset.studioLeftTab)),
  );
  $$("[data-studio-right-tab]").forEach(
    (button) =>
      (button.onclick = () =>
        activateStudioRightTab(button.dataset.studioRightTab)),
  );
  $$("[data-studio-insert]").forEach(
    (button) =>
      (button.onclick = () => insertStudioObject(button.dataset.studioInsert)),
  );
  $$("[data-studio-action]").forEach(
    (button) =>
      (button.onclick = () => {
        button.closest("details")?.removeAttribute("open");
        void handleStudioAction(button.dataset.studioAction);
      }),
  );
  $$("[data-studio-export]").forEach(
    (button) =>
      (button.onclick = () => {
        button.closest("details")?.removeAttribute("open");
        void studioExport(button.dataset.studioExport);
      }),
  );
  $$("[data-studio-page-action]").forEach(
    (button) =>
      (button.onclick = () =>
        void handleStudioPageAction(button.dataset.studioPageAction)),
  );
  $("#studio-page-select").onchange = (event) =>
    selectStudioPage(event.target.value);
  $("#studio-page-preset").onchange = (event) => {
    const dimensions = {
      "single-column": [88, 118],
      "double-column": [178, 118],
      "a4-portrait": [210, 297],
      "a4-landscape": [297, 210],
    }[event.target.value];
    if (!dimensions) return;
    $("#studio-page-width").value = dimensions[0];
    $("#studio-page-height").value = dimensions[1];
    void handleStudioPageAction("resize");
  };
  $$("[data-studio-menu]").forEach((details) =>
    details.addEventListener("toggle", () => {
      if (!details.open) return;
      $$("[data-studio-menu]").forEach((other) => {
        if (other !== details) other.removeAttribute("open");
      });
    }),
  );
  $("#studio-svg-input").onchange = (event) =>
    event.target.files[0] && importStudioSvg(event.target.files[0]);
  $("#studio-layer-new").onclick = addStudioLayer;
  $("#studio-layer-up").onclick = () => reorderStudioLayer(-1);
  $("#studio-layer-down").onclick = () => reorderStudioLayer(1);
  const propertyBindings = {
    "studio-prop-name": "name",
    "studio-prop-x": "x",
    "studio-prop-y": "y",
    "studio-prop-width": "width",
    "studio-prop-height": "height",
    "studio-prop-fill": "fill",
    "studio-prop-font-size": "font_size",
    "studio-prop-locked": "locked",
    "studio-prop-shape": "shape",
    "studio-prop-scale": "scale",
  };
  Object.entries(propertyBindings).forEach(([id, key]) => {
    $(`#${id}`).onchange = (event) =>
      updateStudioProperty(
        key,
        event.target.type === "checkbox"
          ? event.target.checked
          : event.target.value,
      );
  });
  $("#studio-theme-preset").onchange = (event) =>
    applyStudioPreset(event.target.value);
  $("#studio-token-font").onchange = async (event) => {
    snapshot();
    state.figure.design_tokens["font.family"] = event.target.value;
    await refreshFigureStudio();
  };
  $("#studio-token-line-width").onchange = async (event) => {
    snapshot();
    state.figure.design_tokens["line.width.pt"] = Math.max(
      0.1,
      Number(event.target.value),
    );
    await refreshFigureStudio();
  };
  $$("[data-lens-operation]").forEach(
    (button) =>
      (button.onclick = () => runStructureLens(button.dataset.lensOperation)),
  );
  $("#lens-cancel").onclick = () => lensAbortController?.abort();
  document.addEventListener(
    "keydown",
    (event) => {
      if (
        state.workspaceMode !== "figure" ||
        /INPUT|SELECT|TEXTAREA/.test(event.target.tagName)
      )
        return;
      if (event.key === "Delete" || event.key === "Backspace") {
        event.preventDefault();
        event.stopImmediatePropagation();
        deleteStudioSelection();
      }
    },
    true,
  );
  applyWorkspaceMode();
}

function syncInspectorPinControl() {
  const pinned = uiPreferences.inspectorPinned !== false,
    control = $("#inspector-pin-button");
  document.documentElement.dataset.inspectorPinned = String(pinned);
  control.setAttribute("aria-pressed", String(pinned));
  control.setAttribute(
    "aria-label",
    pinned ? "Unpin Inspector properties" : "Pin Inspector properties",
  );
  control.title = control.getAttribute("aria-label");
  $("#inspector-pin-label").textContent = pinned ? "Pinned" : "Pin";
}

function initializeApplicationState() {
  const saveElement = $("#project-save-state"),
    actionRegion = $("#action-status-region"),
    actionMessage = $("#action-status-message"),
    actionRetry = $("#action-status-retry");
  workspaceMachine.addEventListener("savestatechange", (event) => {
    const save = event.detail;
    saveElement.dataset.state = save.state;
    saveElement.title = save.message;
    $("span", saveElement).textContent =
      {
        clean: "Saved",
        dirty: "Unsaved",
        saving: "Saving…",
        saved: "Saved",
        error: "Save error",
        conflict: "Conflict",
      }[save.state] || save.state;
    if (["error", "conflict"].includes(save.state)) {
      actionRegion.classList.remove("hidden");
      actionRegion.dataset.state = save.state;
      actionMessage.textContent = save.message;
      actionRetry.classList.toggle("hidden", typeof save.retry !== "function");
      actionRetry.onclick = () => save.retry?.();
    } else if (["error", "conflict"].includes(actionRegion.dataset.state)) {
      actionRegion.classList.add("hidden");
    }
  });
  workspaceMachine.addEventListener("actionstatechange", (event) => {
    const action = event.detail;
    actionRegion.dataset.state = action.state;
    actionMessage.textContent = action.message;
    actionRegion.classList.toggle("hidden", action.state === "idle");
    actionRetry.classList.toggle("hidden", typeof action.retry !== "function");
    actionRetry.onclick = () => action.retry?.();
    if (["success", "warning"].includes(action.state))
      setTimeout(() => {
        if (actionRegion.dataset.state === action.state)
          actionRegion.classList.add("hidden");
      }, 3200);
  });
  window.NNDVState.installResizableSidebars({
    workspace: $(".workspace"),
    left: $("#workspace-panel"),
    right: $("#inspector-panel"),
    preferences: uiPreferences,
  });
  syncInspectorPinControl();
  $("#inspector-pin-button").onclick = () => {
    uiPreferences.inspectorPinned = !uiPreferences.inspectorPinned;
    window.NNDVState.applyPreferences(uiPreferences);
    window.NNDVState.persistPreferences(uiPreferences);
    syncInspectorPinControl();
    markProjectDirty(
      uiPreferences.inspectorPinned
        ? "Inspector properties pinned"
        : "Inspector properties unpinned",
    );
    scheduleAutosave();
    window.requestAnimationFrame(() => sceneRenderer?.resize());
  };
  $("#app-theme-select").value = uiPreferences.theme;
  $("#app-density-select").value = uiPreferences.density;
  $("#app-theme-select").onchange = (event) => {
    uiPreferences.theme = event.target.value;
    window.NNDVState.applyPreferences(uiPreferences);
    window.NNDVState.persistPreferences(uiPreferences);
    markProjectDirty("Application theme changed");
    scheduleAutosave();
    sceneRenderer?.render();
  };
  $("#app-density-select").onchange = (event) => {
    uiPreferences.density = event.target.value;
    window.NNDVState.applyPreferences(uiPreferences);
    window.NNDVState.persistPreferences(uiPreferences);
    markProjectDirty("Application density changed");
    scheduleAutosave();
    sceneRenderer?.resize();
  };
  $$("[data-workspace]").forEach((button) => {
    button.onclick = () => switchWorkspace(button.dataset.workspace);
  });
  workspaceMachine.hydrate({
    workspace: state.workspaceMode,
    contexts: state.projectMeta?.canvas_state?.workspace_contexts || {},
  });
  applyWorkspaceMode();
}

async function init() {
  renderPalette();
  const body = await api("/api/state");
  state.graph = body.graph;
  state.graphId = body.graph_id;
  state.comments = body.comments || [];
  state.capabilities = body.capabilities;
  state.tasks = body.tasks || [];
  state.lazySummary = body.summary;
  updateTrialStatus(body.trial || { enabled: false, active_session_id: null });
  state.lazy = body.graph.nodes.length > 2000;
  if (state.lazy)
    state.semanticLevel = authorSemanticLevel(body.summary.recommended_level);
  let projectRecoveryError = null;
  let storedProjectDraft = null;
  try {
    storedProjectDraft = window.localStorage.getItem("nndv-autosaved-project");
    const draft = JSON.parse(storedProjectDraft || "null");
    if (draft?.graph) {
      const validated = await validatePersistedProject(draft);
      hydrateProjectDraft(validated);
    }
  } catch (error) {
    projectRecoveryError = error;
    state.autosaveBlockedByInvalidProject = Boolean(storedProjectDraft);
  }
  $("#theme-select").innerHTML = body.capabilities.themes
    .map((v) => `<option value="${v}">${v}</option>`)
    .join("");
  $("#layout-select").innerHTML = ["auto", ...body.capabilities.layouts]
    .map((v) => `<option value="${v}">${v}</option>`)
    .join("");
  syncControls();
  renderTasks();
  state.initialized = true;
  if (projectRecoveryError)
    toast(
      `自动保存项目未通过 Graph / Semantic View / Figure IR 校验，已拒绝恢复：${projectRecoveryError.message}`,
      true,
    );
  initializeSurfaceManager();
  initializeTextEntryDialog();
  initializeToolbarMenus();
  initializeFigureStudio();
  initializeApplicationState();
  initializeCommandRegistry();
  $("#autosave-keep-stored").onclick = () => resolveAutosaveConflict("stored");
  $("#autosave-overwrite-stored").onclick = () =>
    resolveAutosaveConflict("current");
  $("#start-button").onclick = openStartCenter;
  $("#generate-paper-button").onclick = generatePaperDraft;
  $("#composer-button").onclick = openComposer;
  $("#scene-studio-button").onclick = () => enterSceneStudio();
  $("#composer-title").oninput = updateComposerControlsFromDialog;
  $("#composer-page").onchange = updateComposerControlsFromDialog;
  $("#composer-arrangement").onchange = updateComposerControlsFromDialog;
  $("#command-button").onclick = openCommandPalette;
  $("#issues-button").onclick = () => openDrawer("issue-center");
  $("#help-button").onclick = () => openDrawer("help-center");
  $("#continue-start").onclick = () => $("#start-center").close();
  $("#shortcuts-button").onclick = () =>
    openDialog($("#shortcuts-dialog"), { trigger: $("#shortcuts-button") });
  $("#tutorial-button").onclick = () => {
    $("#start-center").close();
    openDrawer("help-center");
    toast("教程已打开：选择示例 → 钻取 → 生成候选 → Composer → 导出");
  };
  $$("[data-start-action]").forEach(
    (button) =>
      (button.onclick = () => {
        const action = button.dataset.startAction;
        if (action === "blank-2d") {
          $("#start-center").close();
          $("#new-button").click();
          state.page = "double-column";
          state.projectMeta.paper_workflow = { version: "1.0" };
        } else if (action === "blank-3d") {
          $("#start-center").close();
          void enterSceneStudio({ blank: true });
        } else if (action === "import" || action === "open") {
          $("#start-center").close();
          $("#file-input").click();
        } else if (action === "composer") {
          $("#start-center").close();
          openComposer();
        }
      }),
  );
  $("#composer-add-panel").onclick = () => {
    if (state.composer.panels.length >= 8)
      return toast("Figure Composer 最多支持 A–H 八个 Panel。", "warning");
    const id = [..."ABCDEFGH"].find(
      (candidate) =>
        !state.composer.panels.some((panel) => panel.id === candidate),
    );
    const source = state.composer.panels[0].graph;
    state.composer.panels.push(
      composerPanel(id, `${id} detail`, source, "operation"),
    );
    state.composerProof = null;
    persistComposerState();
    renderComposerPanels();
  };
  $("#composer-preview").onclick = previewComposer;
  $("#composer-export").onclick = exportComposerBundle;
  $("#command-search").oninput = (event) =>
    renderCommandResults(event.target.value);
  $$(".tab").forEach(
    (tab) => (tab.onclick = () => activateWorkspaceTab(tab.dataset.tab)),
  );
  $("#palette-search").oninput = (e) => renderPalette(e.target.value);
  $("#graph-search").oninput = renderTree;
  $("#file-input").onchange = (e) =>
    e.target.files[0] && importFile(e.target.files[0]);
  $("#compare-input").onchange = (e) =>
    e.target.files[0] && compareFile(e.target.files[0]);
  $("#new-button").onclick = () => {
    snapshot();
    state.graph = emptyGraphDocument();
    state.graphId = null;
    state.viewGraph = null;
    state.layout = null;
    state.comments = [];
    state.projectMeta = {};
    resetComposerForNewSource();
    state.collapsed.clear();
    state.focus.clear();
    state.page = "auto";
    state.perspective = false;
    state.animate = false;
    state.themeOverrides = {};
    state.layoutOptions = { rank_gap: 88, node_gap: 34 };
    state.semanticLevel = null;
    state.semanticView = "faithful";
    state.semanticData = null;
    state.sourceSelection.clear();
    state.lazy = false;
    syncControls();
    refresh();
  };
  $("#undo-button").onclick = undo;
  $("#redo-button").onclick = redo;
  $("#analyze-button").onclick = analyze;
  $("#layout-button").onclick = async () => {
    if (!requireGraphNodes("自动布局")) return;
    const generation = sourceGeneration;
    snapshot();
    await submitTask(
      "layout",
      {
        graph: state.viewGraph || state.graph,
        theme: state.theme,
        page: state.page,
        algorithm: state.algorithm,
        direction: state.direction,
        layout: state.layout,
      },
      async (result) => {
        if (generation !== sourceGeneration) return;
        state.viewGraph = result.graph;
        state.layout = result.layout;
        state.fixedLayout = true;
        await refresh(false);
      },
    );
  };
  $("#semantic-level").onchange = (event) => switchSemantic(event.target.value);
  $("#semantic-view").onchange = (event) =>
    switchSemantic(state.semanticLevel || "framework", event.target.value);
  $("#semantic-up").onclick = semanticUp;
  $("#restore-graph").onclick = () => switchSemantic("raw");
  $("#optimize-button").onclick = () => {
    if (!state.layout || !state.viewGraph)
      return toast("没有可优化的布局：请先打开模型并完成布局。", "warning");
    openDialog($("#paper-workflow"), { trigger: $("#paper-menu-button") });
  };
  $("#generate-suggestions").onclick = () => generatePaperSuggestions(false);
  $("#fix-readability").onclick = () => generatePaperSuggestions(true);
  $("#tasks-button").onclick = () => {
    openDrawer("task-center");
    void refreshTasks();
  };
  $("#trial-button").onclick = openTrialMode;
  $("#start-trial-mode").onclick = () => {
    $("#start-center").close();
    openTrialMode();
  };
  $("#trial-consent-apply").onclick = () => applyTrialConsent(true);
  $("#trial-own-model").onclick = startParticipantTrial;
  $("#trial-consent-revoke").onclick = () => applyTrialConsent(false);
  $("#trial-download").onclick = downloadTrialJson;
  $("#trial-finish").onclick = () => finishTrial("completed");
  $("#trial-abandon").onclick = () => finishTrial("abandoned");
  $("#wizard-cancel").onclick = () => {
    state.pendingImport = null;
    $("#import-wizard").close();
  };
  $("#wizard-import").onclick = confirmImport;
  $("#trust-confirm input").onchange = (event) => {
    $("#wizard-import").disabled = !event.target.checked;
  };
  $("#fit-button").onclick = () => applyViewBox(true);
  $("#animate-button").onclick = () => {
    snapshot();
    state.animate = !state.animate;
    $("#canvas svg")?.classList.toggle("flowing", state.animate);
    $("#animate-button").classList.toggle("primary", state.animate);
  };
  $("#perspective-button").onclick = () => {
    snapshot();
    state.perspective = !state.perspective;
    syncControls();
  };
  $("#theme-select").onchange = (e) => {
    snapshot();
    state.theme = e.target.value;
    syncControls();
    refresh(false);
  };
  $("#page-select").onchange = (e) => {
    snapshot();
    state.page = e.target.value;
    state.layout = null;
    refresh(true);
  };
  $("#layout-select").onchange = (e) => {
    snapshot();
    state.algorithm = e.target.value;
    state.layout = null;
    refresh(true);
  };
  $("#direction-select").onchange = (e) => {
    snapshot();
    state.direction = e.target.value;
    state.layout = null;
    refresh(true);
  };
  const themeFields = {
    "style-font": "font_family",
    "style-font-size": "font_size",
    "style-font-weight": "font_weight",
    "style-radius": "node_radius",
    "style-node-opacity": "node_opacity",
    "style-background": "background",
    "style-node-fill": "node_fill",
    "style-border": "border",
    "style-edge": "edge",
    "style-accent": "accent",
    "style-edge-width": "edge_width",
    "style-edge-arrow": "edge_arrow",
    "style-parameter-format": "parameter_format",
    "style-flops-format": "flops_format",
  };
  Object.entries(themeFields).forEach(([id, key]) => {
    $(`#${id}`).onchange = (e) => {
      snapshot();
      state.themeOverrides[key] =
        e.target.type === "number" ? Number(e.target.value) : e.target.value;
      refresh(false);
    };
  });
  $("#style-edge-dashed").onchange = (e) => {
    snapshot();
    state.themeOverrides.edge_dash = e.target.checked ? "6 4" : "";
    refresh(false);
  };
  $("#style-shape-brackets").onchange = (e) => {
    snapshot();
    state.themeOverrides.shape_brackets = e.target.checked;
    refresh(false);
  };
  $("#style-rank-gap").onchange = (e) => {
    snapshot();
    state.layoutOptions.rank_gap = Number(e.target.value);
    state.layout = null;
    refresh(true);
  };
  $("#style-node-gap").onchange = (e) => {
    snapshot();
    state.layoutOptions.node_gap = Number(e.target.value);
    state.layout = null;
    refresh(true);
  };
  $("#style-node-icon").onchange = (e) => {
    const node = state.graph.nodes.find((item) => state.selection.has(item.id));
    if (!node) return;
    snapshot();
    node.attributes = node.attributes || {};
    if (e.target.value) node.attributes.icon_href = e.target.value;
    else {
      delete node.attributes.icon_href;
      delete node.attributes.image_href;
    }
    markGraphModelModified();
    refresh(true);
  };
  $("#metric-select").onchange = (e) => {
    state.metric = e.target.value;
    refresh(false);
  };
  $$(".display-options input").forEach(
    (el) => (el.onchange = () => refresh(false)),
  );
  $$("#export-menu button[data-format]").forEach(
    (button) => (button.onclick = () => exportFormat(button.dataset.format)),
  );
  $("#scene-batch-export").onclick = openSceneBatchDialog;
  $("#scene-batch-start").onclick = () =>
    startSceneBatchExport().catch((error) => {
      workspaceMachine.setAction("scene-batch", "error", {
        message: `Scene batch failed: ${error.message}`,
      });
      toast(`Scene 批量导出失败：${error.message}`, true);
    });
  $("#scene-batch-cancel").onclick = () => sceneBatchController?.abort();
  $("#scene-batch-dialog").addEventListener("close", () =>
    sceneBatchController?.abort(),
  );
  $("#canvas-toolbar").onclick = (e) => {
    const action = e.target.closest("[data-action]")?.dataset.action;
    const operation = ["zoom", "arrow", "image"].includes(action)
      ? addRichAnnotation(action)
      : action
        ? canvasAction(action)
        : null;
    operation?.catch((error) => toast(error.message, true));
  };
  $("#zoom-in").onclick = () => zoomBy(1.2);
  $("#zoom-out").onclick = () => zoomBy(0.8);
  const shell = $("#canvas-shell");
  shell.addEventListener("dragover", (e) => e.preventDefault());
  shell.addEventListener("drop", (e) => {
    e.preventDefault();
    const file = e.dataTransfer.files[0];
    if (file) return importFile(file);
    const raw = e.dataTransfer.getData("application/x-nndv");
    if (raw) {
      const rect = shell.getBoundingClientRect(),
        box = currentViewBox(),
        x = box.x + ((e.clientX - rect.left) / rect.width) * box.width,
        y = box.y + ((e.clientY - rect.top) / rect.height) * box.height;
      addPaletteNode(JSON.parse(raw), x, y);
    }
  });
  document.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
      e.preventDefault();
      openCommandPalette();
      return;
    }
    if (commandRegistry?.handleShortcut(e)) return;
    if (/INPUT|SELECT|TEXTAREA/.test(e.target.tagName)) return;
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "z") {
      e.preventDefault();
      e.shiftKey ? redo() : undo();
    } else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "y") {
      e.preventDefault();
      redo();
    } else if (
      e.key === "Delete" &&
      state.workspaceMode === "graph" &&
      state.selection.size
    ) {
      snapshot();
      const nodeIds = new Set(selectedNodeIds()),
        edgeIds = new Set(selectedEdgeIds());
      state.graph.nodes = state.graph.nodes.filter(
        (node) => !nodeIds.has(node.id),
      );
      state.graph.edges = state.graph.edges.filter(
        (edge) =>
          !edgeIds.has(edge.id) &&
          !nodeIds.has(edge.source) &&
          !nodeIds.has(edge.target),
      );
      state.graph.subgraphs.forEach(
        (group) =>
          (group.node_ids = group.node_ids.filter((id) => !nodeIds.has(id))),
      );
      const valid = new Set([
        ...state.graph.nodes.map((node) => node.id),
        ...state.graph.edges.map((edge) => edge.id),
        ...state.graph.subgraphs.map((group) => group.id),
      ]);
      state.graph.constraints = state.graph.constraints
        .map((item) => ({
          ...item,
          target_ids: item.target_ids.filter((id) => valid.has(id)),
        }))
        .filter((item) => item.target_ids.length);
      state.graph.annotations = state.graph.annotations
        .map((item) => ({
          ...item,
          target_ids: item.target_ids.filter((id) => valid.has(id)),
        }))
        .filter(
          (item) =>
            !item.target_ids.length ||
            item.target_ids.some((id) => valid.has(id)),
        );
      const validNodeIds = new Set(state.graph.nodes.map((node) => node.id));
      state.focus = new Set(
        [...state.focus].filter((id) => validNodeIds.has(id)),
      );
      state.sourceSelection = new Set(
        [...state.sourceSelection].filter((id) => validNodeIds.has(id)),
      );
      Object.values(state.viewMemory).forEach((memory) => {
        if (Array.isArray(memory?.selection))
          memory.selection = memory.selection.filter((id) =>
            validNodeIds.has(id),
          );
      });
      markGraphModelModified();
      state.selection.clear();
      refresh(true);
    } else if (
      state.workspaceMode === "graph" &&
      (e.ctrlKey || e.metaKey) &&
      e.key.toLowerCase() === "d"
    ) {
      e.preventDefault();
      canvasAction("duplicate");
    } else if (e.key === "Escape") {
      const openDialog = $$("dialog[open]").at(-1);
      if (openDialog) openDialog.close();
      else select(null);
    }
  });
  updateHistoryButtons();
  await refresh(!state.fixedLayout);
  updateIssues();
}
init().catch((error) => toast(error.message, true));
