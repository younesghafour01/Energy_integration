



# Energy Integration 

La repository nasce con l’obiettivo di riprodurre, in forma computazionale, la metodologia descritta nel Capitolo 1, “Energy Integration of Continuous Processes: From Pinch Analysis to Hybrid Exergy/Pinch Analysis”, del volume di Assaad Zoughaib From Pinch Methodology to Pinch-Exergy Integration of Flexible Systems (Elsevier/ISTE Press, 2017).
L’implementazione si appoggia ai riferimenti bibliografici richiamati nel capitolo per poter recuperare le informazioni in maniera completa per la ricostruzione dei modelli. In particolare i riferimenti sono primncipalmente: Thibault et al. (2015) per il predesign exergetico delle utilities, Barbaro e Bagajewicz (2005, corregidium 2006) per il modello MILP HENS e Tran et al. (2015) per l'estensione del modello di Barbaro e Bagajewicz

## Obiettivo del progetto

Il progetto mira a ricostruire alcune formulazioni della letteratura per:

- calcolare cascata termica, fabbisogni minimi di utility e pinch point;
- costruire Composite Curves e Grand Composite Curve (GCC);
- preselezionare e dimensionare utility avanzate secondo un criterio
  exergetico;
- sintetizzare una Heat Exchanger Network (HEN) minimizzandone il Total
  Annualized Cost (TAC);
- ricostruire topologia, carichi termici, aree, numero di shell, temperature
  interne e bilanci energetici;
- confrontare a posteriori le soluzioni con benchmark pubblicati.


## Funzionalità attualmente implementate

### Pinch Analysis e utilities predesign – THI15

Il modulo [`src/predesign/THI15_predesign.py`](src/predesign/THI15_predesign.py)
implementa la struttura del problema di ottimizzazione ispirato a Thibault et al. (2015):

- lettura di correnti sensibili e carichi isoterm dal file input;
- traslazione delle temperature e costruzione della cascata termica;
- calcolo di `QH_min`, `QC_min` e dei pinch point;
- costruzione delle Composite Curves, della GCC e delle self-sufficient
  pockets;
- discretizzazione della GCC in zone e generazione delle utility candidate;
- MILP di preselezione/configurazione per pompe di calore di processo
  (`HPPr`), pompe di calore da ambiente (`HPUt`), chiller (`Ref` nel modello),
  Organic Rankine Cycle (`ORC`) e cogenerazione (`CHP`);
- ricostruzione delle utility selezionate e dei relativi livelli termici,
  carichi termici e potenze elettriche;
- produzione del report testuale e dei grafici T-Q.

### HENS – BAR05

Il modulo [`src/hens/BAR05_hens.py`](src/hens/BAR05_hens.py) implementa un
MILP per la Heat Exchanger Network Synthesis basato su Barbaro e Bagajewicz
(2005) e sul relativo corrigendum (2006). Il preprocessing termico è interno
al modulo e non dipende dalla pipeline THI15.

La formulazione corrente comprende:

- partizionamento della scala termica in intervalli e heat-transfer zones;
- correnti di processo, utilities fisiche e utilities virtuali di supporto
  alla formulazione;
- tecnologie di scambio e insieme esplicito dei match ammessi;
- bilanci termici e variabili di trasferimento del calore;
- stream splitting, consistenza delle portate e vincoli di fattibilità delle
  temperature;
- calcolo linearizzato dell'area, conteggio di exchanger e shell, costi fissi,
  costi d'area e costi delle utilities;
- minimizzazione del TAC;
- ricostruzione post-soluzione della rete, dei carichi termici, delle temperature
  interne e dei bilanci energetici;
- report specifico di validazione per il benchmark BAR05 4S1.

Il caso attualmente verificato in modo più completo è **BAR05 4S1**.
Gli altri casi della pubblicazione non sono ancora stati validati.

### HENS – TRA15

Il modulo src/hens/TRA15_hens.py rappresenta un’estensione del modello HENS costruito a partire da BAR05. La struttura di base del problema — partizionamento termico, insiemi di correnti e utilities, variabili di scambio termico, calcolo delle aree, costi e minimizzazione del TAC — viene quindi riutilizzata dal modulo BAR05.

Su questa base vengono introdotte le funzionalità aggiuntive considerate nell’estensione di Tran et al. (2015). In particolare, il codice gestisce il non-isothermal mixing delle correnti di processo mediante le Eq. BAR05 (7)–(10), applicate sia alle correnti calde sia a quelle fredde. L’estensione TRA15 prevede inoltre la possibilità di considerare più tecnologie di scambio termico, caratterizzate da costi e fattori correttivi differenti, e correnti flessibili, per le quali la temperatura di uscita può variare entro un intervallo assegnato.

Il caso attualmente verificato è TRA15 Test 1, nel quale è disponibile soltanto la tecnologia T1; la tecnologia T2 è presente nel file di input ma disattivata. Il modello riproduce correttamente la topologia pubblicata e fornisce valori di TAC, utilities, carichi termici e temperature interne molto vicini a quelli riportati dalla fonte.

## Struttura della repository

```text
.
├── esegui.py
├── src/
│   ├── predesign/
│   │   └── THI15_predesign.py
│   └── hens/
│       ├── BAR05_hens.py
│       └── TRA15_hens.py
├── dati_input/
│   ├── predesign/
│   │   ├── 4_flussi.json
│   │   └── dairy.json
│   └── hens/
│       ├── BAR05_hens/
│       │   └── 4S1.json
│       └── TRA15_hens/
│           └── test1.json
├── risultati/
│   ├── predesign/
│   │   ├── 4_flussi/
│   │   └── dairy/
│   └── hens/
│       ├── BAR05_hens/4S1/
│       └── TRA15_hens/test1/
├── archivio/
├── .gitignore
└── README.md
```

`archivio/` contiene versioni precedenti, casi non più collegati all'entry
point e script diagnostici storici. Non fa parte della pipeline corrente. Non
è presente una suite di test automatica attiva fuori da questa cartella.


## Requisiti

Per utilizzare questa repository servono alcuni programmi installati sul computer.

In particolare sono necessari:

- **Python 3**, che esegue il codice della repository;
- **DOcplex**, che permette di scrivere in Python i problemi di ottimizzazione;
- **IBM CPLEX**, che risolve effettivamente i problemi di ottimizzazione;
- **Matplotlib**, utilizzato per creare i grafici della Pinch Analysis e del predesign delle utilities.

### Perché servono DOcplex e CPLEX?

Una parte importante di questa repository consiste nel trovare automaticamente la soluzione migliore tra molte configurazioni possibili.

Ad esempio, nella sintesi della rete di scambiatori il programma deve scegliere:

- quali correnti devono scambiare calore;
- quanto calore deve essere scambiato;
- quali utilities utilizzare;
- quanti scambiatori sono necessari;
- quale area deve avere ogni scambiatore;
- quale configurazione permette di ottenere il costo annuo totale più basso.

Per fare questo vengono costruiti dei problemi matematici di ottimizzazione.

**DOcplex** serve per descrivere questi problemi utilizzando Python.  
Con DOcplex vengono quindi definite le variabili da trovare, le condizioni che devono essere rispettate e l'obiettivo da minimizzare.

**CPLEX** è invece il programma che riceve il problema costruito con DOcplex e cerca la soluzione migliore.

## Installazione

## Requisiti

Per utilizzare la repository è necessario installare:

- Python;
- DOcplex;
- IBM CPLEX;
- Matplotlib.

I risultati attualmente riportati nella repository sono stati ottenuti utilizzando:

- Python 3.14.6
- DOcplex 2.32.264
- IBM CPLEX 22.2.0.0
- Matplotlib 3.11.1

DOcplex viene utilizzato per costruire i problemi matematici di ottimizzazione descritti nei modelli implementati nella repository.
IBM CPLEX è invece il programma che risolve questi problemi e individua la soluzione ottima o la migliore soluzione disponibile.
In particolare, CPLEX viene utilizzato nei modelli di predesign delle utilities e di sintesi delle reti di scambiatori, dove devono essere valutate molte possibili configurazioni.
Matplotlib viene utilizzato per la produzione dei grafici associati alla Pinch Analysis e al predesign delle utilities.

## Utilizzo

La sintassi implementata dal terminale è:

```text
python esegui.py <file_input.json> <modalita> [modello_hens]
```


### Predesign

```bash
python esegui.py dati_input/predesign/4_flussi.json predesign
```

È disponibile anche il caso `dati_input/predesign/dairy.json`.

### BAR05

```bash
python esegui.py dati_input/hens/BAR05_hens/4S1.json hens bar05
```

### TRA15

```bash
python esegui.py dati_input/hens/TRA15_hens/test1.json hens tra15
```

## Struttura dei file JSON

### Campi comuni delle correnti

Ogni caso contiene una lista `flussi`. I campi principali sono:

| Campo | Significato |
|---|---|
| `codice`, `nome` | Identificativi della corrente |
| `tipo` | `hot` oppure `cold` |
| `T_in`, `T_out` | Temperature reali di ingresso e uscita in °C |
| `CP` | Portata termica equivalente per correnti sensibili, se fornita |
| `heat_load_kW` | Carico termico totale; può sostituire `CP` per una corrente sensibile ed è necessario per un carico isotermo |
| `isotermo` | Identifica esplicitamente un carico isotermo; in assenza del campo viene riconosciuto da `T_in == T_out` |
| `delta_T_min_half` | Traslazione Pinch specifica della corrente; altrimenti vale metà di `delta_T_min` |
| `h_W_m2K` | Coefficiente di scambio usato nei casi HENS |
| `splittable` | Abilita lo splitting della corrente nel framework BAR05; il default interno è `true` |
| `disponibile` | Include o esclude la corrente |

### Predesign THI15

I file `dati_input/predesign/*.json` definiscono:

- dati generali: `nome`, `delta_T_min` e `delta_T_max`;
- parametri exergetici e termodinamici: `eta_ex`, `evaP`, `condP`, `T0`,
  `T_f` e l'eventuale `T_cond_max`;
- `utilities`: abilitazione e numero massimo di `HPPr`, `HPUt`, `chiller`,
  `ORC` e `CHP`, oltre al limite complessivo `HP_max`;
- `flussi`: correnti sensibili o isoterme secondo i campi descritti sopra.

`delta_T_max` controlla la discretizzazione della GCC usata per generare i
candidati del MILP di predesign.

### HENS BAR05 e TRA15

I file HENS aggiungono i parametri generali `delta_T_partition_max` e
`numero_intervalli_min` e una sezione `hens` con:

| Campo | Significato |
|---|---|
| `framework` | Seleziona la formulazione `bar05` o `tra15` |
| `separa_al_pinch` | Se `true`, impedisce che una singola heat-transfer zone attraversi il pinch |
| `utilities` | Correnti di servizio calde/fredde, temperature, coefficiente di scambio, costo annuo specifico e disponibilità |
| `technologies` | Tecnologie candidate, fattore `FHEX`, area massima, costi fissi e d'area, stato `enabled` e match ammessi |
| `flexible_streams` | Eventuali correnti con temperatura finale flessibile; vuoto nei due casi correnti |
| `benchmark_exchangers` | Topologia, carichi termici e, quando disponibili, aree o temperature della fonte |
| `benchmark_area_total_m2` / `benchmark_TAC_kUSD_year` | Benchmark globale disponibile per il caso |

I due input HENS correnti  BAR05 4S1 | TRA15 Test 1  rappresentano lo stesso problema termico di base, ma
con alcune impostazioni e precisione differenti:



## Output generati

Ogni esecuzione crea una cartella dedicata secondo la regola:

```text
risultati/<cartella-relativa-dell-input>/<nome-file-senza-estensione>/
```

Il predesign genera:

- `risultati_simulazione.txt`: output completo di Pinch Analysis, MILP e
  utility selezionate;
- `composite_curves_reali.png`;
- `composite_curves_traslate.png`;
- `grand_composite_curve.png`;
- `self_sufficient_pockets.png`;
- `grand_composite_curve_aggiornata.png`;
- `integrated_composite_curve.png`.

BAR05 4S1 genera:

- `risultati_simulazione.txt`: partizione, stato del solver, economia,
  utilities, rete, carichi termici, bilanci e temperature;
- `validazione_BAR05.txt`: confronto dettagliato con i benchmark 4S1.

TRA15 Test 1 genera:

- `risultati_simulazione.txt`: partizione, dimensione del MILP, economia,
  utilities, rete, carichi termici, temperature e bilancio;
- `validazione_TRA15_test1.txt`: confronto con TAC, topologia, utilities,
  carichi termici e temperature pubblicati.

L'output viene sia mostrato nel terminale sia salvato nei file testuali. Una
nuova esecuzione dello stesso caso sovrascrive i report e i grafici omonimi.

## Stato della validazione

vedi cartella risultati






## Stato di sviluppo / sviluppi futuri

Le attività ancora in corso sono: 

- validare gli altri casi BAR05;
- validare TRA15 Test 2–4;

## Riferimenti bibliografici

- F. Thibault, A. Zoughaib, S. Pelloux-Prayer,  
  “A MILP algorithm for utilities pre-design based on the Pinch Analysis and an exergy criterion”,  
  *Computers & Chemical Engineering*, 75, 65–73, 2015.  
  [A MILP algorithm for utilities pre-design based on the Pinch Analysis and an exergy criterion](https://doi.org/10.1016/j.compchemeng.2014.12.010)

- A. Barbaro, M. J. Bagajewicz,  
  “New rigorous one-step MILP formulation for heat exchanger network synthesis”,  
  *Computers & Chemical Engineering*, 29(9), 1945–1976, 2005.  
  [New rigorous one-step MILP formulation for heat exchanger network synthesis](https://doi.org/10.1016/j.compchemeng.2005.04.006)

- A. Barbaro, M. J. Bagajewicz,  
  “Corrigendum to ‘New rigorous one-step MILP formulation for heat exchanger network synthesis’”,  
  *Computers & Chemical Engineering*, 30(8), 1310–1313, 2006.  
  [Corrigendum to “New rigorous one-step MILP formulation for heat exchanger network synthesis”](https://doi.org/10.1016/j.compchemeng.2006.01.004)

- C.-T. Tran, F. Thibault, H. Thieriot, A. Zoughaib, S. Pelloux-Prayer,  
  “New features to Barbaro's heat exchanger network algorithm: heat exchanger technologies and waste heat flow representation”,  
  *Proceedings of ECOS 2015 — 28th International Conference on Efficiency, Cost, Optimization, Simulation and Environmental Impact of Energy Systems*,  
  Pau, France, 2015.  
  [New features to Barbaro's heat exchanger network algorithm: heat exchanger technologies and waste heat flow representation](https://www.researchgate.net/publication/282288007_New_features_to_Barbaro%27s_heat_exchanger_network_algorithm_heat_exchanger_technologies_and_waste_heat_flow_representation)

- H. C. Becker,  
  *Methodology and Thermo-Economic Optimization for Integration of Industrial Heat Pumps*,  
  PhD Thesis No. 5341, École Polytechnique Fédérale de Lausanne (EPFL),  
  Lausanne, Switzerland, 2012.  
  [Methodology and Thermo-Economic Optimization for Integration of Industrial Heat Pumps](https://infoscience.epfl.ch/entities/publication/3eec1edd-9e62-4260-a8ea-46f39caa5660)