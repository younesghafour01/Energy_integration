from docplex.mp.model import Model


def crea_modello_HPPr(HPPr_candidate, zone_GCC, HP_max, T0, T_f, eta_ex):

    # -------------------------------------------------
    # 1. CREAZIONE DEL MODELLO MILP
    # -------------------------------------------------

    modello = Model("preselezione_utilities")


    # -------------------------------------------------
    # 2. ORDINAMENTO DELLE ZONE COME NEL PAPER
    # -------------------------------------------------

    # Nel nostro grafico le zone sono ordinate
    # dalla temperatura più alta alla più bassa.
    #
    # Nel modello MILP:
    # zona 1 = zona più fredda
    # zona Z = zona più calda.
    zone_milp = [
    list(reversed(zona))
    for zona in reversed(zone_GCC)
    ]

    # Numero totale di zone.

    Z = len(zone_milp)
    # -------------------------------------------------
    # 3. INDICI DELLE HP DI PROCESSO
    # -------------------------------------------------

    # Ogni HP candidata è identificata da:
    #
    # (y, j, z, k)
    #
    # y,j = punto dell'evaporatore
    # z,k = punto del condensatore
    indici_HP = [
        (hp["y"], hp["j"], hp["z"], hp["k"])
        for hp in HPPr_candidate
    ]


    # -------------------------------------------------
    # 4. VARIABILI DECISIONALI DELLE HP
    # -------------------------------------------------

    # Variabile binaria:
    #
    # BoolHPPr = 1 -> HP selezionata
    # BoolHPPr = 0 -> HP non selezionata
    BoolHPPr = modello.binary_var_dict(
        indici_HP,
        name="BoolHPPr",
    )

    # Variabile continua:
    #
    # 0 <= FHPPr <= 1
    #
    # rappresenta la frazione del carico disponibile
    # utilizzata dalla HP.
    FHPPr = modello.continuous_var_dict(
        indici_HP,
        lb=0,
        ub=1,
        name="FHPPr",
    )


    # -------------------------------------------------
    # 5. VINCOLI SULLE HP
    # -------------------------------------------------

    # Se la HP non è selezionata:
    #
    # BoolHPPr = 0
    #
    # allora deve necessariamente essere:
    #
    # FHPPr = 0
    for indice in indici_HP:

        modello.add_constraint(
            FHPPr[indice] <= BoolHPPr[indice]
        )


    # Numero massimo di HP di processo selezionabili.
    modello.add_constraint(
        modello.sum(
            BoolHPPr[indice]
            for indice in indici_HP
        ) <= HP_max
    )


    # -------------------------------------------------
    # 6. INDICI E CARICHI DELLA GCC DISCRETIZZATA
    # -------------------------------------------------

    # indici_GCC conterrà:
    #
    # (y, j)
    #
    # Q_GCC conterrà:
    #
    # Q_GCC[y,j] = Q_yj

    indici_GCC = []
    Q_GCC = {}
    T_GCC = {}

    for y, zona in enumerate(
        zone_milp,
        start=1,
    ):

        for j, (Q, T_C) in enumerate(
            zona,
            start=1,
        ):

            indici_GCC.append((y, j))

            Q_GCC[y, j] = Q

            # L'exergia richiede temperature assolute.
            T_GCC[y, j] = T_C + 273.15

    # -------------------------------------------------
    # 7. CALORE PRELEVATO DALLA GCC: Pprel
    # -------------------------------------------------

    # Una variabile Pprel per ogni punto della GCC.
    Pprel = modello.continuous_var_dict(
        indici_GCC,
        lb=0,
        name="Pprel",
    )


    for y, j in indici_GCC:

        # Nella zona più calda Z
        # non viene prelevato calore.
        if y == Z:

            modello.add_constraint(
                Pprel[y, j] == 0
            )

        else:

            # Somma di tutte le HP che hanno
            # l'evaporatore nel punto (y,j).
            modello.add_constraint(

                Pprel[y, j]
                ==
                Q_GCC[y, j]
                * modello.sum(

                    FHPPr[indice]

                    for indice in indici_HP

                    if indice[0] == y
                    and indice[1] == j
                )
            )


    # -------------------------------------------------
    # 8. COP DELLE HP CANDIDATE
    # -------------------------------------------------

    # Dizionario Python:
    #
    # (y,j,z,k) -> COP della HP
    COP_HP = {
        (
            hp["y"],
            hp["j"],
            hp["z"],
            hp["k"],
        ): hp["COP"]

        for hp in HPPr_candidate
    }


    # -------------------------------------------------
    # 9. CALORE FORNITO ALLA GCC: Papp
    # -------------------------------------------------

    Papp = modello.continuous_var_dict(
        indici_GCC,
        lb=0,
        name="Papp",
    )


    for z, k in indici_GCC:

        # Nella zona 1 non viene fornito calore.
        if z == 1:

            modello.add_constraint(
                Papp[z, k] == 0
            )

        else:

            # Somma di tutte le HP che condensano
            # nel punto (z,k).
            modello.add_constraint(

                Papp[z, k]
                ==
                modello.sum(

                    FHPPr[indice]
                    * Q_GCC[
                        indice[0],
                        indice[1]
                    ]
                    * COP_HP[indice]
                    / (
                        COP_HP[indice] - 1
                    )

                    for indice in indici_HP

                    if indice[2] == z
                    and indice[3] == k
                )
            )
        # -------------------------------------------------
    # 10. GCC AGGIORNATA: NHL
    # -------------------------------------------------

    # NHL[y,j] rappresenta il nuovo carico termico
    # della GCC dopo l'inserimento delle utilities.
    #
    # Il limite inferiore lb=0 implementa direttamente
    # il vincolo NHL >= 0 del paper.
    NHL = modello.continuous_var_dict(
        indici_GCC,
        lb=0,
        name="NHL",
    )


    # -------------------------------------------------
    # 10.1 ZONE DA 1 A Z-1
    # -------------------------------------------------

    for y in range(1, Z):

        S_y = len(zone_milp[y - 1])

        for j in range(1, S_y + 1):

            # Effetto cumulativo delle utilities
            # nella stessa zona.
            #
            # I nostri punti sono ordinati:
            #
            # da temperatura alta a temperatura bassa
            #
            # quindi, al punto j, devono essere
            # considerate le utilities da 1 a j.

            effetto_stessa_zona = modello.sum(
                Papp[y, i] - Pprel[y, i]
                for i in range(j, S_y + 1)
            )

            # Effetto delle zone superiori,
            # esclusa la zona Z.
            effetto_zone_superiori = modello.sum(
                Papp[z, k] - Pprel[z, k]

                for z in range(y + 1, Z)

                for k in range(
                    1,
                    len(zone_milp[z - 1]) + 1
                )
            )

            modello.add_constraint(
                NHL[y, j]
                ==
                Q_GCC[y, j]
                + effetto_stessa_zona
                + effetto_zone_superiori
            )


    # -------------------------------------------------
    # 10.2 ZONA Z
    # -------------------------------------------------

    S_Z = len(zone_milp[Z - 1])

    for j in range(1, S_Z + 1):

        # Nella zona più calda viene solamente
        # fornito calore.
        #
        # Il calore fornito ai livelli superiori
        # riduce cumulativamente il fabbisogno
        # termico della GCC.
        modello.add_constraint(
            NHL[Z, j]
            ==
            Q_GCC[Z, j]
            - modello.sum(
                Papp[Z, i]
                for i in range(1, j + 1)
            )
        )
        # -------------------------------------------------
    # 11. CONSUMO ELETTRICO LOCALE: Pelec
    # -------------------------------------------------

    # Pelec[y,j] rappresenta il consumo elettrico
    # delle utilities che prelevano calore nel punto
    # (y,j) della GCC.
    Pelec = modello.continuous_var_dict(
        indici_GCC,
        lb=0,
        name="Pelec",
    )

    for y, j in indici_GCC:

        # Le HP di processo possono evaporare
        # solamente nelle zone da 1 a Z-1.
        #
        # Nella zona Z non abbiamo, per ora,
        # nessuna utility che consumi elettricità.
        if y == Z:

            modello.add_constraint(
                Pelec[y, j] == 0
            )

        else:

            modello.add_constraint(
                Pelec[y, j]
                ==
                modello.sum(

                    FHPPr[indice]
                    * Q_GCC[y, j]
                    / (COP_HP[indice] - 1)

                    for indice in indici_HP

                    if indice[0] == y
                    and indice[1] == j
                )
            )


    # -------------------------------------------------
    # 12. CONSUMO ELETTRICO TOTALE: TEC
    # -------------------------------------------------

    TEC = modello.continuous_var(
        lb=0,
        name="TEC",
    )

    modello.add_constraint(
        TEC
        ==
        modello.sum(
            Pelec[y, j]
            for y, j in indici_GCC
        )
    )
    # -------------------------------------------------
    # 13. FUNZIONE OBIETTIVO EXERGETICA
    # -------------------------------------------------

    S_Z = len(zone_milp[Z - 1])

    T_cold_MER = T_GCC[1, 1]

    # Termine exergetico associato al cold MER residuo.
    #
    # L'articolo distingue:
    # T1,1 > T0  -> contributo nullo
    # T1,1 < T0  -> utilizzo del fattore exergetico.
    #
    # In caso di uguaglianza poniamo il contributo nullo.
    if T_cold_MER >= T0:

        fattore_cold = 0.0

    else:

        fattore_cold = (
            eta_ex
            * T_cold_MER
            / (T0 - T_cold_MER)
        )


    # Termine exergetico associato all'hot MER residuo.
    fattore_hot = (
        (T_f - T0)
        / T_f
    )


    # Variabile che rappresenta il consumo exergetico totale.
    FinalExergy = modello.continuous_var(
        lb=0,
        name="FinalExergy",
    )


    modello.add_constraint(
        FinalExergy
        ==
        NHL[1, 1] * fattore_cold
        +
        NHL[Z, S_Z] * fattore_hot
        +
        TEC
    )


    # CPLEX deve minimizzare il consumo exergetico totale.
    modello.minimize(
        FinalExergy
    )
    # -------------------------------------------------
    # 13. OUTPUT DELLA FUNZIONE
    # -------------------------------------------------

    return (
    modello,
    BoolHPPr,
    FHPPr,
    Pprel,
    Papp,
    NHL,
    Pelec,
    TEC,
    FinalExergy,
    )
def risolvi_modello_HPPr(
    modello,
    BoolHPPr,
    FHPPr,
    HPPr_candidate,
    TEC,
    FinalExergy,
    tolleranza=1e-6,
):

    # -------------------------------------------------
    # 1. RISOLUZIONE DEL MODELLO
    # -------------------------------------------------

    soluzione = modello.solve(
        log_output=True
    )

    # Se CPLEX non trova una soluzione.
    if soluzione is None:
        print("Nessuna soluzione trovata dal modello.")
        return None


    # -------------------------------------------------
    # 2. DIZIONARIO DELLE HP CANDIDATE
    # -------------------------------------------------

    candidate_per_indice = {
        (
            hp["y"],
            hp["j"],
            hp["z"],
            hp["k"],
        ): hp

        for hp in HPPr_candidate
    }


    # -------------------------------------------------
    # 3. ESTRAZIONE DELLE HP UTILIZZATE
    # -------------------------------------------------

    HP_selezionate = []

    for indice, hp in candidate_per_indice.items():

        valore_bool = soluzione.get_value(
            BoolHPPr[indice]
        )

        valore_F = soluzione.get_value(
            FHPPr[indice]
        )

        # Consideriamo effettivamente utilizzata una HP
        # se trasferisce una quantità non nulla di calore.
        if valore_F > tolleranza:

            Q_evap = (
                valore_F
                * hp["Qy_kW"]
            )

            COP = hp["COP"]

            Q_cond = (
                Q_evap
                * COP
                / (COP - 1)
            )

            P_elettrica = (
                Q_evap
                / (COP - 1)
            )

            HP_selezionate.append({
                "indice": indice,
                "BoolHPPr": valore_bool,
                "FHPPr": valore_F,

                # Posizione sulla GCC originale
                "Qy_kW": hp["Qy_kW"],
                "Qz_kW": hp["Qz_kW"],
                "T_yj_C": hp["T_yj_C"],
                "T_zk_C": hp["T_zk_C"],

                # Caratteristiche della HP
                "T_evap_C": hp["T_evap_C"],
                "T_cond_C": hp["T_cond_C"],
                "COP": COP,
                "Q_evap_kW": Q_evap,
                "Q_cond_kW": Q_cond,
                "P_elettrica_kW": P_elettrica,
            })

    # -------------------------------------------------
    # 4. RISULTATI GLOBALI
    # -------------------------------------------------

    risultati = {
    "soluzione": soluzione,
    "HP_selezionate": HP_selezionate,
    "TEC_kW": soluzione.get_value(TEC),
    "FinalExergy_kW": soluzione.get_value(
        FinalExergy
    ),
}
    return risultati

def costruisci_GCC_aggiornata(
    soluzione,
    NHL,
    zone_GCC,
):

    zone_milp = [
        list(reversed(zona))
        for zona in reversed(zone_GCC)
    ]

    punti = [
        (
            soluzione.get_value(NHL[y, j]),
            T,
        )
        for y, zona in enumerate(zone_milp, start=1)
        for j, (_, T) in enumerate(zona, start=1)
    ]

    return sorted(
        punti,
        key=lambda punto: punto[1],
        reverse=True,
    )
