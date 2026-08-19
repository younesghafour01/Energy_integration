from pathlib import Path
import sys
import integrazione_energetica as ie

# Cartella in cui si trova esegui.py.
BASE = Path(__file__).resolve().parent


def main():
    """
    Avvia una delle due modalità disponibili:
    utilities -> Pinch Analysis + utility predesign
    hens      -> Heat Exchanger Network Synthesis
    """
    # Controlla che siano stati forniti almeno:
    # file JSON + modalità di esecuzione.
    if len(sys.argv) < 3:
        raise SystemExit(
            "Uso: python esegui.py FILE.json [utilities|hens] [--log-cplex]"
        )

    # Legge il percorso del file JSON.
    percorso = Path(sys.argv[1])

    # Se il percorso è relativo, lo riferisce alla cartella del progetto.
    if not percorso.is_absolute():
        percorso = BASE / percorso

    # Legge la modalità scelta da terminale.
    modalita = sys.argv[2].lower()

    # Flag opzionale per mostrare il log dettagliato di CPLEX.
    log_output = "--log-cplex" in sys.argv[3:]

    # --------------------------------------------------------
    # PINCH ANALYSIS + UTILITY PREDESIGN
    # --------------------------------------------------------
    if modalita == "utilities":

        # Esegue la Pinch Analysis e costruisce CC, GCC,
        # MPP, PPP e self-sufficient pockets.
        dati_pinch = ie.esegui_analisi_pinch(percorso)

        # Discretizza la GCC, costruisce il MILP,
        # lo risolve con CPLEX e ricostruisce la GCC aggiornata.
        risultati = ie.esegui_predesign_utilities(
            dati_pinch,
            log_output=log_output,
        )

        # Stampa i principali risultati numerici.
        ie.stampa_risultati_milp(risultati)

        # Salva tutti i grafici nella cartella risultati/<nome_json>.
        ie.salva_grafici(
            dati_pinch,
            risultati,
            BASE / "risultati" / percorso.stem,
        )

    # --------------------------------------------------------
    # HEAT EXCHANGER NETWORK SYNTHESIS
    # --------------------------------------------------------
    elif modalita == "hens":

        # Costruisce il modello HENS.
        preparazione = ie.prepara_HEN(percorso)

        # Risolve il modello HENS con CPLEX.
        risultati = ie.risolvi_HEN(
            preparazione,
            log_output=log_output,
        )

        # Stampa i risultati della rete di scambiatori.
        ie.stampa_risultati_HEN(risultati)

    else:
        raise SystemExit(
            "Modalità non valida. Usa 'utilities' oppure 'hens'."
        )


# Esegue main() solo quando esegui.py viene lanciato direttamente.
if __name__ == "__main__":
    main()