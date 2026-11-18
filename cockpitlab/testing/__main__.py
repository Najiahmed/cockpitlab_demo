"""Lance une campagne en ligne de commande (utilisé par la CI, comme un job Jenkins).

    python -m cockpitlab.testing --build 26.10.2 --campaign sanity
    python -m cockpitlab.testing --list

Code de sortie : 0 si GO ou GO AVEC RÉSERVES, 1 sinon.
"""
import argparse
import sys

from ..builds import BUILDS, REFERENCE_BUILD, get_build
from .framework import REGISTRY
from .report import write_reports
from .runner import CAMPAIGNS, GO, GO_RESERVES, run_campaign


def main() -> int:
    parser = argparse.ArgumentParser(prog="cockpitlab.testing")
    parser.add_argument("--build", default=REFERENCE_BUILD.version)
    parser.add_argument("--campaign", choices=list(CAMPAIGNS), default="sanity")
    parser.add_argument("--output", default="reports")
    parser.add_argument("--list", action="store_true", help="liste les builds et les tests")
    args = parser.parse_args()

    if args.list:
        print("Builds :")
        for b in BUILDS:
            print(f"  {b.version:22} {b.channel:18} {b.description}")
        print("\nTests :")
        for c in REGISTRY:
            print(f"  {c.id:8} {c.category:15} {c.severity:9} {c.title}")
        return 0

    build = get_build(args.build)
    campaign = CAMPAIGNS[args.campaign]
    print(f"Campagne {campaign.name} sur la build {build.label}\n")

    def on_result(r):
        mark = {"PASSED": "OK  ", "FAILED": "KO  ", "ERROR": "ERR ", "SKIPPED": "--  "}[r.status.name]
        detail = f"  -> {r.message}" if r.message else ""
        print(f"  {mark}{r.case.id:8} {r.case.title}{detail}")

    report = run_campaign(build, args.campaign, on_result=on_result)
    paths = write_reports(report, args.output)
    print(f"\nVerdict : {report.verdict}   ({report.duration_s:.1f} s)")
    for kind, path in paths.items():
        print(f"  {kind:6} {path}")
    return 0 if report.verdict in (GO, GO_RESERVES) else 1


if __name__ == "__main__":
    sys.exit(main())
