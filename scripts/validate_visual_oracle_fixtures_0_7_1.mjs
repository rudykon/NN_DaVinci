#!/usr/bin/env node
import crypto from "node:crypto";
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import process from "node:process";
import { pathToFileURL } from "node:url";
import { chromium } from "playwright-core";

const root = path.resolve(import.meta.dirname, ".."),
  fixtureRoot = path.join(root, "tests", "fixtures", "scene_oracle_071"),
  outputIndex = process.argv.indexOf("--output"),
  output =
    outputIndex >= 0 ? path.resolve(process.argv[outputIndex + 1]) : null,
  temporary = fs.mkdtempSync(
    path.join(os.tmpdir(), "nndv-071-oracle-fixtures-"),
  ),
  positive = path.join(fixtureRoot, "scene.svg"),
  source = fs.readFileSync(positive, "utf8"),
  mutationDocument = JSON.parse(
    fs.readFileSync(path.join(fixtureRoot, "mutations.json"), "utf8"),
  ),
  mutationFiles = [];

for (const mutation of mutationDocument.mutations) {
  if (!source.includes(mutation.find))
    throw new Error(`mutation anchor was not found: ${mutation.name}`);
  const directory = path.join(temporary, mutation.name);
  fs.mkdirSync(directory, { recursive: true });
  const file = path.join(directory, "scene.svg");
  fs.writeFileSync(file, source.replace(mutation.find, mutation.replace));
  mutationFiles.push({ ...mutation, file });
}

const svgReportPath = path.join(temporary, "svg-report.json"),
  oracle = spawnSync(
    process.execPath,
    [
      path.join(root, "scripts", "scene_svg_oracle_0_7_1.mjs"),
      "--allow-failures",
      "--output",
      svgReportPath,
      positive,
      ...mutationFiles.map((item) => item.file),
    ],
    { cwd: root, encoding: "utf8" },
  );
if (oracle.error) throw oracle.error;
if (oracle.status !== 0)
  throw new Error(
    `SVG fixture oracle exited ${oracle.status}: ${oracle.stderr}`,
  );
const svgReport = JSON.parse(fs.readFileSync(svgReportPath, "utf8")),
  byFile = new Map(svgReport.cases.map((item) => [item.file, item])),
  positiveResult = byFile.get(path.resolve(positive)),
  fixtureResults = [];
if (positiveResult?.status !== "PASS")
  fixtureResults.push({
    name: "positive",
    status: "FAIL",
    reason: `positive fixture did not pass: ${positiveResult?.failures || "missing"}`,
  });
else fixtureResults.push({ name: "positive", status: "PASS" });
for (const mutation of mutationFiles) {
  const result = byFile.get(path.resolve(mutation.file)),
    detected =
      result?.status === "FAIL" &&
      result.failures.some((failure) =>
        failure.includes(mutation.expected_failure),
      );
  fixtureResults.push({
    name: mutation.name,
    status: detected ? "PASS" : "FAIL",
    expectedFailure: mutation.expected_failure,
    observedStatus: result?.status || "MISSING",
    observedFailures: result?.failures || [],
  });
}

const browser = await chromium.launch({
    executablePath: process.env.NNDV_BROWSER || "/usr/bin/google-chrome",
    headless: true,
    args: ["--no-sandbox", "--disable-gpu"],
  }),
  toolbarResults = [];
try {
  for (const [name, filename, expected] of [
    ["toolbar-positive", "toolbar-positive.html", "PASS"],
    ["toolbar-truncated-negative", "toolbar-truncated-negative.html", "FAIL"],
  ]) {
    const viewportResults = [];
    for (const viewport of [
      { width: 390, height: 844 },
      { width: 568, height: 320 },
    ]) {
      const page = await browser.newPage({ viewport });
      await page.goto(pathToFileURL(path.join(fixtureRoot, filename)).href);
      const measurement = await page.evaluate(() => {
        const toolbar = document.querySelector("[data-toolbar]"),
          controls = [...document.querySelectorAll("[data-toolbar-control]")],
          boundary = toolbar.getBoundingClientRect(),
          truncated = controls
            .filter((control) => {
              const box = control.getBoundingClientRect();
              return (
                control.scrollWidth > control.clientWidth + 0.5 ||
                box.left < -0.5 ||
                box.right > innerWidth + 0.5 ||
                box.top < -0.5 ||
                box.bottom > innerHeight + 0.5
              );
            })
            .map((control) => control.textContent.trim());
        return {
          toolbarHeight: boundary.height,
          truncated,
          passed: !truncated.length && boundary.height <= 80,
        };
      });
      viewportResults.push({ viewport, ...measurement });
      await page.close();
    }
    const observed = viewportResults.every((item) => item.passed)
      ? "PASS"
      : "FAIL";
    toolbarResults.push({
      name,
      expected,
      observed,
      status: observed === expected ? "PASS" : "FAIL",
      viewports: viewportResults,
    });
  }
} finally {
  await browser.close();
}

const allResults = [...fixtureResults, ...toolbarResults],
  failures = allResults.filter((item) => item.status !== "PASS"),
  report = {
    schema_version: "nndv-0.7.1-visual-oracle-fixture-report-1",
    status: failures.length ? "FAIL" : "PASS",
    constant_true_rejected:
      positiveResult?.status === "PASS" &&
      mutationFiles.every(
        (mutation) =>
          byFile.get(path.resolve(mutation.file))?.status === "FAIL",
      ),
    fixture_sha256: Object.fromEntries(
      fs
        .readdirSync(fixtureRoot)
        .sort()
        .map((filename) => [
          filename,
          crypto
            .createHash("sha256")
            .update(fs.readFileSync(path.join(fixtureRoot, filename)))
            .digest("hex"),
        ]),
    ),
    svg: fixtureResults,
    toolbar: toolbarResults,
    failures,
  },
  serialized = `${JSON.stringify(report, null, 2)}\n`;
if (output) fs.writeFileSync(output, serialized);
process.stdout.write(serialized);
if (report.status !== "PASS" || !report.constant_true_rejected)
  process.exitCode = 1;
