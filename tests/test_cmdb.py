"""CMDB (K-019): sahte ServiceNow Table API ile senkron, MCP itmesi, CI risk kuralları → kurumsal risk."""
import json
import os
import threading
import unittest
from datetime import date, datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from test_tedarik import KEY, Base

PASSWORD = "sentetik-sn-parolasi"


def f(value, shown=None):
    return {"value": value, "display_value": shown if shown is not None else value}


class FakeServiceNow:
    """Table API'nin kullandığımız alt kümesi: sysparm_query (>= filigran), limit/offset, display_value=all."""

    def __init__(self):
        self.tables, self.calls = {}, []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                url = urlparse(self.path)
                query = {k: v[0] for k, v in parse_qs(url.query).items()}
                outer.calls.append((url.path, query, self.headers.get("Authorization")))
                import base64
                expected = "Basic " + base64.b64encode(f"grc.reader:{PASSWORD}".encode()).decode()
                if self.headers.get("Authorization") != expected:
                    self.send_response(401)
                    self.end_headers()
                    return
                table = url.path.rsplit("/", 1)[-1]
                records = outer.tables.get(table, [])
                mark = next((p.split(">=", 1)[1] for p in query.get("sysparm_query", "").split("^")
                             if p.startswith("sys_updated_on>=")), None)
                if mark:
                    records = [r for r in records if r["sys_updated_on"]["value"] >= mark]
                offset, limit = int(query["sysparm_offset"]), int(query["sysparm_limit"])
                body = json.dumps({"result": records[offset:offset + limit]}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(body)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def close(self):
        self.server.shutdown()


def server(sys_id, name, os_name, os_ver, eos, updated, company="Örnek Grup A.Ş.", patch=None, missing="0",
           boot=None, crit="1 - most critical", used_for="Production"):
    patch = patch or (date.today() - timedelta(days=5)).isoformat()
    boot = boot or (datetime.now(timezone.utc) - timedelta(days=3)).strftime("%Y-%m-%d %H:%M:%S")
    return {"sys_id": f(sys_id), "name": f(name), "sys_class_name": f("cmdb_ci_linux_server", "Linux Server"),
            "company": f("c0mp4ny", company), "used_for": f(used_for), "operational_status": f("1", "Operational"),
            "busines_criticality": f(crit), "owned_by": f("u1", "Okan Yıldız"), "os": f(os_name), "os_version": f(os_ver),
            "u_os_end_of_support": f(eos), "u_last_patch_date": f(patch), "u_missing_critical_patches": f(missing),
            "u_last_boot": f(boot), "fqdn": f(name + ".ornek.test"), "sys_updated_on": f(updated)}


class Cmdb(Base):
    def setUp(self):
        super().setUp()
        self.sn = FakeServiceNow()
        self.addCleanup(self.sn.close)
        secret = os.path.join(self.tmp.name, "sn_password")
        with open(secret, "w") as handle:
            handle.write(PASSWORD)
        self.sn_env = {"TEDARIK_SN_INSTANCE": self.sn.url, "TEDARIK_SN_ALLOW_HTTP": "1", "TEDARIK_SN_USER": "grc.reader",
                       "TEDARIK_SN_PASSWORD_FILE": secret}
        self.app = self.make(**self.sn_env)
        self.company = self.ok("POST", "/companies", {"name": "Örnek Grup A.Ş.", "kind": "own", "servicenow_ref": "c0mp4ny"})["id"]
        old_boot = (datetime.now(timezone.utc) - timedelta(days=140)).strftime("%Y-%m-%d %H:%M:%S")
        self.sn.tables["cmdb_ci_server"] = [
            server("s1", "app01", "Windows Server", "2012 R2", "2023-10-10", "2026-11-01 10:00:00"),
            server("s2", "app02", "RHEL", "9", "2032-05-31", "2026-11-02 10:00:00", missing="3", boot=old_boot),
            server("s3", "test01", "CentOS", "7", "2024-06-30", "2026-11-03 10:00:00", used_for="Test"),
        ]
        self.sn.tables["cmdb_ci_business_app"] = [{
            "sys_id": f("b1"), "name": f("Müşteri Portalı"), "sys_class_name": f("cmdb_ci_business_app"),
            "company": f("c0mp4ny", "Örnek Grup A.Ş."), "used_for": f("Production"), "operational_status": f("1"),
            "busines_criticality": f("1 - most critical"), "sys_updated_on": f("2026-11-01 09:00:00")}]
        self.sn.tables["cmdb_rel_ci"] = [{"sys_id": f("r1"), "parent": f("b1"), "child": f("s1"),
                                          "type": f("t1", "Depends on::Used by"), "sys_updated_on": f("2026-11-01 09:00:00")}]

    def test_servicenow_senkronu_kurallar_ve_risk(self):
        result = self.ok("POST", "/cmdb/sync", {})
        self.assertEqual((result["status"], result["mode"], result["created"], result["relations"]), ("success", "full", 4, 1))
        cis = {c["name"]: c for c in self.ok("GET", "/cmdb_cis")}
        app01 = cis["app01"]
        self.assertEqual((app01["ci_class"], app01["environment"], app01["business_criticality"], app01["company_id"],
                          app01["os_eos_date"], app01["owner"], app01["source"]),
                         ("server", "production", "critical", self.company, "2023-10-10", "Okan Yıldız", "servicenow"))
        self.assertTrue(app01["code"].startswith("CI-"))
        self.assertTrue(all(call[2].startswith("Basic ") for call in self.sn.calls))
        self.assertEqual({q["sysparm_display_value"] for _, q, _ in self.sn.calls}, {"all"})
        context = self.ok("GET", f"/cmdb_cis/{app01['id']}/context")
        self.assertEqual(context["parents"][0]["name"], "Müşteri Portalı")
        exposures = {(e["ci_id"], e["rule"]) for e in self.ok("GET", "/ci_exposures?status=open")}
        self.assertEqual(exposures, {(app01["id"], "os_eos"), (cis["app02"]["id"], "patch"), (cis["app02"]["id"], "uptime")})
        # test ortamındaki CentOS 7 kural dışı (yalnızca üretim)
        risks = {r["origin_ref"]: r for r in self.ok("GET", "/supplier_risks") if r["source"] == "cmdb_rule"}
        self.assertEqual(set(risks), {f"cmdb:os_eos:{self.company}", f"cmdb:patch:{self.company}",
                                      f"cmdb:uptime:{self.company}"})
        eos = risks[f"cmdb:os_eos:{self.company}"]
        self.assertEqual((eos["impact"], eos["company_id"], eos["category"]), (5, self.company, "technology"))
        linked = self.ok("GET", f"/supplier_risks/{eos['id']}/context")["cis"]
        self.assertEqual([(c["name"], c["link_source"]) for c in linked], [("app01", "rule")])
        # artımlı senkron: yalnızca filigrandan sonra güncellenenler istenir; yükseltilen sunucu maruziyeti kapatır
        self.sn.tables["cmdb_ci_server"][0] = server("s1", "app01", "Windows Server", "2022", "2031-10-14",
                                                     "2026-11-10 10:00:00")
        before = len(self.sn.calls)
        again = self.ok("POST", "/cmdb/sync", {})
        self.assertEqual((again["mode"], again["updated"]), ("delta", 1))
        server_query = next(q for p, q, _ in self.sn.calls[before:] if p.endswith("cmdb_ci_server"))
        self.assertIn("sys_updated_on>=2026-11-03 10:00:00", server_query["sysparm_query"])
        self.assertEqual(self.ok("GET", f"/ci_exposures?ci_id={app01['id']}")[0]["status"], "resolved")
        self.assertEqual(self.ok("GET", f"/supplier_risks/{eos['id']}/context")["cis"], [])
        # tam senkronda kaynakta olmayan CI silinmez, eski işaretlenir
        del self.sn.tables["cmdb_ci_server"][2]
        full = self.ok("POST", "/cmdb/sync", {"full": True})
        self.assertEqual(full["stale"], 1)
        self.assertEqual(self.ok("GET", f"/cmdb_cis/{cis['test01']['id']}")["stale"], 1)
        runs = self.ok("GET", "/cmdb_sync_runs")
        self.assertEqual(len(runs), 3)
        # kaynak alanı portalda değişmez; yerel alan değişir
        self.assertEqual(self.call("PATCH", f"/cmdb_cis/{app01['id']}", {"os": "Linux"})[0], 409)
        self.ok("PATCH", f"/cmdb_cis/{app01['id']}", {"description": "DR kopyası var"})

    def test_kimlik_hatasi_ve_yapilandirma(self):
        wrong = os.path.join(self.tmp.name, "wrong")
        with open(wrong, "w") as handle:
            handle.write("yanlis")
        app = self.make(**{**self.sn_env, "TEDARIK_SN_PASSWORD_FILE": wrong})
        result = self.ok("POST", "/cmdb/sync", {}, app=app)
        self.assertEqual(result["status"], "failed")
        self.assertIn("reddedildi", result["errors"][0]["error"])
        self.assertNotIn("yanlis", json.dumps(result))
        self.assertEqual(self.call("POST", "/cmdb/sync", {}, app=self.make())[0], 409)           # yapılandırılmamış
        self.assertEqual(self.call("POST", "/cmdb/sync", {}, app=self.make(role="AUDITOR", **self.sn_env))[0], 403)
        from tedarik.config import Config
        with self.assertRaises(ValueError):
            Config({**self.env(), "TEDARIK_SN_INSTANCE": "http://sn.ornek.test"})

    def test_mcp_itmesi_ve_elle_baglanti(self):
        payload = {"items": [{"sys_id": "m1", "name": "erp-db01", "ci_class": "database", "environment": "production",
                              "company": "Örnek Grup A.Ş.", "vendor": "Oracle", "version": "11g", "eos_date": "2020-12-31",
                              "business_criticality": "high"},
                             {"name": "sys_id yok"}],
                   "idempotency_key": "mcp-cmdb-2026-11-15"}
        status, result = self.app.dispatch("POST", "/api/tdr/cmdb/cis/bulk", {"X-API-Key": KEY}, json.dumps(payload).encode())
        self.assertEqual((status, result["created"], result["status"]), (201, 1, "partial"))
        ci = self.ok("GET", "/cmdb_cis")[0]
        self.assertEqual((ci["source"], ci["company_id"]), ("mcp", self.company))
        app_risk = next(r for r in self.ok("GET", "/supplier_risks") if r["origin_ref"] == f"cmdb:app_eos:{self.company}")
        self.assertEqual(app_risk["impact"], 4)
        manual = self.ok("POST", "/supplier_risks", {"title": "ERP veritabanı tek kopya", "category": "continuity",
                                                     "owner": "x", "entity_name": "ERP", "company_id": self.company})["id"]
        self.ok("POST", f"/supplier_risks/{manual}/cis", {"ci_ids": [ci["id"]]})
        self.assertEqual(self.ok("GET", f"/cmdb_cis/{ci['id']}/context")["risks"][0]["link_source"], "rule")
        self.assertEqual(len(self.ok("GET", f"/cmdb_cis/{ci['id']}/context")["risks"]), 2)
        self.assertEqual(self.app.dispatch("POST", "/api/tdr/cmdb/sync", {"X-API-Key": KEY}, b"{}")[0], 403)


if __name__ == "__main__":
    unittest.main()
