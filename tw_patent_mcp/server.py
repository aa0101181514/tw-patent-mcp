"""MCP server：gpss_* 走智慧局 GPSS，ops_* 走 EPO OPS。stdio 啟動：tw-patent-mcp"""
from __future__ import annotations

import json
from typing import Any

from mcp.server.mcpserver import MCPServer

from . import __version__, config, epo_ops, gpss

config.load_env()
DRY_RUN = ((config.get("TW_PATENT_MCP_DRY_RUN") or config.get("PATENT_MCP_DRY_RUN")) or "").lower() in ("1", "true", "yes")

server = MCPServer(
    name="tw-patent-mcp",
    version=__version__,
    instructions=(
        "專利檢索工具。gpss_search 用智慧局 GPSS 查 23 個資料庫的書目、摘要、請求項（無法律狀態與全文）；"
        "ops_* 用 EPO OPS 查全球書目、INPADOC 法律狀態、專利家族、EP/WO 全文。"
        "GPSS 條件：欄位內用 and/or/not，不支援切截與字距；跨欄位預設 AND，OR 在欄位前加 +，NOT 加 -。"
        "額度有限：先用小 qty 試，確認命中再放大；一次檢索最多 10,000 筆。"
    ),
)

_gpss: gpss.GPSSClient | None = None
_ops: epo_ops.OPSClient | None = None


def _gpss_client() -> gpss.GPSSClient:
    global _gpss
    if _gpss is None:
        _gpss = gpss.GPSSClient(config.get("GPSS_USER_CODE") or "", dry_run=DRY_RUN)
    return _gpss


def _ops_client() -> epo_ops.OPSClient:
    global _ops
    if _ops is None:
        _ops = epo_ops.OPSClient(config.get("EPO_OPS_KEY") or "", config.get("EPO_OPS_SECRET") or "", dry_run=DRY_RUN)
    return _ops


def _dump(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=1)


# ---------------- GPSS ----------------
@server.tool(description="列出 GPSS 資料庫代碼、檢索欄位代碼與輸出欄位代碼。")
def gpss_codes() -> str:
    return _dump({"databases": gpss.DATABASES, "search_fields": gpss.SEARCH_FIELDS, "output_fields": gpss.OUTPUT_FIELDS})


@server.tool(
    description=(
        "智慧局 GPSS 檢索。conditions 是 {欄位代碼: 條件}，例如 "
        '{"TI/AB": "固態電池 or solid state battery", "AX": "台灣積體電路", "ID": "20200101:"}；'
        "欄位代碼前加 + 表示跨欄位 OR、加 - 表示 NOT。databases 例如 [\"TWA\",\"TWB\"]，空＝全部 23 庫。"
        "status：A 公開／B 公告；kind：I 發明／M 新型／D 設計。output 預設 PN,ID,AN,AD,TI,PA,IN,IC,AB，要請求項加 CL。"
    )
)
def gpss_search(
    conditions: dict[str, str],
    databases: list[str] | None = None,
    status: list[str] | None = None,
    kind: list[str] | None = None,
    output: list[str] | None = None,
    qty: int = 20,
    skip: int = 0,
) -> str:
    q = gpss.Query(
        conditions=conditions,
        databases=databases or [],
        status=status or [],
        kind=kind or [],
        output=output or list(gpss.DEFAULT_OUTPUT),
        qty=qty,
        skip=skip,
    )
    return _dump(_gpss_client().search(q))


@server.tool(description="用公開/公告號（PN）或申請號（AN）取單筆 GPSS 資料，含摘要與請求項。例：number=\"TW201644272A\"。")
def gpss_get(number: str, by: str = "PN", databases: list[str] | None = None) -> str:
    if by not in ("PN", "AN"):
        raise ValueError("by 只能是 PN 或 AN")
    q = gpss.Query(conditions={by: number}, databases=databases or [], output=list(gpss.FULL_OUTPUT), qty=5)
    return _dump(_gpss_client().search(q))


@server.tool(description="只組出 GPSS API 網址不送出（驗證碼以 *** 取代），用來檢查條件寫法。")
def gpss_build_url(
    conditions: dict[str, str],
    databases: list[str] | None = None,
    status: list[str] | None = None,
    kind: list[str] | None = None,
    output: list[str] | None = None,
    qty: int = 20,
    skip: int = 0,
) -> str:
    q = gpss.Query(conditions=conditions, databases=databases or [], status=status or [], kind=kind or [],
                   output=output or list(gpss.DEFAULT_OUTPUT), qty=qty, skip=skip)
    return gpss.build_url(q, "***")


# ---------------- EPO OPS ----------------
@server.tool(
    description=(
        "EPO OPS CQL 檢索（全球書目）。例：'ti=battery and pa=tsmc'、'pn=TW201644272'、'ipc=H01M10 and pd within \"2022 2024\"'。"
        "constituent 可為 biblio（含書目）或 abstract。一次最多 100 筆。"
    )
)
def ops_search(cql: str, start: int = 1, end: int = 25, constituent: str | None = None) -> str:
    payload = _ops_client().search(cql, start, end, constituent)
    hits = epo_ops.extract_search_hits(payload)
    return _dump({"hits": hits, "raw": payload} if hits else payload)


@server.tool(description="EPO OPS 書目資料（含 IPC/CPC、申請人、引證、家族 id）。number 照公報號寫即可，例：EP1000000、TW201644272A、TWI700000B、TWM600000U、US10000000B2；程式自動轉成 docdb 格式。")
def ops_biblio(number: str, fmt: str = "auto") -> str:
    return _dump(_ops_client().biblio(number, fmt))


@server.tool(description="EPO OPS INPADOC 法律狀態（有效、撤回、屆期、年費等事件）。")
def ops_legal_status(number: str, fmt: str = "auto") -> str:
    return _dump(_ops_client().legal(number, fmt))


@server.tool(description="EPO OPS INPADOC 專利家族；constituent 可為 biblio 或 legal。每秒最多 1 次。")
def ops_family(number: str, fmt: str = "auto", constituent: str | None = None) -> str:
    return _dump(_ops_client().family(number, fmt, constituent))


@server.tool(description="EPO OPS 全文：part 為 claims、description 或 abstract。全文只有 EP、WO 與部分歐洲國家。")
def ops_fulltext(number: str, part: str = "claims", fmt: str = "auto") -> str:
    c = _ops_client()
    fn = {"claims": c.claims, "description": c.description, "abstract": c.abstract}.get(part)
    if fn is None:
        raise ValueError("part 只能是 claims、description、abstract")
    return _dump(fn(number, fmt))


@server.tool(description="歐洲專利註冊簿（EP 案）：constituent 為 biblio、events 或 procedural-steps。")
def ops_register(number: str, constituent: str = "biblio", fmt: str = "auto") -> str:
    return _dump(_ops_client().register(number, fmt, constituent))


@server.tool(description="EPO OPS 影像清單：某件有哪些 PDF 文件（FullDocument 全件、Drawing 圖式、FirstPageClipping 首頁）與頁數。台灣、美國、歐洲等公報原件多數可取得。")
def ops_images(number: str, fmt: str = "auto") -> str:
    payload = _ops_client().images_inquiry(number, fmt)
    docs = epo_ops.extract_image_docs(payload)
    return _dump({"documents": docs, "raw": payload} if docs else payload)


@server.tool(
    description=(
        "下載 EPO OPS 影像 PDF。link 用 ops_images 回傳的 link（如 published-data/images/EP/1000000/A1/fullimage），"
        "pages 如 '1-5' 或 'all'（需給 max_pages）。每頁一次呼叫並算入每週 4GB，先用 ops_images 看頁數再決定範圍。"
        "檔案存到 TW_PATENT_MCP_DOWNLOAD_DIR（預設 ~/.tw-patent-mcp/downloads），多頁自動合併。"
    )
)
def ops_download_pdf(link: str, pages: str = "1-3", max_pages: int = 0, merge: bool = True) -> str:
    page_list = epo_ops.parse_pages(pages, max_pages)
    if len(page_list) > 50:
        raise ValueError("一次最多 50 頁；超過請分批")
    return _dump(_ops_client().image_pages(link, page_list, merge=merge))


def main() -> None:
    server.run("stdio")


if __name__ == "__main__":
    main()
