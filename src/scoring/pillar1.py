"""Pillar 1 metric builder: commercial lending opportunity.

Gathers the metrics only; directions are part of each metric's definition, and weights live in
weights/baseline.toml. Ported from notebooks/pillar1_commercial_lending_1.ipynb.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from src.scoring.common import HIGHER, Metric, MetricSet, cagr, call, r12, ratio, states_universe, wide

PILLAR, LABEL = "pillar1", "Commercial lending"
BANK = "bank_quarter + bank_msa_year"

METRICS = [
    Metric("local_ci_growth", "Local-lender C&I growth", HIGHER, "{y0}–{y1s} CAGR", BANK, "Bank-reported lending"),
    Metric("local_cre_growth", "Local-lender CRE growth", HIGHER, "{y0}–{y1s} CAGR", BANK, "Bank-reported lending"),
    Metric("local_loans_to_deposits", "Local-lender commercial loans / deposits", HIGHER, "June {y1}", BANK,
           "Bank-reported lending"),
    Metric("allocated_loan_growth", "Allocated commercial loan growth", HIGHER, "{y0}–{y1s} CAGR", BANK,
           "Bank-reported lending"),
    Metric("mm_establishments", "Middle-market establishments (20–249)", HIGHER, "{c1}",
           "msa_year.cbp_establishments_20_249_count", "Middle-market borrowers"),
    Metric("mm_growth", "Middle-market establishment growth", HIGHER, "{c0}–{c1s} CAGR",
           "msa_year.cbp_establishments_20_249_count", "Middle-market borrowers"),
    Metric("mm_share", "Middle-market share of establishments", HIGHER, "{c1}", "msa_year.cbp_establishments_*",
           "Middle-market borrowers"),
    Metric("cre_payroll_growth", "Commercial real estate payroll growth", HIGHER, "{c0}–{c1s} CAGR",
           "msa_year.cre_* (NAICS 531 + 2362)", "CRE lending"),
]


def _pos_cagr(a, b, years):
    return r12((b / a) ** (1 / years) - 1).where((a > 0) & (b > 0))


def _loan_book(bank_quarter: pd.DataFrame, quarter_end: str) -> pd.DataFrame:
    c = call(bank_quarter, quarter_end)
    return pd.DataFrame({
        "ci": c.call_ci_loans_usd,
        "cre": c.call_construction_loans_usd.fillna(0) + c.call_multifamily_loans_usd.fillna(0)
               + c.call_nonfarm_nonres_loans_usd.fillna(0),
        "domestic_deposits": c.call_domestic_deposits_usd,
        "total_deposits": c.call_total_deposits_usd,
    })


def _local_lenders(bmy, book0, book1, y0, y1, cbsas, threshold, growth_cap) -> pd.DataFrame:
    """Per metro: base and capped end C&I and CRE of banks holding >= threshold of their deposits there."""
    s = bmy[(bmy.year == y1) & bmy.sod_deposits_usd.notna()].join(book1, on="rssd_id")
    s = s[s.domestic_deposits > 0].copy()
    s["share_in_msa"] = np.minimum(1, s.sod_deposits_usd / s.domestic_deposits)
    local = s[(s.share_in_msa >= threshold) & s.cbsa_code.isin(cbsas)].copy()
    local["ci0"] = local.rssd_id.map(book0.ci)
    local["cre0"] = local.rssd_id.map(book0.cre)
    cap = (1 + growth_cap) ** (y1 - y0)
    for k in ("ci", "cre"):
        ok = local[f"{k}0"] > 0
        local[f"{k}_base"] = np.where(ok, local[f"{k}0"], 0)
        local[f"{k}_end_capped"] = np.where(ok, np.minimum(local[k].fillna(0), local[f"{k}0"] * cap), 0)
    local["commercial"] = local.ci.fillna(0) + local.cre.fillna(0)
    g = local.groupby("cbsa_code")
    L = pd.DataFrame({c: g[c].sum() for c in ["ci_base", "ci_end_capped", "cre_base", "cre_end_capped",
                                             "commercial", "total_deposits"]}).reindex(cbsas).fillna(0)
    L["local_lenders"] = g.size().reindex(cbsas).fillna(0).astype(int)
    return L


def _allocated(bmy, year, book, cbsas, exclude_home_banking) -> pd.Series:
    """Every bank's C&I + CRE allocated to metros by its share of deposits not booked at main offices."""
    a = bmy[(bmy.year == year) & bmy.sod_deposits_usd.notna()].copy()
    booked = a.sod_main_office_deposits_usd.fillna(0)
    if exclude_home_banking:
        booked = booked + a.sod_home_banking_office_deposits_usd.fillna(0)
    a["booked"] = booked
    a["booked_total"] = a.groupby("rssd_id").booked.transform("sum")
    a = a.join(book, on="rssd_id")
    den = a.domestic_deposits - a.booked_total
    a["share"] = np.where(den > 0, np.clip((a.sod_deposits_usd - a.booked) / den, 0, 1), 0)
    a["alloc"] = a.share * (a.ci.fillna(0) + a.cre.fillna(0))
    return a.groupby("cbsa_code").alloc.sum().reindex(cbsas).fillna(0)


def build(tables: dict[str, pd.DataFrame], settings: dict) -> MetricSet:
    msa_year, bmy, bq = tables["msa_year"], tables["bank_msa_year"], tables["bank_quarter"]
    uni = states_universe(msa_year)
    cbsas = list(uni.index)
    base_q, end_q = settings["base_quarter"], settings["end_quarter"]
    y0, y1 = int(base_q[:4]), int(end_q[:4])
    c0, c1 = int(settings["cbp_start"]), int(settings["cbp_end"])

    def w(col):
        return wide(msa_year, col, cbsas)

    book0, book1 = _loan_book(bq, base_q), _loan_book(bq, end_q)
    L = _local_lenders(bmy, book0, book1, y0, y1, cbsas, settings["local_lender_threshold"], settings["growth_cap"])
    m = pd.DataFrame(index=pd.Index(cbsas, name="cbsa_code"))
    m["local_ci_growth"] = _pos_cagr(L.ci_base, L.ci_end_capped, y1 - y0)
    m["local_cre_growth"] = _pos_cagr(L.cre_base, L.cre_end_capped, y1 - y0)
    m["local_loans_to_deposits"] = r12(L.commercial / L.total_deposits).where(L.total_deposits > 0)

    excl = settings["exclude_home_banking_offices"]
    alloc0, alloc1 = _allocated(bmy, y0, book0, cbsas, excl), _allocated(bmy, y1, book1, cbsas, excl)
    m["allocated_loan_growth"] = _pos_cagr(alloc0, alloc1, y1 - y0)

    mm, est = w("cbp_establishments_20_249_count"), w("cbp_establishments_count")
    m["mm_establishments"] = mm[c1]
    m["mm_growth"] = cagr(mm[c0], mm[c1], c1 - c0)
    m["mm_share"] = ratio(mm[c1], est[c1])
    cre_pay = w("cre_real_estate_payroll_usd") + w("cre_nonres_construction_payroll_usd")
    m["cre_payroll_growth"] = cagr(cre_pay[c0], cre_pay[c1], c1 - c0)

    fmt = {"y0": y0, "y1": y1, "y1s": f"{y1 % 100:02d}", "c0": c0, "c1": c1, "c1s": f"{c1 % 100:02d}"}
    metrics = [Metric(x.key, x.label, x.direction, x.period.format(**fmt), x.source, x.group) for x in METRICS]
    return MetricSet(PILLAR, LABEL, metrics, m, uni["cbsa_title"], dict(settings))
