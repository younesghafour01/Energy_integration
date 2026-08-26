"""Modello HENS BAR05 con le correzioni del Corrigendum 2006.

Architettura conservativa del modulo
------------------------------------
1_INPUT: correnti, utility fisiche e configurazione economica BAR05.
2_NORMALIZZAZIONE: Pinch condivisa e traslazione HENS specifica.
3_INSIEMI_E_INDICI: insiemi base e topologici BAR05.
4_PARAMETRI: ``delta_H``, ``F_U``, LMTD e coefficienti d'area.
5_DISCRETIZZAZIONE: partizionamento degli intervalli termici HENS.
6_VARIABILI: ``q``, portate, area/shell e variabili topologiche.
7_VINCOLI: bilanci, topologia, consistenza, fattibilità e area.
8_FUNZIONE_OBIETTIVO: total annual cost BAR05.
9_SOLVE: preparazione del modello e chiamata CPLEX.
10_POST_PROCESSING: estrazione della rete e aggregazioni.
11_VALIDAZIONE_DIAGNOSTICA: residui, benchmark e report.


"""

import math
from pathlib import Path

from src.common.thermal_preprocessing import (
    carica_caso_studio,
    converti_temperatura_pinch as _converti_temperatura_pinch,
    crea_cascata_termica,
    costruisci_GCC,
)

# ============================================================
# SHARED INFRASTRUCTURE + PREPROCESSING HENS
# ============================================================
# Non importa il modulo THI15. Parte direttamente dal JSON e usa il modulo
# comune neutro per correnti, cascata, MER, pinch e GCC. Restano locali la
# traslazione HENS e l'orchestrazione richiesta dalla pipeline BAR05:
# - correnti
# - cascata termica
# - MER
# - pinch
# - GCC
# necessari al partizionamento degli intervalli di temperatura.


# ============================================================
# 2_NORMALIZZAZIONE - CONVERSIONE REALE / PINCH / HENS
# ============================================================

def converti_temperatura(
    T,
    tipo,
    delta_T_min,
    origine,
    destinazione,
    delta_T_min_half=None,
    ):
    """Converte una temperatura tra scale reale, Pinch e HENS.


    Riferimento bibliografico
    ------------------------
    BAR05, Sec. 2.1, traslazione delle cold streams di ``delta_T_min``;
    .

    Oggetti matematici
    ------------------
    Limiti ``T_m^U``/``T_m^L`` sulla scala HENS e temperature reali.


    """

    # ``pinch`` è una scala di transito valida anche quando origine o
    # destinazione è ``hens``; la conversione reale/Pinch è delegata al
    # convertitore comune, mentre qui resta soltanto la traslazione HENS.
    scale_ammesse = {"reale", "pinch", "hens"}
    if origine not in scale_ammesse:
        raise ValueError(f"Scala non riconosciuta: {origine}")
    if destinazione not in scale_ammesse:
        raise ValueError(f"Scala non riconosciuta: {destinazione}")


    if origine == "hens":
        # Scala HENS gestita localmente dal modulo HENS:
        # hot  = reale
        # cold = reale + ΔTmin
        if tipo == "hot":
            T_reale = T
        else:
            T_reale = T - delta_T_min
    else:
        T_reale = _converti_temperatura_pinch(
            T,
            tipo,
            delta_T_min,
            origine,
            "reale",
            delta_T_min_half,
        )

    if destinazione == "reale":
        return T_reale
    if destinazione == "hens":
        # La convenzione BAR05 mantiene le hot alle temperature reali e
        # trasla le cold verso l'alto di ΔTmin.
        return (
            T_reale
            if tipo == "hot"
            else T_reale + delta_T_min
        )

    return _converti_temperatura_pinch(
        T_reale,
        tipo,
        delta_T_min,
        "reale",
        destinazione,
        delta_T_min_half,
    )

def esegui_analisi_pinch(percorso_json):
    """Esegue il preprocessing termico indipendente richiesto dalla HENS.
    il modello HENS poi usa, soprattutto le heat-transfer zones e
    il punto di separazione al pinch per poter costruire
    delle sottoreti di scambio termico se necessario

    Riferimento bibliografico
    ------------------------
    TRA15, Sec. 2.1.1 e 2.2.1. BAR05 parte invece dagli insiemi di zona e
    intervallo già definiti.

    Input / Output
    --------------
    Restituisce configurazione, cascata, MER, pinch e GCC.
    """

    configurazione = carica_caso_studio(percorso_json)

    (
        risultati_cascata,
        QH_min,
        QC_min,
        pinch_traslati,
    ) = crea_cascata_termica(
        configurazione["flussi"],
        configurazione["delta_T_min"],
    )

    gcc = costruisci_GCC(
        risultati_cascata,
        QH_min,
    )

    return {
        "configurazione": configurazione,
        "risultati_cascata": risultati_cascata,
        "QH_min_kW": QH_min,
        "QC_min_kW": QC_min,
        "pinch_traslati_C": pinch_traslati,
        "gcc": gcc,
    }




# ============================================================================
# 1_INPUT - OGGETTI HENS, UTILITY, TECNOLOGIE E FLEXIBLE STREAMS
# ============================================================================
class UtilityHEN:

    """Rappresenta una heating/cooling utility fisica BAR05.

    Riferimento bibliografico
    ------------------------
    BAR05, Sec. 2.1, insiemi ``HU_z`` e ``CU_z``.

    Oggetti matematici
    ------------------
    Portate ``F_i^H``/``F_j^C``, temperature, ``F_U`` e costo specifico.
    """

    def __init__(
    self,
    codice,
    nome,
    tipo,
    T_in,
    T_out,
    h_W_m2K,
    F_U_kW_K=None,
    costo_USD_per_kW_year=None,
    carico_termico_variabile=True,
    disponibile=True,
):
        """Rappresenta una utility HENS fisica."""

        self.codice = str(codice)
        self.nome = str(nome)
        self.tipo = str(tipo)

        self.T_in = float(T_in)
        self.T_out = float(T_out)

        self.h_W_m2K = float(h_W_m2K)
        self.F_U_kW_K = (
            None
            if F_U_kW_K is None
            else float(F_U_kW_K)
        )

        if self.F_U_kW_K is not None and self.F_U_kW_K <= 0:
            raise ValueError(
                f"F_U_kW_K non valido per {self.codice}: "
                f"{self.F_U_kW_K}"
            )


        self.costo_USD_per_kW_year = (
            None
            if costo_USD_per_kW_year is None
            else float(costo_USD_per_kW_year)
        )

        self.carico_termico_variabile = bool(carico_termico_variabile)
        self.disponibile = bool(disponibile)

class ScambiatoreBAR05:
    """Parametri economici dell'unico tipo di scambiatore BAR05.

    BAR05 non possiede l'insieme delle tecnologie TRA15: il fattore d'area è
    quindi unitario e i match sono quelli ammessi dal caso base.
    """

    def __init__(
        self,
        codice,
        nome,
        A_max_m2,
        costo_fisso_USD_per_year,
        costo_area_USD_per_m2_year,
        matches,
        enabled=True,
    ):
        """Memorizza limite d'area, costi e match del modello base."""
        self.codice = str(codice)
        self.nome = str(nome)

        self.fattore_area = 1.0
        self.A_max_m2 = float(A_max_m2)

        self.costo_fisso_USD_per_year = float(
            costo_fisso_USD_per_year
        )

        self.costo_area_USD_per_m2_year = float(
            costo_area_USD_per_m2_year
        )

        self.matches = frozenset(matches)

        self.enabled = bool(enabled)

def costruisci_utilities(configurazione):
    """Legge e valida le utility fisiche che alimentano la pipeline HENS.

    Fisicamente descrive correnti a temperature fissate e carico variabile
    (BAR05, Sec. 2.1 e Eq. (1)-(2); riusata anche da TRA15 Sec. 2.1.1).
    """
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
    # PDF §1.3.1.2 - Le utility sono separate negli insiemi HU e CU.
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
            F_U_kW_K=dati.get("F_U_kW_K"),
            costo_USD_per_kW_year=costo,
            carico_termico_variabile=bool(dati.get("carico_termico_variabile", True)),
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

def costruisci_scambiatore_base(configurazione):
    """Costruisce la parametrizzazione economica dello scambiatore BAR05.

    Il campo storico ``hens.technologies`` resta accettato per compatibilità
    degli input, ma BAR05 richiede una sola configurazione abilitata e fattore
    d'area unitario. La scelta fra tecnologie appartiene a TRA15.
    """
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
        A_max_m2 = float(dati["A_max_m2"])
        costo_fisso = float(dati["costo_fisso_USD_per_year"])
        costo_area = float(dati["costo_area_USD_per_m2_year"])
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
        tecnologia = ScambiatoreBAR05(
            codice=codice,
            nome=str(dati.get("nome", codice)),
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
    if len(T) != 1:
        raise ValueError(
            "BAR05 richiede una sola configurazione di scambiatore abilitata."
        )
    match_per_configurazione = {t: set(tecnologie[t].matches) for t in T}
    if not T:
        raise ValueError("Nessuna tecnologia HENS abilitata.")
    return {
        "T": T,
        "tecnologie": tecnologie,
        "match_per_configurazione": match_per_configurazione,
    }

# ============================================================================
# 5_DISCRETIZZAZIONE - PARTIZIONE TERMICA HENS
# ============================================================================

def crea_partizione_termica(
    gcc,
    flussi,

    delta_T_min,
    pinch_traslati,
    delta_T_partition_max,
    numero_intervalli_min,
    utilities=None,
    separa_al_pinch=True,
    estremi_termici_aggiuntivi=None,
):
    """Costruisce la partizione HENS sulla scala hot reale/cold traslata.

    Ruolo
    -----
    Include estremi GCC, correnti, utility ed eventuali estremi forniti
    dall'estensione; applica passo massimo, intervalli interni minimi e pinch.

    Riferimento bibliografico
    ------------------------
    BAR05, Sec. 2.1, definizione degli intervalli ``M_z``.
    TRA15, Sec. 2.2.1, per i criteri aggiuntivi di partizionamento adottati
    dall'estensione TRA15: angular points, dimezzamento per passo massimo,
    tre intervalli per stream priva di intervallo interno e cardinalità minima.

    Oggetti matematici
    ------------------
    Zone ``Z``, intervalli ``M_z`` e limiti ``T_m^U``/``T_m^L``.

    
    """
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
    estremi_termici_aggiuntivi = estremi_termici_aggiuntivi or []
    correnti_partizione = list(flussi) + list(utilities_hot) + list(utilities_cold)

    def temperature_corrente(corrente):
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
        T1, T2 = temperature_corrente(corrente)
        temperature_correnti.extend([T1, T2])
    for temperatura, tipo in estremi_termici_aggiuntivi:
        temperature_correnti.append(
            converti_temperatura(
                temperatura, tipo, delta_T_min, "reale", "hens"
            )
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
            T1, T2 = temperature_corrente(corrente)
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

def costruisci_insiemi_base(
    flussi,
    utilities,
    intervalli,
    delta_T_min,
    match_permessi=None,
    NI_H=None,
    NI_C=None,
):
    """Costruisce gli insiemi del modello base BAR05.

    Riferimento bibliografico
    ------------------------
    BAR05, Sec. 2.1, insiemi ``Z``, ``H_z``, ``C_z``, ``HU_z``, ``CU_z``,
    ``M_z``, ``M_i^z``, ``N_j^z``, ``P``, ``P_im^H`` e ``P_jn^C``.

    Oggetti matematici
    ------------------
    Tutti gli insiemi e le mappe temperatura-corrente che indicizzano ``q``.

    Input / Output
    --------------
    Restituisce dizionari con tuple canoniche ``(z, stream, interval)``.

    Note implementative
    --------------------
    Le cold streams sono rappresentate a temperatura reale + ``delta_T_min``.
    """
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

    def temperature_fisiche(flusso):
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
        T1, T2 = temperature_fisiche(flusso)
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
    M_i = {(z, i): [m for m in M[z] if i in H_m[z, m]] for z in Z for i in H[z]}
    N_j = {(z, j): [n for n in M[z] if j in C_n[z, n]] for z in Z for j in C[z]}

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
    }

def genera_indici_scambio(insiemi_HEN, tolleranza=1e-09):
    """Genera gli indici ``q[z,i,m,j,n]`` termicamente ammissibili.

    Riferimento bibliografico
    ------------------------
    BAR05, Sec. 2.1, insieme ``P`` e insiemi ``P_im^H``/``P_jn^C``;

    Oggetti matematici
    ------------------
    Variabile di trasporto ``q_im,jn^z``.

    Input / Output
    --------------
    Restituisce tuple canoniche ``(z, i, m, j, n)``.

    Note implementative
    --------------------
    Gli indici seguono direttamente ``P``, ``P_im^H`` e ``P_jn^C``.
    """
    Z = insiemi_HEN["Z"]
    H = insiemi_HEN["H"]
    C = insiemi_HEN["C"]
    M_i = insiemi_HEN["M_i"]
    N_j = insiemi_HEN["N_j"]
    P = insiemi_HEN["P"]
    P_H = insiemi_HEN["P_H"]
    P_C = insiemi_HEN["P_C"]
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
                        if i not in P_C[z, j, n]:
                            continue
                        T_n_L = T_intervallo[z, n]["T_inf"]
                        if T_n_L < T_m_U - tolleranza:
                            indici_q.append((z, i, m, j, n))
    indici_q = sorted(set(indici_q), key=lambda x: (x[0], x[1], x[2], x[3], x[4]))
    return indici_q

# ============================================================================
# 4_PARAMETRI - ENTALPIE, PORTATE UTILITY E COEFFICIENTI D'AREA
# ============================================================================

def calcola_entalpie_intervalli(insiemi_HEN, tolleranza=1e-09):
    """Calcola ``delta_H_im`` e ``delta_H_jn`` delle process streams.

    Riferimento bibliografico
    ------------------------
    BAR05, Eq. (3)-(4), parametri dei bilanci di processo; TRA15, Eq. (2) e
    bilancio cold analogo dichiarato nel testo di Sec. 2.1.2.

    Input / Output
    --------------
    Restituisce dizionari con chiavi ``(z,i,m)`` e ``(z,j,n)`` in kW.

    Note implementative
    --------------------
    Le correnti NI sono escluse qui e trattate dal blocco dedicato TRA15.
    """
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

def calcola_capacita_utility(
    configurazione,
    utilities_HEN,
    tolleranza=1e-12,
):
    """
    Costruisce i parametri ``F_i^U`` e ``F_j^U`` delle Eq. BAR05 (13)-(14),
    nella versione corretta dal Corrigendum 2006.

    Per le utility fisiche BAR05, F_U è un parametro di input
    espresso come heat-capacity flow [kW/K].

    Non viene ricostruito dal fabbisogno energetico globale
    del processo.

    Le utility virtuali non appartengono alla parametrizzazione
    F_U fisica BAR05.
    """

    del configurazione

    F_U_hot = {}
    F_U_cold = {}
    diagnostica = []

    for tipo, destinazione in (
        ("hot", F_U_hot),
        ("cold", F_U_cold),
    ):

        for utility in utilities_HEN[tipo]:

            # Le utility virtuali non sono utility fisiche BAR05.
            if getattr(utility, "virtuale", False):
                continue

            F_U = utility.F_U_kW_K

            if F_U is None:
                raise ValueError(
                    f"L'utility fisica {utility.codice} non contiene "
                    "'F_U_kW_K'. "
                    "BAR05 richiede F_U come parametro per le Eq. (13)-(14)."
                )

            F_U = float(F_U)

            if F_U <= tolleranza:
                raise ValueError(
                    f"F_U_kW_K non valido per {utility.codice}: {F_U}"
                )

            destinazione[utility.codice] = F_U

            diagnostica.append(
                {
                    "codice": utility.codice,
                    "tipo": tipo,
                    "T_in_C": utility.T_in,
                    "T_out_C": utility.T_out,
                    "F_U_kW_K": F_U,
                    "unita_F_U": "kW/K",
                    "origine": "input fisico BAR05",
                    "verifica_dimensionale": (
                        "F_U [kW/K] * DeltaT_interval [K] "
                        "= upper bound qhat [kW]"
                    ),
                }
            )

    return {
        "F_U_hot": F_U_hot,
        "F_U_cold": F_U_cold,
        "diagnostica": diagnostica,
    }

def costruisci_insiemi_topologici(insiemi_HEN, configurazione=None):
    """Deriva SH/SC, B, limiti e cardinalita massime della formulazione BAR05.

    Riferimento bibliografico
    ------------------------
    BAR05, Sec. 2.1, insiemi ``SH``, ``SC`` e ``B``.

    Oggetti matematici
    ------------------
    ``SH_z``, ``SC_z``, ``B``, intervalli iniziali/finali ed ``Emax``.

    SH e SC contengono le sole process streams dichiarate ``splittable``:
    utility fisiche, utility virtuali e relative pseudo-correnti sono escluse.
    Il default ``splittable=True`` conserva il comportamento dei JSON storici.
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
        z: [
            i
            for i in insiemi_HEN["H"][z]
            if i not in HU[z]
            and i not in VHU.get(z, [])
            and insiemi_HEN["correnti"][i].splittable
        ]
        for z in Z
    }
    SC = {
        z: [
            j
            for j in insiemi_HEN["C"][z]
            if j not in CU[z]
            and j not in VCU.get(z, [])
            and insiemi_HEN["correnti"][j].splittable
        ]
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

# ============================================================================
# 6_VARIABILI / 7_VINCOLI - MODELLO HENS BASE
# ============================================================================
def crea_modello_bilanci(
    insiemi_HEN, indici_q, delta_H_HEN, nome_modello="HENS_bilanci"
):
    """Crea ``q``, portate utility e bilanci energetici di intervallo.

    Riferimento bibliografico
    ------------------------
    BAR05, Eq. (1)-(4), usando il Corrigendum 2006 per domini e fattori
    ``F_U``; TRA15, Sec. 2.1.2, Eq. (1)-(2) e bilanci cold analoghi.

    Oggetti matematici
    ------------------
    ``q_im,jn^z``, ``F_i^H``, ``F_j^C`` e carichi utility ``Q_HU``/``Q_CU``.

    Input / Output
    --------------
    Restituisce il modello DOcplex con variabili e quattro famiglie di bilanci.

    Note implementative
    --------------------
    Il mixing non isotermo è aggiunto successivamente dal modulo TRA15.
    """
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
            f"crea_modello_bilanci() non gestisce ancora il non-isothermal mixing. NI_H={NI_H}, NI_C={NI_C}"
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

def calcola_parametri_area(insiemi_HEN, indici_q, delta_T_min, tolleranza=1e-09):
    """Calcola LMTD e coefficienti lineari per ciascun indice ``q``.

    Riferimento bibliografico
    ------------------------
    BAR05, Eq. (96); TRA15, Eq. (3), (6) e (7).

    Oggetti matematici
    ------------------
    ``h_im``, ``h_jn``, ``delta_T_ML_mn`` e coefficiente
    ``(h_im+h_jn)/(delta_T_ML*h_im*h_jn)``.

    Note implementative
    --------------------
    ``h`` è convertito da W/m²K a kW/m²K; formula LMTD e tolleranza restano
    invariate.
    """
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

def aggiungi_variabili_area(
    modello_bilanci, insiemi_HEN, indici_q, tecnologie_HEN, insiemi_BAR05=None
):
    """Crea le variabili area/shell BAR05, aggregate o individuali per ``B``.

    Riferimento bibliografico
    ------------------------
    BAR05, Eq. (96)-(104); TRA15, Eq. (7) e (10).

    Oggetti matematici
    ------------------
    ``A_ijt^z``, ``U_ijt^z`` e, per match multipli, ``Ahat``/``Uhat``.
    """
    mdl = modello_bilanci["modello"]
    T = tecnologie_HEN["T"]
    match_per_configurazione = tecnologie_HEN["match_per_configurazione"]
    coppie_zona = {(z, i, j) for z, i, m, j, n in indici_q}
    B = set() if insiemi_BAR05 is None else insiemi_BAR05.get("B", set())
    indici_A_U = []
    indici_Ahat_Uhat = []
    for z, i, j in sorted(coppie_zona):
        for t in T:
            if (i, j) not in match_per_configurazione[t]:
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

def aggiungi_vincoli_area(
    modello_HEN,
    indici_q,
    parametri_area,
    tecnologie_HEN,
    insiemi_BAR05=None,
    delta_H_HEN=None,
):
    """Aggiunge equazioni d'area e limiti di capacità delle shell.

    Riferimento bibliografico
    ------------------------
    BAR05, Eq. (96)-(104), con Eq. (100)-(102) corrette dal Corrigendum 2006;
    TRA15, Eq. (7)-(10) per tecnologie multiple.

    Oggetti matematici
    ------------------
    Area equivalente, ``A``, ``U``, ``Ahat``, ``Uhat``, ``G`` e ``qbreve``.

    Note implementative
    --------------------
    I Big-M d'area esistenti sono conservati e documentati nella diagnostica.
    """
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
                A[indice_A] * tecnologie[indice_A[3]].fattore_area
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
        # Bound numerico conservativo ottenuto dai carico_termico totali e dal massimo
        # coefficiente d'area del match; non modifica dati fisici o costi.
        if delta_H_HEN is None:
            raise RuntimeError("delta_H_HEN richiesto per l'area degli exchanger multipli.")
        carico_termico_M = min(
            sum(v for (zz, ii, _), v in delta_H_HEN["delta_H_H"].items() if zz == z and ii == i),
            sum(v for (zz, jj, _), v in delta_H_HEN["delta_H_C"].items() if zz == z and jj == j),
        )
        if carico_termico_M <= 0:
            raise RuntimeError(f"carico_termico bound non disponibile per multiple match {(z, i, j)}.")
        area_M = max(coeff_area[x] for x in qkeys) * carico_termico_M * 2
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
                    mdl.sum(tecnologie[x[4]].fattore_area * Ahat[x] for x in indici_tech) == base,
                    ctname=f"ECOS_multi_area_{z}_{i}_{j}_{k}",
                )
            )
            for x in indici_tech:
                tech = tecnologie[x[4]]
                max_shell = max(
                    1,
                    math.ceil(area_M / (tech.fattore_area * tech.A_max_m2)) + 1,
                )
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

# ============================================================================
# 8_FUNZIONE_OBIETTIVO - TOTAL ANNUAL COST
# ============================================================================

def aggiungi_obiettivo_TAC(modello_HEN, utilities_HEN, tecnologie_HEN):
    """Minimizza il costo annuale di utility, shell e area.

    Riferimento bibliografico
    ------------------------
    BAR05, Eq. (105); TRA15, Eq. (11) per l'indice di tecnologia ``t``.

    Oggetti matematici
    ------------------
    Costi utility, ``c_ijt^F U_ijt``, ``c_ijt^A A_ijt`` e ``TAC``.

    Input / Output
    --------------
    Imposta l'obiettivo DOcplex e conserva le quattro componenti di costo.
    """
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

# ============================================================================
# 6_VARIABILI / 7_VINCOLI - TOPOLOGIA E FORMULAZIONE BAR05
# ============================================================================

def aggiungi_flussi_cumulativi(
    modello_HEN, insiemi_HEN, indici_q, insiemi_BAR05
):
    """Aggiunge flussi cumulativi ``qhat`` e identità BAR05 (5)-(6).

    Ruolo
    -----
    Aggrega ``q_im,jn`` per match e intervallo sui lati hot e cold.

    Riferimento bibliografico
    ------------------------
    BAR05, Eq. (5)-(6).

    Oggetti matematici
    ------------------
    ``qhat_ijm^{z,H}`` e ``qhat_ijn^{z,C}``.
    """
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

def aggiungi_struttura_scambiatori(
    modello_HEN,
    insiemi_HEN,
    insiemi_BAR05,
    delta_H_HEN,
    parametri_utility_BAR05,
    blocchi,
    qL=1e-6,
    framework="bar05",
):
    """Aggiunge presenza, inizio/fine e conteggio BAR05 Eq. (11)-(42).

    Riferimento bibliografico
    ------------------------
    BAR05, Sec. 2.3-2.4, Eq. (11)-(42); Corrigendum 2006 per Eq. (13)-(15),
    (20) e (31)-(35).

    Oggetti matematici
    ------------------
    ``Y``, ``K``, ``Khat`` ed ``E`` sui lati hot/cold.

    Nel corrigendum (13)-(14), F_i^U e F_j^U sono parametri costanti. Il
    prodotto F_U * Y * delta_T_interval e pertanto lineare. Le utility
    virtuali delle flexible streams conservano il bound specifico preesistente
    e non sono trattate come utility fisiche BAR05.
    """
    if not blocchi:
        return modello_HEN

    framework = str(framework).strip().lower()
    if framework not in {"bar05", "tra15"}:
        raise ValueError("framework deve essere 'bar05' oppure 'tra15'.")

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
    bound_virtual_hot_carico_termico = sum(delta_H_HEN["delta_H_C"].values())
    bound_virtual_cold_carico_termico = sum(delta_H_HEN["delta_H_H"].values())
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
            tipo_limite = "physical_hot_utility_BAR05"
        elif i in VHU.get(z, []):
            ub = bound_virtual_hot_carico_termico
            equazione = None
            tipo_limite = "virtual_hot_utility"
        elif framework == "tra15" and i in insiemi_HEN["HU"][z]:
            # Nei case study TRA15 le utility non sono parametrizzate con F_U.
            # Serve soltanto un upper bound costante per l'implicazione qhat/Y.
            # Il fabbisogno totale cold costituisce un Big-M energetico
            # conservativo e non impone una capacità fisica aggiuntiva.
            ub = bound_virtual_hot_carico_termico
            equazione = None
            tipo_limite = "physical_hot_utility_TRA15_bigM"
        else:
            raise KeyError(f"F_U hot mancante per l'utility fisica {i}.")
        if equazione is not None:
            prefisso = f"BAR05_{equazione}"
        elif tipo_limite == "physical_hot_utility_TRA15_bigM":
            prefisso = "TRA15_HU_bigM"
        else:
            prefisso = "BAR05_VHU"
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
            tipo_limite = "physical_cold_utility_BAR05"
        elif j in VCU.get(z, []):
            ub = bound_virtual_cold_carico_termico
            equazione = None
            tipo_limite = "virtual_cold_utility"
        elif framework == "tra15" and j in insiemi_HEN["CU"][z]:
            # Analogo Big-M energetico per la cold utility TRA15.
            ub = bound_virtual_cold_carico_termico
            equazione = None
            tipo_limite = "physical_cold_utility_TRA15_bigM"
        else:
            raise KeyError(f"F_U cold mancante per l'utility fisica {j}.")
        if equazione is not None:
            prefisso = f"BAR05_{equazione}"
        elif tipo_limite == "physical_cold_utility_TRA15_bigM":
            prefisso = "TRA15_CU_bigM"
        else:
            prefisso = "BAR05_VCU"
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
    sequenze_H = _raggruppa_sequenze_match(indici_H, 3)
    sequenze_C = _raggruppa_sequenze_match(indici_C, 3)
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

def aggiungi_consistenza_portate(
    modello_HEN,
    insiemi_HEN,
    insiemi_BAR05,
    delta_H_HEN,
    blocchi,
):
    """Aggiunge ``alpha`` e i vincoli di consistenza delle portate.

    Riferimento bibliografico
    ------------------------
    BAR05, Sec. 2.5, Eq. (57)-(80); Corrigendum 2006 per Eq. (67), (73),
    (75)-(77) e (79).

    Oggetti matematici
    ------------------
    ``alpha_ijm^{z,H}``, ``alpha_ijn^{z,C}`` e rapporti di portata dei rami.

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

    # BAR05 (68), hot streams not in SH: in an exchanger-internal
    # interval the exchanger carries the full stream heat-capacity flow.
    vincoli_68 = []
    for k in modello_HEN["indici_qhat_H"]:
        z, i, j, m = k
        if i in insiemi_HEN["HU"][z] or i in insiemi_BAR05["SH"][z]:
            continue
        if (z, i, j, m - 1) not in set_H or (z, i, j, m + 1) not in set_H:
            continue
        vincoli_68.append(
            mdl.add_constraint(
                qhat_H[k]
                >= (Y_H[k] - K_H[k] - Khat_H[k])
                * delta_H_HEN["delta_H_H"][z, i, m],
                ctname=f"BAR05_68_{z}_{i}_{j}_{m}",
            )
        )
    modello_HEN["vincoli_BAR05_68"] = vincoli_68

    # BAR05 (80), cold streams not in SC. The published domain excludes B.
    vincoli_80 = []
    for k in modello_HEN["indici_qhat_C"]:
        z, i, j, n = k
        if (
            j in insiemi_HEN["CU"][z]
            or j in insiemi_BAR05["SC"][z]
            or (i, j) in insiemi_BAR05["B"]
        ):
            continue
        if (z, i, j, n - 1) not in set_C or (z, i, j, n + 1) not in set_C:
            continue
        vincoli_80.append(
            mdl.add_constraint(
                qhat_C[k]
                >= (Y_C[k] - K_C[k] - Khat_C[k])
                * delta_H_HEN["delta_H_C"][z, j, n],
                ctname=f"BAR05_80_{z}_{i}_{j}_{n}",
            )
        )
    modello_HEN["vincoli_BAR05_80"] = vincoli_80

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
            if (i, j) in insiemi_BAR05["B"]:
                continue
            p = (z, i, j, n - 1)
            vincoli.append(
                mdl.add_constraint(
                    rC(k) <= rC(p) + 1 - alpha_C[k],
                    ctname=f"BAR05_73_{z}_{i}_{j}_{n}",
                )
            )
            vincoli.append(
                mdl.add_constraint(
                    rC(k) >= rC(p) - 1 + alpha_C[k],
                    ctname=f"BAR05_74_{z}_{i}_{j}_{n}",
                )
            )
        modello_HEN["vincoli_BAR05_73_74"] = vincoli
    if "4F" in blocchi:
        vincoli = []
        for k in coppie_C:
            z, i, j, n = k
            if (i, j) in insiemi_BAR05["B"]:
                continue
            p = (z, i, j, n - 1)
            vincoli.append(
                mdl.add_constraint(
                    rC(k) >= rC(p) - (1 + Khat_C[p] + Khat_C[k] - K_C[p]),
                    ctname=f"BAR05_75_{z}_{i}_{j}_{n}",
                )
            )
            vincoli.append(
                mdl.add_constraint(
                    rC(k) <= rC(p) + (1 + K_C[p] + K_C[k] - Khat_C[k]),
                    ctname=f"BAR05_76_{z}_{i}_{j}_{n}",
                )
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

def aggiungi_scambiatori_multipli(
    modello_HEN, insiemi_HEN, insiemi_BAR05, delta_H_HEN
):
    """Aggiunge la formulazione per scambiatori multipli dell'insieme ``B``.

    Riferimento bibliografico
    ------------------------
    BAR05, Sec. 2.4, Eq. (43)-(56); Corrigendum 2006 per Eq. (44) e (48).

    Oggetti matematici
    ------------------
    ``qtilde_H``, ``qtilde_C``, ``X`` e indicatori ``W_exchanger``.

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

def aggiungi_fattibilita_temperature(
    modello_HEN,
    insiemi_HEN,
    insiemi_BAR05,
    delta_H_HEN,
    blocchi,
    tolleranza=1e-9,
):
    """Aggiunge i vincoli di fattibilità delle temperature agli estremi HEX.

    Riferimento bibliografico
    ------------------------
    BAR05, Sec. 2.6, Eq. (81)-(95); Corrigendum 2006 per Eq. (84)-(88),
    (92) e (95).

    Oggetti matematici
    ------------------
    Disequazioni agli hot-end/cold-end per stream splittable e non splittable.

    Le Cp dei benchmark sono costanti lungo ogni stream, quindi i rapporti
    Cp_m/Cp_m+1 delle equazioni corrette valgono uno. I delta_H/DeltaT
    rimanenti sono parametri e mantengono il modello lineare.
    """
    if not ({"5A", "5B"} & set(blocchi)):
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

    # BAR05 (81)-(82): both process streams are non-splittable. Temperatures
    # are already on the HENS scale, so the minimum approach is zero here.
    vincoli_81_82 = []
    for z, i, j in matches:
        if (
            i in insiemi_HEN["HU"][z]
            or j in insiemi_HEN["CU"][z]
            or i in insiemi_BAR05["SH"][z]
            or j in insiemi_BAR05["SC"][z]
        ):
            continue
        ms = sorted(k[3] for k in set_H if k[:3] == (z, i, j))
        ns = sorted(k[3] for k in set_C if k[:3] == (z, i, j))
        for m in ms:
            hm = (z, i, j, m)
            for n in ns:
                cn = (z, i, j, n)
                TmU, TmL = T[z, m]["T_sup"], T[z, m]["T_inf"]
                TnU, TnL = T[z, n]["T_sup"], T[z, n]["T_inf"]
                if TnL > TmU + tolleranza or TnU < TmL - tolleranza:
                    continue
                hot_term = qH[hm] * dT(z, m) / delta_H_HEN["delta_H_H"][z, i, m]
                cold_term = qC[cn] * dT(z, n) / delta_H_HEN["delta_H_C"][z, j, n]
                vincoli_81_82.extend(
                    [
                        mdl.add_constraint(
                            TmL + hot_term
                            >= TnL + cold_term - (2 - KH[hm] - KC[cn]) * TnU,
                            ctname=f"BAR05_81_{z}_{i}_{j}_{m}_{n}",
                        ),
                        mdl.add_constraint(
                            TmU - hot_term
                            >= TnU - cold_term - (2 - KhatH[hm] - KhatC[cn]) * TnU,
                            ctname=f"BAR05_82_{z}_{i}_{j}_{m}_{n}",
                        ),
                    ]
                )
    modello_HEN["vincoli_BAR05_81_82"] = vincoli_81_82

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
                if "5A" in blocchi:
                    vincoli_83_85.append(
                        mdl.add_constraint(
                            KhatC[cn] <= slack,
                            ctname=f"BAR05_83_{z}_{i}_{j}_{m}_{n}",
                        )
                    )
                if "5A" in blocchi:
                    vincoli_83_85.append(
                        mdl.add_constraint(
                            qC[cn] / den_c
                            <= qC[cp] / dT(z, n + 1)
                            + slack * delta_H_HEN["delta_H_C"][z, j, n] / den_c,
                            ctname=f"BAR05_84_{z}_{i}_{j}_{m}_{n}",
                        )
                    )
                if "5A" in blocchi:
                    vincoli_83_85.append(
                        mdl.add_constraint(
                            qH[hm] / den_h
                            >= qH[hp] / dT(z, m + 1)
                            - slack
                            * delta_H_HEN["delta_H_H"][z, i, m + 1]
                            / dT(z, m + 1),
                            ctname=f"BAR05_85_{z}_{i}_{j}_{m}_{n}",
                        )
                    )
    modello_HEN["vincoli_BAR05_83_85"] = vincoli_83_85
    if "5B" not in blocchi:
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
                if "5B" in blocchi:
                    vincoli_86_88.append(
                        mdl.add_constraint(KH[hm] <= slack, ctname=f"BAR05_86_{z}_{i}_{j}_{m}_{n}")
                    )
                if "5B" in blocchi:
                    vincoli_86_88.append(
                        mdl.add_constraint(qH[hm] / den_h <= qH[hp] / dT(z, m - 1) + slack * delta_H_HEN["delta_H_H"][z, i, m] / den_h, ctname=f"BAR05_87_{z}_{i}_{j}_{m}_{n}")
                    )
                if "5B" in blocchi:
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

# ============================================================================
# 9_SOLVE - PREPARAZIONE DEL MODELLO E CHIAMATA AL SOLVER
# ============================================================================

BAR05_BLOCCHI_DEFAULT = frozenset(
    {
        "1", "2", "3A", "3B", "3C", "3D", "4A", "4B",
        "4C", "4D", "4E", "4F", "5A", "5B", "7",
    }
)

def _prepara_modello(
    sorgente,
    bar05_qL=None,
    amax_fisico_m2=None,
    delta_T_partition_max=None,
    numero_intervalli_min=None,
    separa_al_pinch=None,
    bar05_blocchi=None,
    framework=None,
    estensione=None,
):
    """Costruisce una formulazione HENS senza modificare il preprocessing Pinch.

    Usa due partizioni finite: la prima determina le utility virtuali secondo
    TRA15 Eq. (12)-(13), la seconda le include nel modello definitivo.

    ``framework='bar05'`` usa il modello Barbaro-Bagajewicz/corrigendum.
    ``framework='tra15'`` usa lo stesso modello base BAR05, come dichiarato
    da TRA15 Sec. 2.1, aggiungendo le estensioni TRA15 per
    tecnologie multiple e flexible streams. Nei casi TRA15 F_U non è richiesto:
    per le sole implicazioni qhat/Y delle utility si usa un Big-M energetico
    conservativo, mentre i bilanci determinano comunque il carico_termico effettivo.

    Importante: le heat-transfer zones sono una scelta del designer.
    Il case study TRA15 Test 1-4 viene quindi eseguito in una sola zona salvo
    diversa dichiarazione esplicita nel JSON; non viene imposta automaticamente
    la separazione sopra/sotto pinch.
    """
    dati_pinch = (
        esegui_analisi_pinch(sorgente)
        if isinstance(sorgente, (str, Path))
        else sorgente
    )
    configurazione = dict(dati_pinch["configurazione"])

    # Il framework è fissato dall'entry point: BAR05 usa il percorso base,
    # mentre TRA15 fornisce esplicitamente i callback di estensione.
    if framework is None:
        framework = "tra15" if estensione is not None else "bar05"
    else:
        framework = str(framework).strip().lower()
        if framework not in {"bar05", "tra15"}:
            raise ValueError(
                "framework HENS ammesso: 'bar05' oppure 'tra15'."
            )

        # Se il JSON dichiara anche il framework, deve essere coerente con
        # l'entry point esplicito utilizzato.
        hens_cfg = configurazione.get("hens", {})
        if isinstance(hens_cfg, dict) and "framework" in hens_cfg:
            framework_json = _leggi_framework(configurazione)
            if framework_json != framework:
                raise ValueError(
                    "Framework incoerente: il JSON dichiara "
                    f"'{framework_json}' ma il codice ha richiesto '{framework}'."
                )
    if delta_T_partition_max is not None:
        if delta_T_partition_max <= 0:
            raise ValueError("delta_T_partition_max deve essere > 0.")
        configurazione["delta_T_partition_max"] = float(delta_T_partition_max)
    if numero_intervalli_min is not None:
        if numero_intervalli_min < 1:
            raise ValueError("numero_intervalli_min deve essere >= 1.")
        configurazione["numero_intervalli_min"] = int(numero_intervalli_min)
    hens = configurazione.get("hens", {})
    # TRA15 estende il modello base BAR05: qL resta quindi il piccolo
    # limite positivo usato nelle implicazioni qhat/Y del core topologico.
    # F_U, invece, rimane richiesto soltanto dai casi BAR05 che lo dichiarano
    # come parametro fisico delle Eq. (13)-(14).
    if bar05_qL is None:
        bar05_qL = hens.get("bar05_qL", hens.get("qL", 1e-6))
    bar05_qL = float(bar05_qL)
    if bar05_qL <= 0:
        raise ValueError("bar05_qL/qL deve essere > 0.")
    # La suddivisione in heat-transfer zones è una scelta del caso,
    # non una conseguenza automatica della presenza del pinch.
    #
    # BAR05:
    #   i benchmark dichiarano esplicitamente il numero di zone
    #   (4S1/7SP4 -> 2; 10SP1 -> 1), quindi il JSON resta autoritativo.
    #
    # TRA15:
    #   il case study Test 1-4 non impone la regola "no heat transfer
    #   across pinch"; la formulazione descrive le zone come opzione del
    #   designer. In assenza di un valore esplicito si usa quindi una sola
    #   heat-transfer zone.
    default_separa_al_pinch = True if framework == "bar05" else False
    separa_al_pinch = (
        hens.get("separa_al_pinch", default_separa_al_pinch)
        if separa_al_pinch is None
        else separa_al_pinch
    )
    if type(separa_al_pinch) is not bool:
        raise ValueError("'hens.separa_al_pinch' deve essere true oppure false.")
    flussi_flessibili = (
        estensione["costruisci_flussi_flessibili"](configurazione)
        if estensione is not None
        else {}
    )
    estremi_termici_aggiuntivi = (
        estensione["estremi_termici"](flussi_flessibili)
        if estensione is not None
        else []
    )
    utilities_fisiche = costruisci_utilities(configurazione)
    argomenti_partizione = {
        "gcc": dati_pinch["gcc"],
        "flussi": configurazione["flussi"],
        "delta_T_min": configurazione["delta_T_min"],
        "pinch_traslati": dati_pinch["pinch_traslati_C"],
        "delta_T_partition_max": configurazione["delta_T_partition_max"],
        "numero_intervalli_min": configurazione["numero_intervalli_min"],
        "separa_al_pinch": separa_al_pinch,
        "estremi_termici_aggiuntivi": estremi_termici_aggiuntivi,
    }
    partizione_preliminare = crea_partizione_termica(
        utilities=utilities_fisiche, **argomenti_partizione
    )
    utilities_virtuali = (
        estensione["costruisci_utilities_virtuali"](
            intervalli=partizione_preliminare,
            flussi_flessibili=flussi_flessibili,
            flussi=configurazione["flussi"],
            delta_T_min=configurazione["delta_T_min"],
            delta_T_partition_max=configurazione["delta_T_partition_max"],
        )
        if estensione is not None
        else {"hot": [], "cold": []}
    )
    codici_esistenti = {f.codice for f in configurazione["flussi"]} | {
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
    parametri_utility_BAR05 = (
        calcola_capacita_utility(configurazione, utilities_HEN)
        if framework == "bar05"
        else {"F_U_hot": {}, "F_U_cold": {}}
    )
    intervalli_HEN = crea_partizione_termica(
        utilities=utilities_HEN, **argomenti_partizione
    )


    print("\n=== PARTIZIONE HENS ===")

    totale = 0

    for z, intervalli_z in intervalli_HEN.items():
        print(f"\nZona {z}: {len(intervalli_z)} intervalli")

        for m, intervallo in enumerate(intervalli_z, start=1):

            if isinstance(intervallo, dict):
                T_sup = intervallo["T_sup"]
                T_inf = intervallo["T_inf"]
            else:
                T_sup, T_inf = intervallo[:2]

            print(
                f"  m={m:3d} | "
                f"{T_sup:10.4f} -> {T_inf:10.4f} °C | "
                f"ΔT={T_sup - T_inf:10.4f}"
            )

        totale += len(intervalli_z)

    print(f"\nINTERVALLI TOTALI = {totale}")
    print(f"HEAT-TRANSFER ZONES = {len(intervalli_HEN)}")
    print(f"SEPARAZIONE AL PINCH = {separa_al_pinch}")
    print("========================\n")
    costruisci_configurazioni = (
        estensione["costruisci_tecnologie"]
        if estensione is not None
        else costruisci_scambiatore_base
    )
    tecnologie_HEN = costruisci_configurazioni(configurazione)
    if estensione is not None:
        estensione["aggiungi_tecnologia_virtuale"](
            tecnologie_HEN, utilities_HEN, flussi_flessibili
        )
    if amax_fisico_m2 is not None:
        if amax_fisico_m2 <= 0:
            raise ValueError("amax_fisico_m2 deve essere > 0.")
        for tecnologia in tecnologie_HEN["tecnologie"].values():
            if not getattr(tecnologia, "virtuale", False):
                tecnologia.A_max_m2 = float(amax_fisico_m2)
    match_permessi = set().union(
        *tecnologie_HEN["match_per_configurazione"].values()
    )
    costruisci_insiemi = (
        estensione["costruisci_insiemi"]
        if estensione is not None
        else costruisci_insiemi_base
    )
    argomenti_insiemi = dict(
        flussi=configurazione ["flussi"],
        utilities=utilities_HEN,
        intervalli=intervalli_HEN,
        delta_T_min=configurazione["delta_T_min"],
        match_permessi=match_permessi,
    )
    if estensione is not None:
        argomenti_insiemi["flexible_streams"] = flussi_flessibili
    insiemi_HEN = costruisci_insiemi(**argomenti_insiemi)
    # TRA15 è un'estensione del modello base BAR05. Gli insiemi topologici
    # SH/SC/B servono quindi anche a TRA15, in particolare quando il JSON
    # dichiara multiple_matches.
    insiemi_BAR05 = costruisci_insiemi_topologici(
        insiemi_HEN, configurazione
    )
    genera_indici = (
        estensione["genera_indici_scambio"]
        if estensione is not None
        else genera_indici_scambio
    )
    indici_q = genera_indici(insiemi_HEN)
    delta_H_HEN = calcola_entalpie_intervalli(insiemi_HEN)
    modello_HEN = crea_modello_bilanci(
        insiemi_HEN,
        indici_q,
        delta_H_HEN,
        nome_modello=("HENS_BAR05" if framework == "bar05" else "HENS_TRA15"),
    )
    # TRA15 Sec. 2.1 dichiara esplicitamente che il
    # modello proposto estende BAR05. Perciò il core topologico BAR05
    # (qhat, Y, K/Khat, split-flow consistency, temperature feasibility e
    # multiple matches) è comune ai due framework. La differenza TRA15 resta
    # nelle estensioni: tecnologie multiple e flexible streams.
    blocchi_BAR05 = (
        set(BAR05_BLOCCHI_DEFAULT)
        if bar05_blocchi is None
        else set(bar05_blocchi)
    )

    insiemi_BAR05_attivi = dict(insiemi_BAR05)

    # Le multiple matches devono entrare atomicamente con il blocco 7.
    if "7" not in blocchi_BAR05:
        insiemi_BAR05_attivi["B"] = set()
        insiemi_BAR05_attivi["Emax"] = {}
    if "2" in blocchi_BAR05:
        aggiungi_flussi_cumulativi(
            modello_HEN, insiemi_HEN, indici_q, insiemi_BAR05
        )
    parametri_area = calcola_parametri_area(
        insiemi_HEN, indici_q, configurazione["delta_T_min"]
    )
    aggiungi_variabili_area(
        modello_HEN,
        insiemi_HEN,
        indici_q,
        tecnologie_HEN,
        insiemi_BAR05=insiemi_BAR05_attivi,
    )
    blocchi_struttura = blocchi_BAR05 & {"3A", "3B", "3C", "3D"}
    if blocchi_struttura:
        aggiungi_struttura_scambiatori(
            modello_HEN,
            insiemi_HEN,
            insiemi_BAR05_attivi,
            delta_H_HEN,
            parametri_utility_BAR05,
            blocchi_struttura,
            qL=bar05_qL,
            framework=framework,
        )
    if "7" in blocchi_BAR05:
        aggiungi_scambiatori_multipli(
            modello_HEN, insiemi_HEN, insiemi_BAR05_attivi, delta_H_HEN
        )
    if "4A" in blocchi_BAR05:
        aggiungi_consistenza_portate(
            modello_HEN,
            insiemi_HEN,
            insiemi_BAR05_attivi,
            delta_H_HEN,
            blocchi_BAR05,
        )
    if {"5A", "5B"} & blocchi_BAR05:
        aggiungi_fattibilita_temperature(
            modello_HEN,
            insiemi_HEN,
            insiemi_BAR05_attivi,
            delta_H_HEN,
            blocchi_BAR05,
        )
    aggiungi_vincoli_area(
        modello_HEN,
        indici_q,
        parametri_area,
        tecnologie_HEN,
        insiemi_BAR05=insiemi_BAR05_attivi,
        delta_H_HEN=delta_H_HEN,
    )
    target_flessibili = hens.get(
            "diagnostic_force_flexible_Tout_C",
            {}
        )

    if estensione is not None:
        estensione["forza_temperature_uscita_flessibili"](
                modello_HEN,
                insiemi_HEN,
                flussi_flessibili,
                target_flessibili,
            )

    aggiungi_obiettivo_TAC(modello_HEN, utilities_HEN, tecnologie_HEN)

    return {
        "framework": framework,
        "dati_pinch": dati_pinch,
        "configurazione": configurazione,
        "flussi_flessibili": flussi_flessibili,
        "utilities_HEN": utilities_HEN,
        "parametri_utility_BAR05": parametri_utility_BAR05,
        "intervalli_HEN": intervalli_HEN,
        "insiemi_HEN": insiemi_HEN,
        "insiemi_BAR05": insiemi_BAR05,
        "bar05_blocchi": sorted(blocchi_BAR05),
        "bar05_qL": bar05_qL,
        "separa_al_pinch": separa_al_pinch,
        "indici_q": indici_q,
        "delta_H_HEN": delta_H_HEN,
        "parametri_area": parametri_area,
        "tecnologie_HEN": tecnologie_HEN,
        "modello_HEN": modello_HEN,
    }


def individua_correnti_mixing_non_isotermo(preparazione):
    """Legge e valida gli insiemi ``NIH`` e ``NIC`` del caso.

    Ruolo
    -----
    Seleziona le sole correnti di processo soggette a mixing non isotermo,
    escludendo sempre utility fisiche e virtuali.

    Riferimento bibliografico
    -------------------------
    BAR05, Sec. 2.1, insiemi ``NIH`` e ``NIC``; Corrigendum 2006 per la
    notazione corretta delle variabili ``qbar`` nelle Eq. (7)-(10).

    Oggetto matematico
    ------------------
    Sottoinsiemi ``NIH`` delle hot streams e ``NIC`` delle cold streams.

    Implementazione Python
    ----------------------
    Il JSON puo dichiarare ``hens.non_isothermal_mixing.hot`` e ``cold``.
    Se il caso dichiara soltanto ``requires_non_isothermal_mixing=true``, sono
    incluse simmetricamente tutte le process streams, mai le utility.

    Motivo della modifica
    ---------------------
    Necessaria per supportare in modo generale i casi BAR05 che ammettono
    non-isothermal split mixing, senza dipendere dal nome del caso o dalla
    topologia benchmark.
    """

    configurazione = preparazione["configurazione"]
    hens = configurazione.get("hens", {})
    specifica = hens.get("non_isothermal_mixing")
    richiesto = bool(hens.get("requires_non_isothermal_mixing", False))

    insiemi = preparazione["insiemi_HEN"]
    hot_process = {
        i
        for z in insiemi["Z"]
        for i in insiemi["H"][z]
        if i not in insiemi["HU"][z]
    }
    cold_process = {
        j
        for z in insiemi["Z"]
        for j in insiemi["C"][z]
        if j not in insiemi["CU"][z]
    }

    if specifica is None:
        return (
            sorted(hot_process) if richiesto else [],
            sorted(cold_process) if richiesto else [],
        )

    if specifica is True:
        return sorted(hot_process), sorted(cold_process)
    if specifica is False:
        if richiesto:
            raise ValueError(
                "Il caso richiede non-isothermal mixing ma "
                "hens.non_isothermal_mixing e false."
            )
        return [], []
    if not isinstance(specifica, dict):
        raise ValueError(
            "'hens.non_isothermal_mixing' deve essere un booleano oppure "
            "un oggetto con liste 'hot' e 'cold'."
        )

    NIH = {str(codice) for codice in specifica.get("hot", [])}
    NIC = {str(codice) for codice in specifica.get("cold", [])}
    hot_invalidi = NIH - hot_process
    cold_invalidi = NIC - cold_process
    if hot_invalidi or cold_invalidi:
        raise ValueError(
            "Correnti NI non valide o utility incluse: "
            f"hot={sorted(hot_invalidi)}, cold={sorted(cold_invalidi)}."
        )
    if richiesto and not (NIH or NIC):
        raise ValueError(
            "Il caso richiede non-isothermal mixing ma NIH e NIC sono vuoti."
        )
    return sorted(NIH), sorted(NIC)


def aggiungi_mixing_non_isotermo(preparazione, NIH, NIC):
    """Aggiunge ``qbar`` e i vincoli BAR05 corretti per gli stream selezionati.

    Ruolo
    -----
    Sostituisce i bilanci isotermi delle correnti in ``NIH``/``NIC`` con i
    bilanci che permettono non-isothermal split mixing.

    Riferimento bibliografico
    -------------------------
    BAR05, Eq. (7)-(10); Corrigendum 2006, pp. 1310-1311.

    Oggetto matematico
    ------------------
    ``qbar_imn^{z,H}``, ``qbar_jnm^{z,C}`` e vincoli (7)-(10).

    L'implementazione vive nel modulo BAR05 perche le equazioni (7)-(10)
    appartengono al modello base e vengono riusate dall'estensione TRA15.
    """

    mdl = preparazione["modello_HEN"]["modello"]
    modello_HEN = preparazione["modello_HEN"]
    insiemi = preparazione["insiemi_HEN"]
    delta_H_H = dict(preparazione["delta_H_HEN"]["delta_H_H"])
    delta_H_C = dict(preparazione["delta_H_HEN"]["delta_H_C"])

    gruppi_hot = {}
    gruppi_cold = {}
    for indice, variabile in modello_HEN["q"].items():
        z, i, m, j, n = indice[:5]
        gruppi_hot.setdefault((int(z), str(i), int(m)), []).append(variabile)
        gruppi_cold.setdefault((int(z), str(j), int(n)), []).append(variabile)
    q_hot = {chiave: mdl.sum(v) for chiave, v in gruppi_hot.items()}
    q_cold = {chiave: mdl.sum(v) for chiave, v in gruppi_cold.items()}

    def trova_vincolo(nome):
        try:
            vincolo = mdl.get_constraint_by_name(nome)
            if vincolo is not None:
                return vincolo
        except Exception:
            pass
        return next(
            (v for v in mdl.iter_constraints() if getattr(v, "name", None) == nome),
            None,
        )

    qbar_H = {}
    qbar_C = {}
    mancanti = []
    rimossi_hot = 0
    rimossi_cold = 0
    intervalli_hot = {}
    intervalli_cold = {}

    for z in insiemi["Z"]:
        for i in NIH:
            if i not in insiemi["H"][z] or i in insiemi["HU"][z]:
                continue
            intervalli = sorted(
                m for m in insiemi["M_i"][z, i]
                if (z, i, m) in delta_H_H and float(delta_H_H[z, i, m]) > 1e-12
            )
            intervalli_hot[z, i] = intervalli
            for m in intervalli:
                nome = f"bil_HP_z{z}_{i}_m{m}"
                vincolo = trova_vincolo(nome)
                if vincolo is None:
                    mancanti.append(nome)
                else:
                    mdl.remove_constraint(vincolo)
                    rimossi_hot += 1
            for pos, a in enumerate(intervalli):
                for b in intervalli[pos + 1:]:
                    qbar_H[z, i, a, b] = mdl.continuous_var(
                        lb=0, name=f"NI_qbarH_{z}_{i}_{a}_{b}"
                    )

        for j in NIC:
            if j not in insiemi["C"][z] or j in insiemi["CU"][z]:
                continue
            intervalli = sorted(
                n for n in insiemi["N_j"][z, j]
                if (z, j, n) in delta_H_C and float(delta_H_C[z, j, n]) > 1e-12
            )
            intervalli_cold[z, j] = intervalli
            for n in intervalli:
                nome = f"bil_CP_z{z}_{j}_n{n}"
                vincolo = trova_vincolo(nome)
                if vincolo is None:
                    mancanti.append(nome)
                else:
                    mdl.remove_constraint(vincolo)
                    rimossi_cold += 1
            for pos, a in enumerate(intervalli):
                for b in intervalli[pos + 1:]:
                    qbar_C[z, j, a, b] = mdl.continuous_var(
                        lb=0, name=f"NI_qbarC_{z}_{j}_{a}_{b}"
                    )

    if mancanti:
        raise RuntimeError("Bilanci originali mancanti: " + repr(mancanti[:20]))

    n7 = n8 = n9 = n10 = 0
    for (z, i), intervalli in intervalli_hot.items():
        for m in intervalli:
            incoming = [qbar_H[z, i, m, b] for b in intervalli if b > m]
            outgoing = [qbar_H[z, i, a, m] for a in intervalli if a < m]
            esterno = q_hot.get((int(z), str(i), int(m)), 0)
            mdl.add_constraint(
                float(delta_H_H[z, i, m])
                == esterno + mdl.sum(incoming) - mdl.sum(outgoing),
                ctname=f"NI_BAR05_7_{z}_{i}_{m}",
            )
            mdl.add_constraint(
                mdl.sum(outgoing) <= esterno,
                ctname=f"NI_BAR05_9_{z}_{i}_{m}",
            )
            n7 += 1
            n9 += 1

    for (z, j), intervalli in intervalli_cold.items():
        for n in intervalli:
            incoming = [qbar_C[z, j, a, n] for a in intervalli if a < n]
            outgoing = [qbar_C[z, j, n, b] for b in intervalli if b > n]
            esterno = q_cold.get((int(z), str(j), int(n)), 0)
            mdl.add_constraint(
                float(delta_H_C[z, j, n])
                == esterno + mdl.sum(incoming) - mdl.sum(outgoing),
                ctname=f"NI_BAR05_8_{z}_{j}_{n}",
            )
            mdl.add_constraint(
                mdl.sum(outgoing) <= esterno,
                ctname=f"NI_BAR05_10_{z}_{j}_{n}",
            )
            n8 += 1
            n10 += 1

    informazioni = {
        "NIH": list(NIH),
        "NIC": list(NIC),
        "qbar_H": qbar_H,
        "qbar_C": qbar_C,
        "removed_hot": rimossi_hot,
        "removed_cold": rimossi_cold,
        "n_qbarH": len(qbar_H),
        "n_qbarC": len(qbar_C),
        "eq7": n7,
        "eq9": n9,
        "eq8": n8,
        "eq10": n10,
    }
    preparazione["non_isothermal_mixing_BAR05"] = informazioni
    return informazioni


def prepara_modello(sorgente, **opzioni):
    """Prepara la formulazione BAR05 con le correzioni del 2006.

    Riferimento bibliografico
    ------------------------
    BAR05, Sec. 2.1-2.9, Eq. (1)-(105), con Corrigendum 2006.
    """
    preparazione = _prepara_modello(
        sorgente,
        framework="bar05",
        **opzioni,
    )
    NIH, NIC = individua_correnti_mixing_non_isotermo(preparazione)
    if NIH or NIC:
        aggiungi_mixing_non_isotermo(
            preparazione,
            NIH,
            NIC,
        )
    return preparazione


def _leggi_framework(configurazione):
    """Legge il framework HENS dichiarato esplicitamente nel file JSON.

    Il framework NON viene inferito da altri campi dell'input: ogni caso deve
    dichiarare manualmente uno dei due valori ammessi:

        "hens": {
            "framework": "bar05"
        }

    oppure:

        "hens": {
            "framework": "tra15"
        }

    Questo evita che la presenza/assenza di parametri specifici (per esempio
    F_U_kW_K) instradi accidentalmente un caso verso la formulazione sbagliata.
    """
    hens = configurazione.get("hens")

    if not isinstance(hens, dict):
        raise ValueError(
            "La configurazione deve contenere una sezione 'hens' di tipo oggetto."
        )

    if "framework" not in hens:
        raise ValueError(
            "Framework HENS non specificato. Aggiungere nel JSON "
            "'hens.framework': 'bar05' oppure 'tra15'."
        )

    valore = str(hens["framework"]).strip().lower()

    if valore not in {"bar05", "tra15"}:
        raise ValueError(
            "Valore non valido per 'hens.framework'. "
            "Sono ammessi esclusivamente 'bar05' oppure 'tra15'."
        )

    return valore


def prepara_modello_da_configurazione(
    sorgente,
    bar05_qL=None,
    amax_fisico_m2=None,
    delta_T_partition_max=None,
    numero_intervalli_min=None,
    separa_al_pinch=None,
    bar05_blocchi=None,
):
    """Instrada esplicitamente verso BAR05 oppure TRA15 dal campo JSON.

    
    """
    dati_pinch = (
        esegui_analisi_pinch(sorgente)
        if isinstance(sorgente, (str, Path))
        else sorgente
    )
    framework = _leggi_framework(dati_pinch["configurazione"])
    if framework != "bar05":
        raise ValueError(
            "Questo entry point prepara esclusivamente BAR05; "
            "per TRA15 usare src.hens.TRA15_hens.prepara_modello."
        )
    return _prepara_modello(
        dati_pinch,
        bar05_qL=bar05_qL,
        amax_fisico_m2=amax_fisico_m2,
        delta_T_partition_max=delta_T_partition_max,
        numero_intervalli_min=numero_intervalli_min,
        separa_al_pinch=separa_al_pinch,
        bar05_blocchi=bar05_blocchi,
        framework="bar05",
    )

def calcola_confronto_benchmark(configurazione, simulato):
    """Confronta post-solve simulazione e benchmark del JSON.

    Riferimento bibliografico
    ------------------------
    BAR05, Sec. 3; TRA15, Sec. 3. I benchmark non entrano nel MILP.
    """
    hens = configurazione.get("hens", {})
    benchmark = dict(hens.get("benchmark", {}))
    if "TAC_kUSD_year" not in benchmark and "benchmark_TAC_kUSD_year" in hens:
        benchmark["TAC_kUSD_year"] = hens["benchmark_TAC_kUSD_year"]
    if "area_total_m2" not in benchmark and "benchmark_area_total_m2" in hens:
        benchmark["area_total_m2"] = hens["benchmark_area_total_m2"]
    if "numero_exchanger" not in benchmark and "benchmark_exchangers" in hens:
        benchmark["numero_exchanger"] = len(hens["benchmark_exchangers"])

    valori_simulati = {
        "TAC_kUSD_year": simulato["TAC_USD_year"] / 1000.0,
        "area_total_m2": simulato["area_total_m2"],
        "numero_exchanger": simulato["numero_exchanger"],
        "numero_shell": simulato["numero_shell"],
        "HU_kW": simulato["HU_kW"],
        "CU_kW": simulato["CU_kW"],
        "numero_variabili": simulato["numero_variabili"],
        "numero_binarie": simulato["numero_binarie"],
        "numero_vincoli": simulato["numero_vincoli"],
        "numero_intervalli": simulato["numero_intervalli"],
    }
    etichette = {
        "TAC_kUSD_year": "TAC (kUSD/year)",
        "area_total_m2": "Area totale (m2)",
        "numero_exchanger": "Numero exchanger",
        "numero_shell": "Numero shell",
        "HU_kW": "Hot utility (kW)",
        "CU_kW": "Cold utility (kW)",
        "numero_variabili": "Variabili MILP",
        "numero_binarie": "Variabili binarie MILP",
        "numero_vincoli": "Vincoli MILP",
        "numero_intervalli": "Intervalli",
    }
    righe = []
    for chiave, etichetta in etichette.items():
        if chiave not in benchmark:
            continue
        fonte = float(benchmark[chiave])
        valore = float(valori_simulati[chiave])
        errore = valore - fonte
        righe.append(
            {
                "metrica": etichetta,
                "fonte": fonte,
                "simulato": valore,
                "errore_assoluto": abs(errore),
                "errore_relativo_percento": None if abs(fonte) < 1e-12 else 100.0 * errore / fonte,
            }
        )
    return {
        "fonte": hens.get("fonte_benchmark", configurazione.get("fonte")),
        "righe": righe,
    }


def risolvi_modello(preparazione, log_output=False, tolleranza=1e-7):
    """Risolve il MILP HENS e ricostruisce rete e diagnostica.

    Riferimento bibliografico
    ------------------------
    BAR05, Sec. 2.9 e 3; TRA15, Eq. (11) e Sec. 3.

    Oggetti matematici
    ------------------
    TAC, utility duties, exchanger duties, aree, shell, topologia e residui.

    
    """

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
    carico_termico_utilities = {
        codice: valore(espressione)
        for codice, espressione in {
            **modello["Q_HU"],
            **modello["Q_CU"],
        }.items()
    }

    carico_termico_match = {}
    for (z, i, m, j, n), variabile in modello["q"].items():
        q_val = valore(variabile)
        if q_val > tolleranza:
            carico_termico_match[z, i, j] = carico_termico_match.get((z, i, j), 0.0) + q_val

    codici_virtuali = {
        u.codice
        for tipo in ("hot", "cold")
        for u in utilities[tipo]
        if getattr(u, "virtuale", False)
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
            "carico_termico_kW": carico_termico_match.get((z, i, j), 0.0),
        }
        if (
            i in codici_virtuali
            or j in codici_virtuali
            or getattr(tecnologie[t], "virtuale", False)
        ):
            match_virtuali.append(record)
        else:
            scambiatori.append(record)

    carico_termico_exchanger_individuale = {}
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
            carico_termico = cumulativi[k - 1] - (cumulativi[k - 2] if k > 1 else 0.0)
            carico_termico_exchanger_individuale[z, i, j, k] = carico_termico
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
                "carico_termico_kW": carico_termico,
            }
            if (
                i in codici_virtuali
                or j in codici_virtuali
                or getattr(tecnologie[x[4]], "virtuale", False)
            ):
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
            elif fH and hb[3] == he[3]:
                TinH = insiemi["T_intervallo"][z, hb[3]]["T_sup"]
                ToutH = insiemi["T_intervallo"][z, he[3]]["T_inf"]
            elif fH:
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
            elif fC and cb[3] == ce[3]:
                TinC = converti_temperatura(
                    insiemi["T_intervallo"][z, cb[3]]["T_inf"],
                    "cold", delta_T_min, "hens", "reale",
                )
                ToutC = converti_temperatura(
                    insiemi["T_intervallo"][z, ce[3]]["T_sup"],
                    "cold", delta_T_min, "hens", "reale",
                )
            elif fC:
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

    codici_VHU = {
        u.codice for u in utilities["hot"] if getattr(u, "virtuale", False)
    }
    codici_VCU = {
        u.codice for u in utilities["cold"] if getattr(u, "virtuale", False)
    }
    risultati_flessibili = []
    Q_virtuale_hot = 0.0
    Q_virtuale_cold = 0.0
    for codice, dati in preparazione["flussi_flessibili"].items():
        Q_totale = dati["CP_kW_K"] * (dati["T_out_max_C"] - dati["T_out_min_C"])
        if dati["tipo"] == "hot":
            Q_virtuale = sum(
                Q
                for (z, i, j), Q in carico_termico_match.items()
                if i == codice and j in codici_VCU
            )
            T_ottima = dati["T_out_min_C"] + Q_virtuale / dati["CP_kW_K"]
            Q_virtuale_hot += Q_virtuale
        else:
            Q_virtuale = sum(
                Q
                for (z, i, j), Q in carico_termico_match.items()
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
        u.codice: carico_termico_utilities.get(u.codice, 0.0)
        for tipo in ("hot", "cold")
        for u in utilities[tipo]
        if not getattr(u, "virtuale", False)
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
            "carico_termico_kW": carico_termico_utilities.get(u.codice, 0.0),
        }
        for tipo in ("hot", "cold")
        for u in utilities[tipo]
        if getattr(u, "virtuale", False)
    }

    processi = preparazione["configurazione"] ["flussi"]
    Q_hot_effettivo = (
        sum(f.calcola_Q() for f in processi if f.tipo == "hot") - Q_virtuale_hot
    )
    Q_cold_effettivo = (
        sum(f.calcola_Q() for f in processi if f.tipo == "cold") - Q_virtuale_cold
    )
    Q_HU_fisica = sum(
        carico_termico_utilities.get(u.codice, 0.0)
        for u in utilities["hot"]
        if not getattr(u, "virtuale", False)
    )
    Q_CU_fisica = sum(
        carico_termico_utilities.get(u.codice, 0.0)
        for u in utilities["cold"]
        if not getattr(u, "virtuale", False)
    )
    residuo_bilancio = Q_hot_effettivo + Q_HU_fisica - Q_cold_effettivo - Q_CU_fisica

    benchmark = (
        preparazione["configurazione"].get("hens", {}).get("benchmark_TAC_kUSD_year")
    )
    TAC = valore(modello["TAC"])



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

        # Le Eq. (13)-(14) con F_U sono diagnosticate solo quando F_U è
        # realmente presente (framework BAR05). In TRA15 i limiti utility
        # qhat/Y usano invece un Big-M energetico conservativo.
        F_U_hot = preparazione["parametri_utility_BAR05"]["F_U_hot"]
        F_U_cold = preparazione["parametri_utility_BAR05"]["F_U_cold"]

        if F_U_hot or F_U_cold:
            utilities_per_codice = {
                utility.codice: utility
                for tipo in ("hot", "cold")
                for utility in preparazione["utilities_HEN"][tipo]
                if not getattr(utility, "virtuale", False)
            }

            for codice, record in dettagli_13_14.items():
                if record["min_upper_slack_Y1_kW"] == float("inf"):
                    record["min_upper_slack_Y1_kW"] = None

                if codice in F_U_hot:
                    F_soluzione = valore(modello["F_H"][codice])
                    F_U = F_U_hot[codice]
                elif codice in F_U_cold:
                    F_soluzione = valore(modello["F_C"][codice])
                    F_U = F_U_cold[codice]
                else:
                    continue

                utility = utilities_per_codice[codice]
                delta_T_utility = abs(utility.T_in - utility.T_out)
                Q_massimo = F_U * delta_T_utility

                record.update(
                    {
                        "F_solution_kW_K": F_soluzione,
                        "Q_solution_kW": carico_termico_utilities[codice],
                        "Q_U_max_kW": Q_massimo,
                        "utilization_ratio": F_soluzione / F_U,
                    }
                )
            controlli_BAR05["BAR05_13_14_utility"] = dettagli_13_14
        else:
            controlli_BAR05["TRA15_utility_qhat_bounds"] = "Big-M energetico conservativo"
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
        u.codice
        for tipo in ("hot", "cold")
        for u in utilities[tipo]
        if getattr(u, "virtuale", False)
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
        for tipo in ("hot", "cold")
        for u in utilities[tipo]
        if getattr(u, "virtuale", False)
    ) and all(
        t.costo_fisso_USD_per_year == 0.0 and t.costo_area_USD_per_m2_year == 0.0
        for t in tecnologie.values() if getattr(t, "virtuale", False)
    )

    configurazione_effettiva = {
        "framework": preparazione["framework"],
        "delta_T_min_C": preparazione["configurazione"]["delta_T_min"],
        "delta_T_partition_max_C": preparazione["configurazione"][
            "delta_T_partition_max"
        ],
        "numero_intervalli_min": preparazione["configurazione"][
            "numero_intervalli_min"
        ],
        "separa_al_pinch": preparazione["separa_al_pinch"],
        "Amax_m2_per_tecnologia": {
            codice: tecnologia.A_max_m2
            for codice, tecnologia in tecnologie.items()
            if not getattr(tecnologia, "virtuale", False)
        },
        "qL": preparazione["bar05_qL"],
        "bar05_blocchi": preparazione["bar05_blocchi"],
    }

    return {
        "framework": preparazione["framework"],
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
        "gap_CPLEX": mdl.solve_details.gap,
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
        "hot_utility_totale_kW": Q_HU_fisica,
        "cold_utility_totale_kW": Q_CU_fisica,
        "calore_hot_process_totale_kW": Q_hot_effettivo,
        "calore_cold_process_totale_kW": Q_cold_effettivo,
        "carico_termico_exchanger_individuale_kW": carico_termico_exchanger_individuale,
        "temperature_exchangers": temperature_exchangers,
        "virtual_matches": match_virtuali,
        "carico_termico_match_kW": carico_termico_match,
        "matches_per_tecnologia": {
            t: sorted(tecnologia.matches) for t, tecnologia in tecnologie.items()
        },
        "residuo_bilancio_energia_kW": residuo_bilancio,
        "configurazione_HENS": configurazione_effettiva,
        "controlli_BAR05": controlli_BAR05,
    }

def _raggruppa_sequenze_match(indici, posizione_intervallo):
    """Raggruppa e ordina gli indici BAR05 per match e intervallo."""

    sequenze = {}
    for indice in indici:
        z, i, j, intervallo = indice
        sequenze.setdefault((z, i, j), []).append(intervallo)
    return {k: sorted(set(v)) for k, v in sequenze.items()}

# ============================================================================
# 10_POST_PROCESSING / 11_VALIDAZIONE_DIAGNOSTICA
# ============================================================================

def stampa_risultati(risultati):
    """Stampa TAC, utility, rete, area, temperature e bilanci.
    """

    separatore = "=" * 60
    scambiatori = sorted(
        risultati["scambiatori_fisici"],
        key=lambda x: (
            x["hot"], x["cold"], x["zona"], x["tecnologia"],
            x.get("exchanger_id", 1),
        ),
    )

    def titolo(testo):
        print(f"\n{separatore}\n{testo}\n{separatore}")

    def temperatura(valore):
        return "n.d." if valore is None else f"{valore:.3f}"

    def riga_exchanger(dati):
        return (
            f"{dati['hot']}-{dati['cold']} | {dati['tecnologia']} | "
            f"z={dati['zona']} | Q={dati['carico_termico_kW']:.3f} kW | "
            f"A={dati['area_m2']:.3f} m² | U={dati['U']:.0f} | "
            f"Th: {temperatura(dati.get('hot_Tin_C'))} -> "
            f"{temperatura(dati.get('hot_Tout_C'))} °C | "
            f"Tc: {temperatura(dati.get('cold_Tin_C'))} -> "
            f"{temperatura(dati.get('cold_Tout_C'))} °C"
        )

    titolo("MODELLO HENS")
    print(f"Framework: {risultati.get('framework', 'n.d.').upper()}")
    print(f"Status CPLEX: {risultati['status']}")
    print(f"Gap: {risultati['gap_CPLEX']:.6e}")
    print(f"Zone: {risultati['numero_zone']}")
    print(f"Intervalli: {risultati['numero_intervalli']}")
    print(f"Variabili: {risultati['numero_variabili']}")
    print(f"Vincoli: {risultati['numero_vincoli']}")
    print(f"Tempo solve: {risultati['tempo_CPLEX_s']:.3f} s")

    titolo("ECONOMIA")
    print(f"Costo HU: {risultati['costo_HU_USD_year']:,.2f} USD/year")
    print(f"Costo CU: {risultati['costo_CU_USD_year']:,.2f} USD/year")
    print(
        "Costo fisso HEX: "
        f"{risultati['costo_fisso_HEX_USD_year']:,.2f} USD/year"
    )
    print(
        "Costo area HEX: "
        f"{risultati['costo_area_HEX_USD_year']:,.2f} USD/year"
    )
    print(f"TAC: {risultati['TAC_USD_year']:,.2f} USD/year")
    print(f"TAC in kUSD/year: {risultati['TAC_USD_year'] / 1000.0:.6f}")

    titolo("UTILITIES")
    print(f"HU totale: {risultati['hot_utility_totale_kW']:.6f} kW")
    print(f"CU totale: {risultati['cold_utility_totale_kW']:.6f} kW")
    for codice, carico_termico in sorted(risultati["utilities_fisiche_kW"].items()):
        print(f"{codice} | carico_termico={carico_termico:.6f} kW")

    titolo("RETE HEN")
    print(f"Numero exchanger: {risultati['numero_exchanger_fisici']}")
    print(f"Numero shell: {risultati['numero_shell_fisiche']:.0f}")
    print(f"Area totale: {sum(x['area_m2'] for x in scambiatori):.3f} m²")
    for dati in scambiatori:
        print(riga_exchanger(dati))

    titolo("carico_termico AGGREGATI PER MATCH")
    gruppi = {}
    for dati in scambiatori:
        gruppi.setdefault((dati["hot"], dati["cold"]), []).append(dati)
    if not gruppi:
        print("Nessun exchanger fisico attivo")
    for (hot, cold), sezioni in sorted(gruppi.items()):
        carico_termico_totale = sum(x["carico_termico_kW"] for x in sezioni)
        print(
            f"{hot}-{cold} = {carico_termico_totale:.6f} kW | "
            f"exchanger={len(sezioni)}"
        )
        if len(sezioni) > 1:
            for numero, dati in enumerate(sezioni, 1):
                print(
                    f"  sezione {numero}: z={dati['zona']} | "
                    f"{dati['tecnologia']} | Q={dati['carico_termico_kW']:.6f} kW | "
                    f"A={dati['area_m2']:.6f} m² | U={dati['U']:.0f}"
                )

    titolo("BILANCI")
    q_hot = risultati["calore_hot_process_totale_kW"]
    q_cold = risultati["calore_cold_process_totale_kW"]
    hu = risultati["hot_utility_totale_kW"]
    cu = risultati["cold_utility_totale_kW"]
    print(f"Calore totale hot process: {q_hot:.6f} kW")
    print(f"Calore totale cold process: {q_cold:.6f} kW")
    print(f"HU: {hu:.6f} kW")
    print(f"CU: {cu:.6f} kW")
    print(f"HU-CU: {hu - cu:+.6f} kW")
    print(
        "Residuo energetico globale: "
        f"{risultati['residuo_bilancio_energia_kW']:+.6e} kW"
    )

    titolo("TEMPERATURE")
    for dati in scambiatori:
        print(
            f"{dati['hot']}-{dati['cold']} | {dati['tecnologia']} | "
            f"z={dati['zona']} | "
            f"Th: {temperatura(dati.get('hot_Tin_C'))} -> "
            f"{temperatura(dati.get('hot_Tout_C'))} °C | "
            f"Tc: {temperatura(dati.get('cold_Tin_C'))} -> "
            f"{temperatura(dati.get('cold_Tout_C'))} °C"
        )

def salva_validazione(preparazione, risultati, percorso_file):
    """Salva una validazione post-solve guidata dai ``benchmark_*`` del JSON.

    Ruolo
    -----
    Confronta grandezze globali, topologia aggregata, duty, area e dimensione
    MILP senza introdurre alcun dato benchmark nel modello matematico.

    Riferimento bibliografico
    -------------------------
    BAR05, Sec. 3 e Tabelle 1-20; TRA15, Sec. 3, Tabelle 1-2 e Figure 2-5.

    """

    from collections import Counter, defaultdict
    from pathlib import Path

    configurazione = preparazione["configurazione"]
    hens = configurazione.get("hens", {})
    nome = configurazione.get("nome", "caso HENS")

    def errore_percentuale(simulato, riferimento):
        if riferimento is None:
            return None
        riferimento = float(riferimento)
        if abs(riferimento) <= 1e-12:
            return 0.0 if abs(float(simulato)) <= 1e-12 else None
        return 100.0 * (float(simulato) - riferimento) / riferimento

    area_totale = sum(x["area_m2"] for x in risultati["scambiatori_fisici"])
    benchmark_exchangers = list(hens.get("benchmark_exchangers", []))
    benchmark_count = hens.get("benchmark_exchanger_count")
    if benchmark_count is None and benchmark_exchangers:
        benchmark_count = len(benchmark_exchangers)

    TAC_riferimento = None
    if "benchmark_TAC_kUSD_year" in hens:
        TAC_riferimento = 1000.0 * float(hens["benchmark_TAC_kUSD_year"])
    elif "benchmark_TAC_USD_year_exchanger_only" in hens:
        TAC_riferimento = float(hens["benchmark_TAC_USD_year_exchanger_only"])

    metriche = [
        ("TAC_USD_year", risultati["TAC_USD_year"], TAC_riferimento),
        ("hot_utility_kW", risultati["hot_utility_totale_kW"], hens.get("benchmark_hot_utility_kW")),
        ("cold_utility_kW", risultati["cold_utility_totale_kW"], hens.get("benchmark_cold_utility_kW")),
        ("numero_exchanger", risultati["numero_exchanger_fisici"], benchmark_count),
        ("numero_shell", risultati["numero_shell_fisiche"], hens.get("benchmark_shell_count")),
        ("area_totale_m2", area_totale, hens.get("benchmark_area_total_m2")),
    ]

    fonte_counter = Counter(
        (str(x["hot"]), str(x["cold"])) for x in benchmark_exchangers
    )
    simulato_counter = Counter(
        (str(x["hot"]), str(x["cold"]))
        for x in risultati["scambiatori_fisici"]
    )

    fonte_aggregata = defaultdict(lambda: {"Q": 0.0, "A": 0.0, "nA": 0})
    for x in benchmark_exchangers:
        chiave = (str(x["hot"]), str(x["cold"]))
        if "carico_termico_kW" in x:
            fonte_aggregata[chiave]["Q"] += float(x["carico_termico_kW"])
        if "area_m2" in x:
            fonte_aggregata[chiave]["A"] += float(x["area_m2"])
            fonte_aggregata[chiave]["nA"] += 1

    simulata_aggregata = defaultdict(lambda: {"Q": 0.0, "A": 0.0})
    for x in risultati["scambiatori_fisici"]:
        chiave = (str(x["hot"]), str(x["cold"]))
        simulata_aggregata[chiave]["Q"] += float(x["carico_termico_kW"])
        simulata_aggregata[chiave]["A"] += float(x["area_m2"])

    righe = [
        "=" * 100,
        f"VALIDAZIONE HENS GENERALE - {nome}",
        "=" * 100,
        f"Fonte: {configurazione.get('fonte', 'SOURCE_NOT_SPECIFIED')}",
        f"Status solver: {risultati['status']}",
        "",
        "GRANDEZZE GLOBALI",
        "-" * 100,
        f"{'Grandezza':<28}  {'Fonte':>22}  {'Simulato':>20}  {'Errore %':>22}",
    ]
    for etichetta, simulato, riferimento in metriche:
        fonte_testo = "SOURCE_NOT_SPECIFIED" if riferimento is None else f"{float(riferimento):.6f}"
        errore = errore_percentuale(simulato, riferimento)
        errore_testo = "NOT_REPORTED_BY_SOURCE" if riferimento is None else (
            "UNDEFINED" if errore is None else f"{errore:+.6f}"
        )
        righe.append(
            f"{etichetta:<28}  {fonte_testo:>22}  {float(simulato):>20.6f}  {errore_testo:>22}"
        )

    righe.extend(["", "TOPOLOGIA COME MULTINSIEME DI MATCH", "-" * 100])
    if not benchmark_exchangers:
        righe.append("NOT_REPORTED_BY_SOURCE")
    else:
        differenza_conteggi = sum(
            abs(fonte_counter[chiave] - simulato_counter[chiave])
            for chiave in set(fonte_counter) | set(simulato_counter)
        )
        totale_fonte = sum(fonte_counter.values())
        errore_topologia = (
            100.0 * differenza_conteggi / totale_fonte
            if totale_fonte
            else 0.0
        )
        righe.append(f"Errore conteggi topologia [%]: {errore_topologia:+.6f}")
        for chiave in sorted(set(fonte_counter) | set(simulato_counter)):
            righe.append(
                f"{chiave[0]}-{chiave[1]}: fonte={fonte_counter[chiave]}, "
                f"simulato={simulato_counter[chiave]}"
            )

    righe.extend([
        "",
        "DUTY E AREA AGGREGATI PER MATCH",
        "-" * 100,
        f"{'Match':<18}{'Q fonte':>14}{'Q simulato':>14}{'Errore Q %':>16}"
        f"{'A fonte':>14}{'A simulata':>14}{'Errore A %':>16}",
    ])
    for chiave in sorted(set(fonte_aggregata) | set(simulata_aggregata)):
        fonte = fonte_aggregata.get(chiave)
        simulato = simulata_aggregata.get(chiave, {"Q": 0.0, "A": 0.0})
        Q_ref = None if fonte is None else fonte["Q"]
        A_ref = None if fonte is None or fonte["nA"] == 0 else fonte["A"]
        q_ref_testo = "n.d." if Q_ref is None else f"{Q_ref:.3f}"
        a_ref_testo = "n.d." if A_ref is None else f"{A_ref:.3f}"
        errore_Q = errore_percentuale(simulato["Q"], Q_ref)
        errore_A = errore_percentuale(simulato["A"], A_ref)
        errore_Q_testo = "n.d." if Q_ref is None else (
            "UNDEFINED" if errore_Q is None else f"{errore_Q:+.6f}"
        )
        errore_A_testo = "n.d." if A_ref is None else (
            "UNDEFINED" if errore_A is None else f"{errore_A:+.6f}"
        )
        righe.append(
            f"{chiave[0]+'-'+chiave[1]:<18}{q_ref_testo:>14}{simulato['Q']:>14.3f}"
            f"{errore_Q_testo:>16}{a_ref_testo:>14}{simulato['A']:>14.3f}"
            f"{errore_A_testo:>16}"
        )

    righe.extend([
        "",
        "DIMENSIONE MILP",
        "-" * 100,
        f"Variabili: {risultati['numero_variabili']}",
        f"Binarie: {risultati['numero_binarie']}",
        f"Vincoli: {risultati['numero_vincoli']}",
        f"Intervalli: {risultati['numero_intervalli']}",
        f"Zone: {risultati['numero_zone']}",
        "",
        
    ])

    percorso = Path(percorso_file)
    percorso.parent.mkdir(parents=True, exist_ok=True)
    percorso.write_text("\n".join(righe) + "\n", encoding="utf-8")
    return percorso

