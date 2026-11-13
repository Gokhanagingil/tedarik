#!/bin/sh
# PostgreSQL yedeği (pg_dump, özel biçim) /opt/tedarik/backups altına; 14 günden eski yedekler silinir.
#   sh deploy/backup.sh [etiket]
# Geri yükleme (yeni ve boş bir veritabanına): docs/DAGITIM.md, "Geri yükleme".
set -eu
BASE=${TEDARIK_BASE:-/opt/tedarik}
SRC=$(cd "$(dirname "$0")/.." && pwd)
umask 077
mkdir -p "$BASE/backups"
name="$BASE/backups/tedarik-$(date -u +%Y%m%dT%H%M%SZ)${1:+-$1}.dump"
TEDARIK_SECRETS="$BASE/secrets" docker compose -p tedarik -f "$SRC/deploy/compose.yaml" exec -T db \
  pg_dump -U tedarik -d tedarik -Fc --no-owner > "$name.part"
[ -s "$name.part" ] || { rm -f "$name.part"; echo "Yedek boş; iptal" >&2; exit 1; }
mv "$name.part" "$name"
sha256sum "$name" > "$name.sha256"
find "$BASE/backups" -name 'tedarik-*.dump*' -mtime +14 -delete
echo "$name"
