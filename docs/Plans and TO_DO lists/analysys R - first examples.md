# CLAUDE.md — analizy Ecopath with Ecosim i Ecospace w R

## Rola i cel

Pracujesz jako doświadczony ekolog ilościowy i programista R specjalizujący się w modelach Ecopath with Ecosim (EwE), analizach przestrzennych, ocenach MPA oraz reprodukowalnych pipeline’ach naukowych.

Zbuduj kompletny, modułowy projekt R, który:

1. importuje i kontroluje jakość eksportów z Ecopath, Ecosim i Ecospace;
2. integruje wyniki modelu z obserwacjami, środowiskiem i geometrią MPA;
3. ocenia kalibrację oraz walidację Ecosim i Ecospace;
4. porównuje scenariusze połowowe, klimatyczne i przestrzenne;
5. analizuje efekty wewnątrz MPA, na granicy MPA i poza MPA;
6. ocenia spillover oraz przesunięcie nakładu połowowego;
7. analizuje wskaźniki ekosystemowe, zbiorowiska i sieć troficzną;
8. propaguje niepewność i unika pseudoreplikacji;
9. automatycznie tworzy tabele, mapy, wykresy publikacyjne i raport Quarto.

Projekt ma działać również po podmianie eksportów EwE na dane z innego modelu. Wszystkie założenia zależne od konkretnego przypadku umieszczaj w konfiguracji, a nie na stałe w kodzie.

## Zasady bezwzględne

- Najpierw wykonaj inwentaryzację plików, formatów, kolumn i jednostek. Nie zakładaj formatu eksportu bez sprawdzenia.
- Nigdy nie modyfikuj danych w katalogu data_raw.
- Nie wymyślaj brakujących jednostek, nazw grup, dat, scenariuszy ani wyników.
- Zachowuj nazwę źródłową w polu z końcówką _raw, a standaryzację wykonuj przez jawne słowniki.
- Użyj pakietu targets do sterowania pipeline’em i renv do odtwarzania środowiska.
- Porównania scenariuszy wykonuj parami względem BAU przy tym samym ensemble_id, czasie, komórce, grupie i metryce.
- Nie traktuj lat, miesięcy ani komórek pojedynczej deterministycznej symulacji jako niezależnych replik biologicznych.
- Niepewność wnioskuj przede wszystkim z ensemble, Monte Carlo, niezależnych realizacji stochastycznych lub odpowiednio blokowanego bootstrapu.
- Powierzchnie i odległości licz w odpowiednim metrycznym/equal-area CRS, a nie bezpośrednio w stopniach geograficznych.
- Każdy wykres zapisuj razem z tabelą danych wykorzystanych do jego utworzenia.
- Jeżeli brakuje danych do analizy, nie twórz fikcyjnych wyników. Nadaj jej status SKIPPED i zapisz przyczynę.
- Dane demonstracyjne umieszczaj tylko w data_demo i oznaczaj wszystkie wyniki jako DEMO — NOT EMPIRICAL RESULTS.
- Nazwy funkcji, obiektów i komentarze kodu pisz po angielsku. Raport i podpisy figur domyślnie po polsku, z możliwością zmiany języka w konfiguracji.
- Nie zatrzymuj się na pustym szkielecie. Zaimplementuj i przetestuj wszystkie moduły możliwe do wykonania na dostępnych danych.

## Produkty końcowe

Projekt powinien dostarczyć:

- działający plik _targets.R;
- renv.lock i README.md;
- konfigurowalne moduły importu i analizy;
- słownik danych i raport kontroli jakości;
- tabele wynikowe CSV lub Parquet;
- mapy GeoTIFF, jeżeli mają być dalej używane w GIS;
- figury PNG oraz PDF/SVG;
- raport Quarto HTML i PDF;
- testy jednostkowe oraz testy kontraktów danych;
- manifest pokazujący analizy wykonane, pominięte i zakończone błędem.

## Docelowa struktura projektu

~~~text
ecosim_ecospace_analysis/
├── CLAUDE.md
├── README.md
├── _targets.R
├── renv.lock
├── config/
│   ├── project.yml
│   ├── columns.yml
│   ├── groups.csv
│   ├── fleets.csv
│   ├── scenarios.csv
│   ├── indicators.yml
│   └── figures.yml
├── data_raw/
│   ├── ecopath/
│   ├── ecosim/
│   ├── ecospace/
│   ├── observations/
│   ├── environment/
│   └── spatial/
├── data_demo/
├── data_processed/
│   ├── tabular/
│   ├── spatial/
│   └── cache/
├── R/
│   ├── functions_import.R
│   ├── functions_qc.R
│   ├── functions_temporal.R
│   ├── functions_spatial.R
│   ├── functions_mpa.R
│   ├── functions_statistics.R
│   ├── functions_indicators.R
│   ├── functions_network.R
│   ├── functions_uncertainty.R
│   ├── functions_figures.R
│   └── functions_reporting.R
├── scripts/
│   ├── 01_read_ecopath.R
│   ├── 02_read_ecosim.R
│   ├── 03_read_ecospace.R
│   ├── 04_read_observations.R
│   ├── 05_build_dictionaries.R
│   ├── 06_qc_raw_data.R
│   ├── 07_make_temporal_long.R
│   ├── 08_make_spatial_cube.R
│   ├── 09_define_mpa_zones.R
│   ├── 10_pair_scenarios_ensemble.R
│   ├── 11_prebal_qc.R
│   ├── 12_compare_ecosim_fits.R
│   ├── 13_validate_ecosim.R
│   ├── 14_ecosim_residuals.R
│   ├── 15_temporal_trends.R
│   ├── 16_scenario_effects.R
│   ├── 17_factorial_stressors.R
│   ├── 18_ecological_indicators.R
│   ├── 19_network_analysis.R
│   ├── 20_validate_ecospace.R
│   ├── 21_spatial_patterns.R
│   ├── 22_mpa_inside_outside.R
│   ├── 23_spillover_boundary.R
│   ├── 24_effort_displacement.R
│   ├── 25_multivariate_community.R
│   ├── 26_uncertainty_sensitivity.R
│   ├── 27_tradeoffs_mse.R
│   ├── 28_make_all_figures.R
│   ├── 29_make_tables.R
│   └── 30_render_report.R
├── reports/
│   ├── analysis_report.qmd
│   └── references.bib
├── tests/testthat/
└── outputs/
    ├── figures_main/
    ├── figures_supplement/
    ├── figure_data/
    ├── maps/
    ├── tables/
    ├── models/
    ├── logs/
    └── reports/
~~~

## Zalecane pakiety R

Dobierz tylko pakiety potrzebne dla dostępnych danych.

- Pipeline: targets, tarchetypes, renv, yaml, here.
- Tabele: data.table, dplyr, tidyr, readr, arrow, janitor, lubridate.
- Przestrzeń: sf, terra, opcjonalnie exactextractr i tidyterra.
- Grafika: ggplot2, patchwork, scales, viridis, ggrepel.
- Modele: mgcv, glmmTMB, nlme, emmeans, broom, broom.mixed, performance, DHARMa.
- Trendy: segmented, strucchange lub changepoint.
- Zbiorowiska: vegan.
- Sieci: igraph, tidygraph, ggraph.
- Niepewność: boot, opcjonalnie sensitivity.
- Raporty i testy: quarto, knitr, gt, testthat, checkmate.

W obliczeniach równoległych nie przekazuj obiektów SpatRaster między procesami. Zapisuj raster jako GeoTIFF i przekazuj ścieżkę, ponieważ wewnętrzne wskaźniki obiektów terra nie są bezpieczne do serializacji.

## Kanoniczne kontrakty danych

### Szeregi czasowe Ecosim

Plik: data_processed/tabular/ecosim_timeseries.parquet

Wymagane kolumny:

~~~text
model_id
scenario_id
baseline_id
ensemble_id
date
year
month
group_id
fleet_id
metric
value
unit
burnin
source_file
~~~

Klucz powinien być unikatowy dla:

~~~text
model_id + scenario_id + ensemble_id + date + group_id + fleet_id + metric
~~~

Typowe metryki: biomass, catch, fishing_mortality, production, consumption, effort, recruitment i predation_mortality.

### Kostka Ecospace

Plik: data_processed/tabular/ecospace_cube.parquet

Wymagane kolumny:

~~~text
model_id
scenario_id
baseline_id
ensemble_id
date
year
month
cell_id
x
y
cell_area_km2
group_id
fleet_id
metric
value
unit
habitat_class
mpa_id
mpa_zone
signed_distance_mpa_km
depth_m
substrate
productivity
source_file
~~~

Klucz powinien być unikatowy dla:

~~~text
model_id + scenario_id + ensemble_id + date + cell_id + group_id + fleet_id + metric
~~~

Geometrię siatki przechowuj osobno w grid.gpkg i łącz przez cell_id. Nie powielaj geometrii w każdym wierszu dużej tabeli.

### Słownik grup

Plik: config/groups.csv

~~~text
group_id,group_name_raw,group_name,label_pl,label_en,trophic_level,group_type,is_target,is_predator,is_benthic,plot_order,plot_color
~~~

### Słownik scenariuszy

Plik: config/scenarios.csv

~~~text
scenario_id,scenario_label,baseline_id,is_baseline,fishing_level,climate_level,protection_level,effort_response,start_date,end_date,plot_order,plot_color
~~~

### Obserwacje

Plik: data_processed/tabular/observations.parquet

~~~text
observation_id,date,year,cell_id,station_id,group_id,metric,value,unit,se,cv,sample_size,survey_id,gear,effort,quality_flag,source_file
~~~

Jeżeli obserwacja nie ma wariancji, pozostaw NA. Nie wymyślaj jej na potrzeby ważenia.

### Warstwy przestrzenne

- grid.gpkg: geometria komórek, cell_id, powierzchnia i maska morze–ląd;
- mpa.gpkg: mpa_id, typ ochrony, data ustanowienia i geometria;
- siedliska wektorowe lub rastrowe;
- rastry środowiskowe doprowadzone do wspólnego CRS, zasięgu i siatki odniesienia;
- porty, obszary połowowe i VMS/AIS, jeżeli są dostępne.

## Przepływ danych

~~~mermaid
flowchart LR
    A[Surowe eksporty EwE] --> B[Import i słowniki]
    O[Obserwacje i środowisko] --> B
    M[Siatka, siedliska i MPA] --> B
    B --> Q[Kontrola jakości]
    Q --> T[Szeregi Ecosim]
    Q --> S[Kostka Ecospace]
    T --> EC[Kalibracja i walidacja Ecosim]
    S --> ES[Walidacja Ecospace]
    S --> MP[MPA, spillover i effort]
    EC --> U[Scenariusze i niepewność]
    ES --> U
    MP --> U
    U --> I[Wskaźniki, sieci i trade-offs]
    I --> F[Wykresy, mapy, tabele i raport]
~~~

## Zakres skryptów

### Import i przygotowanie

1. 01_read_ecopath.R
   - Import grup, biomasy, P/B, Q/B, EE, połowów, diety i przepływów.
   - Zachowanie wartości i jednostek źródłowych.
   - Standaryzacja nazw wyłącznie przez słowniki.

2. 02_read_ecosim.R
   - Import szeregów czasowych w układzie szerokim lub długim.
   - Utworzenie identyfikatorów scenariusza, ensemble, grupy, floty i metryki.
   - Kontrola kompletności czasu.

3. 03_read_ecospace.R
   - Import tabel komórka–czas, rasterów lub NetCDF.
   - Powiązanie danych z siatką.
   - Kontrola CRS, zasięgu, rozdzielczości i orientacji rastra.
   - Zapis dużych tabel do Parquet i map do GeoTIFF.

4. 04_read_observations.R
   - Import survey, połowów, VMS/AIS, telemetrii i środowiska.
   - Standaryzacja jednostek, czasu, grup i położenia.
   - Flagowanie braków i wartości odstających bez automatycznego usuwania.

5. 05_build_dictionaries.R
   - Słowniki grup, flot, metryk, jednostek i scenariuszy.
   - Raport nazw niedopasowanych.
   - Zakaz cichego fuzzy matching.

6. 06_qc_raw_data.R
   - Braki, duplikaty, zakresy, jednostki, klucze i chronologia.
   - Kontrola wartości ujemnych lub niemożliwych.
   - Zgodność grup pomiędzy modułami.
   - Raport QC oraz heatmapa pokrycia danych.

### Kanoniczne zbiory analityczne

7. 07_make_temporal_long.R
   - Długa tabela Ecosim.
   - Oznaczenie burn-in.
   - Poprawna agregacja miesięczna lub roczna zależna od jednostki.

8. 08_make_spatial_cube.R
   - Tabela komórka–czas–grupa–scenariusz.
   - Powierzchnia, siedlisko, głębokość i środowisko.
   - Partycjonowanie według scenariusza, roku i metryki.

9. 09_define_mpa_zones.R
   - Walidacja geometrii MPA.
   - Udział komórki chroniony przez MPA.
   - Strefy core, edge_inside, edge_outside, outside_near i outside_far.
   - Podpisana odległość: ujemna wewnątrz, dodatnia na zewnątrz.
   - Analiza czułości na szerokość pierścieni.

10. 10_pair_scenarios_ensemble.R
    - Dokładne parowanie scenariusza z BAU.
    - Różnica bezwzględna, względna i log response ratio.
    - Raport brakujących par.

### Ecopath i Ecosim

11. 11_prebal_qc.R
    - Kontrola PREBAL i relacji bilansowych.
    - Log biomasy, P/B i Q/B względem poziomu troficznego.
    - Lista grup wymagających biologicznego przeglądu; bez automatycznej zmiany parametrów.

12. 12_compare_ecosim_fits.R
    - Porównanie modeli: baseline, fishing, vulnerability, forcing środowiskowy/PP.
    - Funkcja celu, liczba parametrów, AIC/AICc, delta AICc i wagi.
    - Jawna definicja n i K.
    - Ocena dopasowania razem ze złożonością i sensownością ekologiczną.

13. 13_validate_ecosim.R
    - Model–obserwacje w okresie kalibracji i walidacji.
    - RMSE, MAE, PBIAS, Pearson, Spearman, MEF/NSE i pokrycie ensemble.
    - Walidacja blokowana w czasie, nie losowe dzielenie pojedynczych lat.
    - Metryki według grupy, zmiennej i okresu.

14. 14_ecosim_residuals.R
    - Reszty w czasie, fitted–residual, rozkład, ACF/PACF.
    - Heteroskedastyczność i obserwacje wpływowe.
    - Kontrola systematycznego biasu według grup.

15. 15_temporal_trends.R
    - GAM/GAMM dla trendów nieliniowych.
    - Punkty zmiany i zmiany nachylenia, jeżeli dane je uzasadniają.
    - Przedziały niepewności i poprawna obsługa autokorelacji.

16. 16_scenario_effects.R
    - Sparowane efekty względem BAU.
    - Efekty końcowe, średnie, skumulowane i ekstremalne.
    - Wyniki dla biomasy, połowów, flot i wskaźników.
    - Skala bezwzględna, procentowa i log response ratio.

17. 17_factorial_stressors.R
    - Model czynnikowy, jeśli scenariusze tworzą odpowiedni projekt:

~~~r
response ~ fishing * climate * protection * effort_response
~~~

    - Efekty główne, interakcje i kontrasty marginalne.
    - Jawne oznaczenie kombinacji brakujących w projekcie.

18. 18_ecological_indicators.R
    - Biomasa całkowita i drapieżników.
    - Średni poziom troficzny biomasy i połowów.
    - Stosunki grup pelagicznych/demersalnych oraz docelowych/wrażliwych.
    - Formuły wskaźników w config/indicators.yml.
    - Brak indeksu syntetycznego bez jawnych wag i analizy wrażliwości.

19. 19_network_analysis.R
    - Connectance, cycling, omnivory, ascendancy i Finn Cycling Index, jeśli dane pozwalają.
    - Porównanie sieci między scenariuszami.
    - Czytelne grafy ograniczone do najważniejszych przepływów.

### Ecospace, MPA i przestrzeń

20. 20_validate_ecospace.R
    - Porównanie map modelowych z survey, telemetrią lub SDM.
    - Korelacja przestrzenna, RMSE/MAE, overlap i odtwarzanie hotspotów.
    - Blokowa walidacja przestrzenna.
    - Mapy reszt i autokorelacja przestrzenna reszt.
    - Osobno walidacja wzorca względnego i wartości bezwzględnych.

21. 21_spatial_patterns.R
    - Mapy biomasy, połowu, śmiertelności, effortu i wskaźników.
    - Mapy scenariusz minus BAU.
    - Prawdopodobieństwo poprawy w ensemble.
    - Trwałość hotspotów, przesunięcie centroidu i zmiana zasięgu.

22. 22_mpa_inside_outside.R
    - Porównanie core, edge i kontroli outside.
    - Ważenie wyników powierzchnią.
    - Kontrole dopasowane według siedliska, głębokości i produktywności.
    - Model mieszany lub GAMM, na przykład:

~~~r
response ~ scenario * mpa_zone * period +
  habitat_class + depth_m + productivity +
  (1 | ensemble_id) + (1 | cell_id)
~~~

    - Jeżeli są prawdziwe dane przed i po ustanowieniu MPA: BACI.
    - Głównym efektem BACI jest interakcja treatment × period.

23. 23_spillover_boundary.R
    - Odpowiedź względem podpisanej odległości od granicy MPA.
    - Osobne krzywe według scenariusza i okresu.
    - Kontrola siedliska, czasu i struktury przestrzennej.
    - Dla dużych danych preferuj model podobny do:

~~~r
mgcv::bam(
  log1p(value) ~ scenario_id +
    s(signed_distance_mpa_km, by = scenario_id) +
    s(x, y) + s(year) + habitat_class +
    s(ensemble_id, bs = "re"),
  data = analysis_data,
  method = "fREML",
  discrete = TRUE
)
~~~

    - Szerokość spillover podawaj z niepewnością.
    - Nie interpretuj samego wzrostu poza granicą jako dowodu przyczynowego bez odpowiedniej kontroli.

24. 24_effort_displacement.R
    - Zmiana całkowitego effortu oraz jego redystrybucja.
    - Udział wysiłku przesunięty do pierścieni wokół MPA.
    - Koszt i odległość od portu, jeżeli dostępne.
    - Lokalizacja nowych hotspotów effortu.

25. 25_multivariate_community.R
    - Macierz próbka × grupa i transformacja Hellingera.
    - PCA lub NMDS.
    - PERMANOVA z permutacjami ograniczonymi zgodnie z projektem.
    - Test dyspersji przed interpretacją PERMANOVA.
    - Trajektorie zbiorowisk i wkład grup w różnice.

### Niepewność, decyzje i raportowanie

26. 26_uncertainty_sensitivity.R
    - Mediany, przedziały kwantylowe i prawdopodobieństwo przekroczenia progów.
    - Sparowane różnice ensemble scenariusz–BAU.
    - Analiza wrażliwości najważniejszych parametrów.
    - Oddzielne oznaczanie niepewności parametrów, obserwacji, procesu i scenariusza.

27. 27_tradeoffs_mse.R
    - Cele ekologiczne, połowowe, ekonomiczne i społeczne, jeśli dane istnieją.
    - Prawdopodobieństwo osiągnięcia celu.
    - Front Pareto oraz winners–losers.
    - Wagi celów w konfiguracji i analiza wrażliwości na ich zmianę.

28. 28_make_all_figures.R
    - Wszystkie figury wyłącznie z zatwierdzonych tabel wynikowych.
    - Wspólny motyw, kolory i kolejność scenariuszy.
    - Dane źródłowe każdej figury w outputs/figure_data.

29. 29_make_tables.R
    - Tabele QC, walidacji, kontrastów, MPA, niepewności i trade-offs.
    - Wersje maszynowe CSV/Parquet oraz tabele do raportu.

30. 30_render_report.R
    - Raport Quarto z metodami, wynikami, diagnostyką i ograniczeniami.
    - Wersja R, pakiety, konfiguracja i data uruchomienia.
    - Żadnych ręcznie wpisanych liczb w tekście wynikowym.

## Reguły obróbki

### Agregacja przestrzenna

Dla gęstości:

~~~text
weighted_mean = sum(value_i × area_i) / sum(area_i)
~~~

Dla całkowitej biomasy z mapy gęstości:

~~~text
total_biomass = sum(density_i × area_i)
~~~

Nie sumuj gęstości bez powierzchni komórki.

### Efekty scenariusza

Dla każdej dokładnie sparowanej jednostki:

~~~text
absolute_change = scenario - baseline
relative_change_pct = 100 × (scenario - baseline) / baseline
log_response_ratio = log((scenario + epsilon) / (baseline + epsilon))
~~~

Epsilon stosuj tylko przy uzasadnionych zerach i wykonaj analizę wrażliwości. Nie raportuj procentowej zmiany, gdy baseline jest równy lub bardzo bliski zeru.

### Czas

- Jawnie zdefiniuj burn-in.
- Oddziel okres kalibracji, walidacji i projekcji.
- Biomasa zwykle wymaga średniej po miesiącach; połowy lub produkcja mogą wymagać sumy. Decyduje jednostka.
- Uwzględniaj autokorelację i trend nieliniowy, jeżeli wskazują na to diagnostyki.

### MPA

- Korzystaj z udziału powierzchni komórki wewnątrz MPA, a nie tylko z centroidu.
- Przetestuj kilka szerokości pierścieni.
- Kontrole outside dopasuj siedliskowo i batymetrycznie.
- Dla wielu MPA uwzględnij mpa_id jako poziom hierarchii.
- Uwzględnij prawidłową datę aktywacji ochrony.

### Braki i obserwacje odstające

- Nie zamieniaj NA na zero bez jednoznacznej podstawy w danych źródłowych.
- Każde wykluczenie musi mieć flagę i przyczynę.
- Jeżeli obserwacje wpływowe zmieniają wynik, pokaż analizę z nimi i bez nich.

## Wymagane wykresy

Każda figura otrzymuje identyfikator F01–F36 i odpowiadający plik danych.

| ID | Wykres | Minimalna zawartość |
|---|---|---|
| F01 | Pokrycie danych | heatmapa grup × lat × źródeł |
| F02 | PREBAL | log(B), log(P/B), log(Q/B) vs poziom troficzny |
| F03 | Ranking Ecosim | AICc, delta AICc i wagi modeli |
| F04 | Model–obserwacje | czas, obserwacje, model, ensemble, kalibracja/walidacja |
| F05 | Model vs dane 1:1 | linia równości i metryki dopasowania |
| F06 | Diagnostyka reszt | czas, rozkład, fitted–residual i ACF |
| F07 | Trajektorie scenariuszy | wartość w czasie i pasma niepewności |
| F08 | Forest plot efektów | sparowane efekty względem BAU |
| F09 | Heatmapa odpowiedzi | grupa × scenariusz |
| F10 | Efekt skumulowany | skumulowana różnica względem BAU |
| F11 | Punkty zmiany | trend i oszacowane zmiany reżimu |
| F12 | Interakcje presji | fishing × climate × protection |
| F13 | Powierzchnia odpowiedzi | dwie ciągłe presje, jeśli możliwe |
| F14 | ECOIND small multiples | wskaźniki ekosystemowe w czasie |
| F15 | Profil troficzny | biomasa/przepływ według poziomu troficznego |
| F16 | Sieć troficzna | grupy i najważniejsze przepływy |
| F17 | Zmiana przepływów | scenariusz minus BAU |
| F18 | Mapa stanu | biomasa, połów, effort lub wskaźnik |
| F19 | Mapa różnicy | scenariusz minus BAU, środek skali = 0 |
| F20 | Prawdopodobieństwo korzyści | udział ensemble z poprawą |
| F21 | Walidacja przestrzenna | obserwacje, model i reszty |
| F22 | Trwałość hotspotów | częstość przekroczenia progu |
| F23 | Przesunięcie centroidu | ścieżki lub wektory w czasie |
| F24 | Efekty MPA | forest plot core, edge, outside |
| F25 | Rozkłady stref MPA | violin/boxplot z punktami ensemble |
| F26 | BACI | before/after × impact/control |
| F27 | Spillover | odpowiedź względem podpisanej odległości |
| F28 | Przesunięcie effortu | mapa zmian wokół MPA i portów |
| F29 | Profil pierścieniowy | efekt w strefach odległości |
| F30 | PCA/NMDS | trajektorie zbiorowisk |
| F31 | Heatmapa klastrów | podobieństwo odpowiedzi |
| F32 | Wrażliwość | tornado lub Sobol |
| F33 | Fan chart | kwantyle ensemble w czasie |
| F34 | Osiągnięcie celów | scenariusz × cel i prawdopodobieństwo |
| F35 | Front Pareto | kompromis między celami |
| F36 | Winners–losers | efekty dla grup, flot lub sektorów |

Schemat wykresu model–obserwacje:

~~~text
wartość
  │       obserwacje ●  ●
  │   ┌──── pasmo ensemble ────┐
  │ ──┼──── linia modelu ──────┼──
  │   └────────────────────────┘
  └────────────────────────────── czas
      kalibracja       walidacja
~~~

Schemat krzywej spillover:

~~~text
odpowiedź
  │      wewnątrz MPA      poza MPA
  │          ╭──────╮
  │      ╭───╯      ╰───────
  │──────┼─────────────────────────
  └──────┴───────────────────────── odległość
       ujemna   0 = granica   dodatnia
~~~

### Standard graficzny

- Stałe kolory scenariuszy zapisuj w config/scenarios.csv.
- Zmiany pokazuj paletą rozbieżną wycentrowaną w zerze.
- Mapy wartości bezwzględnych pokazuj paletą percepcyjnie równomierną, np. viridis.
- Porównywane mapy muszą mieć wspólne limity skali.
- Dodaj granice MPA, jednostkę, skalę i kierunek północy, gdy są potrzebne.
- Nie używaj palety rainbow ani podwójnej osi Y.
- Opisz dokładnie, co oznacza pasmo niepewności.
- Wykresy wektorowe zapisuj jako PDF/SVG, mapy jako PNG/TIFF 300–600 dpi.
- Podpis figury ma podawać jednostkę analizy, okres, baseline i typ niepewności.

## Główne figury publikacji

Ogranicz główny tekst do około siedmiu figur:

1. pokrycie danych i schemat projektu;
2. kalibracja i walidacja Ecosim;
3. trajektorie najważniejszych scenariuszy;
4. forest plot efektów ekologicznych i połowowych;
5. mapy stanu, różnicy i prawdopodobieństwa korzyści;
6. MPA inside–edge–outside oraz spillover;
7. trade-offs/Pareto i prawdopodobieństwo celów.

Pozostałe diagnostyki umieść w suplementach.

## Minimalna konfiguracja

Utwórz config/project.yml podobny do poniższego, a wartości uzupełnij dopiero po inspekcji danych.

~~~yaml
project:
  name: "ecosim_ecospace_analysis"
  language: "pl"
  timezone: "UTC"
  seed: 20260826

paths:
  ecopath: "data_raw/ecopath"
  ecosim: "data_raw/ecosim"
  ecospace: "data_raw/ecospace"
  observations: "data_raw/observations"
  spatial: "data_raw/spatial"

time:
  burnin_end: null
  calibration_start: null
  calibration_end: null
  validation_start: null
  validation_end: null

scenario:
  baseline_id: "BAU"
  pairing_keys:
    - ensemble_id
    - date
    - cell_id
    - group_id
    - fleet_id
    - metric

mpa:
  inside_threshold: 0.5
  ring_widths_km: [1, 5, 10, 20, 50]
  signed_distance_inside_negative: true

uncertainty:
  interval: [0.025, 0.975]
  bootstrap_repetitions: 2000

figures:
  width_mm: 180
  base_font_size: 9
  raster_dpi: 400
~~~

Wartości null mają wymuszać świadome uzupełnienie, nie automatyczne zgadywanie.

## Minimalny szkielet pipeline’u

Rozwiń ten wzorzec zgodnie z rzeczywistymi plikami:

~~~r
library(targets)
library(tarchetypes)

tar_option_set(
  packages = c(
    "data.table", "dplyr", "tidyr", "arrow",
    "sf", "terra", "ggplot2", "mgcv", "glmmTMB",
    "vegan", "igraph", "yaml"
  ),
  seed = 20260826
)

lapply(list.files("R", pattern = "[.]R$", full.names = TRUE), source)

list(
  tar_target(config, read_project_config("config/project.yml")),
  tar_target(raw_inventory, inventory_raw_files(config)),
  tar_target(group_dictionary, read_group_dictionary("config/groups.csv")),
  tar_target(scenario_dictionary, read_scenario_dictionary("config/scenarios.csv")),

  tar_target(ecopath_raw, import_ecopath(raw_inventory, config)),
  tar_target(ecosim_raw, import_ecosim(raw_inventory, config)),
  tar_target(ecospace_files, index_ecospace_files(raw_inventory, config)),
  tar_target(observations_raw, import_observations(raw_inventory, config)),

  tar_target(qc_report, run_all_qc(
    ecopath_raw, ecosim_raw, ecospace_files, observations_raw, config
  )),

  tar_target(ecosim_long, make_ecosim_long(ecosim_raw, config)),
  tar_target(
    ecospace_cube_path,
    build_ecospace_cube(ecospace_files, config),
    format = "file"
  ),
  tar_target(mpa_zones_path, build_mpa_zones(config), format = "file"),
  tar_target(scenario_pairs, pair_scenarios(ecosim_long, config)),

  tar_target(
    ecosim_validation,
    validate_ecosim(ecosim_long, observations_raw, config)
  ),
  tar_target(
    ecospace_validation,
    validate_ecospace(ecospace_cube_path, observations_raw, config)
  ),
  tar_target(
    mpa_effects,
    estimate_mpa_effects(ecospace_cube_path, mpa_zones_path, config)
  ),
  tar_target(
    spillover_model,
    fit_spillover_model(ecospace_cube_path, mpa_zones_path, config)
  ),
  tar_target(
    uncertainty_results,
    summarise_uncertainty(scenario_pairs, mpa_effects, config)
  ),

  tar_target(
    figure_manifest,
    make_all_figures(
      ecosim_validation,
      ecospace_validation,
      mpa_effects,
      spillover_model,
      uncertainty_results,
      config
    )
  ),
  tar_quarto(report, "reports/analysis_report.qmd")
)
~~~

## Testy obowiązkowe

Dodaj co najmniej:

- unikatowość kluczy kanonicznych;
- zgodność jednostek w obrębie metryki;
- poprawność dat i kompletność osi czasu;
- dodatnie powierzchnie komórek;
- zgodność CRS;
- udział MPA w komórce mieszczący się w zakresie 0–1;
- poprawny znak podpisanej odległości;
- kompletność par scenariusz–BAU;
- poprawność agregacji ważonej powierzchnią na małym przykładzie;
- reprodukowalność bootstrapu przy stałym seedzie;
- zgodność danych figur z tabelami wynikowymi;
- brak ścieżek absolutnych autora w raporcie.

Diagnostyka modeli powinna obejmować, zależnie od typu modelu:

- strukturę i rozkład reszt;
- autokorelację czasową i przestrzenną;
- nadmierną dyspersję i zero-inflation;
- współliniowość;
- concurvity dla GAM;
- stabilność dopasowania i ostrzeżenia;
- wrażliwość na rozkład, burn-in oraz szerokość stref MPA.

## Manifest analiz

Utwórz outputs/tables/analysis_manifest.csv:

~~~text
analysis_id,script,status,required_inputs,available_inputs,output_files,warning_count,error_message,run_timestamp
~~~

Dozwolone statusy:

- COMPLETED;
- COMPLETED_WITH_WARNINGS;
- SKIPPED_MISSING_DATA;
- SKIPPED_NOT_APPLICABLE;
- FAILED.

Pipeline może utworzyć raport częściowy, ale musi jednoznacznie ujawnić braki.

## Kryteria ukończenia

Zadanie jest ukończone, gdy:

1. renv::restore() odtwarza środowisko;
2. targets::tar_make() prowadzi od danych surowych do raportu bez ręcznych kroków;
3. dane przechodzą testy kontraktów lub problemy są jawnie raportowane;
4. każdy scenariusz ma właściwy baseline;
5. efekty scenariuszy są prawidłowo sparowane po ensemble;
6. agregacje przestrzenne uwzględniają powierzchnię;
7. analiza MPA kontroluje siedlisko i głębokość, jeśli są dostępne;
8. każdy model ma diagnostykę i zapisany obiekt dopasowania;
9. wykresy zawierają jednostki, legendy, niepewność i dane źródłowe;
10. raport odróżnia wynik symulacji od wnioskowania o rzeczywistym ekosystemie;
11. żaden wynik demo nie jest przedstawiony jako empiryczny;
12. README dokładnie opisuje rozmieszczenie eksportów i uruchomienie projektu.

## Kolejność pracy Claude Code

1. Przeczytaj ten dokument i wykonaj rekurencyjną inwentaryzację repozytorium.
2. Rozpoznaj formaty, jednostki, czas, scenariusze, ensemble i strukturę siatki.
3. Utwórz outputs/tables/input_inventory.csv oraz data_issues.csv.
4. Zaproponuj jawne mapowanie rzeczywistych kolumn do kontraktów kanonicznych.
5. Zbuduj strukturę, konfigurację, funkcje importu i testy QC.
6. Uruchom import na małej próbce i sprawdź liczebności oraz sumy kontrolne.
7. Implementuj modułami: Ecosim, Ecospace, MPA, niepewność, trade-offs.
8. Po każdym module uruchom testy i zapisz diagnostykę.
9. Wygeneruj figury, tabele i raport.
10. Podsumuj: co powstało, co wykonano, co pominięto, jakie ostrzeżenia pozostały i jakich danych brakuje.

Jeżeli repozytorium nie zawiera jeszcze danych, przygotuj pełną strukturę, kontrakty, konfigurację, importery i testy. Opcjonalny przykład demo musi pozostać oddzielony i jednoznacznie oznaczony.

## Podstawa metodyczna

Przy uzasadnianiu metod korzystaj z dokumentacji EwE i literatury źródłowej:

- Christensen, V. i Walters, C.J. (2004), Ecopath with Ecosim: methods, capabilities and limitations: https://doi.org/10.1016/j.ecolmodel.2003.09.003
- Heymans, J.J. i in. (2016), Best practice in Ecopath with Ecosim food-web models: https://doi.org/10.1016/j.ecolmodel.2015.12.007
- Scott, E. i in. (2016), The Ecosim Stepwise Fitting Procedure: https://doi.org/10.1016/j.softx.2016.02.002
- Bentley, J.W. i in. (2024), advances in Ecosim model calibration: https://doi.org/10.1093/icesjms/fsad213
- Romagnoni, G. i in. (2015), spatial performance of Ecospace: https://doi.org/10.1016/j.ecolmodel.2014.12.016
- Steenbeek, J. i in. (2021), spatial-temporal marine ecosystem modelling: https://doi.org/10.1016/j.envsoft.2021.105209
- Coll, M. i Steenbeek, J. (2017), standardized ecological indicators: https://doi.org/10.1016/j.envsoft.2016.12.004
- Steenbeek, J. i in. (2018), Ecosampler and parameter uncertainty: https://doi.org/10.1016/j.softx.2018.06.004
- Walters, C. i in. (1999), Ecospace spatial patterns: https://doi.org/10.1007/s100219900101
- Oficjalna strona EwE: https://ecopath.org/

Dobieraj metody do struktury danych, nie odwrotnie. Każde istotne odejście od tego planu opisz w raporcie wraz z uzasadnieniem.

