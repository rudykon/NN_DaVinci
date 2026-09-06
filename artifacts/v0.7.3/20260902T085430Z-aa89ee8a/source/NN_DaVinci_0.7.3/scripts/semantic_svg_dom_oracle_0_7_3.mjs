#!/usr/bin/env node
/* Independent browser-DOM/CTM oracle for reader-visible architecture roles. */
import fs from "node:fs";
import path from "node:path";
import process from "node:process";
import { pathToFileURL } from "node:url";
import { chromium } from "playwright-core";

const args = process.argv.slice(2);
let output = null;
let allowFailures = false;
const caseDirs = [];
for (let index = 0; index < args.length; index += 1) {
  if (args[index] === "--output") output = args[++index];
  else if (args[index] === "--allow-failures") allowFailures = true;
  else if (args[index].startsWith("-"))
    throw new Error(`unknown option ${args[index]}`);
  else caseDirs.push(path.resolve(args[index]));
}
if (!caseDirs.length)
  throw new Error("at least one real-model case directory is required");

const browser = await chromium.launch({
  executablePath: process.env.NNDV_BROWSER || "/usr/bin/google-chrome",
  headless: true,
  args: ["--no-sandbox", "--disable-gpu"],
});
const cases = [];
try {
  for (const caseDir of caseDirs) {
    const semantic = JSON.parse(
      fs.readFileSync(path.join(caseDir, "semantic.semantic.json"), "utf8"),
    );
    const evidence = semantic.architecture_evidence;
    const context = await browser.newContext({
      viewport: { width: 1800, height: 1200 },
      deviceScaleFactor: 1,
    });
    await context.route(/https?:\/\//, (route) =>
      route.abort("blockedbyclient"),
    );
    const page = await context.newPage();
    const runtimeErrors = [];
    page.on("pageerror", (error) => runtimeErrors.push(error.message));
    page.on("console", (message) => {
      if (message.type() === "error") runtimeErrors.push(message.text());
    });
    await page.goto(pathToFileURL(path.join(caseDir, "scene.svg")).href, {
      waitUntil: "load",
    });
    await page.evaluate(async () => {
      if (document.fonts) await document.fonts.ready;
    });
    const measured = await page.evaluate(
      ({ roles, routes, digest }) => {
        const normalize = (value) =>
          String(value || "")
            .normalize("NFKC")
            .replace(/[\W_]+/gu, "")
            .toLocaleLowerCase();
        const svg = document.querySelector("svg");
        const boundary = svg.getBoundingClientRect();
        const blockers = [];
        const labelRows = [];
        const visible = (element) => {
          const style = getComputedStyle(element);
          return (
            style.display !== "none" &&
            style.visibility !== "hidden" &&
            Number(style.opacity || 1) > 0.001
          );
        };
        const landedBox = (element) => {
          const box = element.getBBox(),
            matrix = element.getScreenCTM();
          if (!matrix) return null;
          const corners = [
            new DOMPoint(box.x, box.y),
            new DOMPoint(box.x + box.width, box.y),
            new DOMPoint(box.x + box.width, box.y + box.height),
            new DOMPoint(box.x, box.y + box.height),
          ].map((point) => point.matrixTransform(matrix));
          return {
            left: Math.min(...corners.map((point) => point.x)),
            top: Math.min(...corners.map((point) => point.y)),
            right: Math.max(...corners.map((point) => point.x)),
            bottom: Math.max(...corners.map((point) => point.y)),
          };
        };
        for (const role of roles) {
          const selector = `[data-kind="label"][data-architecture-role-id="${CSS.escape(role.id)}"]`;
          const labels = [...document.querySelectorAll(selector)];
          if (!labels.length)
            blockers.push({ code: "svg_missing_role_label", role_id: role.id });
          for (const label of labels) {
            const box = landedBox(label),
              isVisible = visible(label);
            const inPage =
              box &&
              box.left >= boundary.left - 0.6 &&
              box.top >= boundary.top - 0.6 &&
              box.right <= boundary.right + 0.6 &&
              box.bottom <= boundary.bottom + 0.6;
            const matrix = label.getScreenCTM();
            const row = {
              role_id: role.id,
              text: label.textContent,
              visible: isVisible,
              in_page: Boolean(inPage),
              ctm: matrix
                ? [matrix.a, matrix.b, matrix.c, matrix.d, matrix.e, matrix.f]
                : null,
              box,
            };
            labelRows.push(row);
            if (!isVisible)
              blockers.push({
                code: "svg_hidden_role_label",
                role_id: role.id,
              });
            if (!inPage)
              blockers.push({
                code: "svg_role_label_off_page",
                role_id: role.id,
              });
            if (normalize(label.textContent) !== normalize(role.label))
              blockers.push({
                code: "svg_role_text_mismatch",
                role_id: role.id,
              });
            if (
              Number(label.dataset.repeatCount || 1) !==
              Number(role.repeat_count || 1)
            )
              blockers.push({
                code: "svg_repeat_count_mismatch",
                role_id: role.id,
              });
            if (label.dataset.evidenceDigest !== digest)
              blockers.push({
                code: "stale_evidence_digest",
                role_id: role.id,
              });
          }
        }
        for (const route of routes) {
          const selector = `[data-kind="arrow"][data-architecture-route-id="${CSS.escape(route.id)}"]`;
          const arrows = [...document.querySelectorAll(selector)];
          if (!arrows.length)
            blockers.push({
              code: "svg_missing_route_arrow",
              route_id: route.id,
            });
          for (const arrow of arrows) {
            if (!visible(arrow))
              blockers.push({ code: "svg_hidden_route", route_id: route.id });
            if (arrow.dataset.architectureDirection !== "source-to-target")
              blockers.push({
                code: "svg_route_direction_mismatch",
                route_id: route.id,
              });
            let endpoints = [];
            try {
              endpoints = JSON.parse(arrow.dataset.endpointRoleIds || "[]");
            } catch {
              /* blocker below */
            }
            if (
              JSON.stringify(endpoints) !==
              JSON.stringify([route.source_role_id, route.target_role_id])
            )
              blockers.push({
                code: "svg_route_endpoint_mismatch",
                route_id: route.id,
              });
            if (arrow.dataset.evidenceDigest !== digest)
              blockers.push({
                code: "stale_evidence_digest",
                route_id: route.id,
              });
          }
        }
        return {
          blockers,
          label_rows: labelRows,
          boundary: {
            left: boundary.left,
            top: boundary.top,
            right: boundary.right,
            bottom: boundary.bottom,
          },
        };
      },
      {
        roles: evidence.detected_roles,
        routes: evidence.critical_routes,
        digest: evidence.provenance_digest,
      },
    );
    measured.blockers.push(
      ...runtimeErrors.map((detail) => ({
        code: "browser_runtime_error",
        detail,
      })),
    );
    cases.push({
      case_dir: caseDir,
      family: evidence.family,
      expected_role_count: evidence.detected_roles.length,
      expected_route_count: evidence.critical_routes.length,
      status: measured.blockers.length ? "FAIL" : "PASS",
      ...measured,
    });
    await context.close();
  }
} finally {
  await browser.close();
}
const report = {
  schema_version: "nndv-0.7.3-semantic-svg-dom-oracle-1",
  oracle: "independent-browser-dom-ctm",
  status: cases.every((item) => item.status === "PASS") ? "PASS" : "FAIL",
  cases,
};
const encoded = `${JSON.stringify(report, null, 2)}\n`;
if (output) {
  fs.mkdirSync(path.dirname(path.resolve(output)), { recursive: true });
  fs.writeFileSync(output, encoded);
}
process.stdout.write(encoded);
if (report.status !== "PASS" && !allowFailures) process.exitCode = 1;
