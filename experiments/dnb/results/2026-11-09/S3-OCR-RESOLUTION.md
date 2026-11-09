# S3 OCR resolution fix

2026-11-09. Candidate held; test-bed improvement only.

## Problem

The generated low-resolution image fixture `PNG fact hotel-905` was misread by
both 1.7.1 and the frozen candidate as `PNG fact hote-005`. The OCR warning was
retained, but the numeric token was lost. The image is 800x200 with very small
glyphs; Tesseract had too few pixels per character.

## Fix

`src/dethrottled/formats.py` now makes one bounded 2x Lanczos pass before OCR
for standalone images up to 2.5 million input pixels. Larger images are left at
native resolution. The helper is `_ocr_png`.

The first version also upscaled PDF page rasters. That regressed table OCR: a
150-DPI table page lost three row lines because it was rendered twice. PDF pages
are already rasterised at the OCR DPI, so `pdf_text` now calls
`image_text(..., upscale=False)`. The regression was caught by the table test and
fixed before this record.

## Results

| Input | Reference 1.7.1 | Candidate with fix |
|---|---|---|
| `office.png` | `PNG fact hote-005` | `PNG fact hotel-905` |
| `table.pdf` forced OCR | 320 chars | 320 chars |
| OCR warning | present | present |

## Transparent PNGs

A transparent RGBA image commonly stores RGB 0,0,0 behind alpha 0. Converting
that directly to RGB paints dark text on a black background. The reference
returned empty content for a transparent image with dark text; the candidate now
composites transparency onto a background chosen from the visible pixels'
luminance: white for dark text, black for light text.

| Input | Reference 1.7.1 | Candidate with fix |
|---|---|---|
| transparent dark text | empty | `transparent fact alpha-717` |
| transparent light text | `transparent fact bravo-718` | `transparent fact bravo-718` |

The focused OCR tests now cover both luminance directions and both transparent
backgrounds. They pass **7/7** in the candidate image.

The focused OCR tests pass, including native-resolution preservation for large
images and PDF pages, plus transparent dark/light text:

```
7 passed, 1 warning in 0.93s
```

The candidate image used for this check is
`dethrottled-dnb-api:1.8.0-dev-ocr-20261109`
(`sha256:500998195739…`), built over `dethrottled:1.7.1` with the improved
source. The frozen candidate images are unchanged.

Evidence: [s3-ocr-reference.json](s3-ocr-reference.json),
[s3-ocr-alpha-dark-reference.json](s3-ocr-alpha-dark-reference.json),
[s3-ocr-alpha-dark-candidate.json](s3-ocr-alpha-dark-candidate.json),
[s3-ocr-alpha-light-reference.json](s3-ocr-alpha-light-reference.json),
[s3-ocr-alpha-light-candidate.json](s3-ocr-alpha-light-candidate.json),
[s3-ocr-candidate.json](s3-ocr-candidate.json),
[s3-ocr-table-reference.json](s3-ocr-table-reference.json),
[s3-ocr-table-candidate.json](s3-ocr-table-candidate.json),
[s3-ocr-tests.log](s3-ocr-tests.log).
