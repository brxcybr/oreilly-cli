# O'Reilly CLI

We're in the AI era. You want to chat with your favorite technical books using Claude Code, Cursor, or any LLM tool. This gets you there.

Export any O'Reilly book to Markdown, PDF, EPUB, JSON, or plain text. Download by chapters so you don't burn through your context window.

> Requires a valid O'Reilly Learning subscription.

For detailed documentation on the CLI, non-interactive source resolution, cookie handling, MCP server, testing, and troubleshooting, see [docs/CLI_AND_MCP.md](docs/CLI_AND_MCP.md).

## Disclaimer

For personal and educational use only. Please read the [O'Reilly Terms of Service](https://www.oreilly.com/terms/).

## Credits

Inspired by [safaribooks](https://github.com/lorenzodifuccia/safaribooks) by [@lorenzodifuccia](https://github.com/lorenzodifuccia).

This repository is maintained as the `brxcybr/oreilly-cli` fork. User-facing paths, examples, and local service names use `oreilly-cli`; inherited plugin/module names are left intact where they make upstream comparison and future update work clearer.


## Features

- **Export by chapters** - save tokens, focus on what matters
- **LLM-ready formats** - Markdown, JSON, plain text optimized for AI
- **Traditional formats** - PDF and EPUB 3
- **O'Reilly V2 API** - fast and reliable
- **Images & styles included** - complete book experience
- **Web UI** - search, preview, download

<img src="docs/main.png" alt="Main Page">

## Quick Start

### Docker

```bash
git clone https://github.com/brxcybr/oreilly-cli.git
cd oreilly-cli
docker compose up -d
```

### Python

```bash
git clone https://github.com/brxcybr/oreilly-cli.git
cd oreilly-cli
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python main.py
```

Then open http://localhost:8000

## Setting Up Cookies

Click "Set Cookies" in the web interface and follow the steps:

<img src="docs/cookie-modal.png" alt="Cookie Setup" style="max-width:320px; height:auto;">

## CLI Usage

Full CLI documentation is available in [docs/CLI_AND_MCP.md](docs/CLI_AND_MCP.md).

The CLI runs as a one-shot or interactive local process. Docker and the web UI do not need to be running.

```bash
python oreilly_cli.py menu
```

On startup, menu mode checks the current session. If cookies are missing or expired, it shows browser DevTools instructions, waits for pasted cookie data, stores it locally, validates the session, and then opens menu options for search, metadata lookup, export, formats, status, and cookie refresh.

Menu cookie refresh defaults to reading from the system clipboard so long cookie strings do not need to be pasted into a terminal prompt. The export menu accepts book IDs, ISBNs, book URLs, and playlist URLs; when the source is a playlist, it offers manifest-backed resume.

You can also use direct commands:

```bash
python oreilly_cli.py status
python oreilly_cli.py login
python oreilly_cli.py formats
python oreilly_cli.py search "python concurrency" --limit 10
python oreilly_cli.py book 9781492056355
python oreilly_cli.py export 9781492056355 --format markdown --output-dir ~/Documents/OReillyExports
```

Non-interactive source resolution is also supported. Sources can be book IDs, ISBNs, O'Reilly book URLs, or O'Reilly playlist URLs. Playlist resolution uses authenticated JSON endpoints first and can fall back to the playlist page's server-rendered state when needed.

Playlist examples use a placeholder UUID. Replace it with your own private playlist ID locally; do not publish restricted playlist IDs.

```bash
python oreilly_cli.py resolve \
  "https://learning.oreilly.com/library/view/azure-data-factory/9798868802188/"

python oreilly_cli.py export \
  "https://learning.oreilly.com/library/view/azure-data-factory/9798868802188/" \
  --format markdown

python oreilly_cli.py export \
  9798868802188 9781492056355 \
  --format epub \
  --continue-on-error

python oreilly_cli.py export \
  "https://learning.oreilly.com/playlists/00000000-0000-4000-8000-000000000000/" \
  --format markdown \
  --max-items 10 \
  --dry-run

python oreilly_cli.py \
  --cookies-file ~/.oreilly-cli/cookies.json \
  export "https://learning.oreilly.com/playlists/00000000-0000-4000-8000-000000000000/" \
  --login-clipboard \
  --format markdown \
  --output-style combined \
  --keepalive-interval 300 \
  --output-dir "$HOME/iCloud/Training/Data Engineering/books"
```

Exports from multiple sources are serialized and capped by `--max-items` to avoid unattended mass export behavior. Use `--dry-run` to inspect resolved books before exporting a playlist.

Playlist exports write a durable manifest before the first book download starts:

- `playlist-<playlist-id>-isbns.json`
- `playlist-<playlist-id>-isbns.csv`

The manifest is stored in the destination folder and includes each resolved ISBN, title, status, output directory, and any failure message. During export the CLI updates the manifest as books move through `pending`, `in_progress`, `completed`, or `failed`. If a long playlist run times out, rerun the same command with `--resume` and fresh cookies; completed entries from the manifest will be skipped.

Cookie input can be pasted interactively or piped from stdin:

```javascript
copy(document.cookie)
```

```bash
python oreilly_cli.py --cookies-file ~/.oreilly-cli/cookies.json login --clipboard
python oreilly_cli.py --cookies-file ~/.oreilly-cli/cookies.json login --file ~/Downloads/oreilly-cookies.json
```

`--clipboard` and `--login-clipboard` detect the host OS and try the native clipboard reader: `pbpaste` on macOS, PowerShell `Get-Clipboard -Raw` on Windows and WSL, `wl-paste` on Wayland Linux, and `xclip` or `xsel` on X11 Linux.

If you prefer stdin, pipe from the clipboard command for your platform:

```bash
# macOS
pbpaste | python oreilly_cli.py --cookies-file ~/.oreilly-cli/cookies.json login --stdin

# Windows PowerShell
Get-Clipboard -Raw | python oreilly_cli.py --cookies-file ~/.oreilly-cli/cookies.json login --stdin

# Linux Wayland
wl-paste | python oreilly_cli.py --cookies-file ~/.oreilly-cli/cookies.json login --stdin

# Linux X11
xclip -selection clipboard -out | python oreilly_cli.py --cookies-file ~/.oreilly-cli/cookies.json login --stdin
```

For one-shot exports, pass fresh cookies directly to `export` with `--login-stdin`, `--login-clipboard`, or `--login-file`. The CLI imports and validates the cookies before starting the export in the same process.

During long exports, `--keepalive-interval` performs real authenticated profile requests. If O'Reilly rotates usable auth cookies in a response, the CLI persists the updated non-Akamai cookies back to the configured cookie file so the active export can keep using them. This is best-effort; it cannot recover an already expired browser session token.

For large cookie blobs, prefer `--stdin`, `--clipboard`, or `--file`. Terminal interactive paste can hit line-buffer limits before the CLI receives the full cookie data.

Supported cookie input formats:

- raw `Cookie:` header copied from browser DevTools
- JSON object, such as `{"orm-jwt": "..."}`
- JSON array of browser cookie objects with `name` and `value` fields

Credential handling:

- Cookie values are never printed back to the terminal.
- Cookie files are written with `0600` permissions where possible.
- Cookie directories are written with `0700` permissions where possible.
- The CLI checks authentication before search, metadata, and export operations.
- If the session expires, rerun `login` or choose cookie refresh in `menu`.

Configuration precedence:

1. CLI flags: `--cookies-file`, `--output-dir`
2. Environment variables: `OREILLY_COOKIES_FILE`, `OREILLY_OUTPUT_DIR`
3. Existing repo defaults

Common output layout:

| Export | Typical output |
|--------|----------------|
| Combined Markdown | `<output>/<book-slug>/<Book Title>.md` |
| Separate Markdown | `<output>/<book-slug>/Markdown/` |
| EPUB/PDF/text/JSON/chunks | Files under the book's output directory |
| Playlist resume manifest | `playlist-<playlist-id>-isbns.json` and `.csv` in the selected output directory |

Before publishing changes publicly, keep local cookie files, exported books, playlist manifests, raw browser captures, and real restricted playlist IDs out of git. The repository ignores common local credential/output paths, but you should still review `git status --short` before committing.

## Architecture

Plugin-based microkernel design:

| Layer | Components |
|-------|------------|
| **Kernel** | Plugin registry, shared HTTP client |
| **Core** | Auth, Book, Chapters, Assets, HtmlProcessor |
| **Output** | Epub, Markdown, Pdf, PlainText, JsonExport |
| **Utility** | Chunking, Token, Downloader |

### API

```
GET  /api/status       - auth check
GET  /api/search?q=    - find books
GET  /api/book/{id}    - metadata
POST /api/download     - start export
GET  /api/progress     - SSE stream
```

## Local MCP Server

Full MCP documentation is available in [docs/CLI_AND_MCP.md](docs/CLI_AND_MCP.md).

This clone also includes a local-only stdio MCP server at `mcp_server.py`. It is intended for personal, authorized use with a valid O'Reilly Learning subscription. The MCP server wraps the existing plugin kernel; it does not expose cookies, JWTs, headers, or book/chapter text through MCP responses.

Install dependencies:

```bash
pip install -r requirements.txt
```

Run the server directly:

```bash
python /absolute/path/to/oreilly-cli/mcp_server.py
```

Available tools:

| Tool | Purpose |
|------|---------|
| `oreilly_status` | Check whether the stored session appears valid. |
| `oreilly_list_formats` | List supported export formats from the downloader plugin. |
| `oreilly_search` | Search for books and return concise metadata only. |
| `oreilly_get_book` | Return book metadata and chapter list without chapter bodies. |
| `oreilly_export_book` | Export one authorized book and return generated file paths. |

Optional environment variables:

| Variable | Purpose |
|----------|---------|
| `OREILLY_COOKIES_FILE` | Path to the local cookies JSON file. Defaults to the existing repo behavior. |
| `OREILLY_OUTPUT_DIR` | Default export directory. Defaults to `output/` in the repo. |

When `OREILLY_COOKIES_FILE` is set, the MCP wrapper attempts to keep the cookie directory at `0700` and the cookie file at `0600` where possible. It never prints or returns cookie contents. If authentication is missing or expired, refresh cookies manually through your browser and rerun the existing cookie-import workflow.

Example MCP client configuration:

```json
{
  "mcpServers": {
    "oreilly-cli": {
      "command": "python",
      "args": ["/absolute/path/to/oreilly-cli/mcp_server.py"],
      "env": {
        "OREILLY_COOKIES_FILE": "/Users/<user>/.oreilly-cli/cookies.json",
        "OREILLY_OUTPUT_DIR": "/Users/<user>/Documents/OReillyExports"
      }
    }
  }
}
```

Exports are serialized in-process so a single MCP server process runs only one export at a time.

## Contributing

Found a bug or have an idea? PRs and issues are always welcome!


## Recent Changes

- **Chunking: streaming & memory fix** — `chunk_book()` now streams chunks directly to disk instead of accumulating in memory. Replaced `tiktoken` tokenizer with a word-count heuristic to avoid memory spikes on large books. (@zirkleta)
- **System: command injection fix** — `_show_macos_picker()` rejects paths containing `"` before interpolating into osascript, preventing command injection via crafted directory names. (@zirkleta)
- **`patch_chunk_titles.py`** — New utility script that backfills `book_title` into existing `*_chunks.jsonl` files in the output directory. (@zirkleta)

## License

MIT

## Star History

<picture>
  <source
    media="(prefers-color-scheme: dark)"
    srcset="
      https://api.star-history.com/svg?repos=brxcybr/oreilly-cli&type=Date&theme=dark
    "
  />
  <source
    media="(prefers-color-scheme: light)"
    srcset="
      https://api.star-history.com/svg?repos=brxcybr/oreilly-cli&type=Date
    "
  />
  <img
    alt="Star History Chart"
    src="https://api.star-history.com/svg?repos=brxcybr/oreilly-cli&type=Date"
  />
</picture>
