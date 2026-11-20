# BankUnited Quarto documentation migration

This folder contains the Quarto Book source project within `docs/handoff/`. The existing handoff documents and repository evidence are retained alongside the book source files.

## Build

Install [Quarto](https://quarto.org/docs/get-started/) and, for PDF rendering, a LaTeX distribution (for example TinyTeX).

cd docs/handoff
quarto render --to html
quarto render --to pdf

Output is written to `_site/` (HTML and PDF outputs, depending on format). This environment did not have the Quarto CLI installed, so rendered outputs were **not** tested here.

## Source and review policy

- `.qmd` files are the maintained documentation source.
- The original November 12 handoff files remain in `docs/handoff/` as evidence and historical source material.
- Do **not** overwrite root `README.md`, `docs/technical_handoff.md`, `docs/methodology.md`, code, data, or the dashboard with these unreviewed chapters.
- Replace the old independent documentation drafts only after technical-owner review and agreement on the new canonical Quarto source.
- Do not commit API keys, private CRA files or restricted sponsor information.

## Immediate next steps

Confirm with Elliot whether HTML+PDF Quarto Book meets the handoff format requirement; assign chapter reviewers; resolve T76 README gaps; validate `quarto render` in CI; obtain sponsor-approved transfer mechanism.
