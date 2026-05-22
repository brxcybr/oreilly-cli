"""Repair local links in generated Markdown and chunk exports."""

from __future__ import annotations

import json
import os
import posixpath
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit, urlunsplit

from .base import Plugin


@dataclass
class LinkRepairReport:
    """Summary of a link repair pass."""

    files_scanned: int = 0
    files_changed: int = 0
    links_seen: int = 0
    links_repaired: int = 0
    unresolved: list[dict[str, str]] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "files_scanned": self.files_scanned,
            "files_changed": self.files_changed,
            "links_seen": self.links_seen,
            "links_repaired": self.links_repaired,
            "unresolved": self.unresolved,
        }

    def merge(self, other: "LinkRepairReport") -> None:
        self.files_scanned += other.files_scanned
        self.files_changed += other.files_changed
        self.links_seen += other.links_seen
        self.links_repaired += other.links_repaired
        self.unresolved.extend(other.unresolved)


@dataclass
class _RepairContext:
    document_path: Path
    book_dir: Path


class LinkRepairPlugin(Plugin):
    """Normalize generated local links so they resolve from exported files."""

    MARKDOWN_LINK = re.compile(
        r"(?P<prefix>!?\[(?:[^\]]|\](?!\())*(?:\]\[[^\]]*)?\]\()"
        r"(?P<target>(?:\\.|[^()\n]|\([^)\n]*\))+)"
        r"(?P<suffix>\))"
    )
    HTML_ATTR = re.compile(r'(?P<prefix>\b(?:href|src)=["\'])(?P<target>[^"\']+)(?P<suffix>["\'])')
    LOCAL_SCHEMES = {"", "file"}
    SKIP_SCHEMES = {"http", "https", "mailto", "tel", "data", "javascript"}

    def __init__(self):
        self._basename_cache: dict[Path, dict[str, list[Path]]] = {}

    def repair_markdown(
        self,
        markdown: str,
        document_path: Path,
        book_dir: Path | None = None,
    ) -> tuple[str, LinkRepairReport]:
        """Repair Markdown and inline HTML links for one document."""
        context = _RepairContext(
            document_path=document_path,
            book_dir=book_dir or self._infer_book_dir(document_path),
        )
        report = LinkRepairReport(files_scanned=1)
        changed = False

        def replace_markdown(groups: dict[str, str]) -> str:
            nonlocal changed
            original = groups["target"]
            unresolved_before = len(report.unresolved)
            repaired = self._repair_target(original, context, report)
            if repaired == original and len(report.unresolved) > unresolved_before:
                external = self._external_url_from_markdown_prefix(groups["prefix"])
                if external:
                    report.unresolved.pop()
                    report.links_repaired += 1
                    repaired = external
            if repaired != original:
                changed = True
            return f"{groups['prefix']}{repaired}{groups['suffix']}"

        def replace_html(groups: dict[str, str]) -> str:
            nonlocal changed
            original = groups["target"]
            repaired = self._repair_target(original, context, report)
            if repaired != original:
                changed = True
            return f"{groups['prefix']}{repaired}{groups['suffix']}"

        markdown = self._replace_outside_code(markdown, self.MARKDOWN_LINK, replace_markdown)
        markdown = self._replace_outside_code(markdown, self.HTML_ATTR, replace_html)
        if changed:
            report.files_changed = 1
        return markdown, report

    def repair_chunk_record(
        self,
        chunk: dict,
        document_path: Path,
        book_dir: Path | None = None,
    ) -> tuple[dict, LinkRepairReport]:
        """Repair Markdown-style links and chapter references in one JSONL chunk."""
        context = _RepairContext(
            document_path=document_path,
            book_dir=book_dir or self._infer_book_dir(document_path),
        )
        report = LinkRepairReport(files_scanned=1)
        repaired = dict(chunk)
        changed = False

        content = repaired.get("content")
        if isinstance(content, str):
            repaired_content, content_report = self.repair_markdown(content, document_path, context.book_dir)
            report.links_seen += content_report.links_seen
            report.links_repaired += content_report.links_repaired
            report.unresolved.extend(content_report.unresolved)
            if repaired_content != content:
                repaired["content"] = repaired_content
                changed = True

        chapter_filename = repaired.get("chapter_filename")
        if isinstance(chapter_filename, str):
            repaired_filename = self._repair_target(chapter_filename, context, report)
            if repaired_filename != chapter_filename:
                repaired["chapter_filename"] = repaired_filename
                changed = True

        if changed:
            report.files_changed = 1
        return repaired, report

    def repair_markdown_file(self, path: Path, write: bool = False) -> LinkRepairReport:
        original = path.read_text(encoding="utf-8")
        repaired, report = self.repair_markdown(original, path)
        if write and repaired != original:
            path.write_text(repaired, encoding="utf-8")
        return report

    def repair_jsonl_file(self, path: Path, write: bool = False) -> LinkRepairReport:
        report = LinkRepairReport(files_scanned=1)
        changed = False
        lines: list[str] = []

        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                lines.append(line)
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                lines.append(line)
                continue
            if not isinstance(record, dict):
                lines.append(line)
                continue

            repaired, record_report = self.repair_chunk_record(record, path)
            report.links_seen += record_report.links_seen
            report.links_repaired += record_report.links_repaired
            report.unresolved.extend(record_report.unresolved)
            if repaired != record:
                changed = True
            lines.append(json.dumps(repaired, ensure_ascii=False))

        if changed:
            report.files_changed = 1
            if write:
                path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return report

    def repair_directory(self, path: Path, write: bool = False) -> LinkRepairReport:
        """Repair or audit Markdown and JSONL chunk files under a directory."""
        root = path.expanduser()
        report = LinkRepairReport()
        if root.is_file():
            files = [root]
        else:
            files = sorted(
                file_path
                for file_path in root.rglob("*")
                if file_path.is_file() and file_path.suffix.lower() in {".md", ".jsonl"}
            )

        for file_path in files:
            suffix = file_path.suffix.lower()
            if suffix == ".md":
                report.merge(self.repair_markdown_file(file_path, write=write))
            elif suffix == ".jsonl":
                report.merge(self.repair_jsonl_file(file_path, write=write))

        return report

    def _repair_target(self, target: str, context: _RepairContext, report: LinkRepairReport) -> str:
        parsed = self._split_target(target)
        if parsed is None:
            return target

        url, title = parsed
        pieces = urlsplit(url)
        scheme = pieces.scheme.lower()
        if scheme in self.SKIP_SCHEMES or scheme not in self.LOCAL_SCHEMES:
            return target
        if not pieces.path or pieces.path.startswith("#"):
            return target

        report.links_seen += 1
        resolved = self._resolve_local_path(unquote(pieces.path), context)
        if resolved is None:
            report.unresolved.append(
                {
                    "file": str(context.document_path),
                    "target": url,
                }
            )
            return target

        relative = self._relative_posix_path(resolved, context.document_path.parent)
        rebuilt = urlunsplit(("", "", relative, pieces.query, pieces.fragment))
        if rebuilt == url:
            return target
        report.links_repaired += 1
        if title:
            return f"{rebuilt}{title}"
        if target.startswith("<") and target.endswith(">"):
            return f"<{rebuilt}>"
        return rebuilt

    def _resolve_local_path(self, raw_path: str, context: _RepairContext) -> Path | None:
        normalized = self._normalize_local_path(raw_path)
        if not normalized:
            return None

        candidates = self._candidate_paths(normalized, context)
        for candidate in candidates:
            if candidate.exists():
                return candidate

        if normalized.lower().endswith(".html"):
            xhtml_path = normalized[:-5] + ".xhtml"
            for candidate in self._candidate_paths(xhtml_path, context):
                if candidate.exists():
                    return candidate

        basename = Path(normalized).name
        if basename:
            for candidate in (
                context.book_dir / "OEBPS" / "Images" / basename,
                context.book_dir / "OEBPS" / basename,
            ):
                if candidate.exists():
                    return candidate
            discovered = self._find_by_basename(basename, context.book_dir)
            if discovered is not None:
                return discovered

            if basename.lower().endswith(".html"):
                discovered = self._find_by_basename(basename[:-5] + ".xhtml", context.book_dir)
                if discovered is not None:
                    return discovered

        return None

    def _candidate_paths(self, path_text: str, context: _RepairContext) -> list[Path]:
        rel = Path(path_text)
        without_parent_refs = self._strip_parent_refs(path_text)
        candidates = [
            context.document_path.parent / rel,
            context.book_dir / rel,
            context.book_dir / "OEBPS" / rel,
        ]
        if without_parent_refs != path_text:
            stripped = Path(without_parent_refs)
            candidates.extend(
                [
                    context.book_dir / stripped,
                    context.book_dir / "OEBPS" / stripped,
                    context.book_dir / "OEBPS" / "OEBPS" / stripped,
                ]
            )
        if path_text.startswith(("Images/", "./Images/")):
            candidates.append(context.book_dir / "OEBPS" / rel)
        return candidates

    def _find_by_basename(self, basename: str, book_dir: Path) -> Path | None:
        cache = self._basename_cache.get(book_dir)
        if cache is None:
            cache = {}
            search_root = book_dir / "OEBPS"
            if search_root.exists():
                for candidate in search_root.rglob("*"):
                    if candidate.is_file():
                        cache.setdefault(candidate.name, []).append(candidate)
            self._basename_cache[book_dir] = cache

        matches = cache.get(basename, [])
        if len(matches) == 1:
            return matches[0]
        return None

    def _infer_book_dir(self, document_path: Path) -> Path:
        parent = document_path.parent
        if parent.name in {"Markdown", "Chunks"}:
            return parent.parent
        return parent

    def _normalize_local_path(self, value: str) -> str:
        stripped = value.strip()
        if stripped.startswith("<") and stripped.endswith(">"):
            stripped = stripped[1:-1]
        stripped = stripped.replace("\\", "/")
        while stripped.startswith("./"):
            stripped = stripped[2:]
        return posixpath.normpath(stripped)

    def _strip_parent_refs(self, value: str) -> str:
        parts = [part for part in value.split("/") if part and part != "."]
        while parts and parts[0] == "..":
            parts.pop(0)
        return "/".join(parts)

    def _relative_posix_path(self, target: Path, start: Path) -> str:
        text = os.path.relpath(target, start).replace(os.sep, "/")
        return quote(text, safe="/#%:@")

    def _split_target(self, target: str) -> tuple[str, str] | None:
        stripped = target.strip()
        if not stripped:
            return None
        if stripped.startswith("<") and stripped.endswith(">"):
            return stripped[1:-1], ""
        if " " not in stripped and "\t" not in stripped:
            return stripped, ""

        match = re.match(r"(?P<url>\S+)(?P<title>\s+['\"(].*)$", stripped)
        if not match:
            return stripped, ""
        return match.group("url"), match.group("title")

    def _replace_outside_code(self, text: str, pattern: re.Pattern, callback) -> str:
        masked = self._mask_code(text)
        parts: list[str] = []
        last = 0

        for match in pattern.finditer(masked):
            parts.append(text[last:match.start()])
            groups = {
                name: text[match.start(name):match.end(name)]
                for name in pattern.groupindex
            }
            parts.append(callback(groups))
            last = match.end()

        if not parts:
            return text
        parts.append(text[last:])
        return "".join(parts)

    def _mask_code(self, text: str) -> str:
        masked = list(text)

        def mask_range(start: int, end: int) -> None:
            for index in range(start, end):
                if masked[index] != "\n":
                    masked[index] = " "

        for match in re.finditer(r"(?ms)^(```|~~~).*?^\1[ \t]*$", text):
            mask_range(match.start(), match.end())

        for match in re.finditer(r"(?m)^(?: {4}|\t).*$", text):
            if "![" not in match.group(0):
                mask_range(match.start(), match.end())

        for match in re.finditer(r"`[^`\n]*`", text):
            mask_range(match.start(), match.end())

        return "".join(masked)

    def _external_url_from_markdown_prefix(self, prefix: str) -> str | None:
        if prefix.startswith("![") or not prefix.endswith("]("):
            return None
        label = prefix[1:-2].replace("\\_", "_")
        scheme = urlsplit(label).scheme.lower()
        if scheme in {"http", "https"}:
            return label
        return None
