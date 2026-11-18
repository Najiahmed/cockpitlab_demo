"""Rapport HTML d'une série de scénarios (frise des étapes)."""
from __future__ import annotations

import html
from datetime import datetime
from pathlib import Path

from .engine import ScenarioRun, StepStatus

ICONS = {StepStatus.PASSED: ("✔", "#16a34a"), StepStatus.FAILED: ("✘", "#dc2626"),
         StepStatus.SKIPPED: ("–", "#9ca3af"), StepStatus.PENDING: ("·", "#9ca3af"),
         StepStatus.RUNNING: ("▶", "#0891b2")}


def to_html(runs: list[ScenarioRun], build_label: str, when: datetime | None = None) -> str:
    e = html.escape
    when = when or datetime.now()
    passed = sum(r.passed for r in runs)
    blocks = []
    for run in runs:
        colour = "#16a34a" if run.passed else "#dc2626"
        steps = []
        for i, (step, result) in enumerate(zip(run.scenario.steps, run.results), 1):
            icon, c = ICONS[result.status]
            steps.append(f"<tr><td class='n'>{i}</td><td style='color:{c}'>{icon}</td>"
                         f"<td>{e(step.label)}</td><td class='d'>{e(result.detail)}</td></tr>")
        blocks.append(f"""
        <section style="border-left:5px solid {colour}">
          <h2>{e(run.scenario.id)} · {e(run.scenario.title)}
              <span style="background:{colour}">{'Réussi' if run.passed else 'Échoué'}</span></h2>
          <p>{e(run.scenario.description)} · {run.sim_time_s:.1f} s simulées</p>
          <table>{''.join(steps)}</table>
        </section>""")
    return f"""<!DOCTYPE html><html lang="fr"><head><meta charset="utf-8">
<title>Scénarios · {e(build_label)}</title><style>
body{{font-family:Segoe UI,system-ui,sans-serif;background:#f5f7fa;margin:0;color:#111827}}
header{{background:#0d131c;color:#e6edf5;padding:24px 40px}} header h1{{margin:0;font-size:22px}}
header p{{margin:4px 0 0;color:#9aa6b6}} main{{padding:24px 40px;max-width:1100px}}
section{{background:#fff;border-radius:10px;padding:14px 20px;margin-bottom:16px;box-shadow:0 1px 3px #0001}}
h2{{font-size:17px;margin:0 0 4px}} h2 span{{color:#fff;border-radius:9px;padding:1px 9px;font-size:12px;margin-left:8px}}
section p{{color:#6b7280;margin:0 0 8px;font-size:13px}} table{{border-collapse:collapse;width:100%;table-layout:fixed}}
td:nth-child(2){{width:24px}} td:nth-child(3){{width:55%}}
td{{padding:4px 8px;font-size:13px;border-top:1px solid #f0f2f5}} .n{{color:#9ca3af;width:24px}} .d{{color:#6b7280}}
</style></head><body><header><h1>Rapport de scénarios</h1>
<p>Build {e(build_label)} · {when:%d/%m/%Y %H:%M:%S} · {passed}/{len(runs)} scénarios réussis</p></header>
<main>{''.join(blocks)}</main></body></html>"""


def write_html(runs: list[ScenarioRun], build_label: str, directory: str | Path = "reports") -> Path:
    out = Path(directory)
    out.mkdir(parents=True, exist_ok=True)
    version = runs[0].build_version if runs else "build"
    path = out / f"{version}_scenarios_{datetime.now():%Y%m%d-%H%M%S}.html"
    path.write_text(to_html(runs, build_label), encoding="utf-8")
    return path
