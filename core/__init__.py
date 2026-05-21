"""Core package exports.

Kernel and HTTP client imports are lazy so lightweight modules such as
``core.types`` can be imported without requiring network/client dependencies.
"""

from .types import BookInfo, ChapterInfo, ChapterSummary, FormatInfo

__all__ = [
    "Kernel",
    "create_default_kernel",
    "HttpClient",
    "ChapterInfo",
    "ChapterSummary",
    "BookInfo",
    "FormatInfo",
]


def __getattr__(name):
    if name in {"Kernel", "create_default_kernel"}:
        from .kernel import Kernel, create_default_kernel

        return {"Kernel": Kernel, "create_default_kernel": create_default_kernel}[name]
    if name == "HttpClient":
        from .http_client import HttpClient

        return HttpClient
    raise AttributeError(name)
