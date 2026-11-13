# TR-03 validation and release evidence update — 2026-11-12

**Evidence scope:** Team emails from Austin, Akayiah and Bhavana, plus the supplied `clean_clone_step_log_integrated-v0.2.md`. This note does not assert sponsor acceptance or independently re-execute the pipeline.

- Release: `integrated-v0.2`; reported confirmed merge SHA `3c48fd512e9a0bf9b43a2ec5755c7145bee9833e` (PR #100).
- T75 clean clone: Windows, Python 3.14.5, Git 2.55; full pipeline approximately 20 minutes; 222 tests passed; 163 checks passed, 0 failed, 16 warnings; no processed tables changed. Four T75 acceptance criteria passed.
- Data-check reconciliation: Oct 28 data-v0.5: 161 passed and 13 warnings; PR #93 added five bank-ID checks, with two passes and three warnings; integrated-v0.2: 163 passed and 16 warnings.
- Refreshed report: [PR #120](https://github.com/Kottakotavenkatakeerthika/bankunited-market-expansion/pull/120), **reported not merged** as of Akayiah's message. Do not mark merged without verification.
- Baseline ML reproduction: output identical to committed baseline, Charlotte #16 of 287, score 88.4. **Scenario comparison not rerun**.
- Power BI: `dashboard/BankUnited_Market_Opportunity_Engine_v0.7.pbix` opened; Charlotte #16 of 287, 88.4. Dashboard README filename differs and refresh instructions remain pending T76.
- Raw-data onboarding: most data (~2 GB) downloadable with user-owned FDIC/FRED/BEA/BLS keys and `HTTP_USER_AGENT`; 30 FFIEC CRA files need approved Drive archive transfer. Credentials and data must not be embedded in this ZIP.
- Corrected README and independent retest: T76 fixes planned; T63 retest reported scheduled Nov 18–19.

**Do not infer:** all scenario outputs validated; confidential data transfer approved; canonical technical handoff complete; sponsor signoff obtained.
