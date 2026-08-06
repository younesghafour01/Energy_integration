import json
from pathlib import Path

from analisi_pinch import (
    Flusso,
    crea_cascata_termica,
    costruisci_curve_composite,
    riporta_curve_composite_a_temperature_reali,
    costruisci_GCC,
    self_sufficient_pockets,
    grafico_TQ,
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

    flussi = [
        Flusso(**dati_flusso)
        for dati_flusso in configurazione["flussi"]
    ]

    return nome_caso, delta_T_min, flussi


def esegui_prova():
    # 1. Lettura e verifica dell'input JSON
    nome_caso, delta_T_min, flussi = carica_caso_studio(PERCORSO_JSON)

    print("=" * 65)
    print(f"CASO STUDIO: {nome_caso}")
    print(f"Delta T minimo: {delta_T_min:.2f} °C")
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

    # 2. Cascata termica
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

    # 3. Composite Curves
    hot_CC_traslata, cold_CC_traslata = (
        costruisci_curve_composite(
            risultati=risultati,
            QH_min=QH_min,
        )
    )

    hot_CC, cold_CC = (
        riporta_curve_composite_a_temperature_reali(
            hot_CC_traslata=hot_CC_traslata,
            cold_CC_traslata=cold_CC_traslata,
            delta_T_min=delta_T_min,
        )
    )

    # 4. GCC e self-sufficient pockets
    gcc = costruisci_GCC(
        risultati=risultati,
        QH_min=QH_min,
    )

    pockets = self_sufficient_pockets(gcc)

    print("\n4. PUNTI DELLA GCC")

    for Q, T_star in gcc:
        print(
            f"Q = {Q:7.2f} kW | "
            f"T* = {T_star:7.2f} °C"
        )

    print(f"\nNumero di pocket: {len(pockets)}")

    # 5. Grafici
    
    grafico_TQ(
    tipo_grafico="composite",
    hot_CC=hot_CC,
    cold_CC=cold_CC,
    percorso_salvataggio=(
        CARTELLA_RISULTATI / "composite_curves.png"
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
            CARTELLA_RISULTATI / "grand_composite_curve.png"
        ),
        mostra=False,
    )

    grafico_TQ(
        tipo_grafico="pockets",
        gcc=gcc,
        pockets=pockets,
        percorso_salvataggio=(
            CARTELLA_RISULTATI / "self_sufficient_pockets.png"
        ),
        mostra=False,
    )


if __name__ == "__main__":
    esegui_prova()


    