"""Infrastruttura termica condivisa e neutra rispetto ai modelli.

Contiene soltanto gli oggetti e gli algoritmi Pinch che hanno la stessa
semantica, firma e struttura di output nelle pipeline predesign e HENS.
"""

import json
from pathlib import Path


class Flusso:
    """Rappresenta una corrente sensibile o un carico termico isotermo.

    Ruolo
    -----
    Normalizza i dati fisici di una corrente prima della Pinch Analysis.


    Oggetti matematici
    ------------------
    Temperature di ingresso/uscita, ``CP`` e carico ``Q`` della corrente.

    Input / Output
    --------------
    I campi JSON diventano attributi Python.

    Note implementative
    --------------------
    Per una corrente isoterma il carico è letto da ``heat_load_kW``; per una
    corrente sensibile ``CP`` può essere ricavato dal carico dichiarato.
    """

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
        splittable=True,
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
        self.splittable = bool(splittable)

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
        """Restituisce ``Q`` in kW .

        Per carichi isotermi usa ``heat_load_kW``; altrimenti applica
        ``Q = CP * abs(T_in - T_out)``.
        """

        if self.heat_load_kW is not None:
            return self.heat_load_kW

        return self.CP * abs(self.T_in - self.T_out)

def carica_caso_studio(percorso_json):
    """Carica il caso studio e costruisce gli oggetti :class:`Flusso`.

    Ruolo
    -----
    Realizza lo stadio 1_INPUT della pipeline.

    Oggetti matematici
    ------------------
    Dati delle correnti e parametri globali del caso.

    Input / Output
    --------------
    Legge un JSON e restituisce lo stesso dizionario sostituendo la lista
    ``flussi`` con oggetti Python.
    """

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


# CONVERSIONE, CASCATA E GCC PINCH CONDIVISE

def converti_temperatura_pinch(
    T,
    tipo,
    delta_T_min,
    origine,
    destinazione,
    delta_T_min_half=None,
    ):
    """Converte una temperatura tra scala reale e scala traslata Pinch.

    Ruolo
    -----
    Applica le traslazioni usate dal preprocessing termico.

    Riferimento bibliografico
    ------------------------
    Convenzione Pinch usata per costruire la GCC consumata da THI15 e per il
    preprocessing HENS. THI15, Sec. 2.1.1, assume la GCC come dato del modello.

    Oggetti matematici
    ------------------
    Temperature reali, traslate Pinch ``T*``.

    Input / Output
    --------------
    Restituisce un valore nella scala ``destinazione``; usa il mezzo
    ``delta_T_min`` specifico della corrente quando fornito.

    Note implementative
    --------------------
    Accetta soltanto ``reale`` e ``pinch``. La scala HENS è gestita dal wrapper
    specifico in ``BAR05_hens.py``.
    """

    # Usa il valore specifico della corrente, se definito; altrimenti assume la
    # traslazione Pinch standard ΔTmin/2.
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

    raise ValueError(f"Scala non riconosciuta: {destinazione}")


def crea_cascata_termica(flussi, delta_T_min, tolleranza=1e-9):
    """Costruisce cascata termica, calcola MER e identifica il main pinch point.

    Ruolo
    -----
    Aggrega i contributi hot/cold negli intervalli ``T*`` e rende non
    negativa la cascata mediante ``QH_min``.

    Riferimento bibliografico
    ------------------------
    Thibault et al. (2015), Sec. 2.1.1

    Oggetti matematici
    ------------------
    Intervalli termici, ``delta_H``, ``QH_min``, ``QC_min`` e Pinch Point.

    Input / Output
    --------------
    Da una sequenza di :class:`Flusso` restituisce righe della Problem Table
    e i target energetici in kW.

    Note implementative
    --------------------
    I carichi isotermi hanno ``delta_T = 0``;
    """
    # Tiene solo i flussi dichiarati disponibili nel caso studio.
    flussi_attivi = [flusso for flusso in flussi if flusso.disponibile]

    flussi_traslati = []
    temperature = []
    carichi_isotermi = {}

    for flusso in flussi_attivi:
        # Converte le temperature reali del flusso nella scala Pinch T*.
        T_in_star = converti_temperatura_pinch(
            flusso.T_in,
            flusso.tipo,
            delta_T_min,
            "reale",
            "pinch",
            flusso.delta_T_min_half,
        )
        T_out_star = converti_temperatura_pinch(
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
            # Somma il carico_termico alla componente hot oppure cold.
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


def costruisci_GCC(risultati, QH_min):
    """Costruisce la Grand Composite Curve dalla cascata finale.

    Ruolo
    -----
    Trasforma ciascun residuo della cascata in una coordinata ``(Q, T*)``.

    Riferimento bibliografico
    ------------------------
    Thibault et al. (2015), Sec. 2.1.1.

    Oggetti matematici
    ------------------
    Parametri ``Q_z,k`` e ``T_z,k`` prima della discretizzazione.

    Input / Output
    --------------
    Restituisce una lista di tuple ``(Q_kW, T_star_C)``.
    """

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
