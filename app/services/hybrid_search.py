"""
Hybrid Semantic Search Engine
=============================
3-Tier Confidence Search Architecture:
  Level 1: Fast-Path Dictionary (PartMatcher) & Clean OEM SQL Lookup
  Level 2: OpenAI text-embedding-3-small Vector Search via Qdrant
  Level 3: Threshold Scoring & Decision Router (HIGH >= 0.85, MEDIUM 0.65-0.84, LOW < 0.65)
  Shadow Mode: ENABLE_SHADOW_MODE=true logs vector matches in background without altering primary responses
"""

import os
import logging
import asyncio
from typing import Dict, Any, Optional

from app.services.db_queries import search_part_and_alternatives
from app.services.part_matcher import get_part_matcher
from app.services.vector_search import get_vector_search_service
from app.database import log_unmatched_query

logger = logging.getLogger(__name__)

# Thresholds
HIGH_CONFIDENCE_THRESHOLD = 0.85
MEDIUM_CONFIDENCE_THRESHOLD = 0.65


async def perform_hybrid_part_search(
    query_text: str,
    customer_phone: str = "",
) -> Dict[str, Any]:
    """
    Executes 3-tier hybrid search:
    Level 1 -> Dictionary & OEM Fast-Path
    Level 2 -> Vector Search via Qdrant & OpenAI text-embedding-3-small
    Level 3 -> Threshold Scoring (HIGH, MEDIUM, LOW) & Shadow Mode support
    """
    shadow_mode = os.getenv("ENABLE_SHADOW_MODE", "false").lower() in ("true", "1")
    query_clean = (query_text or "").strip()

    # =========================================================================
    # LEVEL 1: Fast-Path Dictionary & Clean OEM SQL Search
    # =========================================================================
    level1_res = await search_part_and_alternatives(query_clean)
    matcher = get_part_matcher()
    dict_match = matcher.find_part(query_clean)

    l1_found = level1_res.get("found", False)
    l1_product = level1_res.get("product")
    l1_confidence = 1.0 if (l1_found and l1_product) else (0.8 if dict_match else 0.0)

    if l1_found and l1_product:
        # Fast-Path Success
        result = {
            "found": True,
            "product": l1_product,
            "alternatives": level1_res.get("alternatives", []),
            "confidence_level": "HIGH",
            "confidence_score": 1.0,
            "source": "LEVEL_1_FASTPATH",
            "search_tier": "LEVEL_1",
            "dict_match": dict_match.matched_synonym if dict_match else None,
        }

        # SHADOW MODE: Log Level 2 vector search in background without altering response
        if shadow_mode:
            asyncio.create_task(_run_shadow_mode_logging(query_clean, l1_product))

        return result

    # =========================================================================
    # LEVEL 2: OpenAI text-embedding-3-small Vector Search via Qdrant
    # =========================================================================
    vector_service = get_vector_search_service()
    vector_hits = vector_service.search_vector(query_clean, limit=3)

    best_hit = vector_hits[0] if vector_hits else None
    vector_score = best_hit.get("score", 0.0) if best_hit else 0.0

    # Map Qdrant hit to product dict format if hit exists
    vec_product = None
    if best_hit and best_hit.get("payload"):
        p = best_hit["payload"]
        vec_product = {
            "id": p.get("product_id") or best_hit.get("id"),
            "oem_number": p.get("oem_number", ""),
            "clean_oem": p.get("clean_oem", ""),
            "name_ar": p.get("name_ar", ""),
            "name_fr": p.get("name_fr", ""),
            "description": p.get("description", ""),
            "primary_image_url": p.get("primary_image_url"),
            "price": float(p.get("price", 0.0)),
            "stock_quantity": int(p.get("stock_quantity", 0)),
        }

    # =========================================================================
    # LEVEL 3: Threshold Scoring & Decision Router
    # =========================================================================
    final_score = max(vector_score, l1_confidence)

    # 1. HIGH CONFIDENCE (>= 0.85): Direct Product Match
    if final_score >= HIGH_CONFIDENCE_THRESHOLD and vec_product:
        logger.info("[HYBRID] Level 2 Vector High Match: score=%.2f for '%s'", final_score, query_clean)
        
        # Candidate alternatives from remaining hits
        alternatives = []
        for hit in vector_hits[1:]:
            p = hit.get("payload", {})
            if p:
                alternatives.append({
                    "oem_number": p.get("oem_number", ""),
                    "name_ar": p.get("name_ar", ""),
                    "name_fr": p.get("name_fr", ""),
                    "price": float(p.get("price", 0.0)),
                    "stock_quantity": int(p.get("stock_quantity", 0)),
                    "notes": f"Vector match (score: {hit.get('score', 0):.2f})",
                })

        return {
            "found": True,
            "product": vec_product,
            "alternatives": alternatives,
            "confidence_level": "HIGH",
            "confidence_score": round(final_score, 2),
            "source": "LEVEL_2_VECTOR_HIGH",
            "search_tier": "LEVEL_2",
        }

    # 2. MEDIUM CONFIDENCE (0.65 - 0.84): Candidate Options / Disambiguation
    elif final_score >= MEDIUM_CONFIDENCE_THRESHOLD:
        logger.info("[HYBRID] Level 2 Vector Medium Match: score=%.2f for '%s'", final_score, query_clean)
        
        options = []
        for hit in vector_hits:
            p = hit.get("payload", {})
            if p:
                options.append({
                    "oem_number": p.get("oem_number", ""),
                    "name_ar": p.get("name_ar", ""),
                    "name_fr": p.get("name_fr", ""),
                    "price": float(p.get("price", 0.0)),
                    "stock_quantity": int(p.get("stock_quantity", 0)),
                    "notes": f"Suggested match (confidence: {hit.get('score', 0):.2f})",
                })

        main_prod = vec_product or (level1_res.get("product") if level1_res else None)

        return {
            "found": True if main_prod else False,
            "product": main_prod,
            "alternatives": options,
            "confidence_level": "MEDIUM",
            "confidence_score": round(final_score, 2),
            "source": "LEVEL_2_VECTOR_MEDIUM",
            "search_tier": "LEVEL_2",
            "prompt_instructions": "Offer customer options to confirm part identity.",
        }

    # 3. LOW CONFIDENCE (< 0.65): Unmatched Query -> Log for Human Agent
    else:
        logger.info("[HYBRID] Low Confidence (score=%.2f) for '%s'. Logging unmatched query.", final_score, query_clean)
        suggested = vec_product.get("oem_number") if vec_product else (dict_match.matched_synonym if dict_match else "")
        
        # Log to unmatched_queries table
        await log_unmatched_query(
            query_text=query_clean,
            phone=customer_phone,
            confidence_score=round(final_score, 2),
            suggested_match=suggested or "",
        )

        return {
            "found": False,
            "product": None,
            "alternatives": level1_res.get("alternatives", []),
            "confidence_level": "LOW",
            "confidence_score": round(final_score, 2),
            "source": "LEVEL_3_UNMATCHED_FALLBACK",
            "search_tier": "LEVEL_3",
        }


async def _run_shadow_mode_logging(query_text: str, level1_product: Dict[str, Any]):
    """Background shadow mode task: logs Qdrant vector search results for testing evaluation."""
    try:
        vector_service = get_vector_search_service()
        vector_hits = vector_service.search_vector(query_text, limit=1)
        if vector_hits:
            hit = vector_hits[0]
            score = hit.get("score", 0.0)
            payload = hit.get("payload", {})
            vec_oem = payload.get("oem_number", "N/A")
            l1_oem = level1_product.get("oem_number", "N/A")
            logger.info(
                "[SHADOW_MODE] Query: '%s' | Level1 OEM: %s | Vector Match OEM: %s (score: %.2f)",
                query_text, l1_oem, vec_oem, score
            )
            print(f"[SHADOW_MODE] Query: '{query_text}' | L1: {l1_oem} | Vector: {vec_oem} (score={score:.2f})")
    except Exception as exc:
        logger.warning("[SHADOW_MODE_ERROR] %s", exc)
