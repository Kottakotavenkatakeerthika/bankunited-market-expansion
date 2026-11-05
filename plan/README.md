# Implementation Plan: GitHub is the source of truth

The Excel Implementation Plan is **generated from this repo's issues**. Never edit the Excel file;
edit the issue, and the next build picks it up.

| To change... | Do this in GitHub |
| --- | --- |
| % complete, owner, dates, evidence, notes | Open the issue → ⋯ → Edit → change the value in the **Plan fields** table → Save |
| Mark a task done | Close the issue (closed = 100%) |
| Sprint | Set the issue's Milestone (S0–S6) |
| Workstream | The `ws:` label |
| Add a task or blocker | New issue → "Plan task" or "Plan blocker" template; title starts with the next free T## / B## |
| Log a plan change | Edit the **Plan Change Log** issue → add a row to its table |

## Getting the Excel file
- Automatic: every Wednesday 11:30 PM ET, after the 9 PM cutoff, the "Build Implementation Plan" action
  commits `plan/BankUnited_Implementation_Plan_latest.xlsx` plus a dated copy in `plan/archive/`.
- On demand: Actions → Build Implementation Plan → Run workflow, then download the file from `plan/`.
- Locally: `python plan/plan_github.py build --template plan/template.xlsx --out plan_latest.xlsx`

`plan/template.xlsx` only supplies the layout and formatting (titles, summary, legend). Its rows are ignored.
To change the layout, replace that file.

## One-time setup (already done if issues show a Plan fields table)
`python plan/plan_github.py reconcile --plan "BankUnited Project Implementation_Plan_10-29_v3.xlsx"` previews
what would change; add `--apply` to update the issues. Re-running it is safe; matching issues are left alone.
After this, do not run reconcile again unless the pod agrees to reload from an Excel file, because it overwrites issue fields with the Excel values.
