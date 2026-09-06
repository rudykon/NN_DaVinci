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
const ownedTemporary = !process.env.NNDV_SEMANTIC_E2E_DIR;
const temporary =
  process.env.NNDV_SEMANTIC_E2E_DIR ||
  (await mkdtemp(join(tmpdir(), "nndv-semantic-e2e-")));
await mkdir(temporary, { recursive: true });
const reportPath =
  process.env.NNDV_SEMANTIC_E2E_REPORT ||
  join(temporary, "semantic-workflow.json");
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
let browser;
const assertions = [];
const check = (condition, message) => {
  assert.ok(condition, message);
  assertions.push(message);
};

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
  await page.goto(baseURL, { waitUntil: "networkidle" });
  await page.locator("#canvas svg").waitFor();

  // 0. A real browser opens a 10k operation graph through semantic summary;
  // no synchronous full-render limit is relaxed.
  const largePath = join(temporary, "lazy-10k.json");
  await writeFile(
    largePath,
    JSON.stringify({
      name: "Lazy 10k",
      layers: Array.from({ length: 10_000 }, (_, index) => ({
        name: `Operation ${index}`,
        type: "Linear",
        category: "linear",
      })),
    }),
    "utf8",
  );
  await page.locator("#file-input").setInputFiles(largePath);
  await page.locator("#import-wizard[open]").waitFor();
  const largeStarted = performance.now();
  await page.locator("#wizard-import").click();
  await page.waitForFunction(
    () => document.querySelector("#canvas")?.textContent.includes("Lazy 10k"),
    null,
    { timeout: 10_000 },
  );
  const firstInteractiveMs = performance.now() - largeStarted;
  check(
    firstInteractiveMs <= 2000,
    `10k first interactive semantic view is <=2s (${firstInteractiveMs.toFixed(1)}ms)`,
  );
  check(
    (await page.locator("#canvas .node").count()) <= 500,
    "10k browser creates at most 500 visible nodes",
  );
  check(
    (await page.locator("#canvas svg *").count()) <= 2000,
    "10k browser creates at most 2,000 SVG DOM objects",
  );
  check(
    (await page.locator("#lazy-stats").textContent()).includes("DOM"),
    "lazy viewport publishes measured slice budgets",
  );

  // 1. Safe, guided import with scale/view recommendation.
  await page
    .locator("#file-input")
    .setInputFiles(join(projectRoot, "examples", "transformer.json"));
  await page.locator("#import-wizard[open]").waitFor();
  check(
    (await page.locator("#import-plan").textContent()).includes("safe-data"),
    "wizard displays the non-executing safety level",
  );
  check(
    (await page.locator("#import-plan").textContent()).includes("Sample input"),
    "wizard explains sample input, size, and initial view",
  );
  await page.locator("#wizard-shape").fill("1,196,768");
  await page.locator("#wizard-import").click();
  await page.locator("#import-wizard").waitFor({ state: "hidden" });
  await waitForTasks(page);
  await idle(page);
  check(
    (await page.locator("#canvas").textContent()).includes("Transformer"),
    "guided import opens the local Transformer without weights",
  );

  // 2. Five-level drilldown and round-trip navigation.
  await selectToolbarOption(page, "#semantic-level", "framework");
  await idle(page);
  check(
    (await page.locator("#canvas .node").count()) === 1,
    "framework level is a bounded semantic summary",
  );
  await page.locator("#canvas .node").first().dispatchEvent("dblclick");
  await idle(page);
  check(
    (await page.locator("#semantic-level").inputValue()) === "stage",
    "double-click drills from framework to stage",
  );
  await page.locator("#canvas .node").first().dispatchEvent("dblclick");
  await idle(page);
  check(
    (await page.locator("#semantic-level").inputValue()) === "block",
    "double-click drills to block",
  );
  await page.locator("#canvas .node").first().dispatchEvent("dblclick");
  await idle(page);
  check(
    (await page.locator("#semantic-level").inputValue()) === "module",
    "double-click drills from block to author-facing module",
  );
  await page.locator("#canvas .node").first().dispatchEvent("dblclick");
  await idle(page);
  check(
    (await page.locator("#semantic-level").inputValue()) === "operation",
    "drilldown reaches operation level",
  );

  // 3-4. Full-graph search maps into the semantic slice and inspector keeps
  // analysis plus source provenance.
  await page.locator('.tab[data-tab="structure"]').click();
  await page.locator("#graph-search").fill("Attention");
  const attentionTree = page.locator("#structure-tree [data-node]").filter({
    hasText: "Attention",
  });
  await attentionTree.first().click();
  await idle(page);
  check(
    (await page.locator("#canvas .node.selected").count()) >= 1,
    "search locates and selects an operation through source mapping",
  );
  const inspector = await page.locator("#inspector").textContent();
  check(
    inspector.includes("provenance") && inspector.includes("confidence"),
    "inspector exposes semantic confidence and source provenance",
  );
  check(
    inspector.includes("参数") || inspector.includes("flops"),
    "inspector exposes parameter/FLOP analysis evidence",
  );

  // 5-6. Paper View and review-before-apply optimization.
  await selectToolbarOption(page, "#semantic-view", "paper");
  await idle(page);
  await clickToolbarControl(page, "#optimize-button");
  await page.locator("#generate-suggestions").click();
  await page.locator(".suggestion-card").first().waitFor();
  check(
    (await page.locator(".suggestion-card").count()) <= 3,
    "paper optimizer returns at most three candidates",
  );
  check(
    (await page.locator(".metric-diff tr").count()) >= 11,
    "candidate shows all before/after objectives",
  );
  await page.locator("[data-apply-suggestion]").first().click();
  await page.locator("#paper-workflow").evaluate((dialog) => dialog.close());
  await idle(page);

  // 7. One manual node edit and one manual edge route after optimization.
  const node = page.locator("#canvas .node").first();
  const nodeBox = await node.boundingBox();
  check(nodeBox, "optimized node has draggable geometry");
  await node.hover();
  await page.mouse.down();
  await page.mouse.move(nodeBox.x + nodeBox.width / 2 + 28, nodeBox.y + 24, {
    steps: 4,
  });
  await page.mouse.up();
  await idle(page);
  const edge = page.locator("#canvas .edge").first();
  const edgeBox = await edge.boundingBox();
  check(edgeBox, "optimized edge has editable geometry");
  await page.mouse.move(
    edgeBox.x + edgeBox.width / 2,
    edgeBox.y + edgeBox.height / 2,
  );
  await page.mouse.down();
  await page.mouse.move(
    edgeBox.x + edgeBox.width / 2 + 18,
    edgeBox.y + edgeBox.height / 2 + 22,
    { steps: 4 },
  );
  await page.mouse.up();
  await idle(page);

  // 8. Explicit save persists an autosaved local draft across refresh.
  const projectPath = await saveDownload(page, "project", temporary);
  const project = JSON.parse(await readFile(projectPath, "utf8"));
  check(
    project.semantic_view.level === "operation" &&
      project.semantic_view.view === "paper",
    "project stores semantic level and view",
  );
  check(
    project.graph.constraints.some((item) => item.kind === "position"),
    "project stores the manual node position",
  );
  await page.reload({ waitUntil: "networkidle" });
  await page.locator("#canvas svg").waitFor();
  check(
    (await page.locator("#semantic-view").inputValue()) === "paper",
    "refresh restores the saved local semantic workflow",
  );

  // 9. Four publication targets, including editable PPTX.
  for (const format of ["svg", "pdf", "tikz", "pptx"]) {
    const output = await saveDownload(page, format, temporary);
    const data = await readFile(output);
    check(data.length > 100, `${format} export is non-empty`);
  }
  await clickToolbarControl(page, "#tasks-button");
  check(
    (await page.locator("#task-list").textContent()).includes("succeeded"),
    "task center survives the workflow and shows successful local jobs",
  );
  check(
    errors.length === 0,
    `browser console remains clean: ${errors.join(" | ")}`,
  );
  await context.close();

  const report = {
    schema_version: "0.3.0-semantic-workflow-1",
    status: "passed",
    scenario: "semantic-paper-export-loop",
    assertions,
    assertion_count: assertions.length,
    duration_ms: Math.round(performance.now() - started),
    browser: await browser.version(),
    performance: {
      lazy_10k_first_view_ms: Math.round(firstInteractiveMs * 10) / 10,
      baseline_0_3_0_ms: 1678.1,
      no_regression: firstInteractiveMs <= 1678.1,
    },
  };
  await import("node:fs/promises").then(({ writeFile }) =>
    writeFile(reportPath, JSON.stringify(report, null, 2) + "\n", "utf8"),
  );
  console.log(`NNDV_SEMANTIC_E2E_RESULT=${JSON.stringify(report)}`);
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

async function idle(page) {
  await page.waitForFunction(
    () => !document.querySelector("#status")?.textContent.includes("正在"),
  );
  await page.waitForTimeout(100);
}

async function revealToolbarControl(page, selector) {
  const locator = page.locator(selector);
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

async function clickToolbarControl(page, selector) {
  const locator = await revealToolbarControl(page, selector);
  await locator.click();
}

async function selectToolbarOption(page, selector, value) {
  const locator = await revealToolbarControl(page, selector);
  await locator.selectOption(value);
}

async function waitForTasks(page) {
  await page.waitForFunction(
    () => document.querySelector("#task-badge")?.textContent === "0",
    null,
    { timeout: 15_000 },
  );
}

async function saveDownload(page, format, directory) {
  await page.locator("#export-button").click();
  const promise = page.waitForEvent("download", { timeout: 30_000 });
  await page.locator(`#export-menu [data-format="${format}"]`).click();
  const download = await promise;
  const destination = join(
    directory,
    `${Date.now()}-${format}-${download.suggestedFilename()}`,
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
