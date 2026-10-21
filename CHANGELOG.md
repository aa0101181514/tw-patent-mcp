# Changelog

## 0.2.0 (2026-10-21)

- `ops_search`, `ops_biblio`, `ops_legal_status` and `ops_family` now return a flattened summary by default (roughly one tenth of the raw size). Pass `raw=true` for the original OPS JSON.
- `ops_search` with `constituent=biblio` or `abstract` now returns hits instead of an empty list, plus the total result count.
- EPO OPS call spacing follows the `X-Throttling-Control` header returned by OPS instead of a fixed 6 seconds. Page downloads for a 26-page gazette drop from about 2.5 minutes to under 20 seconds while the service is green.
- An OPS access token rejected as invalid is refreshed once automatically.
- Fixed GPSS single-paragraph abstracts being split into one character per line (the official JSON format returns a string, not an array, for a single paragraph). Multi-paragraph claim text is handled the same way.
- Tools carry MCP annotations (`readOnlyHint` etc.); only `ops_download_pdf` writes files.
- Quota information returned to the model is trimmed to usage and throttling headers.
- User-Agent now reports the package name and version.
- Tests: 34 (server dry run, OPS summaries against recorded samples, GPSS regression).

## 0.1.1 (2026-10-20)

- MCP registry `server.json` and `mcp-name` marker.

## 0.1.0 (2026-10-20)

- First release: 12 tools over Taiwan IPO GPSS and EPO OPS.
