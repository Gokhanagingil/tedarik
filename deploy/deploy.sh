#!/bin/sh
# Tedarik Portalı sunucu kurulumu ve güncellemesi. Sunucuda root (veya sudo) ile, kaynak klasörünün kökünden:
#   sh deploy/deploy.sh
# Yalıtım kuralları: yalnızca "tedarik" compose projesine dokunulur; başka konteyner, ağ, volume veya ters vekil
# ayarı değiştirilmez; sunucu genelinde prune veya "down -v" yapılmaz. Başlamadan önce ve sonra diğer
# konteynerlerin kimliği ve başlama zamanı karşılaştırılır; fark varsa betik hata verir.
set -eu
BASE=${TEDARIK_BASE:-/opt/tedarik}
PROJECT=tedarik
PORT=${TEDARIK_PORT:-18090}
SRC=$(cd "$(dirname "$0")/.." && pwd)
COMPOSE="docker compose -p $PROJECT -f $SRC/deploy/compose.yaml"
export TEDARIK_SECRETS="$BASE/secrets" TEDARIK_PORT="$PORT" TEDARIK_RELEASE="${TEDARIK_RELEASE:-$(date -u +%Y%m%d%H%M%S)}"
umask 077
mkdir -p "$BASE/secrets" "$BASE/backups"
chmod 0700 "$BASE" "$BASE/secrets" "$BASE/backups"

others() {   # bu projeye ait olmayan konteynerler: kimlik, ad, başlama zamanı
  docker ps -aq | while read -r id; do
    docker inspect --format '{{.Id}} {{.Name}} {{.State.StartedAt}} {{index .Config.Labels "com.docker.compose.project"}}' "$id"
  done | awk -v p="$PROJECT" '$4 != p {print $1, $2, $3}' | sort
}
others > "$BASE/.others-before"

# Port denetimi: 127.0.0.1:$PORT başka bir süreçte ise dur (bu projenin kendi konteyneri hariç).
if command -v ss >/dev/null 2>&1 && ss -ltn "sport = :$PORT" | grep -q LISTEN; then
  if ! $COMPOSE ps --format '{{.Ports}}' 2>/dev/null | grep -q "127.0.0.1:$PORT->"; then
    echo "127.0.0.1:$PORT başka bir uygulama tarafından kullanılıyor; TEDARIK_PORT ile başka port seçin" >&2
    exit 1
  fi
fi

# Sırlar yalnızca bir kez üretilir ve sunucuda kalır (Git'e, CI günlüğüne girmez).
secret() { [ -s "$BASE/secrets/$1" ] || head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n' > "$BASE/secrets/$1"; }
secret db_password
secret mcp_api_key
printf 'postgresql://tedarik:%s@db:5432/tedarik' "$(cat "$BASE/secrets/db_password")" > "$BASE/secrets/database_url"
chown 70:70 "$BASE/secrets/db_password"                     # postgres (alpine) kullanıcısı
chown 10001:10001 "$BASE/secrets/database_url" "$BASE/secrets/mcp_api_key"
chmod 0400 "$BASE/secrets/"*

# Güncellemeden önce veritabanı yedeği (veritabanı çalışıyorsa).
if $COMPOSE ps --status running --services 2>/dev/null | grep -qx db; then
  sh "$SRC/deploy/backup.sh" pre-deploy
fi

[ "${TEDARIK_SKIP_BUILD:-0}" = 1 ] || $COMPOSE build --pull=false app   # 1: hazır imaj (ör. CI'da derlenip taranmış)
$COMPOSE up -d --wait --wait-timeout 120

# İlk yönetici: geçici parola yalnızca root'un okuyabildiği dosyaya yazılır.
out=$($COMPOSE exec -T app python -m tedarik.bootstrap create "${TEDARIK_ADMIN:-tdradmin}")
if [ "$out" != "ACCOUNT_ALREADY_EXISTS" ]; then
  printf '%s\n' "$out" > "$BASE/.first-login"
  chmod 0600 "$BASE/.first-login"
  echo "İlk yönetici oluşturuldu; geçici parola: $BASE/.first-login (yalnızca root okur)"
fi

status=$(docker run --rm --network host python:3.12-alpine@sha256:213242b537a1c166a0c53e903461fc18d5518e7196c93dbecda452660a848918 \
  python -c "import urllib.request,urllib.error
try: urllib.request.urlopen('http://127.0.0.1:$PORT/api/health', timeout=5); print(200)
except urllib.error.HTTPError as e: print(e.code)" 2>/dev/null || true)
[ "$status" = "401" ] || { echo "Sağlık denetimi beklenmedik sonuç verdi: $status" >&2; exit 1; }

# Günlük yedek (yalnızca bu uygulamaya ait cron dosyası). Kapatmak için TEDARIK_BACKUP_CRON=0.
if [ "${TEDARIK_BACKUP_CRON:-1}" = 1 ] && [ -d /etc/cron.d ] && [ -e "$BASE/current" ]; then
  printf '%s\n' "# Tedarik Portalı günlük PostgreSQL yedeği (deploy.sh yazar)" \
    "17 2 * * * root TEDARIK_BASE=$BASE sh $BASE/current/deploy/backup.sh daily >/dev/null 2>&1" > /etc/cron.d/tedarik-backup
  chmod 0644 /etc/cron.d/tedarik-backup
fi

# Eski sürüm klasörleri (yalnızca bu uygulamanınkiler): son 5 tutulur.
if [ -d "$BASE/releases" ]; then
  ls -1dt "$BASE/releases"/* 2>/dev/null | tail -n +6 | while read -r old; do rm -rf "$old"; done
fi

others > "$BASE/.others-after"
if ! cmp -s "$BASE/.others-before" "$BASE/.others-after"; then
  echo "UYARI: diğer konteynerlerde değişiklik görüldü:" >&2
  diff "$BASE/.others-before" "$BASE/.others-after" >&2 || true
  exit 1
fi
echo "Tedarik Portalı çalışıyor: http://127.0.0.1:$PORT (yalnızca sunucu içinden). Diğer konteynerler değişmedi."
