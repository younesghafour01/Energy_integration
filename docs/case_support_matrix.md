# Matrice di supporto dei casi HENS

Gli errori sono calcolati come `(simulato-fonte)/fonte·100`. “Non validato”
indica che il modello è eseguibile o costruibile, ma il benchmark complessivo
non è riprodotto: un TAC vicino, da solo, non è considerato validazione.

| Caso | Fonte | Input completo | Solver | Benchmark | Stato |
|---|---|---|---|---|---|
| BAR05 4S1 | Tabelle 1-4, Fig. 14 | Sì | integer optimal | regressione invariata; confronto source disponibile nel report | SUPPORTED_NEAR_BENCHMARK |
| BAR05 7SP4 | Tabelle 5-8, Fig. 15 | Sì, con parametri implementativi marcati | integer infeasible | non raggiunto | INFEASIBLE |
| BAR05 10SP1 | Tabelle 9-12, Fig. 16 | Sì, con parametri implementativi marcati | limite 60 s, nessun incumbent | non concluso | SUPPORTED_NOT_VALIDATED |
| BAR05 EX1 | Tabelle 13-16, Fig. 17 | Sì | integer optimal, tolerance | HU −0.000%; CU +0.000%; area +2.287%; exchanger +12.500%; topologia +12.500% | SUPPORTED_NEAR_BENCHMARK |
| BAR05 EX2 | Tabelle 17-20, Fig. 18 | Sì | integer optimal, tolerance | HU +0.000%; area +0.478%; exchanger −11.111%; topologia +33.333% | SUPPORTED_NEAR_BENCHMARK |
| TRA15 Test 1 | Tabelle 1-2, Fig. 2 | Sì | integer optimal | regressione invariata: TAC 180793.09 USD/y | SUPPORTED_NEAR_BENCHMARK |
| TRA15 Test 2 | Tabelle 1-2, Fig. 3 | Sì | integer optimal | TAC 176825.98 USD/y; regressione preservata | SUPPORTED_NEAR_BENCHMARK |
| TRA15 Test 3 | Tabelle 1-2, Fig. 4 | Sì | integer optimal | TAC −3.647%; HU −29.140%; CU −39.693%; topologia +0.000%, duty differenti | SUPPORTED_NOT_VALIDATED |
| TRA15 Test 4 | Tabelle 1-2, Fig. 5 | Sì, con inconsistenza source documentata | integer optimal | TAC −26.840%; HU −33.820%; topologia +33.333%; CU non riportata | SUPPORTED_NOT_VALIDATED |

## Classificazione smoke test dei sei nuovi input

| Caso | Esito richiesto | Diagnosi sintetica |
|---|---|---|
| Test 3 | SOLVED_BUT_BENCHMARK_DIFFERS | stesso multinsieme di match, ma utility e duty diversi |
| Test 4 | SOLVED_BUT_BENCHMARK_DIFFERS | costo utility elevato e surplus flessibile non riproducono Figura 5 |
| 7SP4 | INTEGER_INFEASIBLE | conflitto strutturale ancora da isolare tra partizione, struttura e area |
| 10SP1 | NON CLASSIFICABILE A-F: TIME_LIMIT | input accettato e modello costruito, ma nessun incumbent entro 60 s; non è corretto chiamarlo input non supportato o infeasible |
| EX1 | SOLVED_BUT_BENCHMARK_DIFFERS | utility esatte; un exchanger aggiuntivo e redistribuzione dei duty |
| EX2 | SOLVED_BUT_BENCHMARK_DIFFERS | area molto vicina, ma numero/topologia/duty differenti |

I report dettagliati sono sotto `risultati/hens/.../validazione_*.txt` e
riportano esclusivamente errori percentuali, senza classi qualitative per le
singole grandezze.
