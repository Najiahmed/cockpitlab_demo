"""Rapports de campagne : HTML (lecture humaine), JUnit XML (Jenkins / GitLab), JSON, tickets."""
from __future__ import annotations

import html
import json
import xml.etree.ElementTree as ET
from pathlib import Path

from .framework import CATEGORIES, Status, TestResult
from .runner import GO, GO_RESERVES, NO_GO, REJECTED, CampaignReport

VERDICT_COLORS = {GO: "#16a34a", GO_RESERVES: "#d97706", NO_GO: "#dc2626", REJECTED: "#7f1d1d"}
STATUS_COLORS = {Status.PASSED: "#16a34a", Status.FAILED: "#dc2626",
                 Status.ERROR: "#9333ea", Status.SKIPPED: "#6b7280"}
SEVERITY_TO_PRIORITY = {"bloquant": "Blocker", "majeur": "Major", "mineur": "Minor"}
COMPONENTS = {"SAF": "Sécurité", "NET": "Réseau véhicule", "PWT": "Groupe motopropulseur",
              "BAT": "Batterie / BMS", "HMI": "IHM", "CLU": "Combiné", "BCM": "Carrosserie",
              "CHA": "Châssis", "SYS": "Système", "PERF": "Performance"}


def component(requirement: str) -> str:
    code = requirement.split("-")[1] if requirement.startswith("REQ-") else ""
    return COMPONENTS.get(code, "Cockpit")


def file_stem(report: CampaignReport) -> str:
    return f"{report.build.version}_{report.campaign.key}_{report.started_at:%Y%m%d-%H%M%S}"


# --------------------------------------------------------------------------
def ticket_draft(result: TestResult, report: CampaignReport) -> str:
    """Brouillon de ticket d'anomalie prêt à copier dans Jira."""
    case = result.case
    actions = [s.text for s in result.steps if s.ok is None]
    lines = [
        f"Titre : [{case.id}] {case.title} — en échec sur {report.build.version}",
        f"Priorité : {SEVERITY_TO_PRIORITY[case.severity]} ({case.severity})",
        f"Composant : Cockpit / {component(case.requirement)}",
        f"Détecté par : campagne {report.campaign.name}, test {case.id}",
        f"Build : {report.build.version} ({report.build.channel})",
        f"Exigence : {case.requirement}",
        "",
        "Étapes pour reproduire :",
        *[f"  {i}. {a}" for i, a in enumerate(actions, 1)],
        "",
        f"Résultat attendu : {result.expected or case.title}",
        f"Résultat obtenu : {result.observed or result.message}",
        "",
        f"Reproductible : relancer {case.id} sur le banc (simulation déterministe, reproductible à 100 %).",
        "Preuves : rapport de campagne et extrait de trace CAN joints.",
    ]
    if result.measures:
        at = lines.index("") + len(actions) + 2
        lines[at:at] = ["", "Mesures : " + ", ".join(f"{k} = {v}" for k, v in result.measures.items())]
    return "\n".join(lines)


# --------------------------------------------------------------------------
def to_junit(report: CampaignReport) -> str:
    suite = ET.Element("testsuite", {
        "name": f"CockpitLab {report.campaign.name}",
        "tests": str(len(report.results)),
        "failures": str(report.count(Status.FAILED)),
        "errors": str(report.count(Status.ERROR)),
        "skipped": str(report.count(Status.SKIPPED)),
        "time": f"{report.duration_s:.3f}",
        "timestamp": report.started_at.isoformat(timespec="seconds"),
    })
    props = ET.SubElement(suite, "properties")
    for name, value in (("build", report.build.version), ("verdict", report.verdict)):
        ET.SubElement(props, "property", {"name": name, "value": value})
    for r in report.results:
        tc = ET.SubElement(suite, "testcase", {
            "classname": f"cockpit.{r.case.category}", "name": f"{r.case.id} {r.case.title}",
            "time": f"{r.duration_s:.3f}",
        })
        if r.status == Status.FAILED:
            ET.SubElement(tc, "failure", {"message": r.message}).text = _evidence_text(r)
        elif r.status == Status.ERROR:
            ET.SubElement(tc, "error", {"message": r.message}).text = _evidence_text(r)
        elif r.status == Status.SKIPPED:
            ET.SubElement(tc, "skipped", {"message": r.message})
    ET.indent(suite)
    return ET.tostring(suite, encoding="unicode", xml_declaration=True)


def _evidence_text(r: TestResult) -> str:
    out = []
    for key, value in r.evidence.items():
        if isinstance(value, list):
            out.append(f"{key} :")
            out.extend(f"  {line}" for line in value)
        else:
            out.append(f"{key} : {value}")
    return "\n".join(out)


def to_json(report: CampaignReport) -> str:
    return json.dumps({
        "build": report.build.version,
        "campaign": report.campaign.key,
        "started_at": report.started_at.isoformat(timespec="seconds"),
        "duration_s": round(report.duration_s, 3),
        "verdict": report.verdict,
        "results": [{
            "id": r.case.id, "title": r.case.title, "category": r.case.category,
            "severity": r.case.severity, "status": r.status.name,
            "duration_s": round(r.duration_s, 4), "measures": r.measures, "message": r.message,
        } for r in report.results],
    }, ensure_ascii=False, indent=2)


# --------------------------------------------------------------------------
def to_html(report: CampaignReport) -> str:
    e = html.escape
    verdict = report.verdict
    total = len(report.results)
    executed = total - report.count(Status.SKIPPED)
    rate = report.count(Status.PASSED) / executed * 100 if executed else 0.0

    rows = []
    for r in report.results:
        measures = "<br>".join(f"{e(k)} : <b>{e(v)}</b>" for k, v in r.measures.items())
        rows.append(
            f"<tr><td class='mono'>{e(r.case.id)}</td><td>{e(r.case.title)}</td>"
            f"<td>{e(CATEGORIES[r.case.category])}</td><td>{e(r.case.severity)}</td>"
            f"<td><span class='pill' style='background:{STATUS_COLORS[r.status]}'>{e(r.status.value)}</span></td>"
            f"<td class='num'>{r.duration_s * 1000:.0f} ms</td><td>{measures}</td></tr>")

    failures = []
    for r in report.failures:
        steps = "".join(
            f"<li class='{'ok' if s.ok else 'ko' if s.ok is False else 'act'}'>{e(s.text)}</li>"
            for s in r.steps)
        evidence = []
        for key, value in r.evidence.items():
            if isinstance(value, list):
                evidence.append(f"<dt>{e(key)}</dt><dd><pre>{e(chr(10).join(value))}</pre></dd>")
            else:
                evidence.append(f"<dt>{e(key)}</dt><dd>{e(str(value))}</dd>")
        failures.append(f"""
        <section class="failure">
          <h3>{e(r.case.id)} · {e(r.case.title)} <span class="sev">{e(r.case.severity)}</span></h3>
          <p class="req">{e(r.case.requirement)}</p>
          <p class="msg">{e(r.message)}</p>
          <div class="cols">
            <div><h4>Déroulé</h4><ol>{steps}</ol></div>
            <div><h4>Preuves</h4><dl>{''.join(evidence)}</dl></div>
          </div>
          <h4>Brouillon de ticket</h4><pre class="ticket">{e(ticket_draft(r, report))}</pre>
        </section>""")

    env = "".join(f"<span>{e(k)} : {e(v)}</span>" for k, v in report.environment.items())
    return f"""<!DOCTYPE html>
<html lang="fr"><head><meta charset="utf-8">
<title>Rapport {e(report.campaign.name)} · {e(report.build.version)}</title>
<style>
 body{{font-family:Segoe UI,system-ui,sans-serif;margin:0;background:#f5f7fa;color:#111827}}
 header{{background:#0d131c;color:#e6edf5;padding:28px 40px}}
 header h1{{margin:0 0 4px;font-size:24px}} header p{{margin:0;color:#9aa6b6}}
 .env span{{margin-right:18px;font-size:13px;color:#9aa6b6}}
 main{{padding:28px 40px;max-width:1300px}}
 .summary{{display:flex;gap:16px;flex-wrap:wrap;margin-bottom:28px}}
 .tile{{background:#fff;border-radius:12px;padding:16px 22px;box-shadow:0 1px 3px #0001;min-width:120px}}
 .tile b{{display:block;font-size:28px}} .tile span{{color:#6b7280;font-size:13px}}
 .verdict{{color:#fff;background:{VERDICT_COLORS[verdict]}}} .verdict span{{color:#fffc}}
 table{{border-collapse:collapse;width:100%;background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 1px 3px #0001}}
 th,td{{padding:9px 12px;border-bottom:1px solid #eef0f3;text-align:left;font-size:14px;vertical-align:top}}
 th{{background:#f0f2f5;color:#4b5563;font-weight:600}}
 .mono,pre{{font-family:Consolas,monospace}} .num{{text-align:right;white-space:nowrap}}
 .pill{{color:#fff;border-radius:10px;padding:2px 10px;font-size:12px;white-space:nowrap}}
 h2{{margin:36px 0 12px}}
 .failure{{background:#fff;border-left:5px solid #dc2626;border-radius:10px;padding:16px 22px;margin-bottom:18px;box-shadow:0 1px 3px #0001}}
 .failure h3{{margin:0 0 4px}} .sev{{background:#fee2e2;color:#991b1b;border-radius:8px;padding:1px 8px;font-size:12px}}
 .req{{color:#6b7280;margin:0 0 8px}} .msg{{font-weight:600;color:#b91c1c}}
 .cols{{display:grid;grid-template-columns:1fr 1.4fr;gap:24px}}
 li.ok::marker{{content:"✔  ";color:#16a34a}} li.ko::marker{{content:"✘  ";color:#dc2626}} li.act::marker{{content:"▸  ";color:#6b7280}}
 li.ko{{color:#b91c1c;font-weight:600}}
 dt{{font-weight:600;font-size:13px;color:#4b5563}} dd{{margin:0 0 8px}}
 pre{{background:#0d131c;color:#d1fae5;padding:10px 12px;border-radius:8px;font-size:12px;overflow-x:auto}}
 pre.ticket{{background:#f8fafc;color:#111827;border:1px solid #e5e7eb}}
</style></head><body>
<header>
  <h1>Rapport de campagne · {e(report.campaign.name)}</h1>
  <p>Build {e(report.build.version)} ({e(report.build.channel)}) · {e(report.build.description)}</p>
  <p class="env">{report.started_at:%d/%m/%Y %H:%M:%S} · durée {report.duration_s:.1f} s · {env}</p>
</header>
<main>
  <div class="summary">
    <div class="tile verdict"><b>{e(verdict)}</b><span>Verdict</span></div>
    <div class="tile"><b>{total}</b><span>Tests</span></div>
    <div class="tile"><b style="color:#16a34a">{report.count(Status.PASSED)}</b><span>Réussis</span></div>
    <div class="tile"><b style="color:#dc2626">{report.count(Status.FAILED)}</b><span>Échoués</span></div>
    <div class="tile"><b style="color:#9333ea">{report.count(Status.ERROR)}</b><span>Erreurs</span></div>
    <div class="tile"><b style="color:#6b7280">{report.count(Status.SKIPPED)}</b><span>Non exécutés</span></div>
    <div class="tile"><b>{rate:.0f} %</b><span>Taux de réussite</span></div>
  </div>
  <table><thead><tr><th>ID</th><th>Test</th><th>Campagne</th><th>Sévérité</th><th>Statut</th>
  <th>Durée</th><th>Mesures</th></tr></thead><tbody>{''.join(rows)}</tbody></table>
  {'<h2>Anomalies détectées</h2>' + ''.join(failures) if failures else '<h2>Aucune anomalie détectée</h2>'}
</main></body></html>"""


def write_reports(report: CampaignReport, directory: str | Path = "reports") -> dict[str, Path]:
    out = Path(directory)
    out.mkdir(parents=True, exist_ok=True)
    stem = file_stem(report)
    paths = {"html": out / f"{stem}.html", "junit": out / f"{stem}_junit.xml", "json": out / f"{stem}.json"}
    paths["html"].write_text(to_html(report), encoding="utf-8")
    paths["junit"].write_text(to_junit(report), encoding="utf-8")
    paths["json"].write_text(to_json(report), encoding="utf-8")
    return paths
