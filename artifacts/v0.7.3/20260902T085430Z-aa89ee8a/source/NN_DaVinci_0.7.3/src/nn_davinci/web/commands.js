(function initializeCommands(global) {
  "use strict";

  function escapeHtml(value) {
    const element = document.createElement("span");
    element.textContent = value ?? "";
    return element.innerHTML;
  }

  function normalize(value) {
    return String(value || "")
      .normalize("NFKD")
      .toLowerCase()
      .replace(/[^\p{L}\p{N}]+/gu, " ")
      .trim();
  }

  function availability(command, context) {
    if (!command.available) return { enabled: true, reason: "" };
    const result = command.available(context);
    if (result === true || result === undefined)
      return { enabled: true, reason: "" };
    if (result === false)
      return {
        enabled: false,
        reason: command.disabledReason || "Unavailable now",
      };
    if (typeof result === "string") return { enabled: false, reason: result };
    return {
      enabled: result.enabled !== false,
      reason: result.reason || command.disabledReason || "",
    };
  }

  class CommandRegistry extends global.EventTarget {
    constructor(options = {}) {
      super();
      this.commands = new Map();
      this.context = options.context || (() => ({}));
      this.dialog = null;
      this.input = null;
      this.results = null;
      this.returnFocus = null;
      this.activeIndex = 0;
      this.searchProvider = null;
      this.onAnnounce = options.onAnnounce || (() => {});
    }

    register(command) {
      if (!command?.id || !command?.label || typeof command.run !== "function")
        throw new Error("Commands require id, label, and run");
      this.commands.set(command.id, {
        category: "General",
        shortcut: "",
        keywords: [],
        ...command,
      });
      return () => this.commands.delete(command.id);
    }

    registerAll(commands) {
      return commands.map((command) => this.register(command));
    }

    get(id) {
      return this.commands.get(id) || null;
    }

    status(id) {
      const command = this.get(id);
      return command
        ? availability(command, this.context())
        : { enabled: false, reason: "Unknown command" };
    }

    async execute(id, source = "command-palette") {
      const command = this.get(id);
      if (!command) throw new Error(`Unknown command: ${id}`);
      const status = availability(command, this.context());
      if (!status.enabled) {
        this.onAnnounce(status.reason, "warning");
        this.dispatchEvent(
          new global.CustomEvent("commandblocked", {
            detail: { command, reason: status.reason, source },
          }),
        );
        return false;
      }
      this.dispatchEvent(
        new global.CustomEvent("commandrun", { detail: { command, source } }),
      );
      await command.run(this.context(), { source });
      return true;
    }

    search(query = "") {
      const needle = normalize(query);
      return [...this.commands.values()]
        .map((command) => {
          const haystack = normalize(
            [
              command.label,
              command.category,
              command.description,
              command.shortcut,
              ...(command.keywords || []),
            ].join(" "),
          );
          const exact = normalize(command.label) === needle;
          const prefix = normalize(command.label).startsWith(needle);
          const included = !needle || haystack.includes(needle);
          return { command, score: exact ? 0 : prefix ? 1 : included ? 2 : 99 };
        })
        .filter((item) => item.score < 99)
        .sort(
          (a, b) =>
            a.score - b.score ||
            a.command.category.localeCompare(b.command.category) ||
            a.command.label.localeCompare(b.command.label),
        );
    }

    bind({ dialog, input, results, searchProvider }) {
      this.dialog = dialog;
      this.input = input;
      this.results = results;
      this.searchProvider = searchProvider || null;
      input.addEventListener("input", () => this.render(input.value));
      input.addEventListener("keydown", (event) => this.keydown(event));
      results.addEventListener("click", (event) => {
        const button = event.target.closest("[data-command-id]");
        if (button) void this.activate(button.dataset.commandId);
        const searchItem = event.target.closest("[data-command-search-index]");
        if (searchItem)
          this.activateSearch(Number(searchItem.dataset.commandSearchIndex));
      });
      dialog.addEventListener("close", () => {
        const target = this.returnFocus;
        this.returnFocus = null;
        if (target?.isConnected) target.focus();
      });
      dialog.addEventListener("cancel", () => this.close());
    }

    open(trigger = document.activeElement) {
      if (!this.dialog) throw new Error("Command palette is not bound");
      this.returnFocus = trigger;
      this.input.value = "";
      this.activeIndex = 0;
      this.render("");
      if (!this.dialog.open) this.dialog.showModal();
      global.requestAnimationFrame(() => this.input.focus());
    }

    close() {
      if (this.dialog?.open) this.dialog.close();
    }

    render(query) {
      const context = this.context();
      const commands = this.search(query);
      const external = this.searchProvider?.(query, context) || [];
      this.currentExternal = external;
      this.results.innerHTML =
        commands
          .map(({ command }, index) => {
            const status = availability(command, context);
            return `<button
              type="button"
              role="option"
              id="command-option-${escapeHtml(command.id)}"
              data-command-id="${escapeHtml(command.id)}"
              data-command-index="${index}"
              aria-selected="${index === this.activeIndex}"
              aria-disabled="${!status.enabled}"
              ${status.enabled ? "" : "disabled"}
              title="${escapeHtml(status.reason)}"
            ><span><strong>${escapeHtml(command.label)}</strong><small>${escapeHtml(
              status.enabled
                ? command.description || command.category
                : status.reason,
            )}</small></span><kbd>${escapeHtml(command.shortcut)}</kbd></button>`;
          })
          .join("") +
          external
            .map(
              (item, index) =>
                `<button type="button" role="option" data-command-search-index="${index}"><span><strong>${escapeHtml(item.label)}</strong><small>${escapeHtml(item.description || "Search result")}</small></span></button>`,
            )
            .join("") ||
        '<p class="command-empty">No matching commands or objects.</p>';
      this.resultButtons = [
        ...this.results.querySelectorAll("button:not(:disabled)"),
      ];
      this.activeIndex = Math.min(
        this.activeIndex,
        Math.max(0, this.resultButtons.length - 1),
      );
      this.updateActive();
    }

    updateActive() {
      this.resultButtons?.forEach((button, index) => {
        const active = index === this.activeIndex;
        button.setAttribute("aria-selected", String(active));
        button.tabIndex = active ? 0 : -1;
      });
      const active = this.resultButtons?.[this.activeIndex];
      if (active)
        this.input.setAttribute("aria-activedescendant", active.id || "");
      else this.input.removeAttribute("aria-activedescendant");
    }

    keydown(event) {
      if (["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) {
        const last = Math.max(0, (this.resultButtons?.length || 1) - 1);
        if (event.key === "Home") this.activeIndex = 0;
        else if (event.key === "End") this.activeIndex = last;
        else if (event.key === "ArrowDown")
          this.activeIndex = (this.activeIndex + 1) % (last + 1);
        else this.activeIndex = (this.activeIndex + last) % (last + 1);
        this.updateActive();
        this.resultButtons?.[this.activeIndex]?.scrollIntoView({
          block: "nearest",
        });
        event.preventDefault();
      } else if (event.key === "Enter") {
        this.resultButtons?.[this.activeIndex]?.click();
        event.preventDefault();
      } else if (event.key === "Escape") {
        this.close();
        event.preventDefault();
      }
    }

    async activate(id) {
      if (await this.execute(id)) this.close();
    }

    activateSearch(index) {
      const item = this.currentExternal?.[index];
      if (!item) return;
      this.close();
      item.run();
    }

    handleShortcut(event) {
      if (event.defaultPrevented) return false;
      const target = event.target;
      if (
        /INPUT|TEXTAREA|SELECT/.test(target?.tagName) ||
        target?.isContentEditable
      )
        return false;
      const pressed = shortcutFromEvent(event);
      const command = [...this.commands.values()].find(
        (item) => canonicalShortcut(item.shortcut) === pressed,
      );
      if (!command) return false;
      event.preventDefault();
      void this.execute(command.id, "shortcut");
      return true;
    }
  }

  function canonicalShortcut(shortcut) {
    return String(shortcut || "")
      .toLowerCase()
      .replace(/⌘|cmd|command|ctrl/g, "mod")
      .replace(/option/g, "alt")
      .replace(/\s+/g, "")
      .split("+")
      .filter(Boolean)
      .sort()
      .join("+");
  }

  function shortcutFromEvent(event) {
    const parts = [];
    if (event.ctrlKey || event.metaKey) parts.push("mod");
    if (event.altKey) parts.push("alt");
    if (event.shiftKey) parts.push("shift");
    const key = event.key.toLowerCase();
    if (!["control", "meta", "alt", "shift"].includes(key)) parts.push(key);
    return parts.sort().join("+");
  }

  global.NNDVCommands = Object.freeze({ CommandRegistry, canonicalShortcut });
})(window);
