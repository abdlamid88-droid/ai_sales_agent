import re
import os
import sqlite3
try:
    import asyncpg
except ImportError:
    asyncpg = None
try:
    import aiosqlite
except ImportError:
    aiosqlite = None

from app.database import IS_SQLITE, INIT_URL, DATABASE_URL

STOP_WORDS = {
    'هل', 'عندكم', 'هذا', 'هذي', 'هذه', 'وبكم', 'السعر', 'سعر', 'عن', 'اريد', 'أريد', 'ابحث', 'أبحث', 
    'سيارة', 'سلام', 'عليكم', 'مرحبا', 'مرحباً', 'من', 'فضلك', 'بكم', 'حبيت', 'نسقسيك', 
    'خي', 'خويا', 'في', 'على', 'ما', 'هو', 'هي', 'لو', 'سمحت', 'عندك', 'تتوفر', 'متوفر',
    'كاين', 'كاينش', 'بياسة', 'البياسة', 'شحال', 'بشحال', 'سومة', 'السومة', 'راني', 'نحوس',
    'متوفرة', 'متاحة', 'موجودة', 'الرسالة', 'رسالة', 'رسائل', 'الرسائل', 'جوابا', 'جواب', 'نتلق',
    'هناك', 'مشكل', 'مشكلة', 'أعقد', 'اعقد', 'اللهجة', 'الجزائرية', 'قبل', 'يجيب', 'مثل', 'عدم', 'رد', 'الرد',
    'نحتاج', 'خصني', 'بغيت', 'حاب', 'حابة', 'نعرف', 'شوف', 'قل', 'قولي', 'تاع', 'ديال', 'تاعي', 'بدنا'
}

PART_TYPE_KEYWORDS = [
    'ARBRA', 'ARBRE', 'CAME', 'AMORTIS', 'FILTR', 'DURIT', 'ALTERN', 'POMPE', 
    'PLAQUET', 'DISQ', 'AILE', 'AIL', 'BOUGIE', 'RADIAT', 'FAR', 'FEU', 'PARE',
    'ANTIVOL', 'NEIMAN', 'NIMAN', 'LOCK', 'STARTER', 'DEMAR', 'SERPENT',
    'مساعد', 'قفل', 'نيمان', 'انتفول', 'انتيفول', 'امورتيسور', 'دينامو', 'دومار',
    'بوجي', 'ديسك', 'بلاكيط', 'روتيل', 'بيالاط', 'فلتر', 'فيلتر'
]

CAR_MODELS = [
    'CIELO', 'LANOS', 'RACER', 'AVEO', 'OPTRA', 'SAIL', 'ACCENT', 'SWIFT', 'ATOS', 'PIC', 
    'SPARK', 'MARUTI', 'ALTO', 'TUC', 'SPORTGE', 'GOLF', 'PASSAT', 'RIO', 'CERATO', 
    'ELANTRA', 'CRETA', 'SANTAFE', 'CARENS', 'MATRIX', 'I30', 'NUB', 'LANOS',
    'QQ', 'CHERY', 'كيو', 'كيوكيو', 'شيري', 'كوكو', 'CLIO', 'كليو', 'SYMBOL', 'سيمبول',
    'MEGANE', 'ميغان', 'LOGAN', 'لوغان', 'STEPWAY', 'ستيبواي', 'DUSTER', 'داستر',
    'YARIS', 'ياريس', 'I20', 'I10', 'PICANTO', 'بيكانتو', 'POLO', 'بولو', 'LEON', 'ليون'
]

def clean_input_text(text: str) -> str:
    """إزالة كافة الرموز والممسافات للحصول على صيغة رقم OEM نظيفة للبحث"""
    if not text:
        return ""
    return re.sub(r'[^a-zA-Z0-9]', '', text).lower()

def is_valid_oem_clean(clean_kw: str) -> bool:
    """تجنب البحث برقم OEM النظيف للأرقام السعة الحجمية القصيرة مثل 15 الناتجة عن 1.5"""
    if not clean_kw or len(clean_kw) < 4:
        return False
    if clean_kw.isdigit() and len(clean_kw) <= 3:
        return False
    return True

def extract_search_keywords(text: str) -> list[str]:
    """استخراج الكلمات الرئيسية الهامة للبحث وتصفية الكلمات التفاعلية الزائدة"""
    if not text:
        return []
    words = re.findall(r'[\w\.-]+', text)
    return [w for w in words if w.lower() not in STOP_WORDS and len(w) > 1]

async def search_part_and_alternatives(query_text: str) -> dict:
    """
    البحث عن قطعة غيار في قاعدة البيانات بالاعتماد على رقم OEM أو الاسم (عربي/فرنسي)،
    واستخراج تفاصيل المخزون والسعر، بالإضافة إلى البدائل المتقاطعة (Cross-References).
    """
    cleaned_query = clean_input_text(query_text)
    raw_query = query_text.strip() if query_text else ""
    keywords = extract_search_keywords(raw_query)

    # Dialect Synonym Expansion via PartMatcher
    try:
        from app.services.part_matcher import get_part_matcher
        matcher = get_part_matcher()
        res = matcher.find_part(raw_query)
        if res:
            for extra_kw in [res.standard_ar, res.standard_en, res.matched_synonym, res.category]:
                if extra_kw and extra_kw not in keywords:
                    keywords.append(extra_kw)
    except Exception as exc:
        pass

    if IS_SQLITE or asyncpg is None:
        return await _search_part_sqlite(raw_query, cleaned_query, keywords)
    else:
        return await _search_part_pg(raw_query, cleaned_query, keywords)

async def _search_part_sqlite(raw_query: str, cleaned_query: str, keywords: list[str]) -> dict:
    db_url = DATABASE_URL if DATABASE_URL else "sqlite:///./sales_agent.db"
    db_path = db_url.replace("sqlite+aiosqlite:///", "").replace("sqlite:///", "")
    if not db_path or db_path == db_url or "postgresql" in db_path:
        db_path = "sales_agent.db"
        
    primary_type = None
    detected_models = []
    for kw in keywords:
        kw_upper = kw.upper()
        if any(pt in kw_upper for pt in PART_TYPE_KEYWORDS) and not primary_type:
            primary_type = kw
        if any(cm in kw_upper for cm in CAR_MODELS):
            detected_models.append(kw)

    if aiosqlite is not None:
        async with aiosqlite.connect(db_path) as conn:
            conn.row_factory = aiosqlite.Row
            main_product = None
            
            # 1. Clean OEM Exact or Prefix Match
            if is_valid_oem_clean(cleaned_query):
                async with conn.execute('''
                    SELECT p.id, p.oem_number, p.clean_oem, p.name_ar, p.name_fr, p.description, p.primary_image_url, i.price, i.stock_quantity
                    FROM products p
                    JOIN inventory i ON p.id = i.product_id
                    WHERE p.clean_oem = ? OR p.clean_oem LIKE ?;
                ''', (cleaned_query, f"%{cleaned_query}%")) as cursor:
                    main_product = await cursor.fetchone()

            # 2. Scored Keyword Search (Strict matching of primary part type & car models)
            if not main_product and keywords:
                async with conn.execute('''
                    SELECT p.id, p.oem_number, p.clean_oem, p.name_ar, p.name_fr, p.description, p.primary_image_url, i.price, i.stock_quantity
                    FROM products p
                    JOIN inventory i ON p.id = i.product_id;
                ''') as cursor:
                    all_products = await cursor.fetchall()
                    best_product = None
                    best_score = 0
                    
                    for prod in all_products:
                        p_text = f"{prod['name_ar']} {prod['name_fr']} {prod['oem_number']} {prod['description']}".upper()
                        score = 0
                        
                        if primary_type:
                            if primary_type.upper() in p_text:
                                score += 15
                            elif any(pt in p_text for pt in PART_TYPE_KEYWORDS if pt in primary_type.upper()):
                                score += 10
                                
                        if detected_models:
                            matched_m = False
                            for m in detected_models:
                                if m.upper() in p_text:
                                    score += 10
                                    matched_m = True
                                    
                        for kw in keywords:
                            if kw.upper() in p_text:
                                score += 3
                                
                        if score > best_score:
                            best_score = score
                            best_product = prod
                            
                    if best_product:
                        main_product = best_product

            if not main_product:
                return {
                    "found": False,
                    "query": raw_query,
                    "product": None,
                    "alternatives": []
                }

            product_id = main_product["id"]
            product_dict = {
                "id": main_product["id"],
                "oem_number": main_product["oem_number"],
                "clean_oem": main_product["clean_oem"],
                "name_ar": main_product["name_ar"],
                "name_fr": main_product["name_fr"],
                "description": main_product["description"],
                "primary_image_url": main_product["primary_image_url"],
                "price": float(main_product["price"]),
                "stock_quantity": int(main_product["stock_quantity"]),
                "in_stock": int(main_product["stock_quantity"]) > 0
            }

            alternatives = []
            async with conn.execute('''
                SELECT p.id, p.oem_number, p.name_ar, p.name_fr, p.description, p.primary_image_url, i.price, i.stock_quantity, cr.notes
                FROM cross_references cr
                JOIN products p ON p.id = (CASE WHEN cr.product_id = ? THEN cr.alternative_product_id ELSE cr.product_id END)
                JOIN inventory i ON p.id = i.product_id
                WHERE cr.product_id = ? OR cr.alternative_product_id = ?;
            ''', (product_id, product_id, product_id)) as cursor:
                alt_rows = await cursor.fetchall()
                for alt in alt_rows:
                    alternatives.append({
                        "id": alt["id"],
                        "oem_number": alt["oem_number"],
                        "name_ar": alt["name_ar"],
                        "name_fr": alt["name_fr"],
                        "description": alt["description"],
                        "primary_image_url": alt["primary_image_url"],
                        "price": float(alt["price"]),
                        "stock_quantity": int(alt["stock_quantity"]),
                        "in_stock": int(alt["stock_quantity"]) > 0,
                        "notes": alt["notes"]
                    })

            return {
                "found": True,
                "query": raw_query,
                "product": product_dict,
                "alternatives": alternatives
            }
    else:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            main_product = None
            
            if is_valid_oem_clean(cleaned_query):
                cursor.execute('''
                    SELECT p.id, p.oem_number, p.clean_oem, p.name_ar, p.name_fr, p.description, p.primary_image_url, i.price, i.stock_quantity
                    FROM products p
                    JOIN inventory i ON p.id = i.product_id
                    WHERE p.clean_oem = ? OR p.clean_oem LIKE ?;
                ''', (cleaned_query, f"%{cleaned_query}%"))
                main_product = cursor.fetchone()

            if not main_product and keywords:
                cursor.execute('''
                    SELECT p.id, p.oem_number, p.clean_oem, p.name_ar, p.name_fr, p.description, p.primary_image_url, i.price, i.stock_quantity
                    FROM products p
                    JOIN inventory i ON p.id = i.product_id;
                ''')
                all_products = cursor.fetchall()
                best_product = None
                best_score = 0
                
                for prod in all_products:
                    p_text = f"{prod['name_ar']} {prod['name_fr']} {prod['oem_number']} {prod['description']}".upper()
                    score = 0
                    
                    if primary_type:
                        if primary_type.upper() in p_text:
                            score += 10
                        else:
                            continue
                            
                    if detected_models:
                        matched_m = False
                        for m in detected_models:
                            if m.upper() in p_text:
                                score += 5
                                matched_m = True
                        if not matched_m:
                            continue
                            
                    for kw in keywords:
                        if kw.upper() in p_text:
                            score += 2
                            
                    if score > best_score:
                        best_score = score
                        best_product = prod
                        
                if best_product:
                    main_product = best_product

            if not main_product:
                return {
                    "found": False,
                    "query": raw_query,
                    "product": None,
                    "alternatives": []
                }

            product_id = main_product["id"]
            product_dict = {
                "id": main_product["id"],
                "oem_number": main_product["oem_number"],
                "clean_oem": main_product["clean_oem"],
                "name_ar": main_product["name_ar"],
                "name_fr": main_product["name_fr"],
                "description": main_product["description"],
                "primary_image_url": main_product["primary_image_url"],
                "price": float(main_product["price"]),
                "stock_quantity": int(main_product["stock_quantity"]),
                "in_stock": int(main_product["stock_quantity"]) > 0
            }

            cursor.execute('''
                SELECT p.id, p.oem_number, p.name_ar, p.name_fr, p.description, p.primary_image_url, i.price, i.stock_quantity, cr.notes
                FROM cross_references cr
                JOIN products p ON p.id = (CASE WHEN cr.product_id = ? THEN cr.alternative_product_id ELSE cr.product_id END)
                JOIN inventory i ON p.id = i.product_id
                WHERE cr.product_id = ? OR cr.alternative_product_id = ?;
            ''', (product_id, product_id, product_id))
            alt_rows = cursor.fetchall()
            alternatives = []
            for alt in alt_rows:
                alternatives.append({
                    "id": alt["id"],
                    "oem_number": alt["oem_number"],
                    "name_ar": alt["name_ar"],
                    "name_fr": alt["name_fr"],
                    "description": alt["description"],
                    "primary_image_url": alt["primary_image_url"],
                    "price": float(alt["price"]),
                    "stock_quantity": int(alt["stock_quantity"]),
                    "in_stock": int(alt["stock_quantity"]) > 0,
                    "notes": alt["notes"]
                })

            return {
                "found": True,
                "query": raw_query,
                "product": product_dict,
                "alternatives": alternatives
            }

async def _search_part_pg(raw_query: str, cleaned_query: str, keywords: list[str]) -> dict:
    if asyncpg is None:
        return await _search_part_sqlite(raw_query, cleaned_query, keywords)
        
    try:
        conn = await asyncpg.connect(INIT_URL)
    except Exception:
        return await _search_part_sqlite(raw_query, cleaned_query, keywords)

    try:
        main_product = None
        if is_valid_oem_clean(cleaned_query):
            main_product = await conn.fetchrow('''
                SELECT p.id, p.oem_number, p.clean_oem, p.name_ar, p.name_fr, p.description, p.primary_image_url, i.price, i.stock_quantity
                FROM products p
                JOIN inventory i ON p.id = i.product_id
                WHERE p.clean_oem = $1 OR p.clean_oem ILIKE $2;
            ''', cleaned_query, f"%{cleaned_query}%")

        if not main_product and keywords:
            for kw in keywords:
                clean_kw = clean_input_text(kw)
                main_product = await conn.fetchrow('''
                    SELECT p.id, p.oem_number, p.clean_oem, p.name_ar, p.name_fr, p.description, p.primary_image_url, i.price, i.stock_quantity
                    FROM products p
                    JOIN inventory i ON p.id = i.product_id
                    WHERE p.name_ar ILIKE $1 OR p.name_fr ILIKE $1 OR p.description ILIKE $1;
                ''', f"%{kw}%")
                if main_product:
                    break

        if not main_product and raw_query:
            main_product = await conn.fetchrow('''
                SELECT p.id, p.oem_number, p.clean_oem, p.name_ar, p.name_fr, p.description, p.primary_image_url, i.price, i.stock_quantity
                FROM products p
                JOIN inventory i ON p.id = i.product_id
                WHERE p.name_ar ILIKE $1 OR p.name_fr ILIKE $1 OR p.oem_number ILIKE $1;
            ''', f"%{raw_query}%")

        if not main_product:
            return {
                "found": False,
                "query": raw_query,
                "product": None,
                "alternatives": []
            }

        product_id = main_product["id"]
        product_dict = {
            "id": main_product["id"],
            "oem_number": main_product["oem_number"],
            "clean_oem": main_product["clean_oem"],
            "name_ar": main_product["name_ar"],
            "name_fr": main_product["name_fr"],
            "description": main_product["description"],
            "primary_image_url": main_product["primary_image_url"],
            "price": float(main_product["price"]),
            "stock_quantity": int(main_product["stock_quantity"]),
            "in_stock": int(main_product["stock_quantity"]) > 0
        }

        alt_rows = await conn.fetch('''
            SELECT p.id, p.oem_number, p.name_ar, p.name_fr, p.description, p.primary_image_url, i.price, i.stock_quantity, cr.notes
            FROM cross_references cr
            JOIN products p ON p.id = (CASE WHEN cr.product_id = $1 THEN cr.alternative_product_id ELSE cr.product_id END)
            JOIN inventory i ON p.id = i.product_id
            WHERE cr.product_id = $1 OR cr.alternative_product_id = $1;
        ''', product_id)

        alternatives = []
        for alt in alt_rows:
            alternatives.append({
                "id": alt["id"],
                "oem_number": alt["oem_number"],
                "name_ar": alt["name_ar"],
                "name_fr": alt["name_fr"],
                "description": alt["description"],
                "primary_image_url": alt["primary_image_url"],
                "price": float(alt["price"]),
                "stock_quantity": int(alt["stock_quantity"]),
                "in_stock": int(alt["stock_quantity"]) > 0,
                "notes": alt["notes"]
            })

        return {
            "found": True,
            "query": raw_query,
            "product": product_dict,
            "alternatives": alternatives
        }
    finally:
        await conn.close()
