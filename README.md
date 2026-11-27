# Ecosim Analysis Platform

Webowe narzędzie do analizy, porównywania i prezentacji wyników modelu **EwE
(Ecopath with Ecosim + Ecospace)** dla Bałtyku oraz do uruchamiania z przeglądarki
**skryptów R** pisanych przez naukowców na ustandaryzowanym formacie danych.

> Architektura i decyzje projektowe: [`docs/architecture.md`](docs/architecture.md).
> Kontrakt danych / format dla skryptów R: [`docs/data-contract.md`](docs/data-contract.md).

## Zasada: surowe → kanoniczne → prezentacja

Nikt powyżej warstwy ingestii nie czyta surowego `DataEcosim/`. Pipeline raz parsuje
wszystkie formaty Ecosim do **kanonicznego tidy store** (Parquet) + **katalogu** (DuckDB),
a API, frontend i skrypty R pracują wyłącznie na tym modelu.

```
DataEcosim/ ──(ingestia)──► data/ (timeseries Parquet + catalog DuckDB + dictionaries)
                                     │
                          ┌──────────┴───────────┐
                       API (FastAPI)        R runner (sandbox)
                          │
                    Frontend (React)
```

## Struktura repo

```
backend/    FastAPI + pipeline ingestii + katalog (Python, pakiet `ecosim`)
frontend/   React SPA (Vite + TS) — przeglądarka katalogu, wykresy, mapy
rkit/       Pakiet R `ecosimkit` + zarejestrowane analizy
deploy/     Wdrożenie na serwer: nginx, systemd, .env, deploy.sh (instrukcja w deploy/README.md)
docs/       architecture.md, data-contract.md, ewe-data-formats.md, plany
data/       Kanoniczny store (generowany, w .gitignore)
DataEcosim/ Surowe dane źródłowe (w .gitignore)
```

## Szybki start (tryb lokalny)

```powershell
# 1. Środowisko (uv zarządza .venv; --native-tls dla firmowego CA)
uv pip install --native-tls -e .\backend[dev]

# 2. Ingestia surowych danych do kanonicznego store + katalog
$env:PYTHONPATH = "backend"
python -m ecosim.cli ingest

# 3. Serwer API (http://127.0.0.1:8000/docs)
python -m ecosim.cli serve --reload

# 4. Frontend (http://localhost:5173)
cd frontend; npm install; npm run dev
```

Lokalnie aplikacja otwiera się bez logowania. Na serwerze logowanie włącza się, zakładając
konto (`python -m ecosim.cli auth set-user <nazwa> --role admin|tester`) — patrz
`deploy/README.md`.

## Przykładowe zapytania API

```
GET /catalog/scenarios
GET /catalog/tree
GET /timeseries?variable=biomass&freq=annual&scenario=baseline_cumulative&group=Cod%20adult
GET /regions/layers?scenario=ssp1_a002          # obszary referencyjne (ICES, zarządzanie) na siatce modelu
POST /spatial/zonal                             # zmienna z map w obszarach, rok po roku
```

## Status (roadmap)

- [x] Etap 0 — szkielet, kanoniczny schemat, słowniki
- [x] Etap 1 — ingestia szeregów czasowych → Parquet + katalog + API
- [x] Etap 2 — ingestia przestrzenna (`.asc` → COG) + endpointy map
- [x] Etap 3 — framework R (kontrakt, `ecosimkit`, runner, UI analiz)
- [x] Obszary ICES i zarządzania: paczki obszarów, sumy/przecięcia, statystyki w obszarach,
      analizy R na obszarach (plan `docs/Plans and TO_DO lists/26.11_ICES_obszary_PLAN.md`)
- [ ] Etap 4 — hardening na serwer: logowanie (admin/tester) i pliki wdrożenia **zrobione**;
      do zrobienia izolacja skryptów R (do tego czasu R wyłączony na serwerze), kolejka zadań,
      osobne profile użytkowników
