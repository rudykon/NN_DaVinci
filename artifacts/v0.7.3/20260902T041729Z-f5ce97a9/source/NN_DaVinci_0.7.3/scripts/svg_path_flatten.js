/* Screen-space SVG path flattening. No NN_DaVinci layout code is imported. */
(function installSvgPathFlattener(scope) {
  "use strict";
  const commandToken = /^[A-Za-z]$/;
  const tokenPattern = /[AaCcHhLlMmQqSsTtVvZz]|[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?/g;
  const distance = (a, b) => Math.hypot(a.x - b.x, a.y - b.y);
  const orientation = (a, b, c) =>
    (b.x - a.x) * (c.y - a.y) - (b.y - a.y) * (c.x - a.x);
  const pointLineDistance = (point, start, end, epsilon) => {
    const chord = distance(start, end);
    return chord <= epsilon
      ? distance(point, start)
      : Math.abs(orientation(start, end, point)) / chord;
  };
  const controlHullFlatness = (start, first, second, end, epsilon) =>
    Math.max(
      pointLineDistance(first, start, end, epsilon),
      pointLineDistance(second, start, end, epsilon),
    );
  const deCasteljau = (start, first, second, end) => {
    const middle = (a, b) => ({ x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 });
    const p01 = middle(start, first);
    const p12 = middle(first, second);
    const p23 = middle(second, end);
    const p012 = middle(p01, p12);
    const p123 = middle(p12, p23);
    const split = middle(p012, p123);
    return [[start, p01, p012, split], [split, p123, p23, end]];
  };

  scope.nndvFlattenPathData = function flattenPathData(
    pathData,
    matrix,
    tolerance = 0.25,
    epsilon = 1e-9,
  ) {
    const screen = (point) => ({
      x: matrix.a * point.x + matrix.c * point.y + matrix.e,
      y: matrix.b * point.x + matrix.d * point.y + matrix.f,
    });
    const tokens = pathData.match(tokenPattern) || [];
    let cursor = 0;
    let command = null;
    let current = { x: 0, y: 0 };
    let subpath = { x: 0, y: 0 };
    let lastCubic = null;
    let lastQuadratic = null;
    let seenMove = false;
    const points = [];
    const nextNumber = () => {
      if (cursor >= tokens.length || commandToken.test(tokens[cursor]))
        throw new Error(`malformed SVG path near token ${cursor}`);
      const value = Number(tokens[cursor++]);
      if (!Number.isFinite(value)) throw new Error("non-finite SVG path value");
      return value;
    };
    const parametersRemain = () =>
      cursor < tokens.length && !commandToken.test(tokens[cursor]);
    const localPoint = (relative) => {
      const x = nextNumber();
      const y = nextNumber();
      return relative ? { x: current.x + x, y: current.y + y } : { x, y };
    };
    const clearControls = () => {
      lastCubic = null;
      lastQuadratic = null;
    };
    const appendLine = (target) => {
      if (!points.length) points.push(screen(current));
      points.push(screen(target));
      current = target;
      clearControls();
    };
    const appendCubic = (control1, control2, target) => {
      const start = screen(current);
      const end = screen(target);
      if (!points.length) points.push(start);
      const stack = [[start, screen(control1), screen(control2), end, 0]];
      while (stack.length) {
        const [p0, p1, p2, p3, depth] = stack.pop();
        if (
          controlHullFlatness(p0, p1, p2, p3, epsilon) <= tolerance ||
          depth >= 32
        ) {
          points.push(p3);
        } else {
          const [left, right] = deCasteljau(p0, p1, p2, p3);
          stack.push([...right, depth + 1], [...left, depth + 1]);
        }
      }
      current = target;
    };
    const appendQuadratic = (control, target) => {
      const first = {
        x: current.x + (2 * (control.x - current.x)) / 3,
        y: current.y + (2 * (control.y - current.y)) / 3,
      };
      const second = {
        x: target.x + (2 * (control.x - target.x)) / 3,
        y: target.y + (2 * (control.y - target.y)) / 3,
      };
      appendCubic(first, second, target);
    };
    const angleBetween = (ux, uy, vx, vy) =>
      Math.atan2(ux * vy - uy * vx, ux * vx + uy * vy);
    const appendArc = (rxValue, ryValue, rotation, largeArc, sweep, target) => {
      let rx = Math.abs(rxValue);
      let ry = Math.abs(ryValue);
      if (rx <= epsilon || ry <= epsilon) {
        appendLine(target);
        return;
      }
      if (distance(current, target) <= epsilon) {
        current = target;
        clearControls();
        return;
      }
      const phi = (rotation * Math.PI) / 180;
      const cosine = Math.cos(phi);
      const sine = Math.sin(phi);
      const halfX = (current.x - target.x) / 2;
      const halfY = (current.y - target.y) / 2;
      const xPrime = cosine * halfX + sine * halfY;
      const yPrime = -sine * halfX + cosine * halfY;
      const radii = xPrime ** 2 / rx ** 2 + yPrime ** 2 / ry ** 2;
      if (radii > 1) {
        const scale = Math.sqrt(radii);
        rx *= scale;
        ry *= scale;
      }
      const numerator = Math.max(
        0,
        rx ** 2 * ry ** 2 - rx ** 2 * yPrime ** 2 - ry ** 2 * xPrime ** 2,
      );
      const denominator = Math.max(
        epsilon,
        rx ** 2 * yPrime ** 2 + ry ** 2 * xPrime ** 2,
      );
      const coefficient =
        (Boolean(largeArc) === Boolean(sweep) ? -1 : 1) *
        Math.sqrt(numerator / denominator);
      const centerPrimeX = coefficient * ((rx * yPrime) / ry);
      const centerPrimeY = coefficient * (-(ry * xPrime) / rx);
      const center = {
        x: cosine * centerPrimeX - sine * centerPrimeY + (current.x + target.x) / 2,
        y: sine * centerPrimeX + cosine * centerPrimeY + (current.y + target.y) / 2,
      };
      const ux = (xPrime - centerPrimeX) / rx;
      const uy = (yPrime - centerPrimeY) / ry;
      const vx = (-xPrime - centerPrimeX) / rx;
      const vy = (-yPrime - centerPrimeY) / ry;
      const startAngle = angleBetween(1, 0, ux, uy);
      let delta = angleBetween(ux, uy, vx, vy);
      if (!sweep && delta > 0) delta -= 2 * Math.PI;
      if (sweep && delta < 0) delta += 2 * Math.PI;
      const atAngle = (angle) =>
        screen({
          x: center.x + cosine * rx * Math.cos(angle) - sine * ry * Math.sin(angle),
          y: center.y + sine * rx * Math.cos(angle) + cosine * ry * Math.sin(angle),
        });
      if (!points.length) points.push(screen(current));
      // Initial pi/8 sectors prevent a half-turn midpoint lying on its chord.
      const sectors = Math.max(1, Math.ceil(Math.abs(delta) / (Math.PI / 8)));
      for (let index = 0; index < sectors; index += 1) {
        const begin = startAngle + (delta * index) / sectors;
        const end = startAngle + (delta * (index + 1)) / sectors;
        const stack = [[begin, end, atAngle(begin), atAngle(end), 0]];
        while (stack.length) {
          const [a0, a1, p0, p1, depth] = stack.pop();
          const middleAngle = (a0 + a1) / 2;
          const middle = atAngle(middleAngle);
          if (
            pointLineDistance(middle, p0, p1, epsilon) <= tolerance ||
            depth >= 32
          ) {
            points.push(p1);
          } else {
            stack.push([middleAngle, a1, middle, p1, depth + 1]);
            stack.push([a0, middleAngle, p0, middle, depth + 1]);
          }
        }
      }
      current = target;
      clearControls();
    };

    while (cursor < tokens.length) {
      if (commandToken.test(tokens[cursor])) command = tokens[cursor++];
      if (!command) throw new Error("SVG path does not start with a command");
      const relative = command === command.toLowerCase();
      const upper = command.toUpperCase();
      if (upper === "Z") {
        appendLine({ ...subpath });
        command = null;
        continue;
      }
      if (!parametersRemain()) throw new Error(`SVG path command ${command} lacks parameters`);
      if (upper === "M") {
        const target = localPoint(relative);
        if (seenMove) throw new Error("publication edge path contains multiple subpaths");
        seenMove = true;
        current = target;
        subpath = { ...target };
        points.push(screen(target));
        clearControls();
        command = relative ? "l" : "L";
      } else if (upper === "L") appendLine(localPoint(relative));
      else if (upper === "H") {
        const value = nextNumber();
        appendLine({ x: relative ? current.x + value : value, y: current.y });
      } else if (upper === "V") {
        const value = nextNumber();
        appendLine({ x: current.x, y: relative ? current.y + value : value });
      } else if (upper === "C") {
        const control1 = localPoint(relative);
        const control2 = localPoint(relative);
        const target = localPoint(relative);
        appendCubic(control1, control2, target);
        lastCubic = control2;
        lastQuadratic = null;
      } else if (upper === "S") {
        const control1 = lastCubic
          ? { x: 2 * current.x - lastCubic.x, y: 2 * current.y - lastCubic.y }
          : { ...current };
        const control2 = localPoint(relative);
        const target = localPoint(relative);
        appendCubic(control1, control2, target);
        lastCubic = control2;
        lastQuadratic = null;
      } else if (upper === "Q") {
        const control = localPoint(relative);
        const target = localPoint(relative);
        appendQuadratic(control, target);
        lastQuadratic = control;
        lastCubic = null;
      } else if (upper === "T") {
        const control = lastQuadratic
          ? { x: 2 * current.x - lastQuadratic.x, y: 2 * current.y - lastQuadratic.y }
          : { ...current };
        const target = localPoint(relative);
        appendQuadratic(control, target);
        lastQuadratic = control;
        lastCubic = null;
      } else if (upper === "A") {
        const rx = nextNumber();
        const ry = nextNumber();
        const rotation = nextNumber();
        const largeArc = nextNumber();
        const sweep = nextNumber();
        const target = localPoint(relative);
        appendArc(rx, ry, rotation, largeArc, sweep, target);
      } else throw new Error(`unsupported SVG path command ${command}`);
    }
    if (points.length < 2)
      throw new Error("publication edge path has fewer than two points");
    return points;
  };
})(globalThis);
