from unittest import TestCase

from smart_tests.utils.embedding import EmbeddingOptions


class EmbeddingOptionsTest(TestCase):
    def test_client_mode(self):
        e = EmbeddingOptions.from_collect_options({"embedding": {
            "mode": "client", "modelId": 7, "provider": "openai",
            "modelName": "text-embedding-3-small", "dimensions": 1536, "canonicalId": 3}})
        self.assertEqual(e, EmbeddingOptions("client", 7, "openai", "text-embedding-3-small", 1536, 3))
        self.assertTrue(e.is_client_mode)

    def test_server_mode_has_null_details(self):
        e = EmbeddingOptions.from_collect_options({"embedding": {
            "mode": "server", "modelId": None, "provider": None,
            "modelName": None, "dimensions": None, "canonicalId": None}})
        self.assertFalse(e.is_client_mode)
        self.assertIsNone(e.dimensions)

    def test_no_embedding_block(self):
        self.assertIsNone(EmbeddingOptions.from_collect_options({"commitMessage": True}))
        self.assertIsNone(EmbeddingOptions.from_collect_options({"embedding": None}))
