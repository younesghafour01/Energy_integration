"""Estensione TRA15 del core HENS BAR05.

Architettura del modulo
------------------------------------
1_INPUT-5_DISCRETIZZAZIONE: il core BAR05 costruisce correnti, utility fisiche,
    partizione e insiemi base; questo modulo aggiunge tecnologie multiple,
    flexible streams, utility virtuali e gli insiemi TRA15.
6_VARIABILI / 7_VINCOLI: riuso del modello BAR05 e del non-isothermal mixing
    Eq. (7)-(10), con aggiunta dei domini indicizzati per tecnologia.
8_FUNZIONE_OBIETTIVO: TRA15 Eq. (11), costruita nel core comune.
9_SOLVE: preparazione e risoluzione TRA15.
10_POST_PROCESSING: estrazione e stampa della rete.
11_VALIDAZIONE_DIAGNOSTICA: confronto con TRA15 Test 1.

"""

from __future__ import annotations



from pathlib import Path

from src.hens.BAR05_hens import (
    _prepara_modello as prepara_modello_base,
    UtilityHEN,
    aggiungi_mixing_non_isotermo,
    costruisci_insiemi_base,
    converti_temperatura,
    risolvi_modello as risolvi_modello_base,
)


class UtilityVirtualeTRA15(UtilityHEN):
    """Utility virtuale introdotta da TRA15 per una surplus part."""

    def __init__(self, **dati):
        super().__init__(**dati)
        self.virtuale = True

class TecnologiaHEN:
    """Rappresenta una tecnologia HEX candidata e i relativi match ammessi.

    È l'estensione TRA15 del modello base BAR05: ``FHEX_t`` corregge l'area e
    ``P_t`` limita gli accoppiamenti (TRA15, Sec. 2.2.2, Eq. (6)-(11)).
    """

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
        """Memorizza prestazioni, limiti d'area, costi e insieme P_t."""
        self.codice = str(codice)
        self.nome = str(nome)

        self.fattore_area = float(FHEX)
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


def costruisci_tecnologie(configurazione):
    """Costruisce tecnologie abilitate e insiemi di match ``P_t``.

    Riferimento bibliografico
    ------------------------
    TRA15, Sec. 2.2.2, definizione di ``T`` e ``P_t``, Eq. (6)-(11).

    Oggetti matematici
    ------------------
    ``T``, ``P_t``, ``FHEX_t``, ``A_ijt^max``, ``c_ijt^F`` e ``c_ijt^A``.

    Input / Output
    --------------
    Converte ``hens.technologies`` in oggetti :class:`TecnologiaHEN` e mappe
    indicizzate per codice tecnologia.
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
    match_per_configurazione = {t: set(tecnologie[t].matches) for t in T}
    if not T:
        raise ValueError("Nessuna tecnologia HENS abilitata.")
    return {
        "T": T,
        "tecnologie": tecnologie,
        "match_per_configurazione": match_per_configurazione,
    }


def costruisci_flussi_flessibili(configurazione):
    """Valida e indicizza le flexible streams dichiarate nel JSON.

    Il flusso nominale rappresenta la corrente completa: ``T_out`` coincide
    con ``T_out_min_C`` per una hot stream e con ``T_out_max_C`` per una cold
    stream. Il tratto tra i due limiti e la surplus part.

    Riferimento bibliografico
    ------------------------
    TRA15, Sec. 2.2.3, insiemi ``HF_z``/``CF_z`` e intervallo
    ``(T_out^L, T_out^U)``.

    Oggetti matematici
    ------------------
    Flexible streams e relative surplus parts.

    Note implementative
    --------------------
    Il dizionario indicizzato per codice è una IMPLEMENTATION CHOICE; i limiti
    dichiarati non vengono modificati.
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


def estrai_estremi_termici_flessibili(flussi_flessibili):
    """Restituisce gli estremi reali aggiunti alla partizione da TRA15."""
    return [
        (temperatura, dati["tipo"])
        for dati in flussi_flessibili.values()
        for temperatura in (dati["T_out_min_C"], dati["T_out_max_C"])
    ]




def costruisci_utilities_virtuali(
    intervalli,
    flussi_flessibili,
    flussi,
    delta_T_min,
    delta_T_partition_max,
):
    """Crea le utility virtuali delle surplus parts flessibili.

    Riferimento bibliografico
    ------------------------
    TRA15, Sec. 2.2.3, Eq. (12)-(13).

    Oggetti matematici
    ------------------
    Virtual hot utility ``i_v`` e virtual cold utility ``j_v``.

    Gli estremi sono ricavati da una partizione preliminare priva di utility
    virtuali. Le temperature della cold utility vengono memorizzate sulla
    scala reale; la traslazione ``+delta_T_min`` le riporta ai valori di
    TRA15 Eq. (13) sulla scala HENS.

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
            UtilityVirtualeTRA15(
                codice="VHU",
                nome="Virtual hot utility",
                tipo="hot",
                T_in=T_sup + estensione,
                T_out=T_sup,
                h_W_m2K=h_default,
                costo_USD_per_kW_year=0.0,
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
            UtilityVirtualeTRA15(
                codice="VCU",
                nome="Virtual cold utility",
                tipo="cold",
                T_in=T_out_reale - estensione,
                T_out=T_out_reale,
                h_W_m2K=h_default,
                costo_USD_per_kW_year=0.0,
            )
        )

    return virtuali


def aggiungi_tecnologia_virtuale(
    tecnologie_HEN,
    utilities_HEN,
    flussi_flessibili,
):
    """Aggiunge la tecnologia HEX gratuita ai soli match virtuali.

    Riferimento bibliografico
    ------------------------
    TRA15, Sec. 2.2.3, paragrafo successivo alle Eq. (14)-(15).

    Oggetti matematici
    ------------------
    Tecnologia virtuale, insieme ``P_t`` e costi nulli.
    """

    VHU = [
        u.codice for u in utilities_HEN["hot"]
        if getattr(u, "virtuale", False)
    ]
    VCU = [
        u.codice for u in utilities_HEN["cold"]
        if getattr(u, "virtuale", False)
    ]
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
    tecnologie_HEN["match_per_configurazione"][codice] = set(matches)
    return tecnologie_HEN

# ============================================================================
# 3_INSIEMI_E_INDICI - INSIEMI HENS, MATCH E DOMINI DI TRASPORTO
# ============================================================================


def forza_temperature_uscita_flessibili(
    modello_HEN,
    insiemi_HEN,
    flussi_flessibili,
    target_per_stream,
):
    """Aggiunge un vincolo diagnostico su ``T_out`` di una flexible stream.

    Riferimento bibliografico
    ------------------------
    IMPLEMENTATION CHOICE - non direttamente definita da TRA15.

    Oggetti matematici
    ------------------
    Carico della surplus part, equivalente a un target di temperatura d'uscita.

    Serve esclusivamente per sensitivity test; se target_per_stream è vuoto
    non modifica il modello.
    """

    if not target_per_stream:
        return modello_HEN

    mdl = modello_HEN["modello"]
    q = modello_HEN["q"]

    VHU = {
        codice
        for z in insiemi_HEN["Z"]
        for codice in insiemi_HEN.get("VHU", {}).get(z, [])
    }
    VCU = {
        codice
        for z in insiemi_HEN["Z"]
        for codice in insiemi_HEN.get("VCU", {}).get(z, [])
    }

    vincoli = []

    for codice, T_target in target_per_stream.items():

        if codice not in flussi_flessibili:
            raise ValueError(
                f"{codice} non è una flexible stream."
            )

        dati = flussi_flessibili[codice]
        T_target = float(T_target)

        T_min = dati["T_out_min_C"]
        T_max = dati["T_out_max_C"]
        CP = dati["CP_kW_K"]

        if not (T_min <= T_target <= T_max):
            raise ValueError(
                f"T_out forzata di {codice} fuori range: "
                f"{T_target} °C non appartiene a [{T_min}, {T_max}]."
            )

        if dati["tipo"] == "hot":

            Q_virtuale_target = CP * (T_target - T_min)

            indici_virtuali = [
                indice
                for indice in modello_HEN["q"]
                if indice[1] == codice and indice[3] in VCU
            ]

        else:

            Q_virtuale_target = CP * (T_max - T_target)

            indici_virtuali = [
                indice
                for indice in modello_HEN["q"]
                if indice[3] == codice and indice[1] in VHU
            ]

        if not indici_virtuali:
            raise RuntimeError(
                f"Nessun match virtuale trovato per {codice}."
            )

        vincoli.append(
            mdl.add_constraint(
                mdl.sum(q[indice] for indice in indici_virtuali)
                == Q_virtuale_target,
                ctname=f"DIAG_Tout_{codice}_{T_target:g}",
            )
        )

    modello_HEN["vincoli_Tout_flessibile_diagnostica"] = vincoli

    return modello_HEN


def costruisci_insiemi_estesi(
    flussi,
    utilities,
    intervalli,
    delta_T_min,
    match_permessi=None,
    NI_H=None,
    NI_C=None,
    flexible_streams=None,
):
    """Estende gli insiemi BAR05 con flexible streams e utility virtuali."""
    insiemi = costruisci_insiemi_base(
        flussi=flussi,
        utilities=utilities,
        intervalli=intervalli,
        delta_T_min=delta_T_min,
        match_permessi=match_permessi,
        NI_H=NI_H,
        NI_C=NI_C,
    )
    Z, H, C = insiemi["Z"], insiemi["H"], insiemi["C"]
    HU, CU = insiemi["HU"], insiemi["CU"]
    M_i, N_j = insiemi["M_i"], insiemi["N_j"]
    T_intervallo = insiemi["T_intervallo"]
    flexible_streams = flexible_streams or {}
    virtual_hot = {
        u.codice for u in utilities.get("hot", [])
        if getattr(u, "virtuale", False)
    }
    virtual_cold = {
        u.codice for u in utilities.get("cold", [])
        if getattr(u, "virtuale", False)
    }
    VHU = {z: [i for i in HU[z] if i in virtual_hot] for z in Z}
    VCU = {z: [j for j in CU[z] if j in virtual_cold] for z in Z}
    HF = {
        z: [i for i in H[z] if i in flexible_streams
            and flexible_streams[i]["tipo"] == "hot"]
        for z in Z
    }
    CF = {
        z: [j for j in C[z] if j in flexible_streams
            and flexible_streams[j]["tipo"] == "cold"]
        for z in Z
    }

    def intervalli_surplus(z, codice, indici):
        dati = flexible_streams[codice]
        T_min = converti_temperatura(
            dati["T_out_min_C"], dati["tipo"], delta_T_min, "reale", "hens"
        )
        T_max = converti_temperatura(
            dati["T_out_max_C"], dati["tipo"], delta_T_min, "reale", "hens"
        )
        return [
            indice for indice in indici
            if T_intervallo[z, indice]["T_sup"] <= T_max + 1e-9
            and T_intervallo[z, indice]["T_inf"] >= T_min - 1e-9
        ]

    insiemi.update(
        {
            "VHU": VHU,
            "VCU": VCU,
            "HF": HF,
            "CF": CF,
            "MF": {
                (z, i): intervalli_surplus(z, i, M_i[z, i])
                for z in Z for i in HF[z]
            },
            "NF": {
                (z, j): intervalli_surplus(z, j, N_j[z, j])
                for z in Z for j in CF[z]
            },
            "flexible_streams": flexible_streams,
        }
    )
    return insiemi


def genera_indici_scambio(insiemi_HEN, tolleranza=1e-09):
    """Genera gli indici ``q[z,i,m,j,n]`` termicamente ammissibili.

    Riferimento bibliografico
    ------------------------
    BAR05, Sec. 2.1, insieme ``P`` e insiemi ``P_im^H``/``P_jn^C``;
    TRA15, Eq. (14)-(15), esclusioni delle utility virtuali.

    Oggetti matematici
    ------------------
    Variabile di trasporto ``q_im,jn^z``.

    Input / Output
    --------------
    Restituisce tuple canoniche ``(z, i, m, j, n)``.

    Note implementative
    --------------------
    Le esclusioni virtuali sono applicate prima della creazione delle variabili,
    senza creare variabili ``q`` fissate artificialmente a zero.
    """
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


ALL_BLOCKS = {
    "1",
    "2",
    "3A",
    "3B",
    "3C",
    "3D",
    "4A",
    "4B",
    "4C",
    "4D",
    "4E",
    "4F",
    "5A",
    "5B",
    "7",
}


# ============================================================
# 1_INPUT-5_DISCRETIZZAZIONE - ACCESSO AL CORE COMUNE
# ============================================================

def _modello(preparazione):
    """Restituisce il modello DOcplex dalla preparazione comune."""
    return preparazione["modello_HEN"]["modello"]


def _q(preparazione):
    """Restituisce le variabili ``q[z,i,m,j,n]`` del core BAR05."""
    return preparazione["modello_HEN"]["q"]


def _valore(var):
    """Legge un valore DOcplex; IMPLEMENTATION CHOICE di post-processing."""
    try:
        return float(var.solution_value)
    except Exception:
        try:
            return float(var)
        except Exception:
            return None


# ============================================================
# 3_INSIEMI_E_INDICI - STREAMS SOGGETTE A NON-ISOTHERMAL MIXING
# ============================================================

def individua_correnti_mixing_non_isotermo(preparazione):
    """Costruisce ``NIH`` e ``NIC`` con tutte le process streams.

    Riferimento bibliografico
    ------------------------
    BAR05, Sec. 2.1, insiemi ``NIH`` e ``NIC``; TRA15, Sec. 2.1.1 richiama
    tali insiemi. L'attivazione su tutte le process streams è una
    IMPLEMENTATION CHOICE - non direttamente definita da TRA15.

    Input / Output
    --------------
    Restituisce due liste ordinate di codici, escludendo le utility.
    """

    insiemi = preparazione["insiemi_HEN"]

    NIH = set()
    NIC = set()

    for z in insiemi["Z"]:

        NIH.update(
            set(insiemi["H"][z])
            - set(insiemi["HU"][z])
        )

        NIC.update(
            set(insiemi["C"][z])
            - set(insiemi["CU"][z])
        )

    return sorted(NIH), sorted(NIC)


# ============================================================
# 3_INSIEMI_E_INDICI - GRUPPI q PER INTERVALLO
# ============================================================

# ============================================================
# 9_SOLVE - PREPARAZIONE COMPLETA TRA15
# ============================================================

def prepara_modello(
    sorgente,
    delta_T_partition_max=2.5,
    numero_intervalli_min=1,
    separa_al_pinch=False,
    non_isothermal_mixing=True,
):
    """Costruisce il modello TRA15 sul core comune BAR05.

    Riferimento bibliografico
    ------------------------
    TRA15, Sec. 2.1-2.2, Eq. (1)-(15); BAR05 Eq. (7)-(10) per il mixing non
    isotermo.

    Oggetti matematici
    ------------------
    Modello base, tecnologie ``T``/``P_t``, flexible streams e ``qbar``.

    Note implementative
    --------------------
    Default storici preservati: passo 2.5 °C, almeno un intervallo, una zona
    salvo input contrario e mixing NI completo.
    """

    preparazione = prepara_modello_base(
        sorgente,

        delta_T_partition_max=
            float(delta_T_partition_max),

        numero_intervalli_min=
            int(numero_intervalli_min),

        separa_al_pinch=
            bool(separa_al_pinch),

        bar05_blocchi=
            set(ALL_BLOCKS),

        framework="tra15",

        estensione={
            "costruisci_flussi_flessibili": costruisci_flussi_flessibili,
            "estremi_termici": estrai_estremi_termici_flessibili,
            "costruisci_utilities_virtuali": costruisci_utilities_virtuali,
            "costruisci_tecnologie": costruisci_tecnologie,
            "costruisci_insiemi": costruisci_insiemi_estesi,
            "genera_indici_scambio": genera_indici_scambio,
            "aggiungi_tecnologia_virtuale": aggiungi_tecnologia_virtuale,
            "forza_temperature_uscita_flessibili":
                forza_temperature_uscita_flessibili,
        },
    )

    if non_isothermal_mixing:

        NIH, NIC = individua_correnti_mixing_non_isotermo(
            preparazione
        )

        informazioni_mixing = aggiungi_mixing_non_isotermo(
            preparazione,
            NIH,
            NIC,
        )
        preparazione["non_isothermal_mixing_TRA15"] = informazioni_mixing

    return preparazione


# ============================================================
# 9_SOLVE - RISOLUZIONE
# ============================================================
def risolvi_modello(
    preparazione,
    log_output=False,
    time_limit_s=10800,
    mip_gap=1e-7,
    threads=1,
):
    """Risolve il modello TRA15 con il core comune BAR05/TRA15.

    Riferimento bibliografico
    ------------------------
    TRA15, Eq. (11), minimizzazione del costo annuale.

    Oggetti matematici
    ------------------
    Tutte le variabili del core e le Eq. BAR05 (7)-(10) aggiunte dal mixing.

    Note implementative
    --------------------
    Parametri CPLEX, seed, limite temporale e gap sono preservati.
    """

    mdl = _modello(preparazione)

    try:
        mdl.parameters.threads = int(threads)
        mdl.parameters.randomseed = 20260823

        mdl.parameters.mip.tolerances.mipgap = float(mip_gap)
        mdl.parameters.mip.tolerances.absmipgap = float(mip_gap)

        mdl.parameters.timelimit = float(time_limit_s)

    except Exception:
        pass

    # Usa il solver/estrattore completo già presente nel core.
    risultati = risolvi_modello_base(
        preparazione,
        log_output=log_output,
        tolleranza=1e-6,
    )

    # Alias comodi specifici TRA15.
    risultati["feasible"] = True

    risultati["TAC_kUSD_year"] = (
        risultati["TAC_USD_year"] / 1000.0
    )

    risultati["HU_kW"] = (
        risultati["hot_utility_totale_kW"]
    )

    risultati["CU_kW"] = (
        risultati["cold_utility_totale_kW"]
    )

    risultati["gap"] = risultati.get(
        "gap_CPLEX",
        0.0,
    )

    risultati["tempo_solve_s"] = risultati.get(
        "tempo_CPLEX_s",
        0.0,
    )

    return risultati

# ============================================================
# 10_POST_PROCESSING - ESTRAZIONE RISULTATI
# ============================================================

def estrai_risultati(
    preparazione,
):
    """Estrae TAC, utility duties e carichi aggregati per match.

    Riferimento bibliografico
    ------------------------
    TRA15, Sec. 3 e Tabelle 1-2. Funzione di post-processing; non modifica il
    modello matematico.

    Oggetti matematici
    ------------------
    Obiettivo TAC, ``F_i^H``, ``F_j^C`` e somma delle ``q`` per ``(i,j)``.
    """

    mdl = _modello(preparazione)

    insiemi = preparazione[
        "insiemi_HEN"
    ]

    q = _q(preparazione)

    try:
        TAC_USD_year = float(
            mdl.objective_value
        )
    except Exception:
        TAC_USD_year = float(
            mdl.objective_expr.solution_value
        )

    HU = 0.0
    CU = 0.0

    carico_termico_match = {}

    for indice, variabile in q.items():

        z, i, m, j, n = indice[:5]

        valore = _valore(variabile)

        if valore is None:
            continue

        if i in insiemi["HU"][z]:
            HU += valore

        if j in insiemi["CU"][z]:
            CU += valore

        chiave = f"{i}-{j}"

        carico_termico_match[chiave] = (
            carico_termico_match.get(
                chiave,
                0.0,
            )
            + valore
        )

    carico_termico_match = {
        chiave: valore
        for chiave, valore
        in sorted(carico_termico_match.items())
        if abs(valore) > 1e-6
    }

    return {
        "TAC_USD_year":
            TAC_USD_year,

        "TAC_kUSD_year":
            TAC_USD_year / 1000.0,

        "HU_kW":
            HU,

        "CU_kW":
            CU,

        "duties_kW":
            carico_termico_match,
    }


# ============================================================
# 10_POST_PROCESSING / 11_VALIDAZIONE_DIAGNOSTICA
# ============================================================
def stampa_risultati(risultati):
    """Stampa economia, rete, temperature, area e bilancio TRA15.

    Riferimento bibliografico
    ------------------------
    TRA15, Sec. 3, Tabelle 1-2 e Fig. 2-5. Il formato è una
    IMPLEMENTATION CHOICE.
    """

    separatore = "=" * 80

    def titolo(nome):
        print(f"\n{separatore}")
        print(nome)
        print(separatore)

    def temp(x):
        if x is None:
            return "n.d."
        return f"{x:.3f}"

    # ========================================================
    # MODELLO
    # ========================================================

    titolo("MODELLO HENS TRA15")

    print(
        f"Status CPLEX: "
        f"{risultati.get('status')}"
    )

    print(
        f"Gap: "
        f"{risultati.get('gap_CPLEX', 0.0):.6e}"
    )

    print(
        f"Zone: "
        f"{risultati.get('numero_zone')}"
    )

    print(
        f"Intervalli: "
        f"{risultati.get('numero_intervalli')}"
    )

    print(
        f"Variabili totali: "
        f"{risultati.get('numero_variabili')}"
    )

    print(
        f"Variabili binarie: "
        f"{risultati.get('numero_binarie')}"
    )

    print(
        f"Vincoli: "
        f"{risultati.get('numero_vincoli')}"
    )

    print(
        f"Tempo solve: "
        f"{risultati.get('tempo_CPLEX_s', 0.0):.3f} s"
    )

    # ========================================================
    # ECONOMIA
    # ========================================================

    titolo("ECONOMIA")

    print(
        f"Costo HU: "
        f"{risultati['costo_HU_USD_year']:,.2f} USD/year"
    )

    print(
        f"Costo CU: "
        f"{risultati['costo_CU_USD_year']:,.2f} USD/year"
    )

    print(
        f"Costo fisso HEX: "
        f"{risultati['costo_fisso_HEX_USD_year']:,.2f} USD/year"
    )

    print(
        f"Costo area HEX: "
        f"{risultati['costo_area_HEX_USD_year']:,.2f} USD/year"
    )

    print(
        f"TAC: "
        f"{risultati['TAC_USD_year']:,.2f} USD/year"
    )

    print(
        f"TAC: "
        f"{risultati['TAC_USD_year']/1000.0:.6f} "
        f"kUSD/year"
    )

    # ========================================================
    # UTILITIES
    # ========================================================

    titolo("UTILITIES")

    print(
        f"HU totale: "
        f"{risultati['hot_utility_totale_kW']:.6f} kW"
    )

    print(
        f"CU totale: "
        f"{risultati['cold_utility_totale_kW']:.6f} kW"
    )

    # ========================================================
    # RETE
    # ========================================================

    titolo("RETE HEN")

    scambiatori = sorted(
        risultati["scambiatori_fisici"],
        key=lambda x: (
            x["hot"],
            x["cold"],
            x["zona"],
            x.get("exchanger_id", 1),
        ),
    )

    area_totale = sum(
        x["area_m2"]
        for x in scambiatori
    )

    print(
        f"Numero exchanger: "
        f"{risultati['numero_exchanger_fisici']}"
    )

    print(
        f"Numero shell: "
        f"{risultati['numero_shell_fisiche']:.0f}"
    )

    print(
        f"Area totale: "
        f"{area_totale:.3f} m²"
    )

    for x in scambiatori:

        print(
            f"{x['hot']}-{x['cold']} | "
            f"{x['tecnologia']} | "
            f"z={x['zona']} | "
            f"Q={x['carico_termico_kW']:.3f} kW | "
            f"A={x['area_m2']:.3f} m² | "
            f"U={x['U']:.0f} | "
            f"Th: "
            f"{temp(x.get('hot_Tin_C'))} -> "
            f"{temp(x.get('hot_Tout_C'))} °C | "
            f"Tc: "
            f"{temp(x.get('cold_Tin_C'))} -> "
            f"{temp(x.get('cold_Tout_C'))} °C"
        )

    # ========================================================
    # carico_termico AGGREGATI
    # ========================================================

    titolo("CARICHI TERMICI AGGREGATI PER MATCH")

    carico_termico = {}

    for x in scambiatori:

        key = (
            x["hot"],
            x["cold"],
        )

        carico_termico[key] = (
            carico_termico.get(key, 0.0)
            + x["carico_termico_kW"]
        )

    for (hot, cold), q in sorted(
        carico_termico.items()
    ):
        print(
            f"{hot}-{cold} = "
            f"{q:.6f} kW"
        )

    # ========================================================
    # TEMPERATURE
    # ========================================================

    titolo("TEMPERATURE INTERNE DELLA RETE")

    print(
        f"{'Match':<12}"
        f"{'Th,in':>12}"
        f"{'Th,out':>12}"
        f"{'Tc,in':>12}"
        f"{'Tc,out':>12}"
    )

    for x in scambiatori:

        print(
            f"{x['hot']+'-'+x['cold']:<12}"
            f"{temp(x.get('hot_Tin_C')):>12}"
            f"{temp(x.get('hot_Tout_C')):>12}"
            f"{temp(x.get('cold_Tin_C')):>12}"
            f"{temp(x.get('cold_Tout_C')):>12}"
        )

    # ========================================================
    # BILANCIO
    # ========================================================

    titolo("BILANCIO ENERGETICO")

    print(
        f"Hot process: "
        f"{risultati['calore_hot_process_totale_kW']:.6f} kW"
    )

    print(
        f"Cold process: "
        f"{risultati['calore_cold_process_totale_kW']:.6f} kW"
    )

    print(
        f"HU: "
        f"{risultati['hot_utility_totale_kW']:.6f} kW"
    )

    print(
        f"CU: "
        f"{risultati['cold_utility_totale_kW']:.6f} kW"
    )

    print(
        f"Residuo globale: "
        f"{risultati['residuo_bilancio_energia_kW']:+.6e} kW"
    )

def salva_validazione_test1(
    preparazione,
    risultati,
    percorso_file,
):
    """Salva il confronto automatico con il Test 1 pubblicato.

    Riferimento bibliografico
    ------------------------
    TRA15, Sec. 3, Tabella 2 e Fig. 2.

    Oggetti matematici
    ------------------
    TAC, HU, CU, topologia, duties e temperature degli exchanger.

    Note implementative
    --------------------
    I benchmark sono applicati soltanto dopo il solve e non entrano nel MILP.
    """

    benchmark_TAC = 181.0
    benchmark_HU = 204.0
    benchmark_CU = 182.0

    benchmark = {
        ("H3", "C1"): {
            "Q": 204.0,
            "Th_in": 180.0,
            "Th_out": 179.0,
            "Tc_in": 117.0,
            "Tc_out": 155.0,
        },

        ("H1", "C3"): {
            "Q": 182.0,
            "Th_in": 110.0,
            "Th_out": 45.0,
            "Tc_in": 15.0,
            "Tc_out": 25.0,
        },

        ("H1", "C1"): {
            "Q": 85.0,
            "Th_in": 175.0,
            "Th_out": 145.0,
            "Tc_in": 105.0,
            "Tc_out": 117.0,
        },

        ("H1", "C2"): {
            "Q": 94.0,
            "Th_in": 145.0,
            "Th_out": 110.0,
            "Tc_in": 89.0,
            "Tc_out": 112.0,
        },

        ("H2", "C1"): {
            "Q": 461.0,
            "Th_in": 125.0,
            "Th_out": 65.0,
            "Tc_in": 20.0,
            "Tc_out": 105.0,
        },

        ("H2", "C2"): {
            "Q": 206.0,
            "Th_in": 125.0,
            "Th_out": 65.0,
            "Tc_in": 40.0,
            "Tc_out": 89.0,
        },
    }

    scambiatori = risultati[
        "scambiatori_fisici"
    ]

    simulati = {
        (x["hot"], x["cold"]): x
        for x in scambiatori
        if x["carico_termico_kW"] > 1e-7
    }

    righe = []

    def scrivi(testo=""):
        righe.append(testo)

    def errore_percentuale(sim, ref):
        if abs(ref) <= 1e-12:
            return 0.0

        return (
            100.0
            * (sim - ref)
            / ref
        )

    scrivi("=" * 110)
    scrivi("VALIDAZIONE TRA15 - TEST 1")
    scrivi("=" * 110)

    # ========================================================
    # RISULTATO GENERALE
    # ========================================================

    TAC_sim = (
        risultati["TAC_USD_year"]
        / 1000.0
    )

    HU_sim = risultati[
        "hot_utility_totale_kW"
    ]

    CU_sim = risultati[
        "cold_utility_totale_kW"
    ]

    scrivi("\nRISULTATI GLOBALI")
    scrivi("-" * 80)

    scrivi(
        f"{'Grandezza':<25}"
        f"{'TRA15':>15}"
        f"{'Modello':>15}"
        f"{'Delta':>15}"
        f"{'Errore %':>15}"
    )

    dati_globali = [
        (
            "TAC [kUSD/y]",
            benchmark_TAC,
            TAC_sim,
        ),
        (
            "HU [kW]",
            benchmark_HU,
            HU_sim,
        ),
        (
            "CU [kW]",
            benchmark_CU,
            CU_sim,
        ),
    ]

    for nome, ref, sim in dati_globali:

        scrivi(
            f"{nome:<25}"
            f"{ref:>15.6f}"
            f"{sim:>15.6f}"
            f"{sim-ref:>+15.6f}"
            f"{errore_percentuale(sim,ref):>+15.4f}"
        )

    # ========================================================
    # TOPOLOGIA
    # ========================================================

    topologia_fonte = set(
        benchmark.keys()
    )

    topologia_modello = set(
        simulati.keys()
    )

    mancanti = (
        topologia_fonte
        - topologia_modello
    )

    aggiuntivi = (
        topologia_modello
        - topologia_fonte
    )

    scrivi("\nTOPOLOGIA")
    scrivi("-" * 80)

    scrivi(
        f"HEX fonte   : "
        f"{len(topologia_fonte)}"
    )

    scrivi(
        f"HEX modello : "
        f"{len(topologia_modello)}"
    )

    scrivi(
        "Match mancanti: "
        + (
            ", ".join(
                f"{h}-{c}"
                for h, c in sorted(mancanti)
            )
            if mancanti
            else "nessuno"
        )
    )

    scrivi(
        "Match aggiuntivi: "
        + (
            ", ".join(
                f"{h}-{c}"
                for h, c in sorted(aggiuntivi)
            )
            if aggiuntivi
            else "nessuno"
        )
    )

    scrivi(
        "Esito topologia: "
        + (
            "OK - IDENTICA"
            if not mancanti
            and not aggiuntivi
            else "DIFFERENTE"
        )
    )

    # ========================================================
    # CARICHI TERMICI
    # ========================================================

    scrivi("\nCARICO TERMICO PER EXCHANGER")
    scrivi("-" * 90)

    scrivi(
        f"{'Match':<12}"
        f"{'TRA15 [kW]':>16}"
        f"{'Modello [kW]':>16}"
        f"{'Delta [kW]':>16}"
        f"{'Errore %':>16}"
    )

    errori_carico_termico = []

    for match, ref in benchmark.items():

        sim = simulati.get(match)

        Q_sim = (
            0.0
            if sim is None
            else sim["carico_termico_kW"]
        )

        errore = abs(
            Q_sim - ref["Q"]
        )

        errori_carico_termico.append(
            errore
        )

        scrivi(
            f"{match[0]+'-'+match[1]:<12}"
            f"{ref['Q']:>16.3f}"
            f"{Q_sim:>16.3f}"
            f"{Q_sim-ref['Q']:>+16.3f}"
            f"{errore_percentuale(Q_sim,ref['Q']):>+16.3f}"
        )

    MAE_carico_termico = (
        sum(errori_carico_termico)
        / len(errori_carico_termico)
    )

    scrivi(
        f"\nMAE carico_termico = "
        f"{MAE_carico_termico:.6f} kW"
    )

    # ========================================================
    # TEMPERATURE
    # ========================================================

    scrivi("\nTEMPERATURE INTERNE")
    scrivi("-" * 125)

    scrivi(
        f"{'Match':<10}"
        f"{'Th,in src':>12}"
        f"{'Th,in sim':>12}"
        f"{'Th,out src':>13}"
        f"{'Th,out sim':>13}"
        f"{'Tc,in src':>12}"
        f"{'Tc,in sim':>12}"
        f"{'Tc,out src':>13}"
        f"{'Tc,out sim':>13}"
    )

    errori_T = []

    for match, ref in benchmark.items():

        sim = simulati.get(match)

        if sim is None:
            continue

        coppie = [
            (
                "hot_Tin_C",
                ref["Th_in"],
            ),
            (
                "hot_Tout_C",
                ref["Th_out"],
            ),
            (
                "cold_Tin_C",
                ref["Tc_in"],
            ),
            (
                "cold_Tout_C",
                ref["Tc_out"],
            ),
        ]

        for campo, riferimento in coppie:

            valore = sim.get(campo)

            if valore is not None:
                errori_T.append(
                    abs(
                        valore
                        - riferimento
                    )
                )

        scrivi(
            f"{match[0]+'-'+match[1]:<10}"
            f"{ref['Th_in']:>12.3f}"
            f"{sim.get('hot_Tin_C', float('nan')):>12.3f}"
            f"{ref['Th_out']:>13.3f}"
            f"{sim.get('hot_Tout_C', float('nan')):>13.3f}"
            f"{ref['Tc_in']:>12.3f}"
            f"{sim.get('cold_Tin_C', float('nan')):>12.3f}"
            f"{ref['Tc_out']:>13.3f}"
            f"{sim.get('cold_Tout_C', float('nan')):>13.3f}"
        )

    if errori_T:

        MAE_T = (
            sum(errori_T)
            / len(errori_T)
        )

        scrivi(
            f"\nMAE temperature = "
            f"{MAE_T:.6f} °C"
        )

    # ========================================================
    # AREA
    # ========================================================

    area_totale = sum(
        x["area_m2"]
        for x in scambiatori
    )

    scrivi("\nAREA")
    scrivi("-" * 80)

    scrivi(
        f"Area totale modello = "
        f"{area_totale:.3f} m²"
    )

    scrivi(
        "Area totale fonte   = "
        "NON RIPORTATA nel paper TRA15"
    )

    scrivi(
        "Validazione area     = "
        "NON DISPONIBILE"
    )

    # ========================================================
    # DIMENSIONE MILP
    # ========================================================

    scrivi("\nDIMENSIONE DEL PROBLEMA")
    scrivi("-" * 80)

    scrivi(
        f"Intervalli modello = "
        f"{risultati['numero_intervalli']}"
    )

    scrivi(
        f"Variabili totali   = "
        f"{risultati['numero_variabili']}"
    )

    scrivi(
        f"Variabili binarie  = "
        f"{risultati['numero_binarie']}"
    )

    scrivi(
        f"Vincoli             = "
        f"{risultati['numero_vincoli']}"
    )

    scrivi(
        "Dimensione fonte    = "
        "NON RIPORTATA nel paper TRA15"
    )

    # ========================================================
    # BILANCIO
    # ========================================================

    scrivi("\nBILANCIO ENERGETICO")
    scrivi("-" * 80)

    scrivi(
        f"Residuo globale = "
        f"{risultati['residuo_bilancio_energia_kW']:+.6e} kW"
    )

    scrivi("\n" + "=" * 110)

    testo = "\n".join(
        righe
    )

    percorso_file = Path(
        percorso_file
    )

    percorso_file.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    percorso_file.write_text(
        testo,
        encoding="utf-8",
    )

    return testo
# Alias semplice per esegui.py
