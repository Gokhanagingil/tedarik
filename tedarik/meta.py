"""Meta veri: arayüz formları, listeler ve Excel başlıkları için tek kaynak (KS GRC `/api/metadata` karşılığı).

Yanıt, oturumdaki kişinin yetkisine göre süzülür: görüntüleyemediği kaynak listelenmez, yazamadığı kaynakta
`can_write` yanlıştır. Arayüz düğmeleri buna göre çizilir; asıl denetim her zaman sunucudadır.
"""
from . import auth as authz
from .http import API
from .labels import choice, field
from .schema import RESOURCES

HIDDEN = {"idempotency"}


def describe(res, principal):
    fields = []
    for name, column in res.columns.items():
        target = next((r.name for r in RESOURCES.values() if r.table == column.ref), None) if column.ref else None
        item = {"name": name, "label": field(name, res.name), "kind": column.kind, "required": name in res.required,
                "readonly": name in res.readonly, "ref": target}
        if name in res.enums:
            item["options"] = [{"value": v, "label": choice(res.name, name, v)} for v in res.enums[name]]
        fields.append(item)
    can_write = principal.role != "MACHINE" and principal.can(res.write)
    return {"name": res.name, "label": res.label, "module": res.module, "api": list(res.api), "write": res.write,
            "can_write": can_write and ("create" in res.api or "update" in res.api),
            "search": list(res.search), "filters": sorted(res.filters), "unit_scoped": res.scope is not None,
            "fields": fields}


def metadata(c):
    resources = {}
    for res in RESOURCES.values():
        if res.name in HIDDEN or not c.app.enabled(res.module) or not res.api:
            continue
        if res.read_roles and c.principal.role not in res.read_roles:
            continue
        resources[res.name] = describe(res, c.principal)
    return {"resources": resources, "modules": list(c.app.config.modules),
            "roles": [{"value": k, "label": v} for k, v in authz.ROLES.items()],
            "auth_mode": c.app.config.auth_mode, "user": c.principal.public(),
            "permissions": {need: c.principal.role != "MACHINE" and c.principal.can(need)
                            for need in authz.NEEDED}}


def register(app):
    app.route("GET", API + "/metadata", metadata)
