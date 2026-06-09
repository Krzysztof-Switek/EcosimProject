# Architektura

## Cel

Modułowe, rozszerzalne narzędzie webowe do (1) porządkowania i indeksowania danych
EwE, (2) wszechstronnej analizy/porównań/prezentacji wyników (jeden scenariusz wiele
zmiennych, wiele scenariuszy, wiele grup) oraz (3) uruchamiania z przeglądarki skryptów
R na ustandaryzowanym formacie.

## Warstwy

```
DataEcosim/ (surowe, niezmienne)
   │  INGESTIA (Python): rejestr parserów → tidy
   ▼
Kanoniczny STORE              KATALOG (DuckDB) — indeks do nawigacji
  • timeseries/ (Parquet)  ◄────────────┘
  • spatial/ (COG + indeks)
  • dictionaries/ (groups, fleets, scenarios)
   │
   ├─► API (FastAPI): /catalog, /timeseries, /spatial, /analyses, /jobs
   │      └─► Frontend (React): katalog, wykresy, mapy, runner analiz
   └─► R RUNNER: sandbox plikowy (manifest + data) → Rscript → out/result.json
```

## Kanoniczny model

* **Szeregi czasowe** — jedna tidy tabela (schemat w [`data-contract.md`](data-contract.md)),
  Parquet partycjonowany `scenario=/domain=/variable=/freq=`. Zapytania przez DuckDB.
* **Przestrzenne** (etap 2) — `.asc` → Cloud-Optimized GeoTIFF + tabela indeksu rastrów.
* **Słowniki** — `groups` (50), `fleets` (9), `scenarios`; jedno źródło prawdy ID↔nazwa.
* **Katalog** — produkt ingestii (regenerowalny): jeden wpis na (scenario, domain,
  variable, freq) + tabele wymiarów + widok `timeseries` nad Parquet.

## Cztery punkty rozszerzalności (modularność)

1. **Rejestr parserów** — nowy typ pliku = nowy parser w `ingestion/parsers/`.
2. **Typy datasetów w katalogu** — dyspatch po kształcie nagłówka, nie po nazwie pliku.
3. **Pluginy analiz R** — folder `rkit/analyses/<id>/` z `analysis.yaml` + `entry.R`.
4. **Renderery wyników w UI** — dobierane po `type` artefaktu z `result.json`.

## Mapowanie kodu

| Warstwa | Lokalizacja |
|---|---|
| Konfiguracja ścieżek | `backend/ecosim/core/config.py` |
| Kanoniczny schemat | `backend/ecosim/core/schema.py` |
| Parsery | `backend/ecosim/ingestion/parsers/` |
| Zapis Parquet | `backend/ecosim/ingestion/store.py` |
| Pipeline ETL | `backend/ecosim/ingestion/pipeline.py` |
| Budowa katalogu | `backend/ecosim/catalog/build.py` |
| Zapytania katalogu | `backend/ecosim/catalog/service.py` |
| API | `backend/ecosim/api/` |
| CLI | `backend/ecosim/cli.py` |

## Tryby wdrożenia

* **Lokalny (MVP)** — DuckDB plikowy, `Rscript` lokalnie, brak auth, CORS dla Vite.
* **Serwer (etap 4)** — auth, kolejka zadań (Celery/RQ za interfejsem `JobQueue`),
  konteneryzacja R, storage obiektowy. Kontrakty we/wy bez zmian.
