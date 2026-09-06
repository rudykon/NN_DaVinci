from __future__ import annotations

from pathlib import Path
from typing import Any

from ..errors import OptionalDependencyError
from ..ir import Edge, GraphIR, Node, Port, Subgraph, TensorSpec, stable_id
from .base import Adapter, Capability
from .onnx import _category


class KerasAdapter(Adapter):
    name = "keras"
    extensions = (".keras", ".h5", ".hdf5")
    priority = 7
    capabilities = (
        Capability("functional-graph"), Capability("shapes"), Capability("parameters"), Capability("module-hierarchy"),
    )

    def accepts(self, source: Any) -> bool:
        return source.__class__.__module__.startswith(("keras", "tensorflow")) or super().accepts(source)

    def load(self, source: Any, **options: Any) -> GraphIR:
        try:
            import keras
        except ImportError as exc:
            raise OptionalDependencyError(
                "Keras import requires a configured Keras backend",
                hint="Install nn-davinci[keras] and set KERAS_BACKEND if needed.",
            ) from exc
        model = source if not isinstance(source, (str, Path)) else keras.models.load_model(source, compile=False)
        nodes: list[Node] = []
        by_layer: dict[Any, Node] = {}
        for index, layer in enumerate(model.layers):
            node_id = stable_id("node", f"keras:{layer.name}:{index}")
            layer_inputs = _layer_tensors(layer, "input")
            layer_outputs = _layer_tensors(layer, "output")
            input_specs = self._specs(layer_inputs, node_id, "input")
            output_specs = self._specs(layer_outputs, node_id, "output")
            parameters = int(layer.count_params())
            trainable = sum(_elements(getattr(item, "shape", ())) for item in layer.trainable_weights)
            config = layer.get_config() if hasattr(layer, "get_config") else {}
            nodes.append(Node(
                id=node_id, name=layer.name, op_type=layer.__class__.__name__, category=_category(layer.__class__.__name__),
                path=layer.name, inputs=input_specs, outputs=output_specs, parameters=parameters,
                trainable_parameters=trainable, attributes={**config, "call_sites": len(getattr(layer, "_inbound_nodes", []))},
                source={"format": "keras", "index": index},
            ))
            by_layer[layer] = nodes[-1]
        edges: list[Edge] = []
        tensor_producers: dict[int, tuple[Node, Port]] = {}
        for layer, node in by_layer.items():
            for tensor, port in zip(_layer_tensors(layer, "output"), node.outputs):
                tensor_producers[id(tensor)] = (node, port)
        for layer, node in by_layer.items():
            for tensor, port in zip(_layer_tensors(layer, "input"), node.inputs):
                producer = tensor_producers.get(id(tensor))
                if producer and producer[0].id != node.id:
                    edges.append(Edge.create(producer[0].id, node.id, source_port=producer[1].id, target_port=port.id, tensor=port.tensor))
        nested = [layer for layer in model.layers if hasattr(layer, "layers") and layer is not model]
        groups = [
            Subgraph(
                stable_id("group", f"keras:{layer.name}"),
                layer.name,
                [by_layer[layer].id],
                level="module",
                attributes={"path": layer.name, "nested_model": True, "nested_layer_count": len(layer.layers)},
            )
            for layer in nested
        ]
        shared_layers = {
            layer.name: len(getattr(layer, "_inbound_nodes", []))
            for layer in model.layers
            if len(getattr(layer, "_inbound_nodes", [])) > 1
        }
        return GraphIR(
            name=getattr(model, "name", "Keras model"), nodes=nodes, edges=edges,
            subgraphs=groups,
            metadata={
                "source_format": "keras",
                "model_class": model.__class__.__qualname__,
                "shared_layers": shared_layers,
                "nested_models": [layer.name for layer in nested],
            },
        )

    @staticmethod
    def _specs(value: Any, node_id: str, direction: str) -> list[Port]:
        result = []
        for index, tensor in enumerate(_flatten(value)):
            shape = [int(dim) if dim is not None else None for dim in getattr(tensor, "shape", [])]
            spec = TensorSpec(name=getattr(tensor, "name", f"{direction}_{index}"), shape=shape, dtype=str(getattr(tensor, "dtype", "unknown")))
            result.append(Port(f"{node_id}:{direction}:{index}", spec.name, direction, spec))
        return result


def _flatten(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, dict):
        return [item for child in value.values() for item in _flatten(child)]
    if isinstance(value, (tuple, list)):
        return [item for child in value for item in _flatten(child)]
    return [value]


def _layer_tensors(layer: Any, direction: str) -> list[Any]:
    attribute = "input_tensors" if direction == "input" else "output_tensors"
    values: list[Any] = []
    for inbound in getattr(layer, "_inbound_nodes", []):
        values.extend(_flatten(getattr(inbound, attribute, None)))
    if not values:
        try:
            values = _flatten(getattr(layer, direction, None))
        except (AttributeError, ValueError):
            values = []
    unique: list[Any] = []
    seen: set[int] = set()
    for value in values:
        if id(value) not in seen:
            unique.append(value)
            seen.add(id(value))
    return unique


def _elements(shape: Any) -> int:
    result = 1
    for item in shape:
        if item is None:
            return 0
        result *= int(item)
    return result
