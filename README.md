# O'Reilly CLI

O'Reilly CLI is a local CLI and MCP wrapper on top of the original O'Reilly download/export tool. It keeps the original plugin-based export engine and adds scriptable workflows for authenticated book export, playlist resolution, resumable playlist runs, and local MCP access.

> Requires a valid O'Reilly Learning subscription.

This repository is maintained as the `brxcybr/oreilly-cli` fork. User-facing paths, examples, and local service names use `oreilly-cli`; inherited plugin/module names are left intact where they make upstream comparison and future updates easier.

For the full command reference and troubleshooting notes, see [docs/CLI_AND_MCP.md](docs/CLI_AND_MCP.md).

## Scope

This tool is for personal, authorized use with content your O'Reilly Learning session can access. It does not automate username/password login, extract browser cookie databases, bypass DRM, bypass account limits, bypass paywalls, or expose a public service.

The wrapper adds:

- `oreilly_cli.py` for one-shot and interactive local CLI workflows.
- `mcp_server.py` for local stdio MCP clients.
- Cookie import helpers that avoid printing cookie values.
- Book ID, ISBN, book URL, and playlist URL resolution.
- Playlist manifests that allow interrupted exports to resume.

## Install

```bash
git clone https://github.com/brxcybr/oreilly-cli.git
cd oreilly-cli
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Optional web UI:

```bash
python main.py
```

Then open `http://localhost:8000`.

## Cookie Setup

Open `https://learning.oreilly.com` in your browser and confirm you are signed in. Open the browser DevTools console and run:

```javascript
copy(JSON.stringify(
  document.cookie
    .split(';')
    .map(c => {
      const [k, ...v] = c.split('=');
      return [k.trim(), v.join('=').trim()];
    })
    .reduce((r, [k, v]) => ({ ...r, [k]: v }), {})
))
```

That copies a JSON cookie object to your system clipboard. Import it with:

```bash
python oreilly_cli.py -c ~/.oreilly-cli/cookies.json login -l
```

Validate the session:

```bash
python oreilly_cli.py -c ~/.oreilly-cli/cookies.json status
```

If clipboard import is not available on your platform, pipe the clipboard into stdin:

```bash
pbpaste | python oreilly_cli.py -c ~/.oreilly-cli/cookies.json login -s
```

The importer accepts JSON cookie objects, browser cookie arrays, or raw `Cookie:` headers. Cookie files are written with owner-only permissions where the platform allows it.

## CLI Usage

Common short flags:

| Flag | Meaning |
|------|---------|
| `-c` | Cookie file path. If a directory is provided, `cookies.json` is appended. |
| `-o` | Output directory. |
| `-f` | Export format. |
| `-l` | Login/import cookies from clipboard. |
| `-m` | Max resolved playlist items. |
| `-k` | Keepalive interval in seconds. |
| `-n` | Dry run. |
| `-r` | Resume completed playlist items from the manifest. |
| `-x` | Skip images. |

Run the interactive menu:

```bash
python oreilly_cli.py menu
```

List formats:

```bash
python oreilly_cli.py formats
```

Search:

```bash
python oreilly_cli.py search "python concurrency" --limit 10
```

Resolve a book URL:

```bash
python oreilly_cli.py resolve \
  "https://learning.oreilly.com/library/view/azure-data-factory/9798868802188/"
```

Export a book:

```bash
python oreilly_cli.py \
  -c ~/.oreilly-cli/cookies.json \
  -o "$HOME/Documents/OReillyExports" \
  export 9798868802188 \
  -f markdown
```

Export with fresh cookies in the same command:

```bash
python oreilly_cli.py \
  -c ~/.oreilly-cli/cookies.json \
  -o "$HOME/Documents/OReillyExports" \
  export 9798868802188 \
  -l \
  -f markdown
```

## Playlist Resume

Playlist URLs are supported. Documentation examples use a placeholder UUID; do not commit real private playlist IDs.

Dry-run a playlist:

```bash
python oreilly_cli.py \
  -c ~/.oreilly-cli/cookies.json \
  export "https://learning.oreilly.com/playlists/00000000-0000-4000-8000-000000000000/" \
  -f markdown \
  -m 10 \
  -n
```

Run a capped playlist export:

```bash
python oreilly_cli.py \
  -c ~/.oreilly-cli/cookies.json \
  -o "$HOME/Documents/OReillyExports" \
  export "https://learning.oreilly.com/playlists/00000000-0000-4000-8000-000000000000/" \
  -l \
  -f markdown \
  -k 300 \
  -m 10 \
  --output-style combined \
```

Playlist exports write these files in the selected output directory:

- `playlist-<playlist-id>-isbns.json`
- `playlist-<playlist-id>-isbns.csv`

If an export is interrupted, refresh cookies in the browser, copy them with the console command above, and rerun with `--resume`:

```bash
python oreilly_cli.py \
  -c ~/.oreilly-cli/cookies.json \
  -o "$HOME/Documents/OReillyExports" \
  export "https://learning.oreilly.com/playlists/00000000-0000-4000-8000-000000000000/" \
  -l \
  -f markdown \
  -k 300 \
  -r \
  --output-style combined \
```

Completed playlist items from the manifest are skipped.

## MCP Server

The MCP server is local stdio only. It wraps the same plugin kernel and does not return cookies, auth headers, JWTs, or full book/chapter bodies through tool responses.

Run directly:

```bash
python /absolute/path/to/oreilly-cli/mcp_server.py
```

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

Tools:

| Tool | Purpose |
|------|---------|
| `oreilly_status` | Check safe session status. |
| `oreilly_list_formats` | List supported export formats. |
| `oreilly_search` | Search books and return concise metadata. |
| `oreilly_get_book` | Return metadata and chapter list without full chapter contents. |
| `oreilly_export_book` | Export one authorized book and return generated file paths. |

## Output And Hygiene

Common outputs:

| Export | Typical output |
|--------|----------------|
| Combined Markdown | `<output>/<book-slug>/<Book Title>.md` |
| Separate Markdown | `<output>/<book-slug>/Markdown/` |
| EPUB/PDF/text/JSON/chunks | Files under the book output directory |
| Playlist manifest | `playlist-<playlist-id>-isbns.json` and `.csv` |

## Testing

```bash
python -m unittest discover -s tests
python -m compileall oreilly_cli.py mcp_server.py config.py cli core plugins tests
```

## License

MIT
