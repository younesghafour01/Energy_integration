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
    crea_modello_bilanci_HEN,
    calcola_parametri_area_HEN,
    costruisci_tecnologie_HEN,
    aggiungi_variabili_tecnologie_HEN,
    aggiungi_vincoli_area_HEN,
    aggiungi_obiettivo_TAC_HEN,
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

configurazione_HEN = configurazione.get(
    "hens",
    {},
)

separa_al_pinch_HEN = configurazione_HEN.get(
    "separa_al_pinch",
    True,
)

if type(separa_al_pinch_HEN) is not bool:
    raise ValueError(
        "'hens.separa_al_pinch' deve essere "
        "true oppure false."
    )
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
        separa_al_pinch=separa_al_pinch_HEN,
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
        separa_al_pinch=separa_al_pinch_HEN,
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
        separa_al_pinch=separa_al_pinch_HEN,
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
        separa_al_pinch=separa_al_pinch_HEN,
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

    separa_al_pinch=separa_al_pinch_HEN,

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
elif modalita == "hens-balances":

    print("\n" + "=" * 70)
    print("TEST MODELLO BILANCI HENS")
    print("=" * 70)


    # =================================================
    # 1. UTILITIES
    # =================================================

    utilities_HEN = costruisci_utilities_HEN(
        configurazione,
        debug=False,
    )


    # =================================================
    # 2. PARTIZIONE
    # =================================================

    intervalli_HEN = crea_partizione_HEN(
        gcc=dati_pinch["gcc"],
        flussi=configurazione[
            "flussi_oggetti"
        ],
        delta_T_min=configurazione[
            "delta_T_min"
        ],
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
        separa_al_pinch=separa_al_pinch_HEN,
        debug=False,
    )


    # =================================================
    # 3. INSIEMI
    # =================================================

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


    # =================================================
    # 4. INDICI q
    # =================================================

    indici_q = genera_indici_q_HEN(
        insiemi_HEN,
        debug=False,
    )


    # =================================================
    # 5. ΔH PROCESS STREAMS
    # =================================================

    delta_H_HEN = calcola_delta_H_HEN(
        insiemi_HEN,
        debug=False,
    )


    # =================================================
    # 6. MODELLO DOCPLEX
    # =================================================

    modello_bilanci = (
        crea_modello_bilanci_HEN(
            insiemi_HEN=insiemi_HEN,
            indici_q=indici_q,
            delta_H_HEN=delta_H_HEN,
            debug=True,
        )
    )


    mdl = modello_bilanci[
        "modello"
    ]


    # =================================================
    # 7. RISOLUZIONE
    # =================================================

    soluzione = mdl.solve(
        log_output=True
    )


    if soluzione is None:

        print(
            "\nNESSUNA SOLUZIONE "
            "FATTIBILE TROVATA."
        )

    else:

        print(
            "\n" + "=" * 70
        )

        print(
            "SOLUZIONE BILANCI HENS"
        )

        print(
            "=" * 70
        )


        # =============================================
        # HOT UTILITIES
        # =============================================

        for i, variabile in (
            modello_bilanci[
                "F_H"
            ].items()
        ):

            F = variabile.solution_value

            delta_T = (
                modello_bilanci[
                    "delta_T_HU"
                ][i]
            )

            Q = (
                F * delta_T
            )

            print(
                f"\nHot utility {i}"
            )

            print(
                f"  F = "
                f"{F:.6f} kW/K"
            )

            print(
                f"  ΔT totale = "
                f"{delta_T:.3f} K"
            )

            print(
                f"  Q = "
                f"{Q:.3f} kW"
            )


        # =============================================
        # COLD UTILITIES
        # =============================================

        for j, variabile in (
            modello_bilanci[
                "F_C"
            ].items()
        ):

            F = variabile.solution_value

            delta_T = (
                modello_bilanci[
                    "delta_T_CU"
                ][j]
            )

            Q = (
                F * delta_T
            )

            print(
                f"\nCold utility {j}"
            )

            print(
                f"  F = "
                f"{F:.6f} kW/K"
            )

            print(
                f"  ΔT totale = "
                f"{delta_T:.3f} K"
            )

            print(
                f"  Q = "
                f"{Q:.3f} kW"
            )


        # =============================================
        # q NON NULLI
        # =============================================

        q_non_nulli = [
            (
                indice,
                variabile.solution_value,
            )
            for indice, variabile
            in modello_bilanci["q"].items()
            if (
                variabile.solution_value
                > 1e-6
            )
        ]

        print(
            f"\nNumero q non nulli: "
            f"{len(q_non_nulli)}"
        )

        print(
            "\nPrime 20 q non nulle:"
        )

        for (
            indice,
            valore,
        ) in q_non_nulli[:20]:

            print(
                f"  {indice} "
                f"= {valore:.3f} kW"
            )
elif modalita == "hens-area-params":

    print("\n" + "=" * 70)
    print("TEST PARAMETRI AREA HENS")
    print("=" * 70)


    # =================================================
    # 1. UTILITIES HENS
    # =================================================

    utilities_HEN = costruisci_utilities_HEN(
        configurazione,
        debug=False,
    )


    # =================================================
    # 2. PARTIZIONE HENS
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
        separa_al_pinch=separa_al_pinch_HEN,
        debug=False,
    )


    # =================================================
    # 3. INSIEMI HENS
    # =================================================

    insiemi_HEN = costruisci_insiemi_HEN(
        flussi=configurazione["flussi_oggetti"],
        utilities=utilities_HEN,
        intervalli=intervalli_HEN,
        delta_T_min=configurazione["delta_T_min"],
    )


    # =================================================
    # 4. INDICI q
    # =================================================

    indici_q = genera_indici_q_HEN(
        insiemi_HEN,
        debug=False,
    )


    # =================================================
    # 5. PARAMETRI AREA
    # =================================================

    parametri_area = calcola_parametri_area_HEN(
        insiemi_HEN=insiemi_HEN,
        indici_q=indici_q,
        delta_T_min=configurazione["delta_T_min"],
        debug=True,
    )


    # =================================================
    # 6. CONTROLLO SPECIFICO
    # =================================================

    print("\n" + "=" * 70)
    print("CONTROLLO REGRESSIONE AREA")
    print("=" * 70)

    trovati = 0

    for indice, dati in parametri_area["dettagli"].items():

        if (
            abs(dati["delta_T_1_K"] - 20.0) < 1e-6
            and
            abs(dati["delta_T_2_K"] - 20.0) < 1e-6
        ):

            print(f"\nIndice: {indice}")

            print(
                f"ΔT1 = "
                f"{dati['delta_T_1_K']:.6f} K"
            )

            print(
                f"ΔT2 = "
                f"{dati['delta_T_2_K']:.6f} K"
            )

            print(
                f"ΔTML = "
                f"{dati['delta_T_ML_K']:.6f} K"
            )

            print(
                f"K_area = "
                f"{dati['coeff_area_m2_per_kW']:.6f} "
                f"m²/kW"
            )

            trovati += 1

            if trovati >= 5:
                break


    if trovati == 0:

        print(
            "\nNessun caso con "
            "ΔT1 = ΔT2 = 20 K trovato."
        )
elif modalita == "hens-technologies":

    print("\n" + "=" * 70)
    print("TEST TECNOLOGIE HENS")
    print("=" * 70)

    tecnologie_HEN = costruisci_tecnologie_HEN(
        configurazione,
        debug=True,
    )
elif modalita == "hens-tech-vars":

    print("\n" + "=" * 70)
    print("TEST VARIABILI TECNOLOGIE HENS")
    print("=" * 70)


    # =================================================
    # 1. UTILITIES
    # =================================================

    utilities_HEN = costruisci_utilities_HEN(
        configurazione,
        debug=False,
    )


    # =================================================
    # 2. PARTIZIONE
    # =================================================

    intervalli_HEN = crea_partizione_HEN(
        gcc=dati_pinch["gcc"],
        flussi=configurazione[
            "flussi_oggetti"
        ],
        delta_T_min=configurazione[
            "delta_T_min"
        ],
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
        separa_al_pinch=separa_al_pinch_HEN,
        debug=False,
    )


    # =================================================
    # 3. INSIEMI
    # =================================================

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


    # =================================================
    # 4. q
    # =================================================

    indici_q = genera_indici_q_HEN(
        insiemi_HEN,
        debug=False,
    )


    # =================================================
    # 5. ΔH
    # =================================================

    delta_H_HEN = calcola_delta_H_HEN(
        insiemi_HEN,
        debug=False,
    )


    # =================================================
    # 6. MODELLO BILANCI
    # =================================================

    modello_HEN = crea_modello_bilanci_HEN(
        insiemi_HEN=insiemi_HEN,
        indici_q=indici_q,
        delta_H_HEN=delta_H_HEN,
        debug=False,
    )
    parametri_area = calcola_parametri_area_HEN(
    insiemi_HEN=insiemi_HEN,
    indici_q=indici_q,
    delta_T_min=configurazione[
        "delta_T_min"
    ],
    debug=False,
)

    # =================================================
    # 7. TECNOLOGIE
    # =================================================

    tecnologie_HEN = costruisci_tecnologie_HEN(
        configurazione,
        debug=True,
    )


    # =================================================
    # 8. VARIABILI A E U
    # =================================================

    modello_HEN = (
        aggiungi_variabili_tecnologie_HEN(
            modello_bilanci=modello_HEN,
            insiemi_HEN=insiemi_HEN,
            indici_q=indici_q,
            tecnologie_HEN=tecnologie_HEN,
            debug=True,
        )
    )
    modello_HEN = aggiungi_vincoli_area_HEN(
    modello_HEN=modello_HEN,
    indici_q=indici_q,
    parametri_area=parametri_area,
    tecnologie_HEN=tecnologie_HEN,
    debug=True,
)
    # =================================================
# OBIETTIVO TAC
# =================================================

    modello_HEN = aggiungi_obiettivo_TAC_HEN(
    modello_HEN=modello_HEN,
    utilities_HEN=utilities_HEN,
    tecnologie_HEN=tecnologie_HEN,
    debug=True,
    )
    # =================================================
    # 9. RIEPILOGO MODELLO
    # =================================================

    mdl = modello_HEN[
        "modello"
    ]

    soluzione = mdl.solve(
        log_output=True
    )

    print(
        "\nNumero totale variabili DOcplex:",
        mdl.number_of_variables,
    )

    print(
        "Numero totale vincoli:",
        mdl.number_of_constraints,
    )
    if soluzione is None:

        print(
            "\nNESSUNA SOLUZIONE "
            "OTTIMA TROVATA."
        )

    else:

        print(
            "\n" + "=" * 70
        )

        print(
            "RISULTATO ECONOMICO HENS"
        )

        print(
            "=" * 70
        )


        costo_HU = soluzione.get_value(
            modello_HEN[
                "costo_hot_utility"
            ]
        )

        costo_CU = soluzione.get_value(
            modello_HEN[
                "costo_cold_utility"
            ]
        )

        costo_fisso = soluzione.get_value(
            modello_HEN[
                "costo_fisso_HEX"
            ]
        )

        costo_area = soluzione.get_value(
            modello_HEN[
                "costo_area_HEX"
            ]
        )

        TAC = soluzione.get_value(
            modello_HEN[
                "TAC"
            ]
        )


        print(
            f"\nCosto hot utility: "
            f"{costo_HU:,.2f} $/year"
        )

        print(
            f"Costo cold utility: "
            f"{costo_CU:,.2f} $/year"
        )

        print(
            f"Costo fisso HEX: "
            f"{costo_fisso:,.2f} $/year"
        )

        print(
            f"Costo area HEX: "
            f"{costo_area:,.2f} $/year"
        )

        print(
            "\nTAC = "
            f"{TAC:,.2f} $/year"
        )

        print(
            "TAC = "
            f"{TAC / 1000.0:.3f} k$/year"
        )
        print(
            "\n" + "=" * 70
        )

        print(
            "UTILITIES OTTIME"
        )

        print(
            "=" * 70
        )


        for codice, Q_expr in (
            modello_HEN["Q_HU"].items()
        ):

            Q = soluzione.get_value(
                Q_expr
            )

            print(
                f"Hot utility {codice}: "
                f"{Q:.3f} kW"
            )


        for codice, Q_expr in (
            modello_HEN["Q_CU"].items()
        ):

            Q = soluzione.get_value(
                Q_expr
            )

            print(
                f"Cold utility {codice}: "
                f"{Q:.3f} kW"
            )
            print(
            "\n" + "=" * 70
            )

            print(
                "SCAMBIATORI INSTALLATI"
            )

            print(
                "=" * 70
            )


            for indice in modello_HEN[
                "indici_A_U"
            ]:

                z, i, j, t = indice

                U_val = modello_HEN[
                    "U"
                ][indice].solution_value

                A_val = modello_HEN[
                    "A"
                ][indice].solution_value


                if U_val > 1e-6:

                    print(
                        f"Zona {z} | "
                        f"{i} -> {j} | "
                        f"{t} | "
                        f"U = {U_val:.0f} | "
                        f"A = {A_val:.3f} m²"
                    )
            # =================================================
            # DUTY TOTALI PER MATCH
            # =================================================

            print(
                "\n" + "=" * 70
            )

            print(
                "DUTY TOTALI PER MATCH"
            )

            print(
                "=" * 70
            )


            duty_match = {}


            for indice, variabile in (
                modello_HEN["q"].items()
            ):

                z, i, m, j, n = indice

                q_val = variabile.solution_value

                if q_val <= 1e-8:
                    continue

                chiave = (
                    z,
                    i,
                    j,
                )

                duty_match[
                    chiave
                ] = (
                    duty_match.get(
                        chiave,
                        0.0,
                    )
                    +
                    q_val
                )


            for (
                z,
                i,
                j,
            ), Q in sorted(
                duty_match.items()
            ):

                print(
                    f"Zona {z} | "
                    f"{i} -> {j} | "
                    f"Q = {Q:.3f} kW"
                )
            
else:

    raise ValueError(
        f"Modalità non riconosciuta: {modalita}\n"
        "Modalità disponibili: "
        "completo, hens-partition, hens-sets"
    )

