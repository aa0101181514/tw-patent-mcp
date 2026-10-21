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


# 每次回應的 X-Throttling-Control 形如
#   busy (images=green:100, inpadoc=green:45, other=green:1000, retrieval=green:100, search=green:15)
# 括號內是各服務目前每分鐘允許次數；沒看到標頭前一律保守等 6 秒。
DEFAULT_INTERVAL = 6.0
MIN_INTERVAL = {"search": 1.0, "inpadoc": 1.0, "images": 0.5, "retrieval": 0.5, "other": 0.5}
QUOTA_HEADERS = ("x-throttling-control", "x-registeredquotaperweek-used", "x-individualquotaperhour-used")
_THROTTLE_RE = re.compile(r"(\w+)=(\w+):(\d+)")


def parse_throttle(header: str | None) -> dict[str, tuple[str, int]]:
    """'busy (images=green:100, search=green:15)' → {'images': ('green', 100), 'search': ('green', 15)}。"""
    if not header:
        return {}
    return {m.group(1): (m.group(2), int(m.group(3))) for m in _THROTTLE_RE.finditer(header)}


def service_of(path: str) -> str:
    """OPS 路徑對應到節流服務名。"""
    if path.startswith("published-data/search"):
        return "search"
    if path.startswith("published-data/images"):
        return "images"
    if path.startswith(("legal/", "family/")):
        return "inpadoc"
    if path.startswith("published-data/"):
        return "retrieval"
    return "other"


def interval_for(service: str, throttle: dict[str, tuple[str, int]]) -> float:
    """依燈號算兩次呼叫的最小間隔（秒）。紅燈或額度 0 時等一分鐘。"""
    if service not in throttle:
        return DEFAULT_INTERVAL
    color, per_minute = throttle[service]
    if color == "red" or per_minute <= 0:
        return 60.0
    return max(60.0 / per_minute, MIN_INTERVAL.get(service, 1.0))


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
        self._throttle: dict[str, tuple[str, int]] = {}

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
    def _wait(self, service: str) -> None:
        if not self._last_call:
            return
        wait = interval_for(service, self._throttle) - (time.time() - self._last_call)
        if wait > 0:
            time.sleep(wait)

    def _request(self, url: str, params: dict[str, Any] | None, accept: str, service: str) -> httpx.Response:
        """送出請求；token 被 OPS 判為失效時清掉重取一次。"""
        self._wait(service)
        headers = {"Accept": accept, "User-Agent": config.user_agent()}
        with httpx.Client(timeout=self.timeout) as client:
            for attempt in (1, 2):
                headers["Authorization"] = f"Bearer {self.token()}"
                resp = client.get(url, params=params, headers=headers)
                self._last_call = time.time()
                if attempt == 1 and resp.status_code in (400, 401) and "invalid_access_token" in resp.text:
                    self._token = None
                    continue
                break
        throttle = parse_throttle(resp.headers.get("x-throttling-control"))
        if throttle:
            self._throttle = throttle
        return resp

    @staticmethod
    def _quota(resp: httpx.Response) -> dict[str, str]:
        return {k: v for k, v in resp.headers.items() if k.lower() in QUOTA_HEADERS}

    def get(self, path: str, params: dict[str, Any] | None = None, accept: str = "application/json") -> Any:
        path = path.lstrip("/")
        url = f"{REST}/{path}"
        if self.dry_run:
            return {"dry_run": True, "url": url, "params": params or {}}
        resp = self._request(url, params, accept, service_of(path))
        quota = self._quota(resp)
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
        resp = self._request(url, {"Range": str(page)}, "application/pdf", "images")
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
        result = payload["ops:world-patent-data"]["ops:biblio-search"]["ops:search-result"]
    except (KeyError, TypeError):
        return []
    if "exchange-documents" in result:  # constituent=biblio／abstract 時整份書目都在
        return [summarize_document(d) for d in _docs_in(result)]
    hits = []
    for d in _as_list(result.get("ops:publication-reference")):
        ids = _docdb(d.get("document-id"))
        hits.append({
            "country": _s(ids.get("country")),
            "number": _s(ids.get("doc-number")),
            "kind": _s(ids.get("kind")),
            "date": _s(ids.get("date")),
            "family_id": d.get("@family-id"),
        })
    return hits


def search_total(payload: Any) -> int | None:
    try:
        return int(payload["ops:world-patent-data"]["ops:biblio-search"]["@total-result-count"])
    except (KeyError, TypeError, ValueError):
        return None


# ---------------- 壓平 OPS JSON ----------------
# OPS 把 XML 轉成 JSON：文字在 "$"、屬性在 "@xxx"、單一元素是 dict、多個是 list。


def _as_list(node: Any) -> list[dict]:
    if node is None:
        return []
    if isinstance(node, dict):
        return [node]
    return [n for n in node if isinstance(n, dict)]


def _s(node: Any) -> str | None:
    if isinstance(node, dict):
        v = node.get("$")
        return str(v).strip() if v is not None else None
    if isinstance(node, (str, int, float)):
        return str(node).strip()
    return None


def _docdb(ids: Any) -> dict:
    """document-id 可能有 docdb／epodoc／original 三種，優先 docdb。"""
    items = _as_list(ids)
    if not items:
        return {}
    return next((i for i in items if i.get("@document-id-type") == "docdb"), items[0])


def _doc_number(ids: Any) -> str | None:
    d = _docdb(ids)
    if not d:
        return None
    cc, num, kind = _s(d.get("country")), _s(d.get("doc-number")), _s(d.get("kind"))
    if cc and num:
        return f"{cc}{num}{kind or ''}"
    return num


def _ref(ref: Any) -> dict:
    """publication-reference／application-reference → {number, date}。"""
    ids = (ref or {}).get("document-id")
    out = {"number": _doc_number(ids), "date": _s(_docdb(ids).get("date"))}
    return {k: v for k, v in out.items() if v}


def _names(node: Any, key: str, name_key: str) -> list[str]:
    """parties 內的 applicant／inventor：同一人有 epodoc 與 original 兩種格式，只取 epodoc。"""
    items = _as_list((node or {}).get(key))
    chosen = [i for i in items if i.get("@data-format") == "epodoc"] or items
    out: list[str] = []
    for i in chosen:
        name = _s(((i.get(name_key) or {}).get("name")))
        if name and name not in out:
            out.append(name)
    return out


def _ipc(text: str | None) -> str | None:
    """'B28B   1/    29            A I' → 'B28B 1/29'。"""
    if not text:
        return None
    parts = text.split()
    if len(parts) >= 3 and parts[1].endswith("/"):
        return f"{parts[0]} {parts[1]}{parts[2]}"
    return " ".join(parts[:3])


def _cpc(c: dict) -> str | None:
    pieces = [_s(c.get(k)) for k in ("section", "class", "subclass", "main-group")]
    sub = _s(c.get("subgroup"))
    if not all(pieces):
        return None
    return "".join(pieces) + (f"/{sub}" if sub else "")


def _priority(node: Any) -> list[str]:
    out = []
    for p in _as_list((node or {}).get("priority-claim")):
        d = _docdb(p.get("document-id"))
        label = " ".join(x for x in (_s(d.get("country")), _s(d.get("doc-number")), _s(d.get("date"))) if x)
        if label:
            out.append(label)
    return out


def _citations(node: Any) -> list[dict]:
    out = []
    for c in _as_list((node or {}).get("citation")):
        pat = c.get("patcit")
        if pat:
            d = _docdb(pat.get("document-id"))
            item = {
                "number": _doc_number(pat.get("document-id")),
                "date": _s(d.get("date")),
                "applicant": _s(d.get("name")),
            }
        else:
            npl = c.get("nplcit") or {}
            item = {"npl": _s(npl.get("text"))}
        item.update({
            "category": _s(c.get("category")),
            "cited_by": c.get("@cited-by"),
            "phase": c.get("@cited-phase"),
            "claims": _s(c.get("rel-claims")),
        })
        out.append({k: v for k, v in item.items() if v})
    return out


def _lang_texts(node: Any) -> dict[str, str]:
    out: dict[str, str] = {}
    for t in _as_list(node):
        lang = t.get("@lang") or "und"
        if "p" in t:
            text = "\n".join(x for x in (_s(p) for p in _as_list(t.get("p"))) if x)
        else:
            text = _s(t) or ""
        if text:
            out[lang] = text
    return out


def _docs_in(container: Any) -> list[dict]:
    return _as_list(((container or {}).get("exchange-documents") or {}).get("exchange-document"))


def summarize_document(doc: dict) -> dict:
    """一份 exchange-document → 扁平書目。"""
    b = doc.get("bibliographic-data") or {}
    parties = b.get("parties") or {}
    rec = {
        "publication": _ref(b.get("publication-reference")),
        "application": _ref(b.get("application-reference")),
        "family_id": doc.get("@family-id"),
        "title": _lang_texts(b.get("invention-title")),
        "applicants": _names(parties.get("applicants"), "applicant", "applicant-name"),
        "inventors": _names(parties.get("inventors"), "inventor", "inventor-name"),
        "priority": _priority(b.get("priority-claims")),
        "ipc": [x for x in (_ipc(_s(c.get("text"))) for c in _as_list((b.get("classifications-ipcr") or {}).get("classification-ipcr"))) if x],
        "cpc": list(dict.fromkeys(x for x in (_cpc(c) for c in _as_list((b.get("patent-classifications") or {}).get("patent-classification"))) if x)),
        "citations": _citations(b.get("references-cited")),
        "abstract": _lang_texts(doc.get("abstract")),
    }
    return {k: v for k, v in rec.items() if v not in (None, "", [], {})}


def summarize_biblio(payload: Any) -> list[dict]:
    """ops_biblio 的回傳 → [書目]；結構不符時回空。"""
    try:
        docs = _docs_in(payload["ops:world-patent-data"])
    except (KeyError, TypeError):
        return []
    return [summarize_document(d) for d in docs]


def _legal_events(member: dict) -> list[dict]:
    events = []
    for e in _as_list(member.get("ops:legal")):
        details: dict[str, str] = {}
        for k, v in e.items():
            if not k.startswith("ops:L") or not isinstance(v, dict):
                continue
            if "$" in v:
                if k == "ops:L007EP":
                    details["gazette_date"] = _s(v) or ""
            else:  # L500EP 之類的巢狀明細
                for k2, v2 in v.items():
                    if isinstance(v2, dict) and v2.get("@desc"):
                        details[v2["@desc"]] = _s(v2) or ""
        rec = {
            "date": details.pop("gazette_date", None),
            "code": (e.get("@code") or "").strip(),
            "desc": e.get("@desc"),
            "effect": (e.get("@infl") or "").strip() or None,
            "details": details,
        }
        events.append({k: v for k, v in rec.items() if v not in (None, "", {})})
    return events


def summarize_legal(payload: Any) -> dict:
    """INPADOC 法律狀態 → {members: [{publication, application, events: [...]}]}。"""
    try:
        fam = payload["ops:world-patent-data"]["ops:patent-family"]
    except (KeyError, TypeError):
        return {}
    members = []
    for m in _as_list(fam.get("ops:family-member")):
        members.append({
            "family_id": m.get("@family-id"),
            "publication": _ref(m.get("publication-reference")),
            "application": _ref(m.get("application-reference")),
            "events": _legal_events(m),
        })
    return {"members": members}


def summarize_family(payload: Any) -> dict:
    """INPADOC 家族 → {total, members: [{publication, application, priority, representative}]}。"""
    try:
        fam = payload["ops:world-patent-data"]["ops:patent-family"]
    except (KeyError, TypeError):
        return {}
    members = []
    for m in _as_list(fam.get("ops:family-member")):
        app = m.get("application-reference") or {}
        rec = {
            "family_id": m.get("@family-id"),
            "publication": _ref(m.get("publication-reference")),
            "application": _ref(app),
            "representative": app.get("@is-representative") == "YES" or None,
            "priority": _priority(m),
        }
        if "ops:legal" in m:
            rec["events"] = _legal_events(m)
        members.append({k: v for k, v in rec.items() if v not in (None, "", [], {})})
    total = fam.get("@total-result-count")
    return {"total": int(total) if total else len(members), "members": members}
