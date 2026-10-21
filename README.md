# tw-patent-mcp

<!-- mcp-name: io.github.aa0101181514/tw-patent-mcp -->

[English](README.en.md)

專利檢索 MCP 伺服器，串接經濟部智慧財產局全球專利檢索系統（GPSS）API 與歐洲專利局 Open Patent Services（EPO OPS）。

- GPSS：一次檢索台灣、美國、日本、歐洲、韓國、中國、WIPO 等 23 個資料庫的書目、摘要與請求項。
- EPO OPS：全球書目、INPADOC 法律狀態、專利家族、EP 與 WO 全文、歐洲專利註冊簿，以及公報原件 PDF。
- 伺服器端不呼叫任何語言模型，只做查詢、格式轉換與錯誤防護。

## 需要自備的憑證

兩組憑證都免費，需由使用者本人申請。本套件不提供共用憑證。

| 變數 | 取得方式 |
|---|---|
| `GPSS_USER_CODE` | 至 [GPSS API 說明頁](https://tiponet.tipo.gov.tw/gpss1/gpsskmc/gpssapi) 線上申請驗證碼。審核通過後以 Email 寄送，效期 365 日。 |
| `EPO_OPS_KEY`、`EPO_OPS_SECRET` | 至 [EPO Developer Portal](https://developers.epo.org/) 註冊，核准後在 My Apps 建立 app 取得 Consumer Key 與 Secret。 |

只設定其中一組也可以使用，對應的工具才會運作。

## 安裝

需要 [uv](https://docs.astral.sh/uv/)。

Claude Code：

```
claude mcp add tw-patent \
  -e GPSS_USER_CODE=你的驗證碼 \
  -e EPO_OPS_KEY=你的key \
  -e EPO_OPS_SECRET=你的secret \
  -- uvx tw-patent-mcp
```

Claude Desktop 的 `claude_desktop_config.json`：

```json
{
  "mcpServers": {
    "tw-patent": {
      "command": "uvx",
      "args": ["tw-patent-mcp"],
      "env": {
        "GPSS_USER_CODE": "你的驗證碼",
        "EPO_OPS_KEY": "你的key",
        "EPO_OPS_SECRET": "你的secret"
      }
    }
  }
}
```

不想把憑證寫進設定檔時，可改放在 `~/.config/tw-patent-mcp/.env`，格式見 [.env.example](.env.example)。

## 設定

| 環境變數 | 說明 |
|---|---|
| `GPSS_USER_CODE` | GPSS API 驗證碼 |
| `EPO_OPS_KEY`、`EPO_OPS_SECRET` | EPO OPS Consumer Key 與 Secret |
| `TW_PATENT_MCP_HOME` | 本機狀態資料夾，預設 `~/.tw-patent-mcp` |
| `TW_PATENT_MCP_DOWNLOAD_DIR` | PDF 下載位置，預設 `~/.tw-patent-mcp/downloads` |
| `TW_PATENT_MCP_ENV` | 指定 .env 檔路徑 |
| `TW_PATENT_MCP_DRY_RUN` | 設為 `1` 時只回傳請求網址，不實際送出 |

## 工具

| 工具 | 來源 | 用途 |
|---|---|---|
| `gpss_codes` | GPSS | 列出資料庫、檢索欄位與輸出欄位代碼 |
| `gpss_search` | GPSS | 跨 23 個資料庫檢索書目、摘要與請求項 |
| `gpss_get` | GPSS | 以公開公告號或申請號取得單筆資料 |
| `gpss_build_url` | GPSS | 只組出請求網址，用來檢查檢索條件 |
| `ops_search` | EPO OPS | CQL 全球書目檢索，回傳總筆數與命中清單 |
| `ops_biblio` | EPO OPS | 書目資料：標題、申請人、發明人、優先權、IPC/CPC、引證、摘要 |
| `ops_legal_status` | EPO OPS | INPADOC 法律狀態，依家族成員列事件 |
| `ops_family` | EPO OPS | INPADOC 專利家族成員清單 |
| `ops_fulltext` | EPO OPS | 請求項、說明書、摘要全文，限 EP、WO 與部分歐洲國家 |
| `ops_register` | EPO OPS | 歐洲專利註冊簿 |
| `ops_images` | EPO OPS | 列出公報原件、圖式、首頁等影像文件與頁數 |
| `ops_download_pdf` | EPO OPS | 逐頁下載公報 PDF，多頁自動合併 |

專利號照公報寫法輸入即可，例如 `TW201644272A`、`TWI700000B`、`TWM600000U`、`US10000000B2`、`EP1000000`。

`ops_search`、`ops_biblio`、`ops_legal_status`、`ops_family` 預設回傳壓平後的摘要，體積約為原始回應的一成到兩成；需要完整欄位時加 `raw=true`。

## 使用限制與防護

- GPSS 依上班、下班時段設有輸出筆數上限，超過會回傳提示文字。
- GPSS 回應驗證碼無效、過期或 IP 被擋時，本套件會寫入鎖檔並停止後續呼叫，避免持續以無效驗證碼查詢而遭封鎖。確認驗證碼可用後，刪除 `~/.tw-patent-mcp/gpss_lock` 即可恢復。新核發的驗證碼可能要隔日才生效。
- EPO OPS 免費額度為每週 4GB，並有每分鐘呼叫次數限制。本套件依 OPS 每次回應的節流燈號自動調整呼叫間隔，尚未取得燈號前每次間隔 6 秒。PDF 每頁計一次呼叫，下載前請先用 `ops_images` 確認頁數。

## 資料來源與使用責任

- 資料分別來自經濟部智慧財產局與歐洲專利局，僅供參考，請以各國專利局公告為準。
- 使用者須自行遵守智慧財產局對 GPSS 及網站資料的相關規定，以及 EPO OPS [Terms and Conditions](https://www.epo.org/en/service-support/ordering/ops-terms-and-conditions) 與 [Fair use charter](https://www.epo.org/en/service-support/ordering/fair-use)。
- 本套件與智慧財產局、歐洲專利局無隸屬或背書關係。

## 開發

```
uv sync
uv run pytest -q
```

## 授權

[Elastic License 2.0](LICENSE)。本專案為公開原始碼，非開放原始碼授權。
