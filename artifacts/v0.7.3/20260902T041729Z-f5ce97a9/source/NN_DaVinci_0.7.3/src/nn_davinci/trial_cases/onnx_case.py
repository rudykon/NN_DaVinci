"""Standalone ONNX multi-input/output graph used by the trial kit."""

from __future__ import annotations

from typing import Any


def make_multi_io_onnx() -> tuple[Any, dict[str, list[int]]]:
    import onnx
    from onnx import TensorProto, helper

    batch, sequence = "batch", "sequence"
    inputs = [
        helper.make_tensor_value_info("tokens", TensorProto.FLOAT, [batch, sequence, 8]),
        helper.make_tensor_value_info("mask", TensorProto.FLOAT, [batch, sequence, 1]),
    ]
    outputs = [
        helper.make_tensor_value_info("scores", TensorProto.FLOAT, [batch, 8]),
        helper.make_tensor_value_info("features", TensorProto.FLOAT, [batch, sequence, 8]),
    ]
    shared_scale = helper.make_tensor("shared_scale", TensorProto.FLOAT, [1], [0.5])
    nodes = [
        helper.make_node("Mul", ["tokens", "shared_scale"], ["scaled_tokens"], name="shared/scale_tokens"),
        helper.make_node("Mul", ["mask", "shared_scale"], ["scaled_mask"], name="shared/scale_mask"),
        helper.make_node("Mul", ["scaled_tokens", "scaled_mask"], ["features"], name="fusion/apply_mask"),
        helper.make_node("ReduceMean", ["features"], ["scores"], name="heads/pool", axes=[1], keepdims=0),
    ]
    graph = helper.make_graph(nodes, "ExternalMultiIO", inputs, outputs, initializer=[shared_scale])
    model = helper.make_model(graph, producer_name="standalone-onnx-trial-case", opset_imports=[helper.make_opsetid("", 13)])
    onnx.checker.check_model(model)
    return model, {"tokens": [2, 5, 8], "mask": [2, 5, 1]}


__all__ = ["make_multi_io_onnx"]
