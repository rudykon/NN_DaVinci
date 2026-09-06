# NN_DaVinci 0.7.2 PDF font report

## Result boundary

0.7.2 replaces Scene PDF reliance on viewer-provided Base-14 fonts with packaged TrueType font programs. Native Scene PDFs use Type0/CID dictionaries, Identity-H encoding and ToUnicode maps so text remains embedded, searchable and Unicode-mappable in offline output.

Only the publication oracle inside a fresh `artifacts/v0.7.2/<run_id>` owns the final PASS. This document records the implementation and acceptance contract without predeclaring an artifact result.

## Packaged font contract

The wheel and sdist include:

| Asset | Purpose | License evidence |
|---|---|---|
| `NotoSans-Regular.ttf` | primary Latin/general Scene PDF text | `licenses/Noto-OFL-1.1.txt` |
| `DroidSansFallbackFull.ttf` | broad Unicode fallback | `licenses/Droid-Apache-2.0.txt` |
| `NotoSansMath-Regular.ttf` | mathematical-symbol fallback | `licenses/Noto-OFL-1.1.txt` |

The release audit rejects a missing or empty font or license file. Packaging verification installs both wheel and sdist offline and checks that package data, web assets and templates remain available.

## Fourteen-case acceptance

The publication oracle examines the seven real-model and seven template PDFs independently. For every native `scene.pdf`, it requires:

- at least one embedded font program;
- all reported fonts embedded and Unicode-mappable;
- no Base-14 fallback;
- Type0/CID TrueType with Identity-H for the native Scene font;
- a valid page size, searchable required labels and no missing labels;
- no text overlap, boundary contact or rasterized boundary ink failure.

The same oracle compiles all fourteen `scene.tex` files offline and checks the resulting PDFs for embedded, Unicode-mappable fonts, expected labels, page geometry and empty failure lists. TikZ compilation is a separate contract from the native PDF font implementation: a TeX-generated subset font is acceptable when it is embedded and maps text correctly.

| Corpus group | Native PDFs | Expected native font result | Offline TikZ compilations |
|---|---:|---|---:|
| Seven real models | 7 | embedded CID TrueType, Identity-H, Unicode, zero Base-14 | 7 |
| Seven Scene templates | 7 | embedded CID TrueType, Identity-H, Unicode, zero Base-14 | 7 |
| Total | 14 | all cases must pass | 14 |

## Evidence paths

In a fresh artifact, the authoritative aggregate is `reports/visual/scene-publication-oracle.json`. Each case contains `publication.pdf`, `publication.tikz_compiled_pdf` and its failure list. The native files are under `exports/scene-corpus/{real-models,templates}/<case>/scene.pdf`; the matching TikZ sources are adjacent as `scene.tex`.

Direct tests cover embedded font descriptors, Type0/CID structure, ToUnicode maps, Base-14 rejection and Unicode label extraction. The strict SVG oracle remains separate, so a font PASS cannot hide clipping, collision or framing failures in another format.

## Known limits

Font embedding establishes portable text resources and mapping; it is not a claim that every possible Unicode code point is available. Unsupported glyphs must use an installed packaged fallback or fail visibly. The report contains no human readability or usability measurement, and automated inspection is not counted as human evidence.
