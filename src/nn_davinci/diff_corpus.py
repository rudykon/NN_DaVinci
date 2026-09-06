"""Fixed, offline model-difference compatibility corpus."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .adapters.pytorch import PyTorchAdapter
from .analysis.diff import compare_graphs, export_diff
from .ir import GraphIR
from .real_models import construct_real_model, import_real_model

DIFF_CORPUS_VERSION = "1.0"


def _torch() -> tuple[Any, Any]:
    import torch
    from torch import nn

    return torch, nn


def _resnet18_graph() -> GraphIR:
    torch, _ = _torch()
    from torchvision.models import resnet18

    torch.manual_seed(4101)
    model = resnet18(weights=None).eval()
    sample = torch.randn(1, 3, 64, 64)
    graph = PyTorchAdapter().load(model, sample_input=sample)
    graph.metadata.update({"diff_fixture": "resnet18", "weights": "random-local", "seed": 4101})
    return graph


def _moe_transformer_graph() -> GraphIR:
    torch, nn = _torch()
    torch.manual_seed(4102)

    class TopKRouter(nn.Module):  # type: ignore[name-defined]
        def __init__(self) -> None:
            super().__init__()
            self.router_logits = nn.Linear(96, 4)

        def forward(self, x: Any) -> Any:
            score = torch.softmax(self.router_logits(x), dim=-1)
            value, index = torch.topk(score, 2, dim=-1)
            return (torch.nn.functional.one_hot(index, 4).to(score.dtype) * value.unsqueeze(-1)).sum(dim=-2)

    class Expert(nn.Module):  # type: ignore[name-defined]
        def __init__(self) -> None:
            super().__init__()
            self.feed_forward = nn.Sequential(nn.Linear(96, 192), nn.GELU(), nn.Linear(192, 96))

        def forward(self, x: Any) -> Any:
            return self.feed_forward(x)

    class MoETransformerEncoder(nn.Module):  # type: ignore[name-defined]
        def __init__(self) -> None:
            super().__init__()
            self.token_embedding = nn.Embedding(2048, 96)
            self.position_embedding = nn.Embedding(32, 96)
            self.encoder_attention = nn.MultiheadAttention(96, 4, batch_first=True)
            self.router = TopKRouter()
            self.experts = nn.ModuleList([Expert() for _ in range(4)])
            self.output_norm = nn.LayerNorm(96)
            self.pooler = nn.Linear(96, 96)

        def forward(self, tokens: Any) -> Any:
            position = torch.arange(tokens.shape[1], device=tokens.device).unsqueeze(0)
            x = self.token_embedding(tokens) + self.position_embedding(position)
            attention, _ = self.encoder_attention(x, x, x, need_weights=False)
            x = x + attention
            routing = self.router(x)
            expert_output = torch.stack([expert(x) for expert in self.experts], dim=-2)
            x = self.output_norm(x + (expert_output * routing.unsqueeze(-1)).sum(dim=-2))
            return self.pooler(x[:, 0])

    sample = torch.randint(0, 2048, (1, 16), dtype=torch.long)
    graph = PyTorchAdapter().load(MoETransformerEncoder().eval(), sample_input=sample)
    graph.metadata.update({"diff_fixture": "moe_transformer", "weights": "random-local", "seed": 4102})
    return graph


def _attention_unet_graph() -> GraphIR:
    torch, nn = _torch()
    torch.manual_seed(4103)

    def block(in_channels: int, out_channels: int) -> Any:
        return nn.Sequential(nn.Conv2d(in_channels, out_channels, 3, padding=1), nn.ReLU(), nn.Conv2d(out_channels, out_channels, 3, padding=1), nn.ReLU())

    class AttentionUNet(nn.Module):  # type: ignore[name-defined]
        def __init__(self) -> None:
            super().__init__()
            self.encoder1 = block(3, 16)
            self.encoder2 = block(16, 32)
            self.encoder3 = block(32, 64)
            self.pool = nn.MaxPool2d(2)
            self.bottleneck = block(64, 128)
            self.bottleneck_attention = nn.MultiheadAttention(128, 4, batch_first=True)
            self.decoder3 = block(192, 64)
            self.decoder2 = block(96, 32)
            self.decoder1 = block(48, 16)
            self.segmentation_head = nn.Conv2d(16, 4, 1)

        def forward(self, image: Any) -> Any:
            encoder1 = self.encoder1(image)
            encoder2 = self.encoder2(self.pool(encoder1))
            encoder3 = self.encoder3(self.pool(encoder2))
            center = self.bottleneck(self.pool(encoder3))
            tokens = center.flatten(2).transpose(1, 2)
            attended, _ = self.bottleneck_attention(tokens, tokens, tokens, need_weights=False)
            center = (tokens + attended).transpose(1, 2).reshape_as(center)
            decoder3 = self.decoder3(torch.cat((torch.nn.functional.interpolate(center, scale_factor=2.0), encoder3), dim=1))
            decoder2 = self.decoder2(torch.cat((torch.nn.functional.interpolate(decoder3, scale_factor=2.0), encoder2), dim=1))
            decoder1 = self.decoder1(torch.cat((torch.nn.functional.interpolate(decoder2, scale_factor=2.0), encoder1), dim=1))
            return self.segmentation_head(decoder1)

    sample = torch.randn(1, 3, 64, 64)
    graph = PyTorchAdapter().load(AttentionUNet().eval(), sample_input=sample)
    graph.metadata.update({"diff_fixture": "attention_unet", "weights": "random-local", "seed": 4103})
    return graph


def fixed_diff_corpus() -> dict[str, tuple[GraphIR, GraphIR]]:
    before_bert, _, _ = construct_real_model("bert_encoder")
    _, sample_bert, _ = construct_real_model("bert_encoder")
    ordinary_transformer = PyTorchAdapter().load(before_bert, sample_input=sample_bert)
    return {
        "resnet18_to_resnet50": (_resnet18_graph(), import_real_model("resnet50")),
        "transformer_to_moe": (ordinary_transformer, _moe_transformer_graph()),
        "unet_to_attention_unet": (import_real_model("multiscale_unet"), _attention_unet_graph()),
    }


def generate_diff_corpus_report(output_dir: str | Path, *, export_figures: bool = True) -> dict[str, Any]:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {"schema_version": "1.0", "corpus_version": DIFF_CORPUS_VERSION, "comparisons": {}}
    for name, (before, after) in fixed_diff_corpus().items():
        difference = compare_graphs(before, after)
        outputs = export_diff(before, after, root / name, view="change-only") if export_figures else []
        matching = difference.summary["matching"]
        report["comparisons"][name] = {
            "before": {"name": before.name, "nodes": len(before.nodes), "edges": len(before.edges)},
            "after": {"name": after.name, "nodes": len(after.nodes), "edges": len(after.edges)},
            "matching": matching,
            "change_kinds": difference.summary["change_kinds"],
            "metrics": difference.summary["metrics"],
            "bidirectional_provenance": all(item.before_operation_ids and item.after_operation_ids for item in difference.matches),
            "outputs": [path.relative_to(root).as_posix() for path in outputs],
            "passed": bool(difference.matches) and all(item.before_operation_ids and item.after_operation_ids for item in difference.matches),
        }
    report["passed"] = all(item["passed"] for item in report["comparisons"].values())
    (root / "real-model-diff-report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


__all__ = ["DIFF_CORPUS_VERSION", "fixed_diff_corpus", "generate_diff_corpus_report"]
