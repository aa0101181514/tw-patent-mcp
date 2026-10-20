"""智慧局 GPSS 全球專利檢索系統 API（依智慧局 API 說明文件 v1.4）。

單一端點 GET gpss_api，參數以 & 串接。欄位內用 and/or/not；跨欄位預設 AND，
OR 在參數前加 +，NOT 加 -。不支援切截與字距運算。
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

from . import config

BASE_URL = "https://tiponet.tipo.gov.tw/gpss1/gpsskmc/gpss_api"

DATABASES: dict[str, str] = {
    "TWA": "中華民國公開（2003~）", "TWB": "中華民國公告（1950~）", "TWD": "中華民國設計（1964~）",
    "USA": "美國公開（2001~）", "USB": "美國公告（1790~）", "USD": "美國設計（1976~）",
    "JPA": "日本公開（1971~，無全文）", "JPB": "日本公告（1913~）", "JPD": "日本意匠（2000~）",
    "EPA": "歐洲公開（1978~）", "EPB": "歐洲公告（1980~）", "EUIPO": "歐盟設計（2003~）",
    "KPA": "韓國公開（1999~，無全文）", "KPB": "韓國公告（1974~，無全文）", "KPD": "韓國設計（1998~）",
    "CNA": "中國大陸公開（1985~）", "CNB": "中國大陸公告（1985~）", "CND": "中國大陸外觀設計（1985~）",
    "WO": "WIPO 公開（1978~）",
    "SEAA": "東南亞公開（無全文）", "SEAB": "東南亞公告（無全文）",
    "OTA": "其他國家公開（無全文）", "OTB": "其他國家公告（無全文）",
}

SEARCH_FIELDS: dict[str, str] = {
    "PN": "公開/公告號", "ID": "公開/公告日", "AN": "申請號", "AD": "申請日",
    "AX": "申請人名", "AF": "第一申請人名", "AY": "申請人國別", "AZ": "第一申請人國別",
    "IV": "發明人名", "IY": "發明人國別", "LX": "代理人名", "EX": "審查委員",
    "PR": "優先權", "DR": "優先權日", "IC": "IPC", "FC": "第一IPC", "CS": "CPC", "TS": "第一CPC",
    "IQ": "LOC", "FI": "FI", "FT": "F-TERM", "IR": "D-TERM", "UC": "USPC",
    "TI": "專利名稱", "AB": "摘要", "CL": "專利範圍", "CI": "引用專利",
    "TI/AB": "專利名稱/摘要", "TI/AB/CL": "專利名稱/摘要/專利範圍",
}

OUTPUT_FIELDS: dict[str, str] = {
    "PN": "公開/公告號", "ID": "公開/公告日", "AN": "申請號", "AD": "申請日", "TI": "專利名稱",
    "PA": "申請人", "IN": "發明人", "LX": "代理人", "EX": "審查委員", "PR": "優先權",
    "AB": "摘要", "IC": "IPC", "IQ": "LOC", "CS": "CPC", "UC": "USPC", "FI": "FI",
    "FT": "F-TERM", "IR": "D-TERM", "CI": "引用專利", "CL": "專利範圍",
}
DEFAULT_OUTPUT = ["PN", "ID", "AN", "AD", "TI", "PA", "IN", "IC", "AB"]
FULL_OUTPUT = list(OUTPUT_FIELDS)

# 官方「回傳訊息說明」。前三種與驗證碼有關：一旦出現就停手，連打會封整機 IP。
FATAL_MESSAGES = ("userCode not exist", "userCode expired", "IP blocked")
KNOWN_MESSAGES = {
    "No record found": "查無結果",
    "expSkip too much": "跳躍筆數超過總筆數",
    "No search command": "未包含檢索條件",
    "Cannot use truncated and kerning in search conditions": "不可用切截或字距運算",
    "Exceeded search condition length": "檢索條件超出長度限制",
    "Over download quantity": "超出時段流量限制",
}



def lock_file() -> Path:
    return config.gpss_lock_file()


class GPSSError(RuntimeError):
    pass


class GPSSFatal(GPSSError):
    """驗證碼無效／過期／IP 被封。發生後寫入鎖檔，本機不得再呼叫，直到人工解除。"""


@dataclass
class Query:
    """一次 GPSS 檢索。conditions 的 key 是欄位代碼，可帶 + 或 - 前綴表示跨欄位 OR / NOT。"""

    conditions: dict[str, str]
    databases: list[str] = field(default_factory=list)
    status: list[str] = field(default_factory=list)  # A 公開, B 公告
    kind: list[str] = field(default_factory=list)  # I 發明, M 新型, D 設計
    output: list[str] = field(default_factory=lambda: list(DEFAULT_OUTPUT))
    fmt: str = "json"
    qty: int = 30
    skip: int = 0

    def validate(self) -> None:
        if not self.conditions:
            raise GPSSError("至少要有一個檢索條件（No search command）")
        for key, value in self.conditions.items():
            code = key.lstrip("+-")
            if code not in SEARCH_FIELDS:
                raise GPSSError(f"未知檢索欄位 {code}；可用：{', '.join(SEARCH_FIELDS)}")
            if any(ch in value for ch in "*?[]"):
                raise GPSSError("GPSS API 不支援切截（* ?）與字距（[n,m]）運算")
        for db in self.databases:
            if db not in DATABASES:
                raise GPSSError(f"未知資料庫 {db}；可用：{', '.join(DATABASES)}")
        for s in self.status:
            if s not in ("A", "B"):
                raise GPSSError("status 只能是 A（公開）或 B（公告）")
        for k in self.kind:
            if k not in ("I", "M", "D"):
                raise GPSSError("kind 只能是 I（發明）、M（新型）、D（設計）")
        for f in self.output:
            if f not in OUTPUT_FIELDS:
                raise GPSSError(f"未知輸出欄位 {f}；可用：{', '.join(OUTPUT_FIELDS)}")
        if self.fmt not in ("json", "xml"):
            raise GPSSError("fmt 只能是 json 或 xml")
        if not 1 <= self.qty <= 10000:
            raise GPSSError("qty 需在 1 至 10000 之間（單次上限 10,000 筆）")
        if self.skip < 0:
            raise GPSSError("skip 不得為負")

    def to_params(self, user_code: str) -> list[tuple[str, str]]:
        self.validate()
        params: list[tuple[str, str]] = [("userCode", user_code)]
        if self.databases:
            params.append(("patDB", ",".join(self.databases)))
        if self.status:
            params.append(("patAG", ",".join(self.status)))
        if self.kind:
            params.append(("patTY", ",".join(self.kind)))
        params.extend((k, v) for k, v in self.conditions.items())
        params.append(("expFld", ",".join(self.output)))
        params.append(("expFmt", self.fmt))
        params.append(("expQty", str(self.qty)))
        if self.skip:
            params.append(("expSkip", str(self.skip)))
        return params


def build_url(query: Query, user_code: str = "驗證碼") -> str:
    """組出 API 網址。+ 與 - 前綴和 / 必須保留原樣，所以自行編碼。"""
    parts = []
    for key, value in query.to_params(user_code):
        encoded = quote(value, safe=':,/') if key != "userCode" else value
        parts.append(f"{quote(key, safe='+-/')}={encoded}")
    return BASE_URL + "?" + "&".join(parts)


def _list(node: Any, key: str) -> list[dict]:
    if not node:
        return []
    items = node.get(key, [])
    if isinstance(items, dict):
        return [items]
    return list(items)


def _names(node: Any, key: str) -> list[str]:
    out = []
    for item in _list(node, key):
        name = item.get("name") or item.get("english-name") or item.get("keyValue")
        en = item.get("english-name")
        cc = item.get("country-code")
        label = name or ""
        if en and en != name:
            label += f"（{en}）"
        if cc:
            label += f"[{cc}]"
        if label:
            out.append(label)
    return out


def _values(node: Any, key: str) -> list[str]:
    return [item.get("keyValue", "") for item in _list(node, key) if item.get("keyValue")]


def parse_json(payload: dict) -> dict:
    """把 GPSS JSON 整理成扁平結構；錯誤訊息轉成例外。"""
    root = payload.get("gpss-API", payload)
    status = root.get("status", "")
    message = root.get("message", "") or ""
    if status != "success":
        for fatal in FATAL_MESSAGES:
            if fatal in message:
                lock = lock_file()
                lock.parent.mkdir(parents=True, exist_ok=True)
                lock.write_text(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}\n", encoding="utf-8")
                raise GPSSFatal(f"GPSS 拒絕：{message}。已寫入鎖檔 {lock}，請勿再試，先確認驗證碼。")
        human = next((KNOWN_MESSAGES[k] for k in KNOWN_MESSAGES if k in message), None)
        if "No record found" in message:
            return {"total": 0, "skip": 0, "returned": 0, "records": [], "message": message}
        raise GPSSError(f"GPSS 回傳 {status}: {message}" + (f"（{human}）" if human else ""))

    patent = root.get("patent") or {}
    records = []
    for pc in _list(patent, "patentcontent"):
        pub = pc.get("publication-reference") or {}
        app = pc.get("application-reference") or {}
        parties = pc.get("parties") or {}
        title = pc.get("patent-title") or {}
        abstract = pc.get("abstract") or {}
        claims = pc.get("claims") or {}
        rec = {
            "database": pc.get("@database"),
            "status": pc.get("@status"),
            "type": pc.get("@type"),
            "publication_number": pub.get("doc-number"),
            "publication_date": pub.get("date"),
            "application_number": app.get("doc-number"),
            "application_date": app.get("date"),
            "title": title.get("title"),
            "title_en": title.get("english-title"),
            "applicants": _names(parties.get("applicants"), "applicant"),
            "inventors": _names(parties.get("inventors"), "inventor"),
            "agents": _values(parties.get("agents"), "agent"),
            "examiners": _values(pc.get("examiners"), "examiner"),
            "priority": [
                f"{p.get('country','')} {p.get('doc-number','')} {p.get('date','')}".strip()
                for p in _list(pc.get("priority-claims"), "priority-claim")
            ],
            "ipc": _values(pc.get("classifications-ipc"), "ipc"),
            "cpc": _values(pc.get("classifications-cpc"), "cpc"),
            "loc": _values(pc.get("classifications-loc"), "loc"),
            "abstract": "\n".join(p for p in (abstract.get("p") or []) if isinstance(p, str)),
            "citations": _values(pc.get("references-cited"), "citation"),
            "claims": [
                {"num": c.get("@num"), "text": c.get("claim-text")} for c in _list(claims, "claim")
            ],
        }
        records.append({k: v for k, v in rec.items() if v not in (None, "", [], {})})
    return {
        "total": int(root.get("total-rec") or 0),
        "skip": int(root.get("skip") or 0),
        "returned": len(records),
        "created": patent.get("@create-date"),
        "records": records,
    }


class GPSSClient:
    def __init__(self, user_code: str, timeout: float = 60.0, dry_run: bool = False):
        if not user_code:
            raise GPSSError("缺 GPSS_USER_CODE")
        self.user_code = user_code
        self.timeout = timeout
        self.dry_run = dry_run

    def check_lock(self) -> None:
        lock = lock_file()
        if lock.exists():
            raise GPSSFatal(
                f"鎖檔 {lock} 存在（{lock.read_text(encoding='utf-8').strip()}）。"
                "上次呼叫被 GPSS 拒絕；確認驗證碼已生效後手動刪除鎖檔再試。"
            )

    def search(self, query: Query) -> dict:
        query.fmt = "json"
        url = build_url(query, self.user_code)
        if self.dry_run:
            return {"dry_run": True, "url": url.replace(self.user_code, "***")}
        self.check_lock()
        with httpx.Client(timeout=self.timeout, headers={"User-Agent": "patent-mcp/0.1"}) as client:
            resp = client.get(url)
        if resp.status_code != 200:
            raise GPSSError(f"HTTP {resp.status_code}（新驗證碼隔日才生效，期間會回 500）")
        try:
            payload = resp.json()
        except json.JSONDecodeError as exc:
            raise GPSSError(f"非 JSON 回應：{resp.text[:200]}") from exc
        result = parse_json(payload)
        result["url"] = url.replace(self.user_code, "***")
        return result
