import json
from pathlib import Path

import matplotlib.pyplot as plt
import math
from docplex.mp.model import Model

from dataclasses import dataclass


@dataclass
class UtilityHEN:
    codice: str
    nome: str
    tipo: str
    T_in: float
    T_out: float
    h_W_m2K: float
    costo_USD_per_kW_year: float = None
    duty_variabile: bool = True
    disponibile: bool = True

@dataclass
class TecnologiaHEN:
    codice: str
    nome: str
    FHEX: float
    A_max_m2: float
    costo_fisso_USD_per_year: float
    costo_area_USD_per_m2_year: float
    matches: frozenset
    enabled: bool = True

class Flusso:
    """Corrente sensibile o carico termico isotermo."""

    def __init__(
        self,
        codice,
        nome,
        tipo,
        T_in,
        T_out,
        CP=None,
        processo=None,
        zona=None,
        disponibile=True,
        heat_load_kW=None,
        delta_T_min_half=None,
        isotermo=None,
        remark=None,
        unit=None,
        h_W_m2K=None,
    ):
        if tipo not in ("hot", "cold"):
            raise ValueError(
                f"Tipo non valido per il flusso "
                f"{codice}: {tipo}"
            )

        self.codice = codice
        self.nome = nome
        self.tipo = tipo

        self.T_in = float(T_in)
        self.T_out = float(T_out)

        self.heat_load_kW = (
            None
            if heat_load_kW is None
            else float(heat_load_kW)
        )

        self.delta_T_min_half = (
            None
            if delta_T_min_half is None
            else float(delta_T_min_half)
        )

        # =============================================
        # COEFFICIENTE DI SCAMBIO PER HENS
        # =============================================

        self.h_W_m2K = (
            None
            if h_W_m2K is None
            else float(h_W_m2K)
        )

        if (
            self.h_W_m2K is not None
            and self.h_W_m2K <= 0
        ):
            raise ValueError(
                f"h_W_m2K non valido per "
                f"{codice}: {self.h_W_m2K}"
            )


        # =============================================
        # FLUSSO ISOTERMO
        # =============================================

        self.isotermo = (
            abs(
                self.T_in
                - self.T_out
            ) <= 1e-12
            if isotermo is None
            else bool(isotermo)
        )


        self.processo = processo
        self.zona = zona
        self.disponibile = bool(disponibile)
        self.remark = remark
        self.unit = unit


        # =============================================
        # CALCOLO CP
        # =============================================

        if self.isotermo:

            if self.heat_load_kW is None:
                raise ValueError(
                    f"Il flusso isotermo "
                    f"{codice} richiede "
                    f"heat_load_kW."
                )

            self.CP = (
                None
                if CP is None
                else float(CP)
            )

        elif CP is not None:

            self.CP = float(CP)

        elif self.heat_load_kW is not None:

            self.CP = (
                self.heat_load_kW
                /
                abs(
                    self.T_out
                    - self.T_in
                )
            )

        else:

            raise ValueError(
                f"Il flusso {codice} "
                f"richiede CP oppure "
                f"heat_load_kW."
            )


    def calcola_Q(self):

        if self.heat_load_kW is not None:
            return self.heat_load_kW

        return (
            self.CP
            * abs(
                self.T_in
                - self.T_out
            )
        )


    def calcola_T_traslate(
        self,
        delta_T_min,
    ):

        delta_half = (
            self.delta_T_min_half
            if self.delta_T_min_half
            is not None
            else delta_T_min / 2
        )

        traslazione = (
            -delta_half
            if self.tipo == "hot"
            else delta_half
        )

        return (
            self.T_in + traslazione,
            self.T_out + traslazione,
        )

def carica_caso_studio(percorso_json):
    """Carica il caso studio dal file JSON."""

    with Path(percorso_json).open(
        mode="r",
        encoding="utf-8",
    ) as file:
        configurazione = json.load(file)

    configurazione["flussi_oggetti"] = [Flusso(**dati_flusso)
        for dati_flusso in configurazione["flussi"]]

    return configurazione

def crea_cascata_termica(flussi, delta_T_min, tolleranza=1e-9):
    """Crea la cascata termica includendo i carichi termici isotermi."""

    flussi_attivi = [
        flusso for flusso in flussi
        if flusso.disponibile
    ]

    # Traslazione delle temperature e individuazione dei carichi isotermi
    flussi_traslati = []
    temperature = []
    carichi_isotermi = {}

    for flusso in flussi_attivi:

        T_in_star, T_out_star = flusso.calcola_T_traslate(delta_T_min)

        flussi_traslati.append(
            (flusso, T_in_star, T_out_star)
        )

        temperature.extend([
            T_in_star,
            T_out_star,
        ])

        if flusso.isotermo:

            if T_in_star not in carichi_isotermi:
                carichi_isotermi[T_in_star] = {
                    "hot": 0.0,
                    "cold": 0.0,
                }

            carichi_isotermi[T_in_star][flusso.tipo] += flusso.calcola_Q()

    # Livelli di temperatura della problem table
    livelli = sorted(
        set(temperature),
        reverse=True,
    )

    risultati = []
    cascata_provvisoria = 0.0

    # Costruzione della cascata termica
    for indice, T_sup in enumerate(livelli):

        # Carichi termici isotermi
        if T_sup in carichi_isotermi:

            Q_hot = carichi_isotermi[T_sup]["hot"]
            Q_cold = carichi_isotermi[T_sup]["cold"]

            delta_H = Q_hot - Q_cold
            cascata_provvisoria += delta_H

            risultati.append({
                "T_sup": T_sup,
                "T_inf": T_sup,
                "CP_hot": 0.0,
                "CP_cold": 0.0,
                "delta_H_hot": Q_hot,
                "delta_H_cold": Q_cold,
                "delta_H": delta_H,
                "cascata_provvisoria": cascata_provvisoria,
            })

        # Dopo l'ultimo livello non esistono altri intervalli
        if indice == len(livelli) - 1:
            break

        T_inf = livelli[indice + 1]

        # Capacità termiche complessive nell'intervallo
        CP_hot = 0.0
        CP_cold = 0.0

        for flusso, T_in_star, T_out_star in flussi_traslati:

            if flusso.isotermo:
                continue

            T_max = max(T_in_star, T_out_star)
            T_min = min(T_in_star, T_out_star)

            if T_max >= T_sup and T_min <= T_inf:

                if flusso.tipo == "hot":
                    CP_hot += flusso.CP
                else:
                    CP_cold += flusso.CP

        # Bilancio energetico dell'intervallo
        delta_T = T_sup - T_inf

        Q_hot = CP_hot * delta_T
        Q_cold = CP_cold * delta_T
        delta_H = Q_hot - Q_cold

        cascata_provvisoria += delta_H

        risultati.append({
            "T_sup": T_sup,
            "T_inf": T_inf,
            "CP_hot": CP_hot,
            "CP_cold": CP_cold,
            "delta_H_hot": Q_hot,
            "delta_H_cold": Q_cold,
            "delta_H": delta_H,
            "cascata_provvisoria": cascata_provvisoria,
        })

    # Minimum Energy Requirements
    valori_cascata = [
        0.0,
        *[
            riga["cascata_provvisoria"]
            for riga in risultati
        ],
    ]

    QH_min = max(
        0.0,
        -min(valori_cascata),
    )

    # Cascata termica finale
    for riga in risultati:
        riga["cascata_finale"] = (
            riga["cascata_provvisoria"]
            + QH_min
        )

    QC_min = risultati[-1]["cascata_finale"]

    # Temperature traslate dei pinch point
    pinch_traslati = []

    if abs(QH_min) <= tolleranza:
        pinch_traslati.append(livelli[0])

    for riga in risultati:

        if abs(riga["cascata_finale"]) <= tolleranza:
            pinch_traslati.append(
                riga["T_inf"]
            )

    pinch_traslati = list(
        dict.fromkeys(pinch_traslati)
    )

    return (
        risultati,
        QH_min,
        QC_min,
        pinch_traslati,
    )

def costruisci_curve_composite(
    risultati, QC_min, tolleranza=1e-9,
):
    """Costruisce Hot e Cold Composite Curve a temperature traslate."""

    def costruisci_lato(
        chiave_CP,
        chiave_delta_H,
        Q_iniziale,
    ):

        indici_attivi = [
            i
            for i, riga in enumerate(risultati)
            if riga[chiave_CP] > tolleranza
            or riga[chiave_delta_H] > tolleranza
        ]

        elementi = list(
            reversed(
                risultati[
                    indici_attivi[0]:
                    indici_attivi[-1] + 1
                ]
            )
        )

        Q = Q_iniziale

        punti = [
            (Q, elementi[0]["T_inf"])
        ]

        for riga in elementi:

            Q += riga[chiave_delta_H]

            punti.append(
                (Q, riga["T_sup"])
            )

        return punti

    hot_CC_traslata = costruisci_lato(
        "CP_hot",
        "delta_H_hot",
        0.0,
    )

    cold_CC_traslata = costruisci_lato(
        "CP_cold",
        "delta_H_cold",
        QC_min,
    )

    return (
        hot_CC_traslata,
        cold_CC_traslata,
    )

def costruisci_GCC(risultati, QH_min):
    gcc = [(QH_min, risultati[0]["T_sup"])]
    gcc.extend((riga["cascata_finale"], riga["T_inf"]) for riga in risultati)
    return gcc

def self_sufficient_pockets(gcc, delta_T_min, tolleranza=1e-9):
    """Individua MPP, PPP e self-sufficient pockets sulla GCC."""
    def crea_record(codice, tipo, indice, posizione):
        Q, T_star = gcc[indice]
        return {
            "codice": codice,
            "tipo": tipo,
            "indice_gcc": indice,
            "Q_kW": 0.0 if abs(Q) <= tolleranza else Q,
            "T_traslata_C": T_star,
            "T_hot_C": T_star + delta_T_min / 2,
            "T_cold_C": T_star - delta_T_min / 2,
            "posizione": posizione,
        }

    indici_mpp = [i for i, (Q, _) in enumerate(gcc) if abs(Q) <= tolleranza]
    if not indici_mpp:
        raise ValueError("La GCC non contiene alcun Main Pinch Point.")
    main_pinch_points = [
        crea_record(f"MPP_{n}", "main_pinch_point", i, "main_pinch")
        for n, i in enumerate(indici_mpp, start=1)
    ]
    primo_mpp = min(indici_mpp)
    ultimo_mpp = max(indici_mpp)

    potential_pinch_points = []
    for i in range(1, len(gcc) - 1):
        Q_precedente = gcc[i - 1][0]
        Q_corrente = gcc[i][0]
        Q_successivo = gcc[i + 1][0]
        minimo_locale = (
            Q_corrente < Q_precedente - tolleranza
            and Q_corrente < Q_successivo - tolleranza
        )
        if Q_corrente <= tolleranza or not minimo_locale:
            continue
        if i < primo_mpp:
            posizione = "sopra_main_pinch"
        elif i > ultimo_mpp:
            posizione = "sotto_main_pinch"
        else:
            posizione = "tra_main_pinch"
        potential_pinch_points.append(
            crea_record(
                f"PPP_{len(potential_pinch_points) + 1}",
                "potential_pinch_point", i, posizione,
            )
        )

    pockets = []
    indice_pinch = indici_mpp[0]
    punti_sopra = gcc[:indice_pinch + 1]
    punti_sotto = list(reversed(gcc[indice_pinch:]))
    for nome_zona, punti_zona in (
        ("sopra_pinch", punti_sopra),
        ("sotto_pinch", punti_sotto),
    ):
        for i in range(len(punti_zona) - 2):
            Q_inizio, T_inizio = punti_zona[i]
            Q_successivo, _ = punti_zona[i + 1]
            estremo_esterno = i == 0
            minimo_locale = (
                i > 0
                and Q_inizio <= punti_zona[i - 1][0] + tolleranza
                and Q_successivo > Q_inizio + tolleranza
            )
            if not (estremo_esterno or minimo_locale):
                continue
            if Q_successivo <= Q_inizio + tolleranza:
                continue
            for i_fine in range(i + 2, len(punti_zona)):
                Q_precedente, T_precedente = punti_zona[i_fine - 1]
                Q_corrente, T_corrente = punti_zona[i_fine]
                attraversa = (
                    min(Q_precedente, Q_corrente) - tolleranza
                    <= Q_inizio
                    <= max(Q_precedente, Q_corrente) + tolleranza
                )
                if not attraversa:
                    continue
                denominatore = Q_corrente - Q_precedente
                if abs(denominatore) < tolleranza:
                    T_fine = T_precedente
                else:
                    frazione = (Q_inizio - Q_precedente) / denominatore
                    T_fine = T_precedente + frazione * (T_corrente - T_precedente)
                pockets.append({
                    "zona": nome_zona,
                    "Q_riferimento_kW": Q_inizio,
                    "T_inizio_traslata_C": T_inizio,
                    "T_fine_traslata_C": T_fine,
                    "punti_gcc": punti_zona[i:i_fine] + [(Q_inizio, T_fine)],
                })
                break

    return {
        "main_pinch_points": main_pinch_points,
        "potential_pinch_points": potential_pinch_points,
        "pockets": pockets,
    }

def discretizza_GCC(gcc, punti_pinch, delta_T_max, tolleranza=1e-9):
    limiti = sorted({
        0,
        len(gcc) - 1,
        *[
            punto["indice_gcc"]
            for tipo in ("main_pinch_points", "potential_pinch_points")
            for punto in punti_pinch[tipo]
        ],
    })
    zone_discretizzate = []
    for inizio, fine in zip(limiti, limiti[1:]):
        zona = gcc[inizio:fine + 1]
        vertici = [zona[0]]
        for p1, p2, p3 in zip(zona, zona[1:], zona[2:]):
            Q1, T1 = p1
            Q2, T2 = p2
            Q3, T3 = p3
            if abs((Q2 - Q1) * (T3 - T2) - (T2 - T1) * (Q3 - Q2)) > tolleranza:
                vertici.append(p2)
        vertici.append(zona[-1])

        zona_discretizzata = [vertici[0]]
        for (Q1, T1), (Q2, T2) in zip(vertici, vertici[1:]):
            n = 1
            while abs(T2 - T1) / n > delta_T_max:
                n *= 2
            zona_discretizzata.extend(
                (Q1 + (Q2 - Q1) * i / n, T1 + (T2 - T1) * i / n)
                for i in range(1, n + 1)
            )
        zone_discretizzate.append(zona_discretizzata)
    return zone_discretizzate

def converti_zone_milp(zone_GCC):
    """Zona 1 fredda, zona Z calda; k=1 freddo, k=Sz caldo."""
    return [list(reversed(zona)) for zona in reversed(zone_GCC)]

def genera_HPPr_candidate(
    zone_GCC, eta_ex, EvaP, CondP, T_cond_max=None,
):
    """Precalcola le candidate HPPr secondo [1.4], con y < z."""
    zone_milp = converti_zone_milp(zone_GCC)
    candidate = []
    for y in range(len(zone_milp) - 1):
        for z in range(y + 1, len(zone_milp)):
            for j, (Qy, Ty_C) in enumerate(zone_milp[y], start=1):
                for k, (Qz, Tz_C) in enumerate(zone_milp[z], start=1):
                    if Ty_C >= Tz_C:
                        continue
                    Ty_K = Ty_C + 273.15
                    Tz_K = Tz_C + 273.15
                    if T_cond_max is not None and Tz_K > T_cond_max:
                        continue
                    T_evap_K = Ty_K - EvaP
                    T_cond_K = Tz_K + CondP
                    denominatore = T_cond_K - T_evap_K
                    if denominatore <= 0:
                        continue
                    COP = eta_ex * T_cond_K / denominatore
                    if COP <= 1:
                        continue
                    candidate.append({
                        "y": y + 1, "j": j, "z": z + 1, "k": k,
                        "Qy_kW": Qy, "Qz_kW": Qz,
                        "T_yj_C": Ty_C, "T_zk_C": Tz_C,
                        "T_evap_C": T_evap_K - 273.15,
                        "T_cond_C": T_cond_K - 273.15,
                        "COP": COP,
                    })
    return candidate

def genera_candidate_utilities(
    zone_GCC, utilities, eta_ex, EvaP, CondP, T0, T_f,
    T_cond_max=None,
):
    """Precalcola [1.4]-[1.8] solo per le tecnologie abilitate."""
    nomi = ("HPPr", "HPUt", "chiller", "ORC", "CHP")
    candidati = {nome: [] for nome in nomi}
    zone_milp = converti_zone_milp(zone_GCC)
    Z = len(zone_milp)

    if utilities["HPPr"]["enabled"]:
        candidati["HPPr"] = genera_HPPr_candidate(
            zone_GCC, eta_ex, EvaP, CondP, T_cond_max,
        )

    # [1.31]-[1.35]: i filtri di temperatura evitano variabili inammissibili.
    for z, zona in enumerate(zone_milp, start=1):
        for k, (Q, T_C) in enumerate(zona, start=1):
            T_K = T_C + 273.15

            if utilities["HPUt"]["enabled"]:
                ammessa = z > 1 and T_K >= T0 and (
                    T_cond_max is None or T_K <= T_cond_max
                )
                denominatore = (T_K + CondP) - (T0 - EvaP)
                if ammessa and denominatore > 0:
                    COP = eta_ex * (T_K + CondP) / denominatore
                    if COP > 1:
                        candidati["HPUt"].append({
                            "z": z, "k": k, "Q_kW": Q, "T_zk_C": T_C,
                            "T_evap_C": T0 - EvaP - 273.15,
                            "T_cond_C": T_K + CondP - 273.15, "COP": COP,
                        })

            if utilities["chiller"]["enabled"] and z < Z and T_K <= T0:
                denominatore = (T0 + CondP) - (T_K - EvaP)
                if denominatore > 0:
                    COP = eta_ex * (T0 + CondP) / denominatore
                    if COP > 1:
                        candidati["chiller"].append({
                            "z": z, "k": k, "Q_kW": Q, "T_zk_C": T_C,
                            "T_evap_C": T_K - EvaP - 273.15,
                            "T_cond_C": T0 + CondP - 273.15, "COP": COP,
                        })

            if utilities["ORC"]["enabled"] and z < Z and T_K >= T0:
                T_hot = T_K - CondP
                T_cold = T0 + EvaP
                efficienza = eta_ex * (1 - T_cold / T_hot)
                if 0 < efficienza < 1:
                    candidati["ORC"].append({
                        "z": z, "k": k, "Q_kW": Q, "T_zk_C": T_C,
                        "T_hot_C": T_hot - 273.15,
                        "T_reject_C": T_cold - 273.15,
                        "efficienza": efficienza,
                    })

            if utilities["CHP"]["enabled"] and z == Z:
                efficienza = eta_ex * (
                    1 - (T_K + EvaP) / (T_f - CondP)
                )
                if 0 < efficienza < 1:
                    candidati["CHP"].append({
                        "k": k, "Q_kW": Q, "T_zk_C": T_C,
                        "T_fiamma_C": T_f - CondP - 273.15,
                        "efficienza": efficienza,
                    })
    return candidati

def costruisci_curva_utilities(risultati_milp):
    """Combina tutte le utility selezionate in una curva cumulativa."""
    carichi_isotermi = {}

    def aggiungi(T_C, delta_Q):
        chiave = round(float(T_C), 9)
        carichi_isotermi[chiave] = carichi_isotermi.get(chiave, 0.0) + delta_Q

    nomi_hp = ("HPPr_selezionate", "HPUt_selezionate", "chiller_selezionati")
    for nome in nomi_hp:
        for utility in risultati_milp.get(nome, []):
            aggiungi(utility["T_evap_C"], -utility["Q_evap_kW"])
            aggiungi(utility["T_cond_C"], utility["Q_cond_kW"])
    for utility in risultati_milp.get("ORC_selezionati", []):
        aggiungi(utility["T_hot_C"], -utility["heat_load_kW"])
        aggiungi(utility["T_reject_C"], utility["Q_scarto_kW"])
    for utility in risultati_milp.get("CHP_selezionati", []):
        aggiungi(utility["T_fiamma_C"], -utility["PprelCHP_kW"])
        aggiungi(utility["T_processo_C"], utility["heat_load_kW"])

    Q = 0.0
    curva = []
    for T_C, delta_Q in sorted(carichi_isotermi.items()):
        curva.append((Q, T_C))
        Q += delta_Q
        curva.append((Q, T_C))
    if not curva:
        return []
    Q_min = min(Q_punto for Q_punto, _ in curva)
    return [(Q_punto - Q_min, T_C) for Q_punto, T_C in curva]

def crea_modello_utilities(
    candidati, zone_GCC, utilities, T0, T_f, eta_ex,
):
    """Crea il MILP lineare delle equazioni [1.9]-[1.36]."""
    modello = Model("preselezione_utilities")
    zone_milp = converti_zone_milp(zone_GCC)
    Z = len(zone_milp)

    indici_GCC = []
    Q_GCC = {}
    T_GCC = {}
    for z, zona in enumerate(zone_milp, start=1):
        for k, (Q, T_C) in enumerate(zona, start=1):
            indici_GCC.append((z, k))
            Q_GCC[z, k] = Q
            T_GCC[z, k] = T_C + 273.15

    mappe = {
        "HPPr": {
            (c["y"], c["j"], c["z"], c["k"]): c
            for c in candidati["HPPr"]
        },
        "HPUt": {(c["z"], c["k"]): c for c in candidati["HPUt"]},
        "chiller": {(c["z"], c["k"]): c for c in candidati["chiller"]},
        "ORC": {(c["z"], c["k"]): c for c in candidati["ORC"]},
        "CHP": {c["k"]: c for c in candidati["CHP"]},
    }

    # [1.9]-[1.13] - variabili Bool/F create solo se abilitate.
    BoolHPPr = modello.binary_var_dict(mappe["HPPr"], name="BoolHPPr")
    FHPPr = modello.continuous_var_dict(
        mappe["HPPr"], lb=0, ub=1, name="FHPPr",
    )
    BoolHPUt = modello.binary_var_dict(mappe["HPUt"], name="BoolHPUt")
    FHPUt = modello.continuous_var_dict(
        mappe["HPUt"], lb=0, ub=1, name="FHPUt",
    )
    BoolRef = modello.binary_var_dict(mappe["chiller"], name="BoolRef")
    FRef = modello.continuous_var_dict(
        mappe["chiller"], lb=0, ub=1, name="FRef",
    )
    BoolORC = modello.binary_var_dict(mappe["ORC"], name="BoolORC")
    FORC = modello.continuous_var_dict(
        mappe["ORC"], lb=0, ub=1, name="FORC",
    )
    BoolChp = modello.binary_var_dict(mappe["CHP"], name="BoolChp")
    FChp = modello.continuous_var_dict(
        mappe["CHP"], lb=0, ub=1, name="FChp",
    )

    coppie = (
        (FHPPr, BoolHPPr), (FHPUt, BoolHPUt),
        (FRef, BoolRef), (FORC, BoolORC), (FChp, BoolChp),
    )
    for frazioni, booleane in coppie:
        for indice in frazioni:
            modello.add_constraint(frazioni[indice] <= booleane[indice])

    # [1.14]-[1.17] - limiti per tecnologia e limite HP condiviso.
    if BoolChp:
        modello.add_constraint(modello.sum(BoolChp.values()) <= utilities["CHP"]["max"])
    if BoolRef:
        modello.add_constraint(modello.sum(BoolRef.values()) <= utilities["chiller"]["max"])
    if BoolORC:
        modello.add_constraint(modello.sum(BoolORC.values()) <= utilities["ORC"]["max"])
    if BoolHPPr:
        modello.add_constraint(modello.sum(BoolHPPr.values()) <= utilities["HPPr"]["max"])
    if BoolHPUt:
        modello.add_constraint(modello.sum(BoolHPUt.values()) <= utilities["HPUt"]["max"])
    if BoolHPPr or BoolHPUt:
        modello.add_constraint(
            modello.sum(BoolHPPr.values()) + modello.sum(BoolHPUt.values())
            <= utilities["HP_max"]
        )

    variabili = {
        "BoolHPPr": BoolHPPr, "FHPPr": FHPPr,
        "BoolHPUt": BoolHPUt, "FHPUt": FHPUt,
        "BoolRef": BoolRef, "FRef": FRef,
        "BoolORC": BoolORC, "FORC": FORC,
        "BoolChp": BoolChp, "FChp": FChp,
    }

    # [1.18]-[1.19] - calore prelevato.
    Pprel = modello.continuous_var_dict(indici_GCC, lb=0, name="Pprel")
    for y, j in indici_GCC:
        if y == Z:
            modello.add_constraint(Pprel[y, j] == 0)
            continue
        termini = [
            FHPPr[indice]
            for indice in FHPPr
            if indice[0] == y and indice[1] == j
        ]
        if (y, j) in FRef:
            termini.append(FRef[y, j])
        if (y, j) in FORC:
            termini.append(FORC[y, j])
        modello.add_constraint(Pprel[y, j] == Q_GCC[y, j] * modello.sum(termini))

    # [1.20]-[1.22] - calore fornito.
    Papp = modello.continuous_var_dict(indici_GCC, lb=0, name="Papp")
    for z, k in indici_GCC:
        if z == 1:
            modello.add_constraint(Papp[z, k] == 0)
            continue
        termini = [
            FHPPr[indice]
            * Q_GCC[indice[0], indice[1]]
            * mappe["HPPr"][indice]["COP"]
            / (mappe["HPPr"][indice]["COP"] - 1)
            for indice in FHPPr
            if indice[2] == z and indice[3] == k
        ]
        if (z, k) in FHPUt:
            termini.append(FHPUt[z, k] * Q_GCC[z, k])
        if z == Z and k in FChp:
            termini.append(FChp[k] * Q_GCC[z, k])
        modello.add_constraint(Papp[z, k] == modello.sum(termini))

    # [1.23]-[1.25] - aggiornamento GCC e preservazione del MPP.
    NHL = modello.continuous_var_dict(indici_GCC, lb=0, name="NHL")
    for y in range(1, Z):
        S_y = len(zone_milp[y - 1])
        for j in range(1, S_y + 1):
            effetto_stessa_zona = modello.sum(
                Papp[y, i] - Pprel[y, i]
                for i in range(j, S_y + 1)
            )
            effetto_zone_superiori = modello.sum(
                Papp[z, k] - Pprel[z, k]
                for z in range(y + 1, Z)
                for k in range(1, len(zone_milp[z - 1]) + 1)
            )
            modello.add_constraint(
                NHL[y, j]
                == Q_GCC[y, j] + effetto_stessa_zona + effetto_zone_superiori
            )
    S_Z = len(zone_milp[Z - 1])
    for j in range(1, S_Z + 1):
        modello.add_constraint(
            NHL[Z, j]
            == Q_GCC[Z, j] - modello.sum(Papp[Z, i] for i in range(1, j + 1))
        )

    # [1.26]-[1.28] - consumi elettrici.
    Pelec = modello.continuous_var_dict(indici_GCC, lb=0, name="Pelec")
    for y, j in indici_GCC:
        termini = []
        if y < Z:
            termini.extend(
                FHPPr[indice] * Q_GCC[y, j]
                / (mappe["HPPr"][indice]["COP"] - 1)
                for indice in FHPPr
                if indice[0] == y and indice[1] == j
            )
            if (y, j) in FRef:
                termini.append(
                    FRef[y, j] * Q_GCC[y, j]
                    / (mappe["chiller"][y, j]["COP"] - 1)
                )
        if (y, j) in FHPUt:
            termini.append(
                FHPUt[y, j] * Q_GCC[y, j]
                / mappe["HPUt"][y, j]["COP"]
            )
        modello.add_constraint(Pelec[y, j] == modello.sum(termini))

    TEC = modello.continuous_var(lb=0, name="TEC")
    modello.add_constraint(
        TEC == modello.sum(Pelec[indice] for indice in indici_GCC)
    )

    # [1.29]-[1.30] - produzione elettrica e fuel heat load CHP.
    TEP = modello.continuous_var(lb=0, name="TEP")
    produzione_ORC = modello.sum(
        FORC[indice] * Q_GCC[indice] * candidato["efficienza"]
        for indice, candidato in mappe["ORC"].items()
    )
    produzione_CHP = modello.sum(
        FChp[k] * Q_GCC[Z, k] * candidato["efficienza"]
        / (1 - candidato["efficienza"])
        for k, candidato in mappe["CHP"].items()
    )
    modello.add_constraint(TEP == produzione_ORC + produzione_CHP)

    PprelCHP = modello.continuous_var(lb=0, name="PprelCHP")
    modello.add_constraint(
        PprelCHP
        == modello.sum(
            FChp[k] * Q_GCC[Z, k] / (1 - candidato["efficienza"])
            for k, candidato in mappe["CHP"].items()
        )
    )

    # [1.36] - temperature assolute e termine cold piecewise esatto.
    T_cold_MER = T_GCC[1, 1]
    fattore_cold = (
        0.0 if T_cold_MER >= T0
        else eta_ex * T_cold_MER / (T0 - T_cold_MER)
    )
    fattore_hot = (T_f - T0) / T_f
    FinalExergy = modello.continuous_var(lb=-modello.infinity, name="FinalExergy")
    modello.add_constraint(
        FinalExergy
        == NHL[1, 1] * fattore_cold
        + (NHL[Z, S_Z] + PprelCHP) * fattore_hot
        + TEC - TEP
    )
    modello.minimize(FinalExergy)

    return {
        "modello": modello,
        "zone_milp": zone_milp,
        "Z": Z,
        "indici_GCC": indici_GCC,
        "Q_GCC": Q_GCC,
        "T_GCC": T_GCC,
        "candidati": candidati,
        "mappe": mappe,
        "variabili": variabili,
        "Pprel": Pprel,
        "Papp": Papp,
        "NHL": NHL,
        "Pelec": Pelec,
        "TEC": TEC,
        "TEP": TEP,
        "PprelCHP": PprelCHP,
        "FinalExergy": FinalExergy,
    }

def risolvi_modello_utilities(componenti, log_output=False, tolleranza=1e-6):
    """Risolvi il MILP e restituisce un solo dizionario strutturato."""
    modello = componenti["modello"]
    soluzione = modello.solve(log_output=log_output)
    if soluzione is None:
        print("Nessuna soluzione trovata dal modello.")
        return None

    mappe = componenti["mappe"]
    v = componenti["variabili"]
    Q_GCC = componenti["Q_GCC"]
    Z = componenti["Z"]
    S_Z = len(componenti["zone_milp"][Z - 1])

    HPPr_selezionate = []
    for indice, hp in mappe["HPPr"].items():
        frazione = soluzione.get_value(v["FHPPr"][indice])
        if frazione <= tolleranza:
            continue
        Q_evap = frazione * hp["Qy_kW"]
        COP = hp["COP"]
        Q_cond = Q_evap * COP / (COP - 1)
        HPPr_selezionate.append({
            "tipo": "HPPr", "indice": indice,
            "BoolHPPr": soluzione.get_value(v["BoolHPPr"][indice]),
            "FHPPr": frazione,
            "y": indice[0], "j": indice[1], "z": indice[2], "k": indice[3],
            "T_yj_C": hp["T_yj_C"], "T_zk_C": hp["T_zk_C"],
            "T_evap_C": hp["T_evap_C"], "T_cond_C": hp["T_cond_C"],
            "heat_load_kW": Q_cond, "Q_evap_kW": Q_evap,
            "Q_cond_kW": Q_cond, "COP": COP,
            "P_elettrica_kW": Q_evap / (COP - 1),
        })

    HPUt_selezionate = []
    for indice, hp in mappe["HPUt"].items():
        frazione = soluzione.get_value(v["FHPUt"][indice])
        if frazione <= tolleranza:
            continue
        Q_cond = frazione * hp["Q_kW"]
        W = Q_cond / hp["COP"]
        HPUt_selezionate.append({
            "tipo": "HPUt", "indice": indice,
            "BoolHPUt": soluzione.get_value(v["BoolHPUt"][indice]),
            "FHPUt": frazione, "z": indice[0], "k": indice[1],
            "T_evap_C": hp["T_evap_C"], "T_cond_C": hp["T_cond_C"],
            "heat_load_kW": Q_cond, "Q_evap_kW": Q_cond - W,
            "Q_cond_kW": Q_cond, "COP": hp["COP"],
            "P_elettrica_kW": W,
        })

    chiller_selezionati = []
    for indice, ref in mappe["chiller"].items():
        frazione = soluzione.get_value(v["FRef"][indice])
        if frazione <= tolleranza:
            continue
        Q_evap = frazione * ref["Q_kW"]
        W = Q_evap / (ref["COP"] - 1)
        chiller_selezionati.append({
            "tipo": "chiller", "indice": indice,
            "BoolRef": soluzione.get_value(v["BoolRef"][indice]),
            "FRef": frazione, "z": indice[0], "k": indice[1],
            "T_evap_C": ref["T_evap_C"], "T_cond_C": ref["T_cond_C"],
            "heat_load_kW": Q_evap, "Q_evap_kW": Q_evap,
            "Q_cond_kW": Q_evap + W, "COP": ref["COP"],
            "P_elettrica_kW": W,
        })

    ORC_selezionati = []
    for indice, orc in mappe["ORC"].items():
        frazione = soluzione.get_value(v["FORC"][indice])
        if frazione <= tolleranza:
            continue
        Q_assorbito = frazione * orc["Q_kW"]
        P_elettrica = Q_assorbito * orc["efficienza"]
        ORC_selezionati.append({
            "tipo": "ORC", "indice": indice,
            "BoolORC": soluzione.get_value(v["BoolORC"][indice]),
            "FORC": frazione, "z": indice[0], "k": indice[1],
            "T_hot_C": orc["T_hot_C"], "T_reject_C": orc["T_reject_C"],
            "heat_load_kW": Q_assorbito,
            "efficienza": orc["efficienza"],
            "P_elettrica_prodotta_kW": P_elettrica,
            "Q_scarto_kW": Q_assorbito - P_elettrica,
        })

    CHP_selezionati = []
    for k, chp in mappe["CHP"].items():
        frazione = soluzione.get_value(v["FChp"][k])
        if frazione <= tolleranza:
            continue
        Q_process = frazione * Q_GCC[Z, k]
        fuel = Q_process / (1 - chp["efficienza"])
        CHP_selezionati.append({
            "tipo": "CHP", "indice": k,
            "BoolChp": soluzione.get_value(v["BoolChp"][k]),
            "FChp": frazione, "k": k,
            "T_processo_C": chp["T_zk_C"],
            "T_fiamma_C": chp["T_fiamma_C"],
            "heat_load_kW": Q_process,
            "efficienza": chp["efficienza"],
            "PprelCHP_kW": fuel,
            "P_elettrica_prodotta_kW": fuel * chp["efficienza"],
        })

    risultati = {
        "HPPr_selezionate": HPPr_selezionate,
        "HPUt_selezionate": HPUt_selezionate,
        "chiller_selezionati": chiller_selezionati,
        "ORC_selezionati": ORC_selezionati,
        "CHP_selezionati": CHP_selezionati,
        "TEC_kW": soluzione.get_value(componenti["TEC"]),
        "TEP_kW": soluzione.get_value(componenti["TEP"]),
        "PprelCHP_kW": soluzione.get_value(componenti["PprelCHP"]),
        "hot_MER_residuo_kW": soluzione.get_value(componenti["NHL"][Z, S_Z]),
        "cold_MER_residuo_kW": soluzione.get_value(componenti["NHL"][1, 1]),
        "FinalExergy_kW": soluzione.get_value(componenti["FinalExergy"]),
        "soluzione": soluzione,
    }
    
    return risultati

def prepara_pinch(percorso_json):
    """Esegue la Pinch Analysis del caso studio."""

    configurazione = carica_caso_studio(percorso_json)

    flussi = configurazione["flussi_oggetti"]
    delta_T_min = configurazione["delta_T_min"]

    risultati_cascata, QH_min, QC_min, pinch_traslati = (
        crea_cascata_termica(
            flussi,
            delta_T_min,
        )
    )

    hot_CC_star, cold_CC_star = (
    costruisci_curve_composite(
        risultati_cascata,
        QC_min,
    )
)

    gcc = costruisci_GCC(
        risultati_cascata,
        QH_min,
    )

    pinch_data = self_sufficient_pockets(
        gcc,
        delta_T_min,
    )

    zone_GCC = discretizza_GCC(
        gcc,
        pinch_data,
        configurazione["delta_T_max"],
    )

    return {
        "configurazione": configurazione,
        "risultati_cascata": risultati_cascata,
        "QH_min_kW": QH_min,
        "QC_min_kW": QC_min,
        "pinch_traslati_C": pinch_traslati,
        "hot_CC_traslata": hot_CC_star,
        "cold_CC_traslata": cold_CC_star,
        "gcc": gcc,
        "pinch_data": pinch_data,
        "zone_GCC": zone_GCC,
    }

def esegui_milp(dati_pinch, log_output=False):
    """Genera le utility candidate e risolve il MILP."""

    configurazione = dati_pinch["configurazione"]
    utilities = configurazione["utilities"]

    candidati = genera_candidate_utilities(
        dati_pinch["zone_GCC"],
        utilities,
        configurazione["eta_ex"],
        configurazione["evaP"],
        configurazione["condP"],
        configurazione["T0"],
        configurazione["T_f"],
        configurazione["T_cond_max"],
    )

    componenti = crea_modello_utilities(
        candidati,
        dati_pinch["zone_GCC"],
        utilities,
        configurazione["T0"],
        configurazione["T_f"],
        configurazione["eta_ex"],
    )

    risultati = risolvi_modello_utilities(
        componenti,
        log_output=log_output,
    )
    risultati["gcc_aggiornata"] = costruisci_GCC_aggiornata(
    risultati["soluzione"],
    componenti["NHL"],
    dati_pinch["zone_GCC"],
    )
    return risultati

def costruisci_GCC_aggiornata(soluzione, NHL, zone_GCC):
    """Costruisce la GCC dopo l'inserimento delle utilities."""

    zone_milp = converti_zone_milp(zone_GCC)

    punti = []

    # Dalla zona più calda alla più fredda
    for z in range(len(zone_milp), 0, -1):

        zona = zone_milp[z - 1]

        # Dalla temperatura più alta alla più bassa
        for k in range(len(zona), 0, -1):

            _, T = zona[k - 1]

            Q = soluzione.get_value(
                NHL[z, k]
            )

            punti.append(
                (Q, T)
            )

    return punti

def grafico_TQ(
    tipo_grafico, hot_CC=None, cold_CC=None, gcc=None,
    utility_curve=None, pockets=None, pinch_data=None,
    percorso_salvataggio=None, mostra=True,
):
    """Rappresenta Composite Curves, GCC, pockets oppure ICC."""
    fig, ax = plt.subplots(figsize=(8, 6))
    if tipo_grafico in ("composite", "composite_traslate"):
        Q_hot, T_hot = zip(*hot_CC)
        Q_cold, T_cold = zip(*cold_CC)
        ax.plot(Q_hot, T_hot, color="red", marker="o", label="Hot CC")
        ax.plot(Q_cold, T_cold, color="blue", marker="o", label="Cold CC")
        if tipo_grafico == "composite":
            ax.set_title("Composite Curves - temperature reali")
            ax.set_ylabel("Temperatura reale [°C]")
        else:
            ax.set_title("Composite Curves - temperature traslate")
            ax.set_ylabel("Temperatura traslata T* [°C]")
    elif tipo_grafico in ("gcc", "gcc_aggiornata"):
        Q, T = zip(*gcc)
        ax.plot(Q, T, color="red", linewidth=2)
        ax.axvline(0, color="black", linestyle="--", linewidth=1)

        if tipo_grafico == "gcc":
            ax.set_title("Grand Composite Curve")
        else:
            ax.set_title("Grand Composite Curve aggiornata")

        ax.set_ylabel("Temperatura traslata [°C]")
    elif tipo_grafico == "pockets":
        if gcc is not None:
            Q, T = zip(*gcc)
            ax.plot(Q, T, color="lightgray", linewidth=2, label="GCC")
        for indice, pocket in enumerate(pockets or [], start=1):
            Q_pocket, T_pocket = zip(*pocket["punti_gcc"])
            ax.plot(
                Q_pocket, T_pocket, linewidth=1.7,
                label=f"Pocket {indice}: {pocket['zona']}",
            )
        if pinch_data is not None:
            mpp = pinch_data["main_pinch_points"]
            ppp = pinch_data["potential_pinch_points"]
            if mpp:
                ax.scatter(
                    [p["Q_kW"] for p in mpp],
                    [p["T_traslata_C"] for p in mpp],
                    marker="s", s=50, label="MPP", color="black"
                )
            if ppp:
                ax.scatter(
                    [p["Q_kW"] for p in ppp],
                    [p["T_traslata_C"] for p in ppp],
                    marker="D", s=40, label="PPP",color="red"
                )
        ax.axvline(0, color="black", linestyle="--", linewidth=1)
        ax.set_title("Self-sufficient pockets")
        ax.set_ylabel("Temperatura traslata [°C]")
    elif tipo_grafico == "icc":
        Q, T = zip(*gcc)
        ax.plot(Q, T, color="red", linewidth=2, label="GCC")
        if utility_curve:
            Q_ut, T_ut = zip(*utility_curve)
            ax.plot(Q_ut, T_ut, color="green", linewidth=2, label="Utilities")
        ax.axvline(0, color="black", linestyle="--", linewidth=1)
        ax.set_title("Integrated Composite Curve")
        ax.set_ylabel("Temperatura [°C]")
    else:
        raise ValueError(
            "tipo_grafico deve essere 'composite', 'composite_traslate', "
            "'gcc', 'icc' oppure 'pockets'."
        )

    ax.set_xlabel("Potenza termica cumulata Q [kW]")
    ax.grid(True, linestyle="--", alpha=0.4)
    ax.legend()
    if percorso_salvataggio is not None:
        percorso_salvataggio = Path(percorso_salvataggio)
        percorso_salvataggio.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(percorso_salvataggio, dpi=300, bbox_inches="tight")
        print(f"Grafico salvato in: {percorso_salvataggio}")
    if mostra:
        plt.show()
    else:
        plt.close(fig)
    return fig, ax

def stampa_risultati_milp(risultati):
    print(
        f"TEC={risultati['TEC_kW']:.3f} kW, "
        f"TEP={risultati['TEP_kW']:.3f} kW, "
        f"hot MER={risultati['hot_MER_residuo_kW']:.3f} kW, "
        f"cold MER={risultati['cold_MER_residuo_kW']:.3f} kW, "
        f"FinalExergy={risultati['FinalExergy_kW']:.3f} kW"
    )
    for hp in risultati["HPPr_selezionate"]:
        print(
            f"HPPr {hp['indice']}: Tevap={hp['T_evap_C']:.2f} °C, "
            f"Tcond={hp['T_cond_C']:.2f} °C, COP={hp['COP']:.3f}, "
            f"Qevap={hp['Q_evap_kW']:.3f} kW, "
            f"Qcond={hp['Q_cond_kW']:.3f} kW, "
            f"W={hp['P_elettrica_kW']:.3f} kW"
        )

def salva_grafici(dati_pinch, risultati_milp, cartella):

    cartella = Path(cartella)
    cartella.mkdir(
        parents=True,
        exist_ok=True,
    )

    curva_utilities = costruisci_curva_utilities(
        risultati_milp
    )

    # Composite Curves
    grafico_TQ(
        "composite_traslate",
        hot_CC=dati_pinch["hot_CC_traslata"],
        cold_CC=dati_pinch["cold_CC_traslata"],
        percorso_salvataggio=(
            cartella / "composite_curves_traslate.png"
        ),
        mostra=False,
    )

    # GCC iniziale
    grafico_TQ(
        "gcc",
        gcc=dati_pinch["gcc"],
        percorso_salvataggio=(
            cartella / "grand_composite_curve.png"
        ),
        mostra=False,
    )

    # Self-sufficient pockets
    grafico_TQ(
        "pockets",
        gcc=dati_pinch["gcc"],
        pockets=dati_pinch["pinch_data"]["pockets"],
        pinch_data=dati_pinch["pinch_data"],
        percorso_salvataggio=(
            cartella / "self_sufficient_pockets.png"
        ),
        mostra=False,
    )

    # GCC aggiornata
    grafico_TQ(
        "gcc_aggiornata",
        gcc=risultati_milp["gcc_aggiornata"],
        percorso_salvataggio=(
            cartella / "grand_composite_curve_aggiornata.png"
        ),
        mostra=False,
    )

    # Integrated Composite Curve
    grafico_TQ(
        "icc",
        gcc=dati_pinch["gcc"],
        utility_curve=curva_utilities,
        percorso_salvataggio=(
            cartella / "integrated_composite_curve.png"
        ),
        mostra=False,
    )

#-----------------------------------------
#PREPROCESSING DELLA HEN
#-----------------------------------------

def costruisci_insiemi_HEN(
    flussi,
    utilities,
    intervalli,
    delta_T_min,
    match_permessi=None,
    NI_H=None,
    NI_C=None,
):
    """Costruisce gli insiemi del modello HENS."""

    # -------------------------------------------------
    # 1. CORRENTI
    # -------------------------------------------------

    processi = [
        flusso
        for flusso in flussi
        if flusso.disponibile
    ]

    hot_utilities = utilities.get("hot", [])
    cold_utilities = utilities.get("cold", [])

    correnti = (
        processi
        + hot_utilities
        + cold_utilities
    )

    correnti_per_codice = {
        flusso.codice: flusso
        for flusso in correnti
    }


    # -------------------------------------------------
    # 2. ZONE Z
    # -------------------------------------------------

    Z = list(intervalli.keys())


    # -------------------------------------------------
    # 3. INTERVALLI Mz
    # -------------------------------------------------

    M = {
        z: list(range(1, len(intervalli[z]) + 1))
        for z in Z
    }


    # Temperature superiore e inferiore degli intervalli
    T_intervallo = {
        (z, m): {
            "T_sup": T_sup,
            "T_inf": T_inf,
        }
        for z in Z
        for m, (T_sup, T_inf) in enumerate(
            intervalli[z],
            start=1,
        )
    }


    # -------------------------------------------------
    # 4. TEMPERATURE SULLA SCALA HEN
    # -------------------------------------------------

    def temperature_HEN(flusso):

        if flusso.tipo == "hot":
            return (
                flusso.T_in,
                flusso.T_out,
            )

        return (
            flusso.T_in + delta_T_min,
            flusso.T_out + delta_T_min,
        )


    # -------------------------------------------------
    # 5. PRESENZA DI UNA CORRENTE IN UN INTERVALLO
    # -------------------------------------------------

    def presente(flusso, T_sup, T_inf):

        T1, T2 = temperature_HEN(flusso)

        T_max = max(T1, T2)
        T_min = min(T1, T2)

        return (
            T_max >= T_sup
            and T_min <= T_inf
        )


    # -------------------------------------------------
    # 6. Hm e Cn
    # -------------------------------------------------

    H_m = {}
    C_n = {}

    for z in Z:

        for m in M[z]:

            T_sup, T_inf = intervalli[z][m - 1]

            H_m[z, m] = [
                flusso.codice
                for flusso in correnti
                if flusso.tipo == "hot"
                and presente(
                    flusso,
                    T_sup,
                    T_inf,
                )
            ]

            C_n[z, m] = [
                flusso.codice
                for flusso in correnti
                if flusso.tipo == "cold"
                and presente(
                    flusso,
                    T_sup,
                    T_inf,
                )
            ]


    # -------------------------------------------------
    # 7. Hz e Cz
    # -------------------------------------------------

    H = {
        z: sorted({
            i
            for m in M[z]
            for i in H_m[z, m]
        })
        for z in Z
    }

    C = {
        z: sorted({
            j
            for m in M[z]
            for j in C_n[z, m]
        })
        for z in Z
    }


    # -------------------------------------------------
    # 8. HUz e CUz
    # -------------------------------------------------

    codici_HU = {
        utility.codice
        for utility in hot_utilities
    }

    codici_CU = {
        utility.codice
        for utility in cold_utilities
    }

    HU = {
        z: [
            i
            for i in H[z]
            if i in codici_HU
        ]
        for z in Z
    }

    CU = {
        z: [
            j
            for j in C[z]
            if j in codici_CU
        ]
        for z in Z
    }


    # -------------------------------------------------
    # 9. Mi e Nj
    # -------------------------------------------------

    M_i = {
        (z, i): [
            m
            for m in M[z]
            if i in H_m[z, m]
        ]
        for z in Z
        for i in H[z]
    }

    N_j = {
        (z, j): [
            n
            for n in M[z]
            if j in C_n[z, n]
        ]
        for z in Z
        for j in C[z]
    }


    # -------------------------------------------------
    # 10. MATCH CONSENTITI P
    # -------------------------------------------------

    if match_permessi is None:

        P = {
            (i, j)

            for z in Z
            for i in H[z]
            for j in C[z]

            # Evita uno scambio diretto
            # hot utility -> cold utility
            if not (
                i in HU[z]
                and j in CU[z]
            )
        }

    else:

        P = set(match_permessi)


    # -------------------------------------------------
    # 11. P_Him e P_Cjn
    # -------------------------------------------------

    P_H = {
        (z, i, m): [
            j
            for j in C[z]
            if (i, j) in P
        ]
        for z in Z
        for i in H[z]
        for m in M_i[z, i]
    }

    P_C = {
        (z, j, n): [
            i
            for i in H[z]
            if (i, j) in P
        ]
        for z in Z
        for j in C[z]
        for n in N_j[z, j]
    }


    # -------------------------------------------------
    # 12. NON-ISOTHERMAL MIXING
    # -------------------------------------------------

    NI_H = set() if NI_H is None else set(NI_H)
    NI_C = set() if NI_C is None else set(NI_C)


    return {
        "Z": Z,
        "H": H,
        "C": C,
        "HU": HU,
        "CU": CU,
        "M": M,
        "M_i": M_i,
        "N_j": N_j,
        "H_m": H_m,
        "C_n": C_n,
        "P": P,
        "P_H": P_H,
        "P_C": P_C,
        "NI_H": NI_H,
        "NI_C": NI_C,
        "T_intervallo": T_intervallo,
        "correnti": correnti_per_codice,
    }

def crea_partizione_HEN(
    gcc,
    flussi,
    delta_T_min,
    pinch_traslati,
    delta_T_partition_max,
    numero_intervalli_min,
    utilities=None,
    separa_al_pinch=True,
    debug=False,
):
    """
    Costruisce la partizione di temperatura per il modello HENS.

    La scala HENS utilizzata è:

        hot  -> T reale
        cold -> T reale + delta_T_min

    La partizione considera sia le process streams sia,
    se fornite, le utility HENS.

    Procedura:
    1. individua i punti angolari della GCC;
    2. converte la GCC dalla scala simmetrica alla scala HENS;
    3. aggiunge gli estremi termici delle correnti;
    4. divide il problema nelle zone determinate dai pinch;
    5. STEP 1: limita la massima ampiezza degli intervalli;
    6. STEP 2: garantisce almeno un intervallo interno
       per ogni corrente;
    7. STEP 3: garantisce il numero minimo di intervalli.

    Returns
    -------
    dict

        {
            zona: [
                (T_sup, T_inf),
                ...
            ]
        }
    """

    tolleranza = 1e-9

    # =================================================
    # 0. CONTROLLO INPUT
    # =================================================
    if type(separa_al_pinch) is not bool:
        raise ValueError(
            "separa_al_pinch deve essere "
            "True oppure False."
        )
    if len(gcc) < 2:
        raise ValueError(
            "La GCC deve contenere almeno due punti."
        )

    if delta_T_partition_max <= 0:
        raise ValueError(
            "delta_T_partition_max deve essere > 0."
        )

    if numero_intervalli_min < 1:
        raise ValueError(
            "numero_intervalli_min deve essere >= 1."
        )


    # =================================================
    # 1. UTILITIES HENS
    # =================================================
    #
    # Se non vengono passate utilities manteniamo
    # il comportamento precedente process-only.
    # =================================================

    if utilities is None:
        utilities = {
            "hot": [],
            "cold": [],
        }

    utilities_hot = utilities.get(
        "hot",
        [],
    )

    utilities_cold = utilities.get(
        "cold",
        [],
    )

    correnti_partizione = (
        list(flussi)
        + list(utilities_hot)
        + list(utilities_cold)
    )


    # =================================================
    # FUNZIONE DI SUPPORTO:
    # TEMPERATURE SULLA SCALA HENS
    # =================================================

    def temperature_corrente_HEN(corrente):
        """
        Restituisce T_in e T_out sulla scala HENS.

        Hot:
            nessuna traslazione

        Cold:
            + delta_T_min
        """

        if corrente.tipo == "hot":

            return (
                float(corrente.T_in),
                float(corrente.T_out),
            )

        elif corrente.tipo == "cold":

            return (
                float(corrente.T_in)
                + delta_T_min,

                float(corrente.T_out)
                + delta_T_min,
            )

        else:

            raise ValueError(
                f"Tipo corrente non riconosciuto "
                f"per {corrente.codice}: "
                f"{corrente.tipo}"
            )


    # =================================================
    # FUNZIONE DI SUPPORTO:
    # DISPONIBILITÀ
    # =================================================

    def corrente_disponibile(corrente):

        return getattr(
            corrente,
            "disponibile",
            True,
        )


    # =================================================
    # FUNZIONE DI SUPPORTO:
    # STAMPA LIVELLI
    # =================================================

    def stampa_livelli(
        titolo,
        livelli,
    ):

        if not debug:
            return

        print(f"\n{titolo}")

        for T in sorted(
            livelli,
            reverse=True,
        ):

            print(
                f"  {T:.2f} °C"
            )


    # =================================================
    # 2. PUNTI ANGOLARI DELLA GCC
    # =================================================

    vertici = [
        gcc[0]
    ]

    for p1, p2, p3 in zip(
        gcc,
        gcc[1:],
        gcc[2:],
    ):

        Q1, T1 = p1
        Q2, T2 = p2
        Q3, T3 = p3

        # Confronto delle pendenze senza divisione.
        #
        # (Q2-Q1)/(T2-T1)
        #
        # confrontata con
        #
        # (Q3-Q2)/(T3-T2)

        lhs = (
            (Q2 - Q1)
            * (T3 - T2)
        )

        rhs = (
            (T2 - T1)
            * (Q3 - Q2)
        )

        cambio_pendenza = (
            abs(lhs - rhs)
            > tolleranza
        )

        if cambio_pendenza:

            vertici.append(
                p2
            )

    vertici.append(
        gcc[-1]
    )


    # =================================================
    # 3. CONVERSIONE GCC -> SCALA HENS
    # =================================================
    #
    # Pinch Analysis:
    #
    # hot  -> T - DTmin/2
    # cold -> T + DTmin/2
    #
    # HENS:
    #
    # hot  -> T
    # cold -> T + DTmin
    #
    # Quindi la scala viene traslata di:
    #
    # + DTmin/2
    # =================================================

    temperature_gcc = [
        T_star
        + delta_T_min / 2
        for _, T_star in vertici
    ]

    pinch_HEN = [
        T_star
        + delta_T_min / 2
        for T_star in pinch_traslati
    ]


    # =================================================
    # 4. ESTREMI DI TUTTE LE CORRENTI
    # =================================================
    #
    # Questo è importante soprattutto per le utilities.
    #
    # Nel benchmark:
    #
    # H3:
    #     180 -> 179 °C
    #
    # C3:
    #     15 -> 25 °C reali
    #
    # sulla scala HENS:
    #
    #     35 -> 45 °C
    #
    # Gli estremi devono appartenere alla partizione
    # affinché la presenza delle correnti negli
    # intervalli sia rappresentata esattamente.
    # =================================================

    temperature_correnti = []

    for corrente in correnti_partizione:

        if not corrente_disponibile(
            corrente
        ):
            continue

        T1, T2 = (
            temperature_corrente_HEN(
                corrente
            )
        )

        temperature_correnti.extend(
            [
                T1,
                T2,
            ]
        )


    # =================================================
    # 5. RANGE COMPLETO DELLA HENS
    # =================================================

    temperature_base = (
        list(temperature_gcc)
        + list(temperature_correnti)
    )

    if not temperature_base:
        raise ValueError(
            "Nessuna temperatura disponibile "
            "per costruire la partizione HENS."
        )

    T_max = max(
        temperature_base
    )

    T_min = min(
        temperature_base
    )


    # =================================================
    # 6. DEFINIZIONE DELLE ZONE
    # =================================================

    pinch_interni = sorted(
        {
            T
            for T in pinch_HEN
            if (
                T_min + tolleranza
                < T
                < T_max - tolleranza
            )
        },
        reverse=True,
    )


    if separa_al_pinch:

        # ---------------------------------------------
        # Modalità Pinch Design:
        #
        # i pinch separano sottoreti indipendenti
        # ---------------------------------------------

        limiti_zone = [
            T_max,
            *pinch_interni,
            T_min,
        ]

    else:

        # ---------------------------------------------
        # Modalità economica globale:
        #
        # una sola heat-transfer zone
        # ---------------------------------------------

        limiti_zone = [
            T_max,
            T_min,
        ]


    # =================================================
    # CONTENITORE DELLE ZONE
    # =================================================

    zone = {}

    # =================================================
    # 7. CICLO SULLE ZONE
    # =================================================

    for z, (
        T_sup_z,
        T_inf_z,
    ) in enumerate(
        zip(
            limiti_zone,
            limiti_zone[1:],
        ),
        start=1,
    ):


        # =============================================
        # PARTIZIONE INIZIALE
        # =============================================
        #
        # Comprende:
        #
        # - limiti della zona;
        # - vertici della GCC;
        # - estremi delle process streams;
        # - estremi delle utilities.
        #
        # Questo evita intervalli che attraversano
        # l'inizio o la fine di una corrente.
        # =============================================

        livelli = {
            T_sup_z,
            T_inf_z,
        }


        # ---------------------------------------------
        # Punti angolari GCC
        # ---------------------------------------------

        for T in temperature_gcc:

            if (
                T_inf_z
                - tolleranza
                <= T
                <= T_sup_z
                + tolleranza
            ):

                livelli.add(
                    T
                )


        # ---------------------------------------------
        # Estremi delle correnti
        # ---------------------------------------------

        for T in temperature_correnti:

            if (
                T_inf_z
                - tolleranza
                <= T
                <= T_sup_z
                + tolleranza
            ):

                livelli.add(
                    T
                )


        livelli_iniziali = set(
            livelli
        )


        if debug:

            print(
                f"\n{'=' * 55}"
                f"\nZONA HEN {z}"
                f"\n"
                f"{T_sup_z:.2f} -> "
                f"{T_inf_z:.2f} °C"
                f"\n{'=' * 55}"
            )

        stampa_livelli(
            "Livelli iniziali "
            "(GCC + estremi correnti):",
            livelli_iniziali,
        )


        # =================================================
        # STEP 1
        # MASSIMA AMPIEZZA INTERVALLI
        # =================================================

        iterazione = 0

        while True:

            livelli_ordinati = sorted(
                livelli,
                reverse=True,
            )

            nuovi_livelli = []

            for (
                T_sup,
                T_inf,
            ) in zip(
                livelli_ordinati,
                livelli_ordinati[1:],
            ):

                delta_T = (
                    T_sup
                    - T_inf
                )

                if (
                    delta_T
                    >
                    delta_T_partition_max
                    + tolleranza
                ):

                    T_medio = (
                        T_sup
                        + T_inf
                    ) / 2

                    nuovi_livelli.append(
                        T_medio
                    )


            if not nuovi_livelli:
                break


            iterazione += 1

            if debug:

                print(
                    f"\nSTEP 1 - "
                    f"dimezzamento "
                    f"{iterazione}:"
                )

                for T in nuovi_livelli:

                    print(
                        f"  aggiunto livello "
                        f"{T:.2f} °C"
                    )


            livelli.update(
                nuovi_livelli
            )


        stampa_livelli(
            "Dopo STEP 1 - "
            "vincolo ΔTpartition,max:",
            livelli,
        )


        # =================================================
        # STEP 2
        # ALMENO UN INTERVALLO INTERNO PER CORRENTE
        # =================================================

        for corrente in correnti_partizione:

            if not corrente_disponibile(
                corrente
            ):
                continue


            # -----------------------------------------
            # Temperature sulla scala HENS
            # -----------------------------------------

            T1, T2 = (
                temperature_corrente_HEN(
                    corrente
                )
            )


            # -----------------------------------------
            # Intersezione corrente-zona
            # -----------------------------------------

            T_stream_sup = min(
                max(T1, T2),
                T_sup_z,
            )

            T_stream_inf = max(
                min(T1, T2),
                T_inf_z,
            )


            # Nessuna presenza significativa
            # della corrente nella zona.
            if (
                T_stream_sup
                <=
                T_stream_inf
                + tolleranza
            ):
                continue


            # -----------------------------------------
            # Livelli strettamente interni
            # alla corrente
            # -----------------------------------------

            livelli_interni = [
                T
                for T in livelli
                if (
                    T_stream_inf
                    + tolleranza
                    < T
                    < T_stream_sup
                    - tolleranza
                )
            ]


            # -----------------------------------------
            # Per avere almeno un intervallo
            # completamente interno servono almeno
            # due livelli interni.
            #
            # Altrimenti il tratto viene diviso
            # in tre parti uguali.
            # -----------------------------------------

            if len(
                livelli_interni
            ) < 2:

                delta_T_stream = (
                    T_stream_sup
                    - T_stream_inf
                )

                T_a = (
                    T_stream_inf
                    + delta_T_stream / 3
                )

                T_b = (
                    T_stream_inf
                    + 2
                    * delta_T_stream / 3
                )


                if debug:

                    print(
                        f"\nSTEP 2 applicato a "
                        f"{corrente.codice}:"
                    )

                    print(
                        f"  tipo: "
                        f"{corrente.tipo}"
                    )

                    print(
                        f"  tratto nella zona: "
                        f"{T_stream_sup:.2f} -> "
                        f"{T_stream_inf:.2f} °C"
                    )

                    print(
                        f"  livelli interni "
                        f"prima della divisione: "
                        f"{len(livelli_interni)}"
                    )

                    print(
                        f"  nuovi livelli: "
                        f"{T_b:.2f} °C, "
                        f"{T_a:.2f} °C"
                    )


                livelli.add(
                    T_a
                )

                livelli.add(
                    T_b
                )


        stampa_livelli(
            "Dopo STEP 2 - "
            "intervalli interni degli stream:",
            livelli,
        )


        # =================================================
        # STEP 3
        # NUMERO MINIMO DI INTERVALLI
        # =================================================

        while (
            len(livelli) - 1
            <
            numero_intervalli_min
        ):

            livelli_ordinati = sorted(
                livelli,
                reverse=True,
            )


            (
                T_sup_maggiore,
                T_inf_maggiore,
            ) = max(
                zip(
                    livelli_ordinati,
                    livelli_ordinati[1:],
                ),
                key=lambda coppia:
                    coppia[0]
                    - coppia[1],
            )


            T_medio = (
                T_sup_maggiore
                + T_inf_maggiore
            ) / 2


            if debug:

                print(
                    "\nSTEP 3 - "
                    "numero minimo "
                    "di intervalli:"
                )

                print(
                    f"  intervalli attuali: "
                    f"{len(livelli) - 1}"
                )

                print(
                    f"  intervallo maggiore: "
                    f"{T_sup_maggiore:.2f} -> "
                    f"{T_inf_maggiore:.2f} °C"
                )

                print(
                    f"  nuovo livello: "
                    f"{T_medio:.2f} °C"
                )


            livelli.add(
                T_medio
            )


        # =================================================
        # 8. INTERVALLI FINALI
        # =================================================

        livelli_finali = sorted(
            livelli,
            reverse=True,
        )


        stampa_livelli(
            "Livelli finali HEN:",
            livelli_finali,
        )


        zone[z] = [
            (
                T_sup,
                T_inf,
            )
            for (
                T_sup,
                T_inf,
            ) in zip(
                livelli_finali,
                livelli_finali[1:],
            )
        ]


        if debug:

            print(
                f"\nNumero intervalli "
                f"Zona {z}: "
                f"{len(zone[z])}"
            )


    # =================================================
    # 9. RIEPILOGO
    # =================================================

    if debug:

        numero_totale = sum(
            len(intervalli)
            for intervalli
            in zone.values()
        )

        print(
            f"\n{'=' * 55}"
            f"\nRIEPILOGO PARTIZIONE HEN"
            f"\n{'=' * 55}"
        )

        for (
            z,
            intervalli,
        ) in zone.items():

            print(
                f"Zona {z}: "
                f"{len(intervalli)} "
                f"intervalli"
            )

        print(
            f"Numero totale "
            f"intervalli HEN: "
            f"{numero_totale}"
        )


    return zone

def genera_indici_q_HEN(
    insiemi_HEN,
    tolleranza=1e-9,
    debug=False,
):
    """
    Genera gli indici ammissibili della variabile di trasferimento
    termico q^z_{im,jn} del modello HENS.

    Una variabile q[z, i, m, j, n] viene generata solamente se:

    - la hot stream i è presente nella zona z;
    - i è presente nell'intervallo m;
    - la cold stream j è presente nella zona z;
    - j è presente nell'intervallo n;
    - il match i-j è consentito;
    - j appartiene a P_H[z, i, m];
    - i appartiene a P_C[z, j, n];
    - T_n^L < T_m^U.

    Returns
    -------
    list
        Lista di tuple:
        (z, i, m, j, n)
    """

    Z = insiemi_HEN["Z"]

    H = insiemi_HEN["H"]
    C = insiemi_HEN["C"]

    M_i = insiemi_HEN["M_i"]
    N_j = insiemi_HEN["N_j"]

    P = insiemi_HEN["P"]
    P_H = insiemi_HEN["P_H"]
    P_C = insiemi_HEN["P_C"]

    T_intervallo = insiemi_HEN["T_intervallo"]

    indici_q = []


    # =================================================
    # GENERAZIONE DEGLI INDICI
    # =================================================

    for z in Z:

        for i in H[z]:

            for m in M_i[z, i]:

                # Temperatura superiore
                # dell'intervallo hot m
                T_m_U = T_intervallo[z, m]["T_sup"]

                for j in P_H[z, i, m]:

                    # Controllo ridondante ma utile:
                    # il match globale deve essere ammesso.
                    if (i, j) not in P:
                        continue

                    # La cold stream deve essere
                    # effettivamente presente nella zona.
                    if j not in C[z]:
                        continue

                    for n in N_j[z, j]:

                        # Coerenza anche dal lato cold.
                        if i not in P_C[z, j, n]:
                            continue

                        # Temperatura inferiore
                        # dell'intervallo cold n
                        T_n_L = T_intervallo[z, n]["T_inf"]


                        # ---------------------------------
                        # FATTIBILITÀ TERMICA
                        #
                        # Condizione riportata nel modello:
                        #
                        # T_n^L < T_m^U
                        #
                        # La scala HENS incorpora già
                        # delta_T_min tramite lo shift
                        # delle cold streams.
                        # ---------------------------------

                        if (
                            T_n_L
                            <
                            T_m_U - tolleranza
                        ):

                            indici_q.append(
                                (
                                    z,
                                    i,
                                    m,
                                    j,
                                    n,
                                )
                            )


    # =================================================
    # RIMOZIONE EVENTUALI DUPLICATI
    # =================================================

    indici_q = sorted(
        set(indici_q),
        key=lambda x: (
            x[0],
            x[1],
            x[2],
            x[3],
            x[4],
        ),
    )


    # =================================================
    # STAMPA DIAGNOSTICA
    # =================================================

    if debug:

        print("\n" + "=" * 65)
        print("INDICI AMMISSIBILI q^z_im,jn")
        print("=" * 65)

        for z in Z:

            indici_zona = [
                indice
                for indice in indici_q
                if indice[0] == z
            ]

            print(
                f"\nZona {z}: "
                f"{len(indici_zona)} variabili q"
            )

            for i in H[z]:

                print(
                    f"\n  Hot stream {i}"
                )

                for m in M_i[z, i]:

                    indici_im = [
                        indice
                        for indice in indici_zona
                        if (
                            indice[1] == i
                            and indice[2] == m
                        )
                    ]

                    if not indici_im:
                        print(
                            f"    m={m}: "
                            f"nessun trasferimento ammissibile"
                        )
                        continue

                    print(
                        f"    m={m}:"
                    )

                    for _, _, _, j, n in indici_im:

                        T_m_U = (
                            T_intervallo[z, m]["T_sup"]
                        )

                        T_n_L = (
                            T_intervallo[z, n]["T_inf"]
                        )

                        print(
                            f"      {i}[m={m}] "
                            f"-> {j}[n={n}] "
                            f"| "
                            f"T_m^U={T_m_U:.2f} °C, "
                            f"T_n^L={T_n_L:.2f} °C"
                        )

        print(
            "\nNumero totale variabili q ammissibili:",
            len(indici_q),
        )

    return indici_q

def calcola_delta_H_HEN(
    insiemi_HEN,
    tolleranza=1e-9,
    debug=False,
):
    """
    Calcola le variazioni entalpiche delle process streams
    in ciascun intervallo del modello HENS.

    Restituisce:

        delta_H_H[z, i, m]
            calore disponibile dalla hot process stream i
            nell'intervallo m della zona z [kW]

        delta_H_C[z, j, n]
            calore richiesto dalla cold process stream j
            nell'intervallo n della zona z [kW]

    Le utilities sono escluse perché il loro carico termico
    sarà determinato dal modello attraverso le variabili F_H e F_C.

    Le correnti appartenenti a NI_H o NI_C sono escluse
    dal base model, coerentemente con le equazioni HENS.
    """

    Z = insiemi_HEN["Z"]

    H = insiemi_HEN["H"]
    C = insiemi_HEN["C"]

    HU = insiemi_HEN["HU"]
    CU = insiemi_HEN["CU"]

    M_i = insiemi_HEN["M_i"]
    N_j = insiemi_HEN["N_j"]

    NI_H = insiemi_HEN["NI_H"]
    NI_C = insiemi_HEN["NI_C"]

    T_intervallo = insiemi_HEN["T_intervallo"]
    correnti = insiemi_HEN["correnti"]

    delta_H_H = {}
    delta_H_C = {}


    # =================================================
    # FUNZIONE DI SUPPORTO:
    # CP EQUIVALENTE DELLA CORRENTE
    # =================================================

    def calcola_CP_equivalente(flusso):

        delta_T_totale = abs(
            flusso.T_in - flusso.T_out
        )

        if delta_T_totale <= tolleranza:

            raise ValueError(
                f"La corrente {flusso.codice} è isoterma. "
                "La gestione delle correnti isoterme nel modello "
                "HENS deve essere trattata separatamente."
            )

        Q_totale = flusso.calcola_Q()

        return (
            Q_totale
            / delta_T_totale
        )


    # =================================================
    # 1. HOT PROCESS STREAMS
    # =================================================

    for z in Z:

        for i in H[z]:

            # Le hot utilities non hanno ΔH noto:
            # il loro carico dipenderà da F_H.
            if i in HU[z]:
                continue

            # Il base model non tratta qui
            # il non-isothermal mixing.
            if i in NI_H:
                continue

            flusso = correnti[i]

            CP = calcola_CP_equivalente(
                flusso
            )

            for m in M_i[z, i]:

                T_sup = (
                    T_intervallo[z, m]["T_sup"]
                )

                T_inf = (
                    T_intervallo[z, m]["T_inf"]
                )

                delta_T = (
                    T_sup - T_inf
                )

                delta_H_H[z, i, m] = (
                    CP * delta_T
                )


    # =================================================
    # 2. COLD PROCESS STREAMS
    # =================================================

    for z in Z:

        for j in C[z]:

            # Le cold utilities non hanno ΔH noto:
            # il loro carico dipenderà da F_C.
            if j in CU[z]:
                continue

            if j in NI_C:
                continue

            flusso = correnti[j]

            CP = calcola_CP_equivalente(
                flusso
            )

            for n in N_j[z, j]:

                T_sup = (
                    T_intervallo[z, n]["T_sup"]
                )

                T_inf = (
                    T_intervallo[z, n]["T_inf"]
                )

                delta_T = (
                    T_sup - T_inf
                )

                delta_H_C[z, j, n] = (
                    CP * delta_T
                )


    # =================================================
    # 3. STAMPA DIAGNOSTICA
    # =================================================

    if debug:

        print("\n" + "=" * 65)
        print("ΔH DELLE PROCESS STREAMS - HENS")
        print("=" * 65)

        for z in Z:

            print(
                f"\n{'-' * 65}"
                f"\nZONA {z}"
                f"\n{'-' * 65}"
            )


            # -----------------------------------------
            # HOT STREAMS
            # -----------------------------------------

            print("\nHOT PROCESS STREAMS")

            for i in H[z]:

                if i in HU[z] or i in NI_H:
                    continue

                flusso = correnti[i]

                CP = calcola_CP_equivalente(
                    flusso
                )

                print(
                    f"\n  {i} | "
                    f"CP = {CP:.6f} kW/K"
                )

                totale_zona = 0.0

                for m in M_i[z, i]:

                    valore = (
                        delta_H_H[z, i, m]
                    )

                    totale_zona += valore

                    T_sup = (
                        T_intervallo[z, m]["T_sup"]
                    )

                    T_inf = (
                        T_intervallo[z, m]["T_inf"]
                    )

                    print(
                        f"    m={m:2d} | "
                        f"{T_sup:8.2f} -> "
                        f"{T_inf:8.2f} °C | "
                        f"ΔH = {valore:9.3f} kW"
                    )

                print(
                    f"    Totale zona = "
                    f"{totale_zona:.3f} kW"
                )


            # -----------------------------------------
            # COLD STREAMS
            # -----------------------------------------

            print("\nCOLD PROCESS STREAMS")

            for j in C[z]:

                if j in CU[z] or j in NI_C:
                    continue

                flusso = correnti[j]

                CP = calcola_CP_equivalente(
                    flusso
                )

                print(
                    f"\n  {j} | "
                    f"CP = {CP:.6f} kW/K"
                )

                totale_zona = 0.0

                for n in N_j[z, j]:

                    valore = (
                        delta_H_C[z, j, n]
                    )

                    totale_zona += valore

                    T_sup = (
                        T_intervallo[z, n]["T_sup"]
                    )

                    T_inf = (
                        T_intervallo[z, n]["T_inf"]
                    )

                    print(
                        f"    n={n:2d} | "
                        f"{T_sup:8.2f} -> "
                        f"{T_inf:8.2f} °C | "
                        f"ΔH = {valore:9.3f} kW"
                    )

                print(
                    f"    Totale zona = "
                    f"{totale_zona:.3f} kW"
                )


        # =================================================
        # 4. CONTROLLO GLOBALE PER CORRENTE
        # =================================================

        print(
            "\n" + "=" * 65
            + "\nCONTROLLO BILANCI PER CORRENTE"
            + "\n" + "=" * 65
        )

        codici_process = {
            codice
            for z in Z
            for codice in (
                set(H[z]) | set(C[z])
            )
            if (
                codice not in HU[z]
                and codice not in CU[z]
            )
        }

        for codice in sorted(codici_process):

            flusso = correnti[codice]

            Q_riferimento = (
                flusso.calcola_Q()
            )

            if flusso.tipo == "hot":

                Q_calcolato = sum(
                    valore
                    for (z, i, m), valore
                    in delta_H_H.items()
                    if i == codice
                )

            else:

                Q_calcolato = sum(
                    valore
                    for (z, j, n), valore
                    in delta_H_C.items()
                    if j == codice
                )

            errore = (
                Q_calcolato
                - Q_riferimento
            )

            print(
                f"{codice}: "
                f"Q input = {Q_riferimento:.3f} kW | "
                f"ΣΔH = {Q_calcolato:.3f} kW | "
                f"errore = {errore:+.6f} kW"
            )


    return {
        "delta_H_H": delta_H_H,
        "delta_H_C": delta_H_C,
    }

def calcola_parametri_area_HEN(
    insiemi_HEN,
    indici_q,
    delta_T_min,
    tolleranza=1e-9,
    debug=False,
):
    """
    Calcola i parametri necessari per l'equazione dell'area HENS.

    Per ogni indice ammissibile:

        (z, i, m, j, n)

    calcola:

    - h_im della hot stream [kW/m²K]
    - h_jn della cold stream [kW/m²K]
    - ΔT_ML_mn [K]
    - coefficiente area [m²/kW]

    tale che:

        contributo_area =
            coeff_area[z,i,m,j,n]
            * q[z,i,m,j,n]

    e quindi, nel base model:

        A[z,i,j] =
            sum(coeff_area[k] * q[k])

    per tutti gli intervalli appartenenti al match i-j.

    Note
    ----
    Le temperature degli intervalli cold sono memorizzate
    sulla scala HENS:

        T_cold,HENS = T_cold,reale + delta_T_min

    Per il calcolo del LMTD vengono quindi riportate
    alla temperatura reale sottraendo delta_T_min.

    I coefficienti h sono letti in W/m²K e convertiti
    internamente in kW/m²K per essere coerenti con q [kW].
    """

    # =================================================
    # 1. INPUT
    # =================================================

    T_intervallo = (
        insiemi_HEN["T_intervallo"]
    )

    correnti = (
        insiemi_HEN["correnti"]
    )


    if delta_T_min < 0:

        raise ValueError(
            "delta_T_min deve essere >= 0."
        )


    if len(indici_q) != len(
        set(indici_q)
    ):

        raise ValueError(
            "indici_q contiene duplicati."
        )


    # =================================================
    # 2. FUNZIONE PER h
    # =================================================

    def leggi_h_kW_m2K(
        codice_corrente,
    ):
        """
        Legge h_W_m2K dall'oggetto corrente
        e lo converte:

            W/m²K -> kW/m²K
        """

        if codice_corrente not in correnti:

            raise KeyError(
                f"Corrente {codice_corrente} "
                "non presente in insiemi_HEN['correnti']."
            )

        corrente = (
            correnti[codice_corrente]
        )


        if not hasattr(
            corrente,
            "h_W_m2K",
        ):

            raise ValueError(
                f"La corrente {codice_corrente} "
                "non possiede l'attributo "
                "'h_W_m2K'. "
                "Controllare la classe Flusso "
                "e il caricamento del JSON."
            )


        h_W_m2K = (
            corrente.h_W_m2K
        )


        if h_W_m2K is None:

            raise ValueError(
                f"h_W_m2K non definito "
                f"per {codice_corrente}."
            )


        h_W_m2K = float(
            h_W_m2K
        )


        if h_W_m2K <= 0:

            raise ValueError(
                f"h_W_m2K deve essere > 0 "
                f"per {codice_corrente}. "
                f"Ricevuto: {h_W_m2K}"
            )


        # W/m²K -> kW/m²K
        return (
            h_W_m2K / 1000.0
        )


    # =================================================
    # 3. FUNZIONE LMTD
    # =================================================

    def calcola_LMTD(
        delta_T_1,
        delta_T_2,
    ):
        """
        Calcola la differenza media logaritmica
        di temperatura.

        ΔT_ML =
            (ΔT1 - ΔT2)
            / ln(ΔT1 / ΔT2)

        Se ΔT1 ≈ ΔT2:

            ΔT_ML = ΔT1
        """

        if (
            delta_T_1
            <= tolleranza
            or
            delta_T_2
            <= tolleranza
        ):

            raise ValueError(
                "LMTD non definibile con "
                "differenze di temperatura "
                "nulle o negative. "
                f"ΔT1={delta_T_1:.6f}, "
                f"ΔT2={delta_T_2:.6f}"
            )


        if abs(
            delta_T_1
            - delta_T_2
        ) <= tolleranza:

            return (
                0.5
                * (
                    delta_T_1
                    + delta_T_2
                )
            )


        return (
            (
                delta_T_1
                - delta_T_2
            )
            /
            math.log(
                delta_T_1
                / delta_T_2
            )
        )


    # =================================================
    # 4. CONTENITORI
    # =================================================

    h_H = {}
    h_C = {}

    delta_T_ML = {}

    coeff_area = {}

    dettagli = {}


    # =================================================
    # 5. CICLO SUGLI INDICI q
    # =================================================

    for indice in indici_q:

        (
            z,
            i,
            m,
            j,
            n,
        ) = indice


        # =============================================
        # 5.1 COEFFICIENTI DI FILM
        # =============================================

        chiave_h_hot = (
            z,
            i,
            m,
        )

        chiave_h_cold = (
            z,
            j,
            n,
        )


        if chiave_h_hot not in h_H:

            h_H[
                chiave_h_hot
            ] = leggi_h_kW_m2K(
                i
            )


        if chiave_h_cold not in h_C:

            h_C[
                chiave_h_cold
            ] = leggi_h_kW_m2K(
                j
            )


        h_im = (
            h_H[chiave_h_hot]
        )

        h_jn = (
            h_C[chiave_h_cold]
        )


        # =============================================
        # 5.2 TEMPERATURE INTERVALLO HOT
        # =============================================

        T_hot_U = (
            T_intervallo[
                z,
                m,
            ]["T_sup"]
        )

        T_hot_L = (
            T_intervallo[
                z,
                m,
            ]["T_inf"]
        )


        # =============================================
        # 5.3 TEMPERATURE INTERVALLO COLD
        #     SULLA SCALA HENS
        # =============================================

        T_cold_U_HEN = (
            T_intervallo[
                z,
                n,
            ]["T_sup"]
        )

        T_cold_L_HEN = (
            T_intervallo[
                z,
                n,
            ]["T_inf"]
        )


        # =============================================
        # 5.4 TEMPERATURE COLD REALI
        # =============================================
        #
        # Scala HENS:
        #
        # Tcold,HEN =
        #     Tcold,reale + delta_T_min
        #
        # quindi:
        #
        # Tcold,reale =
        #     Tcold,HEN - delta_T_min
        # =============================================

        T_cold_U = (
            T_cold_U_HEN
            - delta_T_min
        )

        T_cold_L = (
            T_cold_L_HEN
            - delta_T_min
        )


        # =============================================
        # 5.5 DIFFERENZE DI TEMPERATURA
        #     PER CONTROCORRENTE
        # =============================================
        #
        # Estremo caldo:
        #
        #   Thot,U - Tcold,U
        #
        # Estremo freddo:
        #
        #   Thot,L - Tcold,L
        #
        # =============================================

        delta_T_1 = (
            T_hot_U
            - T_cold_U
        )

        delta_T_2 = (
            T_hot_L
            - T_cold_L
        )


        # =============================================
        # 5.6 LMTD
        # =============================================

        DT_ML = calcola_LMTD(
            delta_T_1,
            delta_T_2,
        )


        delta_T_ML[
            (
                z,
                m,
                n,
            )
        ] = DT_ML


        # =============================================
        # 5.7 COEFFICIENTE AREA
        # =============================================
        #
        # Dalla eq. [1.39]:
        #
        # A =
        # Σ q *
        #
        #     (h_im + h_jn)
        # -----------------------
        # ΔTML * h_im * h_jn
        #
        # equivalente a:
        #
        # q / ΔTML *
        # (
        #   1/h_im + 1/h_jn
        # )
        #
        # h è già espresso in kW/m²K.
        #
        # Risultato:
        #
        # coeff_area [m²/kW]
        # =============================================

        coeff = (
            (
                1.0 / h_im
                +
                1.0 / h_jn
            )
            /
            DT_ML
        )


        coeff_area[
            indice
        ] = coeff


        # =============================================
        # 5.8 DETTAGLI DIAGNOSTICI
        # =============================================

        dettagli[
            indice
        ] = {

            "h_hot_kW_m2K":
                h_im,

            "h_cold_kW_m2K":
                h_jn,

            "T_hot_U_C":
                T_hot_U,

            "T_hot_L_C":
                T_hot_L,

            "T_cold_U_HEN_C":
                T_cold_U_HEN,

            "T_cold_L_HEN_C":
                T_cold_L_HEN,

            "T_cold_U_reale_C":
                T_cold_U,

            "T_cold_L_reale_C":
                T_cold_L,

            "delta_T_1_K":
                delta_T_1,

            "delta_T_2_K":
                delta_T_2,

            "delta_T_ML_K":
                DT_ML,

            "coeff_area_m2_per_kW":
                coeff,
        }


    # =================================================
    # 6. DEBUG
    # =================================================

    if debug:

        print(
            "\n" + "=" * 70
        )

        print(
            "PARAMETRI AREA HENS"
        )

        print(
            "=" * 70
        )

        print(
            f"\nNumero indici q analizzati: "
            f"{len(indici_q)}"
        )

        print(
            f"Numero coefficienti area: "
            f"{len(coeff_area)}"
        )


        if coeff_area:

            valori_lmtd = [
                dettagli[k][
                    "delta_T_ML_K"
                ]
                for k in indici_q
            ]

            valori_coeff = [
                coeff_area[k]
                for k in indici_q
            ]


            print(
                f"\nΔTML minimo: "
                f"{min(valori_lmtd):.6f} K"
            )

            print(
                f"ΔTML massimo: "
                f"{max(valori_lmtd):.6f} K"
            )

            print(
                f"Coeff. area minimo: "
                f"{min(valori_coeff):.6f} "
                f"m²/kW"
            )

            print(
                f"Coeff. area massimo: "
                f"{max(valori_coeff):.6f} "
                f"m²/kW"
            )


        print(
            "\nPrime 20 combinazioni:"
        )


        for indice in indici_q[:20]:

            dati = (
                dettagli[indice]
            )

            print(
                f"\n{indice}"
            )

            print(
                f"  h_hot  = "
                f"{dati['h_hot_kW_m2K']:.6f} "
                f"kW/m²K"
            )

            print(
                f"  h_cold = "
                f"{dati['h_cold_kW_m2K']:.6f} "
                f"kW/m²K"
            )

            print(
                f"  ΔT1 = "
                f"{dati['delta_T_1_K']:.3f} K"
            )

            print(
                f"  ΔT2 = "
                f"{dati['delta_T_2_K']:.3f} K"
            )

            print(
                f"  ΔTML = "
                f"{dati['delta_T_ML_K']:.3f} K"
            )

            print(
                f"  K_area = "
                f"{dati['coeff_area_m2_per_kW']:.6f} "
                f"m²/kW"
            )


    # =================================================
    # 7. OUTPUT
    # =================================================

    return {

        "h_H":
            h_H,

        "h_C":
            h_C,

        "delta_T_ML":
            delta_T_ML,

        "coeff_area":
            coeff_area,

        "dettagli":
            dettagli,
    }

def costruisci_utilities_HEN(
    configurazione,
    debug=False,
):
    """
    Costruisce le utility termiche utilizzate nel modello HENS.

    Le utility devono essere definite nel JSON come:

        hens -> utilities

    Returns
    -------
    dict
        {
            "hot": [UtilityHEN, ...],
            "cold": [UtilityHEN, ...]
        }
    """

    # =================================================
    # 1. LETTURA SEZIONE HENS
    # =================================================

    if "hens" not in configurazione:
        raise ValueError(
            "La configurazione non contiene "
            "la sezione 'hens'."
        )

    dati_hens = configurazione["hens"]

    if not isinstance(dati_hens, dict):
        raise ValueError(
            "La sezione 'hens' deve essere "
            "un dizionario."
        )


    # =================================================
    # 2. LETTURA UTILITIES
    # =================================================

    if "utilities" not in dati_hens:
        raise ValueError(
            "La sezione 'hens' non contiene "
            "'utilities'."
        )

    dati_utilities = dati_hens["utilities"]

    if not isinstance(dati_utilities, list):
        raise ValueError(
            "'hens.utilities' deve essere "
            "una lista."
        )


    # =================================================
    # 3. CONTENITORI
    # =================================================

    utilities = {
        "hot": [],
        "cold": [],
    }

    codici = set()


    # =================================================
    # 4. COSTRUZIONE UTILITIES
    # =================================================

    for dati in dati_utilities:

        if not isinstance(dati, dict):
            raise ValueError(
                "Ogni utility HENS deve essere "
                "definita tramite un dizionario."
            )


        # ---------------------------------------------
        # Campi obbligatori
        # ---------------------------------------------

        campi_obbligatori = [
            "codice",
            "tipo",
            "T_in",
            "T_out",
            "h_W_m2K",
        ]

        mancanti = [
            campo
            for campo in campi_obbligatori
            if campo not in dati
        ]

        if mancanti:
            raise ValueError(
                "Utility HENS incompleta. "
                f"Campi mancanti: {mancanti}"
            )


        # ---------------------------------------------
        # Normalizzazione tipo
        # ---------------------------------------------

        tipo = str(
            dati["tipo"]
        ).strip().lower()

        if tipo not in (
            "hot",
            "cold",
        ):
            raise ValueError(
                f"Tipo non valido per utility "
                f"{dati['codice']}: {tipo}"
            )


        # ---------------------------------------------
        # Costo utility
        # ---------------------------------------------

        costo_raw = dati.get(
            "costo_USD_per_kW_year"
        )

        costo = (
            None
            if costo_raw is None
            else float(costo_raw)
        )


        # ---------------------------------------------
        # Creazione UtilityHEN
        # ---------------------------------------------

        utility = UtilityHEN(
            codice=str(
                dati["codice"]
            ),

            nome=str(
                dati.get(
                    "nome",
                    dati["codice"],
                )
            ),

            tipo=tipo,

            T_in=float(
                dati["T_in"]
            ),

            T_out=float(
                dati["T_out"]
            ),

            h_W_m2K=float(
                dati["h_W_m2K"]
            ),

            costo_USD_per_kW_year=costo,

            duty_variabile=bool(
                dati.get(
                    "duty_variabile",
                    True,
                )
            ),

            disponibile=bool(
                dati.get(
                    "disponibile",
                    True,
                )
            ),
        )


        # =================================================
        # 5. CONTROLLI
        # =================================================

        if utility.codice in codici:

            raise ValueError(
                f"Utility HENS duplicata: "
                f"{utility.codice}"
            )

        codici.add(
            utility.codice
        )


        # ---------------------------------------------
        # Temperature
        # ---------------------------------------------

        if (
            utility.tipo == "hot"
            and utility.T_in
            <= utility.T_out
        ):

            raise ValueError(
                f"La hot utility "
                f"{utility.codice} deve avere "
                f"T_in > T_out."
            )


        if (
            utility.tipo == "cold"
            and utility.T_out
            <= utility.T_in
        ):

            raise ValueError(
                f"La cold utility "
                f"{utility.codice} deve avere "
                f"T_out > T_in."
            )


        # ---------------------------------------------
        # Coefficiente di film
        # ---------------------------------------------

        if utility.h_W_m2K <= 0:

            raise ValueError(
                f"h_W_m2K non valido per "
                f"{utility.codice}: "
                f"{utility.h_W_m2K}"
            )


        # ---------------------------------------------
        # Costo
        # ---------------------------------------------

        if (
            utility.costo_USD_per_kW_year
            is not None
            and
            utility.costo_USD_per_kW_year < 0
        ):

            raise ValueError(
                f"Costo utility negativo per "
                f"{utility.codice}: "
                f"{utility.costo_USD_per_kW_year}"
            )


        # ---------------------------------------------
        # Utility disabilitata
        # ---------------------------------------------

        if not utility.disponibile:

            if debug:
                print(
                    f"Utility "
                    f"{utility.codice} ignorata: "
                    f"disponibile=False"
                )

            continue


        utilities[
            utility.tipo
        ].append(
            utility
        )


    # =================================================
    # 6. DEBUG
    # =================================================

    if debug:

        print(
            "\n" + "=" * 60
        )

        print(
            "UTILITY HENS"
        )

        print(
            "=" * 60
        )


        for tipo in (
            "hot",
            "cold",
        ):

            for utility in utilities[tipo]:

                costo_testo = (
                    "non definito"
                    if utility.costo_USD_per_kW_year
                    is None
                    else
                    (
                        f"{utility.costo_USD_per_kW_year:.2f} "
                        f"$/kW/year"
                    )
                )

                print(
                    f"{utility.codice} | "
                    f"{utility.tipo.upper()} | "
                    f"{utility.T_in:.2f} -> "
                    f"{utility.T_out:.2f} °C | "
                    f"h = "
                    f"{utility.h_W_m2K:.2f} W/m²K | "
                    f"costo = {costo_testo}"
                )


    return utilities

def crea_modello_bilanci_HEN(
    insiemi_HEN,
    indici_q,
    delta_H_HEN,
    nome_modello="HENS_bilanci",
    debug=False,
):
    """
    Costruisce il primo modello DOcplex della HENS,
    contenente solamente:

    - variabili q[z,i,m,j,n];
    - variabili F_H delle hot utilities;
    - variabili F_C delle cold utilities;
    - bilanci energetici hot process;
    - bilanci energetici cold process;
    - bilanci energetici hot utilities;
    - bilanci energetici cold utilities.

    Non vengono ancora considerate:
    - area degli scambiatori;
    - numero di scambiatori;
    - tecnologie HEX;
    - costi;
    - non-isothermal mixing;
    - flexible streams.

    Parameters
    ----------
    insiemi_HEN : dict
        Insiemi prodotti da costruisci_insiemi_HEN().

    indici_q : list
        Tuple ammissibili:
            (z, i, m, j, n)

    delta_H_HEN : dict
        Output di calcola_delta_H_HEN():

            {
                "delta_H_H": {...},
                "delta_H_C": {...},
            }

    nome_modello : str
        Nome del modello DOcplex.

    debug : bool
        Se True stampa informazioni diagnostiche.

    Returns
    -------
    dict
        Contiene modello, variabili ed espressioni
        utili per la successiva risoluzione.
    """

    # =================================================
    # 1. LETTURA DEGLI INSIEMI
    # =================================================

    Z = insiemi_HEN["Z"]

    H = insiemi_HEN["H"]
    C = insiemi_HEN["C"]

    HU = insiemi_HEN["HU"]
    CU = insiemi_HEN["CU"]

    M_i = insiemi_HEN["M_i"]
    N_j = insiemi_HEN["N_j"]

    NI_H = set(
        insiemi_HEN.get(
            "NI_H",
            [],
        )
    )

    NI_C = set(
        insiemi_HEN.get(
            "NI_C",
            [],
        )
    )

    T_intervallo = (
        insiemi_HEN["T_intervallo"]
    )

    delta_H_H = (
        delta_H_HEN["delta_H_H"]
    )

    delta_H_C = (
        delta_H_HEN["delta_H_C"]
    )


    # =================================================
    # 2. CONTROLLO VERSIONE DEL MODELLO
    # =================================================
    #
    # Non abbiamo ancora implementato le equazioni
    # necessarie al non-isothermal mixing.
    # È meglio fermarsi esplicitamente invece di
    # costruire un modello incompleto.
    # =================================================

    if NI_H or NI_C:

        raise NotImplementedError(
            "crea_modello_bilanci_HEN() "
            "non gestisce ancora il "
            "non-isothermal mixing. "
            f"NI_H={NI_H}, NI_C={NI_C}"
        )


    # =================================================
    # 3. CONTROLLO INDICI q
    # =================================================

    if len(indici_q) != len(
        set(indici_q)
    ):

        raise ValueError(
            "indici_q contiene duplicati."
        )


    # =================================================
    # 4. CREAZIONE MODELLO DOCPLEX
    # =================================================

    mdl = Model(
        name=nome_modello
    )


    # =================================================
    # 5. VARIABILI q
    # =================================================
    #
    # q[z,i,m,j,n] >= 0
    #
    # Calore trasferito:
    #
    # hot stream i, intervallo m
    #               ↓
    # cold stream j, intervallo n
    #
    # [kW]
    # =================================================

    q = mdl.continuous_var_dict(
        indici_q,
        lb=0,
        name="q",
    )


    # =================================================
    # 6. INDICI DELLE UTILITIES
    # =================================================

    codici_HU = sorted(
        {
            i
            for z in Z
            for i in HU[z]
        }
    )

    codici_CU = sorted(
        {
            j
            for z in Z
            for j in CU[z]
        }
    )


    # =================================================
    # 7. VARIABILI F DELLE UTILITIES
    # =================================================
    #
    # F_H e F_C hanno dimensionalmente:
    #
    #     kW/K
    #
    # perché:
    #
    #     Q = F * ΔT
    #
    # =================================================

    F_H = mdl.continuous_var_dict(
        codici_HU,
        lb=0,
        name="F_H",
    )

    F_C = mdl.continuous_var_dict(
        codici_CU,
        lb=0,
        name="F_C",
    )


    # =================================================
    # 8. PREPROCESSING DEGLI INDICI q
    # =================================================
    #
    # Evitiamo di scorrere tutte le variabili q
    # ogni volta che costruiamo un bilancio.
    #
    # q_da_hot[z,i,m]:
    #     tutte le q che partono da (z,i,m)
    #
    # q_a_cold[z,j,n]:
    #     tutte le q che arrivano a (z,j,n)
    # =================================================

    q_da_hot = {}
    q_a_cold = {}

    for indice in indici_q:

        z, i, m, j, n = indice

        q_da_hot.setdefault(
            (z, i, m),
            [],
        ).append(
            indice
        )

        q_a_cold.setdefault(
            (z, j, n),
            [],
        ).append(
            indice
        )


    # =================================================
    # 9. CONTENITORI DEI VINCOLI
    # =================================================

    vincoli_hot_process = []
    vincoli_cold_process = []

    vincoli_hot_utility = []
    vincoli_cold_utility = []


    # =================================================
    # 10. BILANCI HOT
    # =================================================

    for z in Z:

        for i in H[z]:

            # =========================================
            # HOT UTILITY
            # =========================================
            #
            # F_i^H (T_m^U - T_m^L)
            #
            #       =
            #
            # Σ_j Σ_n q[z,i,m,j,n]
            #
            # =========================================

            if i in HU[z]:

                for m in M_i[z, i]:

                    T_sup = (
                        T_intervallo[
                            z,
                            m,
                        ]["T_sup"]
                    )

                    T_inf = (
                        T_intervallo[
                            z,
                            m,
                        ]["T_inf"]
                    )

                    delta_T_m = (
                        T_sup - T_inf
                    )

                    chiavi_q = (
                        q_da_hot.get(
                            (z, i, m),
                            [],
                        )
                    )

                    Q_uscente = mdl.sum(
                        q[k]
                        for k in chiavi_q
                    )

                    vincolo = mdl.add_constraint(
                        F_H[i]
                        * delta_T_m
                        ==
                        Q_uscente,
                        ctname=(
                            f"bil_HU_"
                            f"z{z}_"
                            f"{i}_"
                            f"m{m}"
                        ),
                    )

                    vincoli_hot_utility.append(
                        vincolo
                    )


            # =========================================
            # HOT PROCESS STREAM
            # =========================================
            #
            # ΔH[z,i,m]
            #
            #       =
            #
            # Σ_j Σ_n q[z,i,m,j,n]
            #
            # =========================================

            else:

                for m in M_i[z, i]:

                    chiave_delta_H = (
                        z,
                        i,
                        m,
                    )

                    if (
                        chiave_delta_H
                        not in delta_H_H
                    ):

                        raise KeyError(
                            "ΔH hot mancante per "
                            f"{chiave_delta_H}"
                        )

                    valore_delta_H = (
                        delta_H_H[
                            chiave_delta_H
                        ]
                    )

                    chiavi_q = (
                        q_da_hot.get(
                            chiave_delta_H,
                            [],
                        )
                    )

                    # Una process stream con ΔH > 0
                    # deve avere almeno un trasferimento
                    # potenzialmente disponibile.
                    if (
                        valore_delta_H > 1e-12
                        and not chiavi_q
                    ):

                        raise ValueError(
                            "Nessun indice q disponibile "
                            "per il bilancio hot "
                            f"{chiave_delta_H}."
                        )

                    Q_uscente = mdl.sum(
                        q[k]
                        for k in chiavi_q
                    )

                    vincolo = mdl.add_constraint(
                        Q_uscente
                        ==
                        valore_delta_H,
                        ctname=(
                            f"bil_HP_"
                            f"z{z}_"
                            f"{i}_"
                            f"m{m}"
                        ),
                    )

                    vincoli_hot_process.append(
                        vincolo
                    )


    # =================================================
    # 11. BILANCI COLD
    # =================================================

    for z in Z:

        for j in C[z]:

            # =========================================
            # COLD UTILITY
            # =========================================
            #
            # F_j^C (T_n^U - T_n^L)
            #
            #       =
            #
            # Σ_i Σ_m q[z,i,m,j,n]
            #
            # =========================================

            if j in CU[z]:

                for n in N_j[z, j]:

                    T_sup = (
                        T_intervallo[
                            z,
                            n,
                        ]["T_sup"]
                    )

                    T_inf = (
                        T_intervallo[
                            z,
                            n,
                        ]["T_inf"]
                    )

                    delta_T_n = (
                        T_sup - T_inf
                    )

                    chiavi_q = (
                        q_a_cold.get(
                            (z, j, n),
                            [],
                        )
                    )

                    Q_entrante = mdl.sum(
                        q[k]
                        for k in chiavi_q
                    )

                    vincolo = mdl.add_constraint(
                        F_C[j]
                        * delta_T_n
                        ==
                        Q_entrante,
                        ctname=(
                            f"bil_CU_"
                            f"z{z}_"
                            f"{j}_"
                            f"n{n}"
                        ),
                    )

                    vincoli_cold_utility.append(
                        vincolo
                    )


            # =========================================
            # COLD PROCESS STREAM
            # =========================================
            #
            # ΔH[z,j,n]
            #
            #       =
            #
            # Σ_i Σ_m q[z,i,m,j,n]
            #
            # =========================================

            else:

                for n in N_j[z, j]:

                    chiave_delta_H = (
                        z,
                        j,
                        n,
                    )

                    if (
                        chiave_delta_H
                        not in delta_H_C
                    ):

                        raise KeyError(
                            "ΔH cold mancante per "
                            f"{chiave_delta_H}"
                        )

                    valore_delta_H = (
                        delta_H_C[
                            chiave_delta_H
                        ]
                    )

                    chiavi_q = (
                        q_a_cold.get(
                            chiave_delta_H,
                            [],
                        )
                    )

                    if (
                        valore_delta_H > 1e-12
                        and not chiavi_q
                    ):

                        raise ValueError(
                            "Nessun indice q disponibile "
                            "per il bilancio cold "
                            f"{chiave_delta_H}."
                        )

                    Q_entrante = mdl.sum(
                        q[k]
                        for k in chiavi_q
                    )

                    vincolo = mdl.add_constraint(
                        Q_entrante
                        ==
                        valore_delta_H,
                        ctname=(
                            f"bil_CP_"
                            f"z{z}_"
                            f"{j}_"
                            f"n{n}"
                        ),
                    )

                    vincoli_cold_process.append(
                        vincolo
                    )


    # =================================================
    # 12. ΔT TOTALE DELLE UTILITIES
    # =================================================
    #
    # Serve per ricostruire successivamente:
    #
    # Q_HU = F_H * ΔT_tot
    # Q_CU = F_C * ΔT_tot
    #
    # =================================================

    delta_T_HU = {
        i: 0.0
        for i in codici_HU
    }

    delta_T_CU = {
        j: 0.0
        for j in codici_CU
    }


    for z in Z:

        for i in HU[z]:

            for m in M_i[z, i]:

                T_sup = (
                    T_intervallo[
                        z,
                        m,
                    ]["T_sup"]
                )

                T_inf = (
                    T_intervallo[
                        z,
                        m,
                    ]["T_inf"]
                )

                delta_T_HU[i] += (
                    T_sup - T_inf
                )


        for j in CU[z]:

            for n in N_j[z, j]:

                T_sup = (
                    T_intervallo[
                        z,
                        n,
                    ]["T_sup"]
                )

                T_inf = (
                    T_intervallo[
                        z,
                        n,
                    ]["T_inf"]
                )

                delta_T_CU[j] += (
                    T_sup - T_inf
                )


    # =================================================
    # 13. ESPRESSIONI DEI DUTY DELLE UTILITIES
    # =================================================

    Q_HU = {
        i: (
            F_H[i]
            * delta_T_HU[i]
        )
        for i in codici_HU
    }

    Q_CU = {
        j: (
            F_C[j]
            * delta_T_CU[j]
        )
        for j in codici_CU
    }


    # =================================================
    # 14. OBIETTIVO TEMPORANEO
    # =================================================
    #
    # In questa fase cerchiamo solamente
    # una soluzione energeticamente fattibile.
    #
    # La vera funzione obiettivo TAC verrà inserita
    # successivamente.
    # =================================================

    mdl.minimize(0)


    # =================================================
    # 15. DEBUG
    # =================================================

    if debug:

        print("\n" + "=" * 65)
        print("MODELLO DOCPLEX - BILANCI HENS")
        print("=" * 65)

        print(
            f"Variabili q: "
            f"{len(q)}"
        )

        print(
            f"Variabili F_H: "
            f"{len(F_H)}"
        )

        print(
            f"Variabili F_C: "
            f"{len(F_C)}"
        )

        print(
            "\nVincoli hot process:",
            len(
                vincoli_hot_process
            ),
        )

        print(
            "Vincoli cold process:",
            len(
                vincoli_cold_process
            ),
        )

        print(
            "Vincoli hot utility:",
            len(
                vincoli_hot_utility
            ),
        )

        print(
            "Vincoli cold utility:",
            len(
                vincoli_cold_utility
            ),
        )

        print(
            "\nTotale vincoli:",
            mdl.number_of_constraints,
        )

        print("\nUtilities:")

        for i in codici_HU:

            print(
                f"  {i}: "
                f"ΔT totale = "
                f"{delta_T_HU[i]:.3f} K"
            )

        for j in codici_CU:

            print(
                f"  {j}: "
                f"ΔT totale = "
                f"{delta_T_CU[j]:.3f} K"
            )


    return {
        "modello": mdl,

        "q": q,

        "F_H": F_H,
        "F_C": F_C,

        "Q_HU": Q_HU,
        "Q_CU": Q_CU,

        "delta_T_HU": delta_T_HU,
        "delta_T_CU": delta_T_CU,

        "vincoli": {
            "hot_process":
                vincoli_hot_process,

            "cold_process":
                vincoli_cold_process,

            "hot_utility":
                vincoli_hot_utility,

            "cold_utility":
                vincoli_cold_utility,
        },
    }

def aggiungi_variabili_tecnologie_HEN(
    modello_bilanci,
    insiemi_HEN,
    indici_q,
    tecnologie_HEN,
    debug=False,
):
    """
    Aggiunge al modello HENS le variabili associate
    agli scambiatori e alle tecnologie:

        A[z,i,j,t] >= 0
        U[z,i,j,t] intera >= 0

    Le variabili vengono create solamente quando:

    1. il match (i,j) è termodinamicamente possibile
       nella zona z, cioè esiste almeno un indice q;

    2. il match (i,j) è consentito dalla tecnologia t,
       cioè (i,j) appartiene a P_t.

    Non vengono ancora aggiunti:
    - equazione dell'area;
    - vincolo A <= Amax * U;
    - funzione obiettivo TAC.

    Parameters
    ----------
    modello_bilanci : dict
        Output di crea_modello_bilanci_HEN().

    insiemi_HEN : dict
        Insiemi HENS.

    indici_q : list
        Indici delle variabili q:
            (z,i,m,j,n)

    tecnologie_HEN : dict
        Output di costruisci_tecnologie_HEN().

    debug : bool
        Attiva output diagnostico.

    Returns
    -------
    dict
        Dizionario modello_bilanci aggiornato con:

        - indici_A_U
        - A
        - U
    """

    # =================================================
    # 1. MODELLO DOCPLEX
    # =================================================

    mdl = modello_bilanci[
        "modello"
    ]


    # =================================================
    # 2. TECNOLOGIE
    # =================================================

    T = tecnologie_HEN[
        "T"
    ]

    P_t = tecnologie_HEN[
        "P_t"
    ]


    # =================================================
    # 3. MATCH EFFETTIVAMENTE POSSIBILI PER ZONA
    # =================================================
    #
    # Se esiste almeno una:
    #
    # q[z,i,m,j,n]
    #
    # allora il match (i,j) può essere utilizzato
    # nella zona z.
    # =================================================

    coppie_zona = {
        (
            z,
            i,
            j,
        )
        for (
            z,
            i,
            m,
            j,
            n,
        )
        in indici_q
    }


    # =================================================
    # 4. COSTRUZIONE INDICI (z,i,j,t)
    # =================================================

    indici_A_U = []


    for (
        z,
        i,
        j,
    ) in sorted(
        coppie_zona
    ):

        for t in T:

            # La tecnologia t deve poter essere
            # utilizzata sul match i-j.

            if (
                i,
                j,
            ) not in P_t[t]:

                continue


            indici_A_U.append(
                (
                    z,
                    i,
                    j,
                    t,
                )
            )


    # =================================================
    # 5. CONTROLLO DUPLICATI
    # =================================================

    if len(indici_A_U) != len(
        set(indici_A_U)
    ):

        raise ValueError(
            "Sono stati generati indici "
            "A/U duplicati."
        )


    # =================================================
    # 6. VARIABILI DI AREA
    # =================================================
    #
    # A[z,i,j,t] [m²]
    #
    # Area totale assegnata alla tecnologia t
    # per il match i-j nella zona z.
    # =================================================

    A = mdl.continuous_var_dict(
        indici_A_U,
        lb=0,
        name="A",
    )


    # =================================================
    # 7. VARIABILI INTERE U
    # =================================================
    #
    # U[z,i,j,t]
    #
    # Numero di exchanger/shells della tecnologia t
    # utilizzati per il match i-j nella zona z.
    #
    # Il PDF utilizza una variabile intera,
    # non semplicemente binaria.
    # =================================================

    U = mdl.integer_var_dict(
        indici_A_U,
        lb=0,
        name="U",
    )


    # =================================================
    # 8. DEBUG
    # =================================================

    if debug:

        print(
            "\n" + "=" * 70
        )

        print(
            "VARIABILI TECNOLOGIE HENS"
        )

        print(
            "=" * 70
        )

        print(
            f"\nNumero coppie zona-match "
            f"termodinamicamente possibili: "
            f"{len(coppie_zona)}"
        )

        print(
            f"Numero variabili A: "
            f"{len(A)}"
        )

        print(
            f"Numero variabili U: "
            f"{len(U)}"
        )


        print(
            "\nIndici A/U:"
        )


        for indice in indici_A_U:

            (
                z,
                i,
                j,
                t,
            ) = indice

            print(
                f"  Zona {z} | "
                f"{i} -> {j} | "
                f"{t}"
            )


    # =================================================
    # 9. AGGIORNAMENTO OUTPUT MODELLO
    # =================================================

    modello_bilanci[
        "indici_A_U"
    ] = indici_A_U

    modello_bilanci[
        "A"
    ] = A

    modello_bilanci[
        "U"
    ] = U

    modello_bilanci[
        "tecnologie_HEN"
    ] = tecnologie_HEN


    return modello_bilanci
def aggiungi_vincoli_area_HEN(
    modello_HEN,
    indici_q,
    parametri_area,
    tecnologie_HEN,
    debug=False,
):
    """
    Aggiunge al modello HENS:

    1. equazione dell'area con tecnologie multiple:

           sum_t A[z,i,j,t] * FHEX[t]
               =
           sum_m,n K_area[z,i,m,j,n]
                     * q[z,i,m,j,n]

    2. vincolo di capacità:

           A[z,i,j,t]
               <=
           A_max[t] * U[z,i,j,t]

    Le equazioni corrispondono alle [1.43]-[1.46]
    del modello HENS esteso.

    Parameters
    ----------
    modello_HEN : dict
        Modello restituito da
        aggiungi_variabili_tecnologie_HEN().

    indici_q : list
        Indici q:
            (z, i, m, j, n)

    parametri_area : dict
        Output di calcola_parametri_area_HEN().

    tecnologie_HEN : dict
        Output di costruisci_tecnologie_HEN().

    debug : bool
        Attiva output diagnostico.

    Returns
    -------
    dict
        modello_HEN aggiornato con i vincoli area.
    """

    # =================================================
    # 1. RECUPERO MODELLO E VARIABILI
    # =================================================

    mdl = modello_HEN[
        "modello"
    ]

    q = modello_HEN[
        "q"
    ]

    A = modello_HEN[
        "A"
    ]

    U = modello_HEN[
        "U"
    ]

    indici_A_U = modello_HEN[
        "indici_A_U"
    ]


    # =================================================
    # 2. PARAMETRI
    # =================================================

    coeff_area = parametri_area[
        "coeff_area"
    ]

    tecnologie = tecnologie_HEN[
        "tecnologie"
    ]


    # =================================================
    # 3. CONTROLLO COEFFICIENTI AREA
    # =================================================

    mancanti = [
        indice
        for indice in indici_q
        if indice not in coeff_area
    ]

    if mancanti:

        raise KeyError(
            "Mancano coefficienti area "
            "per alcuni indici q. "
            f"Primo indice mancante: "
            f"{mancanti[0]}"
        )


    # =================================================
    # 4. RAGGRUPPAMENTO q PER MATCH (z,i,j)
    # =================================================
    #
    # Da:
    #
    #   q[z,i,m,j,n]
    #
    # costruiamo:
    #
    #   q_match[z,i,j]
    #
    # che contiene tutti gli intervalli m,n
    # appartenenti allo stesso match.
    # =================================================

    q_match = {}

    for indice in indici_q:

        (
            z,
            i,
            m,
            j,
            n,
        ) = indice

        chiave_match = (
            z,
            i,
            j,
        )

        q_match.setdefault(
            chiave_match,
            [],
        ).append(
            indice
        )


    # =================================================
    # 5. RAGGRUPPAMENTO TECNOLOGIE PER MATCH
    # =================================================
    #
    # Per ciascun:
    #
    #   (z,i,j)
    #
    # troviamo tutti gli indici:
    #
    #   (z,i,j,t)
    #
    # effettivamente creati.
    # =================================================

    tecnologie_match = {}

    for indice in indici_A_U:

        (
            z,
            i,
            j,
            t,
        ) = indice

        chiave_match = (
            z,
            i,
            j,
        )

        tecnologie_match.setdefault(
            chiave_match,
            [],
        ).append(
            indice
        )


    # =================================================
    # 6. CONTENITORI VINCOLI
    # =================================================

    vincoli_equazione_area = []
    vincoli_Amax = []


    # =================================================
    # 7. EQUAZIONE AREA [1.43]
    # =================================================
    #
    # sum_t A[z,i,j,t] * FHEX[t]
    #
    # =
    #
    # sum_m,n
    #     coeff_area[z,i,m,j,n]
    #     * q[z,i,m,j,n]
    #
    # =================================================

    for chiave_match in sorted(
        q_match
    ):

        (
            z,
            i,
            j,
        ) = chiave_match


        # ---------------------------------------------
        # Tecnologie disponibili per il match
        # ---------------------------------------------

        indici_tecnologie = (
            tecnologie_match.get(
                chiave_match,
                [],
            )
        )


        if not indici_tecnologie:

            raise ValueError(
                "Il match "
                f"{chiave_match} "
                "possiede variabili q ma "
                "nessuna tecnologia HEX disponibile."
            )


        # ---------------------------------------------
        # Lato termico:
        #
        # Σ K_area * q
        # ---------------------------------------------

        area_equivalente = mdl.sum(
            coeff_area[indice]
            * q[indice]
            for indice
            in q_match[
                chiave_match
            ]
        )


        # ---------------------------------------------
        # Lato tecnologie:
        #
        # Σ A * FHEX
        # ---------------------------------------------

        area_tecnologie = mdl.sum(
            A[indice_A]
            * tecnologie[
                indice_A[3]
            ].FHEX
            for indice_A
            in indici_tecnologie
        )


        # ---------------------------------------------
        # Vincolo
        # ---------------------------------------------

        vincolo = mdl.add_constraint(
            area_tecnologie
            ==
            area_equivalente,

            ctname=(
                f"area_"
                f"z{z}_"
                f"{i}_"
                f"{j}"
            ),
        )


        vincoli_equazione_area.append(
            vincolo
        )


    # =================================================
    # 8. VINCOLO AREA MASSIMA [1.46]
    # =================================================
    #
    # A[z,i,j,t]
    #
    # <=
    #
    # Amax[t] * U[z,i,j,t]
    #
    # =================================================

    for indice in indici_A_U:

        (
            z,
            i,
            j,
            t,
        ) = indice

        tecnologia = tecnologie[
            t
        ]

        A_max = (
            tecnologia.A_max_m2
        )


        vincolo = mdl.add_constraint(
            A[indice]
            <=
            A_max
            * U[indice],

            ctname=(
                f"Amax_"
                f"z{z}_"
                f"{i}_"
                f"{j}_"
                f"{t}"
            ),
        )


        vincoli_Amax.append(
            vincolo
        )


    # =================================================
    # 9. NOTA SU [1.44] E [1.45]
    # =================================================
    #
    # [1.44]:
    # A = 0 per tecnologie non consentite.
    #
    # Non serve un vincolo esplicito perché non
    # creiamo proprio A[z,i,j,t] quando
    # (i,j) non appartiene a P_t.
    #
    # [1.45]:
    # A >= 0 per tecnologie consentite.
    #
    # È già garantito da:
    #
    # continuous_var_dict(..., lb=0)
    #
    # =================================================


    # =================================================
    # 10. SALVATAGGIO NEL MODELLO
    # =================================================

    modello_HEN[
        "vincoli_area"
    ] = {

        "equazione_area":
            vincoli_equazione_area,

        "Amax":
            vincoli_Amax,
    }


    # =================================================
    # 11. DEBUG
    # =================================================

    if debug:

        print(
            "\n" + "=" * 70
        )

        print(
            "VINCOLI AREA HENS"
        )

        print(
            "=" * 70
        )


        print(
            "\nEquazioni area [1.43]:",
            len(
                vincoli_equazione_area
            ),
        )


        print(
            "Vincoli Amax [1.46]:",
            len(
                vincoli_Amax
            ),
        )


        print(
            "Vincoli area aggiunti:",
            (
                len(
                    vincoli_equazione_area
                )
                +
                len(
                    vincoli_Amax
                )
            ),
        )


        print(
            "\nNumero totale variabili:",
            mdl.number_of_variables,
        )

        print(
            "Numero totale vincoli:",
            mdl.number_of_constraints,
        )


    return modello_HEN

def aggiungi_obiettivo_TAC_HEN(
    modello_HEN,
    utilities_HEN,
    tecnologie_HEN,
    debug=False,
):
    """
    Aggiunge al modello HENS la funzione obiettivo
    TAC - Total Annualized Cost.

    TAC =

        costo hot utilities
        +
        costo cold utilities
        +
        costo fisso degli exchanger
        +
        costo proporzionale all'area

    cioè:

        TAC =
            sum_i c_HU[i] * Q_HU[i]
            +
            sum_j c_CU[j] * Q_CU[j]
            +
            sum_z,i,j,t cF[t] * U[z,i,j,t]
            +
            sum_z,i,j,t cA[t] * A[z,i,j,t]

    Le unità sono USD/year.

    Parameters
    ----------
    modello_HEN : dict
        Modello HENS contenente almeno:
        - modello
        - Q_HU
        - Q_CU
        - A
        - U
        - indici_A_U

    utilities_HEN : dict
        Output di costruisci_utilities_HEN().

    tecnologie_HEN : dict
        Output di costruisci_tecnologie_HEN().

    debug : bool
        Se True stampa i parametri economici utilizzati.

    Returns
    -------
    dict
        modello_HEN aggiornato con:
        - costo_hot_utility
        - costo_cold_utility
        - costo_fisso_HEX
        - costo_area_HEX
        - TAC
    """

    # =================================================
    # 1. MODELLO E VARIABILI
    # =================================================

    mdl = modello_HEN[
        "modello"
    ]

    Q_HU = modello_HEN[
        "Q_HU"
    ]

    Q_CU = modello_HEN[
        "Q_CU"
    ]

    A = modello_HEN[
        "A"
    ]

    U = modello_HEN[
        "U"
    ]

    indici_A_U = modello_HEN[
        "indici_A_U"
    ]


    # =================================================
    # 2. TECNOLOGIE
    # =================================================

    tecnologie = tecnologie_HEN[
        "tecnologie"
    ]


    # =================================================
    # 3. DIZIONARI DELLE UTILITIES
    # =================================================

    hot_utilities = {
        utility.codice: utility
        for utility in utilities_HEN["hot"]
    }

    cold_utilities = {
        utility.codice: utility
        for utility in utilities_HEN["cold"]
    }


    # =================================================
    # 4. CONTROLLO COSTI HOT UTILITIES
    # =================================================

    for codice in Q_HU:

        if codice not in hot_utilities:

            raise KeyError(
                f"Hot utility {codice} presente "
                "nel modello ma non in "
                "utilities_HEN."
            )

        utility = hot_utilities[
            codice
        ]

        if (
            utility.costo_USD_per_kW_year
            is None
        ):

            raise ValueError(
                f"Costo non definito per "
                f"hot utility {codice}."
            )

        if (
            utility.costo_USD_per_kW_year
            < 0
        ):

            raise ValueError(
                f"Costo negativo per "
                f"hot utility {codice}."
            )


    # =================================================
    # 5. CONTROLLO COSTI COLD UTILITIES
    # =================================================

    for codice in Q_CU:

        if codice not in cold_utilities:

            raise KeyError(
                f"Cold utility {codice} presente "
                "nel modello ma non in "
                "utilities_HEN."
            )

        utility = cold_utilities[
            codice
        ]

        if (
            utility.costo_USD_per_kW_year
            is None
        ):

            raise ValueError(
                f"Costo non definito per "
                f"cold utility {codice}."
            )

        if (
            utility.costo_USD_per_kW_year
            < 0
        ):

            raise ValueError(
                f"Costo negativo per "
                f"cold utility {codice}."
            )


    # =================================================
    # 6. COSTO HOT UTILITIES
    # =================================================
    #
    # $/(kW year) * kW
    #
    # =
    #
    # $/year
    # =================================================

    costo_hot_utility = mdl.sum(

        hot_utilities[
            codice
        ].costo_USD_per_kW_year

        * Q_HU[
            codice
        ]

        for codice in Q_HU
    )


    # =================================================
    # 7. COSTO COLD UTILITIES
    # =================================================

    costo_cold_utility = mdl.sum(

        cold_utilities[
            codice
        ].costo_USD_per_kW_year

        * Q_CU[
            codice
        ]

        for codice in Q_CU
    )


    # =================================================
    # 8. COSTO FISSO DEGLI EXCHANGER
    # =================================================
    #
    # cF[t] * U[z,i,j,t]
    #
    # U è intera e rappresenta il numero di
    # exchanger/shells installati.
    # =================================================

    costo_fisso_HEX = mdl.sum(

        tecnologie[
            t
        ].costo_fisso_USD_per_year

        * U[
            (
                z,
                i,
                j,
                t,
            )
        ]

        for (
            z,
            i,
            j,
            t,
        ) in indici_A_U
    )


    # =================================================
    # 9. COSTO DELL'AREA
    # =================================================
    #
    # cA[t] * A[z,i,j,t]
    #
    # $/(m² year) * m²
    #
    # =
    #
    # $/year
    # =================================================

    costo_area_HEX = mdl.sum(

        tecnologie[
            t
        ].costo_area_USD_per_m2_year

        * A[
            (
                z,
                i,
                j,
                t,
            )
        ]

        for (
            z,
            i,
            j,
            t,
        ) in indici_A_U
    )


    # =================================================
    # 10. TAC
    # =================================================

    TAC = (
        costo_hot_utility
        +
        costo_cold_utility
        +
        costo_fisso_HEX
        +
        costo_area_HEX
    )


    # =================================================
    # 11. FUNZIONE OBIETTIVO
    # =================================================
    #
    # Questa chiamata sostituisce il precedente:
    #
    # mdl.minimize(0)
    #
    # =================================================

    mdl.minimize(
        TAC
    )


    # =================================================
    # 12. SALVATAGGIO
    # =================================================

    modello_HEN[
        "costo_hot_utility"
    ] = costo_hot_utility

    modello_HEN[
        "costo_cold_utility"
    ] = costo_cold_utility

    modello_HEN[
        "costo_fisso_HEX"
    ] = costo_fisso_HEX

    modello_HEN[
        "costo_area_HEX"
    ] = costo_area_HEX

    modello_HEN[
        "TAC"
    ] = TAC


    # =================================================
    # 13. DEBUG
    # =================================================

    if debug:

        print(
            "\n" + "=" * 70
        )

        print(
            "OBIETTIVO TAC HENS"
        )

        print(
            "=" * 70
        )


        print(
            "\nHOT UTILITIES"
        )

        for codice in Q_HU:

            utility = (
                hot_utilities[
                    codice
                ]
            )

            print(
                f"  {codice}: "
                f"{utility.costo_USD_per_kW_year:.2f} "
                f"$/kW/year"
            )


        print(
            "\nCOLD UTILITIES"
        )

        for codice in Q_CU:

            utility = (
                cold_utilities[
                    codice
                ]
            )

            print(
                f"  {codice}: "
                f"{utility.costo_USD_per_kW_year:.2f} "
                f"$/kW/year"
            )


        print(
            "\nTECNOLOGIE"
        )

        for t in tecnologie_HEN["T"]:

            tecnologia = (
                tecnologie[t]
            )

            print(
                f"  {t}: "
                f"cF = "
                f"{tecnologia.costo_fisso_USD_per_year:.2f} "
                f"$/year | "
                f"cA = "
                f"{tecnologia.costo_area_USD_per_m2_year:.2f} "
                f"$/m²/year"
            )


        print(
            "\nFunzione obiettivo:"
        )

        print(
            "  min TAC"
        )


    return modello_HEN

def costruisci_tecnologie_HEN(
    configurazione,
    debug=False,
):
    """
    Costruisce le tecnologie degli scambiatori HENS.

    Dal JSON legge:

        hens -> technologies

    e costruisce:

    - insieme T delle tecnologie disponibili;
    - oggetti TecnologiaHEN;
    - insieme P_t dei match consentiti
      per ciascuna tecnologia.

    Returns
    -------
    dict
        {
            "T": ["T1", ...],

            "tecnologie": {
                "T1": TecnologiaHEN(...),
                ...
            },

            "P_t": {
                "T1": {
                    ("H1", "C1"),
                    ...
                }
            }
        }
    """

    # =================================================
    # 1. LETTURA SEZIONE HENS
    # =================================================

    if "hens" not in configurazione:

        raise ValueError(
            "La configurazione non contiene "
            "la sezione 'hens'."
        )


    dati_hens = configurazione[
        "hens"
    ]


    if "technologies" not in dati_hens:

        raise ValueError(
            "La sezione 'hens' non contiene "
            "'technologies'."
        )


    dati_tecnologie = dati_hens[
        "technologies"
    ]


    if not isinstance(
        dati_tecnologie,
        list,
    ):

        raise ValueError(
            "'hens.technologies' deve essere "
            "una lista."
        )


    # =================================================
    # 2. CORRENTI DISPONIBILI
    # =================================================
    #
    # Costruiamo gli insiemi hot/cold direttamente
    # dal JSON per verificare che i match dichiarati
    # abbiano direzione fisicamente corretta.
    # =================================================

    hot_codes = set()
    cold_codes = set()


    # ---------------------------------------------
    # Process streams
    # ---------------------------------------------

    for dati_flusso in configurazione.get(
        "flussi",
        [],
    ):

        if not dati_flusso.get(
            "disponibile",
            True,
        ):
            continue

        codice = str(
            dati_flusso["codice"]
        )

        tipo = str(
            dati_flusso["tipo"]
        ).strip().lower()

        if tipo == "hot":
            hot_codes.add(
                codice
            )

        elif tipo == "cold":
            cold_codes.add(
                codice
            )


    # ---------------------------------------------
    # Utility streams
    # ---------------------------------------------

    for dati_utility in dati_hens.get(
        "utilities",
        [],
    ):

        if not dati_utility.get(
            "disponibile",
            True,
        ):
            continue

        codice = str(
            dati_utility["codice"]
        )

        tipo = str(
            dati_utility["tipo"]
        ).strip().lower()

        if tipo == "hot":
            hot_codes.add(
                codice
            )

        elif tipo == "cold":
            cold_codes.add(
                codice
            )


    # =================================================
    # 3. CONTENITORI
    # =================================================

    tecnologie = {}

    codici = set()


    # =================================================
    # 4. COSTRUZIONE TECNOLOGIE
    # =================================================

    for dati in dati_tecnologie:

        if not isinstance(
            dati,
            dict,
        ):

            raise ValueError(
                "Ogni tecnologia HENS deve "
                "essere un dizionario."
            )


        # ---------------------------------------------
        # Campi obbligatori
        # ---------------------------------------------

        campi_obbligatori = [
            "codice",
            "FHEX",
            "A_max_m2",
            "costo_fisso_USD_per_year",
            "costo_area_USD_per_m2_year",
            "matches",
        ]


        mancanti = [
            campo
            for campo in campi_obbligatori
            if campo not in dati
        ]


        if mancanti:

            raise ValueError(
                "Tecnologia HENS incompleta. "
                f"Campi mancanti: {mancanti}"
            )


        codice = str(
            dati["codice"]
        )


        # ---------------------------------------------
        # Codice duplicato
        # ---------------------------------------------

        if codice in codici:

            raise ValueError(
                f"Tecnologia HENS duplicata: "
                f"{codice}"
            )

        codici.add(
            codice
        )


        # ---------------------------------------------
        # Enabled
        # ---------------------------------------------

        enabled = bool(
            dati.get(
                "enabled",
                True,
            )
        )


        # ---------------------------------------------
        # Parametri numerici
        # ---------------------------------------------

        FHEX = float(
            dati["FHEX"]
        )

        A_max_m2 = float(
            dati["A_max_m2"]
        )

        costo_fisso = float(
            dati[
                "costo_fisso_USD_per_year"
            ]
        )

        costo_area = float(
            dati[
                "costo_area_USD_per_m2_year"
            ]
        )


        # =================================================
        # 5. CONTROLLI NUMERICI
        # =================================================

        if (
            FHEX <= 0
            or FHEX > 1
        ):

            raise ValueError(
                f"FHEX non valido per "
                f"{codice}: {FHEX}. "
                "Deve essere compreso "
                "nell'intervallo (0, 1]."
            )


        if A_max_m2 <= 0:

            raise ValueError(
                f"A_max_m2 non valido "
                f"per {codice}: "
                f"{A_max_m2}"
            )


        if costo_fisso < 0:

            raise ValueError(
                f"Costo fisso negativo "
                f"per {codice}: "
                f"{costo_fisso}"
            )


        if costo_area < 0:

            raise ValueError(
                f"Costo area negativo "
                f"per {codice}: "
                f"{costo_area}"
            )


        # =================================================
        # 6. COSTRUZIONE P_t
        # =================================================

        matches = set()


        for match in dati["matches"]:

            if (
                not isinstance(
                    match,
                    (list, tuple),
                )
                or len(match) != 2
            ):

                raise ValueError(
                    f"Match non valido in "
                    f"{codice}: {match}. "
                    "Ogni match deve essere "
                    "[hot, cold]."
                )


            i = str(
                match[0]
            )

            j = str(
                match[1]
            )


            # -----------------------------------------
            # Controllo hot stream
            # -----------------------------------------

            if i not in hot_codes:

                raise ValueError(
                    f"Match non valido per "
                    f"{codice}: ({i}, {j}). "
                    f"{i} non è una hot stream "
                    "disponibile."
                )


            # -----------------------------------------
            # Controllo cold stream
            # -----------------------------------------

            if j not in cold_codes:

                raise ValueError(
                    f"Match non valido per "
                    f"{codice}: ({i}, {j}). "
                    f"{j} non è una cold stream "
                    "disponibile."
                )


            chiave_match = (
                i,
                j,
            )


            if chiave_match in matches:

                raise ValueError(
                    f"Match duplicato in "
                    f"{codice}: "
                    f"{chiave_match}"
                )


            matches.add(
                chiave_match
            )


        # =================================================
        # 7. CREAZIONE OGGETTO
        # =================================================

        tecnologia = TecnologiaHEN(
            codice=codice,

            nome=str(
                dati.get(
                    "nome",
                    codice,
                )
            ),

            FHEX=FHEX,

            A_max_m2=A_max_m2,

            costo_fisso_USD_per_year=(
                costo_fisso
            ),

            costo_area_USD_per_m2_year=(
                costo_area
            ),

            matches=frozenset(
                matches
            ),

            enabled=enabled,
        )


        # ---------------------------------------------
        # Manteniamo solo tecnologie abilitate
        # ---------------------------------------------

        if not enabled:

            if debug:

                print(
                    f"Tecnologia {codice} "
                    "ignorata: enabled=False"
                )

            continue


        tecnologie[
            codice
        ] = tecnologia


    # =================================================
    # 8. COSTRUZIONE T E P_t
    # =================================================

    T = sorted(
        tecnologie.keys()
    )


    P_t = {
        t: set(
            tecnologie[t].matches
        )
        for t in T
    }


    # =================================================
    # 9. CONTROLLO
    # =================================================

    if not T:

        raise ValueError(
            "Nessuna tecnologia HENS "
            "abilitata."
        )


    # =================================================
    # 10. DEBUG
    # =================================================

    if debug:

        print(
            "\n" + "=" * 70
        )

        print(
            "TECNOLOGIE HENS"
        )

        print(
            "=" * 70
        )


        print(
            "\nT =",
            T,
        )


        for t in T:

            tecnologia = (
                tecnologie[t]
            )

            print(
                f"\n{t} | "
                f"{tecnologia.nome}"
            )

            print(
                f"  FHEX = "
                f"{tecnologia.FHEX:.3f}"
            )

            print(
                f"  A_max = "
                f"{tecnologia.A_max_m2:.2f} m²"
            )

            print(
                f"  costo fisso = "
                f"{tecnologia.costo_fisso_USD_per_year:.2f} "
                f"$/year"
            )

            print(
                f"  costo area = "
                f"{tecnologia.costo_area_USD_per_m2_year:.2f} "
                f"$/m²/year"
            )

            print(
                "  P_t ="
            )

            for match in sorted(
                P_t[t]
            ):

                print(
                    f"    {match}"
                )


    # =================================================
    # 11. OUTPUT
    # =================================================

    return {

        "T":
            T,

        "tecnologie":
            tecnologie,

        "P_t":
            P_t,
    }
