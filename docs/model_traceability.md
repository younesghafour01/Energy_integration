# Shared thermal infrastructure

Dipendenze: `thermal_preprocessing` → BAR05 → TRA15. BAR05 è il modello base
con Corrigendum 2006; TRA15 importa BAR05 e aggiunge esclusivamente le proprie
estensioni. Non esiste alcuna dipendenza BAR05 → TRA15.

File neutro: `src/common/thermal_preprocessing.py`. BAR05 non importa il
modulo THI15; entrambe le pipeline importano direttamente queste funzioni.

| Oggetto/funzione | Ruolo condiviso | Fonte/qualificazione | Consumatori |
|---|---|---|---|
| `Flusso` | corrente fisica, validazione e calcolo `Q` | struttura implementativa neutra | THI15, BAR05/TRA15 |
| `carica_caso_studio` | JSON → configurazione con oggetti `Flusso` | I/O neutro | THI15, BAR05/TRA15 |
| `converti_temperatura_pinch` | reale ↔ `T*` con ±ΔTmin/2 | convenzione Pinch; algoritmo dettagliato `TODO_REFERENCE` | THI15; wrapper BAR05 |
| `crea_cascata_termica` | Problem Table, MER e main pinch | THI15 assume la GCC; BAR05/TRA15 assumono zone/GCC; procedura `TODO_REFERENCE` | THI15, BAR05/TRA15 |
| `costruisci_GCC` | residui della cascata → punti `(Q,T*)` | infrastruttura Pinch condivisa | THI15, BAR05/TRA15 |

# Predesign utilities

Fonte principale: F. Thibault, A. Zoughaib, S. Pelloux-Prayer, “A MILP
algorithm for utilities pre-design based on the Pinch Analysis and an exergy
criterion”, 2015 (THI15).

| Fonte | Eq./Sezione | Concetto matematico | File Python | Funzione | Oggetto Python | Note |
|---|---|---|---|---|---|---|
| THI15 | Sec. 2.1.1 | GCC, MPP, PPP e self-sufficient pockets | `src/predesign/THI15_predesign.py` | `self_sufficient_pockets` | `main_pinch_points`, `potential_pinch_points`, `pockets` | Il riconoscimento numerico con tolleranza è una IMPLEMENTATION CHOICE. |
| Pinch Analysis / THI15 Sec. 2.1.1 | Preprocessing GCC | Conversione reale ↔ Pinch `T*` | `src/common/thermal_preprocessing.py` | `converti_temperatura_pinch` (importata come `converti_temperatura`) | Accetta solo `reale` e `pinch`; non conosce la scala HENS. |
| THI15 | Sec. 2.1.1 | Zone, angular points, passo massimo | `src/predesign/THI15_predesign.py` | `discretizza_GCC`, `riordina_zone_per_milp` | `zone_GCC`, `S_z`, tuple `(z,k)` | La fonte descrive il dimezzamento degli intervalli oltre il passo massimo. |
| THI15 | Eq. (1) | COP heat pump di processo | `src/predesign/THI15_predesign.py` | `genera_candidate_utilities` | `COP_HPPr`, candidato `(y,j,z,k)` | Temperature in kelvin; livelli evaporatore/condensatore corretti con `EvaP`/`CondP`. |
| THI15 | Eq. (2) | COP utility heat pump | `src/predesign/THI15_predesign.py` | `genera_candidate_utilities` | `COP_HPUt`, candidato `(z,k)` | Sorgente esterna a `T0`. |
| THI15 | Eq. (3) | COP chiller | `src/predesign/THI15_predesign.py` | `genera_candidate_utilities` | `COP_ref`, candidato `(z,k)` | Nel codice la tecnologia è denominata `Ref`. |
| THI15 | Eq. (4) | Efficienza ORC | `src/predesign/THI15_predesign.py` | `genera_candidate_utilities` | `Eff_ORC`, candidato `(z,k)` | Calcolata prima del MILP. |
| THI15 | Eq. (5) | Efficienza CHP | `src/predesign/THI15_predesign.py` | `genera_candidate_utilities` | `Eff_CHP`, candidato `k` in zona `Z` | Calcolata prima del MILP. |
| THI15 | Eq. (6)-(10) | Presenza e frazione d'uso delle utility | `src/predesign/THI15_predesign.py` | `crea_modello_utilities` | `BoolChp`, `BoolRef`, `BoolORC`, `BoolHPPr`, `BoolHPUt`; `F*` | Vincoli `F <= Bool`; bounds `0 <= F <= 1`. |
| THI15 | Eq. (11)-(14) | Numero massimo per tecnologia | `src/predesign/THI15_predesign.py` | `crea_modello_utilities` | somme di `Bool*` | CHP, chiller, ORC e limite condiviso HPPr/HPUt. |
| THI15 | Eq. (15)-(16) | Calore prelevato dalla GCC | `src/predesign/THI15_predesign.py` | `crea_modello_utilities` | `Pprel[y,j]` | Zona `Z` fissata a zero. |
| THI15 | Eq. (17)-(19) | Calore fornito alla GCC | `src/predesign/THI15_predesign.py` | `crea_modello_utilities` | `Papp[z,k]` | Zona 1 fissata a zero; contributi HPPr, HPUt e CHP. |
| THI15 | Eq. (20)-(22) | Aggiornamento e non-negatività GCC | `src/predesign/THI15_predesign.py` | `crea_modello_utilities` | `NHL[z,k]` | La non-negatività è il lower bound della variabile. |
| THI15 | Eq. (23)-(25) | Consumo elettrico locale e totale | `src/predesign/THI15_predesign.py` | `crea_modello_utilities` | `Pelec[z,k]`, `TEC` | HPPr, HPUt e chiller. |
| THI15 | Eq. (26) | Produzione elettrica totale | `src/predesign/THI15_predesign.py` | `crea_modello_utilities` | `TEP` | Somma ORC e CHP. |
| THI15 | Eq. (27) | Calore di alimentazione CHP | `src/predesign/THI15_predesign.py` | `crea_modello_utilities` | `PprelCHP` | Ricostruito anche nel post-processing. |
| THI15 | Eq. (28)-(32) | Collocazione rispetto a `T0` e `TCondmax` | `src/predesign/THI15_predesign.py` | `genera_candidate_utilities` | filtri dei dizionari candidati | Le variabili vietate non vengono create: IMPLEMENTATION CHOICE equivalente sul dominio dei candidati. |
| THI15 | Eq. (33) | Obiettivo exergetico | `src/predesign/THI15_predesign.py` | `crea_modello_utilities` | `FinalExergy` | Combina cold/hot MER residui, CHP, `TEC` e `TEP`. |
| THI15 | Sec. 3 | Lettura e rappresentazione della soluzione | `src/predesign/THI15_predesign.py` | `risolvi_modello_utilities`, `costruisci_GCC_aggiornata`, `costruisci_curva_utilities` | dizionari `*_selezionate`, `gcc_aggiornata` | Post-processing; non aggiunge vincoli. |

| Funzione Python | Cosa costruisce | Fonte | Equazione / sezione |
|---|---|---|---|
| `crea_cascata_termica` (common) | Problem Table, MER e pinch | THI15 usa la GCC come input | TODO_REFERENCE per la procedura dettagliata |
| `costruisci_curve_composite` | Hot/Cold Composite Curves | THI15 | Sec. 2.1.1 e Fig. 2; procedura dettagliata da verificare |
| `costruisci_GCC` (common) | Punti GCC | THI15 | Sec. 2.1.1; IMPLEMENTATION CHOICE dalla cascata |
| `self_sufficient_pockets` | MPP, PPP, pockets | THI15 | Sec. 2.1.1, Fig. 1 |
| `discretizza_GCC` | Zone e punti `Q_z,k`, `T_z,k` | THI15 | Sec. 2.1.1 |
| `genera_candidate_utilities` | Configurazioni e parametri termodinamici | THI15 | Eq. (1)-(5), (28)-(32) |
| `crea_modello_utilities` | Variabili, vincoli e obiettivo | THI15 | Eq. (6)-(33) |
| `risolvi_modello_utilities` | Valori fisici e diagnostica solver | THI15 | Eq. (1)-(33), Sec. 3 |
| `costruisci_GCC_aggiornata` | Punti della nuova GCC | THI15 | Eq. (20)-(22), Sec. 3 |
| `costruisci_curva_utilities` | Curva utility per ICC | THI15 | Sec. 3.1 |

# BAR05

Fonti: A. Barbaro, M. J. Bagajewicz, “New rigorous one-step MILP formulation
for heat exchanger network synthesis”, 2005 (BAR05), e Corrigendum 2006. Dove
il corrigendum ripubblica un'equazione, la sua versione ha precedenza.

| Fonte | Eq./Sezione | Concetto matematico | File Python | Funzione | Oggetto Python | Note |
|---|---|---|---|---|---|---|
| BAR05 | Sec. 2.1 | Zone, correnti, utility e intervalli | `src/hens/BAR05_hens.py` | `costruisci_insiemi_base` | `Z`, `H`, `C`, `HU`, `CU`, `M`, `M_i`, `N_j` | Cold streams sulla scala HENS traslata. |
| BAR05 | Sec. 2.1 | Traslazione della scala HENS | `src/hens/BAR05_hens.py` | `converti_temperatura` | hot = reale; cold = reale + `delta_T_min` | Responsabilità esclusiva del modulo HENS. |
| TRA15 Sec. 2.1.1/2.2.1; BAR05 assume zone/intervalli | Preprocessing richiesto dall'implementazione | Orchestrazione minima di cascata, MER, pinch e GCC | `src/hens/BAR05_hens.py` | `esegui_analisi_pinch` | Specifica HENS; usa le primitive common e non costruisce Composite Curves/pockets THI15. |
| BAR05 | Sec. 2.1 | Match e opzioni topologiche | `src/hens/BAR05_hens.py` | `costruisci_insiemi_base`, `costruisci_insiemi_topologici` | `P`, `P_H`, `P_C`, `NI_H`, `NI_C`, `SH`, `SC`, `B` | `B` proviene dal JSON. |
| BAR05 + Corrigendum | Eq. (1)-(4) | Bilanci utility/processo | `src/hens/BAR05_hens.py` | `crea_modello_bilanci` | `q`, `F_H`, `F_C`, famiglie `bil_*` | Corrigendum per domini e refusi di Eq. (3)-(4). |
| BAR05 | Eq. (5)-(6) | Flussi cumulativi hot/cold | `src/hens/BAR05_hens.py` | `aggiungi_flussi_cumulativi` | `qhat_H`, `qhat_C` | Aggregazione per match e intervallo. |
| BAR05 + Corrigendum | Eq. (11)-(14) | Bounds di `qhat` e presenza `Y` | `src/hens/BAR05_hens.py` | `aggiungi_struttura_scambiatori` | `Y_H`, `Y_C`, `qL_BAR05`, limiti `qhat` | Eq. (13)-(14) usano `F_U` corretto dal corrigendum. |
| BAR05 + Corrigendum | Eq. (15)-(35) | Inizio/fine exchanger sui lati hot/cold | `src/hens/BAR05_hens.py` | `aggiungi_struttura_scambiatori` | `K_H`, `Khat_H`, `K_C`, `Khat_C` | Corrigendum per Eq. (15), (20), (31)-(35). |
| BAR05 | Eq. (36)-(42) | Conteggio exchanger | `src/hens/BAR05_hens.py` | `aggiungi_struttura_scambiatori` | `E` | Somma di beginnings/endings. |
| BAR05 + Corrigendum | Eq. (43)-(56) | Match multipli | `src/hens/BAR05_hens.py` | `aggiungi_scambiatori_multipli` | `qtilde_H`, `qtilde_C`, `X_BAR05`, `W_exchanger` | Corrigendum per Eq. (44) e (48). |
| BAR05 + Corrigendum | Eq. (57)-(80) | Consistenza delle portate | `src/hens/BAR05_hens.py` | `aggiungi_consistenza_portate` | `alpha_H`, `alpha_C`, vincoli `BAR05_57_80` | Corrigendum per Eq. (67), (73), (75)-(77), (79). |
| BAR05 + Corrigendum | Eq. (81)-(95) | Fattibilità temperature agli estremi | `src/hens/BAR05_hens.py` | `aggiungi_fattibilita_temperature` | vincoli `BAR05_81_95` | Corrigendum per Eq. (84)-(88), (92), (95). |
| BAR05 | Eq. (96) | Area totale del match | `src/hens/BAR05_hens.py` | `calcola_parametri_area`, `aggiungi_vincoli_area` | `coeff_area`, `A` | LMTD e coefficienti di film in unità coerenti. |
| BAR05 + Corrigendum | Eq. (97)-(102) | Area per exchanger multiplo | `src/hens/BAR05_hens.py` | `aggiungi_vincoli_area` | `Ahat`, `Ahat_base`, `G_BAR05`, `q_breve` | Corrigendum per Eq. (100)-(102). |
| BAR05 + Corrigendum | Eq. (103)-(104) | Massima area di shell | `src/hens/BAR05_hens.py` | `aggiungi_vincoli_area` | `U`, `Uhat`, `A_max_m2` | Eq. (104) corretta per i match in `B`. |
| BAR05 | Eq. (105) | Total annual cost | `src/hens/BAR05_hens.py` | `aggiungi_obiettivo_TAC` | `TAC` e quattro componenti di costo | Nel base è attiva una sola configurazione con fattore area unitario. |
| BAR05 | Sec. 3.1, Tabelle 1-4, Fig. 14 | Benchmark Problem 4S1 | `src/hens/BAR05_hens.py` | `salva_validazione_4S1` | report di validazione | Benchmark esclusivamente post-solve. |

| Funzione Python | Cosa costruisce | Fonte | Equazione / sezione |
|---|---|---|---|
| `crea_partizione_termica` | Zone e intervalli termici | BAR05 / TRA15 | BAR05 Sec. 2.1; procedura esplicita TRA15 Sec. 2.2.1 |
| `costruisci_insiemi_base` | Insiemi base e match | BAR05 | Sec. 2.1 |
| `genera_indici_scambio` | Dominio di `q_im,jn^z` | BAR05 | Sec. 2.1 |
| `calcola_entalpie_intervalli` | Entalpie di intervallo | BAR05 | Eq. (3)-(4) |
| `calcola_capacita_utility` | Parametri utility `F_U` | BAR05 + Corrigendum | Eq. (13)-(14) |
| `costruisci_insiemi_topologici` | `SH`, `SC`, `B`, estremi | BAR05 | Sec. 2.1 |
| `crea_modello_bilanci` | `q`, portate e bilanci | BAR05 + Corrigendum | Eq. (1)-(4) |
| `aggiungi_flussi_cumulativi` | `qhat_H`, `qhat_C` | BAR05 | Eq. (5)-(6) |
| `aggiungi_struttura_scambiatori` | `Y`, `K`, `Khat`, `E` | BAR05 + Corrigendum | Eq. (11)-(42) |
| `aggiungi_scambiatori_multipli` | Variabili per `B` | BAR05 + Corrigendum | Eq. (43)-(56) |
| `aggiungi_consistenza_portate` | Coerenza delle portate dei rami | BAR05 + Corrigendum | Eq. (57)-(80) |
| `aggiungi_fattibilita_temperature` | Approcci agli estremi HEX | BAR05 + Corrigendum | Eq. (81)-(95) |
| `calcola_parametri_area` | LMTD e coefficienti area | BAR05 | Eq. (96) |
| `aggiungi_vincoli_area` | Area e numero shell | BAR05 + Corrigendum | Eq. (96)-(104) |
| `aggiungi_obiettivo_TAC` | TAC | BAR05 | Eq. (105) |
| `risolvi_modello` | Soluzione, rete e residui | BAR05 | Sec. 3; IMPLEMENTATION CHOICE per l'estrazione |

# TRA15

Fonte principale: C.-T. Tran et al., “New features to Barbaro's heat exchanger
network algorithm: heat exchanger technologies and waste heat flow
representation”, ECOS 2015 (TRA15). Il modello base è esplicitamente BAR05.

| Fonte | Eq./Sezione | Concetto matematico | File Python | Funzione | Oggetto Python | Note |
|---|---|---|---|---|---|---|
| TRA15 | Sec. 2.1.1 | Insiemi base BAR05 | `src/hens/BAR05_hens.py` | `costruisci_insiemi_base`, `costruisci_insiemi_topologici` | `Z`, `H`, `C`, `HU`, `CU`, `M`, `P`, `NI_H`, `NI_C` | Core condiviso dichiarato dalla fonte. |
| TRA15 | Eq. (1)-(2) | Bilanci hot utility/processo | `src/hens/BAR05_hens.py` | `crea_modello_bilanci` | `F_H`, `q`, `delta_H_H` | Bilanci cold costruiti in forma analoga, come indicato dal testo. |
| TRA15 | Eq. (3) | Area base controcorrente | `src/hens/BAR05_hens.py` | `calcola_parametri_area` | `coeff_area` | Coincide concettualmente con BAR05 Eq. (96). |
| TRA15 | Eq. (4) | Numero shell base | `src/hens/BAR05_hens.py` | `aggiungi_vincoli_area` | `A`, `U` | `A <= Amax * U`. |
| TRA15 | Eq. (5) | TAC base | `src/hens/BAR05_hens.py` | `aggiungi_obiettivo_TAC` | `TAC` | Il framework completo usa l'estensione Eq. (11). |
| TRA15 | Sec. 2.2.1 | Algoritmo di partizione | `src/hens/BAR05_hens.py` | `crea_partizione_termica` | `intervalli` | Tre passaggi descritti dalla fonte. |
| TRA15 | Eq. (6) | Fattore correttivo tecnologia | `src/hens/TRA15_hens.py` | `costruisci_tecnologie` | `FHEX_t` | L'oggetto TRA15 espone al core il fattore area; BAR05 assume uno. |
| TRA15 | Eq. (7) | Area con tecnologie multiple | `src/hens/TRA15_hens.py` + core BAR05 | `costruisci_tecnologie`, `aggiungi_variabili_area`, `aggiungi_vincoli_area` | `A[z,i,j,t]` | TRA15 costruisce il dominio; BAR05 riusa l'equazione d'area base. |
| TRA15 | Eq. (8)-(9) | Match vietati/ammessi per tecnologia | `src/hens/TRA15_hens.py` | `costruisci_tecnologie` | `P_t`, dominio di `A/U` | Le variabili vietate non vengono create. |
| TRA15 | Eq. (10) | Massima area per tecnologia | `src/hens/TRA15_hens.py` + core BAR05 | `costruisci_tecnologie`, `aggiungi_vincoli_area` | `A[z,i,j,t]`, `U[z,i,j,t]` | Parametri e dominio in TRA15; vincolo base riusato. |
| TRA15 | Eq. (11) | TAC con indice tecnologia | `src/hens/BAR05_hens.py` | `aggiungi_obiettivo_TAC` | `TAC` | Include utility, costi fissi e area. |
| TRA15 | Eq. (12)-(13) | Temperature utility virtuali | `src/hens/TRA15_hens.py` | `costruisci_utilities_virtuali` | `VHU`, `VCU` | Un solo passaggio aggiuntivo di partizione. |
| TRA15 | Eq. (14)-(15) | Utility virtuali limitate alle surplus parts | `src/hens/TRA15_hens.py` | `genera_indici_scambio`, `aggiungi_tecnologia_virtuale` | dominio `q`, `TVIRTUAL`, `P_t` | Gli indici esclusi non generano variabili. |
| BAR05 + Corrigendum, richiamato da TRA15 Sec. 2.1 | Eq. (7)-(10) | Non-isothermal mixing | `src/hens/BAR05_hens.py` | `aggiungi_mixing_non_isotermo` | `qbar_H`, `qbar_C`, vincoli `NI_BAR05_*` | TRA15 importa la stessa implementazione BAR05. |
| TRA15 | Sec. 3, Tabella 2, Fig. 2 | Benchmark Test 1 | `src/hens/TRA15_hens.py` | `salva_validazione_test1` | report di validazione | I benchmark non entrano nel MILP. |

| Funzione Python | Cosa costruisce | Fonte | Equazione / sezione |
|---|---|---|---|
| `crea_partizione_termica` | Partizione termica | TRA15 | Sec. 2.2.1 |
| `costruisci_tecnologie` | `T`, `P_t`, costi e `FHEX_t` | TRA15 | Sec. 2.2.2, Eq. (6)-(11) |
| `costruisci_flussi_flessibili` | `HF_z`, `CF_z` e limiti d'uscita | TRA15 | Sec. 2.2.3 |
| `costruisci_utilities_virtuali` | `i_v`, `j_v` | TRA15 | Eq. (12)-(13) |
| `aggiungi_tecnologia_virtuale` | Tecnologia virtuale gratuita e `P_t` | TRA15 | Sec. 2.2.3, dopo Eq. (14)-(15) |
| `genera_indici_scambio` | Esclusioni delle utility virtuali | TRA15 | Eq. (14)-(15) |
| `aggiungi_variabili_area` | Aree e shell; TRA15 fornisce il dominio indicizzato per `t` | BAR05 / TRA15 | BAR05 Eq. (96)-(104); TRA15 Eq. (7), (10) |
| `aggiungi_vincoli_area` | Area corretta e capacità per tecnologia | TRA15 | Eq. (7)-(10) |
| `aggiungi_obiettivo_TAC` | TAC esteso | TRA15 | Eq. (11) |
| `individua_correnti_mixing_non_isotermo` | `NIH`/`NIC` del caso implementato | BAR05 / TRA15 | BAR05 Sec. 2.1; TRA15 Sec. 2.1.1; IMPLEMENTATION CHOICE per l'attivazione completa |
| `aggiungi_mixing_non_isotermo` (importata da BAR05) | `qbar` e bilanci NI | BAR05 + Corrigendum | Eq. (7)-(10) |
| `prepara_modello` | Pipeline completa TRA15 | TRA15 | Sec. 2.1-2.2 |
| `risolvi_modello` | Soluzione e alias di output | TRA15 | Eq. (11), Sec. 3 |
| `estrai_risultati` | TAC, HU, CU e duties | TRA15 | Sec. 3 |
| `salva_validazione_test1` | Confronto Test 1 | TRA15 | Tabella 2, Fig. 2 |

## Estensioni multi-caso BAR05/TRA15

| Fonte | Eq./Sezione | Oggetto matematico | Funzione/struttura Python | Casi |
|---|---|---|---|---|
| BAR05 + Corrigendum | Eq. (7)-(10) | Insiemi `NIH/NIC`, `qbar_H/qbar_C` e bilanci di mixing non-isotermo | `BAR05_hens.individua_correnti_mixing_non_isotermo` e `BAR05_hens.aggiungi_mixing_non_isotermo`; TRA15 importa quest'ultima | EX1, EX2, Test 1-4 |
| BAR05 | Sec. 3.2-3.5, Tabelle 5-20, Fig. 15-18 | dati fisici e benchmark | `dati_input/hens/BAR05_hens/{7SP4,10SP1,EX1,EX2}.json` | 7SP4, 10SP1, EX1, EX2 |
| TRA15 | Sec. 3, Tabelle 1-2, Fig. 4-5 | flexible outlet, tecnologie, utility virtuali, multiple match | `test3.json`, `test4.json`; strutture `HF_z`, `P_t`, `B` | Test 3, Test 4 |
| BAR05 / TRA15 | Sezioni case study | confronto source-first post-solve | `salva_validazione`: errori percentuali, topologia come multinsieme, duty/area aggregati | tutti i casi con campi `benchmark_*` |

Il dominio dei multiple match è simmetrico e generale. I campi
`benchmark_exchangers` non sono letti durante la costruzione del MILP.

## Matrice feature/caso

| Feature | 4S1 | 7SP4 | 10SP1 | EX1 | EX2 | Test1 | Test2 | Test3 | Test4 |
|---|---|---|---|---|---|---|---|---|---|
| zone multiple | Sì | Sì | — | Sì | — | — | — | — | — |
| pinch separation | Sì | Sì | — | Sì | — | — | — | — | — |
| multiple matches | Sì | — | — | — | Sì | — | — | — | Sì |
| non-isothermal mixing | — | — | — | Sì | Sì | Sì | Sì | Sì | Sì |
| multiple technologies | — | — | — | — | — | Sì | Sì | Sì | Sì |
| flexible streams | — | — | — | — | — | — | — | Sì | Sì |
| virtual utilities | — | — | — | — | — | — | — | Sì | Sì |
| area constraints | Sì | Sì | Sì | Sì | Sì | Sì | Sì | Sì | Sì |
| variable outlet temperatures | — | — | — | — | — | — | — | Sì | Sì |

Le assunzioni non presenti nelle fonti sono marcate
`SOURCE_NOT_SPECIFIED`/`IMPLEMENTATION_PARAMETER` nei JSON e in
`docs/case_source_cards.md`.
