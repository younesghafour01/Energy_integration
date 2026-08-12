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
    virtuale: bool = False


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
    virtuale: bool = False


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
            raise ValueError(f"Tipo non valido per il flusso " f"{codice}: {tipo}")

        self.codice = codice
        self.nome = nome
        self.tipo = tipo

        self.T_in = float(T_in)
        self.T_out = float(T_out)

        self.heat_load_kW = None if heat_load_kW is None else float(heat_load_kW)

        self.delta_T_min_half = (
            None if delta_T_min_half is None else float(delta_T_min_half)
        )

        # COEFFICIENTE DI SCAMBIO PER HENS

        self.h_W_m2K = None if h_W_m2K is None else float(h_W_m2K)

        if self.h_W_m2K is not None and self.h_W_m2K <= 0:
            raise ValueError(f"h_W_m2K non valido per " f"{codice}: {self.h_W_m2K}")

        # FLUSSO ISOTERMO

        self.isotermo = (
            abs(self.T_in - self.T_out) <= 1e-12 if isotermo is None else bool(isotermo)
        )

        self.processo = processo
        self.zona = zona
        self.disponibile = bool(disponibile)
        self.remark = remark
        self.unit = unit

        # CALCOLO CP

        if self.isotermo:

            if self.heat_load_kW is None:
                raise ValueError(
                    f"Il flusso isotermo " f"{codice} richiede " f"heat_load_kW."
                )

            self.CP = None if CP is None else float(CP)

        elif CP is not None:

            self.CP = float(CP)

        elif self.heat_load_kW is not None:

            self.CP = self.heat_load_kW / abs(self.T_out - self.T_in)

        else:

            raise ValueError(
                f"Il flusso {codice} " f"richiede CP oppure " f"heat_load_kW."
            )

    def calcola_Q(self):

        if self.heat_load_kW is not None:
            return self.heat_load_kW

        return self.CP * abs(self.T_in - self.T_out)

    def calcola_T_traslate(
        self,
        delta_T_min,
    ):

        delta_half = (
            self.delta_T_min_half
            if self.delta_T_min_half is not None
            else delta_T_min / 2
        )

        traslazione = -delta_half if self.tipo == "hot" else delta_half

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

    configurazione["flussi_oggetti"] = [
        Flusso(**dati_flusso) for dati_flusso in configurazione["flussi"]
    ]

    return configurazione


def crea_cascata_termica(flussi, delta_T_min, tolleranza=1e-9):
    """Crea la cascata termica includendo i carichi termici isotermi."""

    flussi_attivi = [flusso for flusso in flussi if flusso.disponibile]

    # Traslazione delle temperature e individuazione dei carichi isotermi
    flussi_traslati = []
    temperature = []
    carichi_isotermi = {}

    for flusso in flussi_attivi:

        T_in_star, T_out_star = flusso.calcola_T_traslate(delta_T_min)

        flussi_traslati.append((flusso, T_in_star, T_out_star))

        temperature.extend(
            [
                T_in_star,
                T_out_star,
            ]
        )

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

            risultati.append(
                {
                    "T_sup": T_sup,
                    "T_inf": T_sup,
                    "CP_hot": 0.0,
                    "CP_cold": 0.0,
                    "delta_H_hot": Q_hot,
                    "delta_H_cold": Q_cold,
                    "delta_H": delta_H,
                    "cascata_provvisoria": cascata_provvisoria,
                }
            )

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

        risultati.append(
            {
                "T_sup": T_sup,
                "T_inf": T_inf,
                "CP_hot": CP_hot,
                "CP_cold": CP_cold,
                "delta_H_hot": Q_hot,
                "delta_H_cold": Q_cold,
                "delta_H": delta_H,
                "cascata_provvisoria": cascata_provvisoria,
            }
        )

    # Minimum Energy Requirements
    valori_cascata = [
        0.0,
        *[riga["cascata_provvisoria"] for riga in risultati],
    ]

    QH_min = max(
        0.0,
        -min(valori_cascata),
    )

    # Cascata termica finale
    for riga in risultati:
        riga["cascata_finale"] = riga["cascata_provvisoria"] + QH_min

    QC_min = risultati[-1]["cascata_finale"]

    # Temperature traslate dei pinch point
    pinch_traslati = []

    if abs(QH_min) <= tolleranza:
        pinch_traslati.append(livelli[0])

    for riga in risultati:

        if abs(riga["cascata_finale"]) <= tolleranza:
            pinch_traslati.append(riga["T_inf"])

    pinch_traslati = list(dict.fromkeys(pinch_traslati))

    return (
        risultati,
        QH_min,
        QC_min,
        pinch_traslati,
    )


def costruisci_curve_composite(
    risultati,
    QC_min,
    tolleranza=1e-9,
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
            if riga[chiave_CP] > tolleranza or riga[chiave_delta_H] > tolleranza
        ]

        elementi = list(reversed(risultati[indici_attivi[0] : indici_attivi[-1] + 1]))

        Q = Q_iniziale

        punti = [(Q, elementi[0]["T_inf"])]

        for riga in elementi:

            Q += riga[chiave_delta_H]

            punti.append((Q, riga["T_sup"]))

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
                "potential_pinch_point",
                i,
                posizione,
            )
        )

    pockets = []
    indice_pinch = indici_mpp[0]
    punti_sopra = gcc[: indice_pinch + 1]
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
                pockets.append(
                    {
                        "zona": nome_zona,
                        "Q_riferimento_kW": Q_inizio,
                        "T_inizio_traslata_C": T_inizio,
                        "T_fine_traslata_C": T_fine,
                        "punti_gcc": punti_zona[i:i_fine] + [(Q_inizio, T_fine)],
                    }
                )
                break

    return {
        "main_pinch_points": main_pinch_points,
        "potential_pinch_points": potential_pinch_points,
        "pockets": pockets,
    }


def discretizza_GCC(gcc, punti_pinch, delta_T_max, tolleranza=1e-9):
    limiti = sorted(
        {
            0,
            len(gcc) - 1,
            *[
                punto["indice_gcc"]
                for tipo in ("main_pinch_points", "potential_pinch_points")
                for punto in punti_pinch[tipo]
            ],
        }
    )
    zone_discretizzate = []
    for inizio, fine in zip(limiti, limiti[1:]):
        zona = gcc[inizio : fine + 1]
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
    zone_GCC,
    eta_ex,
    EvaP,
    CondP,
    T_cond_max=None,
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
                    candidate.append(
                        {
                            "y": y + 1,
                            "j": j,
                            "z": z + 1,
                            "k": k,
                            "Qy_kW": Qy,
                            "Qz_kW": Qz,
                            "T_yj_C": Ty_C,
                            "T_zk_C": Tz_C,
                            "T_evap_C": T_evap_K - 273.15,
                            "T_cond_C": T_cond_K - 273.15,
                            "COP": COP,
                        }
                    )
    return candidate


def genera_candidate_utilities(
    zone_GCC,
    utilities,
    eta_ex,
    EvaP,
    CondP,
    T0,
    T_f,
    T_cond_max=None,
):
    """Precalcola [1.4]-[1.8] solo per le tecnologie abilitate."""
    nomi = ("HPPr", "HPUt", "chiller", "ORC", "CHP")
    candidati = {nome: [] for nome in nomi}
    zone_milp = converti_zone_milp(zone_GCC)
    Z = len(zone_milp)

    if utilities["HPPr"]["enabled"]:
        candidati["HPPr"] = genera_HPPr_candidate(
            zone_GCC,
            eta_ex,
            EvaP,
            CondP,
            T_cond_max,
        )

    # [1.31]-[1.35]: i filtri di temperatura evitano variabili inammissibili.
    for z, zona in enumerate(zone_milp, start=1):
        for k, (Q, T_C) in enumerate(zona, start=1):
            T_K = T_C + 273.15

            if utilities["HPUt"]["enabled"]:
                ammessa = (
                    z > 1 and T_K >= T0 and (T_cond_max is None or T_K <= T_cond_max)
                )
                denominatore = (T_K + CondP) - (T0 - EvaP)
                if ammessa and denominatore > 0:
                    COP = eta_ex * (T_K + CondP) / denominatore
                    if COP > 1:
                        candidati["HPUt"].append(
                            {
                                "z": z,
                                "k": k,
                                "Q_kW": Q,
                                "T_zk_C": T_C,
                                "T_evap_C": T0 - EvaP - 273.15,
                                "T_cond_C": T_K + CondP - 273.15,
                                "COP": COP,
                            }
                        )

            if utilities["chiller"]["enabled"] and z < Z and T_K <= T0:
                denominatore = (T0 + CondP) - (T_K - EvaP)
                if denominatore > 0:
                    COP = eta_ex * (T0 + CondP) / denominatore
                    if COP > 1:
                        candidati["chiller"].append(
                            {
                                "z": z,
                                "k": k,
                                "Q_kW": Q,
                                "T_zk_C": T_C,
                                "T_evap_C": T_K - EvaP - 273.15,
                                "T_cond_C": T0 + CondP - 273.15,
                                "COP": COP,
                            }
                        )

            if utilities["ORC"]["enabled"] and z < Z and T_K >= T0:
                T_hot = T_K - CondP
                T_cold = T0 + EvaP
                efficienza = eta_ex * (1 - T_cold / T_hot)
                if 0 < efficienza < 1:
                    candidati["ORC"].append(
                        {
                            "z": z,
                            "k": k,
                            "Q_kW": Q,
                            "T_zk_C": T_C,
                            "T_hot_C": T_hot - 273.15,
                            "T_reject_C": T_cold - 273.15,
                            "efficienza": efficienza,
                        }
                    )

            if utilities["CHP"]["enabled"] and z == Z:
                efficienza = eta_ex * (1 - (T_K + EvaP) / (T_f - CondP))
                if 0 < efficienza < 1:
                    candidati["CHP"].append(
                        {
                            "k": k,
                            "Q_kW": Q,
                            "T_zk_C": T_C,
                            "T_fiamma_C": T_f - CondP - 273.15,
                            "efficienza": efficienza,
                        }
                    )
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
    candidati,
    zone_GCC,
    utilities,
    T0,
    T_f,
    eta_ex,
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
        "HPPr": {(c["y"], c["j"], c["z"], c["k"]): c for c in candidati["HPPr"]},
        "HPUt": {(c["z"], c["k"]): c for c in candidati["HPUt"]},
        "chiller": {(c["z"], c["k"]): c for c in candidati["chiller"]},
        "ORC": {(c["z"], c["k"]): c for c in candidati["ORC"]},
        "CHP": {c["k"]: c for c in candidati["CHP"]},
    }

    # [1.9]-[1.13] - variabili Bool/F create solo se abilitate.
    BoolHPPr = modello.binary_var_dict(mappe["HPPr"], name="BoolHPPr")
    FHPPr = modello.continuous_var_dict(
        mappe["HPPr"],
        lb=0,
        ub=1,
        name="FHPPr",
    )
    BoolHPUt = modello.binary_var_dict(mappe["HPUt"], name="BoolHPUt")
    FHPUt = modello.continuous_var_dict(
        mappe["HPUt"],
        lb=0,
        ub=1,
        name="FHPUt",
    )
    BoolRef = modello.binary_var_dict(mappe["chiller"], name="BoolRef")
    FRef = modello.continuous_var_dict(
        mappe["chiller"],
        lb=0,
        ub=1,
        name="FRef",
    )
    BoolORC = modello.binary_var_dict(mappe["ORC"], name="BoolORC")
    FORC = modello.continuous_var_dict(
        mappe["ORC"],
        lb=0,
        ub=1,
        name="FORC",
    )
    BoolChp = modello.binary_var_dict(mappe["CHP"], name="BoolChp")
    FChp = modello.continuous_var_dict(
        mappe["CHP"],
        lb=0,
        ub=1,
        name="FChp",
    )

    coppie = (
        (FHPPr, BoolHPPr),
        (FHPUt, BoolHPUt),
        (FRef, BoolRef),
        (FORC, BoolORC),
        (FChp, BoolChp),
    )
    for frazioni, booleane in coppie:
        for indice in frazioni:
            modello.add_constraint(frazioni[indice] <= booleane[indice])

    # [1.14]-[1.17] - limiti per tecnologia e limite HP condiviso.
    if BoolChp:
        modello.add_constraint(modello.sum(BoolChp.values()) <= utilities["CHP"]["max"])
    if BoolRef:
        modello.add_constraint(
            modello.sum(BoolRef.values()) <= utilities["chiller"]["max"]
        )
    if BoolORC:
        modello.add_constraint(modello.sum(BoolORC.values()) <= utilities["ORC"]["max"])
    if BoolHPPr:
        modello.add_constraint(
            modello.sum(BoolHPPr.values()) <= utilities["HPPr"]["max"]
        )
    if BoolHPUt:
        modello.add_constraint(
            modello.sum(BoolHPUt.values()) <= utilities["HPUt"]["max"]
        )
    if BoolHPPr or BoolHPUt:
        modello.add_constraint(
            modello.sum(BoolHPPr.values()) + modello.sum(BoolHPUt.values())
            <= utilities["HP_max"]
        )

    variabili = {
        "BoolHPPr": BoolHPPr,
        "FHPPr": FHPPr,
        "BoolHPUt": BoolHPUt,
        "FHPUt": FHPUt,
        "BoolRef": BoolRef,
        "FRef": FRef,
        "BoolORC": BoolORC,
        "FORC": FORC,
        "BoolChp": BoolChp,
        "FChp": FChp,
    }

    # [1.18]-[1.19] - calore prelevato.
    Pprel = modello.continuous_var_dict(indici_GCC, lb=0, name="Pprel")
    for y, j in indici_GCC:
        if y == Z:
            modello.add_constraint(Pprel[y, j] == 0)
            continue
        termini = [
            FHPPr[indice] for indice in FHPPr if indice[0] == y and indice[1] == j
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
                Papp[y, i] - Pprel[y, i] for i in range(j, S_y + 1)
            )
            effetto_zone_superiori = modello.sum(
                Papp[z, k] - Pprel[z, k]
                for z in range(y + 1, Z)
                for k in range(1, len(zone_milp[z - 1]) + 1)
            )
            modello.add_constraint(
                NHL[y, j] == Q_GCC[y, j] + effetto_stessa_zona + effetto_zone_superiori
            )
    S_Z = len(zone_milp[Z - 1])
    for j in range(1, S_Z + 1):
        modello.add_constraint(
            NHL[Z, j] == Q_GCC[Z, j] - modello.sum(Papp[Z, i] for i in range(1, j + 1))
        )

    # [1.26]-[1.28] - consumi elettrici.
    Pelec = modello.continuous_var_dict(indici_GCC, lb=0, name="Pelec")
    for y, j in indici_GCC:
        termini = []
        if y < Z:
            termini.extend(
                FHPPr[indice] * Q_GCC[y, j] / (mappe["HPPr"][indice]["COP"] - 1)
                for indice in FHPPr
                if indice[0] == y and indice[1] == j
            )
            if (y, j) in FRef:
                termini.append(
                    FRef[y, j] * Q_GCC[y, j] / (mappe["chiller"][y, j]["COP"] - 1)
                )
        if (y, j) in FHPUt:
            termini.append(FHPUt[y, j] * Q_GCC[y, j] / mappe["HPUt"][y, j]["COP"])
        modello.add_constraint(Pelec[y, j] == modello.sum(termini))

    TEC = modello.continuous_var(lb=0, name="TEC")
    modello.add_constraint(TEC == modello.sum(Pelec[indice] for indice in indici_GCC))

    # [1.29]-[1.30] - produzione elettrica e fuel heat load CHP.
    TEP = modello.continuous_var(lb=0, name="TEP")
    produzione_ORC = modello.sum(
        FORC[indice] * Q_GCC[indice] * candidato["efficienza"]
        for indice, candidato in mappe["ORC"].items()
    )
    produzione_CHP = modello.sum(
        FChp[k] * Q_GCC[Z, k] * candidato["efficienza"] / (1 - candidato["efficienza"])
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
    fattore_cold = 0.0 if T_cold_MER >= T0 else eta_ex * T_cold_MER / (T0 - T_cold_MER)
    fattore_hot = (T_f - T0) / T_f
    FinalExergy = modello.continuous_var(lb=-modello.infinity, name="FinalExergy")
    modello.add_constraint(
        FinalExergy
        == NHL[1, 1] * fattore_cold + (NHL[Z, S_Z] + PprelCHP) * fattore_hot + TEC - TEP
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
        HPPr_selezionate.append(
            {
                "tipo": "HPPr",
                "indice": indice,
                "BoolHPPr": soluzione.get_value(v["BoolHPPr"][indice]),
                "FHPPr": frazione,
                "y": indice[0],
                "j": indice[1],
                "z": indice[2],
                "k": indice[3],
                "T_yj_C": hp["T_yj_C"],
                "T_zk_C": hp["T_zk_C"],
                "T_evap_C": hp["T_evap_C"],
                "T_cond_C": hp["T_cond_C"],
                "heat_load_kW": Q_cond,
                "Q_evap_kW": Q_evap,
                "Q_cond_kW": Q_cond,
                "COP": COP,
                "P_elettrica_kW": Q_evap / (COP - 1),
            }
        )

    HPUt_selezionate = []
    for indice, hp in mappe["HPUt"].items():
        frazione = soluzione.get_value(v["FHPUt"][indice])
        if frazione <= tolleranza:
            continue
        Q_cond = frazione * hp["Q_kW"]
        W = Q_cond / hp["COP"]
        HPUt_selezionate.append(
            {
                "tipo": "HPUt",
                "indice": indice,
                "BoolHPUt": soluzione.get_value(v["BoolHPUt"][indice]),
                "FHPUt": frazione,
                "z": indice[0],
                "k": indice[1],
                "T_evap_C": hp["T_evap_C"],
                "T_cond_C": hp["T_cond_C"],
                "heat_load_kW": Q_cond,
                "Q_evap_kW": Q_cond - W,
                "Q_cond_kW": Q_cond,
                "COP": hp["COP"],
                "P_elettrica_kW": W,
            }
        )

    chiller_selezionati = []
    for indice, ref in mappe["chiller"].items():
        frazione = soluzione.get_value(v["FRef"][indice])
        if frazione <= tolleranza:
            continue
        Q_evap = frazione * ref["Q_kW"]
        W = Q_evap / (ref["COP"] - 1)
        chiller_selezionati.append(
            {
                "tipo": "chiller",
                "indice": indice,
                "BoolRef": soluzione.get_value(v["BoolRef"][indice]),
                "FRef": frazione,
                "z": indice[0],
                "k": indice[1],
                "T_evap_C": ref["T_evap_C"],
                "T_cond_C": ref["T_cond_C"],
                "heat_load_kW": Q_evap,
                "Q_evap_kW": Q_evap,
                "Q_cond_kW": Q_evap + W,
                "COP": ref["COP"],
                "P_elettrica_kW": W,
            }
        )

    ORC_selezionati = []
    for indice, orc in mappe["ORC"].items():
        frazione = soluzione.get_value(v["FORC"][indice])
        if frazione <= tolleranza:
            continue
        Q_assorbito = frazione * orc["Q_kW"]
        P_elettrica = Q_assorbito * orc["efficienza"]
        ORC_selezionati.append(
            {
                "tipo": "ORC",
                "indice": indice,
                "BoolORC": soluzione.get_value(v["BoolORC"][indice]),
                "FORC": frazione,
                "z": indice[0],
                "k": indice[1],
                "T_hot_C": orc["T_hot_C"],
                "T_reject_C": orc["T_reject_C"],
                "heat_load_kW": Q_assorbito,
                "efficienza": orc["efficienza"],
                "P_elettrica_prodotta_kW": P_elettrica,
                "Q_scarto_kW": Q_assorbito - P_elettrica,
            }
        )

    CHP_selezionati = []
    for k, chp in mappe["CHP"].items():
        frazione = soluzione.get_value(v["FChp"][k])
        if frazione <= tolleranza:
            continue
        Q_process = frazione * Q_GCC[Z, k]
        fuel = Q_process / (1 - chp["efficienza"])
        CHP_selezionati.append(
            {
                "tipo": "CHP",
                "indice": k,
                "BoolChp": soluzione.get_value(v["BoolChp"][k]),
                "FChp": frazione,
                "k": k,
                "T_processo_C": chp["T_zk_C"],
                "T_fiamma_C": chp["T_fiamma_C"],
                "heat_load_kW": Q_process,
                "efficienza": chp["efficienza"],
                "PprelCHP_kW": fuel,
                "P_elettrica_prodotta_kW": fuel * chp["efficienza"],
            }
        )

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

    risultati_cascata, QH_min, QC_min, pinch_traslati = crea_cascata_termica(
        flussi,
        delta_T_min,
    )

    hot_CC_star, cold_CC_star = costruisci_curve_composite(
        risultati_cascata,
        QC_min,
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

            Q = soluzione.get_value(NHL[z, k])

            punti.append((Q, T))

    return punti


def grafico_TQ(
    tipo_grafico,
    hot_CC=None,
    cold_CC=None,
    gcc=None,
    utility_curve=None,
    pockets=None,
    pinch_data=None,
    percorso_salvataggio=None,
    mostra=True,
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
                Q_pocket,
                T_pocket,
                linewidth=1.7,
                label=f"Pocket {indice}: {pocket['zona']}",
            )
        if pinch_data is not None:
            mpp = pinch_data["main_pinch_points"]
            ppp = pinch_data["potential_pinch_points"]
            if mpp:
                ax.scatter(
                    [p["Q_kW"] for p in mpp],
                    [p["T_traslata_C"] for p in mpp],
                    marker="s",
                    s=50,
                    label="MPP",
                    color="black",
                )
            if ppp:
                ax.scatter(
                    [p["Q_kW"] for p in ppp],
                    [p["T_traslata_C"] for p in ppp],
                    marker="D",
                    s=40,
                    label="PPP",
                    color="red",
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

    curva_utilities = costruisci_curva_utilities(risultati_milp)

    # Composite Curves
    grafico_TQ(
        "composite_traslate",
        hot_CC=dati_pinch["hot_CC_traslata"],
        cold_CC=dati_pinch["cold_CC_traslata"],
        percorso_salvataggio=(cartella / "composite_curves_traslate.png"),
        mostra=False,
    )

    # GCC iniziale
    grafico_TQ(
        "gcc",
        gcc=dati_pinch["gcc"],
        percorso_salvataggio=(cartella / "grand_composite_curve.png"),
        mostra=False,
    )

    # Self-sufficient pockets
    grafico_TQ(
        "pockets",
        gcc=dati_pinch["gcc"],
        pockets=dati_pinch["pinch_data"]["pockets"],
        pinch_data=dati_pinch["pinch_data"],
        percorso_salvataggio=(cartella / "self_sufficient_pockets.png"),
        mostra=False,
    )

    # GCC aggiornata
    grafico_TQ(
        "gcc_aggiornata",
        gcc=risultati_milp["gcc_aggiornata"],
        percorso_salvataggio=(cartella / "grand_composite_curve_aggiornata.png"),
        mostra=False,
    )

    # Integrated Composite Curve
    grafico_TQ(
        "icc",
        gcc=dati_pinch["gcc"],
        utility_curve=curva_utilities,
        percorso_salvataggio=(cartella / "integrated_composite_curve.png"),
        mostra=False,
    )


# PREPROCESSING DELLA HEN


def costruisci_flussi_flessibili_HEN(configurazione):
    """Valida e indicizza le flexible streams dichiarate nel JSON.

    Il flusso nominale rappresenta la corrente completa: ``T_out`` coincide
    con ``T_out_min_C`` per una hot stream e con ``T_out_max_C`` per una cold
    stream. Il tratto tra i due limiti e la surplus part.
    """

    processi = {
        flusso.codice: flusso
        for flusso in configurazione["flussi_oggetti"]
        if flusso.disponibile
    }
    codici_utility = {
        str(dati["codice"])
        for dati in configurazione.get("hens", {}).get("utilities", [])
    }
    flessibili = {}

    for dati in configurazione.get("hens", {}).get("flexible_streams", []):
        if not dati.get("enabled", True):
            continue

        codice = str(dati["codice"])
        if codice in codici_utility:
            raise ValueError(f"Una utility non puo essere flexible: {codice}.")
        if codice not in processi:
            raise ValueError(
                f"Flexible stream non trovata tra i flussi di processo: {codice}."
            )
        if codice in flessibili:
            raise ValueError(f"Flexible stream duplicata: {codice}.")

        corrente = processi[codice]
        T_min = float(dati["T_out_min_C"])
        T_max = float(dati["T_out_max_C"])
        if T_min >= T_max:
            raise ValueError(f"Per {codice} deve valere T_out_min_C < T_out_max_C.")

        if corrente.tipo == "hot":
            coerente = corrente.T_in > T_max and abs(corrente.T_out - T_min) <= 1e-9
        else:
            coerente = corrente.T_in < T_min and abs(corrente.T_out - T_max) <= 1e-9
        if not coerente:
            raise ValueError(
                f"Range di uscita non coerente con il verso e i dati di {codice}."
            )

        flessibili[codice] = {
            "codice": codice,
            "tipo": corrente.tipo,
            "T_out_min_C": T_min,
            "T_out_max_C": T_max,
            "CP_kW_K": corrente.CP,
            "corrente": corrente,
        }

    return flessibili


def costruisci_utilities_virtuali_HEN(
    intervalli,
    flussi_flessibili,
    flussi,
    delta_T_min,
    delta_T_partition_max,
):
    """Crea le utility virtuali [1.48]-[1.49] con un solo passaggio aggiuntivo.

    Gli estremi sono ricavati da una partizione preliminare priva di utility
    virtuali. Le temperature della cold utility vengono memorizzate sulla
    scala reale; la traslazione ``+delta_T_min`` le riporta ai valori di
    [1.49] sulla scala HENS.

    ``h_default`` e il massimo coefficiente di film tra tutte le process
    streams disponibili. E una convenzione puramente numerica: la tecnologia
    virtuale ha costo nullo e non condivide match fisici.

    La costruzione con una coppia VHU/VCU e stata verificata sui benchmark
    HENS economici a zona unica; non modella utility virtuali distinte per zona.
    """

    if not flussi_flessibili:
        return {"hot": [], "cold": []}

    T_sup = max(T_U for zona in intervalli.values() for T_U, _ in zona)
    T_inf = min(T_L for zona in intervalli.values() for _, T_L in zona)
    estensione = 1.5 * float(delta_T_partition_max)
    h_default = max(
        float(f.h_W_m2K) for f in flussi if f.h_W_m2K is not None and f.disponibile
    )
    virtuali = {"hot": [], "cold": []}

    if any(dati["tipo"] == "cold" for dati in flussi_flessibili.values()):
        virtuali["hot"].append(
            UtilityHEN(
                codice="VHU",
                nome="Virtual hot utility",
                tipo="hot",
                T_in=T_sup + estensione,
                T_out=T_sup,
                h_W_m2K=h_default,
                costo_USD_per_kW_year=0.0,
                virtuale=True,
            )
        )

    if any(dati["tipo"] == "hot" for dati in flussi_flessibili.values()):
        T_out_reale = T_inf - delta_T_min
        virtuali["cold"].append(
            UtilityHEN(
                codice="VCU",
                nome="Virtual cold utility",
                tipo="cold",
                T_in=T_out_reale - estensione,
                T_out=T_out_reale,
                h_W_m2K=h_default,
                costo_USD_per_kW_year=0.0,
                virtuale=True,
            )
        )

    return virtuali


def aggiungi_tecnologia_virtuale_HEN(
    tecnologie_HEN,
    utilities_HEN,
    flussi_flessibili,
):
    """Aggiunge la tecnologia HEX virtuale esclusivamente ai match virtuali."""

    VHU = [u.codice for u in utilities_HEN["hot"] if u.virtuale]
    VCU = [u.codice for u in utilities_HEN["cold"] if u.virtuale]
    matches = {
        (vhu, codice)
        for vhu in VHU
        for codice, dati in flussi_flessibili.items()
        if dati["tipo"] == "cold"
    } | {
        (codice, vcu)
        for vcu in VCU
        for codice, dati in flussi_flessibili.items()
        if dati["tipo"] == "hot"
    }
    if not matches:
        return tecnologie_HEN

    codice = "TVIRTUAL"
    if codice in tecnologie_HEN["tecnologie"]:
        raise ValueError(f"Codice tecnologia riservato gia utilizzato: {codice}.")

    # U e intera ma non limitata: A_max e solo l'area di una shell virtuale.
    # Si riusa il maggiore A_max dichiarato dal designer, senza magic number.
    A_max = max(t.A_max_m2 for t in tecnologie_HEN["tecnologie"].values())
    tecnologia = TecnologiaHEN(
        codice=codice,
        nome="Virtual heat exchanger technology",
        FHEX=1.0,
        A_max_m2=A_max,
        costo_fisso_USD_per_year=0.0,
        costo_area_USD_per_m2_year=0.0,
        matches=frozenset(matches),
        virtuale=True,
    )
    tecnologie_HEN["T"].append(codice)
    tecnologie_HEN["tecnologie"][codice] = tecnologia
    tecnologie_HEN["P_t"][codice] = set(matches)
    return tecnologie_HEN


def costruisci_insiemi_HEN(
    flussi,
    utilities,
    intervalli,
    delta_T_min,
    match_permessi=None,
    NI_H=None,
    NI_C=None,
    flexible_streams=None,
):
    """Costruisce gli insiemi HENS, inclusi HF, CF, MF e NF.

    Le cold streams sono rappresentate a temperatura reale + delta_T_min."""
    processi = [flusso for flusso in flussi if flusso.disponibile]
    hot_utilities = utilities.get("hot", [])
    cold_utilities = utilities.get("cold", [])
    correnti = processi + hot_utilities + cold_utilities
    correnti_per_codice = {flusso.codice: flusso for flusso in correnti}
    Z = list(intervalli.keys())
    M = {z: list(range(1, len(intervalli[z]) + 1)) for z in Z}
    T_intervallo = {
        (z, m): {"T_sup": T_sup, "T_inf": T_inf}
        for z in Z
        for m, (T_sup, T_inf) in enumerate(intervalli[z], start=1)
    }

    def temperature_HEN(flusso):
        if flusso.tipo == "hot":
            return (flusso.T_in, flusso.T_out)
        return (flusso.T_in + delta_T_min, flusso.T_out + delta_T_min)

    def presente(flusso, T_sup, T_inf):
        T1, T2 = temperature_HEN(flusso)
        T_max = max(T1, T2)
        T_min = min(T1, T2)
        return T_max >= T_sup and T_min <= T_inf

    H_m = {}
    C_n = {}
    for z in Z:
        for m in M[z]:
            T_sup, T_inf = intervalli[z][m - 1]
            H_m[z, m] = [
                flusso.codice
                for flusso in correnti
                if flusso.tipo == "hot" and presente(flusso, T_sup, T_inf)
            ]
            C_n[z, m] = [
                flusso.codice
                for flusso in correnti
                if flusso.tipo == "cold" and presente(flusso, T_sup, T_inf)
            ]
    H = {z: sorted({i for m in M[z] for i in H_m[z, m]}) for z in Z}
    C = {z: sorted({j for m in M[z] for j in C_n[z, m]}) for z in Z}
    codici_HU = {utility.codice for utility in hot_utilities}
    codici_CU = {utility.codice for utility in cold_utilities}
    HU = {z: [i for i in H[z] if i in codici_HU] for z in Z}
    CU = {z: [j for j in C[z] if j in codici_CU] for z in Z}
    virtual_hot_codes = {
        utility.codice
        for utility in hot_utilities
        if getattr(utility, "virtuale", False)
    }
    virtual_cold_codes = {
        utility.codice
        for utility in cold_utilities
        if getattr(utility, "virtuale", False)
    }
    VHU = {z: [i for i in HU[z] if i in virtual_hot_codes] for z in Z}
    VCU = {z: [j for j in CU[z] if j in virtual_cold_codes] for z in Z}
    flexible_streams = flexible_streams or {}
    HF = {
        z: [
            i
            for i in H[z]
            if i in flexible_streams and flexible_streams[i]["tipo"] == "hot"
        ]
        for z in Z
    }
    CF = {
        z: [
            j
            for j in C[z]
            if j in flexible_streams and flexible_streams[j]["tipo"] == "cold"
        ]
        for z in Z
    }
    M_i = {(z, i): [m for m in M[z] if i in H_m[z, m]] for z in Z for i in H[z]}
    N_j = {(z, j): [n for n in M[z] if j in C_n[z, n]] for z in Z for j in C[z]}

    def intervalli_surplus(z, codice, indici):
        dati = flexible_streams[codice]
        shift = delta_T_min if dati["tipo"] == "cold" else 0.0
        T_min = dati["T_out_min_C"] + shift
        T_max = dati["T_out_max_C"] + shift
        return [
            indice
            for indice in indici
            if T_intervallo[z, indice]["T_sup"] <= T_max + 1e-09
            and T_intervallo[z, indice]["T_inf"] >= T_min - 1e-09
        ]

    MF = {(z, i): intervalli_surplus(z, i, M_i[z, i]) for z in Z for i in HF[z]}
    NF = {(z, j): intervalli_surplus(z, j, N_j[z, j]) for z in Z for j in CF[z]}
    if match_permessi is None:
        P = {
            (i, j)
            for z in Z
            for i in H[z]
            for j in C[z]
            if not (i in HU[z] and j in CU[z])
        }
    else:
        P = {
            (i, j)
            for i, j in match_permessi
            if not any((i in HU[z] and j in CU[z] for z in Z))
        }
    P_H = {
        (z, i, m): [j for j in C[z] if (i, j) in P]
        for z in Z
        for i in H[z]
        for m in M_i[z, i]
    }
    P_C = {
        (z, j, n): [i for i in H[z] if (i, j) in P]
        for z in Z
        for j in C[z]
        for n in N_j[z, j]
    }
    NI_H = set() if NI_H is None else set(NI_H)
    NI_C = set() if NI_C is None else set(NI_C)
    return {
        "Z": Z,
        "H": H,
        "C": C,
        "HU": HU,
        "CU": CU,
        "VHU": VHU,
        "VCU": VCU,
        "HF": HF,
        "CF": CF,
        "MF": MF,
        "NF": NF,
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
        "flexible_streams": flexible_streams,
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
    flexible_streams=None,
):
    """Costruisce la partizione HENS sulla scala hot reale/cold traslata.

    Include estremi GCC, correnti, utility e flexible streams; applica il passo
    massimo, gli intervalli interni minimi e, se richiesto, la separazione al pinch."""
    tolleranza = 1e-09
    if type(separa_al_pinch) is not bool:
        raise ValueError("separa_al_pinch deve essere True oppure False.")
    if len(gcc) < 2:
        raise ValueError("La GCC deve contenere almeno due punti.")
    if delta_T_partition_max <= 0:
        raise ValueError("delta_T_partition_max deve essere > 0.")
    if numero_intervalli_min < 1:
        raise ValueError("numero_intervalli_min deve essere >= 1.")
    if utilities is None:
        utilities = {"hot": [], "cold": []}
    utilities_hot = utilities.get("hot", [])
    utilities_cold = utilities.get("cold", [])
    flexible_streams = flexible_streams or {}
    correnti_partizione = list(flussi) + list(utilities_hot) + list(utilities_cold)

    def temperature_corrente_HEN(corrente):
        """
        Restituisce T_in e T_out sulla scala HENS.

        Hot:
            nessuna traslazione

        Cold:
            + delta_T_min
        """
        if corrente.tipo == "hot":
            return (float(corrente.T_in), float(corrente.T_out))
        elif corrente.tipo == "cold":
            return (
                float(corrente.T_in) + delta_T_min,
                float(corrente.T_out) + delta_T_min,
            )
        else:
            raise ValueError(
                f"Tipo corrente non riconosciuto per {corrente.codice}: {corrente.tipo}"
            )

    def corrente_disponibile(corrente):
        return getattr(corrente, "disponibile", True)

    vertici = [gcc[0]]
    for p1, p2, p3 in zip(gcc, gcc[1:], gcc[2:]):
        Q1, T1 = p1
        Q2, T2 = p2
        Q3, T3 = p3
        lhs = (Q2 - Q1) * (T3 - T2)
        rhs = (T2 - T1) * (Q3 - Q2)
        cambio_pendenza = abs(lhs - rhs) > tolleranza
        if cambio_pendenza:
            vertici.append(p2)
    vertici.append(gcc[-1])
    temperature_gcc = [T_star + delta_T_min / 2 for _, T_star in vertici]
    pinch_HEN = [T_star + delta_T_min / 2 for T_star in pinch_traslati]
    temperature_correnti = []
    for corrente in correnti_partizione:
        if not corrente_disponibile(corrente):
            continue
        T1, T2 = temperature_corrente_HEN(corrente)
        temperature_correnti.extend([T1, T2])
    for dati in flexible_streams.values():
        shift = delta_T_min if dati["tipo"] == "cold" else 0.0
        temperature_correnti.extend(
            [dati["T_out_min_C"] + shift, dati["T_out_max_C"] + shift]
        )
    temperature_base = list(temperature_gcc) + list(temperature_correnti)
    if not temperature_base:
        raise ValueError(
            "Nessuna temperatura disponibile per costruire la partizione HENS."
        )
    T_max = max(temperature_base)
    T_min = min(temperature_base)
    pinch_interni = sorted(
        {T for T in pinch_HEN if T_min + tolleranza < T < T_max - tolleranza},
        reverse=True,
    )
    if separa_al_pinch:
        limiti_zone = [T_max, *pinch_interni, T_min]
    else:
        limiti_zone = [T_max, T_min]
    zone = {}
    for z, (T_sup_z, T_inf_z) in enumerate(zip(limiti_zone, limiti_zone[1:]), start=1):
        livelli = {T_sup_z, T_inf_z}
        for T in temperature_gcc:
            if T_inf_z - tolleranza <= T <= T_sup_z + tolleranza:
                livelli.add(T)
        for T in temperature_correnti:
            if T_inf_z - tolleranza <= T <= T_sup_z + tolleranza:
                livelli.add(T)
        livelli_iniziali = set(livelli)
        iterazione = 0
        while True:
            livelli_ordinati = sorted(livelli, reverse=True)
            nuovi_livelli = []
            for T_sup, T_inf in zip(livelli_ordinati, livelli_ordinati[1:]):
                delta_T = T_sup - T_inf
                if delta_T > delta_T_partition_max + tolleranza:
                    T_medio = (T_sup + T_inf) / 2
                    nuovi_livelli.append(T_medio)
            if not nuovi_livelli:
                break
            iterazione += 1
            livelli.update(nuovi_livelli)
        for corrente in correnti_partizione:
            if not corrente_disponibile(corrente):
                continue
            T1, T2 = temperature_corrente_HEN(corrente)
            T_stream_sup = min(max(T1, T2), T_sup_z)
            T_stream_inf = max(min(T1, T2), T_inf_z)
            if T_stream_sup <= T_stream_inf + tolleranza:
                continue
            livelli_interni = [
                T
                for T in livelli
                if T_stream_inf + tolleranza < T < T_stream_sup - tolleranza
            ]
            if len(livelli_interni) < 2:
                delta_T_stream = T_stream_sup - T_stream_inf
                T_a = T_stream_inf + delta_T_stream / 3
                T_b = T_stream_inf + 2 * delta_T_stream / 3
                livelli.add(T_a)
                livelli.add(T_b)
        while len(livelli) - 1 < numero_intervalli_min:
            livelli_ordinati = sorted(livelli, reverse=True)
            T_sup_maggiore, T_inf_maggiore = max(
                zip(livelli_ordinati, livelli_ordinati[1:]),
                key=lambda coppia: coppia[0] - coppia[1],
            )
            T_medio = (T_sup_maggiore + T_inf_maggiore) / 2
            livelli.add(T_medio)
        livelli_finali = sorted(livelli, reverse=True)
        zone[z] = [
            (T_sup, T_inf) for T_sup, T_inf in zip(livelli_finali, livelli_finali[1:])
        ]
    return zone


def genera_indici_q_HEN(insiemi_HEN, tolleranza=1e-09):
    """Genera soltanto gli indici q termicamente e strutturalmente ammessi.

    Le esclusioni delle utility virtuali [1.50]-[1.51] sono applicate qui, senza
    creare variabili q vincolate artificialmente a zero."""
    Z = insiemi_HEN["Z"]
    H = insiemi_HEN["H"]
    C = insiemi_HEN["C"]
    M_i = insiemi_HEN["M_i"]
    N_j = insiemi_HEN["N_j"]
    P = insiemi_HEN["P"]
    P_H = insiemi_HEN["P_H"]
    P_C = insiemi_HEN["P_C"]
    HF = insiemi_HEN.get("HF", {})
    CF = insiemi_HEN.get("CF", {})
    MF = insiemi_HEN.get("MF", {})
    NF = insiemi_HEN.get("NF", {})
    VHU = insiemi_HEN.get("VHU", {})
    VCU = insiemi_HEN.get("VCU", {})
    T_intervallo = insiemi_HEN["T_intervallo"]
    indici_q = []
    for z in Z:
        for i in H[z]:
            for m in M_i[z, i]:
                T_m_U = T_intervallo[z, m]["T_sup"]
                for j in P_H[z, i, m]:
                    if (i, j) not in P:
                        continue
                    if j not in C[z]:
                        continue
                    for n in N_j[z, j]:
                        if i in VHU.get(z, []):
                            if j not in CF.get(z, []) or n not in NF.get((z, j), []):
                                continue
                        if j in VCU.get(z, []):
                            if i not in HF.get(z, []) or m not in MF.get((z, i), []):
                                continue
                        if i not in P_C[z, j, n]:
                            continue
                        T_n_L = T_intervallo[z, n]["T_inf"]
                        if T_n_L < T_m_U - tolleranza:
                            indici_q.append((z, i, m, j, n))
    indici_q = sorted(set(indici_q), key=lambda x: (x[0], x[1], x[2], x[3], x[4]))
    return indici_q


def calcola_delta_H_HEN(insiemi_HEN, tolleranza=1e-09):
    """Calcola i carichi di intervallo delle process streams per [1.37]-[1.38]."""
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

    def calcola_CP_equivalente(flusso):
        delta_T_totale = abs(flusso.T_in - flusso.T_out)
        if delta_T_totale <= tolleranza:
            raise ValueError(
                f"La corrente {flusso.codice} è isoterma. La gestione delle correnti isoterme nel modello HENS deve essere trattata separatamente."
            )
        Q_totale = flusso.calcola_Q()
        return Q_totale / delta_T_totale

    for z in Z:
        for i in H[z]:
            if i in HU[z]:
                continue
            if i in NI_H:
                continue
            flusso = correnti[i]
            CP = calcola_CP_equivalente(flusso)
            for m in M_i[z, i]:
                T_sup = T_intervallo[z, m]["T_sup"]
                T_inf = T_intervallo[z, m]["T_inf"]
                delta_T = T_sup - T_inf
                delta_H_H[z, i, m] = CP * delta_T
    for z in Z:
        for j in C[z]:
            if j in CU[z]:
                continue
            if j in NI_C:
                continue
            flusso = correnti[j]
            CP = calcola_CP_equivalente(flusso)
            for n in N_j[z, j]:
                T_sup = T_intervallo[z, n]["T_sup"]
                T_inf = T_intervallo[z, n]["T_inf"]
                delta_T = T_sup - T_inf
                delta_H_C[z, j, n] = CP * delta_T
    return {"delta_H_H": delta_H_H, "delta_H_C": delta_H_C}


def calcola_parametri_area_HEN(insiemi_HEN, indici_q, delta_T_min, tolleranza=1e-09):
    """Calcola LMTD e coefficienti lineari di area usati in [1.43]."""
    T_intervallo = insiemi_HEN["T_intervallo"]
    correnti = insiemi_HEN["correnti"]
    if delta_T_min < 0:
        raise ValueError("delta_T_min deve essere >= 0.")

    def leggi_h_kW_m2K(codice_corrente):
        """
        Legge h_W_m2K dall'oggetto corrente
        e lo converte:

            W/m²K -> kW/m²K
        """
        if codice_corrente not in correnti:
            raise KeyError(
                f"Corrente {codice_corrente} non presente in insiemi_HEN['correnti']."
            )
        corrente = correnti[codice_corrente]
        if not hasattr(corrente, "h_W_m2K"):
            raise ValueError(
                f"La corrente {codice_corrente} non possiede l'attributo 'h_W_m2K'. Controllare la classe Flusso e il caricamento del JSON."
            )
        h_W_m2K = corrente.h_W_m2K
        if h_W_m2K is None:
            raise ValueError(f"h_W_m2K non definito per {codice_corrente}.")
        h_W_m2K = float(h_W_m2K)
        if h_W_m2K <= 0:
            raise ValueError(
                f"h_W_m2K deve essere > 0 per {codice_corrente}. Ricevuto: {h_W_m2K}"
            )
        return h_W_m2K / 1000.0

    def calcola_LMTD(delta_T_1, delta_T_2):
        """
        Calcola la differenza media logaritmica
        di temperatura.

        ΔT_ML =
            (ΔT1 - ΔT2)
            / ln(ΔT1 / ΔT2)

        Se ΔT1 ≈ ΔT2:

            ΔT_ML = ΔT1
        """
        if delta_T_1 <= tolleranza or delta_T_2 <= tolleranza:
            raise ValueError(
                f"LMTD non definibile con differenze di temperatura nulle o negative. ΔT1={delta_T_1:.6f}, ΔT2={delta_T_2:.6f}"
            )
        if abs(delta_T_1 - delta_T_2) <= tolleranza:
            return 0.5 * (delta_T_1 + delta_T_2)
        return (delta_T_1 - delta_T_2) / math.log(delta_T_1 / delta_T_2)

    h_H = {}
    h_C = {}
    delta_T_ML = {}
    coeff_area = {}
    dettagli = {}
    for indice in indici_q:
        z, i, m, j, n = indice
        chiave_h_hot = (z, i, m)
        chiave_h_cold = (z, j, n)
        if chiave_h_hot not in h_H:
            h_H[chiave_h_hot] = leggi_h_kW_m2K(i)
        if chiave_h_cold not in h_C:
            h_C[chiave_h_cold] = leggi_h_kW_m2K(j)
        h_im = h_H[chiave_h_hot]
        h_jn = h_C[chiave_h_cold]
        T_hot_U = T_intervallo[z, m]["T_sup"]
        T_hot_L = T_intervallo[z, m]["T_inf"]
        T_cold_U_HEN = T_intervallo[z, n]["T_sup"]
        T_cold_L_HEN = T_intervallo[z, n]["T_inf"]
        T_cold_U = T_cold_U_HEN - delta_T_min
        T_cold_L = T_cold_L_HEN - delta_T_min
        delta_T_1 = T_hot_U - T_cold_U
        delta_T_2 = T_hot_L - T_cold_L
        DT_ML = calcola_LMTD(delta_T_1, delta_T_2)
        delta_T_ML[z, m, n] = DT_ML
        coeff = (1.0 / h_im + 1.0 / h_jn) / DT_ML
        coeff_area[indice] = coeff
        dettagli[indice] = {
            "h_hot_kW_m2K": h_im,
            "h_cold_kW_m2K": h_jn,
            "T_hot_U_C": T_hot_U,
            "T_hot_L_C": T_hot_L,
            "T_cold_U_HEN_C": T_cold_U_HEN,
            "T_cold_L_HEN_C": T_cold_L_HEN,
            "T_cold_U_reale_C": T_cold_U,
            "T_cold_L_reale_C": T_cold_L,
            "delta_T_1_K": delta_T_1,
            "delta_T_2_K": delta_T_2,
            "delta_T_ML_K": DT_ML,
            "coeff_area_m2_per_kW": coeff,
        }
    return {
        "h_H": h_H,
        "h_C": h_C,
        "delta_T_ML": delta_T_ML,
        "coeff_area": coeff_area,
        "dettagli": dettagli,
    }


def costruisci_utilities_HEN(configurazione):
    """Legge e valida le utility HENS fisiche dichiarate nel JSON."""
    if "hens" not in configurazione:
        raise ValueError("La configurazione non contiene la sezione 'hens'.")
    dati_hens = configurazione["hens"]
    if not isinstance(dati_hens, dict):
        raise ValueError("La sezione 'hens' deve essere un dizionario.")
    if "utilities" not in dati_hens:
        raise ValueError("La sezione 'hens' non contiene 'utilities'.")
    dati_utilities = dati_hens["utilities"]
    if not isinstance(dati_utilities, list):
        raise ValueError("'hens.utilities' deve essere una lista.")
    utilities = {"hot": [], "cold": []}
    codici = set()
    for dati in dati_utilities:
        if not isinstance(dati, dict):
            raise ValueError(
                "Ogni utility HENS deve essere definita tramite un dizionario."
            )
        campi_obbligatori = ["codice", "tipo", "T_in", "T_out", "h_W_m2K"]
        mancanti = [campo for campo in campi_obbligatori if campo not in dati]
        if mancanti:
            raise ValueError(f"Utility HENS incompleta. Campi mancanti: {mancanti}")
        tipo = str(dati["tipo"]).strip().lower()
        if tipo not in ("hot", "cold"):
            raise ValueError(f"Tipo non valido per utility {dati['codice']}: {tipo}")
        costo_raw = dati.get("costo_USD_per_kW_year")
        costo = None if costo_raw is None else float(costo_raw)
        utility = UtilityHEN(
            codice=str(dati["codice"]),
            nome=str(dati.get("nome", dati["codice"])),
            tipo=tipo,
            T_in=float(dati["T_in"]),
            T_out=float(dati["T_out"]),
            h_W_m2K=float(dati["h_W_m2K"]),
            costo_USD_per_kW_year=costo,
            duty_variabile=bool(dati.get("duty_variabile", True)),
            disponibile=bool(dati.get("disponibile", True)),
        )
        if utility.codice in codici:
            raise ValueError(f"Utility HENS duplicata: {utility.codice}")
        codici.add(utility.codice)
        if utility.tipo == "hot" and utility.T_in <= utility.T_out:
            raise ValueError(
                f"La hot utility {utility.codice} deve avere T_in > T_out."
            )
        if utility.tipo == "cold" and utility.T_out <= utility.T_in:
            raise ValueError(
                f"La cold utility {utility.codice} deve avere T_out > T_in."
            )
        if utility.h_W_m2K <= 0:
            raise ValueError(
                f"h_W_m2K non valido per {utility.codice}: {utility.h_W_m2K}"
            )
        if (
            utility.costo_USD_per_kW_year is not None
            and utility.costo_USD_per_kW_year < 0
        ):
            raise ValueError(
                f"Costo utility negativo per {utility.codice}: {utility.costo_USD_per_kW_year}"
            )
        if not utility.disponibile:
            continue
        utilities[utility.tipo].append(utility)
    return utilities


def crea_modello_bilanci_HEN(
    insiemi_HEN, indici_q, delta_H_HEN, nome_modello="HENS_bilanci"
):
    """Crea variabili q e portate utility con i bilanci HENS [1.37]-[1.41]."""
    Z = insiemi_HEN["Z"]
    H = insiemi_HEN["H"]
    C = insiemi_HEN["C"]
    HU = insiemi_HEN["HU"]
    CU = insiemi_HEN["CU"]
    M_i = insiemi_HEN["M_i"]
    N_j = insiemi_HEN["N_j"]
    NI_H = set(insiemi_HEN.get("NI_H", []))
    NI_C = set(insiemi_HEN.get("NI_C", []))
    T_intervallo = insiemi_HEN["T_intervallo"]
    delta_H_H = delta_H_HEN["delta_H_H"]
    delta_H_C = delta_H_HEN["delta_H_C"]
    if NI_H or NI_C:
        raise NotImplementedError(
            f"crea_modello_bilanci_HEN() non gestisce ancora il non-isothermal mixing. NI_H={NI_H}, NI_C={NI_C}"
        )
    mdl = Model(name=nome_modello)
    q = mdl.continuous_var_dict(indici_q, lb=0, name="q")
    codici_HU = sorted({i for z in Z for i in HU[z]})
    codici_CU = sorted({j for z in Z for j in CU[z]})
    F_H = mdl.continuous_var_dict(codici_HU, lb=0, name="F_H")
    F_C = mdl.continuous_var_dict(codici_CU, lb=0, name="F_C")
    q_da_hot = {}
    q_a_cold = {}
    for indice in indici_q:
        z, i, m, j, n = indice
        q_da_hot.setdefault((z, i, m), []).append(indice)
        q_a_cold.setdefault((z, j, n), []).append(indice)
    vincoli_hot_process = []
    vincoli_cold_process = []
    vincoli_hot_utility = []
    vincoli_cold_utility = []
    for z in Z:
        for i in H[z]:
            if i in HU[z]:
                for m in M_i[z, i]:
                    T_sup = T_intervallo[z, m]["T_sup"]
                    T_inf = T_intervallo[z, m]["T_inf"]
                    delta_T_m = T_sup - T_inf
                    chiavi_q = q_da_hot.get((z, i, m), [])
                    Q_uscente = mdl.sum((q[k] for k in chiavi_q))
                    vincolo = mdl.add_constraint(
                        F_H[i] * delta_T_m == Q_uscente, ctname=f"bil_HU_z{z}_{i}_m{m}"
                    )
                    vincoli_hot_utility.append(vincolo)
            else:
                for m in M_i[z, i]:
                    chiave_delta_H = (z, i, m)
                    if chiave_delta_H not in delta_H_H:
                        raise KeyError(f"ΔH hot mancante per {chiave_delta_H}")
                    valore_delta_H = delta_H_H[chiave_delta_H]
                    chiavi_q = q_da_hot.get(chiave_delta_H, [])
                    if valore_delta_H > 1e-12 and (not chiavi_q):
                        raise ValueError(
                            f"Nessun indice q disponibile per il bilancio hot {chiave_delta_H}."
                        )
                    Q_uscente = mdl.sum((q[k] for k in chiavi_q))
                    vincolo = mdl.add_constraint(
                        Q_uscente == valore_delta_H, ctname=f"bil_HP_z{z}_{i}_m{m}"
                    )
                    vincoli_hot_process.append(vincolo)
    for z in Z:
        for j in C[z]:
            if j in CU[z]:
                for n in N_j[z, j]:
                    T_sup = T_intervallo[z, n]["T_sup"]
                    T_inf = T_intervallo[z, n]["T_inf"]
                    delta_T_n = T_sup - T_inf
                    chiavi_q = q_a_cold.get((z, j, n), [])
                    Q_entrante = mdl.sum((q[k] for k in chiavi_q))
                    vincolo = mdl.add_constraint(
                        F_C[j] * delta_T_n == Q_entrante, ctname=f"bil_CU_z{z}_{j}_n{n}"
                    )
                    vincoli_cold_utility.append(vincolo)
            else:
                for n in N_j[z, j]:
                    chiave_delta_H = (z, j, n)
                    if chiave_delta_H not in delta_H_C:
                        raise KeyError(f"ΔH cold mancante per {chiave_delta_H}")
                    valore_delta_H = delta_H_C[chiave_delta_H]
                    chiavi_q = q_a_cold.get(chiave_delta_H, [])
                    if valore_delta_H > 1e-12 and (not chiavi_q):
                        raise ValueError(
                            f"Nessun indice q disponibile per il bilancio cold {chiave_delta_H}."
                        )
                    Q_entrante = mdl.sum((q[k] for k in chiavi_q))
                    vincolo = mdl.add_constraint(
                        Q_entrante == valore_delta_H, ctname=f"bil_CP_z{z}_{j}_n{n}"
                    )
                    vincoli_cold_process.append(vincolo)
    delta_T_HU = {i: 0.0 for i in codici_HU}
    delta_T_CU = {j: 0.0 for j in codici_CU}
    for z in Z:
        for i in HU[z]:
            for m in M_i[z, i]:
                T_sup = T_intervallo[z, m]["T_sup"]
                T_inf = T_intervallo[z, m]["T_inf"]
                delta_T_HU[i] += T_sup - T_inf
        for j in CU[z]:
            for n in N_j[z, j]:
                T_sup = T_intervallo[z, n]["T_sup"]
                T_inf = T_intervallo[z, n]["T_inf"]
                delta_T_CU[j] += T_sup - T_inf
    Q_HU = {i: F_H[i] * delta_T_HU[i] for i in codici_HU}
    Q_CU = {j: F_C[j] * delta_T_CU[j] for j in codici_CU}
    mdl.minimize(0)
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
            "hot_process": vincoli_hot_process,
            "cold_process": vincoli_cold_process,
            "hot_utility": vincoli_hot_utility,
            "cold_utility": vincoli_cold_utility,
        },
    }


def aggiungi_variabili_tecnologie_HEN(
    modello_bilanci, insiemi_HEN, indici_q, tecnologie_HEN
):
    """Aggiunge area A e numero intero di unita U per tecnologia e match."""
    mdl = modello_bilanci["modello"]
    T = tecnologie_HEN["T"]
    P_t = tecnologie_HEN["P_t"]
    coppie_zona = {(z, i, j) for z, i, m, j, n in indici_q}
    indici_A_U = []
    for z, i, j in sorted(coppie_zona):
        for t in T:
            if (i, j) not in P_t[t]:
                continue
            indici_A_U.append((z, i, j, t))
    A = mdl.continuous_var_dict(indici_A_U, lb=0, name="A")
    U = mdl.integer_var_dict(indici_A_U, lb=0, name="U")
    modello_bilanci["indici_A_U"] = indici_A_U
    modello_bilanci["A"] = A
    modello_bilanci["U"] = U
    modello_bilanci["tecnologie_HEN"] = tecnologie_HEN
    return modello_bilanci


def aggiungi_vincoli_area_HEN(modello_HEN, indici_q, parametri_area, tecnologie_HEN):
    """Aggiunge equazioni di area e capacita per tecnologia [1.43]-[1.46]."""
    mdl = modello_HEN["modello"]
    q = modello_HEN["q"]
    A = modello_HEN["A"]
    U = modello_HEN["U"]
    indici_A_U = modello_HEN["indici_A_U"]
    coeff_area = parametri_area["coeff_area"]
    tecnologie = tecnologie_HEN["tecnologie"]
    mancanti = [indice for indice in indici_q if indice not in coeff_area]
    if mancanti:
        raise KeyError(
            f"Mancano coefficienti area per alcuni indici q. Primo indice mancante: {mancanti[0]}"
        )
    q_match = {}
    for indice in indici_q:
        z, i, m, j, n = indice
        chiave_match = (z, i, j)
        q_match.setdefault(chiave_match, []).append(indice)
    tecnologie_match = {}
    for indice in indici_A_U:
        z, i, j, t = indice
        chiave_match = (z, i, j)
        tecnologie_match.setdefault(chiave_match, []).append(indice)
    vincoli_equazione_area = []
    vincoli_Amax = []
    for chiave_match in sorted(q_match):
        z, i, j = chiave_match
        indici_tecnologie = tecnologie_match.get(chiave_match, [])
        if not indici_tecnologie:
            raise ValueError(
                f"Il match {chiave_match} possiede variabili q ma nessuna tecnologia HEX disponibile."
            )
        area_equivalente = mdl.sum(
            (coeff_area[indice] * q[indice] for indice in q_match[chiave_match])
        )
        area_tecnologie = mdl.sum(
            (
                A[indice_A] * tecnologie[indice_A[3]].FHEX
                for indice_A in indici_tecnologie
            )
        )
        vincolo = mdl.add_constraint(
            area_tecnologie == area_equivalente, ctname=f"area_z{z}_{i}_{j}"
        )
        vincoli_equazione_area.append(vincolo)
    for indice in indici_A_U:
        z, i, j, t = indice
        tecnologia = tecnologie[t]
        A_max = tecnologia.A_max_m2
        vincolo = mdl.add_constraint(
            A[indice] <= A_max * U[indice], ctname=f"Amax_z{z}_{i}_{j}_{t}"
        )
        vincoli_Amax.append(vincolo)
    modello_HEN["vincoli_area"] = {
        "equazione_area": vincoli_equazione_area,
        "Amax": vincoli_Amax,
    }
    return modello_HEN


def aggiungi_obiettivo_TAC_HEN(modello_HEN, utilities_HEN, tecnologie_HEN):
    """Minimizza il costo annuale di utility, unita e area secondo [1.47]."""
    mdl = modello_HEN["modello"]
    Q_HU = modello_HEN["Q_HU"]
    Q_CU = modello_HEN["Q_CU"]
    A = modello_HEN["A"]
    U = modello_HEN["U"]
    indici_A_U = modello_HEN["indici_A_U"]
    tecnologie = tecnologie_HEN["tecnologie"]
    hot_utilities = {utility.codice: utility for utility in utilities_HEN["hot"]}
    cold_utilities = {utility.codice: utility for utility in utilities_HEN["cold"]}
    for codice in Q_HU:
        if codice not in hot_utilities:
            raise KeyError(
                f"Hot utility {codice} presente nel modello ma non in utilities_HEN."
            )
        utility = hot_utilities[codice]
        if utility.costo_USD_per_kW_year is None:
            raise ValueError(f"Costo non definito per hot utility {codice}.")
        if utility.costo_USD_per_kW_year < 0:
            raise ValueError(f"Costo negativo per hot utility {codice}.")
    for codice in Q_CU:
        if codice not in cold_utilities:
            raise KeyError(
                f"Cold utility {codice} presente nel modello ma non in utilities_HEN."
            )
        utility = cold_utilities[codice]
        if utility.costo_USD_per_kW_year is None:
            raise ValueError(f"Costo non definito per cold utility {codice}.")
        if utility.costo_USD_per_kW_year < 0:
            raise ValueError(f"Costo negativo per cold utility {codice}.")
    costo_hot_utility = mdl.sum(
        (hot_utilities[codice].costo_USD_per_kW_year * Q_HU[codice] for codice in Q_HU)
    )
    costo_cold_utility = mdl.sum(
        (cold_utilities[codice].costo_USD_per_kW_year * Q_CU[codice] for codice in Q_CU)
    )
    costo_fisso_HEX = mdl.sum(
        (
            tecnologie[t].costo_fisso_USD_per_year * U[z, i, j, t]
            for z, i, j, t in indici_A_U
        )
    )
    costo_area_HEX = mdl.sum(
        (
            tecnologie[t].costo_area_USD_per_m2_year * A[z, i, j, t]
            for z, i, j, t in indici_A_U
        )
    )
    TAC = costo_hot_utility + costo_cold_utility + costo_fisso_HEX + costo_area_HEX
    mdl.minimize(TAC)
    modello_HEN["costo_hot_utility"] = costo_hot_utility
    modello_HEN["costo_cold_utility"] = costo_cold_utility
    modello_HEN["costo_fisso_HEX"] = costo_fisso_HEX
    modello_HEN["costo_area_HEX"] = costo_area_HEX
    modello_HEN["TAC"] = TAC
    return modello_HEN


def costruisci_tecnologie_HEN(configurazione):
    """Costruisce tecnologie abilitate e match P_t dichiarati nel JSON."""
    if "hens" not in configurazione:
        raise ValueError("La configurazione non contiene la sezione 'hens'.")
    dati_hens = configurazione["hens"]
    if "technologies" not in dati_hens:
        raise ValueError("La sezione 'hens' non contiene 'technologies'.")
    dati_tecnologie = dati_hens["technologies"]
    if not isinstance(dati_tecnologie, list):
        raise ValueError("'hens.technologies' deve essere una lista.")
    hot_codes = set()
    cold_codes = set()
    for dati_flusso in configurazione.get("flussi", []):
        if not dati_flusso.get("disponibile", True):
            continue
        codice = str(dati_flusso["codice"])
        tipo = str(dati_flusso["tipo"]).strip().lower()
        if tipo == "hot":
            hot_codes.add(codice)
        elif tipo == "cold":
            cold_codes.add(codice)
    for dati_utility in dati_hens.get("utilities", []):
        if not dati_utility.get("disponibile", True):
            continue
        codice = str(dati_utility["codice"])
        tipo = str(dati_utility["tipo"]).strip().lower()
        if tipo == "hot":
            hot_codes.add(codice)
        elif tipo == "cold":
            cold_codes.add(codice)
    tecnologie = {}
    codici = set()
    for dati in dati_tecnologie:
        if not isinstance(dati, dict):
            raise ValueError("Ogni tecnologia HENS deve essere un dizionario.")
        campi_obbligatori = [
            "codice",
            "FHEX",
            "A_max_m2",
            "costo_fisso_USD_per_year",
            "costo_area_USD_per_m2_year",
            "matches",
        ]
        mancanti = [campo for campo in campi_obbligatori if campo not in dati]
        if mancanti:
            raise ValueError(f"Tecnologia HENS incompleta. Campi mancanti: {mancanti}")
        codice = str(dati["codice"])
        if codice in codici:
            raise ValueError(f"Tecnologia HENS duplicata: {codice}")
        codici.add(codice)
        enabled = bool(dati.get("enabled", True))
        FHEX = float(dati["FHEX"])
        A_max_m2 = float(dati["A_max_m2"])
        costo_fisso = float(dati["costo_fisso_USD_per_year"])
        costo_area = float(dati["costo_area_USD_per_m2_year"])
        if FHEX <= 0 or FHEX > 1:
            raise ValueError(
                f"FHEX non valido per {codice}: {FHEX}. Deve essere compreso nell'intervallo (0, 1]."
            )
        if A_max_m2 <= 0:
            raise ValueError(f"A_max_m2 non valido per {codice}: {A_max_m2}")
        if costo_fisso < 0:
            raise ValueError(f"Costo fisso negativo per {codice}: {costo_fisso}")
        if costo_area < 0:
            raise ValueError(f"Costo area negativo per {codice}: {costo_area}")
        matches = set()
        for match in dati["matches"]:
            if not isinstance(match, (list, tuple)) or len(match) != 2:
                raise ValueError(
                    f"Match non valido in {codice}: {match}. Ogni match deve essere [hot, cold]."
                )
            i = str(match[0])
            j = str(match[1])
            if i not in hot_codes:
                raise ValueError(
                    f"Match non valido per {codice}: ({i}, {j}). {i} non è una hot stream disponibile."
                )
            if j not in cold_codes:
                raise ValueError(
                    f"Match non valido per {codice}: ({i}, {j}). {j} non è una cold stream disponibile."
                )
            chiave_match = (i, j)
            if chiave_match in matches:
                raise ValueError(f"Match duplicato in {codice}: {chiave_match}")
            matches.add(chiave_match)
        tecnologia = TecnologiaHEN(
            codice=codice,
            nome=str(dati.get("nome", codice)),
            FHEX=FHEX,
            A_max_m2=A_max_m2,
            costo_fisso_USD_per_year=costo_fisso,
            costo_area_USD_per_m2_year=costo_area,
            matches=frozenset(matches),
            enabled=enabled,
        )
        if not enabled:
            continue
        tecnologie[codice] = tecnologia
    T = sorted(tecnologie.keys())
    P_t = {t: set(tecnologie[t].matches) for t in T}
    if not T:
        raise ValueError("Nessuna tecnologia HENS abilitata.")
    return {"T": T, "tecnologie": tecnologie, "P_t": P_t}


def prepara_modello_HEN(sorgente):
    """Coordina una sola volta l intera pipeline HENS senza risolverla.

    Usa due partizioni finite: la prima determina le utility virtuali [1.48]-[1.49],
    la seconda le include nel modello definitivo."""
    dati_pinch = (
        prepara_pinch(sorgente) if isinstance(sorgente, (str, Path)) else sorgente
    )
    configurazione = dati_pinch["configurazione"]
    hens = configurazione.get("hens", {})
    separa_al_pinch = hens.get("separa_al_pinch", True)
    if type(separa_al_pinch) is not bool:
        raise ValueError("'hens.separa_al_pinch' deve essere true oppure false.")
    flussi_flessibili = costruisci_flussi_flessibili_HEN(configurazione)
    utilities_fisiche = costruisci_utilities_HEN(configurazione)
    argomenti_partizione = {
        "gcc": dati_pinch["gcc"],
        "flussi": configurazione["flussi_oggetti"],
        "delta_T_min": configurazione["delta_T_min"],
        "pinch_traslati": dati_pinch["pinch_traslati_C"],
        "delta_T_partition_max": configurazione["delta_T_partition_max"],
        "numero_intervalli_min": configurazione["numero_intervalli_min"],
        "separa_al_pinch": separa_al_pinch,
        "flexible_streams": flussi_flessibili,
    }
    partizione_preliminare = crea_partizione_HEN(
        utilities=utilities_fisiche, **argomenti_partizione
    )
    utilities_virtuali = costruisci_utilities_virtuali_HEN(
        intervalli=partizione_preliminare,
        flussi_flessibili=flussi_flessibili,
        flussi=configurazione["flussi_oggetti"],
        delta_T_min=configurazione["delta_T_min"],
        delta_T_partition_max=configurazione["delta_T_partition_max"],
    )
    codici_esistenti = {f.codice for f in configurazione["flussi_oggetti"]} | {
        u.codice for tipo in ("hot", "cold") for u in utilities_fisiche[tipo]
    }
    collisioni = codici_esistenti & {
        u.codice for tipo in ("hot", "cold") for u in utilities_virtuali[tipo]
    }
    if collisioni:
        raise ValueError(
            f"Codici riservati alle utility virtuali gia usati: {sorted(collisioni)}."
        )
    utilities_HEN = {
        tipo: list(utilities_fisiche[tipo]) + list(utilities_virtuali[tipo])
        for tipo in ("hot", "cold")
    }
    intervalli_HEN = crea_partizione_HEN(
        utilities=utilities_HEN, **argomenti_partizione
    )
    tecnologie_HEN = costruisci_tecnologie_HEN(configurazione)
    aggiungi_tecnologia_virtuale_HEN(tecnologie_HEN, utilities_HEN, flussi_flessibili)
    match_permessi = set().union(*tecnologie_HEN["P_t"].values())
    insiemi_HEN = costruisci_insiemi_HEN(
        flussi=configurazione["flussi_oggetti"],
        utilities=utilities_HEN,
        intervalli=intervalli_HEN,
        delta_T_min=configurazione["delta_T_min"],
        match_permessi=match_permessi,
        flexible_streams=flussi_flessibili,
    )
    indici_q = genera_indici_q_HEN(insiemi_HEN)
    delta_H_HEN = calcola_delta_H_HEN(insiemi_HEN)
    modello_HEN = crea_modello_bilanci_HEN(insiemi_HEN, indici_q, delta_H_HEN)
    parametri_area = calcola_parametri_area_HEN(
        insiemi_HEN, indici_q, configurazione["delta_T_min"]
    )
    aggiungi_variabili_tecnologie_HEN(
        modello_HEN, insiemi_HEN, indici_q, tecnologie_HEN
    )
    aggiungi_vincoli_area_HEN(modello_HEN, indici_q, parametri_area, tecnologie_HEN)
    aggiungi_obiettivo_TAC_HEN(modello_HEN, utilities_HEN, tecnologie_HEN)
    return {
        "dati_pinch": dati_pinch,
        "configurazione": configurazione,
        "flussi_flessibili": flussi_flessibili,
        "utilities_HEN": utilities_HEN,
        "intervalli_HEN": intervalli_HEN,
        "insiemi_HEN": insiemi_HEN,
        "indici_q": indici_q,
        "delta_H_HEN": delta_H_HEN,
        "parametri_area": parametri_area,
        "tecnologie_HEN": tecnologie_HEN,
        "modello_HEN": modello_HEN,
    }


def risolvi_HEN(preparazione, log_output=False, tolleranza=1e-7):
    """Risolve il MILP HENS e ricostruisce risultati strutturati."""

    modello = preparazione["modello_HEN"]
    mdl = modello["modello"]
    soluzione = mdl.solve(log_output=log_output)
    if soluzione is None:
        raise RuntimeError(
            f"CPLEX non ha trovato una soluzione: {mdl.solve_details.status}."
        )

    valore = soluzione.get_value
    insiemi = preparazione["insiemi_HEN"]
    tecnologie = preparazione["tecnologie_HEN"]["tecnologie"]
    utilities = preparazione["utilities_HEN"]
    duty_utilities = {
        codice: valore(espressione)
        for codice, espressione in {
            **modello["Q_HU"],
            **modello["Q_CU"],
        }.items()
    }

    duty_match = {}
    for (z, i, m, j, n), variabile in modello["q"].items():
        q_val = valore(variabile)
        if q_val > tolleranza:
            duty_match[z, i, j] = duty_match.get((z, i, j), 0.0) + q_val

    codici_virtuali = {
        u.codice for tipo in ("hot", "cold") for u in utilities[tipo] if u.virtuale
    }
    scambiatori = []
    match_virtuali = []
    for indice in modello["indici_A_U"]:
        z, i, j, t = indice
        U_val = valore(modello["U"][indice])
        A_val = valore(modello["A"][indice])
        if U_val <= tolleranza:
            continue
        record = {
            "zona": z,
            "hot": i,
            "cold": j,
            "tecnologia": t,
            "U": U_val,
            "area_m2": A_val,
            "duty_kW": duty_match.get((z, i, j), 0.0),
        }
        if i in codici_virtuali or j in codici_virtuali or tecnologie[t].virtuale:
            match_virtuali.append(record)
        else:
            scambiatori.append(record)

    codici_VHU = {u.codice for u in utilities["hot"] if u.virtuale}
    codici_VCU = {u.codice for u in utilities["cold"] if u.virtuale}
    risultati_flessibili = []
    Q_virtuale_hot = 0.0
    Q_virtuale_cold = 0.0
    for codice, dati in preparazione["flussi_flessibili"].items():
        Q_totale = dati["CP_kW_K"] * (dati["T_out_max_C"] - dati["T_out_min_C"])
        if dati["tipo"] == "hot":
            Q_virtuale = sum(
                Q
                for (z, i, j), Q in duty_match.items()
                if i == codice and j in codici_VCU
            )
            T_ottima = dati["T_out_min_C"] + Q_virtuale / dati["CP_kW_K"]
            Q_virtuale_hot += Q_virtuale
        else:
            Q_virtuale = sum(
                Q
                for (z, i, j), Q in duty_match.items()
                if j == codice and i in codici_VHU
            )
            T_ottima = dati["T_out_max_C"] - Q_virtuale / dati["CP_kW_K"]
            Q_virtuale_cold += Q_virtuale

        if not (dati["T_out_min_C"] - 1e-6 <= T_ottima <= dati["T_out_max_C"] + 1e-6):
            raise RuntimeError(
                f"Temperatura ottima fuori range per {codice}: {T_ottima}."
            )
        risultati_flessibili.append(
            {
                "codice": codice,
                "tipo": dati["tipo"],
                "T_out_min_C": dati["T_out_min_C"],
                "T_out_max_C": dati["T_out_max_C"],
                "T_out_ottima_C": min(
                    dati["T_out_max_C"], max(dati["T_out_min_C"], T_ottima)
                ),
                "Q_surplus_totale_kW": Q_totale,
                "Q_surplus_usato_nel_processo_kW": max(0.0, Q_totale - Q_virtuale),
                "Q_surplus_virtuale_kW": Q_virtuale,
            }
        )

    utilities_fisiche = {
        u.codice: duty_utilities.get(u.codice, 0.0)
        for tipo in ("hot", "cold")
        for u in utilities[tipo]
        if not u.virtuale
    }
    utilities_virtuali = {
        u.codice: {
            "tipo": u.tipo,
            "T_in_C": u.T_in,
            "T_out_C": u.T_out,
            "T_in_HEN_C": u.T_in
            + (
                preparazione["configurazione"]["delta_T_min"]
                if u.tipo == "cold"
                else 0.0
            ),
            "T_out_HEN_C": u.T_out
            + (
                preparazione["configurazione"]["delta_T_min"]
                if u.tipo == "cold"
                else 0.0
            ),
            "duty_kW": duty_utilities.get(u.codice, 0.0),
        }
        for tipo in ("hot", "cold")
        for u in utilities[tipo]
        if u.virtuale
    }

    processi = preparazione["configurazione"]["flussi_oggetti"]
    Q_hot_effettivo = (
        sum(f.calcola_Q() for f in processi if f.tipo == "hot") - Q_virtuale_hot
    )
    Q_cold_effettivo = (
        sum(f.calcola_Q() for f in processi if f.tipo == "cold") - Q_virtuale_cold
    )
    Q_HU_fisica = sum(
        duty_utilities.get(u.codice, 0.0) for u in utilities["hot"] if not u.virtuale
    )
    Q_CU_fisica = sum(
        duty_utilities.get(u.codice, 0.0) for u in utilities["cold"] if not u.virtuale
    )
    residuo_bilancio = Q_hot_effettivo + Q_HU_fisica - Q_cold_effettivo - Q_CU_fisica

    benchmark = (
        preparazione["configurazione"].get("hens", {}).get("benchmark_TAC_kUSD_year")
    )
    TAC = valore(modello["TAC"])
    confronto = (
        None
        if benchmark is None
        else {
            "PDF_kUSD_year": float(benchmark),
            "modello_kUSD_year": TAC / 1000.0,
            "errore_assoluto_kUSD_year": TAC / 1000.0 - float(benchmark),
            "errore_percentuale": 100.0
            * (TAC / 1000.0 - float(benchmark))
            / float(benchmark),
        }
    )

    return {
        "soluzione": soluzione,
        "status": mdl.solve_details.status,
        "numero_zone": len(insiemi["Z"]),
        "numero_intervalli": sum(
            len(v) for v in preparazione["intervalli_HEN"].values()
        ),
        "numero_q": len(modello["q"]),
        "numero_A": len(modello["A"]),
        "numero_U": len(modello["U"]),
        "numero_variabili": mdl.number_of_variables,
        "numero_vincoli": mdl.number_of_constraints,
        "costo_HU_USD_year": valore(modello["costo_hot_utility"]),
        "costo_CU_USD_year": valore(modello["costo_cold_utility"]),
        "costo_fisso_HEX_USD_year": valore(modello["costo_fisso_HEX"]),
        "costo_area_HEX_USD_year": valore(modello["costo_area_HEX"]),
        "TAC_USD_year": TAC,
        "utilities_fisiche_kW": utilities_fisiche,
        "utilities_virtuali": utilities_virtuali,
        "flexible_streams": risultati_flessibili,
        "scambiatori_fisici": scambiatori,
        "virtual_matches": match_virtuali,
        "duty_match_kW": duty_match,
        "matches_per_tecnologia": {
            t: sorted(tecnologia.matches) for t, tecnologia in tecnologie.items()
        },
        "residuo_bilancio_energia_kW": residuo_bilancio,
        "confronto_benchmark": confronto,
    }


def stampa_risultati_HEN(risultati):
    """Stampa il report unico dei casi HENS."""

    print("\nMODELLO")
    print(f"Zone: {risultati['numero_zone']}")
    print(f"Intervalli: {risultati['numero_intervalli']}")
    print(
        f"Variabili q/A/U: {risultati['numero_q']}/"
        f"{risultati['numero_A']}/{risultati['numero_U']}"
    )
    print(
        f"Totale variabili/vincoli: {risultati['numero_variabili']}/"
        f"{risultati['numero_vincoli']}"
    )
    print(f"Status CPLEX: {risultati['status']}")

    print("\nECONOMIA")
    for etichetta, chiave in (
        ("Costo HU", "costo_HU_USD_year"),
        ("Costo CU", "costo_CU_USD_year"),
        ("Costo fisso HEX", "costo_fisso_HEX_USD_year"),
        ("Costo area HEX", "costo_area_HEX_USD_year"),
    ):
        print(f"{etichetta}: {risultati[chiave]:,.2f} USD/year")
    print(f"TAC: {risultati['TAC_USD_year']:,.2f} USD/year")
    print(f"TAC: {risultati['TAC_USD_year'] / 1000.0:.3f} kUSD/year")

    print("\nUTILITIES FISICHE")
    for codice, duty in risultati["utilities_fisiche_kW"].items():
        print(f"{codice}: {duty:.3f} kW")

    print("\nFLEXIBLE STREAMS")
    if not risultati["flexible_streams"]:
        print("Nessuna")
    for dati in risultati["flexible_streams"]:
        print(
            f"{dati['codice']} ({dati['tipo']}): "
            f"Tout [{dati['T_out_min_C']:.2f}, {dati['T_out_max_C']:.2f}] C, "
            f"ottima {dati['T_out_ottima_C']:.3f} C; "
            f"surplus totale/usato/virtuale "
            f"{dati['Q_surplus_totale_kW']:.3f}/"
            f"{dati['Q_surplus_usato_nel_processo_kW']:.3f}/"
            f"{dati['Q_surplus_virtuale_kW']:.3f} kW"
        )

    print("\nSCAMBIATORI FISICI")
    for dati in risultati["scambiatori_fisici"]:
        print(
            f"Zona {dati['zona']} | {dati['hot']} -> {dati['cold']} | "
            f"{dati['tecnologia']} | U={dati['U']:.0f} | "
            f"A={dati['area_m2']:.3f} m2 | Q={dati['duty_kW']:.3f} kW"
        )

    print("\nVIRTUAL MATCHES")
    if not risultati["virtual_matches"]:
        print("Nessuno")
    for dati in risultati["virtual_matches"]:
        print(
            f"Zona {dati['zona']} | {dati['hot']} -> {dati['cold']} | "
            f"Q={dati['duty_kW']:.3f} kW"
        )
    for codice, dati in risultati["utilities_virtuali"].items():
        print(
            f"{codice} ({dati['tipo']}): HEN {dati['T_in_HEN_C']:.2f} -> "
            f"{dati['T_out_HEN_C']:.2f} C; reali {dati['T_in_C']:.2f} -> "
            f"{dati['T_out_C']:.2f} C; duty={dati['duty_kW']:.3f} kW"
        )

    print("\nBILANCIO ENERGETICO")
    print(f"Residuo globale: {risultati['residuo_bilancio_energia_kW']:+.6e} kW")

    confronto = risultati["confronto_benchmark"]
    if confronto:
        print("\nCONFRONTO BENCHMARK")
        print(f"PDF: {confronto['PDF_kUSD_year']:.3f} kUSD/year")
        print(f"Modello: {confronto['modello_kUSD_year']:.3f} kUSD/year")
        print(
            f"Scostamento: {confronto['errore_assoluto_kUSD_year']:+.3f} "
            f"kUSD/year ({confronto['errore_percentuale']:+.2f}%)"
        )


def valuta_configurazione_processo(percorso_json, log_output=False):
    """Valuta stream gia estratti; non sostituisce un modello di processo."""

    preparazione = prepara_modello_HEN(percorso_json)
    risultati = risolvi_HEN(preparazione, log_output=log_output)
    return {
        "configurazione": str(percorso_json),
        "QH_min_kW": preparazione["dati_pinch"]["QH_min_kW"],
        "QC_min_kW": preparazione["dati_pinch"]["QC_min_kW"],
        "TAC_USD_year": risultati["TAC_USD_year"],
        "residuo_bilancio_energia_kW": risultati["residuo_bilancio_energia_kW"],
        "risultati_HEN": risultati,
    }


def confronta_configurazioni_processo(configurazioni, log_output=False):
    """Confronta configurazioni definite dal designer ordinandole per TAC."""

    valutazioni = [
        valuta_configurazione_processo(percorso, log_output=log_output)
        for percorso in configurazioni
    ]
    return sorted(valutazioni, key=lambda dati: dati["TAC_USD_year"])
