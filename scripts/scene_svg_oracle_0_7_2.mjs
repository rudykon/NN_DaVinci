#!/usr/bin/env node
/* Independent landed-output oracle for NN_DaVinci Scene publication SVGs. */
import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import process from "node:process";
import { pathToFileURL } from "node:url";
import { chromium } from "playwright-core";

const ORACLE = "scene-publication-svg-chrome-v1";
const LIMITS = Object.freeze({
  minimumFontPt: 7,
  minimumTextScale: 0.98,
  maximumTextScale: 1.02,
  collisionTolerancePx: 0.35,
  boundaryTolerancePx: 0.6,
  maximumLeaderMm: 18,
  maximumStarburstDegree: 6,
  minimumOccupancy: 0.18,
  maximumOccupancy: 0.9,
  maximumFrameAreaRatio: 0.85,
});

function argumentsFor(argv) {
  let inputRoot = null;
  let output = null;
  let allowFailures = false;
  const files = [];
  for (let index = 0; index < argv.length; index += 1) {
    const value = argv[index];
    if (value === "--input-root") inputRoot = argv[++index];
    else if (value === "--output") output = argv[++index];
    else if (value === "--allow-failures") allowFailures = true;
    else if (value === "--help" || value === "-h") {
      process.stdout.write(
        "usage: scene_svg_oracle_0_7_2.mjs [--input-root corpus] [--output report.json] [--allow-failures] [scene.svg ...]\n",
      );
      process.exit(0);
    } else if (value.startsWith("-"))
      throw new Error(`unknown option: ${value}`);
    else files.push(value);
  }
  if (inputRoot) {
    const visit = (directory) => {
      for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
        const candidate = path.join(directory, entry.name);
        if (entry.isDirectory()) visit(candidate);
        else if (entry.isFile() && entry.name === "scene.svg")
          files.push(candidate);
      }
    };
    visit(path.resolve(inputRoot));
  }
  const resolved = [...new Set(files.map((file) => path.resolve(file)))].sort();
  if (!resolved.length)
    throw new Error("no landed scene.svg inputs were found");
  return { files: resolved, output, allowFailures, inputRoot };
}

function digest(file) {
  return crypto
    .createHash("sha256")
    .update(fs.readFileSync(file))
    .digest("hex");
}

const args = argumentsFor(process.argv.slice(2));
const browser = await chromium.launch({
  executablePath: process.env.NNDV_BROWSER || "/usr/bin/google-chrome",
  headless: true,
  args: ["--no-sandbox", "--disable-gpu"],
});
const cases = [];

try {
  for (const file of args.files) {
    const context = await browser.newContext({
      viewport: { width: 1600, height: 1200 },
      deviceScaleFactor: 1,
    });
    await context.route(/https?:\/\//, (route) =>
      route.abort("blockedbyclient"),
    );
    const page = await context.newPage();
    const browserErrors = [];
    page.on("pageerror", (error) => browserErrors.push(error.message));
    page.on("console", (message) => {
      if (message.type() === "error") browserErrors.push(message.text());
    });
    await page.goto(pathToFileURL(file).href, { waitUntil: "load" });
    await page.evaluate(async () => {
      if (document.fonts) await document.fonts.ready;
    });
    const measured = await page.evaluate((limits) => {
      const svg = document.querySelector("svg");
      if (!svg) throw new Error("landed output has no SVG root");
      const round = (value, digits = 6) => Number(value.toFixed(digits));
      const visible = (element) => {
        const style = getComputedStyle(element);
        return (
          style.display !== "none" &&
          style.visibility !== "hidden" &&
          Number(style.opacity || 1) > 0.001
        );
      };
      const rect = (element) => {
        const box = element.getBoundingClientRect();
        return {
          left: box.left,
          top: box.top,
          right: box.right,
          bottom: box.bottom,
          width: box.width,
          height: box.height,
        };
      };
      const landedBBox = (element) => {
        const box = element.getBBox(),
          matrix = element.getScreenCTM();
        if (!matrix) return rect(element);
        const corners = [
            new DOMPoint(box.x, box.y),
            new DOMPoint(box.x + box.width, box.y),
            new DOMPoint(box.x + box.width, box.y + box.height),
            new DOMPoint(box.x, box.y + box.height),
          ].map((candidate) => candidate.matrixTransform(matrix)),
          left = Math.min(...corners.map((candidate) => candidate.x)),
          top = Math.min(...corners.map((candidate) => candidate.y)),
          right = Math.max(...corners.map((candidate) => candidate.x)),
          bottom = Math.max(...corners.map((candidate) => candidate.y));
        return {
          left,
          top,
          right,
          bottom,
          width: right - left,
          height: bottom - top,
        };
      };
      const plainRect = (box) =>
        Object.fromEntries(
          Object.entries(box).map(([key, value]) => [key, round(value)]),
        );
      const intersects = (first, second, tolerance = 0) =>
        Math.min(first.right, second.right) -
          Math.max(first.left, second.left) >
          tolerance &&
        Math.min(first.bottom, second.bottom) -
          Math.max(first.top, second.top) >
          tolerance;
      const outside = (box, boundary) =>
        box.left < boundary.left - limits.boundaryTolerancePx ||
        box.top < boundary.top - limits.boundaryTolerancePx ||
        box.right > boundary.right + limits.boundaryTolerancePx ||
        box.bottom > boundary.bottom + limits.boundaryTolerancePx;
      const union = (boxes) => {
        if (!boxes.length) return null;
        const left = Math.min(...boxes.map((box) => box.left));
        const top = Math.min(...boxes.map((box) => box.top));
        const right = Math.max(...boxes.map((box) => box.right));
        const bottom = Math.max(...boxes.map((box) => box.bottom));
        return {
          left,
          top,
          right,
          bottom,
          width: right - left,
          height: bottom - top,
        };
      };
      const point = (value, matrix) => {
        const transformed = new DOMPoint(value.x, value.y).matrixTransform(
          matrix,
        );
        return { x: transformed.x, y: transformed.y };
      };
      const points = (element) => {
        const matrix = element.getScreenCTM();
        if (!matrix) return [];
        return [...element.points].map((item) => point(item, matrix));
      };
      const orientation = (a, b, c) =>
        (b.x - a.x) * (c.y - a.y) - (b.y - a.y) * (c.x - a.x);
      const properCross = (a, b, c, d) => {
        const abC = orientation(a, b, c),
          abD = orientation(a, b, d),
          cdA = orientation(c, d, a),
          cdB = orientation(c, d, b);
        return abC * abD < -1e-6 && cdA * cdB < -1e-6;
      };
      const pointInPolygon = (candidate, polygon) => {
        let inside = false;
        for (
          let index = 0, previous = polygon.length - 1;
          index < polygon.length;
          previous = index++
        ) {
          const first = polygon[index],
            second = polygon[previous],
            crosses =
              first.y > candidate.y !== second.y > candidate.y &&
              candidate.x <
                ((second.x - first.x) * (candidate.y - first.y)) /
                  (second.y - first.y) +
                  first.x;
          if (crosses) inside = !inside;
        }
        return inside;
      };
      const pointSegmentDistance = (candidate, start, end) => {
        const dx = end.x - start.x,
          dy = end.y - start.y,
          denominator = dx * dx + dy * dy;
        if (!denominator)
          return Math.hypot(candidate.x - start.x, candidate.y - start.y);
        const amount = Math.max(
          0,
          Math.min(
            1,
            ((candidate.x - start.x) * dx + (candidate.y - start.y) * dy) /
              denominator,
          ),
        );
        return Math.hypot(
          candidate.x - (start.x + amount * dx),
          candidate.y - (start.y + amount * dy),
        );
      };
      const pointNearPolygon = (candidate, polygon, tolerance = 3) =>
        pointInPolygon(candidate, polygon) ||
        polygon.some(
          (start, index) =>
            pointSegmentDistance(
              candidate,
              start,
              polygon[(index + 1) % polygon.length],
            ) <= tolerance,
        );
      const segmentIntersectsPolygon = (segment, polygon) => {
        const midpoint = {
          x: (segment.start.x + segment.end.x) / 2,
          y: (segment.start.y + segment.end.y) / 2,
        };
        return (
          pointInPolygon(midpoint, polygon) ||
          polygon.some((start, index) =>
            properCross(
              segment.start,
              segment.end,
              start,
              polygon[(index + 1) % polygon.length],
            ),
          )
        );
      };
      const segmentIntersectsRect = (segment, box) => {
        const polygon = [
          { x: box.left, y: box.top },
          { x: box.right, y: box.top },
          { x: box.right, y: box.bottom },
          { x: box.left, y: box.bottom },
        ];
        return segmentIntersectsPolygon(segment, polygon);
      };
      const endpointIds = (element) => {
        try {
          const value = JSON.parse(element.dataset.endpointObjectIds || "[]");
          return Array.isArray(value) ? value.map(String) : [];
        } catch {
          return [];
        }
      };
      const segments = (elements) =>
        elements.flatMap((element) => {
          const vertices = points(element);
          return vertices.slice(1).map((end, index) => ({
            id: element.id || `${element.dataset.kind}-${index}`,
            objectId: element.dataset.objectId || "",
            endpointIds: endpointIds(element),
            start: vertices[index],
            end,
          }));
        });
      const singularValues = (matrix) => {
        const trace =
            matrix.a * matrix.a +
            matrix.b * matrix.b +
            matrix.c * matrix.c +
            matrix.d * matrix.d,
          determinant = matrix.a * matrix.d - matrix.b * matrix.c,
          root = Math.sqrt(
            Math.max(0, trace * trace - 4 * determinant * determinant),
          );
        return [
          Math.sqrt(Math.max(0, (trace - root) / 2)),
          Math.sqrt(Math.max(0, (trace + root) / 2)),
        ];
      };
      const boundary = rect(svg),
        rootMatrix = svg.getScreenCTM(),
        rootScale = rootMatrix ? singularValues(rootMatrix)[1] : 1,
        pxPerMm = boundary.width / Number(svg.viewBox.baseVal.width || 180),
        labels = [...svg.querySelectorAll('text[data-kind="label"]')].filter(
          visible,
        ),
        faces = [...svg.querySelectorAll('[data-kind="face"]')].filter(visible),
        leaders = [
          ...svg.querySelectorAll('polyline[data-kind="leader"]'),
        ].filter(visible),
        connectors = [
          ...svg.querySelectorAll(
            'polyline[data-kind="polyline"], polyline[data-kind="arrow"]',
          ),
        ].filter(visible),
        arrowRoutes = [
          ...svg.querySelectorAll('polyline[data-kind="arrow"]'),
        ].filter(visible),
        arrowheads = [
          ...svg.querySelectorAll('[data-kind="arrowhead"]'),
        ].filter(visible),
        labelRecords = labels.map((element, index) => ({
          id: element.id || `label-${index}`,
          objectId: element.dataset.objectId || "",
          text: element.textContent.trim(),
          // SVG getBBox supplies the landed glyph geometry; CTM maps that
          // local box into the physical page measured by Chrome.
          rect: landedBBox(element),
          element,
        })),
        faceRecords = faces.map((element, index) => ({
          id: element.id || `face-${index}`,
          objectId: element.dataset.objectId || "",
          rect: rect(element),
          polygon: points(element),
        }));
      const labelLabel = [];
      for (let index = 0; index < labelRecords.length; index += 1)
        for (let other = index + 1; other < labelRecords.length; other += 1)
          if (
            intersects(
              labelRecords[index].rect,
              labelRecords[other].rect,
              limits.collisionTolerancePx,
            )
          )
            labelLabel.push([labelRecords[index].id, labelRecords[other].id]);
      const labelObject = [];
      for (const label of labelRecords)
        for (const face of faceRecords)
          if (intersects(label.rect, face.rect, limits.collisionTolerancePx)) {
            labelObject.push([label.id, face.objectId || face.id]);
            break;
          }
      const clipping = [
        ...labelRecords.map((item) => ({ id: item.id, rect: item.rect })),
        ...faceRecords.map((item) => ({ id: item.id, rect: item.rect })),
        ...leaders.map((element) => ({ id: element.id, rect: rect(element) })),
        ...connectors.map((element) => ({
          id: element.id,
          rect: rect(element),
        })),
      ].filter((item) => outside(item.rect, boundary));
      const fontMeasurements = labelRecords.map((record) => {
        const style = getComputedStyle(record.element),
          matrix = record.element.getScreenCTM(),
          values = matrix ? singularValues(matrix) : [0, 0],
          effectiveFontPt =
            Number.parseFloat(style.fontSize) * values[0] * 0.75,
          scaleRatio = values[1] > 0 ? values[0] / values[1] : 0;
        return {
          id: record.id,
          fontPt: round(effectiveFontPt),
          scaleRatio: round(scaleRatio),
          hasForcedLength:
            record.element.hasAttribute("textLength") ||
            record.element.hasAttribute("lengthAdjust"),
        };
      });
      const leaderSegments = segments(leaders),
        connectorSegments = segments(connectors),
        leaderCrossings = [];
      for (let index = 0; index < leaderSegments.length; index += 1)
        for (let other = index + 1; other < leaderSegments.length; other += 1)
          if (
            leaderSegments[index].objectId !== leaderSegments[other].objectId &&
            properCross(
              leaderSegments[index].start,
              leaderSegments[index].end,
              leaderSegments[other].start,
              leaderSegments[other].end,
            )
          )
            leaderCrossings.push([
              leaderSegments[index].id,
              leaderSegments[other].id,
            ]);
      const connectorEndpointMap = new Map();
      for (const segment of connectorSegments) {
        const values = connectorEndpointMap.get(segment.objectId) || [];
        values.push(segment.start, segment.end);
        connectorEndpointMap.set(segment.objectId, values);
      }
      const connectorEndpoints = new Map(
          [...connectorEndpointMap].map(([objectId, values]) => [
            objectId,
            values.filter(
              (candidate) =>
                values.filter(
                  (other) =>
                    Math.hypot(candidate.x - other.x, candidate.y - other.y) <=
                    2,
                ).length === 1,
            ),
          ]),
        ),
        connectorFace = [],
        leaderFace = [],
        labelConnector = [];
      for (const segment of connectorSegments) {
        for (const face of faceRecords) {
          if (!face.polygon.length) continue;
          if (segment.endpointIds.includes(face.objectId)) continue;
          const isEndpointFace = (
            connectorEndpoints.get(segment.objectId) || []
          ).some((candidate) => pointNearPolygon(candidate, face.polygon));
          if (
            !isEndpointFace &&
            segmentIntersectsPolygon(segment, face.polygon)
          ) {
            connectorFace.push([segment.id, face.objectId || face.id]);
            break;
          }
        }
      }
      for (const segment of leaderSegments) {
        for (const face of faceRecords) {
          if (
            face.objectId !== segment.objectId &&
            face.polygon.length &&
            segmentIntersectsPolygon(segment, face.polygon)
          ) {
            leaderFace.push([segment.id, face.objectId || face.id]);
            break;
          }
        }
      }
      for (const label of labelRecords)
        for (const segment of connectorSegments)
          if (segmentIntersectsRect(segment, label.rect)) {
            labelConnector.push([label.id, segment.id]);
            break;
          }
      const arrowheadObjectIds = new Set(
          arrowheads.map((element) => element.dataset.objectId || ""),
        ),
        missingArrowheads = arrowRoutes
          .map((element) => element.dataset.objectId || "")
          .filter((objectId) => !arrowheadObjectIds.has(objectId));
      const endpoints = connectorSegments.flatMap((segment) => [
          segment.start,
          segment.end,
        ]),
        degrees = endpoints.map(
          (candidate) =>
            endpoints.filter(
              (other) =>
                Math.hypot(candidate.x - other.x, candidate.y - other.y) <= 2,
            ).length,
        ),
        maximumStarburstDegree = degrees.length ? Math.max(...degrees) : 0,
        relevantBoxes = [
          ...faceRecords.map((item) => item.rect),
          ...labelRecords
            .filter((item) => !/^Depth\/?thickness/i.test(item.text))
            .map((item) => item.rect),
        ],
        content = union(relevantBoxes),
        occupancy = content
          ? {
              width: content.width / boundary.width,
              height: content.height / boundary.height,
              maxAxis: Math.max(
                content.width / boundary.width,
                content.height / boundary.height,
              ),
            }
          : { width: 0, height: 0, maxAxis: 0 },
        largestFaceArea = Math.max(
          0,
          ...faceRecords.map((item) => item.rect.width * item.rect.height),
        ),
        contentArea = content ? content.width * content.height : 0,
        largestFaceAreaRatio = contentArea ? largestFaceArea / contentArea : 1,
        maximumLeaderMm = Math.max(
          0,
          ...leaderSegments.map(
            (segment) =>
              Math.hypot(
                segment.start.x - segment.end.x,
                segment.start.y - segment.end.y,
              ) / pxPerMm,
          ),
        ),
        minimumFontPt = Math.min(
          Infinity,
          ...fontMeasurements.map((item) => item.fontPt),
        ),
        minimumScale = Math.min(
          Infinity,
          ...fontMeasurements.map((item) => item.scaleRatio),
        ),
        maximumScale = Math.max(
          0,
          ...fontMeasurements.map((item) => item.scaleRatio),
        ),
        failures = [];
      if (!labels.length) failures.push("no visible publication labels");
      if (labelLabel.length)
        failures.push(`label-label collisions: ${labelLabel.length}`);
      if (labelObject.length)
        failures.push(`label-object collisions: ${labelObject.length}`);
      if (clipping.length)
        failures.push(`clipped visible elements: ${clipping.length}`);
      if (leaderCrossings.length)
        failures.push(`leader crossings: ${leaderCrossings.length}`);
      if (connectorFace.length)
        failures.push(`edge-node collisions: ${connectorFace.length}`);
      if (leaderFace.length)
        failures.push(`leader-object crossings: ${leaderFace.length}`);
      if (labelConnector.length)
        failures.push(`label-edge collisions: ${labelConnector.length}`);
      if (missingArrowheads.length)
        failures.push(`missing arrowheads: ${missingArrowheads.length}`);
      if (maximumLeaderMm > limits.maximumLeaderMm + 0.01)
        failures.push(`leader exceeds ${limits.maximumLeaderMm} mm`);
      if (maximumStarburstDegree > limits.maximumStarburstDegree)
        failures.push(`connector starburst degree ${maximumStarburstDegree}`);
      if (minimumFontPt + 0.01 < limits.minimumFontPt)
        failures.push(`effective font below ${limits.minimumFontPt} pt`);
      if (
        minimumScale < limits.minimumTextScale ||
        maximumScale > limits.maximumTextScale ||
        fontMeasurements.some((item) => item.hasForcedLength)
      )
        failures.push("text scale is not 1.0 within tolerance");
      if (
        occupancy.maxAxis < limits.minimumOccupancy ||
        occupancy.maxAxis > limits.maximumOccupancy
      )
        failures.push(
          `content occupancy ${round(occupancy.maxAxis)} outside threshold`,
        );
      if (
        new Set(faceRecords.map((item) => item.objectId)).size > 2 &&
        largestFaceAreaRatio > limits.maximumFrameAreaRatio
      )
        failures.push(
          `huge frame-like face ratio ${round(largestFaceAreaRatio)}`,
        );
      return {
        status: failures.length ? "FAIL" : "PASS",
        failures,
        counts: {
          labels: labels.length,
          faces: faces.length,
          leaders: leaders.length,
          connectors: connectors.length,
          arrowRoutes: arrowRoutes.length,
          arrowheads: arrowheads.length,
        },
        page: {
          widthPx: round(boundary.width),
          heightPx: round(boundary.height),
          rootScale: round(rootScale),
        },
        collisions: {
          labelLabel,
          labelObject,
          leaderCrossings,
          connectorFace,
          leaderFace,
          labelConnector,
        },
        clipping: clipping.map((item) => item.id),
        text: {
          minimumFontPt: round(minimumFontPt === Infinity ? 0 : minimumFontPt),
          minimumScale: round(minimumScale === Infinity ? 0 : minimumScale),
          maximumScale: round(maximumScale),
          measurements: fontMeasurements,
        },
        leaders: {
          maximumLengthMm: round(maximumLeaderMm),
          maximumStarburstDegree,
        },
        framing: {
          occupancy: Object.fromEntries(
            Object.entries(occupancy).map(([key, value]) => [
              key,
              round(value),
            ]),
          ),
          largestFaceAreaRatio: round(largestFaceAreaRatio),
          contentRect: content ? plainRect(content) : null,
        },
      };
    }, LIMITS);
    measured.file = file;
    measured.sha256 = digest(file);
    measured.browserErrors = browserErrors;
    if (browserErrors.length) {
      measured.status = "FAIL";
      measured.failures.push(
        ...browserErrors.map((error) => `browser: ${error}`),
      );
    }
    cases.push(measured);
    await context.close();
  }
} finally {
  await browser.close();
}

const failures = cases.flatMap((item) =>
    item.failures.map(
      (failure) => `${path.basename(path.dirname(item.file))}: ${failure}`,
    ),
  ),
  report = {
    oracle: ORACLE,
    status: failures.length ? "FAIL" : "PASS",
    limits: LIMITS,
    browser: browser.version(),
    caseCount: cases.length,
    cases,
    failures,
  };
const serialized = `${JSON.stringify(report, null, 2)}\n`;
if (args.output) fs.writeFileSync(path.resolve(args.output), serialized);
process.stdout.write(serialized);
if (failures.length && !args.allowFailures) process.exitCode = 1;
