"""EPO Open Patent Services v3.2（免費：每週 4GB、每分鐘 10 次檢索、家族每秒 1 次）。

憑證：developers.epo.org → My apps 的 Consumer Key / Secret，用 client credentials 換 access token（約 20 分鐘）。
條款：使用者須自行遵守 EPO OPS Terms and Conditions 與 Fair use charter。
"""
from __future__ import annotations

import base64
import re
import time
from pathlib import Path
from typing import Any

import httpx

from . import config

BASE = "https://ops.epo.org/3.2"
TOKEN_URL = f"{BASE}/auth/accesstoken"
REST = f"{BASE}/rest-services"

NUMBER_FORMATS = ("auto", "epodoc", "docdb", "original")

_COMPACT = re.compile(r"^([A-Z]{2})([A-Z]?\d+)([A-Z]\d?)?$")


def normalize_number(number: str, fmt: str = "auto") -> tuple[str, str]:
    """把常見寫法轉成 OPS 接受的 (number, fmt)。

    實測：docdb「國別.號碼.kind」最穩，TW.I700000.B、TW.M600000.U、US.10000000.B2 皆可；
    epodoc 對帶兩碼 kind 的美國號與不帶 kind 的 TWI 號常回 404。
    規則：fmt 非 auto 原樣送出；含「.」視為 docdb；「CC+號碼+kind」拆成 docdb；沒有 kind 用 epodoc。
    """
    number = re.sub(r"[\s-]", "", number).upper()
    if fmt != "auto":
        return number, fmt
    if "." in number:
        return number, "docdb"
    m = _COMPACT.match(number)
    if m and m.group(3):
        return f"{m.group(1)}.{m.group(2)}.{m.group(3)}", "docdb"
    return number, "epodoc"


class OPSError(RuntimeError):
    pass


class OPSClient:
    def __init__(self, key: str, secret: str, timeout: float = 60.0, dry_run: bool = False):
        if not key or not secret:
            raise OPSError("缺 EPO_OPS_KEY 或 EPO_OPS_SECRET")
        self.key, self.secret = key, secret
        self.timeout = timeout
        self.dry_run = dry_run
        self._token: str | None = None
        self._expires_at = 0.0
        self._last_call = 0.0

    # ---- auth ----
    def token(self) -> str:
        if self._token and time.time() < self._expires_at - 30:
            return self._token
        basic = base64.b64encode(f"{self.key}:{self.secret}".encode()).decode()
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.post(
                TOKEN_URL,
                headers={"Authorization": f"Basic {basic}", "Content-Type": "application/x-www-form-urlencoded"},
                data={"grant_type": "client_credentials"},
            )
        if resp.status_code != 200:
            raise OPSError(f"取 token 失敗 HTTP {resp.status_code}: {resp.text[:200]}")
        data = resp.json()
        self._token = data["access_token"]
        self._expires_at = time.time() + int(data.get("expires_in", 1200))
        return self._token

    # ---- transport ----
    def get(self, path: str, params: dict[str, Any] | None = None, accept: str = "application/json") -> Any:
        url = f"{REST}/{path.lstrip('/')}"
        if self.dry_run:
            return {"dry_run": True, "url": url, "params": params or {}}
        # 官方門檻每分鐘 10 次檢索；保守地讓兩次呼叫至少間隔 6 秒。
        wait = 6.0 - (time.time() - self._last_call)
        if wait > 0:
            time.sleep(wait)
        headers = {"Authorization": f"Bearer {self.token()}", "Accept": accept}
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.get(url, params=params, headers=headers)
        self._last_call = time.time()
        quota = {k: v for k, v in resp.headers.items() if k.lower().startswith("x-")}
        if resp.status_code == 404:
            return {"not_found": True, "url": str(resp.url), "quota": quota}
        if resp.status_code == 403:
            raise OPSError(f"403（可能超出額度或被擋）：{resp.text[:300]}；headers={quota}")
        if resp.status_code != 200:
            raise OPSError(f"HTTP {resp.status_code}: {resp.text[:300]}")
        if "json" in resp.headers.get("content-type", ""):
            payload = resp.json()
        else:
            payload = {"raw": resp.text}
        if isinstance(payload, dict):
            payload["_quota"] = quota
        return payload

    # ---- services ----
    def search(self, cql: str, start: int = 1, end: int = 25, constituent: str | None = None) -> Any:
        """CQL 檢索，例如 `ti=battery and pa=tsmc`、`pn=TW201644272`。constituent 可為 biblio、abstract、full-cycle。"""
        if not 1 <= start <= end or end - start > 99:
            raise OPSError("Range 一次最多 100 筆")
        path = "published-data/search" + (f"/{constituent}" if constituent else "")
        return self.get(path, {"q": cql, "Range": f"{start}-{end}"})

    def biblio(self, number: str, fmt: str = "auto", kind: str = "publication") -> Any:
        number, fmt = normalize_number(number, fmt)
        return self.get(f"published-data/{kind}/{fmt}/{number}/biblio")

    def abstract(self, number: str, fmt: str = "auto") -> Any:
        number, fmt = normalize_number(number, fmt)
        return self.get(f"published-data/publication/{fmt}/{number}/abstract")

    def claims(self, number: str, fmt: str = "auto") -> Any:
        number, fmt = normalize_number(number, fmt)
        return self.get(f"published-data/publication/{fmt}/{number}/claims")

    def description(self, number: str, fmt: str = "auto") -> Any:
        number, fmt = normalize_number(number, fmt)
        return self.get(f"published-data/publication/{fmt}/{number}/description")

    def legal(self, number: str, fmt: str = "auto") -> Any:
        """INPADOC 法律狀態。"""
        number, fmt = normalize_number(number, fmt)
        return self.get(f"legal/publication/{fmt}/{number}")

    def family(self, number: str, fmt: str = "auto", constituent: str | None = None) -> Any:
        """INPADOC 專利家族；constituent 可為 biblio 或 legal。"""
        number, fmt = normalize_number(number, fmt)
        path = f"family/publication/{fmt}/{number}" + (f"/{constituent}" if constituent else "")
        return self.get(path)

    def register(self, number: str, fmt: str = "auto", constituent: str = "biblio") -> Any:
        """歐洲專利註冊簿（EP 案審查歷程、程序事件）。constituent：biblio、events、procedural-steps。"""
        number, fmt = normalize_number(number, fmt)
        return self.get(f"register/publication/{fmt}/{number}/{constituent}")

    # ---- images（PDF）----
    def images_inquiry(self, number: str, fmt: str = "auto") -> Any:
        """查某件有哪些影像文件（FullDocument、Drawing、FirstPageClipping）與頁數，回傳含 link 路徑。"""
        number, fmt = normalize_number(number, fmt)
        return self.get(f"published-data/publication/{fmt}/{number}/images")

    def image_page(self, link: str, page: int, out_dir: Path | None = None) -> dict:
        """下載影像文件的一頁 PDF。link 來自 images_inquiry，例如 published-data/images/EP/1000000/A1/fullimage。"""
        link = link.strip("/")
        if not link.startswith("published-data/images/"):
            raise OPSError("link 必須是 images_inquiry 回傳的 published-data/images/… 路徑")
        if page < 1:
            raise OPSError("page 從 1 起算")
        url = f"{REST}/{link}.pdf"
        if self.dry_run:
            return {"dry_run": True, "url": url, "params": {"Range": str(page)}}
        wait = 6.0 - (time.time() - self._last_call)
        if wait > 0:
            time.sleep(wait)
        headers = {"Authorization": f"Bearer {self.token()}", "Accept": "application/pdf"}
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.get(url, params={"Range": str(page)}, headers=headers)
        self._last_call = time.time()
        if resp.status_code == 404:
            return {"not_found": True, "url": str(resp.url)}
        if resp.status_code != 200:
            raise OPSError(f"HTTP {resp.status_code}: {resp.text[:300]}")
        out_dir = out_dir or config.download_dir()
        out_dir.mkdir(parents=True, exist_ok=True)
        stem = re.sub(r"[^A-Za-z0-9]+", "_", link.removeprefix("published-data/images/")).strip("_")
        path = out_dir / f"{stem}_p{page:03d}.pdf"
        path.write_bytes(resp.content)
        return {"path": str(path), "bytes": len(resp.content), "page": page}

    def image_pages(self, link: str, pages: list[int], out_dir: Path | None = None, merge: bool = True) -> dict:
        """下載多頁並（可選）合併成一份 PDF。每頁一次呼叫，各算入每週 4GB。"""
        saved = [self.image_page(link, p, out_dir) for p in pages]
        result: dict[str, Any] = {"pages": saved}
        if self.dry_run or not merge:
            return result
        paths = [Path(s["path"]) for s in saved if "path" in s]
        if len(paths) > 1:
            from pypdf import PdfWriter

            writer = PdfWriter()
            for p in paths:
                writer.append(str(p))
            merged = paths[0].with_name(paths[0].name.rsplit("_p", 1)[0] + f"_p{pages[0]:03d}-{pages[-1]:03d}.pdf")
            with merged.open("wb") as fh:
                writer.write(fh)
            result["merged"] = str(merged)
        return result


def extract_image_docs(payload: Any) -> list[dict]:
    """把 images_inquiry 的 JSON 壓成 [{desc, link, pages, formats}]。"""
    try:
        inq = payload["ops:world-patent-data"]["ops:document-inquiry"]["ops:inquiry-result"]
    except (KeyError, TypeError):
        return []
    if isinstance(inq, dict):
        inq = [inq]
    docs = []
    for r in inq:
        inst = r.get("ops:document-instance") or []
        if isinstance(inst, dict):
            inst = [inst]
        for d in inst:
            fmts = d.get("ops:document-format-options", {}).get("ops:document-format", [])
            if isinstance(fmts, dict):
                fmts = [fmts]
            docs.append({
                "desc": d.get("@desc"),
                "link": d.get("@link"),
                "pages": int(d.get("@number-of-pages") or 0),
                "formats": [f.get("$") for f in fmts],
            })
    return docs


def parse_pages(spec: str, max_pages: int) -> list[int]:
    """'1-3,7' → [1,2,3,7]；'all' → 全部。"""
    if spec.strip().lower() == "all":
        return list(range(1, max_pages + 1))
    pages: list[int] = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            pages.extend(range(int(a), int(b) + 1))
        else:
            pages.append(int(part))
    pages = sorted({p for p in pages if 1 <= p <= (max_pages or 10**6)})
    if not pages:
        raise OPSError("沒有有效頁碼")
    return pages


def extract_search_hits(payload: Any) -> list[dict]:
    """把 OPS 檢索 JSON 壓成 [{country, number, kind, date}]；非預期結構時回空。"""
    try:
        wpd = payload["ops:world-patent-data"]
        docs = wpd["ops:biblio-search"]["ops:search-result"]["ops:publication-reference"]
    except (KeyError, TypeError):
        return []
    if isinstance(docs, dict):
        docs = [docs]
    hits = []
    for d in docs:
        ids = d.get("document-id") or {}
        if isinstance(ids, list):
            ids = next((i for i in ids if i.get("@document-id-type") == "docdb"), ids[0])
        hits.append({
            "country": (ids.get("country") or {}).get("$"),
            "number": (ids.get("doc-number") or {}).get("$"),
            "kind": (ids.get("kind") or {}).get("$"),
            "date": (ids.get("date") or {}).get("$"),
            "family_id": d.get("@family-id"),
        })
    return hits
