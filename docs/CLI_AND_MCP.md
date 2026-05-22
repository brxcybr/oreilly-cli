# CLI and MCP Fork Guide

This fork adds two local automation surfaces on top of the existing O'Reilly Ingest plugin kernel:

- `oreilly_cli.py`: a one-shot and interactive command-line interface.
- `mcp_server.py`: a local stdio MCP server for MCP-compatible desktop clients.

Both paths use the same underlying repository code for authentication checks, search, metadata retrieval, format discovery, and export. They do not run Docker, do not require the web UI to stay open, and do not expose cookies, JWTs, auth headers, or full book text through command metadata responses.

## Scope and Guardrails

This fork is intended for personal, authorized use with a valid O'Reilly Learning subscription. It does not implement username/password login automation, browser-cookie database extraction, DRM bypass, paywall bypass, account-limit bypass, bot-protection bypass, or public network service exposure.

The CLI and MCP wrappers:

- use stored session cookies only after the user manually provides them;
- never print cookie values back to the terminal or MCP client;
- write cookie files with `0600` permissions where possible;
- write cookie directories with `0700` permissions where possible;
- use authenticated JSON endpoints for playlist resolution first, with a server-rendered playlist state fallback;
- serialize exports within a process;
- cap batch playlist export with `--max-items`;
- reject chapter selection for book-only formats such as `epub` and `chunks`.

## Installation

From the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

The CLI can then be run directly:

```bash
python oreilly_cli.py --help
```

The MCP server can be run directly by an MCP client:

```bash
python /absolute/path/to/oreilly-ingest-cli/mcp_server.py
```

## Recommended First Run

For a fresh checkout, use this sequence:

```bash
python oreilly_cli.py --help
python oreilly_cli.py --cookies-file ~/.oreilly-ingest/cookies.json login
python oreilly_cli.py --cookies-file ~/.oreilly-ingest/cookies.json status
python oreilly_cli.py --cookies-file ~/.oreilly-ingest/cookies.json formats
python oreilly_cli.py --cookies-file ~/.oreilly-ingest/cookies.json search "python" --limit 3
```

After authentication is working, run a small dry run before exporting content:

```bash
python oreilly_cli.py \
  --cookies-file ~/.oreilly-ingest/cookies.json \
  export 9798868802188 \
  --format markdown \
  --dry-run
```

## Configuration

Configuration can be supplied through command flags, environment variables, or repository defaults.

Precedence:

1. CLI flags: `--cookies-file`, `--output-dir`
2. Environment variables: `OREILLY_COOKIES_FILE`, `OREILLY_OUTPUT_DIR`
3. Existing repo defaults from `config.py`

Recommended local paths:

```bash
export OREILLY_COOKIES_FILE="$HOME/.oreilly-ingest/cookies.json"
export OREILLY_OUTPUT_DIR="$HOME/Documents/OReillyExports"
```

You can add those exports to your shell profile if you want the paths to be reused automatically.

## Cookie Workflow

The fork intentionally does not automate browser login or extract browser cookies from protected browser storage. The supported workflow is:

1. Open `https://learning.oreilly.com` in your browser.
2. Confirm you are signed in.
3. Open browser DevTools.
4. Run the browser-console copy command below, or find an O'Reilly request and copy its `Cookie` request header.
5. Paste the cookie data into the CLI.

Browser-console copy command:

```javascript
copy(document.cookie)
```

That command copies a raw cookie string, which the CLI and web modal both accept. If your browser or account setup omits a required cookie from `document.cookie`, copy the request `Cookie` header from an authenticated O'Reilly network request instead.

Interactive import:

```bash
python oreilly_cli.py login
```

System clipboard import:

```bash
python oreilly_cli.py --cookies-file ~/.oreilly-ingest/cookies.json login --clipboard
```

`--clipboard` detects the host OS and tries the native clipboard reader: `pbpaste` on macOS, PowerShell `Get-Clipboard -Raw` on Windows and WSL, `wl-paste` on Wayland Linux, and `xclip` or `xsel` on X11 Linux.

Clipboard-to-stdin import examples:

```bash
# macOS
pbpaste | python oreilly_cli.py --cookies-file ~/.oreilly-ingest/cookies.json login --stdin

# Windows PowerShell
Get-Clipboard -Raw | python oreilly_cli.py --cookies-file ~/.oreilly-ingest/cookies.json login --stdin

# Linux Wayland
wl-paste | python oreilly_cli.py --cookies-file ~/.oreilly-ingest/cookies.json login --stdin

# Linux X11
xclip -selection clipboard -out | python oreilly_cli.py --cookies-file ~/.oreilly-ingest/cookies.json login --stdin
```

File import:

```bash
python oreilly_cli.py --cookies-file ~/.oreilly-ingest/cookies.json login --file ~/Downloads/oreilly-cookies.json
```

For large cookie blobs, prefer `--stdin`, `--clipboard`, or `--file`. Terminal interactive paste can hit line-buffer limits before the CLI receives the complete cookie data.

Supported cookie input formats:

```text
Cookie: orm-jwt=...; csrftoken=...
```

```json
{
  "orm-jwt": "...",
  "csrftoken": "..."
}
```

```json
[
  {"name": "orm-jwt", "value": "..."},
  {"name": "csrftoken", "value": "..."}
]
```

The importer filters out known Akamai bot-management cookies that the existing HTTP client already avoids sending. This is intentional because those cookies are tied to browser/TLS behavior and should not be replayed by the CLI.

If a token or cookie is accidentally pasted into a public place, refresh your browser session and replace the stored cookie file.

## CLI Command Reference

All CLI commands are available from:

```bash
python oreilly_cli.py <command>
```

Global options:

| Option | Purpose |
|--------|---------|
| `--cookies-file PATH` | Use a specific local cookies JSON file. |
| `--output-dir PATH` | Use a specific export directory. |
| `--json` | Print machine-readable JSON for supported commands. |

Global options can be supplied before the subcommand or, for convenience, after the subcommand:

```bash
python oreilly_cli.py --output-dir ~/Documents/OReillyExports export 9798868802188 --format pdf
python oreilly_cli.py export 9798868802188 --format pdf --output-dir ~/Documents/OReillyExports
```

### `menu`

Starts the interactive menu:

```bash
python oreilly_cli.py menu
```

Menu mode checks authentication on startup. If the session is missing or expired, it prompts for fresh cookie data, validates the session, then opens options for search, metadata lookup, export, format listing, status, and cookie refresh.

For cookie refresh, menu mode defaults to reading the system clipboard. This avoids the common terminal limitation where a very long cookie string cannot be pasted cleanly into an interactive input line. Manual paste and file import remain available from the menu.

For export, menu mode accepts a book ID, ISBN, book URL, or playlist URL. If the source is a playlist, it asks whether to resume completed items from the destination manifest.

### `login`

Imports pasted cookie data and validates the session:

```bash
python oreilly_cli.py login
python oreilly_cli.py login --clipboard
python oreilly_cli.py login --file ~/Downloads/oreilly-cookies.json
```

### `status`

Checks whether the stored session appears valid:

```bash
python oreilly_cli.py status
python oreilly_cli.py --json status
```

The status output may include JWT expiry if the existing repository can safely derive it from the stored `orm-jwt` cookie. It does not include cookie values.

### `formats`

Lists formats from `DownloaderPlugin.get_formats_info()`:

```bash
python oreilly_cli.py formats
python oreilly_cli.py --json formats
```

Supported format names currently include:

| Format | Output | Notes |
|--------|--------|-------|
| `epub` | EPUB 3 book file | Whole-book only. |
| `markdown` | One combined Markdown file | Default style for Markdown exports. Alias: `md`. |
| `markdown-chapters` | Separate Markdown files under `Markdown/` | Used by `--output-style separate`. |
| `pdf` | One combined PDF file | Default style for PDF exports. |
| `pdf-chapters` | Separate PDF files | Used by `--output-style separate`. |
| `plaintext` | One combined text export | Alias: `txt`. |
| `plaintext-chapters` | Separate text files | Used by `--output-style separate`. |
| `json` | Structured JSON export | Useful for downstream tooling. |
| `jsonl` | JSON Lines export plus JSON | Selecting `jsonl` also includes `json`. |
| `chunks` | Chunked text for RAG/LLM workflows | Whole-book only; controlled by `--chunk-size` and `--chunk-overlap`. |

The special format value `all` expands to `epub`, `markdown`, `pdf`, `plaintext`, `json`, and `chunks`.

Aliases:

- `md` -> `markdown`
- `txt` -> `plaintext`

### `search`

Searches O'Reilly books through the existing book plugin:

```bash
python oreilly_cli.py search "python concurrency" --limit 10
python oreilly_cli.py --json search "azure data factory" --limit 5
```

Search results return concise metadata: title, author list, book ID, URL, and content type. They do not include chapter or book body text.

### `book`

Fetches metadata and chapter list for a book:

```bash
python oreilly_cli.py book 9798868802188
```

The direct `book` command expects a book ID today. For URL/ISBN resolution before export, use `resolve` or `export`, described below.

### `resolve`

Resolves known source forms into exportable book IDs:

```bash
python oreilly_cli.py resolve 9798868802188
python oreilly_cli.py resolve "https://learning.oreilly.com/library/view/azure-data-factory/9798868802188/"
python oreilly_cli.py resolve "https://learning.oreilly.com/playlists/00000000-0000-4000-8000-000000000000/" --max-items 10
```

Supported source forms:

- direct O'Reilly book/archive IDs;
- ISBN-like numeric identifiers;
- O'Reilly book URLs;
- O'Reilly playlist URLs.

Playlist resolution uses authenticated JSON endpoints first. If those private endpoint shapes fail, the resolver fetches the playlist page and reads its server-rendered `initialStoreData` state as a fallback.

Playlist IDs can identify restricted user-owned resources. Documentation and tests use a placeholder UUID; keep real playlist IDs in local commands, not committed examples.

### `export`

Exports one or more authorized books serially:

```bash
python oreilly_cli.py export 9798868802188 --format markdown
```

Export from a book URL:

```bash
python oreilly_cli.py export \
  "https://learning.oreilly.com/library/view/azure-data-factory/9798868802188/" \
  --format markdown
```

Export multiple known identifiers:

```bash
python oreilly_cli.py export \
  9798868802188 9781492056355 \
  --format epub \
  --continue-on-error
```

Resolve a playlist without exporting:

```bash
python oreilly_cli.py export \
  "https://learning.oreilly.com/playlists/00000000-0000-4000-8000-000000000000/" \
  --format markdown \
  --max-items 10 \
  --dry-run
```

Export a capped number of playlist items:

```bash
python oreilly_cli.py export \
  "https://learning.oreilly.com/playlists/00000000-0000-4000-8000-000000000000/" \
  --format markdown \
  --max-items 5
```

Import fresh cookies and export in a single command:

```bash
python oreilly_cli.py \
  --cookies-file ~/.oreilly-ingest/cookies.json \
  export "https://learning.oreilly.com/playlists/00000000-0000-4000-8000-000000000000/" \
  --login-clipboard \
  --format markdown \
  --output-style combined \
  --keepalive-interval 300 \
  --output-dir "$HOME/iCloud/Training/Data Engineering/books"
```

Playlist exports write `playlist-<playlist-id>-isbns.json` and `playlist-<playlist-id>-isbns.csv` into the destination folder before downloads begin. The manifest is updated after each book start, success, or failure, so it can be used as the recovery list for a later run.

The JSON manifest is the durable resume source. It contains:

| Field | Meaning |
|-------|---------|
| `kind` | Constant marker: `oreilly_playlist_manifest`. |
| `playlist_ids` | Playlist UUIDs represented in this manifest. |
| `total` | Number of resolved unique books. |
| `books[].position` | Resolved playlist order after dedupe and `--max-items`. |
| `books[].playlist_id` | Source playlist UUID. |
| `books[].isbn` / `books[].book_id` | Export identifier used by the downloader. |
| `books[].title` | Resolved title when available. |
| `books[].status` | `pending`, `in_progress`, `completed`, or `failed`. |
| `books[].output_dir` | Final book output directory after success. |
| `books[].generated_files` | Generated file paths by format after success. |
| `books[].error` | Sanitized failure message after a failed item. |

The CSV manifest is a compact human-readable ISBN list with position, playlist ID, ISBN, title, status, output directory, and error columns.

### Output Layout

Each exported book gets its own directory under the selected output directory. The folder name is based on the book title and includes a `.book_id` marker for same-title conflict handling.

Common generated paths:

| Export | Typical output |
|--------|----------------|
| Combined Markdown | `<output>/<book-slug>/<Book Title>.md` |
| Separate Markdown | `<output>/<book-slug>/Markdown/README.md` and per-chapter `.md` files |
| EPUB | `<output>/<book-slug>/<Book Title>.epub` |
| PDF | `<output>/<book-slug>/<Book Title>.pdf` or per-chapter PDFs |
| Plain text | `<output>/<book-slug>/...txt` |
| JSON/JSONL | Structured export files under the book directory |
| Chunks | RAG-oriented chunk files under the book directory |
| Assets | `<output>/<book-slug>/OEBPS/Images` and `<output>/<book-slug>/OEBPS/Styles` unless `--skip-images` is used |

Playlist manifests are written at the top level of the selected output directory, not inside a single book directory.

Export options:

| Option | Purpose |
|--------|---------|
| `--format FORMAT` | Export format. Repeat or comma-separate. Defaults to `epub`. |
| `--chapters 0,1,2` | Export selected zero-based chapter indexes where supported. |
| `--output-style combined\|separate` | Write combined output or separate chapter files where supported. Defaults to `combined`. |
| `--separate` | Shortcut for `--output-style separate`. |
| `--skip-images` | Do not download images. |
| `--login-stdin` | Import fresh cookies from stdin before validating and exporting. |
| `--login-clipboard` | Import fresh cookies from the system clipboard before validating and exporting. |
| `--login-file PATH` | Import fresh cookies from a file before validating and exporting. |
| `--keepalive-interval N` | Send best-effort authenticated keepalive checks during export and persist rotated non-Akamai auth cookies when O'Reilly returns them. |
| `--max-items N` | Cap resolved sources, especially playlists. Defaults to 20. |
| `--dry-run` | Resolve sources but do not export. |
| `--resume` | For playlist exports, skip items already marked `completed` in the destination manifest. |
| `--continue-on-error` | Continue after a failed export. |

Chapter selection is rejected for book-only formats (`epub`, `chunks`) because the existing downloader applies chapter filtering before format generation.

Keepalive cannot revive a token that is already expired before the command starts. For long playlist exports, import fresh cookies in the same command with `--login-stdin`, `--login-clipboard`, or `--login-file`.

Recommended recovery workflow after a timeout or expired cookie:

1. Refresh the O'Reilly browser page and copy fresh cookies.
2. Rerun the same playlist export command with `--login-stdin` or `--login-clipboard`.
3. Add `--resume` so the CLI reads the destination manifest and skips `completed` books.
4. Leave `--continue-on-error` off if you want the command to stop at the next failure; add it if you want the remaining unresolved books to keep running.

Resume example after a timeout:

```bash
python oreilly_cli.py \
  --cookies-file ~/.oreilly-ingest/cookies.json \
  export "https://learning.oreilly.com/playlists/00000000-0000-4000-8000-000000000000/" \
  --login-clipboard \
  --format markdown \
  --output-style combined \
  --keepalive-interval 300 \
  --resume \
  --output-dir "$HOME/iCloud/Training/Data Engineering/books"
```

## Common Workflows

### Export One Book as Combined Markdown

```bash
python oreilly_cli.py \
  --cookies-file ~/.oreilly-ingest/cookies.json \
  export 9798868802188 \
  --format markdown \
  --output-style combined \
  --output-dir "$HOME/Documents/OReillyExports"
```

### Export One Book as Separate Chapter Files

```bash
python oreilly_cli.py \
  --cookies-file ~/.oreilly-ingest/cookies.json \
  export 9798868802188 \
  --format markdown \
  --output-style separate \
  --output-dir "$HOME/Documents/OReillyExports"
```

### Export All Supported Book-Level Outputs

```bash
python oreilly_cli.py \
  --cookies-file ~/.oreilly-ingest/cookies.json \
  export 9798868802188 \
  --format all \
  --output-dir "$HOME/Documents/OReillyExports"
```

### Export RAG Chunks

```bash
python oreilly_cli.py \
  --cookies-file ~/.oreilly-ingest/cookies.json \
  export 9798868802188 \
  --format chunks \
  --chunk-size 4000 \
  --chunk-overlap 200 \
  --output-dir "$HOME/Documents/OReillyExports"
```

### Export Without Downloading Images

```bash
python oreilly_cli.py \
  --cookies-file ~/.oreilly-ingest/cookies.json \
  export 9798868802188 \
  --format markdown \
  --skip-images \
  --output-dir "$HOME/Documents/OReillyExports"
```

## MCP Server Reference

The MCP server is local stdio only. It is not a LAN-facing or public HTTP service.

Run directly:

```bash
python /absolute/path/to/oreilly-ingest-cli/mcp_server.py
```

Example client configuration:

```json
{
  "mcpServers": {
    "oreilly-ingest": {
      "command": "python",
      "args": ["/absolute/path/to/oreilly-ingest-cli/mcp_server.py"],
      "env": {
        "OREILLY_COOKIES_FILE": "/Users/<user>/.oreilly-ingest/cookies.json",
        "OREILLY_OUTPUT_DIR": "/Users/<user>/Documents/OReillyExports"
      }
    }
  }
}
```

Tools:

| Tool | Purpose |
|------|---------|
| `oreilly_status` | Returns safe auth/session status and optional expiry. |
| `oreilly_list_formats` | Returns supported formats from the downloader source of truth. |
| `oreilly_search` | Searches books and returns concise metadata. |
| `oreilly_get_book` | Returns book metadata and chapter list without full chapter contents. |
| `oreilly_export_book` | Exports one authorized book and returns generated file paths. |

MCP responses intentionally avoid inline book/chapter text. Export tools return file paths only.

## Public Repo Hygiene

Before publishing changes to a public repository:

- do not commit `cookies.json`, cookie exports, `.env` files, private keys, or generated book output;
- do not commit raw browser captures or restricted playlist pages under `ref/`;
- do not commit real playlist UUIDs in examples, docs, tests, or fixtures;
- use placeholder playlist UUIDs such as `00000000-0000-4000-8000-000000000000` in public documentation;
- verify `git status --short` before staging;
- scan staged changes for JWT-shaped strings, API keys, private keys, and restricted playlist IDs.

This repository's `.gitignore` and `.dockerignore` exclude common local credential files, generated playlist manifests, raw reference captures, and exported book output, but you should still review staged changes before pushing.

## Architecture

The fork keeps the CLI and MCP wrappers thin:

| Capability | Existing implementation used |
|------------|------------------------------|
| Auth/session status | `AuthPlugin.get_status()`, `AuthPlugin.validate_session()`, `HttpClient.get_jwt_status()` |
| Search | `BookPlugin.search()` |
| Metadata | `BookPlugin.fetch()` |
| Chapters/TOC | `ChaptersPlugin.fetch_list()`, `ChaptersPlugin.fetch_toc()` |
| Formats | `DownloaderPlugin.get_formats_info()` |
| Export | `DownloaderPlugin.download()` |
| Output paths | `OutputPlugin.validate_dir()`, `OutputPlugin.create_book_dir()` |

New wrapper modules:

| File | Purpose |
|------|---------|
| `oreilly_cli.py` | Root CLI entry point. |
| `cli/main.py` | CLI command handlers and interactive menu. |
| `cli/cookies.py` | Cookie parsing, filtering, and secure local writes. |
| `cli/resolver.py` | Source resolution for book IDs, ISBNs, URLs, and playlists. |
| `mcp_server.py` | Local stdio MCP server. |

## Testing

Run all unit tests:

```bash
python -m unittest discover -s tests
```

Run a syntax/import check:

```bash
python -m compileall oreilly_cli.py mcp_server.py config.py cli core plugins tests
```

Current tests cover:

- cookie parsing from raw headers, JSON objects, and JSON arrays;
- cookie file permissions;
- format validation;
- chapter-selection validation;
- auth prompt flow with mocks;
- source resolution for book URLs, ISBNs, and playlist-shaped JSON;
- playlist manifest generation and resume status preservation;
- keepalive-safe cookie rotation persistence;
- MCP validation and secret redaction helpers.

Live integration tests are intentionally not included with real credentials. To validate live behavior manually:

```bash
python oreilly_cli.py login
python oreilly_cli.py status
python oreilly_cli.py search "python" --limit 3
python oreilly_cli.py export <BOOK_ID> --format markdown --dry-run
python oreilly_cli.py export <BOOK_ID> --format markdown
```

## Troubleshooting

### `Authenticated: no`

Refresh cookies in the browser and rerun:

```bash
python oreilly_cli.py login
```

### Pasted cookies fail to parse

Use one of the supported formats:

- raw `Cookie:` request header;
- JSON object of cookie name/value pairs;
- JSON array with `name` and `value` fields.

Avoid shell `echo` for large cookie JSON because quoting can corrupt JSON. Prefer:

```bash
python oreilly_cli.py login --clipboard
```

### Playlist does not resolve

Playlist resolution depends on authenticated JSON endpoint shapes. Run:

```bash
python oreilly_cli.py resolve "<playlist-url>" --max-items 5
```

If it returns no books, use direct book URLs or IDs from the playlist as a fallback.

### Chapter selection fails

Chapter selection is only valid for formats that support partial output. Do not combine `--chapters` with `epub` or `chunks`.

### Export fails midway

For non-playlist sources, use:

```bash
python oreilly_cli.py export <sources...> --continue-on-error
```

For playlist sources, prefer the manifest-backed resume flow:

```bash
python oreilly_cli.py \
  --cookies-file ~/.oreilly-ingest/cookies.json \
  export "<playlist-url>" \
  --login-clipboard \
  --format markdown \
  --resume \
  --output-dir "$HOME/Documents/OReillyExports"
```

Failures are reported per source. The CLI does not print cookie values in errors.
