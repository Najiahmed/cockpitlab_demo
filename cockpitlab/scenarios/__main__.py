"""Joue les scénarios sans interface.

    python -m cockpitlab.scenarios --build 26.11.0-rc1
    python -m cockpitlab.scenarios --build 26.10.2 --scenario SCN-05
"""
import argparse
import sys

from ..app.runtime import CockpitRuntime
from ..builds import REFERENCE_BUILD, get_build
from .engine import ScenarioPlayer, StepStatus, load_scenarios
from .report import write_html

MARKS = {StepStatus.PASSED: "OK", StepStatus.FAILED: "KO", StepStatus.SKIPPED: "--"}


def main() -> int:
    parser = argparse.ArgumentParser(prog="cockpitlab.scenarios")
    parser.add_argument("--build", default=REFERENCE_BUILD.version)
    parser.add_argument("--scenario", help="identifiant, par exemple SCN-02 (tous par défaut)")
    parser.add_argument("--output", default="reports")
    args = parser.parse_args()

    build = get_build(args.build)
    scenarios = [s for s in load_scenarios() if not args.scenario or s.id == args.scenario]
    if not scenarios:
        print(f"Scénario introuvable : {args.scenario}")
        return 2
    runs = []
    for scenario in scenarios:
        runtime = CockpitRuntime(build=build)
        run = ScenarioPlayer(runtime, scenario).run_headless()
        runs.append(run)
        print(f"\n{'RÉUSSI' if run.passed else 'ÉCHOUÉ'}  {scenario.id} · {scenario.title}")
        for step, result in zip(scenario.steps, run.results):
            if step.is_check or result.status == StepStatus.FAILED:
                print(f"   {MARKS.get(result.status, '  ')}  {step.label}"
                      + (f"  ({result.detail})" if result.detail else ""))
    path = write_html(runs, build.label, args.output)
    print(f"\n{sum(r.passed for r in runs)}/{len(runs)} scénarios réussis sur {build.label}")
    print(f"Rapport : {path}")
    return 0 if all(r.passed for r in runs) else 1


if __name__ == "__main__":
    sys.exit(main())
