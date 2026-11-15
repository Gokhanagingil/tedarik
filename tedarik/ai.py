"""Yapay zekâ yardımı, insan onaylı (K-025).

Her öneri iki katmanlıdır: kural tabanlı sonuç her zaman üretilir; Yönetim → Entegrasyonlar'da Claude API etkin ve
`anthropic` paketi kuruluysa model önerisi eklenir. Öneri hiçbir zaman kendiliğinden uygulanmaz: arayüz öneriyi
gösterir, kullanıcı "Uygula" derse normal güncelleme uç noktası çağrılır (yetki, kural ve denetim izi aynen işler).

Veri en aza indirilir: yalnızca önerinin gerektirdiği alanlar gönderilir; kişi adları (sahip, onaylayan), kısıtlı kanıt
ve dosya içerikleri gönderilmez. Her model çağrısı denetim izine yazılır (içerik değil, tür ve kayıt).

Claude çağrısı resmî SDK ile yapılır (`anthropic`); paket requirements.txt'e eklenmedi (CLAUDE.md: yeni bağımlılık
onay ister). Paket yoksa kural tabanlı öneriler çalışır ve Entegrasyonlar ekranı durumu gösterir.
"""
import json
import re

from . import audit, crud
from .db import fold, rows
from .schema import RESOURCES

FALLBACK_MODELS = {"claude-opus-5-5", "claude-sonnet-5-5"}       # sunucu tarafı ret yedeği desteklenen modeller
VAGUE = ("sorun", "problem", "risk var", "olabilir", "yetersiz", "eksik", "zayif", "kotu", "genel", "cesitli", "bazi")


class AiUnavailable(RuntimeError):
    pass


# ------------------------------------------------------------------ Claude bağlantısı

def _sdk():
    try:
        import anthropic
        return anthropic
    except ImportError:
        raise AiUnavailable("anthropic paketi kurulu değil (kurulum onayı bekleniyor); kural tabanlı öneri gösteriliyor") \
            from None


def _client(db, config):
    from .modules.integrations import enabled, secret
    if not enabled(db, "ai"):
        raise AiUnavailable("Yapay zekâ yardımı kapalı (Yönetim → Entegrasyonlar)")
    anthropic = _sdk()
    key = secret(db, config, "ai", "api_key")
    if not key:
        raise AiUnavailable("Claude API anahtarı girilmemiş")
    base = config.env.get("TEDARIK_AI_BASE_URL") or None        # kurumsal ağ geçidi veya sınama sunucusu
    return anthropic, anthropic.Anthropic(api_key=key, base_url=base, timeout=90.0, max_retries=2)


def _error(anthropic, exc):
    if isinstance(exc, anthropic.AuthenticationError):
        return "API anahtarı geçersiz"
    if isinstance(exc, anthropic.PermissionDeniedError):
        return "API anahtarının bu işleme yetkisi yok"
    if isinstance(exc, anthropic.NotFoundError):
        return "Model veya uç nokta bulunamadı"
    if isinstance(exc, anthropic.RateLimitError):
        return "Hız sınırına takıldı; biraz sonra yeniden deneyin"
    if isinstance(exc, anthropic.APIStatusError):
        return f"Claude API hatası ({exc.status_code})"
    if isinstance(exc, anthropic.APIConnectionError):
        return "Claude API'ye bağlanılamadı"
    return type(exc).__name__


def ask(db, config, principal, purpose, system, prompt, schema, object_type=None, object_id=None):
    """Yapılandırılmış (JSON şemalı) tek çağrı. Dönüş: sözlük. Hata: AiUnavailable."""
    from .modules.integrations import settings
    anthropic, client = _client(db, config)
    s = settings(db, "ai")
    model = s.get("model") or "claude-opus-5-5"
    params = {"model": model, "max_tokens": 16000, "system": system,
              "messages": [{"role": "user", "content": prompt}],
              "output_config": {"effort": s.get("effort") or "medium",
                                "format": {"type": "json_schema", "schema": schema}}}
    try:
        if model in FALLBACK_MODELS:      # ret durumunda sunucu tarafı yedek model (varsayılan yönlendirme)
            response = client.beta.messages.create(betas=["server-side-fallback-2026-07-01"], fallbacks="default",
                                                   **params)
        else:
            response = client.messages.create(**params)
    except anthropic.APIError as exc:
        raise AiUnavailable(_error(anthropic, exc)) from None
    audit.log(db, principal, "AI", object_type or "ai", object_id, {"purpose": purpose, "model": response.model})
    if response.stop_reason == "refusal":
        raise AiUnavailable("Model bu isteği yanıtlamadı")
    if response.stop_reason == "max_tokens":
        raise AiUnavailable("Model yanıtı tamamlanamadı")
    text = next((b.text for b in response.content if b.type == "text"), "")
    try:
        return json.loads(text)
    except ValueError:
        raise AiUnavailable("Model yanıtı okunamadı") from None


def test_connection(db, config):
    from .modules.integrations import settings
    try:
        anthropic, client = _client(db, config)
    except AiUnavailable as exc:
        return [("fail", "Yapay zekâ", str(exc))]
    model = settings(db, "ai").get("model") or "claude-opus-5-5"
    try:
        info = client.models.retrieve(model)            # ücretsiz; anahtarı ve modele erişimi doğrular
    except anthropic.APIError as exc:
        return [("fail", "Claude API", _error(anthropic, exc))]
    return [("ok", "Claude API", f"anahtar geçerli; model {getattr(info, 'display_name', model)} erişilebilir")]


def _run(db, config, principal, rules, call):
    """Kural tabanlı sonucu döndürür; yapay zekâ kullanılabiliyorsa model önerisini ekler."""
    out = {"rules": rules, "ai": None, "ai_note": None}
    try:
        out["ai"] = call()
    except AiUnavailable as exc:
        out["ai_note"] = str(exc)
    return out


# ------------------------------------------------------------------ risk ifadesi kalite denetimi

RISK_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["score", "issues", "cause", "risk_event",
                                                                               "consequence"],
               "properties": {"score": {"type": "integer"}, "issues": {"type": "array", "items": {"type": "string"}},
                              "cause": {"type": "string"}, "risk_event": {"type": "string"},
                              "consequence": {"type": "string"}}}


def risk_rules(risk):
    issues, score = [], 100
    parts = {"cause": "Neden", "risk_event": "Risk olayı", "consequence": "İş etkisi"}
    for key, label in parts.items():
        text = (risk.get(key) or "").strip()
        if not text:
            issues.append(f"{label} boş: risk ifadesi neden → olay → etki yapısında olmalı (ISO 31000 6.4.2).")
            score -= 25
        elif len(text.split()) < 4:
            issues.append(f"{label} çok kısa; ölçülebilir ve somut yazın.")
            score -= 10
    title = fold(risk.get("title") or "")
    if any(v in title for v in VAGUE) and len(title.split()) < 6:
        issues.append("Başlık genel ifadeler içeriyor; olayı somutlaştırın (ne olur, neyi etkiler).")
        score -= 10
    consequence = fold(risk.get("consequence") or "")
    if consequence and not re.search(r"\d|tl|gun|saat|musteri|ceza|kayip|kesinti|itibar|sozlesme", consequence):
        issues.append("Etki ölçülebilir değil: tutar, süre, müşteri sayısı veya düzenleyici sonuç ekleyin.")
        score -= 10
    if risk.get("cause") and risk.get("risk_event") and fold(risk["cause"]) == fold(risk["risk_event"]):
        issues.append("Neden ile olay aynı; neden olayı tetikleyen koşul olmalı.")
        score -= 15
    if not risk.get("process_id"):
        issues.append("Risk bir sürece bağlı değil; sahiplik ve kontrol eşlemesi için süreç seçin.")
        score -= 5
    return {"score": max(score, 0), "issues": issues or ["Belirgin bir eksik bulunmadı."],
            "template": "[Neden] nedeniyle [olay] gerçekleşebilir; bu durum [ölçülebilir etki] sonucunu doğurur."}


def risk_quality(db, config, principal, risk_id):
    risk = crud.get(db, RESOURCES["supplier_risks"], risk_id)
    rules = risk_rules(risk)
    payload = {k: risk.get(k) for k in ("title", "category", "risk_type", "cause", "risk_event", "consequence",
                                        "impact_area", "likelihood", "impact")}
    return _run(db, config, principal, rules, lambda: ask(
        db, config, principal, "risk_quality",
        "Sen ISO 31000 uygulayan deneyimli bir kurumsal risk uzmanısın. Risk ifadesinin kalitesini değerlendir: "
        "neden–olay–etki ayrımı, somutluk, ölçülebilir etki, kontrol edilebilirlik. Türkçe yaz. Uydurma rakam verme; "
        "ölçü gerekiyorsa köşeli parantezle yer tutucu bırak.",
        "Aşağıdaki risk kaydını değerlendir; 0-100 kalite puanı, eksikler ve iyileştirilmiş neden/olay/etki öner.\n"
        + json.dumps(payload, ensure_ascii=False, default=str), RISK_SCHEMA, "supplier_risks", risk_id))


# ------------------------------------------------------------------ kanıt → kontrol eşleme önerisi

EVIDENCE_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["matches"],
                   "properties": {"matches": {"type": "array", "items": {
                       "type": "object", "additionalProperties": False, "required": ["control_id", "reason"],
                       "properties": {"control_id": {"type": "integer"}, "reason": {"type": "string"}}}}}}


def evidence_controls(db, config, principal, evidence_id):
    from .modules.grc import EVIDENCE, evidence_visible
    from .modules.grc_library import _cos, _vector, _vectors
    evidence = crud.get(db, EVIDENCE, evidence_id)
    if not evidence_visible(principal, evidence):
        raise crud.NotFound("Kanıt bulunamadı")
    controls = rows(db, "SELECT id, code, name, description, method FROM tdr_controls WHERE active=1")
    linked = {r["control_id"] for r in rows(db, "SELECT control_id FROM tdr_evidence_controls WHERE evidence_id=?",
                                            (evidence_id,))}
    candidates = [k for k in controls if k["id"] not in linked]
    docs = [" ".join(filter(None, [k["name"], k["name"], k.get("description"), k.get("method")])) for k in candidates]
    if not candidates:
        return {"rules": [], "ai": None, "ai_note": "Bağlanabilecek aktif kontrol yok"}
    vectors, idf = _vectors(docs)
    source = _vector(" ".join(filter(None, [evidence["title"], evidence["title"], evidence.get("description"),
                                            evidence.get("file_name")])), idf)
    scored = sorted(((round(_cos(source, v), 3), k) for v, k in zip(vectors, candidates)), key=lambda x: -x[0])
    rules = [{"control_id": k["id"], "code": k["code"], "name": k["name"], "score": s} for s, k in scored[:6] if s >= 0.08]
    shortlist = [k for _s, k in scored[:25]]
    restricted = evidence.get("confidentiality") == "restricted"

    def call():
        if restricted:
            raise AiUnavailable("Kısıtlı kanıt yapay zekâya gönderilmez")
        result = ask(db, config, principal, "evidence_controls",
                     "Sen bir BT denetçisisin. Bir kanıtın hangi kontrollerin etkinliğini gösterdiğine karar ver. "
                     "Yalnızca verilen listeden seç; emin değilsen seçme. Gerekçeyi Türkçe ve tek cümle yaz.",
                     "Kanıt:\n" + json.dumps({"başlık": evidence["title"], "açıklama": evidence.get("description"),
                                              "dosya": evidence.get("file_name")}, ensure_ascii=False)
                     + "\n\nAday kontroller:\n" + json.dumps([{"control_id": k["id"], "kod": k["code"], "ad": k["name"],
                                                               "açıklama": (k.get("description") or "")[:300]}
                                                              for k in shortlist], ensure_ascii=False),
                     EVIDENCE_SCHEMA, "evidence", evidence_id)
        names = {k["id"]: k for k in shortlist}
        return [{"control_id": m["control_id"], "code": names[m["control_id"]]["code"],
                 "name": names[m["control_id"]]["name"], "reason": m["reason"]}
                for m in result.get("matches", []) if m.get("control_id") in names][:6]
    return _run(db, config, principal, rules, call)


# ------------------------------------------------------------------ denetim raporu taslağı

REPORT_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["summary", "key_messages"],
                 "properties": {"summary": {"type": "string"},
                                "key_messages": {"type": "array", "items": {"type": "string"}}}}


def report_rules(report):
    a, s = report["audit"], report["summary"]
    sev = s.get("findings_by_severity", {})
    parts = [f"{a['name']} denetimi {s['standards']} standart ve {s['clauses']} madde kapsamında, {s['tests']} kontrol "
             f"test edilerek yürütülmüştür."]
    if s["tests"]:
        parts.append(f"Test edilen kontrollerin {s['pass']} tanesi başarılı, {s['fail']} tanesi başarısız; "
                     f"{s['untested']} kontrol test edilmemiştir.")
    if s["findings"]:
        parts.append(f"Toplam {s['findings']} bulgu tespit edilmiştir (kritik {sev.get('critical', 0)}, yüksek "
                     f"{sev.get('high', 0)}, orta {sev.get('medium', 0)}, düşük {sev.get('low', 0)}).")
    else:
        parts.append("Bulgu tespit edilmemiştir.")
    if s.get("responses_pending"):
        parts.append(f"{s['responses_pending']} bulgu için yönetim yanıtı beklenmektedir.")
    if a.get("opinion"):
        parts.append(f"Genel görüş: {a['opinion_label']}.")
    return {"summary": " ".join(parts)}


def report_draft(db, config, principal, audit_id, report):
    rules = report_rules(report)
    payload = {"denetim": {k: report["audit"].get(k) for k in ("name", "kind_label", "audit_objective", "scope",
                                                                "opinion_label", "conclusion")},
               "özet": report["summary"],
               "bulgular": [{k: f.get(k) for k in ("code", "title", "severity", "status", "root_cause",
                                                   "response_status", "clauses")} for f in report["findings"][:40]]}
    return _run(db, config, principal, rules, lambda: ask(
        db, config, principal, "audit_report",
        "Sen IIA standartlarına göre çalışan kıdemli bir iç denetçisin. Denetim sonuçlarından yönetim kurulu için kısa, "
        "nesnel bir yönetici özeti yaz. Türkçe, resmi dil. Verilmeyen bilgi ekleme; kişi adı kullanma.",
        "Denetim verisi:\n" + json.dumps(payload, ensure_ascii=False, default=str), REPORT_SCHEMA, "audits", audit_id))
