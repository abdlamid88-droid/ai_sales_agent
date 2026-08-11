import os
import re
import json
import logging
import httpx
from PIL import Image
try:
    from google import genai
    from google.genai import types
except ImportError:
    genai = None
    types = None

from dotenv import load_dotenv

load_dotenv()

WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN") or os.getenv("WHATSAPP_ACCESS_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

client = None
if GEMINI_API_KEY and genai:
    try:
        client = genai.Client(api_key=GEMINI_API_KEY)
    except Exception as e:
        print(f"Warning: Could not initialize Gemini Client: {e}")

async def fetch_whatsapp_media_bytes(media_id: str) -> tuple[bytes, str]:
    """تنزيل ملف الميديا (صوت أو صورة) من WhatsApp Graph API باستخدام media_id"""
    if not WHATSAPP_TOKEN or not media_id:
        raise ValueError("WHATSAPP_TOKEN or media_id is missing")

    url = f"https://graph.facebook.com/v18.0/{media_id}"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}"
    }
    
    async with httpx.AsyncClient() as http_client:
        # Step 1: Get media download URL
        resp = await http_client.get(url, headers=headers)
        if not resp.is_success:
            print(f"Failed to fetch WhatsApp media metadata for media_id {media_id}. Status code: {resp.status_code}, Meta response body: {resp.text}")
            resp.raise_for_status()
            
        media_data = resp.json()
        download_url = media_data.get("url")
        mime_type = media_data.get("mime_type", "application/octet-stream")
        
        if not download_url:
            raise ValueError(f"Could not retrieve download URL for media_id: {media_id}")
            
        # Step 2: Download media binary stream
        media_resp = await http_client.get(download_url, headers=headers)
        if not media_resp.is_success:
            print(f"Failed to download WhatsApp media bytes for media_id {media_id}. Status code: {media_resp.status_code}, Meta response body: {media_resp.text}")
            media_resp.raise_for_status()
            
        return media_resp.content, mime_type

async def download_whatsapp_audio(media_id: str) -> str | None:
    """
    تنزيل التسجيل الصوتي من WhatsApp وحفظه كملف محلي في المجلد media/audio/
    يرجع المسار الكامل للملف الصوتي المحلي أو None عند الفشل.
    """
    try:
        audio_bytes, mime_type = await fetch_whatsapp_media_bytes(media_id)
        if not audio_bytes:
            return None

        ext = "ogg"
        clean_mime = mime_type.split(";")[0].strip().lower() if mime_type else ""
        if "mp3" in clean_mime:
            ext = "mp3"
        elif "m4a" in clean_mime or "mp4" in clean_mime or "aac" in clean_mime:
            ext = "m4a"
        elif "wav" in clean_mime:
            ext = "wav"

        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        audio_dir = os.path.join(project_root, "media", "audio")
        os.makedirs(audio_dir, exist_ok=True)

        file_path = os.path.join(audio_dir, f"{media_id}.{ext}")
        with open(file_path, "wb") as f:
            f.write(audio_bytes)

        logging.info("[AUDIO_DOWNLOAD] Saved WhatsApp audio to %s", file_path)
        return file_path
    except Exception as exc:
        logging.error("[AUDIO_DOWNLOAD] Failed to download WhatsApp audio (media_id=%s): %s", media_id, exc)
        return None

async def process_voice_note(media_id: str) -> str:
    """تنزيل التسجيل الصوتي وتحويله إلى نص باستخدام Gemini Multimodal API (Speech-to-Text)"""
    try:
        audio_bytes, mime_type = await fetch_whatsapp_media_bytes(media_id)
        clean_mime_type = mime_type.split(";")[0].strip() if mime_type else "audio/ogg"
        
        if client and types:
            prompt = (
                "قم بتفريغ وتنسيق هذا التسجيل الصوتي من عميل يبحث عن قطع غيار سيارات. "
                "استخرج اسم قطعة الغيار المطلوبة، أرقام OEM، أو مظهر السيارة بدقة باللغة العربية أو الفرنسية. "
                "أرجع النص المفرغ فقط دون مقدمات."
            )
            response = await client.aio.models.generate_content(
                model="gemini-2.5-flash",
                contents=[
                    prompt,
                    types.Part.from_bytes(data=audio_bytes, mime_type=clean_mime_type)
                ]
            )
            return response.text.strip() if response and response.text else ""
            
        return "تسجيل صوتي استفسار قطعة غيار"
        
    except Exception as e:
        print(f"Error processing voice note (media_id: {media_id}): {e}")
        return ""

async def process_part_image(media_id: str) -> str:
    """تنزيل صورة قطعة الغيار واستخراج رقم OEM أو الوصف باستخدام Gemini Vision API"""
    try:
        image_bytes, mime_type = await fetch_whatsapp_media_bytes(media_id)
        clean_mime_type = mime_type.split(";")[0].strip() if mime_type else "image/jpeg"
        
        if client and types:
            prompt = (
                "Analyze this auto part image. Identify any visible OEM part numbers, part names, or labels. "
                "Output ONLY a valid JSON object in the following format:\n"
                '{"oem_number": "EXTRACTED_OEM_OR_EMPTY", "part_description": "SHORT_DESCRIPTION"}'
            )
            response = await client.aio.models.generate_content(
                model="gemini-2.5-flash",
                contents=[
                    prompt,
                    types.Part.from_bytes(data=image_bytes, mime_type=clean_mime_type)
                ]
            )
            
            res_text = response.text.strip() if response and response.text else ""
            try:
                if "```json" in res_text:
                    res_text = res_text.split("```json")[1].split("```")[0].strip()
                elif "```" in res_text:
                    res_text = res_text.split("```")[1].split("```")[0].strip()
                    
                parsed = json.loads(res_text)
                oem = parsed.get("oem_number", "").strip()
                desc = parsed.get("part_description", "").strip()
                
                if oem and oem.upper() != "NONE" and oem.upper() != "EMPTY":
                    return f"{oem} {desc}".strip()
                return desc if desc else res_text
            except Exception:
                return res_text
                
        return "صورة قطعة غيار"
            
    except Exception as e:
        print(f"Error processing part image (media_id: {media_id}): {e}")
        return ""

def translate_part_name_terms(name: str) -> str:
    """ترجمة مصطلحات قطع الغيار بالدارجة الجزائرية والفرنسية والعربية إلى الإنجليزية لتحسين البحث عن الصور"""
    if not name:
        return ""
    try:
        from app.services.part_matcher import get_part_matcher
        matcher = get_part_matcher()
        res = matcher.find_part(name)
        if res and res.standard_en:
            return res.standard_en
    except Exception as exc:
        logging.warning("PartMatcher fallback error: %s", exc)

    terms = {
        'فلتر هواء': 'car panel air filter',
        'فلتر زيت': 'car oil filter',
        'مساعد': 'car shock absorber',
        'رفرف': 'car fender',
        'دينامو': 'car alternator',
        'نيمان': 'car ignition lock',
        'عمود الكامات': 'camshaft',
        'شجرة الكامات': 'camshaft',
        'ail': 'car fender',
        'aile': 'car fender',
        'antivol': 'car ignition lock',
        'accordion': 'air intake accordion hose',
        'durite filter': 'air intake accordion hose',
        'durite filtre': 'air intake accordion hose',
        'durite': 'radiator hose',
        'filtre a air': 'car panel air filter',
        'filtre à air': 'car panel air filter',
        'filtre air': 'car panel air filter',
        'filter air': 'car panel air filter',
        'filtre a huile': 'car oil filter',
        'filtre à huile': 'car oil filter',
        'filtre huile': 'car oil filter',
        'arbracame': 'camshaft',
        'arbracam': 'camshaft',
        'arbra': 'camshaft',
        'arbre a came': 'camshaft',
        'arbre à cames': 'camshaft',
        'amortiss': 'car shock absorber',
        'amortisseur': 'car shock absorber',
        'alternat': 'car alternator',
        'alternateur': 'car alternator',
        'pompe a eau': 'car water pump',
        'pompe a huile': 'car oil pump',
        'bougie': 'spark plug',
        'plaquette': 'brake pads',
        'disque': 'brake disc'
    }
    name_lower = name.lower()
    for fr, en in terms.items():
        if fr in name_lower:
            return en
    return name

def is_valid_image_url(url: str) -> bool:
    if not url or not url.startswith("https://"):
        return False
    clean_path = url.split("?")[0].lower()
    if "example.com" in clean_path or "placeholder" in clean_path:
        return False
    if not clean_path.endswith((".jpg", ".jpeg", ".png", ".webp")):
        return False
    return True

def normalize_oem_number(oem: str) -> str:
    """تنظيف وتوحيد رقم OEM بإزالة الشرطات والمسافات والرموز الخاصة (مثل تحويل 37300-2A460 إلى 373002A460)"""
    if not oem:
        return ""
    return re.sub(r'[^A-Z0-9]', '', str(oem).upper())

# ---------------------------------------------------------------------------
# Diagram-specific search domains (line-art / exploded-view catalogues)
# ---------------------------------------------------------------------------
_DIAGRAM_DOMAINS = {
    "partsouq.com", "amayama.com", "epc-data.com", "catcar.info",
    "toyodiy.com", "partsfan.com", "microcat.com", "procarparts.com",
    "oem-parts-online.com", "genuine-parts.com",
}

# Keywords that signal a result IS a schematic/exploded-view
_DIAGRAM_KEYWORDS = {
    "exploded", "schematic", "diagram", "epc", "oem", "catalog",
    "parts", "assembly", "assy", "illustration",
}

# Keywords that signal a result is a product photo (reject for diagram slot)
_PHOTO_KEYWORDS = {
    "photo", "product", "image", "buy", "shop", "stock", "picture",
    "amazon", "ebay", "aliexpress",
}

# Domains that host accurate OEM genuine-part product photos
_PHOTO_PRIORITY_DOMAINS = {
    "partsouq.com", "amayama.com", "hyundaipartsdeal.com",
    "kiapartsnow.com", "hyundaioemparts.com", "parts.hyundai.com",
    "mobis.parts", "megazip.net", "partsfan.com",
    "oemcats.com", "genuine-parts.com",
}

# Keywords in URL/title that indicate a complete assembly/kit rather
# than the bare individual component the OEM code references.
_ASSEMBLY_REJECT_KEYWORDS = {
    "complete assembly", "full assembly", "strut assembly",
    "strut complete", "strut mount", "with spring",
    "coil spring", "kit complete", "complete kit",
    "full kit", "assembly kit", "suspension kit",
}


def _build_precise_photo_query(oem_number: str, part_name: str = "") -> str:
    """
    Build a search query that targets the EXACT component for this OEM,
    not a complete assembly containing it.
    """
    clean_name = ""
    if part_name:
        # Extract meaningful keywords from the catalog description
        # Drop parenthetical codes like (PM)(CSA), slash-separated model lists
        import re as _re
        stripped = _re.sub(r'\([^)]*\)', '', part_name)          # remove (...)
        stripped = _re.sub(r'[/\\|]+', ' ', stripped)            # slashes → space
        tokens   = [t.strip() for t in stripped.split() if len(t.strip()) > 2]
        # Keep at most 4 meaningful tokens to avoid over-constraining
        clean_name = ' '.join(tokens[:4])

    if clean_name:
        return f'"{oem_number}" {clean_name} genuine OEM part'
    return f'"{oem_number}" genuine OEM part -assembly -kit -complete'


def _url_looks_like_diagram(url: str, context: str = "") -> bool:
    """
    Return True if *url* (and optional search-result context text) likely
    represents a technical line-art / exploded-view diagram rather than a
    product photograph.
    """
    if not url:
        return False
    combined = (url + " " + context).lower()
    # Prefer results from known EPC / OEM catalogue domains
    for domain in _DIAGRAM_DOMAINS:
        if domain in combined:
            return True
    # Accept if URL path contains diagram keywords
    path = url.split("?")[0].lower()
    for kw in _DIAGRAM_KEYWORDS:
        if kw in path:
            return True
    # Reject if clearly a product-photo host
    for kw in _PHOTO_KEYWORDS:
        if kw in path:
            return False
    # Neutral URL – accept as candidate
    return True


async def _fetch_diagram_url(
    oem_number: str,
    api_key: str = "",
    cse_id: str = "",
    serper_key: str = "",
) -> str | None:
    """
    Search for an exploded-view / schematic diagram URL for *oem_number*.
    Applies domain and keyword filtering to reject product-photo results.
    Falls back through up to 10 Google/Serper results before giving up.
    """
    ua = {"User-Agent": "AutoPartsSalesBot/1.0"}
    query = f'"{oem_number}" exploded view diagram schematic OEM parts'

    if api_key and cse_id:
        try:
            params = {"key": api_key, "cx": cse_id, "q": query,
                      "searchType": "image", "num": 10}
            async with httpx.AsyncClient(timeout=6.0) as hc:
                resp = await hc.get(
                    "https://www.googleapis.com/customsearch/v1",
                    params=params, headers=ua,
                )
                if resp.is_success:
                    for item in resp.json().get("items", []):
                        link    = item.get("link", "")
                        context = item.get("title", "") + " " + item.get("snippet", "")
                        if is_valid_image_url(link) and _url_looks_like_diagram(link, context):
                            logging.info("[DIAGRAM] Google CSE match: %s", link)
                            return link
        except Exception as exc:
            logging.warning("[DIAGRAM] Google CSE error: %s", exc)

    if serper_key:
        try:
            async with httpx.AsyncClient(timeout=6.0) as hc:
                resp = await hc.post(
                    "https://google.serper.dev/images",
                    headers={"X-API-KEY": serper_key, "Content-Type": "application/json"},
                    json={"q": query, "num": 10},
                )
                if resp.is_success:
                    for item in resp.json().get("images", []):
                        link    = item.get("imageUrl", "")
                        context = item.get("title", "") + " " + item.get("link", "")
                        if is_valid_image_url(link) and _url_looks_like_diagram(link, context):
                            logging.info("[DIAGRAM] Serper match: %s", link)
                            return link
        except Exception as exc:
            logging.warning("[DIAGRAM] Serper error: %s", exc)

    return None


async def _fetch_photo_url(
    oem_number: str,
    api_key: str = "",
    cse_id: str = "",
    serper_key: str = "",
    part_name: str = "",
) -> str | None:
    """
    Search for a real product photograph of *oem_number*.

    Strategy:
      1. Build a precise query using catalog description keywords.
      2. Iterate through up to 10 results.
      3. Prefer images from OEM-catalog domains (partsouq, amayama, etc.).
      4. Reject images whose URL/title contains assembly-reject keywords.
      5. If no OEM-domain result found, fall back to the best generic match.
    """
    ua    = {"User-Agent": "AutoPartsSalesBot/1.0"}
    query = _build_precise_photo_query(oem_number, part_name)
    print(f"[PHOTO_QUERY] {query}")

    def _accept_photo(link: str, context: str = "") -> bool:
        """Return True if *link* is acceptable — reject assembly images."""
        if not is_valid_image_url(link):
            return False
        combined = (link + " " + context).lower()
        for reject_kw in _ASSEMBLY_REJECT_KEYWORDS:
            if reject_kw in combined:
                logging.info("[PHOTO_REJECT] Assembly keyword '%s' in %s", reject_kw, link[:80])
                return False
        return True

    def _is_priority_domain(link: str) -> bool:
        link_lower = link.lower()
        return any(d in link_lower for d in _PHOTO_PRIORITY_DOMAINS)

    async def _search_google(q: str) -> list[dict]:
        if not (api_key and cse_id):
            return []
        try:
            params = {"key": api_key, "cx": cse_id, "q": q,
                      "searchType": "image", "num": 10}
            async with httpx.AsyncClient(timeout=6.0) as hc:
                resp = await hc.get(
                    "https://www.googleapis.com/customsearch/v1",
                    params=params, headers=ua,
                )
                if resp.is_success:
                    return resp.json().get("items", [])
        except Exception as exc:
            logging.warning("[PHOTO] Google CSE error: %s", exc)
        return []

    async def _search_serper(q: str) -> list[dict]:
        if not serper_key:
            return []
        try:
            async with httpx.AsyncClient(timeout=6.0) as hc:
                resp = await hc.post(
                    "https://google.serper.dev/images",
                    headers={"X-API-KEY": serper_key, "Content-Type": "application/json"},
                    json={"q": q, "num": 10},
                )
                if resp.is_success:
                    return resp.json().get("images", [])
        except Exception as exc:
            logging.warning("[PHOTO] Serper error: %s", exc)
        return []

    # ── Collect results from whichever API is configured ──────────────
    items = await _search_google(query) if (api_key and cse_id) else []
    if not items:
        raw_serper = await _search_serper(query)
        # Normalise serper items to match Google CSE shape
        items = [
            {"link": it.get("imageUrl", ""),
             "title": it.get("title", ""),
             "snippet": it.get("link", "")}
            for it in raw_serper
        ]

    # ── Two-pass selection: OEM-domain first, then best generic ──────
    best_generic = None
    for item in items:
        link    = item.get("link", "")
        context = item.get("title", "") + " " + item.get("snippet", "")
        if not _accept_photo(link, context):
            continue
        if _is_priority_domain(link):
            logging.info("[PHOTO] OEM-domain match: %s", link)
            print(f"[PHOTO] Priority domain hit: {link[:100]}")
            return link
        if best_generic is None:
            best_generic = link

    if best_generic:
        logging.info("[PHOTO] Generic fallback: %s", best_generic)
        print(f"[PHOTO] Generic fallback: {best_generic[:100]}")
        return best_generic

    return None



async def fetch_online_part_image_url(oem_number: str = "", part_name: str = "") -> str | None:
    """
    البحث والتوفير التلقائي لصورة/كتالوج قطعة الغيار برقم OEM
    من خلال الكتالوجات المحلية (media/ & static/)، Google API، أو الكتالوج الداخلي.

    PIPELINE (in order):
      0. Local OEM-specific file search (media/catalogs/, media/, static/images/)
      1. Online dual-search  (diagram + photo concurrently via Google CSE / Serper)
      2. Category-map fallback (local static images → ALWAYS generates dual-view card)
      Default: static/images/default.jpg
    """
    english_term = translate_part_name_terms(part_name)
    BASE_DOMAIN  = (os.getenv("BASE_URL") or os.getenv("BASE_DOMAIN") or
                    "https://autoparts-ai.duckdns.org").rstrip("/")

    # ── All helpers are defined at function-top so they are always in scope ───
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    clean_oem    = normalize_oem_number(oem_number) if oem_number else ""
    raw_oem      = str(oem_number).strip()

    from app.services.catalog_generator import (
        generate_part_catalog_card,
        _is_already_catalog_card,
    )

    # ------------------------------------------------------------------
    # Helper A: resolve best matching local product photo for part_name
    # ------------------------------------------------------------------
    def _resolve_photo_path() -> str | None:
        """
        Map part name keywords → a local static product photo.
        Used as the RIGHT panel of the dual-view card.
        Uses PartMatcher first to resolve dialect terms, then falls back to keyword hints.
        """
        static_dir = os.path.join(project_root, "app", "static", "images")
        name_lower = (part_name or "").lower()

        # 1. Try PartMatcher exact/fuzzy match
        try:
            from app.services.part_matcher import get_part_matcher
            matcher = get_part_matcher()
            res = matcher.find_part(part_name)
            if res:
                part_id_map = {
                    "shock_absorber": "shock.jpg",
                    "coil_spring": "shock.jpg",
                    "strut_assembly": "shock.jpg",
                    "air_filter": "air_filter.jpg",
                    "oil_filter": "filter.jpg",
                    "fuel_filter": "filter.jpg",
                    "cabin_filter": "filter.jpg",
                    "alternator": "alternateur.jpg",
                    "ignition_lock": "antivol.jpg",
                    "camshaft": "camshaft.jpg",
                    "fender": "ail.jpg",
                    "accordion_hose": "accordion.jpg",
                    "brake_pad": "brake.jpg",
                    "brake_disc": "brake.jpg",
                    "brake_caliper": "brake.jpg",
                }
                if res.part_id in part_id_map:
                    candidate = os.path.join(static_dir, part_id_map[res.part_id])
                    if os.path.exists(candidate):
                        return candidate
        except Exception as exc:
            logging.warning("PartMatcher _resolve_photo_path error: %s", exc)

        # 2. Fallback to keyword hints
        hints = [
            ("filtre air",    "air_filter.jpg"),
            ("filter air",    "air_filter.jpg"),
            ("filtre huile",  "filter.jpg"),
            ("فلتر هواء",    "air_filter.jpg"),
            ("فلتر زيت",     "filter.jpg"),
            ("accordion",     "accordion.jpg"),
            ("durite filtre", "accordion.jpg"),
            ("durite filter", "accordion.jpg"),
            ("durite",        "durite.jpg"),
            ("alternateur",   "alternateur.jpg"),
            ("alternat",      "alternateur.jpg"),
            ("دينامو",        "alternateur.jpg"),
            ("amortisseur",   "shock.jpg"),
            ("amortiss",      "shock.jpg"),
            ("مساعد",         "shock.jpg"),
            ("camshaft",      "camshaft.jpg"),
            ("arbracame",     "camshaft.jpg"),
            ("arbre",         "camshaft.jpg"),
            ("antivol",       "antivol.jpg"),
            ("نيمان",         "antivol.jpg"),
            ("aile",          "ail.jpg"),
            ("فرفر",          "ail.jpg"),
            ("رفرف",          "ail.jpg"),
            ("ail",           "ail.jpg"),
            ("fender",        "ail.jpg"),
            ("brake",         "brake.jpg"),
            ("shock",         "shock.jpg"),
        ]
        for kw, fname in hints:
            if kw in name_lower:
                candidate = os.path.join(static_dir, fname)
                if os.path.exists(candidate):
                    return candidate
        return None

    # ------------------------------------------------------------------
    # Helper B: generate (or regenerate) a dual-view card, return URL
    # ------------------------------------------------------------------
    def _make_card_url(raw_diagram_path, photo_path=None) -> str:
        """
        Always purge any stale card, then call generate_part_catalog_card()
        with the dual-view layout enforced.  Both args may be None.
        """
        card_filename  = f"{clean_oem or normalize_oem_number(raw_oem) or 'PART'}_card.jpg"
        card_abs       = os.path.join(project_root, "media", "catalogs", card_filename)
        resolved_photo = photo_path or _resolve_photo_path()

        # ── Live execution trace ──────────────────────────────────────
        print(f"[DUALVIEW] Diagram Path Resolved: {raw_diagram_path}")
        print(f"[DUALVIEW] Photo Path Resolved:   {resolved_photo}")
        print(f"[DUALVIEW] Generator Mode Used:   Dual-View Forced")
        print(f"[DUALVIEW] Output Card Path:       {card_abs}")

        # Purge any stale card unconditionally
        if os.path.exists(card_abs):
            try:
                os.remove(card_abs)
                print(f"[DUALVIEW] Purged stale card: {card_abs}")
            except Exception as exc:
                logging.warning("[CACHE_PURGE] Could not delete '%s': %s", card_abs, exc)

        card_title = part_name if part_name else "AUTO PART ASSY"
        generate_part_catalog_card(
            oem_number=clean_oem or raw_oem,
            part_title=card_title,
            diagram_image_path=raw_diagram_path,
            photo_image_path=resolved_photo,
            output_path=card_abs,
        )
        url = f"{BASE_DOMAIN}/media/catalogs/{card_filename}"
        print(f"[DUALVIEW] Card URL returned: {url}")
        logging.info("[OEM_CARD] Dual-view -> '%s'  URL: %s", card_abs, url)
        return url

    # ==================================================================
    # 0.  Local OEM-specific file search
    # ==================================================================
    if oem_number:
        search_dirs = [
            os.path.join(project_root, "media", "catalogs"),
            os.path.join(project_root, "media"),
            os.path.join(project_root, "app", "static", "images"),
            os.path.join(project_root, "static", "images"),
        ]
        exts = [".png", ".jpg", ".jpeg", ".webp"]

        for abs_dir in search_dirs:
            if not os.path.isdir(abs_dir):
                continue

            # Phase A: exact filename match
            candidates = set()
            for ext in exts:
                for stem in (raw_oem, raw_oem.lower(), clean_oem, clean_oem.lower()):
                    candidates.add(f"{stem}{ext}")
                    candidates.add(f"{stem}_card{ext}")

            for fname in candidates:
                abs_path = os.path.join(abs_dir, fname)
                if not os.path.isfile(abs_path):
                    continue

                if "_card" in fname.lower():
                    # May already be a finished dual-view card
                    try:
                        with Image.open(abs_path) as probe:
                            probe.load()
                            if _is_already_catalog_card(probe, filepath=abs_path):
                                rel = os.path.relpath(abs_path, project_root)
                                url = f"{BASE_DOMAIN}/{rel.replace(os.sep, '/')}"
                                print(f"[DUALVIEW] Serving existing _card: {url}")
                                return url
                    except Exception as ex:
                        logging.warning("[OEM_CARD_ERR] %s: %s", abs_path, ex)

                # Raw OEM image → generate dual-view card
                print(f"[DUALVIEW] Raw source found: {abs_path} → dual-view")
                return _make_card_url(abs_path)

            # Phase B: fuzzy normalised-OEM match
            try:
                for f in os.listdir(abs_dir):
                    base, fext = os.path.splitext(f)
                    if fext.lower() not in exts:
                        continue
                    if normalize_oem_number(base) != clean_oem:
                        continue
                    abs_path = os.path.join(abs_dir, f)

                    if "_card" in f.lower():
                        try:
                            with Image.open(abs_path) as probe:
                                probe.load()
                                if _is_already_catalog_card(probe, filepath=abs_path):
                                    rel = os.path.relpath(abs_path, project_root)
                                    url = f"{BASE_DOMAIN}/{rel.replace(os.sep, '/')}"
                                    print(f"[DUALVIEW] Serving fuzzy _card: {url}")
                                    return url
                        except Exception as ex:
                            logging.warning("[OEM_FUZZY_CARD_ERR] %s: %s", abs_path, ex)

                    print(f"[DUALVIEW] Fuzzy raw found: {abs_path} → dual-view")
                    return _make_card_url(abs_path)
            except Exception as dir_err:
                logging.warning("[OEM_DIR_ERR] '%s': %s", abs_dir, dir_err)

        print(f"[DUALVIEW] No local OEM file for '{oem_number}' (clean='{clean_oem}')")

    # ==================================================================
    # 1.  Online dual-search  (diagram + photo run concurrently)
    # ==================================================================
    SERPER_API_KEY        = os.getenv("SERPER_API_KEY")
    GOOGLE_SEARCH_API_KEY = os.getenv("GOOGLE_SEARCH_API_KEY")
    GOOGLE_CSE_ID         = os.getenv("GOOGLE_CSE_ID")

    if oem_number and (GOOGLE_SEARCH_API_KEY or SERPER_API_KEY):
        import asyncio
        diagram_task = asyncio.ensure_future(
            _fetch_diagram_url(oem_number, GOOGLE_SEARCH_API_KEY, GOOGLE_CSE_ID, SERPER_API_KEY)
        )
        photo_task = asyncio.ensure_future(
            _fetch_photo_url(oem_number, GOOGLE_SEARCH_API_KEY, GOOGLE_CSE_ID, SERPER_API_KEY, part_name=part_name)
        )
        diagram_url, photo_url = await asyncio.gather(diagram_task, photo_task)
        print(f"[DUALVIEW] Online diagram_url={diagram_url}")
        print(f"[DUALVIEW] Online photo_url={photo_url}")

        if diagram_url or photo_url:
            return _make_card_url(diagram_url, photo_url)

    # ==================================================================
    # 2.  Category-map fallback (local static images)
    #     When oem_number is provided: ALWAYS generates dual-view via _make_card_url.
    #     When no oem_number: returns raw static URL (no card needed).
    # ==================================================================
    # Ordered longest/most-specific first to prevent false matches
    CATEGORY_MAP = [
        ("filtre air",    "air_filter.jpg"),
        ("filter air",    "air_filter.jpg"),
        ("filtre huile",  "filter.jpg"),
        ("فلتر هواء",    "air_filter.jpg"),
        ("فلتر زيت",     "filter.jpg"),
        ("durite filtre", "accordion.jpg"),
        ("durite filter", "accordion.jpg"),
        ("accordion",     "accordion.jpg"),
        ("durite",        "durite.jpg"),
        ("alternateur",   "alternateur.jpg"),
        ("alternat",      "alternateur.jpg"),
        ("دينامو",        "alternateur.jpg"),
        ("amortisseur",   "shock.jpg"),
        ("amortiss",      "shock.jpg"),
        ("مساعد",         "shock.jpg"),
        ("camshaft",      "camshaft.jpg"),
        ("arbracame",     "camshaft.jpg"),
        ("arbre",         "camshaft.jpg"),
        ("cames",         "camshaft.jpg"),
        ("arbra",         "camshaft.jpg"),
        ("antivol",       "antivol.jpg"),
        ("نيمان",         "antivol.jpg"),
        ("aile",          "ail.jpg"),
        ("fender",        "ail.jpg"),
        ("رفرف",          "ail.jpg"),
        ("ail",           "ail.jpg"),
        ("air filter",    "air_filter.jpg"),
        ("oil filter",    "filter.jpg"),
        ("brake",         "brake.jpg"),
        ("shock",         "shock.jpg"),
        ("عمود الكامات",  "camshaft.jpg"),
        ("شجرة الكامات",  "camshaft.jpg"),
    ]

    term_lower     = english_term.lower()
    part_lower     = (part_name or "").lower()
    static_img_dir = os.path.join(project_root, "app", "static", "images")

    for key, img_fname in CATEGORY_MAP:
        if key not in term_lower and key not in part_lower:
            continue

        local_img = os.path.join(static_img_dir, img_fname)
        print(f"[DUALVIEW] Category-map hit: key='{key}' → {img_fname}  exists={os.path.exists(local_img)}")

        if oem_number and os.path.exists(local_img):
            resolved_photo = _resolve_photo_path()

            # If diagram == photo (same file), force left panel to placeholder
            if resolved_photo and (os.path.abspath(local_img) == os.path.abspath(resolved_photo)):
                print(f"[DUALVIEW] diagram==photo ({img_fname}) → placeholder on left")
                return _make_card_url(None, local_img)

            return _make_card_url(local_img, resolved_photo)

        # No OEM → return raw static URL (WhatsApp will serve it directly)
        raw_url = f"{BASE_DOMAIN}/static/images/{img_fname}"
        print(f"[DUALVIEW] No OEM → raw static URL: {raw_url}")
        return raw_url

    default_url = f"{BASE_DOMAIN}/static/images/default.jpg"
    print(f"[DUALVIEW] No category match → default: {default_url}")
    return default_url
