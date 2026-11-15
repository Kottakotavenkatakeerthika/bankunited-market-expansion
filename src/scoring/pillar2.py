"""Pillar 2 metric builder: deposits and treasury.

Gathers the metrics only; directions are part of each metric's definition, and weights live in
weights/baseline.toml. Ported from notebooks/pillar2_deposits_treasury.ipynb.
"""
from __future__ import annotations

import pandas as pd

from src.scoring.common import HIGHER, Metric, MetricSet, cagr, call, r12, ratio, states_universe, wide

PILLAR, LABEL = "pillar2", "Deposits and treasury"

METRICS = [
    Metric("deposits_per_capita", "Deposits per capita (ex-HQ)", HIGHER, "June {d1}", "msa_year.sod_* + pep",
           "Deposit market"),
    Metric("deposit_growth", "Deposit growth (ex-HQ)", HIGHER, "{d0}–{d1s} CAGR", "msa_year.sod_*", "Deposit market"),
    Metric("deposits_per_branch", "Deposits per non-HQ branch", HIGHER, "June {d1}", "msa_year.sod_* + bank_msa_year",
           "Deposit market"),
    Metric("wage_bill", "Total wage bill", HIGHER, "{q1}", "msa_year.bls_qcew_total_wages_usd",
           "Operating-deposit demand"),
    Metric("wage_bill_growth", "Wage bill growth", HIGHER, "{q0}–{q1s} CAGR", "msa_year.bls_qcew_total_wages_usd",
           "Operating-deposit demand"),
    Metric("payroll_per_establishment", "Payroll per establishment", HIGHER, "{cy}", "msa_year.cbp_*",
           "Operating-deposit demand"),
    Metric("income_per_capita", "Personal income per capita", HIGHER, "{b1}", "msa_year.bea_* + pep",
           "Household deposit base"),
    Metric("income_growth", "Personal income growth", HIGHER, "{b0}–{b1s} CAGR", "msa_year.bea_personal_income_usd",
           "Household deposit base"),
    Metric("incumbent_nib_share", "Incumbent non-interest-bearing share", HIGHER, "June {d1}",
           "bank_quarter × bank_msa_year", "Incumbent franchise"),
    Metric("incumbent_uninsured_share", "Incumbent uninsured share", HIGHER, "June {d1}",
           "bank_quarter × bank_msa_year", "Incumbent franchise"),
]


def _incumbent_shares(bmy, bq, settings, cbsas, d1, local_basis=True):
    """Deposit-weighted bank-wide non-interest-bearing and uninsured shares of each metro's banks."""
    c = call(bq, settings["call_quarter"])
    tot = c.call_total_deposits_usd.where(c.call_total_deposits_usd > 0)
    nib = r12(c.call_noninterest_bearing_deposits_usd / tot)
    unins = (c.call_uninsured_deposits_usd / tot).where(c.call_uninsured_deposits_usd.notna(),
                                                       1 - c.call_insured_deposits_usd_net / tot).clip(0, 1)
    b = bmy[(bmy.year == d1) & bmy.sod_deposits_usd.notna() & bmy.cbsa_code.isin(cbsas)].copy()
    w = b.sod_deposits_usd
    if local_basis:
        w = w - b.sod_main_office_deposits_usd.fillna(0)
        if settings["exclude_home_banking_offices"]:
            w = w - b.sod_home_banking_office_deposits_usd.fillna(0)
    b["w"] = w.clip(lower=0)
    b["nib"], b["unins"] = b.rssd_id.map(nib), b.rssd_id.map(unins)
    g = b.assign(w_nib=b.w.where(b.nib.notna(), 0), x_nib=b.w * b.nib.fillna(0),
                 w_un=b.w.where(b.unins.notna(), 0), x_un=b.w * b.unins.fillna(0)).groupby("cbsa_code")
    S = pd.DataFrame({k: g[k].sum() for k in ["w", "w_nib", "x_nib", "w_un", "x_un"]}).reindex(cbsas)
    ok_nib = (S.w_nib > 0) & (S.w_nib / S.w >= settings["min_call_coverage"])
    ok_un = (S.w_un > 0) & (S.w_un / S.w >= settings["min_call_coverage"])
    return r12(S.x_nib / S.w_nib).where(ok_nib), r12(S.x_un / S.w_un).where(ok_un)


def build(tables: dict[str, pd.DataFrame], settings: dict) -> MetricSet:
    msa_year, bmy, bq = tables["msa_year"], tables["bank_msa_year"], tables["bank_quarter"]
    uni = states_universe(msa_year)
    cbsas = list(uni.index)

    def w(col):
        return wide(msa_year, col, cbsas)

    d0, d1 = int(settings["sod_start"]), int(settings["sod_end"])
    dep = w("sod_deposits_usd")
    booked = w("sod_main_office_deposits_usd").fillna(0)
    if settings["exclude_home_banking_offices"]:
        booked = booked + w("sod_home_banking_office_deposits_usd").fillna(0)
    # Booked deposits never exceed reported ones in data-v0.5 (max 99.25% of a metro); clip at 0 as in
    # Pillars 1 and 3 so a data error can't produce negative local deposits.
    local_dep = (dep - booked).clip(lower=0).where(dep.notna())
    pop = w("pep_population_count")

    # main offices in each metro (a bank-metro row with main-office deposits) leave the branch count
    bm = bmy[(bmy.year == d1) & bmy.sod_deposits_usd.notna()]
    main_offices = bm[bm.sod_main_office_deposits_usd.fillna(0) > 0].groupby("cbsa_code").size().reindex(cbsas).fillna(0)
    branches = w("sod_branches_count")[d1]
    local_branches = (branches - main_offices).where(lambda b: b > 0, branches)

    m = pd.DataFrame(index=pd.Index(cbsas, name="cbsa_code"))
    m["deposits_per_capita"] = ratio(local_dep[d1], pop[d1])
    m["deposit_growth"] = cagr(local_dep[d0], local_dep[d1], d1 - d0)
    m["deposits_per_branch"] = ratio(local_dep[d1], local_branches)

    q0, q1 = int(settings["qcew_start"]), int(settings["qcew_end"])
    wages = w("bls_qcew_total_wages_usd")
    m["wage_bill"] = wages[q1]
    m["wage_bill_growth"] = cagr(wages[q0], wages[q1], q1 - q0)
    cy = int(settings["cbp_year"])
    m["payroll_per_establishment"] = ratio(w("cbp_annual_payroll_usd")[cy], w("cbp_establishments_count")[cy])

    b0, b1 = int(settings["bea_start"]), int(settings["bea_end"])
    income = w("bea_personal_income_usd")
    m["income_per_capita"] = ratio(income[b1], pop[b1])
    m["income_growth"] = cagr(income[b0], income[b1], b1 - b0)

    m["incumbent_nib_share"], m["incumbent_uninsured_share"] = _incumbent_shares(bmy, bq, settings, cbsas, d1)

    fmt = {"d0": d0, "d1": d1, "d1s": f"{d1 % 100:02d}", "q0": q0, "q1": q1, "q1s": f"{q1 % 100:02d}",
           "cy": cy, "b0": b0, "b1": b1, "b1s": f"{b1 % 100:02d}"}
    metrics = [Metric(x.key, x.label, x.direction, x.period.format(**fmt), x.source, x.group) for x in METRICS]
    return MetricSet(PILLAR, LABEL, metrics, m, uni["cbsa_title"], dict(settings))
