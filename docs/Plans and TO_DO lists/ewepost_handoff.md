# ewepost — dokument przekazania kontekstu

**Cel dokumentu:** wklej to na początku nowej rozmowy z Claude, żeby odtworzyć pełny kontekst bez powtarzania ustaleń.

**Status:** projekt narzędzia do obróbki danych z Ecosim/Ecospace. **Nie** manuskrypt.
**Data ostatniej aktualizacji:** 2026-08-27
**Rozmówca:** Maciej — ekolog ekosystemów morskich, MIR-PIB (Gdynia) / SLU Aqua, modelowanie EwE/Ecospace, ENA, detekcja zmian reżimowych, MSE. Tryb pracy: krytyczny recenzent, nie asystent. Wymaga pełnych tekstów bez skrótów, jawnego rozdzielania faktów / interpretacji / spekulacji.

---

## 1. Czego dotyczy projekt

Budowa narzędzia (pakiet R `ewepost`) do post-processingu wyjść **Ecosim i Ecospace**, obejmującego:

- analizy statystyczne szeregów czasowych i map,
- kontrast MPA / poza-MPA (spillover, redystrybucja nakładu),
- analizę sieci troficznych (ENA),
- ocenę dopasowania i niepewności.

**Rpath został usunięty z zakresu na wyraźne życzenie.** Wszystkie ścieżki opierają się wyłącznie na natywnych wyjściach EwE6 i jego wtyczek.

---

## 2. Ustalenia metodyczne, które są fundamentem całej architektury

### 2.1. Problem determinizmu (najważniejszy)

Output Ecosim/Ecospace jest **deterministyczny**. Pojedynczy przebieg nie ma wariancji. W konsekwencji:

- testy istotności na komórkach siatki lub krokach czasowych to **pseudoreplikacja**; p-wartość można dowolnie zmniejszyć zwiększając rozdzielczość siatki,
- jedyne legalne źródła wariancji: ensemble Monte Carlo na parametrach Ecopath, ensemble wulnerabilności, ensemble forsowań, replikacja warunków początkowych,
- każda „statystyka" musi być zdefiniowana jako analiza **rozkładu wygenerowanego przez zdefiniowany a priori mechanizm losowania**, nie jako test hipotezy o populacji.

**Implementacja:** twardy walidator `require_ensemble()`, który **rzuca błąd** (nie ostrzeżenie), gdy oś niepewności ma jeden poziom. Funkcje wizualizacyjne oznaczone `[E]` odmawiają rysowania bez ensemble'u.

### 2.2. Ograniczenie ensemble'u w Ecospace — strukturalne, nie tymczasowe

Z User Guide EwE (Christensen, Steenbeek & Walters 2024, rozdz. *Addressing Uncertainty*):

| Źródło niepewności | Mechanizm natywny | Status |
|---|---|---|
| Parametry Ecopath (B, P/B, Q/B, EE, diety) | MC + Ecosampler → propagowane do Ecosim **i Ecospace** | dostępne |
| Parametry Ecosim (v, forsowania) | częściowo Stepwise Fitting / Multi-Sim | dostępne |
| **Parametry Ecospace** (dispersal, vulnerability in bad habitat, effective power, HFCM) | **niedostępne dla MC/Ecosampler** | wymaga zewnętrznych, skryptowanych re-runów |
| Struktura (agregacja, diety, równania) | brak | wyłącznie zewnętrzne re-runy |

Narzędzie musi to jawnie raportować (figura **F82** — macierz pokrycia: klasa parametru × czy była perturbowana). Obietnica „analizy niepewności Ecospace" bez tego zastrzeżenia wprowadza użytkownika w błąd.

### 2.3. Gradient ≠ dowód korzyści dla rybołówstwa

Gradient biomasy przy granicy MPA jest matematyczną konsekwencją dyfuzji przy różnicy zagęszczeń (Hilborn i in., *Theoretical Ecology* 2024). Jedynym poprawnym testem korzyści rybackiej jest **porównanie całkowitego połowu i zysku na całej domenie** między scenariuszem z MPA i bez MPA.

**Implementacja:** funkcja `ewepost_spillover_gradient()` zwraca `$meta$caveat` ze stałym tekstem ostrzegawczym, a funkcja wizualizacyjna wstawia go do podpisu figury. Ostrzeżenie w dokumentacji zostanie pominięte; w podpisie figury pojedzie razem z figurą do manuskryptu.

### 2.4. Counterfactual w tej samej komórce, nie in vs out

Przewaga modelu nad danymi empirycznymi: dostępny jest idealny counterfactual (ten sam przebieg bez MPA). Analizować **różnicę scenariuszy w tej samej komórce**, nie różnicę między komórkami. To eliminuje confounding siedliskowy w całości.

### 2.5. Dispersal rate determinuje wynik MPA

Z User Guide (*Spatial Model Skill Assessment*): tempo dyspersji wpływa na efekty MPA — wysoka dyspersja przewiduje duży spillover i utrudnia odbudowę biomasy, redukując korzyści dla gatunków silnie eksploatowanych; jednocześnie wyższe tempa dyspersji dają modele **lepiej dopasowane do danych, ale ekologicznie nierealistyczne**.

**Figura F68 (`viz_sens_dispersal`) jest obowiązkowa**, nie opcjonalna. Bez niej wynik MPA jest nieinterpretowalny.

### 2.6. Model floty jest najsłabszy dokładnie tam, gdzie go używamy

Ecospace zakłada, że wszystkie elementy floty mają **pełną wiedzę** o rozkładzie gatunków docelowych. Modele grawitacyjne tracą wydajność predykcyjną przy wcześniej nieobserwowanej dynamice — czyli przy zamknięciu przestrzennym (Dolder i in., *Fish and Fisheries* 2025).

**Figura F69** — wrażliwość na parametry alokacji nakładu + scenariusz kontrolny „nakład przesunięty proporcjonalnie".

---

## 3. Co EwE produkuje natywnie (specyfikacja warstwy adapterów)

Źródło: https://pressbooks.bccampus.ca/eweguide/ (CC BY-NC-SA, EII 2024)

### 3.1. Kluczowe odkrycia z User Guide

| Mechanizm | Znaczenie dla narzędzia |
|---|---|
| **Regions** (*Ecospace Output*) | Ecospace automatycznie sumuje wyniki po całym obszarze wg grupy i floty, a po wczytaniu mapy podobszarów w „Maps → Regions" — także per region. Komórka należy do **co najwyżej jednego regionu**. |
| **Transect Extraction Plugin** (*Ecospace Output*) | Po przebiegu wyciąga wzdłuż transektu głębokość, biomasę, połów i MPA przecięte, per krok czasowy. To natywne źródło profilu gradientu MPA. |
| **Results Extractor** (CEFAS) | B, consumption `Qji = Bj·(Q/B)j·DCji`, residuals per grupa, SS per grupa i globalne, opcja Yearly (średnie roczne), **„Biomass integrated"** = pole pod szeregiem zmiany względem stanu początkowego (metryka porównawcza strategii zarządczych). |
| **enaR Plugin (SCOR)** | Pełna sieć przepływów **per komórka, per krok**. Ścieżka: `{output}/{scenariusz}/ena_data/Timestep=000x/`, plik na komórkę, nazwa `nnn{wiersz}-nnn{kolumna}-{model}-{scenariusz}.txt`, indeksowanie 1-based od lewego górnego rogu. Status: **prototyp**. |
| **XY Hotspot Tool** | Walidacja telemetryczna: liczy błąd predykcji między mapami modelu a mapami z telemetrii; zwraca raster błędu. |
| **Prebal Plugin** | PREBAL jest natywny — nie reimplementować, ingestować. |
| **Ecospace Spinup Plugin** | Spin-up natywny (status EwE Pro). |
| **Stepwise Fitting Plugin** | Automatyzuje siatkę hipotez dopasowania SS/AIC. |
| **Ecospace MonteCarlo / Sensitivity / Fit / Spatial SS** | Wszystkie w statusie **prototypu** — formaty niestabilne, wymagają izolacji za wersjonowanymi adapterami. |

Rejestr wtyczek w User Guide ma stan z **27 września 2022** — może być nieaktualny.

### 3.2. Ostrzeżenie o skali

User Guide ostrzega wprost, że zapis wyjścia przestrzennego dla każdego miesięcznego kroku daje bardzo duże wolumeny. Dla plików SCOR jest to katastrofalne: 20 000 komórek × 600 kroków = **12 mln małych plików tekstowych**. Adapter musi działać strumieniowo i redukować w locie.

### 3.3. Metody scoringu stosowane w literaturze Ecospace

Z rozdz. *Addressing Uncertainty*:
- korelacja przestrzenna Spearmana — `raster::corLocal()` (obecnie: `terra::focalPairs()`),
- korelacja Mantela z 999 permutacjami (Lynam i in. 2017),
- Püts i in. 2020: Pearson + RMSE (czas) i Schoener's D (przestrzeń), połączone na **diagramie Taylora**,
- statystyki przestrzenno-czasowej korelacji krzyżowej **wciąż w opracowaniu**.

Framework „bound, search, score" (Romagnoni i in. 2015). Typowo tunowane parametry Ecospace: *vulnerability exchange rate*, *base dispersal rate*, *relative vulnerability to predation in bad habitat*, *effective power of fishing fleets*.

---

## 4. Architektura narzędzia

### 4.1. Struktura

Pakiet R `ewepost` + osobne repo projektu użytkownika. Pakiet **nie zna** żadnej nazwy grupy, floty ani scenariusza — wszystko przychodzi z rejestrów projektu.

```
ewepost/                          # PAKIET
├── R/ (contracts, registry, adapt_*, store_*, prep_*, an_*, viz_*, rep_*)
├── inst/ (extdata/fixtures, schemas, config, cli, targets)
├── tests/testthat/
└── vignettes/

projekt-uzytkownika/              # OSOBNE repo
├── _targets.R
├── config/ (project.yml, runs_registry.csv, groups_, fleets_,
│            scenarios_, regions_, transects_registry.csv)
├── data/{raw,interim,store}/
└── outputs/{figures,tables,logs,reports}/
```

### 4.2. Warstwy (jednokierunkowa zależność)

```
ADAPT → STORE → PREP → AN → VIZ → REP
```

**VIZ nigdy nie liczy statystyk. AN nigdy nie rysuje.** Jedyny sposób, żeby dało się testować obie warstwy osobno.

### 4.3. Klucz główny

```
run_id = hash(model_variant, ecosim_scenario, ecospace_scenario,
              forcing_set, mc_sample, vuln_set, grid_res, ewe_version)
```

Plus obowiązkowa kolumna `uncertainty_axis ∈ {none, ecopath_param, vulnerability, forcing, ecospace_param, structural}` — steruje walidatorem ensemble'u. Żaden adapter nie odtwarza metadanych z nazw katalogów; parsuje je tylko po to, by **dopasować** do wiersza rejestru. Brak dopasowania = błąd, nie zgadywanie.

### 4.4. Kanoniczny model danych (9 tabel)

| Tabela | Zawartość |
|---|---|
| `sim_ts` | szeregi zagregowane: run_id, scenario, uncertainty_axis, mc_sample, year, month, group, fleet, zone_type, zone_id, variable, value, unit, source_tool |
| `sim_map` | rastry (netCDF): (cell\|x,y) × time × group × run |
| `grid_meta` | metadane siatki: cell_id, row, col, x, y, area_km2, kowarianty, region_id, mpa_\*, access_\*, dist_border_\*, zone_\*, ctrl_match_id, edge_flag, land_mask, excluded_flag |
| `transect` | natywne i własne transekty: transect_id, position_along, cell_id, depth, mpa_flag, group, variable, value |
| `network` | macierze przepływów na poziomie modelu |
| `ena_cell` | **ENA per komórka** (z SCOR): run_id, scenario, timestep, cell_id, index_name, value |
| `obs` | obserwacje + flagi `used_in_calibration` / `used_in_validation` (jednoczesne TRUE = błąd twardy) |
| `params` | parametry per przebieg z `param_class` |
| `fitstats` | SS, AIC, AICc, r, RMSE, AAE, AE, MEF, Schoener D |

**Składowanie:** DuckDB (agregacje SQL na dziesiątkach mln wierszy) + netCDF (rastry). Nie czysty Parquet.

**Konwencja zwrotu z AN:** każda funkcja zwraca `list(estimate, meta, diagnostics)`, gdzie `meta` zawiera `run_ids`, `n_ensemble`, `uncertainty_axes`, `method`, `call`. VIZ czyta `meta` i **automatycznie** dopisuje do podpisu figury, na czym oparto niepewność.

### 4.5. Moduły analityczne

- **AN-1** diagnostyka wejścia (PREBAL, EE/GE, wrażliwość na agregację)
- **AN-2** kalibracja i skill (SS/AICc, r, ρ, RMSE, nRMSE, AAE, AE, MEF, reszty, retro, hindcast)
- **AN-3** ENA (poziom modelu + **poziom komórki z SCOR**, MTI, keystoneness ≥2 definicje, spektra troficzne, robustness)
- **AN-4** szeregi czasowe (GLS/GAM, STARS + siatka L×p, ITA, changepoint, TGAM, gradient forest, stabilność, DFA)
- **AN-5** scenariusze (LRR, **Biomass integrated uogólnione**, Pareto, dominacja, ryzyko, specyficzność wskaźników)
- **AN-6** przestrzeń (wskaźniki Woillez, Schoener D / Warren I, Mantel 999, `focalPairs`, DiD, gradient, strumień graniczny, metryki floty, autokorelacja)
- **AN-7** walidacja (model vs obs, walidacja regionalna, **blokowa CV**, XY Hotspot, audyt cyrkularności)
- **AN-8** ensemble i wrażliwość (Ecosampler, kwantyle, dekompozycja wariancji, Morris, Sobol, emulator GP)
- **AN-9** MSE (odczyt wyjść CEFAS-MSE; **bez** orkiestracji pętli — poza zakresem v1)

### 4.6. Katalog wykresów

85 figur w 9 blokach (A–I), z oznaczeniami: **[E]** wymaga ensemble'u, **[N]** dane z natywnego wyjścia EwE, **[C]** zestaw rdzeniowy.

Zestaw rdzeniowy (`--set core`): F01, F06, F09, F10, F15, F16, F17, F25, F27, F29, F31, F37, F38, F39, F45, F46, F48, F51, F53, F57, F68, F70, F72, F75, F76, F82 + F-REC-1, F-REC-3.

**Figury bez odpowiednika w istniejących narzędziach:**
- **F25/F26** — mapa wskaźnika ENA po siatce (A/C, FCI, APL per komórka z SCOR) i jej wersja różnicowa. Pokazują, czy MPA zmienia **organizację sieci troficznej**, a nie tylko poziom biomas.
- **F82** — macierz pokrycia niepewności.
- **F-REC-3** — ranking konwencji agregacji.

**Nie implementujemy wykresów radarowych.** Pole wielokąta zależy od kolejności osi, więc figura koduje decyzję rysującego, nie dane. `viz_radar()` zwraca błąd z odesłaniem do F37 (forest plot LRR).

---

## 5. Stan kodu — co już napisane

Pięć plików `.R` (skrypty stojące samodzielnie, do wchłonięcia przez pakiet):

| Plik | Zawartość |
|---|---|
| `ewepost_grid.R` | `ewepost_grid_meta()`, `ewepost_attach_regions()`, `ewepost_attach_mpa()`, `ewepost_signed_distance()` (euklidesowa i **po wodzie**), `ewepost_buffer_zones()`, `ewepost_match_controls()` |
| `ewepost_zonal.R` | `EWEPOST_VAR_SEMANTICS`, `ewepost_semantics()`, `ewepost_zonal_one()`, `ewepost_zonal_stack()`, `ewepost_conv_grid()`, `ewepost_zonal_all_conv()` |
| `ewepost_transect.R` | `ewepost_transect_line()`, `ewepost_transect_perpendicular()`, `ewepost_transect_cells()`, `ewepost_transect_extract()`, `ewepost_transect_signed()`, `ewepost_spillover_gradient()` |
| `ewepost_reconcile.R` | `ewepost_disc_metrics()`, `ewepost_reconcile_zonal()`, `ewepost_reconcile_search()`, `ewepost_reconcile_transect()`, `ewepost_invariants()`, `viz_reconcile_*()`, `viz_conv_ranking()` |
| `ewepost_selftest.R` | 7 testów na syntetycznej siatce lon/lat, działa **bez danych z EwE** |

### 5.1. Rola ścieżki R — to nie jest fallback

EwE nie dokumentuje konwencji agregacji strefowej (suma vs średnia arytmetyczna vs średnia ważona powierzchnią; traktowanie lądu i komórek wykluczonych). Ścieżka R pełni trzy funkcje:

1. **Identyfikacja konwencji** — `ewepost_reconcile_search()` przeszukuje 16 konwencji × 2 statystyki i wskazuje tę, która odtwarza eksport EwE. Wynik fiksuje się w `project.yml`.
2. **Rozszerzenie poza możliwości EwE** — pierścienie buforowe, komórki dopasowane kontrolnie, strefy nakładające się (Regions wymaga ≤1 regionu na komórkę).
3. **Kontrola krzyżowa** — dwie niezależne implementacje jako jedyny mechanizm wykrywania błędów jednostek, masek i wag.

**Kolejność w pipeline: najpierw uzgodnienie, potem cokolwiek innego.** Certyfikat zgodności jest warunkiem wejścia do modułu analitycznego.

### 5.2. Semantyka zmiennych — najważniejsza decyzja

| Semantyka | Zmienne | Suma | Średnia |
|---|---|---|---|
| `density` | biomass, catch, landings, discards, effort, consumption, value, cost, profit | `Σ vᵢaᵢ` | `Σ vᵢaᵢ / Σ aᵢ` |
| `rate` | **F, Z, pred_mort, TL, feeding time, P/B, Q/B** | niezdefiniowana | `Σ rᵢwᵢ / Σ wᵢ`, `wᵢ = Bᵢaᵢ` |
| `fraction` | habitat foraging capacity | niezdefiniowana | ważona powierzchnią |
| `flag` | mpa, substrat | liczba komórek | udział powierzchni |

**`mean(F)` po komórkach jest błędem systematycznym w jednym kierunku:** F = 0 w komórkach chronionych, a te mają wyższą biomasę, więc średnia arytmetyczna zaniża realną śmiertelność połowową na jednostkę biomasy. To samo dotyczy TL wspólnoty i czasu żerowania. `ewepost_semantics()` **rzuca błąd** dla nieznanej zmiennej zamiast zgadywać.

### 5.3. Powierzchnia komórki na siatce lon/lat

Modele bałtyckie mają rozpiętość 6–8° szerokości; powierzchnia komórki spada z `cos(φ)` — między 54°N a 62°N różnica ~21%. Naiwna `mean()` po komórkach zawyża wkład komórek północnych. Rozwiązanie: `terra::cellSize(unit = "km")`, wszystkie agregacje ważone `area_km2`.

**Otwarte:** czy EwE stosuje wagę powierzchniową. Jeśli nie — a jest to prawdopodobne, bo Ecospace operuje na jednorodnej siatce — natywne region-summary są obciążone i ścieżka R jest *poprawniejsza*. Wtedy nie dopasowywać się do EwE, tylko zaraportować rozbieżność jako znany artefakt.

### 5.4. Odległość euklidesowa vs po wodzie

Dla zamknięć na szwedzkim wybrzeżu metryka euklidesowa jest błędna — odległość „w poprzek półwyspu" nie odpowiada trasie, którą biomasa może przebyć, a dyfuzja Ecospace nie przenosi biomasy przez ląd. `method = "cost"` liczy odległość po wodzie. Jeśli różnica przekracza kilka procent, wariant euklidesowy nie nadaje się do publikacji dla tego obszaru.

### 5.5. Transekt — trzy pułapki obsłużone

1. **Kolejność:** `terra::extract()` na linii nie gwarantuje uporządkowania wzdłuż linii. Rozwiązanie: zagęszczenie do punktów co ¼ boku komórki + deduplikacja przez `rleid()`.
2. **Nierównomierność:** oś X to **odległość wzdłuż linii w km**, nie indeks komórki. Kolumny `d_enter`/`d_exit` do ewentualnego ważenia.
3. **Przerwy na lądzie:** `gap_flag`, bez interpolacji.

`ewepost_transect_perpendicular()` wyznacza kierunek z gradientu pola odległości ze znakiem — transekt nieprostopadły systematycznie zawyża zasięg spillover.

Zasięg spillover = pierwsza odległość dodatnia, przy której **przedział symultaniczny pochodnej pierwszej** obejmuje zero (nie przedział punktowy — ten zawyża zasięg przez brak kontroli wielokrotnego testowania).

### 5.6. Niezmienniki (test, nie interpretacja)

| Kod | Warunek | Co wykrywa |
|---|---|---|
| I1 | `Σ area_km2` po strefach = powierzchnia komórek objętych | dziury i nakładanie stref |
| I2 | `Σ n_cells` po strefach = liczba komórek objętych | komórka w dwóch strefach / w żadnej |
| I3 | `total = mean × area_km2` dla density/extensive | błąd wagi lub jednostek |
| I4 | brak ujemnych biomas | wybuch numeryczny lub błąd odczytu ASC |

### 5.7. Protokół uruchomienia

```r
source("ewepost_grid.R"); source("ewepost_zonal.R")
source("ewepost_transect.R"); source("ewepost_reconcile.R")
source("ewepost_selftest.R"); ewepost_selftest()          # 0. bez danych EwE

base <- ewepost_set_crs(terra::rast("depth.asc"), "EPSG:4326")
gm   <- ewepost_grid_meta(base, edge_width = 2L)
gm   <- ewepost_attach_regions(gm, terra::rast("regions.asc"))
gm   <- ewepost_attach_mpa(gm, sf::read_sf("mpa_S3.gpkg"), scenario = "S3")
gm   <- ewepost_signed_distance(gm, "S3", method = "cost")
gm   <- ewepost_buffer_zones(gm, "S3", breaks = c(0, 2, 5, 10, 20))

# KROK BLOKUJĄCY: identyfikacja konwencji
allc   <- ewepost_zonal_all_conv(maps, gm, "region_id", "biomass", "cod", 1991:2040)
native <- adapt_ecospace_regions("ecospace/S3/regions_summary.csv")
srch   <- ewepost_reconcile_search(native, allc)
viz_conv_ranking(srch)
# max_abs_rel < 1e-6 → konwencja zidentyfikowana, zapisz do project.yml
# max_abs_rel ~ 1e-2 → ZATRZYMAJ SIĘ, znajdź źródło rozbieżności
```

---

## 6. Testy i wydajność

**Testy:** adaptery na fixtures (5 grup, 3 floty, siatka 6×6, 24 kroki), kontrakty tabel, **niezmiennik krzyżowy „agregacja własna ≡ natywne Regions"** (najważniejszy test w pakiecie — wyłapuje błędy powierzchni, masek, wag i jednostek), walidatory, snapshoty wykresów (`vdiffr`), benchmarki.

**Wydajność:** strumieniowanie SCOR per katalog Timestep z `future.apply`; ASC → netCDF przy pierwszym ingeście; DuckDB zamiast `dplyr` na ramkach; pre-agregacja do kwantyli **przed** VIZ.

**Proweniencja:** każdy artefakt → wpis w `outputs/logs/provenance.jsonl` (kod, funkcja, wersja pakietu, sha256 wejść, run_ids, n_ensemble, osie niepewności, czas).

---

## 7. Ryzyka projektowe (ocena krytyczna)

1. **Zależność od formatów prototypowych** — enaR, Ecospace MonteCarlo/Sensitivity/Fit, Spatial SS. Rejestr wtyczek z 09.2022. Mitygacja: `experimental()`, fixtures, deklaracja wersji EwE.
2. **Ograniczenie ensemble'u w Ecospace jest strukturalne.** Mitygacja: F82 + twardy walidator + dokumentacja tego, czego się **nie** da.
3. **Skala danych** — naiwna implementacja przewróci się na pierwszym realnym modelu.
4. **Podwójne źródła tej samej wielkości** (Regions vs agregacja rastrów; SS z Results Extractora vs własne) — bez polityki rozstrzygania (`source_tool` + priorytet w konfiguracji) narzędzie da dwa wyniki na to samo pytanie.
5. **Kuszenie do reimplementacji** — PREBAL, spin-up, ENA, EcoIND mają natywne wtyczki. Domyślnie ingest; własna implementacja tylko jako `method = "internal"` z testem zgodności.
6. **Zakres pełzający ku MSE** — granica: wszystko, co wymaga uruchomienia EwE, jest poza zakresem v1.
7. **Brak pokrycia zachowania floty** — F69/F74 pokazują problem, nie rozwiązują go.

---

## 8. Znane luki w napisanym kodzie

1. `ewepost_transect_perpendicular()` używa różnic centralnych — na granicy o wysokiej krzywiźnie kierunek będzie niedokładny. Lepsze: normalna z wygładzonego poligonu (`sf::st_simplify`).
2. Brak ważenia transektu długością przecięcia (`d_exit - d_enter` dostępne, nieużywane).
3. `ewepost_match_controls()` — dopasowanie zachłanne, nieoptymalne globalnie. Docelowo `optmatch` lub caliper.
4. **Brak walidatora macierzy dostępu flot** (`access_<fleet>_<scenario>`). Test pełnego pokrycia iloczynu `flota × scenariusz × strefa`, bez `NA` i duplikatów, wyłapuje niespójności typu „flota rozszczepiona w S3, ale nie w S1". **Priorytet na następną iterację.**
5. `ewepost_reconcile_search()` zakłada, że rozbieżność ma źródło w konwencji. Jeśli najlepsza konwencja daje błąd ~1e-2, źródło jest inne: **jednostki** (t vs t·km⁻²), **moment agregacji czasowej** (średnia roczna z miesięcy vs wartość grudniowa), albo **inne indeksowanie komórek**. Diagnostyka tych trzech przypadków to osobny moduł.

---

## 9. Plan wydań

| Wersja | Zakres | Kryterium ukończenia |
|---|---|---|
| v0.1 | ADAPT (Ecopath, Ecosim CSV, Results Extractor, Ecospace maps, Regions) + STORE + kontrakty + testy | test niezmiennika Regions ≡ agregacja własna przechodzi |
| v0.2 | PREP + AN-2 (skill) + F06, F09, F10, F15 | pełny raport skill z jednego modelu |
| v0.3 | AN-6 przestrzeń + Transects + F45–F57, F68, F69 | pełny workflow MPA na jednym scenariuszu |
| v0.4 | AN-8 ensemble + Ecosampler + F76, F77, F82 + walidatory | odmowa rysowania [E] bez ensemble'u działa |
| v0.5 | AN-3 ENA + SCOR + F25, F26 | mapy wskaźników sieciowych po siatce |
| v0.6 | AN-4, AN-5, AN-7, AN-9 + reszta katalogu | pełny katalog |
| v1.0 | CLI, winiety, dokumentacja ograniczeń, stabilne API | użycie na drugim, niezwiązanym modelu bez zmian w pakiecie |

---

## 10. Otwarte pytania — potrzebne od Macieja

**Blokujące architekturę:**

1. **Wersja EwE i lista faktycznie zainstalowanych wtyczek** (Tools > Options > Plugins). Rejestr z 09.2022 — nie wiadomo, które prototypy awansowały. Determinuje liczbę ścieżek z fallbackiem.
2. **Czy jest dostęp do uruchamiania EwE z kodu** (headless / API). Jeśli tak — v1 może objąć orkiestrację re-runów po parametrach Ecospace, czyli jedyną drogę do prawdziwego ensemble'u przestrzennego. Jeśli nie — AN-8 pozostaje ograniczony do propagacji niepewności Ecopath i trzeba to zadeklarować.
3. **Realna skala:** liczba grup, flot, komórek wodnych, kroków czasowych, scenariuszy, replik MC. Decyduje, czy STORE to DuckDB + netCDF, czy wystarczy Parquet. Przebudowa tej warstwy później jest kosztowna.

**Potrzebne do domknięcia napisanego kodu:**

4. **CRS rastrów Ecospace** (pliki `.asc` zwykle go nie niosą).
5. **Przykładowy eksport Regions** (kilka wierszy) — nazwy kolumn i konwencja nazewnictwa stref, do napisania `adapt_ecospace_regions()`.
6. **Format macierzy dostępu flot w S1–S3A** — do walidatora z punktu 8.4.

---

## 11. Kontekst projektowy Macieja (istotny dla doboru przykładów)

- **Ecospace, scenariusze zamknięć trałowych S1–S3/S3A** (szwedzkie) — konfiguracja klas flot, struktura grup śledziowych, materiały dla interesariuszy. Rozwiązywanie niespójności strukturalnych w macierzach dostępu flota × scenariusz; możliwe rozszczepienie klas flot i rozdzielenie komponentu przybrzeżnego i pełnomorskiego śledzia.
- Praca nad MSE dla wschodniego Bałtyku (dorsz, śledź centralny, szprot, stornia) — **poza zakresem tego narzędzia** (Rpath usunięty), ale wyjścia wtyczki CEFAS-MSE są w zakresie odczytu.
- Zgłoszona wcześniej podatność recenzencka: brak zastosowanych analiz gradient forest / threshold na własnych danych (tylko dyskusje narzędziowe).

---

## 12. Jak kontynuować rozmowę

Najbardziej opłacalne następne kroki, w kolejności:

1. **`adapt_ecospace_regions()` + walidator macierzy dostępu flot** — odblokowuje krok uzgodnienia, czyli cały pipeline.
2. **Diagnostyka trzech pozostałych źródeł rozbieżności** (jednostki, moment agregacji czasowej, indeksowanie komórek).
3. **`adapt_enar_scor()` strumieniowy + `an_ena_cell.R`** — daje F25/F26, funkcjonalność bez odpowiednika w istniejących narzędziach.
4. **Szkielet pakietu**: `DESCRIPTION`, `NAMESPACE`, `contracts.R` z pełnymi schematami T1–T9, walidatory, sygnatury roxygen wszystkich `adapt_*`/`an_*`/`viz_*`, fixtures, `_targets.R`.

---

## Źródła kluczowe

- Christensen V., Steenbeek J., Walters C.J. (2024). *User Guide for Ecopath with Ecosim (EwE)*. Ecopath International Initiative. https://pressbooks.bccampus.ca/eweguide/ (CC BY-NC-SA)
- de Mutsert K. i in. (2023). Advances in spatial-temporal coastal and marine ecosystem modeling using Ecospace. *Treatise on Estuarine and Coastal Science*, 2nd ed. Elsevier.
- Steenbeek J. i in. (2021). Making spatial-temporal marine ecosystem modelling better — A perspective. *Environmental Modelling & Software* 145: 105209.
- Heymans J.J. i in. (2016). Best practice in Ecopath with Ecosim food-web models. *Ecological Modelling*.
- Steenbeek J. i in. (2018). Ecosampler. *SoftwareX*.
- Coll M., Steenbeek J. (2017). ECOIND plug-in. *Environmental Modelling & Software*.
- Romagnoni G. i in. (2015). The Ecospace model applied to the North Sea. *Ecological Modelling* 300: 50–60.
- Püts M. i in. (2020). Insights on integrating habitat preferences in process-oriented ecological models. *Ecological Modelling* 431: 109189.
- Woillez M. i in. (2007, 2009). Wskaźniki przestrzenne. *ICES JMS* 64: 537–550; *Aquat. Living Resour.* 22: 155–164.
- Spence M.A. i in. (2018). A general framework for combining ecosystem models. *Fish and Fisheries*.
- Hilborn R. i in. (2024). When does spillover from MPAs indicate benefits to fish abundance and catch? *Theoretical Ecology*.
- Dolder P. i in. (2025). A comparison of fleet dynamics models for predicting fisher location choice. *Fish and Fisheries*.
- Di Lorenzo M. i in. (2020). Assessing spillover from MPAs and its drivers. *Fish and Fisheries*.
