from pathlib import Path

from sp500_candidate_engine.llm_preselection.config import (
    load_llm_preselection_config,
)


def test_production_config_defines_two_stage_top_20() -> None:
    config = load_llm_preselection_config(
        Path("config/llm_preselection/policy_v1.yaml")
    )

    assert config.requested_count == 20
    assert config.first_stage_pool_size >= 20
    assert config.windows.news_days == 30
    assert config.windows.fact_quarters == 8
    assert config.windows.price_sessions == 60
    assert sum(config.rubric.values()) == 100
