# Tensor Geometry

Tensor Geometry turns recorded tensor shapes into editable 2-D/isometric vector glyphs. Each block is made from explicit SVG/PDF/TikZ/PPTX polygons. It does not use CSS `perspective`, and it does not infer a missing dimension.

## Supported tensor forms

| Form | Layout | Example |
| --- | --- | --- |
| feature map | `NCHW`, `NHWC` | `[1, 64, 56, 56]` |
| sequence | `BTD` | `[1, 197, 768]`, `[B, T, D]` |
| matrix | `matrix` | `[M, N]` |
| vector | `vector` | `[D]` |
| scalar | `scalar` | `[]` |

`auto` maps rank 4 to NCHW, rank 3 to BTD, rank 2 to matrix, rank 1 to vector and rank 0 to scalar. Choose NHWC explicitly when the source records that layout. Multiple input/output glyphs use the same geometry compiler and retain independent shapes.

Dynamic batch, symbolic sequence and unknown dimensions remain symbols or `?`. For example, `[null, "T", 768]` renders as `[?, T, 768]`. Unknown axes use a neutral visual extent and are listed in geometry metadata; they are never replaced by guessed numbers.

## Visual scaling

The available mappings are `linear`, `sqrt`, `log`, `normalized` and `manual`. They affect only polygon extents. Metadata always includes:

- `scale_is_visual_only=true`;
- the selected scale mode and axis mapping;
- the evidence-backed model shape and source label;
- unknown visual axes;
- a legend note explaining that labels are authoritative.

Manual mode requires positive width, height and depth. It is useful for a consistent visual rhythm across Panels, but it still leaves the numeric/symbolic source shape untouched.

Figure Studio permits the required shape-label edit without rewriting a model fact. For an evidence-backed tensor, the control stores `author_shape_override`, its exact `author_shape_override_label`, and `shape_label_origin=author_override`; `tensor_shape`, `shape_label`, dtype, port binding, and `provenance.evidence.tensor` remain unchanged and are cross-validated. The renderer may use the override for the displayed glyph and label, but marks the SVG text `data-shape-label-origin="author_override"` and does not mark it `data-real-shape`. An author-created tensor glyph instead owns its entered shape directly. Style and visual-scale edits never change either source evidence or an author override.

## Operators and routing

Editable vector primitives are provided for convolution, pooling, upsampling, concatenation, addition, attention, normalization, routing and experts. Shape-transition records distinguish equal, changed and unknown transitions.

Skip/residual routes use bounded orthogonal detours. Template routing separates branches and merges, orders tensor faces back-to-front, and uses both colour and shape/dash semantics. Figure proof checks overlap, clipping, edge-node collisions and unexplained crossings.

## Accessibility, physical scale and export

The default front/top/side faces remain distinguishable in grayscale, and data versus annotation edges differ by dash as well as semantic metadata. Required authoring text must remain at least 7 pt; the layout wraps, abbreviates with a retained full label, reallocates space or fails rather than compressing glyphs. The final Chrome calculation allows 0.01 pt only as numeric measurement tolerance, not as a smaller style value.

SVG may record `data-real-shape=true` and an intended identity transform for diagnostics, but neither is final evidence. `figure_proof()` checks compiled primitives provisionally. The release verdict comes from Chrome loading the persisted SVG and measuring the complete CTM, rendered bounds, natural text advance and effective font/stroke sizes. Thus a declared scale of 1 is a producer claim; the measured horizontal/vertical scales and singular values are authoritative.

The same millimetre/point primitives feed all seven outputs:

- SVG polygons plus digest-bound Figure IR metadata;
- PDF vector pages with embedded/extractable fonts;
- standalone editable TikZ with defined colours;
- editable PPTX freeforms, text boxes and connectors, not a full-page bitmap;
- 300-DPI RGBA PNG with physical-resolution metadata;
- vector EPSF Level 3 through SVG→PDF→Poppler, with raster fallback rejected;
- dependency-free HTML containing the corrected SVG pages and canonical Figure source.

The fresh full gate generates the same 14-Figure corpus in all seven formats, runs the independent SVG oracle, then registers object positions across SVG, PDF and compiled TikZ PDF. Each compared key position must differ by at most 1 mm, with physical Page-size error at most 0.05 mm:

```bash
./scripts/verify-full-0.6.1.sh
```

## Key implementation paths

- `src/nn_davinci/tensor_geometry.py`
- `src/nn_davinci/units.py`
- `src/nn_davinci/figure_export.py`
- `tests/test_tensor_geometry.py`
- `scripts/validate_cross_format_positions_0_6_1.py`
- `scripts/figure_svg_oracle.mjs`
