import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import {
  mkdir,
  mkdtemp,
  readFile,
  rm,
  stat,
  writeFile,
} from "node:fs/promises";
import net from "node:net";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

const projectRoot = resolve(import.meta.dirname, "../..");
const playwrightModule =
  process.env.NNDV_PLAYWRIGHT_MODULE || "playwright-core";
const { chromium } = await import(playwrightModule);
const python = process.env.NNDV_PYTHON || "python";
const browserPath = process.env.NNDV_BROWSER || "/usr/bin/google-chrome";
const ownedTemporary = !process.env.NNDV_FIGURE_E2E_DIR;
const temporary =
  process.env.NNDV_FIGURE_E2E_DIR ||
  (await mkdtemp(join(tmpdir(), "nndv-figure-studio-e2e-")));
await mkdir(temporary, { recursive: true });
const reportPath =
  process.env.NNDV_FIGURE_E2E_REPORT ||
  join(temporary, "figure-studio-e2e.json");
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

let browser;
let browserVersion = "not-started";
let successful = false;
const errors = [];
const expectedNegativeControlErrors = [];
let expectingTamperedProjectRejection = false;
const assertions = [];
const interactionSamples = [];
const testedViewports = [];
const requiredWorkflows = {
  real_model_semantic_mixed_figure: false,
  structure_lens_explicit_panel: false,
  tensor_shape_style_edit: false,
  long_label_final_svg_bbox: false,
  second_page: false,
  six_panels: false,
  rebuild_undo_restores_evidence: false,
  save_refresh_restore: false,
  tampered_project_rejected: false,
  svg_metadata_roundtrip: false,
  seven_format_exports: false,
  submission_package: false,
  responsive_1440_800_390: false,
  zero_browser_errors: false,
};
const workflowMeasurements = {
  model: null,
  semantic: null,
  mixed_figure: null,
  long_label_svg: null,
  exports: {},
};
const record = (condition, message) => {
  assert.ok(condition, message);
  assertions.push(message);
};

try {
  await waitForServer(`${baseURL}/api/state`);
  browser = await chromium.launch({
    executablePath: browserPath,
    headless: true,
    args: ["--no-sandbox", "--disable-dev-shm-usage"],
  });
  browserVersion = browser.version();
  const context = await browser.newContext({
    acceptDownloads: true,
    viewport: { width: 1440, height: 900 },
  });
  const page = await context.newPage();
  page.on("console", (message) => {
    if (message.type() !== "error") return;
    const text = message.text();
    if (
      expectingTamperedProjectRejection &&
      /Failed to load resource:.*400 \(BAD REQUEST\)/.test(text)
    )
      expectedNegativeControlErrors.push(text);
    else errors.push(text);
  });
  page.on("pageerror", (error) => errors.push(error.stack || error.message));
  page.on("requestfailed", (request) =>
    errors.push(
      `${request.method()} ${request.url()}: ${request.failure()?.errorText}`,
    ),
  );

  await page.goto(baseURL, { waitUntil: "networkidle" });
  await idle(page);
  await page.evaluate(() => window.localStorage.clear());
  await page.reload({ waitUntil: "networkidle" });
  await idle(page);

  // Open an executable, deterministic local model through the product UI.
  await page.locator("#start-button").click();
  await page.locator("#start-center[open]").waitFor();
  await page.locator("#real-model-list [data-real-model]").first().waitFor();
  record(
    (await page.locator("#real-model-list [data-real-model]").count()) === 7,
    "Start Center exposes all seven offline real-model fixtures",
  );
  const modelResponsePromise = page.waitForResponse(
    (response) =>
      response.url().endsWith("/api/real-models/resnet50") &&
      response.request().method() === "POST",
  );
  await page.locator('[data-real-model="resnet50"]').click();
  const modelResponse = await modelResponsePromise;
  const modelBody = await modelResponse.json();
  await idle(page);
  record(
    modelResponse.ok() &&
      modelBody.graph?.metadata?.corpus_key === "resnet50" &&
      modelBody.graph?.metadata?.weights?.includes("no downloaded weights"),
    "real torchvision ResNet50 import is served by the local real-model endpoint",
  );
  record(
    modelBody.graph.nodes.length > 0 &&
      modelBody.graph.edges.length > 0 &&
      modelBody.graph.nodes.some(
        (node) => (node.inputs || []).length || (node.outputs || []).length,
      ),
    "real-model Graph IR carries executable nodes, edges, and tensor ports",
  );
  workflowMeasurements.model = {
    key: "resnet50",
    graph_id: modelBody.graph_id,
    nodes: modelBody.graph.nodes.length,
    edges: modelBody.graph.edges.length,
  };

  // Explicitly request a Semantic View and retain the observed server response.
  const semanticResponsePromise = page.waitForResponse(
    (response) =>
      response.url().endsWith("/api/semantic") &&
      response.request().method() === "POST",
  );
  await selectToolbarOption(page, "#semantic-level", "block");
  const semanticResponse = await semanticResponsePromise;
  const semanticBody = await semanticResponse.json();
  await idle(page);
  const semanticRequest = semanticResponse.request().postDataJSON();
  record(
    semanticResponse.ok() &&
      semanticRequest.level === "block" &&
      semanticRequest.view === "paper" &&
      semanticBody.level === "block" &&
      semanticBody.view === "paper",
    "Semantic View is materialized as block/paper through /api/semantic",
  );
  record(
    semanticBody.graph.nodes.length > 0 &&
      semanticBody.semantic?.source_to_semantic?.block,
    "Semantic View returns evidence-backed source-to-semantic mappings",
  );
  record(
    (await page.locator("#semantic-level").inputValue()) === "block",
    "the visible model canvas is in Block Semantic View",
  );
  workflowMeasurements.semantic = {
    level: semanticBody.level,
    view: semanticBody.view,
    nodes: semanticBody.graph.nodes.length,
  };

  // Enter Figure Studio from that graph. This must exercise the mixed Figure
  // endpoint, not a bundled template shortcut.
  const mixedResponsePromise = page.waitForResponse(
    (response) =>
      response.url().endsWith("/api/figure/from-graph") &&
      response.request().method() === "POST",
  );
  await clickToolbarControl(page, "#figure-studio-button");
  const mixedResponse = await mixedResponsePromise;
  const mixedBody = await mixedResponse.json();
  const mixedRequest = mixedResponse.request().postDataJSON();
  await idle(page);
  const mixedPanels = mixedBody.figure.pages.flatMap((item) => item.panels);
  const mixedObjects = figureObjects(mixedBody.figure);
  record(
    await page.locator("body.figure-studio-active").isVisible(),
    "Figure Studio opens as a distinct workspace",
  );
  record(
    mixedResponse.ok() &&
      mixedRequest.mode === "mixed" &&
      mixedRequest.graph_id === modelBody.graph_id &&
      mixedRequest.level === "block" &&
      mixedRequest.view === "paper" &&
      mixedBody.figure.metadata?.semantic_view?.selected_level === "block" &&
      mixedBody.figure.metadata?.semantic_view?.view === "paper",
    "real Graph IR is converted using the author-selected Block/Paper Semantic View",
  );
  record(
    mixedPanels.some((panel) => panel.mode === "mixed") &&
      mixedObjects.some(
        (object) => (object.provenance?.graph_ir_ids || []).length > 0,
      ),
    "automatic mixed Figure contains editable objects with Graph IR provenance",
  );
  const mixedSemanticIds = new Set(
    (mixedBody.semantic_view?.entities || []).map((item) => item.id),
  );
  const mixedFigureSemanticIds = mixedObjects
    .filter((item) => item.provenance?.kind === "semantic_view")
    .map((item) => item.provenance.source_id);
  record(
    mixedBody.provenance_validation?.passed === true &&
      mixedFigureSemanticIds.length > 0 &&
      mixedFigureSemanticIds.every((id) => mixedSemanticIds.has(id)),
    "automatic mixed Figure references only entities in its returned Semantic View",
  );
  record(
    (await page.locator("#canvas polygon[data-tensor-face]").count()) > 0,
    "automatic mixed Figure renders genuine tensor geometry",
  );
  record(
    (await page
      .locator("#studio-template-list .studio-template-card")
      .count()) === 7,
    "seven bundled offline templates remain available beside model-to-figure",
  );
  workflowMeasurements.mixed_figure = {
    pages: mixedBody.figure.pages.length,
    panels: mixedPanels.length,
    objects: mixedObjects.length,
    mode: mixedRequest.mode,
  };
  requiredWorkflows.real_model_semantic_mixed_figure = true;

  // Add an explicit author display-shape override without rewriting the
  // auto-generated tensor's authoritative model evidence, then edit style.
  const layersTab = page.locator('[data-studio-left-tab="layers"]');
  const layersHitGeometry = await layersTab.evaluate((element) => {
    const bounds = element.getBoundingClientRect();
    const hit = document.elementFromPoint(
      bounds.left + bounds.width / 2,
      bounds.top + bounds.height / 2,
    );
    const resizer = document
      .querySelector(".sidebar-resizer-left")
      ?.getBoundingClientRect();
    return {
      passed: hit === element || element.contains(hit),
      tab: {
        left: bounds.left,
        right: bounds.right,
        top: bounds.top,
        bottom: bounds.bottom,
      },
      resizer: resizer
        ? { left: resizer.left, right: resizer.right, top: resizer.top }
        : null,
      hit: hit?.className || hit?.tagName || null,
    };
  });
  record(
    layersHitGeometry.passed,
    `left sidebar resize handle does not cover the Layers tab hit target (${JSON.stringify(layersHitGeometry)})`,
  );
  await layersTab.click();
  const tensorRow = page
    .locator('.studio-object-row:has(.object-kind:text-is("tensor-glyph"))')
    .first();
  await tensorRow.waitFor();
  const tensorId = await tensorRow.getAttribute("data-object-id");
  const sourceTensor = mixedObjects.find((item) => item.id === tensorId);
  record(
    Boolean(
      tensorId &&
        sourceTensor?.metadata?.tensor_shape &&
        sourceTensor?.provenance?.evidence?.tensor,
    ),
    "automatic tensor glyph and its source tensor evidence are exposed in the object tree",
  );
  await tensorRow.click();
  await page.locator("#studio-prop-shape").fill("1,32,112,112");
  await page.locator("#studio-prop-shape").dispatchEvent("change");
  await idle(page);
  interactionSamples.push(await reportedRenderMs(page));
  record(
    (await page.locator("#canvas").textContent()).includes(
      "[1, 32, 112, 112]",
    ) &&
      (await page
        .locator(
          `#canvas text[data-figure-object-id="${tensorId}"][data-shape-label-origin="author_override"]`,
        )
        .count()) === 1,
    "tensor shape property renders an explicit author override label",
  );
  await page
    .locator(`.studio-object-row[data-object-id="${tensorId}"]`)
    .click();
  await page.locator("#studio-prop-fill").fill("#005ea8");
  await page.locator("#studio-prop-fill").dispatchEvent("change");
  await idle(page);
  interactionSamples.push(await reportedRenderMs(page));
  record(
    (await page
      .locator(
        `#canvas polygon[data-figure-object-id="${tensorId}"][data-tensor-face="front"]`,
      )
      .getAttribute("fill")) === "#005ea8",
    "tensor style property updates the editable front-face vector fill",
  );
  requiredWorkflows.tensor_shape_style_edit = true;

  // Create a long label, export the actual SVG, and measure that final output
  // with browser geometry APIs. No Python proof values are used here.
  const longLabel =
    "Extended evidence annotation explains how the encoder preserves tensor identity across residual attention stages while keeping every source binding available for reproducible review.";
  await submitTextEntry(page, [longLabel], () =>
    clickStudioInsert(page, "annotation"),
  );
  await idle(page);
  const longLabelRow = page
    .locator(".studio-object-row")
    .filter({ hasText: longLabel })
    .first();
  const longLabelId = await longLabelRow.getAttribute("data-object-id");
  record(
    Boolean(longLabelId),
    "long author label is retained as an editable Figure object",
  );
  const singlePageSvgPath = await studioDownload(
    page,
    '[data-studio-export="svg"]',
    temporary,
    "single-page-svg",
  );
  const singlePageSvgText = await readFile(singlePageSvgPath, "utf8");
  const svgProbe = await context.newPage();
  collectBrowserErrors(svgProbe, errors);
  const longLabelMeasurement = await measureFinalSvgText(
    svgProbe,
    singlePageSvgText,
    longLabelId,
  );
  await svgProbe.close();
  workflowMeasurements.long_label_svg = longLabelMeasurement;
  record(
    longLabelMeasurement.line_count >= 2,
    "final SVG auto-wraps the long label into multiple tspans",
  );
  record(
    longLabelMeasurement.bbox.width > 0 && longLabelMeasurement.bbox.height > 0,
    "final SVG long label has a non-empty Chrome getBBox measurement",
  );
  record(
    longLabelMeasurement.within_panel,
    "Chrome getBBox and CTM place the full long label inside its panel",
  );
  record(
    longLabelMeasurement.within_svg_client_rect,
    "Chrome getBoundingClientRect confirms the long label is not page-clipped",
  );
  record(
    Math.abs(longLabelMeasurement.ctm_scale_ratio - 1) <= 0.001,
    "final SVG text CTM preserves 1:1 horizontal/vertical scale",
  );
  requiredWorkflows.long_label_final_svg_bbox = true;

  record(
    singlePageSvgText.includes('id="nndv-figure-ir"') &&
      singlePageSvgText.includes('data-nndv-version="0.7.3"') &&
      singlePageSvgText.includes('data-geometry-unit="mm"') &&
      singlePageSvgText.includes('data-style-unit="pt"'),
    "final SVG embeds versioned Figure IR plus explicit mm/pt unit metadata",
  );
  await page.locator("#studio-svg-input").setInputFiles(singlePageSvgPath);
  await idle(page);
  const roundtripProjectPath = await studioDownload(
    page,
    '[data-studio-action="save-project"]',
    temporary,
    "roundtrip-project",
  );
  const roundtrip = JSON.parse(await readFile(roundtripProjectPath, "utf8"));
  const roundtripObjects = figureObjects(roundtrip.figure_ir);
  const roundtripTensor = roundtripObjects.find((item) => item.id === tensorId);
  record(
    roundtrip.figure_ir.pages.length === mixedBody.figure.pages.length &&
      roundtripObjects.some(
        (item) => item.id === longLabelId && item.metadata.text === longLabel,
      ),
    "native SVG metadata round-trip restores the page and exact long-label object",
  );
  record(
    roundtripTensor?.metadata?.author_shape_override_label ===
      "[1, 32, 112, 112]" &&
      roundtripTensor?.metadata?.shape_label_origin === "author_override" &&
      roundtripTensor?.metadata?.shape_label ===
        sourceTensor?.metadata?.shape_label &&
      JSON.stringify(roundtripTensor?.metadata?.tensor_shape) ===
        JSON.stringify(sourceTensor?.metadata?.tensor_shape) &&
      JSON.stringify(roundtripTensor?.provenance?.evidence?.tensor) ===
        JSON.stringify(sourceTensor?.provenance?.evidence?.tensor) &&
      roundtripTensor?.style?.overrides?.front_fill === "#005ea8",
    "native SVG metadata round-trip restores the author shape override and style without changing source evidence",
  );
  requiredWorkflows.svg_metadata_roundtrip = true;

  // Structure Lens may preview and highlight, but it may mutate the Figure
  // only after the explicit Add control is clicked.
  const pagesBeforeLens = await page
    .locator("#studio-page-select option")
    .count();
  const panelsBeforeLens = await page.locator("#canvas .figure-panel").count();
  await studioAction(page, "structure-lens");
  await page.locator("#structure-lens-dialog[open]").waitFor();
  const terminalRealEdge = modelBody.graph.edges.at(-1);
  await page.locator("#lens-source").selectOption(terminalRealEdge.source);
  await page.locator("#lens-target").selectOption(terminalRealEdge.target);
  const lensResponsePromise = page.waitForResponse(
    (response) =>
      response.url().endsWith("/api/structure-lens/downstream") &&
      response.request().method() === "POST",
  );
  await page.locator('[data-lens-operation="downstream"]').click();
  const lensResponse = await lensResponsePromise;
  const lensBody = await lensResponse.json();
  await page.locator("#structure-lens-results .lens-result-card").waitFor();
  record(
    lensResponse.ok() &&
      lensBody.operation === "downstream-trace" &&
      lensBody.metadata?.enumerated_all_simple_paths === false &&
      lensBody.metadata?.maximum_visits === 10_000 &&
      (await page.locator("#structure-lens-results").textContent()).includes(
        "bounded",
      ),
    "Structure Lens returns a bounded downstream result from real Graph IR",
  );
  record(
    lensBody.figure_panel_preview?.available === true &&
      figureObjects({
        pages: [{ panels: [lensBody.figure_panel_preview.panel] }],
      }).some((item) => (item.provenance?.graph_ir_ids || []).length > 0),
    "Structure Lens result includes an evidence-backed provenance Panel preview",
  );
  record(
    (await page.locator("#studio-page-select option").count()) ===
      pagesBeforeLens,
    "Structure Lens query alone does not create a Figure Page",
  );
  record(
    (await page.locator("#canvas .figure-panel").count()) === panelsBeforeLens,
    "Structure Lens preview alone does not create a Figure Panel",
  );
  const lensAddRenderPromise = page.waitForResponse(
    (response) =>
      response.url().endsWith("/api/figure/render") &&
      response.request().method() === "POST",
  );
  await page.locator("#lens-add-panel").click();
  await requireSuccessfulJsonResponse(
    await lensAddRenderPromise,
    "explicit Structure Lens Page render",
  );
  await idle(page);
  const pagesAfterLens = await page
    .locator("#studio-page-select option")
    .count();
  const panelsAfterLens = await page.locator("#canvas .figure-panel").count();
  record(
    pagesAfterLens === pagesBeforeLens + 1,
    "explicit Structure Lens Add creates exactly one new provenance Page",
  );
  record(
    panelsAfterLens === panelsBeforeLens + 1,
    "explicit Structure Lens Add creates exactly one new provenance Panel",
  );
  record(
    (await page.locator("#studio-page-select").inputValue()).startsWith(
      "lens_page",
    ),
    "new Structure Lens Page becomes the active editable page",
  );
  requiredWorkflows.structure_lens_explicit_panel = true;
  requiredWorkflows.second_page = true;
  await page.locator('#structure-lens-dialog button[value="cancel"]').click();

  for (
    let attempt = 0;
    (await page.locator("#canvas .figure-panel").count()) < 6 && attempt < 8;
    attempt += 1
  ) {
    const panelRenderPromise = page.waitForResponse(
      (response) =>
        response.url().endsWith("/api/figure/render") &&
        response.request().method() === "POST",
    );
    await studioPageAction(page, "add");
    await requireSuccessfulJsonResponse(
      await panelRenderPromise,
      "six-Panel multi-page Figure render",
    );
    await idle(page);
    interactionSamples.push(await reportedRenderMs(page));
  }
  const finalPanelCount = await page.locator("#canvas .figure-panel").count();
  const finalPageCount = await page
    .locator("#studio-page-select option")
    .count();
  record(
    finalPanelCount >= 6,
    `Figure Studio supports at least six editable Panels (observed ${finalPanelCount})`,
  );
  record(
    finalPageCount >= 2,
    "Figure Studio preserves a real second Page while adding Panels",
  );
  requiredWorkflows.six_panels = true;

  const rebuildResponsePromise = page.waitForResponse(
    (response) =>
      response.url().endsWith("/api/figure/from-graph") &&
      response.request().method() === "POST",
  );
  await studioAction(page, "new-from-graph");
  const rebuildResponse = await rebuildResponsePromise;
  const rebuildBody = await rebuildResponse.json();
  const rebuildRequest = rebuildResponse.request().postDataJSON();
  await idle(page);
  record(
    rebuildResponse.ok() &&
      rebuildRequest.existing_figure?.pages?.length === finalPageCount &&
      rebuildRequest.level === "block" &&
      rebuildRequest.view === "paper" &&
      rebuildBody.provenance_validation?.passed === true,
    "Figure rebuild forwards the prior Figure and selected Semantic View for reconciliation",
  );
  const undoRenderPromise = page.waitForResponse(
    (response) =>
      response.url().endsWith("/api/figure/render") &&
      response.request().method() === "POST",
  );
  await page.locator("#studio-document-title").click();
  await page.keyboard.press("Control+z");
  await requireSuccessfulJsonResponse(
    await undoRenderPromise,
    "Figure rebuild undo render",
  );
  await idle(page);
  record(
    (await page.locator("#studio-page-select option").count()) ===
      finalPageCount &&
      (await page.locator("#canvas .figure-panel").count()) ===
        finalPanelCount &&
      (await page.locator("#canvas").textContent()).includes(
        "[1, 32, 112, 112]",
      ),
    "Undo after rebuild restores the complete prior Figure and author tensor override",
  );
  requiredWorkflows.rebuild_undo_restores_evidence = true;

  const savedProjectPath = await studioDownload(
    page,
    '[data-studio-action="save-project"]',
    temporary,
    "project",
  );
  const saved = JSON.parse(await readFile(savedProjectPath, "utf8"));
  const savedObjects = figureObjects(saved.figure_ir);
  const savedTensor = savedObjects.find((item) => item.id === tensorId);
  const savedLensPage = saved.figure_ir.pages.find((item) =>
    item.title.startsWith("Structure Lens"),
  );
  record(saved.project_version === "1.4", "saved project uses schema 1.4");
  const savedSemanticIds = new Set(
    (saved.semantic_view?.document?.entities || []).map((item) => item.id),
  );
  record(
    savedSemanticIds.size > 0 &&
      savedObjects
        .filter((item) => item.provenance?.kind === "semantic_view")
        .every((item) => savedSemanticIds.has(item.provenance.source_id)),
    "saved project persists the exact Semantic View used by its model-derived Figure",
  );
  record(
    saved.figure_ir.pages.length === finalPageCount,
    "saved project retains every Figure Page",
  );
  record(
    saved.figure_ir.pages.flatMap((item) => item.panels).length ===
      finalPanelCount,
    "saved project retains all six-or-more Panels",
  );
  record(
    savedLensPage?.panels.some((panel) =>
      figureObjects({ pages: [{ panels: [panel] }] }).some(
        (item) => (item.provenance?.graph_ir_ids || []).length > 0,
      ),
    ),
    "saved Structure Lens Page retains Graph IR provenance",
  );
  record(
    savedTensor?.metadata?.author_shape_override_label ===
      "[1, 32, 112, 112]" &&
      savedTensor?.metadata?.shape_label_origin === "author_override" &&
      JSON.stringify(savedTensor?.metadata?.tensor_shape) ===
        JSON.stringify(sourceTensor?.metadata?.tensor_shape) &&
      JSON.stringify(savedTensor?.provenance?.evidence?.tensor) ===
        JSON.stringify(sourceTensor?.provenance?.evidence?.tensor) &&
      savedTensor?.style?.overrides?.front_fill === "#005ea8",
    "saved project retains the author shape override and style without changing model evidence",
  );
  record(
    savedObjects.some(
      (item) => item.id === longLabelId && item.metadata?.text === longLabel,
    ),
    "saved project retains the exact wrapped long-label source text",
  );
  await page.waitForFunction(
    ({ pageCount, panelCount }) => {
      const draft = JSON.parse(
        window.localStorage.getItem("nndv-autosaved-project") || "null",
      );
      return (
        draft?.figure_ir?.pages?.length === pageCount &&
        draft?.semantic_view?.document?.entities?.length > 0 &&
        draft.figure_ir.pages.flatMap((item) => item.panels || []).length ===
          panelCount
      );
    },
    { pageCount: finalPageCount, panelCount: finalPanelCount },
    { timeout: 10_000 },
  );
  await page.reload({ waitUntil: "networkidle" });
  await idle(page);
  record(
    (await page.locator("body.figure-studio-active").count()) === 1,
    "refresh recovers directly into the Figure Studio workspace",
  );
  record(
    (await page.locator("#studio-page-select option").count()) ===
      finalPageCount &&
      (await page.locator("#canvas .figure-panel").count()) === finalPanelCount,
    "save, refresh, and local recovery restore all Pages and Panels",
  );
  record(
    (await page.locator("#canvas").textContent()).includes("[1, 32, 112, 112]"),
    "refresh recovery retains the author tensor shape override label",
  );
  requiredWorkflows.save_refresh_restore = true;

  // Download and validate all seven actual browser exports from the multi-page
  // document. Page-split formats are ZIPs by policy; PDF/HTML are page-aware.
  for (const format of ["svg", "pdf", "tikz", "pptx", "png", "eps", "html"]) {
    const exportedPath = await studioDownload(
      page,
      `[data-studio-export="${format}"]`,
      temporary,
      `seven-format-${format}`,
    );
    const bytes = await readFile(exportedPath);
    const signature = exportSignature(format, bytes);
    workflowMeasurements.exports[format] = {
      bytes: bytes.length,
      signature,
    };
    record(
      bytes.length > 100,
      `${format.toUpperCase()} browser download is non-empty`,
    );
    record(
      signature !== null,
      `${format.toUpperCase()} browser download has the expected native/ZIP signature`,
    );
  }
  requiredWorkflows.seven_format_exports =
    Object.keys(workflowMeasurements.exports).length === 7;

  const submission = await studioDownload(
    page,
    '[data-studio-action="submission-package"]',
    temporary,
    "submission-package",
  );
  const submissionBytes = await readFile(submission);
  record(
    (await stat(submission)).size > 10_000,
    "submission package is generated as a non-empty seven-format archive",
  );
  record(
    submissionBytes.subarray(0, 2).toString("ascii") === "PK",
    "submission package download is a real ZIP archive",
  );
  requiredWorkflows.submission_package = true;

  for (const viewport of [
    { width: 1440, height: 900 },
    { width: 800, height: 720 },
    { width: 390, height: 780 },
  ]) {
    await page.setViewportSize(viewport);
    await page.waitForTimeout(80);
    const geometry = await page.evaluate(() => {
      const toolbar = document
        .querySelector("#figure-studio-toolbar")
        .getBoundingClientRect();
      return {
        viewport: window.innerWidth,
        documentWidth: document.documentElement.scrollWidth,
        bodyWidth: document.body.scrollWidth,
        toolbarLeft: toolbar.left,
        toolbarRight: toolbar.right,
        drawerButtons: [
          ...document.querySelectorAll(".studio-drawer-button"),
        ].filter((button) => button.getClientRects().length).length,
      };
    });
    record(
      geometry.documentWidth <= geometry.viewport &&
        geometry.bodyWidth <= geometry.viewport,
      `${viewport.width}px Figure Studio has no horizontal page overflow`,
    );
    record(
      geometry.toolbarLeft >= 0 && geometry.toolbarRight <= viewport.width,
      `${viewport.width}px Figure Studio toolbar remains bounded`,
    );
    if (viewport.width <= 800) {
      record(
        geometry.drawerButtons === 2,
        `${viewport.width}px reuses the canonical left/right drawer controls`,
      );
      await page
        .locator(
          '#figure-studio-toolbar .studio-drawer-button[data-open-responsive-drawer="workspace-panel"]',
        )
        .click();
      record(
        (await page.locator("#workspace-panel.drawer-open").count()) === 1,
        `${viewport.width}px opens the canonical Figure layer drawer`,
      );
      await page.keyboard.press("Escape");
    }
    testedViewports.push(viewport.width);
  }
  requiredWorkflows.responsive_1440_800_390 =
    testedViewports.join(",") === "1440,800,390";

  // Persisted ingestion must reject before browser hydration or provenance
  // reindexing. Keep the rejected draft intact instead of silently replacing
  // it with the initial graph during startup.
  const tamperedProject = structuredClone(saved),
    tamperedSemanticObject = savedObjects.find(
      (item) => item.provenance?.kind === "semantic_view",
    );
  tamperedProject.figure_ir.metadata.provenance_index.figure_to_source[
    tamperedSemanticObject.id
  ].semantic_id = "orphan-semantic-entity";
  await page.evaluate((draft) => {
    window.localStorage.setItem(
      "nndv-autosaved-project",
      JSON.stringify(draft),
    );
  }, tamperedProject);
  const rejectedValidationPromise = page.waitForResponse(
    (response) =>
      response.url().endsWith("/api/project") &&
      response.request().method() === "POST",
  );
  expectingTamperedProjectRejection = true;
  await page.reload({ waitUntil: "networkidle" });
  const rejectedValidation = await rejectedValidationPromise;
  await idle(page);
  await page.waitForTimeout(500);
  expectingTamperedProjectRejection = false;
  const rejectedState = await page.evaluate(() => ({
    figureWorkspace: document.body.classList.contains("figure-studio-active"),
    message: document.querySelector("#toast")?.textContent || "",
    retained: JSON.parse(
      window.localStorage.getItem("nndv-autosaved-project") || "null",
    ),
  }));
  record(
    rejectedValidation.status() === 400 && !rejectedState.figureWorkspace,
    "tampered persisted project is rejected before Figure workspace hydration",
  );
  record(
    rejectedState.message.includes("已拒绝恢复") &&
      rejectedState.retained?.figure_ir?.metadata?.provenance_index
        ?.figure_to_source?.[tamperedSemanticObject.id]?.semantic_id ===
        "orphan-semantic-entity",
    "rejected autosave is reported and retained without silent reindex or overwrite",
  );
  requiredWorkflows.tampered_project_rejected = true;

  const medianInteractionMs = median(interactionSamples);
  record(
    medianInteractionMs <= 100,
    `median Figure Studio interaction is ${medianInteractionMs.toFixed(2)} ms (target <= 100 ms)`,
  );
  record(
    errors.length === 0,
    `unexpected console/page/request errors = ${errors.length}`,
  );
  requiredWorkflows.zero_browser_errors = errors.length === 0;

  await context.close();
  successful = true;
} catch (error) {
  error.message += `\nServer output:\n${serverOutput}\nDiagnostics: ${temporary}`;
  throw error;
} finally {
  if (browser) await browser.close();
  server.kill("SIGTERM");
  const report = {
    schema_version: "nndv-0.6.1-figure-studio-e2e-1",
    status: successful ? "PASS" : "FAIL",
    browser: browserVersion,
    counts: {
      scenarios: 1,
      passed: successful ? 1 : 0,
      failed: successful ? 0 : 1,
      skipped: 0,
      assertions: assertions.length,
      console_page_request_errors: errors.length,
    },
    tested_viewports: testedViewports,
    median_interaction_ms: interactionSamples.length
      ? Math.round(median(interactionSamples) * 100) / 100
      : null,
    interaction_samples_ms: interactionSamples.map(
      (value) => Math.round(value * 100) / 100,
    ),
    behaviors: assertions,
    required_workflows: requiredWorkflows,
    workflow_measurements: workflowMeasurements,
    errors,
    expected_negative_control_errors: expectedNegativeControlErrors,
    temporary,
  };
  await writeFile(reportPath, `${JSON.stringify(report, null, 2)}\n`, "utf8");
  console.log(`NNDV_FIGURE_E2E_RESULT=${JSON.stringify(report)}`);
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
      // Server is still starting.
    }
    await new Promise((resolveWait) => setTimeout(resolveWait, 100));
  }
  throw new Error(`local server did not start at ${url}`);
}

async function idle(page) {
  await page.waitForFunction(() => {
    const shell = document.querySelector("#canvas-shell");
    return (
      shell?.getAttribute("aria-busy") === "false" &&
      document.querySelector("#canvas svg")
    );
  });
  await page.waitForTimeout(90);
}

async function submitTextEntry(page, values, action) {
  await action();
  const dialog = page.locator("#text-entry-dialog");
  await dialog.waitFor({ state: "visible" });
  const fields = dialog.locator("[data-entry-field]");
  assert.equal(await fields.count(), values.length);
  for (let index = 0; index < values.length; index += 1)
    await fields.nth(index).fill(values[index]);
  await dialog.locator("#text-entry-confirm").click();
  await dialog.waitFor({ state: "hidden" });
}

async function studioAction(page, action) {
  await page.evaluate((value) => {
    const button = document.querySelector(`[data-studio-action="${value}"]`);
    if (!button) throw new Error(`missing studio action ${value}`);
    button.click();
  }, action);
}

async function studioPageAction(page, action) {
  await page.evaluate((value) => {
    const button = document.querySelector(
      `[data-studio-page-action="${value}"]`,
    );
    if (!button) throw new Error(`missing studio page action ${value}`);
    button.click();
  }, action);
}

async function clickStudioInsert(page, kind) {
  await page.evaluate((value) => {
    const button = document.querySelector(`[data-studio-insert="${value}"]`);
    if (!button) throw new Error(`missing studio insert ${value}`);
    button.click();
  }, kind);
}

async function clickToolbarControl(page, selector) {
  const locator = await revealToolbarControl(page, selector);
  await locator.click();
}

async function selectToolbarOption(page, selector, value) {
  const locator = await revealToolbarControl(page, selector);
  await locator.selectOption(value);
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

async function studioDownload(page, selector, directory, label) {
  const downloadPromise = page.waitForEvent("download", { timeout: 120_000 });
  await page.evaluate((value) => {
    const button = document.querySelector(value);
    if (!button) throw new Error(`missing download action ${value}`);
    button.click();
  }, selector);
  const download = await downloadPromise;
  const destination = join(
    directory,
    `${Date.now()}-${label}-${download.suggestedFilename()}`,
  );
  await download.saveAs(destination);
  await idle(page);
  return destination;
}

async function requireSuccessfulJsonResponse(response, label) {
  if (response.ok()) return response;
  let detail = response.statusText();
  try {
    const body = await response.json();
    detail = body.hint
      ? `${body.message} — ${body.hint}`
      : body.message || detail;
  } catch {}
  throw new Error(`${label} failed (${response.status()}): ${detail}`);
}

function figureObjects(figure) {
  return (figure?.pages || [])
    .flatMap((pageItem) => pageItem.panels || [])
    .flatMap((panel) => panel.layers || [])
    .flatMap((layer) => layer.objects || []);
}

function collectBrowserErrors(page, target) {
  page.on("console", (message) => {
    if (message.type() === "error") target.push(message.text());
  });
  page.on("pageerror", (error) => target.push(error.stack || error.message));
  page.on("requestfailed", (request) =>
    target.push(
      `${request.method()} ${request.url()}: ${request.failure()?.errorText}`,
    ),
  );
}

async function measureFinalSvgText(page, svgText, objectId) {
  const probeUrl = `${baseURL}/__e2e_final_svg_${Date.now()}.svg`;
  await page.route(probeUrl, (route) =>
    route.fulfill({
      status: 200,
      contentType: "image/svg+xml; charset=utf-8",
      body: svgText,
    }),
  );
  await page.goto(probeUrl, {
    waitUntil: "load",
  });
  await page.evaluate(() => document.fonts?.ready);
  return page.evaluate((id) => {
    const text = [
      ...document.querySelectorAll("text[data-figure-object-id]"),
    ].find((element) => element.dataset.figureObjectId === id);
    if (!text) throw new Error(`final SVG is missing text object ${id}`);
    const panel = text.closest(".figure-panel");
    const panelBoundary = panel?.querySelector(".panel-boundary");
    const svg = document.documentElement;
    if (!panelBoundary || svg.localName !== "svg")
      throw new Error("final SVG measurement targets are incomplete");

    const transformedBounds = (element) => {
      const box = element.getBBox();
      const matrix = element.getCTM();
      if (!matrix) throw new Error("final SVG element has no CTM");
      const points = [
        new window.DOMPoint(box.x, box.y),
        new window.DOMPoint(box.x + box.width, box.y),
        new window.DOMPoint(box.x + box.width, box.y + box.height),
        new window.DOMPoint(box.x, box.y + box.height),
      ].map((point) => point.matrixTransform(matrix));
      const xs = points.map((point) => point.x);
      const ys = points.map((point) => point.y);
      return {
        x: Math.min(...xs),
        y: Math.min(...ys),
        width: Math.max(...xs) - Math.min(...xs),
        height: Math.max(...ys) - Math.min(...ys),
      };
    };

    const bbox = text.getBBox();
    const textBounds = transformedBounds(text);
    const panelBounds = transformedBounds(panelBoundary);
    const textClient = text.getBoundingClientRect();
    const svgClient = svg.getBoundingClientRect();
    const ctm = text.getCTM();
    const scaleX = Math.hypot(ctm.a, ctm.b);
    const scaleY = Math.hypot(ctm.c, ctm.d);
    const tolerance = 0.25;
    return {
      line_count: text.querySelectorAll("tspan").length,
      bbox: { x: bbox.x, y: bbox.y, width: bbox.width, height: bbox.height },
      transformed_bbox: textBounds,
      panel_bbox: panelBounds,
      client_rect: {
        left: textClient.left,
        top: textClient.top,
        right: textClient.right,
        bottom: textClient.bottom,
      },
      svg_client_rect: {
        left: svgClient.left,
        top: svgClient.top,
        right: svgClient.right,
        bottom: svgClient.bottom,
      },
      ctm: {
        a: ctm.a,
        b: ctm.b,
        c: ctm.c,
        d: ctm.d,
        e: ctm.e,
        f: ctm.f,
      },
      ctm_scale_ratio: scaleY ? scaleX / scaleY : Number.POSITIVE_INFINITY,
      within_panel:
        textBounds.x >= panelBounds.x - tolerance &&
        textBounds.y >= panelBounds.y - tolerance &&
        textBounds.x + textBounds.width <=
          panelBounds.x + panelBounds.width + tolerance &&
        textBounds.y + textBounds.height <=
          panelBounds.y + panelBounds.height + tolerance,
      within_svg_client_rect:
        textClient.left >= svgClient.left - 0.5 &&
        textClient.top >= svgClient.top - 0.5 &&
        textClient.right <= svgClient.right + 0.5 &&
        textClient.bottom <= svgClient.bottom + 0.5,
      clip_path: window.getComputedStyle(text).clipPath,
    };
  }, objectId);
}

function exportSignature(format, bytes) {
  const zip = bytes.subarray(0, 2).toString("ascii") === "PK";
  const prefix = bytes.subarray(0, 256).toString("utf8");
  if (format === "svg")
    return zip ? "zip" : prefix.includes("<svg") ? "svg" : null;
  if (format === "pdf") return prefix.startsWith("%PDF-") ? "pdf" : null;
  if (format === "tikz")
    return zip
      ? "zip"
      : prefix.includes("\\begin{tikzpicture}")
        ? "tikz"
        : null;
  if (format === "pptx") return zip ? "pptx-zip" : null;
  if (format === "png")
    return zip || bytes.subarray(0, 8).toString("hex") === "89504e470d0a1a0a"
      ? zip
        ? "zip"
        : "png"
      : null;
  if (format === "eps")
    return zip ? "zip" : prefix.startsWith("%!PS") ? "eps" : null;
  if (format === "html")
    return prefix.toLowerCase().includes("<!doctype html") ? "html" : null;
  return null;
}

async function reportedRenderMs(page) {
  return page.locator("#status").evaluate((status) => {
    const match = /\u6700\u8fd1\u6e32\u67d3\s+([0-9.]+)\s+ms/.exec(
      status.textContent || "",
    );
    if (!match)
      throw new Error(
        `missing Figure Studio render timing: ${status.textContent}`,
      );
    return Number(match[1]);
  });
}

function median(values) {
  const sorted = values.slice().sort((first, second) => first - second);
  if (!sorted.length) return Number.POSITIVE_INFINITY;
  const middle = Math.floor(sorted.length / 2);
  return sorted.length % 2
    ? sorted[middle]
    : (sorted[middle - 1] + sorted[middle]) / 2;
}
