"""Reproducible report counterfactuals; never changes the submitted configuration."""
from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gameday_lab.cache import CachingClient, SemanticCache
from gameday_lab.client import ResilientClient
from gameday_lab.factory import build_client
from gameday_lab.sim.config import load_config
from gameday_lab.sim.engine import run_scenario


class UnsafeLadder(ResilientClient):
    def ladder(self, task: str) -> list[str]:
        return self.order[:]


def measure(cfg, scenario, client):
    m = run_scenario(cfg, scenario, client, None).metrics()
    keys = ("availability", "faq_availability", "cache_hit_ratio", "wrong_answers",
            "wrong_answers_by_reason", "outdated_answers", "stale_served",
            "cost_per_good_turn", "amplification", "retry_ratio", "recovery_s",
            "latency_p95_s", "give_up_reasons", "incompatible_routes")
    return {k: m[k] for k in keys if k in m}


def main():
    cfg = load_config()
    out = {}
    for scenario in ("G2_overload_storm", "G3_brownout"):
        for budget in (True, False):
            settings = {**cfg.client, "breaker": {**cfg.client["breaker"], "min_calls": 10**9},
                        "max_attempts_per_provider": 5}
            if not budget:
                settings.update(retry_budget_ratio=100, retry_budget_max_tokens=1e9,
                                retry_budget_min_per_s=1e6)
            variant = replace(cfg, client=settings)
            out[f"{scenario}_budget_{budget}"] = measure(
                variant, scenario, build_client("resilient", variant))
    for scenario in ("G6_provider_outage", "G4_slow_region"):
        variant = replace(cfg, client={**cfg.client, "attempt_timeout_s": 30})
        out[f"{scenario}_timeout_30"] = measure(
            variant, scenario, build_client("resilient", variant))
    out["G6_unsafe_ladder"] = measure(cfg, "G6_provider_outage", UnsafeLadder(
        cfg.provider_infos(), cfg.fallback_order, cfg.client, seed=1))
    cache_cfg = load_config(scenarios_path="configs/scenarios_cache.yaml")
    for threshold in (0.80, 0.95, 0.97):
        variant = replace(cache_cfg, cache={**cache_cfg.cache, "similarity_threshold": threshold})
        out[f"C1_threshold_{threshold}"] = measure(variant, "C1_faq_outage", build_client("cached", variant))
    for ttl in (30, 60, 300):
        variant = replace(cache_cfg, cache={**cache_cfg.cache, "ttl_s": ttl})
        out[f"C1_ttl_{ttl}"] = measure(variant, "C1_faq_outage", build_client("cached", variant))
    variant = replace(cache_cfg, cache={**cache_cfg.cache, "max_stale_s": 0})
    out["C1_no_stale"] = measure(variant, "C1_faq_outage", build_client("cached", variant))
    Path("reports/experiments.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
