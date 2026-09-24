# Formaty danych EwE (Ecopath with Ecosim) — źródło i weryfikacja

Ten dokument jest **podstawą**, na której opiera się cały nasz kanoniczny model danych
(`docs/data-contract.md`, `backend/ecosim/ingestion/parsers/`). Dotąd nasze parsery były
zbudowane wyłącznie na podstawie realnych plików wyjściowych w `DataEcosim/` — nigdy nie
zostały formalnie zweryfikowane względem oficjalnej dokumentacji programu, z którego te
dane pochodzą. Ten dokument to robi: zestawia, co oficjalna dokumentacja EwE mówi o
formatach danych (Ecopath, Ecosim, Ecospace, Monte Carlo), cytuje konkretne strony, i
kończy się sekcją **Rozjazdy** — konkretnymi, zweryfikowanymi miejscami, gdzie nasza
implementacja różni się od (albo nie jest pokryta przez) to, co dokumentacja opisuje.

## Źródła

- **User Guide** — `docs/User_guide/User-Guide-for-Ecopath-with-Ecosim-EwE-...pdf`, 308
  stron. Podręcznik użytkownika programu (interfejs, funkcje, jak z czego korzystać).
  Cytowany niżej jako **UG s.N**.
- **Podręcznik modelowania** — `docs/User_guide/Ecosystem-Modelling-with-EwE-...pdf`, 578
  stron. Bardziej matematyczne/naukowe źródło (równania, algorytmy, samouczki krok-po-kroku
  z konkretnymi nazwami plików). Cytowany niżej jako **PM s.N**.

**Zasada pracy z tymi dwoma dokumentami** (obowiązująca projektowo — patrz też pamięć
projektu): sekcje 1-5 tego pliku pokrywają to, co już zweryfikowaliśmy i czego faktycznie
dziś używamy. **Gdy pojawi się nowy temat wymagający weryfikacji** (nowa funkcja, inny
kształt danych, wątpliwość co do konwencji EwE) — najpierw sprawdzić, czy jest już tu
opisany; jeśli nie, użyć spisu treści poniżej, żeby znaleźć właściwy rozdział w PDF-ie i
doczytać **tylko tamten fragment**, zamiast zgadywać albo za każdym razem czytać cały
podręcznik od nowa. Po zweryfikowaniu — dopisać ustalenie do tego pliku, żeby następnym
razem było już gotowe.

### Spis treści — User Guide (308 stron)

```
Working with EwE
  Getting Started ................................................ 2
Ecopath
  Ecopath Input .................................................. 5
  Linked Stanza Recruitment ..................................... 22
  Ecopath Output ................................................ 26
  Ecopath Tools .................................................. 43
  Using Ecosampler .............................................. 45
Ecosim
  Density-dependent catchability ................................ 54
  Price Elasticity ............................................... 56
  Vulnerability Multiplier Estimator ............................. 62
  Time Series .................................................... 65
  Time Series Fitting ............................................ 68
  Hints for time series fitting .................................. 70
  Multi-sim ....................................................... 76
  Function shapes ................................................ 83
  Other Mortality Response Functions ............................. 87
  Monte Carlo ..................................................... 92
  Fishing policy exploration ..................................... 95
  CEFAS Management Strategy Evaluation (CEFAS-MSE) .............. 101
  MSE LP Constrained Optimization of Fishing Effort .............. 115
  Other mortality forcing ........................................ 120
  Environmental Productivity ..................................... 124
  Results Extractor .............................................. 127   <- prawdopodobne źródło naszych CSV
Ecospace
  Do You Need Ecospace? .......................................... 133
  What Transfers from Ecosim to Ecospace? ........................ 135
  Ecospace Workflow .............................................. 139
  Movement ........................................................ 143
  Dispersal Rate IBM .............................................. 147
  Land or water? / Excluding Map Cells ........................... 153
  Spatial Data .................................................... 159
  Response Curves ................................................ 163
  Spatial Distribution ........................................... 166
  Setting Base Effort ............................................ 170
  Model Type Options .............................................. 173
  Addressing Uncertainty ......................................... 177
  Ecospace Output ................................................. 182
Ecospace Advanced
  Cumulative Impacts .............................................. 187
  Ecoengineer Plug-In ............................................. 189
  Biomass Emitter .................................................. 199
  Spatial Optimizations (Edit) .................................... 210
  Ecological indicators: EcoIND ................................... 229
  Geospatial Considerations ....................................... 232
  Geospatial Projections .......................................... 236   <- WGS84 vs UTM/"Assume Square Cells"
  Spatial-Temporal Data ............................................ 239
  Spatial-Temporal Data Framework ................................. 243
  Sharing External Spatial Datasets ............................... 255
  Spatial Model Skill Assessment .................................. 260
Ecotracer
  Input and Data ................................................... 268
  Output and Data Management ...................................... 274   <- opis mechanizmu CSV-per-species dla Ecospace
  Driving Ecotracer with Spatial-Temporal Data .................... 277
Plug-ins
  Overview of EWE Plug-ins ......................................... 286
  enaR SCOR Files from Ecospace .................................... 290
Glossary .......................................................... 292
Contributors ...................................................... 293
Versioning history ................................................ 294
```

### Spis treści — Podręcznik modelowania / "Ecosystem Modelling with EwE" (578 stron)

```
Part I.   Ecosystem Modelling
  1. On modelling and making predictions .......................... 10
  2. Modelling predator-prey interactions ......................... 23
  3. Your research question? ....................................... 30
  4. Defining the ecosystem ......................................... 33
Part II.  An Introduction to Ecopath
  5-9. Energy balance / units / P/B / Q/B / EE .................. 39-59
  10. Mass balance .................................................. 65
  11. Multi-stanza life histories ................................... 76
  12. Uncertainty .................................................... 80
Part III. Network Analysis
  13. Network analysis ............................................... 86
Part IV.  An Introduction to Ecosim
  14. Foraging arena theory ......................................... 96
  15-16. Dynamic modelling / intro to Ecosim ...................... 109-111
  17. Predicting consumption ....................................... 113
  18. Age-structured dynamics ....................................... 123
  19. Recruitment and compensation ................................. 128
  20. Predator satiation and foraging time / Tutorial: Results extractor .. 132/135
  21-26. Holling response, instability, hatchery, mortality, foraging, bout feeding .. 138-170
Part V.   Ecosim: Environment
  27-30. Environmental impacts, primary production, mediation, cyclic dominance .. 180-210
Part VI.  Fitting Models to Data
  31-37. Density-dependence & vulnerability multipliers .......... 221-252
  Tutorial: Time series fitting .................................... 257
  Tutorial: Monte Carlo runs ........................................ 264   <- konkretny opis formatu wyjścia MC
  38. Stock reduction analysis ...................................... 266
  Tutorial: Uncertainty in time series data / Anchovy Bay Ecosampler .. 267-273
Part VII. Ecosim: Fisheries
  Tutorial: MSY ...................................................... 275
  39. Management strategy evaluation ................................ 281
  40. Constrained optimization of fishing effort ................... 288
  41. Fleet effort dynamics .......................................... 297
Part VIII. Ecological, Social and Economic Factors ............... 301-356
Part IX.  Ecospace Introduction
  49. Spatial modelling primer ...................................... 359
  50. Introduction to Ecospace ...................................... 366
  51. Habitat capacity ............................................... 373
  52. Spatial implementation of multi-stanza and IBM ................ 381   <- równania dynamiki komórek siatki
  Tutorial: Spatial model of Anchovy Bay ............................ 389
  Tutorial: Making a base map (bathymetry) .......................... 395
  53. Spatial fishery dynamics ....................................... 399
  54. Predicting spatial effort / Tutorial: Ecospace maps ......... 402-407
  Tutorial: Spatial temporal framework .............................. 413
  55. Migration and advection ........................................ 420
Part X.   Spatial Planning ......................................... 426-447
Part XI.  Spatial Applications (studia przypadków) ................ 451-490
Part XII. Tracking Persistent Pollutants (Ecotracer) ............... 495-511
Part XIII. Research and Policy Questions (studia przypadków) ...... 516-553
Part XIV. Course planning .......................................... 556
Contributors ........................................................ 561
Versioning history .................................................. 567
```

Oba przeczytane w całości (ekstrakcja tekstu przez `pypdf`, nie tylko przeszukanie po
nazwach) pod kątem czterech obszarów: format przestrzenny Ecospace, format szeregów
czasowych Ecosim, Monte Carlo, konwencje numerowania grup/flot.

---

## 1. Ecopath (model bazowy)

Ecopath to statyczny model bilansu masy — punkt startowy, z którego Ecosim/Ecospace
dziedziczą grupy funkcyjne i parametry. Nie ingestujemy danych Ecopath bezpośrednio; nasz
pipeline zaczyna się od wyników Ecosim/Ecospace, ale **nazwa modelu Ecopath** (`ModelName`
w nagłówkach `<HEADER ecopath/>`) jest tym, co odróżnia "model" od "scenariusza" w naszym
dwupoziomowym schemacie identyfikacji (patrz pamięć projektu: jeden model Ecopath →
wiele scenariuszy Ecosim). To zgodne z tym, jak dokumentacja opisuje relację Ecopath→Ecosim
(PM, wielokrotnie w rozdziałach wprowadzających) — bez rozjazdu.

### Czy dane Ecopath da się eksportować do folderu plików? Zweryfikowane 28.08 — nie ma takiej konwencji

Sprawdzone pod kątem realnej potrzeby: użytkownik chce opcjonalnie dodać "kafelek Ecopath",
analogiczny do output/input. Przeszukane UG s.5-44 ("Ecopath Input", "Linked Stanza
Recruitment", "Ecopath Output", "Ecopath Tools") oraz PM rozdz. 5-12 (s.39-80) pod kątem
mechanizmu eksportu danych Ecopath do plików płaskich.

**Wniosek: manual nie opisuje niczego takiego.** Jedyny udokumentowany sposób dzielenia się
danymi Ecopath to eksport/import **całego modelu** przez Ecobase (zewnętrzne, internetowe
repozytorium modeli): *"This can be done from the menu File > Export model > To Ecobase.
Ecobase models are available at www.ecobase.ecopath.org and can also be downloaded directly
from File > Import model > From Ecobase"* (UG s.6). Model Ecopath jest w obu podręcznikach
konsekwentnie traktowany jako **jeden plik bazy danych** ("the database", liczba pojedyncza,
PM ok. s.55 w sekcji tutorialowej) — nie zestaw wyeksportowanych tabel.

Sekcja "Ecopath Output" (UG s.26-42) opisuje wyłącznie **formularze na ekranie wewnątrz
aplikacji EwE** (Basic Estimates, Mortality Rates, panel Status), nigdy eksport do pliku:
*"a suite of indicators are given in the Ecopath > Output forms, which is the topic of this
chapter"* (UG s.26). "Ecopath Tools" (s.43-44) to wyłącznie diagram przepływów (Flow
Diagram) — też brak narzędzi eksportu.

**Brak też odpowiednika `<HEADER ecosim/>`/`RunInfo.txt`** — żadnej konwencji nazw
plików/folderów per "przebieg" Ecopath, co ma sens: to model bez wymiaru czasu/przebiegu,
nie ma czego tak nazywać.

**Konsekwencja dla architektury tego projektu:** w przeciwieństwie do output/input, gdzie
odkrywanie oparte o treść pliku miało realną podstawę w dokumentacji (nagłówki `<HEADER
.../>`, `RunInfo.txt`), **tu takiej podstawy nie ma**. Zbudowanie "wskaż folder, appka sama
znajdzie pliki Ecopath" byłoby wymyśleniem konwencji, której EwE nie ma — dokładnie to,
przed czym ostrzega zasada [[ecosim-verify-against-ewe-docs]]. Jeśli wsparcie dla Ecopath
ma powstać, musi mieć inny kształt niż istniejące dwa kafelki (np. pojedynczy plik, nie
folder) — do ustalenia z realną próbką danych, nie z góry.

---

## 2. Ecosim — szeregi czasowe

**Realne źródło naszych CSV-ów jest prawdopodobnie nieudokumentowane wprost.** User Guide
wymienia **"Results Extractor Plugin"** (CEFAS, status "Released", kategoria "Data export",
UG s.301) jako osobny plugin do eksportu wyników — ale **nigdzie nie dokumentuje jego
dokładnego układu kolumn**. To niemal na pewno jest prawdziwe źródło naszych plików (4
kształty: szeroki-wg-ID, szeroki-wg-nazwy/predacja, długi flota-grupa, jednoseryjny) — ale
nie ma oficjalnej specyfikacji, względem której moglibyśmy je zweryfikować.

**Podstawowy, wbudowany auto-save Ecosim (BEZ pluginu) ma inny, prostszy kształt:** "modele
używające tylko Ecosim do dynamiki czasowej będą miały **jeden plik wyjściowy** zawierający
**jedną kolumnę na grupę funkcyjną i 12 wierszy danych na rok**" (**✏️ poprawiony numer strony
27.08: UG s.275, nie s.289** — s.289 to w rzeczywistości środek tabeli statusów pluginów,
niezwiązanej treści; s.275 to rozdział "Output and Data Management" opisujący mechanizm
współdzielony z Ecotracer) — strukturalnie to ten sam "wide" kształt co
`biomass_monthly.csv` (`timestep\group` + kolumny ID), tylko **plik nie musi nazywać się
`<zmienna>_annual.csv`/`<zmienna>_monthly.csv`** jak w przypadku pluginu Results Extractor.

**✅ Naprawione (27.08).** Nasz parser rozpoznawał `freq` (roczne/miesięczne) **wyłącznie z
nazwy pliku** (`_annual`/`_monthly`) — dla pliku bez takiego sufiksu domyślnie zakładał
"annual", nawet gdyby dane w środku były w rzeczywistości miesięczne. Zweryfikowane na
prawdziwych plikach: EwE **zawsze** nazywa kolumnę czasu w samym nagłówku danych `year` dla
danych rocznych i `timestep` dla miesięcznych — niezależnie od nazwy pliku, konsekwentnie
w każdym z 4 kształtów, jakie mamy (wide-by-id, long, single-series — sprawdzone wprost na
`biomass_annual/monthly.csv`, `catch-fleet-group_annual/monthly.csv`, `fib_annual/monthly.csv`).
`ecosim_csv.py` teraz ustala `freq` z **tej etykiety w nagłówku danych**, nie z nazwy pliku —
nazwa pliku zostaje tylko jako zapasowa wskazówka, gdyby nagłówek był niejednoznaczny. Dla
wszystkich naszych obecnych plików to nie zmienia niczego (nagłówek i nazwa pliku zawsze się
zgadzają) — ale plik z podstawowego auto-save, bez sufiksu `_annual`/`_monthly` w nazwie,
będzie teraz poprawnie rozpoznany jako miesięczny. Pokryte testami z syntetycznym plikiem
zbudowanym dokładnie wg opisu z podręcznika (nie mamy prawdziwej próbki tego formatu).

**Multi-sim** (Ecosim > Tools > Multi-sim, UG s.79-81 + PM s.267-280) — osobna funkcja od
Monte Carlo (patrz sekcja 4): odtwarza Ecosim raz na każdy plik CSV różniących się wartości
funkcji wymuszających (np. 20 skorelowanych szeregów produktywności środowiskowej).
**✏️ Poprawione (27.08, druga tura):** osobny folder na przebieg **nie jest domyślny** —
to opcjonalny checkbox: "Select the folder where the results of each simulation will be
stored... **If you would like each simulation to generate its own folder... check the
create unique folder for every run box**" (UG s.79-80). Domyślnie (odznaczone) wszystkie
przebiegi zapisują się **razem, w jednym folderze** (bez udokumentowanej konwencji
rozróżniania plików między przebiegami w tym trybie). Tylko z zaznaczonym checkboxem dostajemy
**jeden folder z tą samą parą `biomass_annual.csv`/`biomass_monthly.csv`** co normalny
pojedynczy przebieg — cytat: "ta struktura łatwo nadaje się do analizy w R" (PM s.279).
Zapisywany jest też log przebiegu.

**Jednostki:** ani UG, ani PM nie podają wprost, jak jednostki są oznaczone w eksportowanych
plikach CSV. Nasz schemat ma kolumnę `unit` (opcjonalną) — nie ma z czym jej formalnie
zweryfikować z dokumentacji; to nie jest rozjazd, to po prostu obszar, którego oficjalna
dokumentacja nie precyzuje.

### Nie każdy output ma wymiar grupa/flota — realna luka w naszym pipeline

Rozdział "Results Extractor" (UG s.127-131, przeczytany 27.08 po pytaniu użytkownika "czy
flota to jedyna możliwość?") potwierdza wprost, że checkboxy Results Extractora **nie
wszystkie** otwierają okno wyboru grup/flot: "For some checkboxes a selection window will be
opened" (UG s.128) — czyli tylko *niektóre*. Konkretny, jawny przykład **wyniku
bez żadnego wymiaru grupa/flota**: opcja "Fitting Statistics" > SS "gives output of the sum
of squares for all function groups **as well as an overall SS value for the whole model**"
(UG s.130) — jedna liczba dla całego modelu, nie per grupa.

Osobny, większy przykład: plugin **ECOIND** (UG s.229-231, status "Released" wg rejestru
pluginów) liczy **wskaźniki ekosystemowe** — biomass-based, catch-based, trophic-based,
size-based, species-based (Table 3 B-E) — np. "Total Catch" całego systemu, "TL co."
(poziom troficzny **całej społeczności**), MTI (Marine Trophic Index). To są zagregowane
wartości **całego ekosystemu lub całej kategorii** (np. "wszystkie ryby", "wszystkie
bezkręgowce"), nie wartości per pojedyncza grupa funkcyjna z naszego `group_id`/`group_name`
— nie dałoby się ich w ogóle zmapować na wpis w `Mapa_grupy_fleets.xlsx`, bo z definicji nie
odpowiadają jednej grupie.

**Wniosek — dokładna odpowiedź na pytanie użytkownika:** grupa/flota to **jeden z możliwych
kształtów** danych wyjściowych EwE, nie jedyny ani nie uniwersalny wymóg samego
oprogramowania. **Ale to prawdziwa luka w naszym pipeline, nie tylko w opisie**: żaden z 4
kształtów CSV, które faktycznie parsujemy (`ecosim_csv.py`), ani żaden z typów rastrów,
które rozpoznajemy (`asc_grid.py`: Biomass/Catch/Discards/HabitatCapacity per grupa,
Effort per flota), nie odpowiada wynikom bez wymiaru grupa/flota (SS całego modelu, wskaźniki
ECOIND) — takich plików nie ma też w `DataEcosim/`. **Aktualizacja (27.08, tego samego dnia,
druga tura):** `_find_group_map()` w `pipeline.py`/`spatial_pipeline.py` **przestał być
bezwarunkowy** — realny użytkownik trafił na folder z prawdziwymi wynikami Monte Carlo, gdzie
słownik był trzymany osobno, i dostał odrzucenie cytujące plik, o którym EwE nigdy nie
słyszało. Naprawione (27.08): `run_ingest()`/`build_raster_index()` przestały wymagać słownika —
`group_id`/`fleet_id` (prawdziwe dane) zachowane, tylko kolumny `*_name` puste; nazwy
rastrów i tak odczytywane wprost z nazwy pliku, więc dane przestrzenne w ogóle tego nie
odczuwają. **Druga tura (28.08):** cały mechanizm (plik, `group_map.py`, powiązany endpoint
API) usunięty z rdzenia całkowicie, nie tylko uczyniony opcjonalnym — patrz sekcja
"Rozjazdy" niżej i `docs/Plans and TO_DO lists/28.08_session_summary.md`.

### Struktura katalogów wyjściowych EwE — nie ma jednej, ponownie zweryfikowane 27.08

Po naprawie wymogu słownika okazało się, że **walidator dalej odrzucał ten sam prawdziwy
folder Monte Carlo** — tym razem dlatego, że wymagał podfolderu nazwanego dosłownie
`output`. Użytkownik słusznie zakwestionował to jeszcze raz: "przeczytaj dokumentację żeby
wiedzieć dokładnie jakie są struktury katalogów możliwe w różnych wersjach outputów — nie
używaj niczego co zrobiliśmy wcześniej." Pełne, świeże ponowne przeszukanie obu PDF-ów
(nie tylko potwierdzenie tego, co już było w tym pliku) dało jednoznaczną odpowiedź:

- **Nie ma żadnej udokumentowanej, stałej nazwy folderu wyjściowego.** Lokalizacja zapisu to
  zawsze **ustawienie użytkownika**: enaR/SCOR "will be written to your **default output
  directory**, which can be set via **Tools/Options/File management**... **Output location**"
  (UG s.291); Ecosampler "will store this in a subfolder Sample_baseline under the **default
  core output path**" (UG s.50-51); podstawowy auto-save Ecosim — "**The path directory for
  output files can be found in the status window**" (UG s.275, nie s.289 jak wcześniej błędnie
  zacytowano w tym pliku — s.289 to w rzeczywistości środek tabeli statusów pluginów).
- **Multi-sim: osobny folder na przebieg to opcja, nie domyślne zachowanie.** UG s.79-81
  (przeczytane w całości): "Select the folder where the results of each simulation will be
  stored... **If you would like each simulation to generate its own folder... check the
  create unique folder for every run box**." Domyślnie (checkbox odznaczony) wszystkie
  przebiegi lądują **w jednym wspólnym folderze** — dokładna odwrotność tego, co ten plik
  wcześniej sugerował jako "domyślne" zachowanie Multi-sim (poprawka; treść merytoryczna cytatu
  z PM s.279 o "łatwej strukturze do analizy w R" pozostaje trafna, ale tylko dla trybu z
  zaznaczonym checkboxem).
- **Poprawiony cytat Monte Carlo: PM s.265, nie UG s.107.** Rozdział UG "Monte Carlo" (s.92-94,
  przeczytany w całości) opisuje wyłącznie interfejs (liczba prób, c.v., miary SS) — zero
  informacji o strukturze plików/folderów. Prawdziwy opis struktury jest w **PM s.265**:
  "Save output > All results in one file" → jeden plik `MonteCarloTrials.csv`; "Save File >
  Separate files per trial" → **jeden folder na przebieg**, każdy z tym samym kompletem plików
  co zwykły przebieg (np. `biomass annual.csv`). Merytoryczna treść już opisana w sekcji 4
  poniżej pozostaje trafna — poprawiona tylko lokalizacja cytatu.
- **Rozdział "Results Extractor" (UG s.127-131) w całości nie zawiera ani jednego zdania o
  strukturze plików/folderów** — to czysto opis UI (które checkboxy zaznaczyć). Potwierdza to
  jeszcze mocniej, że nasz wzorzec nazw `<zmienna>_annual.csv`/`ecosim_<scenariusz>/` jest
  **wyłącznie empiryczną obserwacją jednego przykładu**, nie udokumentowaną konwencją.
- **Jedyna realnie potwierdzona, natywna konwencja nazewnictwa folderu w całym materiale:**
  `Sample_baseline` / `Sample_[N]` z pluginu Ecosampler (UG s.50-51) — i nawet to jest
  podfolderem czegokolwiek wskazuje ustawienie "Output location", nie stałą ścieżką.

**Wniosek architektoniczny (druga tura, 27.08):** skoro EwE nie gwarantuje żadnej nazwy ani
głębokości folderu, walidacja/discovery **nie mogą** zakładać folderu `output/`, `input/` ani
`ecosim_<scenariusz>/` — każde takie założenie z definicji pasuje tylko do jednego,
konkretnego sposobu spakowania eksportu, nie do tego, co EwE generycznie potrafi wyprodukować.
`_discover_output()`/`_discover_output_rasters()`/`_discover_input()`/
`_discover_input_rasters()` (`pipeline.py`, `spatial_pipeline.py`) zostały przepisane na
**czysto treściowe** (rekurencyjne, bez założeń o nazwach folderów): CSV-y grupowane po
własnym nagłówku `EcosimScenario`/`ModelName` (a nie po folderze, w którym leżą), rastry
grupowane po folderze, w którym faktycznie leżą, z `Ecospace RunInfo.txt` odczytywanym z tego
samego miejsca. `validate_output_root()`/`validate_input_root()` używają dokładnie tej samej
logiki — odrzucają tylko folder, w którym rekurencyjne przeszukanie **niczego** nie znajduje,
niezależnie od tego, na jakim poziomie/pod jaką nazwą użytkownik akurat kliknął.

---

## 3. Ecospace — dane przestrzenne

### Format `.asc` — potwierdzone, brak rozjazdu

- **`.asc` to faktycznie standardowy format ESRI ASCII Grid** — potwierdzone wprost: "musi
  być dostarczony jako mapy rastrowe ESRI ASCII" (UG s.174/3855 wg numeracji tekstu),
  "eksport do formatu ESRI ASCII" (UG, sekcja o eksporcie). Zgodne z naszym parserem
  (`rasterio`, standardowy nagłówek `ncols/nrows/xllcorner/yllcorner/cellsize/NODATA_value`)
  — zweryfikowane też bezpośrednio na surowym pliku
  (`EcospaceMapBiomass-Benthopelagic-00001.asc`): dokładnie taki nagłówek, `NODATA_value=-9999`.
- **Orientacja siatki potwierdzona**: "pliki CSV/mapy mają kolumny reprezentujące siatkę
  długości geograficznej, a wiersze siatkę szerokości geograficznej, licząc od komórki w
  lewym górnym rogu do prawego dolnego rogu" (**✏️ poprawiony numer strony 27.08: UG s.275,
  nie s.289** — ten sam akapit co cytat o podstawowym auto-save powyżej) — czyli wiersze idą
  północ→południe, standardowa orientacja rastra. Zgodne z tym, co już wielokrotnie
  zweryfikowaliśmy wizualnie (wybrzeże Bałtyku poprawnie ułożone po naprawie projekcji
  Mercatora).
- **Konwencja nazywania plików z krokiem czasowym w nazwie pliku jest natywną konwencją
  EwE**, nie naszym obejściem: "odczyt kroku czasowego z ustalonej pozycji w nazwach
  plików" (UG s.258, o warstwach sterujących) — nasz parser
  (`EcospaceMapBiomass-<entity>-<timestep>.asc`) robi dokładnie to samo, zgodnie z
  filozofią samego EwE.

### Projekcja geograficzna — potwierdzone dla naszych danych, ale prawdziwa luka w kodzie

- **WGS84/EPSG:4326 to domyślna projekcja Ecospace**, z automatycznym „tapering" (zwężaniem)
  szerokości komórek wraz z szerokością geograficzną (`cos(latitude)`), wbudowanym w
  obliczenia dyspersji/wysiłku połowowego (UG s.246-250, rozdziały "Geospatial
  Considerations"/"Geospatial Projections"). To dokładnie ten sam efekt fizyczny, który stał
  za naszą wcześniejszą poprawką projekcji Mercatora (`buildRowReprojection` w
  `RasterMap.tsx`) — siatka faktycznie jest równoodległościowa (linowa w stopniach), tak jak
  założyliśmy.
- **Ale istnieje przełącznik "Assume Square Cells"** — per-model/per-scenariusz opcja,
  przełączająca Ecospace na lokalną projekcję UTM w metrach, bez zwężania komórek (UG
  s.247). **Dokumentacja wprost NIE mówi, czy i jak stan tej flagi jest sygnalizowany w
  eksportowanych plikach** — to prawdziwa luka nawet w oficjalnych materiałach, nie tylko w
  naszym kodzie.
- **Zweryfikowane bezpośrednio dla naszego datasetu**: `Ecospace RunInfo.txt` (Baltic Sea
  Baseline_cumulative) zawiera pole `CoordinateSystemWKT` z pełnym WKT potwierdzającym
  `GEOGCS['WGS 84',...AUTHORITY['EPSG','4326']]` — czyli **dla naszych obecnych danych
  założenie WGS84 jest w 100% potwierdzone**.
- **Prawdziwy rozjazd**: `write_cog()` w `backend/ecosim/ingestion/parsers/asc_grid.py`
  ma na sztywno zakodowane `WGS84 = "EPSG:4326"` i **nigdy nie czyta ani nie weryfikuje**
  pola `CoordinateSystemWKT` z `Ecospace RunInfo.txt` w runtime — mimo że komentarz w kodzie
  sugeruje, że to pole "potwierdza" WGS84 (potwierdza, ale tylko dlatego, że ktoś to
  sprawdził ręcznie raz, nie dlatego, że kod to weryfikuje). Dla **innego** modelu EwE
  zbudowanego w trybie "Assume Square Cells" (współrzędne w metrach, nie w stopniach) nasz
  kod cicho oznaczyłby raster jako WGS84 mimo że to nieprawda — `xllcorner`/`yllcorner`
  byłyby liczbami rzędu setek tysięcy (metry UTM), a my i tak wpisalibyśmy im etykietę
  EPSG:4326.

  **✅ Naprawione (27.08).** `_discover_output_rasters()` teraz czyta `CoordinateSystemWKT`
  z `Ecospace RunInfo.txt` i przenosi je do indeksu (`raster_index.csv`, kolumna
  `source_crs_wkt`); `write_cog()` przyjmuje je i **odrzuca konwersję** (`ValueError`,
  czytelny komunikat), jeśli nie parsuje się jako EPSG:4326, zamiast milcząco zakładać
  WGS84. Po drodze złapany drugi, prawdziwy błąd: EwE eksportuje ten WKT z pojedynczymi
  cudzysłowami (`'...'`) zamiast standardowych podwójnych (`"..."`) wymaganych przez format
  WKT — `rasterio` odrzucał go jako nieparsowalny, dopóki nie znormalizowaliśmy cudzysłowów
  przed parsowaniem. Zweryfikowane end-to-end: przebudowany indeks (13091 rastrów), świeża
  konwersja przez żywe API z prawdziwym `CoordinateSystemWKT` z naszego datasetu — przechodzi
  bez błędu (bo to naprawdę WGS84). Rastry input-driverów (`input/`, brak `RunInfo.txt`) nadal
  nie są tym sprawdzane — nie ma z czym porównać, zachowanie bez zmian.

### Cykl zapisu map przestrzennych: nie zawsze rocznie — kolejny prawdziwy rozjazd

Nasz kod (`asc_grid.py`: `year = start_year + (timestep - 1) // 12`, oraz cały indeks
rastrów w `RASTER_INDEX_COLUMNS`) zakłada, że Ecospace zapisuje mapy przestrzenne
**dokładnie raz na rok** — potwierdzone empirycznie na naszych danych (kroki czasowe map
idą 1, 13, 25, 37... — co 12). Ale to założenie **nie jest gwarancją EwE**, tylko
konfiguracją konkretnego eksportu. Wprost z rozdziału "Ecospace Output" (UG s.182):

> *"Be aware that writing output to hard-drive can amount to large volumes of data,
> **especially when writing spatial output for every monthly time step**."*

Czyli Ecospace **może** być skonfigurowany do zapisu map co miesiąc, nie tylko rocznie.

**✅ Naprawione (27.08), zabezpieczająco (nie pełne wsparcie).** Nasz `id` rastra
(`scenario|domain|variable|entity_slug|year`) **nie ma wymiaru miesiąca** — gdyby kiedyś
pojawiły się dane z miesięcznym cyklem zapisu, dwa różne pliki `.asc` z tego samego roku
dostałyby ten sam `id` i **cicho by się zderzyły** w indeksie (11 z 12 miesięcy
przepadałoby bez żadnego błędu — zależnie od kolejności wczytywania plików). Nie budowałem
pełnego wsparcia dla miesięcznej częstotliwości map (nie mamy takich danych, to byłaby
spekulacja) — zamiast tego `build_raster_index()` teraz **wykrywa kolizję** i zgłasza ją
jako czytelny błąd (`report.errors`, widoczny w `ecosim ingest-spatial` i
`POST /admin/reload`) zamiast milcząco nadpisywać. Zweryfikowane: pełna przebudowa
prawdziwego indeksu (13091 plików) — zero kolizji, zero błędów, bez zmian w zachowaniu na
obecnych danych; osobny test z syntetycznie skonstruowaną kolizją (dwa pliki, ten sam rok)
potwierdza wykrycie.

### `Ecospace RunInfo.txt` — plik, którego oficjalna dokumentacja w ogóle nie zna

Przeszukałem cały User Guide (case-insensitive, "RunInfo", "Run Info") — **ten plik nie
jest wspomniany ani razu**. To znaczy, że cały nasz pipeline geo-referencji (`ModelName`,
`EcosimScenario`, `StartYear`, i potencjalnie `CoordinateSystemWKT` gdybyśmy zaczęli go
odczytywać) opiera się na nieudokumentowanym, prawdopodobnie wewnętrznym pliku
pomocniczym EwE. Nie jest to błąd — plik realnie istnieje i ma stabilną, sensowną
strukturę `<HEADER .../>` (tę samą, co pliki CSV) — ale to znaczy, że nie mamy żadnej
oficjalnej gwarancji stabilności tego formatu między wersjami EwE. Warto o tym pamiętać
przy ewentualnej aktualizacji wersji EwE używanej do generowania nowych danych.

---

## 4. Monte Carlo — trzy różne mechanizmy, jeden wzorzec wyjścia

To jest obszar, którego **jeszcze w ogóle nie obsługujemy** (kafelek "Monte Carlo" w
aplikacji to na razie czysta zaślepka) — więc ta sekcja to głównie materiał projektowy pod
przyszłą implementację, nie lista rozjazdów.

Dokumentacja opisuje **trzy odrębne, łatwe do pomylenia mechanizmy**:

1. **Wbudowana rutyna "Monte Carlo runs"** (Ecosim > Output > Tools > Monte Carlo, UG
   s.92-94 — **✏️ poprawiony numer strony 27.08**, wcześniej błędnie s.106-108) — narzędzie do
   **dopasowania parametrów / analizy wrażliwości**, nie ogólne
   "uruchom N wariantów". Każda próba losuje na nowo 4 parametry Ecopath per grupa: **B,
   P/B, EE, BA** — z rozkładu jednostajnego wyśrodkowanego na wartości bazowej, o
   szerokości sterowanej współczynnikiem zmienności (CV) użytkownika (opcjonalnie z
   rodowodu/pedigree). Próba jest odrzucana i losowana ponownie (do 2000 razy), dopóki nie
   da zbilansowanego modelu Ecopath. Cel: zmniejszenie SS (sumy kwadratów odchyleń) względem
   obserwacji, albo test wrażliwości wyniku.
2. **Zapis wyników tej rutyny ma dwa tryby** — **✏️ poprawiony cytat (27.08, druga tura):**
   UG "Monte Carlo" (s.92-94, przeczytany w całości przy weryfikacji) opisuje wyłącznie
   interfejs (liczba prób, c.v., miary SS) — **nie strukturę plików**; opis struktury jest
   wyłącznie w **PM s.264-265** ("Save output" dialog):
   - **jeden połączony plik** `MonteCarloTrials.csv` — wiersz na parametr na przebieg,
     opisany wprost jako "niewygodny format wymagający dodatkowej obróbki" (PM s.265);
   - **osobne pliki per przebieg** — **jeden folder na przebieg**, każdy zawierający
     dokładnie ten sam zestaw plików, co zwykły pojedynczy przebieg Ecosim (w tym
     `biomass_annual.csv`) — **strukturalnie to po prostu N powielonych normalnych folderów
     wynikowych Ecosim, odróżnionych tylko numerem przebiegu.**
3. **Plugin Ecosampler** (UG s.49-66) — mechanizm do pełnych, równoległych przebiegów
   Ecopath+Ecosim+Ecospace+Ecotracer na wielu wylosowanych zestawach parametrów
   ("samples"). Struktura: `Sample_[numer]` jako podfolder w standardowej ścieżce
   auto-save (pierwszy przebieg to zawsze `Sample_baseline`) — "przekierowuje cały
   auto-save komponentów do unikalnego folderu na próbkę" (UG s.65). Każdy `Sample_N`
   zawiera **kompletny, zwyczajny zestaw plików wyjściowych**, jaki dałyby normalne
   ustawienia auto-save.
4. Osobny **"Ecospace MonteCarlo Plugin"** (UBC, status "Prototype", UG s.302) —
   jawnie niedojrzały/nieopublikowany. Nie projektować pod niego.

**Wniosek architektoniczny**: niezależnie od tego, który z trzech prawdziwych mechanizmów
(wbudowane MC z zapisem per-plik, Multi-sim, Ecosampler) wygenerował dane, **wzorzec
wyjścia jest ten sam — jeden folder na przebieg/próbkę, każdy strukturalnie identyczny z
normalnym pojedynczym wyjściem Ecosim/Ecospace**, różniący się tylko numerem/etykietą
przebiegu. Żeby to kiedyś zaingestować, potrzebujemy: (a) wykrywania wielu takich folderów
jako jednej logicznej grupy, (b) nowego wymiaru w schemacie (`run_id`/`trial_id` czy
podobnie — dziś `TIMESERIES_COLUMNS` w `core/schema.py` nie ma takiej kolumny w ogóle), i
osobno (c) jeśli chcemy też pokazywać same wylosowane parametry (nie tylko wyniki) —
osobnego pliku podsumowania (`MonteCarloTrials.csv` albo nagranie z Ecosampler), z innym
kształtem niż wyniki per-przebieg.

**Obecnie żadne dane Monte Carlo/Multi-sim nie istnieją w `DataEcosim/`** (sprawdzone —
brak folderów `Sample_*`, `MonteCarloTrials.csv`, ani nic podobnego) — więc to wszystko jest
materiał projektowy na przyszłość, nie coś do naprawienia teraz.

---

## 5. Numerowanie grup i flot

**Brak uniwersalnej, stałej konwencji — potwierdzone wprost, z ostrzeżeniem od autorów
EwE**: "Jeśli pobierzesz plik CSV lub dodasz/usuniesz grupy w swoim modelu... pliki CSV
używają numerów do odwołania się do grup i flot. Musisz sprawdzić plik CSV, żeby upewnić
się, że numery grup i flot w pliku CSV odpowiadają Twojemu modelowi" (PM s.264). Numeracja
jest **per-model**, przypisywana w kolejności, w jakiej modeler wprowadził grupy — jedyna
twarda zasada: grupy detrytusu muszą mieć **wyższy numer niż ostatnia grupa żywa** (UG
s.20, "muszą mieć wyższy numer grupy niż ostatnia grupa żywa"). Świeży, pusty model
zaczyna z dokładnie jedną grupą — Detritus (PM s.171) — ale to tylko stan startowy, nie
gwarancja że detrytus zawsze ma numer 1 w gotowym modelu.

**To potwierdza, dlaczego nie da się bezpiecznie zgadywać numeracji** — dokładnie zgodnie z
ostrzeżeniem manuala. Wcześniej (do 27.08) obsługiwaliśmy to osobnym, dostarczonym przez
modelera plikiem (`Mapa_grupy_fleets.xlsx`) jako jedynym źródłem prawdy ID↔nazwa. Ten
mechanizm został **całkowicie usunięty 2026-08-28** (patrz
`docs/Plans and TO_DO lists/28.08_session_summary.md`) — mylił użytkowników co do tego, co
jest strukturą EwE a co dodatkiem tego projektu, i z definicji jest specyficzny dla
użytkownika/instalacji, nie dla całej aplikacji. Dziś `group_id`/`fleet_id` są zawsze
zachowane z surowych danych; nazwa rozwiązuje się tylko tam, gdzie EwE samo ją zapisuje
(nazwa pliku `.asc`, nagłówki kolumn w kształcie wide-by-name) — w przeciwnym razie zostaje
`null`. Jeśli słownik ID↔nazwa kiedyś wróci, ma żyć w katalogu profilu użytkownika, nie być
skanowany z surowego folderu danych.

---

## 6. Rozjazdy — podsumowanie

| Obszar | Status | Co dokładnie |
|---|---|---|
| Czy dane Ecopath mają eksportowalną-do-folderu konwencję (jak output/input) | ℹ️ Zweryfikowane 28.08 — nie mają | Jedyny udokumentowany eksport to całego modelu przez Ecobase (UG s.6); "Ecopath Output" (s.26-42) to wyłącznie formularze w aplikacji, nie pliki. Brak odpowiednika `<HEADER ecosim/>`/`RunInfo.txt`. Wniosek: folder-discovery tile jak dla output/input nie ma podstawy w dokumentacji — inny kształt wsparcia potrzebny, jeśli w ogóle |
| Format `.asc` (nagłówek, orientacja) | ✅ Zgodne | Standardowy ESRI ASCII Grid, orientacja NW→SE, potwierdzone na realnym pliku |
| Konwencja nazw plików z krokiem czasowym | ✅ Zgodne | To natywna konwencja EwE, nie nasze obejście |
| Projekcja WGS84 + tapering przez szerokość | ✅ Zgodne | Potwierdza założenia za naprawą Mercatora z 25.08 |
| Zewnętrzny słownik grup/flot zamiast hardkodowanej numeracji | ✅ Zgodne | Wprost zalecane przez dokumentację (PM s.264) |
| `write_cog()` nie odczytywał `CoordinateSystemWKT` | ✅ Naprawione 27.08 | Teraz czyta pole z `RunInfo.txt`, przenosi przez indeks, odrzuca konwersję z czytelnym błędem gdy ≠ EPSG:4326; po drodze naprawiony też realny błąd parsowania WKT EwE (pojedyncze cudzysłowy zamiast standardowych podwójnych) |
| `Ecospace RunInfo.txt` niedokumentowany oficjalnie | ℹ️ Do wiedzy | Realny, stabilny, ale bez oficjalnej gwarancji formatu między wersjami EwE |
| 4 kształty CSV Ecosim (`ecosim_csv.py`) | ℹ️ Brak oficjalnej specyfikacji | Prawdopodobne źródło: nieudokumentowany "Results Extractor Plugin"; nasz parser zbudowany empirycznie z realnych plików, co jest tu jedyną możliwą strategią |
| Podstawowy auto-save Ecosim (bez pluginu) | ✅ Naprawione 27.08 | `freq` teraz z etykiety w nagłówku danych (`year`/`timestep`), nie z nazwy pliku — plik bez sufiksu `_annual`/`_monthly` rozpoznawany poprawnie; pokryte testem z syntetycznym plikiem (brak prawdziwej próbki) |
| Ecospace mógł zapisywać mapy częściej niż raz na rok | ✅ Zabezpieczone 27.08 | UG s.182 wprost potwierdza tę możliwość (miesięczny zapis); nasz `id` rastra nie ma wymiaru miesiąca — `build_raster_index()` teraz wykrywa i zgłasza kolizję zamiast cicho gubić dane; pełne wsparcie miesięcznej częstotliwości NIE zbudowane (brak danych, byłaby to spekulacja) |
| Monte Carlo / Multi-sim / Ecosampler | ⏳ Nie zaimplementowane | Brak danych w `DataEcosim/` na razie; wzorzec "folder na przebieg" udokumentowany wyżej pod przyszłą implementację; wymaga nowego wymiaru `run_id` w schemacie |
| Jednostki (`unit`) w eksporcie Ecosim | ℹ️ Nieudokumentowane | Ani UG, ani PM nie precyzują — nie nasz błąd, po prostu luka w oficjalnych materiałach |
| Wymóg `Mapa_grupy_fleets.xlsx` był bezwarunkowy w naszym pipeline | ✅ Usunięte całkowicie 28.08 | Prawdziwy bug użytkownika: realny folder Monte Carlo odrzucony, bo słownik leżał gdzie indziej. `Mapa_grupy_fleets.xlsx` to była nasza własna konwencja do rozwiązywania id→nazwa, nie artefakt EwE — żaden fragment UG/PM go nie wymaga. Po pierwszej naprawie (27.08, opcjonalny) użytkownik poszedł krok dalej: cały mechanizm (plik, `group_map.py`, endpoint `/dictionaries/groups\|fleets`, pole `group_dictionary_found`) usunięty z rdzenia aplikacji — rastry biorą nazwę wprost z nazwy pliku (natywnie opisowej), CSV wide-by-name z nagłówków kolumn, pozostałe kształty zachowują id z nazwą `null`. Przyszły słownik ID↔nazwa, jeśli powstanie, ma żyć per-profil użytkownika, nie być skanowany z surowych danych. Pokryte `test_group_fleet_naming.py` |
| Wymóg konkretnej nazwy/głębokości folderu (`output/`, `ecosim_<scenario>/`) | ✅ Naprawione 27.08 (druga runda) | Drugi, głębszy bug: walidacja i odkrywanie zakładały stały układ folderów wzorowany na jednym przykładzie z `DataEcosim/`. Świeża weryfikacja UG s.50-51/79-81/265/275 (agent fork) potwierdziła: lokalizacja output EwE to w pełni konfigurowalne ustawienie użytkownika, **bez żadnej udokumentowanej/stałej nazwy folderu**. Odkrywanie przepisane na w pełni rekurencyjne i oparte o treść pliku (nagłówek `EcosimScenario` w CSV, obecność `Ecospace RunInfo.txt` przy `.asc`), nie o nazwę/głębokość folderu. Pokryte `test_source_validation.py` (m.in. `..._also_accepts_pointing_directly_at_output_subfolder`, dowodzi że "wskazanie o jeden poziom za nisko/wysoko" już nie jest błędem) |

Ten dokument powstał jako czysta analiza (patrz plan sesji z 27.08); jedyny punkt z
konkretną, tanią akcją naprawczą (`CoordinateSystemWKT`) został naprawiony tego samego dnia
— patrz sekcja 3. Pozostałe pozycje (`run_id` pod Monte Carlo, ewentualne rozszerzenie
`ecosim_csv.py` o podstawowy kształt auto-save) czekają na realną potrzebę, zgodnie z
zasadą "nie zgadywać z góry" przyjętą dla całego Etapu 3.

### Przy okazji zauważone (nie z PDF-ów, z samego czytania `data-contract.md`)

Przykładowy `analysis.yaml` w `docs/data-contract.md` wciąż pokazuje polskie
`name`/`description`/`label` — nie zaktualizowany po wczorajszym tłumaczeniu prawdziwego
pliku na angielski (26.08, sekcja o regule języka UI). Przykładowy `manifest.json` w tym
samym dokumencie też nie pokazuje kształtu `{variable, domain, scenarios}` per zmienna,
który realnie obsługuje `runner.py` od wczoraj. Drobny dryf dokumentacji względem kodu,
niezwiązany z EwE — osobna, szybka poprawka, jeśli będzie potrzebna.
