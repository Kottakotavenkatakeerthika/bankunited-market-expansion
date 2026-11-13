# Faculty final-delivery alignment — November 2026 guidance

The guidance requires **three coordinated deliverables**, all describing the same release and scope.

| Faculty requirement | Repository / package evidence | Status / next step |
|---|---|---|
| 1. Complete product handoff | Code, processed data, tests, scores, dashboard present; tracker updated | **Partial** — add technical runbook, methodology, semantic contracts, final report, updated customer journey, normal/exception evidence, accessible raw-data procedure, owner reviews |
| 2. Working final demonstration | Power BI v0.7 and scenario outputs present | **Not verified** — execute representative end-to-end journey, show one traceable finding and meaningful missing-data exception on same release |
| 3. Short executive deck | Earlier demo slides exist separately; not validated against newest snapshot | **Pending** — prepare recommended five slides: decision, delivered journey, methodology, results/validation, handoff/next steps |
| Decision story | README describes commercial-bank expansion market ranking | **Partial** — distinguish market ranking from recommendation/entry decision |
| Semantic contract | Data dictionary and source metadata exist | **Partial** — explicit record unit, business meaning, units, missing-value semantics, version and owner required |
| ML evaluation / leakage | Not fully established from new ZIP review | **Pending owner evidence** — cutoff, source release lag, splits, baselines, error cases, validation and model versions |
| Architecture / interfaces | README and code structure present | **Partial** — diagram, interfaces, refresh/lineage, configuration and tested environment needed |
| Methodology and worked example | Pillar notebooks and score outputs present; docs/methodology.md empty | **Incomplete** — explain formulas, weights, example input → score → dashboard and limitations |
| Reproducibility | Pinned requirements and test files; external raw data | **Not independently verified** — tagged run log, clean rebuild and dashboard refresh evidence |
| Sign-offs / sponsor access | Proposed owner roster in tracker | **Pending** — named reviewers, dates, approvals and verified sponsor repository access |

**Important scope statement:** `dashboard/README.md` calls the dashboard Market Attractiveness MVP only; Fit & Feasibility is not yet applied. The demo and final report must not claim a complete two-score product unless implementation evidence is subsequently supplied.

**Guidance source:** `Practicum Guidance Final Delivery Package.pdf`, pp. 1–3 and 6–9.
