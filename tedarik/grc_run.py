"""İç otomatik kontrolleri çalıştırır (günlük zamanlanmış görev): python -m tedarik.grc_run

Her aktif ve iç kuralı olan kontrol bir kez çalışır; sonuç "system" kaynağıyla, sorgu özeti kanıtıyla kaydedilir.
"""
import sys

from .auth import Principal
from .config import Config

SYSTEM = Principal("system", "ADMIN", "system", "Zamanlanmış görev")


def main():
    from .http import build
    from .modules import grc
    app = build(Config())
    try:
        if not app.enabled("grc"):
            print("GRC_DISABLED")
            return 0
        with app.database.connect() as db:
            results = grc.run_all(db, app, SYSTEM)
    finally:
        app.close()
    failed = sum(1 for r in results if r["finding_id"])
    print(f"{len(results)} otomatik kontrol çalıştı; {failed} başarısız")
    return 0


if __name__ == "__main__":
    sys.exit(main())
