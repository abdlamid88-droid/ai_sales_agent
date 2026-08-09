"""
محرك مطابقة أسماء قطع الغيار (Part Name Matcher)
================================================
يبحث عن القطعة المقصودة من رسالة العميل (دارجة جزائرية / فرنسية / فصحى / إنجليزية)
باستخدام قاموس المرادفات + المطابقة الضبابية (Fuzzy Matching).

الاستخدام:
    from app.services.part_matcher import PartMatcher

    matcher = PartMatcher()
    result = matcher.find_part("عندي مشكل فالأمورتيسور الأمامي ديال الكورسا")
    print(result)
"""

import os
import json
import re
from dataclasses import dataclass
from typing import Optional, List

try:
    from rapidfuzz import fuzz, process
    HAS_RAPIDFUZZ = True
except ImportError:
    import difflib
    HAS_RAPIDFUZZ = False


# --- تطبيع النص (إزالة التشكيل، توحيد الحروف العربية المتشابهة) ---
ARABIC_NORMALIZATION_MAP = {
    "أ": "ا", "إ": "ا", "آ": "ا",
    "ة": "ه",
    "ى": "ي",
    "ؤ": "و",
    "ئ": "ي",
}

ARABIC_DIACRITICS = re.compile(r"[\u064B-\u0652\u0670\u0640]")


def normalize_text(text: str) -> str:
    """توحيد النص العربي/الفرنسي لتسهيل المطابقة."""
    if not text:
        return ""
    text = text.strip().lower()
    text = ARABIC_DIACRITICS.sub("", text)
    for src, dst in ARABIC_NORMALIZATION_MAP.items():
        text = text.replace(src, dst)
    # إزالة الرموز الزائدة مع إبقاء المسافات والحروف/الأرقام
    text = re.sub(r"[^\w\s\u0600-\u06FF]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


@dataclass
class MatchResult:
    part_id: str
    standard_ar: str
    standard_en: str
    category: str
    matched_synonym: str
    confidence: float  # 0-100
    match_type: str  # "exact" | "fuzzy" | "none"


class PartMatcher:
    def __init__(self, dictionary_path: Optional[str] = None):
        if not dictionary_path:
            dictionary_path = os.path.join(os.path.dirname(__file__), "synonyms_dictionary.json")

        if not os.path.exists(dictionary_path):
            raise FileNotFoundError(f"Synonyms dictionary not found at {dictionary_path}")

        with open(dictionary_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.parts = data.get("parts", [])

        # بناء خريطة: كل مرادف (بعد التطبيع) -> معلومات القطعة
        self._synonym_index: dict[str, dict] = {}
        self._all_synonyms: List[str] = []
        self._synonym_to_part: dict[str, dict] = {}

        for part in self.parts:
            all_terms = [part["standard_ar"], part["standard_en"]] + part.get("synonyms", [])
            for term in all_terms:
                norm = normalize_text(term)
                if not norm:
                    continue
                self._synonym_index[norm] = part
                self._all_synonyms.append(norm)
                self._synonym_to_part[norm] = part

    def find_part(self, customer_message: str, fuzzy_threshold: int = 75) -> Optional[MatchResult]:
        """
        يبحث عن أقرب قطعة مطابقة لرسالة العميل.
        1. يحاول تطابق مباشر (exact) لأي مرادف داخل الرسالة.
        2. إذا لم يجد، يستخدم fuzzy matching لإيجاد أقرب مرادف.
        """
        norm_message = normalize_text(customer_message)
        if not norm_message:
            return None

        # 1) تطابق مباشر: هل أي مرادف موجود كنص فرعي داخل الرسالة؟
        for synonym in sorted(self._all_synonyms, key=len, reverse=True):
            if synonym and synonym in norm_message:
                part = self._synonym_to_part[synonym]
                return MatchResult(
                    part_id=part["part_id"],
                    standard_ar=part["standard_ar"],
                    standard_en=part["standard_en"],
                    category=part["category"],
                    matched_synonym=synonym,
                    confidence=100.0,
                    match_type="exact",
                )

        # 2) تطابق ضبابي
        if HAS_RAPIDFUZZ:
            best = process.extractOne(
                norm_message, self._all_synonyms, scorer=fuzz.token_set_ratio
            )
            if best:
                matched_synonym, score, _ = best
                if score >= fuzzy_threshold:
                    part = self._synonym_to_part[matched_synonym]
                    return MatchResult(
                        part_id=part["part_id"],
                        standard_ar=part["standard_ar"],
                        standard_en=part["standard_en"],
                        category=part["category"],
                        matched_synonym=matched_synonym,
                        confidence=round(score, 1),
                        match_type="fuzzy",
                    )
        else:
            matches = difflib.get_close_matches(norm_message, self._all_synonyms, n=1, cutoff=fuzzy_threshold/100.0)
            if matches:
                matched_synonym = matches[0]
                part = self._synonym_to_part[matched_synonym]
                return MatchResult(
                    part_id=part["part_id"],
                    standard_ar=part["standard_ar"],
                    standard_en=part["standard_en"],
                    category=part["category"],
                    matched_synonym=matched_synonym,
                    confidence=80.0,
                    match_type="fuzzy",
                )

        return None

    def find_top_candidates(self, customer_message: str, limit: int = 3) -> List[MatchResult]:
        """
        يرجع أفضل عدة احتمالات بدل نتيجة واحدة فقط.
        """
        norm_message = normalize_text(customer_message)
        if not norm_message:
            return []

        results = []
        seen_part_ids = set()

        if HAS_RAPIDFUZZ:
            matches = process.extract(
                norm_message, self._all_synonyms, scorer=fuzz.token_set_ratio, limit=limit * 3
            )
            for matched_synonym, score, _ in matches:
                part = self._synonym_to_part[matched_synonym]
                if part["part_id"] in seen_part_ids:
                    continue
                seen_part_ids.add(part["part_id"])
                results.append(
                    MatchResult(
                        part_id=part["part_id"],
                        standard_ar=part["standard_ar"],
                        standard_en=part["standard_en"],
                        category=part["category"],
                        matched_synonym=matched_synonym,
                        confidence=round(score, 1),
                        match_type="fuzzy",
                    )
                )
                if len(results) >= limit:
                    break
        else:
            matches = difflib.get_close_matches(norm_message, self._all_synonyms, n=limit * 3, cutoff=0.5)
            for matched_synonym in matches:
                part = self._synonym_to_part[matched_synonym]
                if part["part_id"] in seen_part_ids:
                    continue
                seen_part_ids.add(part["part_id"])
                results.append(
                    MatchResult(
                        part_id=part["part_id"],
                        standard_ar=part["standard_ar"],
                        standard_en=part["standard_en"],
                        category=part["category"],
                        matched_synonym=matched_synonym,
                        confidence=75.0,
                        match_type="fuzzy",
                    )
                )
                if len(results) >= limit:
                    break

        return results


# Singleton global instance for efficient reuse across requests
_global_matcher: Optional[PartMatcher] = None

def get_part_matcher() -> PartMatcher:
    global _global_matcher
    if _global_matcher is None:
        _global_matcher = PartMatcher()
    return _global_matcher
