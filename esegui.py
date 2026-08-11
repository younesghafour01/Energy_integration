from pathlib import Path
import sys

from integrazione_energetica import (
    prepara_pinch,
    esegui_milp,
    stampa_risultati_milp,
    salva_grafici,
)


BASE = Path(__file__).resolve().parent

PERCORSO_JSON = Path(sys.argv[1])

if not PERCORSO_JSON.is_absolute():
    PERCORSO_JSON = BASE / PERCORSO_JSON

CARTELLA_RISULTATI = (
    BASE
    / "risultati"
    / PERCORSO_JSON.stem
)


dati_pinch = prepara_pinch(
    PERCORSO_JSON
)

risultati = esegui_milp(
    dati_pinch
)

stampa_risultati_milp(
    risultati
)

salva_grafici(
    dati_pinch,
    risultati,
    CARTELLA_RISULTATI,
)