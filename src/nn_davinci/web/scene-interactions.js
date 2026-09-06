(function initializeSceneInteractions(global) {
  "use strict";

  function copy(value) {
    return value === undefined ? undefined : JSON.parse(JSON.stringify(value));
  }

  function clamp(value, minimum, maximum) {
    return Math.max(minimum, Math.min(maximum, value));
  }

  function flatten(scene) {
    return global.NNDVSceneRenderer?.flattenObjects(scene) || [];
  }

  function sceneGroups(scene) {
    return (scene?.layers || []).flatMap((layer) =>
      (layer.groups || []).map((group) => ({ group, layer })),
    );
  }

  function sceneObject(scene, id) {
    return flatten(scene).find((object) => object.id === id) || null;
  }

  function objectPosition(object) {
    object.transform = object.transform || {};
    object.transform.position = (object.transform.position || [0, 0, 0]).map(
      Number,
    );
    return object.transform.position;
  }

  function emit(target, name, detail) {
    target.dispatchEvent(new global.CustomEvent(name, { detail }));
  }

  class SceneInteractions extends global.EventTarget {
    constructor(renderer, options = {}) {
      super();
      if (!renderer) throw new Error("SceneInteractions requires a renderer");
      this.renderer = renderer;
      this.canvas = renderer.canvas;
      this.fallbackElement = options.fallbackElement || null;
      this.marqueeElement = options.marqueeElement || null;
      this.beforeChange = options.beforeChange || (() => {});
      this.onChange = options.onChange || (() => {});
      this.onSelectionChange = options.onSelectionChange || (() => {});
      this.onCameraChange = options.onCameraChange || (() => {});
      this.scene = null;
      this.selection = new Set();
      this.tool = "select";
      this.snap = { enabled: true, grid: 0.25 };
      this.pointer = null;
      this.disposed = false;
      this.bound = {
        down: (event) => this.pointerDown(event),
        move: (event) => this.pointerMove(event),
        up: (event) => this.pointerUp(event),
        wheel: (event) => this.wheel(event),
        context: (event) => event.preventDefault(),
        fallbackClick: (event) => this.fallbackClick(event),
      };
      this.canvas.addEventListener("pointerdown", this.bound.down);
      global.addEventListener("pointermove", this.bound.move);
      global.addEventListener("pointerup", this.bound.up);
      this.canvas.addEventListener("wheel", this.bound.wheel, {
        passive: false,
      });
      this.canvas.addEventListener("contextmenu", this.bound.context);
      this.fallbackElement?.addEventListener("click", this.bound.fallbackClick);
    }

    setScene(scene) {
      this.scene = scene;
      this.selection = new Set(
        (scene?.selection_ids || []).filter((id) => sceneObject(scene, id)),
      );
      this.syncSelectionFlags();
      this.renderer.setSelection(this.selection);
    }

    setTool(tool) {
      this.tool = ["select", "orbit", "pan", "move"].includes(tool)
        ? tool
        : "select";
      this.canvas.dataset.sceneTool = this.tool;
    }

    setSnapping(enabled, grid = this.snap.grid) {
      this.snap = {
        enabled: !!enabled,
        grid: Math.max(0.001, Number(grid) || 0.25),
      };
    }

    pointerDown(event) {
      if (this.disposed || event.target !== this.canvas || !this.scene) return;
      const camera = this.renderer.getCameraState();
      const orbit = this.tool === "orbit" || event.button === 2 || event.altKey;
      const pan =
        this.tool === "pan" || event.button === 1 || (event.shiftKey && orbit);
      const hit =
        !orbit && !pan
          ? this.renderer.pick(event.clientX, event.clientY)
          : null;
      const mode = pan ? "pan" : orbit ? "orbit" : hit ? "select" : "marquee";
      this.pointer = {
        id: event.pointerId,
        mode,
        startX: event.clientX,
        startY: event.clientY,
        lastX: event.clientX,
        lastY: event.clientY,
        moved: false,
        camera,
        hit,
        additive: event.shiftKey || event.ctrlKey || event.metaKey,
      };
      if (["orbit", "pan"].includes(mode) && camera?.locked) {
        this.pointer = null;
        emit(this, "warning", { message: "Camera is locked" });
        return;
      }
      if (["orbit", "pan"].includes(mode)) this.beforeChange("camera");
      if (mode === "marquee")
        this.showMarquee(event.clientX, event.clientY, 0, 0);
      this.canvas.setPointerCapture?.(event.pointerId);
      event.preventDefault();
    }

    pointerMove(event) {
      const pointer = this.pointer;
      if (!pointer || pointer.id !== event.pointerId) return;
      const dx = event.clientX - pointer.lastX,
        dy = event.clientY - pointer.lastY;
      pointer.lastX = event.clientX;
      pointer.lastY = event.clientY;
      pointer.moved ||=
        Math.hypot(
          event.clientX - pointer.startX,
          event.clientY - pointer.startY,
        ) > 3;
      if (pointer.mode === "orbit") this.orbit(dx, dy);
      else if (pointer.mode === "pan") this.pan(dx, dy);
      else if (pointer.mode === "marquee")
        this.showMarquee(
          Math.min(pointer.startX, event.clientX),
          Math.min(pointer.startY, event.clientY),
          Math.abs(event.clientX - pointer.startX),
          Math.abs(event.clientY - pointer.startY),
        );
      event.preventDefault();
    }

    pointerUp(event) {
      const pointer = this.pointer;
      if (!pointer || pointer.id !== event.pointerId) return;
      this.pointer = null;
      this.canvas.releasePointerCapture?.(event.pointerId);
      if (pointer.mode === "select" && !pointer.moved)
        this.select(pointer.hit?.object?.id || null, pointer.additive);
      else if (pointer.mode === "marquee") {
        this.hideMarquee();
        if (pointer.moved)
          this.selectMarquee(
            pointer.startX,
            pointer.startY,
            event.clientX,
            event.clientY,
            pointer.additive,
          );
        else this.select(null, pointer.additive);
      } else if (["orbit", "pan"].includes(pointer.mode)) {
        this.commitCamera(pointer.mode);
      }
    }

    wheel(event) {
      if (!this.scene) return;
      const camera = this.renderer.getCameraState();
      if (!camera || camera.locked) return;
      this.beforeChange("camera");
      const direction = Math.exp(clamp(event.deltaY, -160, 160) * 0.0018);
      if (camera.projection === "orthographic")
        camera.ortho_height = clamp(
          camera.ortho_height * direction,
          0.05,
          10000,
        );
      else {
        const offset = [0, 1, 2].map(
          (index) => camera.position[index] - camera.target[index],
        );
        camera.position = [0, 1, 2].map(
          (index) => camera.target[index] + offset[index] * direction,
        );
      }
      this.renderer.setCamera(camera);
      this.commitCamera("zoom");
      event.preventDefault();
    }

    orbit(dx, dy) {
      const camera = this.renderer.getCameraState();
      if (!camera) return;
      const offset = [0, 1, 2].map(
        (index) => camera.position[index] - camera.target[index],
      );
      const radius = Math.max(0.001, Math.hypot(...offset));
      let azimuth = Math.atan2(offset[0], offset[2]);
      let elevation = Math.asin(clamp(offset[1] / radius, -1, 1));
      azimuth -= dx * 0.008;
      elevation = clamp(
        elevation + dy * 0.008,
        -Math.PI * 0.495,
        Math.PI * 0.495,
      );
      camera.position = [
        camera.target[0] + radius * Math.cos(elevation) * Math.sin(azimuth),
        camera.target[1] + radius * Math.sin(elevation),
        camera.target[2] + radius * Math.cos(elevation) * Math.cos(azimuth),
      ];
      camera.up = [0, 1, 0];
      this.renderer.setCamera(camera);
    }

    pan(dx, dy) {
      const camera = this.renderer.getCameraState();
      if (!camera) return;
      const forward = normalize(subtract(camera.target, camera.position));
      const right = normalize(cross(forward, camera.up));
      const up = normalize(cross(right, forward));
      const distance = Math.max(
        0.1,
        length(subtract(camera.position, camera.target)),
      );
      const scale =
        camera.projection === "orthographic"
          ? camera.ortho_height / Math.max(200, this.canvas.clientHeight)
          : distance / Math.max(200, this.canvas.clientHeight);
      const shift = add(
        scaleVector(right, -dx * scale),
        scaleVector(up, dy * scale),
      );
      camera.position = add(camera.position, shift);
      camera.target = add(camera.target, shift);
      this.renderer.setCamera(camera);
    }

    commitCamera(reason) {
      const camera = this.renderer.getCameraState();
      const stored = (this.scene?.cameras || []).find(
        (item) => item.id === camera?.id,
      );
      if (stored && camera) {
        Object.assign(stored, copy(camera));
        stored.metadata = stored.metadata || {};
        if (reason === "initial-auto-frame") {
          stored.metadata.last_auto_frame = "initial-open";
        } else {
          stored.metadata.user_saved_camera = true;
          stored.metadata.last_camera_action = String(reason || "camera");
          this.scene.metadata = this.scene.metadata || {};
          this.scene.metadata.auto_frame_on_open = false;
        }
      }
      this.onCameraChange(copy(camera), reason);
      this.onChange("camera", { reason, camera: copy(camera) });
      emit(this, "camerachange", { camera: copy(camera), reason });
    }

    select(id, additive = false) {
      if (!additive) this.selection.clear();
      if (id) {
        if (additive && this.selection.has(id)) this.selection.delete(id);
        else this.selection.add(id);
      }
      this.commitSelection();
    }

    setSelection(ids, { notify = true } = {}) {
      const values = Array.isArray(ids) ? ids : [...(ids || [])];
      this.selection = new Set(
        values.filter((id) => sceneObject(this.scene, id)),
      );
      this.syncSelectionFlags();
      if (notify) this.commitSelection();
      else this.renderer.setSelection(this.selection);
    }

    commitSelection() {
      if (this.scene) this.scene.selection_ids = [...this.selection];
      this.syncSelectionFlags();
      this.renderer.setSelection(this.selection);
      const objects = [...this.selection]
        .map((id) => sceneObject(this.scene, id))
        .filter(Boolean);
      const provenance = {
        graph: unique(
          objects.flatMap((item) => item.provenance?.graph_ir_ids || []),
        ),
        semantic: unique(
          objects.flatMap((item) => item.provenance?.semantic_view_ids || []),
        ),
        figure: unique(
          objects.flatMap((item) => item.provenance?.figure_ir_ids || []),
        ),
      };
      this.onSelectionChange([...this.selection], provenance);
      emit(this, "selectionchange", {
        ids: [...this.selection],
        objects,
        provenance,
      });
    }

    syncSelectionFlags() {
      if (!this.scene) return;
      flatten(this.scene).forEach((object) => {
        object.selected = this.selection.has(object.id);
      });
      sceneGroups(this.scene).forEach(({ group }) => {
        group.selected = this.selection.has(group.id);
      });
      this.scene.selection_ids = [...this.selection];
    }

    showMarquee(x, y, width, height) {
      if (!this.marqueeElement) return;
      const parent =
        this.marqueeElement.offsetParent?.getBoundingClientRect() || {
          left: 0,
          top: 0,
        };
      Object.assign(this.marqueeElement.style, {
        left: `${x - parent.left}px`,
        top: `${y - parent.top}px`,
        width: `${width}px`,
        height: `${height}px`,
      });
      this.marqueeElement.hidden = false;
    }

    hideMarquee() {
      if (this.marqueeElement) this.marqueeElement.hidden = true;
    }

    selectMarquee(startX, startY, endX, endY, additive) {
      const minimumX = Math.min(startX, endX),
        maximumX = Math.max(startX, endX),
        minimumY = Math.min(startY, endY),
        maximumY = Math.max(startY, endY);
      const ids = flatten(this.scene)
        .filter((object) => object.visible !== false && !object.locked)
        .filter((object) => {
          const point = this.renderer.projectPoint(objectPosition(object));
          return (
            point.depth >= -1 &&
            point.depth <= 1 &&
            point.x >= minimumX &&
            point.x <= maximumX &&
            point.y >= minimumY &&
            point.y <= maximumY
          );
        })
        .map((object) => object.id);
      if (!additive) this.selection.clear();
      ids.forEach((id) => this.selection.add(id));
      this.commitSelection();
    }

    selectedObjects({ includeLocked = false } = {}) {
      return [...this.selection]
        .map((id) => sceneObject(this.scene, id))
        .filter((object) => object && (includeLocked || !object.locked));
    }

    mutate(label, operation) {
      const objects = this.selectedObjects();
      if (!objects.length) {
        emit(this, "warning", {
          message: "Select one or more unlocked objects",
        });
        return false;
      }
      this.beforeChange(label);
      operation(objects);
      this.renderer.setScene(this.scene, this.scene.active_camera_id);
      this.renderer.setSelection(this.selection);
      this.onChange(label, { ids: [...this.selection] });
      emit(this, "scenechange", { label, ids: [...this.selection] });
      return true;
    }

    transformSelected({ axis = "xyz", translation, rotation, scale } = {}) {
      return this.mutate("transform", (objects) => {
        const axes =
          axis === "xyz" ? [0, 1, 2] : [Math.max(0, "xyz".indexOf(axis))];
        for (const object of objects) {
          object.transform = object.transform || {};
          if (translation !== undefined) {
            const current = objectPosition(object);
            const values = Array.isArray(translation)
              ? translation.map(Number)
              : [Number(translation), Number(translation), Number(translation)];
            for (const index of axes) current[index] += values[index] || 0;
            object.transform.position = current.map((value) =>
              this.snapValue(value),
            );
          }
          if (rotation !== undefined) {
            const current = (object.transform.rotation || [0, 0, 0]).map(
              Number,
            );
            const values = Array.isArray(rotation)
              ? rotation.map(Number)
              : [Number(rotation), Number(rotation), Number(rotation)];
            for (const index of axes) current[index] += values[index] || 0;
            object.transform.rotation = current;
          }
          if (scale !== undefined) {
            const current = (object.transform.scale || [1, 1, 1]).map(Number);
            const values = Array.isArray(scale)
              ? scale.map(Number)
              : [Number(scale), Number(scale), Number(scale)];
            for (const index of axes) current[index] *= values[index] || 1;
            object.transform.scale = current.map((value) =>
              Math.max(0.001, value),
            );
          }
        }
      });
    }

    snapValue(value) {
      return this.snap.enabled
        ? Math.round(value / this.snap.grid) * this.snap.grid
        : value;
    }

    align(axis = "x", mode = "center") {
      const index = Math.max(0, "xyz".indexOf(axis));
      return this.mutate(`align-${axis}`, (objects) => {
        const values = objects.map((object) => objectPosition(object)[index]);
        const target =
          mode === "min"
            ? Math.min(...values)
            : mode === "max"
              ? Math.max(...values)
              : values.reduce((sum, value) => sum + value, 0) / values.length;
        objects.forEach((object) => {
          objectPosition(object)[index] = this.snapValue(target);
        });
      });
    }

    distribute(axis = "x") {
      const index = Math.max(0, "xyz".indexOf(axis));
      return this.mutate(`distribute-${axis}`, (objects) => {
        if (objects.length < 3) return;
        objects.sort(
          (a, b) => objectPosition(a)[index] - objectPosition(b)[index],
        );
        const first = objectPosition(objects[0])[index],
          last = objectPosition(objects.at(-1))[index],
          step = (last - first) / (objects.length - 1);
        objects.forEach((object, itemIndex) => {
          objectPosition(object)[index] = this.snapValue(
            first + step * itemIndex,
          );
        });
      });
    }

    setDepthSpacing(spacing = 1) {
      return this.mutate("depth-spacing", (objects) => {
        objects.sort((a, b) => Number(a.order || 0) - Number(b.order || 0));
        const center = (objects.length - 1) / 2;
        objects.forEach((object, index) => {
          objectPosition(object)[2] = this.snapValue(
            (index - center) * Number(spacing),
          );
        });
      });
    }

    setOpacity(opacity) {
      return this.mutate("opacity", (objects) => {
        objects.forEach((object) => {
          object.material = object.material || {};
          object.material.opacity = clamp(Number(opacity), 0, 1);
        });
      });
    }

    toggleLock() {
      const objects = this.selectedObjects({ includeLocked: true });
      if (!objects.length) return false;
      this.beforeChange("lock");
      const locked = !objects.every((object) => object.locked);
      objects.forEach((object) => {
        object.locked = locked;
      });
      this.renderer.render();
      this.onChange("lock", { ids: [...this.selection], locked });
      return true;
    }

    toggleCameraLock() {
      const camera = this.renderer.getCameraState();
      if (!camera) return false;
      this.beforeChange("camera-lock");
      camera.locked = !camera.locked;
      this.renderer.setCamera(camera);
      this.commitCamera("lock");
      return camera.locked;
    }

    group() {
      const objects = this.selectedObjects();
      if (objects.length < 2) return false;
      this.beforeChange("group");
      const firstLayer = (this.scene.layers || []).find((layer) =>
        layer.objects?.some((object) => object.id === objects[0].id),
      );
      if (!firstLayer) return false;
      firstLayer.groups = firstLayer.groups || [];
      const id = `group-${Date.now().toString(36)}`;
      firstLayer.groups.push({
        id,
        name: `Group ${firstLayer.groups.length + 1}`,
        object_ids: objects.map((object) => object.id),
        visible: true,
        locked: false,
        selected: false,
        metadata: { collapsed: false },
      });
      objects.forEach((object) => {
        object.parent_group_id = id;
      });
      this.onChange("group", { id, ids: objects.map((object) => object.id) });
      emit(this, "scenechange", { label: "group", id });
      return true;
    }

    ungroup() {
      const ids = new Set(this.selection);
      const matches = sceneGroups(this.scene).filter(({ group }) =>
        (group.object_ids || []).some((id) => ids.has(id)),
      );
      if (!matches.length) return false;
      this.beforeChange("ungroup");
      for (const { group, layer } of matches) {
        (group.object_ids || []).forEach((id) => {
          const object = sceneObject(this.scene, id);
          if (object?.parent_group_id === group.id)
            object.parent_group_id = null;
        });
        layer.groups = (layer.groups || []).filter(
          (item) => item.id !== group.id,
        );
      }
      this.onChange("ungroup", { ids: [...ids] });
      return true;
    }

    toggleHidden() {
      const objects = this.selectedObjects({ includeLocked: true });
      if (!objects.length) return false;
      this.beforeChange("visibility");
      const visible = objects.every((object) => object.visible === false);
      objects.forEach((object) => {
        object.visible = visible;
      });
      if (!visible) this.selection.clear();
      this.renderer.setScene(this.scene, this.scene.active_camera_id);
      this.commitSelection();
      this.onChange("visibility", { visible });
      return true;
    }

    isolate() {
      if (!this.selection.size) return false;
      this.beforeChange("isolate");
      const selected = new Set(this.selection);
      flatten(this.scene).forEach((object) => {
        object.visible = selected.has(object.id);
      });
      this.renderer.setScene(this.scene, this.scene.active_camera_id);
      this.renderer.setSelection(this.selection);
      this.onChange("isolate", { ids: [...selected] });
      return true;
    }

    showAll() {
      this.beforeChange("show-all");
      flatten(this.scene).forEach((object) => {
        object.visible = true;
      });
      this.renderer.setScene(this.scene, this.scene.active_camera_id);
      this.renderer.setSelection(this.selection);
      this.onChange("show-all", {});
    }

    focus() {
      const camera = this.renderer.getCameraState();
      if (!camera || camera.locked) {
        emit(this, "warning", { message: "Camera is locked" });
        return false;
      }
      this.beforeChange("frame-selection");
      if (!this.renderer.frameObjects([...this.selection])) return false;
      this.commitCamera("frame-selection");
      return true;
    }

    collapseOrExplode(explode = false) {
      const selected = this.selectedObjects({ includeLocked: true });
      if (!selected.length) return false;
      this.beforeChange(explode ? "explode" : "collapse");
      const center = [0, 1, 2].map(
        (axis) =>
          selected.reduce(
            (sum, object) => sum + objectPosition(object)[axis],
            0,
          ) / selected.length,
      );
      selected.forEach((object, index) => {
        object.metadata = object.metadata || {};
        if (explode) {
          if (!object.metadata.pre_explode_position)
            object.metadata.pre_explode_position = [...objectPosition(object)];
          const angle = (index / Math.max(1, selected.length)) * Math.PI * 2;
          object.transform.position = [
            center[0] + Math.cos(angle) * 2,
            center[1] + Math.sin(angle) * 1.2,
            center[2] + (index - selected.length / 2) * 0.6,
          ];
          object.metadata.exploded = true;
        } else {
          object.transform.position =
            object.metadata.pre_explode_position || center;
          delete object.metadata.pre_explode_position;
          object.metadata.exploded = false;
        }
      });
      this.renderer.setScene(this.scene, this.scene.active_camera_id);
      this.renderer.setSelection(this.selection);
      this.onChange(explode ? "explode" : "collapse", {});
      return true;
    }

    fallbackClick(event) {
      const object = event.target.closest?.(
        "[data-scene-object-id],[data-object-id]",
      );
      if (!object) return;
      this.select(
        object.dataset.sceneObjectId || object.dataset.objectId,
        event.shiftKey || event.ctrlKey || event.metaKey,
      );
    }

    dispose() {
      this.disposed = true;
      this.canvas.removeEventListener("pointerdown", this.bound.down);
      global.removeEventListener("pointermove", this.bound.move);
      global.removeEventListener("pointerup", this.bound.up);
      this.canvas.removeEventListener("wheel", this.bound.wheel);
      this.canvas.removeEventListener("contextmenu", this.bound.context);
      this.fallbackElement?.removeEventListener(
        "click",
        this.bound.fallbackClick,
      );
    }
  }

  function length(a) {
    return Math.hypot(...a);
  }

  function normalize(a) {
    const divisor = length(a) || 1;
    return a.map((value) => value / divisor);
  }

  function subtract(a, b) {
    return a.map((value, index) => value - b[index]);
  }

  function add(a, b) {
    return a.map((value, index) => value + b[index]);
  }

  function scaleVector(a, value) {
    return a.map((item) => item * value);
  }

  function cross(a, b) {
    return [
      a[1] * b[2] - a[2] * b[1],
      a[2] * b[0] - a[0] * b[2],
      a[0] * b[1] - a[1] * b[0],
    ];
  }

  function unique(values) {
    return [...new Set(values)];
  }

  global.NNDVSceneInteractions = Object.freeze({ SceneInteractions });
})(window);
