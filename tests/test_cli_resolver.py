import unittest
from pathlib import Path

from cli.resolver import resolve_book_source, resolve_playlist, resolve_sources, _extract_book_entries, _extract_playlist_from_html


class _BookPlugin:
    def search(self, query, limit=5):
        return [{"id": "9798868802188", "title": "Azure Data Factory", "authors": []}]


class _Http:
    def __init__(self, data):
        self.data = data

    def get_json(self, url):
        if "playlists" not in url:
            raise RuntimeError("unexpected")
        return self.data


class _Kernel:
    def __init__(self, playlist_data=None):
        self.http = _Http(playlist_data or {})
        self.book = _BookPlugin()

    def __getitem__(self, name):
        if name == "book":
            return self.book
        raise KeyError(name)


class ResolverTests(unittest.TestCase):
    def test_resolve_book_url(self):
        item = resolve_book_source(
            _Kernel(),
            "https://learning.oreilly.com/library/view/azure-data-factory/9798868802188/",
        )
        self.assertEqual(item.book_id, "9798868802188")
        self.assertEqual(item.reason, "book_url")

    def test_resolve_isbn_uses_search(self):
        item = resolve_book_source(_Kernel(), "9798868802188")
        self.assertEqual(item.book_id, "9798868802188")
        self.assertEqual(item.reason, "isbn")

    def test_resolve_playlist_from_json(self):
        data = {
            "results": [
                {"content": {"archive_id": "1111111111", "title": "First"}},
                {"content": {"url": "https://learning.oreilly.com/library/view/title/2222222222/"}},
            ]
        }
        items, warnings = resolve_playlist(
            _Kernel(data),
            "00000000-0000-4000-8000-000000000000",
            "https://learning.oreilly.com/playlists/00000000-0000-4000-8000-000000000000/",
            max_items=20,
        )
        self.assertEqual([item.book_id for item in items], ["1111111111", "2222222222"])
        self.assertEqual(warnings, [])

    def test_extract_playlist_from_saved_ssr_html(self):
        html = Path("tests/fixtures/playlist_ssr.html").read_text(encoding="utf-8")
        playlist = _extract_playlist_from_html(html)
        books = _extract_book_entries(playlist)
        self.assertEqual(playlist["id"], "00000000-0000-4000-8000-000000000000")
        self.assertEqual(books[0][0], "9781492050032")
        self.assertIn(("9798868802188", None), books)

    def test_resolve_sources_limits_and_dedupes(self):
        sources = [
            "https://learning.oreilly.com/library/view/title/1111111111/",
            "1111111111",
            "https://learning.oreilly.com/library/view/title/2222222222/",
        ]
        items, warnings = resolve_sources(_Kernel(), sources, max_items=1)
        self.assertEqual([item.book_id for item in items], ["1111111111"])
        self.assertTrue(warnings)


if __name__ == "__main__":
    unittest.main()
