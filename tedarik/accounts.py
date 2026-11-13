"""Tedarik rolleri ve birim kapsamı (K-013). Kullanıcı tablosu KS GRC ile ortaktır (`users`); tedarike özgü
yetki bilgisi `tdr_` önekli tablolardadır ve KS GRC'nin `roles`/`user_roles` tablolarına yazılmaz.

- `tdr_user_roles`: yalnızca `local` modunda rolü belirler (kullanıcı başına bir rol). `entra` modunda rol
  Entra uygulama rolünden gelir ve bu tablo kullanılmaz.
- `tdr_user_units`: Birim Kullanıcısının yazabildiği birimler; iki modda da geçerlidir.
"""
from .schema import Resource, fk

USER_ROLES = Resource("user_roles", "Kullanıcı Rolleri", {
    "user_id": "INTEGER NOT NULL UNIQUE REFERENCES users(id)", "role": "TEXT NOT NULL",
    "assigned_by": "TEXT NOT NULL", "assigned_at": "TIMESTAMP NOT NULL"},
    module="core", api=(), search=(), write="admin",
    enums={"role": ("ADMIN", "SUPPLIER_MANAGER", "UNIT_USER", "AUDITOR", "VIEWER")})

USER_UNITS = Resource("user_units", "Kullanıcı Birimleri", {
    "user_id": "INTEGER NOT NULL REFERENCES users(id)", "org_unit_id": fk("org_units"),
    "assigned_by": "TEXT NOT NULL", "assigned_at": "TIMESTAMP NOT NULL"},
    module="core", api=(), search=(), write="admin", unique=(("user_id", "org_unit_id"),))
