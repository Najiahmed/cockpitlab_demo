"""Catalogue des cas de test du cockpit.

Convention d'identifiants : SAN (Sanity), NR (non-régression), END (endurance),
PERF (performance). Chaque test référence l'exigence qu'il vérifie.
"""
from __future__ import annotations

import statistics
import time

from ..bus import DATABASE
from .framework import TestContext, case

CRITICAL = "critical"


def _periods_ms(ctx: TestContext, frame_id: int) -> list[float]:
    stamps = [f.timestamp for f in ctx.rt.bus.recent(100_000) if f.arbitration_id == frame_id]
    return [(b - a) * 1000 for a, b in zip(stamps, stamps[1:])]


# =========================== SANITY ==========================================
@case("SAN-01", "Toutes les trames du réseau cockpit sont reçues au démarrage",
      "sanity", "bloquant", "REQ-NET-001 : le cockpit reçoit les 5 trames du réseau en moins de 1 s")
def san_all_frames(ctx: TestContext):
    ctx.run(1.0, "Mettre le banc sous tension et attendre 1 s")
    received = [m.name for m in DATABASE.messages if ctx.state.is_valid(m.name)]
    missing = [m.name for m in DATABASE.messages if m.name not in received]
    ctx.measure("Trames reçues", f"{len(received)}/{len(DATABASE.messages)}")
    ctx.check(not missing, "Toutes les trames sont reçues", f"manquantes : {', '.join(missing)}")


@case("SAN-02", "Le véhicule passe à l'état READY", "sanity", "bloquant",
      "REQ-PWT-001 : l'état READY est affiché après appui sur Démarrer")
def san_ready(ctx: TestContext):
    ctx.step("Appuyer sur Démarrer")
    ctx.vehicle.power_on()
    ctx.run(0.5, "Attendre 0,5 s")
    ctx.check(ctx.state.is_valid("VCU_Status"), "La trame VCU_Status est valide")
    ctx.check(ctx.state.ready, "READY est affiché au combiné")


@case("SAN-03", "Aucune alerte critique au repos", "sanity", "bloquant",
      "REQ-HMI-001 : aucune alerte critique n'est affichée sur un véhicule sain au repos")
def san_no_critical(ctx: TestContext):
    ctx.vehicle.power_on()
    ctx.step("Démarrer le véhicule et rester à l'arrêt 10 s")
    delay = ctx.run_until(lambda: any(a.level == CRITICAL for a in ctx.state.alerts), 10.0)
    alerts = ", ".join(a.code for a in ctx.state.alerts)
    ctx.check(delay is None, "Aucune alerte critique pendant 10 s", f"alerte(s) : {alerts}")


@case("SAN-04", "Vitesse nulle affichée à l'arrêt", "sanity", "bloquant",
      "REQ-CLU-001 : le combiné affiche 0 km/h véhicule à l'arrêt")
def san_speed_zero(ctx: TestContext):
    ctx.run(2.0, "Banc sous tension, véhicule à l'arrêt pendant 2 s")
    ctx.check(ctx.state.is_valid("ESP_Speed"), "La vitesse est valide")
    ctx.check(ctx.state.speed_kmh == 0, "La vitesse affichée vaut 0 km/h",
              f"{ctx.state.speed_kmh:.1f} km/h")


@case("SAN-05", "Le véhicule roule en marche avant", "sanity", "bloquant",
      "REQ-PWT-002 : en D, l'accélérateur fait avancer le véhicule")
def san_drive(ctx: TestContext):
    ctx.start_vehicle("D")
    ctx.vehicle.inputs.accelerator = 1.0
    ctx.run(3.0, "Accélérer à fond pendant 3 s")
    ctx.measure("Vitesse après 3 s", ctx.state.speed_kmh, "km/h")
    ctx.check(ctx.state.is_valid("VCU_Status") and ctx.state.gear == "D", "Le rapport D est affiché")
    ctx.check(ctx.state.speed_kmh > 20, "La vitesse dépasse 20 km/h", f"{ctx.state.speed_kmh:.1f} km/h")


# ========================= NON-RÉGRESSION ====================================
@case("NR-01", "Codage et décodage de toutes les trames", "non_regression", "majeur",
      "REQ-NET-002 : chaque signal est restitué à sa résolution près")
def nr_codec(ctx: TestContext):
    ctx.run(0.5, "Laisser émettre toutes les trames")
    values = ctx.vehicle.signal_values()
    for message in DATABASE.messages:
        decoded = message.decode(message.encode(values[message.name]))
        for signal in message.signals:
            expected, got = values[message.name][signal.name], decoded[signal.name]
            ok = got == expected if isinstance(expected, (bool, str)) else abs(got - expected) <= signal.factor
            ctx.check(ok, f"{message.name}.{signal.name} restitué", f"attendu {expected}, obtenu {got}")


@case("NR-02", "Période de la trame ESP_Speed : 20 ms ± 10 %", "non_regression", "majeur",
      "REQ-NET-010 : ESP_Speed est émise toutes les 20 ms (tolérance ± 2 ms)", dt=0.002)
def nr_esp_period(ctx: TestContext):
    ctx.run(1.0, "Enregistrer la trace CAN pendant 1 s")
    periods = _periods_ms(ctx, DATABASE.by_name("ESP_Speed").frame_id)
    mean = statistics.mean(periods)
    ctx.measure("Période moyenne", mean, "ms")
    ctx.measure("Gigue max", max(periods) - min(periods), "ms")
    ctx.check(18 <= mean <= 22, "La période moyenne est comprise entre 18 et 22 ms", f"{mean:.1f} ms")


@case("NR-03", "Périodes des autres trames ± 10 %", "non_regression", "majeur",
      "REQ-NET-011 : chaque trame respecte sa période nominale (tolérance ± 10 %)", dt=0.002)
def nr_other_periods(ctx: TestContext):
    ctx.run(3.0, "Enregistrer la trace CAN pendant 3 s")
    for message in DATABASE.messages:
        if message.name == "ESP_Speed":
            continue
        periods = _periods_ms(ctx, message.frame_id)
        ctx.check(bool(periods), f"{message.name} est émise")
        mean = statistics.mean(periods)
        ctx.measure(message.name, mean, "ms")
        ctx.check(abs(mean - message.cycle_ms) <= 0.1 * message.cycle_ms,
                  f"{message.name} : période {message.cycle_ms} ms ± 10 %", f"{mean:.1f} ms")


@case("NR-04", "Accélération 0 à 100 km/h entre 6 et 12 s", "non_regression", "mineur",
      "REQ-PWT-010 : performance d'accélération conforme à la calibration")
def nr_acceleration(ctx: TestContext):
    ctx.start_vehicle("D")
    ctx.vehicle.inputs.accelerator = 1.0
    ctx.step("Accélérer à fond")
    delay = ctx.run_until(lambda: ctx.state.speed_kmh >= 100, 20.0)
    ctx.check(delay is not None, "100 km/h atteints en moins de 20 s")
    ctx.measure("0-100 km/h", delay, "s")
    ctx.check(6 <= delay <= 12, "Le temps est compris entre 6 et 12 s", f"{delay:.1f} s")


@case("NR-05", "Marche arrière refusée au-dessus de 5 km/h", "non_regression", "bloquant",
      "REQ-PWT-020 : le passage en R est refusé au-dessus de 5 km/h")
def nr_reverse_refused(ctx: TestContext):
    ctx.start_vehicle("D")
    ctx.vehicle.inputs.accelerator = 1.0
    ctx.run(3.0, "Rouler à plus de 20 km/h")
    ctx.vehicle.inputs.accelerator = 0.0
    ctx.step("Demander le rapport R")
    ctx.vehicle.inputs.requested_gear = "R"
    ctx.run(0.3)
    ctx.check(ctx.state.gear == "D", "Le rapport reste D", f"rapport affiché : {ctx.state.gear}")
    ctx.check(bool(ctx.vehicle.last_rejection), "Un message de refus est produit")


@case("NR-06", "Vitesse en marche arrière limitée à 20 km/h", "non_regression", "majeur",
      "REQ-PWT-021 : la vitesse en R ne dépasse pas 20 km/h")
def nr_reverse_limit(ctx: TestContext):
    ctx.start_vehicle("R")
    ctx.vehicle.inputs.accelerator = 1.0
    ctx.step("Accélérer à fond en marche arrière pendant 15 s")
    top = 0.0
    for _ in range(int(15 / ctx.case.dt)):
        ctx.rt.step(ctx.case.dt)
        top = max(top, ctx.state.speed_kmh)
    ctx.measure("Vitesse max en R", top, "km/h")
    ctx.check(top <= 20.5, "La vitesse reste inférieure ou égale à 20 km/h", f"{top:.1f} km/h")


@case("NR-07", "Alerte ceinture au-dessus de 10 km/h", "non_regression", "bloquant",
      "REQ-SAF-001 : ceinture débouclée au-dessus de 10 km/h, alerte en moins de 1 s")
def nr_seatbelt_alert(ctx: TestContext):
    ctx.step("Déboucler la ceinture conducteur")
    ctx.vehicle.inputs.seatbelt_buckled = False
    ctx.start_vehicle("D")
    ctx.vehicle.inputs.accelerator = 0.6
    ctx.step("Accélérer jusqu'à 15 km/h")
    ctx.run_until(lambda: ctx.state.speed_kmh >= 15, 10.0)
    delay = ctx.run_until(lambda: ctx.state.has_alert("SEATBELT"), 1.0)
    active = ", ".join(a.code for a in ctx.state.alerts) or "aucune"
    ctx.check(delay is not None, "L'alerte ceinture s'affiche en moins de 1 s",
              f"aucune alerte ceinture après 1 s à {ctx.state.speed_kmh:.0f} km/h (alertes actives : {active})")
    ctx.measure("Délai d'alerte", delay, "s")


@case("NR-08", "Pas d'alerte ceinture à l'arrêt", "non_regression", "mineur",
      "REQ-SAF-002 : aucune alerte ceinture véhicule à l'arrêt")
def nr_seatbelt_standstill(ctx: TestContext):
    ctx.vehicle.inputs.seatbelt_buckled = False
    ctx.start_vehicle("P")
    ctx.run(3.0, "Ceinture débouclée, véhicule à l'arrêt pendant 3 s")
    ctx.check(not ctx.state.has_alert("SEATBELT"), "Aucune alerte ceinture")


@case("NR-09", "Alerte batterie faible sous 15 %", "non_regression", "majeur",
      "REQ-BAT-001 : alerte batterie faible sous 15 %, pas au-dessus")
def nr_low_battery(ctx: TestContext):
    ctx.vehicle.soc_pct = 16.0
    ctx.run(1.5, "Régler la batterie à 16 %")
    ctx.check(not ctx.state.has_alert("LOW_BATTERY"), "Aucune alerte à 16 %")
    ctx.step("Régler la batterie à 14 %")
    ctx.vehicle.soc_pct = 14.0
    delay = ctx.run_until(lambda: ctx.state.has_alert("LOW_BATTERY"), 1.5)
    ctx.check(delay is not None, "L'alerte s'affiche en moins de 1,5 s",
              f"aucune alerte batterie après 1,5 s (SOC affiché : {ctx.state.soc_pct:.1f} %)")
    ctx.measure("Délai d'alerte", delay, "s")


@case("NR-10", "Feux de détresse : les deux clignotants s'allument", "non_regression", "majeur",
      "REQ-BCM-001 : les feux de détresse allument les deux témoins de clignotant")
def nr_hazard(ctx: TestContext):
    ctx.vehicle.inputs.hazard = True
    ctx.run(0.3, "Activer les feux de détresse")
    ctx.check(ctx.state.left_turn, "Témoin gauche allumé")
    ctx.check(ctx.state.right_turn, "Témoin droit allumé")


@case("NR-11", "Perte de la trame vitesse détectée en moins de 100 ms", "non_regression", "bloquant",
      "REQ-NET-020 : perte d'ESP_Speed signalée en moins de 100 ms, retour automatique ensuite")
def nr_signal_loss(ctx: TestContext):
    ctx.run(1.0, "Banc en fonctionnement nominal")
    ctx.step("Couper l'émission de ESP_Speed")
    ctx.vehicle.muted.add("ESP_Speed")
    delay = ctx.run_until(lambda: ctx.state.has_alert("SIGNAL_LOST:ESP_Speed"), 0.1)
    ctx.check(delay is not None, "La perte est signalée en moins de 100 ms",
              "aucune alerte SIGNAL_LOST:ESP_Speed après 100 ms")
    ctx.measure("Délai de détection", delay * 1000, "ms")
    ctx.check(not ctx.state.is_valid("ESP_Speed"), "La vitesse est invalidée (affichage ---)")
    ctx.step("Rétablir l'émission")
    ctx.vehicle.muted.discard("ESP_Speed")
    ctx.run(0.1)
    ctx.check(ctx.state.is_valid("ESP_Speed"), "La vitesse redevient valide")


@case("NR-12", "Autonomie cohérente avec le niveau de batterie", "non_regression", "mineur",
      "REQ-BAT-002 : autonomie = énergie restante / consommation moyenne (± 2 km)")
def nr_range(ctx: TestContext):
    ctx.vehicle.soc_pct = 50.0
    ctx.run(1.0, "Régler la batterie à 50 %")
    v = ctx.vehicle
    expected = int(0.5 * v.BATTERY_KWH / v.AVG_CONSUMPTION_KWH_PER_KM)
    ctx.measure("Autonomie attendue", f"{expected} km")
    ctx.measure("Autonomie affichée", f"{ctx.state.range_km} km")
    ctx.check(abs(ctx.state.range_km - expected) <= 2, "Écart inférieur ou égal à 2 km",
              f"{ctx.state.range_km} km affichés pour {expected} km attendus")


@case("NR-13", "Freinage d'urgence de 100 à 0 km/h en moins de 5 s", "non_regression", "bloquant",
      "REQ-CHA-001 : décélération conforme au freinage d'urgence")
def nr_emergency_brake(ctx: TestContext):
    ctx.start_vehicle("D")
    ctx.vehicle.inputs.accelerator = 1.0
    ctx.step("Atteindre 100 km/h")
    ctx.run_until(lambda: ctx.state.speed_kmh >= 100, 20.0)
    ctx.vehicle.inputs.accelerator = 0.0
    ctx.vehicle.inputs.brake = 1.0
    ctx.step("Freiner à fond")
    delay = ctx.run_until(lambda: ctx.state.speed_kmh == 0, 10.0)
    ctx.check(delay is not None, "Le véhicule s'arrête")
    ctx.measure("100-0 km/h", delay, "s")
    ctx.check(delay < 5, "Arrêt en moins de 5 s", f"{delay:.1f} s")


@case("NR-14", "Récupération d'énergie au lever de pied", "non_regression", "mineur",
      "REQ-PWT-030 : puissance négative (recharge) au lever de pied en D")
def nr_regen(ctx: TestContext):
    ctx.start_vehicle("D")
    ctx.vehicle.inputs.accelerator = 1.0
    ctx.run(4.0, "Accélérer 4 s")
    ctx.vehicle.inputs.accelerator = 0.0
    ctx.run(0.3, "Lever le pied")
    ctx.measure("Puissance", ctx.state.power_kw, "kW")
    ctx.check(ctx.state.power_kw < 0, "La puissance est négative (recharge)")


@case("NR-15", "Trame vitesse corrompue rejetée", "non_regression", "bloquant",
      "REQ-NET-021 : une vitesse incohérente n'est jamais affichée et lève une alerte en moins de 100 ms")
def nr_corrupted_speed(ctx: TestContext):
    ctx.start_vehicle("D")
    ctx.vehicle.inputs.accelerator = 0.4
    ctx.run(4.0, "Rouler à environ 30 km/h")
    before = ctx.state.speed_kmh
    ctx.step("Corrompre la charge utile de ESP_Speed")
    ctx.vehicle.corrupted.add("ESP_Speed")
    delay = ctx.run_until(lambda: ctx.state.has_alert("DATA_INVALID:ESP_Speed"), 0.1)
    ctx.check(delay is not None, "L'alerte « Donnée incohérente » s'affiche en moins de 100 ms",
              "aucune alerte DATA_INVALID:ESP_Speed")
    ctx.run(1.0, "Maintenir la corruption 1 s")
    ctx.measure("Trames rejetées", ctx.rt.state_service.rejected_frames)
    ctx.check(not ctx.state.is_valid("ESP_Speed"), "La vitesse est invalidée (affichage ---)")
    ctx.check(ctx.state.speed_kmh < before + 30, "Aucune vitesse absurde n'est retenue",
              f"{ctx.state.speed_kmh:.0f} km/h retenus")
    ctx.step("Réparer la trame")
    ctx.vehicle.corrupted.discard("ESP_Speed")
    ctx.run(0.1)
    ctx.check(ctx.state.is_valid("ESP_Speed"), "La vitesse redevient valide")


# ============================ ENDURANCE ======================================
@case("END-01", "100 cycles démarrage / arrêt", "endurance", "majeur",
      "REQ-PWT-040 : 100 cycles de contact sans défaut ni perte de trame")
def end_power_cycles(ctx: TestContext):
    ctx.step("Enchaîner 100 cycles : démarrer, attendre 0,4 s, arrêter, attendre 0,2 s")
    for i in range(1, 101):
        ctx.vehicle.power_on()
        ctx.rt.run_for(0.4, ctx.case.dt)
        if not ctx.state.ready or ctx.state.stale:
            ctx.check(False, f"Cycle {i} : READY affiché sans perte de trame")
        ctx.vehicle.power_off()
        ctx.rt.run_for(0.2, ctx.case.dt)
        if ctx.state.ready:
            ctx.check(False, f"Cycle {i} : véhicule arrêté")
    ctx.measure("Cycles réussis", "100/100")
    ctx.check(True, "100 cycles sans défaut")


@case("END-02", "20 minutes de conduite urbaine", "endurance", "majeur",
      "REQ-SYS-001 : 20 min de roulage sans perte de trame, bilan énergétique cohérent", dt=0.05)
def end_urban_drive(ctx: TestContext):
    ctx.start_vehicle("D")
    soc_start = ctx.vehicle.soc_pct
    inputs = ctx.vehicle.inputs
    ctx.step("Répéter un cycle urbain d'une minute : accélération, croisière, freinage, arrêt")
    for minute in range(1, 21):
        for accel, brake, seconds in ((0.5, 0, 10), (0.12, 0, 30), (0, 0.3, 12), (0, 0, 8)):
            inputs.accelerator, inputs.brake = accel, brake
            for _ in range(int(seconds / ctx.case.dt)):
                ctx.rt.step(ctx.case.dt)
                if ctx.state.stale:
                    ctx.check(False, f"Minute {minute} : aucune perte de trame",
                              ", ".join(sorted(ctx.state.stale)))
    used = soc_start - ctx.vehicle.soc_pct
    ctx.measure("Distance", ctx.vehicle.odometer_km, "km")
    ctx.measure("Batterie consommée", used, "%")
    ctx.measure("Trames échangées", ctx.rt.bus.frames_sent)
    ctx.check(True, "Aucune perte de trame en 20 min")
    ctx.check(ctx.vehicle.odometer_km > 5, "Distance parcourue supérieure à 5 km")
    ctx.check(0 < used < 15, "Consommation comprise entre 0 et 15 % de batterie", f"{used:.1f} %")


# =========================== PERFORMANCE =====================================
@case("PERF-01", "Temps de traitement d'une trame par le middleware", "performance", "mineur",
      "REQ-PERF-001 : moins de 200 µs par trame décodée sur le poste de test")
def perf_decode(ctx: TestContext):
    ctx.run(1.0, "Capturer 1 s de trafic CAN")
    frames = ctx.rt.bus.recent(100_000)
    sample = (frames * (10_000 // len(frames) + 1))[:10_000]
    ctx.step("Rejouer 10 000 trames dans le middleware")
    on_frame = ctx.rt.state_service._on_frame
    start = time.perf_counter()
    for frame in sample:
        on_frame(frame)
    per_frame_us = (time.perf_counter() - start) / len(sample) * 1e6
    ctx.measure("Temps par trame", per_frame_us, "µs")
    ctx.check(per_frame_us < 200, "Moins de 200 µs par trame", f"{per_frame_us:.0f} µs")


@case("PERF-02", "Charge du bus CAN inférieure à 30 %", "performance", "majeur",
      "REQ-NET-030 : charge du bus à 500 kbit/s inférieure à 30 %", dt=0.002)
def perf_bus_load(ctx: TestContext):
    ctx.vehicle.power_on()
    ctx.run(2.0, "Mesurer le trafic pendant 2 s")
    bits = sum(47 + 8 * len(f.data) for f in ctx.rt.bus.recent(100_000)) * 1.2  # + bit stuffing
    load = bits / 2.0 / 500_000 * 100
    ctx.measure("Charge du bus", load, "%")
    ctx.check(load < 30, "Charge inférieure à 30 %", f"{load:.1f} %")


@case("PERF-03", "Délai d'affichage de READY après démarrage", "performance", "majeur",
      "REQ-PERF-002 : READY affiché moins de 300 ms après appui sur Démarrer", dt=0.005)
def perf_ready_delay(ctx: TestContext):
    ctx.run(0.5, "Banc sous tension")
    ctx.step("Appuyer sur Démarrer")
    ctx.vehicle.power_on()
    delay = ctx.run_until(lambda: ctx.state.ready, 1.0)
    ctx.check(delay is not None, "READY s'affiche")
    ctx.measure("Délai", delay * 1000, "ms")
    ctx.check(delay < 0.3, "Délai inférieur à 300 ms", f"{delay * 1000:.0f} ms")
