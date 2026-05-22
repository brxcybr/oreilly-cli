import json
import tempfile
import unittest
from pathlib import Path

from plugins.link_repair import LinkRepairPlugin


class LinkRepairPluginTests(unittest.TestCase):
    def setUp(self):
        self.plugin = LinkRepairPlugin()

    def test_repairs_combined_markdown_links_against_oebps(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            book_dir = Path(tmpdir)
            (book_dir / "OEBPS" / "Images").mkdir(parents=True)
            (book_dir / "OEBPS" / "Images" / "figure 1.png").write_text("image", encoding="utf-8")
            (book_dir / "OEBPS" / "ch01.xhtml").write_text("<html></html>", encoding="utf-8")
            md_path = book_dir / "Book.md"

            markdown = "![Figure](./Images/figure 1.png)\n[Chapter](ch01.html#start)\n"
            repaired, report = self.plugin.repair_markdown(markdown, md_path, book_dir)

            self.assertIn("](OEBPS/Images/figure%201.png)", repaired)
            self.assertIn("](OEBPS/ch01.xhtml#start)", repaired)
            self.assertEqual(report.links_seen, 2)
            self.assertEqual(report.links_repaired, 2)
            self.assertEqual(report.unresolved, [])

    def test_repairs_separate_markdown_links_from_markdown_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            book_dir = Path(tmpdir)
            (book_dir / "Markdown").mkdir()
            (book_dir / "OEBPS" / "Images").mkdir(parents=True)
            (book_dir / "OEBPS" / "Images" / "figure.png").write_text("image", encoding="utf-8")
            (book_dir / "OEBPS" / "ch01.xhtml").write_text("<html></html>", encoding="utf-8")
            md_path = book_dir / "Markdown" / "ch01.md"

            markdown = "![Figure](Images/figure.png)\n[Chapter](ch01.xhtml#start)\n"
            repaired, _ = self.plugin.repair_markdown(markdown, md_path, book_dir)

            self.assertIn("](../OEBPS/Images/figure.png)", repaired)
            self.assertIn("](../OEBPS/ch01.xhtml#start)", repaired)

    def test_repairs_chunk_content_and_chapter_filename(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            book_dir = Path(tmpdir)
            (book_dir / "OEBPS" / "Images").mkdir(parents=True)
            (book_dir / "OEBPS" / "Images" / "figure.png").write_text("image", encoding="utf-8")
            (book_dir / "OEBPS" / "ch01.xhtml").write_text("<html></html>", encoding="utf-8")
            jsonl_path = book_dir / "Book_chunks.jsonl"

            chunk = {
                "content": "See ![Figure](./Images/figure.png)",
                "chapter_filename": "ch01.html",
            }
            repaired, report = self.plugin.repair_chunk_record(chunk, jsonl_path, book_dir)

            self.assertEqual(repaired["content"], "See ![Figure](OEBPS/Images/figure.png)")
            self.assertEqual(repaired["chapter_filename"], "OEBPS/ch01.xhtml")
            self.assertEqual(report.links_repaired, 2)

    def test_repairs_markdown_image_targets_with_parentheses(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            book_dir = Path(tmpdir)
            (book_dir / "OEBPS" / "Images").mkdir(parents=True)
            (book_dir / "OEBPS" / "Images" / "table_(a).jpg").write_text("image", encoding="utf-8")
            md_path = book_dir / "Book.md"

            repaired, report = self.plugin.repair_markdown("![](./Images/table_(a).jpg)\n", md_path, book_dir)

            self.assertEqual(repaired, "![](OEBPS/Images/table_%28a%29.jpg)\n")
            self.assertEqual(report.links_repaired, 1)

    def test_repairs_multiline_image_alt_text(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            book_dir = Path(tmpdir)
            (book_dir / "OEBPS" / "Images").mkdir(parents=True)
            (book_dir / "OEBPS" / "Images" / "figure.jpg").write_text("image", encoding="utf-8")
            md_path = book_dir / "Book.md"

            repaired, report = self.plugin.repair_markdown(
                "![Figure caption\n](./Images/figure.jpg)\n",
                md_path,
                book_dir,
            )

            self.assertEqual(repaired, "![Figure caption\n](OEBPS/Images/figure.jpg)\n")
            self.assertEqual(report.links_repaired, 1)

    def test_repairs_image_alt_text_with_bracket_tokens(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            book_dir = Path(tmpdir)
            (book_dir / "OEBPS" / "Images").mkdir(parents=True)
            (book_dir / "OEBPS" / "Images" / "figure.jpg").write_text("image", encoding="utf-8")
            md_path = book_dir / "Book.md"

            repaired, report = self.plugin.repair_markdown(
                "![Azure AD[nd]Joined Devices](./Images/figure.jpg)\n",
                md_path,
                book_dir,
            )

            self.assertEqual(repaired, "![Azure AD[nd]Joined Devices](OEBPS/Images/figure.jpg)\n")
            self.assertEqual(report.links_repaired, 1)

    def test_uses_external_url_label_when_local_target_is_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            book_dir = Path(tmpdir)
            md_path = book_dir / "Book.md"

            repaired, report = self.plugin.repair_markdown(
                "[https://example.com/file\\_ColorImages.pdf](_ColorImages.pdf)\n",
                md_path,
                book_dir,
            )

            self.assertEqual(
                repaired,
                "[https://example.com/file\\_ColorImages.pdf](https://example.com/file_ColorImages.pdf)\n",
            )
            self.assertEqual(report.links_repaired, 1)
            self.assertEqual(report.unresolved, [])

    def test_ignores_link_like_syntax_in_fenced_code_blocks(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            book_dir = Path(tmpdir)
            md_path = book_dir / "Book.md"

            markdown = "```\nPCollection<String> lines = pipeline.read(From.textFile(inputPath));\n```\n"
            repaired, report = self.plugin.repair_markdown(markdown, md_path, book_dir)

            self.assertEqual(repaired, markdown)
            self.assertEqual(report.links_seen, 0)
            self.assertEqual(report.unresolved, [])

    def test_ignores_link_like_syntax_in_inline_code(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            book_dir = Path(tmpdir)
            md_path = book_dir / "Book.md"

            markdown = "`(VALUES [ROW](<row1 columns>), [ROW](<row2 columns>))`\n"
            repaired, report = self.plugin.repair_markdown(markdown, md_path, book_dir)

            self.assertEqual(repaired, markdown)
            self.assertEqual(report.links_seen, 0)
            self.assertEqual(report.unresolved, [])

    def test_ignores_link_like_syntax_in_indented_code_blocks(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            book_dir = Path(tmpdir)
            md_path = book_dir / "Book.md"

            markdown = "    [index_name](index_col_name[, ...]) ]\n"
            repaired, report = self.plugin.repair_markdown(markdown, md_path, book_dir)

            self.assertEqual(repaired, markdown)
            self.assertEqual(report.links_seen, 0)
            self.assertEqual(report.unresolved, [])

    def test_repairs_indented_image_links(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            book_dir = Path(tmpdir)
            (book_dir / "OEBPS" / "Images").mkdir(parents=True)
            (book_dir / "OEBPS" / "Images" / "figure.jpg").write_text("image", encoding="utf-8")
            md_path = book_dir / "Book.md"

            markdown = "    ![Figure](./Images/figure.jpg)\n"
            repaired, report = self.plugin.repair_markdown(markdown, md_path, book_dir)

            self.assertEqual(repaired, "    ![Figure](OEBPS/Images/figure.jpg)\n")
            self.assertEqual(report.links_repaired, 1)

    def test_preserves_existing_repaired_link_titles(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            book_dir = Path(tmpdir)
            (book_dir / "OEBPS").mkdir()
            (book_dir / "OEBPS" / "ch04.xhtml").write_text("<html></html>", encoding="utf-8")
            md_path = book_dir / "Book.md"

            markdown = '[Chapter 4](OEBPS/ch04.xhtml  "Chapter 4")\n'
            repaired, report = self.plugin.repair_markdown(markdown, md_path, book_dir)

            self.assertEqual(repaired, markdown)
            self.assertEqual(report.links_repaired, 0)

    def test_repair_jsonl_file_writes_repaired_records(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            book_dir = Path(tmpdir)
            (book_dir / "OEBPS").mkdir()
            (book_dir / "OEBPS" / "ch01.xhtml").write_text("<html></html>", encoding="utf-8")
            jsonl_path = book_dir / "Book_chunks.jsonl"
            jsonl_path.write_text(
                json.dumps({"content": "body", "chapter_filename": "ch01.html"}) + "\n",
                encoding="utf-8",
            )

            report = self.plugin.repair_jsonl_file(jsonl_path, write=True)
            record = json.loads(jsonl_path.read_text(encoding="utf-8"))

            self.assertEqual(record["chapter_filename"], "OEBPS/ch01.xhtml")
            self.assertEqual(report.files_changed, 1)


if __name__ == "__main__":
    unittest.main()
