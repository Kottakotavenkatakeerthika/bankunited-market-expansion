"""Scoring pipeline: pillar metric builders (scripts, not notebooks) and the scoring engine.

    src/scoring/common.py    Metric and MetricSet, shared helpers (percentiles, growth, ratios)
    src/scoring/pillar3.py   Pillar 3 metric builder (more pillars follow)
    src/scoring/engine.py    percentiles, pillar scores, and the pillar export files
    src/scoring/run.py       one command: build every ported pillar, write its export

Each pillar builder only gathers metrics: it returns raw values for every metric it defines, with each
metric's direction and description. Weights come from weights/baseline.toml, never from the builder.
During the port the engine still writes the notebook-format exports in outputs/pillar_scores/, so
src/market_attractiveness.py and src/compare_scenarios.py run unchanged; tests/test_scoring_parity.py
checks those exports against the notebooks' committed ones.
"""
