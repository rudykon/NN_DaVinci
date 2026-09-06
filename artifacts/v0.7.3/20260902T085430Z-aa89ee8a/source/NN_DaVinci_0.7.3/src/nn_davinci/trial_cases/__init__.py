"""Standalone framework-only models used by the researcher trial kit.

The modules in this package intentionally do not import NN_DaVinci.  They are
ordinary PyTorch/ONNX programs so the compatibility path cannot depend on
visualizer-specific annotations embedded in a model.
"""

from .onnx_case import make_multi_io_onnx
from .pytorch_cases import (
    make_custom_unknown,
    make_dynamic_branch,
    make_shared_siamese,
    make_transformer_residual,
    make_unet_skip,
)

__all__ = [
    "make_custom_unknown",
    "make_dynamic_branch",
    "make_multi_io_onnx",
    "make_shared_siamese",
    "make_transformer_residual",
    "make_unet_skip",
]
