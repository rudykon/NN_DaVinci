(function initializeStateMachine(global) {
  "use strict";

  const WORKSPACES = new Set(["graph", "figure", "scene"]);
  const SAVE_STATES = new Set([
    "clean",
    "dirty",
    "saving",
    "saved",
    "error",
    "conflict",
  ]);
  const ACTION_STATES = new Set([
    "idle",
    "busy",
    "success",
    "warning",
    "error",
  ]);
  const STORAGE_KEY = "nndv-ui-preferences-0.7";

  function copy(value) {
    return value === undefined ? undefined : JSON.parse(JSON.stringify(value));
  }

  function emit(target, name, detail) {
    target.dispatchEvent(new global.CustomEvent(name, { detail }));
  }

  class WorkspaceStateMachine extends global.EventTarget {
    constructor(initial = {}) {
      super();
      this.workspace = WORKSPACES.has(initial.workspace)
        ? initial.workspace
        : "graph";
      this.contexts = {
        graph: {},
        figure: {},
        scene: {},
        ...copy(initial.contexts || {}),
      };
      this.save = {
        state: "clean",
        message: "All changes saved",
        revision: null,
        localRevision: null,
        updatedAt: null,
        retry: null,
      };
      this.actions = new Map();
    }

    transition(next, context) {
      if (!WORKSPACES.has(next)) throw new Error(`Unknown workspace: ${next}`);
      const previous = this.workspace;
      if (context) this.contexts[previous] = copy(context);
      this.workspace = next;
      emit(this, "workspacechange", {
        previous,
        workspace: next,
        context: copy(this.contexts[next]),
      });
      return copy(this.contexts[next]);
    }

    setContext(workspace, context) {
      if (!WORKSPACES.has(workspace))
        throw new Error(`Unknown workspace: ${workspace}`);
      this.contexts[workspace] = copy(context || {});
      emit(this, "contextchange", {
        workspace,
        context: copy(this.contexts[workspace]),
      });
    }

    patchContext(workspace, patch) {
      this.setContext(workspace, {
        ...(this.contexts[workspace] || {}),
        ...copy(patch || {}),
      });
    }

    setSaveState(next, details = {}) {
      if (!SAVE_STATES.has(next))
        throw new Error(`Unknown save state: ${next}`);
      this.save = {
        ...this.save,
        ...details,
        state: next,
        updatedAt: new Date().toISOString(),
      };
      const snapshot = {
        ...copy({ ...this.save, retry: null }),
        retry: this.save.retry,
      };
      emit(this, "savestatechange", snapshot);
      return snapshot;
    }

    markDirty(message = "Unsaved changes") {
      return this.setSaveState("dirty", { message, retry: null });
    }

    markConflict(remoteRevision, retry) {
      return this.setSaveState("conflict", {
        message: "A newer project revision exists",
        remoteRevision,
        retry,
      });
    }

    setAction(id, next, details = {}) {
      if (!ACTION_STATES.has(next))
        throw new Error(`Unknown action state: ${next}`);
      const value = {
        id,
        state: next,
        message: details.message || "",
        retry: details.retry || null,
        updatedAt: new Date().toISOString(),
      };
      this.actions.set(id, value);
      const snapshot = {
        ...copy({ ...value, retry: null }),
        retry: value.retry,
      };
      emit(this, "actionstatechange", snapshot);
      return snapshot;
    }

    async runAction(id, operation, labels = {}) {
      this.setAction(id, "busy", { message: labels.busy || "Working…" });
      try {
        const result = await operation();
        this.setAction(id, labels.warning ? "warning" : "success", {
          message: labels.warning || labels.success || "Complete",
        });
        return result;
      } catch (error) {
        this.setAction(id, "error", {
          message: error.message,
          retry: () => this.runAction(id, operation, labels),
        });
        throw error;
      }
    }

    serialize() {
      return {
        version: "1.0",
        workspace: this.workspace,
        contexts: copy(this.contexts),
        save: { ...copy(this.save), retry: undefined },
      };
    }

    hydrate(value) {
      if (!value || typeof value !== "object") return;
      if (WORKSPACES.has(value.workspace)) this.workspace = value.workspace;
      for (const name of WORKSPACES) {
        if (value.contexts?.[name])
          this.contexts[name] = copy(value.contexts[name]);
      }
      if (SAVE_STATES.has(value.save?.state))
        this.save = { ...this.save, ...copy(value.save), retry: null };
    }
  }

  function readPreferences() {
    const defaults = {
      theme: "light",
      density: "balanced",
      inspectorPinned: true,
      sidebars: { left: 245, right: 270 },
    };
    try {
      const saved = JSON.parse(
        global.localStorage.getItem(STORAGE_KEY) || "null",
      );
      return {
        ...defaults,
        ...(saved || {}),
        sidebars: { ...defaults.sidebars, ...(saved?.sidebars || {}) },
      };
    } catch {
      return defaults;
    }
  }

  function applyPreferences(preferences, root = document.documentElement) {
    const themes = new Set(["light", "dark", "high-contrast", "paper"]);
    const densities = new Set(["compact", "balanced", "comfortable"]);
    const theme = themes.has(preferences.theme) ? preferences.theme : "light";
    const migratedDensity =
      preferences.density === "spacious" ? "comfortable" : preferences.density;
    const density = densities.has(migratedDensity)
      ? migratedDensity
      : "balanced";
    root.dataset.appTheme = theme;
    root.dataset.density = density;
    preferences.theme = theme;
    preferences.density = density;
    preferences.inspectorPinned = preferences.inspectorPinned !== false;
    root.dataset.inspectorPinned = String(preferences.inspectorPinned);
    root.style.setProperty(
      "--workspace-left-width",
      `${Math.max(200, Math.min(420, Number(preferences.sidebars?.left) || 245))}px`,
    );
    root.style.setProperty(
      "--workspace-right-width",
      `${Math.max(220, Math.min(460, Number(preferences.sidebars?.right) || 270))}px`,
    );
    return { ...preferences, theme, density };
  }

  function persistPreferences(preferences) {
    global.localStorage.setItem(STORAGE_KEY, JSON.stringify(preferences));
  }

  function installResizableSidebars({ workspace, left, right, preferences }) {
    if (!workspace || !left || !right) return () => {};
    const disposers = [];
    const createHandle = (panel, side) => {
      const handle = document.createElement("div");
      handle.className = `sidebar-resizer sidebar-resizer-${side}`;
      handle.tabIndex = 0;
      handle.setAttribute("role", "separator");
      handle.setAttribute("aria-orientation", "vertical");
      handle.setAttribute(
        "aria-label",
        side === "left" ? "Resize left sidebar" : "Resize right sidebar",
      );
      panel.append(handle);
      const update = (width) => {
        const limits = side === "left" ? [200, 420] : [220, 460];
        const next = Math.round(
          Math.max(limits[0], Math.min(limits[1], width)),
        );
        preferences.sidebars[side] = next;
        document.documentElement.style.setProperty(
          side === "left"
            ? "--workspace-left-width"
            : "--workspace-right-width",
          `${next}px`,
        );
        handle.setAttribute("aria-valuenow", String(next));
      };
      let start = null;
      const move = (event) => {
        if (!start) return;
        const delta = event.clientX - start.x;
        update(start.width + (side === "left" ? delta : -delta));
      };
      const stop = () => {
        if (!start) return;
        start = null;
        document.body.classList.remove("resizing-sidebar");
        persistPreferences(preferences);
      };
      const down = (event) => {
        if (global.innerWidth <= 800) return;
        start = {
          x: event.clientX,
          width: panel.getBoundingClientRect().width,
        };
        handle.setPointerCapture?.(event.pointerId);
        document.body.classList.add("resizing-sidebar");
        event.preventDefault();
      };
      const key = (event) => {
        if (!["ArrowLeft", "ArrowRight"].includes(event.key)) return;
        const direction = event.key === "ArrowRight" ? 1 : -1;
        const current = panel.getBoundingClientRect().width;
        update(current + direction * (side === "left" ? 8 : -8));
        persistPreferences(preferences);
        event.preventDefault();
      };
      handle.addEventListener("pointerdown", down);
      global.addEventListener("pointermove", move);
      global.addEventListener("pointerup", stop);
      handle.addEventListener("keydown", key);
      disposers.push(() => {
        handle.removeEventListener("pointerdown", down);
        global.removeEventListener("pointermove", move);
        global.removeEventListener("pointerup", stop);
        handle.removeEventListener("keydown", key);
        handle.remove();
      });
    };
    createHandle(left, "left");
    createHandle(right, "right");
    return () => disposers.forEach((dispose) => dispose());
  }

  global.NNDVState = Object.freeze({
    WorkspaceStateMachine,
    readPreferences,
    applyPreferences,
    persistPreferences,
    installResizableSidebars,
  });
})(window);
