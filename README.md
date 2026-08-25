# Energy Integration from Scratch

Implementazione Python di Pinch Analysis, preselezione exergetica delle
utility e sintesi MILP di heat exchanger network (HENS). Il modello usa
DOcplex e IBM CPLEX; i casi studio sono file JSON esterni al codice.

Le fonti scientifiche locali sono:

- `fonti/Energy_Integration.pdf`;
- `fonti/BAR05.pdf`;
- `fonti/BAR05_corrigendum.pdf` (prevale sulle equazioni originali corrette
  nel 2006).

## Struttura

```text
integrazione_energetica.py       modello e post-processing
esegui.py                        CLI
casi/energy_integration/         Test 1-4
casi/bar05/                      4S1, 7SP4, 10SP1, EX1, EX2
tests/                           baseline e regressioni automatiche
docs/                            inventario e rapporto di validazione
fonti/                           PDF scientifici
risultati/                       output ordinari
_archive_validation/             diagnostica storica, non operativa
```

## Esecuzione

L'ambiente deve contenere `matplotlib`, `docplex` e un'installazione CPLEX
utilizzabile. Le sole modalità CLI disponibili sono `utilities` e `hens`.

```powershell
# HENS
.\.venv\Scripts\python.exe esegui.py casi\energy_integration\test1.json hens

# Pinch Analysis e utility predesign
.\.venv\Scripts\python.exe esegui.py dati_input_hens.json utilities

# Log CPLEX opzionale
.\.venv\Scripts\python.exe esegui.py casi\bar05\4S1.json hens --log-cplex
```

Regressione completa:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests\test_hens_regression.py
```

La suite risolve T1-T4 e 4S1 e controlla status, gap, TAC, HU/CU, duty,
topologia, area, shell, residuo energetico e temperature flessibili. Controlla
anche il dominio di BAR05 (73)-(74), la configurazione `splittable` e il
rifiuto esplicito di EX1/EX2. Le tolleranze sono dichiarate in
`tests/baseline_pre_cleanup.json`.

## Pipeline HENS

`prepara_HEN()` esegue il preprocessing e costruisce un unico MILP; non esiste
logica specifica per nome del caso. `risolvi_HEN()` risolve e restituisce dati
strutturati; `stampa_risultati_HEN()` produce il report leggibile.

La formulazione comprende:

- bilanci HENS [1.37]-[1.41];
- nucleo BAR05 con `q`, `qhat`, `Y`, `K`, `Khat`, `E`, `alpha`, consistenza
  delle portate e delle temperature;
- multiple exchanger configurabili con `hens.multiple_matches`;
- tecnologia `t`, `FHEX_t`, `P_t` e costi [1.42]-[1.47];
- flexible streams e utility/tecnologia virtuali [1.48]-[1.51].

La proprietà BAR05 di splitting è configurabile su ogni process stream:

```json
{"codice": "H1", "splittable": false}
```

Se il campo manca, il default è `true`, preservando il comportamento dei casi
Energy Integration precedenti. Le utility fisiche e virtuali non entrano in
`SH` o `SC`. Per le stream non splittable vengono attivate automaticamente le
famiglie applicabili BAR05 (68), (80), (81) e (82).

Per autorizzare più exchanger sulla stessa coppia:

```json
"multiple_matches": [["H1", "C1"]],
"max_exchangers_per_multiple_match": 2
```

Le equazioni BAR05 (73)-(74), e le altre famiglie con lo stesso dominio, sono
escluse per `(i,j) in B`. I benchmark presenti nel JSON sono usati soltanto
nel confronto post-solve, mai nell'obiettivo o nei vincoli.

## Stato di validazione

- Energy Integration T1-T4: regressione numerica invariata rispetto al
  checkpoint `pre-cleanup-validation`.
- BAR05 4S1: topologia e duty pubblicati riprodotti; area totale del modello
  1373.591 m² contro 1358.7 m² (+1.096%).
- BAR05 7SP4 e 10SP1: input ricostruiti dalle fonti, ma il primo tentativo non
  ha completato il solve entro circa quattro minuti; non sono dichiarati
  validati.
- BAR05 EX1 ed EX2: `NON ANCORA SUPPORTATI`. Richiedono non-isothermal mixing,
  `qbar_H`, `qbar_C` ed Eq. (7)-(10) con gli indici del corrigendum. Il codice
  solleva intenzionalmente `NotImplementedError` e non usa approssimazioni.

Il dettaglio numerico, la matrice delle funzionalità e le discrepanze residue
sono in `docs/validazione_finale.md`. L'inventario completo delle funzioni
prima della pulizia è in `docs/inventario_funzioni.md`.

## Limiti scientifici dichiarati

Il non-isothermal mixing non è implementato. 7SP4 e 10SP1 non possono ancora
essere usati come regressioni numeriche concluse. Le discrepanze pubblicate dei
Test 2-4 non sono state corrette con tuning, selezione post-hoc di equazioni o
parametri di benchmark nel MILP.

La modifica del processo descritta da Energy Integration richiede inoltre un
modello esterno delle unit operation, proprietà termodinamiche, variabili e
limiti operativi, estrazione delle stream e costi di processo. Il repository
valuta stream già definite; non contiene un simulatore di processo né un
ottimizzatore metaeuristico delle unit operation.
