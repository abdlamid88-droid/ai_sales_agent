import os
import json
import logging
import httpx
from fastapi import FastAPI, Query, HTTPException, Request, BackgroundTasks
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv

logging.basicConfig(level=logging.INFO)

from app.database import init_db, save_or_update_lead
from app.services.db_queries import search_part_and_alternatives
from app.services.hybrid_search import perform_hybrid_part_search
from app.services.media import process_voice_note, process_part_image
from app.services.llm import generate_parts_sales_response

from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    # تهيئة قاعدة البيانات وإنشاء جدول قطع الغيار والمخزون وحقن البيانات
    await init_db()
    yield

app = FastAPI(title="Auto Parts AI Sales Agent", lifespan=lifespan)
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
media_dir = os.path.join(project_root, "media")
static_dir = os.path.join(project_root, "app", "static")

if not os.path.exists(media_dir):
    os.makedirs(media_dir, exist_ok=True)
app.mount("/media", StaticFiles(directory=media_dir), name="media")

if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

VERIFY_TOKEN = os.getenv("VERIFY_TOKEN") or os.getenv("WEBHOOK_VERIFY_TOKEN", "smart_agent_2026")
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN") or os.getenv("WHATSAPP_ACCESS_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")

MEDIA_CACHE = {}

async def upload_media_to_whatsapp(image_url_or_path: str, http_client: httpx.AsyncClient) -> str | None:
    """رفع الصورة مباشرة إلى سيرفرات Meta WhatsApp Media API وإرجاع media_id لضمان عرض الصورة 100%"""
    if not image_url_or_path:
        return None
        
    if image_url_or_path in MEDIA_CACHE:
        logging.info(f"[META_MEDIA_CACHE] Using cached media_id '{MEDIA_CACHE[image_url_or_path]}' for URL '{image_url_or_path}'")
        return MEDIA_CACHE[image_url_or_path]

    media_url = f"https://graph.facebook.com/v18.0/{PHONE_NUMBER_ID}/media"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}"
    }

    image_bytes = None
    filename = "part_image.jpg"
    mime_type = "image/jpeg"

    # 1. فحص ما إذا كانت الصورة ملفاً محلياً في مجلد media/ أو static/ باستخدام المسارات المطلقة
    if "/media/" in image_url_or_path:
        rel_sub = image_url_or_path.split("/media/")[-1]
        abs_local_path = os.path.abspath(os.path.join(project_root, "media", rel_sub))
        if os.path.exists(abs_local_path):
            with open(abs_local_path, "rb") as f:
                image_bytes = f.read()
            filename = os.path.basename(abs_local_path)
            mime_type = "image/png" if filename.lower().endswith(".png") else "image/jpeg"
            logging.info(f"[META_MEDIA_LOCAL] Found local media file at '{abs_local_path}' ({len(image_bytes)} bytes)")

    if not image_bytes and "/static/images/" in image_url_or_path:
        rel_sub = image_url_or_path.split("/static/images/")[-1]
        abs_local_path = os.path.abspath(os.path.join(project_root, "app", "static", "images", rel_sub))
        if not os.path.exists(abs_local_path):
            abs_local_path = os.path.abspath(os.path.join(project_root, "static", "images", rel_sub))

        if os.path.exists(abs_local_path):
            with open(abs_local_path, "rb") as f:
                image_bytes = f.read()
            filename = os.path.basename(abs_local_path)
            mime_type = "image/png" if filename.lower().endswith(".png") else "image/jpeg"
            logging.info(f"[META_MEDIA_LOCAL] Found local static image file at '{abs_local_path}' ({len(image_bytes)} bytes)")

    # 2. إذا لم تكن محلياً، نزلها عبر HTTP
    if not image_bytes and (image_url_or_path.startswith("http://") or image_url_or_path.startswith("https://")):
        try:
            logging.info(f"[META_MEDIA_DOWNLOAD] Downloading remote image from '{image_url_or_path}'")
            resp = await http_client.get(image_url_or_path, timeout=6.0)
            if resp.is_success:
                image_bytes = resp.content
                filename = os.path.basename(image_url_or_path.split("?")[0]) or "downloaded_part.jpg"
                mime_type = "image/png" if filename.lower().endswith(".png") else "image/jpeg"
                logging.info(f"[META_MEDIA_DOWNLOAD] Successfully downloaded remote image ({len(image_bytes)} bytes)")
            else:
                logging.warning(f"[META_MEDIA_DOWNLOAD_FAILED] HTTP {resp.status_code} for URL '{image_url_or_path}'")
        except Exception as e:
            logging.error(f"[META_MEDIA_DOWNLOAD_ERROR] Error downloading image '{image_url_or_path}': {e}")

    if not image_bytes:
        logging.error(f"[META_MEDIA_ERROR] No image bytes available for upload to Meta API from '{image_url_or_path}'")
        return None

    try:
        files = {
            "file": (filename, image_bytes, mime_type)
        }
        data = {
            "messaging_product": "whatsapp"
        }
        logging.info(f"[META_MEDIA_UPLOAD] Sending POST request to Meta Media endpoint '{media_url}' with filename='{filename}' ({len(image_bytes)} bytes)...")
        upload_resp = await http_client.post(media_url, headers=headers, data=data, files=files)
        if upload_resp.is_success:
            media_id = upload_resp.json().get("id")
            if media_id:
                MEDIA_CACHE[image_url_or_path] = media_id
                logging.info(f"[META_MEDIA_UPLOAD_SUCCESS] Meta API returned media_id='{media_id}'")
                return media_id
        else:
            logging.error(f"[META_MEDIA_UPLOAD_FAILED] Meta Media Upload HTTP {upload_resp.status_code}: {upload_resp.text}")
    except Exception as e:
        logging.error(f"[META_MEDIA_UPLOAD_EXCEPTION] Meta media upload exception: {e}")

    return None

async def send_whatsapp_message(to_number: str, text: str, image_url: str = None):
    """إرسال رسالة نصية مضمونة التسليم أولاً، ثم إرسال الصورة كبطاقة/مخطط عبر Meta Media ID لضمان الظهور الفوري 100%"""
    url = f"https://graph.facebook.com/v18.0/{PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json"
    }

    async with httpx.AsyncClient(timeout=10.0) as http_client:
        # 1. إرسال الرد المالي والمخزني النصي أولاً (تسليم مضمون 100%)
        text_data = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to_number,
            "type": "text",
            "text": {"body": text}
        }
        try:
            resp = await http_client.post(url, headers=headers, json=text_data)
            if resp.is_success:
                logging.info(f"[WHATSAPP_TEXT_SUCCESS] Text message delivered to {to_number}, status: {resp.status_code}")
                print(f"[WHATSAPP_TEXT_SUCCESS] Text message delivered to {to_number}, status: {resp.status_code}")
            else:
                logging.error(f"[WHATSAPP_TEXT_FAILED] Status: {resp.status_code}, Body: {resp.text}")
                print(f"[WHATSAPP_TEXT_FAILED] Status: {resp.status_code}, Body: {resp.text}")
        except Exception as e:
            logging.error(f"[WHATSAPP_TEXT_EXCEPTION] Exception sending text to {to_number}: {e}")

        # 2. إرسال الصورة كرسالة مرفقة عبر Meta Media ID إن وجدت
        if image_url:
            clean_url = str(image_url).lower().strip()
            if not clean_url.startswith("https://") and not clean_url.startswith("http://") or "example.com" in clean_url or "placeholder" in clean_url or "dummy" in clean_url:
                image_url = None
                
        if image_url:
            logging.info(f"[WHATSAPP_IMAGE_DISPATCH] Processing image dispatch for URL '{image_url}' to {to_number}")
            media_id = await upload_media_to_whatsapp(image_url, http_client)
            if media_id:
                img_data = {
                    "messaging_product": "whatsapp",
                    "recipient_type": "individual",
                    "to": to_number,
                    "type": "image",
                    "image": {"id": media_id}
                }
            else:
                img_data = {
                    "messaging_product": "whatsapp",
                    "recipient_type": "individual",
                    "to": to_number,
                    "type": "image",
                    "image": {"link": image_url}
                }
            try:
                img_resp = await http_client.post(url, headers=headers, json=img_data)
                if img_resp.is_success:
                    logging.info(f"[WHATSAPP_IMAGE_SUCCESS] Image attachment (media_id={media_id}) sent successfully to {to_number}, status: {img_resp.status_code}")
                    print(f"[WHATSAPP_IMAGE_SUCCESS] Image attachment (media_id={media_id}) sent successfully to {to_number}, status: {img_resp.status_code}")
                else:
                    logging.error(f"[WHATSAPP_IMAGE_FAILED] Status: {img_resp.status_code}, Body: {img_resp.text}")
                    print(f"[WHATSAPP_IMAGE_FAILED] Status: {img_resp.status_code}, Body: {img_resp.text}")
            except Exception as e:
                logging.error(f"[WHATSAPP_IMAGE_EXCEPTION] Exception sending image to {to_number}: {e}")

# للتوافق مع التسمية القديمة
send_whatsapp_reply = send_whatsapp_message

async def handle_customer_request(from_number: str, client_name: str, msg_type: str, message_data: dict):
    """معالجة استفسار العميل بناءً على نوع الرسالة (نص، صوت، صورة)، والبحث في المخزون، وتوليد رد الذكاء الاصطناعي، وإرساله"""
    user_query = ""
    
    try:
        if msg_type in ["text", "button", "interactive"]:
            user_query = message_data.get("text", {}).get("body", "") or message_data.get("button", {}).get("text", "") or message_data.get("interactive", {}).get("button_reply", {}).get("title", "")
            
        elif msg_type in ["audio", "voice"]:
            media_id = message_data.get("audio", {}).get("id") or message_data.get("voice", {}).get("id")
            if media_id:
                # 1. تنزيل الملف الصوتي إلى المجلد المحلي media/audio/
                from app.services.media import download_whatsapp_audio
                from app.services.stt import transcribe_audio_openai
                local_audio_path = await download_whatsapp_audio(media_id)
                if local_audio_path:
                    user_query = transcribe_audio_openai(local_audio_path)
                # 2. الاحتياط المباشر في حال عدم تهيئة OpenAI أو إرجاع نص فارغ
                if not user_query:
                    user_query = await process_voice_note(media_id)
                
        elif msg_type == "image":
            media_id = message_data.get("image", {}).get("id")
            caption = message_data.get("image", {}).get("caption", "")
            if media_id:
                extracted_text = await process_part_image(media_id)
                user_query = f"{extracted_text} {caption}".strip()
                
        if not user_query:
            user_query = "استفسار عن قطعة غيار"
            
        print(f"Processing request from {from_number} ({client_name}) [{msg_type}]: '{user_query}'")

        # 1. البحث الهجين (Level 1: Fast-Path + Level 2: Vector + Level 3: Threshold Scoring & Shadow Mode)
        db_results = await perform_hybrid_part_search(user_query, customer_phone=from_number)

        # 2. تسجيل/تحديث العميل والمنتج المهتم به
        matched_product_name = db_results.get("product", {}).get("name_ar") if db_results.get("found") else user_query
        await save_or_update_lead(from_number, client_name, matched_product_name)

        # 3. توليد رد المبيعات عبر LLM
        reply_text, image_url = await generate_parts_sales_response(user_query, db_results)

        if not reply_text or not reply_text.strip():
            reply_text = (
                f"مرحباً بك! 👋\n"
                f"عذراً، قطعة الغيار المطلوبة '{user_query}' غير متوفرة حالياً في المخزون السريع.\n\n"
                f"يرجى تزويدنا برقم الهيكل (VIN) أو تفاصيل السيارة وسنقوم بالبحث والمتابعة معك فوراً! 🚗"
            )

        print(f"Generated response text for {from_number} (image_url={image_url}):\n{reply_text}")

        # 4. إرسال الرد للعميل عبر واتساب
        await send_whatsapp_message(from_number, reply_text, image_url=image_url)

    except Exception as e:
        print(f"Error handling customer request for {from_number}: {e}")

@app.get("/webhook")
async def verify_webhook(
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_challenge: str = Query(None, alias="hub.challenge"),
    hub_verify_token: str = Query(None, alias="hub.verify_token")
):
    if hub_mode == "subscribe" and hub_verify_token == VERIFY_TOKEN:
        return PlainTextResponse(content=hub_challenge, status_code=200)
    raise HTTPException(status_code=403, detail="Verification token mismatch")

@app.post("/webhook")
async def receive_whatsapp_message(request: Request, background_tasks: BackgroundTasks):
    try:
        body = await request.json()
        print(f"Incoming WhatsApp Payload: {json.dumps(body, ensure_ascii=False)}")
        
        entry = body.get("entry", [])[0]
        changes = entry.get("changes", [])[0]
        value = changes.get("value", {})
        messages = value.get("messages", [])
        contacts = value.get("contacts", [])
        
        if messages:
            for message in messages:
                msg_type = message.get("type")
                from_number = message.get("from")
                
                client_name = contacts[0].get("profile", {}).get("name", "عميل غير معروف") if contacts else "عميل غير معروف"
                
                if msg_type in ["text", "audio", "voice", "image", "document", "location", "interactive", "button"]:
                    background_tasks.add_task(
                        handle_customer_request,
                        from_number,
                        client_name,
                        msg_type,
                        message
                    )
                
        return {"status": "success"}
        
    except Exception as e:
        print(f"Error in webhook endpoint: {e}")
        return {"status": "error"}
