from __future__ import annotations

import tempfile
import unittest
from pathlib import Path


class CompatibilityMatrixTests(unittest.TestCase):
    def test_01_pytorch_torchvision_resnet18_shapes_parameters_and_hierarchy(self):
        import torch
        from torchvision.models import resnet18

        from nn_davinci.adapters.pytorch import PyTorchAdapter

        model = resnet18(weights=None).eval()
        graph = PyTorchAdapter().load(model, sample_input=torch.zeros(1, 3, 64, 64)).validate()
        self.assertEqual(graph.metadata["source_format"], "pytorch_fx")
        self.assertEqual(sum(node.parameters for node in graph.nodes), 11_689_512)
        self.assertTrue(any(node.outputs and node.outputs[0].tensor for node in graph.nodes))
        self.assertTrue(any(group.attributes.get("path", "").startswith("layer") for group in graph.subgraphs))
        self.assertGreater(len(graph.edges), 20)

    def test_02_pytorch_shared_dynamic_nested_and_torchscript(self):
        import torch

        from nn_davinci.adapters.pytorch import PyTorchAdapter

        class SharedDynamic(torch.nn.Module):
            def __init__(self):
                super().__init__()
                self.projection = torch.nn.Linear(4, 4)

            def forward(self, value):
                first = self.projection(value)
                if bool((first.sum() > -1000).item()):
                    return self.projection(first)
                return first

        class NestedOutput(torch.nn.Module):
            def __init__(self):
                super().__init__()
                self.projection = torch.nn.Linear(4, 2)

            def forward(self, value):
                score = self.projection(value)
                return {"score": score, "aux": (score.mean(dim=-1), score.max(dim=-1).values)}

        adapter = PyTorchAdapter()
        sample = torch.ones(1, 4)
        dynamic = adapter.load(SharedDynamic().eval(), sample_input=sample).validate()
        self.assertEqual(dynamic.metadata["source_format"], "pytorch_runtime")
        self.assertEqual(sum(node.parameters for node in dynamic.nodes), 20)
        self.assertTrue(any(node.shared_weights for node in dynamic.nodes))
        nested = adapter.load(NestedOutput().eval(), sample_input=sample).validate()
        output = next(node for node in nested.nodes if node.category == "output")
        self.assertEqual(len(output.outputs), 3)

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nested.torchscript"
            torch.jit.trace(torch.nn.Sequential(torch.nn.Linear(4, 2)).eval(), sample).save(str(path))
            scripted = adapter.load(path, sample_input=sample).validate()
            self.assertEqual(scripted.metadata["source_format"], "pytorch_torchscript")
            self.assertTrue(scripted.nodes)

    def test_03_pytorch_state_dict_is_explicitly_weights_only(self):
        import torch

        from nn_davinci.adapters.pytorch import PyTorchAdapter

        model = torch.nn.Sequential(torch.nn.Linear(4, 3), torch.nn.Linear(3, 2))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "weights.pth"
            torch.save(model.state_dict(), path)
            graph = PyTorchAdapter().load(path, allow_pickle=True).validate()
        self.assertFalse(graph.metadata["structure_available"])
        self.assertEqual(graph.metadata["representation"], "weight-groups-only")
        self.assertTrue(graph.metadata["limitations"])
        self.assertFalse(graph.edges)
        self.assertTrue(all(node.op_type == "ParameterGroup" for node in graph.nodes))

    def test_04_onnx_dynamic_control_flow_external_data_and_multi_io(self):
        import numpy as np
        import onnx
        from onnx import TensorProto, helper, numpy_helper

        from nn_davinci.adapters.onnx import OnnxAdapter

        condition = helper.make_tensor_value_info("condition", TensorProto.BOOL, [])
        value = helper.make_tensor_value_info("value", TensorProto.FLOAT, ["batch", 4])
        projected = helper.make_tensor_value_info("projected", TensorProto.FLOAT, ["batch", 4])
        looped = helper.make_tensor_value_info("looped", TensorProto.FLOAT, ["batch", 4])
        then_graph = helper.make_graph(
            [helper.make_node("Identity", ["projected"], ["then_value"], name="then_identity")],
            "then_branch",
            [],
            [helper.make_tensor_value_info("then_value", TensorProto.FLOAT, ["batch", 4])],
        )
        else_graph = helper.make_graph(
            [helper.make_node("Neg", ["projected"], ["else_value"], name="else_neg")],
            "else_branch",
            [],
            [helper.make_tensor_value_info("else_value", TensorProto.FLOAT, ["batch", 4])],
        )
        body = helper.make_graph(
            [
                helper.make_node("Identity", ["cond_in"], ["cond_out"], name="condition_passthrough"),
                helper.make_node("Identity", ["loop_in"], ["loop_out"], name="value_passthrough"),
            ],
            "loop_body",
            [
                helper.make_tensor_value_info("iteration", TensorProto.INT64, []),
                helper.make_tensor_value_info("cond_in", TensorProto.BOOL, []),
                helper.make_tensor_value_info("loop_in", TensorProto.FLOAT, ["batch", 4]),
            ],
            [
                helper.make_tensor_value_info("cond_out", TensorProto.BOOL, []),
                helper.make_tensor_value_info("loop_out", TensorProto.FLOAT, ["batch", 4]),
            ],
        )
        weight = numpy_helper.from_array(np.eye(4, dtype=np.float32), name="weight")
        trip = numpy_helper.from_array(np.asarray(2, dtype=np.int64), name="trip_count")
        initial_condition = numpy_helper.from_array(np.asarray(True, dtype=np.bool_), name="initial_condition")
        nodes = [
            helper.make_node("MatMul", ["value", "weight"], ["projected"], name="projection"),
            helper.make_node("If", ["condition"], ["selected"], name="branch", then_branch=then_graph, else_branch=else_graph),
            helper.make_node("Loop", ["trip_count", "initial_condition", "projected"], ["looped"], name="loop", body=body),
        ]
        model = helper.make_model(
            helper.make_graph(nodes, "control_flow", [condition, value], [projected, looped], [weight, trip, initial_condition]),
            opset_imports=[helper.make_opsetid("", 18)],
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "control.onnx"
            onnx.save_model(
                model,
                path,
                save_as_external_data=True,
                all_tensors_to_one_file=True,
                location="control.data",
                size_threshold=0,
            )
            self.assertTrue((Path(directory) / "control.data").exists())
            graph = OnnxAdapter().load(path).validate()
        self.assertEqual(graph.inputs[1].shape, ["batch", 4])
        self.assertEqual(len(graph.outputs), 2)
        self.assertEqual(sum(node.parameters for node in graph.nodes), 18)
        self.assertTrue(any(node.source.get("format") == "onnx_subgraph" for node in graph.nodes))
        self.assertGreaterEqual(len(graph.metadata["control_subgraphs"]), 3)
        self.assertTrue(any(edge.kind == "control" for edge in graph.edges))

    def test_05_keras_branch_residual_shared_and_nested_model(self):
        import keras

        from nn_davinci.adapters.keras import KerasAdapter

        nested_input = keras.Input(shape=(4,), name="nested_input")
        nested_output = keras.layers.Dense(4, name="nested_dense")(nested_input)
        nested = keras.Model(nested_input, nested_output, name="nested_model")
        inputs = keras.Input(shape=(4,), name="features")
        shared = keras.layers.Dense(4, name="shared_projection")
        first = shared(inputs)
        second = shared(inputs)
        residual = keras.layers.Add(name="residual_add")([first, second])
        outputs = nested(residual)
        model = keras.Model(inputs, [outputs, first], name="keras_matrix")
        graph = KerasAdapter().load(model).validate()
        self.assertEqual(graph.metadata["shared_layers"]["shared_projection"], 2)
        self.assertIn("nested_model", graph.metadata["nested_models"])
        self.assertTrue(any(group.attributes.get("nested_model") for group in graph.subgraphs))
        self.assertEqual(sum(node.parameters for node in graph.nodes), 40)
        self.assertEqual(len(graph.edges), 4)

    def test_06_tensorflow_graphdef_control_edge_savedmodel_multi_signature(self):
        import tensorflow as tf

        from nn_davinci.adapters.tensorflow import TensorFlowAdapter

        raw = tf.Graph()
        with raw.as_default():
            value = tf.compat.v1.placeholder(tf.float32, shape=[None, 4], name="value")
            prerequisite = tf.identity(value, name="prerequisite")
            with tf.control_dependencies([prerequisite]):
                tf.identity(value, name="controlled")
        graph = TensorFlowAdapter().load(raw.as_graph_def(add_shapes=True)).validate()
        self.assertTrue(any(edge.kind == "control" for edge in graph.edges))
        self.assertEqual(next(node for node in graph.nodes if node.path == "value").outputs[0].tensor.shape, [None, 4])

        class Module(tf.Module):
            @tf.function(input_signature=[tf.TensorSpec([None, 4], tf.float32)])
            def add(self, value):
                return {"output": value + 1}

            @tf.function(input_signature=[tf.TensorSpec([None, 4], tf.float32)])
            def scale(self, value):
                return {"output": value * 2}

        module = Module()
        with tempfile.TemporaryDirectory() as directory:
            tf.saved_model.save(module, directory, signatures={"add": module.add, "scale": module.scale})
            add_graph = TensorFlowAdapter().load(directory, signature="add").validate()
            scale_graph = TensorFlowAdapter().load(directory, signature="scale").validate()
        self.assertEqual(add_graph.metadata["available_signatures"], ["add", "scale"])
        self.assertEqual(add_graph.metadata["selected_signature"], "add")
        self.assertEqual(scale_graph.metadata["selected_signature"], "scale")
        self.assertTrue(add_graph.nodes and scale_graph.nodes)

    def test_07_jax_pytree_input_and_multiple_outputs(self):
        import jax.numpy as jnp

        from nn_davinci.adapters.jax import JaxAdapter

        def function(batch):
            hidden = jnp.tanh(batch["x"] @ batch["weight"])
            return hidden, {"mean": hidden.mean(axis=-1)}

        sample = {"x": jnp.ones((2, 4)), "weight": jnp.ones((4, 3))}
        graph = JaxAdapter().load(function, sample_input=sample).validate()
        self.assertEqual(graph.metadata["interface"], "callable + sample_input -> JAXPR")
        self.assertEqual(graph.metadata["sample_pytree_type"], "dict")
        self.assertEqual(graph.metadata["output_count"], 2)
        self.assertEqual(sum(node.category == "output" for node in graph.nodes), 2)
        self.assertTrue(any(node.op_type == "dot_general" for node in graph.nodes))

    def test_08_mlir_lightweight_subset_shapes_and_rejection(self):
        from nn_davinci.adapters.jax import MlirAdapter
        from nn_davinci.errors import AdapterError

        accepted = '''
        module {
          %0 = "stablehlo.constant"() : () -> tensor<2x?xf32>
          %1 = "stablehlo.add"(%0, %0) : (tensor<2x?xf32>, tensor<2x?xf32>) -> tensor<2x?xf32>
        }
        '''
        graph = MlirAdapter().load(accepted).validate()
        self.assertEqual(graph.metadata["support_level"], "lightweight-ssa-subset")
        self.assertEqual(graph.nodes[-1].outputs[0].tensor.shape, [2, None])
        with self.assertRaisesRegex(AdapterError, "Unsupported MLIR syntax"):
            MlirAdapter().load('^bb0(%arg0: tensor<2xf32>):')


if __name__ == "__main__":
    unittest.main()
