import os
import asyncio
import unittest

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///test_hybrid_parts.db"
os.environ["ENABLE_SHADOW_MODE"] = "true"

from app.database import init_db, get_db_connection, log_unmatched_query
from app.services.vector_search import get_vector_search_service, VectorSearchService
from app.services.hybrid_search import perform_hybrid_part_search
from app.scripts.index_catalog import index_catalog_to_qdrant


class TestHybridSearch(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        if os.path.exists("test_hybrid_parts.db"):
            try:
                os.remove("test_hybrid_parts.db")
            except Exception:
                pass
        await init_db()

    async def asyncTearDown(self):
        if os.path.exists("test_hybrid_parts.db"):
            try:
                os.remove("test_hybrid_parts.db")
            except Exception:
                pass

    async def test_level1_fastpath_search(self):
        # Level 1 fast-path OEM search
        res = await perform_hybrid_part_search("1K0 129 620 D")
        self.assertTrue(res["found"])
        self.assertEqual(res["confidence_level"], "HIGH")
        self.assertEqual(res["search_tier"], "LEVEL_1")
        self.assertEqual(res["product"]["oem_number"], "1K0129620D")

    async def test_level1_fastpath_dialect_search(self):
        # Level 1 fast-path Algerian dialect search
        res = await perform_hybrid_part_search("خصني أمورتيسور")
        self.assertTrue(res["found"] or res["confidence_level"] in ("HIGH", "MEDIUM"))
        self.assertIsNotNone(res["search_tier"])

    async def test_catalog_indexer_and_vector_service(self):
        # Test CLI indexing function
        await index_catalog_to_qdrant()
        vector_service = get_vector_search_service()

        hits = vector_service.search_vector("1K0129620D", limit=3)
        self.assertIsInstance(hits, list)

    async def test_unmatched_query_logging(self):
        # Level 3 low confidence unmatched query
        unknown_query = "قطعة غيار مش موجودة في الدنيا 99999"
        res = await perform_hybrid_part_search(unknown_query, customer_phone="213555999000")
        self.assertFalse(res["found"])
        self.assertEqual(res["confidence_level"], "LOW")
        self.assertEqual(res["search_tier"], "LEVEL_3")

        # Verify unmatched_queries table entry in DB
        conn = await get_db_connection()
        async with conn.execute("SELECT query_text, phone FROM unmatched_queries WHERE phone = '213555999000';") as cursor:
            row = await cursor.fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row["phone"], "213555999000")
        await conn.close()


if __name__ == "__main__":
    unittest.main()
