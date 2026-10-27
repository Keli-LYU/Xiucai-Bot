#!/usr/bin/env bash
set -euo pipefail
umask 027

ROOT=/opt/qq-bot
PHASE=${1:?prepare or activate}
RELEASE=${2:?release identifier required}
[[ "$RELEASE" =~ ^[0-9]{8}T[0-9]{6}Z$ ]] || exit 2
[[ ! -L "$ROOT" && "$(realpath -m "$ROOT")" == /opt/qq-bot ]] || exit 2
APP="$ROOT/releases/$RELEASE"
ARCHIVE="$ROOT/incoming/qq-bot-$RELEASE.tar.gz"
ENV_FILE="$ROOT/incoming/qq-bot-$RELEASE.env"

if [[ "$PHASE" == prepare ]]; then
    if id qqbot >/dev/null 2>&1; then
        [[ "$(getent passwd qqbot | cut -d: -f6)" == "$ROOT" ]] || {
            echo 'Existing qqbot account has a different home; refusing to reuse.' >&2
            exit 1
        }
    else
        useradd --system --user-group --home-dir "$ROOT" --shell /usr/sbin/nologin qqbot
    fi
    install -d -m 0755 "$ROOT" "$ROOT/releases" "$ROOT/admin"
    install -d -m 0750 -o root -g qqbot "$ROOT/shared"
    install -d -m 0700 -o qqbot -g qqbot "$ROOT/shared/.cache"
    [[ ! -e "$APP" ]] || { echo 'Release already exists.' >&2; exit 1; }
    mkdir -m 0750 "$APP"
    tar -xzf "$ARCHIVE" -C "$APP" --no-same-owner --no-same-permissions
    ln -s "$ROOT/shared/.env" "$APP/.env"
    ln -s "$ROOT/shared/.cache" "$APP/.cache"
    if [[ -f "$APP/seed/markdown-images.json" && ! -e "$ROOT/shared/.cache/markdown-images.json" ]]; then
        install -m 0600 -o qqbot -g qqbot "$APP/seed/markdown-images.json" "$ROOT/shared/.cache/markdown-images.json"
    fi
    python3 -m venv "$APP/.venv"
    "$APP/.venv/bin/python" -m pip install --timeout 30 --retries 2 -r "$APP/requirements.txt"
    chown -R root:qqbot "$APP"
    chmod -R g+rX "$APP"
    cd "$APP"
    runuser -u qqbot -- "$APP/.venv/bin/python" -m unittest discover -s tests -v
    "$APP/.venv/bin/python" -m compileall -q "$APP"/*.py
    echo "PREPARED $RELEASE"
elif [[ "$PHASE" == activate ]]; then
    [[ -x "$APP/.venv/bin/python" && -f "$ENV_FILE" ]] || exit 1
    if [[ -f "$ROOT/shared/.env" ]]; then
        cp -p "$ROOT/shared/.env" "$ROOT/admin/env-before-$RELEASE"
    fi
    install -m 0640 -o root -g qqbot "$ENV_FILE" "$ROOT/shared/.env"
    if [[ -L "$ROOT/current" ]]; then
        readlink "$ROOT/current" > "$ROOT/admin/previous-$RELEASE"
    fi
    ln -s "$APP" "$ROOT/current.next"
    mv -Tf "$ROOT/current.next" "$ROOT/current"
    install -m 0644 "$APP/deploy/qq-bot.service" /etc/systemd/system/qq-bot.service
    systemd-analyze verify /etc/systemd/system/qq-bot.service
    systemctl daemon-reload
    systemctl enable qq-bot.service
    systemctl restart qq-bot.service
    systemctl is-enabled qq-bot.service
    systemctl is-active qq-bot.service
    echo "ACTIVATED $RELEASE"
else
    echo 'Unknown phase.' >&2
    exit 2
fi
