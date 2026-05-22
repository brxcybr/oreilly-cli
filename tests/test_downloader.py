import json
import tempfile
import unittest
from pathlib import Path

from plugins.chunking import ChunkingPlugin
from plugins.downloader import DownloaderPlugin
from plugins.link_repair import LinkRepairPlugin


class _FakeHttp:
    def get_jwt_status(self):
        return {"valid": True}


class _FakeKernel:
    def __init__(self, plugins):
        self.plugins = plugins
        self.http = _FakeHttp()

    def __getitem__(self, name):
        return self.plugins[name]

    def get(self, name):
        return self.plugins.get(name)


class _FakeBookPlugin:
    def fetch(self, book_id):
        return {
            "title": "Example Book",
            "authors": [],
            "publishers": [],
        }


class _FakeChaptersPlugin:
    def fetch_list(self, book_id):
        return [
            {
                "filename": "ch01.html",
                "content_url": "https://example.com/ch01",
                "stylesheets": [],
                "images": [],
                "title": "Chapter 1",
            }
        ]

    def fetch_toc(self, book_id):
        return []

    def reorder_by_toc(self, chapters, toc):
        return chapters

    def fetch_content(self, url):
        return "<p>Chapter body</p>"


class _FakeAssetsPlugin:
    def download_all_css(self, css_list, oebps, progress_callback=None):
        return {}

    def download_all_images(self, image_list, oebps, progress_callback=None):
        return {}


class _FakeHtmlProcessor:
    def process(self, raw_html, book_id, skip_images=False, path_prefix=""):
        return raw_html, []

    def wrap_xhtml(self, processed, css_refs, title):
        return f"<html><body>{processed}</body></html>"


class _FakeOutputPlugin:
    def create_book_dir(self, output_dir, book_id, title, authors=None):
        book_dir = Path(output_dir) / "example-book"
        book_dir.mkdir(parents=True, exist_ok=True)
        return book_dir

    def get_oebps_dir(self, book_dir):
        return Path(book_dir) / "OEBPS"


class _FakeMarkdownPlugin:
    def generate_book(self, book_info, chapters_data, book_dir, single_file=True):
        path = Path(book_dir) / "Example Book.md"
        path.write_text("[Chapter](ch01.html)\n", encoding="utf-8")
        return path


class DownloaderPluginTests(unittest.TestCase):
    def test_download_repairs_generated_markdown_links_before_returning(self):
        link_repair = LinkRepairPlugin()
        downloader = DownloaderPlugin()
        kernel = _FakeKernel(
            {
                "book": _FakeBookPlugin(),
                "chapters": _FakeChaptersPlugin(),
                "assets": _FakeAssetsPlugin(),
                "html_processor": _FakeHtmlProcessor(),
                "output": _FakeOutputPlugin(),
                "markdown": _FakeMarkdownPlugin(),
                "link_repair": link_repair,
            }
        )
        downloader.kernel = kernel
        link_repair.kernel = kernel
        progress_statuses = []

        with tempfile.TemporaryDirectory() as tmpdir:
            result = downloader.download(
                book_id="1234567890",
                output_dir=Path(tmpdir),
                formats=["markdown"],
                skip_images=True,
                progress_callback=lambda progress: progress_statuses.append(progress.status),
            )

            markdown = (result.output_dir / "Example Book.md").read_text(encoding="utf-8")

        self.assertIn("[Chapter](OEBPS/ch01.xhtml)", markdown)
        self.assertEqual(result.link_repair["links_repaired"], 1)
        self.assertEqual(result.link_repair["unresolved"], [])
        self.assertIn("repairing_links", progress_statuses)

    def test_default_chunk_export_repairs_chapter_filename_links(self):
        link_repair = LinkRepairPlugin()
        chunking = ChunkingPlugin()
        downloader = DownloaderPlugin()
        kernel = _FakeKernel(
            {
                "book": _FakeBookPlugin(),
                "chapters": _FakeChaptersPlugin(),
                "assets": _FakeAssetsPlugin(),
                "html_processor": _FakeHtmlProcessor(),
                "output": _FakeOutputPlugin(),
                "chunking": chunking,
                "link_repair": link_repair,
            }
        )
        downloader.kernel = kernel
        chunking.kernel = kernel
        link_repair.kernel = kernel

        with tempfile.TemporaryDirectory() as tmpdir:
            result = downloader.download(
                book_id="1234567890",
                output_dir=Path(tmpdir),
                formats=["chunks"],
                skip_images=True,
            )

            chunks_path = Path(result.files["chunks"])
            records = [
                json.loads(line)
                for line in chunks_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]

        self.assertEqual(records[0]["chapter_filename"], "OEBPS/ch01.xhtml")
        self.assertEqual(result.link_repair["unresolved"], [])


if __name__ == "__main__":
    unittest.main()
