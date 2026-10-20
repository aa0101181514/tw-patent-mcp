import json

import pytest

from tw_patent_mcp import gpss


def test_build_url_matches_official_example():
    q = gpss.Query(
        conditions={"TI": "太陽能", "ID": "20150101:20160101"},
        databases=["TWA", "TWB"], status=["A", "B"], kind=["I"],
        output=["PN", "AN", "ID", "AD", "TI"], fmt="json", qty=100,
    )
    url = gpss.build_url(q, "CODE")
    assert url == (
        "https://tiponet.tipo.gov.tw/gpss1/gpsskmc/gpss_api?userCode=CODE&patDB=TWA,TWB&patAG=A,B&patTY=I"
        "&TI=%E5%A4%AA%E9%99%BD%E8%83%BD&ID=20150101:20160101&expFld=PN,AN,ID,AD,TI&expFmt=json&expQty=100"
    )


def test_cross_field_or_not_prefix_and_slash_kept():
    q = gpss.Query(conditions={"TI/AB": "網架結構 or Filter frame", "+AB": "x", "-IC": "F24F"}, output=["PN"])
    url = gpss.build_url(q, "C")
    assert "&TI/AB=" in url and "&+AB=x" in url and "&-IC=F24F" in url
    assert "Filter%20frame" in url  # 空白要編碼，or 保留


def test_rejects_truncation_and_unknown_field():
    with pytest.raises(gpss.GPSSError):
        gpss.Query(conditions={"TI": "comput*"}).validate()
    with pytest.raises(gpss.GPSSError):
        gpss.Query(conditions={"ZZ": "x"}).validate()
    with pytest.raises(gpss.GPSSError):
        gpss.Query(conditions={}).validate()
    with pytest.raises(gpss.GPSSError):
        gpss.Query(conditions={"TI": "a"}, databases=["XX"]).validate()


SAMPLE = {
    "gpss-API": {
        "status": "success", "message": "", "skip": "0", "total-rec": "1", "qty-rec": "30",
        "patent": {
            "@create-date": "20210728",
            "patentcontent": [{
                "@sequence": "1", "@database": "美國設計", "@status": "B", "@type": "新式樣",
                "publication-reference": {"doc-number": "USD0254332S", "date": "19800226"},
                "application-reference": {"doc-number": "US05895783", "date": "19780412"},
                "parties": {
                    "applicants": {"applicant": [{"@sequence": "1", "english-name": "Stanley Electric Co., Ltd.", "country-code": "JP"}]},
                    "inventors": {"inventor": {"@sequence": "1", "name": "山田太郎", "english-name": "YAMADA TARO"}},
                },
                "classifications-ipc": {"ipc": [{"@sequence": "1", "keyValue": "H01L 33/00"}]},
                "patent-title": {"title": "燈具", "english-title": "Lamp"},
                "abstract": {"p": ["第一段", "第二段"]},
                "claims": {"claim": [{"@num": "1", "claim-text": "一種燈具…"}]},
            }],
        },
    }
}


def test_parse_success():
    r = gpss.parse_json(SAMPLE)
    assert r["total"] == 1 and r["returned"] == 1
    rec = r["records"][0]
    assert rec["publication_number"] == "USD0254332S"
    assert rec["applicants"] == ["Stanley Electric Co., Ltd.[JP]"]
    assert rec["inventors"] == ["山田太郎（YAMADA TARO）"]
    assert rec["ipc"] == ["H01L 33/00"]
    assert rec["abstract"] == "第一段\n第二段"
    assert rec["claims"][0]["num"] == "1"


def test_parse_no_record_is_empty_not_error():
    r = gpss.parse_json({"gpss-API": {"status": "fail", "message": "No record found"}})
    assert r["total"] == 0 and r["records"] == []


def test_fatal_message_writes_lock(tmp_path, monkeypatch):
    monkeypatch.setenv("TW_PATENT_MCP_HOME", str(tmp_path))
    lock = tmp_path / "gpss_lock"
    with pytest.raises(gpss.GPSSFatal):
        gpss.parse_json({"gpss-API": {"status": "fail", "message": "userCode not exist"}})
    assert lock.exists() and "userCode not exist" in lock.read_text()
    client = gpss.GPSSClient("x")
    with pytest.raises(gpss.GPSSFatal):
        client.check_lock()


def test_dry_run_masks_code():
    client = gpss.GPSSClient("SECRET16", dry_run=True)
    out = client.search(gpss.Query(conditions={"TI": "x"}))
    assert out["dry_run"] and "SECRET16" not in out["url"] and "***" in out["url"]


def test_paths_follow_home_env(tmp_path, monkeypatch):
    from tw_patent_mcp import config

    monkeypatch.setenv("TW_PATENT_MCP_HOME", str(tmp_path))
    monkeypatch.delenv("TW_PATENT_MCP_DOWNLOAD_DIR", raising=False)
    assert config.gpss_lock_file() == tmp_path / "gpss_lock"
    assert config.download_dir() == tmp_path / "downloads"
    monkeypatch.setenv("TW_PATENT_MCP_DOWNLOAD_DIR", str(tmp_path / "pdf"))
    assert config.download_dir() == tmp_path / "pdf"


def test_load_env_does_not_override(tmp_path, monkeypatch):
    from tw_patent_mcp import config

    env = tmp_path / "x.env"
    env.write_text("GPSS_USER_CODE=fromfile\nEPO_OPS_KEY='k'\n", encoding="utf-8")
    monkeypatch.setenv("GPSS_USER_CODE", "fromenv")
    monkeypatch.delenv("EPO_OPS_KEY", raising=False)
    assert config.load_env(env) == env
    assert config.get("GPSS_USER_CODE") == "fromenv"
    assert config.get("EPO_OPS_KEY") == "k"
