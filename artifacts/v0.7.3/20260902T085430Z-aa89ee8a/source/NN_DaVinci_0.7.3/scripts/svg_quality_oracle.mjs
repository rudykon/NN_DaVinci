#!/usr/bin/env node
/* Independent final-SVG geometry oracle.
 * Chromium reads serialized SVG plus a separately hashed input-side manifest.
 * This process imports neither Python layout nor quality code.
 */
import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import process from "node:process";
import { fileURLToPath, pathToFileURL } from "node:url";
import { chromium } from "playwright-core";

const TOLERANCE = Object.freeze({
  bboxPx: 0.5,
  safetyGapPx: 1.0,
  fontPt: 0.05,
  occupancy: 0.01,
  endpointRadiusPx: 1.0,
  curveErrorPx: 0.25,
  epsilon: 1e-9,
});
const ALLOWED_ROLES = new Set([
  "publication-root",
  "container",
  "node",
  "group",
  "group-label",
  "annotation",
  "legend",
  "edge",
  "edge-label",
  "marker",
  "required-text",
  "decoration",
]);

function parseArguments(argv) {
  const files = [];
  let output = null;
  let manifest = null;
  let requireMetadata = false;
  let strictRoles = false;
  for (let index = 0; index < argv.length; index += 1) {
    if (argv[index] === "--output") output = argv[++index];
    else if (argv[index] === "--manifest") manifest = argv[++index];
    else if (argv[index] === "--require-metadata") requireMetadata = true;
    else if (argv[index] === "--strict-roles") strictRoles = true;
    else files.push(argv[index]);
  }
  if (!files.length)
    throw new Error(
      "usage: svg_quality_oracle.mjs [--output report.json] [--manifest input.json] " +
        "[--require-metadata] [--strict-roles] file.svg ...",
    );
  if (requireMetadata && !manifest)
    throw new Error("--require-metadata requires --manifest");
  return { files, output, manifest, requireMetadata, strictRoles };
}

function fileSha256(file) {
  return crypto
    .createHash("sha256")
    .update(fs.readFileSync(file))
    .digest("hex");
}

const arguments_ = parseArguments(process.argv.slice(2));
const inputManifest = arguments_.manifest
  ? JSON.parse(fs.readFileSync(path.resolve(arguments_.manifest), "utf8"))
  : null;
const inputManifestSha256 = arguments_.manifest
  ? fileSha256(path.resolve(arguments_.manifest))
  : null;
const executablePath = process.env.NNDV_BROWSER || "/usr/bin/google-chrome";
const pathFlattener = path.join(
  path.dirname(fileURLToPath(import.meta.url)),
  "svg_path_flatten.js",
);
const pathFlattenerSource = fs.readFileSync(pathFlattener, "utf8");
const browser = await chromium.launch({
  executablePath,
  headless: true,
  args: ["--no-sandbox"],
});
const reports = [];

try {
  for (const input of arguments_.files) {
    const absolute = path.resolve(input);
    const fixtureKey = path.basename(absolute, path.extname(absolute));
    const expected =
      inputManifest?.fixtures?.[fixtureKey] ??
      inputManifest?.fixtures?.[path.basename(absolute)] ??
      null;
    const page = await browser.newPage({
      viewport: { width: 2000, height: 1600 },
    });
    await page.goto(pathToFileURL(absolute).href, { waitUntil: "load" });
    await page.evaluate((source) => globalThis.eval(source), pathFlattenerSource);
    await page.evaluate(() => document.fonts?.ready);
    const measured = await page.evaluate(
      ({ tol, requireMetadata, strictRoles, expected, allowedRoles }) => {
        const svg = document.querySelector("svg");
        if (!svg) throw new Error("document does not contain an SVG root");
        const role = (element) => element.getAttribute("data-nndv-role") || "";
        const plain = (rect) => ({
          left: rect.left,
          top: rect.top,
          right: rect.right,
          bottom: rect.bottom,
          width: rect.width,
          height: rect.height,
        });
        const intersects = (first, second, tolerance = 0) =>
          Math.min(first.right, second.right) -
            Math.max(first.left, second.left) >
            tolerance &&
          Math.min(first.bottom, second.bottom) -
            Math.max(first.top, second.top) >
            tolerance;
        const outside = (rect, box) =>
          rect.left < box.left - tol.bboxPx ||
          rect.top < box.top - tol.bboxPx ||
          rect.right > box.right + tol.bboxPx ||
          rect.bottom > box.bottom + tol.bboxPx;
        const distance = (first, second) =>
          Math.hypot(first.x - second.x, first.y - second.y);
        const matrixPoint = (point, matrix) =>
          new DOMPoint(point.x, point.y).matrixTransform(matrix);
        const pointInRect = (point, rect, gap = 0) =>
          point.x >= rect.left - gap &&
          point.x <= rect.right + gap &&
          point.y >= rect.top - gap &&
          point.y <= rect.bottom + gap;
        const orientation = (a, b, c) =>
          (b.x - a.x) * (c.y - a.y) - (b.y - a.y) * (c.x - a.x);
        const pointOnSegment = (a, point, b) =>
          Math.abs(orientation(a, point, b)) <= tol.bboxPx &&
          point.x >= Math.min(a.x, b.x) - tol.bboxPx &&
          point.x <= Math.max(a.x, b.x) + tol.bboxPx &&
          point.y >= Math.min(a.y, b.y) - tol.bboxPx &&
          point.y <= Math.max(a.y, b.y) + tol.bboxPx;
        const segmentsCross = (a, b, c, d) => {
          const o1 = orientation(a, b, c);
          const o2 = orientation(a, b, d);
          const o3 = orientation(c, d, a);
          const o4 = orientation(c, d, b);
          if (
            ((o1 > tol.bboxPx && o2 < -tol.bboxPx) ||
              (o1 < -tol.bboxPx && o2 > tol.bboxPx)) &&
            ((o3 > tol.bboxPx && o4 < -tol.bboxPx) ||
              (o3 < -tol.bboxPx && o4 > tol.bboxPx))
          )
            return true;
          return (
            (Math.abs(o1) <= tol.bboxPx && pointOnSegment(a, c, b)) ||
            (Math.abs(o2) <= tol.bboxPx && pointOnSegment(a, d, b)) ||
            (Math.abs(o3) <= tol.bboxPx && pointOnSegment(c, a, d)) ||
            (Math.abs(o4) <= tol.bboxPx && pointOnSegment(c, b, d))
          );
        };
        const segmentRectInterval = (first, second, rect, gap = 0) => {
          const expanded = {
            left: rect.left - gap,
            right: rect.right + gap,
            top: rect.top - gap,
            bottom: rect.bottom + gap,
          };
          const dx = second.x - first.x;
          const dy = second.y - first.y;
          let low = 0;
          let high = 1;
          for (const [p, q] of [
            [-dx, first.x - expanded.left],
            [dx, expanded.right - first.x],
            [-dy, first.y - expanded.top],
            [dy, expanded.bottom - first.y],
          ]) {
            if (Math.abs(p) <= tol.epsilon) {
              if (q < 0) return null;
              continue;
            }
            const ratio = q / p;
            if (p < 0) low = Math.max(low, ratio);
            else high = Math.min(high, ratio);
            if (low > high) return null;
          }
          return [low, high];
        };
        const root = plain(svg.getBoundingClientRect());
        const margin = Number(svg.dataset.pageMargin || 0);
        const pageBox = {
          left: root.left + margin,
          top: root.top + margin,
          right: root.right - margin,
          bottom: root.bottom - margin,
        };
        const contentElement = svg.querySelector(".architecture-content");
        const content = plain((contentElement || svg).getBoundingClientRect());
        const clipping = [];
        if (content.left < pageBox.left - tol.bboxPx) clipping.push("left");
        if (content.top < pageBox.top - tol.bboxPx) clipping.push("top");
        if (content.right > pageBox.right + tol.bboxPx) clipping.push("right");
        if (content.bottom > pageBox.bottom + tol.bboxPx)
          clipping.push("bottom");

        const graphicalSelector =
          "g,path,rect,text,circle,ellipse,line,polygon,polyline,image,use";
        const graphics = [...svg.querySelectorAll(graphicalSelector)].filter(
          (element) => !element.closest("defs"),
        );
        const unknownRoles = strictRoles
          ? graphics
              .filter((element) => !allowedRoles.includes(role(element)))
              .map(
                (element) =>
                  `${element.tagName.toLowerCase()}#${element.id || "-"}:${role(element) || "missing"}`,
              )
          : [];
        if (strictRoles && svg.dataset.publicationLayer !== "true")
          unknownRoles.push("svg:not-publication-layer");

        const nodes = [
          ...svg.querySelectorAll('g.node[data-nndv-role="node"]'),
        ].map((group) => {
          const body = group.querySelector(
            ':scope > rect.node-body[data-nndv-role="node"]',
          );
          return {
            id: group.dataset.nodeId,
            rect: plain(body.getBoundingClientRect()),
          };
        });
        const nodeOverlaps = [];
        for (let index = 0; index < nodes.length; index += 1)
          for (let other = index + 1; other < nodes.length; other += 1)
            if (intersects(nodes[index].rect, nodes[other].rect, tol.bboxPx))
              nodeOverlaps.push([nodes[index].id, nodes[other].id]);

        const texts = [...svg.querySelectorAll("text")].map(
          (element, index) => {
            const matrix = element.getScreenCTM();
            const a = matrix?.a ?? 1;
            const b = matrix?.b ?? 0;
            const c = matrix?.c ?? 0;
            const d = matrix?.d ?? 1;
            const sx = Math.hypot(a, b);
            const sy = Math.hypot(c, d);
            const trace = a * a + b * b + c * c + d * d;
            const determinant = a * d - b * c;
            const discriminant = Math.sqrt(
              Math.max(0, trace * trace - 4 * determinant * determinant),
            );
            const sigmaMax = Math.sqrt(Math.max(0, (trace + discriminant) / 2));
            const sigmaMin = Math.sqrt(Math.max(0, (trace - discriminant) / 2));
            const ctmHorizontal = sy <= tol.epsilon ? 0 : Math.min(1, sx / sy);
            const transformShape =
              sigmaMax <= tol.epsilon ? 0 : sigmaMin / sigmaMax;
            const actualAdvance = element.getComputedTextLength();
            const clone = element.cloneNode(true);
            clone.removeAttribute("textLength");
            clone.removeAttribute("lengthAdjust");
            clone.removeAttribute("transform");
            clone.removeAttribute("font-stretch");
            clone.style.setProperty("font-stretch", "normal", "important");
            clone.style.setProperty("transform", "none", "important");
            clone.style.setProperty("visibility", "hidden", "important");
            element.parentNode.appendChild(clone);
            const referenceAdvance = clone.getComputedTextLength();
            clone.remove();
            const glyphAdvance =
              referenceAdvance > tol.epsilon
                ? Math.min(1, actualAdvance / referenceAdvance)
                : 1;
            const effectiveHorizontal = Math.min(ctmHorizontal, glyphAdvance);
            const computedPx = Number.parseFloat(
              getComputedStyle(element).fontSize,
            );
            const finalPt = computedPx * sy * 0.75;
            const rect = plain(element.getBoundingClientRect());
            const owner = element.closest("g.node");
            const ownerBody = owner?.querySelector(":scope > rect.node-body");
            const overflow = ownerBody
              ? outside(rect, plain(ownerBody.getBoundingClientRect()))
              : false;
            const localBox = element.getBBox();
            const quad = matrix
              ? [
                  matrixPoint({ x: localBox.x, y: localBox.y }, matrix),
                  matrixPoint(
                    { x: localBox.x + localBox.width, y: localBox.y },
                    matrix,
                  ),
                  matrixPoint(
                    {
                      x: localBox.x + localBox.width,
                      y: localBox.y + localBox.height,
                    },
                    matrix,
                  ),
                  matrixPoint(
                    { x: localBox.x, y: localBox.y + localBox.height },
                    matrix,
                  ),
                ]
              : [];
            const quadBounds = quad.length
              ? {
                  left: Math.min(...quad.map((point) => point.x)),
                  right: Math.max(...quad.map((point) => point.x)),
                  top: Math.min(...quad.map((point) => point.y)),
                  bottom: Math.max(...quad.map((point) => point.y)),
                }
              : rect;
            const quadRectDelta = Math.max(
              Math.abs(quadBounds.left - rect.left),
              Math.abs(quadBounds.right - rect.right),
              Math.abs(quadBounds.top - rect.top),
              Math.abs(quadBounds.bottom - rect.bottom),
            );
            return {
              id: `${owner?.dataset.nodeId || "document"}:${element.dataset.labelRole || role(element) || index}`,
              role: role(element),
              required:
                role(element) === "required-text" ||
                element.dataset.required === "true",
              text: element.textContent,
              reference_advance: referenceAdvance,
              actual_advance: actualAdvance,
              natural_width: referenceAdvance * sy,
              actual_width: actualAdvance * sx,
              ctm_horizontal: ctmHorizontal,
              glyph_advance: glyphAdvance,
              horizontal_scale: effectiveHorizontal,
              transform_shape: transformShape,
              final_font_pt: finalPt,
              singular: sy <= tol.epsilon || sigmaMin <= tol.epsilon,
              overflow,
              quad_rect_delta: quadRectDelta,
              rect,
            };
          },
        );

        const flatten = (element) => {
          const matrix = element.getScreenCTM();
          if (!matrix || typeof globalThis.nndvFlattenPathData !== "function")
            throw new Error("independent SVG path flattener is unavailable");
          return globalThis.nndvFlattenPathData(
            element.getAttribute("d") || "",
            {
              a: matrix.a,
              b: matrix.b,
              c: matrix.c,
              d: matrix.d,
              e: matrix.e,
              f: matrix.f,
            },
            tol.curveErrorPx,
            tol.epsilon,
          );
        };

        const edges = [
          ...svg.querySelectorAll('g.edge[data-nndv-role="edge"]'),
        ].map((group) => {
          const element = group.querySelector(
            ':scope > path[data-nndv-role="edge"]',
          );
          return {
            id: group.dataset.edgeId || group.id.replace(/^edge-/, ""),
            source: group.dataset.source,
            target: group.dataset.target,
            element,
            points: flatten(element),
          };
        });
        const edgeNode = [];
        const endpointErrors = [];
        for (const edge of edges) {
          for (const node of nodes) {
            let hit = false;
            for (let index = 1; index < edge.points.length; index += 1) {
              const first = edge.points[index - 1];
              const second = edge.points[index];
              const interval = segmentRectInterval(
                first,
                second,
                node.rect,
                tol.safetyGapPx,
              );
              if (!interval) continue;
              const enter = {
                x: first.x + (second.x - first.x) * interval[0],
                y: first.y + (second.y - first.y) * interval[0],
              };
              const exit = {
                x: first.x + (second.x - first.x) * interval[1],
                y: first.y + (second.y - first.y) * interval[1],
              };
              const sourcePort =
                node.id === edge.source &&
                index === 1 &&
                Math.max(
                  distance(enter, edge.points[0]),
                  distance(exit, edge.points[0]),
                ) <=
                  tol.endpointRadiusPx + tol.safetyGapPx;
              const targetPort =
                node.id === edge.target &&
                index === edge.points.length - 1 &&
                Math.max(
                  distance(enter, edge.points.at(-1)),
                  distance(exit, edge.points.at(-1)),
                ) <=
                  tol.endpointRadiusPx + tol.safetyGapPx;
              if (!sourcePort && !targetPort) {
                hit = true;
                break;
              }
            }
            if (hit) edgeNode.push([edge.id, node.id]);
          }
          for (const [kind, nodeId, point] of [
            ["source", edge.source, edge.points[0]],
            ["target", edge.target, edge.points.at(-1)],
          ]) {
            const node = nodes.find((candidate) => candidate.id === nodeId);
            if (!node) continue;
            const boundaryDistance = Math.min(
              Math.abs(point.x - node.rect.left),
              Math.abs(point.x - node.rect.right),
              Math.abs(point.y - node.rect.top),
              Math.abs(point.y - node.rect.bottom),
            );
            if (
              !pointInRect(point, node.rect, tol.bboxPx) ||
              boundaryDistance > tol.bboxPx
            )
              endpointErrors.push(`${edge.id}:${kind}`);
          }
        }

        const allCrossings = [];
        for (let index = 0; index < edges.length; index += 1)
          for (let other = index + 1; other < edges.length; other += 1) {
            const first = edges[index];
            const second = edges[other];
            if (
              [first.source, first.target].some(
                (id) => id === second.source || id === second.target,
              )
            )
              continue;
            let found = false;
            for (
              let firstIndex = 1;
              firstIndex < first.points.length && !found;
              firstIndex += 1
            )
              for (
                let secondIndex = 1;
                secondIndex < second.points.length;
                secondIndex += 1
              )
                if (
                  segmentsCross(
                    first.points[firstIndex - 1],
                    first.points[firstIndex],
                    second.points[secondIndex - 1],
                    second.points[secondIndex],
                  )
                ) {
                  found = true;
                  break;
                }
            if (found) allCrossings.push([first.id, second.id].sort());
          }
        const declaredCrossings = expected?.exceptions?.crossings || [];
        const edgeIds = new Set(edges.map((edge) => edge.id));
        const exceptionErrors = [];
        const explained = new Set();
        for (const item of declaredCrossings) {
          if (
            !Array.isArray(item.edges) ||
            item.edges.length !== 2 ||
            !item.reason
          ) {
            exceptionErrors.push("malformed crossing exception");
            continue;
          }
          if (!item.edges.every((id) => edgeIds.has(id))) {
            exceptionErrors.push(
              `unknown crossing exception edge: ${item.edges.join(",")}`,
            );
            continue;
          }
          explained.add([...item.edges].sort().join("\u0000"));
        }
        const edgeCrossings = allCrossings.filter(
          (pair) => !explained.has(pair.join("\u0000")),
        );

        const markerNodeCollisions = [];
        for (const edge of edges) {
          const markerReference = edge.element.getAttribute("marker-end");
          const match = markerReference?.match(/#([^\)]+)/);
          if (!match || edge.points.length < 2) continue;
          const marker = svg.querySelector(`marker#${CSS.escape(match[1])}`);
          const markerPath = marker?.querySelector("path");
          if (!marker || !markerPath) continue;
          const viewBox = (
            marker.getAttribute("viewBox") ||
            `0 0 ${marker.getAttribute("markerWidth") || 3} ${marker.getAttribute("markerHeight") || 3}`
          )
            .trim()
            .split(/[ ,]+/)
            .map(Number);
          const [viewX, viewY, viewWidth, viewHeight] = viewBox;
          const markerWidth = Number(marker.getAttribute("markerWidth") || 3);
          const markerHeight = Number(marker.getAttribute("markerHeight") || 3);
          const refX = Number(marker.getAttribute("refX") || 0);
          const refY = Number(marker.getAttribute("refY") || 0);
          const strokeScale =
            marker.getAttribute("markerUnits") === "userSpaceOnUse"
              ? 1
              : Number.parseFloat(getComputedStyle(edge.element).strokeWidth) ||
                1;
          const scaleX = (markerWidth / viewWidth) * strokeScale;
          const scaleY = (markerHeight / viewHeight) * strokeScale;
          const end = edge.points.at(-1);
          const previous = edge.points.at(-2);
          const angle = Math.atan2(end.y - previous.y, end.x - previous.x);
          const cosine = Math.cos(angle);
          const sine = Math.sin(angle);
          const total = markerPath.getTotalLength();
          const polygon = [];
          for (let index = 0; index <= 16; index += 1) {
            const local = markerPath.getPointAtLength((total * index) / 16);
            const x = (local.x - refX - viewX) * scaleX;
            const y = (local.y - refY - viewY) * scaleY;
            polygon.push({
              x: end.x + x * cosine - y * sine,
              y: end.y + x * sine + y * cosine,
            });
          }
          const polygonBox = {
            left: Math.min(...polygon.map((point) => point.x)),
            right: Math.max(...polygon.map((point) => point.x)),
            top: Math.min(...polygon.map((point) => point.y)),
            bottom: Math.max(...polygon.map((point) => point.y)),
          };
          for (const node of nodes) {
            if (
              node.id === edge.source ||
              node.id === edge.target ||
              !intersects(polygonBox, node.rect, 0)
            )
              continue;
            if (polygon.some((point) => pointInRect(point, node.rect)))
              markerNodeCollisions.push([edge.id, node.id]);
          }
        }

        const groupLabelConflicts = [];
        const edgeLabelConflicts = [];
        for (const element of svg.querySelectorAll(
          '[data-nndv-role="group-label"]',
        )) {
          const box = plain(element.getBoundingClientRect());
          for (const node of nodes)
            if (intersects(box, node.rect, tol.bboxPx))
              groupLabelConflicts.push([element.textContent, node.id]);
        }
        for (const element of svg.querySelectorAll(
          '[data-nndv-role="edge-label"] text,[data-nndv-role="edge-label"]:not(g)',
        )) {
          const box = plain(element.getBoundingClientRect());
          for (const node of nodes)
            if (intersects(box, node.rect, tol.bboxPx))
              edgeLabelConflicts.push([element.textContent, node.id]);
        }
        const annotations = [
          ...svg.querySelectorAll(
            'g[data-nndv-role="annotation"][data-annotation-id]',
          ),
        ].map((element) => ({
          id: element.dataset.annotationId,
          rect: plain(element.getBoundingClientRect()),
        }));
        const legends = [
          ...svg.querySelectorAll('g.legend[data-nndv-role="legend"]'),
        ].map((element, index) => ({
          id: `legend-${index}`,
          rect: plain(element.getBoundingClientRect()),
        }));
        const annotationNodeCollisions = annotations.flatMap((annotation) =>
          nodes
            .filter((node) =>
              intersects(annotation.rect, node.rect, tol.bboxPx),
            )
            .map((node) => [annotation.id, node.id]),
        );
        const legendNodeCollisions = legends.flatMap((legend) =>
          nodes
            .filter((node) => intersects(legend.rect, node.rect, tol.bboxPx))
            .map((node) => [legend.id, node.id]),
        );
        const titles = [...svg.querySelectorAll("text.diagram-title")].map(
          (element, index) => ({
            id: `title-${index}`,
            rect: plain(element.getBoundingClientRect()),
          }),
        );
        const groupLabels = [
          ...svg.querySelectorAll('[data-nndv-role="group-label"]'),
        ].map((element, index) => ({
          id: `group-label-${index}`,
          rect: plain(element.getBoundingClientRect()),
        }));
        const titleNodeCollisions = titles.flatMap((title) =>
          nodes
            .filter((node) => intersects(title.rect, node.rect, tol.bboxPx))
            .map((node) => [title.id, node.id]),
        );
        const titleLegendCollisions = titles.flatMap((title) =>
          legends
            .filter((legend) => intersects(title.rect, legend.rect, tol.bboxPx))
            .map((legend) => [title.id, legend.id]),
        );
        const titleGroupLabelCollisions = titles.flatMap((title) =>
          groupLabels
            .filter((label) => intersects(title.rect, label.rect, tol.bboxPx))
            .map((label) => [title.id, label.id]),
        );
        const annotationPageViolations = annotations
          .filter((item) => outside(item.rect, pageBox))
          .map((item) => item.id);
        const legendPageViolations = legends
          .filter((item) => outside(item.rect, pageBox))
          .map((item) => item.id);
        const textPageViolations = texts
          .filter(
            (item) =>
              ["annotation", "legend", "required-text"].includes(item.role) &&
              outside(item.rect, pageBox),
          )
          .map((item) => item.id);

        const availableWidth = Math.max(1, root.width - 2 * margin);
        const availableHeight = Math.max(1, root.height - 2 * margin);
        const occupancy =
          (content.width * content.height) / (availableWidth * availableHeight);
        let metadata = null;
        let metadataParseError = null;
        try {
          metadata = JSON.parse(
            svg.querySelector("metadata")?.textContent || "null",
          );
        } catch (error) {
          metadataParseError = String(error);
        }
        const metadataErrors = [];
        if (requireMetadata) {
          if (!metadata)
            metadataErrors.push(
              metadataParseError
                ? `malformed metadata: ${metadataParseError}`
                : "missing metadata",
            );
          if (!expected)
            metadataErrors.push("input-side fixture manifest entry is missing");
          if (metadata?.schema_version !== "nndv-publication-svg-metadata-1")
            metadataErrors.push("metadata schema_version mismatch");
          if (metadata?.metrics_version !== "chrome-final-svg-v2")
            metadataErrors.push("metadata metrics_version mismatch");
          for (const key of [
            "fixture_id",
            "input_sha256",
            "run_id",
            "node_count",
            "edge_count",
          ])
            if (metadata?.identity?.[key] !== expected?.[key])
              metadataErrors.push(`metadata identity ${key} mismatch`);
          if (
            metadata?.node_count !== nodes.length ||
            metadata?.edge_count !== edges.length
          )
            metadataErrors.push("metadata DOM node/edge count mismatch");
        }
        const required = texts.filter((item) => item.required);
        const minimumFont = required.length
          ? Math.min(...required.map((item) => item.final_font_pt))
          : null;
        const minimumHorizontal = required.length
          ? Math.min(...required.map((item) => item.horizontal_scale))
          : null;
        const minimumShape = required.length
          ? Math.min(...required.map((item) => item.transform_shape))
          : null;
        const metadataDelta = metadata?.paper
          ? {
              occupancy: Math.abs(
                occupancy - Number(metadata.paper.content_occupancy),
              ),
              final_font_pt:
                minimumFont === null
                  ? 0
                  : Math.abs(
                      minimumFont - Number(metadata.paper.final_body_font_pt),
                    ),
              content_width_px: Math.abs(
                content.width -
                  Number(metadata.paper.content_width) *
                    Number(svg.dataset.diagramScale || 1),
              ),
              content_height_px: Math.abs(
                content.height -
                  Number(metadata.paper.content_height) *
                    Number(svg.dataset.diagramScale || 1),
              ),
              node_overlap_count: Math.abs(
                nodeOverlaps.length -
                  Number(metadata.paper.node_overlap_count || 0),
              ),
              clipping_state: Number(
                Boolean(clipping.length) !== Boolean(metadata.paper.cropped),
              ),
            }
          : null;
        if (requireMetadata && !metadataDelta)
          metadataErrors.push("paper metadata is absent");
        if (
          metadataDelta &&
          (metadataDelta.occupancy > tol.occupancy ||
            metadataDelta.final_font_pt > tol.fontPt ||
            metadataDelta.content_width_px > tol.bboxPx ||
            metadataDelta.content_height_px > tol.bboxPx ||
            metadataDelta.node_overlap_count !== 0 ||
            metadataDelta.clipping_state !== 0)
        )
          metadataErrors.push(
            "independent geometry differs from metadata beyond fixed tolerance",
          );
        return {
          tolerance: tol,
          root,
          content,
          occupancy,
          clipping,
          node_count: nodes.length,
          edge_count: edges.length,
          node_overlaps: nodeOverlaps,
          required_texts: required,
          minimum_font_pt: minimumFont,
          minimum_horizontal_scale: minimumHorizontal,
          minimum_transform_shape: minimumShape,
          singular_text_transforms: required
            .filter((item) => item.singular)
            .map((item) => item.id),
          text_overflows: texts
            .filter((item) => item.overflow)
            .map((item) => item.id),
          text_page_violations: textPageViolations,
          edge_node_collisions: edgeNode,
          edge_crossings: edgeCrossings,
          all_edge_crossings: allCrossings,
          endpoint_errors: endpointErrors,
          marker_node_collisions: markerNodeCollisions,
          group_label_conflicts: groupLabelConflicts,
          edge_label_conflicts: edgeLabelConflicts,
          annotation_node_collisions: annotationNodeCollisions,
          legend_node_collisions: legendNodeCollisions,
          title_node_collisions: titleNodeCollisions,
          title_legend_collisions: titleLegendCollisions,
          title_group_label_collisions: titleGroupLabelCollisions,
          annotation_page_violations: annotationPageViolations,
          legend_page_violations: legendPageViolations,
          unknown_roles: unknownRoles,
          exception_errors: exceptionErrors,
          metadata_errors: metadataErrors,
          metadata_delta: metadataDelta,
        };
      },
      {
        tol: TOLERANCE,
        requireMetadata: arguments_.requireMetadata,
        strictRoles: arguments_.strictRoles,
        expected,
        allowedRoles: [...ALLOWED_ROLES],
      },
    );
    measured.file = absolute;
    measured.sha256 = fileSha256(absolute);
    measured.fixture_manifest = expected;
    const arrayBlockers = [
      "clipping",
      "node_overlaps",
      "singular_text_transforms",
      "text_overflows",
      "text_page_violations",
      "edge_node_collisions",
      "edge_crossings",
      "endpoint_errors",
      "marker_node_collisions",
      "group_label_conflicts",
      "edge_label_conflicts",
      "annotation_node_collisions",
      "legend_node_collisions",
      "title_node_collisions",
      "title_legend_collisions",
      "title_group_label_collisions",
      "annotation_page_violations",
      "legend_page_violations",
      "unknown_roles",
      "exception_errors",
      "metadata_errors",
    ];
    measured.passed =
      arrayBlockers.every((key) => measured[key].length === 0) &&
      (measured.minimum_font_pt === null ||
        measured.minimum_font_pt + TOLERANCE.fontPt >= 7) &&
      (measured.minimum_horizontal_scale === null ||
        measured.minimum_horizontal_scale + TOLERANCE.epsilon >= 1) &&
      (measured.minimum_transform_shape === null ||
        measured.minimum_transform_shape + TOLERANCE.epsilon >= 1);
    reports.push(measured);
    await page.close();
  }
} finally {
  await browser.close();
}

const reportDocument = {
  schema_version: "2.0.2",
  oracle: "chrome-final-svg-v2",
  browser: executablePath,
  strict_roles: arguments_.strictRoles,
  require_metadata: arguments_.requireMetadata,
  input_manifest: arguments_.manifest
    ? path.resolve(arguments_.manifest)
    : null,
  input_manifest_sha256: inputManifestSha256,
  tolerance: TOLERANCE,
  reports,
};
const serialized = `${JSON.stringify(reportDocument, null, 2)}\n`;
if (arguments_.output) fs.writeFileSync(arguments_.output, serialized);
process.stdout.write(serialized);
process.exitCode = reports.every((report) => report.passed) ? 0 : 1;
