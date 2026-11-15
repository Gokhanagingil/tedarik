"""Doküman yönetimi (ISO 9001 7.5 "Dokümante edilmiş bilgi"). K-020. Bilinçli olarak sade tutuldu.

- Tanımlama (7.5.2): otomatik kod, başlık, tür, süreç, birim, sahip, onaylayan, gizlilik.
- Gözden geçirme ve onay (7.5.2 c): taslak → onayda → yayımlandı. Onaylayan, hazırlayandan farklı olmalıdır
  (dört göz); doküman bir onaylayana atanmışsa yalnızca o kişi veya Yönetici onaylar. Ret gerekçe ister.
- Değişiklik kontrolü (7.5.3.2): her yayın değiştirilemez bir revizyon kaydı (numara, değişiklik özeti, hazırlayan,
  onaylayan, dosya özeti) bırakır. Yayımlanmış doküman değiştirilmek istenirse yeni revizyon taslağı açılır; o
  sürece kadar son yayımlanan revizyon geçerlidir. Geçersiz kılınan doküman yanlışlıkla kullanılmasın diye açıkça
  "geçersiz" görünür ve değiştirilemez.
- Erişim ve koruma (7.5.3.1): dosya içeriği veritabanında; SHA-256 her indirmede doğrulanır.
- Saklama (7.5.3.2): kayıt türündeki dokümanda saklama süresi.
- Yayımda geçerlilik tarihi ve bir sonraki gözden geçirme tarihi (gözden geçirme periyodu) atanır.
"""
import hashlib
import mimetypes
from datetime import date, timedelta

from .. import audit, auth as authz, crud, files
from ..db import one, rows, utcnow
from ..http import API, MAX_UPLOAD_BODY, Raw
from ..schema import Resource, fk

M = "documents"
EDITABLE_WHEN_PUBLISHED = {"owner", "approver", "process_id", "org_unit_id", "confidentiality", "review_period_months",
                           "retention_years", "reference_url"}

DOCUMENTS = Resource("documents", "Dokümanlar", {
    "code": "TEXT NOT NULL UNIQUE", "title": "TEXT NOT NULL", "category": "TEXT NOT NULL DEFAULT 'procedure'",
    "version": "TEXT", "owner": "TEXT", "status": "TEXT NOT NULL DEFAULT 'draft'", "reference_url": "TEXT",
    "approved_by": "TEXT", "approved_on": "DATE", "review_date": "DATE", "description": "TEXT",
    "process_id": fk("processes", False), "org_unit_id": fk("org_units", False), "approver": "TEXT",
    "prepared_by": "TEXT", "current_revision": "INTEGER NOT NULL DEFAULT 0", "effective_date": "DATE",
    "review_period_months": "INTEGER NOT NULL DEFAULT 12", "confidentiality": "TEXT NOT NULL DEFAULT 'internal'",
    "retention_years": "INTEGER", "pending_change": "TEXT", "draft_file_id": "INTEGER",
    "created_at": "TIMESTAMP NOT NULL", "updated_at": "TIMESTAMP"},
    module=M, write="write", code_prefix="DOK", search=("code", "title", "description"),
    readonly=("status", "version", "approved_by", "approved_on", "prepared_by", "current_revision", "effective_date",
              "pending_change", "draft_file_id"),
    enums={"category": ("policy", "procedure", "instruction", "form", "plan", "standard", "guideline",
                        "contract_clause", "record"),
           "status": ("draft", "in_review", "published", "obsolete", "active", "retired"),
           "confidentiality": ("public", "internal", "confidential", "restricted")})

REVISIONS = Resource("document_revisions", "Doküman Revizyonları", {
    "document_id": fk("documents"), "revision": "INTEGER NOT NULL", "change_summary": "TEXT NOT NULL",
    "prepared_by": "TEXT NOT NULL", "approved_by": "TEXT NOT NULL", "approved_at": "TIMESTAMP NOT NULL",
    "effective_date": "DATE NOT NULL", "file_id": "INTEGER", "file_name": "TEXT", "sha256": "TEXT"},
    module=M, unique=(("document_id", "revision"),), api=("list", "get"), search=("change_summary",), immutable=True)

DOC_FILES = Resource("document_files", "Doküman Dosyaları", {
    "document_id": fk("documents"), "file_name": "TEXT NOT NULL", "file_size": "INTEGER NOT NULL",
    "mime_type": "TEXT NOT NULL", "sha256": "TEXT NOT NULL", "uploaded_by": "TEXT NOT NULL",
    "uploaded_at": "TIMESTAMP NOT NULL"},
    module=M, api=("list",), search=("file_name",), immutable=True)
Resource("document_blobs", "Doküman dosya içeriği", {"file_id": fk("document_files"), "content": "BLOB NOT NULL"},
         module=M, unique=(("file_id",),), api=(), search=(), immutable=True)


def _document_rules(db, data, current, principal):
    merged = {**(current or {}), **data}
    if merged.get("review_period_months") is not None and not 1 <= merged["review_period_months"] <= 60:
        raise crud.Invalid("Gözden geçirme periyodu 1–60 ay olmalı")
    if merged.get("retention_years") is not None and not 0 <= merged["retention_years"] <= 100:
        raise crud.Invalid("Saklama süresi 0–100 yıl olmalı")
    if merged.get("category") == "record" and merged.get("retention_years") is None:
        raise crud.Invalid("Kayıt türündeki dokümanda saklama süresi gerekli (ISO 9001 7.5.3.2)")
    if merged.get("reference_url") and not str(merged["reference_url"]).startswith(("https://", "http://")):
        raise crud.Invalid("Referans bağlantısı http:// veya https:// ile başlamalı")
    if current is None:
        data["prepared_by"] = principal.username if principal else "system"
        return
    if current["status"] in ("obsolete", "retired"):
        raise crud.Conflict("Geçersiz kılınan doküman değiştirilemez")
    if current["status"] in ("published", "active", "in_review") and set(data) - EDITABLE_WHEN_PUBLISHED - {"updated_at"}:
        raise crud.Conflict("Yayımlanmış veya onaydaki dokümanın içeriği değiştirilmez; yeni revizyon başlatın")


def _scope(db, record):
    units = {record.get("org_unit_id")}
    if record.get("process_id"):
        process = one(db, "SELECT org_unit_id FROM tdr_processes WHERE id=?", (record["process_id"],))
        units.add(process["org_unit_id"] if process else None)
    return units


DOCUMENTS.before_save = _document_rules
DOCUMENTS.scope = _scope


def _load(c):
    document = crud.get(c.db, DOCUMENTS, c.params["id"])
    authz.check(c.principal, DOCUMENTS, "write")
    crud.check_scope(c.db, DOCUMENTS, c.principal, document)
    return document


def upload(c):
    authz.require_human(c.principal)
    document = _load(c)
    if document["status"] != "draft":
        raise crud.Conflict("Dosya yalnızca taslak dokümana yüklenir; yeni revizyon başlatın")
    filename = c.body.get("file_name") or "dokuman.pdf"
    binary = files.decode(c.body)
    files.valid_file(filename, binary)
    digest = hashlib.sha256(binary).hexdigest()
    mime = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    file_id = c.db.execute("INSERT INTO tdr_document_files (document_id, file_name, file_size, mime_type, sha256, "
                           "uploaded_by, uploaded_at) VALUES (?,?,?,?,?,?,?)",
                           (document["id"], filename, len(binary), mime, digest, c.principal.username, utcnow())).lastrowid
    c.db.execute("INSERT INTO tdr_document_blobs (file_id, content) VALUES (?,?)", (file_id, binary))
    c.db.execute("UPDATE tdr_documents SET draft_file_id=?, updated_at=? WHERE id=?", (file_id, utcnow(), document["id"]))
    audit.log(c.db, c.principal, "UPLOAD", DOCUMENTS.name, document["id"], {"file_id": file_id, "sha256": digest})
    return 201, {"file_id": file_id, "sha256": digest, "file_name": filename, "size": len(binary)}


def download(c):
    authz.check(c.principal, DOCUMENTS, "read")
    authz.require_human(c.principal)
    file = one(c.db, "SELECT * FROM tdr_document_files WHERE id=? AND document_id=?", (c.params["file"], c.params["id"]))
    if not file:
        raise crud.NotFound("Doküman dosyası bulunamadı")
    blob = one(c.db, "SELECT content FROM tdr_document_blobs WHERE file_id=?", (file["id"],))
    content = bytes(blob["content"]) if blob else b""
    if hashlib.sha256(content).hexdigest() != file["sha256"]:
        raise crud.Conflict("Doküman dosyasının bütünlük doğrulaması başarısız")
    audit.log(c.db, c.principal, "DOWNLOAD", DOCUMENTS.name, file["document_id"], {"file_id": file["id"]})
    return Raw(content, "application/octet-stream", file["file_name"])


def transition(c):
    authz.require_human(c.principal)
    document = crud.get(c.db, DOCUMENTS, c.params["id"])
    authz.check(c.principal, DOCUMENTS, "write")
    action, note = c.body.get("action"), (c.body.get("note") or "").strip()
    status, now, today = document["status"], utcnow(), date.today()
    if status == "active":
        status = "published"
    if action == "submit" and status == "draft":
        crud.check_scope(c.db, DOCUMENTS, c.principal, document)
        change = (c.body.get("change_summary") or "").strip()
        if not change:
            raise crud.Invalid("Değişiklik özetini yazın (ne değişti, neden)")
        if not document["draft_file_id"] and not document["reference_url"]:
            raise crud.Invalid("Onaya göndermeden önce dosya yükleyin veya referans bağlantısı girin")
        updates = {"status": "in_review", "pending_change": change[:2000]}
    elif action == "approve" and status == "in_review":
        if c.principal.username == document["prepared_by"]:
            raise crud.Forbidden("Hazırlayan kendi dokümanını onaylayamaz (dört göz)")
        if document["approver"] and c.principal.username != document["approver"] and c.principal.role != "ADMIN":
            raise crud.Forbidden(f"Bu dokümanı atanmış onaylayan ({document['approver']}) veya Yönetici onaylar")
        if not c.principal.can("manage") and c.principal.username != document["approver"]:
            raise crud.Forbidden("Onay yetkiniz yok")
        revision = (document["current_revision"] or 0) + 1
        file = one(c.db, "SELECT * FROM tdr_document_files WHERE id=?", (document["draft_file_id"],)) \
            if document["draft_file_id"] else None
        c.db.execute("INSERT INTO tdr_document_revisions (document_id, revision, change_summary, prepared_by, approved_by, "
                     "approved_at, effective_date, file_id, file_name, sha256) VALUES (?,?,?,?,?,?,?,?,?,?)",
                     (document["id"], revision, document["pending_change"] or "İlk yayın", document["prepared_by"]
                      or document["owner"] or "bilinmiyor", c.principal.username, now, today.isoformat(),
                      file["id"] if file else None, file["file_name"] if file else None, file["sha256"] if file else None))
        months = document["review_period_months"] or 12
        updates = {"status": "published", "current_revision": revision, "version": f"Rev. {revision}",
                   "effective_date": today.isoformat(), "approved_by": c.principal.username,
                   "approved_on": today.isoformat(), "pending_change": None,
                   "review_date": (today + timedelta(days=round(months * 30.44))).isoformat()}
    elif action == "reject" and status == "in_review":
        if not note:
            raise crud.Invalid("Ret gerekçesi gerekli")
        if not c.principal.can("manage") and c.principal.username != document["approver"]:
            raise crud.Forbidden("Ret yetkiniz yok")
        updates = {"status": "draft"}
    elif action == "revise" and status == "published":
        crud.check_scope(c.db, DOCUMENTS, c.principal, document)
        updates = {"status": "draft", "prepared_by": c.principal.username, "draft_file_id": None}
    elif action == "obsolete" and status in ("published", "draft", "in_review"):
        authz.require(c.principal, "manage")
        if not note:
            raise crud.Invalid("Geçersiz kılma gerekçesi gerekli")
        updates = {"status": "obsolete"}
    else:
        raise crud.Conflict("Bu durumda bu işlem yapılamaz")
    sets = ", ".join(f"{k}=?" for k in updates)
    c.db.execute(f"UPDATE tdr_documents SET {sets}, updated_at=? WHERE id=?", (*updates.values(), now, document["id"]))
    audit.log(c.db, c.principal, action.upper(), DOCUMENTS.name, document["id"],
              {"from": status, "to": updates["status"], "note": note or None})
    return context_data(c.db, c.app, document["id"])


def context_data(db, app, document_id):
    document = crud.get(db, DOCUMENTS, document_id)
    document["revisions"] = rows(db, "SELECT * FROM tdr_document_revisions WHERE document_id=? ORDER BY revision DESC",
                                 (document_id,))
    document["files"] = rows(db, "SELECT * FROM tdr_document_files WHERE document_id=? ORDER BY id DESC", (document_id,))
    document["current_file"] = next((r for r in document["revisions"] if r["file_id"]), None)
    document["process"] = one(db, "SELECT id, code, name FROM tdr_processes WHERE id=?", (document["process_id"],)) \
        if document["process_id"] else None
    document["controls"] = rows(db, """SELECT c.id, c.code, c.name FROM tdr_controls c JOIN tdr_control_documents m
        ON m.control_id=c.id WHERE m.document_id=? ORDER BY c.code""", (document_id,)) if app.enabled("grc") else []
    document["clauses"] = rows(db, """SELECT cl.id, cl.code, cl.title, s.code AS standard FROM tdr_clauses cl
        JOIN tdr_document_clauses m ON m.clause_id=cl.id JOIN tdr_standards s ON s.id=cl.standard_id
        WHERE m.document_id=? ORDER BY s.code, cl.code""", (document_id,)) if app.enabled("grc") else []
    document["plans"] = rows(db, "SELECT id, code, title, status FROM tdr_bc_plans WHERE document_id=?", (document_id,)) \
        if app.enabled("continuity") else []
    document["review_overdue"] = bool(document["status"] in ("published", "active") and document["review_date"]
                                      and str(document["review_date"]) < date.today().isoformat())
    return document


def context(c):
    authz.check(c.principal, DOCUMENTS, "read")
    return context_data(c.db, c.app, c.params["id"])


def overview(c):
    authz.check(c.principal, DOCUMENTS, "read")
    today = date.today().isoformat()
    return {
        "by_status": rows(c.db, "SELECT status AS key, COUNT(*) AS count FROM tdr_documents GROUP BY status"),
        "by_category": rows(c.db, "SELECT category AS key, COUNT(*) AS count FROM tdr_documents WHERE status IN "
                                  "('published','active') GROUP BY category"),
        "review_overdue": rows(c.db, "SELECT id, code, title, owner, review_date FROM tdr_documents WHERE status IN "
                                     "('published','active') AND review_date < ? ORDER BY review_date", (today,)),
        "awaiting_approval": rows(c.db, "SELECT id, code, title, prepared_by, approver FROM tdr_documents WHERE "
                                        "status='in_review' ORDER BY updated_at"),
    }


def register(app):
    app.route("POST", API + "/documents/{id}/files", upload, max_body=MAX_UPLOAD_BODY)
    app.route("GET", API + "/documents/{id}/files/{file}", download)
    app.route("POST", API + "/documents/{id}/transition", transition)
    app.route("GET", API + "/documents/{id}/context", context)
    app.route("GET", API + "/documents-overview", overview)
