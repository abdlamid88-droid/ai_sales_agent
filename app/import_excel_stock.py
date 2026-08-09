import os
import sqlite3
import pandas as pd
from app.services.db_queries import clean_input_text

def import_excel_data(excel_path="app/test stock FATEH  04-08-2026.xlsx", db_path="sales_agent.db"):
    if not os.path.exists(excel_path):
        print(f"Error: Excel file not found at {excel_path}")
        return

    df = pd.read_excel(excel_path)
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    imported_count = 0
    updated_count = 0
    
    for idx, row in df.iterrows():
        raw_ref = str(row.get("reference", "")).strip() if pd.notna(row.get("reference")) else ""
        raw_desc = str(row.get("designation", "")).strip() if pd.notna(row.get("designation")) else ""
        brand = str(row.get("marque", "")).strip() if pd.notna(row.get("marque")) else ""
        
        if not raw_ref and not raw_desc:
            continue
            
        oem_number = raw_ref if raw_ref and raw_ref != "nan" else f"GEN-{idx+1:04d}"
        clean_oem = clean_input_text(oem_number) if oem_number else clean_input_text(raw_desc)
        
        name_ar = raw_desc if raw_desc and raw_desc != "nan" else oem_number
        name_fr = f"{raw_desc} ({brand})".strip() if brand and brand != "nan" else name_ar
        
        try:
            qty = int(row.get("quantite", 0)) if pd.notna(row.get("quantite")) else 0
        except Exception:
            qty = 0
            
        try:
            price = float(row.get("prix detail", 0)) if pd.notna(row.get("prix detail")) else 0.0
        except Exception:
            price = 0.0

        # Insert or update product
        cursor.execute("SELECT id FROM products WHERE clean_oem = ?", (clean_oem,))
        existing = cursor.fetchone()
        
        if existing:
            product_id = existing[0]
            cursor.execute("""
                UPDATE products SET oem_number = ?, name_ar = ?, name_fr = ?, description = ? WHERE id = ?
            """, (oem_number, name_ar, name_fr, raw_desc, product_id))
            cursor.execute("""
                INSERT INTO inventory (product_id, price, stock_quantity) VALUES (?, ?, ?)
                ON CONFLICT(product_id) DO UPDATE SET price = excluded.price, stock_quantity = excluded.stock_quantity
            """, (product_id, price, qty))
            updated_count += 1
        else:
            cursor.execute("""
                INSERT INTO products (oem_number, clean_oem, name_ar, name_fr, description)
                VALUES (?, ?, ?, ?, ?)
            """, (oem_number, clean_oem, name_ar, name_fr, raw_desc))
            product_id = cursor.lastrowid
            cursor.execute("""
                INSERT INTO inventory (product_id, price, stock_quantity) VALUES (?, ?, ?)
            """, (product_id, price, qty))
            imported_count += 1

    conn.commit()
    conn.close()
    print(f"Import complete! Imported {imported_count} new products, updated {updated_count} existing products.")

if __name__ == "__main__":
    import_excel_data()
