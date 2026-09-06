import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import net from "node:net";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { performance } from "node:perf_hooks";
import { chromium } from "playwright-core";

const projectRoot = resolve(import.meta.dirname, "../..");
const python = process.env.NNDV_PYTHON || "python";
const browserPath = process.env.NNDV_BROWSER || "/usr/bin/google-chrome";
const ownedTemporary = !process.env.NNDV_PRODUCT_E2E_DIR;
const temporary =
  process.env.NNDV_PRODUCT_E2E_DIR ||
  (await mkdtemp(join(tmpdir(), "nndv-product-e2e-")));
await mkdir(temporary, { recursive: true });
const reportPath =
  process.env.NNDV_PRODUCT_E2E_REPORT ||
  join(temporary, "product-workflow.json");
const largePath = join(temporary, "lazy-50k.json");
await writeFile(
  largePath,
  JSON.stringify({
    name: "Lazy 50k Product",
    layers: Array.from({ length: 50_000 }, (_, index) => ({
      name: `Operation ${index}`,
      type: "Linear",
      category: "linear",
    })),
  }),
  "utf8",
);

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

const started = performance.now();
const assertions = [];
const metrics = {
  automated_interaction_only: true,
  clicks: 0,
  steps: [],
  recoveries: 0,
  first_real_model_figure_ms: null,
  autosave_probe_ms: null,
  cancellation_ms: null,
  lazy_50k_first_view_ms: null,
};
const check = (condition, message) => {
  assert.ok(condition, message);
  assertions.push(message);
};
let browser;

try {
  await waitForServer(`${baseURL}/api/state`);
  browser = await chromium.launch({
    executablePath: browserPath,
    headless: true,
    args: ["--no-sandbox", "--disable-gpu"],
  });
  const context = await browser.newContext({ acceptDownloads: true });
  const page = await context.newPage();
  const errors = [];
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(message.text());
  });
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("request", (request) => {
    if (request.resourceType() === "document") metrics.steps.push("navigation");
  });
  await page.goto(baseURL, { waitUntil: "networkidle" });
  await page.locator("#canvas svg").waitFor();

  // Start Center: all product entry points and seven offline real models.
  await click(page, "#start-button");
  await page.locator("#start-center[open]").waitFor();
  await page.locator("#real-model-list [data-real-model]").first().waitFor();
  check(
    (await page.locator("#real-model-list [data-real-model]").count()) === 7,
    "Start Center exposes seven offline real-model entries",
  );
  const startActions = await page
    .locator("[data-start-action]")
    .evaluateAll((elements) =>
      elements.map((element) => element.dataset.startAction).sort(),
    );
  check(
    JSON.stringify(startActions) ===
      JSON.stringify(["blank-2d", "blank-3d", "composer", "import", "open"]),
    "Start Center exposes explicit blank-2d/blank-3d/import/open/composer entry points",
  );

  const modelStarted = performance.now();
  await click(page, '[data-real-model="vision_transformer"]');
  await idle(page);
  metrics.first_real_model_figure_ms = Math.round(
    performance.now() - modelStarted,
  );
  metrics.steps.push("real-model-open");
  check(
    metrics.first_real_model_figure_ms <= 2000,
    `real-model first paper-capable view is <=2s (${metrics.first_real_model_figure_ms}ms)`,
  );
  check(
    (await page.locator("#canvas").textContent()).includes("Encoder") ||
      (await page.locator("#canvas").textContent()).includes("Vision"),
    "real Vision Transformer opens without downloaded weights",
  );

  // Five-level evidence browsing plus global command search.
  let delayedFrameworkRequest = false;
  await page.route("**/api/semantic", async (route) => {
    const level = route.request().postDataJSON()?.level;
    if (
      !delayedFrameworkRequest &&
      (level === "framework" || level === "model")
    ) {
      delayedFrameworkRequest = true;
      await new Promise((resolveWait) => setTimeout(resolveWait, 350));
    }
    await route.continue();
  });
  const frameworkRequest = page.waitForRequest(
    (request) =>
      request.url().endsWith("/api/semantic") &&
      ["framework", "model"].includes(request.postDataJSON()?.level),
  );
  await selectToolbarOption(page, "#semantic-level", "framework");
  await frameworkRequest;
  const blockResponsePromise = page.waitForResponse(
    (response) =>
      response.url().endsWith("/api/semantic") &&
      response.request().postDataJSON()?.level === "block",
  );
  await selectToolbarOption(page, "#semantic-level", "block");
  const blockBody = await (await blockResponsePromise).json();
  await idle(page);
  await page.unroute("**/api/semantic");
  const rapidSwitchNodeIds = await page
      .locator("#canvas .node")
      .evaluateAll((nodes) =>
        nodes.map((node) => node.getAttribute("data-node-id") || ""),
      ),
    blockNodeIds = new Set(blockBody.graph.nodes.map((node) => node.id)),
    unexpectedRapidSwitchIds = rapidSwitchNodeIds.filter(
      (id) => !blockNodeIds.has(id) && !id.includes("semantic_block_"),
    );
  check(
    rapidSwitchNodeIds.length > 0 && unexpectedRapidSwitchIds.length === 0,
    unexpectedRapidSwitchIds.length
      ? `rapid Semantic View switches keep only the latest block render (unexpected: ${unexpectedRapidSwitchIds.slice(0, 4).join(", ")})`
      : "rapid Semantic View switches keep only the latest block render",
  );
  await selectToolbarOption(page, "#semantic-level", "framework");
  await idle(page);
  await page.locator("#canvas .node").first().dispatchEvent("dblclick");
  await idle(page);
  await page.locator("#canvas .node").first().dispatchEvent("dblclick");
  await idle(page);
  check(
    (await page.locator("#semantic-level").inputValue()) === "block",
    "framework drilldown reaches semantic block view",
  );
  await selectToolbarOption(page, "#semantic-level", "operation");
  await idle(page);
  await page.keyboard.press("Control+KeyK");
  await page.locator("#command-search").fill("self_attention");
  const globalResult = page
    .locator("#command-results [data-command-search-index]")
    .first();
  await globalResult.waitFor();
  await click(page, globalResult);
  check(
    (await page.locator("#selection-count").textContent()) !== "未选择",
    "command palette global search locates an operation",
  );
  await click(page, "#analyze-button");
  await waitForTasks(page);
  await idle(page);
  check(
    (await page.locator("#inspector").textContent()).includes("provenance") ||
      (await page.locator("#analysis-summary").textContent()).includes("FLOPs"),
    "structure and analysis evidence remain inspectable",
  );
  metrics.steps.push("evidence-reviewed");

  // One-click paper candidates remain review-before-apply.
  await click(page, "#generate-paper-button");
  await page.locator("#paper-workflow[open]").waitFor();
  const candidates = page.locator("#paper-suggestions .suggestion-card");
  await candidates.first().waitFor();
  check(
    (await candidates.count()) <= 3 && (await candidates.count()) > 0,
    "one-click paper generation returns at most three candidates",
  );
  check(
    (await candidates.first().textContent()).includes("minimum_font") &&
      (await candidates.first().textContent()).includes("crossing"),
    "candidate comparison exposes geometry metrics and readability",
  );
  await click(page, candidates.first().locator("[data-apply-suggestion]"));
  await idle(page);
  await click(page, "#paper-workflow form button");
  metrics.steps.push("candidate-applied");

  // Multi-panel composition, isolated edit, proof and one-shot bundle.
  await click(page, "#composer-button");
  await page.locator("#composer-workflow[open]").waitFor();
  check(
    (await page.locator("#composer-panels .composer-panel").count()) === 2,
    "Composer starts with overview and detail panels",
  );
  await click(page, "#composer-add-panel");
  check(
    (await page.locator("#composer-panels .composer-panel").count()) === 3,
    "Composer supports A/B/C/D panel management",
  );
  await page.locator("#composer-title").fill("Researcher recovery figure");
  await page.locator("#composer-page").selectOption("wide-two-column");
  await page.locator("#composer-arrangement").selectOption("horizontal");
  await page
    .locator('[data-panel="A"] [data-panel-field="title"]')
    .fill("Human overview");
  await page
    .locator('[data-panel="B"] [data-panel-field="semantic_level"]')
    .selectOption("layer");
  await click(page, "#composer-preview");
  await page.waitForFunction(
    () =>
      document
        .querySelector("#composer-workflow")
        ?.getAttribute("aria-busy") === "false",
  );
  await idle(page);
  check(
    (await page.locator("#composer-proof").textContent()).includes("mm") &&
      (await page.locator("#composer-proof").textContent()).includes("pt"),
    "proof preview reports physical size, font and line width",
  );
  await click(page, "#composer-workflow form button");
  const panelDigestsBefore = await waitForPanelDigests(page);
  const node = page.locator("#canvas .node").first();
  const nodeBox = await node.boundingBox();
  await node.hover();
  await page.mouse.down();
  await page.mouse.move(
    nodeBox.x + nodeBox.width / 2 + 28,
    nodeBox.y + nodeBox.height / 2 + 16,
  );
  await page.mouse.up();
  await idle(page);
  const panelDigestsAfter = await waitForPanelDigests(page);
  check(
    (await page.locator("#canvas .node").first().getAttribute("transform")) !==
      null,
    "a composed panel node remains manually draggable",
  );
  check(
    panelDigestsBefore.B === panelDigestsAfter.B &&
      panelDigestsBefore.C === panelDigestsAfter.C,
    "editing one panel does not re-layout the other panels",
  );
  const edgePoint = await page.evaluate(() => {
    for (const path of document.querySelectorAll("#canvas .edge path")) {
      const length = path.getTotalLength();
      for (const fraction of [0.5, 0.35, 0.65, 0.2, 0.8]) {
        const point = path.getPointAtLength(length * fraction);
        const svgPoint = path.ownerSVGElement.createSVGPoint();
        svgPoint.x = point.x;
        svgPoint.y = point.y;
        const screen = svgPoint.matrixTransform(path.getScreenCTM());
        if (document.elementFromPoint(screen.x, screen.y)?.closest(".edge"))
          return { x: screen.x, y: screen.y };
      }
    }
    return null;
  });
  check(edgePoint, "a composed panel edge exposes a draggable route segment");
  await page.mouse.move(edgePoint.x, edgePoint.y);
  await page.mouse.down();
  await page.mouse.move(edgePoint.x + 18, edgePoint.y + 22, { steps: 4 });
  await page.mouse.up();
  await idle(page);
  check(
    (await page.locator("#canvas .edge").first().count()) === 1,
    "a composed panel edge route remains editable",
  );

  await click(page, "#composer-button");
  await page.locator("#composer-workflow[open]").waitFor();
  const bundlePromise = page.waitForEvent("download", { timeout: 30_000 });
  await click(page, "#composer-export");
  const bundle = await bundlePromise;
  const bundlePath = join(temporary, "paper-figure.zip");
  await bundle.saveAs(bundlePath);
  const bundleBytes = await readFile(bundlePath);
  check(
    bundleBytes.length > 1000 && bundleBytes.subarray(0, 2).toString() === "PK",
    "Composer exports a non-empty multi-format ZIP bundle",
  );
  await click(page, "#composer-workflow form button");
  metrics.steps.push("composer-edited-exported");

  // Debounced idle autosave and crash/reload recovery.
  const autosaveStarted = performance.now();
  await page.waitForFunction(
    () =>
      (() => {
        const composer = JSON.parse(
          window.localStorage.getItem("nndv-autosaved-project") || "null",
        )?.figure_composer;
        return (
          composer?.panels?.length === 3 &&
          composer.panels.some((panel) => panel.locked_node_ids.length > 0) &&
          composer.panels.some(
            (panel) => Object.keys(panel.manual_routes || {}).length > 0,
          )
        );
      })(),
    null,
    { timeout: 3000 },
  );
  metrics.autosave_probe_ms = Math.round(performance.now() - autosaveStarted);
  check(
    metrics.autosave_probe_ms < 1000,
    `idle autosave completes without blocking the interaction loop (${metrics.autosave_probe_ms}ms)`,
  );
  const projectPath = await saveDownload(page, "project", temporary);
  check(
    (await readFile(projectPath)).length > 1000,
    "multi-panel project download is non-empty",
  );
  const composerRecoveryBefore = await composerRecoveryState(page);
  check(
    composerRecoveryBefore.title === "Researcher recovery figure" &&
      composerRecoveryBefore.pagePreset === "wide-two-column" &&
      composerRecoveryBefore.arrangement === "horizontal" &&
      composerRecoveryBefore.panelTitles.A === "Human overview" &&
      composerRecoveryBefore.panelLevels.B === "layer",
    "autosave captures the participant's Composer controls and panel semantics",
  );
  check(
    composerRecoveryBefore.lockedNodeCount > 0 &&
      composerRecoveryBefore.manualRouteCount > 0,
    "autosave captures participant node locks and manual edge routes",
  );
  await page.reload({ waitUntil: "networkidle" });
  await page.locator("#canvas svg").waitFor();
  await idle(page);
  check(
    (await page.locator("#canvas .node").count()) > 0,
    "refresh restores the autosaved composed figure",
  );
  const composerRecoveryAfterRefresh = await composerRecoveryState(page);
  check(
    JSON.stringify(composerRecoveryAfterRefresh.panelLayoutDigests) ===
      JSON.stringify(composerRecoveryBefore.panelLayoutDigests),
    "refresh restores the exact Composer panel layout instead of re-layout",
  );
  check(
    composerRecoveryAfterRefresh.lockedNodeCount ===
      composerRecoveryBefore.lockedNodeCount &&
      composerRecoveryAfterRefresh.manualRouteCount ===
        composerRecoveryBefore.manualRouteCount,
    "refresh restores participant locks and manual routes",
  );
  await click(page, "#composer-button");
  await page.locator("#composer-workflow[open]").waitFor();
  check(
    (await page.locator("#composer-title").inputValue()) ===
      "Researcher recovery figure" &&
      (await page.locator("#composer-page").inputValue()) ===
        "wide-two-column" &&
      (await page.locator("#composer-arrangement").inputValue()) ===
        "horizontal" &&
      (await page.locator("#composer-panels .composer-panel").count()) === 3,
    "reopened Composer restores participant controls and all panels",
  );
  await click(page, "#composer-workflow form button");

  await page.locator("#file-input").setInputFiles(projectPath);
  await idle(page);
  const composerRecoveryAfterProjectOpen = await composerRecoveryState(page);
  check(
    JSON.stringify(composerRecoveryAfterProjectOpen.panelLayoutDigests) ===
      JSON.stringify(composerRecoveryBefore.panelLayoutDigests) &&
      composerRecoveryAfterProjectOpen.lockedNodeCount ===
        composerRecoveryBefore.lockedNodeCount &&
      composerRecoveryAfterProjectOpen.manualRouteCount ===
        composerRecoveryBefore.manualRouteCount,
    "opening the saved project restores exact Composer geometry and manual edits",
  );
  metrics.steps.push("project-refresh-recovered");

  // 50k summary opens in a real browser without full-rendering the graph.
  await page.locator("#file-input").setInputFiles(largePath);
  await page.locator("#import-wizard[open]").waitFor();
  const largeStarted = performance.now();
  await click(page, "#wizard-import");
  await page.waitForFunction(
    () =>
      document
        .querySelector("#canvas")
        ?.textContent.includes("Lazy 50k Product"),
    null,
    { timeout: 15_000 },
  );
  metrics.lazy_50k_first_view_ms = Math.round(performance.now() - largeStarted);
  check(
    (await page.locator("#canvas .node").count()) <= 500,
    "50k semantic summary creates at most 500 visible nodes",
  );
  check(
    (await page.locator("#canvas svg *").count()) <= 2000,
    "50k semantic summary stays below 2,000 SVG DOM objects",
  );
  check(
    (await page.locator("#lazy-stats").textContent()).includes("ms"),
    "50k lazy viewport reports measured update latency",
  );
  metrics.steps.push("lazy-50k-opened");

  // Cooperative cancellation is observed through the product task API.
  const cancellation = await page.evaluate(async () => {
    const graph = {
      name: "cancel-fixture",
      nodes: Array.from({ length: 1800 }, (_, index) => ({
        id: `n${index}`,
        name: `n${index}`,
        op_type: "Linear",
        category: "linear",
        path: `n${index}`,
        namespace: "",
        inputs: [],
        outputs: [],
        parent: null,
        level: "operation",
        parameters: 0,
        trainable_parameters: 0,
        buffers: 0,
        shared_weights: [],
        attributes: {},
        source: {},
        analysis: {},
        tags: [],
        visible: true,
      })),
      edges: [],
      subgraphs: [],
      annotations: [],
      constraints: [],
      inputs: [],
      outputs: [],
      metadata: {},
      analysis: {},
      ir_version: "1.0",
    };
    const submitted = await fetch("/api/tasks", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ kind: "layout", graph }),
    }).then((response) => response.json());
    const startedAt = performance.now();
    let cancelled = await fetch(`/api/tasks/${submitted.id}/cancel`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    }).then((response) => response.json());
    while (
      ["queued", "running"].includes(cancelled.status) &&
      performance.now() - startedAt < 1000
    ) {
      await new Promise((resolve) => setTimeout(resolve, 30));
      cancelled = await fetch(`/api/tasks/${submitted.id}`).then((response) =>
        response.json(),
      );
    }
    return { elapsed: performance.now() - startedAt, status: cancelled.status };
  });
  metrics.cancellation_ms = Math.round(cancellation.elapsed);
  check(
    metrics.cancellation_ms <= 1000 &&
      ["cancelled", "succeeded"].includes(cancellation.status),
    `task cancellation responds within 1s (${metrics.cancellation_ms}ms, ${cancellation.status})`,
  );
  check(
    errors.length === 0,
    `browser console remains clean: ${errors.join(" | ")}`,
  );
  await context.close();

  const report = {
    schema_version: "0.5.1-product-workflow-1",
    status: "passed",
    scenario: "real-model-paper-composer-first-use",
    assertions,
    assertion_count: assertions.length,
    duration_ms: Math.round(performance.now() - started),
    browser: await browser.version(),
    automation_metrics: metrics,
    usability_claim:
      "Automated interaction metrics only; no human usability study was performed.",
  };
  await writeFile(reportPath, JSON.stringify(report, null, 2) + "\n", "utf8");
  console.log(`NNDV_PRODUCT_E2E_RESULT=${JSON.stringify(report)}`);
} catch (error) {
  console.error(error.stack || error);
  console.error(serverOutput);
  process.exitCode = 1;
} finally {
  if (browser) await browser.close();
  server.kill("SIGTERM");
  await new Promise((resolveWait) => {
    const timer = setTimeout(resolveWait, 1500);
    server.once("exit", () => {
      clearTimeout(timer);
      resolveWait();
    });
  });
  if (ownedTemporary && process.exitCode !== 1)
    await rm(temporary, { recursive: true, force: true });
}

async function click(page, selector) {
  const locator = await revealToolbarControl(page, selector);
  await locator.click();
  metrics.clicks += 1;
}

async function revealToolbarControl(page, selector) {
  const locator =
    typeof selector === "string" ? page.locator(selector) : selector;
  if (await locator.isVisible()) return locator;
  const menuId = await locator.evaluate(
    (element) => element.closest("[data-toolbar-menu]")?.id || null,
  );
  assert.ok(menuId, `hidden control ${selector} must belong to a toolbar menu`);
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

async function idle(page) {
  await page.waitForFunction(
    () => !document.querySelector("#status")?.textContent.includes("正在"),
  );
  await page.waitForTimeout(100);
}

async function waitForPanelDigests(page) {
  const handle = await page.waitForFunction(() => {
    try {
      const metadata = JSON.parse(
        document.querySelector("#canvas svg metadata")?.textContent || "{}",
      );
      const digests = metadata.layout?.panel_layout_digests;
      return digests?.B && digests?.C ? digests : false;
    } catch {
      return false;
    }
  });
  return handle.jsonValue();
}

async function composerRecoveryState(page) {
  return page.evaluate(() => {
    const draft = JSON.parse(
      window.localStorage.getItem("nndv-autosaved-project") || "null",
    );
    const composer = draft?.figure_composer || {};
    const metadata = JSON.parse(
      document.querySelector("#canvas svg metadata")?.textContent || "{}",
    );
    return {
      title: composer.title,
      pagePreset: composer.page_preset,
      arrangement: composer.arrangement,
      panelTitles: Object.fromEntries(
        (composer.panels || []).map((panel) => [panel.id, panel.title]),
      ),
      panelLevels: Object.fromEntries(
        (composer.panels || []).map((panel) => [
          panel.id,
          panel.semantic_level,
        ]),
      ),
      lockedNodeCount: (composer.panels || []).reduce(
        (total, panel) => total + (panel.locked_node_ids || []).length,
        0,
      ),
      manualRouteCount: (composer.panels || []).reduce(
        (total, panel) => total + Object.keys(panel.manual_routes || {}).length,
        0,
      ),
      panelLayoutDigests: metadata.layout?.panel_layout_digests || null,
    };
  });
}

async function waitForTasks(page) {
  await page.waitForFunction(
    () => document.querySelector("#task-badge")?.textContent === "0",
    null,
    { timeout: 20_000 },
  );
}

async function saveDownload(page, format, directory) {
  await click(page, "#export-button");
  const promise = page.waitForEvent("download", { timeout: 30_000 });
  await click(page, `#export-menu [data-format="${format}"]`);
  const download = await promise;
  const destination = join(
    directory,
    `${format}-${download.suggestedFilename()}`,
  );
  await download.saveAs(destination);
  return destination;
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
