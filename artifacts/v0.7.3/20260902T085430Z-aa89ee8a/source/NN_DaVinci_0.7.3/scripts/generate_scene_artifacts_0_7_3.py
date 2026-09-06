#!/usr/bin/env python3
"""Generate the fresh NN_DaVinci 0.7.3 fourteen-case Scene corpus."""

from __future__ import annotations

import os
from pathlib import Path
import runpy


os.environ["NNDV_CORPUS_VERSION"] = "0.7.3"
os.environ["NNDV_CORPUS_RELEASE"] = "0.7.3 — Reader-Visible Scientific Completeness & Generalization Hotfix"
os.environ["NNDV_CORPUS_SCHEMA"] = "nndv-0.7.3-scene-artifact-corpus-1"
os.environ["NNDV_COMPARISON_SCHEMA"] = "nndv-0.7.3-2d-3d-comparison-1"
runpy.run_path(str(Path(__file__).with_name("generate_scene_artifacts_0_7_2.py")), run_name="__main__")
