"""Modül yükleyici. Her modül kendi kaynaklarını (tablolarını), uç noktalarını ve başlangıç verisini getirir.

Bir modül şunları tanımlayabilir: REQUIRES (bağımlı olduğu modüller), register(app), seed(db).
Etkin modüller TEDARIK_MODULES ile seçilir; kapalı modülün tablosu ve uç noktası açılmaz.
"""
import importlib

REMINDERS = []   # zamanlanmış hatırlatmalar: fn(db, app) -> kuyruğa yazılan ileti sayısı (notify.reminders)


def reminder(fn):
    """Modül içe aktarılırken bir kez kaydedilir; işlev kendi modülünün açık olduğunu denetler."""
    if fn not in REMINDERS:
        REMINDERS.append(fn)
    return fn


def load(config):
    loaded = []
    for name in config.modules:
        mod = importlib.import_module(f"tedarik.modules.{name}")
        for dependency in getattr(mod, "REQUIRES", ()):
            if dependency not in config.modules:
                raise RuntimeError(f"{name} modülü {dependency} modülünü gerektirir")
        loaded.append(mod)
    return loaded
