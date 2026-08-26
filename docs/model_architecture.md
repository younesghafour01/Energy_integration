# Architettura dei modelli

## Direzione delle dipendenze

L'architettura HENS segue un solo verso:

```text
src/common/thermal_preprocessing.py
                ↓
src/predesign/THI15_predesign.py     src/hens/BAR05_hens.py
                                                  ↓
                                     src/hens/TRA15_hens.py
```

THI15 e BAR05 riusano il preprocessing termico neutro senza importarsi a
vicenda. TRA15 importa il modello base BAR05 e vi innesta le proprie estensioni.
BAR05 non importa, né direttamente né a runtime, il modulo TRA15.

## Proprietà dei moduli

| Modulo | Responsabilità | Non contiene |
|---|---|---|
| `src/common/thermal_preprocessing.py` | `Flusso`, caricamento JSON, conversione reale/Pinch, cascata e GCC | scale HENS, insiemi o equazioni di un modello |
| `src/predesign/THI15_predesign.py` | discretizzazione e MILP utilities THI15 | traslazione della scala HENS |
| `src/hens/BAR05_hens.py` | preprocessing necessario alla HENS, modello BAR05, Corrigendum 2006, area, TAC, solve e validazione | flexible streams, utility/tecnologia virtuale, classe tecnologia TRA15, `FHEX_t` e `P_t` |
| `src/hens/TRA15_hens.py` | BAR05 più tecnologie multiple, `FHEX_t`, `P_t`, flexible streams, utility virtuali e tecnologia virtuale | copie del modello matematico base BAR05 |

```text
BAR05 = modello base + corrigendum
TRA15 = BAR05 + estensioni TRA15
```

## Infrastruttura condivisa THI15/BAR05

Solo gli algoritmi identici per significato, input e output sono in
`src/common/thermal_preprocessing.py`: `Flusso`, `carica_caso_studio`,
`converti_temperatura_pinch`, `crea_cascata_termica` e `costruisci_GCC`.

Il common conosce solo le scale `reale` e `pinch`.
`BAR05_hens.converti_temperatura` aggiunge localmente la scala HENS (hot
invariata, cold traslata di `delta_T_min`). THI15 non conosce questa scala.

`esegui_analisi_pinch` resta specifica della pipeline HENS: orchestra il solo
sottoinsieme necessario a partizione e sintesi. La routine del predesign
produce invece anche gli oggetti richiesti dal modello THI15.

## Modello base BAR05

`BAR05_hens.py` possiede utility fisiche, partizione e insiemi base, insiemi
topologici, bilanci, formulazione BAR05/corrigendum, area, TAC, solve e
validazione. Anche il non-isothermal mixing Eq. (7)-(10) vive qui perché
appartiene a BAR05 e viene riusato da TRA15.

Gli input BAR05 non dichiarano più `FHEX`: nel modello base il fattore d'area
è implicitamente uno. BAR05 accetta esattamente una configurazione abilitata;
la scelta tra più tecnologie è responsabilità TRA15.

## Estensione TRA15

`TRA15_hens.py` importa il builder base `_prepara_modello` da BAR05 e
fornisce punti di estensione espliciti per:

- `TecnologiaHEN`, tecnologie multiple, `FHEX_t` e match `P_t`;
- flexible streams e relativi estremi di partizione;
- utility virtuali `VHU`/`VCU` e tecnologia virtuale gratuita;
- insiemi `HF`, `CF`, `MF`, `NF` e dominio di scambio TRA15;
- eventuali vincoli diagnostici sulla temperatura d'uscita flessibile.

Il builder BAR05 applica questi oggetti alle stesse equazioni base senza
conoscere o importare TRA15. Senza callback costruisce esclusivamente BAR05.
Il mixing non isotermo viene importato da BAR05 e applicato da TRA15, non
duplicato.

## API pubbliche

| Operazione | BAR05 | TRA15 |
|---|---|---|
| preparazione | `prepara_modello` | `prepara_modello` |
| soluzione | `risolvi_modello` | `risolvi_modello` |
| stampa | `stampa_risultati` | `stampa_risultati` |
| validazione | `salva_validazione` | wrapper di validazione TRA15 |

## Invarianti del refactoring

Il refactoring modifica proprietà e dipendenze, non la formulazione: ordine di
costruzione, indici, coefficienti, bounds, obiettivo, opzioni solver e nomi
consumati dal post-processing restano invariati. La validazione riporta
l'errore percentuale e non classi qualitative.

## Regressione del refactoring

| Caso | Variabili | Binarie | Vincoli | TAC [USD/anno] | Exchanger/shell | Area [m²] |
|---|---:|---:|---:|---:|---:|---:|
| BAR05 4S1 | 1142 | 147 | 2437 | 185510.20 | 7/7 | 1373.591 |
| TRA15 Test 1 | 1719 | 162 | 2741 | 180793.09 | 6/6 | 1265.882 |
| TRA15 Test 2 | 1721 | 162 | 2742 | 176825.98 | 6/6 | 1473.488 |

I conteggi e le topologie coincidono con le baseline precedenti al refactoring;
le differenze numeriche osservate sono nulle alla precisione riportata.
