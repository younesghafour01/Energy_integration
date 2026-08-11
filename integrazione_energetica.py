import matplotlib.pyplot as plt
from pathlib import Path
from docplex.mp.model import Model


class Flusso:
    def __init__(self, codice,nome, tipo, T_in, T_out, CP, processo, zona, disponibile):
        self.codice=codice
        self.nome=nome
        self.tipo=tipo
        self.T_in=T_in
        self.T_out=T_out
        self.CP=CP
        self.processo=processo
        self.zona=zona
        self.disponibile= disponibile

    def calcola_Q(self): #potenza termica scambiata da un determinato flusso 
        return self.CP*abs(self.T_in-self.T_out)
    
    def calcola_T_traslate(self, delta_T_min): #traslazione delle temperature 
        
        if self.tipo == "hot":
            traslazione = -delta_T_min / 2
        elif self.tipo == "cold":
            traslazione = delta_T_min / 2
        else:
            raise ValueError(f"Tipo non valido per il flusso {self.codice}: {self.tipo}")

        return (
            self.T_in + traslazione,
            self.T_out + traslazione,)

def crea_cascata_termica (flussi, delta_T_min):
# 1. Raccolta dei livelli di temperatura traslata
    temperature= []

    for flusso in flussi:
        if flusso.disponibile:
            T_in_star, T_out_star = flusso.calcola_T_traslate(delta_T_min)
            temperature.extend([T_in_star, T_out_star])
    livelli = sorted(set(temperature), reverse=True)

# 2. Calcolo di ΔH in ogni intervallo
    risultati = []
    cascata_provvisoria = 0.0

    for T_sup, T_inf in zip(livelli,livelli[1:]):
        cp_hot= 0.0
        cp_cold= 0.0
        for flusso in flussi:
            if not flusso.disponibile:
                continue

            T_in_star, T_out_star = flusso.calcola_T_traslate(delta_T_min)
            # Verifica: il flusso copre tutto l'intervallo tra T_sup e T_inf se si allora sommiamo il cp ai caldi se calod ai freddi se freddo
            attivo = (max(T_in_star, T_out_star) >= T_sup) and (min(T_in_star, T_out_star) <= T_inf)
            if attivo:
                if flusso.tipo == "hot":
                    cp_hot += flusso.CP
                elif flusso.tipo == "cold":
                    cp_cold += flusso.CP

        delta_T_intervallo = T_sup - T_inf
        delta_H_hot = cp_hot * delta_T_intervallo
        delta_H_cold = cp_cold * delta_T_intervallo
        delta_H = delta_H_hot - delta_H_cold
        cascata_provvisoria += delta_H

        risultati.append({
            "T_sup": T_sup,
            "T_inf": T_inf,
            "CP_hot": cp_hot,
            "CP_cold": cp_cold,
            "delta_H_hot": delta_H_hot,
            "delta_H_cold": delta_H_cold,
            "delta_H": delta_H,
            "cascata_provvisoria": cascata_provvisoria,
        })
    # 3. calcollo della hot utility minima MER
    valori_cascata = [0.0] + [riga["cascata_provvisoria"] for riga in risultati]
    minimo_cascata = min(valori_cascata)
    QH_min = max(0.0, -minimo_cascata)

    for riga in risultati:
        riga["cascata_finale"] = (riga["cascata_provvisoria"] + QH_min)

    QC_min = risultati[-1]["cascata_finale"]

    pinch_traslati = []

    # Controllo del limite superiore della cascata.
    if abs(QH_min) < 1e-9:
        pinch_traslati.append(risultati[0]["T_sup"])

    # Controllo dei limiti inferiori degli intervalli.
    for riga in risultati:
        if abs(riga["cascata_finale"]) < 1e-9:
            pinch_traslati.append(riga["T_inf"])

    return risultati, QH_min, QC_min, pinch_traslati

def costruisci_curve_composite(risultati, QH_min, QC_min, delta_T_min, tolleranza=1e-9):

    """Costruisce separatamente Hot CC e Cold CC traslate."""

    Q_hot_totale = sum(riga["delta_H_hot"] for riga in risultati)
    Q_cold_totale = sum(riga["delta_H_cold"] for riga in risultati)

    def costruisci_lato(
        chiave_CP,
        chiave_delta_H,
        Q_iniziale,):
        # Intervalli nei quali esiste almeno un flusso
        # del tipo considerato.
        indici_attivi = [ indice for indice, riga in enumerate(risultati)
            if riga[chiave_CP] > tolleranza]

        if not indici_attivi:
            return []

        primo = indici_attivi[0]
        ultimo = indici_attivi[-1]

        # Elimina gli intervalli esterni nei quali CP = 0.
        intervalli = list( reversed(risultati[primo:ultimo + 1]))

        Q = Q_iniziale
        punti = [(Q, intervalli[0]["T_inf"])]

        for indice, riga in enumerate(intervalli):
            Q += riga[chiave_delta_H]

            ultimo_intervallo = ( indice == len(intervalli) - 1)

            if ultimo_intervallo:
                cambia_CP = True
            else:
                CP_successivo = intervalli[indice + 1][chiave_CP]
                cambia_CP = (abs(riga[chiave_CP] - CP_successivo)> tolleranza )

            # Aggiunge solamente estremi e veri cambi di pendenza.
            if cambia_CP:
                punti.append((Q, riga["T_sup"]))

        return punti

    hot_CC_traslata = costruisci_lato(
        chiave_CP="CP_hot",
        chiave_delta_H="delta_H_hot",
        Q_iniziale=0.0,
    )

    cold_CC_traslata = costruisci_lato(
        chiave_CP="CP_cold",
        chiave_delta_H="delta_H_cold",
        Q_iniziale=QC_min,
    )

    hot_CC = [ (Q, T_star + delta_T_min / 2) for Q, T_star in hot_CC_traslata]
    cold_CC = [(Q, T_star - delta_T_min / 2)  for Q, T_star in cold_CC_traslata ]

    return hot_CC_traslata, cold_CC_traslata, hot_CC, cold_CC

def costruisci_GCC(risultati, QH_min):

    gcc=[]
    T_max= risultati[0]["T_sup"]
    gcc.append((QH_min, T_max))

    for riga in risultati:
        Q_netto = riga["cascata_finale"]
        T_star = riga["T_inf"]
        gcc.append((Q_netto, T_star))

    return gcc

def self_sufficient_pockets(gcc, delta_T_min, tolleranza=1e-9):
    """Individua MPP, PPP e self-sufficient pockets sulla GCC."""

    def crea_record(codice, tipo, indice, posizione):
        """Crea il dizionario contenente i dati del punto."""
        Q, T_star = gcc[indice]

        return {
            "codice": codice,
            "tipo": tipo,
            "indice_gcc": indice,
            "Q_kW": 0.0 if abs(Q) <= tolleranza else Q,
            "T_traslata_C": T_star,
            "T_hot_C": T_star + delta_T_min / 2,
            "T_cold_C": T_star - delta_T_min / 2,
            "posizione": posizione,
        }

    # Individuazione dei Main Pinch Points.
    indici_mpp = [
        indice
        for indice, (Q, _) in enumerate(gcc)
        if abs(Q) <= tolleranza
    ]

    main_pinch_points = [
        crea_record(
            codice=f"MPP_{numero}",
            tipo="main_pinch_point",
            indice=indice,
            posizione="main_pinch",
        )
        for numero, indice in enumerate(indici_mpp, start=1)
    ]

    primo_mpp = min(indici_mpp)
    ultimo_mpp = max(indici_mpp)

    potential_pinch_points = []
    for indice in range(1, len(gcc) - 1):
        Q_precedente = gcc[indice - 1][0]
        Q_corrente = gcc[indice][0]
        Q_successivo = gcc[indice + 1][0]

        minimo_locale = (
            Q_corrente < Q_precedente - tolleranza
            and Q_corrente < Q_successivo - tolleranza
        )

        if Q_corrente <= tolleranza or not minimo_locale:
            continue

        if indice < primo_mpp:
            posizione = "sopra_main_pinch"
        elif indice > ultimo_mpp:
            posizione = "sotto_main_pinch"
        else:
            posizione = "tra_main_pinch"

        potential_pinch_points.append(
            crea_record(
                codice=f"PPP_{len(potential_pinch_points) + 1}",
                tipo="potential_pinch_point",
                indice=indice,
                posizione=posizione,
            )
        )

    pockets = []
    indice_pinch = next(
        indice
        for indice, (Q, _) in enumerate(gcc)
        if abs(Q) < tolleranza
    )

    punti_sopra = gcc[:indice_pinch + 1]
    punti_sotto = list(reversed(gcc[indice_pinch:]))

    for nome_zona, punti_zona in [
        ("sopra_pinch", punti_sopra),
        ("sotto_pinch", punti_sotto),
    ]:
        for indice in range(len(punti_zona) - 2):
            Q_inizio, T_inizio = punti_zona[indice]
            Q_successivo, _ = punti_zona[indice + 1]

            estremo_esterno = indice == 0
            minimo_locale = (
                indice > 0
                and Q_inizio <= punti_zona[indice - 1][0] + tolleranza
                and Q_successivo > Q_inizio + tolleranza
            )

            if not (estremo_esterno or minimo_locale):
                continue

            if Q_successivo <= Q_inizio + tolleranza:
                continue

            for indice_fine in range(indice + 2, len(punti_zona)):
                Q_precedente, T_precedente = punti_zona[indice_fine - 1]
                Q_corrente, T_corrente = punti_zona[indice_fine]

                attraversa_riferimento = (
                    min(Q_precedente, Q_corrente) - tolleranza
                    <= Q_inizio
                    <= max(Q_precedente, Q_corrente) + tolleranza
                )

                if not attraversa_riferimento:
                    continue

                denominatore = Q_corrente - Q_precedente
                if abs(denominatore) < tolleranza:
                    T_fine = T_precedente
                else:
                    frazione = (Q_inizio - Q_precedente) / denominatore
                    T_fine = T_precedente + frazione * (T_corrente - T_precedente)

                pockets.append({
                    "zona": nome_zona,
                    "Q_riferimento_kW": Q_inizio,
                    "T_inizio_traslata_C": T_inizio,
                    "T_fine_traslata_C": T_fine,
                    "punti_gcc": punti_zona[indice:indice_fine] + [(Q_inizio, T_fine)],
                })
                break

    return {
        "main_pinch_points": main_pinch_points,
        "potential_pinch_points": potential_pinch_points,
        "pockets": pockets,
    }

def discretizza_GCC(gcc, punti_pinch, delta_T_max, tolleranza=1e-9):

    limiti = sorted({
        0,
        len(gcc) - 1,
        *[
            punto["indice_gcc"]
            for tipo in ("main_pinch_points", "potential_pinch_points")
            for punto in punti_pinch[tipo]
        ]
    })

    zone_discretizzate = []

    for inizio, fine in zip(limiti, limiti[1:]):

        zona = gcc[inizio:fine + 1]

        vertici = [zona[0]]

        for p1, p2, p3 in zip(zona, zona[1:], zona[2:]):

            Q1, T1 = p1
            Q2, T2 = p2
            Q3, T3 = p3

            if abs((Q2-Q1)*(T3-T2) - (T2-T1)*(Q3-Q2)) > tolleranza:
                vertici.append(p2)

        vertici.append(zona[-1])

        zona_discretizzata = [vertici[0]]

        for (Q1, T1), (Q2, T2) in zip(vertici, vertici[1:]):

            n = 1

            while abs(T2 - T1) / n > delta_T_max:
                n *= 2

            zona_discretizzata += [
                (
                    Q1 + (Q2-Q1) * i/n,
                    T1 + (T2-T1) * i/n
                )
                for i in range(1, n + 1)
            ]

        zone_discretizzate.append(zona_discretizzata)

    return zone_discretizzate

def genera_HPPr_candidate(
    zone_GCC,
    eta_ex,
    EvaP,
    CondP,
    T_cond_max
):

    zone_milp = [
    list(reversed(zona))
    for zona in reversed(zone_GCC)
    ]
    candidate = []

    for y in range(len(zone_milp) - 1):
        for z in range(y + 1, len(zone_milp)):

            for j, (Qy, Ty_C) in enumerate(zone_milp[y], start=1):
                for k, (Qz, Tz_C) in enumerate(zone_milp[z], start=1):

                    if Ty_C >= Tz_C:
                        continue

                    Ty_K = Ty_C + 273.15
                    Tz_K = Tz_C + 273.15

                    # Vincolo [31] dell'articolo
                    if Tz_K > T_cond_max:
                        continue

                    T_evap_K = Ty_K - EvaP
                    T_cond_K = Tz_K + CondP

                    COP = (
                        eta_ex
                        * T_cond_K
                        / (T_cond_K - T_evap_K)
                    )

                    candidate.append({
                        "y": y + 1,
                        "j": j,
                        "z": z + 1,
                        "k": k,
                        "Qy_kW": Qy,
                        "Qz_kW": Qz,
                        "T_yj_C": Ty_C,
                        "T_zk_C": Tz_C,
                        "T_evap_C": T_evap_K - 273.15,
                        "T_cond_C": T_cond_K - 273.15,
                        "COP": COP,
                    })

    return candidate

def costruisci_curva_utilities_HP(hp_selezionate):
    """Costruisce la utility composite curve delle HP selezionate."""

    eventi = {}

    for hp in hp_selezionate:

        T_evap = hp["T_evap_C"]
        T_cond = hp["T_cond_C"]

        eventi[T_evap] = (
            eventi.get(T_evap, 0.0)
            - hp["Q_evap_kW"]
        )

        eventi[T_cond] = (
            eventi.get(T_cond, 0.0)
            + hp["Q_cond_kW"]
        )

    Q = 0.0
    curva = []

    for T, delta_Q in sorted(eventi.items()):

        curva.append((Q, T))

        Q += delta_Q

        curva.append((Q, T))

    if not curva:
        return []

    # Trasla la curva verso destra in modo
    # che l'ascissa minima sia zero.
    Q_min = min(Q for Q, _ in curva)

    return [
        (Q - Q_min, T)
        for Q, T in curva
    ]

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

def grafico_TQ(
    tipo_grafico,
    hot_CC=None,
    cold_CC=None,
    gcc=None,
    utility_curve=None,
    pockets=None,
    pinch_data=None,
    percorso_salvataggio=None,
    mostra=True,
):
    """Rappresenta Composite Curves, GCC oppure self-sufficient pockets."""

    fig, ax = plt.subplots(figsize=(8, 6))

    if tipo_grafico in ("composite", "composite_traslate"):
        Q_hot, T_hot = zip(*hot_CC)
        Q_cold, T_cold = zip(*cold_CC)

        ax.plot(
            Q_hot,
            T_hot,
            color="red",
            marker="o",
            label="Hot CC",
        )

        ax.plot(
            Q_cold,
            T_cold,
            color="blue",
            marker="o",
            label="Cold CC",
        )

        if tipo_grafico == "composite":
            ax.set_title("Composite Curves – temperature reali")
            ax.set_ylabel("Temperatura reale [°C]")
        else:
            ax.set_title("Composite Curves – temperature traslate")
            ax.set_ylabel("Temperatura traslata T* [°C]")

    elif tipo_grafico == "gcc":
        Q, T = zip(*gcc)

        ax.plot(Q, T, color="red", marker="o", label="GCC")
        ax.axvline(0, color="black", linestyle="--", linewidth=1)

        ax.set_title("Grand Composite Curve")
        ax.set_ylabel("Temperatura traslata [°C]")

    elif tipo_grafico == "pockets":
    # GCC completa come riferimento.
        if gcc is not None:
            Q, T = zip(*gcc)
            ax.plot(
                Q,
                T,
                color="lightgray",
                linewidth=2,
                label="GCC",
            )

        # Evidenzia ciascuna self-sufficient pocket.
        for indice, pocket in enumerate(pockets, start=1):
            Q_pocket, T_pocket = zip(*pocket["punti_gcc"])

            ax.plot(
                Q_pocket,
                T_pocket,
                marker="o",
                linewidth=3,
                label=f"Pocket {indice}: {pocket['zona']}",
            )

        # MPP e PPP
        if pinch_data is not None:

            mpp = pinch_data["main_pinch_points"]
            ppp = pinch_data["potential_pinch_points"]

            if mpp:
                ax.scatter(
                    [p["Q_kW"] for p in mpp],
                    [p["T_traslata_C"] for p in mpp],
                    marker="s",
                    s=50,
                    label="MPP",
                )
                for p in mpp:
                    ax.annotate(
                        p["codice"],
                        (p["Q_kW"], p["T_traslata_C"]),
                        xytext=(5, 5),
                        textcoords="offset points",
                    )

            if ppp:
                ax.scatter(
                    [p["Q_kW"] for p in ppp],
                    [p["T_traslata_C"] for p in ppp],
                    marker="D",
                    s=40,
                    label="PPP",
                )
                for p in ppp:
                    ax.annotate(
                        p["codice"],
                        (p["Q_kW"], p["T_traslata_C"]),
                        xytext=(5, -10),
                        textcoords="offset points",
                    )

        ax.axvline(0, color="black", linestyle="--", linewidth=1)

        ax.set_title("Self-sufficient pockets")
        ax.set_ylabel("Temperatura traslata [°C]")

    
    elif tipo_grafico == "icc":

        # GCC del processo.
        Q, T = zip(*gcc)

        ax.plot(
            Q,
            T,
            color="red",
            linewidth=2,
            label="GCC",
        )

            # Utility Composite Curve.
        if utility_curve:

            Q_ut, T_ut = zip(*utility_curve)

            ax.plot(
                Q_ut,
                T_ut,
                color="green",
                linewidth=2,
                label="Utilities",
            )

        ax.axvline(
            0,
            color="black",
            linestyle="--",
            linewidth=1,
        )

        ax.set_title(
            "Integrated Composite Curve"
        )

        ax.set_ylabel(
            "Temperatura [°C]"
        )
    else:
        raise ValueError(
            "tipo_grafico deve essere 'composite', "
            "'composite_traslate', 'gcc', "
            "'icc' oppure 'pockets'."
        )

    ax.set_xlabel("Potenza termica cumulata Q [kW]")
    ax.grid(True, linestyle="--", alpha=0.4)
    ax.legend()

    # Salvataggio del grafico prima della visualizzazione.
    if percorso_salvataggio is not None:
        percorso_salvataggio = Path(percorso_salvataggio)

        percorso_salvataggio.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        fig.savefig(
            percorso_salvataggio,
            dpi=300,
            bbox_inches="tight",
        )

        print(f"Grafico salvato in: {percorso_salvataggio}")

    if mostra:
        plt.show()
    else:
        plt.close(fig)

    return fig, ax