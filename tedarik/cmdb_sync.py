"""CMDB senkronu (günlük zamanlanmış görev): python -m tedarik.cmdb_sync [--full]

ServiceNow yapılandırılmışsa artımlı (veya tam) senkron yapar; ardından CI risk kurallarını değerlendirir.
Yapılandırılmamışsa yalnızca kuralları değerlendirir (MCP ile itilen veya elle girilen CI'lar için).
"""
import sys

from .auth import Principal
from .config import Config

SYSTEM = Principal("system", "ADMIN", "system", "Zamanlanmış görev")


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    from .http import build
    from .modules import cmdb
    app = build(Config())
    try:
        if not app.enabled("cmdb"):
            print("CMDB_DISABLED")
            return 0
        with app.database.connect() as db:
            if app.config.sn_instance:
                result = cmdb.sync_servicenow(db, app, SYSTEM, full="--full" in argv)
                print(f"Senkron {result['status']} ({result['mode']}): {result['created']} yeni, {result['updated']} "
                      f"güncellenen, {result['stale']} eski; açık maruziyet {result['rules']['open']}")
            else:
                result = cmdb.evaluate_rules(db, SYSTEM)
                print(f"ServiceNow yapılandırılmadı; kurallar değerlendirildi: açık maruziyet {result['open']}")
    finally:
        app.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
