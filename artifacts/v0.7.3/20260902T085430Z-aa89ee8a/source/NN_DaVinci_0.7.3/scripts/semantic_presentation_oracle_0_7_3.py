#!/usr/bin/env python3
"""Independent landed-file oracle for architecture-role presentation.

This module intentionally does not import NN_DaVinci.  Architecture Evidence
is read from the landed Semantic View, while SVG/PDF/TikZ/PPTX are inspected
as unrelated file formats.  In-memory Figure/Scene objects and producer PASS
booleans are never accepted as evidence.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from hashlib import sha256
import json
import math
from pathlib import Path
import re
import subprocess
from typing import Any, Iterable
import xml.etree.ElementTree as ET
import zipfile


ORACLE_VERSION = "nndv-semantic-presentation-oracle-0.7.3-1"
BINDING_PREFIX = "NNDV-PRESENTATION-BINDING "


def normalize_text(value: str) -> str:
    return re.sub(r"[\W_]+", "", value, flags=re.UNICODE).casefold()


def _semantic_number(value: Any) -> Any:
    if isinstance(value, float) and math.isfinite(value) and value.is_integer():
        return int(value)
    if isinstance(value, dict):
        return {str(key): _semantic_number(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_semantic_number(item) for item in value]
    return value


def _evidence_digest(evidence: dict[str, Any]) -> str:
    payload = dict(evidence)
    payload.pop("provenance_digest", None)
    encoded = json.dumps(_semantic_number(payload), sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha256(encoded).hexdigest()


def _block(blockers: list[dict[str, Any]], code: str, detail: str, **context: Any) -> None:
    blockers.append({"code": code, "detail": detail, **context})


def _parse_bindings(payload: str) -> list[dict[str, Any]]:
    bindings: list[dict[str, Any]] = []
    for line in payload.splitlines():
        marker = line.find(BINDING_PREFIX)
        if marker < 0:
            continue
        candidate = line[marker + len(BINDING_PREFIX) :].strip()
        if candidate.startswith("%"):
            candidate = candidate[1:].strip()
        try:
            value = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            bindings.append(value)
    return bindings


def _check_bindings(
    format_name: str,
    bindings: Iterable[dict[str, Any]],
    roles: list[dict[str, Any]],
    routes: list[dict[str, Any]],
    evidence_digest: str,
    blockers: list[dict[str, Any]],
) -> dict[str, Any]:
    items = list(bindings)
    label_by_role: dict[str, list[dict[str, Any]]] = defaultdict(list)
    route_by_id: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        role_id = item.get("architecture_role_id")
        route_id = item.get("architecture_route_id")
        if item.get("architecture_evidence_digest") not in {None, evidence_digest} and (role_id or route_id):
            _block(blockers, "stale_evidence_digest", f"{format_name} binding uses a stale evidence digest", format=format_name, binding=item)
        if role_id and item.get("kind") == "label":
            label_by_role[str(role_id)].append(item)
        if route_id:
            route_by_id[str(route_id)].append(item)
    for role in roles:
        if not label_by_role.get(role["id"]):
            _block(blockers, f"{format_name}_missing_role_binding", f"{format_name} has no label binding for role {role['id']}", role_id=role["id"])
        for item in label_by_role.get(role["id"], []):
            if item.get("architecture_role") != role["role"]:
                _block(blockers, f"{format_name}_role_binding_mismatch", f"{format_name} role type is misbound", role_id=role["id"])
            if int(item.get("repeat_count", 1)) != int(role.get("repeat_count", 1)):
                _block(blockers, f"{format_name}_repeat_count_mismatch", f"{format_name} repeat count differs from evidence", role_id=role["id"])
    for route in routes:
        landed = route_by_id.get(route["id"], [])
        if not landed:
            _block(blockers, f"{format_name}_missing_route", f"{format_name} has no primitive for route {route['id']}", route_id=route["id"])
            continue
        arrows = [item for item in landed if item.get("kind") == "arrow"]
        if not arrows:
            _block(blockers, f"{format_name}_missing_route_arrow", f"{format_name} route has no arrowhead primitive", route_id=route["id"])
            continue
        expected_endpoints = [route["source_role_id"], route["target_role_id"]]
        for item in arrows:
            if item.get("architecture_direction") != "source-to-target":
                _block(blockers, f"{format_name}_route_direction_mismatch", f"{format_name} route direction is absent or reversed", route_id=route["id"])
            if item.get("endpoint_role_ids") != expected_endpoints:
                _block(blockers, f"{format_name}_route_endpoint_mismatch", f"{format_name} route endpoints differ from evidence", route_id=route["id"])
    return {
        "binding_count": len(items),
        "bound_role_labels": len(label_by_role),
        "bound_routes": len(route_by_id),
    }


def _svg_inspection(
    path: Path,
    roles: list[dict[str, Any]],
    routes: list[dict[str, Any]],
    evidence_digest: str,
    blockers: list[dict[str, Any]],
) -> dict[str, Any]:
    root = ET.parse(path).getroot()
    view_box = [float(value) for value in root.attrib.get("viewBox", "0 0 0 0").split()]
    left, top, width, height = view_box if len(view_box) == 4 else (0.0, 0.0, 0.0, 0.0)
    labels_by_role: dict[str, list[Any]] = defaultdict(list)
    all_role_text: dict[str, list[str]] = defaultdict(list)
    bindings: list[dict[str, Any]] = []
    for element in root.iter():
        attributes = element.attrib
        role_id = attributes.get("data-architecture-role-id")
        route_id = attributes.get("data-architecture-route-id")
        if role_id or route_id:
            binding = {
                "kind": attributes.get("data-kind"),
                "architecture_role_id": role_id,
                "architecture_role": attributes.get("data-architecture-role"),
                "architecture_route_id": route_id,
                "architecture_route_role": attributes.get("data-architecture-route-role"),
                "architecture_direction": attributes.get("data-architecture-direction"),
                "architecture_evidence_digest": attributes.get("data-evidence-digest"),
                "endpoint_role_ids": json.loads(attributes.get("data-endpoint-role-ids", "[]")),
                "repeat_count": int(attributes.get("data-repeat-count", "1")),
            }
            bindings.append(binding)
        if attributes.get("data-kind") == "label" and role_id:
            labels_by_role[role_id].append(element)
            all_role_text[normalize_text("".join(element.itertext()))].append(role_id)
    for role in roles:
        expected_text = normalize_text(role["label"])
        labels = labels_by_role.get(role["id"], [])
        if not labels:
            if expected_text in all_role_text:
                _block(blockers, "svg_role_binding_mismatch", "SVG contains the expected text under the wrong role ID", role_id=role["id"])
            else:
                _block(blockers, "svg_missing_role_label", "SVG is missing a required visible role label", role_id=role["id"])
            continue
        for label in labels:
            attributes = label.attrib
            style = attributes.get("style", "").replace(" ", "").casefold()
            hidden = (
                attributes.get("display", "").casefold() == "none"
                or attributes.get("visibility", "").casefold() == "hidden"
                or float(attributes.get("opacity", "1")) <= 0.001
                or "display:none" in style
                or "visibility:hidden" in style
                or "opacity:0" in style
            )
            if hidden:
                _block(blockers, "svg_hidden_role_label", "SVG role label exists but is not visible", role_id=role["id"])
            x = float(attributes.get("x", str(left - 1)))
            y = float(attributes.get("y", str(top - 1)))
            if x < left or x > left + width or y < top or y > top + height:
                _block(blockers, "svg_role_label_off_page", "SVG role label anchor is outside the page", role_id=role["id"], x=x, y=y)
            if normalize_text("".join(label.itertext())) != expected_text:
                _block(blockers, "svg_role_text_mismatch", "SVG visible role text differs from evidence", role_id=role["id"])
            if attributes.get("data-evidence-digest") != evidence_digest:
                _block(blockers, "stale_evidence_digest", "SVG role label uses a stale evidence digest", role_id=role["id"])
    binding_result = _check_bindings("svg", bindings, roles, routes, evidence_digest, blockers)
    return {"path": str(path), "view_box": view_box, "visible_role_ids": sorted(labels_by_role), **binding_result}


def _run_text(command: list[str]) -> tuple[str, str | None]:
    try:
        result = subprocess.run(command, text=True, capture_output=True, check=False)
    except OSError as exc:
        return "", f"{type(exc).__name__}: {exc}"
    if result.returncode:
        return result.stdout, result.stderr.strip() or f"exit {result.returncode}"
    return result.stdout, None


def _pdf_inspection(
    path: Path,
    roles: list[dict[str, Any]],
    routes: list[dict[str, Any]],
    evidence_digest: str,
    blockers: list[dict[str, Any]],
    *,
    prefix: str = "pdf",
    require_bindings: bool = True,
) -> dict[str, Any]:
    extracted, error = _run_text(["pdftotext", str(path), "-"])
    if error:
        _block(blockers, f"{prefix}_text_extraction_failed", f"pdftotext failed: {error}")
    normalized = normalize_text(extracted)
    missing = [role["id"] for role in roles if normalize_text(role["label"]) not in normalized]
    for role_id in missing:
        _block(blockers, f"{prefix}_missing_role_text", f"{prefix} extracted text omits a required role", role_id=role_id)
    raw = path.read_bytes().decode("latin-1", errors="replace")
    bindings = _parse_bindings(raw)
    binding_result = (
        _check_bindings(prefix, bindings, roles, routes, evidence_digest, blockers)
        if require_bindings
        else {
            "binding_count": len(bindings),
            "bound_role_labels": 0,
            "bound_routes": 0,
            "binding_validation": "paired-landed-tikz-source",
        }
    )
    return {"path": str(path), "extracted_text": extracted, "missing_role_ids": missing, **binding_result}


def _tikz_inspection(
    path: Path,
    roles: list[dict[str, Any]],
    routes: list[dict[str, Any]],
    evidence_digest: str,
    blockers: list[dict[str, Any]],
) -> dict[str, Any]:
    payload = path.read_text(encoding="utf-8")
    bindings = _parse_bindings(payload)
    binding_result = _check_bindings("tikz", bindings, roles, routes, evidence_digest, blockers)
    searchable = payload.replace(r"\texttimes{}", "×").replace(r"\textperiodcentered{}", "·")
    searchable = searchable.replace(r"\_", "_").replace(r"\&", "&").replace(r"\#", "#").replace(r"\%", "%")
    normalized = normalize_text(searchable)
    missing = [role["id"] for role in roles if normalize_text(role["label"]) not in normalized]
    for role_id in missing:
        _block(blockers, "tikz_missing_role_text", "TikZ source omits a required role label", role_id=role_id)
    return {"path": str(path), "missing_role_ids": missing, **binding_result}


def _pptx_inspection(
    path: Path,
    roles: list[dict[str, Any]],
    routes: list[dict[str, Any]],
    evidence_digest: str,
    blockers: list[dict[str, Any]],
) -> dict[str, Any]:
    bindings: list[dict[str, Any]] = []
    label_text: dict[str, list[str]] = defaultdict(list)
    media: list[str] = []
    namespaces = {
        "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
        "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    }
    try:
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            media = [name for name in names if name.startswith("ppt/media/")]
            slide = ET.fromstring(archive.read("ppt/slides/slide1.xml"))
    except (OSError, KeyError, zipfile.BadZipFile, ET.ParseError) as exc:
        _block(blockers, "pptx_invalid_package", f"PPTX cannot be parsed: {type(exc).__name__}: {exc}")
        return {"path": str(path), "media": media, "binding_count": 0}
    if media:
        _block(blockers, "pptx_flattened_media", "PPTX contains flattened media instead of editable primitives", media=media)
    for shape in [*slide.findall(".//p:sp", namespaces), *slide.findall(".//p:cxnSp", namespaces)]:
        descriptor = shape.find(".//p:cNvPr", namespaces)
        if descriptor is None or not descriptor.attrib.get("descr"):
            continue
        try:
            binding = json.loads(descriptor.attrib["descr"])
        except json.JSONDecodeError:
            continue
        if not isinstance(binding, dict):
            continue
        bindings.append(binding)
        if binding.get("kind") == "label" and binding.get("architecture_role_id"):
            label_text[str(binding["architecture_role_id"])].append("".join(item.text or "" for item in shape.findall(".//a:t", namespaces)))
    for role in roles:
        texts = label_text.get(role["id"], [])
        if not texts:
            _block(blockers, "pptx_missing_role_label", "PPTX has no editable text shape for a required role", role_id=role["id"])
        elif all(normalize_text(text) != normalize_text(role["label"]) for text in texts):
            _block(blockers, "pptx_role_text_mismatch", "PPTX role label text differs from evidence", role_id=role["id"])
    binding_result = _check_bindings("pptx", bindings, roles, routes, evidence_digest, blockers)
    return {"path": str(path), "media": media, "editable_role_ids": sorted(label_text), **binding_result}


def inspect_case(
    case_dir: Path,
    *,
    require_pptx: bool = True,
    require_tikz_pdf: bool = False,
    tikz_pdf_root: Path | None = None,
) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    semantic_path = case_dir / "semantic.semantic.json"
    try:
        semantic = json.loads(semantic_path.read_text(encoding="utf-8"))
        evidence = semantic["architecture_evidence"]
    except (OSError, KeyError, json.JSONDecodeError, TypeError) as exc:
        _block(blockers, "missing_architecture_evidence", f"landed Semantic View cannot be read: {type(exc).__name__}: {exc}")
        return {"status": "FAIL", "case_dir": str(case_dir), "blockers": blockers}
    expected_digest = _evidence_digest(evidence)
    if evidence.get("provenance_digest") != expected_digest:
        _block(blockers, "evidence_digest_invalid", "landed Architecture Evidence digest is stale or tampered")
    roles = list(evidence.get("detected_roles", []))
    routes = list(evidence.get("critical_routes", []))
    inspections: dict[str, Any] = {}
    required = {"svg": case_dir / "scene.svg", "pdf": case_dir / "scene.pdf", "tikz": case_dir / "scene.tex"}
    if require_pptx:
        required["pptx"] = case_dir / "scene.pptx"
    for format_name, path in required.items():
        if not path.is_file():
            _block(blockers, f"missing_{format_name}_artifact", f"required landed {format_name} artifact is absent", path=str(path))
    if required["svg"].is_file():
        inspections["svg"] = _svg_inspection(required["svg"], roles, routes, expected_digest, blockers)
    if required["pdf"].is_file():
        inspections["pdf"] = _pdf_inspection(required["pdf"], roles, routes, expected_digest, blockers)
    if required["tikz"].is_file():
        inspections["tikz"] = _tikz_inspection(required["tikz"], roles, routes, expected_digest, blockers)
    if require_pptx and required["pptx"].is_file():
        inspections["pptx"] = _pptx_inspection(required["pptx"], roles, routes, expected_digest, blockers)
    tikz_pdf = (tikz_pdf_root / case_dir.name / "scene-tikz.pdf") if tikz_pdf_root is not None else case_dir / "scene-tikz.pdf"
    if require_tikz_pdf:
        if not tikz_pdf.is_file():
            _block(blockers, "missing_tikz_pdf_artifact", "compiled TikZ PDF is absent", path=str(tikz_pdf))
        else:
            inspections["tikz_pdf"] = _pdf_inspection(
                tikz_pdf,
                roles,
                [],
                expected_digest,
                blockers,
                prefix="tikz_pdf",
                require_bindings=False,
            )
    return {
        "status": "PASS" if not blockers else "FAIL",
        "oracle_version": ORACLE_VERSION,
        "case_dir": str(case_dir),
        "family": evidence.get("family"),
        "evidence_digest": expected_digest,
        "expected_role_count": len(roles),
        "expected_route_count": len(routes),
        "inspections": inspections,
        "blockers": blockers,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case_dirs", nargs="+", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--allow-failures", action="store_true")
    parser.add_argument("--no-pptx", action="store_true")
    parser.add_argument("--require-tikz-pdf", action="store_true")
    parser.add_argument(
        "--tikz-pdf-root",
        type=Path,
        help="root containing <case-name>/scene-tikz.pdf compiled proof artifacts",
    )
    args = parser.parse_args()
    cases = [
        inspect_case(
            path,
            require_pptx=not args.no_pptx,
            require_tikz_pdf=args.require_tikz_pdf,
            tikz_pdf_root=args.tikz_pdf_root,
        )
        for path in args.case_dirs
    ]
    report = {
        "schema_version": "nndv-0.7.3-semantic-presentation-report-1",
        "oracle_version": ORACLE_VERSION,
        "status": "PASS" if all(item["status"] == "PASS" for item in cases) else "FAIL",
        "case_count": len(cases),
        "cases": cases,
    }
    encoded = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    print(encoded, end="")
    return 0 if report["status"] == "PASS" or args.allow_failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
