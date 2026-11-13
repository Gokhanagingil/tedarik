"""Anket motoru: kurucu, sürüm, kampanya, hedef, davet, taslak, koşul, puan, anonimlik, sonuç, risk sinyali."""
import json
import unittest

from test_tedarik import Base


class AnketTabani(Base):
    def setUp(self):
        super().setUp()
        self.unit, self.item, self.supplier, self.engagement = self.base_data()
        self.other = self.ok("POST", "/suppliers", {"code": "S2", "name": "İkinci Tedarikçi", "tier": "critical"})["id"]

    def as_user(self, name, role="VIEWER"):
        return self.make(role=role, user=name)

    def template(self, code="T1", purpose="satisfaction"):
        template = self.ok("POST", "/survey_templates", {"code": code, "name": "Deneme şablonu", "purpose": purpose})["id"]
        section = self.ok("POST", "/survey_sections", {"template_id": template, "title": "Hizmet"})["id"]
        q = {}
        q["kalite"] = self.ok("POST", "/survey_questions", {"template_id": template, "section_id": section,
                                                            "text": "Kalite", "kind": "scale_1_5", "weight": 2,
                                                            "risk_category": "performance", "risk_threshold": 50})["id"]
        q["olay"] = self.ok("POST", "/survey_questions", {
            "template_id": template, "section_id": section, "text": "Güvenlik olayı yaşandı mı?", "kind": "yes_no",
            "options_json": json.dumps([{"value": "yes", "label": "Evet", "score": 0},
                                        {"value": "no", "label": "Hayır", "score": 100}]),
            "risk_category": "security", "risk_threshold": 60})["id"]
        q["ayrinti"] = self.ok("POST", "/survey_questions", {
            "template_id": template, "section_id": section, "text": "Olayı anlatın", "kind": "text",
            "show_if_json": json.dumps({"question": "S2", "equals": "yes"})})["id"]
        q["tavsiye"] = self.ok("POST", "/survey_questions", {"template_id": template, "text": "Tavsiye eder misiniz?",
                                                             "kind": "nps_0_10", "required": 0})["id"]
        q["kanal"] = self.ok("POST", "/survey_questions", {
            "template_id": template, "text": "Hangi kanallar?", "kind": "multi_choice", "required": 0, "weight": 0,
            "options_json": json.dumps([{"label": "E-posta"}, {"label": "Telefon"}, {"label": "Portal"}])})["id"]
        return template, q


class Kurucu(AnketTabani):
    def test_soru_dogrulama_ve_yapi(self):
        template, q = self.template()
        bad = [{"kind": "single_choice"},                                          # seçenek yok
               {"kind": "text", "risk_category": "security"},                      # puansız soruda risk
               {"kind": "scale_1_5", "risk_threshold": 40},                        # kategorisiz eşik
               {"kind": "scale_1_5", "show_if_json": json.dumps({"question": "YOK", "equals": 1})},
               {"kind": "single_choice", "options_json": json.dumps([{"label": "A"}, {"label": "A"}])}]
        for body in bad:
            self.assertEqual(self.call("POST", "/survey_questions", {"template_id": template, "text": "x", **body})[0],
                             400, body)
        form = self.ok("GET", f"/survey_templates/{template}/structure")
        self.assertEqual([x["code"] for x in form["questions"]], ["S1", "S2", "S3", "S4", "S5"])
        self.assertEqual(form["questions"][4]["options"][0], {"label": "E-posta", "value": "E-posta"})
        self.assertEqual(form["questions"][2]["show_if"], {"question": "S2", "equals": "yes"})
        order = [{"id": q["tavsiye"]}, {"id": q["kalite"]}, {"id": q["olay"]}, {"id": q["ayrinti"]}, {"id": q["kanal"]}]
        reordered = self.ok("POST", f"/survey_templates/{template}/reorder", {"questions": order})
        self.assertEqual(reordered["questions"][0]["id"], q["tavsiye"])
        self.assertIsNone(reordered["questions"][0]["section_id"])

    def test_yayimlanan_sablon_donar_yeni_surum_kopyalanir(self):
        template, q = self.template()
        self.ok("POST", f"/survey_templates/{template}/publish", {})
        self.assertEqual(self.call("PATCH", f"/survey_questions/{q['kalite']}", {"text": "Yeni"})[0], 409)
        self.assertEqual(self.call("POST", "/survey_questions", {"template_id": template, "text": "Ek"})[0], 409)
        self.assertEqual(self.call("PATCH", f"/survey_templates/{template}", {"name": "Yeni ad"})[0], 409)
        copy = self.ok("POST", f"/survey_templates/{template}/copy", {})
        self.assertEqual((copy["code"], copy["version"], copy["status"], copy["parent_id"]), ("T1", 2, "draft", template))
        self.assertEqual(len(copy["questions"]), 5)
        self.assertEqual(copy["questions"][2]["show_if"], {"question": "S2", "equals": "yes"})
        self.assertNotEqual(copy["questions"][0]["section_id"], q["kalite"])
        self.ok("PATCH", f"/survey_questions/{copy['questions'][0]['id']}", {"text": "Kalite (yeni sürüm)"})
        self.ok("PATCH", f"/survey_questions/{copy['questions'][4]['id']}", {"disabled": 1})     # silme yok, kaldır
        self.assertEqual(len(self.ok("GET", f"/survey_templates/{copy['id']}/structure")["questions"]), 4)
        self.assertEqual(len(self.ok("GET", f"/survey_templates/{copy['id']}/structure?all=1")["questions"]), 5)

    def test_baslangic_sablonlari(self):
        templates = {t["code"]: t for t in self.ok("GET", "/survey_templates")}
        self.assertEqual(templates["RISK-DEG"]["purpose"], "risk")
        risk = self.ok("GET", f"/survey_templates/{templates['RISK-DEG']['id']}/structure")
        negative = next(x for x in risk["questions"] if "güvenlik olayı" in x["text"])
        self.assertEqual(negative["options"][0], {"value": "yes", "label": "Evet", "score": 0})

    def test_yetki(self):
        viewer = self.as_user("ali")
        self.assertEqual(self.call("POST", "/survey_templates", {"code": "X", "name": "X"}, app=viewer)[0], 403)


class Kampanya(AnketTabani):
    def campaign(self, template, **extra):
        body = {"code": "2026-Q4", "name": "4. çeyrek memnuniyet", "template_id": template, "subject": "supplier",
                **extra}
        return self.ok("POST", "/survey_campaigns", body)["id"]

    def answer(self, app, campaign, target, values, submit=True):
        started = self.ok("POST", f"/survey_campaigns/{campaign}/responses", {"target_id": target}, app=app)
        return self.call("POST", f"/survey_responses/{started['response_id']}/answers",
                         {"answers": [{"question_id": k, "value": v} for k, v in values.items()], "submit": submit},
                         app=app)

    def test_tam_akis_puan_kosul_sonuc_ve_risk_sinyali(self):
        template, q = self.template()
        campaign = self.campaign(template)
        self.assertEqual(self.call("POST", f"/survey_campaigns/{campaign}/open", {})[0], 400)      # hedef yok
        added = self.ok("POST", f"/survey_campaigns/{campaign}/targets", {"supplier_ids": [self.supplier],
                                                                          "tier": "critical"})
        self.assertEqual(added, {"added": 2, "skipped": 0})          # S1 ve S2 ikisi de kritik
        self.assertEqual(self.call("POST", f"/survey_campaigns/{campaign}/open", {})[0], 400)      # davet yok
        invited = self.ok("POST", f"/survey_campaigns/{campaign}/invite", {"respondents": ["ayse", "can"]})
        self.assertEqual(invited, {"created": 4, "skipped": 0})
        self.assertEqual(self.ok("POST", f"/survey_campaigns/{campaign}/invite",
                                 {"respondents": ["ayse"]}), {"created": 0, "skipped": 2})
        self.ok("POST", f"/survey_campaigns/{campaign}/open", {})
        self.assertEqual(self.ok("GET", f"/survey_templates/{template}")["status"], "published")
        targets = {t["supplier_id"]: t["id"] for t in self.ok("GET", f"/survey_campaigns/{campaign}/context")["targets"]}
        ayse, can, mert = self.as_user("ayse"), self.as_user("can"), self.as_user("mert")
        mine = self.ok("GET", "/my/surveys", app=ayse)
        self.assertEqual(len(mine), 2)
        self.assertEqual({m["state"] for m in mine}, {"new"})
        self.assertEqual(self.call("POST", f"/survey_campaigns/{campaign}/responses",
                                   {"target_id": targets[self.supplier]}, app=mert)[0], 403)   # davetsiz
        # taslak: koşullu soru görünür olur, zorunlu eksik bildirilir
        draft = self.answer(ayse, campaign, targets[self.supplier], {q["olay"]: "yes"}, submit=False)[1]
        self.assertIn(q["ayrinti"], draft["visible"])
        self.assertEqual(set(draft["required_missing"]), {q["kalite"], q["ayrinti"]})
        blocked = self.answer(ayse, campaign, targets[self.supplier], {q["kalite"]: 2})
        self.assertEqual(blocked[0], 400)
        self.assertIn("Olayı anlatın", blocked[1]["error"])
        self.assertEqual(self.answer(ayse, campaign, targets[self.supplier], {q["kalite"]: 9})[0], 400)
        done = self.answer(ayse, campaign, targets[self.supplier], {q["kalite"]: 2, q["ayrinti"]: "Veri sızıntısı",
                                                                    q["tavsiye"]: 3, q["kanal"]: ["E-posta", "Portal"]})
        self.assertEqual(done[0], 200, done[1])
        # kalite (2-1)*25=25 ağırlık 2; olay evet=0 ağırlık 1; tavsiye 30 ağırlık 1; kanal ağırlık 0 -> (50+0+30)/4
        self.assertEqual(done[1]["score"], 20.0)
        self.assertEqual(self.answer(ayse, campaign, targets[self.supplier], {q["kalite"]: 5})[0], 409)  # gönderildi
        self.answer(can, campaign, targets[self.supplier], {q["kalite"]: 3, q["olay"]: "no", q["tavsiye"]: 10})
        self.answer(can, campaign, targets[self.other], {q["kalite"]: 5, q["olay"]: "no", q["tavsiye"]: 9})
        result = self.ok("GET", f"/survey_campaigns/{campaign}/results")
        self.assertEqual((result["invited"], result["submitted"], result["response_rate"]), (4, 3, 75.0))
        kalite = next(x for x in result["questions"] if x["id"] == q["kalite"])
        self.assertEqual((kalite["average"], kalite["distribution"][1]), (3.33, {"value": 2, "count": 1}))
        tavsiye = next(x for x in result["questions"] if x["id"] == q["tavsiye"])
        self.assertEqual(tavsiye["nps"], {"promoters": 2, "passives": 0, "detractors": 1, "score": 33})
        kanal = next(x for x in result["questions"] if x["id"] == q["kanal"])
        self.assertEqual([d["count"] for d in kanal["distribution"]], [1, 0, 1])
        self.assertEqual(next(x for x in result["questions"] if x["id"] == q["ayrinti"])["answers"], ["Veri sızıntısı"])
        by_supplier = {t["supplier_id"]: t for t in result["targets"]}
        self.assertEqual(by_supplier[self.other]["average_score"], 97.5)       # (2×100 + 100 + 90) / 4
        signals = result["risk_signals"]
        self.assertEqual([(s["supplier_id"], s["category"]) for s in signals], [(self.supplier, "performance"),
                                                                                (self.supplier, "security")])
        self.assertEqual(signals[0]["average_score"], 37.5)
        viewer_result = self.call("GET", f"/survey_campaigns/{campaign}/results", app=mert)
        self.assertEqual(viewer_result[0], 403)
        created = self.ok("POST", f"/survey_campaigns/{campaign}/risk-signals",
                          {"origin_refs": [signals[1]["origin_ref"]]})["created"]
        risk = self.ok("GET", f"/supplier_risks/{created[0]}")
        self.assertEqual((risk["category"], risk["supplier_id"], risk["status"]), ("security", self.supplier, "open"))
        again = self.ok("POST", f"/survey_campaigns/{campaign}/risk-signals", {"origin_refs": [signals[1]["origin_ref"]]})
        self.assertEqual(again["created"], [])
        self.assertEqual(self.ok("GET", f"/survey_campaigns/{campaign}/results")["risk_signals"][1]["risk"]["id"],
                         created[0])
        history = self.ok("GET", f"/suppliers/{self.supplier}/surveys")
        self.assertEqual((history[0]["responses"], history[0]["score"]), (2, round((20.0 + 75.0) / 2, 1)))
        self.ok("POST", f"/survey_campaigns/{campaign}/close", {})
        self.assertEqual(self.call("POST", f"/survey_campaigns/{campaign}/responses",
                                   {"target_id": targets[self.other]}, app=ayse)[0], 409)
        self.assertEqual({m["state"] for m in self.ok("GET", "/my/surveys", app=ayse)}, {"submitted"})

    def test_anonim_ve_bagimsiz_anket(self):
        template, q = self.template(code="GENEL", purpose="general")
        campaign = self.ok("POST", "/survey_campaigns", {"code": "CALISAN", "name": "İç memnuniyet",
                                                         "template_id": template, "subject": "none",
                                                         "audience": "all", "anonymous": 1, "min_responses": 2})["id"]
        self.assertEqual(self.call("POST", f"/survey_campaigns/{campaign}/targets",
                                   {"supplier_ids": [self.supplier]})[0], 400)       # bağımsız ankette hedef yok
        self.ok("POST", f"/survey_campaigns/{campaign}/open", {})
        ayse, can = self.as_user("ayse"), self.as_user("can")
        self.assertEqual(self.ok("GET", "/my/surveys", app=ayse)[0]["state"], "new")
        self.answer(ayse, campaign, None, {q["kalite"]: 4, q["olay"]: "no"})
        hidden = self.ok("GET", f"/survey_campaigns/{campaign}/results")
        self.assertTrue(hidden["hidden"])
        self.assertNotIn("questions", hidden)
        with self.db() as db:
            stored = db.execute("SELECT respondent, invitation_id FROM tdr_survey_responses").fetchall()
        self.assertEqual([(r["respondent"], r["invitation_id"]) for r in stored], [(None, None)])
        again = self.ok("POST", f"/survey_campaigns/{campaign}/responses", {}, app=ayse)
        self.assertEqual(again["status"], "submitted")            # aynı kişi ikinci kez yanıtlayamaz
        self.answer(can, campaign, None, {q["kalite"]: 2, q["olay"]: "no"})
        shown = self.ok("GET", f"/survey_campaigns/{campaign}/results")
        self.assertFalse(shown["hidden"])
        self.assertIsNone(shown["response_ids"])
        self.assertEqual(shown["risk_signals"], [])
        other = self.call("GET", f"/survey_responses/{again['response_id']}/form", app=can)
        self.assertEqual(other[0], 403)                           # başkasının yanıtı açılamaz
        mine = self.ok("GET", f"/survey_responses/{again['response_id']}/form", app=ayse)
        self.assertEqual(mine["response"]["status"], "submitted")
        self.assertEqual(mine["answers"][str(q["kalite"])] if str(q["kalite"]) in mine["answers"]
                         else mine["answers"][q["kalite"]], 4)

    def test_acik_kampanyada_sadece_sinirli_duzenleme(self):
        template, _ = self.template()
        campaign = self.campaign(template, audience="all")
        self.ok("POST", f"/survey_campaigns/{campaign}/targets", {"supplier_ids": [self.supplier]})
        self.ok("POST", f"/survey_campaigns/{campaign}/open", {})
        self.assertEqual(self.call("PATCH", f"/survey_campaigns/{campaign}", {"anonymous": 1})[0], 409)
        self.ok("PATCH", f"/survey_campaigns/{campaign}", {"closes_on": "2099-12-31"})
        self.assertEqual(self.call("PATCH", f"/survey_campaigns/{campaign}", {"closes_on": "2000-01-01",
                                                                              "opens_on": "2001-01-01"})[0], 409)


if __name__ == "__main__":
    unittest.main()
