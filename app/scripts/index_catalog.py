"""
Catalog Indexing Utility
========================
CLI script to generate rich text representations for all auto parts in sales_agent.db
and populate the Qdrant vector database using OpenAI text-embedding-3-small embeddings.

Usage:
    python -m app.scripts.index_catalog
"""

import os
import sys
import asyncio
import logging
from typing import List, Dict, Any

# Ensure project root is in sys.path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from app.database import get_db_connection, IS_SQLITE
from app.services.part_matcher import get_part_matcher
from app.services.vector_search import get_vector_search_service, DEFAULT_COLLECTION

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


async def fetch_all_products_with_inventory() -> List[Dict[str, Any]]:
    """Fetch all product and inventory data from database."""
    conn = await get_db_connection()
    products = []
    try:
        if IS_SQLITE:
            async with conn.execute('''
                SELECT p.id, p.oem_number, p.clean_oem, p.name_ar, p.name_fr, p.description, p.primary_image_url,
                       COALESCE(i.price, 0.0) as price, COALESCE(i.stock_quantity, 0) as stock_quantity
                FROM products p
                LEFT JOIN inventory i ON p.id = i.product_id;
            ''') as cursor:
                rows = await cursor.fetchall()
                for r in rows:
                    products.append(dict(r))
            await conn.close()
        else:
            rows = await conn.fetch('''
                SELECT p.id, p.oem_number, p.clean_oem, p.name_ar, p.name_fr, p.description, p.primary_image_url,
                       COALESCE(i.price, 0.0) as price, COALESCE(i.stock_quantity, 0) as stock_quantity
                FROM products p
                LEFT JOIN inventory i ON p.id = i.product_id;
            ''')
            for r in rows:
                products.append(dict(r))
            await conn.close()
    except Exception as exc:
        logger.error("[INDEXER] Failed to fetch products: %s", exc)
    return products


def build_part_text_representation(prod: Dict[str, Any], matcher) -> str:
    """Build rich text representation for embedding generation."""
    oem_num    = prod.get("oem_number", "")
    clean_oem  = prod.get("clean_oem", "")
    name_ar    = prod.get("name_ar", "")
    name_fr    = prod.get("name_fr", "")
    desc       = prod.get("description", "") or ""
    price      = prod.get("price", 0.0)

    synonyms_str = ""
    category_str = ""
    # Try finding synonyms from PartMatcher dictionary
    match_res = matcher.find_part(f"{name_ar} {name_fr}")
    if match_res:
        category_str = match_res.category
        synonyms_str = match_res.matched_synonym

    parts = [
        f"OEM Part Number: {oem_num}",
        f"Clean OEM: {clean_oem}",
        f"Arabic Name: {name_ar}",
        f"French Name: {name_fr}",
    ]
    if desc:
        parts.append(f"Description: {desc}")
    if category_str:
        parts.append(f"Category: {category_str}")
    if synonyms_str:
        parts.append(f"Synonyms: {synonyms_str}")
    parts.append(f"Price: {price} DZD")

    return " | ".join(parts)


async def index_catalog_to_qdrant():
    """Main indexing task: reads sales_agent.db and indexes into Qdrant."""
    logger.info("[INDEXER] Starting catalog indexing...")
    products = await fetch_all_products_with_inventory()

    if not products:
        logger.warning("[INDEXER] No products found in database to index.")
        return

    matcher = get_part_matcher()
    vector_service = get_vector_search_service()

    if not vector_service.ensure_collection():
        logger.error("[INDEXER] Could not ensure Qdrant collection '%s'", DEFAULT_COLLECTION)
        return

    success_count = 0
    for prod in products:
        prod_id = prod["id"]
        text_rep = build_part_text_representation(prod, matcher)

        payload = {
            "product_id": prod_id,
            "oem_number": prod.get("oem_number", ""),
            "clean_oem": prod.get("clean_oem", ""),
            "name_ar": prod.get("name_ar", ""),
            "name_fr": prod.get("name_fr", ""),
            "description": prod.get("description", ""),
            "primary_image_url": prod.get("primary_image_url"),
            "price": float(prod.get("price", 0.0)),
            "stock_quantity": int(prod.get("stock_quantity", 0)),
        }

        if vector_service.upsert_part(prod_id, text_rep, payload):
            success_count += 1
            logger.info("  Indexed product ID %s (%s - %s)", prod_id, prod.get("oem_number"), prod.get("name_fr"))

    logger.info("=================================================================")
    logger.info("[INDEXER] Successfully indexed %d / %d parts into Qdrant collection '%s'",
                success_count, len(products), DEFAULT_COLLECTION)
    logger.info("=================================================================")


def main():
    asyncio.run(index_catalog_to_qdrant())


if __name__ == "__main__":
    main()
