#!/usr/bin/env node
/*
 * Independent Figure Studio final-SVG geometry oracle.
 *
 * The oracle opens the serialized SVG in Chromium and derives every verdict
 * from the rendered DOM.  It intentionally does not parse Figure IR metadata,
 * Python proof output, data-font-size-pt, data-horizontal-scale, or any other
 * producer-side quality assertion.
 */
import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import process from "node:process";
import { fileURLToPath, pathToFileURL } from "node:url";

const ORACLE_NAME = "figure-final-svg-chrome-v1";
const CONFIG = Object.freeze({
  cssPxToMm: 25.4 / 96,
  cssPxToPt: 72 / 96,
  boundaryTolerancePx: 0.6,
  collisionTolerancePx: 0.35,
  endpointTolerancePx: 1.5,
  curveTolerancePx: 0.2,
  epsilon: 1e-7,
  minimumFontPt: 7,
  minimumStrokePt: 0.1,
  scaleMinimum: 0.98,
  scaleMaximum: 1.02,
  transformShapeMinimum: 0.98,
  minimumPageOccupancy: 0.02,
  maximumPageOccupancy: 0.98,
});

function parseArguments(argv) {
  const files = [];
  let output = null;
  let allowFailures = false;
  for (let index = 0; index < argv.length; index += 1) {
    const value = argv[index];
    if (value === "--output") {
      output = argv[++index];
      if (!output) throw new Error("--output requires a path");
    } else if (value === "--allow-failures") {
      allowFailures = true;
    } else if (value === "--help" || value === "-h") {
      process.stdout.write(
        "usage: figure_svg_oracle.mjs [--output report.json] [--allow-failures] file.svg ...\n",
      );
      process.exit(0);
    } else if (value.startsWith("-")) {
      throw new Error(`unknown option: ${value}`);
    } else {
      files.push(value);
    }
  }
  if (!files.length)
    throw new Error("at least one persisted SVG path is required");
  return { files, output, allowFailures };
}

function sha256(file) {
  return crypto
    .createHash("sha256")
    .update(fs.readFileSync(file))
    .digest("hex");
}

const args = parseArguments(process.argv.slice(2));
const inputs = args.files.map((value) => {
  const absolute = path.resolve(value);
  const stat = fs.statSync(absolute);
  if (!stat.isFile()) throw new Error(`SVG input is not a file: ${absolute}`);
  return absolute;
});
const executablePath = process.env.NNDV_BROWSER || "/usr/bin/google-chrome";
let playwright;
try {
  playwright = await import("playwright-core");
} catch (error) {
  const override = process.env.NNDV_PLAYWRIGHT_MODULE;
  if (!override) {
    throw new Error(
      "playwright-core is not installed beside the oracle; install project dependencies " +
        "or set NNDV_PLAYWRIGHT_MODULE to playwright-core/index.mjs",
      { cause: error },
    );
  }
  playwright = await import(pathToFileURL(path.resolve(override)).href);
}
const { chromium } = playwright;
const flattenerPath = path.join(
  path.dirname(fileURLToPath(import.meta.url)),
  "svg_path_flatten.js",
);
const flattenerSource = fs.readFileSync(flattenerPath, "utf8");
const browser = await chromium.launch({
  executablePath,
  headless: true,
  args: ["--no-sandbox", "--disable-gpu"],
});
const browserVersion = browser.version();
const reports = [];

try {
  for (const absolute of inputs) {
    const context = await browser.newContext({
      viewport: { width: 4096, height: 4096 },
      deviceScaleFactor: 1,
    });
    await context.route(/https?:\/\//, (route) =>
      route.abort("blockedbyclient"),
    );
    const page = await context.newPage();
    const browserErrors = [];
    page.on("pageerror", (error) =>
      browserErrors.push(`pageerror: ${error.message}`),
    );
    page.on("console", (message) => {
      if (message.type() === "error")
        browserErrors.push(`console: ${message.text()}`);
    });
    await page.goto(pathToFileURL(absolute).href, { waitUntil: "load" });
    await page.evaluate((source) => globalThis.eval(source), flattenerSource);
    await page.evaluate(async () => {
      if (document.fonts) await document.fonts.ready;
    });

    const measured = await page.evaluate((configuration) => {
      "use strict";
      const svg = document.querySelector("svg");
      if (!svg)
        throw new Error("persisted document does not contain an SVG root");
      const cfg = configuration;
      const issues = [];
      const issueKeys = new Set();
      const measurementErrors = [];
      const ignoredProducerClaims = [
        "metadata proof/pass",
        "metadata minimum font",
        "data-font-size-pt",
        "data-horizontal-scale",
        "data-transform-text-scale",
      ];

      const round = (value, digits = 6) =>
        Number.isFinite(value) ? Number(value.toFixed(digits)) : null;
      const plainRect = (rect) => ({
        left: round(rect.left),
        top: round(rect.top),
        right: round(rect.right),
        bottom: round(rect.bottom),
        width: round(rect.width),
        height: round(rect.height),
      });
      const rectMm = (rect) => ({
        x: round(rect.left * cfg.cssPxToMm),
        y: round(rect.top * cfg.cssPxToMm),
        width: round(rect.width * cfg.cssPxToMm),
        height: round(rect.height * cfg.cssPxToMm),
      });
      const matrixPlain = (matrix) =>
        matrix
          ? {
              a: round(matrix.a),
              b: round(matrix.b),
              c: round(matrix.c),
              d: round(matrix.d),
              e: round(matrix.e),
              f: round(matrix.f),
            }
          : null;
      const point = (x, y) => ({ x, y });
      const distance = (first, second) =>
        Math.hypot(first.x - second.x, first.y - second.y);
      const rectFromPoints = (points) => {
        if (!points.length) return null;
        const xs = points.map((item) => item.x);
        const ys = points.map((item) => item.y);
        return {
          left: Math.min(...xs),
          top: Math.min(...ys),
          right: Math.max(...xs),
          bottom: Math.max(...ys),
          width: Math.max(...xs) - Math.min(...xs),
          height: Math.max(...ys) - Math.min(...ys),
        };
      };
      const unionRects = (rectangles) => {
        const valid = rectangles.filter(Boolean);
        if (!valid.length) return null;
        const left = Math.min(...valid.map((item) => item.left));
        const top = Math.min(...valid.map((item) => item.top));
        const right = Math.max(...valid.map((item) => item.right));
        const bottom = Math.max(...valid.map((item) => item.bottom));
        return {
          left,
          top,
          right,
          bottom,
          width: right - left,
          height: bottom - top,
        };
      };
      const intersectRect = (first, second) => {
        const left = Math.max(first.left, second.left);
        const top = Math.max(first.top, second.top);
        const right = Math.min(first.right, second.right);
        const bottom = Math.min(first.bottom, second.bottom);
        return right > left && bottom > top
          ? {
              left,
              top,
              right,
              bottom,
              width: right - left,
              height: bottom - top,
            }
          : null;
      };
      const rectOutside = (candidate, boundary) =>
        candidate.left < boundary.left - cfg.boundaryTolerancePx ||
        candidate.top < boundary.top - cfg.boundaryTolerancePx ||
        candidate.right > boundary.right + cfg.boundaryTolerancePx ||
        candidate.bottom > boundary.bottom + cfg.boundaryTolerancePx;
      const rectCompletelyOutside = (candidate, boundary) =>
        candidate.right < boundary.left - cfg.boundaryTolerancePx ||
        candidate.left > boundary.right + cfg.boundaryTolerancePx ||
        candidate.bottom < boundary.top - cfg.boundaryTolerancePx ||
        candidate.top > boundary.bottom + cfg.boundaryTolerancePx;
      const rectPositiveOverlap = (first, second, tolerance = 0) =>
        Math.min(first.right, second.right) -
          Math.max(first.left, second.left) >
          tolerance &&
        Math.min(first.bottom, second.bottom) -
          Math.max(first.top, second.top) >
          tolerance;
      const transformPoint = (item, matrix) => {
        const result = new DOMPoint(item.x, item.y).matrixTransform(matrix);
        return point(result.x, result.y);
      };
      const bboxQuad = (element, matrix = element.getScreenCTM()) => {
        try {
          const box = element.getBBox();
          if (!matrix) return [];
          return [
            transformPoint(point(box.x, box.y), matrix),
            transformPoint(point(box.x + box.width, box.y), matrix),
            transformPoint(
              point(box.x + box.width, box.y + box.height),
              matrix,
            ),
            transformPoint(point(box.x, box.y + box.height), matrix),
          ];
        } catch (error) {
          measurementErrors.push(
            `${element.tagName.toLowerCase()} getBBox failed: ${String(error)}`,
          );
          return [];
        }
      };
      const orientation = (a, b, c) =>
        (b.x - a.x) * (c.y - a.y) - (b.y - a.y) * (c.x - a.x);
      const pointOnSegment = (a, candidate, b, tolerance = cfg.epsilon) =>
        Math.abs(orientation(a, b, candidate)) <= tolerance &&
        candidate.x >= Math.min(a.x, b.x) - tolerance &&
        candidate.x <= Math.max(a.x, b.x) + tolerance &&
        candidate.y >= Math.min(a.y, b.y) - tolerance &&
        candidate.y <= Math.max(a.y, b.y) + tolerance;
      const pointInPolygon = (candidate, polygon, includeBoundary = true) => {
        if (polygon.length < 3) return false;
        for (let index = 0; index < polygon.length; index += 1) {
          const next = (index + 1) % polygon.length;
          if (
            pointOnSegment(
              polygon[index],
              candidate,
              polygon[next],
              cfg.collisionTolerancePx,
            )
          )
            return includeBoundary;
        }
        let inside = false;
        for (
          let index = 0, previous = polygon.length - 1;
          index < polygon.length;
          previous = index++
        ) {
          const currentPoint = polygon[index];
          const previousPoint = polygon[previous];
          const crosses =
            currentPoint.y > candidate.y !== previousPoint.y > candidate.y &&
            candidate.x <
              ((previousPoint.x - currentPoint.x) *
                (candidate.y - currentPoint.y)) /
                (previousPoint.y - currentPoint.y) +
                currentPoint.x;
          if (crosses) inside = !inside;
        }
        return inside;
      };
      const properSegmentsCross = (a, b, c, d) => {
        const first = orientation(a, b, c);
        const second = orientation(a, b, d);
        const third = orientation(c, d, a);
        const fourth = orientation(c, d, b);
        return (
          ((first > cfg.epsilon && second < -cfg.epsilon) ||
            (first < -cfg.epsilon && second > cfg.epsilon)) &&
          ((third > cfg.epsilon && fourth < -cfg.epsilon) ||
            (third < -cfg.epsilon && fourth > cfg.epsilon))
        );
      };
      const segmentsIntersect = (a, b, c, d) => {
        if (properSegmentsCross(a, b, c, d)) return true;
        return (
          pointOnSegment(a, c, b, cfg.collisionTolerancePx) ||
          pointOnSegment(a, d, b, cfg.collisionTolerancePx) ||
          pointOnSegment(c, a, d, cfg.collisionTolerancePx) ||
          pointOnSegment(c, b, d, cfg.collisionTolerancePx)
        );
      };
      const collinearOverlapLength = (a, b, c, d) => {
        if (
          Math.abs(orientation(a, b, c)) > cfg.collisionTolerancePx ||
          Math.abs(orientation(a, b, d)) > cfg.collisionTolerancePx
        )
          return 0;
        const useX = Math.abs(b.x - a.x) >= Math.abs(b.y - a.y);
        const first = useX ? [a.x, b.x] : [a.y, b.y];
        const second = useX ? [c.x, d.x] : [c.y, d.y];
        return Math.max(
          0,
          Math.min(Math.max(...first), Math.max(...second)) -
            Math.max(Math.min(...first), Math.min(...second)),
        );
      };
      const polygonsOverlap = (first, second) => {
        const firstRect = rectFromPoints(first);
        const secondRect = rectFromPoints(second);
        if (
          !firstRect ||
          !secondRect ||
          !rectPositiveOverlap(firstRect, secondRect, cfg.collisionTolerancePx)
        )
          return false;
        if (first.some((item) => pointInPolygon(item, second, false)))
          return true;
        if (second.some((item) => pointInPolygon(item, first, false)))
          return true;
        const overlapRect = intersectRect(firstRect, secondRect);
        if (overlapRect) {
          const center = point(
            overlapRect.left + overlapRect.width / 2,
            overlapRect.top + overlapRect.height / 2,
          );
          if (
            pointInPolygon(center, first, false) &&
            pointInPolygon(center, second, false)
          )
            return true;
        }
        for (let firstIndex = 0; firstIndex < first.length; firstIndex += 1)
          for (
            let secondIndex = 0;
            secondIndex < second.length;
            secondIndex += 1
          )
            if (
              properSegmentsCross(
                first[firstIndex],
                first[(firstIndex + 1) % first.length],
                second[secondIndex],
                second[(secondIndex + 1) % second.length],
              )
            )
              return true;
        return false;
      };
      const polygonContainsPolygon = (container, candidate) =>
        candidate.every((item) => pointInPolygon(item, container, true));
      const segmentPolygonHits = (a, b, polygon) => {
        const hits = [];
        if (pointInPolygon(a, polygon, true)) hits.push(a);
        if (pointInPolygon(b, polygon, true)) hits.push(b);
        for (let index = 0; index < polygon.length; index += 1) {
          const c = polygon[index];
          const d = polygon[(index + 1) % polygon.length];
          if (!segmentsIntersect(a, b, c, d)) continue;
          const denominator =
            (a.x - b.x) * (c.y - d.y) - (a.y - b.y) * (c.x - d.x);
          if (Math.abs(denominator) > cfg.epsilon) {
            const x =
              ((a.x * b.y - a.y * b.x) * (c.x - d.x) -
                (a.x - b.x) * (c.x * d.y - c.y * d.x)) /
              denominator;
            const y =
              ((a.x * b.y - a.y * b.x) * (c.y - d.y) -
                (a.y - b.y) * (c.x * d.y - c.y * d.x)) /
              denominator;
            hits.push(point(x, y));
          } else {
            for (const candidate of [a, b, c, d])
              if (
                pointOnSegment(a, candidate, b) &&
                pointOnSegment(c, candidate, d)
              )
                hits.push(candidate);
          }
        }
        return hits;
      };
      const addIssue = (code, objects, message, details = {}) => {
        const uniqueObjects = [...new Set(objects.filter(Boolean))];
        const key = `${code}\u0000${[...uniqueObjects].sort().join("\u0000")}\u0000${
          uniqueObjects.length ? "" : message
        }`;
        if (issueKeys.has(key)) return;
        issueKeys.add(key);
        issues.push({
          code,
          objects: uniqueObjects,
          message,
          details,
        });
      };
      const primaryObjectId = (element, fallback) =>
        element.getAttribute("data-figure-object-id") ||
        element
          .closest("[data-figure-object-id]")
          ?.getAttribute("data-figure-object-id") ||
        fallback;
      const pageIdFor = (element) =>
        element.getAttribute("data-page-id") ||
        element.closest("[data-page-id]")?.getAttribute("data-page-id") ||
        "page-root";
      const panelIdFor = (element) =>
        element.getAttribute("data-panel-id") ||
        element.closest("[data-panel-id]")?.getAttribute("data-panel-id") ||
        null;
      const parsePaintAlpha = (paint) => {
        const value = String(paint || "")
          .trim()
          .toLowerCase();
        if (!value || value === "none" || value === "transparent") return 0;
        const slashAlpha = value.match(/\/\s*([\d.]+%?)\s*\)$/);
        if (slashAlpha) {
          const numeric = Number.parseFloat(slashAlpha[1]);
          return Math.max(
            0,
            Math.min(1, slashAlpha[1].endsWith("%") ? numeric / 100 : numeric),
          );
        }
        if (value.startsWith("rgba(")) {
          const components = value.match(/[-+]?\d*\.?\d+%?/g) || [];
          if (components.length >= 4) {
            const alpha = components.at(-1);
            const numeric = Number.parseFloat(alpha);
            return Math.max(
              0,
              Math.min(1, alpha.endsWith("%") ? numeric / 100 : numeric),
            );
          }
        }
        return 1;
      };
      const renderedState = (element, kind) => {
        let opacity = 1;
        let hidden = false;
        for (
          let current = element;
          current && current instanceof Element;
          current = current.parentElement
        ) {
          const style = getComputedStyle(current);
          if (
            style.display === "none" ||
            style.visibility === "hidden" ||
            style.visibility === "collapse" ||
            style.contentVisibility === "hidden"
          )
            hidden = true;
          const ownOpacity = Number.parseFloat(style.opacity);
          if (Number.isFinite(ownOpacity)) opacity *= ownOpacity;
          if (current === svg) break;
        }
        const style = getComputedStyle(element);
        let paint = 1;
        if (kind === "text") {
          const fill =
            parsePaintAlpha(style.fill) *
            Number.parseFloat(style.fillOpacity || "1");
          const stroke =
            parsePaintAlpha(style.stroke) *
            Number.parseFloat(style.strokeOpacity || "1") *
            (Number.parseFloat(style.strokeWidth || "0") > 0 ? 1 : 0);
          paint = Math.max(fill, stroke);
        } else if (kind !== "image") {
          const fill =
            parsePaintAlpha(style.fill) *
            Number.parseFloat(style.fillOpacity || "1");
          const stroke =
            parsePaintAlpha(style.stroke) *
            Number.parseFloat(style.strokeOpacity || "1") *
            (Number.parseFloat(style.strokeWidth || "0") > 0 ? 1 : 0);
          paint = Math.max(fill, stroke);
        }
        const effectiveOpacity = Math.max(
          0,
          opacity * (Number.isFinite(paint) ? paint : 1),
        );
        return {
          hidden,
          transparent: !hidden && effectiveOpacity <= cfg.epsilon,
          effectiveOpacity,
        };
      };
      const parseFamilies = (value) => {
        const result = [];
        let token = "";
        let quote = null;
        for (const character of String(value || "")) {
          if (
            (character === '"' || character === "'") &&
            (!quote || quote === character)
          ) {
            quote = quote ? null : character;
          } else if (character === "," && !quote) {
            if (token.trim())
              result.push(token.trim().replace(/^["']|["']$/g, ""));
            token = "";
          } else token += character;
        }
        if (token.trim()) result.push(token.trim().replace(/^["']|["']$/g, ""));
        return result;
      };
      const genericFamilies = new Set([
        "serif",
        "sans-serif",
        "monospace",
        "cursive",
        "fantasy",
        "system-ui",
        "ui-serif",
        "ui-sans-serif",
        "ui-monospace",
        "math",
      ]);
      const canvas = document.createElementNS(
        "http://www.w3.org/1999/xhtml",
        "canvas",
      );
      const canvasContext = canvas.getContext("2d");
      const fontFallbackDetected = (primary, weight, style) => {
        if (
          !primary ||
          genericFamilies.has(primary.toLowerCase()) ||
          !canvasContext
        )
          return false;
        const quoted = `"${primary.replaceAll('"', '\\"')}"`;
        const probes = [
          "mmmmmmmmmmlliWWW@#",
          "0123456789ABCxyz",
          "汉字数学Σ∫√",
        ];
        return ["monospace", "serif", "sans-serif"].every((fallback) => {
          for (const probe of probes) {
            canvasContext.font = `${style} ${weight} 64px ${quoted}, ${fallback}`;
            const requestedWidth = canvasContext.measureText(probe).width;
            canvasContext.font = `${style} ${weight} 64px ${fallback}`;
            const fallbackWidth = canvasContext.measureText(probe).width;
            if (Math.abs(requestedWidth - fallbackWidth) > 0.01) return false;
          }
          return true;
        });
      };

      const rootRect = plainRect(svg.getBoundingClientRect());
      const pageGroups = [
        ...svg.querySelectorAll(
          "g.figure-page[data-page-id], g[data-page-id].figure-page",
        ),
      ];
      const pages = (pageGroups.length ? pageGroups : [svg]).map(
        (element, index) => {
          const boundaryElement =
            element === svg
              ? svg
              : element.querySelector(
                  ":scope > rect.page-boundary, :scope > rect",
                );
          const rect = plainRect(
            (boundaryElement || element).getBoundingClientRect(),
          );
          return {
            id:
              element === svg
                ? "page-root"
                : element.getAttribute("data-page-id") || `page-${index + 1}`,
            element,
            boundaryElement,
            rect,
            baseMatrix: element.getScreenCTM(),
          };
        },
      );
      const pageById = new Map(pages.map((item) => [item.id, item]));
      const panels = [
        ...svg.querySelectorAll("g.figure-panel[data-panel-id]"),
      ].map((element, index) => {
        const boundaryElement = element.querySelector(
          ":scope > rect.panel-boundary, :scope > [data-nndv-role='panel']",
        );
        return {
          id: element.getAttribute("data-panel-id") || `panel-${index + 1}`,
          pageId: pageIdFor(element),
          element,
          boundaryElement,
          rect: plainRect((boundaryElement || element).getBoundingClientRect()),
        };
      });
      const panelByKey = new Map(
        panels.map((item) => [`${item.pageId}\u0000${item.id}`, item]),
      );
      const ownerPanel = (pageId, panelId) =>
        panelId ? panelByKey.get(`${pageId}\u0000${panelId}`) || null : null;
      for (const page of pages)
        if (page.element !== svg && rectOutside(page.rect, rootRect))
          addIssue(
            "PAGE_ROOT_CLIP",
            [page.id],
            "Figure Page boundary crosses the root SVG viewport",
          );
      for (const panel of panels) {
        const page = pageById.get(panel.pageId);
        if (page && rectOutside(panel.rect, page.rect))
          addIssue(
            "PANEL_PAGE_CLIP",
            [panel.id],
            "Figure Panel boundary crosses its Page boundary",
            { page_id: panel.pageId },
          );
      }

      const texts = [...svg.querySelectorAll("text")].map((element, index) => {
        const role =
          element.getAttribute("data-text-role") ||
          (element.classList.contains("panel-label")
            ? "panel-label"
            : "figure-text");
        const objectId = primaryObjectId(
          element,
          role === "panel-label"
            ? `panel-label:${panelIdFor(element) || index}`
            : `text:${index}`,
        );
        const pageId = pageIdFor(element);
        const panelId = panelIdFor(element);
        const state = renderedState(element, "text");
        const matrix = element.getScreenCTM();
        const page = pageById.get(pageId) || pages[0];
        let relativeMatrix = null;
        try {
          if (matrix && page?.baseMatrix)
            relativeMatrix = page.baseMatrix.inverse().multiply(matrix);
        } catch (error) {
          measurementErrors.push(
            `${objectId} relative CTM failed: ${String(error)}`,
          );
        }
        const relative = relativeMatrix || new DOMMatrix();
        const horizontalCtm = Math.hypot(relative.a, relative.b);
        const verticalCtm = Math.hypot(relative.c, relative.d);
        const dot = relative.a * relative.c + relative.b * relative.d;
        const orthogonality =
          horizontalCtm > cfg.epsilon && verticalCtm > cfg.epsilon
            ? Math.abs(dot / (horizontalCtm * verticalCtm))
            : 1;
        const trace =
          relative.a ** 2 + relative.b ** 2 + relative.c ** 2 + relative.d ** 2;
        const determinant = relative.a * relative.d - relative.b * relative.c;
        const discriminant = Math.sqrt(
          Math.max(0, trace ** 2 - 4 * determinant ** 2),
        );
        const sigmaMax = Math.sqrt(Math.max(0, (trace + discriminant) / 2));
        const sigmaMin = Math.sqrt(Math.max(0, (trace - discriminant) / 2));
        const transformShape = sigmaMax > cfg.epsilon ? sigmaMin / sigmaMax : 0;
        const screenHorizontal = matrix ? Math.hypot(matrix.a, matrix.b) : 0;
        const screenVertical = matrix ? Math.hypot(matrix.c, matrix.d) : 0;
        const computedStyle = getComputedStyle(element);
        const computedFontPx = Number.parseFloat(computedStyle.fontSize);
        const effectiveFontPt = computedFontPx * screenVertical * cfg.cssPxToPt;
        let actualAdvance = 0;
        let naturalAdvance = 0;
        try {
          actualAdvance = element.getComputedTextLength();
          if (!state.hidden) {
            const clone = element.cloneNode(true);
            for (const item of [clone, ...clone.querySelectorAll("*")]) {
              item.removeAttribute("textLength");
              item.removeAttribute("lengthAdjust");
              item.removeAttribute("transform");
              item.style.setProperty("font-stretch", "normal", "important");
              item.style.setProperty(
                "font-variation-settings",
                "normal",
                "important",
              );
              item.style.setProperty("letter-spacing", "normal", "important");
              item.style.setProperty("transform", "none", "important");
            }
            clone.style.setProperty("visibility", "hidden", "important");
            element.parentNode.appendChild(clone);
            naturalAdvance = clone.getComputedTextLength();
            clone.remove();
          }
        } catch (error) {
          measurementErrors.push(
            `${objectId} text advance failed: ${String(error)}`,
          );
        }
        const glyphAdvanceScale =
          naturalAdvance > cfg.epsilon ? actualAdvance / naturalAdvance : 1;
        const rect = plainRect(element.getBoundingClientRect());
        const quad = bboxQuad(element, matrix);
        const families = parseFamilies(computedStyle.fontFamily);
        const primaryFamily = families[0] || "";
        const sample = element.textContent || "BESbswy";
        let fontCheck = true;
        if (document.fonts && primaryFamily) {
          try {
            const escaped = primaryFamily.replaceAll('"', '\\"');
            fontCheck = document.fonts.check(
              `${computedStyle.fontStyle} ${computedStyle.fontWeight} ${Math.max(1, computedFontPx)}px "${escaped}"`,
              sample,
            );
          } catch {
            fontCheck = false;
          }
        }
        const fallbackDetected = fontFallbackDetected(
          primaryFamily,
          computedStyle.fontWeight,
          computedStyle.fontStyle,
        );
        return {
          index,
          element,
          id: objectId,
          role,
          pageId,
          panelId,
          text: element.textContent || "",
          characters: [...(element.textContent || "")].length,
          bbox: rect,
          bboxMm: rectMm(rect),
          localBBox: (() => {
            try {
              const box = element.getBBox();
              return {
                x: round(box.x),
                y: round(box.y),
                width: round(box.width),
                height: round(box.height),
              };
            } catch {
              return null;
            }
          })(),
          quad,
          screenCtm: matrixPlain(matrix),
          relativeCtm: matrixPlain(relative),
          horizontalCtmScale: round(horizontalCtm),
          verticalCtmScale: round(verticalCtm),
          transformShape: round(transformShape),
          orthogonalityError: round(orthogonality),
          rotationDegrees: round(
            (Math.atan2(relative.b, relative.a) * 180) / Math.PI,
          ),
          computedFontPx: round(computedFontPx),
          effectiveFontPt: round(effectiveFontPt),
          computedTextLength: round(actualAdvance),
          naturalTextLength: round(naturalAdvance),
          glyphAdvanceScale: round(glyphAdvanceScale),
          screenAdvancePx: round(actualAdvance * screenHorizontal),
          fontFamily: computedStyle.fontFamily,
          fontPrimary: primaryFamily,
          fontSetCheck: fontCheck,
          fallbackDetected,
          display: computedStyle.display,
          visibility: computedStyle.visibility,
          effectiveOpacity: round(state.effectiveOpacity),
          hidden: state.hidden,
          transparent: state.transparent,
          zeroSize: rect.width <= cfg.epsilon || rect.height <= cfg.epsilon,
        };
      });

      for (const text of texts) {
        if (text.hidden) {
          addIssue(
            "TEXT_HIDDEN",
            [text.id],
            "text is hidden by display or visibility",
            {
              role: text.role,
            },
          );
          continue;
        }
        if (text.transparent) {
          addIssue(
            "TEXT_TRANSPARENT",
            [text.id],
            "text has zero effective paint opacity",
            {
              role: text.role,
            },
          );
          continue;
        }
        if (text.zeroSize) {
          addIssue(
            "TEXT_ZERO_SIZE",
            [text.id],
            "visible text has a zero-size rendered bbox",
            {
              role: text.role,
            },
          );
          continue;
        }
        if (text.effectiveFontPt + 0.01 < cfg.minimumFontPt)
          addIssue(
            "TEXT_FONT_TOO_SMALL",
            [text.id],
            "measured effective font is below 7 pt",
            {
              role: text.role,
              effective_font_pt: text.effectiveFontPt,
            },
          );
        if (
          text.horizontalCtmScale < cfg.scaleMinimum ||
          text.horizontalCtmScale > cfg.scaleMaximum ||
          text.verticalCtmScale < cfg.scaleMinimum ||
          text.verticalCtmScale > cfg.scaleMaximum
        )
          addIssue(
            "TEXT_CTM_SCALE",
            [text.id],
            "text CTM scale is not approximately 1",
            {
              horizontal: text.horizontalCtmScale,
              vertical: text.verticalCtmScale,
            },
          );
        if (
          text.transformShape < cfg.transformShapeMinimum ||
          text.orthogonalityError > 0.02
        )
          addIssue(
            "TEXT_TRANSFORM_SHAPE",
            [text.id],
            "text CTM contains anisotropy or shear",
            {
              shape: text.transformShape,
              orthogonality_error: text.orthogonalityError,
            },
          );
        if (Math.abs(text.glyphAdvanceScale - 1) > 0.02)
          addIssue(
            "TEXT_GLYPH_COMPRESSION",
            [text.id],
            "rendered glyph advance differs from the natural advance",
            { scale: text.glyphAdvanceScale },
          );
        if (!text.fontSetCheck)
          addIssue(
            "FONT_NOT_LOADED",
            [text.id],
            "the computed primary font is not loaded",
            {
              family: text.fontPrimary,
            },
          );
        if (text.fallbackDetected)
          addIssue(
            "FONT_FALLBACK",
            [text.id],
            "the requested primary font resolved to fallback",
            {
              family: text.fontPrimary,
            },
          );
        const page = pageById.get(text.pageId) || pages[0];
        if (!page) continue;
        if (rectCompletelyOutside(text.bbox, page.rect))
          addIssue(
            "TEXT_OFF_PAGE",
            [text.id],
            "text is wholly outside its Figure Page",
            {
              page_id: page.id,
            },
          );
        else if (rectOutside(text.bbox, page.rect))
          addIssue(
            "TEXT_PAGE_CLIP",
            [text.id],
            "text crosses its Figure Page boundary",
            {
              page_id: page.id,
            },
          );
        const panel = ownerPanel(text.pageId, text.panelId);
        if (panel) {
          if (rectCompletelyOutside(text.bbox, panel.rect))
            addIssue(
              "TEXT_OFF_PANEL",
              [text.id],
              "text is wholly outside its Figure Panel",
              {
                page_id: text.pageId,
                panel_id: panel.id,
                role: text.role,
              },
            );
          else if (rectOutside(text.bbox, panel.rect))
            addIssue(
              "TEXT_PANEL_CLIP",
              [text.id],
              "text crosses its Figure Panel boundary",
              {
                page_id: text.pageId,
                panel_id: panel.id,
                role: text.role,
              },
            );
        }
      }

      const edgeSelector = [
        "path[data-nndv-role='edge']",
        "polyline[data-nndv-role='edge']",
        "line[data-nndv-role='edge']",
        "path[data-primitive-kind='path']",
        "polyline[data-primitive-kind='polyline']",
        "line[data-primitive-kind='line']",
      ].join(",");
      const edgeElements = [
        ...new Set(svg.querySelectorAll(edgeSelector)),
      ].filter((element) => !element.closest("defs"));
      const edges = edgeElements.map((element, index) => {
        const id = primaryObjectId(element, `edge:${index}`);
        const matrix = element.getScreenCTM();
        const identity = { a: 1, b: 0, c: 0, d: 1, e: 0, f: 0 };
        let localPoints = [];
        let screenPoints = [];
        try {
          if (!matrix) throw new Error("getScreenCTM returned null");
          if (element.tagName.toLowerCase() === "path") {
            const data = element.getAttribute("d") || "";
            localPoints = globalThis.nndvFlattenPathData(
              data,
              identity,
              cfg.curveTolerancePx /
                Math.max(1, Math.hypot(matrix.a, matrix.b)),
              cfg.epsilon,
            );
            screenPoints = globalThis.nndvFlattenPathData(
              data,
              matrixPlain(matrix),
              cfg.curveTolerancePx,
              cfg.epsilon,
            );
          } else if (element.tagName.toLowerCase() === "line") {
            localPoints = [
              point(
                Number(element.getAttribute("x1") || 0),
                Number(element.getAttribute("y1") || 0),
              ),
              point(
                Number(element.getAttribute("x2") || 0),
                Number(element.getAttribute("y2") || 0),
              ),
            ];
            screenPoints = localPoints.map((item) =>
              transformPoint(item, matrix),
            );
          } else {
            localPoints = [...element.points].map((item) =>
              point(item.x, item.y),
            );
            screenPoints = localPoints.map((item) =>
              transformPoint(item, matrix),
            );
          }
        } catch (error) {
          measurementErrors.push(`${id} edge flatten failed: ${String(error)}`);
        }
        return {
          element,
          id,
          pageId: pageIdFor(element),
          panelId: panelIdFor(element),
          matrix,
          localPoints,
          screenPoints,
          bbox: plainRect(element.getBoundingClientRect()),
          state: renderedState(element, "shape"),
        };
      });

      const shapeTags = new Set([
        "rect",
        "polygon",
        "circle",
        "ellipse",
        "image",
        "use",
        "path",
      ]);
      const shapeElements = [
        ...svg.querySelectorAll("rect,polygon,circle,ellipse,image,use,path"),
      ].filter((element) => {
        if (element.closest("defs")) return false;
        if (edgeElements.includes(element)) return false;
        if (
          element === svg ||
          element.classList.contains("figure-background") ||
          element.classList.contains("panel-boundary") ||
          element.classList.contains("page-boundary") ||
          element.getAttribute("data-nndv-role") === "panel"
        )
          return false;
        return Boolean(
          element.getAttribute("data-figure-object-id") ||
            element.closest("[data-figure-object-id]") ||
            element.getAttribute("data-tensor-face"),
        );
      });
      const elementPolygon = (element) => {
        const tag = element.tagName.toLowerCase();
        if (!shapeTags.has(tag)) return [];
        const matrix = element.getScreenCTM();
        if (!matrix) return [];
        if (tag === "polygon")
          return [...element.points].map((item) =>
            transformPoint(point(item.x, item.y), matrix),
          );
        if (tag === "circle" || tag === "ellipse") {
          const cx = Number(element.getAttribute("cx") || 0);
          const cy = Number(element.getAttribute("cy") || 0);
          const rx = Number(
            element.getAttribute(tag === "circle" ? "r" : "rx") || 0,
          );
          const ry = Number(
            element.getAttribute(tag === "circle" ? "r" : "ry") || 0,
          );
          return Array.from({ length: 40 }, (_, index) => {
            const angle = (2 * Math.PI * index) / 40;
            return transformPoint(
              point(cx + rx * Math.cos(angle), cy + ry * Math.sin(angle)),
              matrix,
            );
          });
        }
        if (tag === "path") {
          try {
            return globalThis.nndvFlattenPathData(
              element.getAttribute("d") || "",
              matrixPlain(matrix),
              cfg.curveTolerancePx,
              cfg.epsilon,
            );
          } catch (error) {
            measurementErrors.push(
              `shape path flatten failed: ${String(error)}`,
            );
            return bboxQuad(element, matrix);
          }
        }
        return bboxQuad(element, matrix);
      };
      const shapes = shapeElements.map((element, index) => {
        const id = primaryObjectId(element, `shape:${index}`);
        const state = renderedState(
          element,
          element.tagName.toLowerCase() === "image" ? "image" : "shape",
        );
        const polygon = elementPolygon(element);
        const rect = plainRect(element.getBoundingClientRect());
        return {
          element,
          id,
          componentId: `${id}:${element.getAttribute("data-tensor-face") || index}`,
          pageId: pageIdFor(element),
          panelId: panelIdFor(element),
          primitive:
            element.getAttribute("data-primitive-kind") ||
            element.tagName.toLowerCase(),
          tensorFace: element.getAttribute("data-tensor-face") || null,
          polygon,
          bbox: rect,
          state,
          zeroSize: rect.width <= cfg.epsilon || rect.height <= cfg.epsilon,
        };
      });

      // Measure every rendered stroke from the persisted DOM.  CSSOM exposes
      // stroke-width in the element's user coordinate system; the singular
      // values of the complete screen CTM give the conservative minimum and
      // maximum physical widths after arbitrary transforms.  A
      // non-scaling-stroke is already expressed in screen CSS pixels.
      const strokeElements = [
        ...svg.querySelectorAll(
          "path,polyline,line,rect,polygon,circle,ellipse,text,use",
        ),
      ].filter((element) => !element.closest("defs"));
      const strokes = [];
      for (const [index, element] of strokeElements.entries()) {
        const style = getComputedStyle(element);
        const localStroke = Number.parseFloat(style.strokeWidth || "0");
        const opacityValue = Number.parseFloat(style.strokeOpacity || "1");
        const strokeAlpha =
          parsePaintAlpha(style.stroke) *
          (Number.isFinite(opacityValue) ? opacityValue : 1);
        const state = renderedState(element, "shape");
        if (
          !Number.isFinite(localStroke) ||
          localStroke <= cfg.epsilon ||
          strokeAlpha <= cfg.epsilon ||
          state.hidden ||
          state.transparent
        )
          continue;
        const matrix = element.getScreenCTM();
        if (!matrix) {
          measurementErrors.push(
            `${primaryObjectId(element, `stroke:${index}`)} stroke CTM is null`,
          );
          continue;
        }
        const trace = matrix.a ** 2 + matrix.b ** 2 + matrix.c ** 2 + matrix.d ** 2;
        const determinant = matrix.a * matrix.d - matrix.b * matrix.c;
        const discriminant = Math.sqrt(
          Math.max(0, trace ** 2 - 4 * determinant ** 2),
        );
        let sigmaMaximum = Math.sqrt(
          Math.max(0, (trace + discriminant) / 2),
        );
        let sigmaMinimum = Math.sqrt(
          Math.max(0, (trace - discriminant) / 2),
        );
        const nonScaling = style.vectorEffect === "non-scaling-stroke";
        if (nonScaling) sigmaMinimum = sigmaMaximum = 1;
        const effectiveMinimum =
          localStroke * sigmaMinimum * cfg.cssPxToPt;
        const effectiveMaximum =
          localStroke * sigmaMaximum * cfg.cssPxToPt;
        const measurement = {
          id: primaryObjectId(element, `stroke:${index}`),
          pageId: pageIdFor(element),
          panelId: panelIdFor(element),
          primitive: element.tagName.toLowerCase(),
          computedStrokeUserUnits: round(localStroke),
          effectiveStrokePt: round(effectiveMinimum),
          effectiveStrokeMaximumPt: round(effectiveMaximum),
          ctmMinimumScale: round(sigmaMinimum),
          ctmMaximumScale: round(sigmaMaximum),
          nonScaling,
          screenCtm: matrixPlain(matrix),
        };
        strokes.push(measurement);
        if (effectiveMinimum + 0.01 < cfg.minimumStrokePt)
          addIssue(
            "STROKE_TOO_THIN",
            [measurement.id],
            "measured effective stroke is below the strict physical minimum",
            {
              effective_stroke_pt: measurement.effectiveStrokePt,
              minimum_stroke_pt: cfg.minimumStrokePt,
            },
          );
      }

      for (const shape of shapes) {
        if (shape.state.hidden) {
          addIssue("OBJECT_HIDDEN", [shape.id], "graphical object is hidden", {
            primitive: shape.primitive,
          });
          continue;
        }
        if (shape.state.transparent) {
          addIssue(
            "OBJECT_TRANSPARENT",
            [shape.id],
            "graphical object has zero paint opacity",
            {
              primitive: shape.primitive,
            },
          );
          continue;
        }
        if (shape.zeroSize) {
          addIssue(
            "OBJECT_ZERO_SIZE",
            [shape.id],
            "graphical object has a zero-size bbox",
            {
              primitive: shape.primitive,
            },
          );
          continue;
        }
        const page = pageById.get(shape.pageId) || pages[0];
        if (page) {
          if (rectCompletelyOutside(shape.bbox, page.rect))
            addIssue(
              "OBJECT_OFF_PAGE",
              [shape.id],
              "graphical object is wholly outside its Page",
              {
                page_id: page.id,
              },
            );
          else if (rectOutside(shape.bbox, page.rect))
            addIssue(
              "OBJECT_PAGE_CLIP",
              [shape.id],
              "graphical object crosses its Page boundary",
              {
                page_id: page.id,
              },
            );
        }
        const panel = ownerPanel(shape.pageId, shape.panelId);
        if (panel) {
          if (rectCompletelyOutside(shape.bbox, panel.rect))
            addIssue(
              "OBJECT_OFF_PANEL",
              [shape.id],
              "graphical object is wholly outside its Panel",
              {
                panel_id: panel.id,
              },
            );
          else if (rectOutside(shape.bbox, panel.rect))
            addIssue(
              "OBJECT_PANEL_CLIP",
              [shape.id],
              "graphical object crosses its Panel boundary",
              {
                panel_id: panel.id,
              },
            );
        }
      }

      const activeTexts = texts.filter(
        (item) =>
          !item.hidden &&
          !item.transparent &&
          !item.zeroSize &&
          item.quad.length >= 3,
      );
      const activeShapes = shapes.filter(
        (item) =>
          !item.state.hidden &&
          !item.state.transparent &&
          !item.zeroSize &&
          item.polygon.length >= 3,
      );
      for (let index = 0; index < activeTexts.length; index += 1)
        for (let other = index + 1; other < activeTexts.length; other += 1) {
          const first = activeTexts[index];
          const second = activeTexts[other];
          if (
            first.pageId !== second.pageId ||
            !polygonsOverlap(first.quad, second.quad)
          )
            continue;
          const roles = new Set([first.role, second.role]);
          const code =
            roles.has("panel-label") && roles.has("title")
              ? "PANEL_LABEL_TITLE_COLLISION"
              : "TEXT_TEXT_COLLISION";
          addIssue(
            code,
            [first.id, second.id],
            "rendered text bboxes overlap",
            {
              roles: [first.role, second.role],
            },
          );
        }
      for (const text of activeTexts) {
        const ownerShapes = activeShapes.filter(
          (shape) => shape.id === text.id,
        );
        if (
          text.role === "node-label" &&
          ownerShapes.length &&
          !ownerShapes.some((shape) =>
            polygonContainsPolygon(shape.polygon, text.quad),
          )
        )
          addIssue(
            "TEXT_OWNER_OVERFLOW",
            [text.id],
            "node label bbox exceeds its owner shape",
            {
              role: text.role,
            },
          );
        for (const shape of activeShapes) {
          if (text.pageId !== shape.pageId) continue;
          if (text.id === shape.id && text.role !== "tensor-shape-label")
            continue;
          if (polygonsOverlap(text.quad, shape.polygon))
            addIssue(
              "TEXT_SHAPE_COLLISION",
              [text.id, shape.id],
              "text bbox overlaps a graphical object",
              {
                role: text.role,
                primitive: shape.primitive,
              },
            );
        }
      }
      const seenShapePairs = new Set();
      for (let index = 0; index < activeShapes.length; index += 1)
        for (let other = index + 1; other < activeShapes.length; other += 1) {
          const first = activeShapes[index];
          const second = activeShapes[other];
          if (first.id === second.id || first.pageId !== second.pageId)
            continue;
          const key = [first.id, second.id].sort().join("\u0000");
          if (
            seenShapePairs.has(key) ||
            !polygonsOverlap(first.polygon, second.polygon)
          )
            continue;
          seenShapePairs.add(key);
          addIssue(
            "SHAPE_SHAPE_OVERLAP",
            [first.id, second.id],
            "node/tensor/polygon objects overlap",
            {
              primitives: [first.primitive, second.primitive],
            },
          );
        }

      for (const edge of edges) {
        if (edge.state.hidden) {
          addIssue("OBJECT_HIDDEN", [edge.id], "edge is hidden", {
            primitive: "edge",
          });
          continue;
        }
        if (edge.state.transparent) {
          addIssue(
            "OBJECT_TRANSPARENT",
            [edge.id],
            "edge has zero paint opacity",
            {
              primitive: "edge",
            },
          );
          continue;
        }
        const edgeLength = edge.screenPoints
          .slice(1)
          .reduce(
            (total, item, index) =>
              total + distance(edge.screenPoints[index], item),
            0,
          );
        if (edge.screenPoints.length < 2 || edgeLength <= cfg.epsilon) {
          addIssue(
            "EDGE_ZERO_SIZE",
            [edge.id],
            "edge has no measurable rendered length",
          );
          continue;
        }
        const page = pageById.get(edge.pageId) || pages[0];
        if (page) {
          if (rectCompletelyOutside(edge.bbox, page.rect))
            addIssue(
              "EDGE_OFF_PAGE",
              [edge.id],
              "edge is wholly outside its Page",
              {
                page_id: page.id,
              },
            );
          else if (rectOutside(edge.bbox, page.rect))
            addIssue(
              "EDGE_PAGE_CLIP",
              [edge.id],
              "edge crosses its Page boundary",
              {
                page_id: page.id,
              },
            );
        }
        const panel = ownerPanel(edge.pageId, edge.panelId);
        if (panel) {
          if (rectCompletelyOutside(edge.bbox, panel.rect))
            addIssue(
              "EDGE_OFF_PANEL",
              [edge.id],
              "edge is wholly outside its Panel",
              { panel_id: panel.id },
            );
          else if (rectOutside(edge.bbox, panel.rect))
            addIssue(
              "EDGE_PANEL_CLIP",
              [edge.id],
              "edge crosses its Panel boundary",
              { panel_id: panel.id },
            );
        }
        for (const shape of activeShapes) {
          if (edge.id === shape.id || edge.pageId !== shape.pageId) continue;
          const hits = [];
          for (
            let segment = 1;
            segment < edge.screenPoints.length;
            segment += 1
          ) {
            for (const hit of segmentPolygonHits(
              edge.screenPoints[segment - 1],
              edge.screenPoints[segment],
              shape.polygon,
            ))
              hits.push({ point: hit, segment });
          }
          if (!hits.length) continue;
          const start = edge.screenPoints[0];
          const end = edge.screenPoints.at(-1);
          const endpointOnly = hits.every(
            (hit) =>
              (hit.segment === 1 &&
                distance(hit.point, start) <= cfg.endpointTolerancePx) ||
              (hit.segment === edge.screenPoints.length - 1 &&
                distance(hit.point, end) <= cfg.endpointTolerancePx),
          );
          if (!endpointOnly)
            addIssue(
              "EDGE_SHAPE_COLLISION",
              [edge.id, shape.id],
              "complete edge polyline/path intersects an unrelated graphical object",
              {
                primitive: shape.primitive,
                flattened_points: edge.screenPoints.length,
              },
            );
        }
        for (const text of activeTexts) {
          if (edge.id === text.id || edge.pageId !== text.pageId) continue;
          let collision = false;
          for (
            let segment = 1;
            segment < edge.screenPoints.length && !collision;
            segment += 1
          )
            collision =
              segmentPolygonHits(
                edge.screenPoints[segment - 1],
                edge.screenPoints[segment],
                text.quad,
              ).length > 0;
          if (collision)
            addIssue(
              "TEXT_EDGE_COLLISION",
              [text.id, edge.id],
              "text bbox intersects an edge",
              {
                role: text.role,
              },
            );
        }
      }

      for (let index = 0; index < edges.length; index += 1)
        for (let other = index + 1; other < edges.length; other += 1) {
          const first = edges[index];
          const second = edges[other];
          if (first.id === second.id || first.pageId !== second.pageId) continue;
          let crossing = false;
          for (let a = 1; a < first.screenPoints.length && !crossing; a += 1)
            for (
              let b = 1;
              b < second.screenPoints.length && !crossing;
              b += 1
            ) {
              const a0 = first.screenPoints[a - 1];
              const a1 = first.screenPoints[a];
              const b0 = second.screenPoints[b - 1];
              const b1 = second.screenPoints[b];
              if (!segmentsIntersect(a0, a1, b0, b1)) continue;
              const sharedEndpoint = [a0, a1].some((firstPoint) =>
                [b0, b1].some(
                  (secondPoint) =>
                    distance(firstPoint, secondPoint) <=
                      cfg.endpointTolerancePx &&
                    [first.screenPoints[0], first.screenPoints.at(-1)].some(
                      (endpoint) =>
                        distance(endpoint, firstPoint) <=
                        cfg.endpointTolerancePx,
                    ) &&
                    [second.screenPoints[0], second.screenPoints.at(-1)].some(
                      (endpoint) =>
                        distance(endpoint, secondPoint) <=
                        cfg.endpointTolerancePx,
                    ),
                ),
              );
              const overlap = collinearOverlapLength(a0, a1, b0, b1);
              if (
                properSegmentsCross(a0, a1, b0, b1) ||
                overlap > cfg.endpointTolerancePx ||
                !sharedEndpoint
              )
                crossing = true;
            }
          if (crossing)
            addIssue(
              "EDGE_EDGE_CROSSING",
              [first.id, second.id],
              "unexplained edges cross",
            );
        }

      const markerMeasurements = [];
      const markerReference = (value) => {
        const match = String(value || "").match(
          /url\(\s*["']?#([^)'"\s]+)["']?\s*\)/,
        );
        return match ? match[1] : null;
      };
      for (const edge of edges) {
        if (
          edge.screenPoints.length < 2 ||
          edge.localPoints.length < 2 ||
          !edge.matrix
        )
          continue;
        for (const position of ["start", "end"]) {
          const reference = markerReference(
            edge.element.getAttribute(`marker-${position}`),
          );
          if (!reference) continue;
          const marker = svg.querySelector(`marker#${CSS.escape(reference)}`);
          if (!marker) {
            addIssue(
              "MARKER_MISSING",
              [edge.id],
              "edge references a missing marker",
              {
                marker: reference,
                position,
              },
            );
            continue;
          }
          const viewBox = String(marker.getAttribute("viewBox") || "0 0 3 3")
            .trim()
            .split(/[\s,]+/)
            .map(Number);
          const [viewX, viewY, viewWidth, viewHeight] = viewBox;
          const markerWidth = Number.parseFloat(
            marker.getAttribute("markerWidth") || "3",
          );
          const markerHeight = Number.parseFloat(
            marker.getAttribute("markerHeight") || "3",
          );
          const refX = Number.parseFloat(marker.getAttribute("refX") || "0");
          const refY = Number.parseFloat(marker.getAttribute("refY") || "0");
          let childBox = null;
          for (const child of marker.querySelectorAll(
            "path,polygon,rect,circle,ellipse",
          )) {
            try {
              const box = child.getBBox();
              const item = {
                left: box.x,
                top: box.y,
                right: box.x + box.width,
                bottom: box.y + box.height,
                width: box.width,
                height: box.height,
              };
              childBox = unionRects([childBox, item]);
            } catch {
              // Fall back to the marker viewBox below.
            }
          }
          childBox ||= {
            left: viewX,
            top: viewY,
            right: viewX + viewWidth,
            bottom: viewY + viewHeight,
            width: viewWidth,
            height: viewHeight,
          };
          const preserve =
            marker.getAttribute("preserveAspectRatio") || "xMidYMid meet";
          let scaleX = markerWidth / viewWidth;
          let scaleY = markerHeight / viewHeight;
          let offsetX = 0;
          let offsetY = 0;
          if (!preserve.trim().startsWith("none")) {
            const uniform = preserve.includes("slice")
              ? Math.max(scaleX, scaleY)
              : Math.min(scaleX, scaleY);
            scaleX = uniform;
            scaleY = uniform;
            const spareX = markerWidth - viewWidth * uniform;
            const spareY = markerHeight - viewHeight * uniform;
            offsetX = preserve.includes("xMax")
              ? spareX
              : preserve.includes("xMid")
                ? spareX / 2
                : 0;
            offsetY = preserve.includes("YMax")
              ? spareY
              : preserve.includes("YMid")
                ? spareY / 2
                : 0;
          }
          const mapMarker = (candidate) =>
            point(
              (candidate.x - viewX) * scaleX + offsetX,
              (candidate.y - viewY) * scaleY + offsetY,
            );
          const mappedReference = mapMarker(point(refX, refY));
          const localEndpoint =
            position === "start"
              ? edge.localPoints[0]
              : edge.localPoints.at(-1);
          const screenEndpoint =
            position === "start"
              ? edge.screenPoints[0]
              : edge.screenPoints.at(-1);
          const adjacent =
            position === "start"
              ? edge.localPoints[1]
              : edge.localPoints.at(-2);
          let angle =
            position === "start"
              ? Math.atan2(
                  adjacent.y - localEndpoint.y,
                  adjacent.x - localEndpoint.x,
                )
              : Math.atan2(
                  localEndpoint.y - adjacent.y,
                  localEndpoint.x - adjacent.x,
                );
          const orient = marker.getAttribute("orient") || "0";
          if (orient === "auto-start-reverse" && position === "start")
            angle += Math.PI;
          else if (orient !== "auto" && orient !== "auto-start-reverse") {
            const numeric = Number.parseFloat(orient);
            if (Number.isFinite(numeric)) angle = (numeric * Math.PI) / 180;
          }
          const markerUnitScale =
            marker.getAttribute("markerUnits") === "userSpaceOnUse"
              ? 1
              : Number.parseFloat(
                  getComputedStyle(edge.element).strokeWidth || "1",
                );
          const cosine = Math.cos(angle);
          const sine = Math.sin(angle);
          const markerCorners = [
            point(childBox.left, childBox.top),
            point(childBox.right, childBox.top),
            point(childBox.right, childBox.bottom),
            point(childBox.left, childBox.bottom),
          ].map((candidate) => {
            const mapped = mapMarker(candidate);
            const x = (mapped.x - mappedReference.x) * markerUnitScale;
            const y = (mapped.y - mappedReference.y) * markerUnitScale;
            const rotated = point(x * cosine - y * sine, x * sine + y * cosine);
            return point(
              screenEndpoint.x +
                edge.matrix.a * rotated.x +
                edge.matrix.c * rotated.y,
              screenEndpoint.y +
                edge.matrix.b * rotated.x +
                edge.matrix.d * rotated.y,
            );
          });
          const bounds = rectFromPoints(markerCorners);
          markerMeasurements.push({
            edge_id: edge.id,
            marker_id: reference,
            position,
            bbox_px: bounds ? plainRect(bounds) : null,
          });
          if (!bounds) continue;
          const page = pageById.get(edge.pageId) || pages[0];
          if (page && rectOutside(bounds, page.rect))
            addIssue(
              "MARKER_PAGE_CLIP",
              [edge.id],
              "rendered marker crosses its Page boundary",
              {
                marker: reference,
                position,
                page_id: page.id,
              },
            );
          const panel = ownerPanel(edge.pageId, edge.panelId);
          if (panel && rectOutside(bounds, panel.rect))
            addIssue(
              "MARKER_PANEL_CLIP",
              [edge.id],
              "rendered marker crosses its Panel boundary",
              {
                marker: reference,
                position,
                panel_id: panel.id,
              },
            );
        }
      }

      const semanticLeafElements = [
        ...svg.querySelectorAll(
          "[data-figure-object-id]:is(text,rect,polygon,circle,ellipse,path,polyline,line,image,use), text.panel-label",
        ),
      ].filter((element) => !element.closest("defs"));
      const occupancy = pages.map((page) => {
        const boxes = [];
        for (const element of semanticLeafElements) {
          if (pageIdFor(element) !== page.id) continue;
          const kind =
            element.tagName.toLowerCase() === "text" ? "text" : "shape";
          const state = renderedState(element, kind);
          if (state.hidden || state.transparent) continue;
          const rect = plainRect(element.getBoundingClientRect());
          if (rect.width <= cfg.epsilon || rect.height <= cfg.epsilon) continue;
          const clipped = intersectRect(rect, page.rect);
          if (clipped) boxes.push(clipped);
        }
        for (const marker of markerMeasurements) {
          const edge = edges.find((item) => item.id === marker.edge_id);
          if (edge?.pageId === page.id && marker.bbox_px) {
            const clipped = intersectRect(marker.bbox_px, page.rect);
            if (clipped) boxes.push(clipped);
          }
        }
        const content = unionRects(boxes);
        const pageArea = page.rect.width * page.rect.height;
        const ratio =
          content && pageArea > cfg.epsilon
            ? (content.width * content.height) / pageArea
            : 0;
        if (ratio < cfg.minimumPageOccupancy)
          addIssue(
            "PAGE_OCCUPANCY_LOW",
            [page.id],
            "Page bbox occupancy is below the strict minimum",
            {
              occupancy: round(ratio),
            },
          );
        if (ratio > cfg.maximumPageOccupancy)
          addIssue(
            "PAGE_OCCUPANCY_HIGH",
            [page.id],
            "Page bbox occupancy is above the strict maximum",
            {
              occupancy: round(ratio),
            },
          );
        return {
          page_id: page.id,
          page_bbox_px: page.rect,
          content_bbox_px: content ? plainRect(content) : null,
          bbox_occupancy: round(ratio),
        };
      });

      for (const message of measurementErrors)
        addIssue("ORACLE_MEASUREMENT_ERROR", [], message);
      const issueCounts = {};
      for (const issue of issues)
        issueCounts[issue.code] = (issueCounts[issue.code] || 0) + 1;
      const visibleTexts = texts.filter(
        (item) => !item.hidden && !item.transparent && !item.zeroSize,
      );
      const publicText = (item) => ({
        id: item.id,
        role: item.role,
        page_id: item.pageId,
        panel_id: item.panelId,
        text: item.text,
        characters: item.characters,
        bbox_px: item.bbox,
        bbox_mm: item.bboxMm,
        local_bbox: item.localBBox,
        computed_text_length: item.computedTextLength,
        natural_text_length: item.naturalTextLength,
        screen_advance_px: item.screenAdvancePx,
        effective_font_pt: item.effectiveFontPt,
        horizontal_ctm_scale: item.horizontalCtmScale,
        vertical_ctm_scale: item.verticalCtmScale,
        transform_shape: item.transformShape,
        orthogonality_error: item.orthogonalityError,
        glyph_advance_scale: item.glyphAdvanceScale,
        rotation_degrees: item.rotationDegrees,
        screen_ctm: item.screenCtm,
        relative_ctm: item.relativeCtm,
        font_family: item.fontFamily,
        font_primary: item.fontPrimary,
        font_set_check: item.fontSetCheck,
        fallback_detected: item.fallbackDetected,
        effective_opacity: item.effectiveOpacity,
        hidden: item.hidden,
        transparent: item.transparent,
        zero_size: item.zeroSize,
      });
      return {
        source: {
          loaded_from_persisted_file: location.protocol === "file:",
          url: location.href,
          metadata_consulted: false,
          producer_claims_ignored: ignoredProducerClaims,
        },
        root: {
          bbox_px: rootRect,
          bbox_mm: rectMm(rootRect),
          width_attribute: svg.getAttribute("width"),
          height_attribute: svg.getAttribute("height"),
          view_box: svg.getAttribute("viewBox"),
        },
        font_set_status: document.fonts?.status || "unsupported",
        pages: pages.map((item) => ({ id: item.id, bbox_px: item.rect })),
        panels: panels.map((item) => ({
          id: item.id,
          page_id: item.pageId,
          bbox_px: item.rect,
        })),
        texts: texts.map(publicText),
        shapes: shapes.map((item) => ({
          id: item.id,
          component_id: item.componentId,
          page_id: item.pageId,
          panel_id: item.panelId,
          primitive: item.primitive,
          tensor_face: item.tensorFace,
          bbox_px: item.bbox,
          hidden: item.state.hidden,
          transparent: item.state.transparent,
          zero_size: item.zeroSize,
        })),
        edges: edges.map((item) => ({
          id: item.id,
          page_id: item.pageId,
          panel_id: item.panelId,
          bbox_px: item.bbox,
          flattened_point_count: item.screenPoints.length,
          flattened_points_px: item.screenPoints.map((value) => ({
            x: round(value.x),
            y: round(value.y),
          })),
        })),
        markers: markerMeasurements,
        strokes: strokes.map((item) => ({
          id: item.id,
          page_id: item.pageId,
          panel_id: item.panelId,
          primitive: item.primitive,
          computed_stroke_user_units: item.computedStrokeUserUnits,
          effective_stroke_pt: item.effectiveStrokePt,
          effective_stroke_maximum_pt: item.effectiveStrokeMaximumPt,
          ctm_minimum_scale: item.ctmMinimumScale,
          ctm_maximum_scale: item.ctmMaximumScale,
          non_scaling_stroke: item.nonScaling,
          screen_ctm: item.screenCtm,
        })),
        occupancy,
        summary: {
          page_count: pages.length,
          panel_count: panels.length,
          text_count: texts.length,
          visible_text_count: visibleTexts.length,
          shape_component_count: shapes.length,
          edge_count: edges.length,
          marker_count: markerMeasurements.length,
          stroke_count: strokes.length,
          maximum_text_characters: texts.length
            ? Math.max(...texts.map((item) => item.characters))
            : 0,
          minimum_font_pt: visibleTexts.length
            ? round(
                Math.min(...visibleTexts.map((item) => item.effectiveFontPt)),
              )
            : null,
          minimum_stroke_pt: strokes.length
            ? round(Math.min(...strokes.map((item) => item.effectiveStrokePt)))
            : null,
          maximum_stroke_pt: strokes.length
            ? round(
                Math.max(
                  ...strokes.map((item) => item.effectiveStrokeMaximumPt),
                ),
              )
            : null,
          minimum_horizontal_ctm_scale: visibleTexts.length
            ? round(
                Math.min(
                  ...visibleTexts.map((item) => item.horizontalCtmScale),
                ),
              )
            : null,
          minimum_vertical_ctm_scale: visibleTexts.length
            ? round(
                Math.min(...visibleTexts.map((item) => item.verticalCtmScale)),
              )
            : null,
          minimum_transform_shape: visibleTexts.length
            ? round(
                Math.min(...visibleTexts.map((item) => item.transformShape)),
              )
            : null,
          fallback_text_count: texts.filter((item) => item.fallbackDetected)
            .length,
          hidden_text_count: texts.filter((item) => item.hidden).length,
          transparent_text_count: texts.filter((item) => item.transparent)
            .length,
          zero_size_text_count: texts.filter((item) => item.zeroSize).length,
          issue_count: issues.length,
        },
        issue_counts: issueCounts,
        issues,
        passed: issues.length === 0,
      };
    }, CONFIG);

    measured.file = absolute;
    measured.sha256 = sha256(absolute);
    measured.browser_errors = browserErrors;
    if (browserErrors.length) {
      for (const message of browserErrors) {
        measured.issues.push({
          code: "BROWSER_RUNTIME_ERROR",
          objects: [],
          message,
          details: {},
        });
        measured.issue_counts.BROWSER_RUNTIME_ERROR =
          (measured.issue_counts.BROWSER_RUNTIME_ERROR || 0) + 1;
      }
      measured.summary.issue_count = measured.issues.length;
      measured.passed = false;
    }
    reports.push(measured);
    await context.close();
  }
} finally {
  await browser.close();
}

const documentReport = {
  schema_version: "nndv-figure-svg-oracle-report-1",
  oracle: ORACLE_NAME,
  browser: { executable: executablePath, version: browserVersion },
  measurement_contract: {
    final_dom_only: true,
    metadata_trusted: false,
    python_proof_imported: false,
    data_scale_claims_trusted: false,
    stroke_under_full_ctm: true,
    path_flattener: path.basename(flattenerPath),
    tolerance: CONFIG,
  },
  reports,
  summary: {
    files: reports.length,
    passed: reports.filter((item) => item.passed).length,
    failed: reports.filter((item) => !item.passed).length,
    issues: reports.reduce((total, item) => total + item.issues.length, 0),
  },
  passed: reports.every((item) => item.passed),
};
const serialized = `${JSON.stringify(documentReport, null, 2)}\n`;
if (args.output) fs.writeFileSync(path.resolve(args.output), serialized);
process.stdout.write(serialized);
if (!args.allowFailures && !documentReport.passed) process.exitCode = 1;
