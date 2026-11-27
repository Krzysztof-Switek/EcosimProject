# Wdrożenie na serwer (Ubuntu 24.04, nginx, systemd)

Aplikacja na serwerze: nginx serwuje zbudowany frontend (`frontend/dist`) i przekazuje
`/api/` do backendu, który słucha tylko na `127.0.0.1:8000`. Dostęp wyłącznie po
zalogowaniu (`backend/ecosim/core/auth.py`), dwie role:

- **admin** — wszystko, w tym źródła danych, przeglądanie folderów serwera, paczki obszarów;
- **tester** — przeglądanie, liczenie, eksport, zapisywanie obszarów; bez zmian w źródłach
  danych i paczkach (kafelki wyszarzone, API odpowiada 403).

| Plik | Gdzie na serwerze |
|---|---|
| `ecosim.env.example` | `/etc/ecosim/ecosim.env` |
| `ecosim.service` | `/etc/systemd/system/ecosim.service` |
| `nginx-ecosim.conf` | `/etc/nginx/sites-available/ecosim` (+ link w `sites-enabled`) |
| `deploy.sh` | uruchamiany z `/srv/ecosim/app` przy każdej aktualizacji |

## Pierwsza instalacja

```bash
# 1. pakiety systemowe
sudo apt update && sudo apt install -y nginx git curl certbot python3-certbot-nginx
# Node 20+ (tylko do zbudowania frontendu), np. z NodeSource

# 2. użytkownik i katalogi
sudo useradd --system --create-home --shell /bin/bash ecosim
sudo mkdir -p /srv/ecosim/{app,data,profile,python,bin} /etc/ecosim
sudo chown -R ecosim:ecosim /srv/ecosim

#    uv do /srv/ecosim/bin (Python 3.12 pobierze sam do /srv/ecosim/python) --
#    nie do katalogu domowego, bo usługa nie ma dostępu do katalogów domowych
sudo -u ecosim bash -c 'curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR=/srv/ecosim/bin UV_NO_MODIFY_PATH=1 sh'

# 3. kod
sudo -u ecosim git clone <adres repozytorium> /srv/ecosim/app

# 4. konfiguracja
sudo cp /srv/ecosim/app/deploy/ecosim.env.example /etc/ecosim/ecosim.env
sudo cp /srv/ecosim/app/deploy/ecosim.service /etc/systemd/system/
sudo cp /srv/ecosim/app/deploy/nginx-ecosim.conf /etc/nginx/sites-available/ecosim
#    w pliku nginx: ecosim.example.org -> prawdziwa domena
sudo ln -s /etc/nginx/sites-available/ecosim /etc/nginx/sites-enabled/
sudo certbot --nginx -d <domena>

# 5. pozwolenie na restart usługi bez hasła (dla deploy.sh)
echo 'ecosim ALL=(root) NOPASSWD: /bin/systemctl restart ecosim' | sudo tee /etc/sudoers.d/ecosim

# 6. budowa i start
sudo -u ecosim bash -c 'cd /srv/ecosim/app && ./deploy/deploy.sh'
sudo systemctl enable --now ecosim
sudo systemctl reload nginx

# 7. konta (hasło podaje się interaktywnie, min. 10 znaków); najpierw administrator
ecosim_cli() { sudo -u ecosim bash -c "set -a; . /etc/ecosim/ecosim.env; cd /srv/ecosim/app && \
  PYTHONPATH=backend .venv/bin/python -m ecosim.cli $*"; }
ecosim_cli auth set-user admin --role admin
ecosim_cli auth set-user sweden --role tester    # konto(a) testerów
ecosim_cli auth status                           # lista kont

# 8. firewall
sudo ufw allow OpenSSH && sudo ufw allow 'Nginx Full' && sudo ufw enable
```

Dane modelu kopiuje się do `/srv/ecosim/data` (np. `rsync -av --progress <folder> ecosim@serwer:/srv/ecosim/data/`),
a potem wskazuje w aplikacji jako źródło danych.

## Aktualizacja

```bash
sudo -u ecosim bash -c 'cd /srv/ecosim/app && ./deploy/deploy.sh'
```

## Bezpieczeństwo — co jest ustawione

- `ECOSIM_REQUIRE_AUTH=1`: bez `auth.json` aplikacja jest zablokowana, a nie otwarta.
- Hasła tylko jako hash scrypt w `/srv/ecosim/profile/profiles/default/auth.json` (prawa 600).
  Nowe hasło konta (`auth set-user`) albo usunięcie konta (`auth remove-user`) kończy jego sesje.
- Sesja: ciasteczko HttpOnly, SameSite=Strict, Secure (HTTPS), ważne 12 h.
- Limit: 5 nieudanych logowań z jednego adresu na 15 minut.
- `ECOSIM_BROWSE_ROOT`: przeglądarka folderów w aplikacji widzi tylko `/srv/ecosim/data`.
- `ECOSIM_DISABLE_R=1`: analizy R wyłączone (skrypt R działałby z prawami serwera).
- systemd: usługa może pisać tylko do `/srv/ecosim/profile`.
- Wszyscy zalogowani dzielą jeden profil (aktywne źródło danych, zapisane obszary).
