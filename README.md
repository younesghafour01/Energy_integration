# Energy Integration from Scratch

Implementazione di un algoritmo di ottimizzazione per l'integrazione energetica basato sulla **Pinch Analysis**.

Questa versione rappresenta il **caso base a quattro flussi** ed è tratta da:

> Zoughaib, A. (2017), *Energy Integration of Continuous Processes: From Pinch Analysis to Hybrid Exergy/Pinch Analysis*.

La Pinch Analysis è un metodo fortemente basato sulla rappresentazione grafica. Per questo motivo, il programma affianca ai risultati numerici i principali grafici utilizzati durante l'analisi.

Leggendo il codice è possibile seguire la ricostruzione del metodo nello stesso ordine con cui viene presentato nella fonte di riferimento.

---

## Struttura del progetto

Il progetto si articola in tre file principali.

### `dati_input.json`

Contiene i dati di input del caso studio e i parametri necessari all'analisi.

### `integrazione_energetica.py`

Contiene gli strumenti per la Pinch Analysis e il modello matematico MILP utilizzato per la preselezione delle process heat pump.

Il file comprende:

#### Classe `Flusso`

La classe `Flusso` caratterizza i flussi di processo e contiene i metodi:

- `calcola_Q()`
- `calcola_T_traslate()`

#### Funzioni per la Pinch Analysis

- `crea_cascata_termica()`
- `costruisci_curve_composite()`
- `costruisci_GCC()`
- `self_sufficient_pockets()`

#### Funzioni per preparare il problema di ottimizzazione

- `discretizza_GCC()`
- `genera_HPPr_candidate()`
- `crea_modello_HPPr()`

La funzione `crea_modello_HPPr()` utilizza **DOcplex** per costruire:

- variabili decisionali;
- vincoli;
- funzione obiettivo.

DOcplex prepara quindi il problema matematico che viene successivamente risolto da **CPLEX**.

#### Funzione di risoluzione

- `risolvi_modello_HPPr()`

Questa funzione passa il modello a CPLEX e recupera la soluzione ottima.

CPLEX è un solver matematico di ottimizzazione sviluppato da IBM. Nel nostro caso risolve un problema MILP composto da variabili continue e binarie, vincoli lineari e una funzione obiettivo exergetica.

#### Funzioni per la visualizzazione

- `grafico_TQ()`
- `costruisci_curva_utilities_HP()`

Queste funzioni permettono di visualizzare le Composite Curves, la GCC, le self-sufficient pockets e la Integrated Composite Curve.

### `prova_4_flussi.py`

È il file da eseguire.

Legge i dati da `dati_input.json`, esegue la simulazione, stampa i risultati nel terminale e genera i grafici.

---

## Cosa fa l'algoritmo

In sintesi, il programma:

1. legge i dati di processo dal file JSON;
2. esegue la cascata termica;
3. calcola i **Minimum Energy Requirements**;
4. costruisce le **Composite Curves** e la **Grand Composite Curve**;
5. individua **Main Pinch Point**, **Potential Pinch Points** e **self-sufficient pockets**;
6. discretizza la GCC;
7. genera le process heat pump candidate;
8. costruisce il modello MILP con DOcplex;
9. risolve il MILP con CPLEX;
10. restituisce la HP selezionata e i principali risultati energetici ed exergetici;
11. genera i grafici nella cartella `risultati/`.

---

# Avvio del programma

## Requisiti

Sul PC devono essere installati:

- Python 3;
- IBM ILOG CPLEX Optimization Studio.

Librerie Python necessarie:

- `matplotlib`
- `docplex`
- `cplex`

---

## Struttura della cartella

I file principali devono trovarsi nella stessa cartella:

```text
energy-integration-from-scratch/
├── integrazione_energetica.py
├── prova_4_flussi.py
├── dati_input.json
└── risultati/
```

La cartella `risultati/` viene creata automaticamente se non esiste.

---

## Primo avvio

### 1. Aprire il terminale nella cartella del progetto

Posizionarsi nella cartella:

```text
energy-integration-from-scratch
```

È possibile verificare la posizione con:

```bash
pwd
ls
```

### 2. Creare l'ambiente virtuale

```bash
python -m venv .venv
```

### 3. Attivare l'ambiente virtuale

Con Git Bash:

```bash
source .venv/Scripts/activate
```

### 4. Installare le librerie Python

```bash
python -m pip install --upgrade pip
python -m pip install matplotlib docplex
```

### 5. Installare CPLEX

CPLEX deve essere installato dal sito ufficiale IBM:

[IBM ILOG CPLEX Optimization Studio](https://www.ibm.com/products/ilog-cplex-optimization-studio)

Per questo progetto è consigliata la versione accademica.

Dopo aver installato CPLEX, installare anche l'interfaccia Python nell'ambiente virtuale:

```bash
python -m pip install cplex
```

Collegare DOcplex alla versione completa di CPLEX Studio:

```bash
docplex config --upgrade "C:/Program Files/IBM/ILOG/CPLEX_Studio..."
```

Sostituire il percorso con quello effettivo della propria installazione.

Verificare che Python riesca a importare CPLEX:

```bash
python -c "import cplex; print(cplex.__version__)"
```

---

## Esecuzione

Con l'ambiente virtuale attivo e il terminale posizionato nella cartella del progetto:

```bash
python prova_4_flussi.py
```

Non è necessario eseguire direttamente `integrazione_energetica.py`.

---

## Risultati

I principali risultati numerici vengono stampati direttamente nel terminale.

I grafici vengono salvati nella cartella:

```text
risultati/
```
