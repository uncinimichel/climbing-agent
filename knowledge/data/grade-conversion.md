# Grade Conversion — the normalized difficulty ladder

Climbing grades come in incompatible systems. To rank and compare routes across venues we
normalize every grade onto a single **`dataGrade` 1–7** integer scale, keeping the raw
grade + system alongside it (never lose the original).

> **Provenance:** the `dataGrade` scale and this mapping are learned from the
> **multi-pitch.com** dataset (`/dev/multi-pitch`), reverse-engineered from ~40 routes
> whose `originalGrade` and `dataGrade` were both recorded. It targets the **easy→moderate
> multi-pitch trad** band the platform focuses on; extend it deliberately at the extremes.

## The `dataGrade` scale

`1` = very easy (Diff) · `7` = hard end of the current dataset (E1 / VI+ / TD). Higher =
harder. Used only for **sorting/comparison** — always show the `originalGrade` to humans.

## Conversion table (observed)

| dataGrade | BAS (British Adjectival + tech) | UIAA | YDS | Alpine (ALP) | French Sport (FS) | Norwegian (N) |
|:---:|---|---|---|---|---|---|
| **1** | `D 3a`, `D 3b` (Difficult) | — | — | — | — | — |
| **2** | `VD 3c` (Very Difficult) | `IV−` | — | — | — | — |
| **3** | `S 3c`, `S 4a`, `S 4b` (Severe) | — | `5.7` | — | `f4c` | — |
| **4** | `HS 4a`, `HS 4b` (Hard Severe) | `IV+` | — | `Difficile` (D) | — | — |
| **5** | `VS 4b`, `VS 4c`, `VS 5a` (Very Severe) | `V+` | `5.8` | — | `f5a` | — |
| **6** | `HVS 5b`, `HVS 5c` (Hard Very Severe) | — | — | — | — | — |
| **7** | `E1 5b` (Extreme 1) | `VI+` | — | `TD` (f6a+) | `f6b` | `N6−` |

Notes:
- The BAS grade has **two parts**: the adjectival (`VS`) = overall seriousness/quality, and
  the technical (`5a`) = hardest single move. Store both (`tradGrade`, `techGrade`).
- `V+ (f5c)` and `VI+ (f6b)` show UIAA↔French cross-annotations kept in the raw data.
- Alpine grades (`AD`/`D`/`TD`/`ED`…) describe overall commitment; a French sport grade in
  parentheses gives the technical crux.

## Grading system codes

| Code | System | Looks like |
|---|---|---|
| `BAS` | British Adjectival System | `VS 4c`, `HVS 5b`, `E1 5b` |
| `UIAA` | UIAA (Alps/Germany) | `IV−`, `V+`, `VI+` |
| `YDS` | Yosemite Decimal (US) | `5.7`, `5.8`, `5.10a` |
| `ALP` | Alpine (overall commitment) | `PD`, `AD`, `D`, `TD`, `ED` (+ optional Fr sport crux) |
| `FS` | French Sport | `f4c`, `f5a`, `f6a+` |
| `N` | Norwegian | `N6−` |

## How to use it in the engine

1. **Parse** the raw grade string → detect `gradeSys` → store `originalGrade`.
2. **Map** to `dataGrade` via the table (nearest band; interpolate for grades between rows).
3. **Sort/compare** venues and routes by `dataGrade`; **display** `originalGrade`.
4. **Filter** by ability: "show me ≤ dataGrade 5" = up to VS / 5.8 / V+.

## Caveats

- The table is **calibrated to this dataset's band** (Diff→E1). Above E1 / below Diff it
  needs extending — do so from a reference conversion chart, and log it in
  [`../roadmap/decisions.md`](../roadmap/decisions.md).
- Grade conversion is **inherently approximate** — systems weight danger, sustained
  difficulty, and single-move crux differently. `dataGrade` is a *sortable proxy*, not an
  equivalence claim.
- Keep the raw `originalGrade` forever; never let the normalization overwrite it.
