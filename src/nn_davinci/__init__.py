"""NN_DaVinci public API."""

from .version import __version__

from .api import (
    capture_runtime,
    draw,
    explain_model,
    load_graph,
    render,
    render_project,
    render_scene,
    scene_from_graph,
    semantic_view,
)
from .architecture_evidence import (
    ArchitectureEvidence,
    ArchitectureRole,
    CriticalRoute,
    RepeatedStructure,
    derive_architecture_evidence,
)
from .architecture_parity import (
    validate_figure_scene_architecture_parity,
    validate_landed_architecture_parity,
)
from .figure_ir import FigureIR, FigureObject, FigurePage, FigurePanel, new_figure
from .ir import Edge, GraphIR, Node, Port, TensorSpec
from .operators import register_operator_type
from .project import Project
from .scene_ir import Camera, Group3D, Layer3D, Light, Object3D, Scene, new_scene
from .semantic import SemanticView, derive_semantic_view

__all__ = [
    "__version__",
    "Edge",
    "GraphIR",
    "FigureIR",
    "FigureObject",
    "FigurePage",
    "FigurePanel",
    "Node",
    "Port",
    "Project",
    "Scene",
    "Camera",
    "Light",
    "Layer3D",
    "Group3D",
    "Object3D",
    "TensorSpec",
    "SemanticView",
    "ArchitectureEvidence",
    "ArchitectureRole",
    "CriticalRoute",
    "RepeatedStructure",
    "draw",
    "capture_runtime",
    "explain_model",
    "load_graph",
    "render",
    "render_project",
    "render_scene",
    "scene_from_graph",
    "semantic_view",
    "derive_semantic_view",
    "derive_architecture_evidence",
    "validate_figure_scene_architecture_parity",
    "validate_landed_architecture_parity",
    "register_operator_type",
    "new_figure",
    "new_scene",
]
