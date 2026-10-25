#!/usr/bin/env sh
set -eu
systemctl --user disable --now docs-local.service || true
rm -f "${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user/docs-local.service"
systemctl --user daemon-reload
echo 'Inicialização automática removida.'
