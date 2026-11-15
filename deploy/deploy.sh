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
# Docker yoksa: yalnızca açıkça istendiğinde (TEDARIK_INSTALL_DOCKER=1) Ubuntu paketlerinden kurulur.
if ! command -v docker >/dev/null 2>&1 || ! docker compose version >/dev/null 2>&1; then
  if [ "${TEDARIK_INSTALL_DOCKER:-0}" = 1 ] && command -v apt-get >/dev/null 2>&1; then
    echo "Docker kuruluyor (Ubuntu paketleri: docker.io, docker-compose-v2, docker-buildx)"
    apt-get update -q
    DEBIAN_FRONTEND=noninteractive apt-get install -y -q docker.io docker-compose-v2 docker-buildx
    systemctl enable --now docker
  else
    echo "Docker Engine ve Compose v2 kurulu değil. Kurmak için TEDARIK_INSTALL_DOCKER=1 verin." >&2
    exit 1
  fi
fi
docker compose version

umask 077
mkdir -p "$BASE/secrets" "$BASE/backups"

# Kalıcı kurulum ayarları (ör. alan adı) sunucuda tutulur; sonraki kurulumlar aynı ayarla çalışır.
SETTINGS="$BASE/settings.env"
if [ -n "${TEDARIK_DOMAIN:-}" ]; then
  printf 'TEDARIK_DOMAIN=%s\n' "$TEDARIK_DOMAIN" > "$SETTINGS"
fi
if [ -f "$SETTINGS" ]; then
  . "$SETTINGS"
  export TEDARIK_DOMAIN
fi
if [ -n "${TEDARIK_DOMAIN:-}" ]; then
  case "$TEDARIK_DOMAIN" in *[!a-z0-9.-]*) echo "Geçersiz alan adı: $TEDARIK_DOMAIN" >&2; exit 1;; esac
  export COMPOSE_PROFILES=tls TEDARIK_COOKIE_SECURE=1 TEDARIK_TRUST_PROXY=1
  if command -v ss >/dev/null 2>&1 && ss -ltn "sport = :443" | grep -q LISTEN && \
     ! docker ps --filter label=com.docker.compose.project=$PROJECT --format '{{.Ports}}' 2>/dev/null | grep -q ':443->'; then
    echo "443. port başka bir uygulama tarafından kullanılıyor; TLS ters vekili başlatılamaz" >&2
    exit 1
  fi
fi
# ServiceNow CMDB bağlantısı (isteğe bağlı, K-019): adres ve kullanıcı ayar dosyasında, parola sır dosyasında.
# Parola Git'e ve CI günlüğüne girmez; yönetici sunucuda $BASE/secrets/sn_password dosyasına yazar.
SN_SETTINGS="$BASE/servicenow.env"
if [ -n "${TEDARIK_SN_INSTANCE:-}" ]; then
  case "$TEDARIK_SN_INSTANCE" in https://*) ;; *) echo "TEDARIK_SN_INSTANCE https:// ile başlamalı" >&2; exit 1;; esac
  printf 'TEDARIK_SN_INSTANCE=%s\nTEDARIK_SN_USER=%s\n' "$TEDARIK_SN_INSTANCE" "${TEDARIK_SN_USER:-}" > "$SN_SETTINGS"
fi
if [ -f "$SN_SETTINGS" ]; then
  . "$SN_SETTINGS"
  export TEDARIK_SN_INSTANCE TEDARIK_SN_USER
  # ServiceNow MCP sunucusu (K-021): TEDARIK_SN_MCP_URL ve OAuth için TEDARIK_SN_MCP_TOKEN_URL, TEDARIK_SN_MCP_CLIENT_ID
  # (aynı dosyada); belirteç $BASE/secrets/sn_mcp_token, OAuth istemci sırrı $BASE/secrets/sn_mcp_client_secret dosyasında.
  if [ -n "${TEDARIK_SN_MCP_URL:-}" ]; then
    case "$TEDARIK_SN_MCP_URL" in https://*) ;; *) echo "TEDARIK_SN_MCP_URL https:// ile başlamalı" >&2; exit 1;; esac
    export TEDARIK_SN_MCP_URL
    if [ -n "${TEDARIK_SN_MCP_TOKEN_URL:-}" ]; then
      export TEDARIK_SN_MCP_TOKEN_URL TEDARIK_SN_MCP_CLIENT_ID TEDARIK_SN_MCP_CLIENT_SECRET_FILE=/run/secrets/sn_mcp_client_secret
    else
      export TEDARIK_SN_MCP_TOKEN_FILE=/run/secrets/sn_mcp_token
    fi
  fi
fi
# Kurumsal giriş (Entra ID + MFA, docs/KIMLIK.md): $BASE/entra.env varsa uygulama entra modunda çalışır.
# Dosyada yalnızca gizli olmayan ayarlar durur (TEDARIK_ENTRA_TENANT_ID, TEDARIK_ENTRA_CLIENT_ID,
# TEDARIK_ENTRA_AUTH_CONTEXT); istemci sırrı yalnızca $BASE/secrets/entra_client_secret dosyasındadır.
ENTRA_SETTINGS="$BASE/entra.env"
if [ -f "$ENTRA_SETTINGS" ]; then
  . "$ENTRA_SETTINGS"
  [ -n "${TEDARIK_DOMAIN:-}" ] || { echo "Entra girişi için HTTPS alan adı (TEDARIK_DOMAIN) gerekli" >&2; exit 1; }
  [ -s "$BASE/secrets/entra_client_secret" ] || { echo "Entra istemci sırrı yok: $BASE/secrets/entra_client_secret" >&2; exit 1; }
  TEDARIK_ENTRA_REDIRECT_URI="${TEDARIK_ENTRA_REDIRECT_URI:-https://$TEDARIK_DOMAIN/auth/entra/callback}"
  export TEDARIK_AUTH_MODE=entra TEDARIK_ENTRA_TENANT_ID TEDARIK_ENTRA_CLIENT_ID TEDARIK_ENTRA_AUTH_CONTEXT \
    TEDARIK_ENTRA_REDIRECT_URI TEDARIK_ENTRA_CLIENT_SECRET_FILE=/run/secrets/entra_client_secret
fi
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
for optional in sn_password sn_mcp_token sn_mcp_client_secret entra_client_secret; do   # boş: yapılandırılmadı
  [ -e "$BASE/secrets/$optional" ] || : > "$BASE/secrets/$optional"
done
chown 10001:10001 "$BASE/secrets/database_url" "$BASE/secrets/mcp_api_key" "$BASE/secrets/sn_password" \
  "$BASE/secrets/sn_mcp_token" "$BASE/secrets/sn_mcp_client_secret" "$BASE/secrets/entra_client_secret"
chmod 0400 "$BASE/secrets/"*

# Güncellemeden önce veritabanı yedeği (veritabanı çalışıyorsa).
if $COMPOSE ps --status running --services 2>/dev/null | grep -qx db; then
  sh "$SRC/deploy/backup.sh" pre-deploy
fi

[ "${TEDARIK_SKIP_BUILD:-0}" = 1 ] || $COMPOSE build --pull=false app   # 1: hazır imaj (ör. CI'da derlenip taranmış)
$COMPOSE up -d --wait --wait-timeout 120

# İlk yönetici: geçici parola yalnızca root'un okuyabildiği dosyaya yazılır.
# Entra modunda yönetici Entra uygulama rolüyle (KS.TDR.Admin) gelir; yerel hesap açılmaz.
if [ "${TEDARIK_AUTH_MODE:-local}" = local ]; then
  out=$($COMPOSE exec -T app python -m tedarik.bootstrap create "${TEDARIK_ADMIN:-tdradmin}")
  if [ "$out" != "ACCOUNT_ALREADY_EXISTS" ]; then
    printf '%s\n' "$out" > "$BASE/.first-login"
    chmod 0600 "$BASE/.first-login"
    echo "İlk yönetici oluşturuldu; geçici parola: $BASE/.first-login (yalnızca root okur)"
  fi
else
  echo "Kurumsal giriş (Entra ID) ön denetimi:"
  $COMPOSE exec -T app python -m tedarik.entra_check || echo "UYARI: Entra ön denetimi hata verdi; yukarıdaki maddeleri düzeltin" >&2
fi

# Standart kütüphanesi (K-023): tam metinli paketler her kurulumda kurulur veya güncellenir; kurumun
# uygulanabilirlik kararları, kapsam seçimi ve eşlemeleri korunur.
$COMPOSE exec -T app python -m tedarik.standards_cli install || echo "UYARI: standart kütüphanesi kurulamadı" >&2

# Demo verisi (yalnızca istenirse ve veritabanında demo dışı tedarikçi yoksa). Demo kullanıcıların geçici
# parolaları yalnızca root'un okuyabildiği dosyaya yazılır; CI günlüğüne basılmaz.
if [ "${TEDARIK_SEED_DEMO:-0}" = 1 ] || [ "${TEDARIK_SEED_DEMO:-}" = true ]; then
  demo=$($COMPOSE exec -T app python -m tedarik.demo)
  case "$demo" in
    DEMO_ALREADY_LOADED) echo "Demo verisi zaten yüklü" ;;
    DEMO_SECTIONS_ADDED*) echo "Yüklü demoya yeni bölümler eklendi (${demo#DEMO_SECTIONS_ADDED }); kullanıcı parolaları değişmedi" ;;
    *) (umask 077; printf '%s\n' "$demo" > "$BASE/.demo-users")
       echo "Demo verisi yüklendi; demo kullanıcıların geçici parolaları: $BASE/.demo-users (yalnızca root okur)" ;;
  esac
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
  # Uyum (GRC): portal verisinden iç otomatik kontroller her sabah çalışır (K-015).
  printf '%s\n' "# Tedarik Portalı iç otomatik kontrolleri (deploy.sh yazar)" \
    "43 5 * * * root docker exec tedarik-app-1 python -m tedarik.grc_run >/dev/null 2>&1" \
    > /etc/cron.d/tedarik-grc
  chmod 0644 /etc/cron.d/tedarik-grc
  # CMDB (K-019): ServiceNow yapılandırıldıysa senkron, değilse yalnızca kural değerlendirmesi; her gece.
  printf '%s\n' "# Tedarik Portalı CMDB senkronu ve CI risk kuralları (deploy.sh yazar)" \
    "23 4 * * * root docker exec tedarik-app-1 python -m tedarik.cmdb_sync >/dev/null 2>&1" \
    > /etc/cron.d/tedarik-cmdb
  chmod 0644 /etc/cron.d/tedarik-cmdb
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
if [ -n "${TEDARIK_DOMAIN:-}" ]; then
  echo "Tedarik Portalı çalışıyor: https://$TEDARIK_DOMAIN (sertifika ilk açılışta otomatik alınır). Diğer konteynerler değişmedi."
else
  echo "Tedarik Portalı çalışıyor: http://127.0.0.1:$PORT (yalnızca sunucu içinden). Diğer konteynerler değişmedi."
fi
