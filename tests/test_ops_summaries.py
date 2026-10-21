"""壓平 OPS JSON：樣本取自 2026-10-21 實測回應（EP1000000、TW201644272A）。"""
import json
from pathlib import Path

from tw_patent_mcp import epo_ops

SAMPLES = Path(__file__).parent / "samples"


def load(name: str) -> dict:
    return json.loads((SAMPLES / f"ops_{name}.json").read_text(encoding="utf-8"))


def test_summarize_biblio_ep():
    docs = epo_ops.summarize_biblio(load("biblio_ep"))
    assert [d["publication"]["number"] for d in docs] == ["EP1000000A1", "EP1000000B1"]  # epodoc 不帶 kind 會回兩份
    doc = docs[0]
    assert doc["publication"] == {"number": "EP1000000A1", "date": "20000517"}
    assert doc["application"] == {"number": "EP99203729A", "date": "19991108"}
    assert doc["family_id"] == "19768124"
    assert doc["title"]["en"].startswith("Apparatus for manufacturing green bricks")
    assert doc["applicants"] == ["BOER BEHEER NIJMEGEN BV DE [NL]", "BEHEERMIJ DE BOER NIJMEGEN BV [NL]"]
    assert doc["inventors"] == ["KOSMAN WILHELMUS JACOBUS MARIA [NL]"]  # original 格式的重複名不列
    assert doc["priority"] == ["NL 1010536 19981112"]
    assert doc["ipc"][:2] == ["B28B 1/29", "B28B 5/02"]
    assert doc["cpc"][0] == "B28B1/29"
    c = doc["citations"][0]
    assert c["number"] == "EP0680812A1" and c["category"] == "A" and c["cited_by"] == "examiner" and c["claims"] == "1,10,11"
    assert doc["abstract"]["en"].startswith("[0001]")


def test_summarize_biblio_tw_and_cpc_dedup():
    (doc,) = epo_ops.summarize_biblio(load("biblio_tw"))
    assert doc["publication"]["number"] == "TW201644272A"
    assert doc["application"]["number"] == "TW105131793A"
    assert doc["priority"] == ["KR 20110115218 20111107"]
    assert len(doc["cpc"]) == len(set(doc["cpc"]))
    assert "citations" not in doc  # 無引證時不出現空欄位


def test_summarize_legal():
    out = epo_ops.summarize_legal(load("legal_ep"))
    m = out["members"][0]
    assert m["publication"]["number"] == "EP1000000A1"
    e = m["events"][0]
    assert e == {
        "date": "2002-06-05", "code": "17Q", "desc": "FIRST EXAMINATION REPORT DESPATCHED",
        "effect": "+", "details": {"Effective DATE": "20020423"},
    }
    assert m["events"][1]["details"]["Designated State(s)"].startswith("AT BE CH")
    assert "effect" not in m["events"][2]  # @infl 為空白時不列


def test_summarize_family():
    out = epo_ops.summarize_family(load("family_ep"))
    assert out["total"] == 6 and len(out["members"]) == 6
    assert out["members"][0]["representative"] is True
    assert {m["publication"]["number"] for m in out["members"]} >= {"EP1000000A1", "EP1000000B1"}
    assert out["members"][0]["priority"] == ["NL 1010536 19981112"]


def test_search_with_biblio_constituent():
    payload = load("search")
    hits = epo_ops.extract_search_hits(payload)
    assert epo_ops.search_total(payload) == 1
    assert hits[0]["publication"]["number"] == "EP1000000A1" and "title" in hits[0]


def test_unexpected_payloads_give_empty():
    assert epo_ops.summarize_biblio({"x": 1}) == []
    assert epo_ops.summarize_legal({"not_found": True}) == {}
    assert epo_ops.summarize_family(None) == {}


def test_throttle_parsing_and_interval():
    t = epo_ops.parse_throttle("busy (images=green:100, inpadoc=green:45, other=green:1000, retrieval=green:100, search=green:15)")
    assert t["search"] == ("green", 15)
    assert epo_ops.interval_for("search", t) == 4.0
    assert epo_ops.interval_for("images", t) == 0.6
    assert epo_ops.interval_for("other", t) == 0.5  # 下限
    assert epo_ops.interval_for("search", {}) == epo_ops.DEFAULT_INTERVAL
    assert epo_ops.interval_for("search", epo_ops.parse_throttle("overloaded (search=red:0)")) == 60.0
    assert epo_ops.parse_throttle(None) == {}


def test_service_of():
    assert epo_ops.service_of("published-data/search/biblio") == "search"
    assert epo_ops.service_of("published-data/images/EP/1/A1/fullimage") == "images"
    assert epo_ops.service_of("legal/publication/epodoc/EP1") == "inpadoc"
    assert epo_ops.service_of("family/publication/epodoc/EP1") == "inpadoc"
    assert epo_ops.service_of("published-data/publication/epodoc/EP1/biblio") == "retrieval"
    assert epo_ops.service_of("register/publication/epodoc/EP1/biblio") == "other"


def test_token_refresh_on_invalid_token(monkeypatch):
    """第一次回 400 invalid_access_token 要清 token 重取一次，第二次成功。"""
    import httpx

    c = epo_ops.OPSClient("k", "s")
    tokens = iter(["old", "new"])
    monkeypatch.setattr(c, "token", lambda: next(tokens))
    calls = []

    def fake_get(self, url, params=None, headers=None):
        calls.append(headers["Authorization"])
        if len(calls) == 1:
            return httpx.Response(400, text='{"error":"invalid_access_token"}', request=httpx.Request("GET", url))
        return httpx.Response(200, json={"ok": True}, headers={"content-type": "application/json",
                              "x-throttling-control": "idle (search=green:30)"}, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.Client, "get", fake_get)
    monkeypatch.setattr(epo_ops.time, "sleep", lambda s: None)
    out = c.get("published-data/publication/epodoc/EP1000000/biblio")
    assert calls == ["Bearer old", "Bearer new"] and out["ok"] is True
    assert c._throttle["search"] == ("green", 30)
    assert set(out["_quota"]) == {"x-throttling-control"}
