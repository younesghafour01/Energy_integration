import json
import math
from pathlib import Path

# 1. STRUTTURE DATI

class Flusso:
    """Corrente sensibile o carico termico isotermo."""

    def __init__(
        self,
        codice,
        nome,
        tipo,
        T_in,
        T_out,
        CP=None,
        processo=None,
        zona=None,
        disponibile=True,
        heat_load_kW=None,
        delta_T_min_half=None,
        isotermo=None,
        remark=None,
        unit=None,
        h_W_m2K=None,
    ):
        if tipo not in ("hot", "cold"):
            raise ValueError(f"Tipo non valido per il flusso {codice}: {tipo}")

        self.codice = codice
        self.nome = nome
        self.tipo = tipo

        # Temperature sempre memorizzate sulla scala reale.
        self.T_in = float(T_in)
        self.T_out = float(T_out)

        self.heat_load_kW = (
            None if heat_load_kW is None else float(heat_load_kW)
        )

        # Valore specifico del flusso per la traslazione Pinch.
        # Se None, verrà usato delta_T_min / 2.
        self.delta_T_min_half = (
            None if delta_T_min_half is None else float(delta_T_min_half)
        )

        self.h_W_m2K = (
            None if h_W_m2K is None else float(h_W_m2K)
        )

        if self.h_W_m2K is not None and self.h_W_m2K <= 0:
            raise ValueError(
                f"h_W_m2K non valido per {codice}: {self.h_W_m2K}"
            )

        # Se non specificato nel JSON, identifica automaticamente
        # una corrente isoterma da T_in == T_out.
        self.isotermo = (
            abs(self.T_in - self.T_out) <= 1e-12
            if isotermo is None
            else bool(isotermo)
        )

        self.processo = processo
        self.zona = zona
        self.disponibile = bool(disponibile)
        self.remark = remark
        self.unit = unit

        # Determinazione del CP.
        if self.isotermo:

            if self.heat_load_kW is None:
                raise ValueError(
                    f"Il flusso isotermo {codice} richiede heat_load_kW."
                )

            self.CP = None if CP is None else float(CP)

        elif CP is not None:

            self.CP = float(CP)

        elif self.heat_load_kW is not None:

            self.CP = (
                self.heat_load_kW
                / abs(self.T_out - self.T_in)
            )

        else:

            raise ValueError(
                f"Il flusso {codice} richiede CP oppure heat_load_kW."
            )

    def calcola_Q(self):
        """Restituisce il carico termico totale della corrente in kW."""

        if self.heat_load_kW is not None:
            return self.heat_load_kW

        return self.CP * abs(self.T_in - self.T_out)

# 2. INPUT funzioni che gestiscono l'input = "configuazione"

def carica_caso_studio(percorso_json):
    """Carica il caso studio e converte i flussi in oggetti Flusso."""

    # Legge il file JSON e converte il suo contenuto
    # nel dizionario Python "configurazione".
    with Path(percorso_json).open(
        mode="r",
        encoding="utf-8",
    ) as file:
        configurazione = json.load(file)

    # Sostituisce la lista di dizionari "flussi" letta dal JSON
    # con una lista di oggetti della classe Flusso.
    configurazione["flussi"] = [
        Flusso(**dati_flusso)
        for dati_flusso in configurazione["flussi"]
    ]

    # Restituisce l'intera configurazione del caso studio,
    # con "flussi" ormai contenente oggetti Flusso.
    return configurazione

# 3. CONVERSIONI DI TEMPERATURA

def converti_temperatura(
    T,
    tipo,
    delta_T_min,
    origine,
    destinazione,
    delta_T_min_half=None,
    ):
    """Converte una temperatura tra le scale reale, Pinch e HENS."""

    # Usa il valore specifico della corrente, se definito; #caso deiry_case definisce i delta_T_min per ogni corrente
    # altrimenti assume la traslazione standard ΔTmin/2.
    delta_half = (
        delta_T_min / 2
        if delta_T_min_half is None
        else delta_T_min_half
    )

    # Prima riporta sempre la temperatura alla scala reale.
    if origine == "reale":
        T_reale = T

    elif origine == "pinch":
        # Scala Pinch:
        # hot  = reale - delta_half
        # cold = reale + delta_half
        if tipo == "hot":
            T_reale = T + delta_half
        else:
            T_reale = T - delta_half

    elif origine == "hens":
        # Scala HENS:
        # hot  = reale
        # cold = reale + ΔTmin
        if tipo == "hot":
            T_reale = T
        else:
            T_reale = T - delta_T_min

    else:
        raise ValueError(f"Scala non riconosciuta: {origine}")

    # Dalla temperatura reale passa alla scala richiesta.
    if destinazione == "reale":
        return T_reale

    if destinazione == "pinch":
        return (
            T_reale - delta_half
            if tipo == "hot"
            else T_reale + delta_half
        )

    if destinazione == "hens":
        return (
            T_reale
            if tipo == "hot"
            else T_reale + delta_T_min
        )

    raise ValueError(f"Scala non riconosciuta: {destinazione}")

# 4. PINCH ANALYSIS STRUMENTI

def crea_cascata_termica(flussi, delta_T_min, tolleranza=1e-9):
    """Crea la cascata termica includendo i carichi termici isotermi."""
    # Tiene solo i flussi dichiarati disponibili nel caso studio.
    flussi_attivi = [flusso for flusso in flussi if flusso.disponibile]

    flussi_traslati = []
    temperature = []
    carichi_isotermi = {}

    for flusso in flussi_attivi:
        # Converte le temperature reali del flusso nella scala Pinch T*.
        T_in_star = converti_temperatura(
            flusso.T_in,
            flusso.tipo,
            delta_T_min,
            "reale",
            "pinch",
            flusso.delta_T_min_half,
        )
        T_out_star = converti_temperatura(
            flusso.T_out,
            flusso.tipo,
            delta_T_min,
            "reale",
            "pinch",
            flusso.delta_T_min_half,
        )

        # Salva insieme il flusso originale e i suoi estremi traslati.
        flussi_traslati.append((flusso, T_in_star, T_out_star))

        # Raccoglie tutti gli estremi di temperatura, che diventeranno i limiti degli intervalli della Problem Table.
        temperature.extend([T_in_star, T_out_star,])

        # I flussi isotermi hanno T_in = T_out e quindi non possono essere trattati con Q = CP * ΔT.
        # Il loro carico viene quindi registrato direttamente alla temperatura T*.
        if flusso.isotermo:
            # Se è la prima corrente isoterma a questa temperatura,
            # inizializza il relativo contenitore.
            if T_in_star not in carichi_isotermi:
                carichi_isotermi[T_in_star] = {"hot": 0.0,"cold": 0.0,}
            # Somma il duty alla componente hot oppure cold.
            carichi_isotermi[T_in_star][flusso.tipo] += flusso.calcola_Q()
    # Crea i livelli termici della Problem Table:
    # elimina i duplicati e li ordina dalla temperatura più alta alla più bassa.
    livelli = sorted(set(temperature),reverse=True,)

    # "risultati" conterrà una riga per ogni intervallo o carico isotermo.
    risultati = []
    # Prima cascata costruita assumendo inizialmente QH = 0.
    cascata_provvisoria = 0.0
    # Scorre tutti i livelli termici dall'alto verso il basso.
    for indice, T_sup in enumerate(livelli):
        # Se a questo livello esiste un carico isotermo,
        # lo inserisce direttamente nella cascata.
        if T_sup in carichi_isotermi:
            Q_hot = carichi_isotermi[T_sup]["hot"]
            Q_cold = carichi_isotermi[T_sup]["cold"]
            # Bilancio energetico del carico isotermo:
            # hot aggiunge energia, cold la sottrae.
            delta_H = Q_hot - Q_cold
            # Aggiorna il valore cumulativo della cascata.
            cascata_provvisoria += delta_H
            # Registra il carico isotermo come intervallo a ΔT = 0 quindi T_inf = T_sup.
            risultati.append(
                {
                    "T_sup": T_sup,
                    "T_inf": T_sup,
                    "CP_hot": 0.0,
                    "CP_cold": 0.0,
                    "delta_H_hot": Q_hot,
                    "delta_H_cold": Q_cold,
                    "delta_H": delta_H,
                    "cascata_provvisoria": cascata_provvisoria,
                }
            )

        # L'ultimo livello non ha un livello inferiore:
        # quindi non può formare un ulteriore intervallo.
        if indice == len(livelli) - 1:
            break

        # Temperatura inferiore dell'intervallo corrente.
        T_inf = livelli[indice + 1]

        # Somma dei CP delle hot e cold stream presenti nell'intervallo.
        CP_hot = 0.0
        CP_cold = 0.0

        for flusso, T_in_star, T_out_star in flussi_traslati:
            # Le correnti isotermiche sono già state trattate sopra.
            if flusso.isotermo:
                continue
            # Estremi termici della corrente indipendentemente dal suo verso.
            T_max = max(T_in_star, T_out_star)
            T_min = min(T_in_star, T_out_star)
            # Verifica se la corrente attraversa completamente
            # l'intervallo [T_inf, T_sup].
            if T_max >= T_sup and T_min <= T_inf:
                if flusso.tipo == "hot":
                    CP_hot += flusso.CP
                else:
                    CP_cold += flusso.CP
        # Ampiezza termica dell'intervallo.
        delta_T = T_sup - T_inf
        # Calore ceduto dalle hot e richiesto dalle cold nell'intervallo.
        Q_hot = CP_hot * delta_T
        Q_cold = CP_cold * delta_T
        # Bilancio netto dell'intervallo:
        # positivo = surplus di calore
        # negativo = deficit di calore.
        delta_H = Q_hot - Q_cold

        # Trasferisce il surplus/deficit al livello successivo della cascata.
        cascata_provvisoria += delta_H

        # Salva tutti i dati dell'intervallo nella Problem Table.
        risultati.append(
            {
                "T_sup": T_sup,
                "T_inf": T_inf,
                "CP_hot": CP_hot,
                "CP_cold": CP_cold,
                "delta_H_hot": Q_hot,
                "delta_H_cold": Q_cold,
                "delta_H": delta_H,
                "cascata_provvisoria": cascata_provvisoria,
            }
        )

    # Raccoglie tutti i valori della cascata provvisoria,
    # includendo anche il valore iniziale pari a zero.
    valori_cascata = [0.0, *[riga["cascata_provvisoria"] for riga in risultati],]
    # Il minimo valore negativo indica quanta hot utility
    # bisogna aggiungere all'inizio per rendere tutta la cascata >= 0.
    QH_min = max( 0.0, -min(valori_cascata),)
    # Costruisce la cascata finale aggiungendo QH_min
    # a tutti i valori della cascata provvisoria.
    for riga in risultati:
        riga["cascata_finale"] = ( riga["cascata_provvisoria"] + QH_min)
    # Il calore che rimane in fondo alla cascata
    # è il minimo fabbisogno di cold utility.
    QC_min = risultati[-1]["cascata_finale"]
 
    # Il Main Pinch Point corrisponde al minimo della cascata
    # Individua il primo punto in cui la cascata raggiung il proprio minimo globale.

    indice_pinch = min(
        range(len(valori_cascata)),
        key=valori_cascata.__getitem__,
    )

    # Se il minimo è il valore iniziale della cascata,
    # il pinch coincide con il livello termico più alto.
    if indice_pinch == 0:
        T_pinch_traslata = livelli[0]

    # Altrimenti corrisponde alla temperatura inferiore
    # dell'intervallo in cui viene raggiunto il minimo.
    else:
        T_pinch_traslata = risultati[
            indice_pinch - 1
        ]["T_inf"]

    pinch_traslati = [T_pinch_traslata]

    return (
        risultati,
        QH_min,
        QC_min,
        pinch_traslati,
    )

def costruisci_curve_composite(flussi, risultati, QC_min, tolleranza=1e-9):
    """Costruisce Hot e Cold Composite Curve sia reali sia traslate."""

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
    
def costruisci_GCC(risultati, QH_min):
    """Costruisce i punti della Grand Composite Curve a partire dalla cascata termica."""

    # Crea il primo punto della GCC:
    # sull'asse Q parte dal minimo fabbisogno di hot utility QH_min,
    # mentre la temperatura è il livello termico più alto della cascata.
    gcc = [(QH_min, risultati[0]["T_sup"])]

    # Aggiunge un punto per ogni riga della cascata finale.
    # Ogni punto ha coordinate:
    # (calore residuo della cascata finale, temperatura inferiore dell'intervallo).
    gcc.extend(
        (riga["cascata_finale"], riga["T_inf"])
        for riga in risultati
    )

    # Restituisce la GCC come lista di punti (Q, T*).
    return gcc

#le pinch rules sono una cosa da rispettare per non andare ad aumentare il MER e il MER cold definito dalla GCC che abbiamo costruito

def self_sufficient_pockets(
    gcc,
    delta_T_min,
    tolleranza=1e-9,
):
    """
    Individua sulla GCC:
    - l'unico Main Pinch Point (MPP);
    - i Potential Pinch Point (PPP);
    - le self-sufficient pockets.

    La metodologia assume un solo Main Pinch Point.
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
            "La GCC non presenta un Main Pinch Point con Q = 0."
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

##################################################

#ANALSI PINCH

def esegui_analisi_pinch(percorso_json):
    """Esegue la Pinch Analysis del caso studio."""

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

######################################################


# 5. UTILITY TARGETING E MILP

def discretizza_GCC(gcc, punti_pinch, delta_T_max, tolleranza=1e-9):
    """Divide la GCC in zone e discretizza ciascuna zona secondo il modello."""

    # MPP e PPP delimitano le zone della GCC. ricercchiamo gli indici che delimitano le zone in cui vogliamo iniziare a discretizzare la curva
    limiti_zone = sorted({0,len(gcc) - 1,*[punto["indice_gcc"]  for tipo in ("main_pinch_points", "potential_pinch_points")  for punto in punti_pinch[tipo] ],
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
    """
    Riordina le zone secondo la convenzione del modello:
    z=1 zona più fredda, z=Z zona più calda;
    k=1 punto più freddo della zona.
    """
    return [list(reversed(zona)) for zona in reversed(zone_GCC)]

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
    """
    Genera tutte le utility candidate e precalcola
    COP ed efficienze secondo le equazioni [1.4]-[1.8].

    Indici del modello:
        HPPr -> (y, j, z, k)
        HPUt -> (z, k)
        Ref  -> (z, k)
        ORC  -> (z, k)
        CHP  -> k nella zona Z
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
    # [1.4] HPPr
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
                        # [1.34] Limite TCondmax sul livello T_zk.
                        if T_cond_max is not None and T_zk > T_cond_max:
                            continue

                        T_evap = T_yj - EvaP #Evap è il delta_T di scambio dell'evaporatore
                        T_cond = T_zk + CondP

                        denominatore = T_cond - T_evap

                        if denominatore <= 0:
                            continue

                        # [1.4]
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
    # [1.5]-[1.8]
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
            # [1.5] HPUt
            #
            # Evaporatore alla sorgente ambiente T0;
            # condensatore al livello termico (z,k).
            # ----------------------------------------------------

            if utilities["HPUt"]["enabled"]:

                T_evap = T0 - EvaP
                T_cond = T_zk + CondP

                # [1.31] HPUt vietata sotto T0.
                # [1.35] HPUt vietata sopra TCondmax.
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
            # [1.6] Refrigerazione Ref
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

                    # [1.6]
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
            # [1.7] ORC
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

                    # [1.7]
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
            # [1.8] CHP
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

                # [1.8]
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
    """
    Costruisce il MILP di preselezione delle utility
    secondo le equazioni [1.9]-[1.36] del modello.

    Questa funzione NON risolve il problema.

    Il suo compito è tradurre il modello matematico in un oggetto DOcplex:
        1. crea il modello;
        2. definisce le variabili decisionali;
        3. aggiunge i vincoli;
        4. definisce la funzione obiettivo;
        5. restituisce tutto ciò che servirà per la successiva risoluzione.

    DOcplex è quindi l'interfaccia Python con cui "scriviamo"
    matematicamente il MILP. CPLEX sarà poi il solver che lo risolve.
    """

    # ============================================================
    # CREAZIONE DEL MODELLO DOCPLEX
    # ============================================================

    # Importiamo la classe Model soltanto quando serve costruire il MILP.
    #
    # In questo modo la semplice Pinch Analysis può funzionare
    # anche senza caricare DOcplex.
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
    # Esempio:
    # [(1,1), (1,2), (1,3), (2,1), ...]
    indici_GCC = []

    # Dizionari contenenti i parametri numerici del modello:
    #
    # Q_GCC[z,k] = coordinata energetica Q_zk
    # T_GCC[z,k] = temperatura T_zk
    #
    # Non sono variabili decisionali:
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
    # [1.9]-[1.13]
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
        (FChp, BoolChp),      # [1.9]
        (FRef, BoolRef),      # [1.10]
        (FORC, BoolORC),      # [1.11]
        (FHPPr, BoolHPPr),    # [1.12]
        (FHPUt, BoolHPUt),    # [1.13]
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
    # [1.14]-[1.17]
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
    # [1.18]-[1.19]
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
    # [1.20]-[1.22]
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
    # [1.23]-[1.25]
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
    # [1.23]
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
            # specifica nell'equazione [1.24].
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
    # [1.24]
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
    # [1.26]-[1.28]
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
    # [1.28] TEC = Total Electricity Consumption
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
    # [1.29]
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
    # [1.30]
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

    # Le equazioni [1.31]-[1.35] non compaiono qui come
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
    # [1.36]
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
def risolvi_modello_utilities(
    componenti,
    log_output=False,
    tolleranza=1e-6,
):
    """
    Risolve il MILP e ricostruisce le caratteristiche
    fisiche delle utility selezionate.
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
    # [1.29]-[1.30] ricostruiscono fuel e potenza elettrica.
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

######################################################à

#PREDESIGN DELLE UTILITIES

def esegui_predesign_utilities(dati_pinch, log_output=False):
    """Discretizza la GCC, costruisce e risolve il utility predesign MILP."""

    configurazione = dati_pinch["configurazione"]
    utilities = configurazione["utilities"]

    # --------------------------------------------------------
    # Discretizzazione richiesta dal modello di predesign.
    # --------------------------------------------------------

    zone_GCC, S_z = discretizza_GCC(
        dati_pinch["gcc"],
        dati_pinch["pinch_data"],
        configurazione["delta_T_max"],
    )

    # --------------------------------------------------------
    # Generazione delle utility candidate [1.4]-[1.8].
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
    # Costruzione MILP [1.9]-[1.36].
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

    # Diagnostica del predesign.
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
    risultati["gcc_aggiornata"] = costruisci_GCC_aggiornata(
        risultati["soluzione"],
        componenti["NHL"],
        componenti["Papp"],
        componenti["Pprel"],
        zone_GCC,
    )

    # Mantiene disponibili i dati di discretizzazione.
    risultati["zone_GCC"] = zone_GCC
    risultati["S_z"] = S_z

    return risultati

########################################################

# 6. OUTPUT E PLOTTING 

def costruisci_GCC_aggiornata(soluzione, NHL, Papp, Pprel, zone_GCC):
    """Costruisce la GCC dopo l'inserimento delle utilities."""

    zone_milp = riordina_zone_per_milp(zone_GCC)

    punti = []

    # Dalla zona più calda alla più fredda
    for z in range(len(zone_milp), 0, -1):

        zona = zone_milp[z - 1]

        # Dalla temperatura più alta alla più bassa
        for k in range(len(zona), 0, -1):

            _, T = zona[k - 1]

            Q = soluzione.get_value(NHL[z, k])

            punti.append((Q, T))

            Papp_zk = soluzione.get_value(Papp[z, k])
            Pprel_zk = soluzione.get_value(Pprel[z, k])

            if Papp_zk > 1e-9 or Pprel_zk > 1e-9:
                punti.append((Q + Papp_zk + Pprel_zk, T))

    return punti

def costruisci_curva_utilities(risultati_milp):
    """Combina tutte le utility selezionate in una curva cumulativa."""
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

def stampa_punti_curva(nome, curva):
    """Stampa indice, carico termico e temperatura dei punti di una curva."""
    print(f"\n{nome}")
    print("indice | Q [kW] | T [°C]")
    for indice, (Q, T) in enumerate(curva):
        print(f"{indice:6d} | {Q:8.3f} | {T:7.3f}")

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
    """Rappresenta Composite Curves, GCC, pockets oppure ICC."""
    # Import ritardato: calcoli Pinch/MILP/HENS non richiedono Matplotlib.
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(8, 6))
    if tipo_grafico in ("composite", "composite_traslate"):
        Q_hot, T_hot = zip(*hot_CC)
        Q_cold, T_cold = zip(*cold_CC)
        ax.plot(Q_hot, T_hot, color="red", marker="o", label="Hot CC")
        ax.plot(Q_cold, T_cold, color="blue", marker="o", label="Cold CC")
        if tipo_grafico == "composite":
            ax.set_title("Composite Curves - temperature reali")
            ax.set_ylabel("Temperatura reale [°C]")
        else:
            ax.set_title("Composite Curves - temperature traslate")
            ax.set_ylabel("Temperatura traslata T* [°C]")
    elif tipo_grafico in ("gcc", "gcc_aggiornata"):
        Q, T = zip(*gcc)
        ax.plot(Q, T, color="red", linewidth=2)
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

def stampa_risultati_milp(risultati):
    """Stampa la soluzione del MILP di utility targeting."""

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
            f"duty={orc['heat_load_kW']:.3f} kW, "
            f"Wprod={orc['P_elettrica_prodotta_kW']:.3f} kW"
        )
    for chp in risultati["CHP_selezionati"]:
        print(
            f"CHP {chp['indice']}: F={chp['FChp']:.6f}, "
            f"Tprocesso={chp['T_processo_C']:.2f} °C, Eff={chp['Eff_CHP']:.3f}, "
            f"duty={chp['heat_load_kW']:.3f} kW, "
            f"Wprod={chp['P_elettrica_prodotta_kW']:.3f} kW"
        )

    print("\nGLOBALI")
    print(f"TEC: {risultati['TEC_kW']:.3f} kW")
    print(f"TEP: {risultati['TEP_kW']:.3f} kW")
    print(f"PprelCHP: {risultati['PprelCHP_kW']:.3f} kW")
    print(f"Hot MER residuo: {risultati['hot_MER_residuo_kW']:.3f} kW")
    print(f"Cold MER residuo: {risultati['cold_MER_residuo_kW']:.3f} kW")
    print(f"FinalExergy: {risultati['FinalExergy_kW']:.3f} kW")

def salva_grafici(dati_pinch, risultati_milp, cartella):
    """Salva Composite Curves, GCC, ICC e self-sufficient pockets."""


    cartella = Path(cartella)
    cartella.mkdir(
        parents=True,
        exist_ok=True,
    )

    curva_utilities = costruisci_curva_utilities(risultati_milp)
    stampa_punti_curva("GCC iniziale", dati_pinch["gcc"])
    stampa_punti_curva("GCC aggiornata", risultati_milp["gcc_aggiornata"])
    stampa_punti_curva("Curva utilities", curva_utilities)

    caso_dairy = "dairy" in dati_pinch["configurazione"].get("nome", "").lower()
    dairy_ylim = (-20, 100) if caso_dairy else None
    dairy_yticks = list(range(-20, 101, 20)) if caso_dairy else None

    # Composite Curves - temperature reali
    grafico_TQ(
        "composite",
        hot_CC=dati_pinch["hot_CC"],
        cold_CC=dati_pinch["cold_CC"],
        percorso_salvataggio=(
            cartella / "composite_curves_reali.png"
        ),
        mostra=False,
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






#------------------------------- HEAT EXCHANGE NETWORK SYNTHESIS-----------------------------------------------------------------------------------


# 1. STRUTTURE DATI

class UtilityHEN:
    """Utility fisica o virtuale disponibile nel modello HENS."""

    def __init__(
        self,
        codice,
        nome,
        tipo,
        T_in,
        T_out,
        h_W_m2K,
        costo_USD_per_kW_year=None,
        duty_variabile=True,
        disponibile=True,
        virtuale=False,
    ):
        self.codice = str(codice)
        self.nome = str(nome)
        self.tipo = str(tipo)

        self.T_in = float(T_in)
        self.T_out = float(T_out)

        self.h_W_m2K = float(h_W_m2K)

        self.costo_USD_per_kW_year = (
            None
            if costo_USD_per_kW_year is None
            else float(costo_USD_per_kW_year)
        )

        self.duty_variabile = bool(duty_variabile)
        self.disponibile = bool(disponibile)
        self.virtuale = bool(virtuale)

class TecnologiaHEN:
    """Tecnologia di scambio disponibile nel modello HENS."""

    def __init__(
        self,
        codice,
        nome,
        FHEX,
        A_max_m2,
        costo_fisso_USD_per_year,
        costo_area_USD_per_m2_year,
        matches,
        enabled=True,
        virtuale=False,
    ):
        self.codice = str(codice)
        self.nome = str(nome)

        self.FHEX = float(FHEX)
        self.A_max_m2 = float(A_max_m2)

        self.costo_fisso_USD_per_year = float(
            costo_fisso_USD_per_year
        )

        self.costo_area_USD_per_m2_year = float(
            costo_area_USD_per_m2_year
        )

        self.matches = frozenset(matches)

        self.enabled = bool(enabled)
        self.virtuale = bool(virtuale)

# 2. INPUT funzioni che gestiscono l'input = "configuazione"

def costruisci_utilities_HEN(configurazione):
    """Legge e valida le utility HENS fisiche dichiarate nel JSON."""
    if "hens" not in configurazione:
        raise ValueError("La configurazione non contiene la sezione 'hens'.")
    dati_hens = configurazione["hens"]
    if not isinstance(dati_hens, dict):
        raise ValueError("La sezione 'hens' deve essere un dizionario.")
    if "utilities" not in dati_hens:
        raise ValueError("La sezione 'hens' non contiene 'utilities'.")
    dati_utilities = dati_hens["utilities"]
    if not isinstance(dati_utilities, list):
        raise ValueError("'hens.utilities' deve essere una lista.")
    utilities = {"hot": [], "cold": []}
    codici = set()
    for dati in dati_utilities:
        if not isinstance(dati, dict):
            raise ValueError(
                "Ogni utility HENS deve essere definita tramite un dizionario."
            )
        campi_obbligatori = ["codice", "tipo", "T_in", "T_out", "h_W_m2K"]
        mancanti = [campo for campo in campi_obbligatori if campo not in dati]
        if mancanti:
            raise ValueError(f"Utility HENS incompleta. Campi mancanti: {mancanti}")
        tipo = str(dati["tipo"]).strip().lower()
        if tipo not in ("hot", "cold"):
            raise ValueError(f"Tipo non valido per utility {dati['codice']}: {tipo}")
        costo_raw = dati.get("costo_USD_per_kW_year")
        costo = None if costo_raw is None else float(costo_raw)
        utility = UtilityHEN(
            codice=str(dati["codice"]),
            nome=str(dati.get("nome", dati["codice"])),
            tipo=tipo,
            T_in=float(dati["T_in"]),
            T_out=float(dati["T_out"]),
            h_W_m2K=float(dati["h_W_m2K"]),
            costo_USD_per_kW_year=costo,
            duty_variabile=bool(dati.get("duty_variabile", True)),
            disponibile=bool(dati.get("disponibile", True)),
        )
        if utility.codice in codici:
            raise ValueError(f"Utility HENS duplicata: {utility.codice}")
        codici.add(utility.codice)
        if utility.tipo == "hot" and utility.T_in <= utility.T_out:
            raise ValueError(
                f"La hot utility {utility.codice} deve avere T_in > T_out."
            )
        if utility.tipo == "cold" and utility.T_out <= utility.T_in:
            raise ValueError(
                f"La cold utility {utility.codice} deve avere T_out > T_in."
            )
        if utility.h_W_m2K <= 0:
            raise ValueError(
                f"h_W_m2K non valido per {utility.codice}: {utility.h_W_m2K}"
            )
        if (
            utility.costo_USD_per_kW_year is not None
            and utility.costo_USD_per_kW_year < 0
        ):
            raise ValueError(
                f"Costo utility negativo per {utility.codice}: {utility.costo_USD_per_kW_year}"
            )
        if not utility.disponibile:
            continue
        utilities[utility.tipo].append(utility)
    return utilities

def costruisci_tecnologie_HEN(configurazione):
    """Costruisce tecnologie abilitate e match P_t dichiarati nel JSON."""
    if "hens" not in configurazione:
        raise ValueError("La configurazione non contiene la sezione 'hens'.")
    dati_hens = configurazione["hens"]
    if "technologies" not in dati_hens:
        raise ValueError("La sezione 'hens' non contiene 'technologies'.")
    dati_tecnologie = dati_hens["technologies"]
    if not isinstance(dati_tecnologie, list):
        raise ValueError("'hens.technologies' deve essere una lista.")
    hot_codes = set()
    cold_codes = set()
    for flusso in configurazione["flussi"]:
        if not flusso.disponibile:
            continue

        if flusso.tipo == "hot":
            hot_codes.add(flusso.codice)

        elif flusso.tipo == "cold":
            cold_codes.add(flusso.codice)
    for dati_utility in dati_hens.get("utilities", []):
        if not dati_utility.get("disponibile", True):
            continue
        codice = str(dati_utility["codice"])
        tipo = str(dati_utility["tipo"]).strip().lower()
        if tipo == "hot":
            hot_codes.add(codice)
        elif tipo == "cold":
            cold_codes.add(codice)
    tecnologie = {}
    codici = set()
    for dati in dati_tecnologie:
        if not isinstance(dati, dict):
            raise ValueError("Ogni tecnologia HENS deve essere un dizionario.")
        campi_obbligatori = [
            "codice",
            "FHEX",
            "A_max_m2",
            "costo_fisso_USD_per_year",
            "costo_area_USD_per_m2_year",
            "matches",
        ]
        mancanti = [campo for campo in campi_obbligatori if campo not in dati]
        if mancanti:
            raise ValueError(f"Tecnologia HENS incompleta. Campi mancanti: {mancanti}")
        codice = str(dati["codice"])
        if codice in codici:
            raise ValueError(f"Tecnologia HENS duplicata: {codice}")
        codici.add(codice)
        enabled = bool(dati.get("enabled", True))
        FHEX = float(dati["FHEX"])
        A_max_m2 = float(dati["A_max_m2"])
        costo_fisso = float(dati["costo_fisso_USD_per_year"])
        costo_area = float(dati["costo_area_USD_per_m2_year"])
        if FHEX <= 0 or FHEX > 1:
            raise ValueError(
                f"FHEX non valido per {codice}: {FHEX}. Deve essere compreso nell'intervallo (0, 1]."
            )
        if A_max_m2 <= 0:
            raise ValueError(f"A_max_m2 non valido per {codice}: {A_max_m2}")
        if costo_fisso < 0:
            raise ValueError(f"Costo fisso negativo per {codice}: {costo_fisso}")
        if costo_area < 0:
            raise ValueError(f"Costo area negativo per {codice}: {costo_area}")
        matches = set()
        for match in dati["matches"]:
            if not isinstance(match, (list, tuple)) or len(match) != 2:
                raise ValueError(
                    f"Match non valido in {codice}: {match}. Ogni match deve essere [hot, cold]."
                )
            i = str(match[0])
            j = str(match[1])
            if i not in hot_codes:
                raise ValueError(
                    f"Match non valido per {codice}: ({i}, {j}). {i} non è una hot stream disponibile."
                )
            if j not in cold_codes:
                raise ValueError(
                    f"Match non valido per {codice}: ({i}, {j}). {j} non è una cold stream disponibile."
                )
            chiave_match = (i, j)
            if chiave_match in matches:
                raise ValueError(f"Match duplicato in {codice}: {chiave_match}")
            matches.add(chiave_match)
        tecnologia = TecnologiaHEN(
            codice=codice,
            nome=str(dati.get("nome", codice)),
            FHEX=FHEX,
            A_max_m2=A_max_m2,
            costo_fisso_USD_per_year=costo_fisso,
            costo_area_USD_per_m2_year=costo_area,
            matches=frozenset(matches),
            enabled=enabled,
        )
        if not enabled:
            continue
        tecnologie[codice] = tecnologia
    T = sorted(tecnologie.keys())
    P_t = {t: set(tecnologie[t].matches) for t in T}
    if not T:
        raise ValueError("Nessuna tecnologia HENS abilitata.")
    return {"T": T, "tecnologie": tecnologie, "P_t": P_t}

def costruisci_flussi_flessibili_HEN(configurazione):
    """Valida e indicizza le flexible streams dichiarate nel JSON.

    Il flusso nominale rappresenta la corrente completa: ``T_out`` coincide
    con ``T_out_min_C`` per una hot stream e con ``T_out_max_C`` per una cold
    stream. Il tratto tra i due limiti e la surplus part.
    """

    processi = {
        flusso.codice: flusso
        for flusso in configurazione ["flussi"]
        if flusso.disponibile
    }
    codici_utility = {
        str(dati["codice"])
        for dati in configurazione.get("hens", {}).get("utilities", [])
    }
    flessibili = {}

    for dati in configurazione.get("hens", {}).get("flexible_streams", []):
        if not dati.get("enabled", True):
            continue

        codice = str(dati["codice"])
        if codice in codici_utility:
            raise ValueError(f"Una utility non puo essere flexible: {codice}.")
        if codice not in processi:
            raise ValueError(
                f"Flexible stream non trovata tra i flussi di processo: {codice}."
            )
        if codice in flessibili:
            raise ValueError(f"Flexible stream duplicata: {codice}.")

        corrente = processi[codice]
        T_min = float(dati["T_out_min_C"])
        T_max = float(dati["T_out_max_C"])
        if T_min >= T_max:
            raise ValueError(f"Per {codice} deve valere T_out_min_C < T_out_max_C.")

        if corrente.tipo == "hot":
            coerente = corrente.T_in > T_max and abs(corrente.T_out - T_min) <= 1e-9
        else:
            coerente = corrente.T_in < T_min and abs(corrente.T_out - T_max) <= 1e-9
        if not coerente:
            raise ValueError(
                f"Range di uscita non coerente con il verso e i dati di {codice}."
            )

        flessibili[codice] = {
            "codice": codice,
            "tipo": corrente.tipo,
            "T_out_min_C": T_min,
            "T_out_max_C": T_max,
            "CP_kW_K": corrente.CP,
            "corrente": corrente,
        }

    return flessibili



#3. PREPROCESSING HENS E FLEXIBLE STREAMS-

def crea_partizione_HEN(
    gcc,
    flussi,

    delta_T_min,
    pinch_traslati,
    delta_T_partition_max,
    numero_intervalli_min,
    utilities=None,
    separa_al_pinch=True,
    flexible_streams=None,
):
    """Costruisce la partizione HENS sulla scala hot reale/cold traslata.

    Include estremi GCC, correnti, utility e flexible streams; applica il passo
    massimo, gli intervalli interni minimi e, se richiesto, la separazione al pinch."""
    tolleranza = 1e-09
    if type(separa_al_pinch) is not bool:
        raise ValueError("separa_al_pinch deve essere True oppure False.")
    if len(gcc) < 2:
        raise ValueError("La GCC deve contenere almeno due punti.")
    if delta_T_partition_max <= 0:
        raise ValueError("delta_T_partition_max deve essere > 0.")
    if numero_intervalli_min < 1:
        raise ValueError("numero_intervalli_min deve essere >= 1.")
    if utilities is None:
        utilities = {"hot": [], "cold": []}
    utilities_hot = utilities.get("hot", [])
    utilities_cold = utilities.get("cold", [])
    flexible_streams = flexible_streams or {}
    correnti_partizione = list(flussi) + list(utilities_hot) + list(utilities_cold)

    def temperature_corrente_HEN(corrente):
        return (
            converti_temperatura(
                corrente.T_in,
                corrente.tipo,
                delta_T_min,
                "reale",
                "hens",
            ),
            converti_temperatura(
                corrente.T_out,
                corrente.tipo,
                delta_T_min,
                "reale",
                "hens",
            ),
        )

    def corrente_disponibile(corrente):
        return getattr(corrente, "disponibile", True)

    vertici = [gcc[0]]
    for p1, p2, p3 in zip(gcc, gcc[1:], gcc[2:]):
        Q1, T1 = p1
        Q2, T2 = p2
        Q3, T3 = p3
        lhs = (Q2 - Q1) * (T3 - T2)
        rhs = (T2 - T1) * (Q3 - Q2)
        cambio_pendenza = abs(lhs - rhs) > tolleranza
        if cambio_pendenza:
            vertici.append(p2)
    vertici.append(gcc[-1])
    temperature_gcc = [
        converti_temperatura(
            T_star,
            "hot",
            delta_T_min,
            "pinch",
            "hens",
        )
        for _, T_star in vertici
    ]

    pinch_HEN = [
        converti_temperatura(
            T_star,
            "hot",
            delta_T_min,
            "pinch",
            "hens",
        )
        for T_star in pinch_traslati
    ]
    temperature_correnti = []
    
    for corrente in correnti_partizione:
        if not corrente_disponibile(corrente):
            continue
        T1, T2 = temperature_corrente_HEN(corrente)
        temperature_correnti.extend([T1, T2])
    for dati in flexible_streams.values():
        temperature_correnti.extend(
    [
        converti_temperatura(
            dati["T_out_min_C"],
            dati["tipo"],
            delta_T_min,
            "reale",
            "hens",
        ),
        converti_temperatura(
            dati["T_out_max_C"],
            dati["tipo"],
            delta_T_min,
            "reale",
            "hens",
        ),
    ]
)
      
    
    temperature_base = list(temperature_gcc) + list(temperature_correnti)
    if not temperature_base:
        raise ValueError(
            "Nessuna temperatura disponibile per costruire la partizione HENS."
        )
    T_max = max(temperature_base)
    T_min = min(temperature_base)
    pinch_interni = sorted(
        {T for T in pinch_HEN if T_min + tolleranza < T < T_max - tolleranza},
        reverse=True,
    )
    if separa_al_pinch:
        limiti_zone = [T_max, *pinch_interni, T_min]
    else:
        limiti_zone = [T_max, T_min]
    zone = {}
    for z, (T_sup_z, T_inf_z) in enumerate(zip(limiti_zone, limiti_zone[1:]), start=1):
        livelli = {T_sup_z, T_inf_z}
        for T in temperature_gcc:
            if T_inf_z - tolleranza <= T <= T_sup_z + tolleranza:
                livelli.add(T)
        for T in temperature_correnti:
            if T_inf_z - tolleranza <= T <= T_sup_z + tolleranza:
                livelli.add(T)
        livelli_iniziali = set(livelli)
        iterazione = 0
        while True:
            livelli_ordinati = sorted(livelli, reverse=True)
            nuovi_livelli = []
            for T_sup, T_inf in zip(livelli_ordinati, livelli_ordinati[1:]):
                delta_T = T_sup - T_inf
                if delta_T > delta_T_partition_max + tolleranza:
                    T_medio = (T_sup + T_inf) / 2
                    nuovi_livelli.append(T_medio)
            if not nuovi_livelli:
                break
            iterazione += 1
            livelli.update(nuovi_livelli)
        for corrente in correnti_partizione:
            if not corrente_disponibile(corrente):
                continue
            T1, T2 = temperature_corrente_HEN(corrente)
            T_stream_sup = min(max(T1, T2), T_sup_z)
            T_stream_inf = max(min(T1, T2), T_inf_z)
            if T_stream_sup <= T_stream_inf + tolleranza:
                continue
            livelli_interni = [
                T
                for T in livelli
                if T_stream_inf + tolleranza < T < T_stream_sup - tolleranza
            ]
            if len(livelli_interni) < 2:
                delta_T_stream = T_stream_sup - T_stream_inf
                T_a = T_stream_inf + delta_T_stream / 3
                T_b = T_stream_inf + 2 * delta_T_stream / 3
                livelli.add(T_a)
                livelli.add(T_b)
        while len(livelli) - 1 < numero_intervalli_min:
            livelli_ordinati = sorted(livelli, reverse=True)
            T_sup_maggiore, T_inf_maggiore = max(
                zip(livelli_ordinati, livelli_ordinati[1:]),
                key=lambda coppia: coppia[0] - coppia[1],
            )
            T_medio = (T_sup_maggiore + T_inf_maggiore) / 2
            livelli.add(T_medio)
        livelli_finali = sorted(livelli, reverse=True)
        zone[z] = [
            (T_sup, T_inf) for T_sup, T_inf in zip(livelli_finali, livelli_finali[1:])
        ]
    
    return zone

def costruisci_utilities_virtuali_HEN(
    intervalli,
    flussi_flessibili,
    flussi,
    delta_T_min,
    delta_T_partition_max,
):
    """Crea le utility virtuali [1.48]-[1.49] con un solo passaggio aggiuntivo.

    Gli estremi sono ricavati da una partizione preliminare priva di utility
    virtuali. Le temperature della cold utility vengono memorizzate sulla
    scala reale; la traslazione ``+delta_T_min`` le riporta ai valori di
    [1.49] sulla scala HENS.

    ``h_default`` e il massimo coefficiente di film tra tutte le process
    streams disponibili. E una convenzione puramente numerica: la tecnologia
    virtuale ha costo nullo e non condivide match fisici.

    La costruzione con una coppia VHU/VCU e stata verificata sui benchmark
    HENS economici a zona unica; non modella utility virtuali distinte per zona.
    """

    if not flussi_flessibili:
        return {"hot": [], "cold": []}

    T_sup = max(T_U for zona in intervalli.values() for T_U, _ in zona)
    T_inf = min(T_L for zona in intervalli.values() for _, T_L in zona)
    estensione = 1.5 * float(delta_T_partition_max)
    h_default = max(
        float(f.h_W_m2K) for f in flussi if f.h_W_m2K is not None and f.disponibile
    )
    virtuali = {"hot": [], "cold": []}

    if any(dati["tipo"] == "cold" for dati in flussi_flessibili.values()):
        virtuali["hot"].append(
            UtilityHEN(
                codice="VHU",
                nome="Virtual hot utility",
                tipo="hot",
                T_in=T_sup + estensione,
                T_out=T_sup,
                h_W_m2K=h_default,
                costo_USD_per_kW_year=0.0,
                virtuale=True,
            )
        )

    if any(dati["tipo"] == "hot" for dati in flussi_flessibili.values()):
        T_out_reale = converti_temperatura(
                                            T_inf,
                                            "cold",
                                            delta_T_min,
                                            "hens",
                                            "reale",
                                        )
        virtuali["cold"].append(
            UtilityHEN(
                codice="VCU",
                nome="Virtual cold utility",
                tipo="cold",
                T_in=T_out_reale - estensione,
                T_out=T_out_reale,
                h_W_m2K=h_default,
                costo_USD_per_kW_year=0.0,
                virtuale=True,
            )
        )

    return virtuali

def aggiungi_tecnologia_virtuale_HEN(
    tecnologie_HEN,
    utilities_HEN,
    flussi_flessibili,
):
    """Aggiunge la tecnologia HEX virtuale esclusivamente ai match virtuali."""

    VHU = [u.codice for u in utilities_HEN["hot"] if u.virtuale]
    VCU = [u.codice for u in utilities_HEN["cold"] if u.virtuale]
    matches = {
        (vhu, codice)
        for vhu in VHU
        for codice, dati in flussi_flessibili.items()
        if dati["tipo"] == "cold"
    } | {
        (codice, vcu)
        for vcu in VCU
        for codice, dati in flussi_flessibili.items()
        if dati["tipo"] == "hot"
    }
    if not matches:
        return tecnologie_HEN

    codice = "TVIRTUAL"
    if codice in tecnologie_HEN["tecnologie"]:
        raise ValueError(f"Codice tecnologia riservato gia utilizzato: {codice}.")

    # U e intera ma non limitata: A_max e solo l'area di una shell virtuale.
    # Si riusa il maggiore A_max dichiarato dal designer, senza magic number.
    A_max = max(t.A_max_m2 for t in tecnologie_HEN["tecnologie"].values())
    tecnologia = TecnologiaHEN(
        codice=codice,
        nome="Virtual heat exchanger technology",
        FHEX=1.0,
        A_max_m2=A_max,
        costo_fisso_USD_per_year=0.0,
        costo_area_USD_per_m2_year=0.0,
        matches=frozenset(matches),
        virtuale=True,
    )
    tecnologie_HEN["T"].append(codice)
    tecnologie_HEN["tecnologie"][codice] = tecnologia
    tecnologie_HEN["P_t"][codice] = set(matches)
    return tecnologie_HEN

def costruisci_insiemi_HEN(
    flussi,
    utilities,
    intervalli,
    delta_T_min,
    match_permessi=None,
    NI_H=None,
    NI_C=None,
    flexible_streams=None,
):
    """Costruisce gli insiemi HENS, inclusi HF, CF, MF e NF.

    Le cold streams sono rappresentate a temperatura reale + delta_T_min."""
    processi = [flusso for flusso in flussi if flusso.disponibile]
    hot_utilities = utilities.get("hot", [])
    cold_utilities = utilities.get("cold", [])
    correnti = processi + hot_utilities + cold_utilities
    correnti_per_codice = {flusso.codice: flusso for flusso in correnti}
    Z = list(intervalli.keys())
    M = {z: list(range(1, len(intervalli[z]) + 1)) for z in Z}
    T_intervallo = {
        (z, m): {"T_sup": T_sup, "T_inf": T_inf}
        for z in Z
        for m, (T_sup, T_inf) in enumerate(intervalli[z], start=1)
    }

    def temperature_HEN(flusso):
        return (
            converti_temperatura(
                flusso.T_in,
                flusso.tipo,
                delta_T_min,
                "reale",
                "hens",
            ),
            converti_temperatura(
                flusso.T_out,
                flusso.tipo,
                delta_T_min,
                "reale",
                "hens",
            ),
        )

    def presente(flusso, T_sup, T_inf):
        T1, T2 = temperature_HEN(flusso)
        T_max = max(T1, T2)
        T_min = min(T1, T2)
        return T_max >= T_sup and T_min <= T_inf

    H_m = {}
    C_n = {}
    for z in Z:
        for m in M[z]:
            T_sup, T_inf = intervalli[z][m - 1]
            H_m[z, m] = [
                flusso.codice
                for flusso in correnti
                if flusso.tipo == "hot" and presente(flusso, T_sup, T_inf)
            ]
            C_n[z, m] = [
                flusso.codice
                for flusso in correnti
                if flusso.tipo == "cold" and presente(flusso, T_sup, T_inf)
            ]
    H = {z: sorted({i for m in M[z] for i in H_m[z, m]}) for z in Z}
    C = {z: sorted({j for m in M[z] for j in C_n[z, m]}) for z in Z}
    codici_HU = {utility.codice for utility in hot_utilities}
    codici_CU = {utility.codice for utility in cold_utilities}
    HU = {z: [i for i in H[z] if i in codici_HU] for z in Z}
    CU = {z: [j for j in C[z] if j in codici_CU] for z in Z}
    virtual_hot_codes = {
        utility.codice
        for utility in hot_utilities
        if getattr(utility, "virtuale", False)
    }
    virtual_cold_codes = {
        utility.codice
        for utility in cold_utilities
        if getattr(utility, "virtuale", False)
    }
    VHU = {z: [i for i in HU[z] if i in virtual_hot_codes] for z in Z}
    VCU = {z: [j for j in CU[z] if j in virtual_cold_codes] for z in Z}
    flexible_streams = flexible_streams or {}
    HF = {
        z: [
            i
            for i in H[z]
            if i in flexible_streams and flexible_streams[i]["tipo"] == "hot"
        ]
        for z in Z
    }
    CF = {
        z: [
            j
            for j in C[z]
            if j in flexible_streams and flexible_streams[j]["tipo"] == "cold"
        ]
        for z in Z
    }
    M_i = {(z, i): [m for m in M[z] if i in H_m[z, m]] for z in Z for i in H[z]}
    N_j = {(z, j): [n for n in M[z] if j in C_n[z, n]] for z in Z for j in C[z]}

    def intervalli_surplus(z, codice, indici):
        dati = flexible_streams[codice]
        T_min = converti_temperatura(
            dati["T_out_min_C"],
            dati["tipo"],
            delta_T_min,
            "reale",
            "hens",
        )

        T_max = converti_temperatura(
            dati["T_out_max_C"],
            dati["tipo"],
            delta_T_min,
            "reale",
            "hens",
        )
        return [
            indice
            for indice in indici
            if T_intervallo[z, indice]["T_sup"] <= T_max + 1e-09
            and T_intervallo[z, indice]["T_inf"] >= T_min - 1e-09
        ]

    MF = {(z, i): intervalli_surplus(z, i, M_i[z, i]) for z in Z for i in HF[z]}
    NF = {(z, j): intervalli_surplus(z, j, N_j[z, j]) for z in Z for j in CF[z]}
    if match_permessi is None:
        P = {
            (i, j)
            for z in Z
            for i in H[z]
            for j in C[z]
            if not (i in HU[z] and j in CU[z])
        }
    else:
        P = {
            (i, j)
            for i, j in match_permessi
            if not any((i in HU[z] and j in CU[z] for z in Z))
        }
    P_H = {
        (z, i, m): [j for j in C[z] if (i, j) in P]
        for z in Z
        for i in H[z]
        for m in M_i[z, i]
    }
    P_C = {
        (z, j, n): [i for i in H[z] if (i, j) in P]
        for z in Z
        for j in C[z]
        for n in N_j[z, j]
    }
    NI_H = set() if NI_H is None else set(NI_H)
    NI_C = set() if NI_C is None else set(NI_C)
    return {
        "Z": Z,
        "H": H,
        "C": C,
        "HU": HU,
        "CU": CU,
        "VHU": VHU,
        "VCU": VCU,
        "HF": HF,
        "CF": CF,
        "MF": MF,
        "NF": NF,
        "M": M,
        "M_i": M_i,
        "N_j": N_j,
        "H_m": H_m,
        "C_n": C_n,
        "P": P,
        "P_H": P_H,
        "P_C": P_C,
        "NI_H": NI_H,
        "NI_C": NI_C,
        "T_intervallo": T_intervallo,
        "correnti": correnti_per_codice,
        "flexible_streams": flexible_streams,
    }

def genera_indici_q_HEN(insiemi_HEN, tolleranza=1e-09):
    """Genera soltanto gli indici q termicamente e strutturalmente ammessi.

    Le esclusioni delle utility virtuali [1.50]-[1.51] sono applicate qui, senza
    creare variabili q vincolate artificialmente a zero."""
    Z = insiemi_HEN["Z"]
    H = insiemi_HEN["H"]
    C = insiemi_HEN["C"]
    M_i = insiemi_HEN["M_i"]
    N_j = insiemi_HEN["N_j"]
    P = insiemi_HEN["P"]
    P_H = insiemi_HEN["P_H"]
    P_C = insiemi_HEN["P_C"]
    HF = insiemi_HEN.get("HF", {})
    CF = insiemi_HEN.get("CF", {})
    MF = insiemi_HEN.get("MF", {})
    NF = insiemi_HEN.get("NF", {})
    VHU = insiemi_HEN.get("VHU", {})
    VCU = insiemi_HEN.get("VCU", {})
    T_intervallo = insiemi_HEN["T_intervallo"]
    indici_q = []
    for z in Z:
        for i in H[z]:
            for m in M_i[z, i]:
                T_m_U = T_intervallo[z, m]["T_sup"]
                for j in P_H[z, i, m]:
                    if (i, j) not in P:
                        continue
                    if j not in C[z]:
                        continue
                    for n in N_j[z, j]:
                        if i in VHU.get(z, []):
                            if j not in CF.get(z, []) or n not in NF.get((z, j), []):
                                continue
                        if j in VCU.get(z, []):
                            if i not in HF.get(z, []) or m not in MF.get((z, i), []):
                                continue
                        if i not in P_C[z, j, n]:
                            continue
                        T_n_L = T_intervallo[z, n]["T_inf"]
                        if T_n_L < T_m_U - tolleranza:
                            indici_q.append((z, i, m, j, n))
    indici_q = sorted(set(indici_q), key=lambda x: (x[0], x[1], x[2], x[3], x[4]))
    return indici_q

def calcola_delta_H_HEN(insiemi_HEN, tolleranza=1e-09):
    """Calcola i carichi di intervallo delle process streams per [1.37]-[1.38]."""
    Z = insiemi_HEN["Z"]
    H = insiemi_HEN["H"]
    C = insiemi_HEN["C"]
    HU = insiemi_HEN["HU"]
    CU = insiemi_HEN["CU"]
    M_i = insiemi_HEN["M_i"]
    N_j = insiemi_HEN["N_j"]
    NI_H = insiemi_HEN["NI_H"]
    NI_C = insiemi_HEN["NI_C"]
    T_intervallo = insiemi_HEN["T_intervallo"]
    correnti = insiemi_HEN["correnti"]
    delta_H_H = {}
    delta_H_C = {}

    def calcola_CP_equivalente(flusso):
        delta_T_totale = abs(flusso.T_in - flusso.T_out)
        if delta_T_totale <= tolleranza:
            raise ValueError(
                f"La corrente {flusso.codice} è isoterma. La gestione delle correnti isoterme nel modello HENS deve essere trattata separatamente."
            )
        Q_totale = flusso.calcola_Q()
        return Q_totale / delta_T_totale

    for z in Z:
        for i in H[z]:
            if i in HU[z]:
                continue
            if i in NI_H:
                continue
            flusso = correnti[i]
            CP = calcola_CP_equivalente(flusso)
            for m in M_i[z, i]:
                T_sup = T_intervallo[z, m]["T_sup"]
                T_inf = T_intervallo[z, m]["T_inf"]
                delta_T = T_sup - T_inf
                delta_H_H[z, i, m] = CP * delta_T
    for z in Z:
        for j in C[z]:
            if j in CU[z]:
                continue
            if j in NI_C:
                continue
            flusso = correnti[j]
            CP = calcola_CP_equivalente(flusso)
            for n in N_j[z, j]:
                T_sup = T_intervallo[z, n]["T_sup"]
                T_inf = T_intervallo[z, n]["T_inf"]
                delta_T = T_sup - T_inf
                delta_H_C[z, j, n] = CP * delta_T
    return {"delta_H_H": delta_H_H, "delta_H_C": delta_H_C}

def calcola_F_U_BAR05_HEN(configurazione, utilities_HEN, tolleranza=1e-12):
    """Costruisce i parametri fisici F_i^U/F_j^U del corrigendum BAR05.

    Il bound della hot utility deriva dall'intero fabbisogno nominale delle
    process cold streams; quello della cold utility dall'intera disponibilita
    nominale delle process hot streams. Le flexible streams contribuiscono
    quindi con il duty nominale massimo, prima del solve. Le utility virtuali
    non appartengono a questa parametrizzazione fisica.
    """
    processi = [
        flusso
        for flusso in configurazione ["flussi"]
        if flusso.disponibile
    ]
    Q_HU_max = sum(
        flusso.calcola_Q() for flusso in processi if flusso.tipo == "cold"
    )
    Q_CU_max = sum(
        flusso.calcola_Q() for flusso in processi if flusso.tipo == "hot"
    )
    F_U_hot = {}
    F_U_cold = {}
    diagnostica = []

    for tipo, Q_U_max, destinazione in (
        ("hot", Q_HU_max, F_U_hot),
        ("cold", Q_CU_max, F_U_cold),
    ):
        for utility in utilities_HEN[tipo]:
            if utility.virtuale:
                continue
            delta_T_utility = abs(utility.T_in - utility.T_out)
            if delta_T_utility <= tolleranza:
                raise ValueError(
                    f"Impossibile costruire F_U per {utility.codice}: "
                    f"|T_in-T_out|={delta_T_utility}."
                )
            F_U = Q_U_max / delta_T_utility
            destinazione[utility.codice] = F_U
            diagnostica.append(
                {
                    "codice": utility.codice,
                    "tipo": tipo,
                    "T_in_C": utility.T_in,
                    "T_out_C": utility.T_out,
                    "Q_U_max_kW": Q_U_max,
                    "delta_T_utility_K": delta_T_utility,
                    "F_U_kW_K": F_U,
                    "unita_F_U": "kW/K",
                    "verifica_dimensionale": (
                        "F_U [kW/K] * delta_T_interval [K] = qhat_U [kW]"
                    ),
                }
            )
    return {
        "F_U_hot": F_U_hot,
        "F_U_cold": F_U_cold,
        "Q_HU_max_kW": Q_HU_max,
        "Q_CU_max_kW": Q_CU_max,
        "diagnostica": diagnostica,
    }

def costruisci_insiemi_BAR05_HEN(insiemi_HEN, configurazione=None):
    """Deriva SH/SC, B, limiti e cardinalita massime della formulazione BAR05.

    SH e SC contengono tutte e sole le process streams: utility fisiche,
    utility virtuali e relative pseudo-correnti sono escluse dallo splitting.
    B e letto da ``hens.multiple_matches`` e non contiene logica specifica per
    un test. Gli estremi sono ricavati da M_i/N_j, senza duplicare la
    partizione HENS.
    """
    Z = insiemi_HEN["Z"]
    HU = insiemi_HEN["HU"]
    CU = insiemi_HEN["CU"]
    VHU = insiemi_HEN.get("VHU", {})
    VCU = insiemi_HEN.get("VCU", {})
    SH = {
        z: [i for i in insiemi_HEN["H"][z] if i not in HU[z] and i not in VHU.get(z, [])]
        for z in Z
    }
    SC = {
        z: [j for j in insiemi_HEN["C"][z] if j not in CU[z] and j not in VCU.get(z, [])]
        for z in Z
    }
    hens = (configurazione or {}).get("hens", {})
    dati_B = hens.get("multiple_matches", [])
    if not isinstance(dati_B, list):
        raise ValueError("'hens.multiple_matches' deve essere una lista.")
    B = set()
    for match in dati_B:
        if not isinstance(match, (list, tuple)) or len(match) != 2:
            raise ValueError(f"Multiple match non valido: {match}.")
        coppia = (str(match[0]), str(match[1]))
        if coppia not in insiemi_HEN["P"]:
            raise ValueError(f"Multiple match non presente in P: {coppia}.")
        B.add(coppia)
    limite_default = int(hens.get("max_exchangers_per_multiple_match", 2))
    if B and limite_default < 2:
        raise ValueError("Il massimo per una multiple match deve essere almeno 2.")
    Emax = {coppia: limite_default for coppia in B}
    m0 = {(z, i): min(insiemi_HEN["M_i"][z, i]) for z in Z for i in insiemi_HEN["H"][z]}
    mf = {(z, i): max(insiemi_HEN["M_i"][z, i]) for z in Z for i in insiemi_HEN["H"][z]}
    n0 = {(z, j): min(insiemi_HEN["N_j"][z, j]) for z in Z for j in insiemi_HEN["C"][z]}
    nf = {(z, j): max(insiemi_HEN["N_j"][z, j]) for z in Z for j in insiemi_HEN["C"][z]}
    return {"SH": SH, "SC": SC, "B": B, "Emax": Emax, "m0": m0, "mf": mf, "n0": n0, "nf": nf}

# 4. MODELLO HENS BASE
def crea_modello_bilanci_HEN(
    insiemi_HEN, indici_q, delta_H_HEN, nome_modello="HENS_bilanci"
):
    """Crea variabili q e portate utility con i bilanci HENS [1.37]-[1.41]."""
    # Import ritardato per mantenere indipendente la modalita' Pinch.
    from docplex.mp.model import Model

    Z = insiemi_HEN["Z"]
    H = insiemi_HEN["H"]
    C = insiemi_HEN["C"]
    HU = insiemi_HEN["HU"]
    CU = insiemi_HEN["CU"]
    M_i = insiemi_HEN["M_i"]
    N_j = insiemi_HEN["N_j"]
    NI_H = set(insiemi_HEN.get("NI_H", []))
    NI_C = set(insiemi_HEN.get("NI_C", []))
    T_intervallo = insiemi_HEN["T_intervallo"]
    delta_H_H = delta_H_HEN["delta_H_H"]
    delta_H_C = delta_H_HEN["delta_H_C"]
    if NI_H or NI_C:
        raise NotImplementedError(
            f"crea_modello_bilanci_HEN() non gestisce ancora il non-isothermal mixing. NI_H={NI_H}, NI_C={NI_C}"
        )
    mdl = Model(name=nome_modello)
    q = mdl.continuous_var_dict(indici_q, lb=0, name="q")
    codici_HU = sorted({i for z in Z for i in HU[z]})
    codici_CU = sorted({j for z in Z for j in CU[z]})
    F_H = mdl.continuous_var_dict(codici_HU, lb=0, name="F_H")
    F_C = mdl.continuous_var_dict(codici_CU, lb=0, name="F_C")
    q_da_hot = {}
    q_a_cold = {}
    for indice in indici_q:
        z, i, m, j, n = indice
        q_da_hot.setdefault((z, i, m), []).append(indice)
        q_a_cold.setdefault((z, j, n), []).append(indice)
    vincoli_hot_process = []
    vincoli_cold_process = []
    vincoli_hot_utility = []
    vincoli_cold_utility = []
    for z in Z:
        for i in H[z]:
            if i in HU[z]:
                for m in M_i[z, i]:
                    T_sup = T_intervallo[z, m]["T_sup"]
                    T_inf = T_intervallo[z, m]["T_inf"]
                    delta_T_m = T_sup - T_inf
                    chiavi_q = q_da_hot.get((z, i, m), [])
                    Q_uscente = mdl.sum((q[k] for k in chiavi_q))
                    vincolo = mdl.add_constraint(
                        F_H[i] * delta_T_m == Q_uscente, ctname=f"bil_HU_z{z}_{i}_m{m}"
                    )
                    vincoli_hot_utility.append(vincolo)
            else:
                for m in M_i[z, i]:
                    chiave_delta_H = (z, i, m)
                    if chiave_delta_H not in delta_H_H:
                        raise KeyError(f"ΔH hot mancante per {chiave_delta_H}")
                    valore_delta_H = delta_H_H[chiave_delta_H]
                    chiavi_q = q_da_hot.get(chiave_delta_H, [])
                    if valore_delta_H > 1e-12 and (not chiavi_q):
                        raise ValueError(
                            f"Nessun indice q disponibile per il bilancio hot {chiave_delta_H}."
                        )
                    Q_uscente = mdl.sum((q[k] for k in chiavi_q))
                    vincolo = mdl.add_constraint(
                        Q_uscente == valore_delta_H, ctname=f"bil_HP_z{z}_{i}_m{m}"
                    )
                    vincoli_hot_process.append(vincolo)
    for z in Z:
        for j in C[z]:
            if j in CU[z]:
                for n in N_j[z, j]:
                    T_sup = T_intervallo[z, n]["T_sup"]
                    T_inf = T_intervallo[z, n]["T_inf"]
                    delta_T_n = T_sup - T_inf
                    chiavi_q = q_a_cold.get((z, j, n), [])
                    Q_entrante = mdl.sum((q[k] for k in chiavi_q))
                    vincolo = mdl.add_constraint(
                        F_C[j] * delta_T_n == Q_entrante, ctname=f"bil_CU_z{z}_{j}_n{n}"
                    )
                    vincoli_cold_utility.append(vincolo)
            else:
                for n in N_j[z, j]:
                    chiave_delta_H = (z, j, n)
                    if chiave_delta_H not in delta_H_C:
                        raise KeyError(f"ΔH cold mancante per {chiave_delta_H}")
                    valore_delta_H = delta_H_C[chiave_delta_H]
                    chiavi_q = q_a_cold.get(chiave_delta_H, [])
                    if valore_delta_H > 1e-12 and (not chiavi_q):
                        raise ValueError(
                            f"Nessun indice q disponibile per il bilancio cold {chiave_delta_H}."
                        )
                    Q_entrante = mdl.sum((q[k] for k in chiavi_q))
                    vincolo = mdl.add_constraint(
                        Q_entrante == valore_delta_H, ctname=f"bil_CP_z{z}_{j}_n{n}"
                    )
                    vincoli_cold_process.append(vincolo)
    delta_T_HU = {i: 0.0 for i in codici_HU}
    delta_T_CU = {j: 0.0 for j in codici_CU}
    for z in Z:
        for i in HU[z]:
            for m in M_i[z, i]:
                T_sup = T_intervallo[z, m]["T_sup"]
                T_inf = T_intervallo[z, m]["T_inf"]
                delta_T_HU[i] += T_sup - T_inf
        for j in CU[z]:
            for n in N_j[z, j]:
                T_sup = T_intervallo[z, n]["T_sup"]
                T_inf = T_intervallo[z, n]["T_inf"]
                delta_T_CU[j] += T_sup - T_inf
    Q_HU = {i: F_H[i] * delta_T_HU[i] for i in codici_HU}
    Q_CU = {j: F_C[j] * delta_T_CU[j] for j in codici_CU}
    mdl.minimize(0)
    return {
        "modello": mdl,
        "q": q,
        "F_H": F_H,
        "F_C": F_C,
        "Q_HU": Q_HU,
        "Q_CU": Q_CU,
        "delta_T_HU": delta_T_HU,
        "delta_T_CU": delta_T_CU,
        "vincoli": {
            "hot_process": vincoli_hot_process,
            "cold_process": vincoli_cold_process,
            "hot_utility": vincoli_hot_utility,
            "cold_utility": vincoli_cold_utility,
        },
    }

def calcola_parametri_area_HEN(insiemi_HEN, indici_q, delta_T_min, tolleranza=1e-09):
    """Calcola LMTD e coefficienti lineari di area usati in [1.43]."""
    T_intervallo = insiemi_HEN["T_intervallo"]
    correnti = insiemi_HEN["correnti"]
    if delta_T_min < 0:
        raise ValueError("delta_T_min deve essere >= 0.")

    def leggi_h_kW_m2K(codice_corrente):
        """
        Legge h_W_m2K dall'oggetto corrente
        e lo converte:

            W/m²K -> kW/m²K
        """
        if codice_corrente not in correnti:
            raise KeyError(
                f"Corrente {codice_corrente} non presente in insiemi_HEN['correnti']."
            )
        corrente = correnti[codice_corrente]
        if not hasattr(corrente, "h_W_m2K"):
            raise ValueError(
                f"La corrente {codice_corrente} non possiede l'attributo 'h_W_m2K'. Controllare la classe Flusso e il caricamento del JSON."
            )
        h_W_m2K = corrente.h_W_m2K
        if h_W_m2K is None:
            raise ValueError(f"h_W_m2K non definito per {codice_corrente}.")
        h_W_m2K = float(h_W_m2K)
        if h_W_m2K <= 0:
            raise ValueError(
                f"h_W_m2K deve essere > 0 per {codice_corrente}. Ricevuto: {h_W_m2K}"
            )
        return h_W_m2K / 1000.0

    def calcola_LMTD(delta_T_1, delta_T_2):
        """
        Calcola la differenza media logaritmica
        di temperatura.

        ΔT_ML =
            (ΔT1 - ΔT2)
            / ln(ΔT1 / ΔT2)

        Se ΔT1 ≈ ΔT2:

            ΔT_ML = ΔT1
        """
        if delta_T_1 <= tolleranza or delta_T_2 <= tolleranza:
            raise ValueError(
                f"LMTD non definibile con differenze di temperatura nulle o negative. ΔT1={delta_T_1:.6f}, ΔT2={delta_T_2:.6f}"
            )
        if abs(delta_T_1 - delta_T_2) <= tolleranza:
            return 0.5 * (delta_T_1 + delta_T_2)
        return (delta_T_1 - delta_T_2) / math.log(delta_T_1 / delta_T_2)

    h_H = {}
    h_C = {}
    delta_T_ML = {}
    coeff_area = {}
    dettagli = {}
    for indice in indici_q:
        z, i, m, j, n = indice
        chiave_h_hot = (z, i, m)
        chiave_h_cold = (z, j, n)
        if chiave_h_hot not in h_H:
            h_H[chiave_h_hot] = leggi_h_kW_m2K(i)
        if chiave_h_cold not in h_C:
            h_C[chiave_h_cold] = leggi_h_kW_m2K(j)
        h_im = h_H[chiave_h_hot]
        h_jn = h_C[chiave_h_cold]
        T_hot_U = T_intervallo[z, m]["T_sup"]
        T_hot_L = T_intervallo[z, m]["T_inf"]
        T_cold_U_HEN = T_intervallo[z, n]["T_sup"]
        T_cold_L_HEN = T_intervallo[z, n]["T_inf"]
        T_cold_U = converti_temperatura(
                                        T_cold_U_HEN,
                                        "cold",
                                        delta_T_min,
                                        "hens",
                                        "reale",
                                        )

        T_cold_L = converti_temperatura(
                                        T_cold_L_HEN,
                                        "cold",
                                        delta_T_min,
                                        "hens",
                                        "reale",
                                    )
        delta_T_1 = T_hot_U - T_cold_U
        delta_T_2 = T_hot_L - T_cold_L
        DT_ML = calcola_LMTD(delta_T_1, delta_T_2)
        delta_T_ML[z, m, n] = DT_ML
        coeff = (1.0 / h_im + 1.0 / h_jn) / DT_ML
        coeff_area[indice] = coeff
        dettagli[indice] = {
            "h_hot_kW_m2K": h_im,
            "h_cold_kW_m2K": h_jn,
            "T_hot_U_C": T_hot_U,
            "T_hot_L_C": T_hot_L,
            "T_cold_U_HEN_C": T_cold_U_HEN,
            "T_cold_L_HEN_C": T_cold_L_HEN,
            "T_cold_U_reale_C": T_cold_U,
            "T_cold_L_reale_C": T_cold_L,
            "delta_T_1_K": delta_T_1,
            "delta_T_2_K": delta_T_2,
            "delta_T_ML_K": DT_ML,
            "coeff_area_m2_per_kW": coeff,
        }
    return {
        "h_H": h_H,
        "h_C": h_C,
        "delta_T_ML": delta_T_ML,
        "coeff_area": coeff_area,
        "dettagli": dettagli,
    }

def aggiungi_variabili_tecnologie_HEN(
    modello_bilanci, insiemi_HEN, indici_q, tecnologie_HEN, insiemi_BAR05=None
):
    """Aggiunge A/U aggregate o Ahat/Uhat individuali per i match in B."""
    mdl = modello_bilanci["modello"]
    T = tecnologie_HEN["T"]
    P_t = tecnologie_HEN["P_t"]
    coppie_zona = {(z, i, j) for z, i, m, j, n in indici_q}
    B = set() if insiemi_BAR05 is None else insiemi_BAR05.get("B", set())
    indici_A_U = []
    indici_Ahat_Uhat = []
    for z, i, j in sorted(coppie_zona):
        for t in T:
            if (i, j) not in P_t[t]:
                continue
            if (i, j) in B:
                for k in range(1, insiemi_BAR05["Emax"][i, j] + 1):
                    indici_Ahat_Uhat.append((z, i, j, k, t))
            else:
                indici_A_U.append((z, i, j, t))
    A = mdl.continuous_var_dict(indici_A_U, lb=0, name="A")
    U = mdl.integer_var_dict(indici_A_U, lb=0, name="U")
    Ahat = mdl.continuous_var_dict(indici_Ahat_Uhat, lb=0, name="Ahat")
    Uhat = mdl.integer_var_dict(indici_Ahat_Uhat, lb=0, name="Uhat")
    What = mdl.binary_var_dict(indici_Ahat_Uhat, name="What")
    modello_bilanci["indici_A_U"] = indici_A_U
    modello_bilanci["indici_Ahat_Uhat"] = indici_Ahat_Uhat
    modello_bilanci["A"] = A
    modello_bilanci["U"] = U
    modello_bilanci["Ahat"] = Ahat
    modello_bilanci["Uhat"] = Uhat
    modello_bilanci["What"] = What
    modello_bilanci["tecnologie_HEN"] = tecnologie_HEN
    return modello_bilanci

def aggiungi_vincoli_area_HEN(
    modello_HEN,
    indici_q,
    parametri_area,
    tecnologie_HEN,
    insiemi_BAR05=None,
    delta_H_HEN=None,
):
    """Aggiunge area/capacita ECOS e la separazione BAR05 (97)-(104) per B."""
    mdl = modello_HEN["modello"]
    q = modello_HEN["q"]
    A = modello_HEN["A"]
    U = modello_HEN["U"]
    indici_A_U = modello_HEN["indici_A_U"]
    Ahat = modello_HEN.get("Ahat", {})
    Uhat = modello_HEN.get("Uhat", {})
    indici_Ahat_Uhat = modello_HEN.get("indici_Ahat_Uhat", [])
    coeff_area = parametri_area["coeff_area"]
    tecnologie = tecnologie_HEN["tecnologie"]
    B = set() if insiemi_BAR05 is None else insiemi_BAR05.get("B", set())
    mancanti = [indice for indice in indici_q if indice not in coeff_area]
    if mancanti:
        raise KeyError(
            f"Mancano coefficienti area per alcuni indici q. Primo indice mancante: {mancanti[0]}"
        )
    q_match = {}
    for indice in indici_q:
        z, i, m, j, n = indice
        chiave_match = (z, i, j)
        q_match.setdefault(chiave_match, []).append(indice)
    tecnologie_match = {}
    for indice in indici_A_U:
        z, i, j, t = indice
        chiave_match = (z, i, j)
        tecnologie_match.setdefault(chiave_match, []).append(indice)
    vincoli_equazione_area = []
    vincoli_Amax = []
    for chiave_match in sorted(q_match):
        z, i, j = chiave_match
        if (i, j) in B:
            continue
        indici_tecnologie = tecnologie_match.get(chiave_match, [])
        if not indici_tecnologie:
            raise ValueError(
                f"Il match {chiave_match} possiede variabili q ma nessuna tecnologia HEX disponibile."
            )
        area_equivalente = mdl.sum(
            (coeff_area[indice] * q[indice] for indice in q_match[chiave_match])
        )
        area_tecnologie = mdl.sum(
            (
                A[indice_A] * tecnologie[indice_A[3]].FHEX
                for indice_A in indici_tecnologie
            )
        )
        vincolo = mdl.add_constraint(
            area_tecnologie == area_equivalente, ctname=f"area_z{z}_{i}_{j}"
        )
        vincoli_equazione_area.append(vincolo)
    for indice in indici_A_U:
        z, i, j, t = indice
        tecnologia = tecnologie[t]
        A_max = tecnologia.A_max_m2
        vincolo = mdl.add_constraint(
            A[indice] <= A_max * U[indice], ctname=f"Amax_z{z}_{i}_{j}_{t}"
        )
        vincoli_Amax.append(vincolo)
    modello_HEN["vincoli_area"] = {
        "equazione_area": vincoli_equazione_area,
        "Amax": vincoli_Amax,
    }
    if not B:
        return modello_HEN

    if "qtilde_H" not in modello_HEN or "W_exchanger" not in modello_HEN:
        raise RuntimeError("La formulazione area multipla richiede BAR05 (43)-(56).")
    qtilde_H = modello_HEN["qtilde_H"]
    Ahat, Uhat, What = modello_HEN["Ahat"], modello_HEN["Uhat"], modello_HEN["What"]
    KH, KhatH, YH = modello_HEN["K_H"], modello_HEN["Khat_H"], modello_HEN["Y_H"]
    q_breve_indices = [x for x in indici_q if (x[1], x[3]) in B]
    q_breve = mdl.continuous_var_dict(q_breve_indices, lb=0, name="qbreve")
    G = {}
    Ahat_base = {}
    vincoli_multipli = []
    for z, i, j in sorted(k for k in q_match if (k[1], k[2]) in B):
        massimo = insiemi_BAR05["Emax"][i, j]
        qkeys = q_match[z, i, j]
        hkeys = sorted(
            (k for k in modello_HEN["indici_qhat_H"] if k[:3] == (z, i, j)),
            key=lambda x: x[3],
        )
        area_totale = mdl.sum(coeff_area[x] * q[x] for x in qkeys)
        # Bound numerico conservativo ottenuto dai duty totali e dal massimo
        # coefficiente d'area del match; non modifica dati fisici o costi.
        if delta_H_HEN is None:
            raise RuntimeError("delta_H_HEN richiesto per l'area degli exchanger multipli.")
        duty_M = min(
            sum(v for (zz, ii, _), v in delta_H_HEN["delta_H_H"].items() if zz == z and ii == i),
            sum(v for (zz, jj, _), v in delta_H_HEN["delta_H_C"].items() if zz == z and jj == j),
        )
        if duty_M <= 0:
            raise RuntimeError(f"Duty bound non disponibile per multiple match {(z, i, j)}.")
        area_M = max(coeff_area[x] for x in qkeys) * duty_M * 2
        for hk in hkeys:
            m = hk[3]
            relativi = [x for x in qkeys if x[2] == m]
            vincoli_multipli.append(
                mdl.add_constraint(
                    mdl.sum(q_breve[x] for x in relativi) == qtilde_H[hk],
                    ctname=f"BAR05_101_{z}_{i}_{j}_{m}",
                )
            )
            for x in relativi:
                vincoli_multipli.append(
                    mdl.add_constraint(q_breve[x] <= q[x], ctname=f"BAR05_102_{z}_{i}_{j}_{m}_{x[4]}")
                )
            gs = []
            for k in range(1, massimo + 1):
                g = mdl.binary_var(name=f"G_{z}_{i}_{j}_{k}_{m}")
                G[z, i, j, k, m] = g
                gs.append(g)
            vincoli_multipli.extend(
                [
                    mdl.add_constraint(mdl.sum(gs) == 1, ctname=f"BAR05_G_one_{z}_{i}_{j}_{m}"),
                    mdl.add_constraint(
                        mdl.sum(k * G[z, i, j, k, m] for k in range(1, massimo + 1))
                        == mdl.sum(KH[x] for x in hkeys if x[3] <= m) + 1 - YH[hk],
                        ctname=f"BAR05_100_{z}_{i}_{j}_{m}",
                    ),
                ]
            )
        basi = []
        for k in range(1, massimo + 1):
            base = mdl.continuous_var(lb=0, ub=area_M, name=f"Ahat_base_{z}_{i}_{j}_{k}")
            Ahat_base[z, i, j, k] = base
            basi.append(base)
            precedenti = mdl.sum(Ahat_base[z, i, j, h] for h in range(1, k))
            for hk in hkeys:
                m = hk[3]
                area_cumulativa = mdl.sum(
                    coeff_area[x] * (q[x] - q_breve[x]) for x in qkeys if x[2] <= m
                )
                gate = 2 - KhatH[hk] - G[z, i, j, k, m]
                vincoli_multipli.extend(
                    [
                        mdl.add_constraint(base <= area_cumulativa - precedenti + area_M * gate, ctname=f"BAR05_97_{z}_{i}_{j}_{k}_{m}"),
                        mdl.add_constraint(base >= area_cumulativa - precedenti - area_M * gate, ctname=f"BAR05_98_{z}_{i}_{j}_{k}_{m}"),
                    ]
                )
            w_unit = modello_HEN["W_exchanger"][z, i, j, k]
            indici_tech = [x for x in modello_HEN["indici_Ahat_Uhat"] if x[:4] == (z, i, j, k)]
            vincoli_multipli.append(
                mdl.add_constraint(mdl.sum(What[x] for x in indici_tech) == w_unit, ctname=f"ECOS_multi_tech_{z}_{i}_{j}_{k}")
            )
            vincoli_multipli.append(
                mdl.add_constraint(
                    mdl.sum(tecnologie[x[4]].FHEX * Ahat[x] for x in indici_tech) == base,
                    ctname=f"ECOS_multi_area_{z}_{i}_{j}_{k}",
                )
            )
            for x in indici_tech:
                tech = tecnologie[x[4]]
                max_shell = max(1, math.ceil(area_M / (tech.FHEX * tech.A_max_m2)) + 1)
                vincoli_multipli.extend(
                    [
                        mdl.add_constraint(Ahat[x] <= tech.A_max_m2 * Uhat[x], ctname=f"BAR05_104_{z}_{i}_{j}_{k}_{x[4]}"),
                        mdl.add_constraint(Uhat[x] >= What[x], ctname=f"ECOS_multi_shell_L_{z}_{i}_{j}_{k}_{x[4]}"),
                        mdl.add_constraint(Uhat[x] <= max_shell * What[x], ctname=f"ECOS_multi_shell_U_{z}_{i}_{j}_{k}_{x[4]}"),
                    ]
                )
        vincoli_multipli.extend(
            [
                mdl.add_constraint(mdl.sum(basi) == area_totale, ctname=f"BAR05_99_total_{z}_{i}_{j}"),
                *[
                    mdl.add_constraint(Ahat_base[z, i, j, k] <= area_M * modello_HEN["W_exchanger"][z, i, j, k], ctname=f"BAR05_Aexist_{z}_{i}_{j}_{k}")
                    for k in range(1, massimo + 1)
                ],
            ]
        )
    modello_HEN.update(
        {
            "q_breve": q_breve,
            "G_BAR05": G,
            "Ahat_base": Ahat_base,
            "vincoli_BAR05_97_104": vincoli_multipli,
        }
    )
    return modello_HEN

def aggiungi_obiettivo_TAC_HEN(modello_HEN, utilities_HEN, tecnologie_HEN):
    """Minimizza il costo annuale di utility, unita e area secondo [1.47]."""
    mdl = modello_HEN["modello"]
    Q_HU = modello_HEN["Q_HU"]
    Q_CU = modello_HEN["Q_CU"]
    A = modello_HEN["A"]
    U = modello_HEN["U"]
    indici_A_U = modello_HEN["indici_A_U"]
    Ahat = modello_HEN.get("Ahat", {})
    Uhat = modello_HEN.get("Uhat", {})
    indici_Ahat_Uhat = modello_HEN.get("indici_Ahat_Uhat", [])
    tecnologie = tecnologie_HEN["tecnologie"]
    hot_utilities = {utility.codice: utility for utility in utilities_HEN["hot"]}
    cold_utilities = {utility.codice: utility for utility in utilities_HEN["cold"]}
    for codice in Q_HU:
        if codice not in hot_utilities:
            raise KeyError(
                f"Hot utility {codice} presente nel modello ma non in utilities_HEN."
            )
        utility = hot_utilities[codice]
        if utility.costo_USD_per_kW_year is None:
            raise ValueError(f"Costo non definito per hot utility {codice}.")
        if utility.costo_USD_per_kW_year < 0:
            raise ValueError(f"Costo negativo per hot utility {codice}.")
    for codice in Q_CU:
        if codice not in cold_utilities:
            raise KeyError(
                f"Cold utility {codice} presente nel modello ma non in utilities_HEN."
            )
        utility = cold_utilities[codice]
        if utility.costo_USD_per_kW_year is None:
            raise ValueError(f"Costo non definito per cold utility {codice}.")
        if utility.costo_USD_per_kW_year < 0:
            raise ValueError(f"Costo negativo per cold utility {codice}.")
    costo_hot_utility = mdl.sum(
        (hot_utilities[codice].costo_USD_per_kW_year * Q_HU[codice] for codice in Q_HU)
    )
    costo_cold_utility = mdl.sum(
        (cold_utilities[codice].costo_USD_per_kW_year * Q_CU[codice] for codice in Q_CU)
    )
    costo_fisso_HEX = mdl.sum(
        (
            tecnologie[t].costo_fisso_USD_per_year * U[z, i, j, t]
            for z, i, j, t in indici_A_U
        )
    ) + mdl.sum(
        tecnologie[t].costo_fisso_USD_per_year * Uhat[z, i, j, k, t]
        for z, i, j, k, t in indici_Ahat_Uhat
    )
    costo_area_HEX = mdl.sum(
        (
            tecnologie[t].costo_area_USD_per_m2_year * A[z, i, j, t]
            for z, i, j, t in indici_A_U
        )
    ) + mdl.sum(
        tecnologie[t].costo_area_USD_per_m2_year * Ahat[z, i, j, k, t]
        for z, i, j, k, t in indici_Ahat_Uhat
    )
    TAC = costo_hot_utility + costo_cold_utility + costo_fisso_HEX + costo_area_HEX
    mdl.minimize(TAC)
    modello_HEN["costo_hot_utility"] = costo_hot_utility
    modello_HEN["costo_cold_utility"] = costo_cold_utility
    modello_HEN["costo_fisso_HEX"] = costo_fisso_HEX
    modello_HEN["costo_area_HEX"] = costo_area_HEX
    modello_HEN["TAC"] = TAC
    return modello_HEN

#adaattamento per equazioni avanzate
# 5. MODELLO BAR05

def aggiungi_flussi_cumulativi_BAR05_HEN(
    modello_HEN, insiemi_HEN, indici_q, insiemi_BAR05
):
    """Aggiunge qhat hot/cold e le identita BAR05 (5)-(6)."""
    del insiemi_HEN, insiemi_BAR05
    mdl = modello_HEN["modello"]
    q = modello_HEN["q"]
    gruppi_H = {}
    gruppi_C = {}
    for indice in indici_q:
        z, i, m, j, n = indice
        gruppi_H.setdefault((z, i, j, m), []).append(indice)
        gruppi_C.setdefault((z, i, j, n), []).append(indice)
    indici_H = sorted(gruppi_H)
    indici_C = sorted(gruppi_C)
    qhat_H = mdl.continuous_var_dict(indici_H, lb=0, name="qhat_H")
    qhat_C = mdl.continuous_var_dict(indici_C, lb=0, name="qhat_C")
    vincoli_5 = [
        mdl.add_constraint(
            qhat_H[k] == mdl.sum(q[indice] for indice in gruppi_H[k]),
            ctname=f"BAR05_5_z{k[0]}_{k[1]}_{k[2]}_m{k[3]}",
        )
        for k in indici_H
    ]
    vincoli_6 = [
        mdl.add_constraint(
            qhat_C[k] == mdl.sum(q[indice] for indice in gruppi_C[k]),
            ctname=f"BAR05_6_z{k[0]}_{k[1]}_{k[2]}_n{k[3]}",
        )
        for k in indici_C
    ]
    modello_HEN.update(
        {
            "qhat_H": qhat_H,
            "qhat_C": qhat_C,
            "indici_qhat_H": indici_H,
            "indici_qhat_C": indici_C,
            "gruppi_qhat_H": gruppi_H,
            "gruppi_qhat_C": gruppi_C,
            "vincoli_BAR05_5_6": vincoli_5 + vincoli_6,
        }
    )
    return modello_HEN

def aggiungi_struttura_scambiatori_BAR05_HEN(
    modello_HEN,
    insiemi_HEN,
    insiemi_BAR05,
    delta_H_HEN,
    parametri_utility_BAR05,
    blocchi,
    qL=1e-6,
):
    """Aggiunge BAR05 (11)-(42), incluse le definizioni cumulative per B.

    Nel corrigendum (13)-(14), F_i^U e F_j^U sono parametri costanti. Il
    prodotto F_U * Y * delta_T_interval e pertanto lineare. Le utility
    virtuali delle flexible streams conservano il bound specifico preesistente
    e non sono trattate come utility fisiche BAR05.
    """
    if not blocchi:
        return modello_HEN
    mdl = modello_HEN["modello"]
    qhat_H = modello_HEN["qhat_H"]
    qhat_C = modello_HEN["qhat_C"]
    indici_H = modello_HEN["indici_qhat_H"]
    indici_C = modello_HEN["indici_qhat_C"]
    B = insiemi_BAR05["B"]
    Emax = insiemi_BAR05["Emax"]

    def crea_Y(indici, nome):
        return {
            k: (
                mdl.continuous_var(lb=0, ub=Emax[k[1], k[2]], name=f"{nome}_{k[0]}_{k[1]}_{k[2]}_{k[3]}")
                if (k[1], k[2]) in B
                else mdl.binary_var(name=f"{nome}_{k[0]}_{k[1]}_{k[2]}_{k[3]}")
            )
            for k in indici
        }

    Y_H = crea_Y(indici_H, "Y_H")
    Y_C = crea_Y(indici_C, "Y_C")
    F_U_hot = parametri_utility_BAR05["F_U_hot"]
    F_U_cold = parametri_utility_BAR05["F_U_cold"]
    T_intervallo = insiemi_HEN["T_intervallo"]
    VHU = insiemi_HEN.get("VHU", {})
    VCU = insiemi_HEN.get("VCU", {})

    # Le utility virtuali descrivono la surplus part delle flexible streams e
    # non sono utility fisiche del corrigendum. Mantengono il bound globale
    # preesistente, separato e documentato, per non cambiarne il comportamento.
    bound_virtual_hot_duty = sum(delta_H_HEN["delta_H_C"].values())
    bound_virtual_cold_duty = sum(delta_H_HEN["delta_H_H"].values())
    vincoli_A = []
    limiti_H = {}
    limiti_C = {}
    for k in indici_H:
        z, i, j, m = k
        delta_T_intervallo = (
            T_intervallo[z, m]["T_sup"] - T_intervallo[z, m]["T_inf"]
        )
        if i not in insiemi_HEN["HU"][z]:
            ub = delta_H_HEN["delta_H_H"][z, i, m]
            equazione = 11
            tipo_limite = "process_hot"
        elif i in F_U_hot:
            ub = F_U_hot[i] * delta_T_intervallo
            equazione = 13
            tipo_limite = "physical_hot_utility"
        elif i in VHU.get(z, []):
            ub = bound_virtual_hot_duty
            equazione = None
            tipo_limite = "virtual_hot_utility"
        else:
            raise KeyError(f"F_U hot mancante per l'utility fisica {i}.")
        prefisso = f"BAR05_{equazione}" if equazione is not None else "BAR05_VHU"
        vincoli_A.extend(
            [
                mdl.add_constraint(
                    qhat_H[k] >= qL * Y_H[k],
                    ctname=f"{prefisso}L_{z}_{i}_{j}_{m}",
                ),
                mdl.add_constraint(
                    qhat_H[k] <= ub * Y_H[k],
                    ctname=f"{prefisso}U_{z}_{i}_{j}_{m}",
                ),
            ]
        )
        limiti_H[k] = {
            "equazione": equazione,
            "tipo": tipo_limite,
            "coefficiente_upper_kW": ub,
            "delta_T_intervallo_K": delta_T_intervallo,
            "F_U_kW_K": F_U_hot.get(i),
            "nome_lower": f"{prefisso}L_{z}_{i}_{j}_{m}",
            "nome_upper": f"{prefisso}U_{z}_{i}_{j}_{m}",
        }
    for k in indici_C:
        z, i, j, n = k
        delta_T_intervallo = (
            T_intervallo[z, n]["T_sup"] - T_intervallo[z, n]["T_inf"]
        )
        if j not in insiemi_HEN["CU"][z]:
            ub = delta_H_HEN["delta_H_C"][z, j, n]
            equazione = 12
            tipo_limite = "process_cold"
        elif j in F_U_cold:
            ub = F_U_cold[j] * delta_T_intervallo
            equazione = 14
            tipo_limite = "physical_cold_utility"
        elif j in VCU.get(z, []):
            ub = bound_virtual_cold_duty
            equazione = None
            tipo_limite = "virtual_cold_utility"
        else:
            raise KeyError(f"F_U cold mancante per l'utility fisica {j}.")
        prefisso = f"BAR05_{equazione}" if equazione is not None else "BAR05_VCU"
        vincoli_A.extend(
            [
                mdl.add_constraint(
                    qhat_C[k] >= qL * Y_C[k],
                    ctname=f"{prefisso}L_{z}_{i}_{j}_{n}",
                ),
                mdl.add_constraint(
                    qhat_C[k] <= ub * Y_C[k],
                    ctname=f"{prefisso}U_{z}_{i}_{j}_{n}",
                ),
            ]
        )
        limiti_C[k] = {
            "equazione": equazione,
            "tipo": tipo_limite,
            "coefficiente_upper_kW": ub,
            "delta_T_intervallo_K": delta_T_intervallo,
            "F_U_kW_K": F_U_cold.get(j),
            "nome_lower": f"{prefisso}L_{z}_{i}_{j}_{n}",
            "nome_upper": f"{prefisso}U_{z}_{i}_{j}_{n}",
        }
    modello_HEN.update(
        {
            "Y_H": Y_H,
            "Y_C": Y_C,
            "qL_BAR05": qL,
            "vincoli_BAR05_11_14": vincoli_A,
            "limiti_qhat_BAR05_H": limiti_H,
            "limiti_qhat_BAR05_C": limiti_C,
            "parametri_utility_BAR05": parametri_utility_BAR05,
        }
    )

    if "3B" not in blocchi:
        return modello_HEN
    def crea_K(indici, nome):
        return {
            k: (
                mdl.binary_var(name=f"{nome}_{k[0]}_{k[1]}_{k[2]}_{k[3]}")
                if (k[1], k[2]) in B
                else mdl.continuous_var(lb=0, ub=1, name=f"{nome}_{k[0]}_{k[1]}_{k[2]}_{k[3]}")
            )
            for k in indici
        }

    K_H = crea_K(indici_H, "K_H")
    Khat_H = crea_K(indici_H, "Khat_H")
    set_H = set(indici_H)
    vincoli_B = []
    for k in indici_H:
        z, i, j, m = k
        if (i, j) in B:
            hkeys = sorted(
                (x for x in indici_H if x[:3] == (z, i, j)), key=lambda x: x[3]
            )
            vincoli_B.append(
                mdl.add_constraint(
                    Y_H[k]
                    == mdl.sum(K_H[x] for x in hkeys if x[3] <= m)
                    - mdl.sum(Khat_H[x] for x in hkeys if x[3] < m),
                    ctname=f"BAR05_25_{z}_{i}_{j}_{m}",
                )
            )
            continue
        precedente = (z, i, j, m - 1)
        successivo = (z, i, j, m + 1)
        if precedente in set_H:
            vincoli_B.extend(
                [
                    mdl.add_constraint(K_H[k] <= 2 - Y_H[k] - Y_H[precedente], ctname=f"BAR05_16_{z}_{i}_{j}_{m}"),
                    mdl.add_constraint(K_H[k] <= Y_H[k], ctname=f"BAR05_17_{z}_{i}_{j}_{m}"),
                    mdl.add_constraint(K_H[k] >= Y_H[k] - Y_H[precedente], ctname=f"BAR05_18_{z}_{i}_{j}_{m}"),
                ]
            )
        else:
            vincoli_B.append(mdl.add_constraint(K_H[k] == Y_H[k], ctname=f"BAR05_15_17_{z}_{i}_{j}_{m}"))
        if successivo in set_H:
            vincoli_B.extend(
                [
                    mdl.add_constraint(Khat_H[k] <= 2 - Y_H[k] - Y_H[successivo], ctname=f"BAR05_21_{z}_{i}_{j}_{m}"),
                    mdl.add_constraint(Khat_H[k] <= Y_H[k], ctname=f"BAR05_22_{z}_{i}_{j}_{m}"),
                    mdl.add_constraint(Khat_H[k] >= Y_H[k] - Y_H[successivo], ctname=f"BAR05_23_{z}_{i}_{j}_{m}"),
                ]
            )
        else:
            vincoli_B.append(mdl.add_constraint(Khat_H[k] == Y_H[k], ctname=f"BAR05_20_22_{z}_{i}_{j}_{m}"))
    modello_HEN.update({"K_H": K_H, "Khat_H": Khat_H, "vincoli_BAR05_15_24": vincoli_B})

    if "3C" not in blocchi:
        return modello_HEN
    K_C = crea_K(indici_C, "K_C")
    Khat_C = crea_K(indici_C, "Khat_C")
    set_C = set(indici_C)
    vincoli_C = []
    for k in indici_C:
        z, i, j, n = k
        if (i, j) in B:
            ckeys = sorted(
                (x for x in indici_C if x[:3] == (z, i, j)), key=lambda x: x[3]
            )
            vincoli_C.append(
                mdl.add_constraint(
                    Y_C[k]
                    == mdl.sum(K_C[x] for x in ckeys if x[3] <= n)
                    - mdl.sum(Khat_C[x] for x in ckeys if x[3] < n),
                    ctname=f"BAR05_36_{z}_{i}_{j}_{n}",
                )
            )
            continue
        precedente = (z, i, j, n - 1)
        successivo = (z, i, j, n + 1)
        if precedente in set_C:
            vincoli_C.extend(
                [
                    mdl.add_constraint(K_C[k] <= 2 - Y_C[k] - Y_C[precedente], ctname=f"BAR05_27_{z}_{i}_{j}_{n}"),
                    mdl.add_constraint(K_C[k] <= Y_C[k], ctname=f"BAR05_28_{z}_{i}_{j}_{n}"),
                    mdl.add_constraint(K_C[k] >= Y_C[k] - Y_C[precedente], ctname=f"BAR05_29_{z}_{i}_{j}_{n}"),
                ]
            )
        else:
            vincoli_C.append(mdl.add_constraint(K_C[k] == Y_C[k], ctname=f"BAR05_26_28_{z}_{i}_{j}_{n}"))
        if successivo in set_C:
            vincoli_C.extend(
                [
                    mdl.add_constraint(Khat_C[k] <= 2 - Y_C[k] - Y_C[successivo], ctname=f"BAR05_32_{z}_{i}_{j}_{n}"),
                    mdl.add_constraint(Khat_C[k] <= Y_C[k], ctname=f"BAR05_33_{z}_{i}_{j}_{n}"),
                    mdl.add_constraint(Khat_C[k] >= Y_C[k] - Y_C[successivo], ctname=f"BAR05_34_{z}_{i}_{j}_{n}"),
                ]
            )
        else:
            vincoli_C.append(mdl.add_constraint(Khat_C[k] == Y_C[k], ctname=f"BAR05_31_33_{z}_{i}_{j}_{n}"))
    modello_HEN.update({"K_C": K_C, "Khat_C": Khat_C, "vincoli_BAR05_26_35": vincoli_C})

    if "3D" not in blocchi:
        return modello_HEN
    matches = sorted({(z, i, j) for z, i, j, _ in indici_H})
    E = {
        match: mdl.integer_var(
            lb=0,
            ub=(Emax[match[1], match[2]] if (match[1], match[2]) in B else 1),
            name=f"E_{match[0]}_{match[1]}_{match[2]}",
        )
        for match in matches
    }
    sequenze_H = _sequenze_match_BAR05(indici_H, 3)
    sequenze_C = _sequenze_match_BAR05(indici_C, 3)
    vincoli_D = []
    for match in matches:
        z, i, j = match

        hkeys = [(z, i, j, m) for m in sequenze_H.get(match, [])]
        ckeys = [(z, i, j, n) for n in sequenze_C.get(match, [])]

        vincoli_D.extend(
            [
                mdl.add_constraint(
                    E[match] == mdl.sum(K_H[k] for k in hkeys),
                    ctname=f"BAR05_37_{z}_{i}_{j}",
                ),
                mdl.add_constraint(
                    E[match] == mdl.sum(K_C[k] for k in ckeys),
                    ctname=f"BAR05_38_{z}_{i}_{j}",
                ),
                mdl.add_constraint(
                    E[match] == mdl.sum(Khat_H[k] for k in hkeys),
                    ctname=f"BAR05_39_{z}_{i}_{j}",
                ),
                mdl.add_constraint(
                    E[match] == mdl.sum(Khat_C[k] for k in ckeys),
                    ctname=f"BAR05_40_{z}_{i}_{j}",
                ),
            ]
        )
        limite = Emax[i, j] if (i, j) in B else 1
        numero_eq = 42 if (i, j) in B else 41
        vincoli_D.append(
            mdl.add_constraint(
                E[match] <= limite,
                ctname=f"BAR05_{numero_eq}_{z}_{i}_{j}",
            )
        )
    modello_HEN.update({"E": E, "vincoli_BAR05_37_42": vincoli_D})
    return modello_HEN

def aggiungi_consistenza_portate_BAR05_HEN(
    modello_HEN, insiemi_HEN, insiemi_BAR05, delta_H_HEN, blocchi
):
    """Aggiunge alpha e la flow-rate consistency BAR05 per B vuoto.

    Nel progetto delta_H = F*Cp*delta_T e CP e costante. Quindi
    qhat/delta_H = (F_ramo*Cp*delta_T)/(F*Cp*delta_T) = F_ramo/F.
    I rapporti sono tutti rispetto a parametri numerici: la trasformazione e
    lineare e non introduce divisioni per variabili DOcplex.
    """
    if "4A" not in blocchi:
        return modello_HEN
    mdl = modello_HEN["modello"]
    qhat_H = modello_HEN["qhat_H"]
    qhat_C = modello_HEN["qhat_C"]
    Y_H, Y_C = modello_HEN["Y_H"], modello_HEN["Y_C"]
    K_H, Khat_H = modello_HEN["K_H"], modello_HEN["Khat_H"]
    K_C, Khat_C = modello_HEN["K_C"], modello_HEN["Khat_C"]
    set_H = set(modello_HEN["indici_qhat_H"])
    set_C = set(modello_HEN["indici_qhat_C"])
    coppie_H = [
        k for k in modello_HEN["indici_qhat_H"]
        if k[1] in insiemi_BAR05["SH"][k[0]] and (k[0], k[1], k[2], k[3] - 1) in set_H
    ]
    alpha_H = mdl.continuous_var_dict(coppie_H, lb=0, ub=1, name="alpha_H")
    vincoli_57_60 = []
    for k in coppie_H:
        z, i, j, m = k
        p = (z, i, j, m - 1)
        vincoli_57_60.extend(
            [
                mdl.add_constraint(alpha_H[k] <= 1 - K_H[k] - K_H[p], ctname=f"BAR05_57_{z}_{i}_{j}_{m}"),
                mdl.add_constraint(alpha_H[k] <= 1 - Khat_H[k] - Khat_H[p], ctname=f"BAR05_58_{z}_{i}_{j}_{m}"),
                mdl.add_constraint(alpha_H[k] >= Y_H[k] - K_H[k] - K_H[p] - Khat_H[k] - Khat_H[p], ctname=f"BAR05_59_{z}_{i}_{j}_{m}"),
            ]
        )
    modello_HEN.update({"alpha_H": alpha_H, "vincoli_BAR05_57_60": vincoli_57_60})

    if "4B" not in blocchi:
        return modello_HEN
    coppie_C = [
        k for k in modello_HEN["indici_qhat_C"]
        if k[2] in insiemi_BAR05["SC"][k[0]] and (k[0], k[1], k[2], k[3] - 1) in set_C
    ]
    alpha_C = mdl.continuous_var_dict(coppie_C, lb=0, ub=1, name="alpha_C")
    vincoli_69_72 = []
    for k in coppie_C:
        z, i, j, n = k
        p = (z, i, j, n - 1)
        vincoli_69_72.extend(
            [
                mdl.add_constraint(alpha_C[k] <= 1 - K_C[k] - K_C[p], ctname=f"BAR05_69_{z}_{i}_{j}_{n}"),
                mdl.add_constraint(alpha_C[k] <= 1 - Khat_C[k] - Khat_C[p], ctname=f"BAR05_70_{z}_{i}_{j}_{n}"),
                mdl.add_constraint(alpha_C[k] >= Y_C[k] - K_C[k] - K_C[p] - Khat_C[k] - Khat_C[p], ctname=f"BAR05_71_{z}_{i}_{j}_{n}"),
            ]
        )
    modello_HEN.update({"alpha_C": alpha_C, "vincoli_BAR05_69_72": vincoli_69_72})

    def rH(k):
        z, i, j, m = k
        return qhat_H[k] / delta_H_HEN["delta_H_H"][z, i, m]

    def rC(k):
        z, i, j, n = k
        return qhat_C[k] / delta_H_HEN["delta_H_C"][z, j, n]

    if "4C" in blocchi:
        vincoli = []
        for k in coppie_H:
            z, i, j, m = k
            p = (z, i, j, m - 1)
            vincoli.extend(
                [
                    mdl.add_constraint(rH(k) <= rH(p) + 1 - alpha_H[k], ctname=f"BAR05_61_{z}_{i}_{j}_{m}"),
                    mdl.add_constraint(rH(k) >= rH(p) - 1 + alpha_H[k], ctname=f"BAR05_62_{z}_{i}_{j}_{m}"),
                ]
            )
        modello_HEN["vincoli_BAR05_61_62"] = vincoli
    if "4D" in blocchi:
        vincoli = []
        for k in coppie_H:
            z, i, j, m = k
            if (i, j) in insiemi_BAR05["B"]:
                continue
            p = (z, i, j, m - 1)
            vincoli.extend(
                [
                    mdl.add_constraint(rH(k) >= rH(p) - (1 + Khat_H[p] + Khat_H[k] - K_H[p]), ctname=f"BAR05_63_{z}_{i}_{j}_{m}"),
                    mdl.add_constraint(rH(k) <= rH(p) + (1 + K_H[p] + K_H[k] - Khat_H[k]), ctname=f"BAR05_64_{z}_{i}_{j}_{m}"),
                ]
            )
        if insiemi_BAR05["B"] and "qtilde_H" in modello_HEN:
            qtilde_H = modello_HEN["qtilde_H"]
            for k in coppie_H:
                z, i, j, m = k
                if (i, j) not in insiemi_BAR05["B"]:
                    continue
                p = (z, i, j, m - 1)
                vincoli.extend(
                    [
                        mdl.add_constraint(rH(k) >= rH(p) - (1 + Khat_H[p] + Khat_H[k] - K_H[p]), ctname=f"BAR05_65_{z}_{i}_{j}_{m}"),
                        mdl.add_constraint(rH(k) >= qtilde_H[p] / delta_H_HEN["delta_H_H"][z, i, m - 1] - (2 + Khat_H[k] - K_H[p] - Y_H[p]), ctname=f"BAR05_66_{z}_{i}_{j}_{m}"),
                        mdl.add_constraint((qhat_H[k] - qtilde_H[k]) / delta_H_HEN["delta_H_H"][z, i, m] <= rH(p) + (2 + K_H[p] - Khat_H[k] - Y_H[k]), ctname=f"BAR05_67_{z}_{i}_{j}_{m}"),
                    ]
                )
        modello_HEN["vincoli_BAR05_63_67"] = vincoli
    if "4E" in blocchi:
        vincoli = []
        for k in coppie_C:
            z, i, j, n = k
            p = (z, i, j, n - 1)
            vincoli.extend(
                [
                    mdl.add_constraint(rC(k) <= rC(p) + 1 - alpha_C[k], ctname=f"BAR05_73_{z}_{i}_{j}_{n}"),
                    mdl.add_constraint(rC(k) >= rC(p) - 1 + alpha_C[k], ctname=f"BAR05_74_{z}_{i}_{j}_{n}"),
                ]
            )
        modello_HEN["vincoli_BAR05_73_74"] = vincoli
    if "4F" in blocchi:
        vincoli = []
        for k in coppie_C:
            z, i, j, n = k
            if (i, j) in insiemi_BAR05["B"]:
                continue
            p = (z, i, j, n - 1)
            vincoli.extend(
                [
                    mdl.add_constraint(rC(k) >= rC(p) - (1 + Khat_C[p] + Khat_C[k] - K_C[p]), ctname=f"BAR05_75_{z}_{i}_{j}_{n}"),
                    mdl.add_constraint(rC(k) <= rC(p) + (1 + K_C[p] + K_C[k] - Khat_C[k]), ctname=f"BAR05_76_{z}_{i}_{j}_{n}"),
                ]
            )
        if insiemi_BAR05["B"] and "qtilde_C" in modello_HEN:
            qtilde_C = modello_HEN["qtilde_C"]
            for k in coppie_C:
                z, i, j, n = k
                if (i, j) not in insiemi_BAR05["B"]:
                    continue
                p = (z, i, j, n - 1)
                vincoli.extend(
                    [
                        mdl.add_constraint(rC(k) >= rC(p) - (1 + Khat_C[p] + Khat_C[k] - K_C[p]), ctname=f"BAR05_77_{z}_{i}_{j}_{n}"),
                        mdl.add_constraint(rC(k) >= qtilde_C[p] / delta_H_HEN["delta_H_C"][z, j, n - 1] - (2 + Khat_C[k] - K_C[p] - Y_C[p]), ctname=f"BAR05_78_{z}_{i}_{j}_{n}"),
                        mdl.add_constraint((qhat_C[k] - qtilde_C[k]) / delta_H_HEN["delta_H_C"][z, j, n] <= rC(p) + (2 + K_C[p] - Khat_C[k] - Y_C[k]), ctname=f"BAR05_79_{z}_{i}_{j}_{n}"),
                    ]
                )
        modello_HEN["vincoli_BAR05_75_79"] = vincoli
    return modello_HEN

def aggiungi_scambiatori_multipli_BAR05_HEN(
    modello_HEN, insiemi_HEN, insiemi_BAR05, delta_H_HEN
):
    """Aggiunge BAR05 (43)-(56) per le coppie configurate nell'insieme B.

    ``qtilde`` separa il carico quando la fine di un exchanger e l'inizio del
    successivo ricadono nello stesso intervallo. ``X`` rende attiva
    l'uguaglianza dei carichi cumulativi soltanto alla coppia di estremi
    corrispondente. Il corrigendum e usato per (44) e (48).
    """
    B = insiemi_BAR05["B"]
    if not B:
        modello_HEN.update(
            {"qtilde_H": {}, "qtilde_C": {}, "X_BAR05": {}, "W_exchanger": {}}
        )
        return modello_HEN
    mdl = modello_HEN["modello"]
    qH, qC = modello_HEN["qhat_H"], modello_HEN["qhat_C"]
    KH, KhatH = modello_HEN["K_H"], modello_HEN["Khat_H"]
    KC, KhatC = modello_HEN["K_C"], modello_HEN["Khat_C"]
    indici_H = [k for k in modello_HEN["indici_qhat_H"] if (k[1], k[2]) in B]
    indici_C = [k for k in modello_HEN["indici_qhat_C"] if (k[1], k[2]) in B]
    qtilde_H = mdl.continuous_var_dict(indici_H, lb=0, name="qtilde_H")
    qtilde_C = mdl.continuous_var_dict(indici_C, lb=0, name="qtilde_C")
    T = insiemi_HEN["T_intervallo"]
    coppie_mn = []
    for h in indici_H:
        z, i, j, m = h
        for c in indici_C:
            if c[:3] != h[:3]:
                continue
            n = c[3]
            if T[z, n]["T_inf"] < T[z, m]["T_sup"] - 1e-9:
                coppie_mn.append((z, i, j, m, n))
    X = mdl.continuous_var_dict(coppie_mn, lb=0, name="X_BAR05")
    vincoli = []
    for z, i, j in sorted({k[:3] for k in indici_H}):
        hs = sorted((k for k in indici_H if k[:3] == (z, i, j)), key=lambda k: k[3])
        cs = sorted((k for k in indici_C if k[:3] == (z, i, j)), key=lambda k: k[3])
        M_consistenza = max(
            sum(delta_H_HEN["delta_H_H"].get((z, i, k[3]), 0.0) for k in hs),
            sum(delta_H_HEN["delta_H_C"].get((z, j, k[3]), 0.0) for k in cs),
        )
        for _, _, _, m, n in (x for x in coppie_mn if x[:3] == (z, i, j)):
            hk, ck = (z, i, j, m), (z, i, j, n)
            cum_H = mdl.sum(qH[k] for k in hs if k[3] <= m)
            cum_C = mdl.sum(qC[k] for k in cs if k[3] <= n)
            differenza = cum_H - qtilde_H[hk] - cum_C + qtilde_C[ck]
            vincoli.extend(
                [
                    mdl.add_constraint(differenza <= 4 * M_consistenza * X[z, i, j, m, n], ctname=f"BAR05_43_{z}_{i}_{j}_{m}_{n}"),
                    mdl.add_constraint(differenza >= -4 * M_consistenza * X[z, i, j, m, n], ctname=f"BAR05_44_{z}_{i}_{j}_{m}_{n}"),
                    mdl.add_constraint(
                        X[z, i, j, m, n]
                        == 2
                        - KhatH[hk]
                        - KhatC[ck]
                        + 0.25 * mdl.sum(KhatC[k] for k in cs if k[3] <= n)
                        - 0.25 * mdl.sum(KhatH[k] for k in hs if k[3] <= m),
                        ctname=f"BAR05_45_{z}_{i}_{j}_{m}_{n}",
                    ),
                ]
            )
            if T[z, n]["T_inf"] >= T[z, m]["T_inf"] - 1e-9:
                vincoli.append(
                    mdl.add_constraint(
                        mdl.sum(KhatH[k] for k in hs if k[3] <= m)
                        >= mdl.sum(KhatC[k] for k in cs if k[3] <= n),
                        ctname=f"BAR05_46_{z}_{i}_{j}_{m}_{n}",
                    )
                )
        for k in hs:
            m = k[3]
            vincoli.append(
                mdl.add_constraint(
                    mdl.sum(KH[x] - KhatH[x] for x in hs if x[3] <= m) <= 1,
                    ctname=f"BAR05_47_{z}_{i}_{j}_{m}",
                )
            )
            delta = delta_H_HEN["delta_H_H"].get((z, i, m), M_consistenza)
            vincoli.extend(
                [
                    mdl.add_constraint(qtilde_H[k] <= qH[k], ctname=f"BAR05_49_{z}_{i}_{j}_{m}"),
                    mdl.add_constraint(qtilde_H[k] <= delta * KH[k], ctname=f"BAR05_50_{z}_{i}_{j}_{m}"),
                    mdl.add_constraint(qtilde_H[k] <= delta * KhatH[k], ctname=f"BAR05_51_{z}_{i}_{j}_{m}"),
                ]
            )
        for k in cs:
            n = k[3]
            vincoli.append(
                mdl.add_constraint(
                    mdl.sum(KC[x] - KhatC[x] for x in cs if x[3] <= n) <= 1,
                    ctname=f"BAR05_48_{z}_{i}_{j}_{n}",
                )
            )
            delta = delta_H_HEN["delta_H_C"].get((z, j, n), M_consistenza)
            vincoli.extend(
                [
                    mdl.add_constraint(qtilde_C[k] <= qC[k], ctname=f"BAR05_53_{z}_{i}_{j}_{n}"),
                    mdl.add_constraint(qtilde_C[k] <= delta * KC[k], ctname=f"BAR05_54_{z}_{i}_{j}_{n}"),
                    mdl.add_constraint(qtilde_C[k] <= delta * KhatC[k], ctname=f"BAR05_55_{z}_{i}_{j}_{n}"),
                ]
            )
    W_exchanger = {}
    for z, i, j in sorted({k[:3] for k in indici_H}):
        massimo = insiemi_BAR05["Emax"][i, j]
        ws = []
        for k in range(1, massimo + 1):
            w = mdl.binary_var(name=f"W_exchanger_{z}_{i}_{j}_{k}")
            W_exchanger[z, i, j, k] = w
            ws.append(w)
            if k > 1:
                vincoli.append(
                    mdl.add_constraint(ws[-2] >= ws[-1], ctname=f"BAR05_W_order_{z}_{i}_{j}_{k}")
                )
        vincoli.append(
            mdl.add_constraint(
                modello_HEN["E"][z, i, j] == mdl.sum(ws),
                ctname=f"BAR05_W_count_{z}_{i}_{j}",
            )
        )
    modello_HEN.update(
        {
            "qtilde_H": qtilde_H,
            "qtilde_C": qtilde_C,
            "X_BAR05": X,
            "W_exchanger": W_exchanger,
            "vincoli_BAR05_43_56": vincoli,
        }
    )
    return modello_HEN

def aggiungi_fattibilita_temperature_BAR05_HEN(
    modello_HEN, insiemi_HEN, insiemi_BAR05, delta_H_HEN, blocchi, tolleranza=1e-9
):
    """Aggiunge BAR05 (83)-(88), nella versione corretta del 2006.

    Le Cp dei benchmark sono costanti lungo ogni stream, quindi i rapporti
    Cp_m/Cp_m+1 delle equazioni corrette valgono uno. I delta_H/DeltaT
    rimanenti sono parametri e mantengono il modello lineare.
    """
    if "5A" not in blocchi:
        return modello_HEN
    mdl = modello_HEN["modello"]
    T = insiemi_HEN["T_intervallo"]
    qH, qC = modello_HEN["qhat_H"], modello_HEN["qhat_C"]
    KH, KhatH = modello_HEN["K_H"], modello_HEN["Khat_H"]
    KC, KhatC = modello_HEN["K_C"], modello_HEN["Khat_C"]
    set_H = set(modello_HEN["indici_qhat_H"])
    set_C = set(modello_HEN["indici_qhat_C"])
    matches = sorted({k[:3] for k in set_H} & {k[:3] for k in set_C})

    def dT(z, k):
        return T[z, k]["T_sup"] - T[z, k]["T_inf"]

    vincoli_83_85 = []
    for z, i, j in matches:
        if i not in insiemi_BAR05["SH"][z] or j not in insiemi_BAR05["SC"][z]:
            continue
        if (i, j) in insiemi_BAR05["B"]:
            continue
        ms = sorted(k[3] for k in set_H if k[:3] == (z, i, j))
        ns = sorted(k[3] for k in set_C if k[:3] == (z, i, j))
        for m in ms:
            hm, hp = (z, i, j, m), (z, i, j, m + 1)
            if hp not in set_H:
                continue
            for n in ns:
                cn, cp = (z, i, j, n), (z, i, j, n + 1)
                if cp not in set_C:
                    continue
                TmU, TmL = T[z, m]["T_sup"], T[z, m]["T_inf"]
                TnU, TnL = T[z, n]["T_sup"], T[z, n]["T_inf"]
                if not (TnL < TmU - tolleranza and TnU > TmL + tolleranza):
                    continue
                den_c = TmU - TnL
                den_h = min(TmU, TnU) - TmL
                if den_c <= tolleranza or den_h <= tolleranza:
                    continue
                slack = 2 - KH[hm] - KC[cn]
                vincoli_83_85.extend(
                    [
                        mdl.add_constraint(KhatC[cn] <= slack, ctname=f"BAR05_83_{z}_{i}_{j}_{m}_{n}"),
                        mdl.add_constraint(qC[cn] / den_c <= qC[cp] / dT(z, n + 1) + slack * delta_H_HEN["delta_H_C"][z, j, n] / den_c, ctname=f"BAR05_84_{z}_{i}_{j}_{m}_{n}"),
                        mdl.add_constraint(qH[hm] / den_h >= qH[hp] / dT(z, m + 1) - slack * delta_H_HEN["delta_H_H"][z, i, m + 1] / dT(z, m + 1), ctname=f"BAR05_85_{z}_{i}_{j}_{m}_{n}"),
                    ]
                )
    modello_HEN["vincoli_BAR05_83_85"] = vincoli_83_85
    diagnostica_5B = {eq for eq in ("5B_86", "5B_87", "5B_88") if eq in blocchi}
    if "5B" not in blocchi and not diagnostica_5B:
        return modello_HEN
    vincoli_86_88 = []
    for z, i, j in matches:
        if i not in insiemi_BAR05["SH"][z] or j not in insiemi_BAR05["SC"][z]:
            continue
        if (i, j) in insiemi_BAR05["B"]:
            continue
        ms = sorted(k[3] for k in set_H if k[:3] == (z, i, j))
        ns = sorted(k[3] for k in set_C if k[:3] == (z, i, j))
        for m in ms:
            hm, hp = (z, i, j, m), (z, i, j, m - 1)
            if hp not in set_H:
                continue
            for n in ns:
                cn, cp = (z, i, j, n), (z, i, j, n - 1)
                if cp not in set_C:
                    continue
                TmU, TmL = T[z, m]["T_sup"], T[z, m]["T_inf"]
                TnU, TnL = T[z, n]["T_sup"], T[z, n]["T_inf"]
                if not (TnL < TmU - tolleranza and TnU > TmL + tolleranza):
                    continue
                den_h = TmU - TnL
                den_c = TnU - max(TmL, TnL)
                if den_h <= tolleranza or den_c <= tolleranza:
                    continue
                slack = 2 - KhatH[hm] - KhatC[cn]
                if "5B" in blocchi or "5B_86" in diagnostica_5B:
                    vincoli_86_88.append(
                        mdl.add_constraint(KH[hm] <= slack, ctname=f"BAR05_86_{z}_{i}_{j}_{m}_{n}")
                    )
                if "5B" in blocchi or "5B_87" in diagnostica_5B:
                    vincoli_86_88.append(
                        mdl.add_constraint(qH[hm] / den_h <= qH[hp] / dT(z, m - 1) + slack * delta_H_HEN["delta_H_H"][z, i, m] / den_h, ctname=f"BAR05_87_{z}_{i}_{j}_{m}_{n}")
                    )
                if "5B" in blocchi or "5B_88" in diagnostica_5B:
                    vincoli_86_88.append(
                        mdl.add_constraint(qC[cn] / den_c >= qC[cp] / dT(z, n - 1) - slack * delta_H_HEN["delta_H_C"][z, j, n - 1] / dT(z, n - 1), ctname=f"BAR05_88_{z}_{i}_{j}_{m}_{n}")
                    )
    modello_HEN["vincoli_BAR05_86_88"] = vincoli_86_88

    # Multiple matches: BAR05 (89)-(95), con (92) e (95) dal corrigendum.
    vincoli_89_95 = []
    if insiemi_BAR05["B"] and "qtilde_H" in modello_HEN:
        tH, tC = modello_HEN["qtilde_H"], modello_HEN["qtilde_C"]
        for z, i, j in matches:
            if (i, j) not in insiemi_BAR05["B"]:
                continue
            ms = sorted(k[3] for k in set_H if k[:3] == (z, i, j))
            ns = sorted(k[3] for k in set_C if k[:3] == (z, i, j))
            for m in ms:
                hm, hn = (z, i, j, m), (z, i, j, m + 1)
                if hn not in set_H:
                    continue
                for n in ns:
                    cn, cnn = (z, i, j, n), (z, i, j, n + 1)
                    if cnn not in set_C:
                        continue
                    TmU, TmL = T[z, m]["T_sup"], T[z, m]["T_inf"]
                    TnU, TnL = T[z, n]["T_sup"], T[z, n]["T_inf"]
                    if not (TnL < TmU - tolleranza and TnU > TmL + tolleranza):
                        continue
                    den_c = TmU - TnL
                    den_h = min(TmU, TnU) - TmL
                    if den_c <= tolleranza or den_h <= tolleranza:
                        continue
                    slack_y = 1 + modello_HEN["Y_C"][cn] - KH[hm] - KC[cn]
                    slack = 2 - KH[hm] - KC[cn]
                    vincoli_89_95.extend(
                        [
                            mdl.add_constraint(KhatC[cn] <= slack_y, ctname=f"BAR05_89_{z}_{i}_{j}_{m}_{n}"),
                            mdl.add_constraint(qC[cn] / den_c <= qC[cnn] / dT(z, n + 1) + slack_y * delta_H_HEN["delta_H_C"][z, j, n] / den_c, ctname=f"BAR05_90_{z}_{i}_{j}_{m}_{n}"),
                            mdl.add_constraint(tC[cn] / den_c <= qC[cnn] / dT(z, n + 1) + slack * delta_H_HEN["delta_H_C"][z, j, n] / den_c, ctname=f"BAR05_91_{z}_{i}_{j}_{m}_{n}"),
                            mdl.add_constraint(qH[hm] / den_h >= qH[hn] / dT(z, m + 1) - slack * delta_H_HEN["delta_H_H"][z, i, m + 1] / dT(z, m + 1), ctname=f"BAR05_92_{z}_{i}_{j}_{m}_{n}"),
                        ]
                    )
            if "5B" not in blocchi:
                continue
            for m in ms:
                hm, hp = (z, i, j, m), (z, i, j, m - 1)
                if hp not in set_H:
                    continue
                for n in ns:
                    cn, cp = (z, i, j, n), (z, i, j, n - 1)
                    if cp not in set_C:
                        continue
                    TmU, TmL = T[z, m]["T_sup"], T[z, m]["T_inf"]
                    TnU, TnL = T[z, n]["T_sup"], T[z, n]["T_inf"]
                    if not (TnL < TmU - tolleranza and TnU > TmL + tolleranza):
                        continue
                    den_h = TmU - TnL
                    den_c = TnU - max(TmL, TnL)
                    if den_h <= tolleranza or den_c <= tolleranza:
                        continue
                    slack_y = 1 + modello_HEN["Y_H"][hm] - KhatH[hm] - KhatC[cn]
                    slack = 2 - KhatH[hm] - KhatC[cn]
                    vincoli_89_95.extend(
                        [
                            mdl.add_constraint(KH[hm] <= slack_y, ctname=f"BAR05_93_{z}_{i}_{j}_{m}_{n}"),
                            mdl.add_constraint((qH[hm] - tH[hm]) / den_h <= qH[hp] / dT(z, m - 1) + slack * delta_H_HEN["delta_H_H"][z, i, m] / den_h, ctname=f"BAR05_94_{z}_{i}_{j}_{m}_{n}"),
                            mdl.add_constraint((qC[cn] - tC[cn]) / den_c >= qC[cp] / dT(z, n - 1) - slack * delta_H_HEN["delta_H_C"][z, j, n - 1] / dT(z, n - 1), ctname=f"BAR05_95_{z}_{i}_{j}_{m}_{n}"),
                        ]
                    )
    modello_HEN["vincoli_BAR05_89_95"] = vincoli_89_95
    return modello_HEN

# 6. PREPARA HEN RISOLVI HEN

def prepara_HEN(
    sorgente,
    bar05_blocchi=None,
    bar05_qL=1e-6,
    amax_fisico_m2=None,
    delta_T_partition_max=None,
    numero_intervalli_min=None,
):
    """Coordina una sola volta l intera pipeline HENS senza risolverla.

    Usa due partizioni finite: la prima determina le utility virtuali [1.48]-[1.49],
    la seconda le include nel modello definitivo."""
    dati_pinch = (
    esegui_analisi_pinch(sorgente)
    if isinstance(sorgente, (str, Path))
    else sorgente
    )
    configurazione = dict(dati_pinch["configurazione"])
    if delta_T_partition_max is not None:
        if delta_T_partition_max <= 0:
            raise ValueError("delta_T_partition_max deve essere > 0.")
        configurazione["delta_T_partition_max"] = float(delta_T_partition_max)
    if numero_intervalli_min is not None:
        if numero_intervalli_min < 1:
            raise ValueError("numero_intervalli_min deve essere >= 1.")
        configurazione["numero_intervalli_min"] = int(numero_intervalli_min)
    hens = configurazione.get("hens", {})
    separa_al_pinch = hens.get("separa_al_pinch", True)
    if type(separa_al_pinch) is not bool:
        raise ValueError("'hens.separa_al_pinch' deve essere true oppure false.")
    flussi_flessibili = costruisci_flussi_flessibili_HEN(configurazione)
    utilities_fisiche = costruisci_utilities_HEN(configurazione)
    argomenti_partizione = {
        "gcc": dati_pinch["gcc"],
        "flussi": configurazione ["flussi"],
        "delta_T_min": configurazione["delta_T_min"],
        "pinch_traslati": dati_pinch["pinch_traslati_C"],
        "delta_T_partition_max": configurazione["delta_T_partition_max"],
        "numero_intervalli_min": configurazione["numero_intervalli_min"],
        "separa_al_pinch": separa_al_pinch,
        "flexible_streams": flussi_flessibili,
    }
    partizione_preliminare = crea_partizione_HEN(
        utilities=utilities_fisiche, **argomenti_partizione
    )
    utilities_virtuali = costruisci_utilities_virtuali_HEN(
        intervalli=partizione_preliminare,
        flussi_flessibili=flussi_flessibili,
        flussi=configurazione ["flussi"],
        delta_T_min=configurazione["delta_T_min"],
        delta_T_partition_max=configurazione["delta_T_partition_max"],
    )
    codici_esistenti = {f.codice for f in configurazione ["flussi"]} | {
        u.codice for tipo in ("hot", "cold") for u in utilities_fisiche[tipo]
    }
    collisioni = codici_esistenti & {
        u.codice for tipo in ("hot", "cold") for u in utilities_virtuali[tipo]
    }
    if collisioni:
        raise ValueError(
            f"Codici riservati alle utility virtuali gia usati: {sorted(collisioni)}."
        )
    utilities_HEN = {
        tipo: list(utilities_fisiche[tipo]) + list(utilities_virtuali[tipo])
        for tipo in ("hot", "cold")
    }
    parametri_utility_BAR05 = calcola_F_U_BAR05_HEN(
        configurazione, utilities_HEN
    )
    intervalli_HEN = crea_partizione_HEN(
        utilities=utilities_HEN, **argomenti_partizione
    )
    tecnologie_HEN = costruisci_tecnologie_HEN(configurazione)
    aggiungi_tecnologia_virtuale_HEN(tecnologie_HEN, utilities_HEN, flussi_flessibili)
    if amax_fisico_m2 is not None:
        if amax_fisico_m2 <= 0:
            raise ValueError("amax_fisico_m2 deve essere > 0.")
        for tecnologia in tecnologie_HEN["tecnologie"].values():
            if not tecnologia.virtuale:
                tecnologia.A_max_m2 = float(amax_fisico_m2)
    match_permessi = set().union(*tecnologie_HEN["P_t"].values())
    insiemi_HEN = costruisci_insiemi_HEN(
        flussi=configurazione ["flussi"],
        utilities=utilities_HEN,
        intervalli=intervalli_HEN,
        delta_T_min=configurazione["delta_T_min"],
        match_permessi=match_permessi,
        flexible_streams=flussi_flessibili,
    )
    insiemi_BAR05 = costruisci_insiemi_BAR05_HEN(insiemi_HEN, configurazione)
    indici_q = genera_indici_q_HEN(insiemi_HEN)
    delta_H_HEN = calcola_delta_H_HEN(insiemi_HEN)
    modello_HEN = crea_modello_bilanci_HEN(insiemi_HEN, indici_q, delta_H_HEN)
    blocchi_BAR05 = set() if bar05_blocchi is None else set(bar05_blocchi)
    insiemi_BAR05_attivi = dict(insiemi_BAR05)
    if "7" not in blocchi_BAR05:
        # B resta disponibile nella diagnostica fin dallo STEP 1, ma le sue
        # equazioni diventano attive atomicamente soltanto nello STEP 7.
        insiemi_BAR05_attivi["B"] = set()
        insiemi_BAR05_attivi["Emax"] = {}
    if "2" in blocchi_BAR05:
        aggiungi_flussi_cumulativi_BAR05_HEN(
            modello_HEN, insiemi_HEN, indici_q, insiemi_BAR05
        )
    parametri_area = calcola_parametri_area_HEN(
        insiemi_HEN, indici_q, configurazione["delta_T_min"]
    )
    aggiungi_variabili_tecnologie_HEN(
        modello_HEN,
        insiemi_HEN,
        indici_q,
        tecnologie_HEN,
        insiemi_BAR05=insiemi_BAR05_attivi,
    )
    blocchi_struttura = blocchi_BAR05 & {"3A", "3B", "3C", "3D"}
    if blocchi_struttura:
        aggiungi_struttura_scambiatori_BAR05_HEN(
            modello_HEN,
            insiemi_HEN,
            insiemi_BAR05_attivi,
            delta_H_HEN,
            parametri_utility_BAR05,
            blocchi_struttura,
            qL=bar05_qL,
        )
    if "7" in blocchi_BAR05:
        aggiungi_scambiatori_multipli_BAR05_HEN(
            modello_HEN, insiemi_HEN, insiemi_BAR05_attivi, delta_H_HEN
        )
    if "4A" in blocchi_BAR05:
        aggiungi_consistenza_portate_BAR05_HEN(
            modello_HEN, insiemi_HEN, insiemi_BAR05_attivi, delta_H_HEN, blocchi_BAR05
        )
    if "5A" in blocchi_BAR05:
        aggiungi_fattibilita_temperature_BAR05_HEN(
            modello_HEN, insiemi_HEN, insiemi_BAR05_attivi, delta_H_HEN, blocchi_BAR05
        )
    aggiungi_vincoli_area_HEN(
        modello_HEN,
        indici_q,
        parametri_area,
        tecnologie_HEN,
        insiemi_BAR05=insiemi_BAR05_attivi,
        delta_H_HEN=delta_H_HEN,
    )
    aggiungi_obiettivo_TAC_HEN(modello_HEN, utilities_HEN, tecnologie_HEN)
    return {
        "dati_pinch": dati_pinch,
        "configurazione": configurazione,
        "flussi_flessibili": flussi_flessibili,
        "utilities_HEN": utilities_HEN,
        "parametri_utility_BAR05": parametri_utility_BAR05,
        "intervalli_HEN": intervalli_HEN,
        "insiemi_HEN": insiemi_HEN,
        "insiemi_BAR05": insiemi_BAR05,
        "bar05_blocchi": sorted(blocchi_BAR05),
        "indici_q": indici_q,
        "delta_H_HEN": delta_H_HEN,
        "parametri_area": parametri_area,
        "tecnologie_HEN": tecnologie_HEN,
        "modello_HEN": modello_HEN,
    }

def risolvi_HEN(preparazione, log_output=False, tolleranza=1e-7):
    """Risolve il MILP HENS e ricostruisce risultati strutturati."""

    modello = preparazione["modello_HEN"]
    delta_T_min = preparazione["configurazione"]["delta_T_min"]
    mdl = modello["modello"]
    soluzione = mdl.solve(log_output=log_output)
    if soluzione is None:
        raise RuntimeError(
            f"CPLEX non ha trovato una soluzione: {mdl.solve_details.status}."
        )

    valore = soluzione.get_value
    insiemi = preparazione["insiemi_HEN"]
    tecnologie = preparazione["tecnologie_HEN"]["tecnologie"]
    utilities = preparazione["utilities_HEN"]
    duty_utilities = {
        codice: valore(espressione)
        for codice, espressione in {
            **modello["Q_HU"],
            **modello["Q_CU"],
        }.items()
    }

    duty_match = {}
    for (z, i, m, j, n), variabile in modello["q"].items():
        q_val = valore(variabile)
        if q_val > tolleranza:
            duty_match[z, i, j] = duty_match.get((z, i, j), 0.0) + q_val

    codici_virtuali = {
        u.codice for tipo in ("hot", "cold") for u in utilities[tipo] if u.virtuale
    }
    scambiatori = []
    match_virtuali = []
    for indice in modello["indici_A_U"]:
        z, i, j, t = indice
        U_val = valore(modello["U"][indice])
        A_val = valore(modello["A"][indice])
        if U_val <= tolleranza:
            continue
        record = {
            "zona": z,
            "hot": i,
            "cold": j,
            "tecnologia": t,
            "U": U_val,
            "area_m2": A_val,
            "duty_kW": duty_match.get((z, i, j), 0.0),
        }
        if i in codici_virtuali or j in codici_virtuali or tecnologie[t].virtuale:
            match_virtuali.append(record)
        else:
            scambiatori.append(record)

    duty_exchanger_individuale = {}
    if modello.get("W_exchanger"):
        for z, i, j, k in sorted(modello["W_exchanger"]):
            if valore(modello["W_exchanger"][z, i, j, k]) <= 0.5:
                continue
            hkeys = sorted(
                (x for x in modello["indici_qhat_H"] if x[:3] == (z, i, j)),
                key=lambda x: x[3],
            )
            estremi = [x for x in hkeys if valore(modello["Khat_H"][x]) > 0.5]
            if k > len(estremi):
                raise RuntimeError(f"Estremo hot mancante per exchanger {(z, i, j, k)}.")
            cumulativi = []
            for estremo in estremi:
                m = estremo[3]
                cumulativi.append(
                    sum(valore(modello["qhat_H"][x]) for x in hkeys if x[3] <= m)
                    - valore(modello["qtilde_H"][estremo])
                )
            duty = cumulativi[k - 1] - (cumulativi[k - 2] if k > 1 else 0.0)
            duty_exchanger_individuale[z, i, j, k] = duty
            candidati = [
                x for x in modello.get("indici_Ahat_Uhat", [])
                if x[:4] == (z, i, j, k) and valore(modello["What"][x]) > 0.5
            ]
            if len(candidati) != 1:
                raise RuntimeError(f"Tecnologia individuale non univoca per {(z, i, j, k)}: {candidati}.")
            x = candidati[0]
            record = {
                "zona": z,
                "hot": i,
                "cold": j,
                "exchanger_id": k,
                "tecnologia": x[4],
                "U": valore(modello["Uhat"][x]),
                "area_m2": valore(modello["Ahat"][x]),
                "duty_kW": duty,
            }
            if i in codici_virtuali or j in codici_virtuali or tecnologie[x[4]].virtuale:
                match_virtuali.append(record)
            else:
                scambiatori.append(record)

    # Ricostruzione diagnostica delle temperature di ramo. Non aggiunge
    # vincoli: usa esclusivamente qhat, beginning/end e i CP gia risolti.
    temperature_exchangers = []
    if all(nome in modello for nome in ("qhat_H", "qhat_C", "K_H", "Khat_H", "K_C", "Khat_C")):
        

        def estremi_lato(record, lato):
            z, i, j = record["zona"], record["hot"], record["cold"]
            ordinal = int(record.get("exchanger_id", 1))
            if lato == "H":
                keys = sorted((x for x in modello["indici_qhat_H"] if x[:3] == (z, i, j)), key=lambda x: x[3])
                starts = [x for x in keys if valore(modello["K_H"][x]) > 0.5]
                ends = [x for x in keys if valore(modello["Khat_H"][x]) > 0.5]
            else:
                keys = sorted((x for x in modello["indici_qhat_C"] if x[:3] == (z, i, j)), key=lambda x: x[3])
                starts = [x for x in keys if valore(modello["K_C"][x]) > 0.5]
                ends = [x for x in keys if valore(modello["Khat_C"][x]) > 0.5]
            if ordinal > len(starts) or ordinal > len(ends):
                return None
            return keys, starts[ordinal - 1], ends[ordinal - 1]

        for record in scambiatori:
            hot_info, cold_info = estremi_lato(record, "H"), estremi_lato(record, "C")
            if hot_info is None or cold_info is None:
                continue
            hkeys, hb, he = hot_info
            ckeys, cb, ce = cold_info
            z, i, j = record["zona"], record["hot"], record["cold"]
            corrente_h = insiemi["correnti"][i]
            corrente_c = insiemi["correnti"][j]

            def frazione(keys, qnome, delta_nome, codice, inizio, fine):
                valori = []
                for k in keys:
                    if inizio[3] <= k[3] <= fine[3]:
                        delta = preparazione["delta_H_HEN"][delta_nome].get((z, codice, k[3]))
                        if delta and delta > 1e-12:
                            valori.append(valore(modello[qnome][k]) / delta)
                return max(valori, default=None)

            fH = None if i in insiemi["HU"][z] else frazione(hkeys, "qhat_H", "delta_H_H", i, hb, he)
            fC = None if j in insiemi["CU"][z] else frazione(ckeys, "qhat_C", "delta_H_C", j, cb, ce)
            TinH = ToutH = TinC = ToutC = None
            if i in insiemi["HU"][z]:
                TinH, ToutH = corrente_h.T_in, corrente_h.T_out
            elif fH and hb[3] != he[3]:
                cp = corrente_h.CP
                T_hb_L = insiemi["T_intervallo"][z, hb[3]]["T_inf"]
                T_he_U = insiemi["T_intervallo"][z, he[3]]["T_sup"]
                q_begin = valore(modello["qhat_H"][hb])
                q_end = valore(modello["qhat_H"][he])
                if "qtilde_H" in modello and he in modello["qtilde_H"]:
                    q_end -= valore(modello["qtilde_H"][he])
                TinH = T_hb_L + q_begin / (fH * cp)
                ToutH = T_he_U - q_end / (fH * cp)
            if j in insiemi["CU"][z]:
                TinC, ToutC = corrente_c.T_in, corrente_c.T_out
            elif fC and cb[3] != ce[3]:
                cp = corrente_c.CP
                T_cb_L = converti_temperatura(
                                            insiemi["T_intervallo"][z, cb[3]]["T_inf"],
                                            "cold",
                                            delta_T_min,
                                            "hens",
                                            "reale",
                                            )

                T_ce_U = converti_temperatura(
                    insiemi["T_intervallo"][z, ce[3]]["T_sup"],
                    "cold",
                    delta_T_min,
                    "hens",
                    "reale",
                                            )
                q_out = valore(modello["qhat_C"][cb])
                q_in = valore(modello["qhat_C"][ce])
                if "qtilde_C" in modello and ce in modello["qtilde_C"]:
                    q_in -= valore(modello["qtilde_C"][ce])
                ToutC = T_cb_L + q_out / (fC * cp)
                TinC = T_ce_U - q_in / (fC * cp)
            record.update(
                {
                    "hot_Tin_C": TinH,
                    "hot_Tout_C": ToutH,
                    "cold_Tin_C": TinC,
                    "cold_Tout_C": ToutC,
                    "delta_T_hot_end_K": None if TinH is None or ToutC is None else TinH - ToutC,
                    "delta_T_cold_end_K": None if ToutH is None or TinC is None else ToutH - TinC,
                    "split_fraction_hot": fH,
                    "split_fraction_cold": fC,
                }
            )
            temperature_exchangers.append(record.copy())

    codici_VHU = {u.codice for u in utilities["hot"] if u.virtuale}
    codici_VCU = {u.codice for u in utilities["cold"] if u.virtuale}
    risultati_flessibili = []
    Q_virtuale_hot = 0.0
    Q_virtuale_cold = 0.0
    for codice, dati in preparazione["flussi_flessibili"].items():
        Q_totale = dati["CP_kW_K"] * (dati["T_out_max_C"] - dati["T_out_min_C"])
        if dati["tipo"] == "hot":
            Q_virtuale = sum(
                Q
                for (z, i, j), Q in duty_match.items()
                if i == codice and j in codici_VCU
            )
            T_ottima = dati["T_out_min_C"] + Q_virtuale / dati["CP_kW_K"]
            Q_virtuale_hot += Q_virtuale
        else:
            Q_virtuale = sum(
                Q
                for (z, i, j), Q in duty_match.items()
                if j == codice and i in codici_VHU
            )
            T_ottima = dati["T_out_max_C"] - Q_virtuale / dati["CP_kW_K"]
            Q_virtuale_cold += Q_virtuale

        if not (dati["T_out_min_C"] - 1e-6 <= T_ottima <= dati["T_out_max_C"] + 1e-6):
            raise RuntimeError(
                f"Temperatura ottima fuori range per {codice}: {T_ottima}."
            )
        risultati_flessibili.append(
            {
                "codice": codice,
                "tipo": dati["tipo"],
                "T_out_min_C": dati["T_out_min_C"],
                "T_out_max_C": dati["T_out_max_C"],
                "T_out_ottima_C": min(
                    dati["T_out_max_C"], max(dati["T_out_min_C"], T_ottima)
                ),
                "Q_surplus_totale_kW": Q_totale,
                "Q_surplus_usato_nel_processo_kW": max(0.0, Q_totale - Q_virtuale),
                "Q_surplus_virtuale_kW": Q_virtuale,
            }
        )

    utilities_fisiche = {
        u.codice: duty_utilities.get(u.codice, 0.0)
        for tipo in ("hot", "cold")
        for u in utilities[tipo]
        if not u.virtuale
    }
    utilities_virtuali = {
        u.codice: {
            "tipo": u.tipo,
            "T_in_C": u.T_in,
            "T_out_C": u.T_out,
            "T_in_HEN_C": converti_temperatura(
                u.T_in,
                u.tipo,
                delta_T_min,
                "reale",
                "hens",
            ),

            "T_out_HEN_C": converti_temperatura(
                u.T_out,
                u.tipo,
                delta_T_min,
                "reale",
                "hens",
            ),
            "duty_kW": duty_utilities.get(u.codice, 0.0),
        }
        for tipo in ("hot", "cold")
        for u in utilities[tipo]
        if u.virtuale
    }

    processi = preparazione["configurazione"] ["flussi"]
    Q_hot_effettivo = (
        sum(f.calcola_Q() for f in processi if f.tipo == "hot") - Q_virtuale_hot
    )
    Q_cold_effettivo = (
        sum(f.calcola_Q() for f in processi if f.tipo == "cold") - Q_virtuale_cold
    )
    Q_HU_fisica = sum(
        duty_utilities.get(u.codice, 0.0) for u in utilities["hot"] if not u.virtuale
    )
    Q_CU_fisica = sum(
        duty_utilities.get(u.codice, 0.0) for u in utilities["cold"] if not u.virtuale
    )
    residuo_bilancio = Q_hot_effettivo + Q_HU_fisica - Q_cold_effettivo - Q_CU_fisica

    benchmark = (
        preparazione["configurazione"].get("hens", {}).get("benchmark_TAC_kUSD_year")
    )
    TAC = valore(modello["TAC"])
    confronto = (
        None
        if benchmark is None
        else {
            "PDF_kUSD_year": float(benchmark),
            "modello_kUSD_year": TAC / 1000.0,
            "errore_assoluto_kUSD_year": TAC / 1000.0 - float(benchmark),
            "errore_percentuale": 100.0
            * (TAC / 1000.0 - float(benchmark))
            / float(benchmark),
        }
    )

    controlli_BAR05 = {}
    if "qhat_H" in modello:
        residui_H = [
            abs(
                valore(modello["qhat_H"][k])
                - sum(valore(modello["q"][indice]) for indice in modello["gruppi_qhat_H"][k])
            )
            for k in modello["indici_qhat_H"]
        ]
        residui_C = [
            abs(
                valore(modello["qhat_C"][k])
                - sum(valore(modello["q"][indice]) for indice in modello["gruppi_qhat_C"][k])
            )
            for k in modello["indici_qhat_C"]
        ]
        controlli_BAR05["residuo_qhat_H_max_kW"] = max(residui_H, default=0.0)
        controlli_BAR05["residuo_qhat_C_max_kW"] = max(residui_C, default=0.0)
    if "E" in modello:
        residui_conteggio = []
        for match, Evar in modello["E"].items():
            z, i, j = match
            hkeys = [k for k in modello["indici_qhat_H"] if k[:3] == match]
            ckeys = [k for k in modello["indici_qhat_C"] if k[:3] == match]
            valori = [
                sum(valore(modello[nome][k]) for k in keys)
                for nome, keys in (("K_H", hkeys), ("Khat_H", hkeys), ("K_C", ckeys), ("Khat_C", ckeys))
            ]
            residui_conteggio.extend(abs(x - valore(Evar)) for x in valori)
        controlli_BAR05["residuo_beginnings_endings_max"] = max(residui_conteggio, default=0.0)
        controlli_BAR05["E_massimo"] = max((valore(v) for v in modello["E"].values()), default=0.0)
    if "Y_H" in modello:
        q_con_Y_zero = [
            valore(modello["qhat_H"][k]) for k, y in modello["Y_H"].items() if valore(y) < 0.5
        ] + [
            valore(modello["qhat_C"][k]) for k, y in modello["Y_C"].items() if valore(y) < 0.5
        ]
        controlli_BAR05["qhat_massimo_con_Y_zero_kW"] = max(q_con_Y_zero, default=0.0)

        # Verifica numerica letterale di BAR05 (11)-(14). I metadati dei
        # limiti distinguono process streams, utility fisiche e virtuali.
        tolleranza_BAR05 = 1e-6
        violazioni_11_14 = []
        dettagli_13_14 = {}
        for qhat_nome, Y_nome, limiti_nome, posizione_utility in (
            ("qhat_H", "Y_H", "limiti_qhat_BAR05_H", 1),
            ("qhat_C", "Y_C", "limiti_qhat_BAR05_C", 2),
        ):
            for k, limite in modello[limiti_nome].items():
                qhat_val = valore(modello[qhat_nome][k])
                Y_val = valore(modello[Y_nome][k])
                lower_slack = qhat_val - modello["qL_BAR05"] * Y_val
                upper_slack = limite["coefficiente_upper_kW"] * Y_val - qhat_val
                violazioni_11_14.append(max(0.0, -lower_slack, -upper_slack))
                if limite["equazione"] not in (13, 14):
                    continue
                codice = k[posizione_utility]
                record = dettagli_13_14.setdefault(
                    codice,
                    {
                        "equazione": limite["equazione"],
                        "F_U_kW_K": limite["F_U_kW_K"],
                        "min_lower_slack_kW": float("inf"),
                        "min_upper_slack_kW": float("inf"),
                        "min_upper_slack_Y1_kW": float("inf"),
                        "vincoli_lower_attivi_Y1": [],
                        "vincoli_upper_attivi_Y1": [],
                    },
                )
                record["min_lower_slack_kW"] = min(
                    record["min_lower_slack_kW"], lower_slack
                )
                record["min_upper_slack_kW"] = min(
                    record["min_upper_slack_kW"], upper_slack
                )
                if Y_val > 0.5:
                    record["min_upper_slack_Y1_kW"] = min(
                        record["min_upper_slack_Y1_kW"], upper_slack
                    )
                    if abs(lower_slack) <= tolleranza_BAR05:
                        record["vincoli_lower_attivi_Y1"].append(
                            limite["nome_lower"]
                        )
                    if abs(upper_slack) <= tolleranza_BAR05:
                        record["vincoli_upper_attivi_Y1"].append(
                            limite["nome_upper"]
                        )
        massimo_violazione = max(violazioni_11_14, default=0.0)
        controlli_BAR05["BAR05_11_14_max_violation_kW"] = massimo_violazione
        if massimo_violazione > tolleranza_BAR05:
            raise RuntimeError(
                "Verifica post-solve BAR05 (11)-(14) fallita: "
                f"violazione massima={massimo_violazione:.6e} kW."
            )

        F_U_hot = preparazione["parametri_utility_BAR05"]["F_U_hot"]
        F_U_cold = preparazione["parametri_utility_BAR05"]["F_U_cold"]
        for codice, record in dettagli_13_14.items():
            if record["min_upper_slack_Y1_kW"] == float("inf"):
                record["min_upper_slack_Y1_kW"] = None
            if codice in F_U_hot:
                F_soluzione = valore(modello["F_H"][codice])
                Q_massimo = preparazione["parametri_utility_BAR05"]["Q_HU_max_kW"]
            else:
                F_soluzione = valore(modello["F_C"][codice])
                Q_massimo = preparazione["parametri_utility_BAR05"]["Q_CU_max_kW"]
            record.update(
                {
                    "F_solution_kW_K": F_soluzione,
                    "Q_solution_kW": duty_utilities[codice],
                    "Q_U_max_kW": Q_massimo,
                    "utilization_ratio": F_soluzione / record["F_U_kW_K"],
                }
            )
        controlli_BAR05["BAR05_13_14_utility"] = dettagli_13_14
    residui_alpha = {"H": [], "C": []}
    for lato, alpha_nome, qhat_nome, delta_nome, posizione_stream in (
        ("H", "alpha_H", "qhat_H", "delta_H_H", 1),
        ("C", "alpha_C", "qhat_C", "delta_H_C", 2),
    ):
        if alpha_nome not in modello:
            continue
        for k, alpha in modello[alpha_nome].items():
            if valore(alpha) < 1 - 1e-6:
                continue
            z, i, j, intervallo = k
            p = (z, i, j, intervallo - 1)
            codice = i if lato == "H" else j
            r1 = valore(modello[qhat_nome][k]) / preparazione["delta_H_HEN"][delta_nome][z, codice, intervallo]
            r0 = valore(modello[qhat_nome][p]) / preparazione["delta_H_HEN"][delta_nome][z, codice, intervallo - 1]
            residui_alpha[lato].append(abs(r1 - r0))
    controlli_BAR05["residuo_split_alpha1_H_max"] = max(residui_alpha["H"], default=0.0)
    controlli_BAR05["residuo_split_alpha1_C_max"] = max(residui_alpha["C"], default=0.0)
    codici_virtuali = {
        u.codice for tipo in ("hot", "cold") for u in utilities[tipo] if u.virtuale
    }
    split_codes = {
        codice
        for nome in ("SH", "SC")
        for valori in preparazione["insiemi_BAR05"][nome].values()
        for codice in valori
    }
    controlli_BAR05["utility_virtuali_in_SH_SC"] = sorted(codici_virtuali & split_codes)
    controlli_BAR05["costi_virtuali_zero"] = all(
        (u.costo_USD_per_kW_year or 0.0) == 0.0
        for tipo in ("hot", "cold") for u in utilities[tipo] if u.virtuale
    ) and all(
        t.costo_fisso_USD_per_year == 0.0 and t.costo_area_USD_per_m2_year == 0.0
        for t in tecnologie.values() if t.virtuale
    )

    return {
        "soluzione": soluzione,
        "status": mdl.solve_details.status,
        "numero_zone": len(insiemi["Z"]),
        "numero_intervalli": sum(
            len(v) for v in preparazione["intervalli_HEN"].values()
        ),
        "numero_q": len(modello["q"]),
        "numero_A": len(modello["A"]) + len(modello.get("Ahat", {})),
        "numero_U": len(modello["U"]) + len(modello.get("Uhat", {})),
        "numero_variabili": mdl.number_of_variables,
        "numero_binarie": sum(1 for _ in mdl.iter_binary_vars()),
        "numero_vincoli": mdl.number_of_constraints,
        "tempo_CPLEX_s": mdl.solve_details.time,
        "costo_HU_USD_year": valore(modello["costo_hot_utility"]),
        "costo_CU_USD_year": valore(modello["costo_cold_utility"]),
        "costo_fisso_HEX_USD_year": valore(modello["costo_fisso_HEX"]),
        "costo_area_HEX_USD_year": valore(modello["costo_area_HEX"]),
        "TAC_USD_year": TAC,
        "utilities_fisiche_kW": utilities_fisiche,
        "utilities_virtuali": utilities_virtuali,
        "flexible_streams": risultati_flessibili,
        "scambiatori_fisici": scambiatori,
        "numero_exchanger_fisici": len(scambiatori),
        "numero_shell_fisiche": sum(x["U"] for x in scambiatori),
        "duty_exchanger_individuale_kW": duty_exchanger_individuale,
        "temperature_exchangers": temperature_exchangers,
        "virtual_matches": match_virtuali,
        "duty_match_kW": duty_match,
        "matches_per_tecnologia": {
            t: sorted(tecnologia.matches) for t, tecnologia in tecnologie.items()
        },
        "residuo_bilancio_energia_kW": residuo_bilancio,
        "confronto_benchmark": confronto,
        "controlli_BAR05": controlli_BAR05,
    }

def _sequenze_match_BAR05(indici, posizione_intervallo):
    """Raggruppa e ordina gli indici BAR05 per match e intervallo."""

    sequenze = {}
    for indice in indici:
        z, i, j, intervallo = indice
        sequenze.setdefault((z, i, j), []).append(intervallo)
    return {k: sorted(set(v)) for k, v in sequenze.items()}

# 7. OUTPUT HENS

def stampa_risultati_HEN(risultati):
    """Stampa il report unico dei casi HENS."""

    print("\nMODELLO")
    print(f"Zone: {risultati['numero_zone']}")
    print(f"Intervalli: {risultati['numero_intervalli']}")
    print(
        f"Variabili q/A/U: {risultati['numero_q']}/"
        f"{risultati['numero_A']}/{risultati['numero_U']}"
    )
    print(
        f"Totale variabili/vincoli: {risultati['numero_variabili']}/"
        f"{risultati['numero_vincoli']}"
    )
    print(f"Status CPLEX: {risultati['status']}")

    print("\nECONOMIA")
    for etichetta, chiave in (
        ("Costo HU", "costo_HU_USD_year"),
        ("Costo CU", "costo_CU_USD_year"),
        ("Costo fisso HEX", "costo_fisso_HEX_USD_year"),
        ("Costo area HEX", "costo_area_HEX_USD_year"),
    ):
        print(f"{etichetta}: {risultati[chiave]:,.2f} USD/year")
    print(f"TAC: {risultati['TAC_USD_year']:,.2f} USD/year")
    print(f"TAC: {risultati['TAC_USD_year'] / 1000.0:.3f} kUSD/year")

    print("\nUTILITIES FISICHE")
    for codice, duty in risultati["utilities_fisiche_kW"].items():
        print(f"{codice}: {duty:.3f} kW")

    print("\nFLEXIBLE STREAMS")
    if not risultati["flexible_streams"]:
        print("Nessuna")
    for dati in risultati["flexible_streams"]:
        print(
            f"{dati['codice']} ({dati['tipo']}): "
            f"Tout [{dati['T_out_min_C']:.2f}, {dati['T_out_max_C']:.2f}] C, "
            f"ottima {dati['T_out_ottima_C']:.3f} C; "
            f"surplus totale/usato/virtuale "
            f"{dati['Q_surplus_totale_kW']:.3f}/"
            f"{dati['Q_surplus_usato_nel_processo_kW']:.3f}/"
            f"{dati['Q_surplus_virtuale_kW']:.3f} kW"
        )

    print("\nSCAMBIATORI FISICI")
    for dati in risultati["scambiatori_fisici"]:
        print(
            f"Zona {dati['zona']} | {dati['hot']} -> {dati['cold']} | "
            f"{dati['tecnologia']} | U={dati['U']:.0f} | "
            f"A={dati['area_m2']:.3f} m2 | Q={dati['duty_kW']:.3f} kW"
        )

    print("\nVIRTUAL MATCHES")
    if not risultati["virtual_matches"]:
        print("Nessuno")
    for dati in risultati["virtual_matches"]:
        print(
            f"Zona {dati['zona']} | {dati['hot']} -> {dati['cold']} | "
            f"Q={dati['duty_kW']:.3f} kW"
        )
    for codice, dati in risultati["utilities_virtuali"].items():
        print(
            f"{codice} ({dati['tipo']}): HEN {dati['T_in_HEN_C']:.2f} -> "
            f"{dati['T_out_HEN_C']:.2f} C; reali {dati['T_in_C']:.2f} -> "
            f"{dati['T_out_C']:.2f} C; duty={dati['duty_kW']:.3f} kW"
        )

    print("\nBILANCIO ENERGETICO")
    print(f"Residuo globale: {risultati['residuo_bilancio_energia_kW']:+.6e} kW")

    confronto = risultati["confronto_benchmark"]
    if confronto:
        print("\nCONFRONTO BENCHMARK")
        print(f"PDF: {confronto['PDF_kUSD_year']:.3f} kUSD/year")
        print(f"Modello: {confronto['modello_kUSD_year']:.3f} kUSD/year")
        print(
            f"Scostamento: {confronto['errore_assoluto_kUSD_year']:+.3f} "
            f"kUSD/year ({confronto['errore_percentuale']:+.2f}%)"
        )



