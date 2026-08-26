# Refactoring findings

Questo documento separa osservazioni strutturali e possibili problemi dalla
modifica documentale. Nessuno dei punti elencati come sospetto ha prodotto una
correzione matematica nel refactoring.

## 1. Incoerenze strutturali trovate

- I tre moduli usavano sezioni numerate con significati diversi. Il predesign
  mescolava Pinch Analysis, discretizzazione e MILP sotto pochi titoli; BAR05
  numerava blocchi per ordine storico; TRA15 usava titoli funzionali non
  allineati. Sono stati aggiunti gli stessi undici nomi di fase, mantenendo
  l'ordine esecutivo e le funzioni esistenti.
- Nel predesign i commenti associavano le formule a etichette `[1.4]-[1.36]`.
  Il PDF fornito di Thibault et al. numera invece le equazioni da (1) a (33).
  I commenti e le docstring sono stati riallineati alla numerazione verificata;
  le espressioni DOcplex non sono state toccate.
- Alcune docstring BAR05/TRA15 rinviavano a una numerazione `[1.xx]` non
  presente nei PDF forniti. I rinvii sono ora verso BAR05, Corrigendum o TRA15
  con sezione/equazione verificabile.
- `TRA15_hens.py` è un wrapper/estensione, mentre quasi tutta la formulazione
  TRA15 vive in `BAR05_hens.py`. La nuova documentazione esplicita questo
  confine; spostare fisicamente il core avrebbe prodotto un refactoring ad alto
  rischio e non è stato fatto.
- `THI15_predesign.py` importa `Model` a livello modulo e anche localmente nel
  costruttore, nonostante un commento dichiari l'intento di mantenere la sola
  Pinch Analysis indipendente da DOcplex. È un'incoerenza di dipendenza, non
  matematica, lasciata invariata.
- L'entry point può fallire su console Windows `cp1252` quando ristampa simboli
  come `Δ`. Le baseline sono state eseguite con `PYTHONIOENCODING=utf-8`.
  Il problema riguarda il reporting e non il solver; non è stato corretto in
  questa modifica.

## 2. Duplicazioni

- `Flusso`, `carica_caso_studio`, la conversione reale/Pinch,
  `crea_cascata_termica` e `costruisci_GCC` erano identici per AST, firma e
  output. Sono ora implementati una sola volta in
  `src/common/thermal_preprocessing.py` e importati direttamente dai due
  moduli; BAR05 continua a non importare THI15.
- `converti_temperatura` non era interamente identica: il nucleo Pinch è common,
  mentre la scala HENS resta nel wrapper di `BAR05_hens.py`.
- `esegui_analisi_pinch` è una duplicazione nominale intenzionale. THI15
  aggiunge Composite Curves, MPP/PPP e pockets; BAR05 restituisce soltanto i
  dati consumati dalla partizione HENS. Unificarle cambierebbe il contratto.
- Il reporting HENS è in parte duplicato tra `stampa_risultati` e
  `stampa_risultati`. Anche questa duplicazione è mantenuta per lasciare
  visibili le grandezze specifiche del benchmark TRA15.
- `estrai_risultati` ricostruisce alcune aggregazioni già disponibili
  nell'output del solver comune. È rimasto invariato per compatibilità.

## 3. Oggetti analoghi rappresentati diversamente

### Decisione sulle duplicazioni termiche

| Funzione originale | THI15 | BAR05 | Comune | Decisione |
|---|---|---|---|---|
| `Flusso` | import | import | sì | A — identica, estratta |
| `carica_caso_studio` | import | import | sì | A — identica, estratta |
| `converti_temperatura` | alias del nucleo Pinch | wrapper Pinch + HENS | solo `converti_temperatura_pinch` | B — parte comune, scala HENS specifica D |
| `crea_cascata_termica` | import | import | sì | A — identica, estratta |
| `costruisci_GCC` | import | import | sì | A — identica, estratta |
| `esegui_analisi_pinch` | Composite Curves e pockets | input minimo HENS | no | B — orchestratori con output diversi; THI15 C, HENS D |

- Le zone del predesign usano punti `(z,k)` della GCC; HENS usa intervalli
  `(z,m)` e `(z,n)`. Uniformare le tuple sarebbe matematicamente fuorviante.
- I candidati del predesign sono dizionari di record; i match HENS sono insiemi
  `P`, `P_t` e indici `q[z,i,m,j,n]`. La documentazione ora usa gli stessi
  termini “candidato”, “match”, “zona”, “intervallo” e “indice”, senza cambiare
  le strutture.
- Le utility del predesign sono configurazioni indicizzate da punti GCC; in
  HENS sono correnti con portata variabile. Condividono un ruolo fisico ma non
  lo stesso oggetto matematico.
- BAR05 rappresenta area/shell aggregate con `A/U` e i match multipli con
  `Ahat/Uhat`; TRA15 aggiunge l'indice tecnologia `t`. La distinzione è ora
  esplicita nelle docstring e nella traceability.

## 4. Funzioni difficili da ricondurre alla fonte

- `crea_cascata_termica`, `costruisci_curve_composite` e `costruisci_GCC` nel
  predesign: THI15 assume la GCC come input e non dettaglia l'algoritmo usato
  qui per produrla. Marcate come `TODO_REFERENCE` o “Riferimento da
  verificare” nella traceability.
- `self_sufficient_pockets`: MPP, PPP e pockets sono descritti da THI15 Sec.
  2.1.1, ma il criterio numerico puntuale e la tolleranza sono una scelta
  implementativa.
- `costruisci_GCC_aggiornata` e `costruisci_curva_utilities`: la fonte mostra
  l'Integrated Composite Curve, ma non specifica l'algoritmo Python di
  interpolazione e aggregazione degli eventi.
- `_prepara_modello`: orchestra blocchi provenienti da più sezioni di BAR05,
  dal Corrigendum e da TRA15; non corrisponde a una singola equazione.
- `forza_temperature_uscita_flessibili`: è un vincolo per sensitivity test,
  esplicitamente marcato `IMPLEMENTATION CHOICE`.

## 5. Possibili bug matematici individuati ma NON corretti

I punti seguenti richiedono una decisione modellistica o una verifica ulteriore.
Non sono stati modificati.

- THI15 Eq. (11)-(14) sono stampate nel PDF con disuguaglianza stretta `<`,
  mentre il codice usa `<=`. Per un parametro chiamato “maximum number” il
  comportamento del codice è plausibile, ma la differenza letterale va chiarita
  sulla versione editoriale/originale della fonte.
- THI15 Sec. 2.1.1 descrive `S_z` come numero di segmenti, poi indicizza i punti
  con `k in [1,S_z]`. Il codice assegna a `S_z` il numero di punti della zona.
  La fonte è internamente ambigua; cambiare questa convenzione altererebbe
  variabili e vincoli, quindi non è stato fatto.
- Per TRA15 le utility fisiche non hanno `F_U_kW_K`; il core applica un Big-M
  energetico conservativo ai legami `qhat/Y`, mentre i bilanci determinano il
  duty. È una scelta implementativa non espressa da TRA15 Eq. (1) e può
  influire sulla forza della rilassazione MILP, anche se non necessariamente
  sulla soluzione intera.
- `individua_correnti_mixing_non_isotermo` abilita il non-isothermal mixing su tutte le
  process streams. TRA15 afferma che lo splitting è permesso nel case study e
  richiama il modello BAR05, ma non dichiara esplicitamente che ogni corrente
  appartenga a `NIH`/`NIC`. Questa scelta può ampliare il dominio rispetto a una
  lettura più restrittiva.
- Le Eq. TRA15 (8)-(9) sono implementate omettendo le variabili area delle
  tecnologie vietate, invece di crearle e fissarle a zero/non negative. È una
  rappresentazione normalmente equivalente sul dominio utile, ma produce una
  dimensione MILP diversa da una trascrizione letterale.
- Il valore numerico `bar05_qL=1e-6` del benchmark realizza il parametro
  positivo `qL` di BAR05 Eq. (11)-(14). La fonte definisce il parametro ma il
  valore specifico non è identificato con certezza nel case study.
- I risultati TRA15 Test 1 sono vicini ma non identici ai valori arrotondati
  pubblicati: TAC 180.793086 contro 181 kUSD/y, HU 202.5 contro 204 kW e CU
  180.5 contro 182 kW. Il codice usa i dati numerici del JSON (361 e 667 kW),
  mentre figura e tabella pubblicate riportano risultati arrotondati; non è
  stata introdotta alcuna calibrazione.

## 6. Riferimenti bibliografici non identificati con certezza

- Algoritmo completo di cascata termica e Composite Curves usato dal
  predesign: `TODO_REFERENCE`.
- Criterio esatto di tolleranza per rilevare PPP e duplicati geometrici della
  GCC: `IMPLEMENTATION CHOICE - non direttamente definita dalla fonte`.
- Metodo di ricostruzione grafica della GCC aggiornata/ICC:
  `IMPLEMENTATION CHOICE - non direttamente definita dalla fonte`.
- Valore numerico del parametro `qL` per BAR05 Problem 4S1:
  `Riferimento da verificare`.
- Attivazione di tutte le process streams in `NIH`/`NIC` per TRA15 Test 1:
  `Riferimento da verificare`.

## Gap analysis dei nuovi casi HENS

- **Test 3:** stesso multinsieme di sei match della Figura 4, ma duty diversi:
  TAC −3.647%, HU −29.140%, CU −39.693%.
- **Test 4:** TAC −26.840%, HU −33.820% ed errore topologico +33.333%.
  Figura 5 è internamente incoerente con i totali descritti nel testo; le sue
  etichette restano solo benchmark.
- **7SP4:** `integer infeasible`. Il gap residuo coinvolge separazione al
  pinch, struttura exchanger e area; nessun bound è stato rilassato dalla rete
  pubblicata.
- **10SP1:** modello costruito e presolto, nessun incumbent entro 60 s. Non è
  prova di infeasibility: `SUPPORTED_NOT_VALIDATED`.
- **EX1:** i valori F e Cp arrotondati di I4 non chiudevano il Q esplicito
  della Tabella 14. `F_U=Q/(Tin-Tout)` è una correzione source-first. Utility
  esatte, area +2.287%, un exchanger in più.
- **EX2:** HU esatta e area +0.478%, ma 8 exchanger contro 9 e duty/topologia
  differenti. Il multiple-match è generale per tutte le coppie di processo.

`Amax`, `qL`, controlli di partizione e costi utility BAR05 non dichiarati sono
marcati `IMPLEMENTATION_PARAMETER`/`SOURCE_NOT_SPECIFIED`. Non sono stati
aggiunti coefficienti, if per nome caso o topologie obbligatorie.

## Separazione delle modifiche

- Refactoring strutturale: intestazioni uniformi e mappa delle undici fasi.
- Documentazione: docstring, commenti bibliografici, architettura, traceability
  e validazione.
- Bug: soltanto registrati in questo file; nessuna correzione matematica è
  inclusa.
