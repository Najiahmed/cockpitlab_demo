"""Exécution des campagnes et verdict Go / No-Go."""
from __future__ import annotations

import platform
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable

from ..builds import Build
from . import catalog  # noqa: F401  (enregistre les cas de test)
from .framework import CATEGORIES, REGISTRY, Status, TestCase, TestResult, execute


@dataclass(frozen=True)
class Campaign:
    key: str
    name: str
    categories: tuple[str, ...]
    sanity_gate: bool  # la Sanity doit passer avant le reste


CAMPAIGNS: dict[str, Campaign] = {c.key: c for c in (
    Campaign("sanity", "Sanity Check", ("sanity",), False),
    Campaign("non_regression", "Non-régression", ("sanity", "non_regression"), True),
    Campaign("endurance", "Endurance", ("sanity", "endurance"), True),
    Campaign("performance", "Performance", ("sanity", "performance"), True),
    Campaign("complete", "Qualification complète", tuple(CATEGORIES), True),
)}

GO, GO_RESERVES, NO_GO, REJECTED = "GO", "GO AVEC RÉSERVES", "NO-GO", "BUILD REJETÉE"


@dataclass
class CampaignReport:
    build: Build
    campaign: Campaign
    started_at: datetime
    results: list[TestResult] = field(default_factory=list)
    duration_s: float = 0.0
    environment: dict[str, str] = field(default_factory=dict)

    def count(self, status: Status) -> int:
        return sum(r.status == status for r in self.results)

    @property
    def verdict(self) -> str:
        return compute_verdict(self.results)

    @property
    def failures(self) -> list[TestResult]:
        return [r for r in self.results if r.failed]


def compute_verdict(results: list[TestResult]) -> str:
    failed = [r for r in results if r.failed]
    if any(r.case.category == "sanity" for r in failed):
        return REJECTED
    if any(r.case.severity in ("bloquant", "majeur") for r in failed):
        return NO_GO
    if failed:
        return GO_RESERVES
    return GO


def cases_for(campaign: Campaign) -> list[TestCase]:
    order = list(CATEGORIES)
    selected = [c for c in REGISTRY if c.category in campaign.categories]
    return sorted(selected, key=lambda c: order.index(c.category))


def run_campaign(build: Build, campaign_key: str,
                 on_start: Callable[[TestCase], None] | None = None,
                 on_result: Callable[[TestResult], None] | None = None,
                 should_stop: Callable[[], bool] | None = None) -> CampaignReport:
    campaign = CAMPAIGNS[campaign_key]
    report = CampaignReport(build, campaign, datetime.now(), environment={
        "Banc": "CockpitLab SIL (simulation logicielle)",
        "Python": platform.python_version(),
        "Système": f"{platform.system()} {platform.release()}",
    })
    started = time.perf_counter()
    gate_closed, stopped = False, False
    for test_case in cases_for(campaign):
        stopped = stopped or bool(should_stop and should_stop())
        if stopped or (gate_closed and test_case.category != "sanity"):
            reason = ("Campagne interrompue" if stopped
                      else "Sanity en échec : build non qualifiable")
            result = TestResult(test_case, Status.SKIPPED, message=reason)
        else:
            if on_start:
                on_start(test_case)
            result = execute(test_case, build)
            if campaign.sanity_gate and test_case.category == "sanity" and result.failed:
                gate_closed = True
        report.results.append(result)
        if on_result:
            on_result(result)
    report.duration_s = time.perf_counter() - started
    return report
