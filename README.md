# Energy Integration from Scratch

Implementazione didattica in Python della Pinch Analysis, della preselezione
exergetica delle utility e della sintesi MILP di heat exchanger network (HENS).
Il riferimento principale è:

> A. Zoughaib (2017), *Energy Integration of Continuous Processes: From
> Pinch Analysis to Hybrid Exergy/Pinch Analysis*.

Il modello usa DOcplex e IBM CPLEX. I dati dei casi studio sono esterni al
codice e vengono letti da file JSON.

## Funzionalità

La parte Pinch comprende heat cascade, Composite Curves, GCC, MPP/PPP,
self-sufficient pockets, discretizzazione, preselezione delle utility, heat
pump, chiller, ORC, CHP e obiettivo exergetico.

La parte HENS implementa:

- partizione sulla scala HENS (hot reale, cold reale + `delta_T_min`);
- bilanci [1.37]-[1.41];
- tecnologie HEX multiple e costi [1.42]-[1.47];
- flexible hot e cold streams;
- insiemi `HF`, `CF`, `MF` e `NF`;
- utility virtuali [1.48]-[1.49];
- esclusione in preprocessing delle variabili `q` proibite da [1.50]-[1.51];
- tecnologia HEX virtuale a costo nullo;
- ricostruzione della temperatura di uscita ottima;
- report economico, energetico e confronto con i benchmark.

Le funzioni matematiche elementari restano separate. `prepara_HEN()`
esegue l'intera pipeline senza risolvere, `risolvi_HEN()` restituisce risultati
strutturati e `stampa_risultati_HEN()` produce il report unico.

## Avvio

Requisiti:

- Python 3;
- `matplotlib`;
- `docplex`;
- `cplex` e una installazione IBM CPLEX utilizzabile.

Esecuzione di un caso HENS:

```bash
python esegui.py dati_input_hens_test1.json hens-solve
```

Le quattro validazioni end-to-end sono:

```bash
python esegui.py dati_input_hens_test1.json hens-solve
python esegui.py dati_input_hens_test2.json hens-solve
python esegui.py dati_input_hens_test3.json hens-solve
python esegui.py dati_input_hens_test4.json hens-solve
```

Per lanciarle insieme:

```bash
python esegui.py dati_input_hens_test1.json hens-regression
```

Il log CPLEX si abilita aggiungendo `--log-cplex`. La modalità `completo`
mantiene la pipeline Pinch/exergy preesistente e salva i grafici in
`risultati/<nome-caso>/`.

## Casi studio HENS

| Test | Configurazione | PDF (kUSD/anno) | Modello (kUSD/anno) |
|---|---|---:|---:|
| 1 | solo T1 | 181 | 179.210 |
| 2 | T1 e T2 | 176 | 175.148 |
| 3 | T1/T2, H1 flessibile, HU 173 | 174 | 165.531 |
| 4 | T1/T2, H1 flessibile, HU 1800 | 598 | 439.026 |

Nel Test 2 la tecnologia T2 deriva esclusivamente dal match `H1-C1`
dichiarato nel JSON ed è selezionata dal modello. Nel Test 3 il surplus di H1
non è usato e la temperatura ottima ricostruita è 65 °C, in accordo con il
comportamento pubblicato. Tutti i bilanci globali chiudono entro la tolleranza
numerica.

Nel Test 4 il modello semplificato mantiene H3 al suo minimo termodinamico di
168.098 kW sia con Tout(H1)=65 °C sia forzando Tout(H1)=45 °C. Usare il
surplus aumenta quindi soltanto cold utility e area, e l'ottimo resta 65 °C.
Il paper ottiene invece 45 °C e una riduzione di hot utility. L'ablation BAR05
mostra che i vincoli di consistenza e la possibilità di due exchanger H1-C1
spostano parzialmente la soluzione, ma non riproducono da soli H3 = 254 kW o
TAC = 598 kUSD/year. Lo scostamento è riportato, non corretto artificialmente.

## Flexible streams e componenti virtuali

Esempio JSON:

```json
"flexible_streams": [
  {
    "codice": "H1",
    "enabled": true,
    "T_out_min_C": 45.0,
    "T_out_max_C": 65.0
  }
]
```

Gli estremi sono sempre inseriti nella partizione. Una partizione preliminare
determina le temperature delle utility virtuali; la partizione finale le
include e non genera altre utility, evitando dipendenze circolari.

Il `T_out` nominale descrive sempre la corrente completa, inclusa la surplus
part: coincide con `T_out_min_C` per una flexible hot stream e con
`T_out_max_C` per una flexible cold stream.

Per la cold utility virtuale le equazioni [1.49] sono applicate sulla scala
HENS. Nell'oggetto Python le temperature sono conservate sulla scala reale e
quindi traslate di `delta_T_min` durante la partizione. Il coefficiente di film
virtuale è il massimo tra quelli dei flussi di processo disponibili: la scelta
serve solo a mantenere finita l'equazione d'area. La tecnologia virtuale ha
costi nulli, match separati e non può influenzare la scelta delle tecnologie
fisiche. Il suo `A_max` riusa il massimo valore dichiarato dal designer per le
tecnologie fisiche; essendo `U` intera e non limitata, non limita il duty
virtuale. La coppia unica VHU/VCU è stata verificata sui benchmark economici
HENS a zona unica; non rappresenta utility virtuali distinte per ciascuna zona.

Per una flexible hot stream:

```text
Tout_opt = T_out_min + Q_virtual / CP
```

Per una flexible cold stream:

```text
Tout_opt = T_out_max - Q_virtual / CP
```

## Estensione rigorosa BAR05

La pipeline HENS puo attivare cumulativamente la parte di Barbaro e
Bagajewicz (2005), incluso l'insieme configurabile `B` per exchanger multipli.
Sono presenti gli insiemi `SH`/`SC`, i flussi cumulativi `qhat`, le variabili
`Y`, `K`, `Khat`, `E`, `alpha`, la consistenza delle frazioni di split e la
fattibilita di temperatura agli estremi. Per le coppie in `B` sono inoltre
presenti `qtilde`, `X`, `G`, `qbreve`, area, tecnologia e shell individuali.
Il corrigendum del 2006 prevale sul paper originale.

Esempio dati:

```json
"multiple_matches": [["H1", "C1"]],
"max_exchangers_per_multiple_match": 2
```

Gli script e i risultati delle ablation BAR05 sono conservati rispettivamente
in `archive/diagnostics/` e `archive/results/`; non fanno parte del percorso
operativo. `prepara_HEN()` accetta `bar05_blocchi` e `bar05_qL` per
analisi programmatiche. Il modello base resta il default quando
`bar05_blocchi` non viene passato.

Il non-isothermal mixing e `qbar` non sono attivi nel core corrente. La relativa
diagnostica storica e i valori pubblicati usati nei confronti sono archiviati e
non entrano nel MILP standard. I parametri fisici e i costi non sono stati
modificati per inseguire i benchmark.

## Sezione 1.4: modifica del processo

Il capitolo descrive il ciclo:

```text
parametri di processo -> simulazione -> estrazione stream -> Pinch/HENS
-> valutazione dell'obiettivo -> nuova configurazione
```

`valuta_configurazione_processo()` applica Pinch e HENS a una configurazione
già simulata e descritta da un JSON. `confronta_configurazioni_processo()`
ordina più configurazioni per TAC. Non è stato aggiunto un genetic algorithm:
il capitolo non fornisce un modello di unit operation direttamente eseguibile
dal repository.

Per automatizzare rigorosamente il concentratore agroalimentare mancano:

- modello delle unit operation e relativi bilanci;
- variabili decisionali e limiti operativi;
- proprietà termodinamiche coerenti per soluzione, vapore e condensato;
- procedura di estrazione automatica delle hot/cold streams;
- funzione obiettivo completa, inclusi investimenti e costi operativi.

Questi elementi devono essere forniti da un simulatore o dal designer prima di
aggiungere un'ottimizzazione metaeuristica.
