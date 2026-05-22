# Changelog

All notable changes to this fork are tracked here. Release entries follow
semantic versioning and should be updated before tagging.

## [Unreleased]

- No unreleased changes yet.

## [0.1.0] - 2026-05-22

### Added

- CLI/MCP wrapper documentation for authenticated O'Reilly search and export workflows.
- Cross-platform cookie import from clipboard, stdin, and files.
- Playlist source resolution, playlist manifests, resume support, and compact CLI flags.
- `repair-links` command for auditing or rewriting generated Markdown and chunk JSONL links.
- Runtime link repair for downloaded books, including Markdown links and chunk `chapter_filename` fields.
- Release checklist and release verification script.

### Fixed

- Default chunking now terminates at the final chunk and uses bounded overlap so short chapters do not generate repeated near-duplicate JSONL records.
- Generated Markdown and chunk links are normalized to local `OEBPS/...` targets where possible.

### Verified

- Unit test and compile gates pass locally.
- Live chunks export smoke reduced a prior multi-GB JSONL output to a bounded 62-record chunk file for `9781098120672`.
