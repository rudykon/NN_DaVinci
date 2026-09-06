import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import net from "node:net";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { performance } from "node:perf_hooks";
import { chromium } from "playwright-core";

let assertionCount = 0;
for (const method of ["ok", "equal", "match", "doesNotMatch", "deepEqual"]) {
  const original = assert[method];
  assert[method] = (...args) => {
    assertionCount += 1;
    return Reflect.apply(original, assert, args);
  };
}
const started = performance.now();
const projectRoot = resolve(import.meta.dirname, "../..");
const python = process.env.NNDV_PYTHON || "python";
let baseURL = process.env.NNDV_BASE_URL;
let server = null;
let taskRoot = null;
if (!baseURL) {
  const port = await freePort();
  taskRoot = await mkdtemp(join(tmpdir(), "nndv-responsive-tasks-"));
  baseURL = `http://127.0.0.1:${port}`;
  server = spawn(
    python,
    [
      "-m",
      "nn_davinci",
      "serve",
      "--host",
      "127.0.0.1",
      "--port",
      String(port),
      "--no-browser",
    ],
    {
      cwd: projectRoot,
      env: {
        ...process.env,
        PYTHONPATH: join(projectRoot, "src"),
        NNDV_TASK_ROOT: taskRoot,
      },
      stdio: "ignore",
    },
  );
  await waitForServer(`${baseURL}/api/state`);
}
const browserPath = process.env.NNDV_BROWSER || "/usr/bin/google-chrome";
const screenshotDir = process.env.NNDV_RESPONSIVE_SCREENSHOT_DIR;
const reportPath = process.env.NNDV_RESPONSIVE_E2E_REPORT;
const testedViewports = [
  { width: 1440, height: 900 },
  { width: 1024, height: 768 },
  { width: 800, height: 720 },
  { width: 768, height: 720 },
  { width: 568, height: 320 },
  { width: 390, height: 780 },
  { width: 320, height: 568 },
];
if (screenshotDir) await mkdir(screenshotDir, { recursive: true });
const browser = await chromium.launch({
  executablePath: browserPath,
  headless: true,
  args: ["--no-sandbox"],
});
const context = await browser.newContext({
  acceptDownloads: true,
  viewport: { width: 1440, height: 900 },
});
const page = await context.newPage();
const errors = [];
let lastProjectResponse = null;
page.on("console", (message) => {
  if (message.type() === "error") errors.push(message.text());
});
page.on("pageerror", (error) => errors.push(error.message));
page.on("response", async (response) => {
  if (!response.url().endsWith("/api/project")) return;
  lastProjectResponse = {
    status: response.status(),
    body: await response.text().catch(() => "<unavailable>"),
  };
});

try {
  await page.goto(baseURL, { waitUntil: "networkidle" });
  await page.locator("#canvas svg").waitFor();

  for (const viewport of testedViewports) {
    await page.setViewportSize(viewport);
    await page.waitForTimeout(80);
    const geometry = await page.evaluate(() => {
      const topbar = document.querySelector(".topbar").getBoundingClientRect();
      const canvasToolbar = document
        .querySelector("#canvas-toolbar")
        .getBoundingClientRect();
      const semanticNav = document
        .querySelector(".semantic-nav")
        .getBoundingClientRect();
      const compactNav = document
        .querySelector("#compact-workspace-nav")
        .getBoundingClientRect();
      const controls = [
        ...document.querySelectorAll(".topbar button, .topbar label.button"),
      ]
        .filter((element) => element.getClientRects().length)
        .map((element) => element.getBoundingClientRect());
      let controlOverlaps = 0;
      for (let index = 0; index < controls.length; index += 1) {
        for (let other = index + 1; other < controls.length; other += 1) {
          const first = controls[index];
          const second = controls[other];
          if (
            Math.min(first.right, second.right) -
              Math.max(first.left, second.left) >
              0.5 &&
            Math.min(first.bottom, second.bottom) -
              Math.max(first.top, second.top) >
              0.5
          )
            controlOverlaps += 1;
        }
      }
      return {
        viewport: window.innerWidth,
        documentWidth: document.documentElement.scrollWidth,
        bodyWidth: document.body.scrollWidth,
        topbar: { left: topbar.left, right: topbar.right, width: topbar.width },
        canvasToolbar: {
          left: canvasToolbar.left,
          right: canvasToolbar.right,
          width: canvasToolbar.width,
        },
        semanticNav: {
          left: semanticNav.left,
          right: semanticNav.right,
          width: semanticNav.width,
        },
        compactNav: {
          visible: compactNav.width > 0,
          left: compactNav.left,
          right: compactNav.right,
        },
        controlOverlaps,
      };
    });
    assert.ok(
      geometry.documentWidth <= geometry.viewport &&
        geometry.bodyWidth <= geometry.viewport,
      `${viewport.width}px must not create horizontal overflow`,
    );
    assert.ok(
      geometry.topbar.left >= 0 && geometry.topbar.right <= viewport.width,
      `${viewport.width}px topbar must stay inside the viewport`,
    );
    assert.ok(
      geometry.canvasToolbar.left >= 0 &&
        geometry.canvasToolbar.right <= viewport.width,
      `${viewport.width}px canvas toolbar must stay inside the viewport`,
    );
    assert.ok(
      geometry.semanticNav.left >= 0 &&
        geometry.semanticNav.right <= viewport.width,
      `${viewport.width}px semantic navigation must stay inside the viewport`,
    );
    if (viewport.width <= 800)
      assert.ok(
        geometry.compactNav.visible &&
          geometry.compactNav.left >= 0 &&
          geometry.compactNav.right <= viewport.width,
        `${viewport.width}px compact workspace navigation must be visible and bounded`,
      );
    assert.equal(
      geometry.controlOverlaps,
      0,
      `${viewport.width}px topbar controls must not overlap`,
    );
    if (screenshotDir)
      await page.screenshot({
        path: join(screenshotDir, `toolbar-${viewport.width}.png`),
      });
  }

  await page.setViewportSize({ width: 1440, height: 900 });
  for (const [trigger, menu] of [
    ["#project-menu-button", "#project-menu"],
    ["#paper-menu-button", "#paper-menu"],
    ["#view-menu-button", "#view-menu"],
    ["#more-menu-button", "#more-menu"],
    ["#export-button", "#export-menu"],
    ["#canvas-edit-menu-button", "#canvas-edit-menu"],
    ["#canvas-annotation-menu-button", "#canvas-annotation-menu"],
  ]) {
    await page.locator(trigger).click();
    await assertMenuInsideViewport(page, menu);
    if (screenshotDir && menu === "#paper-menu")
      await page.screenshot({
        path: join(screenshotDir, "paper-menu-1440.png"),
      });
    assert.equal(
      await page.locator("[data-toolbar-menu]:not(.hidden)").count(),
      1,
      "opening a menu must close the previous menu",
    );
    await page.keyboard.press("Escape");
    assert.equal(
      await page.locator("[data-toolbar-menu]:not(.hidden)").count(),
      0,
      "Escape must close the active menu",
    );
    assert.equal(
      await page.locator(trigger).getAttribute("aria-expanded"),
      "false",
      "Escape must synchronize aria-expanded",
    );
  }

  await page.locator("#paper-menu-button").focus();
  await page.keyboard.press("ArrowDown");
  assert.equal(
    await page.evaluate(() => document.activeElement?.id),
    "generate-paper-button",
    "ArrowDown must open a menu and focus its first action",
  );
  await page.keyboard.press("Escape");
  assert.equal(
    await page.evaluate(() => document.activeElement?.id),
    "paper-menu-button",
    "Escape must restore focus to the opening trigger",
  );

  await page.keyboard.press("ArrowDown");
  await page.keyboard.press("End");
  assert.equal(
    await page.evaluate(() => document.activeElement?.id),
    "composer-button",
    "End must focus the final menu action",
  );
  await page.keyboard.press("Home");
  assert.equal(
    await page.evaluate(() => document.activeElement?.id),
    "generate-paper-button",
    "Home must focus the first menu action",
  );
  await page.keyboard.press("ArrowUp");
  assert.equal(
    await page.evaluate(() => document.activeElement?.id),
    "composer-button",
    "ArrowUp must wrap to the final action",
  );
  await page.keyboard.press("Tab");
  assert.equal(
    await page.evaluate(() => document.activeElement?.id),
    "generate-paper-button",
    "Tab must remain trapped inside an open menu",
  );
  await page.keyboard.press("Shift+Tab");
  assert.equal(
    await page.evaluate(() => document.activeElement?.id),
    "composer-button",
    "Shift+Tab must remain trapped inside an open menu",
  );
  await page.keyboard.press("Escape");

  await page.locator("#project-menu-button").click();
  await page.locator("#canvas-shell").click({ position: { x: 500, y: 400 } });
  assert.equal(
    await page.locator("[data-toolbar-menu]:not(.hidden)").count(),
    0,
    "clicking outside must close the active menu",
  );

  // The canonical side panels become mutually exclusive, focus-trapped
  // drawers at the compact breakpoint instead of disappearing.
  await page.setViewportSize({ width: 768, height: 720 });
  await page.locator('[data-panel-tab="structure"]').click();
  await page.waitForTimeout(40);
  assert.equal(
    await page.locator("#workspace-panel.drawer-open").count(),
    1,
    "compact structure navigation must open the canonical left panel",
  );
  assert.equal(
    await page.locator('.tab[data-tab="structure"].active').count(),
    1,
    "the compact structure proxy must activate the original structure tab",
  );
  assert.equal(await visibleSurfaceCount(page), 1);
  await page.keyboard.press("Shift+Tab");
  assert.equal(
    await page.evaluate(() => document.activeElement?.id),
    "graph-search",
    "Shift+Tab must wrap to the final focusable control in the drawer",
  );
  await page.keyboard.press("Tab");
  assert.equal(
    await page.evaluate(
      () => document.activeElement?.dataset.closeDrawer || null,
    ),
    "workspace-panel",
    "Tab must wrap back to the drawer close button",
  );
  await page.keyboard.press("Escape");
  assert.equal(
    await page.locator("#workspace-panel.drawer-open").count(),
    0,
    "Escape must close a responsive drawer",
  );
  assert.equal(
    await page.evaluate(() => document.activeElement?.dataset.panelTab),
    "structure",
    "closing a drawer must restore focus to its compact trigger",
  );

  await page.locator('[data-panel-tab="library"]').click();
  const drawerLayer = await page.evaluate(() => ({
    drawer: Number.parseInt(
      window.getComputedStyle(document.querySelector("#workspace-panel"))
        .zIndex,
      10,
    ),
    backdrop: Number.parseInt(
      window.getComputedStyle(document.querySelector("#surface-backdrop"))
        .zIndex,
      10,
    ),
  }));
  assert.ok(
    drawerLayer.drawer > drawerLayer.backdrop,
    "drawer must stack above its backdrop",
  );
  await page
    .locator("#surface-backdrop")
    .click({ position: { x: 700, y: 300 } });
  assert.equal(
    await page.locator("#workspace-panel.drawer-open").count(),
    0,
    "clicking the drawer backdrop must close it",
  );

  await page.locator("#canvas .node").first().click({ force: true });
  assert.equal(
    await page.locator("#inspector-toggle.has-selection").count(),
    1,
    "a compact selection must create an obvious Inspector entry",
  );
  await page.locator("#inspector-toggle").click();
  assert.equal(
    await page.locator("#inspector-panel.drawer-open").count(),
    1,
    "the canonical Inspector must be reachable on compact screens",
  );
  assert.ok(
    (await page.locator("#selection-count").textContent()) !== "未选择",
    "the Inspector drawer must retain current selection state",
  );
  await page
    .locator('#inspector-panel [data-close-drawer="inspector-panel"]')
    .click();

  // Opening a drawer closes a menu, and opening a dialog closes the drawer.
  await page.locator("#paper-menu-button").click();
  await page.evaluate(() =>
    document.querySelector('[data-panel-tab="analysis"]').click(),
  );
  assert.equal(
    await page.locator("[data-toolbar-menu]:not(.hidden)").count(),
    0,
    "opening a drawer must close an active menu",
  );
  await page.evaluate(() => document.querySelector("#composer-button").click());
  await page.locator("#composer-workflow[open]").waitFor();
  await page.locator("#composer-status.ready").waitFor();
  assert.equal(
    await page.locator("#workspace-panel.drawer-open").count(),
    0,
    "opening a dialog must close an active responsive drawer",
  );
  assert.equal(await visibleSurfaceCount(page), 1);
  await page.keyboard.press("Shift+Tab");
  assert.equal(
    await page.evaluate(
      () => document.activeElement?.closest("dialog")?.id || null,
    ),
    "composer-workflow",
    "dialog focus must remain inside the modal on Shift+Tab",
  );
  await page.mouse.click(2, 2);
  await page.locator("#composer-workflow").waitFor({ state: "hidden" });

  await page.locator("#more-menu-button").click();
  await page.locator("#tasks-button").click();
  assert.equal(
    await page.locator("#task-center:not(.hidden)").count(),
    1,
    "task center must use the shared drawer layer",
  );
  await page.evaluate(() =>
    document.querySelector('[data-panel-tab="library"]').click(),
  );
  assert.equal(
    await page.locator("#task-center:not(.hidden)").count(),
    0,
    "opening a responsive drawer must close a workflow drawer",
  );
  await page.keyboard.press("Escape");

  // Crossing the 800px breakpoint must clear stale transformed drawers.
  await page.locator('[data-panel-tab="library"]').click();
  await page.setViewportSize({ width: 1024, height: 768 });
  await page.waitForTimeout(60);
  assert.equal(
    await page.locator("[data-responsive-drawer].drawer-open").count(),
    0,
    "resizing to desktop must clear compact drawer state",
  );
  assert.equal(await page.locator("#workspace-panel").isVisible(), true);
  assert.equal(await page.locator("#inspector-panel").isVisible(), true);
  await page.setViewportSize({ width: 800, height: 720 });
  await page.waitForTimeout(60);
  assert.equal(
    await page.locator("#compact-workspace-nav").isVisible(),
    true,
    "800px is the compact drawer breakpoint",
  );

  // Every major workflow remains fully bounded in a short landscape viewport.
  await page.setViewportSize({ width: 568, height: 320 });
  await page.evaluate(() => document.querySelector("#start-button").click());
  await page.locator("#start-center[open]").waitFor();
  await assertDialogUsable(page, "#start-center");
  await page.locator('#start-center button[value="cancel"]').click();

  await page.evaluate(() => document.querySelector("#optimize-button").click());
  await page.locator("#paper-workflow[open]").waitFor();
  await assertDialogUsable(page, "#paper-workflow");
  await page.locator('#paper-workflow button[value="cancel"]').click();

  await page.evaluate(() => document.querySelector("#composer-button").click());
  await page.locator("#composer-workflow[open]").waitFor();
  await assertDialogUsable(page, "#composer-workflow");
  await page.locator('#composer-workflow button[value="cancel"]').click();

  await page.evaluate(() => document.querySelector("#trial-button").click());
  await page.locator("#trial-workflow[open]").waitFor();
  await assertDialogUsable(page, "#trial-workflow");
  await page.locator('#trial-workflow button[value="cancel"]').click();

  await page.keyboard.press("Control+KeyK");
  await page.locator("#command-palette[open]").waitFor();
  await assertDialogUsable(page, "#command-palette");
  await page.keyboard.press("Escape");

  await page.setViewportSize({ width: 390, height: 780 });
  assert.equal(await page.locator("#project-menu-button").isVisible(), false);
  assert.equal(await page.locator("#view-menu-button").isVisible(), false);

  await page.locator("#more-menu-button").click();
  await page.locator('[data-open-toolbar-menu="project-menu"]').click();
  await assertMenuInsideViewport(page, "#project-menu");
  assert.equal(await page.locator("#new-button").isVisible(), true);
  await page.keyboard.press("Escape");

  await page.locator("#more-menu-button").click();
  assert.equal(
    await page.locator(".start-fallback").isVisible(),
    true,
    "Start Center must remain discoverable from More on a phone",
  );
  await page.keyboard.press("Escape");

  await page.locator("#more-menu-button").click();
  await page.locator('[data-open-toolbar-menu="view-menu"]').click();
  await assertMenuInsideViewport(page, "#view-menu");
  if (screenshotDir)
    await page.screenshot({ path: join(screenshotDir, "view-menu-390.png") });
  await page.locator("#page-select").selectOption("double-column");
  await page.waitForTimeout(100);
  assert.equal(
    await page.locator("#page-select").inputValue(),
    "double-column",
  );
  await page.keyboard.press("Escape");

  await page.locator("#paper-menu-button").click();
  await page.locator("#composer-button").click();
  assert.equal(
    await page.locator("#composer-workflow").getAttribute("open"),
    "",
    "Figure Composer must remain reachable from the paper menu",
  );
  await page.locator('#composer-workflow button[value="cancel"]').click();

  // Phone-sized shortest real workflow: import -> block -> Paper View ->
  // Composer A/B -> project save -> SVG vector export.
  await page
    .locator("#file-input")
    .setInputFiles(join(projectRoot, "examples", "transformer.json"));
  await page.locator("#import-wizard[open]").waitFor();
  await assertDialogUsable(page, "#import-wizard");
  await page.locator("#wizard-import").click();
  await page.locator("#import-wizard").waitFor({ state: "hidden" });
  await waitForIdle(page);
  await page.waitForFunction(
    () => document.querySelector("#task-badge")?.textContent === "0",
    null,
    { timeout: 30_000 },
  );

  const levelControl = await revealToolbarControl(page, "#semantic-level");
  await levelControl.selectOption("block");
  await waitForIdle(page);
  const viewControl = await revealToolbarControl(page, "#semantic-view");
  await viewControl.selectOption("paper");
  await waitForIdle(page);
  await page.keyboard.press("Escape");
  assert.equal(await page.locator("#semantic-level").inputValue(), "block");
  assert.equal(await page.locator("#semantic-view").inputValue(), "paper");
  const breadcrumbGeometry = await page.evaluate(() => {
    const container = document
      .querySelector("#breadcrumbs")
      .getBoundingClientRect();
    const active = document
      .querySelector("#breadcrumbs .active")
      .getBoundingClientRect();
    return {
      activeLeft: active.left,
      activeRight: active.right,
      containerLeft: container.left,
      containerRight: container.right,
    };
  });
  assert.ok(
    breadcrumbGeometry.activeLeft >= breadcrumbGeometry.containerLeft &&
      breadcrumbGeometry.activeRight <= breadcrumbGeometry.containerRight,
    "the active semantic breadcrumb must scroll into view",
  );

  await page.locator("#paper-menu-button").click();
  assert.match(
    await page.locator("#composer-button").textContent(),
    /Figure Composer（多 Panel）/,
  );
  await page.locator("#composer-button").click();
  await page.locator("#composer-status.ready").waitFor();
  assert.equal(
    await page.locator("#composer-panels .composer-panel").count(),
    2,
    "first Composer open must create exactly two panels",
  );
  assert.equal(
    await page
      .locator('[data-panel="A"] [data-panel-field="title"]')
      .inputValue(),
    "Semantic blocks",
  );
  assert.equal(
    await page
      .locator('[data-panel="A"] [data-panel-field="semantic_level"]')
      .inputValue(),
    "block",
  );
  assert.equal(
    await page
      .locator('[data-panel="B"] [data-panel-field="title"]')
      .inputValue(),
    "Operation evidence",
  );
  assert.equal(
    await page
      .locator('[data-panel="B"] [data-panel-field="semantic_level"]')
      .inputValue(),
    "operation",
  );
  assert.match(
    await page.locator("#composer-summary").textContent(),
    /2 个 Panel.*A · paper\/block.*B · paper\/operation.*待生成 proof/s,
    "Composer summary must expose panel count, view, level and readiness",
  );
  await page
    .locator('[data-panel="A"] [data-panel-field="semantic_level"]')
    .selectOption("model");
  await page
    .locator('[data-panel="B"] [data-panel-field="semantic_level"]')
    .selectOption("layer");
  const aliasedComposerSummary = await page
    .locator("#composer-summary")
    .textContent();
  assert.match(
    aliasedComposerSummary,
    /A · paper\/framework.*B · paper\/module/s,
    "Composer summary must use author-facing Framework and Module aliases",
  );
  assert.doesNotMatch(
    aliasedComposerSummary,
    /paper\/(?:model|layer)/,
    "Composer summary must not expose persisted model/layer level names",
  );
  await page
    .locator('[data-panel="A"] [data-panel-field="semantic_level"]')
    .selectOption("block");
  await page
    .locator('[data-panel="B"] [data-panel-field="semantic_level"]')
    .selectOption("operation");
  await page.locator('#composer-workflow button[value="cancel"]').click();

  await page.evaluate(() => {
    const trigger = document.querySelector("#composer-button");
    trigger.click();
    trigger.click();
  });
  await page.locator("#composer-workflow[open]").waitFor();
  assert.equal(
    await page.locator("#composer-panels .composer-panel").count(),
    2,
    "repeated Composer activation must restore rather than duplicate initialization",
  );
  await page.locator('#composer-workflow button[value="cancel"]').click();

  const projectDownload = page.waitForEvent("download", { timeout: 30_000 });
  await page.locator("#export-button").click();
  await page.locator('#export-menu [data-format="project"]').click();
  const project = await projectDownload.catch(async (error) => {
    const ui = await page.evaluate(() => ({
      status: document.querySelector("#status")?.textContent,
      saveState: document.querySelector("#project-save-state")?.textContent,
      toast: document.querySelector("#toast")?.textContent,
      exportDisabled: document.querySelector("#export-button")?.disabled,
    }));
    throw new Error(
      `${error.message}; projectResponse=${JSON.stringify(lastProjectResponse)}; ui=${JSON.stringify(ui)}; console=${JSON.stringify(errors)}`,
    );
  });
  assert.match(project.suggestedFilename(), /\.nndv\.json$/);
  assert.equal(
    await project.failure(),
    null,
    "phone project save must succeed",
  );
  await page.waitForFunction(
    () => !document.querySelector("#export-button")?.disabled,
  );

  const svgDownload = page.waitForEvent("download", { timeout: 30_000 });
  await page.locator("#export-button").click();
  await page.locator('#export-menu [data-format="svg"]').click();
  const svg = await svgDownload;
  assert.match(svg.suggestedFilename(), /\.svg$/);
  assert.equal(
    await svg.failure(),
    null,
    "phone SVG vector export must succeed",
  );
  await waitForIdle(page);

  assert.equal(await visibleSurfaceCount(page), 0);

  assert.deepEqual(errors, [], `browser console errors: ${errors.join(" | ")}`);
  const report = {
    schema_version: "0.5.2-responsive-workspace-e2e-1",
    status: "passed",
    scenario: "responsive-workspace-mobile-paper-loop",
    assertion_count: assertionCount,
    duration_ms: Math.round(performance.now() - started),
    viewports: testedViewports,
    viewport_count: testedViewports.length,
    coverage: {
      canonical_workspace_drawers: true,
      inspector_selection_entry: true,
      mutually_exclusive_surfaces: true,
      keyboard_and_focus_restore: true,
      breakpoint_cleanup: true,
      bounded_workflow_dialogs: true,
      composer_default_panels: [
        { id: "A", title: "Semantic blocks", level: "block" },
        { id: "B", title: "Operation evidence", level: "operation" },
      ],
      duplicate_composer_initializations: 0,
      mobile_workflow: [
        "import-model",
        "block-view",
        "paper-view",
        "composer-a-b",
        "save-project",
        "export-svg",
      ],
      unexpected_browser_errors: errors.length,
    },
  };
  if (reportPath) {
    await mkdir(dirname(reportPath), { recursive: true });
    await writeFile(reportPath, `${JSON.stringify(report, null, 2)}\n`, "utf8");
  }
  console.log(`NNDV_RESPONSIVE_TOOLBAR_REPORT=${JSON.stringify(report)}`);
  console.log("NNDV_RESPONSIVE_TOOLBAR_RESULT=PASS");
} finally {
  await browser.close();
  if (server) {
    server.kill("SIGTERM");
    await new Promise((resolveWait) => {
      const timer = setTimeout(resolveWait, 1500);
      server.once("exit", () => {
        clearTimeout(timer);
        resolveWait();
      });
    });
  }
  if (taskRoot) await rm(taskRoot, { recursive: true, force: true });
}

async function assertMenuInsideViewport(targetPage, selector) {
  const geometry = await targetPage.locator(selector).evaluate((menu) => {
    const rect = menu.getBoundingClientRect();
    return {
      hidden: menu.classList.contains("hidden"),
      left: rect.left,
      top: rect.top,
      right: rect.right,
      bottom: rect.bottom,
      width: window.innerWidth,
      height: window.innerHeight,
    };
  });
  assert.equal(geometry.hidden, false, `${selector} must be open`);
  assert.ok(
    geometry.left >= 0 &&
      geometry.top >= 0 &&
      geometry.right <= geometry.width &&
      geometry.bottom <= geometry.height,
    `${selector} must stay inside the viewport: ${JSON.stringify(geometry)}`,
  );
}

async function assertDialogUsable(targetPage, selector) {
  const geometry = await targetPage.locator(selector).evaluate((dialog) => {
    const rect = dialog.getBoundingClientRect();
    const body = dialog.querySelector(".dialog-body");
    const header = dialog.querySelector("header");
    const actions = dialog.querySelector(".dialog-actions, footer");
    const bodyRect = body?.getBoundingClientRect();
    const headerRect = header?.getBoundingClientRect();
    const actionRect = actions?.getBoundingClientRect();
    return {
      left: rect.left,
      top: rect.top,
      right: rect.right,
      bottom: rect.bottom,
      viewportWidth: window.innerWidth,
      viewportHeight: window.innerHeight,
      horizontalOverflow: dialog.scrollWidth > dialog.clientWidth + 1,
      bodyHorizontalOverflow: body
        ? body.scrollWidth > body.clientWidth + 1
        : false,
      bodyHeight: bodyRect?.height || 0,
      headerTop: headerRect?.top ?? null,
      actionBottom: actionRect?.bottom ?? null,
    };
  });
  assert.ok(
    geometry.left >= 0 &&
      geometry.top >= 0 &&
      geometry.right <= geometry.viewportWidth &&
      geometry.bottom <= geometry.viewportHeight,
    `${selector} must fit the viewport: ${JSON.stringify(geometry)}`,
  );
  assert.equal(
    geometry.horizontalOverflow,
    false,
    `${selector} must not overflow horizontally`,
  );
  assert.equal(
    geometry.bodyHorizontalOverflow,
    false,
    `${selector} body must not overflow horizontally`,
  );
  assert.ok(geometry.bodyHeight > 0, `${selector} body must remain scrollable`);
  if (geometry.headerTop !== null)
    assert.ok(
      geometry.headerTop >= geometry.top,
      `${selector} title must remain visible`,
    );
  if (geometry.actionBottom !== null)
    assert.ok(
      geometry.actionBottom <= geometry.bottom + 1,
      `${selector} actions must remain visible`,
    );
}

async function visibleSurfaceCount(targetPage) {
  return targetPage.evaluate(
    () =>
      document.querySelectorAll("[data-toolbar-menu]:not(.hidden)").length +
      document.querySelectorAll("[data-responsive-drawer].drawer-open").length +
      document.querySelectorAll("[data-workflow-drawer]:not(.hidden)").length +
      document.querySelectorAll("dialog[open]").length,
  );
}

async function revealToolbarControl(targetPage, selector) {
  const locator = targetPage.locator(selector);
  if (await locator.isVisible()) return locator;
  const menuId = await locator.evaluate(
    (element) => element.closest("[data-toolbar-menu]")?.id || null,
  );
  assert.ok(menuId, `hidden control ${selector} must belong to a toolbar menu`);
  const trigger = targetPage.locator(
    `[data-menu-trigger][aria-controls="${menuId}"]`,
  );
  if (await trigger.isVisible()) await trigger.click();
  else {
    await targetPage.locator("#more-menu-button").click();
    await targetPage.locator(`[data-open-toolbar-menu="${menuId}"]`).click();
  }
  await locator.waitFor({ state: "visible" });
  return locator;
}

async function waitForIdle(targetPage) {
  await targetPage.waitForFunction(
    () =>
      document.querySelector("#canvas-shell")?.getAttribute("aria-busy") !==
        "true" &&
      !document.querySelector("#status")?.textContent.includes("正在"),
    null,
    { timeout: 30_000 },
  );
  await targetPage.waitForTimeout(80);
}

async function waitForServer(url) {
  const deadline = Date.now() + 15_000;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(url);
      await response.arrayBuffer();
      if (response.ok) return;
    } catch {}
    await new Promise((resolveWait) => setTimeout(resolveWait, 100));
  }
  throw new Error(`server did not start at ${url}`);
}

async function freePort() {
  return new Promise((resolvePort, reject) => {
    const listener = net.createServer();
    listener.once("error", reject);
    listener.listen(0, "127.0.0.1", () => {
      const address = listener.address();
      listener.close(() => resolvePort(address.port));
    });
  });
}
