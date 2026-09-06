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
const ownedTemporary = !process.env.NNDV_TRIAL_E2E_DIR;
const temporary =
  process.env.NNDV_TRIAL_E2E_DIR ||
  (await mkdtemp(join(tmpdir(), "nndv-trial-e2e-")));
await mkdir(temporary, { recursive: true });
const reportPath =
  process.env.NNDV_TRIAL_E2E_REPORT || join(temporary, "trial-workflow.json");
const trialRoot = join(temporary, "local-trial-json");
const cases = [
  "dynamic_pytorch",
  "onnx_multi_io",
  "shared_siamese",
  "transformer_residual",
  "unet_skip",
  "custom_unknown",
];
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
    env: {
      ...process.env,
      PYTHONPATH: join(projectRoot, "src"),
      NNDV_TRIAL_ROOT: trialRoot,
    },
    stdio: ["ignore", "pipe", "pipe"],
  },
);
let serverOutput = "";
server.stdout.on("data", (chunk) => (serverOutput += chunk));
server.stderr.on("data", (chunk) => (serverOutput += chunk));
const assertions = [];
const caseMetrics = {};
const startedAt = performance.now();
let clicks = 0;
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
  await page.goto(baseURL, { waitUntil: "networkidle" });
  await page.locator("#canvas svg").waitFor();

  const initial = await page.evaluate(() =>
    fetch("/api/trial/status").then((response) => response.json()),
  );
  check(initial.enabled === false, "Trial Mode is disabled by default");
  check(initial.session_count === 0, "no trial session exists before consent");
  await click(page, "#trial-button");
  await page.locator("#trial-workflow[open]").waitFor();
  await page.waitForFunction(
    () =>
      document.querySelectorAll("#trial-case-list [data-trial-case]").length ===
      6,
  );
  check(
    (await page.locator("#trial-case-list [data-trial-case]").count()) === 6,
    "Trial Mode exposes six independent model cases",
  );
  await page.locator("#trial-consent").check();
  clicks += 1;
  await click(page, "#trial-consent-apply");
  await page.waitForFunction(
    () => document.querySelector("#trial-indicator")?.textContent === "开",
  );
  check(
    (await page.locator("#trial-status").textContent()).includes(
      "本地记录已启用",
    ),
    "explicit consent enables local-only recording",
  );

  for (const caseKey of cases) {
    const caseStarted = performance.now();
    await openTrialCaseFromChooser(page, caseKey);
    await page.locator("#trial-workflow").waitFor({ state: "hidden" });
    await idle(page);
    await page.waitForTimeout(1200);
    await resolveAutosaveConflictIfPresent(page);
    check(
      (await page.locator("#canvas .node").count()) > 0,
      `${caseKey} opens from the Web trial chooser`,
    );
    await selectToolbarOption(page, "#semantic-view", "faithful");
    await idle(page);
    await selectToolbarOption(page, "#semantic-level", "operation");
    await idle(page);
    await selectToolbarOption(page, "#semantic-view", "paper");
    await idle(page);
    check(
      (await page.locator("#semantic-level").inputValue()) === "operation" &&
        (await page.locator("#semantic-view").inputValue()) === "paper",
      `${caseKey} supports semantic audit and Paper View`,
    );

    await click(page, "#composer-button");
    await page.locator("#composer-workflow[open]").waitFor();
    check(
      (await page.locator("#composer-panels .composer-panel").count()) === 2,
      `${caseKey} starts a two-panel block/evidence composition`,
    );
    await click(page, "#composer-preview");
    await page.waitForFunction(
      () =>
        /[0-9]+(?:\.[0-9]+)? pt 最小字号/.test(
          document.querySelector("#composer-proof")?.textContent || "",
        ),
      null,
      { timeout: 30_000 },
    );
    await idle(page);
    const proofText = await page.locator("#composer-proof").textContent();
    const minimumFontPt = Number(
      proofText.match(/([0-9]+(?:\.[0-9]+)?) pt 最小字号/)?.[1],
    );
    check(
      minimumFontPt >= 7 && !proofText.includes("无法"),
      `${caseKey} reaches a paper-ready >=7 pt Composer proof (measured ${minimumFontPt || "missing"} pt)`,
    );
    await click(page, "#composer-workflow form button");
    await makeComposerManualEdit(page);
    await waitForComposerManualAutosave(page, caseKey);
    const manualState = await composerRecoveryState(page);
    check(
      manualState.lockedNodeCount > 0 && manualState.manualRouteCount > 0,
      `${caseKey} records the deliberate node and edge edits required by T4`,
    );
    await click(page, "#composer-button");
    await page.locator("#composer-workflow[open]").waitFor();
    const bundlePromise = page.waitForEvent("download", { timeout: 30_000 });
    await click(page, "#composer-export");
    const bundle = await bundlePromise;
    const bundlePath = join(temporary, `${caseKey}-paper-figure.zip`);
    await bundle.saveAs(bundlePath);
    check(
      (await readFile(bundlePath)).subarray(0, 2).toString() === "PK",
      `${caseKey} exports the editable Composer bundle`,
    );
    await click(page, "#composer-workflow form button");
    const projectPromise = page.waitForEvent("download", { timeout: 30_000 });
    await click(page, "#export-button");
    await click(page, '#export-menu [data-format="project"]');
    const project = await projectPromise;
    const projectPath = join(temporary, `${caseKey}.nndv.json`);
    await project.saveAs(projectPath);
    await waitForComposerManualAutosave(page, caseKey);
    await page.reload({ waitUntil: "networkidle" });
    await page.locator("#canvas svg").waitFor();
    await idle(page);
    check(
      (await page.locator("#canvas .node").count()) > 0,
      `${caseKey} project and Composer recover after refresh`,
    );
    const refreshedState = await composerRecoveryState(page);
    check(
      JSON.stringify(refreshedState.panelLayoutDigests) ===
        JSON.stringify(manualState.panelLayoutDigests) &&
        refreshedState.lockedNodeCount === manualState.lockedNodeCount &&
        refreshedState.manualRouteCount === manualState.manualRouteCount,
      `${caseKey} refresh preserves exact Panel geometry, locks and routes`,
    );
    await page.locator("#file-input").setInputFiles(projectPath);
    await idle(page);
    const reopenedState = await composerRecoveryState(page);
    check(
      JSON.stringify(reopenedState.panelLayoutDigests) ===
        JSON.stringify(manualState.panelLayoutDigests) &&
        reopenedState.lockedNodeCount === manualState.lockedNodeCount &&
        reopenedState.manualRouteCount === manualState.manualRouteCount,
      `${caseKey} saved project preserves exact Composer state`,
    );
    await click(page, "#trial-button");
    await page.locator("#trial-workflow[open]").waitFor();
    await click(page, "#trial-finish");
    await page.waitForFunction(() =>
      document
        .querySelector("#trial-status")
        ?.textContent.includes("尚未开始任务"),
    );
    caseMetrics[caseKey] = {
      automated_elapsed_ms: Math.round(performance.now() - caseStarted),
      completed: true,
    };
  }

  const exportData = await page.evaluate(() =>
    fetch("/api/trial/export").then((response) => response.json()),
  );
  check(
    exportData.sessions.length === 6,
    "six completed local JSON sessions persist",
  );
  check(
    exportData.sessions.every((session) => session.status === "completed"),
    "all six Web trial workflows are completed",
  );
  check(
    exportData.sessions.every(
      (session) =>
        !JSON.stringify(session).includes(projectRoot) &&
        !JSON.stringify(session).includes(".nndv.json"),
    ),
    "local trial events contain no workspace path or project filename",
  );
  check(
    exportData.aggregate.core_task_success_rate === 1,
    "automated kit workflow records all four required exports for every case",
  );
  check(
    exportData.sessions.every((session) => {
      const edits = session.events.find(
        (event) => event.event_type === "edit_summary",
      );
      return edits?.node_changes > 0 && edits?.edge_changes > 0;
    }),
    "all six automated task paths retain distinct node and edge edit counts",
  );
  check(
    exportData.aggregate.human_conclusion_ready === false,
    "automated sessions never authorize a human-study conclusion",
  );
  check(
    errors.length === 0,
    `browser console remains clean: ${errors.join(" | ")}`,
  );

  const report = {
    schema_version: "0.5.1-trial-workflow-e2e-1",
    status: "passed",
    scenario: "consented-local-six-case-researcher-trial-kit",
    assertion_count: assertions.length,
    assertions,
    cases: caseMetrics,
    automated_metrics: {
      measurement_source: "chrome-automation",
      clicks,
      steps: cases.length * 8,
      duration_ms: Math.round(performance.now() - startedAt),
    },
    human_participants: 0,
    human_usability_claim: false,
    note: "Automated kit readiness only; this run is not a researcher trial and is not counted as a participant.",
  };
  await writeFile(reportPath, JSON.stringify(report, null, 2) + "\n", "utf8");
  console.log(`NNDV_TRIAL_E2E_RESULT=${JSON.stringify(report)}`);
  await context.close();
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
  clicks += 1;
}

async function resolveAutosaveConflictIfPresent(page) {
  const dialog = page.locator("#autosave-conflict-dialog[open]");
  if (!(await dialog.isVisible())) return;
  await page.locator("#autosave-overwrite-stored").click();
  clicks += 1;
  await page.locator("#autosave-conflict-dialog").waitFor({ state: "hidden" });
}

async function openTrialCaseFromChooser(page, caseKey) {
  // Autosave runs after a 350 ms debounce and may then wait up to 800 ms for
  // an idle callback.  Give that deterministic window time to settle before
  // switching cases so a late conflict cannot close the chooser mid-click.
  await page.waitForTimeout(1300);
  const chooser = page.locator("#trial-workflow[open]");
  const conflict = page.locator("#autosave-conflict-dialog[open]");
  const choice = page.locator(`[data-trial-case="${caseKey}"]`);

  for (let attempt = 0; attempt < 3; attempt += 1) {
    await resolveAutosaveConflictIfPresent(page);
    if (!(await chooser.isVisible())) {
      await click(page, "#trial-button");
      await chooser.waitFor();
      await page.waitForFunction(
        () =>
          document
            .querySelector("#trial-workflow")
            ?.getAttribute("aria-busy") === "false",
      );
    }
    await page.waitForTimeout(100);
    if (await conflict.isVisible()) continue;
    try {
      await choice.click({ timeout: 5000 });
      clicks += 1;
      return;
    } catch (error) {
      if ((await conflict.isVisible()) || !(await chooser.isVisible()))
        continue;
      throw error;
    }
  }
  throw new Error(`Trial chooser did not stabilize for ${caseKey}`);
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
    null,
    { timeout: 30_000 },
  );
  await page.waitForTimeout(100);
}

async function makeComposerManualEdit(page) {
  const node = page.locator("#canvas .node").first();
  const nodeBox = await node.boundingBox();
  assert.ok(nodeBox, "composed figure exposes a draggable node");
  await node.hover();
  await page.mouse.down();
  await page.mouse.move(
    nodeBox.x + nodeBox.width / 2 + 24,
    nodeBox.y + nodeBox.height / 2 + 18,
  );
  await page.mouse.up();
  await idle(page);
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
  assert.ok(edgePoint, "composed figure exposes a draggable edge route");
  await page.mouse.move(edgePoint.x, edgePoint.y);
  await page.mouse.down();
  await page.mouse.move(edgePoint.x + 18, edgePoint.y + 22, { steps: 4 });
  await page.mouse.up();
  await idle(page);
}

async function waitForComposerManualAutosave(page, caseKey) {
  await page.waitForFunction(
    (expectedCase) => {
      const composer = JSON.parse(
        window.localStorage.getItem("nndv-autosaved-project") || "null",
      )?.figure_composer;
      const panels = composer?.panels;
      return (
        panels?.[0]?.graph?.metadata?.external_trial_case === expectedCase &&
        panels?.some((panel) => panel.locked_node_ids.length > 0) &&
        panels.some(
          (panel) => Object.keys(panel.manual_routes || {}).length > 0,
        )
      );
    },
    caseKey,
    { timeout: 3000 },
  );
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
