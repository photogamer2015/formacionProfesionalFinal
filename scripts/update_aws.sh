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

info() {
    printf '\n==> %s\n' "$1"
}

run_systemctl() {
    if [ "$(id -u)" -eq 0 ]; then
        systemctl "$@"
    else
        sudo systemctl "$@"
    fi
}

cd "$APP_DIR"

if [ "$SKIP_GIT_PULL" != "1" ]; then
    info "Actualizando codigo desde ${GIT_REMOTE}/${GIT_BRANCH}"
    if ! git diff --quiet || ! git diff --cached --quiet; then
        echo "Hay cambios locales sin guardar. Haz commit/stash antes de actualizar." >&2
        exit 1
    fi

    git fetch "$GIT_REMOTE" "$GIT_BRANCH"
    git pull --ff-only "$GIT_REMOTE" "$GIT_BRANCH"
else
    info "Usando el codigo local sin hacer git pull"
fi

if [ ! -x "$VENV_DIR/bin/python" ]; then
    info "Creando entorno virtual"
    "$PYTHON_BIN" -m venv "$VENV_DIR"
fi

info "Instalando dependencias"
"$VENV_DIR/bin/python" -m pip install --upgrade pip
"$VENV_DIR/bin/python" -m pip install -r requirements.txt

info "Validando configuracion de Django"
"$VENV_DIR/bin/python" manage.py check

if [ "$RUN_TESTS" = "1" ]; then
    info "Ejecutando pruebas"
    "$VENV_DIR/bin/python" manage.py test
fi

info "Aplicando migraciones y archivos estaticos"
"$VENV_DIR/bin/python" manage.py migrate --noinput
"$VENV_DIR/bin/python" manage.py collectstatic --noinput

if [ -f "$APP_DIR/.env" ] && grep -Eq '^(SESSION_COOKIE_AGE|SESSION_EXPIRE_AT_BROWSER_CLOSE)=' "$APP_DIR/.env"; then
    echo "Aviso: la sesion persistente ahora se define en core/settings.py."
    echo "Las variables SESSION_COOKIE_AGE y SESSION_EXPIRE_AT_BROWSER_CLOSE del .env ya no cambian el cierre de sesion."
fi

if command -v systemctl >/dev/null 2>&1; then
    if systemctl list-unit-files "${APP_SERVICE}.service" --no-legend | grep -q "${APP_SERVICE}.service"; then
        info "Reiniciando ${APP_SERVICE}.service"
        run_systemctl restart "$APP_SERVICE"
        run_systemctl status "$APP_SERVICE" --no-pager -l
    else
        echo "Servicio ${APP_SERVICE}.service no encontrado; inicia/reinicia gunicorn manualmente."
    fi
else
    echo "systemctl no disponible; inicia/reinicia gunicorn manualmente."
fi

info "Actualizacion terminada"
