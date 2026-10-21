"""12 個工具走 dry run，驗參數檢查、回傳形狀與 annotations。"""
import json

import pytest

pytestmark = pytest.mark.usefixtures("dry_run_server")


@pytest.fixture(scope="module")
def dry_run_server(tmp_path_factory):
    import os

    os.environ["TW_PATENT_MCP_DRY_RUN"] = "1"
    os.environ["TW_PATENT_MCP_HOME"] = str(tmp_path_factory.mktemp("home"))
    os.environ.setdefault("GPSS_USER_CODE", "DRYCODE")
    os.environ.setdefault("EPO_OPS_KEY", "k")
    os.environ.setdefault("EPO_OPS_SECRET", "s")
    from tw_patent_mcp import server

    return server


@pytest.fixture
def srv(dry_run_server):
    return dry_run_server


@pytest.mark.anyio
async def test_tool_list_and_annotations(srv):
    tools = await srv.server.list_tools()
    names = {t.name for t in tools}
    assert names == {
        "gpss_codes", "gpss_search", "gpss_get", "gpss_build_url",
        "ops_search", "ops_biblio", "ops_legal_status", "ops_family",
        "ops_fulltext", "ops_register", "ops_images", "ops_download_pdf",
    }
    by = {t.name: t for t in tools}
    assert by["ops_download_pdf"].annotations.read_only_hint is False
    assert all(by[n].annotations.read_only_hint for n in names - {"ops_download_pdf"})
    assert by["gpss_codes"].annotations.open_world_hint is False
    assert "raw" in by["ops_biblio"].input_schema["properties"]


def test_gpss_codes(srv):
    out = json.loads(srv.gpss_codes())
    assert "TWA" in out["databases"] and "TI/AB" in out["search_fields"]


def test_gpss_search_dry_run_masks_code(srv):
    out = json.loads(srv.gpss_search({"TI/AB": "battery"}, databases=["TWA"], qty=3))
    assert out["dry_run"] and "DRYCODE" not in out["url"] and "patDB=TWA" in out["url"]


def test_gpss_get_rejects_bad_by(srv):
    with pytest.raises(ValueError):
        srv.gpss_get("TW201644272A", by="XX")
    out = json.loads(srv.gpss_get("TW201644272A"))
    assert "PN=TW201644272A" in out["url"] and "CL" in out["url"]


def test_gpss_build_url_never_sends(srv):
    url = srv.gpss_build_url({"AX": "x"}, kind=["I"])
    assert url.startswith("https://") and "userCode=***" in url and "patTY=I" in url


def test_ops_tools_dry_run_paths(srv):
    assert json.loads(srv.ops_biblio("TWI700000B"))["url"].endswith("/publication/docdb/TW.I700000.B/biblio")
    assert json.loads(srv.ops_legal_status("EP1000000"))["url"].endswith("/legal/publication/epodoc/EP1000000")
    assert json.loads(srv.ops_family("US10000000B2"))["url"].endswith("/family/publication/docdb/US.10000000.B2")
    assert json.loads(srv.ops_fulltext("EP1000000", part="description"))["url"].endswith("/EP1000000/description")
    assert json.loads(srv.ops_register("EP1000000", constituent="events"))["url"].endswith("/EP1000000/events")
    assert json.loads(srv.ops_images("TWM600000U"))["url"].endswith("/docdb/TW.M600000.U/images")
    s = json.loads(srv.ops_search("ti=battery", 1, 10, "biblio"))
    assert s["params"] == {"q": "ti=battery", "Range": "1-10"}


def test_ops_fulltext_rejects_bad_part(srv):
    with pytest.raises(ValueError):
        srv.ops_fulltext("EP1000000", part="drawings")


def test_ops_download_pdf_limits(srv):
    with pytest.raises(ValueError):
        srv.ops_download_pdf("published-data/images/EP/1000000/A1/fullimage", pages="1-60")
    out = json.loads(srv.ops_download_pdf("published-data/images/EP/1000000/A1/fullimage", pages="1-2"))
    assert [p["params"]["Range"] for p in out["pages"]] == ["1", "2"]


def test_ops_result_prefers_summary(srv):
    payload = {"ops:world-patent-data": {}, "_quota": {"x-registeredquotaperweek-used": "1"}}
    out = json.loads(srv._ops_result(payload, {"a": 1}, raw=False))
    assert out == {"summary": {"a": 1}, "quota": {"x-registeredquotaperweek-used": "1"}}
    assert json.loads(srv._ops_result(payload, {"a": 1}, raw=True)) == payload
    assert json.loads(srv._ops_result({"not_found": True}, {}, raw=False)) == {"not_found": True}


def test_version_is_consistent_everywhere():
    """發版要同時改 pyproject、__init__ 與 server.json 兩處；漏改在這裡擋下。"""
    import json
    import re
    from pathlib import Path

    from tw_patent_mcp import __version__

    root = Path(__file__).resolve().parent.parent
    pyproject = re.search(r'^version = "([^"]+)"', (root / "pyproject.toml").read_text(), re.M).group(1)
    sj = json.loads((root / "server.json").read_text())
    assert pyproject == __version__ == sj["version"] == sj["packages"][0]["version"]
