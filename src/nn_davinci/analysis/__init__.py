from .diff import GraphDiff, NodeMatch, compare_graphs, export_diff, visualize_diff
from .explain import ExplainabilityAnalyzer, ExplanationResult
from .runtime import RuntimeAnalyzer
from .static import analyze_graph
from .torchlens import TorchLensAnalyzer

ANALYZERS = {
    "static": analyze_graph,
    "runtime": RuntimeAnalyzer,
    "torchlens": TorchLensAnalyzer,
    "compare": compare_graphs,
    "explain": ExplainabilityAnalyzer,
}


def register_analyzer(name, analyzer, *, replace=False):
    if name in ANALYZERS and not replace:
        raise ValueError(f"Analyzer {name!r} is already registered")
    ANALYZERS[name] = analyzer

__all__ = [
    "ExplainabilityAnalyzer", "ExplanationResult", "GraphDiff", "NodeMatch", "RuntimeAnalyzer",
    "TorchLensAnalyzer", "analyze_graph", "compare_graphs", "export_diff", "visualize_diff",
]
