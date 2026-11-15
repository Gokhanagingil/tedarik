"""Standart kütüphanesi (K-023): python -m tedarik.standards_cli [install|status]

install: `tedarik/data/standards` içindeki tam metin paketlerini kurar veya günceller (kurulumda her seferinde
çalışır; kurumun uygulanabilirlik kararları, kapsam seçimi ve eşlemeleri korunur). status: kurulu sürümleri yazar.
"""
import sys

from .auth import Principal
from .config import Config

SYSTEM = Principal("system", "ADMIN", "system", "Standart kütüphanesi")


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    command = argv[0] if argv else "status"
    from .http import build
    app = build(Config())
    try:
        if not app.enabled("grc"):
            print("GRC_DISABLED")
            return 0
        from .modules import grc_library as L
        with app.database.connect() as db:
            for name, package in L.packages():
                if command == "install":
                    r = L.install_package(db, package, SYSTEM, library_key=package.get("key"))
                    print(f"{r['code']} {r['version']}: {r['created']} yeni, {r['updated']} güncellenen, "
                          f"{r['unchanged']} değişmeyen madde; {r['links']} yeni resmî ilişki")
                else:
                    std = L._installed(db, package)
                    print(f"{package['code']} {package.get('version')}: " + ("kurulu" if std else "kurulu değil"))
    finally:
        app.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
