# CockpitLab · documentation technique

Présentation du projet : voir le [README](README.md).

Cockpit Android Automotive **simulé** sur PC, avec un banc de test intégré :
combiné d'instrumentation, écran central, bus CAN virtuel, campagnes de tests
Sanity et de non-régression, scénarios joués en direct et injection de défauts.

> Projet personnel de démonstration. Le design, les trames CAN, les noms de signaux
> et les contenus sont inventés. Aucun élément ne provient d'un constructeur.

## Lancer le projet (Windows)

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

Pour passer par le bus virtuel de python-can : `python main.py --bus python-can`.

Lancer les tests : `pytest -v`

## Prise en main

1. Dans le banc de test (en bas), cliquez sur **Démarrer**, puis sur **D**.
2. Maintenez **↑** pour accélérer et **↓** pour freiner (ou utilisez les curseurs).
3. Essayez de passer en **R** en roulant : la demande est refusée au-dessus de 5 km/h.
4. Débouclez la ceinture en roulant, ou forcez la batterie à 12 % : une alerte s'affiche sur le combiné.
5. Ouvrez l'onglet **Trace CAN** pour voir les trames passer et leurs valeurs décodées.
6. Ouvrez l'onglet **Tests**, choisissez une build et une campagne, puis cliquez sur **Lancer la campagne**.
7. Ouvrez l'onglet **Scénarios**, installez la build `26.11.0-rc1` sur le banc et jouez **SCN-02** :
   le cockpit roule seul, et l'échec s'affiche en direct dans le bandeau au-dessus des écrans.

## Scénarios joués en direct (onglet Scénarios)

Un scénario est une suite d'actions et de vérifications décrite en **JSON**, dans
`cockpitlab/scenarios/data/`. Il se joue en direct sur le cockpit (en temps réel,
× 2 ou × 4), avec un bandeau de narration au-dessus des écrans, ou sans interface
pour la CI :

```powershell
python -m cockpitlab.scenarios --build 26.11.0-rc1
python -m cockpitlab.scenarios --build 26.10.2 --scenario SCN-05
```

| Scénario | Ce qu'il vérifie |
|---|---|
| SCN-01 Démarrage et premier trajet | Parcours nominal complet, sans alerte critique |
| SCN-02 Ceinture débouclée en roulant | Alerte au-dessus de 10 km/h, disparition quand on boucle |
| SCN-03 Batterie faible pendant un trajet | Alerte sous 15 %, autonomie cohérente |
| SCN-04 Manœuvre de stationnement | R refusée en roulant, puis limitée à 20 km/h |
| SCN-05 Perte du calculateur ESP | Vitesse invalidée (---) en moins de 100 ms, retour automatique |
| SCN-06 Trame vitesse corrompue | Donnée incohérente rejetée, jamais affichée |
| SCN-07 Freinage d'urgence | Arrêt depuis 110 km/h en moins de 5 s, détresse, récupération d'énergie |

Écrire un nouveau scénario ne demande aucun code :

```json
{"id": "SCN-08", "title": "Mon scénario", "steps": [
  {"label": "Démarrer", "action": "power_on"},
  {"label": "Engager D", "action": "gear", "value": "D"},
  {"label": "Accélérer", "action": "accelerator", "value": 0.5},
  {"label": "Atteindre 30 km/h", "wait_until": {"speed_kmh": [">=", 30]}, "timeout": 10},
  {"label": "Aucune alerte critique", "expect": {"no_critical": true}, "during": 2.0}
]}
```

Actions : `power_on`, `power_off`, `gear`, `accelerator`, `brake`, `release`, `input`
(clignotants, feux, ceinture), `soc`, `battery_temp`, `mute` / `unmute` (couper une trame),
`corrupt` / `repair` (corrompre une trame). Vérifications : `expect` (immédiate,
`within` un délai, ou tenue `during` une durée) et `wait_until`. Un fichier mal écrit
est refusé au chargement avec un message qui indique l'étape fautive.

Le même onglet permet de **changer la build installée à chaud** et d'**injecter des
défauts pendant la conduite manuelle** : couper ou corrompre n'importe quelle trame,
faire chauffer la batterie.

### Plausibilité des données

Le middleware rejette les valeurs incohérentes (vitesse hors plage ou qui saute de
plus de 30 km/h entre deux trames, batterie au-delà de 100 %, puissance impossible).
Le combiné affiche alors `---` et l'alerte « Donnée incohérente », et non « Communication
perdue » : la trame arrive, mais son contenu est faux.

**Limite connue, testée et documentée** : la trame `BCM_Lights` ne transporte que des
états binaires, sans grandeur contrôlable. Sa corruption passe inaperçue. Sur un vrai
véhicule, ce type de trame est protégé par un CRC et un compteur (mécanisme E2E d'AUTOSAR).

## Qualification des builds (onglet Tests)

Le banc reçoit des **builds** à qualifier. Chacune peut contenir des régressions
que les campagnes doivent détecter, comme sur un vrai banc d'intégration.

| Build | Canal | Contenu annoncé |
|---|---|---|
| 26.10.2 | release | Release de référence, déjà qualifiée |
| 26.11.0-rc1 | release candidate | Refonte du moteur d'alertes, nouvelle calibration marche arrière |
| 26.11.0-rc2 | release candidate | Correctifs de la rc1, nouveau calcul d'autonomie |
| 26.12.0-nightly.142 | nightly | Mise à jour de la pile réseau du VCU |
| 26.12.0-nightly.143 | nightly | Correctif VCU, optimisation de l'ordonnanceur ESP |

**Campagnes** : Sanity Check (5 tests), Non-régression (15), Endurance (2),
Performance (3), Qualification complète (25). Toutes les campagnes sauf la Sanity
seule commencent par la Sanity : si elle échoue, la suite n'est pas exécutée et la
build est rejetée.

**Verdict** :

| Verdict | Règle |
|---|---|
| BUILD REJETÉE | au moins un test de Sanity en échec |
| NO-GO | au moins un échec bloquant ou majeur |
| GO AVEC RÉSERVES | uniquement des échecs mineurs |
| GO | aucun échec |

Chaque échec produit des **preuves** (état du véhicule, trames en timeout, extrait
de trace CAN) et un **brouillon de ticket** prêt à copier dans Jira. Les rapports
sont enregistrés dans `reports/` en HTML (lecture), JUnit XML (Jenkins, GitLab)
et JSON.

### En ligne de commande (comme un job Jenkins)

```powershell
python -m cockpitlab.testing --list
python -m cockpitlab.testing --build 26.11.0-rc1 --campaign non_regression
```

Le code de sortie vaut 0 pour GO ou GO AVEC RÉSERVES, 1 sinon : un pipeline
s'arrête donc automatiquement sur une build NO-GO. Dans GitHub Actions, le job
**Qualification de la build** se lance aussi à la main (onglet Actions, *Run workflow*)
avec la build et la campagne de son choix, et publie les rapports.

## Architecture

```
 Banc de test (pilotage)           Écrans
        │ DriverInputs            ┌──────────────┐  ┌───────────────┐
        ▼                         │   Combiné    │  │ Écran central │
 ┌──────────────────┐             └──────▲───────┘  └──────▲────────┘
 │ VehicleSimulator │                    │ VehicleState    │
 │ ESP VCU BMS BCM  │             ┌──────┴─────────────────┴──┐
 │ ACU (calculateurs)│            │ Middleware                 │
 └────────┬─────────┘             │ décodage, timeouts, alertes │
          │ trames CAN            └──────────────▲─────────────┘
          ▼                                      │
 ┌────────────────────────────────────────────────┴─┐
 │ Bus CAN virtuel (mémoire ou python-can) + trace   │
 └───────────────────────────────────────────────────┘
```

| Dossier | Rôle |
|---|---|
| `cockpitlab/bus` | Base de signaux (équivalent DBC), codage/décodage, bus virtuel, trace |
| `cockpitlab/vehicle` | Simulateur physique : vitesse, rapports, batterie, feux, ceinture |
| `cockpitlab/middleware` | État véhicule exposé aux écrans, détection de perte de trame, règles d'alerte |
| `cockpitlab/app` | Assemblage, horloge simulée (utilisé par l'interface et les tests) |
| `cockpitlab/builds.py` | Builds à qualifier et régressions qu'elles contiennent |
| `cockpitlab/testing` | Framework de test, catalogue des 25 tests, campagnes, verdict, rapports |
| `cockpitlab/scenarios` | Moteur de scénarios JSON, 7 scénarios, rapport, ligne de commande |
| `cockpitlab/hmi` | Interface PySide6 : combiné, écran central, banc de test, onglet Tests |
| `tests` | Tests pytest du simulateur et du banc lui-même (chaque régression doit être détectée) |

Le cœur (`bus`, `vehicle`, `middleware`, `app`) ne dépend pas de Qt : les tests
tournent en quelques millisecondes et en CI, avec une horloge simulée déterministe.

### Trames CAN

| ID | Message | Émetteur | Période | Signaux |
|---|---|---|---|---|
| 0x0C8 | VCU_Status | VCU | 100 ms | gear, ready, power_kw |
| 0x1A0 | ESP_Speed | ESP | 20 ms | speed_kmh |
| 0x2D0 | BCM_Lights | BCM | 100 ms | clignotants, détresse, feux |
| 0x2F0 | ACU_Seatbelt | ACU | 500 ms | seatbelt_buckled |
| 0x3B0 | BMS_Battery | BMS | 500 ms | soc_pct, range_km, battery_temp_c |

Une trame est déclarée perdue après 3 périodes sans réception. Le combiné affiche
alors `---` et une alerte « Communication perdue ».

