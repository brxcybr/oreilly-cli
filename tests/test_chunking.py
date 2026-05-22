import unittest

from plugins.chunking import ChunkingPlugin


class ChunkingPluginTests(unittest.TestCase):
    def setUp(self):
        self.plugin = ChunkingPlugin()

    def test_short_text_smaller_than_default_chunk_size_is_one_chunk(self):
        text = "Short chapter text that should not be duplicated."

        chunks = self.plugin.chunk_text(text)

        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0]["content"], text)
        self.assertEqual(chunks[0]["start_offset"], 0)
        self.assertEqual(chunks[0]["end_offset"], len(text))

    def test_final_chunk_terminates_instead_of_sliding_one_character(self):
        text = " ".join(f"word{i}" for i in range(1500))

        chunks = self.plugin.chunk_text(text, chunk_size=100, overlap=20)

        self.assertLess(len(chunks), 100)
        self.assertEqual(chunks[-1]["end_offset"], len(text))
        self.assertEqual(
            len({(chunk["start_offset"], chunk["end_offset"]) for chunk in chunks}),
            len(chunks),
        )


if __name__ == "__main__":
    unittest.main()
