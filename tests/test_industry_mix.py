"""Year availability and missing-data behavior for the industry-fit calculation."""
import pandas as pd
import pytest
from src.bankunited_fit import industry_mix


def inputs():
    sectors = pd.DataFrame([
        ['00100', 2022, '23', 20.], ['00100', 2022, '22', 10.],
        ['00100', 2023, '23', 30.], ['00100', 2023, '22', 15.],
        ['00200', 2023, '23', 40.],
    ], columns=['cbsa_code', 'year', 'naics_code', 'cbp_employment_count'])
    totals = pd.DataFrame([
        ['00100', 2022, 100.], ['00100', 2023, 100.],
        ['00200', 2023, 200.], ['00300', 2023, 0.],
    ], columns=['cbsa_code', 'year', 'cbp_employment_count'])
    mapping = pd.DataFrame({'naics_2digit':['23','22'], 'fit_priority':['High','Medium']})
    return sectors, totals, mapping
 

def test_year_fallback_and_incomplete_sectors():
    s, m, p = inputs()
    out = industry_mix(s, m, 2024, p).set_index('cbsa_code')
    assert out.industry_data_year.eq(2023).all()
    assert out.data_year_lag.eq(1).all()
    assert out.loc['00100', 'high_med_share'] == .45
    assert out.loc['00200', 'high_share'] == .2
    assert pd.isna(out.loc['00200', 'high_med_share'])
    assert out.loc['00200', 'high_med_partial_emp'] == 40
    assert out.loc['00200', 'high_med_missing_sectors'] == '22'
    assert not out.loc['00300', 'high_share_ready']
    assert pd.isna(out.loc['00300', 'high_share'])


def test_historical_release_gating_and_no_future_years():
    s, m, p = inputs()
    ledger = pd.DataFrame({'source':['cbp','cbp'], 'dataset':['cbp_county']*2,
                           'year':[2022,2023], 'release_date':['2024-06-01','2025-06-01']})
    out = industry_mix(s,m,2024,p,as_of='2024-12-31',release_dates=ledger)
    assert out.industry_data_year.eq(2022).all()
    assert out.high_share.iloc[0] == .2
    assert industry_mix(s,m,2022,p).industry_data_year.eq(2022).all()
    with pytest.raises(ValueError, match='No common CBP year'):
        industry_mix(s,m,2021,p)
    with pytest.raises(ValueError, match='require release_dates'):
        industry_mix(s,m,2024,p,as_of='2024-12-31')


def test_invalid_or_unmapped_inputs_rejected():
    s,m,p = inputs()
    with pytest.raises(ValueError,match='Duplicate keys'):
        industry_mix(pd.concat([s,s.iloc[:1]]),m,2024,p)
    with pytest.raises(ValueError,match='Unmapped sectors'):
        industry_mix(s,m,2024,p.iloc[:1].assign(fit_priority='High').pipe(
            lambda d: pd.concat([d,pd.DataFrame({'naics_2digit':['42'],'fit_priority':['Medium']})])))
    s.loc[0,'cbp_employment_count']=-1
    with pytest.raises(ValueError,match='finite and nonnegative'):
        industry_mix(s,m,2024,p)


def test_published_total_is_denominator_and_inputs_unchanged():
    s,m,p=inputs()
    original=s.copy(deep=True)
    result=industry_mix(s,m,2023,p).set_index('cbsa_code')
    # Available sectors sum to 45; published all-industry total is 100.
    assert result.loc['00100','high_share']==.3
    pd.testing.assert_frame_equal(s,original)


def test_toml_priorities_and_scoring_weights_are_separate(tmp_path):
    import tomllib
    from pathlib import Path
    from src.bankunited_fit import load_fit_priorities
    from src.market_attractiveness import load_weights, normalize_weights
    path = Path(__file__).resolve().parents[1] / 'weights/baseline.toml'
    cfg = tomllib.loads(path.read_text())
    expected = normalize_weights({'pillars':cfg['pillars'], 'fill':cfg['fill'],
                                  'metrics':{k:cfg[k] for k in ['pillar1','pillar2','pillar3','pillar4']}})
    assert load_weights(path) == expected
    priorities = load_fit_priorities(path)
    assert priorities.set_index('naics_2digit').loc['52','fit_priority'] == 'Medium'
    assert priorities.fit_priority.eq('High').sum() == 6
    assert priorities.fit_priority.eq('Medium').sum() == 5
    assert priorities.in_high_subset.equals(priorities.fit_priority.eq('High'))
    bad = tmp_path / 'bad.toml'
    bad.write_text('[industry_fit.priorities."52"]\nlabel="Finance"\nfit_priority="Unknown"\n')
    with pytest.raises(ValueError, match='Invalid industry priority'):
        load_fit_priorities(bad)


def report_inputs():
    s, m, p = inputs()
    p['label'] = ['Construction', 'Utilities']
    s['cbp_establishments_count'] = 2.
    s['cbp_annual_payroll_usd'] = s.cbp_employment_count * 1000
    s['cbp_counties_reported_count'] = 1.
    m['cbsa_title'] = m.cbsa_code.map({'00100': 'Alpha', '00200': 'Beta', '00300': 'Gamma'})
    x = pd.DataFrame({'cbsa_code':['00100','00200','00300'], 'county_fips':['00001','00002','00003']})
    return s, m, p, x


def test_report_supporting_metrics_and_missingness():
    from src.bankunited_fit import build_report
    s,m,p,x = report_inputs()
    tables = build_report(s,m,x,2024,p,growth_years=1,comparison_metros=['00100','00200'])
    assert tables['Settings'].industry_data_year.iloc[0] == 2023
    growth = tables['Growth'].set_index(['cbsa_code','naics_code'])
    assert growth.loc[('00100','23'),'employment_cagr'] == pytest.approx(.5)
    assert pd.isna(growth.loc[('00200','23'),'employment_cagr'])
    summary = tables['Coverage summary']
    row=summary.loc[summary.cbsa_code.eq('00200') & summary.year.eq(2023)].iloc[0]
    assert row.high_share_ready
    assert not row.high_med_share_ready
    assert row.absent_sector_rows == 1
    assert row.high_med_sectors_missing_employment == 1
    sensitivity=tables['Sensitivity']
    assert pd.isna(sensitivity.loc[sensitivity.cbsa_code.eq('00200') & sensitivity.scenario.eq('High + Medium'),'employment_share'].iloc[0])
    assert not pd.isna(tables['Specialization'].location_quotient).all()


def test_generator_needs_no_existing_exports_or_docs(tmp_path):
    from src.bankunited_fit import generate_report
    s,m,p,x = report_inputs()
    (tmp_path/'data/processed').mkdir(parents=True)
    (tmp_path/'data/reference').mkdir()
    (tmp_path/'weights').mkdir()
    s.to_parquet(tmp_path/'data/processed/msa_naics_year.parquet')
    m.to_parquet(tmp_path/'data/processed/msa_year.parquet')
    x.to_csv(tmp_path/'data/reference/county_cbsa_xwalk.csv',index=False)
    config_text='[industry_fit]\ngrowth_years=1\ncomparison_metros=["00100","00200"]\n'
    for row in p.to_dict('records'):
        config_text += f'\n[industry_fit.priorities."{row["naics_2digit"]}"]\nlabel="{row["label"]}"\nfit_priority="{row["fit_priority"]}"\n'
    path=tmp_path/'weights/baseline.toml'
    path.write_text(config_text)
    output=generate_report(tmp_path,2024)
    assert output.exists()
    saved=pd.read_excel(output,sheet_name='MSA industry fit',dtype={'cbsa_code':str}).set_index('cbsa_code')
    assert saved.loc['00100','high_share'] == .3
    path.write_text(config_text.replace('fit_priority="Medium"','fit_priority="High"') + '\n[industry_fit.priorities."42"]\nlabel="Wholesale"\nfit_priority="Medium"\n')
    generate_report(tmp_path,2024)
    updated=pd.read_excel(output,sheet_name='MSA industry fit',dtype={'cbsa_code':str}).set_index('cbsa_code')
    assert updated.loc['00100','high_share'] == .45
    assert not (tmp_path/'docs').exists()
    assert not list((tmp_path/'outputs').rglob('*.csv'))


def test_market_cli_invokes_fit_generator(monkeypatch):
    from src import market_attractiveness as ma
    from src import bankunited_fit as fit
    calls=[]
    monkeypatch.setattr(ma,'run',lambda **kwargs:(pd.DataFrame(),{'written':['scores.csv','run.json']}))
    monkeypatch.setattr(ma,'weight_table',lambda report:pd.DataFrame())
    monkeypatch.setattr(ma,'summary',lambda *args:'score summary')
    monkeypatch.setattr(fit,'generate_report',lambda **kwargs:calls.append(kwargs) or 'report.xlsx')
    assert ma.main(['--year','2022'])==0
    assert calls==[{'scoring_year':2022,'priorities_file':None}]
    calls.clear()
    assert ma.main(['--show-weights'])==0
    assert not calls
