"""Modül yükleyici. Her modül kendi kaynaklarını (tablolarını), uç noktalarını ve başlangıç verisini getirir.

Bir modül şunları tanımlayabilir: REQUIRES (bağımlı olduğu modüller), register(app), seed(db).
Etkin modüller TEDARIK_MODULES ile seçilir; kapalı modülün tablosu ve uç noktası açılmaz.
"""
import importlib


def load(config):
    loaded = []
    for name in config.modules:
        mod = importlib.import_module(f"tedarik.modules.{name}")
        for dependency in getattr(mod, "REQUIRES", ()):
            if dependency not in config.modules:
                raise RuntimeError(f"{name} modülü {dependency} modülünü gerektirir")
        loaded.append(mod)
    return loaded
