#!/usr/bin/env bash
# Update the app on the server from git and restart it.
# Run as the ecosim user in /srv/ecosim/app (sudo is used only for the restart).
set -euo pipefail
cd /srv/ecosim/app

git pull --ff-only

# uv and the Python it installs live under /srv/ecosim, not in a home
# directory: the service can't read homes (ProtectHome in ecosim.service).
export UV_PYTHON_INSTALL_DIR=/srv/ecosim/python
UV="${UV:-$(command -v uv || echo /srv/ecosim/bin/uv)}"

# Backend: Python env with the app's dependencies.
[ -d .venv ] || "$UV" venv --python 3.12 .venv
"$UV" pip install --python .venv/bin/python -e backend

# Frontend: static build served by nginx.
(cd frontend && npm ci && npm run build)

sudo systemctl restart ecosim
sleep 3
curl -fsS http://127.0.0.1:8000/health && echo " -- API up"
