import json
from pathlib import Path

import matplotlib.pyplot as plt

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
    duty_variabile: bool = True
    disponibile: bool = True

class Flusso:
    """Corrente sensibile o carico termico isotermo."""

    def __init__(
        self, codice, nome, tipo, T_in, T_out, CP=None, processo=None,
        zona=None, disponibile=True, heat_load_kW=None,
        delta_T_min_half=None, isotermo=None, remark=None, unit=None,
    ):
        if tipo not in ("hot", "cold"):
            raise ValueError(f"Tipo non valido per il flusso {codice}: {tipo}")
        self.codice = codice
        self.nome = nome
        self.tipo = tipo
        self.T_in = float(T_in)
        self.T_out = float(T_out)
        self.heat_load_kW = None if heat_load_kW is None else float(heat_load_kW)
        self.delta_T_min_half = (
            None if delta_T_min_half is None else float(delta_T_min_half)
        )
        self.isotermo = (
            abs(self.T_in - self.T_out) <= 1e-12
            if isotermo is None else bool(isotermo)
        )
        self.processo = processo
        self.zona = zona
        self.disponibile = bool(disponibile)
        self.remark = remark
        self.unit = unit

        if self.isotermo:
            if self.heat_load_kW is None:
                raise ValueError(f"Il flusso isotermo {codice} richiede heat_load_kW.")
            self.CP = None if CP is None else float(CP)
        elif CP is not None:
            self.CP = float(CP)
        elif self.heat_load_kW is not None:
            self.CP = self.heat_load_kW / abs(self.T_out - self.T_in)
        else:
            raise ValueError(f"Il flusso {codice} richiede CP oppure heat_load_kW.")

    def calcola_Q(self):
        if self.heat_load_kW is not None:
            return self.heat_load_kW
        return self.CP * abs(self.T_in - self.T_out)

    def calcola_T_traslate(self, delta_T_min):
        delta_half = (
            self.delta_T_min_half
            if self.delta_T_min_half is not None else delta_T_min / 2
        )
        traslazione = -delta_half if self.tipo == "hot" else delta_half
        return self.T_in + traslazione, self.T_out + traslazione

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

    limiti_zone = sorted(
        {
            T_max,
            T_min,
            *pinch_HEN,
        },
        reverse=True,
    )

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

def costruisci_utilities_HEN(
    configurazione,
    debug=False,
):
    """
    Costruisce le utility termiche utilizzate nel modello HENS.

    Le utility devono essere definite nel JSON come:

        "hens": {
            "utilities": [
                {...},
                {...}
            ]
        }

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
            "La configurazione non contiene la sezione "
            "'hens'. Controllare il JSON oppure "
            "prepara_pinch()."
        )

    dati_hens = configurazione["hens"]

    if not isinstance(dati_hens, dict):
        raise ValueError(
            "La sezione 'hens' deve essere un dizionario."
        )


    # =================================================
    # 2. LETTURA UTILITIES HENS
    # =================================================

    if "utilities" not in dati_hens:
        raise ValueError(
            "La sezione 'hens' non contiene "
            "'utilities'."
        )

    dati_utilities = dati_hens["utilities"]

    if not isinstance(dati_utilities, list):
        raise ValueError(
            "'hens.utilities' deve essere una lista."
        )


    # =================================================
    # 3. CONTENITORE RISULTATI
    # =================================================

    utilities = {
        "hot": [],
        "cold": [],
    }

    codici = set()


    # =================================================
    # 4. COSTRUZIONE DELLE UTILITIES
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
                f"{dati['codice']}: {tipo}. "
                "Valori ammessi: 'hot', 'cold'."
            )


        # ---------------------------------------------
        # Creazione oggetto UtilityHEN
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
        # 5. CONTROLLI DI COERENZA
        # =================================================

        # Codici duplicati
        if utility.codice in codici:

            raise ValueError(
                f"Utility HENS duplicata: "
                f"{utility.codice}"
            )

        codici.add(
            utility.codice
        )


        # ---------------------------------------------
        # Coerenza temperatura HOT
        # ---------------------------------------------

        if (
            utility.tipo == "hot"
            and utility.T_in
            <= utility.T_out
        ):

            raise ValueError(
                f"La hot utility "
                f"{utility.codice} deve avere "
                f"T_in > T_out. "
                f"Ricevuto: "
                f"{utility.T_in} -> "
                f"{utility.T_out} °C"
            )


        # ---------------------------------------------
        # Coerenza temperatura COLD
        # ---------------------------------------------

        if (
            utility.tipo == "cold"
            and utility.T_out
            <= utility.T_in
        ):

            raise ValueError(
                f"La cold utility "
                f"{utility.codice} deve avere "
                f"T_out > T_in. "
                f"Ricevuto: "
                f"{utility.T_in} -> "
                f"{utility.T_out} °C"
            )


        # ---------------------------------------------
        # Coefficiente di scambio
        # ---------------------------------------------

        if utility.h_W_m2K <= 0:

            raise ValueError(
                f"h_W_m2K non valido per "
                f"{utility.codice}: "
                f"{utility.h_W_m2K}"
            )


        # ---------------------------------------------
        # Utility non disponibile
        # ---------------------------------------------

        if not utility.disponibile:

            if debug:
                print(
                    f"Utility HENS "
                    f"{utility.codice} ignorata: "
                    f"disponibile=False"
                )

            continue


        # ---------------------------------------------
        # Inserimento
        # ---------------------------------------------

        utilities[
            utility.tipo
        ].append(
            utility
        )


    # =================================================
    # 6. STAMPA DIAGNOSTICA
    # =================================================

    if debug:

        print(
            "\n"
            + "=" * 55
        )

        print(
            "UTILITY HENS COSTRUITE"
        )

        print(
            "=" * 55
        )

        for utility in utilities["hot"]:

            print(
                f"{utility.codice} | "
                f"HOT | "
                f"{utility.T_in:.2f} -> "
                f"{utility.T_out:.2f} °C | "
                f"h = "
                f"{utility.h_W_m2K:.2f} W/m²K"
            )

        for utility in utilities["cold"]:

            print(
                f"{utility.codice} | "
                f"COLD | "
                f"{utility.T_in:.2f} -> "
                f"{utility.T_out:.2f} °C | "
                f"h = "
                f"{utility.h_W_m2K:.2f} W/m²K"
            )

        print(
            f"\nNumero hot utilities: "
            f"{len(utilities['hot'])}"
        )

        print(
            f"Numero cold utilities: "
            f"{len(utilities['cold'])}"
        )


    return utilities