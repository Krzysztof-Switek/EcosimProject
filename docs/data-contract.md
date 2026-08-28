# Kontrakt danych i analiz R

Ten dokument definiuje **domyślny format**, w którym framework rozmawia ze skryptami
naukowców (R, później także Python). Skrypt **nigdy nie czyta surowego katalogu źródłowego
bezpośrednio** — dostaje przefiltrowane dane kanoniczne i zwraca wyniki w ustandaryzowanej
strukturze, którą frontend renderuje automatycznie.

## Oczekiwany układ katalogów źródłowych

**Nie ma jednego wymaganego układu katalogów — odkrywanie jest w pełni oparte o treść
plików, nie o nazwę czy głębokość folderu.** Świeża weryfikacja oficjalnej dokumentacji EwE
(User Guide s.50-51, 79-81, 265, 275 — patrz `docs/ewe-data-formats.md`, sekcja "Struktura
katalogów wyjściowych EwE — nie ma jednej") potwierdziła, że lokalizacja zapisu wyników w
samym EwE jest w pełni konfigurowalnym ustawieniem użytkownika, bez żadnej udokumentowanej
ani stałej nazwy folderu. Wcześniejsza wersja tego dokumentu opisywała sztywny wymóg
(`output/` bezpośrednio pod wskazanym katalogiem + obowiązkowy `Mapa_grupy_fleets.xlsx`) —
to był błąd tego projektu, nie wymóg EwE; został usunięty 27.08 po tym, jak odrzucił
prawdziwy, poprawny eksport Monte Carlo użytkownika zorganizowany inaczej niż jeden
przykładowy zestaw danych, na którym pierwotnie oparto tę konwencję.

Aplikacja rozróżnia **dwa niezależne źródła danych** (patrz `core/workspace.py`) — dane
wyjściowe modelu (wyniki Ecosim/Ecospace) i dane wejściowe (drivery/wymuszenia) — bo mogą
pochodzić z różnych miejsc/momentów. Każde wskazywane osobno na ekranie startowym.

**Model output data** (wymagane) — wskaż **dowolny** katalog; odkrywanie (`_discover_output`
w `ingestion/pipeline.py`, `_discover_output_rasters` w `ingestion/spatial_pipeline.py`)
przeszukuje go **rekurencyjnie**, bez znaczenia na jakiej głębokości czy pod jaką nazwą
folderu leżą pliki:
- Każdy `*.csv` jest otwierany i sprawdzany pod kątem własnego nagłówka `<HEADER ecosim/>`
  z polem `EcosimScenario` — to on (razem z `ModelName`) grupuje pliki w scenariusz, **nie**
  folder, w którym leżą.
- Każdy `*.asc`, którego nazwa pasuje do wzorca timestepu Ecospace, jest traktowany jako
  mapa; jeśli w tym samym folderze leży `Ecospace RunInfo.txt`, z niego brane są
  `ModelName`/`EcosimScenario`/`StartYear`/`CoordinateSystemWKT` — w przeciwnym razie nazwa
  scenariusza spada do nazwy folderu nadrzędnego.

Walidacja przy rejestracji (`validate_output_root`) tylko sprawdza, czy odkrywanie
cokolwiek znalazło — brak wyniku daje czytelny błąd ("No EwE output was found anywhere
under this folder...") zanim cokolwiek się zaindeksuje. Wskazanie katalogu o jeden poziom
za wysoko lub za nisko (np. wprost na sam folder z `.asc`, zamiast jego rodzica) **nie jest
już błędem** — rekurencja i tak to znajdzie.

**Słownik grup/flot (`Mapa_grupy_fleets.xlsx`) jest opcjonalny, nie wymagany.** To **własna
konwencja tego projektu** do rozwiązywania numerycznych id grup/flot EwE na czytelne nazwy —
**nie** artefakt czy wymóg samego EwE; żaden fragment oficjalnej dokumentacji go nie zna ani
nie wymaga. Jeśli plik zostanie znaleziony gdziekolwiek pod wskazanym katalogiem, jest
używany do rozwiązania nazw. Jeśli go nie ma:
- Rastry (`.asc`) i tak mają nazwę encji wprost w nazwie pliku (natywna, opisowa konwencja
  EwE) — nic się nie gubi.
- Wiersze CSV zachowują swoje `group_id`/`fleet_id`, ale `name` wychodzi jako `null`
  (`Dictionaries.empty()`, patrz `parsers/group_map.py`).

Wcześniej brak tego pliku twardo blokował całe ładowanie danych z mylącym błędem
wskazującym na plik xlsx jako "brakujący output modelu" — naprawione 27.08, pokryte
`backend/tests/test_optional_dictionary.py`.

**Model input data** (opcjonalne) — również dowolny katalog, przeszukiwany rekurencyjnie
(`_discover_input`) w poszukiwaniu `trend_*.csv` i pasujących `.asc`. W odróżnieniu od
outputu, pliki driverów **nie mają** żadnej osadzonej w treści identyfikacji (nazwa drivera
ani scenariusza nigdzie w środku pliku) — to jedyne miejsce, gdzie nazwa nadal pochodzi z
położenia w drzewie katalogów: driver = nazwa folderu bezpośrednio nadrzędnego wobec pliku,
scenariusz = folder o poziom wyżej. Bez tego źródła po prostu brak zmiennych typu driver —
reszta działa normalnie.

Jeśli jeden pakiet ma i `output/`, i `input/` obok siebie (typowy przypadek — tak wygląda
dzisiejszy `DataEcosim/`) — wskaż **ten sam katalog** dla obu kafelków; rekurencja znajdzie
oba niezależnie od tego, że leżą pod wspólnym rodzicem.

## Kanoniczny schemat szeregów czasowych (tidy)

Każdy plik wynikowy Ecosim (formaty: szeroki wg ID, szeroki wg nazw/predacja, długi
flota-grupa, jednoseryjny) jest sprowadzany do jednej tabeli o kolumnach:

| kolumna | typ | opis |
|---|---|---|
| `scenario` | str | id scenariusza, np. `baseline_cumulative` |
| `domain` | str | `output` (wyniki Ecosim) lub `input` (drivery) |
| `variable` | str | slug zmiennej, np. `biomass`, `catch_fleet_group`, `predation` |
| `freq` | str | `annual` lub `monthly` |
| `date` | str (ISO) | pierwszy dzień okresu |
| `year`, `month` | int | dla filtrowania (`month=1` dla annual) |
| `group_id`, `group_name` | int/str? | grupa funkcyjna (null dla wskaźników globalnych) |
| `fleet_id`, `fleet_name` | int/str? | flota (tylko zmienne per-flota) |
| `partner_id`, `partner_name` | int/str? | grupa interagująca (np. drapieżnik w `predation`) |
| `value` | float | wartość |
| `unit` | str? | etykieta/jednostka z metadanych EwE |

Słowniki (`groups`, `fleets`, `scenarios`) są jedynym źródłem prawdy dla mapowania
ID ↔ nazwa i są eksportowane do `data/dictionaries/`.

## Sandbox uruchomienia analizy

Dla każdego uruchomienia framework przygotowuje katalog roboczy:

```
job_<id>/
  manifest.json        # selekcja z UI: scenariusze, zmienne, grupy, zakres lat, freq
  params.json          # parametry formularza danej analizy
  data/
    timeseries.parquet # JUŻ przefiltrowane wg selekcji (schemat powyżej)
    spatial/           # (analizy przestrzenne) COG-i + raster_index.csv
    dictionaries/      # groups.csv, fleets.csv, scenarios.csv
  out/                 # <-- skrypt zapisuje tu wyniki
```

### `manifest.json` (przykład)
```json
{
  "analysis_id": "biomass_trend_compare",
  "scenarios": ["baseline_cumulative", "has_cumulative"],
  "variables": ["biomass"],
  "freq": "annual",
  "groups": ["Cod adult", "Herring adult"],
  "year_from": 1998,
  "year_to": 2050
}
```

## Wyniki: katalog `out/` + `result.json`

Skrypt zapisuje artefakty i opisuje je w `out/result.json`. Frontend dobiera
renderer po polu `type`.

```
out/
  result.json
  tables/   *.csv | *.parquet
  figures/  *.png | *.svg
  rasters/  *.tif        (GeoTIFF)
```

### `result.json`
```json
{
  "status": "ok",
  "title": "Porównanie trendów biomasy",
  "artifacts": [
    { "type": "figure", "path": "figures/trend.png", "title": "Trend biomasy" },
    { "type": "table",  "path": "tables/summary.csv", "title": "Podsumowanie" },
    { "type": "scalar", "title": "Zmiana % 1998→2050", "value": -12.4, "unit": "%" },
    { "type": "map",    "path": "rasters/diff.tif", "title": "Mapa różnicowa" }
  ]
}
```

Dozwolone `type`: `figure` | `table` | `map` | `scalar` | `vega_spec`. Nowy typ =
nowy renderer w UI, bez zmian w rdzeniu.

## R SDK `ecosimkit`

Cienka biblioteka, by naukowiec nie pisał kontraktu ręcznie:

```r
library(ecosimkit)

ts     <- ecosim_load_timeseries()   # data.frame ze schematu tidy
params <- ecosim_params()            # lista parametrów z params.json
groups <- ecosim_dict("groups")

fig <- plot_trends(ts)               # własna logika naukowca
ecosim_emit_figure(fig, "trend.png", title = "Trend biomasy")
ecosim_emit_table(summarise(ts), title = "Podsumowanie")
```

Emitery zapisują artefakt do `out/` **i** dopisują wpis do `result.json`.

## Rejestracja analizy (`analysis.yaml`)

Każda analiza to folder w `rkit/analyses/<id>/` z `analysis.yaml` + `entry.R`:

```yaml
id: biomass_trend_compare
name: "Porównanie trendów biomasy"
description: "Porównuje trendy biomasy wybranych grup między scenariuszami."
requires: { domain: timeseries, variables: [biomass], dims: [scenario, group] }
params:
  - { key: smoothing, type: number, default: 3, label: "Wygładzanie (lata)" }
  - { key: relative,  type: bool,   default: false, label: "Względem roku bazowego" }
entry: entry.R
```

Frontend automatycznie generuje formularz z sekcji `params`. Backend przygotowuje
sandbox z danymi spełniającymi `requires`, woła `Rscript entry.R`, po czym czyta
`out/result.json`.

## Uruchamianie

* **Lokalnie (MVP):** backend tworzy sandbox i woła `Rscript entry.R`.
* **Serwer (etap 4):** identycznie, ale w kontenerze z obrazem R + `ecosimkit`,
  za kolejką zadań i z limitami zasobów. **Kontrakt się nie zmienia** — dlatego
  sandbox jest plikowy i język-agnostyczny (ten sam mechanizm zadziała dla Pythona).
```
