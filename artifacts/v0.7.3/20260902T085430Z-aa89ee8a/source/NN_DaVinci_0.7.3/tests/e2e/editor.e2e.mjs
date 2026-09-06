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
const ownedTemporary = !process.env.NNDV_E2E_DIR;
const temporary =
  process.env.NNDV_E2E_DIR || (await mkdtemp(join(tmpdir(), "nndv-e2e-")));
await mkdir(temporary, { recursive: true });
const reportPath =
  process.env.NNDV_E2E_REPORT || join(temporary, "scenarios.json");
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
server.stdout.on("data", (chunk) => {
  serverOutput += chunk;
});
server.stderr.on("data", (chunk) => {
  serverOutput += chunk;
});

const specifications = [
  [
    "load-console-security",
    ["homepage-load", "console-clean", "http-status"],
    async ({ page, check }) => {
      check.equal(
        await page.locator("#canvas svg").count(),
        1,
        "homepage must render an SVG",
      );
      check.equal(
        await page.locator(".toast.error:not(.hidden)").count(),
        0,
        "no error toast",
      );
      const missing = await page.request.get(
        `${baseURL}/definitely-missing.svg`,
      );
      check.equal(missing.status(), 404, "missing assets retain HTTP 404");
      const favicon = await page.request.get(`${baseURL}/favicon.ico`);
      check.ok(
        [200, 404].includes(favicon.status()),
        "favicon must not be converted to 500",
      );
    },
  ],
  [
    "node-drag-coordinates",
    ["palette-drag", "node-position"],
    async ({ page, check }) => {
      const initial = await page.locator("#canvas .node").count();
      await page
        .locator(".palette-item")
        .first()
        .dragTo(page.locator("#canvas-shell"), {
          targetPosition: { x: 360, y: 240 },
        });
      await idle(page);
      check.equal(
        await page.locator("#canvas .node").count(),
        initial + 1,
        "palette drag adds one node",
      );
      const node = page.locator("#canvas .node").last();
      const before = await coordinates(node);
      const box = await node.boundingBox();
      check.ok(box, "dragged node has geometry");
      await node.hover();
      await page.mouse.down();
      await page.mouse.move(
        box.x + box.width / 2 + 46,
        box.y + box.height / 2 + 34,
        { steps: 6 },
      );
      await page.mouse.up();
      await idle(page);
      const after = await coordinates(page.locator("#canvas .node").last());
      check.ok(
        Math.hypot(after.x - before.x, after.y - before.y) > 20,
        "node IR coordinates change after drag",
      );
    },
  ],
  [
    "connect-route-constraint",
    ["connect", "edge-route-control-points"],
    async ({ page, check }) => {
      await selectNodes(page, [0, 1]);
      const before = await page.locator("#canvas .edge").count();
      await canvasAction(page, "connect");
      await idle(page);
      check.equal(
        await page.locator("#canvas .edge").count(),
        before + 1,
        "connect adds an edge",
      );
      const edge = page.locator("#canvas .edge").last();
      const box = await edge.boundingBox();
      check.ok(box, "edge has geometry");
      await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
      await page.mouse.down();
      await page.mouse.move(
        box.x + box.width / 2 + 24,
        box.y + box.height / 2 + 31,
        { steps: 5 },
      );
      await page.mouse.up();
      await idle(page);
      const project = JSON.parse(
        await readFile(await saveDownload(page, "project", temporary), "utf8"),
      );
      const route = project.graph.constraints.find(
        (item) => item.kind === "edge-route",
      );
      check.ok(route, "route edit persists as an edge-route constraint");
      check.ok(
        Array.isArray(route.value?.points) && route.value.points.length >= 3,
        "route constraint stores control points",
      );
    },
  ],
  [
    "align-distribute-lock-hide-geometry",
    ["align", "distribute", "lock", "hide"],
    async ({ page, check }) => {
      await selectNodes(page, [0, 1, 2]);
      await canvasAction(page, "align-y");
      await idle(page);
      const aligned = await nodeCoordinates(page, [0, 1, 2]);
      check.ok(
        aligned.every((item) => Math.abs(item.y - aligned[0].y) < 0.01),
        "horizontal align produces equal y coordinates",
      );
      await canvasAction(page, "distribute");
      await idle(page);
      const distributed = (await nodeCoordinates(page, [0, 1, 2])).sort(
        (a, b) => a.x - b.x,
      );
      const firstGap = distributed[1].x - distributed[0].x;
      const secondGap = distributed[2].x - distributed[1].x;
      check.ok(
        Math.abs(firstGap - secondGap) < 0.01,
        "distribution produces equal x gaps",
      );
      await canvasAction(page, "lock");
      await idle(page);
      const unlocked = JSON.parse(
        await readFile(await saveDownload(page, "project", temporary), "utf8"),
      );
      check.equal(
        unlocked.graph.constraints.filter(
          (item) => item.kind === "position" && item.locked,
        ).length,
        0,
        "first lock toggle unlocks the aligned selection",
      );
      await canvasAction(page, "lock");
      await idle(page);
      const locked = JSON.parse(
        await readFile(await saveDownload(page, "project", temporary), "utf8"),
      );
      check.ok(
        locked.graph.constraints.filter(
          (item) => item.kind === "position" && item.locked,
        ).length >= 3,
        "lock stores locked position constraints",
      );
      await selectNodes(page, [0]);
      const visible = await page.locator("#canvas .node").count();
      await canvasAction(page, "hide");
      await idle(page);
      check.equal(
        await page.locator("#canvas .node").count(),
        visible - 1,
        "hide changes rendered graph geometry",
      );
    },
  ],
  [
    "undo-redo-state",
    ["undo", "redo", "layout-history"],
    async ({ page, check }) => {
      const initial = await page.locator("#canvas .node").count();
      await page
        .locator(".palette-item")
        .first()
        .dragTo(page.locator("#canvas-shell"), {
          targetPosition: { x: 330, y: 210 },
        });
      await idle(page);
      const added = await page.locator("#canvas .node").count();
      check.equal(added, initial + 1, "setup mutation applied");
      await page.locator("#undo-button").click();
      await idle(page);
      check.equal(
        await page.locator("#canvas .node").count(),
        initial,
        "undo restores graph state",
      );
      await page.locator("#redo-button").click();
      await idle(page);
      check.equal(
        await page.locator("#canvas .node").count(),
        added,
        "redo restores graph state",
      );
    },
  ],
  [
    "group-collapse-focus",
    ["group", "collapse-expand", "focus-restore", "delete-prunes-source-state"],
    async ({ page, check }) => {
      const full = await page.locator("#canvas .node").count();
      await selectNodes(page, [0, 1]);
      await submitTextEntry(page, ["E2E Group"], () =>
        canvasAction(page, "group"),
      );
      await idle(page);
      await canvasAction(page, "collapse");
      await idle(page);
      check.ok(
        await page.locator('#canvas .node text:text-is("E2E Group")').count(),
        "collapsed proxy is rendered",
      );
      const collapsed = await page.locator("#canvas .node").count();
      check.ok(collapsed < full, "collapse reduces visible nodes");
      await canvasAction(page, "collapse");
      await idle(page);
      await selectNodes(page, [0]);
      await canvasAction(page, "focus");
      await idle(page);
      check.ok(
        (await page.locator("#canvas .node").count()) < full,
        "focus renders a bounded neighborhood",
      );
      const focusedNodeId = await page
        .locator("#canvas .node.selected")
        .getAttribute("data-node-id");
      check.ok(focusedNodeId, "focused source node remains selected");
      await page.keyboard.press("Delete");
      await idle(page);
      const afterDelete = JSON.parse(
        await readFile(await saveDownload(page, "project", temporary), "utf8"),
      );
      check.ok(
        !afterDelete.graph.nodes.some((node) => node.id === focusedNodeId),
        "Delete removes the selected source node",
      );
      check.equal(
        afterDelete.layout.focus.includes(focusedNodeId),
        false,
        "Delete prunes removed node IDs from focus",
      );
      check.equal(
        afterDelete.canvas_state.selection.includes(focusedNodeId),
        false,
        "Delete prunes removed node IDs from source selection",
      );
      await selectNodes(page, [0]);
      await canvasAction(page, "focus");
      await idle(page);
      await canvasAction(page, "clear-focus");
      await idle(page);
      check.equal(
        await page.locator("#canvas .node").count(),
        full - 1,
        "clear focus restores the remaining full graph",
      );
    },
  ],
  [
    "source-switch-dialog-cancel",
    ["source-switch-cancels-stale-dialog"],
    async ({ page, check }) => {
      await selectNodes(page, [0]);
      await canvasAction(page, "comment");
      const dialog = page.locator("#text-entry-dialog");
      await dialog.waitFor({ state: "visible" });
      await dialog.locator('[data-entry-field="author"]').fill("Stale author");
      await dialog.locator('[data-entry-field="text"]').fill("Stale comment");
      await page.evaluate(() => document.querySelector("#new-button")?.click());
      await idle(page);
      check.equal(
        await dialog.count(),
        1,
        "text-entry dialog remains a stable DOM surface",
      );
      check.equal(
        await dialog.evaluate((element) => element.open),
        false,
        "source replacement closes the pending text-entry dialog",
      );
      const saved = JSON.parse(
        await readFile(await saveDownload(page, "project", temporary), "utf8"),
      );
      check.equal(
        saved.comments.some((comment) => comment.text === "Stale comment"),
        false,
        "source replacement cannot apply stale dialog values",
      );
    },
  ],
  [
    "annotation-presentation-persistence",
    ["annotation", "comment", "theme", "page", "typography", "perspective"],
    async ({ page, check }) => {
      await selectNodes(page, [0]);
      await submitTextEntry(page, ["Paper note"], () =>
        canvasAction(page, "text"),
      );
      await idle(page);
      await submitTextEntry(page, ["Ada", "Review routing"], () =>
        canvasAction(page, "comment"),
      );
      await idle(page);
      await selectToolbarOption(page, "#theme-select", "ieee");
      await idle(page);
      await selectToolbarOption(page, "#page-select", "double-column");
      await idle(page);
      await page.locator("#style-rank-gap").fill("77");
      await page.locator("#style-rank-gap").press("Enter");
      await idle(page);
      await clickToolbarControl(page, "#animate-button");
      await clickToolbarControl(page, "#perspective-button");
      check.ok(
        await page
          .locator("#canvas-shell")
          .evaluate((item) => item.classList.contains("perspective-mode")),
        "perspective class toggles",
      );
      check.ok(
        await page
          .locator("#canvas svg")
          .evaluate((item) => item.classList.contains("flowing")),
        "animation class toggles",
      );
      const saved = JSON.parse(
        await readFile(await saveDownload(page, "project", temporary), "utf8"),
      );
      check.equal(saved.theme, "ieee", "theme persists");
      check.equal(saved.export.page, "double-column", "page persists");
      check.equal(
        saved.layout.layout_options.rank_gap,
        77,
        "typography/layout option persists",
      );
      check.ok(
        saved.comments.some((item) => item.text === "Review routing"),
        "comment persists",
      );
      check.ok(
        saved.graph.annotations.some((item) => item.text === "Paper note"),
        "annotation persists",
      );
      check.equal(
        saved.presentation.teaching_animation,
        true,
        "animation state persists",
      );
      check.equal(
        saved.presentation.perspective_mode,
        true,
        "perspective state persists",
      );
    },
  ],
  [
    "project-round-trip",
    ["project-import", "graph-roundtrip", "presentation-roundtrip"],
    async ({ page, check }) => {
      await selectToolbarOption(page, "#theme-select", "ieee");
      await idle(page);
      await clickToolbarControl(page, "#perspective-button");
      const firstPath = await saveDownload(page, "project", temporary);
      const first = JSON.parse(await readFile(firstPath, "utf8"));
      await clickToolbarControl(page, "#new-button");
      await idle(page);
      await page.locator("#file-input").setInputFiles(firstPath);
      await idle(page);
      const second = JSON.parse(
        await readFile(await saveDownload(page, "project", temporary), "utf8"),
      );
      check.equal(
        second.graph.nodes.length,
        first.graph.nodes.length,
        "node set survives round trip",
      );
      check.equal(
        second.graph.edges.length,
        first.graph.edges.length,
        "edge set survives round trip",
      );
      check.equal(second.theme, first.theme, "theme survives round trip");
      check.equal(
        second.presentation.perspective_mode,
        true,
        "presentation state survives round trip",
      );
    },
  ],
  [
    "seven-format-downloads",
    ["svg", "pdf", "tikz", "png", "eps", "pptx", "html"],
    async ({ page, check }) => {
      const signatures = {
        svg: Buffer.from("<?xml"),
        pdf: Buffer.from("%PDF"),
        tikz: Buffer.from("\\documentclass"),
        png: Buffer.from([0x89, 0x50, 0x4e, 0x47]),
        eps: Buffer.from("%!PS"),
        pptx: Buffer.from("PK"),
        html: Buffer.from("<!doctype"),
      };
      for (const [format, signature] of Object.entries(signatures)) {
        const data = await readFile(
          await saveDownload(page, format, temporary),
        );
        check.ok(data.length > 100, `${format} is non-empty`);
        check.ok(
          data.subarray(0, signature.length).equals(signature),
          `${format} signature`,
        );
      }
    },
  ],
  [
    "dom-xss",
    ["project-import", "dom-xss"],
    async ({ page, check }) => {
      const source = JSON.parse(
        await readFile(await saveDownload(page, "project", temporary), "utf8"),
      );
      source.graph.nodes[0].name =
        '<img src=x onerror="window.__nndvXss=1"><script>window.__nndvXss=2</script>';
      const malicious = join(temporary, "malicious.nndv.json");
      await writeFile(malicious, JSON.stringify(source), "utf8");
      await page.locator("#file-input").setInputFiles(malicious);
      await idle(page);
      check.equal(
        await page.evaluate(() => window.__nndvXss),
        undefined,
        "malicious name does not execute",
      );
      check.equal(
        await page.locator('#canvas img[src="x"]').count(),
        0,
        "malicious HTML is not materialized",
      );
      check.ok(
        (await page.locator("#canvas").textContent()).includes("<img src=x"),
        "malicious text remains literal text",
      );
    },
  ],
];

let browser;
let browserVersion = "not-started";
const results = [];
let successful = false;
try {
  await waitForServer(`${baseURL}/api/state`);
  browser = await chromium.launch({
    executablePath: browserPath,
    headless: true,
    args: ["--no-sandbox", "--disable-dev-shm-usage"],
  });
  browserVersion = browser.version();
  for (const [id, behaviors, action] of specifications) {
    const context = await browser.newContext({ acceptDownloads: true });
    const page = await context.newPage();
    const consoleErrors = [];
    page.on("console", (message) => {
      if (message.type() === "error") consoleErrors.push(message.text());
    });
    page.on("pageerror", (error) =>
      consoleErrors.push(error.stack || error.message),
    );
    let assertions = 0;
    const check = {
      ok(value, message) {
        assertions += 1;
        assert.ok(value, message);
      },
      equal(actual, expected, message) {
        assertions += 1;
        assert.equal(actual, expected, message);
      },
    };
    const started = performance.now();
    try {
      await page.goto(baseURL, { waitUntil: "networkidle" });
      await idle(page);
      await action({ page, check });
      check.equal(
        consoleErrors.length,
        0,
        `console errors: ${consoleErrors.join("\n")}`,
      );
      results.push({
        id,
        status: "passed",
        behaviors,
        assertions,
        duration_ms: Math.round(performance.now() - started),
        console_errors: [],
      });
    } catch (error) {
      results.push({
        id,
        status: "failed",
        behaviors,
        assertions,
        duration_ms: Math.round(performance.now() - started),
        error: error.stack || error.message,
        console_errors: consoleErrors,
      });
      throw error;
    } finally {
      await context.close();
    }
  }
  successful = true;
} catch (error) {
  error.message += `\nServer output:\n${serverOutput}\nDiagnostics: ${temporary}`;
  throw error;
} finally {
  if (browser) await browser.close();
  server.kill("SIGTERM");
  const passed = results.filter((item) => item.status === "passed").length;
  const report = {
    schema_version: "1.0",
    browser: browserVersion,
    scenarios: results,
    behavior_map: Object.fromEntries(
      results.flatMap((item) =>
        item.behaviors.map((behavior) => [behavior, item.id]),
      ),
    ),
    counts: {
      e2e_scenarios: results.length,
      passed,
      failed: results.length - passed,
      skipped: 0,
      assertions: results.reduce((sum, item) => sum + item.assertions, 0),
    },
    temporary,
  };
  await writeFile(reportPath, `${JSON.stringify(report, null, 2)}\n`, "utf8");
  console.log(`NNDV_E2E_RESULT=${JSON.stringify(report)}`);
  if (successful && ownedTemporary && process.env.NNDV_KEEP_DIAGNOSTICS !== "1")
    await rm(temporary, { recursive: true, force: true });
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
  const deadline = Date.now() + 20_000;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(url);
      await response.arrayBuffer();
      if (response.ok) return;
    } catch {
      /* not bound yet */
    }
    await new Promise((resolveWait) => setTimeout(resolveWait, 100));
  }
  throw new Error(`local server did not start at ${url}`);
}
async function idle(page) {
  await page.waitForFunction(() => {
    const status = document.querySelector("#status")?.textContent || "";
    return !status.includes("正在") && document.querySelector("#canvas svg");
  });
  await page.waitForTimeout(80);
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
async function clearSelection(page) {
  await page.locator("#canvas svg").dispatchEvent("click", { bubbles: true });
}
async function selectNodes(page, indexes) {
  await clearSelection(page);
  for (let index = 0; index < indexes.length; index += 1)
    await page
      .locator("#canvas .node")
      .nth(indexes[index])
      .dispatchEvent("click", { bubbles: true, ctrlKey: index > 0 });
}
async function canvasAction(page, name) {
  await page
    .locator(`#canvas-toolbar [data-action="${name}"]`)
    .dispatchEvent("click", { bubbles: true });
}
async function coordinates(locator) {
  const transform = await locator.getAttribute("transform");
  const match = /translate\(([-+\d.e]+)[ ,]([-+\d.e]+)\)/.exec(transform || "");
  assert.ok(match, `missing node translation: ${transform}`);
  return { x: Number(match[1]), y: Number(match[2]) };
}
async function nodeCoordinates(page, indexes) {
  return Promise.all(
    indexes.map((index) =>
      coordinates(page.locator("#canvas .node").nth(index)),
    ),
  );
}
async function submitTextEntry(page, responses, action) {
  await action();
  const dialog = page.locator("#text-entry-dialog");
  await dialog.waitFor({ state: "visible" });
  const fields = dialog.locator("[data-entry-field]");
  assert.equal(
    await fields.count(),
    responses.length,
    "application text-entry field count changed",
  );
  for (let index = 0; index < responses.length; index += 1)
    await fields.nth(index).fill(responses[index] ?? "");
  await dialog.locator("#text-entry-confirm").click();
  await dialog.waitFor({ state: "hidden" });
}
async function saveDownload(page, format, directory) {
  await page.locator("#export-button").click();
  const downloadPromise = page.waitForEvent("download");
  await page.locator(`#export-menu [data-format="${format}"]`).click();
  const download = await downloadPromise;
  const destination = join(
    directory,
    `${Date.now()}-${format}-${download.suggestedFilename()}`,
  );
  await download.saveAs(destination);
  await idle(page);
  return destination;
}
