# Energy Integration from Scratch

Implementazione di un algoritmo di ottimizzazione delle reti di scambio termico basato sulla teoria del pinch analysis

Questa versione rappresenta il caso base a quattro flussi presentato ed è tratto da Zoughaib (2017), Energy Integration of Continuous Processes: From Pinch Analysis to Hybrid Exergy/Pinch Analysis..  

La pinch analysis è un metodo sostanzialmente grafico, quindi in linea generale l'algoritmo svolge dei calcoli e vengono affiancati i grafici ai risultati numerici.

Step by step leggendo il codice è possibile notare la ricostruzione del metodo nello stesso ordine con cui è stato descritto dalla fonte

L'algoritmo si articola in 3 file principali:

- file json contenente i file di input di ogni caso studio

- file di analisi_pinch: in questo file vengono ricostruiti gli strumenti per la pinch analysis e il modello matematico MILP per l'ottimizzazione della rete di scambio. Il file è composto da:

    - una classe Flusso che caratterizza i flussi, questa classe ha 2 metodi calcola_Q e calcola_T_traslate

    - 4 funzioni per l'analisi pinch
        - crea_cascata_termica
        - costruisci_curve_composite
        - costruisci_GCC
        - self_sufficient_pockets
    - 3 funzioni per preparare l'input del risolutore che ricerca la soluzione di ottimo di cuii una che fa uso della libreria docplex
        - def discretizza_GCC
        - genera_HPPr_candidate
        - crea_modello_HPPr questa funzione genera una classe importata doclpex
            - docplex è la libreria che dev’essere utilizzata per creare variabili vincoli e funzioni obiettivo da passare poi a al motore che risolve poi il problema di ottimizzazione detto CPLEX
    - 1 funzione per attivare passare i dati di input al risolutore dopo che sono stati costruiti varibili, vincoli, funzione di ottimo, la GCC è stata discretizzata e indicizzata come previsto dall'algoritmo descritto dalla fonte. CPLEX è un solver matematico di ottimizzazione sviluppato da IBM. In pratica, tu gli fornisci un problema del tipo: minf(x) soggetto a: Ax≤b con alcune variabili continue e/o intere/binarie, e CPLEX cerca automaticamente la soluzione ottima.
        - risolvi_modello_HPPr
    - 2 funzioni per la visualizzazione grafica dei risultati e per poter monitorare i vari step dell'algoritmo graficamente
        - grafico_TQ (genera GCC e curve composite)
        - costruisci_curva_utilities_HP (aggiunge alla GCC le tilities)
- file prova_4_flussi: questo file estrae i dati dal file json ed esegue la simulazione, stampa i risultati e genera i grafici 


Riassumendo in breve cosa fa l'algoritmo:

1. legge i dati di processo da un file JSON (dati input);
2. esegue la cascata termica seguendo le definizioni date dalla fonte principale;
3. calcola i Minimum Energy Requirements (fabbisogno energetico che deve essere coperto dalle utilities);
4. costruisce Composite Curves e Grand Composite Curve per il processo che non fa ancora uso di utilities esterne. 
5. individua Main Pinch Point, Potential Pinch Points e self-sufficient pockets. 
6. discretizza la GCC;
7. genera le heat pump di processo candidate;
8. costruisce il MILP con DOcplex (libreria contenete gli oggetti per cui il risolutore può lavorare)
9. risolve il MILP con CPLEX;
9. restituisce la HP selezionata e i principali risultati energetici/exergetici;
10. genera i grafici nella cartella `risultati`.


Avvio del programma

Requisiti
Sul PC per questa simulazione sono stati installati:
- Python 3
- IBM ILOG CPLEX Optimization Studio
- Le librerie Python necessarie sono:
    - matplotlib
    - docplex


Struttura della cartella
I file principali devono trovarsi nella stessa cartella:

energy-integration-from-scratch/
├── integrazione_energetica.py
├── prova_4_flussi.py
├── dati_input.json
└── risultati/

La cartella `risultati/` viene creata automaticamente se non esiste.


Primo avvio
1. Aprire il terminale nella cartella: energy-integration-from-scratch

(Verificare di essere nella cartella corretta con)

2. Creare l'ambiente virtuale: python -m venv .venv
3. Attivarlo: source .venv/Scripts/activate

4. Installare le librerie:
    python -m pip install --upgrade pip
    python -m pip install matplotlib docplex

5. bisogna installare CPLEX dal sito del produttore. se si usa la mail accademica si accede alla versione più estesa e con meno limitazioni. consigliata per questo progetto
link al prodotto: https://www.ibm.com/products/ilog-cplex-optimization-studio?utm_source=chatgpt.com.
# installare le interfacce Python
python -m pip install cplex

# collegare docplex alla versione completa di CPLEX Studio
docplex config --upgrade "C:/Program Files/IBM/ILOG/CPLEX_Studio..."

# verificare
python -c "import cplex; print(cplex.__version__)"

6. si può lanciare il programma, con l'ambiente virtuale attivo e trovandosi nella cartella del progetto, semplicemnte con: python prova_4_flussi.py

7. I grafici vengono salvati nella cartella:

risultati/

e alcuni dati e risultati stampati sul terminale