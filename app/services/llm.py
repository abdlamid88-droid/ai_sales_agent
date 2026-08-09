import os
import json
try:
    from google import genai
    from google.genai import types
except ImportError:
    genai = None
    types = None

from dotenv import load_dotenv

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
client = None
if GEMINI_API_KEY and genai:
    try:
        client = genai.Client(api_key=GEMINI_API_KEY)
    except Exception as e:
        print(f"Warning: Could not initialize Gemini Client: {e}")

from app.services.media import fetch_online_part_image_url

async def generate_parts_sales_response(user_query: str, db_results: dict) -> tuple[str, str | None]:
    """
    توليد رد مبيعات ذكي ومحترف باللغة العربية/الفرنسية بناءً على استفسار العميل ونتائج قاعدة البيانات الحقيقية.
    يرجع (نص الرد، رابط الصورة الرئيسية إن وجد).
    """
    try:
        found = db_results.get("found", False)
        product = db_results.get("product")
        alternatives = db_results.get("alternatives", [])

        primary_image_url = None
        if product and product.get("primary_image_url"):
            primary_image_url = product.get("primary_image_url")
        elif alternatives and alternatives[0].get("primary_image_url"):
            primary_image_url = alternatives[0].get("primary_image_url")

        # بحث تلقائي عن صورة توضيحية من الإنترنت أو من الكتالوج الداخلي إذا لم تكن متوفرة في قاعدة البيانات المحلية
        if not primary_image_url:
            if product:
                p_oem = product.get("oem_number", "")
                p_name = product.get("name_ar") or product.get("name_fr", "")
                primary_image_url = await fetch_online_part_image_url(p_oem, p_name)
            elif alternatives:
                alt0 = alternatives[0]
                p_oem = alt0.get("oem_number", "")
                p_name = alt0.get("name_ar") or alt0.get("name_fr", "")
                primary_image_url = await fetch_online_part_image_url(p_oem, p_name)
            elif user_query:
                primary_image_url = await fetch_online_part_image_url("", user_query)

        db_json_context = json.dumps(db_results, ensure_ascii=False, indent=2)
        
        prompt = f"""
أنت "وكيل مبيعات قطع غيار السيارات الذكي"، ممثل محترف ومساعد لمتجر قطع غيار السيارات.
مهمتك تقديم إجابة مبيعات جذابة، واضحة، ومباشرة باللغة العربية (مع استخدام المصطلحات الفرنسية الشائعة لقطع الغيار إن لزم).

استفسار العميل الأصلي: "{user_query}"

نتائج البحث الحقيقية في قاعدة بيانات المخزون:
{db_json_context}

تعليمات صياغة الرد:
1. إذا كانت القطعة متوفرة في المخزون (in_stock = true):
   - رحب بالعميل وأكد له توفر القطعة فوراً.
   - اذكر اسم القطعة باللغتين العربية والفرنسية ورقم OEM وسعرها بالدينار (DZD) وحالة المخزون.
   - وجه للعميل دعوة لاتخاذ إجراء (Call to Action) مثل تأكيد الطلب أو تحديد عنوان التوصيل.

2. إذا كانت القطعة المطلوبة غير متوفرة حالياً في المخزون (in_stock = false):
   - اعتذر بلباقة وأخبر العميل أن هذه القطعة غير متوفرة حالياً.
   - إذا كانت هناك بدائل متوافق عليها (alternatives)، اعرض القطع البديلة المتوفرة فوراً بوضوح مع أسعارها.
   - اقترح على العميل تسديد رقم هاتفهم أو تفاصيل السيارة (رقم الهيكل VIN / موديل السيارة / سنة الصنع) لتنبيههم فور توفر شحنة جديدة (Restock Alert).

3. إذا لم يتم العثور على القطعة المطلوبة مطلقاً (found = false):
   - اعتذر بلباقة وأوضح أن رقم القطعة أو الوصف غير موجود حالياً في البحث السريع.
   - اطلب من العميل تزويدك برقم الهيكل (رقم الشاسي VIN) أو معلومات السيارة الكاملة (الماركة، الموديل، سنة الصنع) أو رقم الهاتف لمراجعة الكتالوج الشامل والتواصل معهم.

قم بصياغة رد المبيعات النهائي الآن:
        """

        if client:
            models_to_try = ['gemini-2.5-flash', 'gemini-2.0-flash']
            for model_name in models_to_try:
                try:
                    response = await client.aio.models.generate_content(
                        model=model_name,
                        contents=prompt
                    )
                    if response and response.text:
                        return response.text.strip(), primary_image_url
                except Exception as e:
                    print(f"Error calling Gemini model {model_name}: {e}")

        # Fallback structured sales template generation if LLM call is unavailable
        if found and product:
            p_name = product.get('name_ar') or product.get('name_fr')
            p_oem = product.get('oem_number')
            p_price = product.get('price')
            if product.get('in_stock'):
                reply = (
                    f"مرحباً بك! 👋\n"
                    f"القطعة المطلوبة متوفرة لدينا حالياً في المخزون:\n"
                    f"🔹 **القطعة**: {p_name} ({product.get('name_fr', '')})\n"
                    f"🔹 **رقم OEM**: {p_oem}\n"
                    f"💰 **السعر**: {p_price} دج (DZD)\n"
                    f"✅ **الحالة**: متوفرة للطلب الفوري.\n\n"
                    f"هل ترغب بتأكيد الطلب الآن وتزويدنا برقم الهاتف وعنوان التوصيل؟ 🚚"
                )
            else:
                reply = (
                    f"مرحباً بك! 👋\n"
                    f"للأسف، القطعة الأصلية ({p_name} - OEM: {p_oem}) غير متوفرة حالياً في المخزون.\n"
                )
                if alternatives:
                    reply += "\n💡 **ولكن تتوفر لدينا القطع البديلة المتوافقة التالية**:\n"
                    for alt in alternatives:
                        status = "متوفرة" if alt.get("in_stock") else "غير متوفرة"
                        reply += f"- **{alt.get('name_ar')}** ({alt.get('oem_number')}): {alt.get('price')} دج [{status}]\n"
                reply += "\nيمكنك تزويدنا برقم الهيكل (VIN) أو رقم الهاتف لتنبيهك فور وصول شحنة جديدة! 🔔"
        else:
            reply = (
                f"مرحباً بك! 👋\n"
                f"عذراً، قطعة الغيار المطلوبة '{user_query}' غير متوفرة حالياً في المخزون السريع.\n\n"
                f"يرجى تزويدنا برقم الهيكل (VIN) أو معلومات السيارة (الماركة، الموديل، سنة الصنع) ورقم الهاتف لمراجعة الكتالوج الشامل ومساعدتك فور وصول شحنة جديدة! 🚗"
            )

        return reply, primary_image_url

    except Exception as e:
        print(f"Error generating LLM parts sales response: {e}")
        fallback_msg = "عذراً، أواجه مشكلة تقنية في مراجعة المخزون حالياً. يرجى تزويدنا برقم القطعة أو رقم الهيكل وسنقوم بالرد عليك فوراً."
        return fallback_msg, None
