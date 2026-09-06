from __future__ import annotations

from dataclasses import dataclass
from importlib.util import find_spec
from pathlib import Path
from typing import Any

from ..errors import OptionalDependencyError, ValidationError


@dataclass(slots=True)
class ExplanationResult:
    method: str
    target_layer: str
    target_class: int | None
    maps: list[Any]
    metadata: dict[str, Any]


class ExplainabilityAnalyzer:
    CAM_METHODS = {
        "cam": "CAM", "grad-cam": "GradCAM", "grad-cam++": "GradCAMpp",
        "smooth-grad-cam++": "SmoothGradCAMpp", "score-cam": "ScoreCAM",
        "ss-cam": "SSCAM", "is-cam": "ISCAM", "xgrad-cam": "XGradCAM",
        "layer-cam": "LayerCAM",
    }

    def cam(self, model: Any, sample_input: Any, *, target_layer: str, target_class: int | None = None, method: str = "grad-cam") -> ExplanationResult:
        if find_spec("torch") is None:
            raise OptionalDependencyError("CAM analysis requires PyTorch and TorchCAM", hint="Install nn-davinci[pytorch,explain].")
        try:
            from torchcam import methods
        except ImportError as exc:
            raise OptionalDependencyError(
                "CAM analysis requires PyTorch and TorchCAM",
                hint="Install nn-davinci[pytorch,explain].",
            ) from exc
        normalized = method.lower()
        if normalized not in self.CAM_METHODS:
            raise ValidationError(f"Unknown CAM method {method!r}", hint=f"Choose one of: {', '.join(self.CAM_METHODS)}")
        extractor_class = getattr(methods, self.CAM_METHODS[normalized])
        with extractor_class(model, target_layer=target_layer) as extractor:
            output = model(sample_input)
            class_index = int(output.argmax(dim=-1)[0]) if target_class is None else int(target_class)
            maps = extractor(class_index, output)
        return ExplanationResult(normalized, target_layer, class_index, [item.detach().cpu() for item in maps], {"output_shape": list(output.shape)})

    def input_gradient(self, model: Any, sample_input: Any, *, target_class: int | None = None, absolute: bool = True) -> ExplanationResult:
        if find_spec("torch") is None:
            raise OptionalDependencyError("Input-gradient analysis requires PyTorch", hint="Install nn-davinci[pytorch].")
        value = sample_input.detach().clone().requires_grad_(True)
        model.zero_grad(set_to_none=True)
        output = model(value)
        class_index = int(output.argmax(dim=-1)[0]) if target_class is None else int(target_class)
        output[0, class_index].backward()
        gradient = value.grad.detach().cpu()
        if absolute:
            gradient = gradient.abs()
        return ExplanationResult("input-gradient", "input", class_index, [gradient], {"output_shape": list(output.shape)})

    def capture_features(self, model: Any, sample_input: Any, *, target_layers: list[str]) -> dict[str, Any]:
        try:
            import torch
        except ImportError as exc:
            raise OptionalDependencyError("Feature capture requires PyTorch", hint="Install nn-davinci[pytorch].") from exc
        modules = dict(model.named_modules())
        missing = sorted(set(target_layers) - modules.keys())
        if missing:
            raise ValidationError(f"Target layer(s) not found: {', '.join(missing)}")
        values: dict[str, list[Any]] = {name: [] for name in target_layers}
        handles = [modules[name].register_forward_hook(lambda _m, _i, out, name=name: values[name].append(_detach(out, torch))) for name in target_layers]
        try:
            output = model(sample_input)
        finally:
            for handle in handles:
                handle.remove()
        return {"features": values, "output": _detach(output, torch)}

    def attention(self, model: Any, sample_input: Any, *, target_layers: list[str]) -> dict[str, Any]:
        result = self.capture_features(model, sample_input, target_layers=target_layers)
        return {"attention": result["features"], "note": "Captured layer outputs; choose attention-probability/dropout modules for weights."}

    def channel_importance(self, activations: Any, gradients: Any | None = None) -> Any:
        """Return one importance value per channel/neuron using |activation| or |a·grad|."""
        if find_spec("torch") is None:
            raise OptionalDependencyError("Channel importance requires PyTorch", hint="Install nn-davinci[pytorch].")
        value = activations.detach()
        if gradients is not None:
            value = value * gradients.detach()
        if value.ndim < 2:
            return value.abs()
        reduction_dims = tuple(index for index in range(value.ndim) if index != 1)
        return value.abs().mean(dim=reduction_dims).cpu()

    def pruning_candidates(self, feature_records: dict[str, Any], *, fraction: float = 0.2) -> list[dict[str, Any]]:
        if not 0 < fraction < 1:
            raise ValidationError("Pruning fraction must be between 0 and 1")
        candidates = []
        for path, values in feature_records.items():
            for pass_index, activation in enumerate(values):
                scores = self.channel_importance(activation)
                count = max(1, int(scores.numel() * fraction))
                selected = scores.argsort()[:count]
                candidates.append({
                    "layer": path, "pass_index": pass_index, "channels": selected.tolist(),
                    "scores": scores[selected].tolist(), "method": "mean-absolute-activation",
                })
        return candidates

    def save_heatmaps(self, result: ExplanationResult, output: str | Path, *, input_image: Any = None, opacity: float = 0.48) -> list[Path]:
        try:
            import numpy as np
            from PIL import Image
        except ImportError as exc:
            raise OptionalDependencyError("Heatmap image export requires NumPy and Pillow", hint="Install nn-davinci[explain].") from exc
        stem = Path(output).with_suffix("")
        stem.parent.mkdir(parents=True, exist_ok=True)
        base = None
        if input_image is not None:
            base = Image.open(input_image).convert("RGB") if isinstance(input_image, (str, Path)) else input_image.convert("RGB") if hasattr(input_image, "convert") else Image.fromarray(np.asarray(input_image).astype("uint8")).convert("RGB")
        paths = []
        for index, value in enumerate(result.maps):
            array = value.detach().float().cpu().numpy() if hasattr(value, "detach") else np.asarray(value)
            array = np.squeeze(array)
            while array.ndim > 2:
                array = array.mean(axis=0)
            array = array - np.nanmin(array)
            maximum = np.nanmax(array)
            array = array / maximum if maximum > 0 else array
            color = _colorize(array, np)
            heatmap = Image.fromarray(color, "RGB")
            if base is not None:
                heatmap = heatmap.resize(base.size, Image.Resampling.BILINEAR)
                heatmap = Image.blend(base, heatmap, max(0.0, min(1.0, opacity)))
            destination = stem.with_name(f"{stem.name}-{index + 1}.png")
            heatmap.save(destination)
            paths.append(destination)
        return paths


def _detach(value: Any, torch: Any) -> Any:
    if isinstance(value, torch.Tensor):
        return value.detach().cpu()
    if isinstance(value, dict):
        return {key: _detach(item, torch) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_detach(item, torch) for item in value]
    return value


def _colorize(values: Any, np: Any) -> Any:
    """Small perceptually ordered blue→cyan→yellow→red heatmap without matplotlib."""
    stops = np.array([[26, 35, 126], [20, 130, 180], [58, 190, 130], [245, 220, 70], [205, 45, 35]], dtype=float)
    scaled = np.clip(values, 0, 1) * (len(stops) - 1)
    low = np.floor(scaled).astype(int)
    high = np.clip(low + 1, 0, len(stops) - 1)
    weight = (scaled - low)[..., None]
    return (stops[low] * (1 - weight) + stops[high] * weight).astype("uint8")
