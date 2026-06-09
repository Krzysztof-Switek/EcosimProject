# Kontrakt danych i analiz R

Ten dokument definiuje **domyślny format**, w którym framework rozmawia ze skryptami
naukowców (R, później także Python). Skrypt **nigdy nie czyta surowego `DataEcosim/`** —
dostaje przefiltrowane dane kanoniczne i zwraca wyniki w ustandaryzowanej strukturze,
którą frontend renderuje automatycznie.

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
