(function initializeSceneRenderer(global) {
  "use strict";

  const DEG = Math.PI / 180;
  const EPSILON = 1e-7;

  const vec3 = {
    add: (a, b) => [a[0] + b[0], a[1] + b[1], a[2] + b[2]],
    subtract: (a, b) => [a[0] - b[0], a[1] - b[1], a[2] - b[2]],
    scale: (a, value) => [a[0] * value, a[1] * value, a[2] * value],
    dot: (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2],
    cross: (a, b) => [
      a[1] * b[2] - a[2] * b[1],
      a[2] * b[0] - a[0] * b[2],
      a[0] * b[1] - a[1] * b[0],
    ],
    length: (a) => Math.hypot(a[0], a[1], a[2]),
    normalize(a) {
      const length = vec3.length(a) || 1;
      return [a[0] / length, a[1] / length, a[2] / length];
    },
  };

  function mat4Identity() {
    return new Float32Array([1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]);
  }

  function mat4Multiply(a, b) {
    const out = new Float32Array(16);
    for (let column = 0; column < 4; column += 1) {
      for (let row = 0; row < 4; row += 1) {
        let value = 0;
        for (let index = 0; index < 4; index += 1)
          value += a[index * 4 + row] * b[column * 4 + index];
        out[column * 4 + row] = value;
      }
    }
    return out;
  }

  function mat4Translation(value) {
    const out = mat4Identity();
    out[12] = value[0];
    out[13] = value[1];
    out[14] = value[2];
    return out;
  }

  function mat4Scale(value) {
    const out = mat4Identity();
    out[0] = value[0];
    out[5] = value[1];
    out[10] = value[2];
    return out;
  }

  function mat4Rotation(rotation) {
    const [x, y, z] = rotation.map((value) => Number(value || 0) * DEG);
    const sx = Math.sin(x),
      cx = Math.cos(x),
      sy = Math.sin(y),
      cy = Math.cos(y),
      sz = Math.sin(z),
      cz = Math.cos(z);
    const rx = new Float32Array([
      1,
      0,
      0,
      0,
      0,
      cx,
      sx,
      0,
      0,
      -sx,
      cx,
      0,
      0,
      0,
      0,
      1,
    ]);
    const ry = new Float32Array([
      cy,
      0,
      -sy,
      0,
      0,
      1,
      0,
      0,
      sy,
      0,
      cy,
      0,
      0,
      0,
      0,
      1,
    ]);
    const rz = new Float32Array([
      cz,
      sz,
      0,
      0,
      -sz,
      cz,
      0,
      0,
      0,
      1,
      0,
      0,
      0,
      0,
      0,
      1,
    ]);
    return mat4Multiply(rz, mat4Multiply(ry, rx));
  }

  function mat4FromTransform(transform = {}, geometry = {}) {
    const position = transform.position || [0, 0, 0];
    const rotation = transform.rotation || [0, 0, 0];
    const sourceScale = transform.scale || [1, 1, 1];
    const dimensions = geometry.dimensions || geometry.size || [1, 1, 1];
    const dimensionScale = Array.isArray(dimensions)
      ? dimensions
      : [dimensions.width || 1, dimensions.height || 1, dimensions.depth || 1];
    const scale = [0, 1, 2].map(
      (index) =>
        Number(sourceScale[index] ?? 1) * Number(dimensionScale[index] ?? 1),
    );
    return mat4Multiply(
      mat4Translation(position.map(Number)),
      mat4Multiply(mat4Rotation(rotation), mat4Scale(scale)),
    );
  }

  function mat4LookAt(eye, target, up) {
    const z = vec3.normalize(vec3.subtract(eye, target));
    const x = vec3.normalize(vec3.cross(up, z));
    const y = vec3.cross(z, x);
    return new Float32Array([
      x[0],
      y[0],
      z[0],
      0,
      x[1],
      y[1],
      z[1],
      0,
      x[2],
      y[2],
      z[2],
      0,
      -vec3.dot(x, eye),
      -vec3.dot(y, eye),
      -vec3.dot(z, eye),
      1,
    ]);
  }

  function mat4Perspective(fov, aspect, near, far) {
    const f = 1 / Math.tan(fov / 2),
      range = 1 / (near - far);
    return new Float32Array([
      f / aspect,
      0,
      0,
      0,
      0,
      f,
      0,
      0,
      0,
      0,
      (far + near) * range,
      -1,
      0,
      0,
      2 * far * near * range,
      0,
    ]);
  }

  function mat4Orthographic(height, aspect, near, far) {
    const width = height * aspect,
      left = -width / 2,
      right = width / 2,
      bottom = -height / 2,
      top = height / 2;
    return new Float32Array([
      2 / (right - left),
      0,
      0,
      0,
      0,
      2 / (top - bottom),
      0,
      0,
      0,
      0,
      -2 / (far - near),
      0,
      -(right + left) / (right - left),
      -(top + bottom) / (top - bottom),
      -(far + near) / (far - near),
      1,
    ]);
  }

  function mat4Invert(matrix) {
    const m = matrix;
    const out = new Float32Array(16);
    const b00 = m[0] * m[5] - m[1] * m[4];
    const b01 = m[0] * m[6] - m[2] * m[4];
    const b02 = m[0] * m[7] - m[3] * m[4];
    const b03 = m[1] * m[6] - m[2] * m[5];
    const b04 = m[1] * m[7] - m[3] * m[5];
    const b05 = m[2] * m[7] - m[3] * m[6];
    const b06 = m[8] * m[13] - m[9] * m[12];
    const b07 = m[8] * m[14] - m[10] * m[12];
    const b08 = m[8] * m[15] - m[11] * m[12];
    const b09 = m[9] * m[14] - m[10] * m[13];
    const b10 = m[9] * m[15] - m[11] * m[13];
    const b11 = m[10] * m[15] - m[11] * m[14];
    let determinant =
      b00 * b11 - b01 * b10 + b02 * b09 + b03 * b08 - b04 * b07 + b05 * b06;
    if (!determinant) return null;
    determinant = 1 / determinant;
    out[0] = (m[5] * b11 - m[6] * b10 + m[7] * b09) * determinant;
    out[1] = (-m[1] * b11 + m[2] * b10 - m[3] * b09) * determinant;
    out[2] = (m[13] * b05 - m[14] * b04 + m[15] * b03) * determinant;
    out[3] = (-m[9] * b05 + m[10] * b04 - m[11] * b03) * determinant;
    out[4] = (-m[4] * b11 + m[6] * b08 - m[7] * b07) * determinant;
    out[5] = (m[0] * b11 - m[2] * b08 + m[3] * b07) * determinant;
    out[6] = (-m[12] * b05 + m[14] * b02 - m[15] * b01) * determinant;
    out[7] = (m[8] * b05 - m[10] * b02 + m[11] * b01) * determinant;
    out[8] = (m[4] * b10 - m[5] * b08 + m[7] * b06) * determinant;
    out[9] = (-m[0] * b10 + m[1] * b08 - m[3] * b06) * determinant;
    out[10] = (m[12] * b04 - m[13] * b02 + m[15] * b00) * determinant;
    out[11] = (-m[8] * b04 + m[9] * b02 - m[11] * b00) * determinant;
    out[12] = (-m[4] * b09 + m[5] * b07 - m[6] * b06) * determinant;
    out[13] = (m[0] * b09 - m[1] * b07 + m[2] * b06) * determinant;
    out[14] = (-m[12] * b03 + m[13] * b01 - m[14] * b00) * determinant;
    out[15] = (m[8] * b03 - m[9] * b01 + m[10] * b00) * determinant;
    return out;
  }

  function transformPoint(matrix, point, w = 1) {
    const result = [
      matrix[0] * point[0] +
        matrix[4] * point[1] +
        matrix[8] * point[2] +
        matrix[12] * w,
      matrix[1] * point[0] +
        matrix[5] * point[1] +
        matrix[9] * point[2] +
        matrix[13] * w,
      matrix[2] * point[0] +
        matrix[6] * point[1] +
        matrix[10] * point[2] +
        matrix[14] * w,
      matrix[3] * point[0] +
        matrix[7] * point[1] +
        matrix[11] * point[2] +
        matrix[15] * w,
    ];
    if (Math.abs(result[3]) > EPSILON && w !== 0)
      return result.slice(0, 3).map((value) => value / result[3]);
    return result.slice(0, 3);
  }

  function color(value, fallback = [0.24, 0.43, 0.88, 1]) {
    if (Array.isArray(value)) {
      const normalized = value.slice(0, 4).map(Number);
      while (normalized.length < 4) normalized.push(1);
      return normalized.map((item, index) =>
        index < 3 && item > 1 ? item / 255 : item,
      );
    }
    if (typeof value !== "string") return fallback;
    const raw = value.trim().replace(/^#/, "");
    if (/^[0-9a-f]{3}$/i.test(raw))
      return [...raw].map((item) => parseInt(item + item, 16) / 255).concat(1);
    if (/^[0-9a-f]{6}([0-9a-f]{2})?$/i.test(raw)) {
      const values = raw.match(/.{2}/g).map((item) => parseInt(item, 16) / 255);
      return values.length === 3 ? values.concat(1) : values;
    }
    return fallback;
  }

  function flattenObjects(scene) {
    if (!scene) return [];
    if (Array.isArray(scene.objects)) return scene.objects;
    return (scene.layers || []).flatMap((layer) => {
      if (layer.visible === false) return [];
      return (layer.objects || []).map((object) => {
        Object.defineProperty(object, "_layer", {
          value: layer,
          configurable: true,
          writable: true,
          enumerable: false,
        });
        return object;
      });
    });
  }

  function cubeMesh() {
    const positions = [],
      normals = [];
    const faces = [
      [
        [1, 0, 0],
        [
          [0.5, -0.5, -0.5],
          [0.5, 0.5, -0.5],
          [0.5, 0.5, 0.5],
          [0.5, -0.5, 0.5],
        ],
      ],
      [
        [-1, 0, 0],
        [
          [-0.5, -0.5, 0.5],
          [-0.5, 0.5, 0.5],
          [-0.5, 0.5, -0.5],
          [-0.5, -0.5, -0.5],
        ],
      ],
      [
        [0, 1, 0],
        [
          [-0.5, 0.5, -0.5],
          [-0.5, 0.5, 0.5],
          [0.5, 0.5, 0.5],
          [0.5, 0.5, -0.5],
        ],
      ],
      [
        [0, -1, 0],
        [
          [-0.5, -0.5, 0.5],
          [-0.5, -0.5, -0.5],
          [0.5, -0.5, -0.5],
          [0.5, -0.5, 0.5],
        ],
      ],
      [
        [0, 0, 1],
        [
          [-0.5, -0.5, 0.5],
          [0.5, -0.5, 0.5],
          [0.5, 0.5, 0.5],
          [-0.5, 0.5, 0.5],
        ],
      ],
      [
        [0, 0, -1],
        [
          [0.5, -0.5, -0.5],
          [-0.5, -0.5, -0.5],
          [-0.5, 0.5, -0.5],
          [0.5, 0.5, -0.5],
        ],
      ],
    ];
    for (const [normal, vertices] of faces) {
      for (const index of [0, 1, 2, 0, 2, 3]) {
        positions.push(...vertices[index]);
        normals.push(...normal);
      }
    }
    return { positions, normals };
  }

  function sphereMesh(segments = 16, rings = 10) {
    const positions = [],
      normals = [];
    for (let ring = 0; ring < rings; ring += 1) {
      const v0 = ring / rings,
        v1 = (ring + 1) / rings;
      for (let segment = 0; segment < segments; segment += 1) {
        const u0 = segment / segments,
          u1 = (segment + 1) / segments;
        const point = (u, v) => {
          const phi = v * Math.PI,
            theta = u * Math.PI * 2;
          return [
            Math.sin(phi) * Math.cos(theta) * 0.5,
            Math.cos(phi) * 0.5,
            Math.sin(phi) * Math.sin(theta) * 0.5,
          ];
        };
        const points = [
          point(u0, v0),
          point(u0, v1),
          point(u1, v1),
          point(u1, v0),
        ];
        for (const index of [0, 1, 2, 0, 2, 3]) {
          positions.push(...points[index]);
          normals.push(...vec3.normalize(points[index]));
        }
      }
    }
    return { positions, normals };
  }

  function cylinderMesh(segments = 20) {
    const positions = [],
      normals = [];
    for (let segment = 0; segment < segments; segment += 1) {
      const a = (segment / segments) * Math.PI * 2,
        b = ((segment + 1) / segments) * Math.PI * 2,
        points = [
          [Math.cos(a) * 0.5, -0.5, Math.sin(a) * 0.5],
          [Math.cos(a) * 0.5, 0.5, Math.sin(a) * 0.5],
          [Math.cos(b) * 0.5, 0.5, Math.sin(b) * 0.5],
          [Math.cos(b) * 0.5, -0.5, Math.sin(b) * 0.5],
        ];
      for (const index of [0, 1, 2, 0, 2, 3]) {
        positions.push(...points[index]);
        normals.push(points[index][0] * 2, 0, points[index][2] * 2);
      }
      for (const side of [-1, 1]) {
        const center = [0, side * 0.5, 0],
          left = side > 0 ? points[1] : points[0],
          right = side > 0 ? points[2] : points[3];
        const triangle =
          side > 0 ? [center, right, left] : [center, left, right];
        for (const point of triangle) {
          positions.push(...point);
          normals.push(0, side, 0);
        }
      }
    }
    return { positions, normals };
  }

  function coneMesh(segments = 20) {
    const positions = [],
      normals = [],
      tip = [0, 0.5, 0],
      baseY = -0.5;
    for (let segment = 0; segment < segments; segment += 1) {
      const a = (segment / segments) * Math.PI * 2,
        b = ((segment + 1) / segments) * Math.PI * 2,
        left = [Math.cos(a) * 0.5, baseY, Math.sin(a) * 0.5],
        right = [Math.cos(b) * 0.5, baseY, Math.sin(b) * 0.5],
        sideNormal = vec3.normalize([
          Math.cos((a + b) / 2),
          0.5,
          Math.sin((a + b) / 2),
        ]);
      for (const point of [left, right, tip]) {
        positions.push(...point);
        normals.push(...sideNormal);
      }
      for (const point of [[0, baseY, 0], right, left]) {
        positions.push(...point);
        normals.push(0, -1, 0);
      }
    }
    return { positions, normals };
  }

  function routePoints(object) {
    const raw = object?.geometry?.points;
    if (!Array.isArray(raw) || raw.length < 2) return [];
    const transform = mat4FromTransform(object.transform, {
      dimensions: [1, 1, 1],
    });
    const points = raw
      .filter(
        (point) =>
          Array.isArray(point) &&
          point.length === 3 &&
          point.every((value) => Number.isFinite(Number(value))),
      )
      .map((point) => transformPoint(transform, point.map(Number)));
    if (
      String(object.kind).toLowerCase() !== "bezier-route" ||
      points.length !== 4
    )
      return points;
    const [start, first, second, end] = points,
      sampled = [];
    for (let index = 0; index <= 32; index += 1) {
      const t = index / 32,
        inverse = 1 - t;
      sampled.push(
        [0, 1, 2].map(
          (axis) =>
            inverse ** 3 * start[axis] +
            3 * inverse ** 2 * t * first[axis] +
            3 * inverse * t ** 2 * second[axis] +
            t ** 3 * end[axis],
        ),
      );
    }
    return sampled;
  }

  function segmentMatrix(start, end, radius) {
    const delta = vec3.subtract(end, start),
      length = vec3.length(delta);
    if (length < EPSILON) return null;
    const y = vec3.scale(delta, 1 / length),
      reference = Math.abs(y[1]) < 0.98 ? [0, 1, 0] : [1, 0, 0],
      x = vec3.normalize(vec3.cross(reference, y)),
      z = vec3.normalize(vec3.cross(y, x)),
      midpoint = vec3.scale(vec3.add(start, end), 0.5),
      thickness = Math.max(0.012, Number(radius) || 0.07);
    return new Float32Array([
      x[0] * thickness,
      x[1] * thickness,
      x[2] * thickness,
      0,
      y[0] * length,
      y[1] * length,
      y[2] * length,
      0,
      z[0] * thickness,
      z[1] * thickness,
      z[2] * thickness,
      0,
      midpoint[0],
      midpoint[1],
      midpoint[2],
      1,
    ]);
  }

  function objectCenter(object) {
    const points = routePoints(object);
    if (points.length)
      return [0, 1, 2].map(
        (axis) =>
          points.reduce((total, point) => total + point[axis], 0) /
          points.length,
      );
    return (object.transform?.position || [0, 0, 0]).map(Number);
  }

  function shader(gl, type, source) {
    const instance = gl.createShader(type);
    gl.shaderSource(instance, source);
    gl.compileShader(instance);
    if (!gl.getShaderParameter(instance, gl.COMPILE_STATUS)) {
      const message = gl.getShaderInfoLog(instance);
      gl.deleteShader(instance);
      throw new Error(`Scene shader compilation failed: ${message}`);
    }
    return instance;
  }

  function program(gl) {
    const vertex = shader(
      gl,
      gl.VERTEX_SHADER,
      `#version 300 es
      precision highp float;
      layout(location=0) in vec3 position;
      layout(location=1) in vec3 normal;
      uniform mat4 model;
      uniform mat4 viewProjection;
      out vec3 worldNormal;
      void main() {
        worldNormal = normalize(mat3(model) * normal);
        gl_Position = viewProjection * model * vec4(position, 1.0);
      }`,
    );
    const fragment = shader(
      gl,
      gl.FRAGMENT_SHADER,
      `#version 300 es
      precision highp float;
      in vec3 worldNormal;
      uniform vec4 baseColor;
      uniform bool selected;
      uniform bool unlit;
      out vec4 outputColor;
      void main() {
        float diffuse = unlit ? 1.0 : 0.34 + 0.66 * max(dot(normalize(worldNormal), normalize(vec3(0.45, 0.8, 0.35))), 0.0);
        vec3 value = baseColor.rgb * diffuse;
        if (selected) value = mix(value, vec3(1.0, 0.68, 0.1), 0.48);
        outputColor = vec4(value, baseColor.a);
      }`,
    );
    const instance = gl.createProgram();
    gl.attachShader(instance, vertex);
    gl.attachShader(instance, fragment);
    gl.linkProgram(instance);
    gl.deleteShader(vertex);
    gl.deleteShader(fragment);
    if (!gl.getProgramParameter(instance, gl.LINK_STATUS))
      throw new Error(
        `Scene shader link failed: ${gl.getProgramInfoLog(instance)}`,
      );
    return instance;
  }

  class SceneRenderer extends global.EventTarget {
    constructor(canvas, options = {}) {
      super();
      if (!canvas) throw new Error("SceneRenderer requires a canvas");
      this.canvas = canvas;
      this.fallbackElement = options.fallbackElement || null;
      this.labelElement = options.labelElement || null;
      this.scene = null;
      this.objects = [];
      this.camera = null;
      this.selection = new Set();
      this.contentDensity = "paper";
      this.mode = "webgl2";
      this.disposed = false;
      this.framePending = false;
      this.resizeObserver = null;
      this.gl = canvas.getContext("webgl2", {
        antialias: true,
        alpha: false,
        depth: true,
        preserveDrawingBuffer: false,
      });
      if (!this.gl) {
        this.mode = "cpu-svg";
        this.requestFallback("WebGL2 is unavailable");
        return;
      }
      try {
        this.initializeGl();
      } catch (error) {
        this.mode = "cpu-svg";
        this.requestFallback(error.message);
        return;
      }
      this.onContextLost = (event) => {
        event.preventDefault();
        this.mode = "cpu-svg";
        this.requestFallback("WebGL2 context was lost");
      };
      this.onContextRestored = () => {
        this.gl = canvas.getContext("webgl2");
        this.initializeGl();
        this.mode = "webgl2";
        this.hideCpuFallback();
        this.render();
      };
      canvas.addEventListener("webglcontextlost", this.onContextLost);
      canvas.addEventListener("webglcontextrestored", this.onContextRestored);
      if (global.ResizeObserver) {
        this.resizeObserver = new global.ResizeObserver(() => this.resize());
        this.resizeObserver.observe(canvas.parentElement || canvas);
      } else global.addEventListener("resize", () => this.resize());
      this.resize();
    }

    initializeGl() {
      const gl = this.gl;
      this.program = program(gl);
      this.locations = {
        model: gl.getUniformLocation(this.program, "model"),
        viewProjection: gl.getUniformLocation(this.program, "viewProjection"),
        baseColor: gl.getUniformLocation(this.program, "baseColor"),
        selected: gl.getUniformLocation(this.program, "selected"),
        unlit: gl.getUniformLocation(this.program, "unlit"),
      };
      this.meshes = new Map();
      this.createMesh("box", cubeMesh());
      this.createMesh("sphere", sphereMesh());
      this.createMesh("cylinder", cylinderMesh());
      this.createMesh("cone", coneMesh());
      gl.enable(gl.DEPTH_TEST);
      gl.depthFunc(gl.LEQUAL);
      gl.enable(gl.BLEND);
      gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);
      gl.enable(gl.CULL_FACE);
      gl.cullFace(gl.BACK);
    }

    createMesh(name, data) {
      const gl = this.gl,
        vertexArray = gl.createVertexArray(),
        positionBuffer = gl.createBuffer(),
        normalBuffer = gl.createBuffer();
      gl.bindVertexArray(vertexArray);
      gl.bindBuffer(gl.ARRAY_BUFFER, positionBuffer);
      gl.bufferData(
        gl.ARRAY_BUFFER,
        new Float32Array(data.positions),
        gl.STATIC_DRAW,
      );
      gl.enableVertexAttribArray(0);
      gl.vertexAttribPointer(0, 3, gl.FLOAT, false, 0, 0);
      gl.bindBuffer(gl.ARRAY_BUFFER, normalBuffer);
      gl.bufferData(
        gl.ARRAY_BUFFER,
        new Float32Array(data.normals),
        gl.STATIC_DRAW,
      );
      gl.enableVertexAttribArray(1);
      gl.vertexAttribPointer(1, 3, gl.FLOAT, false, 0, 0);
      gl.bindVertexArray(null);
      this.meshes.set(name, {
        vertexArray,
        buffers: [positionBuffer, normalBuffer],
        count: data.positions.length / 3,
      });
    }

    requestFallback(reason) {
      emit(this, "fallbackrequired", { reason, mode: "cpu-svg" });
    }

    showCpuFallback(svg, reason = "CPU SVG projection") {
      this.mode = "cpu-svg";
      this.canvas.hidden = true;
      if (this.labelElement) {
        this.labelElement.hidden = true;
        this.labelElement.replaceChildren();
      }
      if (this.fallbackElement) {
        this.fallbackElement.hidden = false;
        this.fallbackElement.innerHTML = svg || "";
        this.fallbackElement.dataset.reason = reason;
      }
      emit(this, "modechange", { mode: this.mode, reason });
    }

    hideCpuFallback() {
      this.canvas.hidden = false;
      if (this.labelElement) this.labelElement.hidden = false;
      if (this.fallbackElement) {
        this.fallbackElement.hidden = true;
        this.fallbackElement.replaceChildren();
      }
      emit(this, "modechange", { mode: this.mode });
    }

    setScene(scene, cameraId) {
      this.scene = scene || null;
      this.contentDensity = ["compact", "paper", "detailed"].includes(
        scene?.metadata?.content_density,
      )
        ? scene.metadata.content_density
        : this.contentDensity;
      this.objects = flattenObjects(scene);
      const cameras = scene?.cameras || [];
      const selected =
        cameras.find(
          (item) => item.id === (cameraId || scene?.active_camera_id),
        ) || cameras[0];
      this.camera = this.normalizeCamera(selected);
      this.selection = new Set(scene?.selection_ids || []);
      this.render();
    }

    setContentDensity(density = "paper") {
      this.contentDensity = ["compact", "paper", "detailed"].includes(density)
        ? density
        : "paper";
      if (this.scene) {
        this.scene.metadata = this.scene.metadata || {};
        this.scene.metadata.content_density = this.contentDensity;
      }
      this.updateLabels();
    }

    normalizeCamera(camera = {}) {
      const position = (camera.position || [8, 6, 10]).map(Number);
      const target = (camera.target || [0, 0, 0]).map(Number);
      return {
        id: camera.id || "camera-main",
        projection:
          camera.projection === "orthographic" ? "orthographic" : "perspective",
        position,
        target,
        up: (camera.up || [0, 1, 0]).map(Number),
        fov_y_deg: Number(camera.fov_y_deg || camera.fov || 45),
        ortho_height: Number(camera.ortho_height || 12),
        near: Math.max(0.001, Number(camera.near || 0.01)),
        far: Math.max(1, Number(camera.far || 10000)),
        locked: !!camera.locked,
      };
    }

    setCamera(camera) {
      this.camera = this.normalizeCamera({ ...this.camera, ...camera });
      this.render();
    }

    getCameraState() {
      return this.camera ? JSON.parse(JSON.stringify(this.camera)) : null;
    }

    setProjection(projection) {
      if (!this.camera) return;
      this.camera.projection =
        projection === "orthographic" ? "orthographic" : "perspective";
      this.render();
    }

    setViewPreset(name) {
      if (!this.camera) return;
      const distance = Math.max(
        1,
        vec3.length(vec3.subtract(this.camera.position, this.camera.target)),
      );
      const directions = {
        front: [0, 0, 1],
        back: [0, 0, -1],
        left: [-1, 0, 0],
        right: [1, 0, 0],
        top: [0, 1, 0.001],
        bottom: [0, -1, 0.001],
        isometric: [1, 0.82, 1],
      };
      const direction = vec3.normalize(
        directions[name] || directions.isometric,
      );
      this.camera.position = vec3.add(
        this.camera.target,
        vec3.scale(direction, distance),
      );
      this.camera.up =
        name === "top" || name === "bottom" ? [0, 0, -1] : [0, 1, 0];
      this.render();
    }

    setSelection(ids) {
      this.selection = new Set(ids || []);
      this.render();
    }

    resize() {
      if (!this.gl || this.disposed) return;
      const rect = this.canvas.getBoundingClientRect();
      const ratio = Math.min(2, global.devicePixelRatio || 1);
      const width = Math.max(1, Math.round(rect.width * ratio));
      const height = Math.max(1, Math.round(rect.height * ratio));
      if (this.canvas.width !== width || this.canvas.height !== height) {
        this.canvas.width = width;
        this.canvas.height = height;
      }
      this.render();
    }

    cameraMatrices() {
      const camera = this.camera || this.normalizeCamera();
      const aspect = Math.max(
        0.01,
        this.canvas.width / Math.max(1, this.canvas.height),
      );
      const view = mat4LookAt(camera.position, camera.target, camera.up);
      const projection =
        camera.projection === "orthographic"
          ? mat4Orthographic(
              camera.ortho_height,
              aspect,
              camera.near,
              camera.far,
            )
          : mat4Perspective(
              camera.fov_y_deg * DEG,
              aspect,
              camera.near,
              camera.far,
            );
      return {
        view,
        projection,
        viewProjection: mat4Multiply(projection, view),
      };
    }

    render() {
      if (
        !this.gl ||
        this.mode !== "webgl2" ||
        this.disposed ||
        this.framePending
      )
        return;
      this.framePending = true;
      global.requestAnimationFrame(() => {
        this.framePending = false;
        this.draw();
      });
    }

    draw() {
      const gl = this.gl;
      if (!gl || this.mode !== "webgl2") return;
      const paperTheme =
          global.document?.documentElement?.dataset?.appTheme === "paper",
        background = color(
          paperTheme
            ? "#f8f6ef"
            : this.scene?.world?.background || this.scene?.metadata?.background,
          paperTheme ? [0.973, 0.965, 0.937, 1] : [0.055, 0.071, 0.105, 1],
        );
      gl.viewport(0, 0, this.canvas.width, this.canvas.height);
      gl.clearColor(background[0], background[1], background[2], 1);
      gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
      gl.useProgram(this.program);
      gl.uniformMatrix4fv(
        this.locations.viewProjection,
        false,
        this.cameraMatrices().viewProjection,
      );
      const opaque = [],
        transparent = [];
      for (const object of this.objects) {
        if (object.visible === false || object._layer?.visible === false)
          continue;
        const opacity = Number(object.material?.opacity ?? 1);
        (opacity < 1 ? transparent : opaque).push(object);
      }
      const cameraPosition = this.camera?.position || [0, 0, 0];
      transparent.sort((a, b) => {
        const ap = objectCenter(a),
          bp = objectCenter(b);
        return (
          vec3.length(vec3.subtract(bp, cameraPosition)) -
          vec3.length(vec3.subtract(ap, cameraPosition))
        );
      });
      for (const object of opaque.concat(transparent)) this.drawObject(object);
      gl.bindVertexArray(null);
      this.updateLabels();
    }

    drawObject(object) {
      const points = routePoints(object);
      if (points.length >= 2) {
        const radius = Math.max(0.012, Number(object.geometry?.radius) || 0.07);
        for (let index = 1; index < points.length; index += 1) {
          const model = segmentMatrix(points[index - 1], points[index], radius);
          if (model) this.drawMesh(object, this.meshes.get("cylinder"), model);
        }
        const arrowKinds = new Set([
          "arrow",
          "residual-skip",
          "unet-skip",
          "qkv-branch",
          "expert-branch",
        ]);
        if (arrowKinds.has(String(object.kind).toLowerCase())) {
          const end = points.at(-1),
            previous = points.at(-2),
            direction = vec3.normalize(vec3.subtract(end, previous)),
            headLength = Math.min(
              vec3.length(vec3.subtract(end, previous)) * 0.65,
              Math.max(radius * 6, 0.2),
            ),
            base = vec3.subtract(end, vec3.scale(direction, headLength)),
            model = segmentMatrix(base, end, radius * 2.7);
          if (model) this.drawMesh(object, this.meshes.get("cone"), model);
        }
        return;
      }
      const kind = String(
        object.geometry?.primitive ||
          object.geometry?.kind ||
          object.kind ||
          "box",
      ).toLowerCase();
      const mesh = this.meshes.get(
        kind.includes("sphere")
          ? "sphere"
          : kind.includes("cylinder")
            ? "cylinder"
            : "box",
      );
      this.drawMesh(
        object,
        mesh,
        mat4FromTransform(object.transform, object.geometry),
      );
    }

    drawMesh(object, mesh, model) {
      const gl = this.gl;
      const baseColor = color(
        object.material?.base_color || object.material?.color,
      );
      baseColor[3] *= Number(object.material?.opacity ?? 1);
      gl.uniformMatrix4fv(this.locations.model, false, model);
      gl.uniform4fv(this.locations.baseColor, baseColor);
      gl.uniform1i(
        this.locations.selected,
        this.selection.has(object.id) ? 1 : 0,
      );
      gl.uniform1i(this.locations.unlit, object.material?.unlit ? 1 : 0);
      gl.bindVertexArray(mesh.vertexArray);
      gl.drawArrays(gl.TRIANGLES, 0, mesh.count);
    }

    updateLabels() {
      const layer = this.labelElement;
      if (!layer || this.mode !== "webgl2") return;
      const rect = this.canvas.getBoundingClientRect();
      if (!rect.width || !rect.height) return;
      const candidates = this.objects
        .filter(
          (object) =>
            object.visible !== false &&
            object._layer?.visible !== false &&
            String(object.name || "").trim() &&
            routePoints(object).length === 0,
        )
        .sort(
          (left, right) =>
            Number(this.selection.has(right.id)) -
              Number(this.selection.has(left.id)) ||
            String(left.id).localeCompare(String(right.id)),
        )
        .slice(
          0,
          this.contentDensity === "compact"
            ? 10
            : this.contentDensity === "detailed"
              ? 32
              : 18,
        )
        .map((object) => {
          const projected = this.projectPoint(objectCenter(object));
          return {
            object,
            x: projected.x - rect.left,
            y: projected.y - rect.top,
            depth: projected.depth,
          };
        })
        .filter(
          (item) =>
            Number.isFinite(item.x) &&
            Number.isFinite(item.y) &&
            item.depth >= -1 &&
            item.depth <= 1,
        );
      const fragment = document.createDocumentFragment();
      for (const item of candidates) {
        const label = document.createElement("span");
        label.className = "scene-object-label";
        label.textContent = item.object.name;
        label.title = item.object.name;
        label.dataset.sceneObjectId = item.object.id;
        label.dataset.selected = String(this.selection.has(item.object.id));
        label.style.visibility = "hidden";
        item.label = label;
        fragment.append(label);
      }
      layer.replaceChildren(fragment);
      layer.hidden = false;
      const occupied = [],
        margin = 8,
        gap = 5;
      let visible = 0;
      for (const item of candidates) {
        const measured = item.label.getBoundingClientRect(),
          width = Math.min(190, Math.max(28, measured.width)),
          height = Math.max(20, measured.height),
          offsets = [
            [-width / 2, -height - 13],
            [-width / 2, 13],
            [13, -height / 2],
            [-width - 13, -height / 2],
            [13, -height - 13],
            [-width - 13, -height - 13],
            [13, 13],
            [-width - 13, 13],
          ];
        const placement = offsets
          .map(([offsetX, offsetY]) => ({
            left: item.x + offsetX,
            top: item.y + offsetY,
            right: item.x + offsetX + width,
            bottom: item.y + offsetY + height,
          }))
          .find(
            (box) =>
              box.left >= margin &&
              box.top >= margin &&
              box.right <= rect.width - margin &&
              box.bottom <= rect.height - margin &&
              occupied.every(
                (other) =>
                  box.right + gap <= other.left ||
                  box.left >= other.right + gap ||
                  box.bottom + gap <= other.top ||
                  box.top >= other.bottom + gap,
              ),
          );
        if (!placement) {
          item.label.hidden = true;
          continue;
        }
        item.label.style.left = `${placement.left}px`;
        item.label.style.top = `${placement.top}px`;
        item.label.style.visibility = "visible";
        occupied.push(placement);
        visible += 1;
      }
      layer.dataset.candidateLabelCount = String(candidates.length);
      layer.dataset.visibleLabelCount = String(visible);
      layer.dataset.labelOverlapCount = "0";
    }

    screenRay(clientX, clientY) {
      const rect = this.canvas.getBoundingClientRect();
      if (!rect.width || !rect.height) return null;
      const x = ((clientX - rect.left) / rect.width) * 2 - 1;
      const y = 1 - ((clientY - rect.top) / rect.height) * 2;
      const inverse = mat4Invert(this.cameraMatrices().viewProjection);
      if (!inverse) return null;
      const near = transformPoint(inverse, [x, y, -1]);
      const far = transformPoint(inverse, [x, y, 1]);
      return {
        origin: near,
        direction: vec3.normalize(vec3.subtract(far, near)),
      };
    }

    intersectObject(ray, object) {
      const points = routePoints(object);
      if (points.length >= 2) {
        const radius = Math.max(0.012, Number(object.geometry?.radius) || 0.07),
          minimum = [0, 1, 2].map(
            (axis) => Math.min(...points.map((point) => point[axis])) - radius,
          ),
          maximum = [0, 1, 2].map(
            (axis) => Math.max(...points.map((point) => point[axis])) + radius,
          );
        let near = -Infinity,
          far = Infinity;
        for (let axis = 0; axis < 3; axis += 1) {
          if (Math.abs(ray.direction[axis]) < EPSILON) {
            if (
              ray.origin[axis] < minimum[axis] ||
              ray.origin[axis] > maximum[axis]
            )
              return null;
            continue;
          }
          let first = (minimum[axis] - ray.origin[axis]) / ray.direction[axis],
            second = (maximum[axis] - ray.origin[axis]) / ray.direction[axis];
          if (first > second) [first, second] = [second, first];
          near = Math.max(near, first);
          far = Math.min(far, second);
          if (near > far) return null;
        }
        const distance = near >= 0 ? near : far;
        if (distance < 0) return null;
        return {
          distance,
          point: vec3.add(ray.origin, vec3.scale(ray.direction, distance)),
        };
      }
      const inverse = mat4Invert(
        mat4FromTransform(object.transform, object.geometry),
      );
      if (!inverse) return null;
      const origin = transformPoint(inverse, ray.origin);
      const direction = vec3.normalize(
        transformPoint(inverse, ray.direction, 0),
      );
      let minimum = -Infinity,
        maximum = Infinity;
      for (let axis = 0; axis < 3; axis += 1) {
        if (Math.abs(direction[axis]) < EPSILON) {
          if (origin[axis] < -0.5 || origin[axis] > 0.5) return null;
          continue;
        }
        let first = (-0.5 - origin[axis]) / direction[axis],
          second = (0.5 - origin[axis]) / direction[axis];
        if (first > second) [first, second] = [second, first];
        minimum = Math.max(minimum, first);
        maximum = Math.min(maximum, second);
        if (minimum > maximum) return null;
      }
      const localDistance = minimum >= 0 ? minimum : maximum;
      if (localDistance < 0) return null;
      const localHit = vec3.add(origin, vec3.scale(direction, localDistance));
      const worldHit = transformPoint(
        mat4FromTransform(object.transform, object.geometry),
        localHit,
      );
      return {
        distance: vec3.length(vec3.subtract(worldHit, ray.origin)),
        point: worldHit,
      };
    }

    pick(clientX, clientY) {
      if (this.mode !== "webgl2") return null;
      const ray = this.screenRay(clientX, clientY);
      if (!ray) return null;
      let closest = null;
      for (const object of this.objects) {
        if (object.visible === false || object.locked || object._layer?.locked)
          continue;
        const hit = this.intersectObject(ray, object);
        if (hit && (!closest || hit.distance < closest.distance))
          closest = { ...hit, object, ray };
      }
      return closest;
    }

    projectPoint(point) {
      const clip = transformPoint(this.cameraMatrices().viewProjection, point);
      const rect = this.canvas.getBoundingClientRect();
      return {
        x: rect.left + ((clip[0] + 1) / 2) * rect.width,
        y: rect.top + ((1 - clip[1]) / 2) * rect.height,
        depth: clip[2],
      };
    }

    frameObjects(ids = []) {
      const selected = this.objects.filter(
        (object) =>
          object.visible !== false && (!ids.length || ids.includes(object.id)),
      );
      if (!selected.length || !this.camera || this.camera.locked) return false;
      const points = selected.flatMap((object) => {
        const route = routePoints(object);
        if (route.length) return route;
        const center = objectCenter(object),
          dimensions = object.geometry?.dimensions ||
            object.geometry?.size || [1, 1, 1],
          half = Array.isArray(dimensions)
            ? dimensions.map((value) => Math.abs(Number(value) || 1) / 2)
            : [
                Math.abs(Number(dimensions.width) || 1) / 2,
                Math.abs(Number(dimensions.height) || 1) / 2,
                Math.abs(Number(dimensions.depth) || 1) / 2,
              ];
        return [-1, 1].flatMap((x) =>
          [-1, 1].flatMap((y) =>
            [-1, 1].map((z) => [
              center[0] + x * half[0],
              center[1] + y * half[1],
              center[2] + z * half[2],
            ]),
          ),
        );
      });
      const minimum = [0, 1, 2].map((axis) =>
        Math.min(...points.map((point) => Number(point[axis] || 0))),
      );
      const maximum = [0, 1, 2].map((axis) =>
        Math.max(...points.map((point) => Number(point[axis] || 0))),
      );
      const target = [0, 1, 2].map(
        (axis) => (minimum[axis] + maximum[axis]) / 2,
      );
      const backward = vec3.normalize(
        vec3.subtract(this.camera.position, this.camera.target),
      );
      const forward = vec3.scale(backward, -1);
      const right = vec3.normalize(vec3.cross(forward, this.camera.up));
      const screenUp = vec3.normalize(vec3.cross(right, forward));
      const projected = points.map((point) => {
        const offset = vec3.subtract(point, target);
        return [
          vec3.dot(offset, right),
          vec3.dot(offset, screenUp),
          vec3.dot(offset, backward),
        ];
      });
      const width = Math.max(
        0.5,
        Math.max(...projected.map((point) => point[0])) -
          Math.min(...projected.map((point) => point[0])),
      );
      const height = Math.max(
        0.5,
        Math.max(...projected.map((point) => point[1])) -
          Math.min(...projected.map((point) => point[1])),
      );
      const depth = Math.max(
        0.5,
        Math.max(...projected.map((point) => point[2])) -
          Math.min(...projected.map((point) => point[2])),
      );
      const rect = this.canvas.getBoundingClientRect();
      const aspect = Math.max(
        0.2,
        Number(rect.width || this.canvas.width || 1) /
          Math.max(1, Number(rect.height || this.canvas.height || 1)),
      );
      const padding =
        this.contentDensity === "detailed"
          ? 1.38
          : this.contentDensity === "compact"
            ? 1.16
            : 1.27;
      const framedHeight = Math.max(height, width / aspect) * padding;
      const fov = Math.max(1, Math.min(178, this.camera.fov_y_deg)) * DEG;
      const distance =
        Math.max(
          height / (2 * Math.tan(fov / 2)),
          width / (2 * Math.tan(fov / 2) * aspect),
        ) *
          padding +
        depth;
      this.camera.target = target;
      this.camera.position = vec3.add(
        target,
        vec3.scale(backward, Math.max(4, distance)),
      );
      this.camera.ortho_height = Math.max(2, framedHeight);
      this.render();
      return true;
    }

    dispose() {
      this.disposed = true;
      this.resizeObserver?.disconnect();
      this.labelElement?.replaceChildren();
      this.canvas.removeEventListener("webglcontextlost", this.onContextLost);
      this.canvas.removeEventListener(
        "webglcontextrestored",
        this.onContextRestored,
      );
      if (!this.gl) return;
      for (const mesh of this.meshes?.values() || []) {
        mesh.buffers.forEach((buffer) => this.gl.deleteBuffer(buffer));
        this.gl.deleteVertexArray(mesh.vertexArray);
      }
      if (this.program) this.gl.deleteProgram(this.program);
    }
  }

  function emit(target, name, detail) {
    target.dispatchEvent(new global.CustomEvent(name, { detail }));
  }

  global.NNDVSceneRenderer = Object.freeze({
    SceneRenderer,
    flattenObjects,
    math: Object.freeze({ vec3, mat4Multiply, mat4Invert, transformPoint }),
  });
})(window);
