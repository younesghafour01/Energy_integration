import json
from pathlib import Path


from analisi_pinch import (
    Flusso,
    crea_cascata_termica,
    costruisci_curve_composite,
    costruisci_GCC,
    discretizza_GCC,
    genera_HPPr_candidate,
    costruisci_curva_utilities_HP,
    self_sufficient_pockets,
    grafico_TQ,
)
from modello_milp import (
    crea_modello_HPPr,
    risolvi_modello_HPPr,
)
# Percorso del JSON, nella stessa cartella di questo file.
PERCORSO_JSON = Path(__file__).with_name("dati_input.json")
CARTELLA_RISULTATI = ( Path(__file__).resolve().parent / "risultati")

def carica_caso_studio(percorso_json):
    """Legge il JSON e crea gli oggetti Flusso."""

    with percorso_json.open(
        mode="r",
        encoding="utf-8",
    ) as file:
        configurazione = json.load(file)

    nome_caso = configurazione["nome"]
    delta_T_min = configurazione["delta_T_min"]
    delta_T_max = configurazione["delta_T_max"]
    eta_ex = configurazione["eta_ex"]
    evaP = configurazione["evaP"]
    condP = configurazione["condP"]
    T_cond_max = configurazione["T_cond_max"]
    HP_max = configurazione["HP_max"]
    T0=configurazione["T0"]
    T_f=configurazione["T_f"]
    flussi = [
        Flusso(**dati_flusso)
        for dati_flusso in configurazione["flussi"]
    ]
    
    return nome_caso, delta_T_min, delta_T_max, eta_ex, evaP, condP, T_cond_max, HP_max, T0, T_f,  flussi


def esegui_prova():

    # 1. Lettura e verifica dell'input JSON__________________________________________________-


    nome_caso, delta_T_min, delta_T_max, eta_ex, evaP, condP, T_cond_max, HP_max, T0, T_f, flussi = carica_caso_studio(PERCORSO_JSON)

    print("=" * 65)
    print(f"CASO STUDIO: {nome_caso}")
    print(f"Delta T minimo: {delta_T_min:.2f} °C")
    print(f"Delta T massimo: {delta_T_max:.2f} °C")
    print(f"Numero di flussi caricati: {len(flussi)}")
    print("=" * 65)

    print("\n1. FLUSSI LETTI DAL JSON")

    for flusso in flussi:
        T_in_star, T_out_star = flusso.calcola_T_traslate(
            delta_T_min
        )

        print(
            f"{flusso.codice}: "
            f"tipo={flusso.tipo}, "
            f"T={flusso.T_in:.1f} -> {flusso.T_out:.1f} °C, "
            f"CP={flusso.CP:.2f} kW/K, "
            f"Q={flusso.calcola_Q():.2f} kW, "
            f"T*={T_in_star:.1f} -> {T_out_star:.1f} °C, "
            f"disponibile={flusso.disponibile}"
        )

    # 2. Cascata termica_____________________________________________________________________


    risultati, QH_min, QC_min, pinch_traslati = (
        crea_cascata_termica(
            flussi=flussi,
            delta_T_min=delta_T_min,
        )
    )

    print("\n2. CASCATA TERMICA")

    for riga in risultati:
        print(
            f"{riga['T_sup']:6.1f} -> "
            f"{riga['T_inf']:6.1f} °C | "
            f"CP hot={riga['CP_hot']:4.1f} | "
            f"CP cold={riga['CP_cold']:4.1f} | "
            f"ΔH={riga['delta_H']:7.1f} kW | "
            f"cascata finale="
            f"{riga['cascata_finale']:7.1f} kW"
        )

    print("\n3. RISULTATI ENERGETICI")
    print(f"QH,min = {QH_min:.2f} kW")
    print(f"QC,min = {QC_min:.2f} kW")
    print(f"Pinch traslati = {pinch_traslati}")

    for T_pinch_star in pinch_traslati:
        T_hot_pinch = T_pinch_star + delta_T_min / 2
        T_cold_pinch = T_pinch_star - delta_T_min / 2

        print(
            f"Pinch reale: "
            f"T hot = {T_hot_pinch:.2f} °C, "
            f"T cold = {T_cold_pinch:.2f} °C"
        )

    # 3. Composite Curves_______________________________________________________________

    hot_CC_traslata, cold_CC_traslata, hot_CC, cold_CC = (
        costruisci_curve_composite(
            risultati=risultati,
            QH_min=QH_min,
            QC_min=QC_min,
            delta_T_min=delta_T_min,
        )
    )

    # 4. GCC e self-sufficient pockets_______________________________________________________


    gcc = costruisci_GCC(
        risultati=risultati,
        QH_min=QH_min,
    )
    pinch_data = self_sufficient_pockets(
        gcc,
        delta_T_min,
    )

    main_pinch_points = pinch_data["main_pinch_points"]
    potential_pinch_points = pinch_data["potential_pinch_points"]
    pockets = pinch_data["pockets"]

    zone_GCC = discretizza_GCC(
    gcc,
    pinch_data,
    delta_T_max,
    )
    
    gcc_discretizzata = [ #questa versione della GCC discretizzata ha solo le coppie Q,T che serve per visualizzare il grafico
    punto
    for zona in zone_GCC
    for punto in zona
    ]

    HPPr_candidate = genera_HPPr_candidate(
    zone_GCC,
    eta_ex,
    evaP,
    condP,
    T_cond_max
    )

    (
    modello,
    BoolHPPr,
    FHPPr,
    Pprel,
    Papp,
    NHL,
    Pelec,
    TEC,
    FinalExergy,
    ) = crea_modello_HPPr(
    HPPr_candidate,
    zone_GCC,
    HP_max,
    T0,
    T_f,
    eta_ex,
    )

    risultati_milp = risolvi_modello_HPPr(
    modello,
    BoolHPPr,
    FHPPr,
    HPPr_candidate,
    TEC,
    FinalExergy,
    )
    curva_utilities = costruisci_curva_utilities_HP(
    risultati_milp["HP_selezionate"]
)
    #5 STAMPAGGI _________________________________________________________________________________________


    print("\n4. PUNTI DELLA GCC")

    print("\nMAIN PINCH POINTS")

    for punto in main_pinch_points:
        print(
            f"{punto['codice']}: "
            f"Q = {punto['Q_kW']:.2f} kW, "
            f"T* = {punto['T_traslata_C']:.2f} °C, "
            f"T hot = {punto['T_hot_C']:.2f} °C, "
            f"T cold = {punto['T_cold_C']:.2f} °C"
        )

    print("\nPOTENTIAL PINCH POINTS")

    if not potential_pinch_points:
        print("Nessun PPP individuato.")
    else:
        for punto in potential_pinch_points:
            print(
                f"{punto['codice']}: "
                f"Q = {punto['Q_kW']:.2f} kW, "
                f"T* = {punto['T_traslata_C']:.2f} °C, "
                f"T hot = {punto['T_hot_C']:.2f} °C, "
                f"T cold = {punto['T_cold_C']:.2f} °C, "
                f"posizione = {punto['posizione']}"
            )

    print("\nPUNTI COMPLETI DELLA GCC")

    for Q, T_star in gcc:
        print(
            f"Q = {Q:7.2f} kW | "
            f"T* = {T_star:7.2f} °C"
        )

    print(f"\nNumero di pocket: {len(pockets)}")

    print(f"Numero HPPr candidate: {len(HPPr_candidate)}")

    for hp in HPPr_candidate[:10]:
        print(hp)

    # 5. Creazione della cartella dei risultati____________________________________


    CARTELLA_RISULTATI.mkdir(
        parents=True,
        exist_ok=True,
    )

    print("\n5. RISULTATI MILP")

    print(
        f"TEC = "
        f"{risultati_milp['TEC_kW']:.3f} kW"
    )

    print(
        f"Final Exergy = "
        f"{risultati_milp['FinalExergy_kW']:.3f} kW"
    )

    print("\nHEAT PUMPS SELEZIONATE")

    if not risultati_milp["HP_selezionate"]:
        print("Nessuna heat pump selezionata.")

    else:

        for hp in risultati_milp["HP_selezionate"]:

            print(
                f"HP {hp['indice']} | "
                f"F={hp['FHPPr']:.4f} | "
                f"T evap={hp['T_evap_C']:.2f} °C | "
                f"T cond={hp['T_cond_C']:.2f} °C | "
                f"COP={hp['COP']:.3f} | "
                f"Q evap={hp['Q_evap_kW']:.3f} kW | "
                f"Q cond={hp['Q_cond_kW']:.3f} kW | "
                f"W={hp['P_elettrica_kW']:.3f} kW"
            )
    numero_intervalli = sum(
    len(zona) - 1
    for zona in zone_GCC
    )

    print(
        f"Numero intervalli GCC discretizzata: "
        f"{numero_intervalli}"
    )
    for z, zona in enumerate(zone_GCC, start=1):

        print(
            f"Zona {z}: "
            f"{len(zona) - 1} intervalli"
        )
    # 6. Generazione dei grafici_____________________________________________________-


    grafico_TQ(
        tipo_grafico="composite",
        hot_CC=hot_CC,
        cold_CC=cold_CC,
        percorso_salvataggio=(
            CARTELLA_RISULTATI
            / "composite_curves.png"
        ),
        mostra=False,
    )

    grafico_TQ(
        tipo_grafico="composite_traslate",
        hot_CC=hot_CC_traslata,
        cold_CC=cold_CC_traslata,
        percorso_salvataggio=(
            CARTELLA_RISULTATI
            / "composite_curves_temperature_traslate.png"
        ),
        mostra=False,
    )

    grafico_TQ(
        tipo_grafico="gcc",
        gcc=gcc,
        percorso_salvataggio=(
            CARTELLA_RISULTATI
            / "grand_composite_curve.png"
        ),
        mostra=False,
    )

    grafico_TQ(
        tipo_grafico="pockets",
        gcc=gcc,
        pockets=pockets,
        pinch_data=pinch_data,
        percorso_salvataggio=(
            CARTELLA_RISULTATI
            / "self_sufficient_pockets.png"
        ),
        mostra=False,
    )
    grafico_TQ(
    tipo_grafico="gcc",
    gcc=gcc_discretizzata,
    percorso_salvataggio="risultati/gcc_discretizzata.png",
    mostra=False,
    )

    grafico_TQ(
    tipo_grafico="icc",
    gcc=gcc,
    utility_curve=curva_utilities,
    percorso_salvataggio=(
        CARTELLA_RISULTATI
        / "integrated_composite_curve.png"
    ),
    mostra=False,
)
if __name__ == "__main__":
    esegui_prova()


    