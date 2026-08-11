from pathlib import Path
import sys

from integrazione_energetica import (
    prepara_pinch,
    esegui_milp,
    stampa_risultati_milp,
    salva_grafici,
    crea_partizione_HEN,
    costruisci_insiemi_HEN,
    genera_indici_q_HEN,
    calcola_delta_H_HEN,
    costruisci_utilities_HEN,
)


# =====================================================
# STAMPA DIAGNOSTICA INSIEMI HENS
# =====================================================

def stampa_insiemi_HEN(insiemi):

    Z = insiemi["Z"]
    H = insiemi["H"]
    C = insiemi["C"]
    HU = insiemi["HU"]
    CU = insiemi["CU"]
    M = insiemi["M"]
    M_i = insiemi["M_i"]
    N_j = insiemi["N_j"]
    H_m = insiemi["H_m"]
    C_n = insiemi["C_n"]
    P = insiemi["P"]
    P_H = insiemi["P_H"]
    P_C = insiemi["P_C"]

    print("\n" + "=" * 60)
    print("VERIFICA INSIEMI HENS")
    print("=" * 60)

    print(f"\nZ = {Z}")

    for z in Z:

        print("\n" + "-" * 60)
        print(f"ZONA {z}")
        print("-" * 60)

        print(f"\nH^{z}  = {H[z]}")
        print(f"C^{z}  = {C[z]}")
        print(f"HU^{z} = {HU[z]}")
        print(f"CU^{z} = {CU[z]}")

        print(f"\nM^{z} = {M[z]}")

        print("\nM_i^z - intervalli delle hot streams:")

        for i in H[z]:
            print(
                f"  M[{i}] = {M_i[z, i]}"
            )

        print("\nN_j^z - intervalli delle cold streams:")

        for j in C[z]:
            print(
                f"  N[{j}] = {N_j[z, j]}"
            )

        print("\nCorrenti presenti in ogni intervallo:")

        for m in M[z]:

            print(
                f"  m={m}: "
                f"H={H_m[z, m]} | "
                f"C={C_n[z, m]}"
            )

        print("\nP_H:")

        for i in H[z]:

            for m in M_i[z, i]:

                print(
                    f"  P_H[{i}, {m}] = "
                    f"{P_H[z, i, m]}"
                )

        print("\nP_C:")

        for j in C[z]:

            for n in N_j[z, j]:

                print(
                    f"  P_C[{j}, {n}] = "
                    f"{P_C[z, j, n]}"
                )

    print("\n" + "-" * 60)
    print("P - match consentiti:")

    for i, j in sorted(P):
        print(f"  {i} -> {j}")

    print("-" * 60)


# =====================================================
# INPUT
# =====================================================

BASE = Path(__file__).resolve().parent

PERCORSO_JSON = Path(sys.argv[1])

if not PERCORSO_JSON.is_absolute():
    PERCORSO_JSON = BASE / PERCORSO_JSON

modalita = (
    sys.argv[2]
    if len(sys.argv) > 2
    else "completo"
)

print(f"Modalità: {modalita}")


# =====================================================
# PINCH ANALYSIS
# =====================================================

dati_pinch = prepara_pinch(
    PERCORSO_JSON
)

configurazione = dati_pinch["configurazione"]


# =====================================================
# MODALITÀ 1: SOLO PARTIZIONE HENS
# =====================================================

if modalita == "hens-partition":

    intervalli_HEN = crea_partizione_HEN(
        gcc=dati_pinch["gcc"],
        flussi=configurazione["flussi_oggetti"],
        delta_T_min=configurazione["delta_T_min"],
        pinch_traslati=dati_pinch["pinch_traslati_C"],
        delta_T_partition_max=(
            configurazione["delta_T_partition_max"]
        ),
        numero_intervalli_min=(
            configurazione["numero_intervalli_min"]
        ),
        debug=True,
    )

    print("\nPARTIZIONE HEN")

    for z, intervalli in intervalli_HEN.items():

        print(f"\nZona {z}")

        for m, (T_sup, T_inf) in enumerate(
            intervalli,
            start=1,
        ):

            print(
                f"m={m:2d} | "
                f"{T_sup:8.2f} -> "
                f"{T_inf:8.2f} °C | "
                f"ΔT={T_sup - T_inf:7.2f} °C"
            )

    print(
        "\nNumero totale intervalli HEN:",
        sum(
            len(zona)
            for zona in intervalli_HEN.values()
        ),
    )


# =====================================================
# MODALITÀ 2: VERIFICA INSIEMI HENS
# =====================================================

elif modalita == "hens-sets":

    # Prima costruiamo la partizione.
    intervalli_HEN = crea_partizione_HEN(
        gcc=dati_pinch["gcc"],
        flussi=configurazione["flussi_oggetti"],
        delta_T_min=configurazione["delta_T_min"],
        pinch_traslati=dati_pinch["pinch_traslati_C"],
        delta_T_partition_max=(
            configurazione["delta_T_partition_max"]
        ),
        numero_intervalli_min=(
            configurazione["numero_intervalli_min"]
        ),
        debug=False,
    )

    # Per questo primo test non inseriamo ancora
    # hot/cold utilities HENS.
    utilities_HEN = {
        "hot": [],
        "cold": [],
    }

    insiemi_HEN = costruisci_insiemi_HEN(
        flussi=configurazione["flussi_oggetti"],
        utilities=utilities_HEN,
        intervalli=intervalli_HEN,
        delta_T_min=configurazione["delta_T_min"],
    )

    stampa_insiemi_HEN(
        insiemi_HEN
    )


# =====================================================
# MODALITÀ 3: SIMULAZIONE COMPLETA
# =====================================================

elif modalita == "completo":

    risultati = esegui_milp(
        dati_pinch
    )

    stampa_risultati_milp(
        risultati
    )

    CARTELLA_RISULTATI = (
        BASE
        / "risultati"
        / PERCORSO_JSON.stem
    )

    salva_grafici(
        dati_pinch,
        risultati,
        CARTELLA_RISULTATI,
    )
elif modalita == "hens-q-indices":

    # ---------------------------------------------
    # 1. Partizione HENS
    # ---------------------------------------------

    intervalli_HEN = crea_partizione_HEN(
        gcc=dati_pinch["gcc"],
        flussi=configurazione["flussi_oggetti"],
        delta_T_min=configurazione["delta_T_min"],
        pinch_traslati=dati_pinch["pinch_traslati_C"],
        delta_T_partition_max=(
            configurazione["delta_T_partition_max"]
        ),
        numero_intervalli_min=(
            configurazione["numero_intervalli_min"]
        ),
        debug=False,
    )


    # ---------------------------------------------
    # 2. Utilities
    # Per ora ancora assenti
    # ---------------------------------------------

    utilities_HEN = {
        "hot": [],
        "cold": [],
    }


    # ---------------------------------------------
    # 3. Insiemi HENS
    # ---------------------------------------------

    insiemi_HEN = costruisci_insiemi_HEN(
        flussi=configurazione["flussi_oggetti"],
        utilities=utilities_HEN,
        intervalli=intervalli_HEN,
        delta_T_min=configurazione["delta_T_min"],
    )


    # ---------------------------------------------
    # 4. Indici q
    # ---------------------------------------------

    indici_q = genera_indici_q_HEN(
        insiemi_HEN,
        debug=True,
    )

# =====================================================
# MODALITÀ NON RICONOSCIUTA
# =====================================================
elif modalita == "hens-delta-h":

    # =================================================
    # 1. PARTIZIONE
    # =================================================

    intervalli_HEN = crea_partizione_HEN(
        gcc=dati_pinch["gcc"],
        flussi=configurazione["flussi_oggetti"],
        delta_T_min=configurazione["delta_T_min"],
        pinch_traslati=dati_pinch["pinch_traslati_C"],
        delta_T_partition_max=(
            configurazione["delta_T_partition_max"]
        ),
        numero_intervalli_min=(
            configurazione["numero_intervalli_min"]
        ),
        debug=False,
    )


    # =================================================
    # 2. UTILITIES
    # Per ora non ancora inserite
    # =================================================

    utilities_HEN = {
        "hot": [],
        "cold": [],
    }


    # =================================================
    # 3. INSIEMI
    # =================================================

    insiemi_HEN = costruisci_insiemi_HEN(
        flussi=configurazione["flussi_oggetti"],
        utilities=utilities_HEN,
        intervalli=intervalli_HEN,
        delta_T_min=configurazione["delta_T_min"],
    )


    # =================================================
    # 4. ΔH DELLE PROCESS STREAMS
    # =================================================

    delta_H_HEN = calcola_delta_H_HEN(
        insiemi_HEN,
        debug=True,
    )
elif modalita == "hens-utilities":

    # =============================================
    # 1. Utility HENS
    # =============================================

    utilities_HEN = (
        costruisci_utilities_HEN(
            configurazione
        )
    )


    print("\nUTILITY HENS")

    for utility in utilities_HEN["hot"]:

        print(
            f"{utility.codice} | "
            f"HOT | "
            f"{utility.T_in:.2f} -> "
            f"{utility.T_out:.2f} °C | "
            f"h={utility.h_W_m2K:.2f} W/m²K"
        )

    for utility in utilities_HEN["cold"]:

        print(
            f"{utility.codice} | "
            f"COLD | "
            f"{utility.T_in:.2f} -> "
            f"{utility.T_out:.2f} °C | "
            f"scala HENS: "
            f"{utility.T_in + configurazione['delta_T_min']:.2f} "
            f"-> "
            f"{utility.T_out + configurazione['delta_T_min']:.2f} °C | "
            f"h={utility.h_W_m2K:.2f} W/m²K"
        )


    # =============================================
    # 2. Partizione con utilities
    # =============================================

    intervalli_HEN = crea_partizione_HEN(
        gcc=dati_pinch["gcc"],
        flussi=configurazione["flussi_oggetti"],
        delta_T_min=configurazione["delta_T_min"],
        pinch_traslati=dati_pinch[
            "pinch_traslati_C"
        ],
        delta_T_partition_max=(
            configurazione[
                "delta_T_partition_max"
            ]
        ),
        numero_intervalli_min=(
            configurazione[
                "numero_intervalli_min"
            ]
        ),
        utilities=utilities_HEN,
        debug=True,
    )


    # =============================================
    # 3. Insiemi
    # =============================================

    insiemi_HEN = costruisci_insiemi_HEN(
        flussi=configurazione[
            "flussi_oggetti"
        ],
        utilities=utilities_HEN,
        intervalli=intervalli_HEN,
        delta_T_min=configurazione[
            "delta_T_min"
        ],
    )


    # =============================================
    # 4. Controllo HU e CU
    # =============================================

    print("\n" + "=" * 60)
    print("CONTROLLO UTILITIES NELLE ZONE")
    print("=" * 60)

    for z in insiemi_HEN["Z"]:

        print(f"\nZona {z}")

        print(
            "H  =",
            insiemi_HEN["H"][z],
        )

        print(
            "C  =",
            insiemi_HEN["C"][z],
        )

        print(
            "HU =",
            insiemi_HEN["HU"][z],
        )

        print(
            "CU =",
            insiemi_HEN["CU"][z],
        )
elif modalita == "hens-full-preprocess":

    print("\n" + "=" * 70)
    print("TEST PREPROCESSING HENS COMPLETO")
    print("=" * 70)


    # =================================================
    # 1. COSTRUZIONE UTILITIES HENS
    # =================================================

    utilities_HEN = costruisci_utilities_HEN(
        configurazione,
        debug=True,
    )


    # =================================================
    # 2. PARTIZIONE CON PROCESS STREAMS + UTILITIES
    # =================================================

    intervalli_HEN = crea_partizione_HEN(
        gcc=dati_pinch["gcc"],
        flussi=configurazione["flussi_oggetti"],
        delta_T_min=configurazione["delta_T_min"],
        pinch_traslati=dati_pinch["pinch_traslati_C"],
        delta_T_partition_max=(
            configurazione["delta_T_partition_max"]
        ),
        numero_intervalli_min=(
            configurazione["numero_intervalli_min"]
        ),
        utilities=utilities_HEN,
        debug=False,
    )


    print("\nPARTIZIONE HENS")

    for z, intervalli in intervalli_HEN.items():

        print(
            f"Zona {z}: "
            f"{len(intervalli)} intervalli"
        )


    # =================================================
    # 3. COSTRUZIONE INSIEMI HENS
    # =================================================

    insiemi_HEN = costruisci_insiemi_HEN(
        flussi=configurazione["flussi_oggetti"],
        utilities=utilities_HEN,
        intervalli=intervalli_HEN,
        delta_T_min=configurazione["delta_T_min"],
    )


    print("\n" + "=" * 70)
    print("CONTROLLO INSIEMI")
    print("=" * 70)

    for z in insiemi_HEN["Z"]:

        print(f"\nZona {z}")

        print(
            "H  =",
            insiemi_HEN["H"][z],
        )

        print(
            "C  =",
            insiemi_HEN["C"][z],
        )

        print(
            "HU =",
            insiemi_HEN["HU"][z],
        )

        print(
            "CU =",
            insiemi_HEN["CU"][z],
        )


    # =================================================
    # 4. GENERAZIONE INDICI q
    # =================================================

    indici_q = genera_indici_q_HEN(
        insiemi_HEN,
        debug=False,
    )


    print("\n" + "=" * 70)
    print("CONTROLLO INDICI q")
    print("=" * 70)


    for z in insiemi_HEN["Z"]:

        indici_zona = [
            indice
            for indice in indici_q
            if indice[0] == z
        ]

        print(
            f"Zona {z}: "
            f"{len(indici_zona)} variabili q"
        )


    print(
        "Numero totale variabili q:",
        len(indici_q),
    )


    # =================================================
    # 5. CONTROLLO q ASSOCIATI ALLE UTILITIES
    # =================================================

    q_H3 = [
        indice
        for indice in indici_q
        if indice[1] == "H3"
    ]

    q_C3 = [
        indice
        for indice in indici_q
        if indice[3] == "C3"
    ]


    print("\nIndici q associati a H3:")

    print(
        f"Numero match elementari H3 -> process: "
        f"{len(q_H3)}"
    )

    for indice in q_H3[:10]:
        print(
            " ",
            indice,
        )

    if len(q_H3) > 10:
        print("  ...")


    print("\nIndici q associati a C3:")

    print(
        f"Numero match elementari process -> C3: "
        f"{len(q_C3)}"
    )

    for indice in q_C3[:10]:
        print(
            " ",
            indice,
        )

    if len(q_C3) > 10:
        print("  ...")


    # =================================================
    # 6. CALCOLO ΔH PROCESS STREAMS
    # =================================================

    risultati_delta_H = calcola_delta_H_HEN(
        insiemi_HEN,
        debug=True,
    )

    delta_H_H = risultati_delta_H[
        "delta_H_H"
    ]

    delta_H_C = risultati_delta_H[
        "delta_H_C"
    ]


    # =================================================
    # 7. CONTROLLO:
    # LE UTILITIES NON DEVONO AVERE ΔH FISSO
    # =================================================

    H3_in_delta_H = any(
        i == "H3"
        for (z, i, m)
        in delta_H_H
    )

    C3_in_delta_H = any(
        j == "C3"
        for (z, j, n)
        in delta_H_C
    )


    print("\n" + "=" * 70)
    print("CONTROLLO ΔH DELLE UTILITIES")
    print("=" * 70)

    print(
        "H3 presente in delta_H_H:",
        H3_in_delta_H,
    )

    print(
        "C3 presente in delta_H_C:",
        C3_in_delta_H,
    )


    # =================================================
    # 8. ESITO FINALE
    # =================================================

    print("\n" + "=" * 70)
    print("ESITO PREPROCESSING")
    print("=" * 70)

    if H3_in_delta_H:
        print(
            "ERRORE: H3 ha un ΔH fissato, "
            "ma dovrebbe essere una utility variabile."
        )

    else:
        print(
            "OK: H3 non ha ΔH fissato."
        )

    if C3_in_delta_H:
        print(
            "ERRORE: C3 ha un ΔH fissato, "
            "ma dovrebbe essere una utility variabile."
        )

    else:
        print(
            "OK: C3 non ha ΔH fissato."
        )

    if q_H3:
        print(
            "OK: sono stati generati indici q "
            "per H3."
        )

    else:
        print(
            "ERRORE: nessun indice q generato "
            "per H3."
        )

    if q_C3:
        print(
            "OK: sono stati generati indici q "
            "per C3."
        )

    else:
        print(
            "ERRORE: nessun indice q generato "
            "per C3."
        )
else:

    raise ValueError(
        f"Modalità non riconosciuta: {modalita}\n"
        "Modalità disponibili: "
        "completo, hens-partition, hens-sets"
    )

