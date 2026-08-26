#!/usr/bin/env bash
set -euo pipefail

lan_ip="${1:-}"
if [[ -z "$lan_ip" || "$lan_ip" == *x* ]]; then
  echo "usage: $0 <LAN-IP>" >&2
  exit 2
fi

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
project_dir="$(dirname -- "$script_dir")"
cert_dir="$project_dir/certs"
mkdir -p "$cert_dir"

openssl req -x509 -newkey rsa:2048 -sha256 -nodes -days 825 \
  -keyout "$cert_dir/lan.key" -out "$cert_dir/lan.crt" \
  -subj "/CN=$lan_ip" -addext "subjectAltName=IP:$lan_ip"
chmod 600 "$cert_dir/lan.key"
echo "Created $cert_dir/lan.crt and $cert_dir/lan.key for $lan_ip"
