#!/usr/bin/env sh
set -eu
ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
EXECUTABLE="$ROOT/DocsLocal"
if [ ! -x "$EXECUTABLE" ]; then
    echo 'Autostart is available only for a packaged production executable.' >&2
    exit 1
fi
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
ExecStart=$EXECUTABLE
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
EOF
systemctl --user daemon-reload
systemctl --user enable --now docs-local.service
echo 'Production autostart installed.'
