#!/usr/bin/env python3
"""Independently validate the NN_DaVinci 0.7.3 fourteen-case Scene corpus."""

from __future__ import annotations

import os
from pathlib import Path
import runpy


os.environ["NNDV_VALIDATION_SCHEMA"] = "nndv-0.7.3-scene-artifact-validation-1"
os.environ["NNDV_CORPUS_SCHEMA"] = "nndv-0.7.3-scene-artifact-corpus-1"
os.environ["NNDV_COMPARISON_SCHEMA"] = "nndv-0.7.3-2d-3d-comparison-1"
runpy.run_path(str(Path(__file__).with_name("validate_scene_artifacts_0_7_2.py")), run_name="__main__")
