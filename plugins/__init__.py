"""Plugin package exports.

Exports are lazy to avoid importing optional-heavy output dependencies unless a
kernel is actually being built.
"""

__all__ = [
    "Plugin",
    "AuthPlugin",
    "BookPlugin",
    "ChaptersPlugin",
    "AssetsPlugin",
    "HtmlProcessorPlugin",
    "EpubPlugin",
    "MarkdownPlugin",
    "PdfPlugin",
    "TokenPlugin",
    "PlainTextPlugin",
    "JsonExportPlugin",
    "ChunkingPlugin",
    "ChunkConfig",
    "OutputPlugin",
    "SystemPlugin",
    "DownloaderPlugin",
    "DownloadProgress",
    "DownloadResult",
]


def __getattr__(name):
    if name == "Plugin":
        from .base import Plugin

        return Plugin
    if name == "AuthPlugin":
        from .auth import AuthPlugin

        return AuthPlugin
    if name == "BookPlugin":
        from .book import BookPlugin

        return BookPlugin
    if name == "ChaptersPlugin":
        from .chapters import ChaptersPlugin

        return ChaptersPlugin
    if name == "AssetsPlugin":
        from .assets import AssetsPlugin

        return AssetsPlugin
    if name == "HtmlProcessorPlugin":
        from .html_processor import HtmlProcessorPlugin

        return HtmlProcessorPlugin
    if name == "EpubPlugin":
        from .epub import EpubPlugin

        return EpubPlugin
    if name == "MarkdownPlugin":
        from .markdown import MarkdownPlugin

        return MarkdownPlugin
    if name == "PdfPlugin":
        from .pdf import PdfPlugin

        return PdfPlugin
    if name == "TokenPlugin":
        from .token import TokenPlugin

        return TokenPlugin
    if name == "PlainTextPlugin":
        from .plaintext import PlainTextPlugin

        return PlainTextPlugin
    if name == "JsonExportPlugin":
        from .json_export import JsonExportPlugin

        return JsonExportPlugin
    if name in {"ChunkingPlugin", "ChunkConfig"}:
        from .chunking import ChunkConfig, ChunkingPlugin

        return {"ChunkingPlugin": ChunkingPlugin, "ChunkConfig": ChunkConfig}[name]
    if name == "OutputPlugin":
        from .output import OutputPlugin

        return OutputPlugin
    if name == "SystemPlugin":
        from .system import SystemPlugin

        return SystemPlugin
    if name in {"DownloaderPlugin", "DownloadProgress", "DownloadResult"}:
        from .downloader import DownloadProgress, DownloadResult, DownloaderPlugin

        return {
            "DownloaderPlugin": DownloaderPlugin,
            "DownloadProgress": DownloadProgress,
            "DownloadResult": DownloadResult,
        }[name]
    raise AttributeError(name)
