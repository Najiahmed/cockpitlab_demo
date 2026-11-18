"""Builds logicielles livrées au banc.

Chaque build active (ou non) des défauts dans le simulateur et le middleware :
c'est ce qui permet de démontrer que les campagnes détectent les régressions.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Build:
    version: str
    channel: str
    description: str
    faults: frozenset[str] = frozenset()

    @property
    def label(self) -> str:
        return f"{self.version} ({self.channel})"


# Défauts disponibles
VCU_SILENT = "VCU_SILENT"                        # le calculateur VCU n'émet plus
ESP_SLOW_CYCLE = "ESP_SLOW_CYCLE"                # ESP_Speed émise toutes les 26 ms au lieu de 20
SEATBELT_ALERT_MISSING = "SEATBELT_ALERT_MISSING"  # règle d'alerte ceinture cassée
REVERSE_LIMIT_BROKEN = "REVERSE_LIMIT_BROKEN"    # limitation marche arrière à 40 km/h
RANGE_OFFSET = "RANGE_OFFSET"                    # autonomie affichée surestimée de 15 km

FAULT_DESCRIPTIONS = {
    VCU_SILENT: "Le calculateur VCU n'émet plus sa trame VCU_Status",
    ESP_SLOW_CYCLE: "Trame ESP_Speed émise toutes les 26 ms au lieu de 20 ms",
    SEATBELT_ALERT_MISSING: "L'alerte ceinture n'est plus levée",
    REVERSE_LIMIT_BROKEN: "Vitesse en marche arrière limitée à 40 km/h au lieu de 20",
    RANGE_OFFSET: "Autonomie surestimée de 15 km",
}

BUILDS: tuple[Build, ...] = (
    Build("26.10.2", "release", "Release de référence, déjà qualifiée"),
    Build("26.11.0-rc1", "release candidate",
          "Refonte du moteur d'alertes et nouvelle calibration de la marche arrière",
          frozenset({SEATBELT_ALERT_MISSING, REVERSE_LIMIT_BROKEN})),
    Build("26.11.0-rc2", "release candidate",
          "Correctifs de la rc1, nouveau calcul d'autonomie",
          frozenset({RANGE_OFFSET})),
    Build("26.12.0-nightly.142", "nightly",
          "Mise à jour de la pile réseau du VCU",
          frozenset({VCU_SILENT})),
    Build("26.12.0-nightly.143", "nightly",
          "Correctif VCU, optimisation de l'ordonnanceur ESP",
          frozenset({ESP_SLOW_CYCLE})),
)

REFERENCE_BUILD = BUILDS[0]


def get_build(version: str) -> Build:
    for build in BUILDS:
        if build.version == version:
            return build
    raise KeyError(f"Build inconnue : {version}")
