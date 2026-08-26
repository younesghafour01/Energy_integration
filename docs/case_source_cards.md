# Schede source-first dei nuovi casi HENS

Le schede sono ricostruite direttamente dalle tabelle e figure delle fonti. Le
topologie pubblicate sono memorizzate solo nei campi `benchmark_*`: non
restringono il dominio del MILP. Le temperature sono in °C, i duty in kW e i
coefficienti di scambio in W/(m² K).

## Dati comuni TRA15 Test 3 e Test 4

Fonte: Tran et al. (2015), Sec. 3, Tabelle 1-2 e Figure 4-5. `ΔTmin = 20`.

| Corrente | Tipo | Tin → Tout | Q | h |
|---|---|---:|---:|---:|
| H1 | processo hot, outlet flessibile 45-65 | 175 → 45 | 361 | 56 |
| H2 | processo hot | 125 → 65 | 667 | 56 |
| C1 | processo cold | 20 → 155 | 750 | 56 |
| C2 | processo cold | 40 → 112 | 300 | 56 |
| H3 | hot utility | 180 → 179 | variabile | 56 |
| C3 | cold utility | 15 → 25 | variabile | 56 |

- Zone/separazione al pinch: non prescritte dalla fonte; rappresentazione a una
  zona, senza separazione (`IMPLEMENTATION_PARAMETER`).
- Tecnologie: T1, `FHEX=1`, 5292 USD/(unità·y) + 77.8 USD/(m²·y), per tutti i
  match fisicamente ammessi; T2, `FHEX=0.7`, 4000 + 50, ammessa solo per H1-C1.
- Splitting/non-isothermal mixing: lo splitting è permesso; gli insiemi NI non
  sono enumerati dalla fonte e l'inclusione delle correnti di processo è un
  `IMPLEMENTATION_PARAMETER`. Le utility sono escluse.
- Utility virtuali: previste da TRA15 Eq. (12)-(15) per la parte di surplus
  della corrente flessibile. Area massima: `SOURCE_NOT_SPECIFIED`; 1500 m² è il
  valore implementativo già usato da Test 1/2. I controlli numerici della
  partizione sono anch'essi `IMPLEMENTATION_PARAMETER`.

### TRA15 Test 3

Costo H3 173 e C3 86 USD/(kW·y). Figura 4: TAC 174 kUSD/y, HU 289 kW, CU 211
kW, H1 outlet 65 °C e sei exchanger: H3-C1 289; H1-C1 217 (T2); H1-C2 89;
H2-C1 244; H2-C2 211; H2-C3 211. Numero shell e area totale:
`SOURCE_NOT_SPECIFIED`.

### TRA15 Test 4

Costo H3 1800 e C3 86 USD/(kW·y). Sono ammessi fino a due exchanger per ogni
match processo-processo, in modo simmetrico e senza selezionare coppie dalla
soluzione pubblicata. Figura 5: TAC 598 kUSD/y, HU 254 kW e nove exchanger
(H3-C1 179, H3-C2 75, H1-C1 181 e 28, H1-C2 75, H1-C3 50, H2-C1 363,
H2-C2 150, H2-C3 154). CU, outlet flessibile selezionato, numero shell e area:
`SOURCE_NOT_SPECIFIED`. Le etichette di Figura 5 non chiudono perfettamente i
totali energetici descritti nel testo; sono conservate soltanto come benchmark.

## BAR05 7SP4

Fonte: Barbaro e Bagajewicz (2005), Sec. 3.2, Tabelle 5-8, Figura 15. Dati
originari delle correnti da Papoulias e Grossmann (1983). `ΔTmin=20`, due zone
con separazione al pinch.

| Corrente | Tin → Tout | Q | h |
|---|---:|---:|---:|
| H1 | 675 → 150 | 2187.500 | 55.556 |
| H2 | 590 → 450 | 427.778 | 55.556 |
| H3 | 540 → 115 | 531.250 | 55.556 |
| H4 | 430 → 345 | 1416.667 | 55.556 |
| H5 | 400 → 100 | 1000.000 | 55.556 |
| H6 | 300 → 230 | 2430.556 | 55.556 |
| C1 | 60 → 710 | 8486.111 | 55.556 |
| HU I7 | 801 → 800 | variabile | 55.556 |
| CU J2 | 80 → 140 | variabile | 55.556 |

Una tecnologia BAR05 lineare: 5291.9 USD/(unità·y) + 77.79 USD/(m²·y). Tutti
i match hot-cold fisicamente possibili sono ammessi; multiple match, NI mixing,
flexible stream e utility virtuali non sono richiesti esplicitamente. Figura 15
riporta 10 exchanger e 5087.1 m², con duty/area dei singoli exchanger salvati
nel JSON. Shell e costi utility: `SOURCE_NOT_SPECIFIED`. `Amax=1500`, `qL=1e-6`
e controlli di partizione sono `IMPLEMENTATION_PARAMETER` richiesti dalla
formulazione/implementazione, non ricavati dalla rete benchmark.

## BAR05 10SP1

Fonte: BAR05 Sec. 3.3, Tabelle 9-12, Figura 16. `ΔTmin=10`, una zona, nessuna
separazione al pinch.

| Corrente | Tin → Tout | Q | Corrente | Tin → Tout | Q |
|---|---:|---:|---|---:|---:|
| H1 | 160 → 93 | 163.592 | C1 | 60 → 160 | 211.667 |
| H2 | 249 → 138 | 324.983 | C2 | 116 → 222 | 179.022 |
| H3 | 227 → 66 | 660.547 | C3 | 38 → 221 | 429.033 |
| H4 | 271 → 149 | 425.644 | C4 | 82 → 177 | 456.000 |
| H5 | 199 → 66 | 655.025 | C5 | 93 → 205 | 432.444 |
|  |  |  | CU J6 | 38 → 82 | variabile |

Tutti gli `h` sono 55.556. Tecnologia/costi come 7SP4; sono ammessi tutti i 30
match fisicamente possibili. Multiple match, NI mixing, flexible stream e
utility virtuali non sono richiesti. Figura 16 riporta 10 exchanger e 2070.4
m², con dettagli nel JSON. HU, shell, costi utility e TAC esplicito:
`SOURCE_NOT_SPECIFIED`. `Amax=10000` non vincolante, `qL` e partizione sono
`IMPLEMENTATION_PARAMETER`.

## BAR05 EX1

Fonte: BAR05 Sec. 3.4, Tabelle 13-16, Figura 17. `ΔTmin=10`, due zone e
separazione al pinch.

| Corrente | Tin → Tout | Q | h |
|---|---:|---:|---:|
| H1 | 159 → 77 | 5204.722 | 111.111 |
| H2 | 267 → 88 | 1014.333 | 83.333 |
| H3 | 343 → 90 | 3780.944 | 69.444 |
| C1 | 26 → 127 | 2617.583 | 41.667 |
| C2 | 118 → 265 | 8007.417 | 138.889 |
| HU I4 | 376 → 375.9 | variabile | 277.778 |
| CU J3 | 15 → 30 | variabile | 166.667 |

La fonte permette mixing non-isotermo; poiché non enumera `NIH/NIC`, tutte le
correnti di processo e nessuna utility sono incluse (`IMPLEMENTATION_PARAMETER`).
Tecnologia: 8153.9 + 61.75 USD/(m²·y); tutti i match fisici, nessun multiple
match, flexible stream o utility virtuale. Figura 17: HU 2957 kW, CU 2332 kW,
8 exchanger, area 6997 m² e dettaglio duty/area nel JSON. TAC, shell e costi
utility: `SOURCE_NOT_SPECIFIED`. Per HU, la colonna Q esplicita della Tabella 14
ha precedenza sui valori F e Cp arrotondati. `Amax=10000`, `qL` e partizione
sono parametri implementativi.

## BAR05 EX2

Fonte: BAR05 Sec. 3.5, Tabelle 17-20, Figura 18. `ΔTmin=10`, una zona, senza
separazione al pinch.

| Corrente | Tin → Tout | Q | h |
|---|---:|---:|---:|
| H1 | 100 → 30 | 3616.667 | 111.111 |
| H2 | 75 → 30 | 2100.000 | 111.111 |
| H3 | 50 → 30 | 133.333 | 111.111 |
| C1 | 20 → 100 | 4666.667 | 111.111 |
| C2 | 20 → 75 | 1283.333 | 111.111 |
| C3 | 20 → 40 | 466.667 | 111.111 |
| C4 | 40 → 67.1875 | 483.333 | 111.111 |
| HU I4 | 180 → 179 | variabile | 111.111 |

Mixing non-isotermo su tutte le correnti di processo come rappresentazione
generale; fino a due exchanger per ogni match processo-processo. La capacità è
simmetrica e non deriva da Figura 18. Tecnologia: 9498.8 + 58.95 USD/(m²·y).
Figura 18: HU 1050 kW, 9 exchanger, 10018 m² e dettaglio nel JSON. CU non è
presente; TAC, shell e costi utility: `SOURCE_NOT_SPECIFIED`. Tout di C4 usa il
valore 67.1875 energeticamente coerente, mentre la tabella stampa 67.19.
`Amax=10000`, `qL` e partizione sono `IMPLEMENTATION_PARAMETER`.
