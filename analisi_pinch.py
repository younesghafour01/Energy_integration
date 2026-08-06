import matplotlib.pyplot as plt
from pathlib import Path


class Flusso:
    def __init__(self, codice,nome, tipo, T_in,T_out, CP, processo,zona, disponibile):
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
        if delta_T_min < 0:
            raise ValueError("Delta T minimo non può essere negativo.")

        if self.tipo == "hot":
            traslazione = -delta_T_min / 2
        elif self.tipo == "cold":
            traslazione = delta_T_min / 2
        else:
            raise ValueError(
                f"Tipo non valido per il flusso {self.codice}: {self.tipo}"
            )

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
    valori_cascata = [0.0] + [
    riga["cascata_provvisoria"]
        for riga in risultati
        ]

    minimo_cascata = min(valori_cascata)
    QH_min = max(0.0, -minimo_cascata)

    for riga in risultati:
        riga["cascata_finale"] = (
            riga["cascata_provvisoria"] + QH_min
        )

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
def costruisci_curve_composite(
    risultati,
    QH_min,
    tolleranza=1e-9,
):
    """Costruisce separatamente Hot CC e Cold CC traslate."""

    Q_hot_totale = sum(
        riga["delta_H_hot"]
        for riga in risultati
    )
    Q_cold_totale = sum(
        riga["delta_H_cold"]
        for riga in risultati
    )

    QC_min = QH_min + Q_hot_totale - Q_cold_totale

    def costruisci_lato(
        chiave_CP,
        chiave_delta_H,
        Q_iniziale,
    ):
        # Intervalli nei quali esiste almeno un flusso
        # del tipo considerato.
        indici_attivi = [
            indice
            for indice, riga in enumerate(risultati)
            if riga[chiave_CP] > tolleranza
        ]

        if not indici_attivi:
            return []

        primo = indici_attivi[0]
        ultimo = indici_attivi[-1]

        # Elimina gli intervalli esterni nei quali CP = 0.
        intervalli = list(
            reversed(risultati[primo:ultimo + 1])
        )

        Q = Q_iniziale
        punti = [(Q, intervalli[0]["T_inf"])]

        for indice, riga in enumerate(intervalli):
            Q += riga[chiave_delta_H]

            ultimo_intervallo = (
                indice == len(intervalli) - 1
            )

            if ultimo_intervallo:
                cambia_CP = True
            else:
                CP_successivo = intervalli[indice + 1][
                    chiave_CP
                ]

                cambia_CP = (
                    abs(
                        riga[chiave_CP] - CP_successivo
                    )
                    > tolleranza
                )

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

    return hot_CC_traslata, cold_CC_traslata
def riporta_curve_composite_a_temperature_reali(hot_CC_traslata, cold_CC_traslata, delta_T_min,):
    hot_CC = [
        (Q, T_star + delta_T_min / 2)
        for Q, T_star in hot_CC_traslata
    ]

    cold_CC = [
        (Q, T_star - delta_T_min / 2)
        for Q, T_star in cold_CC_traslata
    ]

    return hot_CC, cold_CC

def costruisci_GCC(risultati, QH_min):

    gcc=[]
    T_max= risultati[0]["T_sup"]
    gcc.append((QH_min, T_max))

    for riga in risultati:
        Q_netto = riga["cascata_finale"]
        T_star = riga["T_inf"]
        gcc.append((Q_netto, T_star))

    return gcc

def self_sufficient_pockets(gcc, tolleranza=1e-9):
    """Individua le pocket sopra e sotto il pinch."""

    pockets = []

    indice_pinch = next(
        indice
        for indice, (Q, _) in enumerate(gcc)
        if abs(Q) < tolleranza
    )

    # Sopra il pinch: temperatura massima -> pinch.
    punti_sopra = gcc[:indice_pinch + 1]

    # Sotto il pinch: temperatura minima -> pinch.
    # La parte inferiore deve quindi essere invertita.
    punti_sotto = list(
        reversed(gcc[indice_pinch:])
    )

    zone = [
        ("sopra_pinch", punti_sopra),
        ("sotto_pinch", punti_sotto),
    ]

    for nome_zona, punti_zona in zone:
        for indice in range(len(punti_zona) - 2):
            Q_inizio, T_inizio = punti_zona[indice]
            Q_successivo, _ = punti_zona[indice + 1]

            # Una pocket deve iniziare dall'estremo esterno
            # oppure da un vero minimo locale.
            estremo_esterno = indice == 0

            minimo_locale = (
                indice > 0
                and Q_inizio
                <= punti_zona[indice - 1][0] + tolleranza
                and Q_successivo
                > Q_inizio + tolleranza
            )

            if not (estremo_esterno or minimo_locale):
                continue

            # La GCC deve inizialmente allontanarsi
            # verso destra dal valore di riferimento.
            if Q_successivo <= Q_inizio + tolleranza:
                continue

            # Cerca il ritorno allo stesso Q di riferimento.
            for indice_fine in range(
                indice + 2,
                len(punti_zona),
            ):
                Q_precedente, T_precedente = (
                    punti_zona[indice_fine - 1]
                )
                Q_corrente, T_corrente = (
                    punti_zona[indice_fine]
                )

                attraversa_riferimento = (
                    min(Q_precedente, Q_corrente)
                    - tolleranza
                    <= Q_inizio
                    <= max(Q_precedente, Q_corrente)
                    + tolleranza
                )

                if not attraversa_riferimento:
                    continue

                denominatore = (
                    Q_corrente - Q_precedente
                )

                if abs(denominatore) < tolleranza:
                    T_fine = T_precedente
                else:
                    frazione = (
                        (Q_inizio - Q_precedente)
                        / denominatore
                    )

                    T_fine = (
                        T_precedente
                        + frazione
                        * (T_corrente - T_precedente)
                    )

                pockets.append({
                    "zona": nome_zona,
                    "Q_riferimento_kW": Q_inizio,
                    "T_inizio_traslata_C": T_inizio,
                    "T_fine_traslata_C": T_fine,
                    "punti_gcc": (
                        punti_zona[indice:indice_fine]
                        + [(Q_inizio, T_fine)]
                    ),
                })

                break

    return pockets

def grafico_TQ(
    tipo_grafico,
    hot_CC=None,
    cold_CC=None,
    gcc=None,
    pockets=None,
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

        ax.plot(Q, T, color="green", marker="o", label="GCC")
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

        ax.axvline(0, color="black", linestyle="--", linewidth=1)

        ax.set_title("Self-sufficient pockets")
        ax.set_ylabel("Temperatura traslata [°C]")

    else:
        raise ValueError(
            "tipo_grafico deve essere 'composite', "
            "'composite_traslate', 'gcc' oppure 'pockets'."
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