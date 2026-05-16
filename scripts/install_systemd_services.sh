#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
service_name="${SERVICE_NAME:-ai-english-learner}"
app_user="${APP_SERVICE_USER:-$(id -un)}"
app_group="${APP_SERVICE_GROUP:-$(id -gn)}"

usage() {
  cat <<EOF
Usage: $0

Installs systemd units for this checkout.

Environment overrides:
  SERVICE_NAME=<name>          default: ai-english-learner
  APP_SERVICE_USER=<user>      default: current user
  APP_SERVICE_GROUP=<group>    default: current user's primary group
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

require_sudo() {
  if [[ "${EUID:-$(id -u)}" -eq 0 ]]; then
    "$@"
  else
    sudo "$@"
  fi
}

render_template() {
  local template="$1"
  local destination="$2"

  : > "$destination"
  while IFS= read -r line || [[ -n "$line" ]]; do
    line="${line//\{%APP_DIR%\}/$root}"
    line="${line//\{%APP_USER%\}/$app_user}"
    line="${line//\{%APP_GROUP%\}/$app_group}"
    printf '%s\n' "$line" >> "$destination"
  done < "$template"
}

if [[ ! -x "$root/.venv/bin/python" ]]; then
  echo "Missing virtualenv at $root/.venv. Create it and install requirements first:" >&2
  echo "  python3 -m venv .venv" >&2
  echo "  .venv/bin/pip install -r requirements.txt" >&2
  exit 1
fi

tmpdir="$(mktemp -d)"
trap 'rm -rf "$tmpdir"' EXIT

render_template \
  "$root/deploy/systemd/ai-english-learner.service.template" \
  "$tmpdir/$service_name.service"
require_sudo install -m 0644 "$tmpdir/$service_name.service" "/etc/systemd/system/$service_name.service"

require_sudo systemctl daemon-reload
require_sudo systemctl enable "$service_name"

echo "Installed systemd service: $service_name"
echo
echo "Start now:"
echo "  sudo systemctl start $service_name"
echo
echo "Check status/logs:"
echo "  sudo systemctl status $service_name"
echo "  sudo journalctl -u $service_name -f"
