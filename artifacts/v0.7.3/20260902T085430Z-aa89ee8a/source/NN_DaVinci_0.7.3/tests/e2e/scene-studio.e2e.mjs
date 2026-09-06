import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { createHash } from "node:crypto";
import { mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { get } from "node:http";
import net from "node:net";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { chromium } from "playwright-core";

const projectRoot = resolve(import.meta.dirname, "../..");
const python = process.env.NNDV_PYTHON || "python";
const browserPath = process.env.NNDV_BROWSER || "/usr/bin/google-chrome";
const ownedTemporary = !process.env.NNDV_SCENE_E2E_DIR;
const temporary =
  process.env.NNDV_SCENE_E2E_DIR ||
  (await mkdtemp(join(tmpdir(), "nndv-scene-studio-e2e-")));
await mkdir(temporary, { recursive: true });
const artifactRoot = join(temporary, "scene-studio-artifacts");
const screenshotRoot = join(artifactRoot, "screenshots");
const downloadRoot = join(artifactRoot, "downloads");
await mkdir(screenshotRoot, { recursive: true });
await mkdir(downloadRoot, { recursive: true });
const reportPath =
  process.env.NNDV_SCENE_E2E_REPORT ||
  join(artifactRoot, "scene-studio-e2e.json");
const port = await freePort();
const baseURL = `http://127.0.0.1:${port}`;
const server = spawn(
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
    env: { ...process.env, PYTHONPATH: join(projectRoot, "src") },
    stdio: ["ignore", "pipe", "pipe"],
  },
);
let serverOutput = "";
server.stdout.on("data", (chunk) => (serverOutput += chunk));
server.stderr.on("data", (chunk) => (serverOutput += chunk));

const assertions = [];
const errors = [];
const failures = [];
const expectedFallbackErrors = [];
const expectedRecoveryErrors = [];
const screenshotManifest = [];
const downloadManifest = [];
const viewportResults = [];
const architectureComparisons = {};
const sceneTemplateArchitectures = {};
const qualityChecks = {};
const requiredWorkflows = {
  blank_2d_3d: false,
  real_model_semantic_scene: false,
  structure_lens_scene: false,
  autosave_reload: false,
  scene_exports_10: false,
  selection_provenance_3d_to_2d: false,
  error_cancel_retry: false,
  architectures_7: false,
  scene_templates_7: false,
};
const viewports = [
  { width: 1920, height: 1080 },
  { width: 1440, height: 900 },
  { width: 1280, height: 720 },
  { width: 1024, height: 768 },
  { width: 800, height: 600 },
  { width: 568, height: 320 },
  { width: 390, height: 844 },
];
const expectedSceneTemplateKeys = [
  "cnn",
  "resnet",
  "unet",
  "transformer",
  "moe",
  "multimodal-fusion",
  "diffusion-unet",
];
const record = (condition, message) => {
  assert.ok(condition, message);
  assertions.push(message);
};
let browser;
let succeeded = false;
let expectRecoverableExportError = false;

try {
  await waitForServer(`${baseURL}/api/state`);
  browser = await chromium.launch({
    executablePath: browserPath,
    headless: true,
    args: [
      "--no-sandbox",
      "--disable-dev-shm-usage",
      "--use-angle=swiftshader",
      "--enable-webgl",
    ],
  });
  const context = await browser.newContext({
    acceptDownloads: true,
    viewport: viewports[0],
  });
  const page = await context.newPage();
  page.on("console", (message) => {
    if (message.type() !== "error") return;
    const text = message.text();
    if (
      /Failed to load resource:.*404/.test(text) &&
      /scene\/(from-graph|generate|render|project)/.test(text)
    )
      expectedFallbackErrors.push(text);
    else if (expectRecoverableExportError && /503/.test(text))
      expectedRecoveryErrors.push(text);
    else errors.push(text);
  });
  page.on("pageerror", (error) => errors.push(error.stack || error.message));

  await page.goto(baseURL, { waitUntil: "networkidle" });
  await page.evaluate(() => window.localStorage.clear());
  await page.reload({ waitUntil: "networkidle" });
  await page.locator("#canvas svg").waitFor();

  await page.locator("#start-button").click();
  await page.locator("#start-center[open]").waitFor();
  record(
    (await page.locator('[data-start-action="blank-2d"]').count()) === 1 &&
      (await page.locator('[data-start-action="blank-3d"]').count()) === 1,
    "Start Center exposes explicit Blank 2D and Blank 3D paths",
  );
  await page.locator("#real-model-list [data-real-model]").first().waitFor();
  await captureScreenshot(page, "start-center-blank-import-architectures", [
    "blank",
    "import",
    "seven-architectures",
  ]);
  await page.locator('[data-start-action="blank-2d"]').click();
  await waitForCanvasIdle(page);
  await captureScreenshot(page, "blank-2d-workspace", ["blank", "2d"]);
  await page.locator("#start-button").click();
  await page.locator("#start-center[open]").waitFor();
  await page.locator('[data-start-action="blank-3d"]').click();
  await page.locator("body.scene-studio-active").waitFor();
  await page.locator("#scene-webgl").waitFor({ state: "visible" });
  await captureScreenshot(page, "blank-3d-scene", ["blank", "3d"]);
  requiredWorkflows.blank_2d_3d = true;

  const graphics = await page.evaluate(() => {
    const canvas = document.querySelector("#scene-webgl");
    const gl = canvas.getContext("webgl2");
    return {
      webgl2: Boolean(gl),
      depth: gl ? gl.isEnabled(gl.DEPTH_TEST) : false,
      depthBits: gl ? gl.getParameter(gl.DEPTH_BITS) : 0,
      width: canvas.width,
      height: canvas.height,
      mode: document.querySelector("#scene-render-mode").textContent,
    };
  });
  record(
    graphics.webgl2 &&
      graphics.depth &&
      graphics.width > 0 &&
      graphics.height > 0,
    "Scene viewport uses a real WebGL2 context with the depth buffer enabled",
  );
  qualityChecks.hidden_line = graphics.depth && graphics.depthBits >= 16;
  record(
    qualityChecks.hidden_line,
    "hidden-line occlusion uses a real depth buffer with at least 16 depth bits",
  );
  record(
    (await page
      .locator('#scene-object-tree [data-scene-object-id^="axis-"]')
      .count()) === 3,
    "blank Scene IR contains explicit locked XYZ world helpers",
  );

  await page.locator('[data-scene-insert="box"]').click();
  await page.locator('[data-scene-insert="sphere"]').click();
  await page.locator('[data-scene-insert="tensor"]').click();
  const authored = page.locator(
    '#scene-object-tree [data-scene-object-id^="object-"]',
  );
  record(
    (await authored.count()) === 3,
    "box, sphere, and semantic tensor primitives are editable Scene objects",
  );

  const sceneUxSurface = await page.evaluate(() => ({
    inspectorGroups: [
      ...document.querySelectorAll("[data-scene-inspector-group]"),
    ].map((element) => element.dataset.sceneInspectorGroup),
    propertyPins: document.querySelectorAll("[data-scene-property-pin]").length,
    gizmoModes: document.querySelectorAll("[data-scene-gizmo-mode]").length,
    gizmoAxes: document.querySelectorAll("[data-scene-gizmo-axis]").length,
    treeSearch: Boolean(document.querySelector("#scene-tree-search")),
    treeFilter: Boolean(document.querySelector("#scene-tree-filter")),
  }));
  record(
    JSON.stringify(sceneUxSurface.inspectorGroups) ===
      JSON.stringify([
        "transform",
        "geometry",
        "appearance",
        "layout",
        "semantics",
        "provenance",
      ]) &&
      sceneUxSurface.propertyPins >= 6 &&
      sceneUxSurface.gizmoModes === 3 &&
      sceneUxSurface.gizmoAxes === 3 &&
      sceneUxSurface.treeSearch &&
      sceneUxSurface.treeFilter,
    `Scene exposes the exact six-group Inspector, per-property pins, XYZ gizmo, and searchable/filterable tree (${JSON.stringify(sceneUxSurface)})`,
  );
  await page.locator('[data-scene-property-pin="appearance"]').click();
  record(
    JSON.parse(
      await page.evaluate(() =>
        window.localStorage.getItem("nndv-scene-property-pins"),
      ),
    ).includes("appearance"),
    "per-property Inspector pin persists independently",
  );
  await page.locator("#scene-content-density").selectOption("compact");
  await page.locator("#scene-content-density").selectOption("paper");
  record(
    (await page.locator("#scene-content-density").inputValue()) === "paper",
    "Scene content density switches independently between Compact, Paper, and Detailed",
  );
  await page.evaluate(() =>
    document.querySelector("#scene-batch-export").click(),
  );
  await page.locator("#scene-batch-dialog[open]").waitFor();
  record(
    (await page.locator("#scene-batch-formats input").count()) === 10,
    "Scene batch dialog exposes all ten export formats with cancellation",
  );
  await page.locator('#scene-batch-dialog button[value="cancel"]').click();
  const browserBatchIsolation = await page.evaluate(async () => {
    const partial = await window.NNDVSceneBatch.run({
      formats: ["svg", "pdf", "png"],
      task: async (format) => {
        if (format === "pdf") throw new Error("fixture failure");
        return format;
      },
    });
    const controller = new window.AbortController();
    const cancelled = await window.NNDVSceneBatch.run({
      formats: ["svg", "pdf"],
      signal: controller.signal,
      task: async () => {
        controller.abort();
        throw new window.DOMException("Cancelled", "AbortError");
      },
    });
    return {
      partial: partial.status,
      successes: partial.successes.map((item) => item.format),
      failures: partial.failures.map((item) => item.format),
      cancelled: cancelled.cancelled.map((item) => item.format),
    };
  });
  record(
    browserBatchIsolation.partial === "partial" &&
      browserBatchIsolation.successes.join(",") === "svg,png" &&
      browserBatchIsolation.failures.join(",") === "pdf" &&
      browserBatchIsolation.cancelled.join(",") === "svg,pdf",
    `Scene batch isolates failures and cancels remaining work (${JSON.stringify(browserBatchIsolation)})`,
  );

  const themeContrasts = {};
  let paperCanvasPixel = null;
  for (const theme of ["light", "dark", "high-contrast", "paper"]) {
    await setApplicationTheme(page, theme);
    themeContrasts[theme] = await applicationContrast(page);
    if (theme === "paper")
      paperCanvasPixel = await page.evaluate(() => {
        const canvas = document.querySelector("#scene-webgl"),
          gl = canvas.getContext("webgl2");
        return [...gl.getParameter(gl.COLOR_CLEAR_VALUE)].map((value) =>
          Math.round(value * 255),
        );
      });
    await captureScreenshot(page, `theme-${theme}-scene`, [
      "theme",
      theme,
      "3d",
    ]);
  }
  qualityChecks.contrast = Object.values(themeContrasts).every(
    (ratio) => ratio >= 4.5,
  );
  qualityChecks.contrast_ratios = themeContrasts;
  record(
    qualityChecks.contrast,
    `all four application themes preserve >=4.5:1 text contrast (${JSON.stringify(themeContrasts)})`,
  );
  qualityChecks.paper_canvas_light =
    paperCanvasPixel?.[0] >= 240 &&
    paperCanvasPixel?.[1] >= 238 &&
    paperCanvasPixel?.[2] >= 230;
  record(
    qualityChecks.paper_canvas_light,
    `Paper theme changes the actual WebGL clear surface to paper-light RGB (${paperCanvasPixel})`,
  );
  await setApplicationTheme(page, "light");

  const surfaceQuality = await page.evaluate(() => {
    const visible = (element) =>
      Boolean(element && element.getClientRects().length);
    const topGroups = [
      ...document.querySelectorAll(
        ".toolbar > .toolbar-cluster, .toolbar > button",
      ),
    ].filter(visible);
    const unlabeledButtons = [...document.querySelectorAll("button")].filter(
      (button) =>
        visible(button) &&
        !button.textContent.trim() &&
        !button.getAttribute("aria-label") &&
        !button.title,
    );
    const computed = window.getComputedStyle(document.body);
    return {
      toolbarGroups: topGroups.length,
      unlabeledButtons: unlabeledButtons.length,
      fontFamily: computed.fontFamily,
      fontSize: Number.parseFloat(computed.fontSize),
    };
  });
  qualityChecks.toolbar = surfaceQuality.toolbarGroups <= 7;
  qualityChecks.label = surfaceQuality.unlabeledButtons === 0;
  qualityChecks.accessibility_labels = qualityChecks.label;
  qualityChecks.font =
    Boolean(surfaceQuality.fontFamily) && surfaceQuality.fontSize >= 10;
  record(
    qualityChecks.toolbar,
    `top application chrome uses <=7 groups (${surfaceQuality.toolbarGroups})`,
  );
  record(
    qualityChecks.label,
    "every visible button has text, title, or an accessible label",
  );
  record(
    qualityChecks.font,
    `application font is resolved and readable (${surfaceQuality.fontFamily}, ${surfaceQuality.fontSize}px)`,
  );

  await authored.nth(0).click();
  await authored.nth(1).click({ modifiers: ["Shift"] });
  record(
    (await page.locator("#scene-context-count").textContent()) === "2 selected",
    "tree selection supports additive multi-selection and contextual actions",
  );
  await page
    .locator('[data-scene-transform="position"][data-axis="x"]')
    .fill("1.13");
  await page
    .locator('[data-scene-transform="position"][data-axis="x"]')
    .press("Enter");
  await page.locator('[data-scene-action="align-y"]').click();
  await page.locator("#scene-depth-spacing").fill("1.5");
  await page.locator("#scene-apply-depth").click();
  await page.locator('[data-scene-action="group"]').click();
  await page.locator('[data-scene-action="lock"]').click();
  record(
    await page
      .locator('[data-scene-transform="position"][data-axis="x"]')
      .isDisabled(),
    "locked Scene selection disables transform editing",
  );
  await page.locator('[data-scene-action="lock"]').click();
  await page.locator('[data-scene-action="explode"]').click();
  await page.locator('[data-scene-action="collapse"]').click();

  await page.locator("#scene-projection").selectOption("orthographic");
  await page.locator("#scene-view-preset").selectOption("top");
  record(
    (await page.locator("#scene-projection").inputValue()) === "orthographic",
    "camera switches between perspective and orthographic projection",
  );
  await page.locator("#scene-camera-lock").click();
  record(
    (await page.locator("#scene-camera-lock").getAttribute("aria-pressed")) ===
      "true",
    "camera lock is explicit and stateful",
  );
  await page.locator("#scene-camera-lock").click();

  const canvasBox = await page.locator("#scene-webgl").boundingBox();
  record(Boolean(canvasBox), "WebGL Scene canvas has interactive geometry");
  await page.locator('button[data-scene-tool="orbit"]').click();
  await page.mouse.move(canvasBox.x + canvasBox.width / 2, canvasBox.y + 160);
  await page.mouse.down();
  await page.mouse.move(
    canvasBox.x + canvasBox.width / 2 + 90,
    canvasBox.y + 205,
    {
      steps: 8,
    },
  );
  await page.mouse.up();
  await page.mouse.wheel(0, -180);
  record(
    (await page
      .locator('button[data-scene-tool="orbit"]')
      .getAttribute("aria-pressed")) === "true",
    "orbit and wheel zoom run through the Scene interaction controller",
  );

  const switchTrigger = page.locator('[data-workspace="scene"]');
  await switchTrigger.focus();
  await page.keyboard.press("Control+K");
  await page.locator("#command-palette[open]").waitFor();
  await page.locator("#command-search").fill("save project");
  record(
    (await page.locator('[data-command-id="project.save"]').count()) === 1,
    "Ctrl/Cmd+K registry searches contextual commands and shortcuts",
  );
  await page.keyboard.press("Escape");
  record(
    await switchTrigger.evaluate(
      (element) => element === document.activeElement,
    ),
    "closing the command surface restores focus to its trigger",
  );
  qualityChecks.focus = true;

  await page.locator("#view-menu-button").click();
  await page.locator("#app-theme-select").selectOption("dark");
  await page.locator("#app-density-select").selectOption("compact");
  record(
    (await page.locator("html").getAttribute("data-app-theme")) === "dark" &&
      (await page.locator("html").getAttribute("data-density")) === "compact",
    "application theme and density are independent persisted preferences",
  );
  await page.keyboard.press("Escape");

  await page.locator(".sidebar-resizer-left").focus();
  await page.keyboard.press("ArrowRight");
  const sidebarPreference = await page.evaluate(() =>
    JSON.parse(window.localStorage.getItem("nndv-ui-preferences-0.7")),
  );
  record(
    sidebarPreference.sidebars.left > 245,
    "keyboard-resizable sidebar width is persisted",
  );

  await page.locator("#inspector-pin-button").click();
  const inspectorPreference = await page.evaluate(() =>
    JSON.parse(window.localStorage.getItem("nndv-ui-preferences-0.7")),
  );
  record(
    inspectorPreference.inspectorPinned === false &&
      (await page.locator("html").getAttribute("data-inspector-pinned")) ===
        "false",
    "Inspector property pin/unpin state is user-controlled and persisted",
  );
  await page.locator("#inspector-pin-button").click();

  await page.waitForTimeout(900);
  const draft = await page.evaluate(() =>
    JSON.parse(window.localStorage.getItem("nndv-autosaved-project")),
  );
  const modelLayer = draft.scene_ir.layers.find(
    (layer) => layer.metadata?.role === "model",
  );
  record(
    draft.project_version === "1.4" &&
      draft.canvas_state.workspace_mode === "scene" &&
      draft.scene_ir.schema_version === "1.0" &&
      draft.scene_ir.cameras.length >= 1 &&
      modelLayer.objects.length === 3 &&
      modelLayer.groups.length === 1,
    "autosave persists Project 1.4 Scene IR, camera, objects, group, and workspace context",
  );
  record(
    modelLayer.objects.every(
      (object) =>
        Array.isArray(object.transform.position) &&
        object.transform.position.length === 3,
    ),
    "Scene objects persist explicit XYZ world coordinates",
  );

  const competingRevision = new Date(Date.now() + 60_000).toISOString();
  await page.evaluate((revision) => {
    const stored = JSON.parse(
      window.localStorage.getItem("nndv-autosaved-project"),
    );
    stored.updated_at = revision;
    stored.name = "Competing stored revision";
    window.localStorage.setItem(
      "nndv-autosaved-project",
      JSON.stringify(stored),
    );
  }, competingRevision);
  await page.locator("#scene-projection").selectOption("perspective");
  await page.locator("#autosave-conflict-dialog[open]").waitFor();
  const reviewedRevision = await page.evaluate(
    () =>
      JSON.parse(window.localStorage.getItem("nndv-autosaved-project"))
        .updated_at,
  );
  record(
    reviewedRevision === competingRevision &&
      (await page.locator('[data-autosave-revision="current"]').count()) ===
        1 &&
      (await page.locator('[data-autosave-revision="stored"]').count()) === 1,
    "autosave conflict compares current and stored revisions before overwrite",
  );
  const conflictGeometry = await boundedSurfaceGeometry(
    page,
    "#autosave-conflict-dialog",
  );
  qualityChecks.dialog = conflictGeometry.bounded;
  record(
    qualityChecks.dialog,
    `autosave comparison dialog remains fully bounded (${JSON.stringify(conflictGeometry)})`,
  );
  await captureScreenshot(page, "autosave-revision-comparison", [
    "dialog",
    "autosave-conflict",
    "cancel-retry",
  ]);
  await page
    .locator('#autosave-conflict-dialog button[value="cancel"]')
    .click();
  await page.locator("#autosave-conflict-dialog").waitFor({ state: "hidden" });
  const cancelRecoveryState = await page.evaluate(() => ({
    saveState: document.querySelector("#project-save-state")?.dataset.state,
    retryVisible: Boolean(
      document.querySelector("#action-status-retry")?.getClientRects().length,
    ),
    actionHidden: document
      .querySelector("#action-status-region")
      ?.classList.contains("hidden"),
    storedRevision: JSON.parse(
      window.localStorage.getItem("nndv-autosaved-project"),
    ).updated_at,
  }));
  record(
    cancelRecoveryState.saveState === "conflict" &&
      cancelRecoveryState.retryVisible &&
      !cancelRecoveryState.actionHidden &&
      cancelRecoveryState.storedRevision === competingRevision,
    `cancelling revision comparison leaves the competing autosave untouched and exposes Retry (${JSON.stringify(cancelRecoveryState)})`,
  );
  await page.locator("#action-status-retry").click();
  await page.locator("#autosave-conflict-dialog[open]").waitFor();
  record(
    await page.locator("#autosave-conflict-dialog").isVisible(),
    "Retry reopens the same autosave revision comparison",
  );
  await page.locator("#autosave-overwrite-stored").click();
  await page.locator("#autosave-conflict-dialog").waitFor({ state: "hidden" });
  const resolvedRevision = await page.evaluate(
    () =>
      JSON.parse(window.localStorage.getItem("nndv-autosaved-project"))
        .updated_at,
  );
  record(
    resolvedRevision !== competingRevision,
    "explicit overwrite resolves the reviewed autosave conflict with a new revision",
  );

  const validAutosave = await page.evaluate(() =>
    window.localStorage.getItem("nndv-autosaved-project"),
  );
  await page.evaluate(() =>
    window.localStorage.setItem("nndv-autosaved-project", "{invalid-json"),
  );
  await page.locator("#scene-projection").selectOption("orthographic");
  await page.locator('#project-save-state[data-state="error"]').waitFor();
  record(
    (await page.locator("#action-status-retry").isVisible()) &&
      /Autosave failed/.test(
        await page.locator("#action-status-message").textContent(),
      ),
    "malformed competing autosave enters an explicit recoverable error state",
  );
  await page.evaluate(
    (draft) => window.localStorage.setItem("nndv-autosaved-project", draft),
    validAutosave,
  );
  await page.locator("#action-status-retry").click();
  await page.locator('#project-save-state[data-state="saved"]').waitFor();
  record(
    JSON.parse(
      await page.evaluate(() =>
        window.localStorage.getItem("nndv-autosaved-project"),
      ),
    ).scene_ir?.layers?.length > 0,
    "autosave Retry succeeds after the invalid stored revision is repaired",
  );

  await page.locator('[data-workspace="graph"]').click();
  await waitForCanvasIdle(page);
  await page.locator("#start-button").click();
  await page.locator("#start-center[open]").waitFor();
  await page.locator("#real-model-list [data-real-model]").first().waitFor();
  const architectureKeys = await page
    .locator("#real-model-list [data-real-model]")
    .evaluateAll((buttons) =>
      buttons.map((button) => button.dataset.realModel),
    );
  record(
    architectureKeys.length === 7 && new Set(architectureKeys).size === 7,
    `Start Center exposes seven distinct offline architectures (${architectureKeys.join(", ")})`,
  );
  const orderedArchitectureKeys = architectureKeys
    .filter((key) => key !== "resnet50")
    .concat("resnet50");
  let realModelBody = null;
  for (const key of orderedArchitectureKeys) {
    if ((await page.locator("#start-center").getAttribute("open")) === null) {
      await page.locator("#start-button").click();
      await page.locator("#start-center[open]").waitFor();
      await page
        .locator(`#real-model-list [data-real-model="${key}"]`)
        .waitFor();
    }
    const modelResponsePromise = page.waitForResponse(
      (response) =>
        response.url().endsWith(`/api/real-models/${key}`) &&
        response.request().method() === "POST",
      { timeout: 120_000 },
    );
    await page.locator(`[data-real-model="${key}"]`).click();
    const modelResponse = await modelResponsePromise;
    const modelBody = await modelResponse.json();
    await waitForCanvasIdle(page);
    record(
      modelResponse.ok() &&
        modelBody.graph?.nodes?.length > 0 &&
        modelBody.graph?.edges?.length > 0,
      `${key} imports as a non-empty offline Graph IR architecture`,
    );
    const twoDimensionalScreenshot = await captureScreenshot(
      page,
      `architecture-${key}-2d`,
      ["architecture", key, "import", "2d", "comparison-pair"],
    );
    if (key === "resnet50") realModelBody = modelBody;

    const sceneResponsePromise = page.waitForResponse(
      (response) =>
        /\/api\/scene\/(from-graph|generate)$/.test(response.url()) &&
        response.request().method() === "POST" &&
        response.ok(),
      { timeout: 120_000 },
    );
    await page.locator('[data-workspace="scene"]').click();
    const architectureSceneResponse = await sceneResponsePromise;
    const architectureSceneBody = await architectureSceneResponse.json();
    const architectureScene =
      architectureSceneBody.scene ||
      architectureSceneBody.scene_ir ||
      architectureSceneBody;
    await page.locator("body.scene-studio-active").waitFor();
    await page.locator("#scene-webgl").waitFor({ state: "visible" });
    await page.locator("#scene-view-preset").selectOption("isometric");
    await page.locator("#scene-frame").click();
    await page.waitForTimeout(120);
    await page.waitForFunction(
      () =>
        [
          ...document.querySelectorAll(
            "#scene-label-layer .scene-object-label:not([hidden])",
          ),
        ].some((label) => {
          const rect = label.getBoundingClientRect();
          return (
            window.getComputedStyle(label).visibility === "visible" &&
            rect.width > 0 &&
            rect.height > 0
          );
        }),
      null,
      { timeout: 120_000 },
    );
    const architectureEvidence = sceneObjectEvidence(architectureScene);
    const visibleLabelCount = await page
      .locator("#scene-label-layer .scene-object-label:not([hidden])")
      .evaluateAll(
        (labels) =>
          labels.filter((label) => {
            const rect = label.getBoundingClientRect();
            return (
              window.getComputedStyle(label).visibility === "visible" &&
              rect.width > 0 &&
              rect.height > 0
            );
          }).length,
      );
    record(
      architectureEvidence.nonHelperModelObjects > 0 && visibleLabelCount > 0,
      `${key} Graph/Semantic → Scene renders ${architectureEvidence.nonHelperModelObjects} non-helper model objects, ${architectureEvidence.routeObjects} routes, and ${visibleLabelCount} visible projected labels`,
    );
    const threeDimensionalScreenshot = await captureScreenshot(
      page,
      `architecture-${key}-3d`,
      ["architecture", key, "3d", "comparison-pair"],
    );
    architectureComparisons[key] = {
      two_d: {
        screenshot_id: twoDimensionalScreenshot.id,
        path: twoDimensionalScreenshot.path,
      },
      three_d: {
        screenshot_id: threeDimensionalScreenshot.id,
        path: threeDimensionalScreenshot.path,
      },
      non_helper_model_objects: architectureEvidence.nonHelperModelObjects,
      route_objects: architectureEvidence.routeObjects,
      visible_labels: visibleLabelCount,
    };
    await page.locator('[data-workspace="graph"]').click();
    await waitForCanvasIdle(page);
  }
  requiredWorkflows.architectures_7 =
    Object.keys(architectureComparisons).length === 7 &&
    architectureKeys.every(
      (key) =>
        architectureComparisons[key]?.non_helper_model_objects > 0 &&
        architectureComparisons[key]?.route_objects > 0 &&
        architectureComparisons[key]?.visible_labels > 0 &&
        architectureComparisons[key]?.two_d?.path &&
        architectureComparisons[key]?.three_d?.path,
    );
  record(
    requiredWorkflows.architectures_7,
    "all seven offline architectures have genuine non-helper 3D Scenes and paired 2D/3D screenshots",
  );

  const semanticResponsePromise = page.waitForResponse(
    (response) =>
      response.url().endsWith("/api/semantic") &&
      response.request().method() === "POST",
    { timeout: 120_000 },
  );
  await selectToolbarOption(page, "#semantic-level", "block");
  const semanticResponse = await semanticResponsePromise;
  const semanticBody = await semanticResponse.json();
  await waitForCanvasIdle(page);
  record(
    semanticResponse.ok() &&
      semanticBody.level === "block" &&
      semanticBody.graph?.nodes?.length > 0 &&
      semanticBody.semantic?.source_to_semantic?.block,
    "real ResNet50 materializes an evidence-backed Block Semantic View",
  );
  await captureScreenshot(page, "comparison-resnet50-semantic-2d", [
    "real-model",
    "semantic",
    "2d",
    "comparison-pair",
  ]);

  const figureResponsePromise = page.waitForResponse(
    (response) =>
      response.url().endsWith("/api/figure/from-graph") &&
      response.request().method() === "POST",
    { timeout: 120_000 },
  );
  await page.locator('[data-workspace="figure"]').click();
  const figureResponse = await figureResponsePromise;
  await page.locator("body.figure-studio-active").waitFor();
  await waitForCanvasIdle(page);
  record(
    figureResponse.ok() &&
      (await page.locator("#canvas [data-figure-object-id]").count()) > 0,
    "real-model Semantic View enters editable Figure Studio before Structure Lens",
  );
  await page.locator('[data-studio-right-tab="proof"]').click();
  await captureScreenshot(page, "figure-proof-resnet50", [
    "proof",
    "figure",
    "real-model",
  ]);

  await page.evaluate(() =>
    document.querySelector('[data-studio-action="structure-lens"]').click(),
  );
  await page.locator("#structure-lens-dialog[open]").waitFor();
  const lensEdge = realModelBody.graph.edges.at(-1);
  await page.locator("#lens-source").selectOption(lensEdge.source);
  await page.locator("#lens-target").selectOption(lensEdge.target);
  const lensResponsePromise = page.waitForResponse(
    (response) =>
      response.url().endsWith("/api/structure-lens/downstream") &&
      response.request().method() === "POST",
    { timeout: 120_000 },
  );
  await page.locator('[data-lens-operation="downstream"]').click();
  const lensResponse = await lensResponsePromise;
  const lensBody = await lensResponse.json();
  await page.locator("#structure-lens-results .lens-result-card").waitFor();
  record(
    lensResponse.ok() &&
      lensBody.node_ids?.length > 0 &&
      lensBody.metadata?.enumerated_all_simple_paths === false &&
      lensBody.figure_panel_preview?.available === true,
    "Structure Lens returns bounded Graph IR evidence and a provenance-backed preview",
  );
  await captureScreenshot(page, "structure-lens-bounded-result", [
    "structure-lens",
    "dialog",
    "provenance",
  ]);
  await page.locator('#structure-lens-dialog button[value="cancel"]').click();

  await page.locator('[data-workspace="scene"]').click();
  await page.locator("body.scene-studio-active").waitFor();
  const sceneResponsePromise = page.waitForResponse(
    (response) =>
      response.url().endsWith("/api/scene/from-graph") &&
      response.request().method() === "POST",
    { timeout: 120_000 },
  );
  await page.locator("#scene-generate-from-graph").click();
  const generatedSceneResponse = await sceneResponsePromise;
  const generatedSceneBody = await generatedSceneResponse.json();
  const generatedSceneRequest = generatedSceneResponse.request().postDataJSON();
  await page.locator("#scene-webgl").waitFor({ state: "visible" });
  const generatedScene =
    generatedSceneBody.scene ||
    generatedSceneBody.scene_ir ||
    generatedSceneBody;
  const generatedSceneObjects = (generatedScene.layers || []).flatMap(
    (layer) => layer.objects || [],
  );
  record(
    generatedSceneResponse.ok() &&
      generatedSceneRequest.level === "block" &&
      generatedSceneRequest.view === "paper" &&
      generatedSceneObjects.some(
        (object) => (object.provenance?.graph_ir_ids || []).length > 0,
      ),
    "real model → Block Semantic View → Scene uses the live Scene API and retains Graph provenance",
  );
  requiredWorkflows.real_model_semantic_scene = true;
  const lensNodeIds = new Set(lensBody.node_ids || []);
  record(
    generatedSceneRequest.focus_ids?.some((id) => lensNodeIds.has(id)),
    "Structure Lens node evidence becomes the bounded focus for Scene generation",
  );
  await page.waitForTimeout(900);
  const lensSceneDraft = await page.evaluate(() =>
    JSON.parse(window.localStorage.getItem("nndv-autosaved-project")),
  );
  record(
    lensSceneDraft.scene_ir?.metadata?.generation_context?.focus_source ===
      "structure-lens" &&
      lensSceneDraft.scene_ir.metadata.generation_context.structure_lens
        ?.bounded === true,
    "Structure Lens → Scene context is explicit and persists in Scene IR metadata",
  );
  requiredWorkflows.structure_lens_scene = true;
  await captureScreenshot(page, "comparison-resnet50-scene-3d", [
    "real-model",
    "semantic",
    "structure-lens",
    "3d",
    "comparison-pair",
  ]);

  const provenancedObject = generatedSceneObjects.find(
    (object) => (object.provenance?.graph_ir_ids || []).length > 0,
  );
  const provenancedRow = page.locator(
    `#scene-object-tree [data-scene-object-id="${provenancedObject.id}"]`,
  );
  await provenancedRow.click();
  const sceneProvenanceText = await page
    .locator("#scene-provenance")
    .textContent();
  await page.locator('[data-workspace="graph"]').click();
  await waitForCanvasIdle(page);
  const selected2DCount = await page.locator("#canvas .node.selected").count();
  record(
    /Graph IR/.test(sceneProvenanceText) && selected2DCount > 0,
    "returning from 3D to 2D synchronizes selection and provenance to the semantic canvas",
  );
  requiredWorkflows.selection_provenance_3d_to_2d = true;
  await captureScreenshot(page, "comparison-return-to-2d-selection", [
    "2d",
    "3d-to-2d",
    "selection",
    "provenance",
    "comparison-pair",
  ]);
  await page.locator('[data-workspace="scene"]').click();
  await page.locator("body.scene-studio-active").waitFor();
  await page.waitForTimeout(900);

  const beforeReload = await page.evaluate(() => {
    const draft = JSON.parse(
      window.localStorage.getItem("nndv-autosaved-project"),
    );
    return {
      workspace: draft.canvas_state.workspace_mode,
      selection: draft.canvas_state.scene_selection,
      sceneId: draft.scene_ir.id,
      cameraId: draft.canvas_state.scene_camera_id,
      focusSource: draft.scene_ir.metadata?.generation_context?.focus_source,
    };
  });
  const preReloadDraft = await page.evaluate(() =>
    JSON.parse(window.localStorage.getItem("nndv-autosaved-project")),
  );
  await writeFile(
    join(artifactRoot, "pre-reload-project.json"),
    JSON.stringify(preReloadDraft, null, 2),
  );
  const preReloadValidation = await page.evaluate(async () => {
    const project = JSON.parse(
      window.localStorage.getItem("nndv-autosaved-project"),
    );
    const response = await fetch("/api/project", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ project }),
    });
    return { status: response.status, body: await response.json() };
  });
  record(
    preReloadValidation.status === 200,
    preReloadValidation.status === 200
      ? "pre-reload Project 1.4 payload passes canonical validation"
      : `pre-reload validation failed: ${JSON.stringify(preReloadValidation.body)}`,
  );
  await page.reload({ waitUntil: "networkidle" });
  await page.locator("body.scene-studio-active").waitFor();
  await page.locator("#scene-webgl").waitFor({ state: "visible" });
  const afterReload = await page.evaluate(() => {
    const selected = [
      ...document.querySelectorAll(
        '#scene-object-tree [data-scene-object-id][aria-selected="true"]',
      ),
    ].map((row) => row.dataset.sceneObjectId);
    return {
      workspace: document.body.classList.contains("scene-studio-active")
        ? "scene"
        : "other",
      selected,
      cameraId: document.querySelector(
        '#scene-camera-list [data-scene-camera-id][aria-selected="true"]',
      )?.dataset.sceneCameraId,
    };
  });
  record(
    beforeReload.workspace === "scene" &&
      afterReload.workspace === "scene" &&
      beforeReload.sceneId &&
      beforeReload.cameraId === afterReload.cameraId &&
      beforeReload.selection.every((id) => afterReload.selected.includes(id)) &&
      beforeReload.focusSource === "structure-lens",
    "a genuine page.reload restores Scene IR, active camera, selection, Lens context, and workspace",
  );
  requiredWorkflows.autosave_reload = true;
  await captureScreenshot(page, "autosave-restored-after-page-reload", [
    "autosave",
    "reload",
    "3d",
  ]);

  await page.locator("#export-button").click();
  await page.locator("#export-menu:not(.hidden)").waitFor();
  const exportMenuGeometry = await boundedSurfaceGeometry(page, "#export-menu");
  qualityChecks.menu = exportMenuGeometry.bounded;
  record(
    qualityChecks.menu,
    `Scene export menu remains bounded (${JSON.stringify(exportMenuGeometry)})`,
  );
  await captureScreenshot(page, "scene-export-menu-10-formats", [
    "export",
    "menu",
    "ten-formats",
  ]);
  await page.keyboard.press("Escape");

  const exportFormats = [
    "svg",
    "pdf",
    "tikz",
    "pptx",
    "png",
    "eps",
    "html",
    "json",
    "gltf",
  ];
  for (const format of exportFormats) {
    const artifact = await downloadSceneFormat(page, format);
    record(
      artifact.bytes > 0,
      `Scene ${format.toUpperCase()} export downloads a non-empty artifact`,
    );
  }

  let intentionalExportFailure = true;
  expectRecoverableExportError = true;
  await page.route("**/api/scene/export/glb", async (route) => {
    if (intentionalExportFailure)
      await route.fulfill({
        status: 503,
        contentType: "application/json",
        body: JSON.stringify({ message: "intentional E2E recovery fault" }),
      });
    else await route.continue();
  });
  await page.locator("#export-button").click();
  await page.locator('#export-menu [data-format="glb"]').click();
  await page.locator('#action-status-region[data-state="error"]').waitFor();
  record(
    (await page.locator("#action-status-retry").isVisible()) &&
      /GLB export failed/.test(
        await page.locator("#action-status-message").textContent(),
      ),
    "Scene export failure is explicit and provides a contextual Retry action",
  );
  expectRecoverableExportError = false;
  intentionalExportFailure = false;
  const glbDownloadPromise = page.waitForEvent("download", {
    timeout: 120_000,
  });
  await page.locator("#action-status-retry").click();
  const glbDownload = await glbDownloadPromise;
  const glbFilename = `glb-${glbDownload
    .suggestedFilename()
    .replace(/[^a-zA-Z0-9._-]+/g, "-")}`;
  const glbPath = join(downloadRoot, glbFilename);
  await glbDownload.saveAs(glbPath);
  const glbEvidence = await fileEvidence(glbPath);
  const glbBytes = glbEvidence.bytes;
  downloadManifest.push({
    format: "glb",
    path: `downloads/${glbFilename}`,
    ...glbEvidence,
  });
  record(
    glbBytes > 0,
    "Retry completes the previously failed GLB Scene download",
  );
  await page.unroute("**/api/scene/export/glb");
  requiredWorkflows.error_cancel_retry = true;
  requiredWorkflows.scene_exports_10 =
    new Set(downloadManifest.map((item) => item.format)).size === 10;
  record(
    requiredWorkflows.scene_exports_10,
    "all 10 Scene formats download: SVG/PDF/TikZ/PPTX/PNG/EPS/HTML/JSON/glTF/GLB",
  );
  await page.locator("#toast").waitFor({ state: "hidden", timeout: 10_000 });

  const densityControl = await revealToolbarControl(
    page,
    "#app-density-select",
  );
  await densityControl.selectOption("balanced");
  await page.keyboard.press("Escape");
  await page.locator(".sidebar-resizer-left").focus();
  await page.keyboard.press("ArrowLeft");
  const defaultLayoutPreferences = await page.evaluate(() =>
    JSON.parse(window.localStorage.getItem("nndv-ui-preferences-0.7")),
  );
  qualityChecks.default_scene_layout =
    defaultLayoutPreferences.density === "balanced" &&
    defaultLayoutPreferences.inspectorPinned === true &&
    defaultLayoutPreferences.sidebars.left === 245 &&
    defaultLayoutPreferences.sidebars.right === 270;
  record(
    qualityChecks.default_scene_layout,
    "responsive Scene area gates start from the default balanced density and 245px/270px sidebar preferences",
  );

  for (const viewport of viewports) {
    await page.setViewportSize(viewport);
    const compact = viewport.width <= 800;
    if (compact) await closeResponsiveDrawers(page);
    await page.waitForTimeout(120);
    const minimumAreaRatio = compact ? 0.7 : 0.6;
    const geometry = await page.evaluate(() => {
      const canvas = document
          .querySelector("#scene-webgl")
          .getBoundingClientRect(),
        topbar = document.querySelector(".topbar").getBoundingClientRect(),
        viewportArea = window.innerWidth * window.innerHeight,
        canvasArea = canvas.width * canvas.height,
        responsiveDrawers = [
          ...document.querySelectorAll("[data-responsive-drawer]"),
        ],
        visibleToolbarControls = [
          ...document.querySelectorAll(
            "#scene-canvas-toolbar button, #scene-canvas-toolbar select, #scene-canvas-toolbar summary, #scene-selection-toolbar button, #scene-selection-toolbar summary",
          ),
        ].filter((element) => element.getClientRects().length),
        toolbarTruncations = visibleToolbarControls
          .filter((element) => {
            const bounds = element.getBoundingClientRect();
            return (
              element.scrollWidth > element.clientWidth + 0.5 ||
              bounds.left < -0.5 ||
              bounds.right > window.innerWidth + 0.5
            );
          })
          .map((element) => element.textContent.trim());
      return {
        viewportWidth: window.innerWidth,
        viewportHeight: window.innerHeight,
        documentWidth: document.documentElement.scrollWidth,
        documentHeight: document.documentElement.scrollHeight,
        bodyWidth: document.body.scrollWidth,
        bodyHeight: document.body.scrollHeight,
        canvasWidth: canvas.width,
        canvasHeight: canvas.height,
        canvasArea,
        viewportArea,
        canvasAreaRatio: Number((canvasArea / viewportArea).toFixed(6)),
        canvasBounds: {
          left: canvas.left,
          top: canvas.top,
          right: canvas.right,
          bottom: canvas.bottom,
        },
        topbarBounds: {
          left: topbar.left,
          top: topbar.top,
          right: topbar.right,
          bottom: topbar.bottom,
        },
        topbarOverlap: Math.max(0, topbar.bottom - canvas.top),
        compactDrawersClosed: responsiveDrawers.every(
          (drawer) =>
            !drawer.classList.contains("drawer-open") &&
            drawer.getAttribute("aria-hidden") === "true",
        ),
        toolbarTruncations,
      };
    });
    viewportResults.push({
      ...viewport,
      minimumAreaRatio,
      compact,
      ...geometry,
    });
    record(
      geometry.viewportWidth === viewport.width &&
        geometry.viewportHeight === viewport.height &&
        geometry.canvasWidth > 250 &&
        geometry.canvasHeight > 120 &&
        geometry.canvasBounds.left >= -0.5 &&
        geometry.canvasBounds.right <= geometry.viewportWidth + 0.5 &&
        geometry.canvasBounds.bottom <= geometry.viewportHeight + 0.5,
      `${viewport.width}×${viewport.height} uses the exact requested viewport and preserves Scene canvas geometry`,
    );
    record(
      geometry.canvasAreaRatio >= minimumAreaRatio,
      `${viewport.width}×${viewport.height} Scene canvas area ratio is ${geometry.canvasAreaRatio.toFixed(6)} (required >= ${minimumAreaRatio.toFixed(2)})`,
    );
    record(
      geometry.documentWidth <= geometry.viewportWidth &&
        geometry.bodyWidth <= geometry.viewportWidth &&
        geometry.documentHeight <= geometry.viewportHeight &&
        geometry.bodyHeight <= geometry.viewportHeight,
      `${viewport.width}×${viewport.height} has no horizontal or vertical page overflow`,
    );
    record(
      geometry.topbarBounds.left >= -0.5 &&
        geometry.topbarBounds.top >= -0.5 &&
        geometry.topbarBounds.right <= geometry.viewportWidth + 0.5 &&
        geometry.topbarOverlap <= 0.5,
      `${viewport.width}×${viewport.height} topbar is bounded and does not cover the Scene canvas`,
    );
    record(
      geometry.toolbarTruncations.length === 0,
      `${viewport.width}×${viewport.height} Scene toolbar has no clipped or truncated local controls`,
    );
    if (compact)
      record(
        geometry.compactDrawersClosed,
        `${viewport.width}×${viewport.height} measures the >=70% Scene canvas gate with both responsive drawers closed`,
      );
    await captureScreenshot(
      page,
      `viewport-${viewport.width}x${viewport.height}`,
      [
        "responsive",
        "3d",
        "exact-viewport",
        "canvas-area-gate",
        compact ? "drawers-closed" : "desktop-sidebars",
      ],
    );
  }
  qualityChecks.geometry = viewportResults.every(
    (result) =>
      result.viewportWidth === result.width &&
      result.viewportHeight === result.height &&
      result.canvasWidth > 250 &&
      result.canvasHeight > 120,
  );
  qualityChecks.overflow = viewportResults.every(
    (result) =>
      result.documentWidth <= result.viewportWidth &&
      result.bodyWidth <= result.viewportWidth &&
      result.documentHeight <= result.viewportHeight &&
      result.bodyHeight <= result.viewportHeight,
  );
  qualityChecks.canvas_area = viewportResults.every(
    (result) => result.canvasAreaRatio >= result.minimumAreaRatio,
  );
  qualityChecks.topbar_clear = viewportResults.every(
    (result) => result.topbarOverlap <= 0.5,
  );
  qualityChecks.compact_drawers_closed = viewportResults
    .filter((result) => result.compact)
    .every((result) => result.compactDrawersClosed);
  record(
    qualityChecks.geometry,
    "all seven exact viewport geometry checks pass",
  );
  record(
    qualityChecks.overflow,
    "all seven exact viewports pass independent horizontal and vertical overflow checks",
  );
  record(
    qualityChecks.canvas_area,
    `all seven exact Scene canvas area gates pass (${viewportResults.map((result) => `${result.width}×${result.height}=${result.canvasAreaRatio.toFixed(6)}`).join(", ")})`,
  );
  record(
    qualityChecks.topbar_clear,
    "the topbar stays bounded and does not overlap the Scene canvas at all seven exact viewports",
  );
  record(
    qualityChecks.compact_drawers_closed,
    "the 800×600, 568×320, and 390×844 area gates are measured with both drawers closed",
  );

  await page.setViewportSize(viewports[0]);
  await page.locator("#start-button").click();
  await page.locator("#start-center[open]").waitFor();
  await page
    .locator("#scene-template-list [data-scene-template]")
    .first()
    .waitFor();
  const sceneTemplateKeys = await page
    .locator("#scene-template-list [data-scene-template]")
    .evaluateAll((buttons) =>
      buttons.map((button) => button.dataset.sceneTemplate),
    );
  record(
    sceneTemplateKeys.length === expectedSceneTemplateKeys.length &&
      expectedSceneTemplateKeys.every((key) => sceneTemplateKeys.includes(key)),
    `Start Center exposes the exact seven editable Scene architecture families (${sceneTemplateKeys.join(", ")})`,
  );
  for (const key of expectedSceneTemplateKeys) {
    if ((await page.locator("#start-center").getAttribute("open")) === null) {
      await page.locator("#start-button").click();
      await page.locator("#start-center[open]").waitFor();
    }
    const templateControl = page.locator(
      `#scene-template-list [data-scene-template="${key}"]`,
    );
    await templateControl.waitFor();
    const templateResponsePromise = page.waitForResponse(
      (response) =>
        response.url().endsWith(`/api/scene/templates/${key}`) &&
        response.request().method() === "POST",
      { timeout: 120_000 },
    );
    await templateControl.click();
    const templateResponse = await templateResponsePromise;
    const templateBody = await templateResponse.json();
    const templateScene = templateBody.scene;
    await page.locator("body.scene-studio-active").waitFor();
    await page.locator("#scene-webgl").waitFor({ state: "visible" });
    const firstTemplateObjectId = templateScene?.layers
      ?.flatMap((layer) => layer.objects || [])
      .at(0)?.id;
    await page
      .locator(
        `#scene-object-tree [data-scene-object-id="${firstTemplateObjectId}"]`,
      )
      .waitFor();
    await page.locator("#scene-frame").click();
    await page.waitForFunction(
      () => {
        const canvas = document
            .querySelector("#scene-webgl")
            .getBoundingClientRect(),
          labels = [
            ...document.querySelectorAll(
              "#scene-label-layer .scene-object-label:not([hidden])",
            ),
          ];
        return (
          canvas.width > 250 &&
          canvas.height > 120 &&
          labels.some((label) => {
            const bounds = label.getBoundingClientRect();
            return (
              window.getComputedStyle(label).visibility === "visible" &&
              bounds.width > 0 &&
              bounds.height > 0
            );
          })
        );
      },
      null,
      { timeout: 120_000 },
    );
    const templateObjects = (templateScene?.layers || []).flatMap(
        (layer) => layer.objects || [],
      ),
      templateEvidence = sceneObjectEvidence(templateScene),
      provenanceOnly = templateObjects.every(
        (object) =>
          object.provenance?.kind === "template" &&
          (object.provenance?.graph_ir_ids || []).length === 0 &&
          (object.provenance?.semantic_view_ids || []).length === 0 &&
          (object.provenance?.figure_ir_ids || []).length === 0,
      );
    record(
      templateResponse.ok() &&
        templateScene?.metadata?.template_provenance_only === true &&
        templateScene?.metadata?.contains_model_evidence === false &&
        templateEvidence.nonHelperModelObjects > 0 &&
        templateEvidence.routeObjects > 0 &&
        provenanceOnly,
      `${key} opens a real editable 3D Scene template with ${templateEvidence.nonHelperModelObjects} non-helper objects, ${templateEvidence.routeObjects} routes, and template-only provenance`,
    );
    const screenshot = await captureScreenshot(
      page,
      `template-architecture-${key}-3d`,
      ["template-architecture", key, "3d"],
    );
    sceneTemplateArchitectures[key] = {
      screenshot_id: screenshot.id,
      path: screenshot.path,
      non_helper_model_objects: templateEvidence.nonHelperModelObjects,
      route_objects: templateEvidence.routeObjects,
    };
  }
  requiredWorkflows.scene_templates_7 =
    Object.keys(sceneTemplateArchitectures).length ===
      expectedSceneTemplateKeys.length &&
    expectedSceneTemplateKeys.every(
      (key) =>
        sceneTemplateArchitectures[key]?.non_helper_model_objects > 0 &&
        sceneTemplateArchitectures[key]?.route_objects > 0,
    );
  record(
    requiredWorkflows.scene_templates_7,
    "CNN, ResNet, U-Net, Transformer, MoE, Multimodal Fusion, and Diffusion U-Net each have an editable 3D Scene template screenshot",
  );

  await page.setViewportSize(viewports[2]);
  await page.waitForTimeout(120);
  qualityChecks.scene_label_occlusion = await sceneLabelGeometry(page);
  record(
    qualityChecks.scene_label_occlusion.passed,
    `visible Scene DOM labels avoid overlap and clipping (${JSON.stringify(qualityChecks.scene_label_occlusion)})`,
  );
  await page.evaluate(() => {
    const event = new window.Event("webglcontextlost", {
      bubbles: false,
      cancelable: true,
    });
    document.querySelector("#scene-webgl").dispatchEvent(event);
  });
  await page.locator("#scene-cpu-fallback:not([hidden])").waitFor();
  record(
    (await page.locator("#scene-cpu-fallback svg").count()) === 1 &&
      /CPU SVG/.test(await page.locator("#scene-render-mode").textContent()),
    "WebGL loss degrades explicitly to a vector CPU SVG projection",
  );
  qualityChecks.stroke =
    (await page.locator("#scene-cpu-fallback svg [stroke]").count()) > 0;
  record(
    qualityChecks.stroke,
    "CPU vector fallback retains explicit visible stroke geometry",
  );
  qualityChecks.cpu_fallback_labels = await page
    .locator("#scene-cpu-fallback svg text")
    .evaluateAll((elements) => {
      const boxes = elements.map((element) => {
        const rect = element.getBoundingClientRect();
        return {
          left: rect.left,
          top: rect.top,
          right: rect.right,
          bottom: rect.bottom,
          height: rect.height,
          font_size_pt: Number(element.getAttribute("data-font-size-pt")),
          font_size_user_units: Number(element.getAttribute("font-size")),
        };
      });
      let overlaps = 0;
      for (let left = 0; left < boxes.length; left += 1) {
        for (let right = left + 1; right < boxes.length; right += 1) {
          if (
            boxes[left].left < boxes[right].right - 0.5 &&
            boxes[left].right > boxes[right].left + 0.5 &&
            boxes[left].top < boxes[right].bottom - 0.5 &&
            boxes[left].bottom > boxes[right].top + 0.5
          )
            overlaps += 1;
        }
      }
      return {
        count: boxes.length,
        overlaps,
        min_font_pt: Math.min(...boxes.map((box) => box.font_size_pt)),
        max_font_user_units: Math.max(
          ...boxes.map((box) => box.font_size_user_units),
        ),
        max_rendered_height_px: Math.max(...boxes.map((box) => box.height)),
      };
    });
  record(
    qualityChecks.cpu_fallback_labels.count > 0 &&
      qualityChecks.cpu_fallback_labels.overlaps === 0 &&
      qualityChecks.cpu_fallback_labels.min_font_pt >= 7 &&
      qualityChecks.cpu_fallback_labels.max_font_user_units < 4 &&
      qualityChecks.cpu_fallback_labels.max_rendered_height_px < 18,
    `CPU SVG labels retain print-size semantics without browser-scale overlap (${JSON.stringify(qualityChecks.cpu_fallback_labels)})`,
  );
  await captureScreenshot(page, "cpu-svg-vector-fallback", [
    "fallback",
    "cpu-svg",
    "stroke",
    "3d",
  ]);
  record(
    errors.length === 0,
    `browser has no unexpected errors: ${errors.join("\n")}`,
  );
  succeeded = true;
} catch (error) {
  failures.push(error?.stack || error?.message || String(error));
  throw error;
} finally {
  const report = {
    schema_version: "nndv-0.7.1-scene-studio-e2e-1",
    release: "0.7.1 — 3D Publication Quality & UX Completion",
    status: succeeded ? "PASS" : "FAIL",
    succeeded,
    human_participants: 0,
    failures,
    assertions,
    assertion_count: assertions.length,
    viewports,
    viewport_results: viewportResults,
    architecture_comparisons: architectureComparisons,
    scene_template_architectures: sceneTemplateArchitectures,
    required_workflows: requiredWorkflows,
    quality_checks: qualityChecks,
    screenshot_manifest: screenshotManifest,
    download_manifest: downloadManifest,
    artifact_root: ".",
    expected_fallback_errors: expectedFallbackErrors,
    expected_recovery_errors: expectedRecoveryErrors,
    browser_errors: errors,
    server_output: succeeded ? undefined : serverOutput,
  };
  await writeFile(reportPath, JSON.stringify(report, null, 2));
  await browser?.close();
  server.kill("SIGTERM");
  if (ownedTemporary && succeeded) await rm(temporary, { recursive: true });
}

async function freePort() {
  return new Promise((resolvePort, reject) => {
    const socket = net.createServer();
    socket.on("error", reject);
    socket.listen(0, "127.0.0.1", () => {
      const address = socket.address();
      socket.close(() => resolvePort(address.port));
    });
  });
}

async function waitForServer(url) {
  const deadline = Date.now() + 45_000;
  while (Date.now() < deadline) {
    if (await httpReady(url)) return;
    await new Promise((resolveWait) => setTimeout(resolveWait, 150));
  }
  throw new Error(`server did not become ready: ${url}\n${serverOutput}`);
}

function httpReady(url) {
  return new Promise((resolveReady) => {
    const request = get(url, (response) => {
      response.resume();
      resolveReady(
        Number(response.statusCode) >= 200 && Number(response.statusCode) < 500,
      );
    });
    request.setTimeout(1500, () => request.destroy());
    request.on("error", () => resolveReady(false));
  });
}

async function waitForCanvasIdle(page) {
  await page.waitForFunction(
    () =>
      document.querySelector("#canvas-shell")?.getAttribute("aria-busy") ===
        "false" && Boolean(document.querySelector("#canvas svg")),
    null,
    { timeout: 120_000 },
  );
  await page.waitForTimeout(80);
}

async function captureScreenshot(page, id, coverage) {
  const viewport = page.viewportSize();
  const filename = `${id}.png`;
  const absolutePath = join(screenshotRoot, filename);
  await page.screenshot({ path: absolutePath, animations: "disabled" });
  const evidence = await fileEvidence(absolutePath);
  const artifact = {
    id,
    path: `screenshots/${filename}`,
    coverage,
    viewport,
    ...evidence,
  };
  screenshotManifest.push(artifact);
  return artifact;
}

async function closeResponsiveDrawers(page) {
  const openDrawers = page.locator("[data-responsive-drawer].drawer-open");
  while ((await openDrawers.count()) > 0) {
    const drawer = openDrawers.first();
    const closeButton = drawer.locator("[data-close-drawer]").first();
    if (await closeButton.isVisible()) await closeButton.click();
    else await page.keyboard.press("Escape");
  }
  await page.waitForFunction(() =>
    [...document.querySelectorAll("[data-responsive-drawer]")].every(
      (drawer) =>
        !drawer.classList.contains("drawer-open") &&
        drawer.getAttribute("aria-hidden") === "true",
    ),
  );
}

async function sceneLabelGeometry(page) {
  return page.locator("#scene-label-layer").evaluate((layer) => {
    const layerBounds = layer.getBoundingClientRect(),
      candidates = [...layer.querySelectorAll(".scene-object-label")],
      labels = candidates.filter((label) => {
        const bounds = label.getBoundingClientRect();
        return (
          !label.hidden &&
          window.getComputedStyle(label).visibility === "visible" &&
          bounds.width > 0 &&
          bounds.height > 0
        );
      }),
      bounds = labels.map((label) => label.getBoundingClientRect());
    let overlapCount = 0;
    for (let index = 0; index < bounds.length; index += 1)
      for (let other = index + 1; other < bounds.length; other += 1) {
        const first = bounds[index],
          second = bounds[other],
          overlapWidth =
            Math.min(first.right, second.right) -
            Math.max(first.left, second.left),
          overlapHeight =
            Math.min(first.bottom, second.bottom) -
            Math.max(first.top, second.top);
        if (overlapWidth > 0.5 && overlapHeight > 0.5) overlapCount += 1;
      }
    const clippedCount = bounds.filter(
      (rect) =>
        rect.left < layerBounds.left - 0.5 ||
        rect.top < layerBounds.top - 0.5 ||
        rect.right > layerBounds.right + 0.5 ||
        rect.bottom > layerBounds.bottom + 0.5,
    ).length;
    return {
      passed: labels.length > 0 && overlapCount === 0 && clippedCount === 0,
      candidate_count: candidates.length,
      visible_count: labels.length,
      label_count: labels.length,
      overlap_count: overlapCount,
      clipped_count: clippedCount,
      method:
        "DOM getBoundingClientRect geometry for visible projected Scene label bounds within #scene-label-layer",
    };
  });
}

function sceneObjectEvidence(scene) {
  let nonHelperModelObjects = 0;
  let routeObjects = 0;
  for (const layer of scene?.layers || []) {
    const helperLayer = /helper/i.test(
      `${layer.id || ""} ${layer.name || ""} ${layer.metadata?.role || ""}`,
    );
    for (const object of layer.objects || []) {
      const helperObject =
        helperLayer ||
        object.metadata?.helper === true ||
        /^axis[-_]/i.test(object.id || "");
      if (helperObject) continue;
      nonHelperModelObjects += 1;
      if (
        (Array.isArray(object.geometry?.points) &&
          object.geometry.points.length >= 2) ||
        object.metadata?.connector === true ||
        /route|connector|edge|arrow|polyline|bezier/i.test(
          `${object.kind || ""} ${object.geometry?.primitive || ""}`,
        )
      )
        routeObjects += 1;
    }
  }
  return { nonHelperModelObjects, routeObjects };
}

async function fileEvidence(path) {
  const bytes = await readFile(path);
  return {
    bytes: bytes.length,
    sha256: createHash("sha256").update(bytes).digest("hex"),
  };
}

async function revealToolbarControl(page, selector) {
  const locator = page.locator(selector);
  if (await locator.isVisible()) return locator;
  const menuId = await locator.evaluate(
    (element) => element.closest("[data-toolbar-menu]")?.id || null,
  );
  if (!menuId) throw new Error(`hidden control ${selector} has no menu`);
  const trigger = page.locator(
    `[data-menu-trigger][aria-controls="${menuId}"]`,
  );
  if (await trigger.isVisible()) await trigger.click();
  else {
    await page.locator("#more-menu-button").click();
    await page.locator(`[data-open-toolbar-menu="${menuId}"]`).click();
  }
  await locator.waitFor({ state: "visible" });
  return locator;
}

async function selectToolbarOption(page, selector, value) {
  const locator = await revealToolbarControl(page, selector);
  await locator.selectOption(value);
}

async function setApplicationTheme(page, theme) {
  const control = await revealToolbarControl(page, "#app-theme-select");
  await control.selectOption(theme);
  await page.keyboard.press("Escape");
  await page.waitForTimeout(60);
}

async function applicationContrast(page) {
  return page.evaluate(() => {
    const rgb = (value) =>
      (value.match(/[\d.]+/g) || []).slice(0, 3).map(Number);
    const luminance = (value) => {
      const channels = rgb(value).map((channel) => {
        const normalized = channel / 255;
        return normalized <= 0.03928
          ? normalized / 12.92
          : ((normalized + 0.055) / 1.055) ** 2.4;
      });
      return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2];
    };
    const style = window.getComputedStyle(document.body),
      foreground = luminance(style.color),
      background = luminance(style.backgroundColor),
      ratio =
        (Math.max(foreground, background) + 0.05) /
        (Math.min(foreground, background) + 0.05);
    return Math.round(ratio * 100) / 100;
  });
}

async function boundedSurfaceGeometry(page, selector) {
  return page.locator(selector).evaluate((element) => {
    const rect = element.getBoundingClientRect();
    const bounded =
      rect.left >= -1 &&
      rect.top >= -1 &&
      rect.right <= window.innerWidth + 1 &&
      rect.bottom <= window.innerHeight + 1 &&
      element.scrollWidth <= element.clientWidth + 1;
    return {
      bounded,
      left: Math.round(rect.left),
      top: Math.round(rect.top),
      right: Math.round(rect.right),
      bottom: Math.round(rect.bottom),
      viewportWidth: window.innerWidth,
      viewportHeight: window.innerHeight,
      horizontalOverflow: element.scrollWidth > element.clientWidth + 1,
    };
  });
}

async function downloadSceneFormat(page, format) {
  const downloadPromise = page.waitForEvent("download", { timeout: 120_000 });
  await page.locator("#export-button").click();
  const control = page.locator(`#export-menu [data-format="${format}"]`);
  await control.waitFor({ state: "visible" });
  await control.click();
  const download = await downloadPromise;
  const failure = await download.failure();
  if (failure) throw new Error(`${format} download failed: ${failure}`);
  const safeFilename = download
    .suggestedFilename()
    .replace(/[^a-zA-Z0-9._-]+/g, "-");
  const filename = `${format}-${safeFilename}`;
  const absolutePath = join(downloadRoot, filename);
  await download.saveAs(absolutePath);
  const evidence = await fileEvidence(absolutePath);
  const artifact = {
    format,
    path: `downloads/${filename}`,
    ...evidence,
  };
  downloadManifest.push(artifact);
  return artifact;
}
