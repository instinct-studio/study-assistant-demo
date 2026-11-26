"""الاتصال بنموذج Gemini اللغوي: فهم وصف الطالب لمهامه، وشرح الجدول بلغة بسيطة."""
import json
import requests

MODELS = ["gemini-flash-latest", "gemini-2.5-flash", "gemini-flash-lite-latest"]
URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


class LLMError(Exception):
    pass


def _call(api_key, prompt, as_json=False):
    if not api_key:
        raise LLMError("لم يُدخل مفتاح Gemini")
    body = {"contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.1}}
    if as_json:
        body["generationConfig"]["responseMimeType"] = "application/json"
    last = None
    for model in MODELS:
        try:
            r = requests.post(URL.format(model=model), json=body, timeout=60,
                              headers={"x-goog-api-key": api_key, "Content-Type": "application/json"})
        except requests.RequestException as e:
            raise LLMError(f"تعذر الاتصال بالإنترنت: {e}")
        if r.status_code == 200:
            try:
                return r.json()["candidates"][0]["content"]["parts"][0]["text"]
            except (KeyError, IndexError):
                raise LLMError("ردّ النموذج بصيغة غير متوقعة")
        last = r
        if r.status_code in (400, 401, 403):
            break
    raise LLMError(f"رفض الخادم الطلب ({last.status_code}): {last.text[:200]}")


def extract_tasks(api_key, text, today):
    """يحوّل وصفًا حرًا إلى مهام منظمة. الحقول غير المذكورة تبقى فارغة ولا تُخمَّن."""
    prompt = f"""أنت مساعد يستخرج مهام دراسية من نص عربي كتبه طالب جامعي. تاريخ اليوم {today}.
أعد مصفوفة JSON فقط، كل عنصر فيها له المفاتيح:
course (اسم المقرر)، task_type (نوع المهمة)، deadline (بصيغة YYYY-MM-DD)، difficulty (عدد صحيح من 1 إلى 5)، remaining_hours (رقم)، status (إحدى القيم: لم تبدأ، قيد التنفيذ، مكتملة).
قواعد صارمة:
- إذا لم يذكر الطالب قيمة بوضوح فاجعلها null ولا تخمّنها أبدًا.
- حوّل التواريخ النسبية مثل "بعد ثلاثة أيام" إلى تاريخ اعتمادًا على تاريخ اليوم.
- إذا لم تُذكر الحالة فاجعلها "لم تبدأ".
- لا تضف مهامًا لم يذكرها الطالب، ولا تضف أي بيانات شخصية.
النص:
{text}"""
    raw = _call(api_key, prompt, as_json=True)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        raise LLMError("لم يُرجع النموذج JSON صالحًا")
    if isinstance(data, dict):
        data = data.get("tasks", [data])
    if not isinstance(data, list):
        raise LLMError("لم يُرجع النموذج قائمة مهام")
    return [d for d in data if isinstance(d, dict)]


def explain(api_key, result, start):
    """يشرح الجدول. يرسل فقط المقرر ونوع المهمة والمواعيد والساعات، دون أي بيانات شخصية."""
    summary = {
        "تاريخ_البداية": str(start),
        "ترتيب_الأولويات": [{k: t[k] for k in ("course", "task_type", "deadline", "difficulty", "remaining_hours")}
                            for t in result["order"]],
        "الجلسات": [{k: s[k] for k in ("date", "course", "task_type", "hours")} for s in result["sessions"]],
        "العجز": [{k: d[k] for k in ("course", "task_type", "deadline", "missing_hours")} for d in result["deficits"]],
        "المتأخرة": [{k: t[k] for k in ("course", "task_type", "deadline")} for t in result["overdue"]],
    }
    prompt = f"""أنت مرشد دراسي. اشرح لطالب جامعي جدول مذاكرته التالي بالعربية وبلغة بسيطة في 5 إلى 8 جمل قصيرة.
قاعدة الترتيب المستخدمة: أقرب موعد، ثم الأعلى صعوبة، ثم الأقصر مدة. جلسات لا تتجاوز ساعة، ولا تتجاوز الوقت المتاح يوميًا.
- اشرح لماذا جاءت أول مهمتين في البداية.
- إذا وُجد عجز زمني أو مهام متأخرة فوضّحه بصراحة واقترح على الطالب خيارات (زيادة ساعات يوم معين، أو التواصل مع الأستاذ) دون أن تغيّر الجدول.
- لا تخترع مواعيد أو مهامًا غير موجودة، ولا تعد بتحسن الدرجات.
- ذكّر في جملة أخيرة بأن الجدول اقتراح والقرار للطالب.
البيانات:
{json.dumps(summary, ensure_ascii=False)}"""
    return _call(api_key, prompt)


def chat(api_key, history):
    """محادثة حرة. history: قائمة {role: user|assistant, text}. يُرسل آخر 10 رسائل فقط."""
    lines = "\n".join(("الطالب: " if m["role"] == "user" else "المساعد: ") + m["text"] for m in history[-10:])
    prompt = f"""أنت المساعد الدراسي الذكي، مرشد دراسي لطلاب الجامعة. أجب بالعربية وبلغة بسيطة وقصيرة (حتى 6 جمل).
ساعد في تنظيم الوقت والمذاكرة وفهم الجدول. لا تخترع معلومات، ولا تطلب بيانات شخصية. القرار النهائي للطالب.
المحادثة حتى الآن:
{lines}
المساعد:"""
    return _call(api_key, prompt)
