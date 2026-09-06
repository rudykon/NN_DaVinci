"""Independent PyTorch model cases for the consented researcher trial.

These are conventional framework examples: no NN_DaVinci imports, tags or
recognizer hints are present.  Fixed random seeds make the sampled execution
and tensor shapes reproducible without downloading weights.
"""

from __future__ import annotations

from typing import Any


def _torch() -> tuple[Any, Any]:
    import torch
    from torch import nn

    return torch, nn


def make_dynamic_branch() -> tuple[Any, Any]:
    """A data-dependent image model that forces sampled runtime capture."""
    torch, nn = _torch()
    torch.manual_seed(5101)

    class DynamicBranchNet(nn.Module):  # type: ignore[name-defined]
        def __init__(self) -> None:
            super().__init__()
            self.stem = nn.Conv2d(3, 8, 3, padding=1)
            self.positive_branch = nn.Conv2d(8, 8, 1)
            self.negative_branch = nn.Conv2d(8, 8, 3, padding=1)
            self.pool = nn.AdaptiveAvgPool2d(1)
            self.classifier = nn.Linear(8, 4)

        def forward(self, image: Any) -> Any:
            hidden = torch.relu(self.stem(image))
            if bool((hidden.mean() >= 0).item()):
                hidden = self.positive_branch(hidden)
            else:
                hidden = self.negative_branch(hidden)
            return self.classifier(self.pool(hidden).flatten(1))

    sample = torch.ones(1, 3, 24, 24)
    return DynamicBranchNet().eval(), sample


def make_shared_siamese() -> tuple[Any, Any]:
    """Two inputs and outputs with one parameter-owning tower called twice."""
    torch, nn = _torch()
    torch.manual_seed(5102)

    class SharedSiamese(nn.Module):  # type: ignore[name-defined]
        def __init__(self) -> None:
            super().__init__()
            self.shared_tower = nn.Sequential(nn.Linear(16, 24), nn.ReLU(), nn.Linear(24, 16))
            self.score = nn.Linear(16, 1)

        def forward(self, left: Any, right: Any) -> tuple[Any, Any]:
            left_features = self.shared_tower(left)
            right_features = self.shared_tower(right)
            difference = left_features - right_features
            return self.score(torch.abs(difference)), left_features + right_features

    return SharedSiamese().eval(), (torch.randn(2, 16), torch.randn(2, 16))


def make_transformer_residual() -> tuple[Any, Any]:
    """Canonical pre-norm Transformer block with both residual additions."""
    torch, nn = _torch()
    torch.manual_seed(5103)

    class TransformerResidualBlock(nn.Module):  # type: ignore[name-defined]
        def __init__(self, width: int = 48, heads: int = 4) -> None:
            super().__init__()
            self.attention_norm = nn.LayerNorm(width)
            self.self_attention = nn.MultiheadAttention(width, heads, batch_first=True)
            self.ffn_norm = nn.LayerNorm(width)
            self.feed_forward = nn.Sequential(nn.Linear(width, 96), nn.GELU(), nn.Linear(96, width))

        def forward(self, tokens: Any) -> Any:
            normalized = self.attention_norm(tokens)
            attended, _ = self.self_attention(normalized, normalized, normalized, need_weights=False)
            attention_output = tokens + attended
            return attention_output + self.feed_forward(self.ffn_norm(attention_output))

    return TransformerResidualBlock().eval(), torch.randn(1, 12, 48)


def make_unet_skip() -> tuple[Any, Any]:
    """Small two-scale U-Net with explicit concatenating skip paths."""
    torch, nn = _torch()
    torch.manual_seed(5104)

    def block(in_channels: int, out_channels: int) -> Any:
        return nn.Sequential(
            nn.Conv2d(in_channels, out_channels, 3, padding=1),
            nn.ReLU(),
            nn.Conv2d(out_channels, out_channels, 3, padding=1),
            nn.ReLU(),
        )

    class TwoScaleUNet(nn.Module):  # type: ignore[name-defined]
        def __init__(self) -> None:
            super().__init__()
            self.encoder_scale_1 = block(1, 8)
            self.encoder_scale_2 = block(8, 16)
            self.pool = nn.MaxPool2d(2)
            self.bottleneck = block(16, 32)
            self.decoder_scale_2 = block(48, 16)
            self.decoder_scale_1 = block(24, 8)
            self.output_head = nn.Conv2d(8, 2, 1)

        def forward(self, image: Any) -> Any:
            skip_1 = self.encoder_scale_1(image)
            skip_2 = self.encoder_scale_2(self.pool(skip_1))
            center = self.bottleneck(self.pool(skip_2))
            up_2 = torch.nn.functional.interpolate(center, scale_factor=2.0, mode="nearest")
            decoded_2 = self.decoder_scale_2(torch.cat((up_2, skip_2), dim=1))
            up_1 = torch.nn.functional.interpolate(decoded_2, scale_factor=2.0, mode="nearest")
            decoded_1 = self.decoder_scale_1(torch.cat((up_1, skip_1), dim=1))
            return self.output_head(decoded_1)

    return TwoScaleUNet().eval(), torch.randn(1, 1, 32, 32)


def make_custom_unknown() -> tuple[Any, Any]:
    """A valid custom operator region with no evidence for a named architecture."""
    torch, nn = _torch()
    torch.manual_seed(5105)

    class SpectralGate(nn.Module):  # type: ignore[name-defined]
        def __init__(self) -> None:
            super().__init__()
            self.projection = nn.Linear(20, 20)
            self.gate = nn.Linear(20, 20)

        def forward(self, signal: Any) -> Any:
            projected = torch.sin(self.projection(signal))
            gated = torch.sigmoid(self.gate(signal))
            return projected * gated

    return SpectralGate().eval(), torch.randn(3, 20)


__all__ = [
    "make_custom_unknown",
    "make_dynamic_branch",
    "make_shared_siamese",
    "make_transformer_residual",
    "make_unet_skip",
]
