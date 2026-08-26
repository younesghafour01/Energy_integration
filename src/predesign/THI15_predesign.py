"""Predesign delle utility.

Architettura del modulo
------------------------------------
1_INPUT: strutture e caricamento importati dall'infrastruttura comune.
2_NORMALIZZAZIONE: conversione Pinch importata dall'infrastruttura comune.
3_INSIEMI_E_INDICI: cascata/GCC condivise; MPP/PPP e pockets specifici.
4_PINCH_ANALYSIS
5_DISCRETIZZAZIONE: :func:`discretizza_GCC`.
6_VARIABILI, 7_VINCOLI, 8_FUNZIONE_OBIETTIVO: MODELLO MATEMATICO
9_SOLVE: :func:`risolvi_modello_utilities`.
10_POST_PROCESSING: ricostruzione delle utility e delle curve T-Q.
11_STAMPA RISULTATI E GRAFICI: Stampa dei risultati e salvataggio grafici costruiti.


"""

# ============================================================================
# SHARED INFRASTRUCTURE - INPUT, CONVERSIONE PINCH, CASCATA E GCC
# ============================================================================
from docplex.mp.model import Model
from pathlib import Path

from src.common.thermal_preprocessing import (
    Flusso,
    carica_caso_studio,
    converti_temperatura_pinch as converti_temperatura,
    crea_cascata_termica,
    costruisci_GCC,
)

# Le cinque funzioni importate da ``thermal_preprocessing`` hanno semantica
# identica anche nella pipeline HENS. Da questo punto iniziano gli algoritmi
# specifici del predesign: Composite Curves, pockets e discretizzazione GCC.

def costruisci_curve_composite(flussi, risultati, QC_min, tolleranza=1e-9):
    """Costruisce Hot/Cold Composite Curves reali e traslate.

    Ruolo
    -----
    Integra i carichi lungo i livelli termici per il controllo grafico della
    Pinch Analysis.

    Riferimento bibliografico
    ------------------------
    Thibault et al. (2015), Sec. 2.1.1 e Fig. 2.

    .

    Input / Output
    --------------
    Restituisce quattro liste ordinate di tuple ``(Q_kW, T_C)``.

    Note implementative
    --------------------
    Le correnti isotermiche producono salti orizzontali espliciti.
    """

    # Costruisce una Composite Curve sulla scala traslata T*
    # usando i risultati già calcolati dalla cascata termica.
    def costruisci_lato_traslato(chiave_CP, chiave_delta_H, Q_iniziale):

        indici_attivi = [
            i for i, riga in enumerate(risultati)
            if riga[chiave_CP] > tolleranza
            or riga[chiave_delta_H] > tolleranza
        ]

        if not indici_attivi:
            return []

        # Considera solo la zona attiva e la percorre dal basso verso l'alto.
        elementi = list(
            reversed(risultati[indici_attivi[0] : indici_attivi[-1] + 1])
        )

        Q = Q_iniziale
        punti = [(Q, elementi[0]["T_inf"])]

        # Somma progressivamente il calore e genera i punti (Q, T*).
        for riga in elementi:
            Q += riga[chiave_delta_H]
            punti.append((Q, riga["T_sup"]))

        return punti

    # Costruisce una Composite Curve direttamente sulla scala reale.
    def costruisci_lato_reale(tipo, Q_iniziale):

        flussi_lato = [
            flusso for flusso in flussi
            if flusso.disponibile and flusso.tipo == tipo
        ]

        if not flussi_lato:
            return []

        # Livelli di temperatura reale del lato considerato.
        livelli = sorted(
            {
                temperatura
                for flusso in flussi_lato
                for temperatura in (flusso.T_in, flusso.T_out)
            }
        )

        # Raggruppa gli eventuali carichi isotermi per temperatura.
        carichi_isotermi = {}

        for flusso in flussi_lato:
            if flusso.isotermo:
                carichi_isotermi[flusso.T_in] = (
                    carichi_isotermi.get(flusso.T_in, 0.0)
                    + flusso.calcola_Q()
                )

        Q = Q_iniziale
        punti = [(Q, livelli[0])]

        # Costruisce la curva dalla temperatura più bassa alla più alta.
        for indice, T_inf in enumerate(livelli):

            if T_inf in carichi_isotermi:
                Q += carichi_isotermi[T_inf]
                punti.append((Q, T_inf))

            if indice == len(livelli) - 1:
                break

            T_sup = livelli[indice + 1]
            CP_totale = 0.0

            # Somma i CP delle correnti presenti nell'intervallo.
            for flusso in flussi_lato:
                if flusso.isotermo:
                    continue

                T_max = max(flusso.T_in, flusso.T_out)
                T_min = min(flusso.T_in, flusso.T_out)

                if T_max >= T_sup and T_min <= T_inf:
                    CP_totale += flusso.CP

            # Aggiorna il calore cumulativo e aggiunge il nuovo punto.
            Q += CP_totale * (T_sup - T_inf)
            punti.append((Q, T_sup))

        return punti

    # Curve sulla scala traslata T*
    hot_CC_traslata = costruisci_lato_traslato("CP_hot", "delta_H_hot", 0.0)
    cold_CC_traslata = costruisci_lato_traslato("CP_cold", "delta_H_cold", QC_min)

    # Curve sulla scala reale
    hot_CC = costruisci_lato_reale("hot", 0.0)
    cold_CC = costruisci_lato_reale("cold", QC_min)

    return hot_CC_traslata, cold_CC_traslata, hot_CC, cold_CC

#le pinch rules sono una cosa da rispettare per non andare ad aumentare il MER e il MER cold definito dalla GCC che abbiamo costruito
#le pinch rules sono implementate nel modello matematico per la costruzione del MILP

def self_sufficient_pockets(
    gcc,
    delta_T_min,
    tolleranza=1e-9,
):
    """Individua MPP, PPP e self-sufficient pockets sulla GCC.

    Ruolo
    -----
    Delimita le zone termiche usate dalla discretizzazione del MILP.

    Riferimento bibliografico
    ------------------------
    Thibault et al. (2015), Sec. 2.1.1 e Fig. 1.

    Oggetti matematici
    ------------------
    Main Pinch Point, Potential Pinch Points, insieme delle pockets e limiti
    delle zone ``z = 1, ..., Z``.

    Input / Output
    --------------
    Legge punti GCC ``(Q, T*)`` e restituisce record indicizzati per posizione
    nella GCC, temperatura e carico.

    """

    # ---------------------------------------------------------
    # FUNZIONE AUSILIARIA
    # ---------------------------------------------------------

    def crea_record(
        codice,
        tipo,
        indice,
        posizione,
    ):
        """Costruisce il record associato a un MPP o PPP."""

        Q, T_star = gcc[indice]

        return {
            "codice": codice,
            "tipo": tipo,
            "indice_gcc": indice,

            "Q_kW": (
                0.0
                if abs(Q) <= tolleranza
                else Q
            ),

            "T_traslata_C": T_star,

            "T_hot_C": converti_temperatura(
                T_star,
                "hot",
                delta_T_min,
                "pinch",
                "reale",
            ),

            "T_cold_C": converti_temperatura(
                T_star,
                "cold",
                delta_T_min,
                "pinch",
                "reale",
            ),

            "posizione": posizione,
        }

    # ---------------------------------------------------------
    # MAIN PINCH POINT
    # ---------------------------------------------------------

    # Il MPP è il punto della GCC con il minimo valore di Q.
    indice_mpp = min(
        range(len(gcc)),
        key=lambda i: gcc[i][0],
    )

    # Per una GCC costruita al MER il minimo deve essere Q = 0.
    if abs(gcc[indice_mpp][0]) > tolleranza:
        raise ValueError(
            "La GCC non presenta un Main Pinch Point ."
        )

    main_pinch_point = crea_record(
        "MPP",
        "main_pinch_point",
        indice_mpp,
        "main_pinch",
    )

    # ---------------------------------------------------------
    # POTENTIAL PINCH POINT
    # ---------------------------------------------------------

    potential_pinch_points = []

    # Un PPP è un minimo locale positivo della GCC.
    for i in range(1, len(gcc) - 1):

        Q_precedente = gcc[i - 1][0]
        Q_corrente = gcc[i][0]
        Q_successivo = gcc[i + 1][0]

        minimo_locale = (
            Q_corrente < Q_precedente - tolleranza
            and Q_corrente < Q_successivo - tolleranza
        )

        # Q = 0 identifica il Main Pinch Point,
        # quindi un PPP deve avere Q > 0.
        if (
            Q_corrente <= tolleranza
            or not minimo_locale
        ):
            continue

        # Posizione rispetto all'unico MPP.
        posizione = (
            "sopra_main_pinch"
            if i < indice_mpp
            else "sotto_main_pinch"
        )

        potential_pinch_points.append(
            crea_record(
                f"PPP_{len(potential_pinch_points) + 1}",
                "potential_pinch_point",
                i,
                posizione,
            )
        )

    # ---------------------------------------------------------
    # SELF-SUFFICIENT POCKETS
    # ---------------------------------------------------------

    pockets = []

    # Divide la GCC nelle regioni sopra e sotto l'unico MPP.
    punti_sopra = gcc[: indice_mpp + 1]

    # La parte sotto pinch viene invertita per analizzarla
    # nello stesso verso logico della parte sopra pinch.
    punti_sotto = list(
        reversed(gcc[indice_mpp:])
    )

    for nome_zona, punti_zona in (
        ("sopra_pinch", punti_sopra),
        ("sotto_pinch", punti_sotto),
    ):

        # Cerca possibili punti di inizio di una pocket.
        for i in range(len(punti_zona) - 2):

            Q_inizio, T_inizio = punti_zona[i]
            Q_successivo, _ = punti_zona[i + 1]

            # Una pocket può iniziare dall'estremo esterno
            # oppure da un minimo locale.
            estremo_esterno = i == 0

            minimo_locale = (
                i > 0
                and Q_inizio
                <= punti_zona[i - 1][0] + tolleranza
                and Q_successivo
                > Q_inizio + tolleranza
            )

            if not (
                estremo_esterno
                or minimo_locale
            ):
                continue

            # La GCC deve inizialmente allontanarsi
            # dal livello energetico Q_inizio.
            if Q_successivo <= Q_inizio + tolleranza:
                continue

            # Cerca il ritorno allo stesso livello energetico.
            for i_fine in range(
                i + 2,
                len(punti_zona),
            ):

                Q_precedente, T_precedente = (
                    punti_zona[i_fine - 1]
                )

                Q_corrente, T_corrente = (
                    punti_zona[i_fine]
                )

                attraversa = (
                    min(
                        Q_precedente,
                        Q_corrente,
                    ) - tolleranza
                    <= Q_inizio
                    <= max(
                        Q_precedente,
                        Q_corrente,
                    ) + tolleranza
                )

                if not attraversa:
                    continue

                # Temperatura esatta alla quale
                # la GCC ritorna a Q_inizio.
                denominatore = (
                    Q_corrente
                    - Q_precedente
                )

                if abs(denominatore) < tolleranza:

                    T_fine = T_precedente

                else:

                    frazione = (
                        Q_inizio
                        - Q_precedente
                    ) / denominatore

                    T_fine = (
                        T_precedente
                        + frazione
                        * (
                            T_corrente
                            - T_precedente
                        )
                    )

                pockets.append(
                    {
                        "zona": nome_zona,

                        "Q_riferimento_kW":
                            Q_inizio,

                        "T_inizio_traslata_C":
                            T_inizio,

                        "T_fine_traslata_C":
                            T_fine,

                        "punti_gcc": (
                            punti_zona[i:i_fine]
                            + [
                                (
                                    Q_inizio,
                                    T_fine,
                                )
                            ]
                        ),
                    }
                )

                # Per questo punto iniziale interessa
                # soltanto la prima chiusura della pocket.
                break

    return {
        # Manteniamo una lista di un elemento perché
        # discretizza_GCC(), plotting e diagnostica
        # utilizzano già questa struttura.
        "main_pinch_points": [
            main_pinch_point
        ],

        "potential_pinch_points":
            potential_pinch_points,

        "pockets":
            pockets,
    }


# ============================================================================
# 4_ANALSI PINCH
# ============================================================================

def esegui_analisi_pinch(percorso_json):
    """Esegue gli stadi di preprocessing che producono la GCC del MILP.

    Input / Output
    --------------
    Accetta il percorso JSON e restituisce un dizionario immutato nella forma
    consumata da :func:`esegui_predesign_utilities`.

    Note implementative
    --------------------
    Funzione orchestratrice: non aggiunge equazioni matematiche proprie.
    """

    configurazione = carica_caso_studio(percorso_json)

    flussi = configurazione["flussi"]
    delta_T_min = configurazione["delta_T_min"]

    # Heat cascade, MER e pinch point.
    (
        risultati_cascata,
        QH_min,
        QC_min,
        pinch_traslati,
    ) = crea_cascata_termica(
        flussi,
        delta_T_min,
    )

    # Composite Curves reali e traslate.
    (
        hot_CC_star,
        cold_CC_star,
        hot_CC,
        cold_CC,
    ) = costruisci_curve_composite(
        flussi,
        risultati_cascata,
        QC_min,
    )

    # Grand Composite Curve.
    gcc = costruisci_GCC(
        risultati_cascata,
        QH_min,
    )

    # MPP, PPP e self-sufficient pockets.
    pinch_data = self_sufficient_pockets(
        gcc,
        delta_T_min,
    )

    return {
        "configurazione": configurazione,
        "risultati_cascata": risultati_cascata,
        "QH_min_kW": QH_min,
        "QC_min_kW": QC_min,
        "pinch_traslati_C": pinch_traslati,
        "hot_CC_traslata": hot_CC_star,
        "cold_CC_traslata": cold_CC_star,
        "hot_CC": hot_CC,
        "cold_CC": cold_CC,
        "gcc": gcc,
        "pinch_data": pinch_data,
    }



# ============================================================================
# 5_DISCRETIZZAZIONE - ZONE E PUNTI DELLA GCC
# ============================================================================

def discretizza_GCC(gcc, punti_pinch, delta_T_max, tolleranza=1e-9):
    """Divide la GCC in zone e discretizza ogni tratto angolare.

    Ruolo
    -----
    Costruisce ``Z``, ``S_z`` e i punti ``(Q_z,k, T_z,k)``.

    Riferimento bibliografico
    ------------------------
    Thibault et al. (2015), Sec. 2.1.1: zone delimitate da MPP/PPP, angular
    points e dimezzamento degli intervalli oltre il passo massimo.

    Oggetti matematici
    ------------------
    ``Z``, ``S_z``, ``Q_z,k`` e ``T_z,k``.

    Input / Output
    --------------
    Restituisce le zone nel verso grafico e il dizionario ``S_z`` nel verso
    matematico (zona 1 fredda, zona Z calda).

    """

    # MPP e PPP delimitano le zone della GCC. ricercchiamo gli
    # indici che delimitano le zone in cui vogliamo iniziare a discretizzare la curva
    limiti_zone = sorted({0,len(gcc) - 1,*[punto["indice_gcc"]
                                           for tipo in ("main_pinch_points", "potential_pinch_points")
                                           for punto in punti_pinch[tipo] ],
        }
    )

    # Le zone vengono inizialmente costruite nell'ordine della GCC:
    # dalla temperatura più alta alla più bassa.
    zone_GCC = []

    for inizio, fine in zip(limiti_zone, limiti_zone[1:]):
        zona = gcc[inizio : fine + 1]
        # Angular points: punti nei quali cambia la pendenza della GCC.
        vertici = [zona[0]]
        for p1, p2, p3 in zip(zona, zona[1:], zona[2:]):
            Q1, T1 = p1
            Q2, T2 = p2
            Q3, T3 = p3
            cambio_pendenza = abs(
                (Q2 - Q1) * (T3 - T2)
                - (T2 - T1) * (Q3 - Q2)
            ) > tolleranza

            if cambio_pendenza:
                vertici.append(p2)
        vertici.append(zona[-1])

        # Punti discretizzati (Q, T) della zona.
        punti_zona = [vertici[0]]

        for (Q1, T1), (Q2, T2) in zip(
            vertici,
            vertici[1:],
        ):
            n = 1

            # Il tratto viene dimezzato finché rispetta delta_T_max.
            while abs(T2 - T1) / n > delta_T_max:
                n *= 2

            punti_zona.extend(
                (
                    Q1 + (Q2 - Q1) * k / n,
                    T1 + (T2 - T1) * k / n,
                )
                for k in range(1, n + 1)
            )

        zone_GCC.append(punti_zona)

    # Nel modello matematico:
    # z=1 è la zona più fredda e z=Z la più calda.
    #
    # S_z è l'estremo dell'indice k:
    # k = 1, ..., S_z.
    S_z = {
        z: len(zona)
        for z, zona in enumerate(
            reversed(zone_GCC),
            start=1,
        )
    }

    return zone_GCC, S_z

def riordina_zone_per_milp(zone_GCC):
    """Riordina zone e punti secondo gli indici ``(z, k)`` della fonte.


    Input / Output
    --------------
    Converte l'ordine grafico in ``z=1`` zona più fredda, ``z=Z`` più calda,
    con ``k=1`` punto più freddo.
    """
    return [list(reversed(zona)) for zona in reversed(zone_GCC)]


# ============================================================================
# 6_VARIABILI, 7_VINCOLI, 8_FUNZIONE_OBIETTIVO - MODELLO MATEMATICO
# ============================================================================

def genera_candidate_utilities(
    zone_GCC,
    utilities,
    eta_ex,
    EvaP,
    CondP,
    T0,
    T_f,
    T_cond_max=None,
):
    """Genera utility candidate e precalcola COP/efficienze.

    Ruolo
    -----
    Enumera le configurazioni ammissibili prima della creazione del MILP.

    Riferimento bibliografico
    ------------------------
    Thibault et al. (2015), Eq. (1)-(5) per HPPr, HPUt, chiller, ORC e CHP;
    Eq. (28)-(32) per i limiti di collocazione e ``TCondmax``.

    Oggetti matematici
    ------------------
    ``COPPacPr_y,j,z,k``, ``COPPacUt_z,k``, ``COPGf_z,k``, ``EffOrc_z,k`` e
    ``EffChp_k``. Indici Python: HPPr ``(y,j,z,k)``, HPUt/Ref/ORC ``(z,k)``,
    CHP ``k`` nella zona ``Z``.

    Input / Output
    --------------
    Riceve zone GCC e parametri termodinamici; restituisce record numerici che
    diventano le mappe di indice delle variabili ``Bool*`` e ``F*``.

    Note implementative
    --------------------
    Temperature assolute in kelvin;
    """

    # Il modello usa:
    # zona 1 = zona a temperatura più bassa
    # zona Z = zona a temperatura più alta.
    zone_milp = riordina_zone_per_milp(zone_GCC)
    Z = len(zone_milp)

    candidati = {
        "HPPr": [],
        "HPUt": [],
        "Ref": [],
        "ORC": [],
        "CHP": [],
    }

    # ============================================================
    # THI15 Eq. (1): HPPr tra una sorgente (y,j) e un pozzo (z,k).
    # Collega un punto (y,j) a temperatura inferiore
    # con un punto (z,k) a temperatura superiore.
    # ============================================================

    if utilities["HPPr"]["enabled"]:

        for y in range(1, Z):
            for z in range(y + 1, Z + 1):

                for j, (Q_yj, T_yj_C) in enumerate(
                    zone_milp[y - 1],
                    start=1,
                ):
                    for k, (Q_zk, T_zk_C) in enumerate(
                        zone_milp[z - 1],
                        start=1,
                    ):

                        # La HP deve trasferire calore
                        # dal livello freddo al livello caldo.
                        if T_yj_C >= T_zk_C:
                            continue

                        T_yj = T_yj_C + 273.15
                        T_zk = T_zk_C + 273.15

                        # Eventuale limite massimo della condensazione.
                        # THI15 Eq. (31): limite TCondmax per HPPr.
                        if T_cond_max is not None and T_zk > T_cond_max:
                            continue

                        T_evap = T_yj - EvaP #Evap è il delta_T di scambio dell'evaporatore
                        T_cond = T_zk + CondP

                        denominatore = T_cond - T_evap

                        if denominatore <= 0:
                            continue

                        # THI15 Eq. (1).
                        COP_HPPr = (
                            eta_ex
                            * T_cond
                            / denominatore
                        )

                        if COP_HPPr <= 1: # ha trovato le possibili pompe che si possono creare con quella temperatura k
                            continue

                        candidati["HPPr"].append(
                            {
                                "y": y,
                                "j": j,
                                "z": z,
                                "k": k,

                                "Q_yj_kW": Q_yj,
                                "Q_zk_kW": Q_zk,

                                "T_yj_C": T_yj_C,
                                "T_zk_C": T_zk_C,

                                "T_evap_C": T_evap - 273.15,
                                "T_cond_C": T_cond - 273.15,

                                "COP_HPPr": COP_HPPr,
                            }
                        )

    # ============================================================
    # THI15 Eq. (2)-(5).
    # HPUt, Ref e ORC sono associate a un punto (z,k).
    # Il CHP è associato al punto k della zona più calda Z.
    # ============================================================

    for z, zona_z in enumerate(zone_milp, start=1):

        for k, (Q_zk, T_zk_C) in enumerate(
            zona_z,
            start=1,
        ):

            T_zk = T_zk_C + 273.15

            # ----------------------------------------------------
            # THI15 Eq. (2): HPUt tra ambiente e punto (z,k).
            #
            # Evaporatore alla sorgente ambiente T0;
            # condensatore al livello termico (z,k).
            # ----------------------------------------------------

            if utilities["HPUt"]["enabled"]:

                T_evap = T0 - EvaP
                T_cond = T_zk + CondP

                # THI15 Eq. (28) e (32): limiti T0 e TCondmax per HPUt.
                ammessa = (
                    z > 1
                    and T_zk >= T0
                    and (
                        T_cond_max is None
                        or T_zk <= T_cond_max
                    )
                )

                denominatore = T_cond - T_evap

                if ammessa and denominatore > 0:

                    COP_HPUt = (
                        eta_ex
                        * T_cond
                        / denominatore
                    )

                    if COP_HPUt > 1:

                        candidati["HPUt"].append(
                            {
                                "z": z,
                                "k": k,

                                "Q_zk_kW": Q_zk,
                                "T_zk_C": T_zk_C,

                                "T_evap_C": T_evap - 273.15,
                                "T_cond_C": T_cond - 273.15,

                                "COP_HPUt": COP_HPUt,
                            }
                        )

            # ----------------------------------------------------
            # THI15 Eq. (3): refrigerazione/chiller.
            #
            # Evaporatore al livello (z,k);
            # condensatore verso l'ambiente T0.
            # ----------------------------------------------------

            if (
                utilities["chiller"]["enabled"]
                and z < Z
                and T_zk <= T0
            ):

                T_evap = T_zk - EvaP
                T_cond = T0 + CondP

                denominatore = T_cond - T_evap

                if denominatore > 0:

                    # THI15 Eq. (3).
                    COP_ref = (
                        eta_ex
                        * T_cond
                        / denominatore
                    )

                    if COP_ref > 1:

                        candidati["Ref"].append(
                            {
                                "z": z,
                                "k": k,

                                "Q_zk_kW": Q_zk,
                                "T_zk_C": T_zk_C,

                                "T_evap_C": T_evap - 273.15,
                                "T_cond_C": T_cond - 273.15,

                                "COP_ref": COP_ref,
                            }
                        )

            # ----------------------------------------------------
            # THI15 Eq. (4): efficienza ORC.
            #
            # Preleva calore dal processo al punto (z,k)
            # e scarica verso l'ambiente.
            # ----------------------------------------------------

            if (
                utilities["ORC"]["enabled"]
                and z < Z
                and T_zk >= T0
            ):

                T_hot = T_zk - CondP
                T_cold = T0 + EvaP

                if T_hot > T_cold:

                    # THI15 Eq. (4).
                    Eff_ORC = (
                        eta_ex
                        * (1 - T_cold / T_hot)
                    )

                    if 0 < Eff_ORC < 1:

                        candidati["ORC"].append(
                            {
                                "z": z,
                                "k": k,

                                "Q_zk_kW": Q_zk,
                                "T_zk_C": T_zk_C,

                                "T_hot_C": T_hot - 273.15,
                                "T_reject_C": T_cold - 273.15,

                                "Eff_ORC": Eff_ORC,
                            }
                        )

            # ----------------------------------------------------
            # THI15 Eq. (5): efficienza CHP.
            #
            # È definito solamente nella zona più calda Z.
            # ----------------------------------------------------

            if (
                utilities["CHP"]["enabled"]
                and z == Z
            ):

                denominatore = T_f - CondP

                if denominatore <= 0:
                    continue

                # THI15 Eq. (5).
                Eff_CHP = (
                    eta_ex
                    * (
                        1
                        - (T_zk + EvaP)
                        / denominatore
                    )
                )

                if 0 < Eff_CHP < 1:

                    candidati["CHP"].append(
                        {
                            "k": k,

                            "Q_Zk_kW": Q_zk,
                            "T_Zk_C": T_zk_C,

                            # Nome usato poi dal post-processing.
                            "T_processo_C": T_zk_C,

                            "T_fiamma_C": (
                                T_f
                                - CondP
                                - 273.15
                            ),

                            "Eff_CHP": Eff_CHP,
                        }
                    )

    return candidati


def crea_modello_utilities(
    candidati,
    zone_GCC,
    utilities,
    T0,
    T_f,
    eta_ex,
):
    """Costruisce, senza risolverlo, il MILP di predesign delle utility.

    Ruolo
    -----
    Crea parametri, variabili, vincoli e funzione obiettivo nello stesso ordine
    concettuale della formulazione pubblicata.

    Riferimento bibliografico
    ------------------------
    Thibault et al. (2015), Eq. (6)-(33): presenza e numerosità (6)-(14),
    bilanci energetici (15)-(19), aggiornamento GCC (20)-(22), elettricità e
    CHP (23)-(27), collocazione (28)-(32), obiettivo exergetico (33).

    Oggetti matematici
    ------------------
    Parametri ``Q_z,k``, ``T_z,k``; variabili ``Bool*``, ``F*``, ``Pprel``,
    ``Papp``, ``NHL``, ``Pelec``, ``TEC``, ``TEP`` e ``PprelChp``;
    funzione obiettivo ``FinalExergy``.

    Input / Output
    --------------
    I record dei candidati diventano mappe indicizzate; il risultato contiene
    il :class:`docplex.mp.model.Model` e le stesse mappe per il post-processing.


    """

    # ============================================================
    # CREAZIONE DEL MODELLO DOCPLEX
    # ============================================================

    # Importiamo la classe Model soltanto quando serve costruire il MILP.
    #
    from docplex.mp.model import Model

    # Model() crea il contenitore matematico del problema.
    #
    # Da questo momento "modello" conterrà:
    # - variabili;
    # - vincoli;
    # - funzione obiettivo.
    modello = Model("preselezione_utilities")

    # ============================================================
    # PREPARAZIONE DELLA GCC
    # ============================================================

    # La GCC originale è memorizzata nel verso grafico.
    #
    # Il modello del PDF usa invece:
    #   z = 1  -> zona più fredda
    #   z = Z  -> zona più calda
    #
    # e all'interno di ogni zona:
    #   k = 1 -> punto più freddo.
    #
    # Questa funzione modifica quindi soltanto l'ordine degli indici,
    # non i valori fisici della GCC.
    zone_milp = riordina_zone_per_milp(zone_GCC)

    # Numero totale di zone del modello.
    Z = len(zone_milp)

    # ============================================================
    # PARAMETRI Q_zk E T_zk DELLA GCC DISCRETIZZATA
    # ============================================================

    # Elenco degli indici (z,k) che esistono nella GCC.
    #
    indici_GCC = []

    # Dizionari contenenti i parametri numerici del modello:
    #
    # Q_GCC[z,k] = coordinata energetica Q_zk
    # T_GCC[z,k] = temperatura T_zk
    # sono dati noti prima della soluzione del MILP.
    Q_GCC = {}
    T_GCC = {}

    for z, zona in enumerate(zone_milp, start=1):

        for k, (Q, T_C) in enumerate(zona, start=1):

            # Salva l'indice matematico (z,k).
            indici_GCC.append((z, k))

            # Parametro energetico Q_zk [kW].
            Q_GCC[z, k] = Q

            # Le equazioni di COP/efficienza utilizzano temperature assolute,
            # quindi la temperatura viene memorizzata in kelvin.
            T_GCC[z, k] = T_C + 273.15

    # Indice k dell'ultimo punto della zona più calda Z.
    #
    # Servirà nelle equazioni che utilizzano NHL_(Z,S_Z).
    k_finale_Z = len(zone_milp[Z - 1])

    # ============================================================
    # MAPPE DELLE UTILITY CANDIDATE
    # ============================================================

    # "candidati" contiene le configurazioni di utility
    # che il preprocessing ha già stabilito essere termodinamicamente
    # possibili.
    #
    # Qui le trasformiamo in dizionari indicizzati esattamente
    # come nel modello matematico.
    #
    # Questo è importante perché DOcplex crea poi una variabile
    # per ciascuna chiave presente in questi dizionari.

    mappe = {

        # Heat pump di processo:
        #
        # prende calore nel punto (y,j)
        # e lo fornisce al punto più caldo (z,k).
        #
        # indice = (y,j,z,k)
        "HPPr": {
            (c["y"], c["j"], c["z"], c["k"]): c
            for c in candidati["HPPr"]
        },

        # Utility heat pump:
        # associata direttamente a un punto (z,k).
        "HPUt": {
            (c["z"], c["k"]): c
            for c in candidati["HPUt"]
        },

        # Refrigerazione/chiller:
        # associata a un punto (z,k).
        "Ref": {
            (c["z"], c["k"]): c
            for c in candidati["Ref"]
        },

        # Organic Rankine Cycle:
        # associato a un punto (z,k).
        "ORC": {
            (c["z"], c["k"]): c
            for c in candidati["ORC"]
        },

        # CHP:
        # può essere collocato soltanto nella zona più calda Z,
        # quindi basta l'indice k.
        "CHP": {
            c["k"]: c
            for c in candidati["CHP"]
        },
    }



    # ============================================================
    # THI15 Eq. (6)-(10): presenza binaria e frazione di utilizzo.
    # VARIABILI DI PRESENZA E FRAZIONI DI UTILIZZO
    # ============================================================

    # Qui compare uno dei concetti fondamentali di DOcplex.
    #
    # binary_var_dict(indici)
    #
    # crea una VARIABILE BINARIA per ogni indice fornito.
    #
    # Una variabile binaria può assumere soltanto:
    #
    #       0 oppure 1
    #
    # Nel nostro problema:
    #
    #       Bool = 1 -> utility installata/selezionata
    #       Bool = 0 -> utility assente

    BoolHPPr = modello.binary_var_dict(
        mappe["HPPr"],
        name="BoolHPPr",
    )

    # continuous_var_dict() crea invece variabili continue.
    #
    # lb = lower bound
    # ub = upper bound
    #
    # quindi:
    #
    #       0 <= FHPPr <= 1
    #
    # F rappresenta la frazione del carico disponibile
    # effettivamente utilizzata dalla utility.
    FHPPr = modello.continuous_var_dict(
        mappe["HPPr"],
        lb=0,
        ub=1,
        name="FHPPr",
    )

    BoolHPUt = modello.binary_var_dict(
        mappe["HPUt"],
        name="BoolHPUt",
    )

    FHPUt = modello.continuous_var_dict(
        mappe["HPUt"],
        lb=0,
        ub=1,
        name="FHPUt",
    )

    BoolRef = modello.binary_var_dict(
        mappe["Ref"],
        name="BoolRef",
    )

    FRef = modello.continuous_var_dict(
        mappe["Ref"],
        lb=0,
        ub=1,
        name="FRef",
    )

    BoolORC = modello.binary_var_dict(
        mappe["ORC"],
        name="BoolORC",
    )

    FORC = modello.continuous_var_dict(
        mappe["ORC"],
        lb=0,
        ub=1,
        name="FORC",
    )

    BoolChp = modello.binary_var_dict(
        mappe["CHP"],
        name="BoolChp",
    )

    FChp = modello.continuous_var_dict(
        mappe["CHP"],
        lb=0,
        ub=1,
        name="FChp",
    )


    # ============================================================
    # COLLEGAMENTO TRA Bool E F
    # ============================================================

    # Per ogni tecnologia imponiamo:
    #
    #               F <= Bool
    #
    # Se:
    #
    # Bool = 0
    #
    # allora necessariamente:
    #
    # F <= 0
    #
    # ma F ha già lower bound 0, quindi:
    #
    # F = 0.
    #
    # Se invece Bool = 1:
    #
    # 0 <= F <= 1
    #
    # e il solver può scegliere liberamente quanta parte
    # del carico utilizzare.

    for F, Bool in (
        (FChp, BoolChp),      # THI15 Eq. (6)
        (FRef, BoolRef),      # THI15 Eq. (7)
        (FORC, BoolORC),      # THI15 Eq. (8)
        (FHPPr, BoolHPPr),    # THI15 Eq. (9)
        (FHPUt, BoolHPUt),    # THI15 Eq. (10)
    ):

        for indice in F:

            # add_constraint() aggiunge un'equazione o disequazione
            # al modello matematico DOcplex.
            #
            # Non viene ancora "calcolata":
            # viene semplicemente memorizzata nel MILP.
            modello.add_constraint(
                F[indice] <= Bool[indice]
            )


    # ============================================================
    # THI15 Eq. (11)-(14): numero massimo di utility.
    # NUMERO MASSIMO DI UTILITY
    # ============================================================

    # modello.sum(...) costruisce una somma simbolica DOcplex.
    #
    # Ad esempio:
    #
    # modello.sum(BoolChp.values())
    #
    # rappresenta matematicamente:
    #
    # Σ BoolChp_k
    #
    # Non restituisce ancora un numero:
    # restituisce un'ESPRESSIONE LINEARE del modello.

    if len(BoolChp) > 0:

        modello.add_constraint(
            modello.sum(BoolChp.values())
            <= utilities["CHP"]["max"]
        )


    if len(BoolRef) > 0:

        modello.add_constraint(
            modello.sum(BoolRef.values())
            <= utilities["chiller"]["max"]
        )


    if len(BoolORC) > 0:

        modello.add_constraint(
            modello.sum(BoolORC.values())
            <= utilities["ORC"]["max"]
        )


    # HPPr e HPUt condividono lo stesso limite HPmax.
    #
    # Quindi il numero complessivo di heat pump selezionate deve rispettare:
    #
    # Σ BoolHPPr + Σ BoolHPUt <= HPmax
    if len(BoolHPPr) > 0 or len(BoolHPUt) > 0:

        modello.add_constraint(
            modello.sum(BoolHPPr.values())
            + modello.sum(BoolHPUt.values())
            <= utilities["HP_max"]
        )


    # Conserviamo le variabili in un dizionario perché serviranno
    # dopo la soluzione per leggere quali utility CPLEX ha selezionato.
    variabili = {
        "BoolHPPr": BoolHPPr,
        "FHPPr": FHPPr,
        "BoolHPUt": BoolHPUt,
        "FHPUt": FHPUt,
        "BoolRef": BoolRef,
        "FRef": FRef,
        "BoolORC": BoolORC,
        "FORC": FORC,
        "BoolChp": BoolChp,
        "FChp": FChp,
    }

    # ============================================================
    # THI15 Eq. (15)-(16): calore prelevato dalla GCC.
    # CALORE PRELEVATO DALLA GCC: Pprel_yj
    # ============================================================

    # Creiamo una variabile continua Pprel[z,k]
    # per ogni punto della GCC.
    #
    # lb=0 significa:
    #
    #       Pprel >= 0
    #
    # quindi il calore prelevato non può essere negativo.
    Pprel = modello.continuous_var_dict(
        indici_GCC,
        lb=0,
        name="Pprel",
    )


    for y, j in indici_GCC:

        # Nella zona più calda Z il modello non consente
        # di prelevare calore dalla GCC.
        #
        # In DOcplex possiamo imporre direttamente:
        #
        #       Pprel[y,j] = 0
        if y == Z:

            modello.add_constraint(
                Pprel[y, j] == 0
            )

            continue

        # Costruiamo la lista delle frazioni F delle HPPr
        # che utilizzano proprio il punto (y,j)
        # come sorgente termica.
        termini = [
            FHPPr[indice]
            for indice in FHPPr
            if indice[0] == y
            and indice[1] == j
        ]

        # Se esiste un candidato chiller nello stesso punto,
        # anche FRef contribuisce al calore prelevato.
        if (y, j) in FRef:
            termini.append(FRef[y, j])

        # Analogamente per ORC.
        if (y, j) in FORC:
            termini.append(FORC[y, j])

        # Traduzione dell'equazione:
        #
        # Pprel_yj =
        # Q_yj * (
        #       Σ FHPPr
        #       + FRef
        #       + FORC
        # )
        #
        # Q_GCC è un parametro noto.
        # Le F sono invece variabili del MILP.
        modello.add_constraint(
            Pprel[y, j]
            == Q_GCC[y, j]
            * modello.sum(termini)
        )


    # ============================================================
    # THI15 Eq. (17)-(19): calore fornito alla GCC.
    # CALORE FORNITO ALLA GCC: Papp_zk
    # ============================================================

    Papp = modello.continuous_var_dict(
        indici_GCC,
        lb=0,
        name="Papp",
    )


    for z, k in indici_GCC:

        # Nella zona più fredda non è ammesso apporto termico.
        if z == 1:

            modello.add_constraint(
                Papp[z, k] == 0
            )

            continue

        # Questa lista conterrà tutti i contributi termici
        # che possono arrivare al punto (z,k).
        termini = []

        # --------------------------------------------------------
        # CONTRIBUTI DELLE HPPr
        # --------------------------------------------------------

        for indice in FHPPr:

            y, j, z_dest, k_dest = indice

            # Consideriamo soltanto le HPPr il cui condensatore
            # è collegato esattamente al punto (z,k).
            if z_dest != z or k_dest != k:
                continue

            COP_HPPr = (
                mappe["HPPr"][indice]["COP_HPPr"]
            )

            # FHPPr * Q_GCC[y,j]
            # è il calore assorbito all'evaporatore:
            #
            #       Q_evap
            #
            # Per una heat pump:
            #
            #       COP = Q_cond / W
            #
            # e:
            #
            #       Q_cond = Q_evap + W
            #
            # da cui:
            #
            # Q_cond =
            # Q_evap * COP/(COP-1)
            termini.append(
                FHPPr[indice]
                * Q_GCC[y, j]
                * COP_HPPr
                / (COP_HPPr - 1)
            )

        # HPUt:
        #
        # la variabile FHPUt rappresenta direttamente
        # la frazione del carico Q_zk fornita al processo.
        if (z, k) in FHPUt:

            termini.append(
                FHPUt[z, k]
                * Q_GCC[z, k]
            )

        # Nella zona più calda può contribuire anche il CHP.
        if z == Z and k in FChp:

            termini.append(
                FChp[k]
                * Q_GCC[Z, k]
            )

        # Somma di tutti gli apporti termici al punto (z,k).
        modello.add_constraint(
            Papp[z, k]
            == modello.sum(termini)
        )


    # ============================================================
    # THI15 Eq. (20)-(22): nuovo heat load della GCC e non-negatività.
    # NUOVO HEAT LOAD DELLA GCC: NHL_zk
    # ============================================================

    # NHL rappresenta la nuova coordinata energetica della GCC
    # dopo l'inserimento delle utility.
    #
    # lb=0 implementa direttamente il vincolo:
    #
    #       NHL_zk >= 0
    #
    # quindi la nuova GCC non può attraversare Q=0.
    NHL = modello.continuous_var_dict(
        indici_GCC,
        lb=0,
        name="NHL",
    )


    # ------------------------------------------------------------
    # THI15 Eq. (20): zone dalla più fredda fino a Z-1.
    # Zone dalla più fredda fino a Z-1
    # ------------------------------------------------------------

    for y in range(1, Z):

        N_punti_y = len(zone_milp[y - 1])

        for j in range(1, N_punti_y + 1):

            # Le utility presenti dal punto j fino alla fine
            # della stessa zona modificano cumulativamente
            # il valore della GCC.
            effetto_stessa_zona = modello.sum(
                Papp[y, i] - Pprel[y, i]
                for i in range(
                    j,
                    N_punti_y + 1,
                )
            )

            # Al valore NHL_yj contribuiscono anche tutte le
            # modifiche introdotte nelle zone a temperatura superiore.
            #
            # La zona Z viene esclusa perché ha una formulazione
            # specifica nell'Eq. (21) di THI15.
            effetto_zone_superiori = modello.sum(
                Papp[z, k] - Pprel[z, k]
                for z in range(y + 1, Z)
                for k in range(
                    1,
                    len(zone_milp[z - 1]) + 1,
                )
            )

            # Nuova coordinata energetica della GCC.
            modello.add_constraint(
                NHL[y, j]
                == Q_GCC[y, j]
                + effetto_stessa_zona
                + effetto_zone_superiori
            )


    # ------------------------------------------------------------
    # THI15 Eq. (21): zona più calda Z.
    # Zona più calda Z
    # ------------------------------------------------------------

    for j in range(1, k_finale_Z + 1):

        # In questa zona l'equazione considera
        # cumulativamente il calore apportato.
        modello.add_constraint(
            NHL[Z, j]
            == Q_GCC[Z, j]
            - modello.sum(
                Papp[Z, i]
                for i in range(1, j + 1)
            )
        )


    # ============================================================
    # THI15 Eq. (23)-(25): consumo elettrico locale e totale.
    # CONSUMO ELETTRICO
    # ============================================================

    # Pelec[z,k] rappresenta la potenza elettrica
    # consumata dalle utility associate al punto (z,k).
    Pelec = modello.continuous_var_dict(
        indici_GCC,
        lb=0,
        name="Pelec",
    )


    for z, k in indici_GCC:

        termini = []

        if z < Z:

            # ----------------------------------------------------
            # Consumo HPPr
            # ----------------------------------------------------

            for indice in FHPPr:

                y, j, _, _ = indice

                # Consideriamo le HPPr che prelevano
                # calore proprio nel punto (z,k).
                if y != z or j != k:
                    continue

                COP_HPPr = (
                    mappe["HPPr"][indice]["COP_HPPr"]
                )

                # Per HPPr:
                #
                # Q_evap = F * Q_zk
                #
                # W = Q_evap/(COP-1)
                termini.append(
                    FHPPr[indice]
                    * Q_GCC[z, k]
                    / (COP_HPPr - 1)
                )

            # ----------------------------------------------------
            # Consumo chiller
            # ----------------------------------------------------

            if (z, k) in FRef:

                COP_ref = (
                    mappe["Ref"][z, k]["COP_ref"]
                )

                termini.append(
                    FRef[z, k]
                    * Q_GCC[z, k]
                    / (COP_ref - 1)
                )

        # --------------------------------------------------------
        # Consumo HPUt
        # --------------------------------------------------------

        if (z, k) in FHPUt:

            COP_HPUt = (
                mappe["HPUt"][z, k]["COP_HPUt"]
            )

            # Per HPUt F*Q rappresenta il calore
            # fornito dal condensatore:
            #
            #       W = Q_cond / COP
            termini.append(
                FHPUt[z, k]
                * Q_GCC[z, k]
                / COP_HPUt
            )

        # Consumo elettrico totale nel punto.
        modello.add_constraint(
            Pelec[z, k]
            == modello.sum(termini)
        )


    # ------------------------------------------------------------
    # THI15 Eq. (25): TEC = Total Electricity Consumption.
    # ------------------------------------------------------------

    # continuous_var() senza "_dict" crea una singola variabile,
    # non una famiglia indicizzata di variabili.
    TEC = modello.continuous_var(
        lb=0,
        name="TEC",
    )


    # TEC è la somma di tutti i consumi elettrici locali.
    modello.add_constraint(
        TEC
        == modello.sum(
            Pelec[indice]
            for indice in indici_GCC
        )
    )


    # ============================================================
    # THI15 Eq. (26): Total Electricity Production.
    # PRODUZIONE ELETTRICA: TEP
    # ============================================================

    # Total Electricity Production.
    TEP = modello.continuous_var(
        lb=0,
        name="TEP",
    )


    # ORC:
    #
    # energia termica utilizzata:
    #       F_ORC * Q_zk
    #
    # produzione elettrica:
    #       F_ORC * Q_zk * Eff_ORC
    produzione_ORC = modello.sum(
        FORC[z, k]
        * Q_GCC[z, k]
        * candidato["Eff_ORC"]
        for (z, k), candidato
        in mappe["ORC"].items()
    )

    # CHP:
    #
    # la formulazione ricava la produzione elettrica
    # dal calore fornito al processo e dall'efficienza CHP.
    produzione_CHP = modello.sum(
        FChp[k]
        * Q_GCC[Z, k]
        * candidato["Eff_CHP"]
        / (1 - candidato["Eff_CHP"])
        for k, candidato
        in mappe["CHP"].items()
    )

    # TEP = produzione ORC + produzione CHP.
    modello.add_constraint(
        TEP
        == produzione_ORC
        + produzione_CHP
    )


    # ============================================================
    # THI15 Eq. (27): calore richiesto dalle unità CHP.
    # ENERGIA TERMICA PRELEVATA DALLA SORGENTE DEL CHP
    # ============================================================

    PprelCHP = modello.continuous_var(
        lb=0,
        name="PprelCHP",
    )


    modello.add_constraint(
        PprelCHP
        == modello.sum(
            FChp[k]
            * Q_GCC[Z, k]
            / (1 - candidato["Eff_CHP"])
            for k, candidato
            in mappe["CHP"].items()
        )
    )


    # Le Eq. (28)-(32) non compaiono qui tutte come
    # constraint DOcplex.
    #
    # Sono state applicate prima, durante genera_candidate_utilities().
    #
    # In pratica:
    # se una utility è termodinamicamente vietata in un certo punto,
    # la corrispondente variabile Bool/F non viene nemmeno creata.
    #
    # Questo riduce anche la dimensione del MILP.

    # ============================================================
    # THI15 Eq. (33): obiettivo exergetico.
    # FUNZIONE OBIETTIVO
    # ============================================================

    # Temperatura del cold MER.
    T_cold_MER = T_GCC[1, 1]

    # Fattore exergetico associato alla cold utility.
    if T_cold_MER >= T0:

        fattore_cold = 0.0

    else:

        fattore_cold = (
            eta_ex
            * T_cold_MER
            / (T0 - T_cold_MER)
        )

    # Fattore exergetico associato alla sorgente calda.
    fattore_hot = (
        (T_f - T0) / T_f
    )

    # FinalExergy è una singola variabile continua.
    #
    # lb=-modello.infinity significa che DOcplex
    # non impone un limite inferiore finito.
    FinalExergy = modello.continuous_var(
        lb=-modello.infinity,
        name="FinalExergy",
    )


    # Definizione matematica della funzione FinalExergy.
    #
    # La relazione viene prima inserita come vincolo:
    #
    # FinalExergy = ...
    modello.add_constraint(
        FinalExergy
        == NHL[1, 1] * fattore_cold
        + (
            NHL[Z, k_finale_Z]
            + PprelCHP
        ) * fattore_hot
        + TEC
        - TEP
    )


    # Con minimize() diciamo a DOcplex quale grandezza
    # CPLEX deve cercare di rendere minima.
    #
    # Da questo momento il problema è:
    #
    # trovare valori di Bool, F, Pprel, Papp, NHL, ...
    #
    # che:
    #   - rispettino tutti i vincoli precedenti;
    #   - minimizzino FinalExergy.
    modello.minimize(FinalExergy)


    # ============================================================
    # RESTITUZIONE DEL MODELLO
    # ============================================================

    # Non restituiamo soltanto "modello".
    #
    # Conserviamo anche variabili e parametri perché,
    # dopo aver chiamato:
    #
    #       soluzione = modello.solve()
    #
    # dovremo recuperare i valori numerici delle singole
    # variabili tramite soluzione.get_value(...).
    return {
        "modello": modello,
        "zone_milp": zone_milp,
        "Z": Z,
        "k_finale_Z": k_finale_Z,
        "indici_GCC": indici_GCC,
        "Q_GCC": Q_GCC,
        "T_GCC": T_GCC,
        "candidati": candidati,
        "mappe": mappe,
        "variabili": variabili,
        "Pprel": Pprel,
        "Papp": Papp,
        "NHL": NHL,
        "Pelec": Pelec,
        "TEC": TEC,
        "TEP": TEP,
        "PprelCHP": PprelCHP,
        "FinalExergy": FinalExergy,
    }

# ============================================================================
# 9_SOLVE - RISOLUZIONE E LETTURA DELLE VARIABILI
# ============================================================================

def risolvi_modello_utilities(
    componenti,
    log_output=False,
    tolleranza=1e-6,
):
    """Risolve il MILP e ricostruisce le grandezze fisiche delle utility.

    Ruolo
    -----
    Invoca CPLEX e legge la soluzione nelle strutture restituite


    Input / Output
    --------------
    Riceve il dizionario del costruttore del modello e restituisce
    utility selezionate e dimensioni del MILP.

  """

    modello = componenti["modello"]

    soluzione = modello.solve(
        log_output=log_output
    )

    if soluzione is None:
        print("Nessuna soluzione trovata dal modello.")
        return None

    mappe = componenti["mappe"]
    v = componenti["variabili"]
    Q_GCC = componenti["Q_GCC"]

    Z = componenti["Z"]
    k_finale_Z = componenti["k_finale_Z"]

    # ------------------------------------------------------------
    # HPPr
    #
    # FHPPr * Q_yj = calore prelevato all'evaporatore.
    # ------------------------------------------------------------

    HPPr_selezionate = []

    for indice, hp in mappe["HPPr"].items():

        frazione = soluzione.get_value(
            v["FHPPr"][indice]
        )

        if frazione <= tolleranza:
            continue

        y, j, z, k = indice

        COP_HPPr = hp["COP_HPPr"]

        Q_evap = (
            frazione
            * Q_GCC[y, j]
        )

        P_elettrica = (
            Q_evap
            / (COP_HPPr - 1)
        )

        Q_cond = (
            Q_evap
            + P_elettrica
        )

        HPPr_selezionate.append({
            "tipo": "HPPr",
            "indice": indice,

            "BoolHPPr": soluzione.get_value(
                v["BoolHPPr"][indice]
            ),
            "FHPPr": frazione,

            "y": y,
            "j": j,
            "z": z,
            "k": k,

            "T_yj_C": hp["T_yj_C"],
            "T_zk_C": hp["T_zk_C"],
            "T_evap_C": hp["T_evap_C"],
            "T_cond_C": hp["T_cond_C"],

            "COP_HPPr": COP_HPPr,

            # Manteniamo COP anche per compatibilità
            # con stampa_risultati_milp().
            "COP": COP_HPPr,

            "Q_evap_kW": Q_evap,
            "Q_cond_kW": Q_cond,
            "heat_load_kW": Q_cond,
            "P_elettrica_kW": P_elettrica,
        })

    # ------------------------------------------------------------
    # HPUt
    #
    # FHPUt * Q_zk = calore fornito al processo.
    # ------------------------------------------------------------

    HPUt_selezionate = []

    for indice, hp in mappe["HPUt"].items():

        frazione = soluzione.get_value(
            v["FHPUt"][indice]
        )

        if frazione <= tolleranza:
            continue

        z, k = indice

        COP_HPUt = hp["COP_HPUt"]

        Q_cond = (
            frazione
            * Q_GCC[z, k]
        )

        P_elettrica = (
            Q_cond
            / COP_HPUt
        )

        Q_evap = (
            Q_cond
            - P_elettrica
        )

        HPUt_selezionate.append({
            "tipo": "HPUt",
            "indice": indice,

            "BoolHPUt": soluzione.get_value(
                v["BoolHPUt"][indice]
            ),
            "FHPUt": frazione,

            "z": z,
            "k": k,

            "T_zk_C": hp["T_zk_C"],
            "T_evap_C": hp["T_evap_C"],
            "T_cond_C": hp["T_cond_C"],

            "COP_HPUt": COP_HPUt,

            "Q_evap_kW": Q_evap,
            "Q_cond_kW": Q_cond,
            "heat_load_kW": Q_cond,
            "P_elettrica_kW": P_elettrica,
        })

    # ------------------------------------------------------------
    # Refrigerazione Ref
    #
    # FRef * Q_zk = calore sottratto al processo.
    # ------------------------------------------------------------

    Ref_selezionati = []

    for indice, ref in mappe["Ref"].items():

        frazione = soluzione.get_value(
            v["FRef"][indice]
        )

        if frazione <= tolleranza:
            continue

        z, k = indice

        COP_ref = ref["COP_ref"]

        Q_evap = (
            frazione
            * Q_GCC[z, k]
        )

        P_elettrica = (
            Q_evap
            / (COP_ref - 1)
        )

        Q_cond = (
            Q_evap
            + P_elettrica
        )

        Ref_selezionati.append({
            "tipo": "Ref",
            "indice": indice,

            "BoolRef": soluzione.get_value(
                v["BoolRef"][indice]
            ),
            "FRef": frazione,

            "z": z,
            "k": k,

            "T_zk_C": ref["T_zk_C"],
            "T_evap_C": ref["T_evap_C"],
            "T_cond_C": ref["T_cond_C"],

            "COP_ref": COP_ref,

            "Q_evap_kW": Q_evap,
            "Q_cond_kW": Q_cond,
            "heat_load_kW": Q_evap,
            "P_elettrica_kW": P_elettrica,
        })

    # ------------------------------------------------------------
    # ORC
    #
    # FORC * Q_zk = calore prelevato dal processo.
    # Eff_ORC determina la produzione elettrica.
    # ------------------------------------------------------------

    ORC_selezionati = []

    for indice, orc in mappe["ORC"].items():

        frazione = soluzione.get_value(
            v["FORC"][indice]
        )

        if frazione <= tolleranza:
            continue

        z, k = indice

        Eff_ORC = orc["Eff_ORC"]

        Q_hot = (
            frazione
            * Q_GCC[z, k]
        )

        P_elettrica = (
            Q_hot
            * Eff_ORC
        )

        Q_scarto = (
            Q_hot
            - P_elettrica
        )

        ORC_selezionati.append({
            "tipo": "ORC",
            "indice": indice,

            "BoolORC": soluzione.get_value(
                v["BoolORC"][indice]
            ),
            "FORC": frazione,

            "z": z,
            "k": k,

            "T_zk_C": orc["T_zk_C"],
            "T_hot_C": orc["T_hot_C"],
            "T_reject_C": orc["T_reject_C"],

            "Eff_ORC": Eff_ORC,

            "heat_load_kW": Q_hot,
            "Q_scarto_kW": Q_scarto,
            "P_elettrica_prodotta_kW": P_elettrica,
        })

    # ------------------------------------------------------------
    # CHP
    #
    # FChp * Q_Zk = calore fornito al processo.
    # THI15 Eq. (26)-(27): ricostruzione di fuel e potenza elettrica.
    # ------------------------------------------------------------

    CHP_selezionati = []

    for k, chp in mappe["CHP"].items():

        frazione = soluzione.get_value(
            v["FChp"][k]
        )

        if frazione <= tolleranza:
            continue

        Eff_CHP = chp["Eff_CHP"]

        Q_process = (
            frazione
            * Q_GCC[Z, k]
        )

        Pprel_CHP = (
            Q_process
            / (1 - Eff_CHP)
        )

        P_elettrica = (
            Pprel_CHP
            * Eff_CHP
        )

        CHP_selezionati.append({
            "tipo": "CHP",
            "indice": k,

            "BoolChp": soluzione.get_value(
                v["BoolChp"][k]
            ),
            "FChp": frazione,

            "z": Z,
            "k": k,

            "T_processo_C": chp["T_processo_C"],
            "T_fiamma_C": chp["T_fiamma_C"],

            "Eff_CHP": Eff_CHP,

            "heat_load_kW": Q_process,
            "PprelCHP_kW": Pprel_CHP,
            "P_elettrica_prodotta_kW": P_elettrica,
        })

    # ------------------------------------------------------------
    # Risultati globali del MILP
    # ------------------------------------------------------------

    risultati = {
        "HPPr_selezionate": HPPr_selezionate,
        "HPUt_selezionate": HPUt_selezionate,

        "Ref_selezionati": Ref_selezionati,

        # Alias mantenuto perché costruisci_curva_utilities()
        # usa ancora questo nome.
        "chiller_selezionati": Ref_selezionati,

        "ORC_selezionati": ORC_selezionati,
        "CHP_selezionati": CHP_selezionati,

        "TEC_kW": soluzione.get_value(
            componenti["TEC"]
        ),

        "TEP_kW": soluzione.get_value(
            componenti["TEP"]
        ),

        "PprelCHP_kW": soluzione.get_value(
            componenti["PprelCHP"]
        ),

        # NHL_Z,SZ = hot MER residuo.
        "hot_MER_residuo_kW": soluzione.get_value(
            componenti["NHL"][Z, k_finale_Z]
        ),

        # NHL_1,1 = cold MER residuo.
        "cold_MER_residuo_kW": soluzione.get_value(
            componenti["NHL"][1, 1]
        ),

        "FinalExergy_kW": soluzione.get_value(
            componenti["FinalExergy"]
        ),

        "solver": {
            "status": soluzione.solve_details.status,
            "objective": soluzione.objective_value,
            "numero_variabili": modello.number_of_variables,
            "numero_binarie": modello.number_of_binary_variables,
            "numero_vincoli": modello.number_of_constraints,
        },

        "soluzione": soluzione,
    }

    # Compatibilità con il vecchio codice HP-only.
    risultati["HP_selezionate"] = HPPr_selezionate

    print("\nPUNTI GCC CON UTILITY ATTIVE")
    print("z | k | T [°C] | Q_GCC [kW] | NHL [kW] | Papp [kW] | Pprel [kW]")
    for z, k in componenti["indici_GCC"]:
        Papp_zk = soluzione.get_value(componenti["Papp"][z, k])
        Pprel_zk = soluzione.get_value(componenti["Pprel"][z, k])
        if Papp_zk > 1e-9 or Pprel_zk > 1e-9:
            T_C = componenti["T_GCC"][z, k] - 273.15
            Q_GCC_zk = componenti["Q_GCC"][z, k]
            NHL_zk = soluzione.get_value(componenti["NHL"][z, k])
            print(
                f"{z} | {k} | {T_C:.3f} | {Q_GCC_zk:.6f} | "
                f"{NHL_zk:.6f} | {Papp_zk:.6f} | {Pprel_zk:.6f}"
            )

    return risultati

# Funzione orchestratrice della pipeline di predesign.

def esegui_predesign_utilities(dati_pinch, log_output=False):
    """Orchestra discretizzazione, creazione di utility candidate, costruzione del modello matematico,
    risoluzione del modello .

    Riferimento bibliografico
    ------------------------
    Thibault et al. (2015), Sec. 2.1.1-2.1.7 ed Eq. (1)-(33).

    Oggetti matematici
    ------------------
    ``Z``, ``S_z``, candidati, modello MILP e soluzione completa.

    Input / Output
    --------------
    Acquisisce il dizionario costruito dalla Pinch Analysis e restituisce i risultati della selezione delle utilities.


    """

    configurazione = dati_pinch["configurazione"]
    utilities = configurazione["utilities"]

    # --------------------------------------------------------
    # Discretizzazione
    # --------------------------------------------------------

    zone_GCC, S_z = discretizza_GCC(
        dati_pinch["gcc"],
        dati_pinch["pinch_data"],
        configurazione["delta_T_max"],
    )

    # --------------------------------------------------------
    # THI15 Eq. (1)-(5): generazione delle utility candidate.
    # --------------------------------------------------------

    candidati = genera_candidate_utilities(
        zone_GCC,
        utilities,
        configurazione["eta_ex"],
        configurazione["evaP"],
        configurazione["condP"],
        configurazione["T0"],
        configurazione["T_f"],
        configurazione.get("T_cond_max"),
    )

    # --------------------------------------------------------
    # THI15 Eq. (6)-(33): costruzione del MILP.
    # --------------------------------------------------------

    componenti = crea_modello_utilities(
        candidati,
        zone_GCC,
        utilities,
        configurazione["T0"],
        configurazione["T_f"],
        configurazione["eta_ex"],
    )

    # --------------------------------------------------------
    # Risoluzione mediante CPLEX.
    # --------------------------------------------------------

    risultati = risolvi_modello_utilities(
        componenti,
        log_output=log_output,
    )

    if risultati is None:
        raise RuntimeError(
            "Il MILP di utility predesign non ha prodotto una soluzione."
        )

    zone_milp = componenti["zone_milp"]

    # Stampa risultati.
    risultati["diagnostica"] = {
        "pinch": {
            "QH_min_kW": dati_pinch["QH_min_kW"],
            "QC_min_kW": dati_pinch["QC_min_kW"],
            "pinch_traslati_C": dati_pinch["pinch_traslati_C"],
            "numero_MPP": len(
                dati_pinch["pinch_data"]["main_pinch_points"]
            ),
            "numero_PPP": len(
                dati_pinch["pinch_data"]["potential_pinch_points"]
            ),
            "numero_pockets": len(
                dati_pinch["pinch_data"]["pockets"]
            ),
        },

        "discretizzazione": {
            "Z": len(zone_milp),

            "zone": [
                {
                    "z": z,
                    "S_z": S_z[z],
                    "Tmin_C": min(T for _, T in zona),
                    "Tmax_C": max(T for _, T in zona),
                    "numero_punti": len(zona),
                    "numero_segmenti": len(zona) - 1,
                }
                for z, zona in enumerate(
                    zone_milp,
                    start=1,
                )
            ],

            "numero_totale_punti": sum(
                len(zona)
                for zona in zone_milp
            ),

            "numero_totale_segmenti": sum(
                len(zona) - 1
                for zona in zone_milp
            ),
        },

        "candidati": {
            nome: len(lista)
            for nome, lista in candidati.items()
        },
    }

    # GCC dopo l'inserimento delle utilities.
    (
        risultati["gcc_aggiornata"],
        risultati["gcc_aggiornata_eventi"],
    ) = costruisci_GCC_aggiornata(
        risultati["soluzione"],
        componenti["NHL"],
        componenti["Papp"],
        componenti["Pprel"],
        zone_GCC,
        configurazione["evaP"],
        configurazione["condP"],
    )

    # Mantiene disponibili i dati di discretizzazione.
    risultati["zone_GCC"] = zone_GCC
    risultati["S_z"] = S_z

    return risultati

# ============================================================================
# 10_POST_PROCESSING - CURVE E REPORTING
# ============================================================================

def costruisci_GCC_aggiornata(
    soluzione,
    NHL,
    Papp,
    Pprel,
    zone_GCC,
    evaP,
    condP,
):
    """Ricostruisce graficamente la GCC aggiornata includendo l'effetto delle utility.

    Riferimento bibliografico
    ------------------------
    Thibault et al. (2015),  Sec. 3 per la
    rappresentazione Integrated Composite Curve.

    Oggetti matematici
    ------------------
    ``NHL_z,k``, ``Papp_z,k`` e ``Pprel_z,k``.

    Input / Output
    --------------
    Legge i valori DOcplex e restituisce punti ``(Q, T)`` e relativi eventi.


    """

    zone_milp = riordina_zone_per_milp(zone_GCC)
    tolleranza = 1e-9
    nodi = []
    eventi_utility = {}

    # Lettura caldo -> freddo dei nodi MILP. Papp e Pprel vengono soltanto
    # riposizionati graficamente alle temperature operative delle HP.
    for z in range(len(zone_milp), 0, -1):
        zona = zone_milp[z - 1]
        for k in range(len(zona), 0, -1):
            Q_processo, T_GCC = zona[k - 1]
            p_app = soluzione.get_value(Papp[z, k])
            p_prel = soluzione.get_value(Pprel[z, k])

            nodi.append(
                {
                    "Q_processo": Q_processo,
                    "T": T_GCC,
                    "NHL": soluzione.get_value(NHL[z, k]),
                }
            )

            if p_app > tolleranza:
                chiave = (round(T_GCC + condP, 9), "Papp")
                eventi_utility[chiave] = eventi_utility.get(chiave, 0.0) + p_app
            if p_prel > tolleranza:
                chiave = (round(T_GCC - evaP, 9), "Pprel")
                eventi_utility[chiave] = eventi_utility.get(chiave, 0.0) - p_prel

    # Rimuove solo i duplicati geometrici ai confini delle zone e conserva
    # tutti i salti isotermi fisici della GCC di processo.
    nodi_puliti = []
    for nodo in nodi:
        if nodi_puliti:
            precedente = nodi_puliti[-1]
            stesso_punto = (
                abs(nodo["Q_processo"] - precedente["Q_processo"])
                <= tolleranza
                and abs(nodo["T"] - precedente["T"]) <= tolleranza
            )
            if stesso_punto:
                continue
        nodi_puliti.append(nodo)

    gruppi_processo = []
    for nodo in nodi_puliti:
        if (
            not gruppi_processo
            or abs(nodo["T"] - gruppi_processo[-1]["T"]) > tolleranza
        ):
            gruppi_processo.append(
                {"T": nodo["T"], "Q": [nodo["Q_processo"]]}
            )
        elif (
            abs(nodo["Q_processo"] - gruppi_processo[-1]["Q"][-1])
            > tolleranza
        ):
            gruppi_processo[-1]["Q"].append(nodo["Q_processo"])

    eventi_utility = [
        {"T": T_evento, "tipo": tipo, "delta_Q": delta_Q}
        for (T_evento, tipo), delta_Q in eventi_utility.items()
        if abs(delta_Q) > tolleranza
    ]
    eventi_utility.sort(key=lambda evento: (-evento["T"], evento["tipo"]))

    if not gruppi_processo:
        return [], []

    punti_evento = []

    def aggiungi_punto(Q, T, tipo):
        if punti_evento:
            Q_precedente, T_precedente, _ = punti_evento[-1]
            if (
                abs(Q - Q_precedente) <= tolleranza
                and abs(T - T_precedente) <= tolleranza
            ):
                return
        punti_evento.append((Q, T, tipo))

    # NHL fissa il livello iniziale. Gli eventi utility spostano poi la
    # coordinata Q cumulativa quando si incontra la loro temperatura reale.
    offset_Q = nodi_puliti[0]["NHL"] - nodi_puliti[0]["Q_processo"]
    indice_utility = 0

    def applica_utility(evento, Q_processo):
        nonlocal offset_Q
        Q_prima = Q_processo + offset_Q
        aggiungi_punto(Q_prima, evento["T"], evento["tipo"])
        offset_Q += evento["delta_Q"]
        aggiungi_punto(Q_processo + offset_Q, evento["T"], evento["tipo"])

    def aggiungi_gruppo(gruppo):
        tipo = "processo_isotermo" if len(gruppo["Q"]) > 1 else "processo"
        for Q_processo in gruppo["Q"]:
            aggiungi_punto(Q_processo + offset_Q, gruppo["T"], tipo)

    primo_gruppo = gruppi_processo[0]
    while (
        indice_utility < len(eventi_utility)
        and eventi_utility[indice_utility]["T"] > primo_gruppo["T"] + tolleranza
    ):
        applica_utility(eventi_utility[indice_utility], primo_gruppo["Q"][0])
        indice_utility += 1

    aggiungi_gruppo(primo_gruppo)
    while (
        indice_utility < len(eventi_utility)
        and abs(eventi_utility[indice_utility]["T"] - primo_gruppo["T"])
        <= tolleranza
    ):
        applica_utility(eventi_utility[indice_utility], primo_gruppo["Q"][-1])
        indice_utility += 1

    for gruppo_precedente, gruppo in zip(
        gruppi_processo,
        gruppi_processo[1:],
    ):
        T_alta = gruppo_precedente["T"]
        T_bassa = gruppo["T"]
        Q_alta = gruppo_precedente["Q"][-1]
        Q_bassa = gruppo["Q"][0]

        while (
            indice_utility < len(eventi_utility)
            and eventi_utility[indice_utility]["T"] > T_bassa + tolleranza
        ):
            evento = eventi_utility[indice_utility]
            frazione = (T_alta - evento["T"]) / (T_alta - T_bassa)
            Q_interpolato = Q_alta + frazione * (Q_bassa - Q_alta)
            applica_utility(evento, Q_interpolato)
            indice_utility += 1

        aggiungi_gruppo(gruppo)
        while (
            indice_utility < len(eventi_utility)
            and abs(eventi_utility[indice_utility]["T"] - T_bassa)
            <= tolleranza
        ):
            applica_utility(eventi_utility[indice_utility], gruppo["Q"][-1])
            indice_utility += 1

    ultimo_gruppo = gruppi_processo[-1]
    while indice_utility < len(eventi_utility):
        applica_utility(eventi_utility[indice_utility], ultimo_gruppo["Q"][-1])
        indice_utility += 1

    punti = [(Q, T) for Q, T, _ in punti_evento]
    return punti, punti_evento
def costruisci_curva_utilities(risultati_milp):
    """Combina le utility selezionate nella curva cumulativa dell'ICC.

    Riferimento bibliografico
    ------------------------
    Thibault et al. (2015), Sec. 3.1, descrizione dell'Integrated Composite
    Curve.

    Oggetti matematici
    ------------------
    Carichi a evaporatore/condensatore, ORC e CHP letti dalla soluzione.

    Input / Output
    --------------
    Restituisce punti ``(Q_kW, T_C)`` ordinati per temperatura.
    """
    carichi_isotermi = {}

    def aggiungi(T_C, delta_Q):
        chiave = round(float(T_C), 9)
        carichi_isotermi[chiave] = carichi_isotermi.get(chiave, 0.0) + delta_Q

    nomi_hp = ("HPPr_selezionate", "HPUt_selezionate", "chiller_selezionati")
    for nome in nomi_hp:
        for utility in risultati_milp.get(nome, []):
            aggiungi(utility["T_evap_C"], -utility["Q_evap_kW"])
            aggiungi(utility["T_cond_C"], utility["Q_cond_kW"])
    for utility in risultati_milp.get("ORC_selezionati", []):
        aggiungi(utility["T_hot_C"], -utility["heat_load_kW"])
        aggiungi(utility["T_reject_C"], utility["Q_scarto_kW"])
    for utility in risultati_milp.get("CHP_selezionati", []):
        aggiungi(utility["T_fiamma_C"], -utility["PprelCHP_kW"])
        aggiungi(utility["T_processo_C"], utility["heat_load_kW"])

    Q = 0.0
    curva = []
    for T_C, delta_Q in sorted(carichi_isotermi.items()):
        curva.append((Q, T_C))
        Q += delta_Q
        curva.append((Q, T_C))
    if not curva:
        return []
    Q_min = min(Q_punto for Q_punto, _ in curva)
    return [(Q_punto - Q_min, T_C) for Q_punto, T_C in curva]
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
    xlim=None,
    ylim=None,
    xticks=None,
    yticks=None,
):
    """Rappresenta Composite Curves, GCC, pockets e ICC.
    """
    # Import ritardato: calcoli Pinch/MILP/HENS non richiedono Matplotlib.
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(8, 6))
    if tipo_grafico in ("composite", "composite_traslate"):
        Q_hot, T_hot = zip(*hot_CC)
        Q_cold, T_cold = zip(*cold_CC)
        ax.plot(
            Q_hot,
            T_hot,
            color="red",
            linestyle="--",
            linewidth=1.2,
            label="Hot CC",
        )
        ax.plot(
            Q_cold,
            T_cold,
            color="blue",
            linestyle="-",
            linewidth=1.2,
            label="Cold CC",
        )
        if tipo_grafico == "composite":
            ax.set_title("Composite Curves - temperature reali")
            ax.set_ylabel("Temperatura reale [°C]")
        else:
            ax.set_title("Composite Curves - temperature traslate")
            ax.set_ylabel("Temperatura traslata T* [°C]")
    elif tipo_grafico in ("gcc", "gcc_aggiornata"):
        Q, T = zip(*gcc)
        linewidth = 1.2 if tipo_grafico == "gcc_aggiornata" else 2
        ax.plot(Q, T, color="red", linewidth=linewidth)
        ax.axvline(0, color="black", linestyle="--", linewidth=1)

        if tipo_grafico == "gcc":
            ax.set_title("Grand Composite Curve")
        else:
            ax.set_title("Grand Composite Curve aggiornata")

        ax.set_ylabel("Temperatura traslata [°C]")
    elif tipo_grafico == "pockets":
        if gcc is not None:
            Q, T = zip(*gcc)
            ax.plot(Q, T, color="lightgray", linewidth=2, label="GCC")
        for indice, pocket in enumerate(pockets or [], start=1):
            Q_pocket, T_pocket = zip(*pocket["punti_gcc"])
            ax.plot(
                Q_pocket,
                T_pocket,
                linewidth=1.7,
                label=f"Pocket {indice}: {pocket['zona']}",
            )
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
                    color="black",
                )
            if ppp:
                ax.scatter(
                    [p["Q_kW"] for p in ppp],
                    [p["T_traslata_C"] for p in ppp],
                    marker="D",
                    s=40,
                    label="PPP",
                    color="red",
                )
        ax.axvline(0, color="black", linestyle="--", linewidth=1)
        ax.set_title("Self-sufficient pockets")
        ax.set_ylabel("Temperatura traslata [°C]")
    elif tipo_grafico == "icc":
        Q, T = zip(*gcc)
        ax.plot(Q, T, color="red", linewidth=2, label="GCC")
        if utility_curve:
            Q_ut, T_ut = zip(*utility_curve)
            ax.plot(Q_ut, T_ut, color="green", linewidth=2, label="Utilities")
        ax.axvline(0, color="black", linestyle="--", linewidth=1)
        ax.set_title("Integrated Composite Curve")
        ax.set_ylabel("Temperatura [°C]")
    else:
        raise ValueError(
            "tipo_grafico deve essere 'composite', 'composite_traslate', "
            "'gcc', 'icc' oppure 'pockets'."
        )

    ax.set_xlabel("Potenza termica cumulata Q [kW]")
    if xlim is not None:
        ax.set_xlim(xlim)
    if ylim is not None:
        ax.set_ylim(ylim)
    if xticks is not None:
        ax.set_xticks(xticks)
        if len(xticks) > 15:
            ax.tick_params(axis="x", labelrotation=45)
    if yticks is not None:
        ax.set_yticks(yticks)
    ax.grid(True, linestyle="--", alpha=0.4)
    handles, labels = ax.get_legend_handles_labels()
    if handles:
        ax.legend(handles, labels)
    if percorso_salvataggio is not None:
        percorso_salvataggio = Path(percorso_salvataggio)
        percorso_salvataggio.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(percorso_salvataggio, dpi=300, bbox_inches="tight")
        print(f"Grafico salvato in: {percorso_salvataggio}")
    if mostra:
        plt.show()
    else:
        plt.close(fig)
    return fig, ax


# ============================================================================
# 11_STAMPA RISULTATI E GRAFICI
# ============================================================================

def stampa_risultati_milp(risultati):
    """Stampa soluzione, target, utility e dimensioni del MILP.


    """

    diagnostica = risultati["diagnostica"]
    pinch = diagnostica["pinch"]
    discretizzazione = diagnostica["discretizzazione"]

    print("\nPINCH")
    print(f"QH_min: {pinch['QH_min_kW']:.3f} kW")
    print(f"QC_min: {pinch['QC_min_kW']:.3f} kW")
    print(f"Pinch traslati: {pinch['pinch_traslati_C']} °C")
    print(
        f"MPP: {pinch['numero_MPP']}, PPP: {pinch['numero_PPP']}, "
        f"pockets: {pinch['numero_pockets']}"
    )

    print("\nDISCRETIZZAZIONE")
    print(f"Z: {discretizzazione['Z']}")
    for zona in discretizzazione["zone"]:
        print(
            f"z={zona['z']}: S_z={zona['S_z']}, "
            f"Tmin={zona['Tmin_C']:.3f} °C, Tmax={zona['Tmax_C']:.3f} °C, "
            f"punti={zona['numero_punti']}, segmenti={zona['numero_segmenti']}"
        )
    print(
        f"Punti totali: {discretizzazione['numero_totale_punti']}; "
        f"segmenti totali: {discretizzazione['numero_totale_segmenti']}"
    )

    print("\nCANDIDATI")
    print(
        ", ".join(
            f"{nome}={numero}"
            for nome, numero in diagnostica["candidati"].items()
        )
    )

    solver = risultati["solver"]
    print("\nSOLVER")
    print(f"Status CPLEX: {solver['status']}")
    print(f"Objective: {solver['objective']:.6f}")
    print(
        f"Variabili: {solver['numero_variabili']}; "
        f"binarie: {solver['numero_binarie']}; "
        f"vincoli: {solver['numero_vincoli']}"
    )

    print("\nUTILITY SELEZIONATE")
    for hp in risultati["HPPr_selezionate"]:
        print(
            f"HPPr {hp['indice']}: F={hp['FHPPr']:.6f}, "
            f"Tevap={hp['T_evap_C']:.2f} °C, Tcond={hp['T_cond_C']:.2f} °C, "
            f"COP={hp['COP']:.3f}, "
            f"Qevap={hp['Q_evap_kW']:.3f} kW, "
            f"Qcond={hp['Q_cond_kW']:.3f} kW, "
            f"W={hp['P_elettrica_kW']:.3f} kW"
        )
    for hp in risultati["HPUt_selezionate"]:
        print(
            f"HPUt {hp['indice']}: F={hp['FHPUt']:.6f}, "
            f"Tevap={hp['T_evap_C']:.2f} °C, Tcond={hp['T_cond_C']:.2f} °C, "
            f"COP={hp['COP_HPUt']:.3f}, Qevap={hp['Q_evap_kW']:.3f} kW, "
            f"Qcond={hp['Q_cond_kW']:.3f} kW, W={hp['P_elettrica_kW']:.3f} kW"
        )
    for ref in risultati["Ref_selezionati"]:
        print(
            f"Ref {ref['indice']}: F={ref['FRef']:.6f}, "
            f"Tevap={ref['T_evap_C']:.2f} °C, Tcond={ref['T_cond_C']:.2f} °C, "
            f"COP={ref['COP_ref']:.3f}, Qevap={ref['Q_evap_kW']:.3f} kW, "
            f"Qcond={ref['Q_cond_kW']:.3f} kW, W={ref['P_elettrica_kW']:.3f} kW"
        )
    for orc in risultati["ORC_selezionati"]:
        print(
            f"ORC {orc['indice']}: F={orc['FORC']:.6f}, "
            f"Thot={orc['T_hot_C']:.2f} °C, Eff={orc['Eff_ORC']:.3f}, "
            f"carico_termico={orc['heat_load_kW']:.3f} kW, "
            f"Wprod={orc['P_elettrica_prodotta_kW']:.3f} kW"
        )
    for chp in risultati["CHP_selezionati"]:
        print(
            f"CHP {chp['indice']}: F={chp['FChp']:.6f}, "
            f"Tprocesso={chp['T_processo_C']:.2f} °C, Eff={chp['Eff_CHP']:.3f}, "
            f"carico_termico={chp['heat_load_kW']:.3f} kW, "
            f"Wprod={chp['P_elettrica_prodotta_kW']:.3f} kW"
        )

    pompe_selezionate = [
        ("HPPr", hp) for hp in risultati["HPPr_selezionate"]
    ] + [
        ("HPUt", hp) for hp in risultati["HPUt_selezionate"]
    ]
    carico_raffreddamento_residuo_hp = (
        risultati["cold_MER_residuo_kW"]
        + sum(
            orc["heat_load_kW"]
            for orc in risultati["ORC_selezionati"]
        )
        + sum(
            ref["Q_evap_kW"]
            for ref in risultati["Ref_selezionati"]
        )
    )

    for tipo, hp in pompe_selezionate:
        righe = [
            ("Heat pump heating capacity (kW)", hp["Q_cond_kW"]),
            ("Heat pump cooling capacity (kW)", hp["Q_evap_kW"]),
            ("Heat pump electrical power (kW)", hp["P_elettrica_kW"]),
            ("Evaporation temperature (°C)", hp["T_evap_C"]),
            ("Condensation temperature (°C)", hp["T_cond_C"]),
            (
                "Remaining cooling load (kW)",
                carico_raffreddamento_residuo_hp,
            ),
        ]
        larghezza_parametro = max(len("Parameter"), *(len(nome) for nome, _ in righe))
        larghezza_valore = max(
            len("Value"),
            *(len(f"{valore:.3f}") for _, valore in righe),
        )
        separatore = (
            f"+-{'-' * larghezza_parametro}-+-{'-' * larghezza_valore}-+"
        )

        print(f"\nPRESELECTION RESULT - {tipo} {hp['indice']}")
        print(separatore)
        print(
            f"| {'Parameter':<{larghezza_parametro}} "
            f"| {'Value':>{larghezza_valore}} |"
        )
        print(separatore)
        for nome, valore in righe:
            print(
                f"| {nome:<{larghezza_parametro}} "
                f"| {valore:>{larghezza_valore}.3f} |"
            )
        print(separatore)

    print("\nGLOBALI")
    print(f"TEC: {risultati['TEC_kW']:.3f} kW")
    print(f"TEP: {risultati['TEP_kW']:.3f} kW")
    print(f"PprelCHP: {risultati['PprelCHP_kW']:.3f} kW")
    print(f"Hot MER residuo: {risultati['hot_MER_residuo_kW']:.3f} kW")
    print(f"Cold MER residuo: {risultati['cold_MER_residuo_kW']:.3f} kW")
    print(f"FinalExergy: {risultati['FinalExergy_kW']:.3f} kW")
def salva_grafici(dati_pinch, risultati_milp, cartella):
    """Salva Composite Curves, GCC, ICC e self-sufficient pockets.

    Riferimento bibliografico
    ------------------------
    Thibault et al. (2015), Fig. 1-9. Funzione di reporting; non costruisce
    variabili o vincoli matematici.
    """


    cartella = Path(cartella)
    cartella.mkdir(
        parents=True,
        exist_ok=True,
    )

    curva_utilities = costruisci_curva_utilities(risultati_milp)

    nome_caso = dati_pinch["configurazione"].get("nome", "").lower()
    caso_dairy = "dairy" in nome_caso
    caso_4_flussi = "4 flussi" in nome_caso
    dairy_ylim = (-20, 100) if caso_dairy else None
    dairy_yticks = list(range(-20, 101, 20)) if caso_dairy else None
    composite_xlim = (
        (0, 10000) if caso_dairy
        else (0, 550) if caso_4_flussi
        else None
    )
    dairy_composite_ylim = (0, 100) if caso_dairy else None
    composite_xticks = (
        list(range(0, 10001, 1000)) if caso_dairy
        else list(range(0, 551, 50)) if caso_4_flussi
        else None
    )
    dairy_composite_yticks = list(range(0, 101, 10)) if caso_dairy else None

    # Composite Curves - temperature reali
    grafico_TQ(
        "composite",
        hot_CC=dati_pinch["hot_CC"],
        cold_CC=dati_pinch["cold_CC"],
        percorso_salvataggio=(
            cartella / "composite_curves_reali.png"
        ),
        mostra=False,
        xlim=composite_xlim,
        ylim=dairy_composite_ylim,
        xticks=composite_xticks,
        yticks=dairy_composite_yticks,
    )

    # Composite Curves - temperature traslate
    grafico_TQ(
        "composite_traslate",
        hot_CC=dati_pinch["hot_CC_traslata"],
        cold_CC=dati_pinch["cold_CC_traslata"],
        percorso_salvataggio=(
            cartella / "composite_curves_traslate.png"
        ),
        mostra=False,
        xlim=composite_xlim,
        ylim=dairy_composite_ylim,
        xticks=composite_xticks,
        yticks=dairy_composite_yticks,
    )


    # GCC iniziale
    grafico_TQ(
        "gcc",
        gcc=dati_pinch["gcc"],
        percorso_salvataggio=(cartella / "grand_composite_curve.png"),
        mostra=False,
    )

    # Self-sufficient pockets
    grafico_TQ(
        "pockets",
        gcc=dati_pinch["gcc"],
        pockets=dati_pinch["pinch_data"]["pockets"],
        pinch_data=dati_pinch["pinch_data"],
        percorso_salvataggio=(cartella / "self_sufficient_pockets.png"),
        mostra=False,
    )

    # GCC aggiornata
    grafico_TQ(
        "gcc_aggiornata",
        gcc=risultati_milp["gcc_aggiornata"],
        percorso_salvataggio=(cartella / "grand_composite_curve_aggiornata.png"),
        mostra=False,
        xlim=(0, 1400) if caso_dairy else None,
        ylim=dairy_ylim,
        xticks=list(range(0, 1401, 200)) if caso_dairy else None,
        yticks=dairy_yticks,
    )

    # Integrated Composite Curve
    grafico_TQ(
        "icc",
        gcc=dati_pinch["gcc"],
        utility_curve=curva_utilities,
        percorso_salvataggio=(cartella / "integrated_composite_curve.png"),
        mostra=False,
        xlim=(0, 2000) if caso_dairy else None,
        ylim=dairy_ylim,
        xticks=list(range(0, 2001, 200)) if caso_dairy else None,
        yticks=dairy_yticks,
    )
