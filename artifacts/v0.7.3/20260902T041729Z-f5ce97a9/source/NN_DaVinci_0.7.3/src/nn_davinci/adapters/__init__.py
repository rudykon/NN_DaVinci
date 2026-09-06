from .base import Adapter, AdapterRegistry, Capability, registry
from .config import PythonConfigAdapter
from .jax import JaxAdapter, MlirAdapter
from .keras import KerasAdapter
from .manual import ManualAdapter
from .onnx import OnnxAdapter
from .pytorch import PyTorchAdapter
from .tensorflow import TensorFlowAdapter

for _adapter in (ManualAdapter(), PythonConfigAdapter(), OnnxAdapter(), PyTorchAdapter(), KerasAdapter(), TensorFlowAdapter(), JaxAdapter(), MlirAdapter()):
    registry.register(_adapter)

__all__ = ["Adapter", "AdapterRegistry", "Capability", "registry"]
