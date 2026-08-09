import os
import asyncio
import unittest
from unittest.mock import AsyncMock, patch

# Use SQLite for testing
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///test_auto_parts.db"

from app.database import init_db
from app.services.db_queries import clean_input_text, search_part_and_alternatives
from app.services.llm import generate_parts_sales_response
from app.main import send_whatsapp_message, app
from fastapi.testclient import TestClient

class TestAutoPartsAgent(unittest.IsolatedAsyncioTestCase):
    
    async def test_clean_input_text(self):
        self.assertEqual(clean_input_text("1K0 129 620-D"), "1k0129620d")
        self.assertEqual(clean_input_text("06L-115.562-A"), "06l115562a")
        self.assertEqual(clean_input_text("5Q0-407-151/A"), "5q0407151a")
        self.assertEqual(clean_input_text(""), "")

    async def test_database_init_and_search(self):
        if os.path.exists("test_auto_parts.db"):
            os.remove("test_auto_parts.db")
            
        await init_db()

        # 1. Search for in-stock part
        res1 = await search_part_and_alternatives("1K0 129 620 D")
        self.assertTrue(res1["found"])
        self.assertEqual(res1["product"]["oem_number"], "1K0129620D")
        self.assertTrue(res1["product"]["in_stock"])
        self.assertEqual(res1["product"]["price"], 3500.0)
        self.assertEqual(len(res1["alternatives"]), 1)
        self.assertEqual(res1["alternatives"][0]["oem_number"], "1K0129620E")

        # 2. Search for out-of-stock part with available alternative
        res2 = await search_part_and_alternatives("06L115562A")
        self.assertTrue(res2["found"])
        self.assertEqual(res2["product"]["oem_number"], "06L115562A")
        self.assertFalse(res2["product"]["in_stock"])
        self.assertEqual(len(res2["alternatives"]), 1)
        self.assertEqual(res2["alternatives"][0]["oem_number"], "HU7008Z")
        self.assertTrue(res2["alternatives"][0]["in_stock"])

        # 3. Search for non-existent part
        res3 = await search_part_and_alternatives("999999999")
        self.assertFalse(res3["found"])
        self.assertIsNone(res3["product"])
        self.assertEqual(len(res3["alternatives"]), 0)

        if os.path.exists("test_auto_parts.db"):
            os.remove("test_auto_parts.db")

    async def test_llm_response_generation(self):
        db_results = {
            "found": True,
            "query": "1K0129620D",
            "product": {
                "oem_number": "1K0129620D",
                "name_ar": "فلتر هواء - جولف 6",
                "name_fr": "Filtre à air Golf 6",
                "price": 3500.0,
                "stock_quantity": 10,
                "in_stock": True,
                "primary_image_url": "https://images.example.com/1k0129620d.jpg"
            },
            "alternatives": []
        }
        
        from unittest.mock import MagicMock
        with patch("app.services.llm.client") as mock_client:
            mock_client.aio.models.generate_content = AsyncMock(
                return_value=MagicMock(text="مرحباً! فلتر الهواء لجولف 6 متوفر بسعر 3500 دج. هل ترغب بالتوصيل؟")
            )
            reply, image_url = await generate_parts_sales_response("1K0129620D", db_results)
            
            self.assertIn("3500", reply)
            self.assertEqual(image_url, "https://images.example.com/1k0129620d.jpg")

    async def test_send_whatsapp_message_payloads(self):
        with patch("httpx.AsyncClient.post") as mock_post:
            mock_post.return_value = AsyncMock(status_code=200)
            
            # Text message test
            await send_whatsapp_message("213555123456", "مرحباً، القطعة متوفرة")
            mock_post.assert_called_once()
            args, kwargs = mock_post.call_args
            self.assertEqual(kwargs["json"]["type"], "text")
            self.assertEqual(kwargs["json"]["text"]["body"], "مرحباً، القطعة متوفرة")
            
            mock_post.reset_mock()
            
            # Image message test with valid URL
            await send_whatsapp_message("213555123456", "صورة فلتر الهواء", image_url="https://cdn.autoparts.com/parts/filter.jpg")
            self.assertEqual(mock_post.call_count, 2)
            first_call_kwargs = mock_post.call_args_list[0][1]
            second_call_kwargs = mock_post.call_args_list[1][1]
            self.assertEqual(first_call_kwargs["json"]["type"], "text")
            self.assertEqual(second_call_kwargs["json"]["type"], "image")
            self.assertEqual(second_call_kwargs["json"]["image"]["link"], "https://cdn.autoparts.com/parts/filter.jpg")

            mock_post.reset_mock()

            # Dummy example.com image URL test (should only send text message)
            await send_whatsapp_message("213555123456", "نص تجريبي", image_url="https://example.com/dummy.jpg")
            mock_post.assert_called_once()
            args, kwargs = mock_post.call_args
            self.assertEqual(kwargs["json"]["type"], "text")
            self.assertEqual(kwargs["json"]["text"]["body"], "نص تجريبي")

    async def test_webhook_endpoints(self):
        await init_db()
        client = TestClient(app)
        
        from app.main import VERIFY_TOKEN
        # Verify GET /webhook subscription
        response = client.get(f"/webhook?hub.mode=subscribe&hub.challenge=123456&hub.verify_token={VERIFY_TOKEN}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.text, "123456")

        # Verify POST /webhook message receipt
        payload = {
            "entry": [{
                "changes": [{
                    "value": {
                        "messages": [{
                            "from": "213555123456",
                            "type": "text",
                            "text": {"body": "1K0129620D"}
                        }],
                        "contacts": [{"profile": {"name": "أحمد"}}]
                    }
                }]
            }]
        }
        response = client.post("/webhook", json=payload)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "success"})

if __name__ == "__main__":
    unittest.main()
