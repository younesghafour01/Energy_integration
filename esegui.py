from pathlib import Path
import sys

from integrazione_energetica import (
    esegui_milp,
    prepara_modello_HEN,
    prepara_pinch,
    risolvi_HEN,
    salva_grafici,
    stampa_risultati_HEN,
    stampa_risultati_milp,
)

BASE = Path(__file__).resolve().parent


def risolvi_caso_HEN(percorso, log_output=False):
    preparazione = prepara_modello_HEN(percorso)
    risultati = risolvi_HEN(preparazione, log_output=log_output)
    stampa_risultati_HEN(risultati)
    return risultati


def regressione_HEN(log_output=False):
    risultati = {}
    for numero in range(1, 5):
        percorso = BASE / f"dati_input_hens_test{numero}.json"
        print(f"\nHENS TEST {numero}")
        risultati[numero] = risolvi_caso_HEN(percorso, log_output=log_output)

    t1, t2, t3, t4 = (risultati[n] for n in range(1, 5))
    print("\nDIAGNOSTICA REGRESSIONE")
    print(f"Test 1 vicino alla baseline 179.210: {t1['TAC_USD_year'] / 1000:.3f}")
    print(f"T2 disponibile su: {t2['matches_per_tecnologia'].get('T2', [])}")
    selezione_T2 = any(x["tecnologia"] == "T2" for x in t2["scambiatori_fisici"])
    print(f"T2 selezionata nel Test 2: {selezione_T2}")
    print(f"TAC Test 2 < Test 1: {t2['TAC_USD_year'] < t1['TAC_USD_year']}")
    print(
        "Tout H1 Test 3/Test 4: "
        f"{t3['flexible_streams'][0]['T_out_ottima_C']:.3f}/"
        f"{t4['flexible_streams'][0]['T_out_ottima_C']:.3f} C"
    )
    for numero, dati in risultati.items():
        chiude = abs(dati["residuo_bilancio_energia_kW"]) <= 1e-6
        print(f"Bilancio Test {numero}: {'OK' if chiude else 'NON CHIUSO'}")


def main():
    if len(sys.argv) < 2:
        raise SystemExit("Uso: python esegui.py FILE.json [MODALITA]")

    percorso = Path(sys.argv[1])
    if not percorso.is_absolute():
        percorso = BASE / percorso
    modalita = sys.argv[2] if len(sys.argv) > 2 else "completo"
    log_output = "--log-cplex" in sys.argv[3:]

    if modalita == "hens-solve":
        risolvi_caso_HEN(percorso, log_output=log_output)
    elif modalita == "hens-regression":
        regressione_HEN(log_output=log_output)
    elif modalita == "completo":
        dati_pinch = prepara_pinch(percorso)
        risultati_milp = esegui_milp(dati_pinch, log_output=log_output)
        stampa_risultati_milp(risultati_milp)
        salva_grafici(dati_pinch, risultati_milp, BASE / "risultati" / percorso.stem)
    else:
        raise SystemExit(f"Modalita non riconosciuta: {modalita}")


if __name__ == "__main__":
    main()
