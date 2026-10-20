# tw-patent-mcp

<!-- mcp-name: io.github.aa0101181514/tw-patent-mcp -->

[繁體中文](README.md)

An MCP server for patent search, built on the Taiwan Intellectual Property Office Global Patent Search System (GPSS) API and the European Patent Office Open Patent Services (EPO OPS).

- GPSS: search bibliographic data, abstracts and claims across 23 databases, including Taiwan, the US, Japan, Europe, Korea, China and WIPO.
- EPO OPS: worldwide bibliographic data, INPADOC legal status, patent families, EP and WO full text, the European Patent Register, and original publication PDFs.
- The server makes no language-model calls. It only queries, normalises output, and guards against API errors.

## Credentials you need

Both credentials are free and must be obtained by each user. This package does not ship shared credentials.

| Variable | How to get it |
|---|---|
| `GPSS_USER_CODE` | Apply online on the [GPSS API page](https://tiponet.tipo.gov.tw/gpss1/gpsskmc/gpssapi). The code is emailed after review and is valid for 365 days. |
| `EPO_OPS_KEY`, `EPO_OPS_SECRET` | Register at the [EPO Developer Portal](https://developers.epo.org/). After approval, create an app under My Apps to get the Consumer Key and Secret. |

You can configure only one of them. The matching tools will work.

## Install

Requires [uv](https://docs.astral.sh/uv/).

Claude Code:

```
claude mcp add tw-patent \
  -e GPSS_USER_CODE=your_code \
  -e EPO_OPS_KEY=your_key \
  -e EPO_OPS_SECRET=your_secret \
  -- uvx tw-patent-mcp
```

Claude Desktop `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "tw-patent": {
      "command": "uvx",
      "args": ["tw-patent-mcp"],
      "env": {
        "GPSS_USER_CODE": "your_code",
        "EPO_OPS_KEY": "your_key",
        "EPO_OPS_SECRET": "your_secret"
      }
    }
  }
}
```

To keep credentials out of client config, put them in `~/.config/tw-patent-mcp/.env`. See [.env.example](.env.example).

## Configuration

| Variable | Meaning |
|---|---|
| `GPSS_USER_CODE` | GPSS API verification code |
| `EPO_OPS_KEY`, `EPO_OPS_SECRET` | EPO OPS Consumer Key and Secret |
| `TW_PATENT_MCP_HOME` | Local state folder, default `~/.tw-patent-mcp` |
| `TW_PATENT_MCP_DOWNLOAD_DIR` | PDF download folder, default `~/.tw-patent-mcp/downloads` |
| `TW_PATENT_MCP_ENV` | Path to a specific .env file |
| `TW_PATENT_MCP_DRY_RUN` | Set to `1` to return request URLs without sending them |

## Tools

| Tool | Source | Purpose |
|---|---|---|
| `gpss_codes` | GPSS | List database, search-field and output-field codes |
| `gpss_search` | GPSS | Search bibliographic data, abstracts and claims across 23 databases |
| `gpss_get` | GPSS | Fetch one record by publication or application number |
| `gpss_build_url` | GPSS | Build the request URL only, to check query syntax |
| `ops_search` | EPO OPS | Worldwide CQL search |
| `ops_biblio` | EPO OPS | Bibliographic data with classifications, applicants and citations |
| `ops_legal_status` | EPO OPS | INPADOC legal status |
| `ops_family` | EPO OPS | INPADOC patent family |
| `ops_fulltext` | EPO OPS | Claims, description and abstract for EP, WO and some European countries |
| `ops_register` | EPO OPS | European Patent Register |
| `ops_images` | EPO OPS | List full documents, drawings and first pages with page counts |
| `ops_download_pdf` | EPO OPS | Download publication PDFs page by page and merge them |

Enter patent numbers as printed on the publication, for example `TW201644272A`, `TWI700000B`, `TWM600000U`, `US10000000B2` or `EP1000000`.

## Limits and safeguards

- GPSS caps output per time slot, with different limits in and outside office hours.
- If GPSS reports an invalid or expired code or a blocked IP, the package writes a lock file and stops further calls, so a bad code is not retried into an IP ban. Delete `~/.tw-patent-mcp/gpss_lock` once the code works. A newly issued code may only become active the next day.
- EPO OPS gives 4GB per week free and limits calls per minute. The package waits at least 6 seconds between calls. Each PDF page is one call, so check page counts with `ops_images` first.

## Data sources and responsibility

- Data comes from the Taiwan Intellectual Property Office and the European Patent Office. It is for reference only. Official gazettes prevail.
- Users must comply with TIPO's rules for GPSS and its website data, and with the EPO OPS [Terms and Conditions](https://www.epo.org/en/service-support/ordering/ops-terms-and-conditions) and [Fair use charter](https://www.epo.org/en/service-support/ordering/fair-use).
- This package is not affiliated with or endorsed by TIPO or the EPO.

## Development

```
uv sync
uv run pytest -q
```

## License

[Elastic License 2.0](LICENSE). This project is source-available, not open source.
