import pytest

from tw_patent_mcp import epo_ops


def test_dry_run_paths():
    c = epo_ops.OPSClient("k", "s", dry_run=True)
    assert c.biblio("EP1000000")["url"].endswith("/published-data/publication/epodoc/EP1000000/biblio")
    assert c.legal("EP1000000")["url"].endswith("/legal/publication/epodoc/EP1000000")
    assert c.family("EP1000000", constituent="legal")["url"].endswith("/family/publication/epodoc/EP1000000/legal")
    assert c.register("EP1000000", constituent="events")["url"].endswith("/register/publication/epodoc/EP1000000/events")
    s = c.search("ti=battery", 1, 25, "biblio")
    assert s["url"].endswith("/published-data/search/biblio") and s["params"] == {"q": "ti=battery", "Range": "1-25"}


def test_search_range_limit():
    c = epo_ops.OPSClient("k", "s", dry_run=True)
    with pytest.raises(epo_ops.OPSError):
        c.search("x", 1, 200)


def test_extract_hits():
    payload = {"ops:world-patent-data": {"ops:biblio-search": {"ops:search-result": {"ops:publication-reference": [
        {"@family-id": "1", "document-id": {"@document-id-type": "docdb", "country": {"$": "TW"}, "doc-number": {"$": "201644272"}, "kind": {"$": "A"}}},
    ]}}}}
    hits = epo_ops.extract_search_hits(payload)
    assert hits == [{"country": "TW", "number": "201644272", "kind": "A", "date": None, "family_id": "1"}]
    assert epo_ops.extract_search_hits({"x": 1}) == []


def test_images_dry_run_and_link_guard():
    c = epo_ops.OPSClient("k", "s", dry_run=True)
    assert c.images_inquiry("EP1000000")["url"].endswith("/published-data/publication/epodoc/EP1000000/images")
    r = c.image_page("published-data/images/EP/1000000/A1/fullimage", 2)
    assert r["url"].endswith("/published-data/images/EP/1000000/A1/fullimage.pdf") and r["params"] == {"Range": "2"}
    with pytest.raises(epo_ops.OPSError):
        c.image_page("register/x", 1)
    assert len(c.image_pages("published-data/images/EP/1000000/A1/fullimage", [1, 2])["pages"]) == 2


def test_extract_image_docs_and_pages():
    payload = {"ops:world-patent-data": {"ops:document-inquiry": {"ops:inquiry-result": {"ops:document-instance": [
        {"@desc": "FullDocument", "@link": "published-data/images/EP/1000000/A1/fullimage", "@number-of-pages": "12",
         "ops:document-format-options": {"ops:document-format": [{"$": "application/pdf"}, {"$": "application/tiff"}]}},
        {"@desc": "Drawing", "@link": "published-data/images/EP/1000000/A1/thumbnail", "@number-of-pages": "1",
         "ops:document-format-options": {"ops:document-format": {"$": "image/png"}}},
    ]}}}}
    docs = epo_ops.extract_image_docs(payload)
    assert docs[0] == {"desc": "FullDocument", "link": "published-data/images/EP/1000000/A1/fullimage", "pages": 12, "formats": ["application/pdf", "application/tiff"]}
    assert docs[1]["formats"] == ["image/png"]
    assert epo_ops.parse_pages("1-3,7", 12) == [1, 2, 3, 7]
    assert epo_ops.parse_pages("all", 4) == [1, 2, 3, 4]
    assert epo_ops.parse_pages("10-20", 12) == [10, 11, 12]
    with pytest.raises(epo_ops.OPSError):
        epo_ops.parse_pages("0", 5)


def test_normalize_number():
    from tw_patent_mcp.epo_ops import normalize_number

    assert normalize_number("US10000000B2") == ("US.10000000.B2", "docdb")
    assert normalize_number("TWI700000B") == ("TW.I700000.B", "docdb")
    assert normalize_number("TWM600000U") == ("TW.M600000.U", "docdb")
    assert normalize_number("TW201644272A") == ("TW.201644272.A", "docdb")
    assert normalize_number("tw 201644272 a") == ("TW.201644272.A", "docdb")
    assert normalize_number("EP1000000") == ("EP1000000", "epodoc")
    assert normalize_number("TW.I700000.B") == ("TW.I700000.B", "docdb")
    assert normalize_number("US10000000B2", fmt="epodoc") == ("US10000000B2", "epodoc")
