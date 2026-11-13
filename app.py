"""Tedarik portalı giriş noktası. Çalıştırma: TEDARIK_AUTH_MODE=dev python app.py"""
from http.server import ThreadingHTTPServer

from tedarik.config import Config
from tedarik.http import build, handler_class

if __name__ == "__main__":
    config = Config()
    app = build(config)
    print(f"Tedarik http://{config.host}:{config.port} adresinde çalışıyor (modüller: {', '.join(config.modules)})")
    ThreadingHTTPServer((config.host, config.port), handler_class(app)).serve_forever()
