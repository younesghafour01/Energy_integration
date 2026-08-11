# Energy Integration from Scratch

Implementazione didattica di un algoritmo per l'integrazione energetica basato sulla **Pinch Analysis** e su un modello **MILP** per la preselezione delle utilities.

Il progetto è stato sviluppato a partire principalmente da:

> Zoughaib, A. (2017), *Energy Integration of Continuous Processes: From Pinch Analysis to Hybrid Exergy/Pinch Analysis*.

Per il Dairy Case sono inoltre utilizzati i dati di processo riportati da:

> Becker, H. (2012), *Methodology and Thermo-Economic Optimization for Integration of Industrial Heat Pumps*, Table B.2.

La formulazione MILP segue l'impostazione di Thibault et al. per la preselezione delle utilities sulla Grand Composite Curve.

La Pinch Analysis è fortemente basata sulla rappresentazione grafica. Per questo il programma affianca ai risultati numerici le principali curve utilizzate durante l'analisi: Composite Curves, Grand Composite Curve, self-sufficient pockets, GCC aggiornata e Integrated Composite Curve.

Il codice è organizzato in modo da poter eseguire casi studio differenti senza modificare le funzioni: i dati e le utilities disponibili vengono definiti tramite file JSON con struttura standard.

---

## Struttura del progetto

```text
energy-integration-from-scratch/
├── integrazione_energetica.py
├── esegui.py
├── dati_input.json
├── dati_input_dairy.json
├── README.md
└── risultati/
```

### `integrazione_energetica.py`

Contiene tutta la logica del programma:

- caricamento del caso studio;
- definizione dei flussi;
- Pinch Analysis;
- costruzione e discretizzazione della GCC;
- generazione delle utilities candidate;
- formulazione e soluzione del MILP;
- post-processing;
- generazione dei grafici.

### `esegui.py`

È il file da eseguire.

Riceve da terminale il file JSON del caso studio e richiama le funzioni contenute in `integrazione_energetica.py`.

In questo modo lo stesso codice può essere utilizzato per casi differenti senza creare file di esecuzione specifici.

### File JSON

I file JSON contengono:

- dati generali del caso studio;
- parametri della Pinch Analysis;
- parametri del modello exergetico;
- configurazione delle utilities;
- dati dei flussi di processo.

Esempi presenti nel progetto:

```text
dati_input.json
dati_input_dairy.json
```

---

## Struttura standard degli input

Ogni caso studio utilizza la stessa struttura generale.

Esempio del blocco utilities:

```json
"utilities": {
    "HPPr": {
        "enabled": true,
        "max": 3
    },
    "HPUt": {
        "enabled": false,
        "max": 0
    },
    "chiller": {
        "enabled": false,
        "max": 0
    },
    "ORC": {
        "enabled": false,
        "max": 0
    },
    "CHP": {
        "enabled": false,
        "max": 0
    },
    "HP_max": 3
}
```

`enabled` stabilisce se una tecnologia può essere utilizzata dal MILP, mentre `max` ne definisce il numero massimo installabile.

`HP_max` rappresenta il limite complessivo sul numero di pompe di calore `HPPr + HPUt`.

I flussi di processo possono essere sensibili oppure isotermi.

Per esempio:

```json
{
    "codice": "eva2",
    "nome": "eva2",
    "tipo": "cold",
    "T_in": 70.3,
    "T_out": 70.3,
    "heat_load_kW": 904.2,
    "delta_T_min_half": 1.2,
    "isotermo": true
}
```

I carichi termici sono espressi in **kW**.

---

## Principali componenti del codice

### Classe `Flusso`

La classe `Flusso` rappresenta una corrente di processo sensibile oppure un carico termico isotermo.

Metodi principali:

- `calcola_Q()`
- `calcola_T_traslate()`

La classe può utilizzare direttamente `heat_load_kW`; per i flussi sensibili il relativo `CP` può essere ricavato dal carico termico e dalla variazione di temperatura.

---

## Pinch Analysis

Le principali funzioni sono:

- `carica_caso_studio()`
- `crea_cascata_termica()`
- `costruisci_curve_composite()`
- `costruisci_GCC()`
- `self_sufficient_pockets()`
- `discretizza_GCC()`

La procedura:

1. legge i flussi dal JSON;
2. trasla le temperature;
3. costruisce la cascata termica;
4. calcola i Minimum Energy Requirements;
5. costruisce le Composite Curves;
6. costruisce la Grand Composite Curve;
7. individua Main Pinch Point, Potential Pinch Points e self-sufficient pockets;
8. suddivide e discretizza la GCC per il successivo problema MILP.

Il codice considera esplicitamente anche i carichi termici isotermi, come evaporazioni e condensazioni.

---

## Generazione delle utilities candidate

Le principali funzioni sono:

- `converti_zone_milp()`
- `genera_HPPr_candidate()`
- `genera_candidate_utilities()`

Il programma può generare candidate per:

- `HPPr`: process heat pumps;
- `HPUt`: utility heat pumps;
- `chiller`;
- `ORC`;
- `CHP`.

Le candidate vengono generate solamente per le tecnologie abilitate nel file JSON.

---

## Modello MILP

La funzione principale è:

```python
crea_modello_utilities()
```

Il modello viene costruito tramite **DOcplex** e comprende:

- variabili binarie di selezione;
- variabili continue di utilizzazione;
- limiti sul numero di utilities;
- prelievo e apporto di calore sulla GCC;
- aggiornamento del heat load mediante `NHL`;
- consumo elettrico totale `TEC`;
- produzione elettrica totale `TEP`;
- funzione obiettivo exergetica.

La funzione:

```python
risolvi_modello_utilities()
```

passa il modello a **CPLEX** e restituisce le utilities selezionate e i principali risultati energetici ed exergetici.

---

## Output numerici

Il programma restituisce, tra gli altri:

- `QH,min`;
- `QC,min`;
- temperature dei pinch point;
- utilities selezionate;
- temperature di evaporazione e condensazione;
- COP;
- carichi termici;
- consumo elettrico `TEC`;
- produzione elettrica `TEP`;
- hot MER residuo;
- cold MER residuo;
- `FinalExergy`.

---

## Grafici

La funzione:

```python
grafico_TQ()
```

viene utilizzata per produrre i principali grafici dell'analisi.

Per ogni caso studio vengono generati:

```text
composite_curves_traslate.png
grand_composite_curve.png
self_sufficient_pockets.png
grand_composite_curve_aggiornata.png
integrated_composite_curve.png
```

In particolare:

- `grand_composite_curve.png` rappresenta la GCC iniziale del processo;
- `self_sufficient_pockets.png` evidenzia MPP, PPP e self-sufficient pockets;
- `grand_composite_curve_aggiornata.png` rappresenta la GCC dopo l'inserimento delle utilities selezionate dal MILP;
- `integrated_composite_curve.png` rappresenta la GCC insieme alla curva cumulativa delle utilities.

---

# Avvio del programma

## Requisiti

Sono necessari:

- Python 3;
- IBM ILOG CPLEX Optimization Studio;
- `matplotlib`;
- `docplex`;
- `cplex`.

---

## Primo avvio

Aprire il terminale nella cartella:

```text
energy-integration-from-scratch
```

Verificare la posizione:

```bash
pwd
ls
```

Creare l'ambiente virtuale:

```bash
python -m venv .venv
```

Attivarlo con Git Bash:

```bash
source .venv/Scripts/activate
```

Installare le librerie Python:

```bash
python -m pip install --upgrade pip
python -m pip install matplotlib docplex cplex
```

Verificare che CPLEX sia disponibile:

```bash
python -c "import cplex; print(cplex.__version__)"
```

---

## Esecuzione

Il programma viene avviato indicando il file JSON da utilizzare.

Lo stesso schema può essere utilizzato per qualsiasi nuovo caso studio:

```bash
python esegui.py nome_file.json
```

Non è necessario modificare `integrazione_energetica.py` o creare un nuovo file Python per ogni caso.

---

## Cartella dei risultati

I risultati vengono organizzati automaticamente in una sottocartella associata al file JSON.

I principali risultati numerici vengono inoltre stampati direttamente nel terminale.
