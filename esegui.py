from pathlib import Path
import sys
import io
from contextlib import redirect_stdout

from src.predesign.THI15_predesign import (
    esegui_analisi_pinch,
    esegui_predesign_utilities,
    stampa_risultati_milp,
    salva_grafici,
)
from src.hens.BAR05_hens import (
    prepara_HENS_BAR05,
    risolvi_HEN,
    stampa_risultati_HEN,
    salva_validazione_BAR05,
)
from src.hens.TRA15_hens import (
    prepara_HENS_TRA15,
    risolvi_HEN_TRA15,
    stampa_risultati_TRA15,
    salva_validazione_TRA15_test1,
)

BASE = Path(__file__).resolve().parent


def stampa_uso():
    print(
        "\nUso:\n"
        "  python esegui.py <file_input.json> predesign\n"
        "  python esegui.py <file_input.json> hens bar05\n"
        "  python esegui.py <file_input.json> hens tra15\n"
    )


def main():

    # ---------------------------------------------------------
    # 1. Controllo argomenti
    # ---------------------------------------------------------
    if len(sys.argv) < 3:
        stampa_uso()
        sys.exit(1)

    percorso_input = Path(sys.argv[1])
    modalita = sys.argv[2].lower()

    # ---------------------------------------------------------
    # 2. Percorso file input
    # ---------------------------------------------------------
    if not percorso_input.is_absolute():
        percorso_input = BASE / percorso_input

    if not percorso_input.exists():
        print(
            f"\nERRORE: file input non trovato:\n"
            f"{percorso_input}\n"
        )
        sys.exit(1)

    # ---------------------------------------------------------
    # 3. PREDESIGN UTILITIES - THI15
    # ---------------------------------------------------------
    if modalita == "predesign":

        percorso_relativo = percorso_input.relative_to(
            BASE / "dati_input"
        )

        cartella_output = (
            BASE
            / "risultati"
            / percorso_relativo.parent
            / percorso_input.stem
        )

        cartella_output.mkdir(
            parents=True,
            exist_ok=True,
        )

        percorso_report = (
            cartella_output
            / "risultati_simulazione.txt"
        )

        # Buffer che raccoglie tutto ciò che viene stampato.
        buffer_output = io.StringIO()

        # ---------------------------------------------------------
        # Esecuzione simulazione
        # ---------------------------------------------------------
        with redirect_stdout(buffer_output):

            print("\n======================================")
            print(" THI15 - UTILITIES PREDESIGN")
            print("======================================\n")

            dati_pinch = esegui_analisi_pinch(
                percorso_input
            )

            risultati_milp = esegui_predesign_utilities(
                dati_pinch,
                log_output=False,
            )

            stampa_risultati_milp(
                risultati_milp
            )

            salva_grafici(
                dati_pinch,
                risultati_milp,
                cartella_output,
            )

        # ---------------------------------------------------------
        # Recupero output
        # ---------------------------------------------------------
        testo_output = buffer_output.getvalue()

        # Lo ristampa normalmente nel terminale.
        print(testo_output)

        # Lo salva anche su file.
        percorso_report.write_text(
            testo_output,
            encoding="utf-8",
        )

        print(
            f"Report testuale salvato in: "
            f"{percorso_report}"
        )

    # ---------------------------------------------------------
    # 4. HENS
    # ---------------------------------------------------------
    elif modalita == "hens":

        if len(sys.argv) < 4:
            print(
                "\nERRORE: per la modalità HENS devi specificare "
                "bar05 oppure tra15.\n"
            )
            stampa_uso()
            sys.exit(1)

        modello_hens = sys.argv[3].lower()

        # =========================================================
        # BAR05
        # =========================================================

        if modello_hens == "bar05":

            percorso_relativo = percorso_input.relative_to(
                BASE / "dati_input"
            )

            cartella_output = (
                BASE
                / "risultati"
                / percorso_relativo.parent
                / percorso_input.stem
            )

            cartella_output.mkdir(
                parents=True,
                exist_ok=True,
            )

            percorso_report = (
                cartella_output
                / "risultati_simulazione.txt"
            )

            buffer_output = io.StringIO()

            with redirect_stdout(buffer_output):

                print("\n======================================")
                print(" HENS - BAR05")
                print("======================================\n")

                preparazione = prepara_HENS_BAR05(
                    percorso_input
                )

                risultati = risolvi_HEN(
                    preparazione,
                    log_output=False,
                )

                stampa_risultati_HEN(
                    risultati
                )
                percorso_validazione = (
                    cartella_output
                    / "validazione_BAR05.txt"
                )

                salva_validazione_BAR05(
                    preparazione,
                    risultati,
                    percorso_validazione,
                )

            testo_output = buffer_output.getvalue()

            # Mostra a terminale
            print(testo_output)

            # Salva lo stesso output
            percorso_report.write_text(
                testo_output,
                encoding="utf-8",
            )

            print(
                f"Report salvato in: "
                f"{percorso_report}"
            )

        # =========================================================
        # TRA15
        # =========================================================

        elif modello_hens == "tra15":

            percorso_relativo = percorso_input.relative_to(
                BASE / "dati_input"
            )

            cartella_output = (
                BASE
                / "risultati"
                / percorso_relativo.parent
                / percorso_input.stem
            )

            cartella_output.mkdir(
                parents=True,
                exist_ok=True,
            )

            percorso_report = (
                cartella_output
                / "risultati_simulazione.txt"
            )

            buffer_output = io.StringIO()

            with redirect_stdout(buffer_output):

                print("\n======================================")
                print(" HENS - TRA15")
                print("======================================\n")

                preparazione = prepara_HENS_TRA15(
                                percorso_input,
                                delta_T_partition_max=11.0,
                                numero_intervalli_min=1,
                                separa_al_pinch=False,
                                non_isothermal_mixing=True,
                            )

                risultati = risolvi_HEN_TRA15(
                    preparazione,
                    log_output=False,
                    time_limit_s=10800,
                    mip_gap=1e-7,
                    threads=1,
                )

                stampa_risultati_TRA15(
                    risultati
                )
                percorso_validazione = (
                    cartella_output
                    / "validazione_TRA15_test1.txt"
                )

                salva_validazione_TRA15_test1(
                    preparazione,
                    risultati,
                    percorso_validazione,
                )

            testo_output = buffer_output.getvalue()

            print(testo_output)

            percorso_report.write_text(
                testo_output,
                encoding="utf-8",
            )

            print(
                f"Report salvato in: "
                f"{percorso_report}"
            )

        else:

            print(
                f"\nERRORE: modello HENS non riconosciuto: "
                f"{modello_hens}\n"
            )

            sys.exit(1)

if __name__ == "__main__":
    main()