"""Tests du banc de test lui-même : chaque régression connue doit être détectée par le bon test.

C'est ce qui garantit que les campagnes ne laissent pas passer une build défectueuse.
"""
import xml.etree.ElementTree as ET

import pytest

from cockpitlab.builds import BUILDS, REFERENCE_BUILD, get_build
from cockpitlab.testing import REGISTRY, Status, run_campaign
from cockpitlab.testing.report import ticket_draft, to_html, to_json, to_junit
from cockpitlab.testing.runner import GO, GO_RESERVES, NO_GO, REJECTED


def failed_ids(report):
    return {r.case.id for r in report.failures}


@pytest.fixture(scope="module")
def reports():
    return {b.version: run_campaign(b, "complete") for b in BUILDS}


def test_catalogue_is_consistent():
    ids = [c.id for c in REGISTRY]
    assert len(ids) == len(set(ids))
    assert all(c.requirement.startswith("REQ-") for c in REGISTRY)
    assert {c.category for c in REGISTRY} == {"sanity", "non_regression", "endurance", "performance"}


def test_reference_build_passes_everything(reports):
    report = reports[REFERENCE_BUILD.version]
    assert report.verdict == GO
    assert all(r.status == Status.PASSED for r in report.results), failed_ids(report)


@pytest.mark.parametrize("version, verdict, expected_failures", [
    ("26.11.0-rc1", NO_GO, {"NR-06", "NR-07"}),
    ("26.11.0-rc2", GO_RESERVES, {"NR-12"}),
    ("26.12.0-nightly.142", REJECTED, {"SAN-01", "SAN-02", "SAN-03", "SAN-05"}),
    ("26.12.0-nightly.143", NO_GO, {"NR-02"}),
])
def test_each_regression_is_detected(reports, version, verdict, expected_failures):
    report = reports[version]
    assert report.verdict == verdict
    assert failed_ids(report) == expected_failures


def test_failed_sanity_blocks_the_rest_of_the_campaign(reports):
    report = reports["26.12.0-nightly.142"]
    skipped = [r for r in report.results if r.status == Status.SKIPPED]
    assert skipped and all(r.case.category != "sanity" for r in skipped)


def test_sanity_campaign_alone_does_not_skip():
    report = run_campaign(get_build("26.12.0-nightly.142"), "sanity")
    assert report.count(Status.SKIPPED) == 0


def test_campaign_can_be_stopped():
    report = run_campaign(REFERENCE_BUILD, "complete", should_stop=lambda: True)
    assert all(r.status == Status.SKIPPED for r in report.results)


def test_failures_carry_evidence_and_ticket(reports):
    report = reports["26.11.0-rc1"]
    failure = next(r for r in report.failures if r.case.id == "NR-07")
    assert failure.evidence["Dernières trames CAN"]
    ticket = ticket_draft(failure, report)
    assert "Priorité : Blocker" in ticket and "26.11.0-rc1" in ticket
    assert "Résultat obtenu : aucune alerte ceinture" in ticket


def test_report_formats(reports):
    report = reports["26.11.0-rc1"]
    suite = ET.fromstring(to_junit(report))
    assert suite.get("failures") == "2"
    assert len(suite.findall("testcase")) == len(report.results)
    assert '"verdict": "NO-GO"' in to_json(report)
    assert "NO-GO" in to_html(report) and "Brouillon de ticket" in to_html(report)
