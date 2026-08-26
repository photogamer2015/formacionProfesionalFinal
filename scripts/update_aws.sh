#!/usr/bin/env bash
set -Eeuo pipefail

APP_DIR="${APP_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
VENV_DIR="${VENV_DIR:-$APP_DIR/venv}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
GIT_REMOTE="${GIT_REMOTE:-origin}"
GIT_BRANCH="${GIT_BRANCH:-main}"
APP_SERVICE="${APP_SERVICE:-formacion}"
RUN_TESTS="${RUN_TESTS:-0}"
SKIP_GIT_PULL="${SKIP_GIT_PULL:-0}"

run_systemctl() {
    if [ "$(id -u)" -eq 0 ]; then
        systemctl "$@"
    else
        sudo systemctl "$@"
    fi
}

cd "$APP_DIR"

if [ "$SKIP_GIT_PULL" != "1" ]; then
    if ! git diff --quiet || ! git diff --cached --quiet; then
        echo "Hay cambios locales sin guardar. Haz commit/stash antes de actualizar." >&2
        exit 1
    fi

    git fetch "$GIT_REMOTE" "$GIT_BRANCH"
    git pull --ff-only "$GIT_REMOTE" "$GIT_BRANCH"
fi

if [ ! -x "$VENV_DIR/bin/python" ]; then
    "$PYTHON_BIN" -m venv "$VENV_DIR"
fi

"$VENV_DIR/bin/python" -m pip install --upgrade pip
"$VENV_DIR/bin/python" -m pip install -r requirements.txt

if [ "$RUN_TESTS" = "1" ]; then
    "$VENV_DIR/bin/python" manage.py test
fi

"$VENV_DIR/bin/python" manage.py migrate --noinput
"$VENV_DIR/bin/python" manage.py collectstatic --noinput

if command -v systemctl >/dev/null 2>&1; then
    if systemctl list-unit-files "${APP_SERVICE}.service" --no-legend | grep -q "${APP_SERVICE}.service"; then
        run_systemctl restart "$APP_SERVICE"
        run_systemctl status "$APP_SERVICE" --no-pager -l
    else
        echo "Servicio ${APP_SERVICE}.service no encontrado; inicia/reinicia gunicorn manualmente."
    fi
else
    echo "systemctl no disponible; inicia/reinicia gunicorn manualmente."
fi
