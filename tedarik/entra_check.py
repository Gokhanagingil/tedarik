"""Entra ID (Azure AD) kurumsal giriş ön denetimi: ayarlar, Microsoft uç noktaları ve uygulama kimlik bilgisi.

    TEDARIK_AUTH_MODE=entra ... python -m tedarik.entra_check

Kullanıcı girişi yapmadan şunları doğrular ve sonucu madde madde yazar (sır veya belirteç yazmaz):
1. Ayarlar geçerli mi (kiracı ve istemci GUID, tam HTTPS dönüş adresi, kimlik doğrulama bağlamı c1–c99, tek sır).
2. Kiracının OpenID yapılandırması sunucudan erişilebilir mi; issuer, yetkilendirme ve belirteç uç noktaları
   uygulamanın kullandıklarıyla aynı mı; imza anahtarları (JWKS) alınabiliyor mu.
3. İstemci kimliği ve sırrı geçerli mi (istemci kimlik bilgisi akışıyla belirteç alınabiliyor mu; belirteç atılır).
MFA'nın gerçekten istenmesi kullanıcı girişinde Koşullu Erişim ilkesiyle sağlanır; uygulama kimlik belirtecinde
`acrs` talebinde yapılandırılmış bağlam yoksa girişi reddeder (vendor/entra_auth.py). Bu denetim o adımı taklit
edemez; çıktıdaki kontrol listesi Entra yöneticisinin doğrulaması gereken ayarları sıralar.
"""
import json
import sys
import urllib.error
import urllib.parse
import urllib.request

from .auth import ENTRA_ROLES
from .config import Config

AUTHORITY = "https://login.microsoftonline.com"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None


def _get_json(url, opener, data=None, timeout=8):
    request = urllib.request.Request(url, data=data, headers={"Accept": "application/json"} | (
        {"Content-Type": "application/x-www-form-urlencoded"} if data else {}))
    with opener.open(request, timeout=timeout) as response:
        raw = response.read(262145)
    if len(raw) > 262144:
        raise ValueError("yanıt çok büyük")
    return json.loads(raw)


def check(config, opener=None):
    """[(durum, başlık, açıklama)] döner; durum: ok | fail | info."""
    from .session import entra_provider
    opener = opener or urllib.request.build_opener(_NoRedirect)
    out = []
    if config.auth_mode != "entra":
        return [("fail", "Mod", "TEDARIK_AUTH_MODE=entra değil; Entra ayarları kullanılmıyor")]
    try:
        provider = entra_provider(config)
    except (ValueError, RuntimeError, OSError) as exc:
        return [("fail", "Ayarlar", f"Geçersiz veya eksik Entra ayarı: {exc}")]
    cfg = provider.config
    out.append(("ok", "Ayarlar", f"kiracı {cfg.tenant}, istemci {cfg.client}, bağlam {cfg.context}, "
                                 f"dönüş adresi {cfg.redirect}"))
    try:
        meta = _get_json(f"{AUTHORITY}/{cfg.tenant}/v2.0/.well-known/openid-configuration", opener)
        same = (meta.get("issuer") == cfg.issuer and meta.get("authorization_endpoint") == f"{cfg.endpoint}/authorize"
                and meta.get("token_endpoint") == f"{cfg.endpoint}/token")
        out.append(("ok" if same else "fail", "OpenID yapılandırması",
                    "issuer ve uç noktalar uygulamanınkiyle aynı" if same else
                    f"beklenmeyen değerler: issuer={meta.get('issuer')}"))
        keys = _get_json(meta.get("jwks_uri") or f"{AUTHORITY}/{cfg.tenant}/discovery/v2.0/keys", opener).get("keys", [])
        rsa = [k for k in keys if k.get("kty") == "RSA" and k.get("kid")]
        out.append(("ok" if rsa else "fail", "İmza anahtarları (JWKS)", f"{len(rsa)} RSA anahtarı alındı"))
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        out.append(("fail", "Microsoft uç noktaları", f"login.microsoftonline.com erişilemedi: {exc}. Sunucunun "
                                                       "dışarıya HTTPS (443) çıkışını denetleyin"))
        return out
    form = urllib.parse.urlencode({"grant_type": "client_credentials", "client_id": cfg.client,
                                   "client_secret": cfg.secret, "scope": "https://graph.microsoft.com/.default"}).encode()
    try:
        token = _get_json(f"{cfg.endpoint}/token", opener, data=form)
        out.append(("ok" if token.get("access_token") else "fail", "İstemci kimlik bilgisi",
                    "istemci kimliği ve sır geçerli (alınan belirteç kullanılmadan atıldı)"))
    except urllib.error.HTTPError as exc:
        try:
            body = json.loads(exc.read(65537) or b"{}")
        except ValueError:
            body = {}
        codes = body.get("error_codes") or []
        reason = {7000215: "istemci sırrı geçersiz", 7000222: "istemci sırrının süresi dolmuş",
                  700016: "uygulama bu kiracıda bulunamadı (istemci kimliği veya kiracı yanlış)",
                  90002: "kiracı bulunamadı"}.get(codes[0] if codes else None, body.get("error") or f"HTTP {exc.code}")
        out.append(("fail", "İstemci kimlik bilgisi", reason))
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        out.append(("fail", "İstemci kimlik bilgisi", f"belirteç uç noktasına erişilemedi: {exc}"))
    roles = ", ".join(sorted(ENTRA_ROLES))
    for item in (f"Uygulama kaydında dönüş adresi karakter karakter: {cfg.redirect}",
                 f"Uygulama rolleri tanımlı ve kullanıcılara/gruplara atanmış: {roles}",
                 "Enterprise application → Assignment required = Yes",
                 f"Yayımlanmış kimlik doğrulama bağlamı {cfg.context} ve onu hedefleyen, MFA isteyen Koşullu Erişim ilkesi "
                 "(ilk denemede yalnızca test grubuna, 'Report-only' değil 'On')",
                 "Token configuration → ID token isteğe bağlı talebi: acrs",
                 "İlk gerçek girişte MFA istendiğini ve rolün doğru geldiğini bir test kullanıcısıyla doğrulayın"):
        out.append(("info", "Entra yöneticisi denetimi", item))
    return out


def main():
    results = check(Config())
    for status, title, detail in results:
        print({"ok": "UYGUN ", "fail": "HATA  ", "info": "DENETLE"}[status], f"{title}: {detail}")
    if any(status == "fail" for status, _, _ in results):
        sys.exit(1)


if __name__ == "__main__":
    main()
