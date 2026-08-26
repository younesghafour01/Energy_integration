from __future__ import annotations

import time

from pathlib import Path

from src.hens.BAR05_hens import (
    prepara_HENS_TRA15 as prepara_HENS_TRA15_base,
    risolvi_HEN as risolvi_HEN_base,
)

ALL_BLOCKS = {
    "1",
    "2",
    "3A",
    "3B",
    "3C",
    "3D",
    "4A",
    "4B",
    "4C",
    "4D",
    "4E",
    "4F",
    "5A",
    "5B",
    "7",
}


# ============================================================
# FUNZIONI DI SUPPORTO
# ============================================================

def _modello(preparazione):
    return preparazione["modello_HEN"]["modello"]


def _q(preparazione):
    return preparazione["modello_HEN"]["q"]


def _valore(var):
    try:
        return float(var.solution_value)
    except Exception:
        try:
            return float(var)
        except Exception:
            return None


def _trova_vincolo(modello, nome):

    try:
        vincolo = modello.get_constraint_by_name(nome)

        if vincolo is not None:
            return vincolo

    except Exception:
        pass

    for vincolo in modello.iter_constraints():

        if getattr(vincolo, "name", None) == nome:
            return vincolo

    return None


# ============================================================
# PROCESS STREAMS SOGGETTE A NON-ISOTHERMAL MIXING
# ============================================================

def individua_stream_NI_TRA15(preparazione):
    """
    Attiva il non-isothermal mixing su tutte le process streams.

    Riproduce il comportamento del vecchio
    test_TRA15_free_NI_hot_cold_v2.py.
    """

    insiemi = preparazione["insiemi_HEN"]

    NIH = set()
    NIC = set()

    for z in insiemi["Z"]:

        NIH.update(
            set(insiemi["H"][z])
            - set(insiemi["HU"][z])
        )

        NIC.update(
            set(insiemi["C"][z])
            - set(insiemi["CU"][z])
        )

    return sorted(NIH), sorted(NIC)


# ============================================================
# GRUPPI q PER INTERVALLO
# ============================================================

def _costruisci_gruppi_q_TRA15(preparazione):

    mdl = _modello(preparazione)
    q = _q(preparazione)

    gruppi_hot = {}
    gruppi_cold = {}

    for indice, variabile in q.items():

        z, i, m, j, n = indice[:5]

        gruppi_hot.setdefault(
            (int(z), str(i), int(m)),
            [],
        ).append(variabile)

        gruppi_cold.setdefault(
            (int(z), str(j), int(n)),
            [],
        ).append(variabile)

    q_hot = {
        chiave: mdl.sum(variabili)
        for chiave, variabili
        in gruppi_hot.items()
    }

    q_cold = {
        chiave: mdl.sum(variabili)
        for chiave, variabili
        in gruppi_cold.items()
    }

    return q_hot, q_cold


# ============================================================
# NON-ISOTHERMAL MIXING - BAR05 EQ. (7)-(10)
# ============================================================

def aggiungi_non_isothermal_mixing_TRA15(
    preparazione,
    NIH,
    NIC,
):
    """
    Implementa il non-isothermal mixing utilizzato nella
    precedente validazione TRA15.

    Equazioni:
        hot  : BAR05 Eq. (7) e (9)
        cold : BAR05 Eq. (8) e (10)

    I bilanci isotermi originali vengono rimossi esclusivamente
    per le stream appartenenti a NIH/NIC.
    """

    mdl = _modello(preparazione)

    insiemi = preparazione["insiemi_HEN"]

    delta_H_H = dict(
        preparazione["delta_H_HEN"]["delta_H_H"]
    )

    delta_H_C = dict(
        preparazione["delta_H_HEN"]["delta_H_C"]
    )

    q_hot, q_cold = _costruisci_gruppi_q_TRA15(
        preparazione
    )

    qbar_H = {}
    qbar_C = {}

    mancanti = []

    vincoli_hot_rimossi = 0
    vincoli_cold_rimossi = 0

    # ========================================================
    # HOT STREAMS
    # ========================================================

    intervalli_hot = {}

    for z in insiemi["Z"]:

        for i in NIH:

            if i not in insiemi["H"][z]:
                continue

            if i in insiemi["HU"][z]:
                continue

            intervalli = sorted(
                m
                for m in insiemi["M_i"][z, i]
                if (z, i, m) in delta_H_H
                and float(delta_H_H[z, i, m]) > 1e-12
            )

            intervalli_hot[z, i] = intervalli

            # Rimuove i vecchi bilanci isotermi.
            for m in intervalli:

                nome = f"bil_HP_z{z}_{i}_m{m}"

                vincolo = _trova_vincolo(
                    mdl,
                    nome,
                )

                if vincolo is None:

                    mancanti.append(nome)

                else:

                    mdl.remove_constraint(
                        vincolo
                    )

                    vincoli_hot_rimossi += 1

            # Variabili qbar canoniche a < b.
            for indice_a, a in enumerate(intervalli):

                for b in intervalli[indice_a + 1:]:

                    qbar_H[z, i, a, b] = (
                        mdl.continuous_var(
                            lb=0,
                            name=(
                                f"NI_qbarH_"
                                f"{z}_{i}_{a}_{b}"
                            ),
                        )
                    )

    # ========================================================
    # COLD STREAMS
    # ========================================================

    intervalli_cold = {}

    for z in insiemi["Z"]:

        for j in NIC:

            if j not in insiemi["C"][z]:
                continue

            if j in insiemi["CU"][z]:
                continue

            intervalli = sorted(
                n
                for n in insiemi["N_j"][z, j]
                if (z, j, n) in delta_H_C
                and float(delta_H_C[z, j, n]) > 1e-12
            )

            intervalli_cold[z, j] = intervalli

            for n in intervalli:

                nome = f"bil_CP_z{z}_{j}_n{n}"

                vincolo = _trova_vincolo(
                    mdl,
                    nome,
                )

                if vincolo is None:

                    mancanti.append(nome)

                else:

                    mdl.remove_constraint(
                        vincolo
                    )

                    vincoli_cold_rimossi += 1

            for indice_a, a in enumerate(intervalli):

                for b in intervalli[indice_a + 1:]:

                    qbar_C[z, j, a, b] = (
                        mdl.continuous_var(
                            lb=0,
                            name=(
                                f"NI_qbarC_"
                                f"{z}_{j}_{a}_{b}"
                            ),
                        )
                    )

    if mancanti:

        raise RuntimeError(
            "Bilanci originali mancanti: "
            + repr(mancanti[:20])
        )

    # ========================================================
    # EQ. (7) e (9) - HOT
    # ========================================================

    n7 = 0
    n9 = 0

    for (z, i), intervalli in intervalli_hot.items():

        for m in intervalli:

            incoming = [
                qbar_H[z, i, m, b]
                for b in intervalli
                if b > m
                and (z, i, m, b) in qbar_H
            ]

            outgoing = [
                qbar_H[z, i, a, m]
                for a in intervalli
                if a < m
                and (z, i, a, m) in qbar_H
            ]

            q_esterno = q_hot.get(
                (int(z), str(i), int(m)),
                0,
            )

            mdl.add_constraint(
                float(delta_H_H[z, i, m])
                == (
                    q_esterno
                    + mdl.sum(incoming)
                    - mdl.sum(outgoing)
                ),
                ctname=f"NI_BAR05_7_{z}_{i}_{m}",
            )

            n7 += 1

            mdl.add_constraint(
                mdl.sum(outgoing)
                <= q_esterno,
                ctname=f"NI_BAR05_9_{z}_{i}_{m}",
            )

            n9 += 1

    # ========================================================
    # EQ. (8) e (10) - COLD
    # ========================================================

    n8 = 0
    n10 = 0

    for (z, j), intervalli in intervalli_cold.items():

        for n in intervalli:

            incoming = [
                qbar_C[z, j, a, n]
                for a in intervalli
                if a < n
                and (z, j, a, n) in qbar_C
            ]

            outgoing = [
                qbar_C[z, j, n, b]
                for b in intervalli
                if b > n
                and (z, j, n, b) in qbar_C
            ]

            q_esterno = q_cold.get(
                (int(z), str(j), int(n)),
                0,
            )

            mdl.add_constraint(
                float(delta_H_C[z, j, n])
                == (
                    q_esterno
                    + mdl.sum(incoming)
                    - mdl.sum(outgoing)
                ),
                ctname=f"NI_BAR05_8_{z}_{j}_{n}",
            )

            n8 += 1

            mdl.add_constraint(
                mdl.sum(outgoing)
                <= q_esterno,
                ctname=f"NI_BAR05_10_{z}_{j}_{n}",
            )

            n10 += 1

    informazioni = {

        "NIH": list(NIH),
        "NIC": list(NIC),

        "qbar_H": qbar_H,
        "qbar_C": qbar_C,

        "removed_hot":
            vincoli_hot_rimossi,

        "removed_cold":
            vincoli_cold_rimossi,

        "n_qbarH":
            len(qbar_H),

        "n_qbarC":
            len(qbar_C),

        "eq7": n7,
        "eq9": n9,
        "eq8": n8,
        "eq10": n10,
    }

    preparazione[
        "non_isothermal_mixing_TRA15"
    ] = informazioni

    return informazioni


# ============================================================
# PREPARAZIONE COMPLETA TRA15
# ============================================================

def prepara_HENS_TRA15(
    sorgente,
    delta_T_partition_max=2.5,
    numero_intervalli_min=1,
    separa_al_pinch=False,
    non_isothermal_mixing=True,
):
    """
    Costruisce il modello TRA15 utilizzato nella precedente
    validazione dei Test 1 e Test 2.

    Default storici:
        delta_T_partition_max = 2.5 °C
        numero_intervalli_min = 1
        separa_al_pinch = False
        FULL non-isothermal mixing
    """

    preparazione = prepara_HENS_TRA15_base(
        sorgente,

        delta_T_partition_max=
            float(delta_T_partition_max),

        numero_intervalli_min=
            int(numero_intervalli_min),

        separa_al_pinch=
            bool(separa_al_pinch),

        bar05_blocchi=
            set(ALL_BLOCKS),
    )

    if non_isothermal_mixing:

        NIH, NIC = individua_stream_NI_TRA15(
            preparazione
        )

        aggiungi_non_isothermal_mixing_TRA15(
            preparazione,
            NIH,
            NIC,
        )

    return preparazione


# ============================================================
# SOLUZIONE
# ============================================================
def risolvi_HENS_TRA15(
    preparazione,
    log_output=False,
    time_limit_s=10800,
    mip_gap=1e-7,
    threads=1,
):
    """
    Risolve il modello TRA15 con il core comune BAR05/TRA15.

    La preparazione contiene già le Eq. (7)-(10) di non-isothermal
    mixing aggiunte da aggiungi_non_isothermal_mixing_TRA15().
    """

    mdl = _modello(preparazione)

    try:
        mdl.parameters.threads = int(threads)
        mdl.parameters.randomseed = 20260823

        mdl.parameters.mip.tolerances.mipgap = float(mip_gap)
        mdl.parameters.mip.tolerances.absmipgap = float(mip_gap)

        mdl.parameters.timelimit = float(time_limit_s)

    except Exception:
        pass

    # Usa il solver/estrattore completo già presente nel core.
    risultati = risolvi_HEN_base(
        preparazione,
        log_output=log_output,
        tolleranza=1e-6,
    )

    # Alias comodi specifici TRA15.
    risultati["feasible"] = True

    risultati["TAC_kUSD_year"] = (
        risultati["TAC_USD_year"] / 1000.0
    )

    risultati["HU_kW"] = (
        risultati["hot_utility_totale_kW"]
    )

    risultati["CU_kW"] = (
        risultati["cold_utility_totale_kW"]
    )

    risultati["gap"] = risultati.get(
        "gap_CPLEX",
        0.0,
    )

    risultati["tempo_solve_s"] = risultati.get(
        "tempo_CPLEX_s",
        0.0,
    )

    return risultati

# ============================================================
# ESTRAZIONE RISULTATI
# ============================================================

def estrai_risultati_TRA15(
    preparazione,
):

    mdl = _modello(preparazione)

    insiemi = preparazione[
        "insiemi_HEN"
    ]

    q = _q(preparazione)

    try:
        TAC_USD_year = float(
            mdl.objective_value
        )
    except Exception:
        TAC_USD_year = float(
            mdl.objective_expr.solution_value
        )

    HU = 0.0
    CU = 0.0

    carico_termico_match = {}

    for indice, variabile in q.items():

        z, i, m, j, n = indice[:5]

        valore = _valore(variabile)

        if valore is None:
            continue

        if i in insiemi["HU"][z]:
            HU += valore

        if j in insiemi["CU"][z]:
            CU += valore

        chiave = f"{i}-{j}"

        carico_termico_match[chiave] = (
            carico_termico_match.get(
                chiave,
                0.0,
            )
            + valore
        )

    carico_termico_match = {
        chiave: valore
        for chiave, valore
        in sorted(carico_termico_match.items())
        if abs(valore) > 1e-6
    }

    return {
        "TAC_USD_year":
            TAC_USD_year,

        "TAC_kUSD_year":
            TAC_USD_year / 1000.0,

        "HU_kW":
            HU,

        "CU_kW":
            CU,

        "duties_kW":
            carico_termico_match,
    }


# ============================================================
# STAMPA
# ============================================================
def stampa_risultati_TRA15(risultati):

    separatore = "=" * 80

    def titolo(nome):
        print(f"\n{separatore}")
        print(nome)
        print(separatore)

    def temp(x):
        if x is None:
            return "n.d."
        return f"{x:.3f}"

    # ========================================================
    # MODELLO
    # ========================================================

    titolo("MODELLO HENS TRA15")

    print(
        f"Status CPLEX: "
        f"{risultati.get('status')}"
    )

    print(
        f"Gap: "
        f"{risultati.get('gap_CPLEX', 0.0):.6e}"
    )

    print(
        f"Zone: "
        f"{risultati.get('numero_zone')}"
    )

    print(
        f"Intervalli: "
        f"{risultati.get('numero_intervalli')}"
    )

    print(
        f"Variabili totali: "
        f"{risultati.get('numero_variabili')}"
    )

    print(
        f"Variabili binarie: "
        f"{risultati.get('numero_binarie')}"
    )

    print(
        f"Vincoli: "
        f"{risultati.get('numero_vincoli')}"
    )

    print(
        f"Tempo solve: "
        f"{risultati.get('tempo_CPLEX_s', 0.0):.3f} s"
    )

    # ========================================================
    # ECONOMIA
    # ========================================================

    titolo("ECONOMIA")

    print(
        f"Costo HU: "
        f"{risultati['costo_HU_USD_year']:,.2f} USD/year"
    )

    print(
        f"Costo CU: "
        f"{risultati['costo_CU_USD_year']:,.2f} USD/year"
    )

    print(
        f"Costo fisso HEX: "
        f"{risultati['costo_fisso_HEX_USD_year']:,.2f} USD/year"
    )

    print(
        f"Costo area HEX: "
        f"{risultati['costo_area_HEX_USD_year']:,.2f} USD/year"
    )

    print(
        f"TAC: "
        f"{risultati['TAC_USD_year']:,.2f} USD/year"
    )

    print(
        f"TAC: "
        f"{risultati['TAC_USD_year']/1000.0:.6f} "
        f"kUSD/year"
    )

    # ========================================================
    # UTILITIES
    # ========================================================

    titolo("UTILITIES")

    print(
        f"HU totale: "
        f"{risultati['hot_utility_totale_kW']:.6f} kW"
    )

    print(
        f"CU totale: "
        f"{risultati['cold_utility_totale_kW']:.6f} kW"
    )

    # ========================================================
    # RETE
    # ========================================================

    titolo("RETE HEN")

    scambiatori = sorted(
        risultati["scambiatori_fisici"],
        key=lambda x: (
            x["hot"],
            x["cold"],
            x["zona"],
            x.get("exchanger_id", 1),
        ),
    )

    area_totale = sum(
        x["area_m2"]
        for x in scambiatori
    )

    print(
        f"Numero exchanger: "
        f"{risultati['numero_exchanger_fisici']}"
    )

    print(
        f"Numero shell: "
        f"{risultati['numero_shell_fisiche']:.0f}"
    )

    print(
        f"Area totale: "
        f"{area_totale:.3f} m²"
    )

    for x in scambiatori:

        print(
            f"{x['hot']}-{x['cold']} | "
            f"{x['tecnologia']} | "
            f"z={x['zona']} | "
            f"Q={x['carico_termico_kW']:.3f} kW | "
            f"A={x['area_m2']:.3f} m² | "
            f"U={x['U']:.0f} | "
            f"Th: "
            f"{temp(x.get('hot_Tin_C'))} -> "
            f"{temp(x.get('hot_Tout_C'))} °C | "
            f"Tc: "
            f"{temp(x.get('cold_Tin_C'))} -> "
            f"{temp(x.get('cold_Tout_C'))} °C"
        )

    # ========================================================
    # carico_termico AGGREGATI
    # ========================================================

    titolo("CARICHI TERMICI AGGREGATI PER MATCH")

    carico_termico = {}

    for x in scambiatori:

        key = (
            x["hot"],
            x["cold"],
        )

        carico_termico[key] = (
            carico_termico.get(key, 0.0)
            + x["carico_termico_kW"]
        )

    for (hot, cold), q in sorted(
        carico_termico.items()
    ):
        print(
            f"{hot}-{cold} = "
            f"{q:.6f} kW"
        )

    # ========================================================
    # TEMPERATURE
    # ========================================================

    titolo("TEMPERATURE INTERNE DELLA RETE")

    print(
        f"{'Match':<12}"
        f"{'Th,in':>12}"
        f"{'Th,out':>12}"
        f"{'Tc,in':>12}"
        f"{'Tc,out':>12}"
    )

    for x in scambiatori:

        print(
            f"{x['hot']+'-'+x['cold']:<12}"
            f"{temp(x.get('hot_Tin_C')):>12}"
            f"{temp(x.get('hot_Tout_C')):>12}"
            f"{temp(x.get('cold_Tin_C')):>12}"
            f"{temp(x.get('cold_Tout_C')):>12}"
        )

    # ========================================================
    # BILANCIO
    # ========================================================

    titolo("BILANCIO ENERGETICO")

    print(
        f"Hot process: "
        f"{risultati['calore_hot_process_totale_kW']:.6f} kW"
    )

    print(
        f"Cold process: "
        f"{risultati['calore_cold_process_totale_kW']:.6f} kW"
    )

    print(
        f"HU: "
        f"{risultati['hot_utility_totale_kW']:.6f} kW"
    )

    print(
        f"CU: "
        f"{risultati['cold_utility_totale_kW']:.6f} kW"
    )

    print(
        f"Residuo globale: "
        f"{risultati['residuo_bilancio_energia_kW']:+.6e} kW"
    )

def salva_validazione_TRA15_test1(
    preparazione,
    risultati,
    percorso_file,
):
    """
    Salva il confronto automatico tra la soluzione simulata
    e il Test 1 pubblicato in Tran et al. 2015.
    """

    benchmark_TAC = 181.0
    benchmark_HU = 204.0
    benchmark_CU = 182.0

    benchmark = {
        ("H3", "C1"): {
            "Q": 204.0,
            "Th_in": 180.0,
            "Th_out": 179.0,
            "Tc_in": 117.0,
            "Tc_out": 155.0,
        },

        ("H1", "C3"): {
            "Q": 182.0,
            "Th_in": 110.0,
            "Th_out": 45.0,
            "Tc_in": 15.0,
            "Tc_out": 25.0,
        },

        ("H1", "C1"): {
            "Q": 85.0,
            "Th_in": 175.0,
            "Th_out": 145.0,
            "Tc_in": 105.0,
            "Tc_out": 117.0,
        },

        ("H1", "C2"): {
            "Q": 94.0,
            "Th_in": 145.0,
            "Th_out": 110.0,
            "Tc_in": 89.0,
            "Tc_out": 112.0,
        },

        ("H2", "C1"): {
            "Q": 461.0,
            "Th_in": 125.0,
            "Th_out": 65.0,
            "Tc_in": 20.0,
            "Tc_out": 105.0,
        },

        ("H2", "C2"): {
            "Q": 206.0,
            "Th_in": 125.0,
            "Th_out": 65.0,
            "Tc_in": 40.0,
            "Tc_out": 89.0,
        },
    }

    scambiatori = risultati[
        "scambiatori_fisici"
    ]

    simulati = {
        (x["hot"], x["cold"]): x
        for x in scambiatori
        if x["carico_termico_kW"] > 1e-7
    }

    righe = []

    def scrivi(testo=""):
        righe.append(testo)

    def errore_percentuale(sim, ref):
        if abs(ref) <= 1e-12:
            return 0.0

        return (
            100.0
            * (sim - ref)
            / ref
        )

    scrivi("=" * 110)
    scrivi("VALIDAZIONE TRA15 - TEST 1")
    scrivi("=" * 110)

    # ========================================================
    # RISULTATO GENERALE
    # ========================================================

    TAC_sim = (
        risultati["TAC_USD_year"]
        / 1000.0
    )

    HU_sim = risultati[
        "hot_utility_totale_kW"
    ]

    CU_sim = risultati[
        "cold_utility_totale_kW"
    ]

    scrivi("\nRISULTATI GLOBALI")
    scrivi("-" * 80)

    scrivi(
        f"{'Grandezza':<25}"
        f"{'TRA15':>15}"
        f"{'Modello':>15}"
        f"{'Delta':>15}"
        f"{'Errore %':>15}"
    )

    dati_globali = [
        (
            "TAC [kUSD/y]",
            benchmark_TAC,
            TAC_sim,
        ),
        (
            "HU [kW]",
            benchmark_HU,
            HU_sim,
        ),
        (
            "CU [kW]",
            benchmark_CU,
            CU_sim,
        ),
    ]

    for nome, ref, sim in dati_globali:

        scrivi(
            f"{nome:<25}"
            f"{ref:>15.6f}"
            f"{sim:>15.6f}"
            f"{sim-ref:>+15.6f}"
            f"{errore_percentuale(sim,ref):>+15.4f}"
        )

    # ========================================================
    # TOPOLOGIA
    # ========================================================

    topologia_fonte = set(
        benchmark.keys()
    )

    topologia_modello = set(
        simulati.keys()
    )

    mancanti = (
        topologia_fonte
        - topologia_modello
    )

    aggiuntivi = (
        topologia_modello
        - topologia_fonte
    )

    scrivi("\nTOPOLOGIA")
    scrivi("-" * 80)

    scrivi(
        f"HEX fonte   : "
        f"{len(topologia_fonte)}"
    )

    scrivi(
        f"HEX modello : "
        f"{len(topologia_modello)}"
    )

    scrivi(
        "Match mancanti: "
        + (
            ", ".join(
                f"{h}-{c}"
                for h, c in sorted(mancanti)
            )
            if mancanti
            else "nessuno"
        )
    )

    scrivi(
        "Match aggiuntivi: "
        + (
            ", ".join(
                f"{h}-{c}"
                for h, c in sorted(aggiuntivi)
            )
            if aggiuntivi
            else "nessuno"
        )
    )

    scrivi(
        "Esito topologia: "
        + (
            "OK - IDENTICA"
            if not mancanti
            and not aggiuntivi
            else "DIFFERENTE"
        )
    )

    # ========================================================
    # CARICHI TERMICI
    # ========================================================

    scrivi("\nCARICO TERMICO PER EXCHANGER")
    scrivi("-" * 90)

    scrivi(
        f"{'Match':<12}"
        f"{'TRA15 [kW]':>16}"
        f"{'Modello [kW]':>16}"
        f"{'Delta [kW]':>16}"
        f"{'Errore %':>16}"
    )

    errori_carico_termico = []

    for match, ref in benchmark.items():

        sim = simulati.get(match)

        Q_sim = (
            0.0
            if sim is None
            else sim["carico_termico_kW"]
        )

        errore = abs(
            Q_sim - ref["Q"]
        )

        errori_carico_termico.append(
            errore
        )

        scrivi(
            f"{match[0]+'-'+match[1]:<12}"
            f"{ref['Q']:>16.3f}"
            f"{Q_sim:>16.3f}"
            f"{Q_sim-ref['Q']:>+16.3f}"
            f"{errore_percentuale(Q_sim,ref['Q']):>+16.3f}"
        )

    MAE_carico_termico = (
        sum(errori_carico_termico)
        / len(errori_carico_termico)
    )

    scrivi(
        f"\nMAE carico_termico = "
        f"{MAE_carico_termico:.6f} kW"
    )

    # ========================================================
    # TEMPERATURE
    # ========================================================

    scrivi("\nTEMPERATURE INTERNE")
    scrivi("-" * 125)

    scrivi(
        f"{'Match':<10}"
        f"{'Th,in src':>12}"
        f"{'Th,in sim':>12}"
        f"{'Th,out src':>13}"
        f"{'Th,out sim':>13}"
        f"{'Tc,in src':>12}"
        f"{'Tc,in sim':>12}"
        f"{'Tc,out src':>13}"
        f"{'Tc,out sim':>13}"
    )

    errori_T = []

    for match, ref in benchmark.items():

        sim = simulati.get(match)

        if sim is None:
            continue

        coppie = [
            (
                "hot_Tin_C",
                ref["Th_in"],
            ),
            (
                "hot_Tout_C",
                ref["Th_out"],
            ),
            (
                "cold_Tin_C",
                ref["Tc_in"],
            ),
            (
                "cold_Tout_C",
                ref["Tc_out"],
            ),
        ]

        for campo, riferimento in coppie:

            valore = sim.get(campo)

            if valore is not None:
                errori_T.append(
                    abs(
                        valore
                        - riferimento
                    )
                )

        scrivi(
            f"{match[0]+'-'+match[1]:<10}"
            f"{ref['Th_in']:>12.3f}"
            f"{sim.get('hot_Tin_C', float('nan')):>12.3f}"
            f"{ref['Th_out']:>13.3f}"
            f"{sim.get('hot_Tout_C', float('nan')):>13.3f}"
            f"{ref['Tc_in']:>12.3f}"
            f"{sim.get('cold_Tin_C', float('nan')):>12.3f}"
            f"{ref['Tc_out']:>13.3f}"
            f"{sim.get('cold_Tout_C', float('nan')):>13.3f}"
        )

    if errori_T:

        MAE_T = (
            sum(errori_T)
            / len(errori_T)
        )

        scrivi(
            f"\nMAE temperature = "
            f"{MAE_T:.6f} °C"
        )

    # ========================================================
    # AREA
    # ========================================================

    area_totale = sum(
        x["area_m2"]
        for x in scambiatori
    )

    scrivi("\nAREA")
    scrivi("-" * 80)

    scrivi(
        f"Area totale modello = "
        f"{area_totale:.3f} m²"
    )

    scrivi(
        "Area totale fonte   = "
        "NON RIPORTATA nel paper TRA15"
    )

    scrivi(
        "Validazione area     = "
        "NON DISPONIBILE"
    )

    # ========================================================
    # DIMENSIONE MILP
    # ========================================================

    scrivi("\nDIMENSIONE DEL PROBLEMA")
    scrivi("-" * 80)

    scrivi(
        f"Intervalli modello = "
        f"{risultati['numero_intervalli']}"
    )

    scrivi(
        f"Variabili totali   = "
        f"{risultati['numero_variabili']}"
    )

    scrivi(
        f"Variabili binarie  = "
        f"{risultati['numero_binarie']}"
    )

    scrivi(
        f"Vincoli             = "
        f"{risultati['numero_vincoli']}"
    )

    scrivi(
        "Dimensione fonte    = "
        "NON RIPORTATA nel paper TRA15"
    )

    # ========================================================
    # BILANCIO
    # ========================================================

    scrivi("\nBILANCIO ENERGETICO")
    scrivi("-" * 80)

    scrivi(
        f"Residuo globale = "
        f"{risultati['residuo_bilancio_energia_kW']:+.6e} kW"
    )

    scrivi("\n" + "=" * 110)

    testo = "\n".join(
        righe
    )

    percorso_file = Path(
        percorso_file
    )

    percorso_file.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    percorso_file.write_text(
        testo,
        encoding="utf-8",
    )

    return testo
# Alias semplice per esegui.py
risolvi_HEN_TRA15 = risolvi_HENS_TRA15