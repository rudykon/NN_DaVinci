# Figure Studio unit system

This document is the normative physical-unit contract for NN_DaVinci 0.6.1 Figure IR and its exporters.

## Authoring units

Figure geometry is stored in millimetres. Page and Panel extents, object rectangles, tensor polygons, routes, margins, gaps and snap coordinates therefore use `mm`. Public typography and line-style values use PostScript points: font size, line width, corner radius, arrow size, baseline grid and line height are expressed in `pt`.

The exact conversion constants are:

```text
1 inch = 25.4 mm
1 inch = 72 pt
1 inch = 96 CSS px

1 pt     = 25.4 / 72 mm = 4 / 3 CSS px
1 CSS px = 25.4 / 96 mm = 3 / 4 pt
```

The implementation is centralized in `src/nn_davinci/units.py`. Renderers must use `pt_to_mm`, `mm_to_pt`, `css_px_to_mm`, `mm_to_css_px`, `pt_to_css_px` and `css_px_to_pt` instead of duplicating rounded conversion factors. Python's provisional diagnostics use `ctm_scales`, `effective_font_pt` and `effective_stroke_pt`. The independent JavaScript oracle shares the exact unit constants but does not import those helpers or verdicts; for final strokes it deliberately retains both singular-value extrema instead of reducing them to one provisional value.

## SVG coordinate contract

A Figure SVG declares physical `width` and `height` in millimetres and a `viewBox` whose user units are the same millimetres. Physical style values are converted before serialization:

- a font requested as 9 pt is serialized as `9 × 25.4 / 72` SVG user units;
- a line requested as 0.8 pt is serialized as `0.8 × 25.4 / 72` user units;
- corner radii and arrow-marker geometry follow the same point-to-millimetre rule;
- NN_DaVinci does not use `vector-effect="non-scaling-stroke"` for its own physical strokes.

The source attribute alone is not proof of the final physical value. Ancestor transforms, nested `viewBox` mappings and CSS can change the rendered result.

## Final CTM measurement

The release oracle opens the serialized SVG in Chrome and reads each relevant element's complete current transformation matrix (CTM). For the 2×2 linear component

```text
[ a c ]
[ b d ]
```

the local axis magnitudes are:

```text
scale_x = sqrt(a² + b²)
scale_y = sqrt(c² + d²)
```

Singular values expose rotation-independent anisotropy and singular transforms. Reflection orientation would require the determinant sign and is not inferred from singular values alone. For a numeric font size stored in millimetre user units, the effective vertical size is:

```text
effective_font_pt = font_size_user × scale_y × 72 / 96
```

because Chrome's CTM maps local user units to CSS pixels. Python's provisional `effective_stroke_pt` helper uses the geometric mean of the two singular values. The final Chrome oracle instead records `computed_width × sigma_min` and `computed_width × sigma_max` after CSS-pixel-to-point conversion; this exposes a thin axis under anisotropic scaling. Its raw diagnostic allows 0.01 pt solely for numeric round-off when emitting an issue, while the strict release validator requires the reported minimum itself to be ≥0.1 pt. A foreign SVG with a non-scaling stroke is measured in CSS pixels without applying the element CTM. The oracle separately rejects singular or unintended anisotropic text transforms.

`getBBox()` supplies local rendered geometry; `getBoundingClientRect()` and CTMs supply viewport geometry. The strict oracle uses both rather than trusting generator-side bounding boxes.

## Typography contract

`src/nn_davinci/text_layout.py` supplies deterministic line breaking and a conservative Unicode-aware advance model shared by the Figure exporters. It supports manual newlines, Latin text, CJK characters, Greek/math symbols and other Unicode scripts. Each text primitive records:

- requested font families and the emitted CSS stack;
- detected scripts;
- ordered fallback candidates;
- line strings, baselines, physical lane and measured bounds;
- requested font size and line height.

The fallback record is reproducible, but the actual installed font selected by a renderer remains environment-dependent and is therefore checked in the final output. Bundled release environments use the declared local fallback stack and verify embedded/subset fonts where the format supports that check.

NN_DaVinci does not use `textLength`, `lengthAdjust`, a horizontal glyph scale or a silent font-size reduction to force text into a box. Required authoring text must remain at least 7 pt. The final oracle allows a 0.01 pt numerical tolerance for CTM/CSS-pixel round-off; it does not permit a requested/local style below 7 pt. The deterministic placement policy is:

1. preserve manual line breaks;
2. wrap at safe break opportunities and, when necessary, Unicode code-point boundaries;
3. use an explicit short visible label while retaining the full name in metadata/legend;
4. enlarge or rearrange the lane/page when the caller authorizes it;
5. otherwise fail with an actionable message.

A lane that cannot hold the requested text at or above the configured minimum is an export error, not a reason to compress glyphs.

## Backend mapping

| Backend | Physical mapping |
|---|---|
| SVG | millimetre canvas/viewBox; point styles converted to millimetre user units |
| PDF | generated page-by-page from corrected SVG; each PDF page retains its own physical size |
| TikZ | millimetre coordinates plus explicit `pt` line widths and `\fontsize{...}{...}\selectfont` |
| PPTX | millimetre geometry converted to EMU; font size remains an editable point value |
| PNG | corrected page SVG rasterized at 300 DPI with embedded physical-resolution metadata |
| EPS | corrected SVG converted through vector PDF to EPSF Level 3; raster fallback is rejected |
| HTML | corrected per-page SVG DOM embedded in an offline viewer with canonical Figure IR source |

At 300 DPI a 178×118 mm Page rasterizes to approximately 2103×1394 pixels (the width may be 2102 or 2103 after the backend's integral-pixel rounding). PNG acceptance checks those pixels, RGBA mode and embedded 300-DPI metadata. Across the 14-Figure corpus, registered key positions in final PDF and compiled TikZ PDF must be within 1 mm of the final SVG, and physical Page-size error must be at most 0.05 mm.

## Proof authority

`figure_proof()` is a deterministic compiled-IR estimate for fast feedback. It reports `final_output_verified=false`, `release_blocker_eligible=false` and null final CTM scale fields. It must never be presented as final-output proof.

The independent Chrome final-SVG oracle is the release-blocking geometry authority. It reads only landed SVG files and expectation manifests, and checks effective units, transforms, text/graphic conflicts, overflow, Page/Panel clipping, full-segment edge/object collisions, all edge crossings, marker clipping, zero-size/transparent objects and adversarial fixtures. Generator metadata may identify objects, but it cannot override measured geometry.

This authority split addresses two historical 0.6.0 failure modes: treating point-valued styles as if they were already millimetre SVG user units, and reporting an intended text scale/provisional `figure_proof()` PASS without measuring the complete landed CTM. The seven persisted 0.6.0 publication SVGs are therefore expected negative controls under the 0.6.1 oracle, not grandfathered passes.

PDF font embedding/extractability, TikZ compilation, PPTX editability, PNG DPI/alpha semantics, EPS vector/font resources and HTML offline/source preservation are additional format-specific checks. Passing SVG geometry alone does not imply those format contracts passed.
