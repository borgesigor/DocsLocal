#!/usr/bin/env sh
set -eu
ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
UNIT_ROOT="$(systemd-escape --path -- "$ROOT")"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
mkdir -p "$UNIT_DIR"
cat > "$UNIT_DIR/docs-local.service" <<EOF
[Unit]
Description=Docs Local Markdown server
After=default.target

[Service]
Type=simple
WorkingDirectory=$UNIT_ROOT
ExecStart=$UNIT_ROOT/.venv/bin/python -m app.main
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
EOF
systemctl --user daemon-reload
systemctl --user enable --now docs-local.service
echo 'Inicialização automática instalada para este usuário.'
