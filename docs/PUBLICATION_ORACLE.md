# Publication oracle

NN_DaVinci 0.6.1 uses an independent Chrome oracle as the release-blocking authority for final Figure SVG geometry. The oracle opens persisted SVG files and measures the rendered DOM; it does not import Python proof output or trust producer assertions embedded in metadata/data attributes.

## Authority boundary

The two proof layers have different jobs:

| Layer | Input | Purpose | Release authority |
|---|---|---|---|
| `figure_proof()` | compiled Figure IR primitives | deterministic early feedback and diagnostics | provisional only; `final_output_verified=false`, `release_blocker_eligible=false` |
| `figure_svg_oracle.mjs` | persisted final SVG file loaded in Chrome | independent rendered geometry and font/CTM measurement | authoritative for final-SVG geometry |

The Chrome oracle declares:

```json
{
  "final_dom_only": true,
  "metadata_trusted": false,
  "python_proof_imported": false,
  "data_scale_claims_trusted": false,
  "stroke_under_full_ctm": true,
  "path_flattener": "svg_path_flatten.js"
}
```

Figure metadata remains useful for source round trip and object identity, but a metadata `pass`, claimed minimum font, `data-font-size-pt` or claimed transform scale cannot change an oracle verdict.

## Persisted-input and freshness contract

Each SVG is opened through a local `file:` URL in a new browser context. HTTP(S) requests are blocked, `document.fonts.ready` is awaited, console/page errors are collected, and the file SHA-256 is recorded. A release corpus validator compares the oracle hashes against the exact SVG hashes emitted by the fresh export job.

The 0.6.1 publication corpus contains 14 final SVG inputs: seven bundled templates and seven distinct fixed-seed offline model-derived Figures. The validator requires exactly 14 measured files, 14 passes, zero geometry issues, zero browser errors and exact hash multiset equality. A template cannot stand in for its similarly named model artifact.

There is also a deliberately failing historical control. The full driver resolves exactly the seven persisted `exports/figure-templates/<slug>/figure.svg` files from authoritative 0.6.0 run `20260829T183558Z-09a7930b`, verifies each byte hash against its pinned manifest, and passes those files—not regenerated equivalents—to the same Chrome oracle with `--allow-failures`. The expected classification is exactly 0 passed and 7 failed with at least one measured issue. In the pinned release environment the observed total is 341 issues. The raw report and its per-template hash/issue summary are stored in the fresh 0.6.1 artifact.

This control documents why the old 0.6.0 `figure_proof()` PASS cannot be trusted as final-output evidence. It is diagnostic and read-only: it cannot help a 0.6.1 Figure pass, and it never changes the old artifact.

## Browser measurements

The oracle uses `getBBox()`, `getBoundingClientRect()`, computed style and the complete element/root CTMs. It records Page/Panel bounds; local and screen text bounds; computed and natural text advances; effective font points; horizontal/vertical CTM scale; singular-value transform shape; orthogonality/rotation; font family/load/fallback state; per-element effective minimum/maximum stroke points and CTM singular scales; shape components; flattened edge points; marker bounds; opacity/visibility; and Page occupancy.

The strict default thresholds are:

| Metric | Threshold |
|---|---:|
| effective text size | 7 pt, with 0.01 pt numeric measurement tolerance |
| effective stroke width | strict release gate: reported minimum ≥0.1 pt |
| horizontal CTM scale | 0.98–1.02 |
| vertical CTM scale | 0.98–1.02 |
| singular-value transform shape | 0.98–1.02 |
| Page bounding-box occupancy | 0.02–0.98 |

Natural text advance is remeasured on a hidden clone after removing `textLength`, `lengthAdjust`, text transforms, font stretch/variation and letter spacing. This lets the oracle detect glyph compression even when the element CTM appears nominal.

Physical stroke styles use the exact conversion in [UNIT_SYSTEM](UNIT_SYSTEM.md). The oracle derives `effective_stroke_pt` and `effective_stroke_maximum_pt` from computed width and both singular values of the complete screen CTM. For `vector-effect=non-scaling-stroke`, computed width is already in screen CSS pixels and the CTM scale is one. It reports per-stroke CTMs plus summary minimum/maximum. The raw JavaScript diagnostic uses a 0.01 pt round-off guard when emitting `STROKE_TOO_THIN`; the strict release validator nevertheless requires the reported minimum itself to be ≥0.1 pt. Raw producer attributes or the Python helper alone are not final-output evidence.

## Geometry checks

The oracle treats rendered semantic leaf objects rather than generator rectangles as authority. Its current issue taxonomy covers:

- text below 7 pt, strict-release reported effective strokes below 0.1 pt, unintended CTM scaling/shear, glyph compression, unloaded/fallback fonts, hidden/transparent/zero-size text;
- text outside its owner, Page or Panel; text-text, text-shape and Panel-label/title collisions;
- hidden/transparent/zero-size/off-Page/off-Panel graphics and shape-shape overlap;
- complete polyline/path segments crossing unrelated node or tensor shapes;
- edge-edge crossings, edge Panel clipping and marker Page/Panel clipping;
- Page bounding-box occupancy outside the declared interval;
- browser runtime and oracle measurement errors.

Curves are flattened by the separate `scripts/svg_path_flatten.js` implementation to a bounded screen-space tolerance before collision/crossing checks. End-point contact with the declared source/target object is allowed; an edge passing through an unrelated object is not. All edge pairs and all flattened segments are considered, not only hand-authored interior waypoints.

## Adversarial truth suite

`verification/fixtures/figure-svg-oracle-expectations.json` defines 21 persisted fixtures: 2 expected passes and 19 expected failures. It has 44 metric assertions and 25 coverage labels. Exact issue-count equality is required; merely returning a failure is insufficient.

The suite covers a valid document, CJK/math text, a 1,000-character caption, a long node name, adjacent shape labels, local 6 pt CSS, transformed text, `textLength` compression, a polyline through a node, a curve through a tensor polygon, caption/Panel clipping, Panel-label/title collision, hidden/transparent/zero/off-Page text, font fallback, second-Page clipping, node/tensor overlap, text/shape collision, edge crossing, marker/edge clipping, Page occupancy and an off-Page object.

The generator deliberately writes misleading producer proof and scale attributes into fixtures. The validator confirms that the oracle ignores them.

The historical seven-SVG control is separate from these 21 synthetic fixtures. Fixtures test known oracle classifications; the historical control binds the repaired authority boundary to real persisted 0.6.0 publication outputs.

## Reports and commands

The raw report schema is `nndv-figure-svg-oracle-report-1`; fixture validation uses `nndv-figure-svg-oracle-fixture-validation-1`; fresh-corpus binding uses `nndv-0.6.1-strict-publication-svg-validation-1`.

The release driver runs the equivalent of:

```bash
python scripts/generate_figure_svg_oracle_fixtures.py <fixtures>

NNDV_BROWSER=/usr/bin/google-chrome \
NNDV_PLAYWRIGHT_MODULE=<playwright-core-index.mjs> \
node scripts/figure_svg_oracle.mjs --allow-failures \
  --output <fixture-oracle.json> <fixtures>/*.svg

python scripts/validate_figure_svg_oracle_fixtures.py \
  <fixture-oracle.json> --output <fixture-validation.json>

node scripts/figure_svg_oracle.mjs \
  --output <publication-oracle.json> <fresh-final-svg-files>

python scripts/validate_strict_figure_oracle_0_6_1.py \
  --oracle-report <publication-oracle.json> \
  --export-report <fresh-export-report.json> \
  --output <strict-validation.json>

node scripts/figure_svg_oracle.mjs --allow-failures \
  --output <authoritative-0.6.0-oracle.json> <seven-pinned-v0.6.0-svg-files>
```

Paths are supplied explicitly by the release driver. Fresh fixture/production inputs come only from the clean 0.6.1 run; the separately labelled historical inputs are resolved only from the pinned read-only artifact and are hash-checked before their negative verdict is accepted.

## Format and human-evidence boundary

This oracle authorizes only final SVG geometry. PDF font embedding/extractability, TikZ compilation, PPTX editability, PNG DPI/alpha metadata, EPS vector/font resources and HTML offline/source preservation require their own checks. It does not verify the scientific truth of an author's caption or architectural interpretation.

Chrome automation is machine evidence. NN_DaVinci 0.6.1 has 0 human participants and all human time, success, ease/learnability and semantic-review metrics are null/N/A. An oracle pass cannot be reported as human usability evidence.

Maintainer `view_image` inspection of generated proof PNGs is a visual diagnostic only. It can reveal obvious crops or unreadable composition, but it is neither a human-participant session nor a replacement for the persisted-SVG Chrome oracle, format validators or recorded hashes.
