"""CMDB senkronu (günlük zamanlanmış görev): python -m tedarik.cmdb_sync [--full]

ServiceNow (Table API veya MCP sunucusu, K-021) yapılandırılmışsa artımlı (veya tam) senkron yapar; ardından CI risk kurallarını değerlendirir.
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
            channel = cmdb.default_channel(cmdb.effective(db, app))       # Table API önceliklidir; yoksa ServiceNow MCP sunucusu
            if channel:
                result = cmdb.sync_servicenow(db, app, SYSTEM, full="--full" in argv, channel=channel)
                print(f"Senkron ({channel}) {result['status']} ({result['mode']}): {result['created']} yeni, "
                      f"{result['updated']} güncellenen, {result['stale']} eski; açık maruziyet {result['rules']['open']}")
            else:
                result = cmdb.evaluate_rules(db, SYSTEM)
                print(f"ServiceNow yapılandırılmadı; kurallar değerlendirildi: açık maruziyet {result['open']}")
    finally:
        app.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
