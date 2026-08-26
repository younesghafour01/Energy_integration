# Validazione di equivalenza del refactoring

## Protocollo

Le baseline sono state acquisite prima delle modifiche con gli input presenti
nella repository. Dopo il gruppo di modifiche strutturali/documentali sono
stati rieseguiti gli stessi quattro comandi con Python/DOcplex/CPLEX
dell'ambiente locale.

Su Windows è stato impostato `PYTHONIOENCODING=utf-8` esclusivamente per
consentire all'entry point di ristampare `Δ` e `°`; questa variabile non cambia
il modello. Il confronto testuale ha escluso soltanto la riga non deterministica
`Tempo solve`. Tutte le altre righe dei sei report (quattro report principali e
due report di validazione HENS) risultano identiche.

## Sintesi prima/dopo

| Caso | Stato prima | Stato dopo | Obiettivo/TAC prima | Obiettivo/TAC dopo | Dimensione prima | Dimensione dopo | Esito |
|---|---|---|---:|---:|---|---|---|
| Predesign `4_flussi` | integer optimal solution | integer optimal solution | -0.016472 kW | -0.016472 kW | 1796 var, 724 bin, 1074 vincoli | 1796 var, 724 bin, 1074 vincoli | Identico |
| Predesign `dairy` | integer optimal, tolerance | integer optimal, tolerance | 651.105428 kW | 651.105428 kW | 2916 var, 1334 bin, 1583 vincoli | 2916 var, 1334 bin, 1583 vincoli | Identico |
| BAR05 `4S1` | integer optimal solution | integer optimal solution | 185510.20 USD/y | 185510.20 USD/y | 1142 var, 147 bin, 2437 vincoli | 1142 var, 147 bin, 2437 vincoli | Identico |
| TRA15 `test1` | integer optimal solution | integer optimal solution | 180793.09 USD/y | 180793.09 USD/y | 1719 var, 162 bin, 2741 vincoli | 1719 var, 162 bin, 2741 vincoli | Identico |

## Predesign `4_flussi`

| Grandezza | Prima | Dopo |
|---|---:|---:|
| `QH_min` | 20.000 kW | 20.000 kW |
| `QC_min` | 60.000 kW | 60.000 kW |
| Utility selezionate | 1 HPPr + 1 ORC | 1 HPPr + 1 ORC |
| HPPr indice | `(1,29,2,9)` | `(1,29,2,9)` |
| HPPr frazione `F` | 0.919265 | 0.919265 |
| HPPr `Qevap` / `Qcond` | 17.236 / 20.000 kW | 17.236 / 20.000 kW |
| HPPr potenza | 2.764 kW | 2.764 kW |
| ORC indice | `(1,20)` | `(1,20)` |
| ORC duty / produzione | 42.764 / 2.780 kW | 42.764 / 2.780 kW |
| `TEC` / `TEP` | 2.764 / 2.780 kW | 2.764 / 2.780 kW |
| Hot / cold MER residuo | 0.000 / 0.000 kW | 0.000 / 0.000 kW |

L'area totale non è un oggetto della formulazione di predesign THI15.

## Predesign `dairy`

| Grandezza | Prima | Dopo |
|---|---:|---:|
| `QH_min` | 1615.068 kW | 1615.068 kW |
| `QC_min` | 818.768 kW | 818.768 kW |
| Utility selezionate | 3 HPPr | 3 HPPr |
| HPPr `(1,1,2,9)` `Qevap/Qcond/W` | 232.743 / 277.063 / 44.320 kW | 232.743 / 277.063 / 44.320 kW |
| HPPr `(1,2,5,5)` `Qevap/Qcond/W` | 304.166 / 466.923 / 162.757 kW | 304.166 / 466.923 / 162.757 kW |
| HPPr `(2,24,5,5)` `Qevap/Qcond/W` | 558.923 / 607.400 / 48.478 kW | 558.923 / 607.400 / 48.478 kW |
| `TEC` / `TEP` | 255.555 / 0.000 kW | 255.555 / 0.000 kW |
| Hot / cold MER residuo | 540.745 / 0.000 kW | 540.745 / 0.000 kW |

## BAR05 `4S1`

| Grandezza | Prima | Dopo |
|---|---:|---:|
| TAC | 185510.20 USD/y | 185510.20 USD/y |
| Hot utility | 168.055556 kW | 168.055556 kW |
| Cold utility | 145.833333 kW | 145.833333 kW |
| Exchanger / shell | 7 / 7 | 7 / 7 |
| Area totale | 1373.591 m² | 1373.591 m² |
| Residuo energetico | `+1.705303e-13` kW | `+1.705303e-13` kW |

| Match | Duty prima [kW] | Duty dopo [kW] |
|---|---:|---:|
| H1-C1 | 109.722222 | 109.722222 |
| H1-C2 | 105.555556 | 105.555556 |
| H1-CU | 145.833333 | 145.833333 |
| H2-C1 | 472.222222 | 472.222222 |
| H2-C2 | 194.444444 | 194.444444 |
| HU-C1 | 168.055556 | 168.055556 |

Il match H1-C2 conserva due sezioni, una in zona 1 da 29.166667 kW e una in
zona 2 da 76.388889 kW.

## TRA15 `test1`

| Grandezza | Prima | Dopo |
|---|---:|---:|
| TAC | 180793.09 USD/y | 180793.09 USD/y |
| Hot utility | 202.500000 kW | 202.500000 kW |
| Cold utility | 180.500000 kW | 180.500000 kW |
| Exchanger / shell | 6 / 6 | 6 / 6 |
| Area totale | 1265.882 m² | 1265.882 m² |
| Residuo energetico | `+2.273737e-13` kW | `+2.273737e-13` kW |

| Match | Duty prima [kW] | Duty dopo [kW] |
|---|---:|---:|
| H1-C1 | 82.880952 | 82.880952 |
| H1-C2 | 97.619048 | 97.619048 |
| H1-C3 | 180.500000 | 180.500000 |
| H2-C1 | 464.619048 | 464.619048 |
| H2-C2 | 202.380952 | 202.380952 |
| H3-C1 | 202.500000 | 202.500000 |

## Validazione estensione multi-caso

Dopo il supporto BAR05 per il mixing non-isotermo e il validatore generale,
le regressioni sono rimaste invariate:

| Caso | Status | TAC [USD/y] | HU/CU [kW] | HEX/shell | Area [m²] | Dimensione MILP |
|---|---|---:|---:|---:|---:|---|
| BAR05 4S1 | integer optimal | 185510.20 | 168.055556 / 145.833333 | 7/7 | 1373.591 | 1142 var, 147 bin, 2437 vincoli |
| TRA15 Test 1 | integer optimal | 180793.09 | 202.500000 / 180.500000 | 6/6 | 1265.882 | 1719 var, 162 bin, 2741 vincoli |
| TRA15 Test 2 | integer optimal | 176825.98 | 195.191871 / 173.191871 | 6/6 | 1473.488 | 1721 var, 162 bin, 2742 vincoli |

| Nuovo caso | Solver | TAC errore % | HU errore % | CU errore % | HEX errore % | Area errore % |
|---|---|---:|---:|---:|---:|---:|
| Test 3 | integer optimal | −3.647 | −29.140 | −39.693 | +0.000 | non riportata |
| Test 4 | integer optimal | −26.840 | −33.820 | non riportata | −33.333 | non riportata |
| 7SP4 | integer infeasible | — | — | — | — | — |
| 10SP1 | nessun incumbent in 60 s | — | — | — | — | — |
| EX1 | integer optimal, tolerance | non riportato | −0.000 | +0.000 | +12.500 | +2.287 |
| EX2 | integer optimal, tolerance | non riportato | +0.000 | non applicabile | −11.111 | +0.478 |

I report `validazione_*.txt` riportano l'errore percentuale con segno al posto
delle classi qualitative. La metrica topologica è la somma delle differenze
assolute dei conteggi divisa per il numero di exchanger della fonte.

## Esito

Non è stata rilevata alcuna variazione di status, obiettivo, utility duties,
exchanger duties, numero di match/exchanger, area totale, variabili principali
o dimensioni MILP. Le sole grandezze non confrontate come invarianti sono i
tempi di solve, per loro natura non deterministici.
