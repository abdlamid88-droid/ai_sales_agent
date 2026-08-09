import os
import sqlite3
from dotenv import load_dotenv

# 1. استدعاء load_dotenv() لتحميل ملف البيئة .env
load_dotenv()

try:
    import asyncpg
except ImportError:
    asyncpg = None

try:
    import aiosqlite
except ImportError:
    aiosqlite = None

# 2. حماية DATABASE_URL من إرجاع None عبر وضع قيمة افتراضية احتياطية (Fallback)
RAW_DB_URL = os.getenv("DATABASE_URL")
if not RAW_DB_URL or RAW_DB_URL.strip() == "":
    DATABASE_URL = "sqlite:///./sales_agent.db"
else:
    DATABASE_URL = RAW_DB_URL.strip()

INIT_URL = DATABASE_URL.replace("postgresql+asyncpg://", "postgres://") if DATABASE_URL else "sqlite:///./sales_agent.db"
IS_SQLITE = "sqlite" in DATABASE_URL.lower() or asyncpg is None

# 3. دالة التحقق والحصول على اتصال آمن بقاعدة البيانات
async def get_db_connection():
    if not DATABASE_URL:
        raise ValueError("DATABASE_URL is invalid or empty")
        
    db_path = DATABASE_URL.replace("sqlite+aiosqlite:///", "").replace("sqlite:///", "")
    if not db_path or db_path == DATABASE_URL or "postgresql" in db_path:
        db_path = "sales_agent.db"

    if IS_SQLITE or asyncpg is None:
        if aiosqlite is not None:
            conn = await aiosqlite.connect(db_path)
            conn.row_factory = aiosqlite.Row
            return conn
        else:
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            return conn
    else:
        try:
            conn = await asyncpg.connect(INIT_URL)
            return conn
        except Exception as pg_err:
            print(f"Warning: Could not connect to PostgreSQL ({pg_err}). Falling back to SQLite database connection.")
            if aiosqlite is not None:
                conn = await aiosqlite.connect(db_path)
                conn.row_factory = aiosqlite.Row
                return conn
            else:
                conn = sqlite3.connect(db_path)
                conn.row_factory = sqlite3.Row
                return conn

async def init_db():
    """إنشاء الجداول وحقن بيانات قطع الغيار التجريبية إذا كانت قاعدة البيانات فارغة"""
    db_url = DATABASE_URL if DATABASE_URL else "sqlite:///./sales_agent.db"
    db_path = db_url.replace("sqlite+aiosqlite:///", "").replace("sqlite:///", "")
    if not db_path or db_path == db_url:
        db_path = "sales_agent.db"

    if IS_SQLITE or asyncpg is None:
            
        if aiosqlite is not None:
            async with aiosqlite.connect(db_path) as conn:
                await conn.execute('''
                    CREATE TABLE IF NOT EXISTS leads (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        phone TEXT UNIQUE NOT NULL,
                        name TEXT,
                        interested_product TEXT,
                        interaction_count INTEGER DEFAULT 1,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );
                ''')
                await conn.execute('''
                    CREATE TABLE IF NOT EXISTS products (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        oem_number TEXT UNIQUE NOT NULL,
                        clean_oem TEXT NOT NULL,
                        name_ar TEXT NOT NULL,
                        name_fr TEXT NOT NULL,
                        description TEXT,
                        primary_image_url TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );
                ''')
                await conn.execute('''
                    CREATE TABLE IF NOT EXISTS inventory (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        product_id INTEGER UNIQUE REFERENCES products(id) ON DELETE CASCADE,
                        price REAL NOT NULL,
                        stock_quantity INTEGER NOT NULL DEFAULT 0,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );
                ''')
                await conn.execute('''
                    CREATE TABLE IF NOT EXISTS cross_references (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        product_id INTEGER REFERENCES products(id) ON DELETE CASCADE,
                        alternative_product_id INTEGER REFERENCES products(id) ON DELETE CASCADE,
                        notes TEXT
                    );
                ''')
                await conn.commit()
                
                async with conn.execute('SELECT COUNT(*) FROM products;') as cursor:
                    row = await cursor.fetchone()
                    if row[0] == 0:
                        await _seed_sample_data_sqlite(conn)
        else:
            with sqlite3.connect(db_path) as conn:
                conn.execute('''
                    CREATE TABLE IF NOT EXISTS leads (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        phone TEXT UNIQUE NOT NULL,
                        name TEXT,
                        interested_product TEXT,
                        interaction_count INTEGER DEFAULT 1,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );
                ''')
                conn.execute('''
                    CREATE TABLE IF NOT EXISTS products (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        oem_number TEXT UNIQUE NOT NULL,
                        clean_oem TEXT NOT NULL,
                        name_ar TEXT NOT NULL,
                        name_fr TEXT NOT NULL,
                        description TEXT,
                        primary_image_url TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );
                ''')
                conn.execute('''
                    CREATE TABLE IF NOT EXISTS inventory (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        product_id INTEGER UNIQUE REFERENCES products(id) ON DELETE CASCADE,
                        price REAL NOT NULL,
                        stock_quantity INTEGER NOT NULL DEFAULT 0,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );
                ''')
                conn.execute('''
                    CREATE TABLE IF NOT EXISTS cross_references (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        product_id INTEGER REFERENCES products(id) ON DELETE CASCADE,
                        alternative_product_id INTEGER REFERENCES products(id) ON DELETE CASCADE,
                        notes TEXT
                    );
                ''')
                conn.commit()
                cursor = conn.execute('SELECT COUNT(*) FROM products;')
                row = cursor.fetchone()
                if row[0] == 0:
                    _seed_sample_data_sync_sqlite(conn)
    else:
        if asyncpg is None:
            print("Warning: asyncpg module unavailable. Falling back to SQLite.")
            return await _init_sqlite_db()

        try:
            conn = await asyncpg.connect(INIT_URL)
        except Exception as pg_err:
            print(f"Warning: Could not connect to PostgreSQL ({pg_err}). Falling back to SQLite database.")
            with sqlite3.connect(db_path) as conn:
                conn.execute('''
                    CREATE TABLE IF NOT EXISTS leads (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        phone TEXT UNIQUE NOT NULL,
                        name TEXT,
                        interested_product TEXT,
                        interaction_count INTEGER DEFAULT 1,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );
                ''')
                conn.execute('''
                    CREATE TABLE IF NOT EXISTS products (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        oem_number TEXT UNIQUE NOT NULL,
                        clean_oem TEXT NOT NULL,
                        name_ar TEXT NOT NULL,
                        name_fr TEXT NOT NULL,
                        description TEXT,
                        primary_image_url TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );
                ''')
                conn.execute('''
                    CREATE TABLE IF NOT EXISTS inventory (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        product_id INTEGER UNIQUE REFERENCES products(id) ON DELETE CASCADE,
                        price REAL NOT NULL,
                        stock_quantity INTEGER NOT NULL DEFAULT 0,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );
                ''')
                conn.execute('''
                    CREATE TABLE IF NOT EXISTS cross_references (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        product_id INTEGER REFERENCES products(id) ON DELETE CASCADE,
                        alternative_product_id INTEGER REFERENCES products(id) ON DELETE CASCADE,
                        notes TEXT
                    );
                ''')
                conn.commit()
                cursor = conn.execute('SELECT COUNT(*) FROM products;')
                row = cursor.fetchone()
                if row[0] == 0:
                    _seed_sample_data_sync_sqlite(conn)
            return

        try:
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS leads (
                    id SERIAL PRIMARY KEY,
                    phone VARCHAR(20) UNIQUE NOT NULL,
                    name VARCHAR(100),
                    interested_product VARCHAR(255),
                    interaction_count INT DEFAULT 1,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            ''')
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS products (
                    id SERIAL PRIMARY KEY,
                    oem_number VARCHAR(100) UNIQUE NOT NULL,
                    clean_oem VARCHAR(100) NOT NULL,
                    name_ar VARCHAR(255) NOT NULL,
                    name_fr VARCHAR(255) NOT NULL,
                    description TEXT,
                    primary_image_url TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            ''')
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS inventory (
                    id SERIAL PRIMARY KEY,
                    product_id INT UNIQUE REFERENCES products(id) ON DELETE CASCADE,
                    price NUMERIC(10, 2) NOT NULL,
                    stock_quantity INT NOT NULL DEFAULT 0,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            ''')
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS cross_references (
                    id SERIAL PRIMARY KEY,
                    product_id INT REFERENCES products(id) ON DELETE CASCADE,
                    alternative_product_id INT REFERENCES products(id) ON DELETE CASCADE,
                    notes VARCHAR(255)
                );
            ''')
            
            count = await conn.fetchval('SELECT COUNT(*) FROM products;')
            if count == 0:
                await _seed_sample_data_pg(conn)
        finally:
            await conn.close()

async def _seed_sample_data_sqlite(conn):
    products = [
        ("1K0129620D", "1k0129620d", "فلتر هواء - جولف 6 / باسات", "Filtre à air - Golf 6 / Passat", "فلتر هواء أصلي محرك 2.0 TDI", "https://images.example.com/parts/1k0129620d.jpg", 3500.0, 15),
        ("1K0129620E", "1k0129620e", "فلتر هواء مان فيلتر C35154", "Filtre à air Mann-Filter C35154", "بديل ممتاذ متوافق من شركة Mann Filter", "https://images.example.com/parts/mann_c35154.jpg", 3200.0, 8),
        ("06L115562A", "06l115562a", "مصفاة زيت (فلتر زيت) - أودي / فولوكسفاغن 2.0 TFSI", "Filtre à huile - Audi / VW 2.0 TFSI", "فلتر زيت أصلي VAG", "https://images.example.com/parts/06l115562a.jpg", 2200.0, 0),
        ("HU7008Z", "hu7008z", "فلتر زيت مان فيلتر HU7008z", "Filtre à huile Mann-Filter HU7008z", "بديل ألمانيا متوفر جودة عالية", "https://images.example.com/parts/hu7008z.jpg", 1900.0, 20),
        ("5Q0407151A", "5q0407151a", "ذراع تعليق أمامي (Triangle) - سيات ليون / جولف 7", "Triangle de suspension AV - Leon / Golf 7", "مثلث تعليق ألومنيوم جهة اليمين", "https://images.example.com/parts/5q0407151a.jpg", 14500.0, 4)
    ]
    
    for p in products:
        cursor = await conn.execute('''
            INSERT INTO products (oem_number, clean_oem, name_ar, name_fr, description, primary_image_url)
            VALUES (?, ?, ?, ?, ?, ?);
        ''', (p[0], p[1], p[2], p[3], p[4], p[5]))
        prod_id = cursor.lastrowid
        await conn.execute('''
            INSERT INTO inventory (product_id, price, stock_quantity)
            VALUES (?, ?, ?);
        ''', (prod_id, p[6], p[7]))

    await conn.execute('INSERT INTO cross_references (product_id, alternative_product_id, notes) VALUES (1, 2, "بديل مان فيلتر متوافق");')
    await conn.execute('INSERT INTO cross_references (product_id, alternative_product_id, notes) VALUES (3, 4, "بديل متوفر في المخزون");')
    await conn.commit()

def _seed_sample_data_sync_sqlite(conn):
    products = [
        ("1K0129620D", "1k0129620d", "فلتر هواء - جولف 6 / باسات", "Filtre à air - Golf 6 / Passat", "فلتر هواء أصلي محرك 2.0 TDI", "https://images.example.com/parts/1k0129620d.jpg", 3500.0, 15),
        ("1K0129620E", "1k0129620e", "فلتر هواء مان فيلتر C35154", "Filtre à air Mann-Filter C35154", "بديل ممتاذ متوافق من شركة Mann Filter", "https://images.example.com/parts/mann_c35154.jpg", 3200.0, 8),
        ("06L115562A", "06l115562a", "مصفاة زيت (فلتر زيت) - أودي / فولوكسفاغن 2.0 TFSI", "Filtre à huile - Audi / VW 2.0 TFSI", "فلتر زيت أصلي VAG", "https://images.example.com/parts/06l115562a.jpg", 2200.0, 0),
        ("HU7008Z", "hu7008z", "فلتر زيت مان فيلتر HU7008z", "Filtre à huile Mann-Filter HU7008z", "بديل ألمانيا متوفر جودة عالية", "https://images.example.com/parts/hu7008z.jpg", 1900.0, 20),
        ("5Q0407151A", "5q0407151a", "ذراع تعليق أمامي (Triangle) - سيات ليون / جولف 7", "Triangle de suspension AV - Leon / Golf 7", "مثلث تعليق ألومنيوم جهة اليمين", "https://images.example.com/parts/5q0407151a.jpg", 14500.0, 4)
    ]
    
    for p in products:
        cursor = conn.execute('''
            INSERT INTO products (oem_number, clean_oem, name_ar, name_fr, description, primary_image_url)
            VALUES (?, ?, ?, ?, ?, ?);
        ''', (p[0], p[1], p[2], p[3], p[4], p[5]))
        prod_id = cursor.lastrowid
        conn.execute('''
            INSERT INTO inventory (product_id, price, stock_quantity)
            VALUES (?, ?, ?);
        ''', (prod_id, p[6], p[7]))

    conn.execute('INSERT INTO cross_references (product_id, alternative_product_id, notes) VALUES (1, 2, "بديل مان فيلتر متوافق");')
    conn.execute('INSERT INTO cross_references (product_id, alternative_product_id, notes) VALUES (3, 4, "بديل متوفر في المخزون");')
    conn.commit()

async def _seed_sample_data_pg(conn):
    products = [
        ("1K0129620D", "1k0129620d", "فلتر هواء - جولف 6 / باسات", "Filtre à air - Golf 6 / Passat", "فلتر هواء أصلي محرك 2.0 TDI", "https://images.example.com/parts/1k0129620d.jpg", 3500.0, 15),
        ("1K0129620E", "1k0129620e", "فلتر هواء مان فيلتر C35154", "Filtre à air Mann-Filter C35154", "بديل ممتاذ متوافق من شركة Mann Filter", "https://images.example.com/parts/mann_c35154.jpg", 3200.0, 8),
        ("06L115562A", "06l115562a", "مصفاة زيت (فلتر زيت) - أودي / فولوكسفاغن 2.0 TFSI", "Filtre à huile - Audi / VW 2.0 TFSI", "فلتر زيت أصلي VAG", "https://images.example.com/parts/06l115562a.jpg", 2200.0, 0),
        ("HU7008Z", "hu7008z", "فلتر زيت مان فيلتر HU7008z", "Filtre à huile Mann-Filter HU7008z", "بديل ألمانيا متوفر جودة عالية", "https://images.example.com/parts/hu7008z.jpg", 1900.0, 20),
        ("5Q0407151A", "5q0407151a", "ذراع تعليق أمامي (Triangle) - سيات ليون / جولف 7", "Triangle de suspension AV - Leon / Golf 7", "مثلث تعليق ألومنيوم جهة اليمين", "https://images.example.com/parts/5q0407151a.jpg", 14500.0, 4)
    ]
    
    for p in products:
        prod_id = await conn.fetchval('''
            INSERT INTO products (oem_number, clean_oem, name_ar, name_fr, description, primary_image_url)
            VALUES ($1, $2, $3, $4, $5, $6) RETURNING id;
        ''', p[0], p[1], p[2], p[3], p[4], p[5])
        await conn.execute('''
            INSERT INTO inventory (product_id, price, stock_quantity)
            VALUES ($1, $2, $3);
        ''', prod_id, p[6], p[7])

    await conn.execute('INSERT INTO cross_references (product_id, alternative_product_id, notes) VALUES (1, 2, $1);', "بديل مان فيلتر متوافق")
    await conn.execute('INSERT INTO cross_references (product_id, alternative_product_id, notes) VALUES (3, 4, $1);', "بديل متوفر في المخزون")

async def save_or_update_lead(phone: str, name: str, product_mention: str):
    """حفظ بيانات العميل أو تحديثها"""
    db_url = DATABASE_URL if DATABASE_URL else "sqlite:///./sales_agent.db"
    if IS_SQLITE or asyncpg is None:
        db_path = db_url.replace("sqlite+aiosqlite:///", "").replace("sqlite:///", "")
        if not db_path or db_path == db_url:
            db_path = "sales_agent.db"
        if aiosqlite is not None:
            async with aiosqlite.connect(db_path) as conn:
                await conn.execute('''
                    INSERT INTO leads (phone, name, interested_product)
                    VALUES (?, ?, ?)
                    ON CONFLICT(phone) DO UPDATE SET
                        name = EXCLUDED.name,
                        interested_product = COALESCE(EXCLUDED.interested_product, leads.interested_product),
                        interaction_count = leads.interaction_count + 1,
                        updated_at = CURRENT_TIMESTAMP;
                ''', (phone, name, product_mention))
                await conn.commit()
        else:
            with sqlite3.connect(db_path) as conn:
                conn.execute('''
                    INSERT INTO leads (phone, name, interested_product)
                    VALUES (?, ?, ?)
                    ON CONFLICT(phone) DO UPDATE SET
                        name = EXCLUDED.name,
                        interested_product = COALESCE(EXCLUDED.interested_product, leads.interested_product),
                        interaction_count = leads.interaction_count + 1,
                        updated_at = CURRENT_TIMESTAMP;
                ''', (phone, name, product_mention))
                conn.commit()
    else:
        if asyncpg is None:
            return
        conn = await asyncpg.connect(INIT_URL)
        try:
            await conn.execute('''
                INSERT INTO leads (phone, name, interested_product)
                VALUES ($1, $2, $3)
                ON CONFLICT (phone) 
                DO UPDATE SET 
                    name = EXCLUDED.name,
                    interested_product = CASE 
                        WHEN EXCLUDED.interested_product IS NOT NULL THEN EXCLUDED.interested_product 
                        ELSE leads.interested_product 
                    END,
                    interaction_count = leads.interaction_count + 1,
                    updated_at = CURRENT_TIMESTAMP;
            ''', phone, name, product_mention)
        finally:
            await conn.close()
