"""المساعد الدراسي الذكي — واجهة Streamlit."""
import json
import os
import re
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import streamlit as st

import engine
import llm

BASE = Path(__file__).parent
st.set_page_config(page_title="المساعد الدراسي الذكي", page_icon="📚", layout="wide")
st.markdown("""
<style>
html, body, [class*="css"], .stMarkdown, .stText, p, h1, h2, h3, h4, label, li { direction: rtl; text-align: right; }
section[data-testid="stSidebar"] { direction: rtl; }
.stTabs [data-baseweb="tab-list"] { direction: rtl; }
.stAlert { direction: rtl; text-align: right; }
[data-testid="stDataFrame"], [data-testid="stTable"] { direction: rtl; }
</style>""", unsafe_allow_html=True)

COLS = {"task_id": "المعرّف", "course": "المقرر", "task_type": "نوع المهمة", "deadline": "الموعد النهائي",
        "difficulty": "الصعوبة", "remaining_hours": "الساعات المتبقية", "status": "الحالة"}

ss = st.session_state
ss.setdefault("raw", [])
ss.setdefault("start", date.today())
ss.setdefault("avail", {})
ss.setdefault("default_hours", 3.0)
ss.setdefault("result", None)
ss.setdefault("prev", None)
ss.setdefault("extracted", None)
ss.setdefault("explanation", None)


def ltr(text):
    """يمنع انقلاب التواريخ داخل النص العربي."""
    return re.sub(r"(\d{4}-\d{2}-\d{2}|\d{2}/\d{2}/\d{4})", "\u2066\\1\u2069", str(text))


def get_key():
    key = os.environ.get("GEMINI_API_KEY", "")
    env = BASE / ".env"
    if not key and env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("GEMINI_API_KEY="):
                key = line.split("=", 1)[1].strip().strip('"')
    return key


def table(rows, cols=COLS):
    if not rows:
        return
    df = pd.DataFrame(rows)[[c for c in cols if c in pd.DataFrame(rows).columns]].rename(columns=cols)
    st.dataframe(df.astype(str).map(ltr), hide_index=True, use_container_width=True)


def next_id():
    used = {str(r.get("task_id")) for r in ss.raw}
    n = 1
    while f"T{n:02d}" in used:
        n += 1
    return f"T{n:02d}"


def compute():
    valid, incomplete, log = engine.clean_tasks(ss.raw)
    days = {(ss.start + timedelta(days=i)).isoformat(): ss.avail.get((ss.start + timedelta(days=i)).isoformat(), ss.default_hours)
            for i in range(120)}
    return valid, incomplete, log, engine.build_schedule(valid, ss.start, days)


# ---------------- الشريط الجانبي ----------------
with st.sidebar:
    st.header("⚙️ الإعدادات")
    key = st.text_input("مفتاح Gemini", value=get_key(), type="password",
                        help="مطلوب فقط لفهم الكتابة الحرة وشرح الجدول. ترتيب المهام يعمل بدونه.")
    st.caption("🟢 النموذج اللغوي متاح" if key else "⚪ النموذج اللغوي غير مفعّل — القواعد تعمل بدونه")
    ss.start = st.date_input("تاريخ بداية الخطة", value=ss.start)
    ss.default_hours = st.number_input("ساعات المذاكرة الافتراضية يوميًا", 0.0, 16.0, float(ss.default_hours), 0.5)
    st.markdown("**ساعات التفرغ لأيام محددة**")
    days = [(ss.start + timedelta(days=i)).isoformat() for i in range(14)]
    av = pd.DataFrame({"التاريخ": days, "الساعات": [ss.avail.get(d, ss.default_hours) for d in days]})
    edited = st.data_editor(av, hide_index=True, disabled=["التاريخ"], key=f"av_{ss.start}_{ss.default_hours}",
                            column_config={"الساعات": st.column_config.NumberColumn(min_value=0.0, max_value=16.0, step=0.5)})
    ss.avail.update({r["التاريخ"]: float(r["الساعات"] or 0) for _, r in edited.iterrows()})
    st.divider()
    st.caption("🔒 لا يطلب البرنامج اسمًا أو رقمًا جامعيًا، ولا يُرسل إلى النموذج اللغوي إلا وصف المهام ومواعيدها.")

st.title("📚 المساعد الدراسي الذكي")
st.info("أداة مساعدة تقترح جدول مذاكرة، والقرار النهائي وتعديل الجدول بيد الطالب.")
st.link_button("🤖 افتح وكيل Gemini Enterprise (المساعد الدراسي الذكي)", "https://vertexaisearch.cloud.google/home/cid/3dbf9c2f-1fc2-48a6-92a6-1531a573d5b3/agents/r/agent/7956485310315971303/session/-")

t1, t2, t3, t4, t5 = st.tabs(["① إدخال المهام", "② التحقق والتنظيف", "③ جدول المذاكرة", "④ تحديث الإنجاز", "⑤ محادثة مع Gemini"])

# ---------------- ① الإدخال ----------------
with t1:
    c1, c2, c3 = st.columns(3)
    if c1.button("📂 تحميل البيانات التجريبية", use_container_width=True):
        data = json.loads((BASE / "data" / "tasks_raw.json").read_text(encoding="utf-8"))
        ss.raw = data["tasks"]
        ss.start = date.fromisoformat(data["schedule"]["plan_start_date"])
        ss.avail = {k: float(v) for k, v in data["schedule"]["daily_available_hours"].items()}
        ss.result = ss.prev = ss.explanation = None
        st.rerun()
    up = c2.file_uploader("رفع ملف JSON", type="json", label_visibility="collapsed")
    if up is not None and c2.button("إضافة الملف المرفوع", use_container_width=True):
        try:
            data = json.loads(up.read().decode("utf-8"))
            ss.raw += data["tasks"] if isinstance(data, dict) else data
            st.rerun()
        except (json.JSONDecodeError, KeyError, UnicodeDecodeError):
            st.error("الملف ليس بصيغة JSON صحيحة")
    if c3.button("🗑️ مسح كل المهام", use_container_width=True):
        ss.raw, ss.result, ss.prev, ss.explanation = [], None, None, None
        st.rerun()

    with st.expander("✍️ أضف مهامك بكلامك (ذكاء اصطناعي)", expanded=not ss.raw):
        text = st.text_area("اكتب مهامك كما تتحدث", height=110,
                            placeholder="مثال: عندي واجب محاسبة يوم 5 ديسمبر صعب شوي ياخذ ثلاث ساعات، واختبار إحصاء بعد أسبوع...")
        if st.button("🤖 حوّل الكلام إلى مهام"):
            if not text.strip():
                st.warning("اكتب وصف المهام أولًا")
            else:
                try:
                    with st.spinner("يقرأ النموذج اللغوي الوصف..."):
                        ss.extracted = llm.extract_tasks(key, text, ss.start.isoformat())
                except llm.LLMError as e:
                    st.error(f"تعذر استخدام النموذج اللغوي: {e}")
        if ss.extracted is not None:
            if not ss.extracted:
                st.warning("لم يجد النموذج مهامًا في النص")
            else:
                st.write("هذا ما فهمه النموذج. الحقول الفارغة لم تُذكر ولن تُخمَّن، وستُطلب في خطوة التحقق:")
                table(ss.extracted)
                if st.button("✅ إضافة هذه المهام"):
                    for t in ss.extracted:
                        t["task_id"] = next_id()
                        ss.raw.append(t)
                    ss.extracted = None
                    st.rerun()

    with st.expander("➕ إضافة مهمة يدويًا"):
        with st.form("manual", clear_on_submit=True):
            a, b = st.columns(2)
            course = a.text_input("المقرر")
            ttype = b.text_input("نوع المهمة")
            dl = a.date_input("الموعد النهائي", value=None)
            diff = b.slider("الصعوبة", 1, 5, 3)
            hrs = a.number_input("الساعات المتبقية", 0.0, 200.0, 2.0, 0.5)
            stt = b.selectbox("الحالة", engine.STATUSES)
            if st.form_submit_button("إضافة"):
                ss.raw.append({"task_id": next_id(), "course": course, "task_type": ttype,
                               "deadline": dl.isoformat() if dl else "", "difficulty": diff,
                               "remaining_hours": hrs, "status": stt})
                st.rerun()

    st.subheader(f"المهام المُدخلة ({len(ss.raw)})")
    if ss.raw:
        table(ss.raw)
    else:
        st.caption("لا توجد مهام بعد.")

# ---------------- ② التحقق ----------------
with t2:
    if not ss.raw:
        st.caption("أدخل المهام أولًا.")
    else:
        valid, incomplete, log, _ = compute()
        a, b, c = st.columns(3)
        a.metric("السجلات المُدخلة", len(ss.raw))
        b.metric("السجلات الصالحة", len(valid))
        c.metric("تحتاج استكمالًا", len(incomplete))
        if log:
            st.subheader("سجل التنظيف")
            st.dataframe(pd.DataFrame(log, columns=["المعرّف", "المشكلة", "الإجراء"]).map(ltr), hide_index=True, use_container_width=True)
        else:
            st.success("البيانات نظيفة ولا تحتاج تعديلًا.")
        for t in incomplete:
            with st.container(border=True):
                st.warning(f"المهمة {t['task_id']} ({t.get('course') or 'بلا مقرر'}): " + "؛ ".join(t["problems"]))
                with st.form(f"fix_{t['task_id']}"):
                    a, b = st.columns(2)
                    course = a.text_input("المقرر", value=str(t.get("course") or ""))
                    ttype = b.text_input("نوع المهمة", value=str(t.get("task_type") or ""))
                    dl = a.date_input("الموعد النهائي", value=engine.parse_date(t.get("deadline")))
                    d0 = engine.parse_number(t.get("difficulty"))
                    diff = b.slider("الصعوبة", 1, 5, int(d0) if d0 and 1 <= d0 <= 5 and d0 == int(d0) else 3)
                    h0 = engine.parse_number(t.get("remaining_hours"))
                    hrs = a.number_input("الساعات المتبقية", 0.0, 200.0, float(h0) if h0 is not None and 0 <= h0 <= 200 else 1.0, 0.5)
                    st0 = engine.STATUS_MAP.get(str(t.get("status") or "").strip().lower(), "لم تبدأ")
                    stt = b.selectbox("الحالة", engine.STATUSES, index=engine.STATUSES.index(st0))
                    if st.form_submit_button("حفظ الاستكمال"):
                        for r in ss.raw:
                            if str(r.get("task_id")) == t["task_id"]:
                                r.update(course=course, task_type=ttype, deadline=dl.isoformat() if dl else "",
                                         difficulty=diff, remaining_hours=hrs, status=stt)
                                break
                        st.rerun()

# ---------------- ③ الجدول ----------------
with t3:
    if not ss.raw:
        st.caption("أدخل المهام أولًا.")
    else:
        valid, incomplete, _, res = compute()
        if st.button("📅 أنشئ الجدول", type="primary"):
            ss.result, ss.explanation = res, None
        r = ss.result
        if r:
            if incomplete:
                st.warning(f"{len(incomplete)} مهمة لم تدخل الجدول لأنها تحتاج استكمالًا (انظر تبويب التحقق).")
            for t in r["overdue"]:
                st.error(ltr(f"⏰ متأخرة: {t['course']} – {t['task_type']} كان موعدها {t['deadline']}. لم تُجدول، تواصل مع أستاذ المقرر."))
            for d in r["deficits"]:
                st.error(ltr(f"⚠️ عجز زمني: {d['course']} – {d['task_type']} ينقصها {d['missing_hours']:g} ساعة قبل {d['deadline']}."))
            if not r["deficits"] and not r["overdue"] and r["order"]:
                st.success("الوقت المتاح يكفي لكل المهام قبل مواعيدها.")

            st.subheader("ترتيب الأولويات وسببه")
            for line in engine.reasons(r["order"]):
                st.markdown(ltr(line))
            st.subheader("الجدول اليومي")
            if r["sessions"]:
                df = pd.DataFrame(r["sessions"])
                for d, g in df.groupby("date", sort=True):
                    total = g["hours"].sum()
                    with st.expander(ltr(f"📆 {d} — {total:g} ساعة"), expanded=True):
                        st.dataframe(g[["course", "task_type", "hours", "deadline"]].rename(columns={
                            "course": "المقرر", "task_type": "المهمة", "hours": "مدة الجلسة (ساعة)", "deadline": "الموعد"}).astype(str).map(ltr),
                            hide_index=True, use_container_width=True)
            else:
                st.caption("لا توجد جلسات.")

            st.subheader("🤖 شرح الجدول بلغة بسيطة")
            if st.button("اشرح لي الجدول"):
                try:
                    with st.spinner("يكتب النموذج اللغوي الشرح..."):
                        ss.explanation = llm.explain(key, r, ss.start)
                except llm.LLMError as e:
                    st.error(f"تعذر استخدام النموذج اللغوي: {e}")
            if ss.explanation:
                st.markdown(ltr(ss.explanation))

# ---------------- ④ التحديث ----------------
with t4:
    valid = engine.clean_tasks(ss.raw)[0] if ss.raw else []
    if not valid:
        st.caption("لا توجد مهام صالحة بعد.")
    else:
        opts = {f"{t['task_id']} – {t['course']} – {t['task_type']}": t for t in valid}
        choice = st.selectbox("اختر المهمة", list(opts))
        t = opts[choice]
        with st.form("update"):
            a, b = st.columns(2)
            stt = a.selectbox("الحالة الجديدة", engine.STATUSES, index=engine.STATUSES.index(t["status"]))
            hrs = b.number_input("الساعات المتبقية الآن", 0.0, 200.0, float(t["remaining_hours"]), 0.5)
            if st.form_submit_button("تحديث وإعادة الجدولة"):
                old = compute()[3]
                for r in ss.raw:
                    if str(r.get("task_id")) == t["task_id"]:
                        r.update(status=stt, remaining_hours=0 if stt == "مكتملة" else hrs)
                        break
                ss.prev, ss.result, ss.explanation = old, compute()[3], None
                st.rerun()
        if ss.prev and ss.result:
            ch = engine.compare(ss.prev, ss.result)
            st.subheader("ما الذي تغيّر في الجدول؟")
            if ch:
                for c in ch:
                    st.markdown(f"- {c}")
            else:
                st.caption("لم يتغير توزيع الساعات.")
            st.caption("افتح تبويب «جدول المذاكرة» لرؤية الجدول الجديد.")

# ---------------- ⑤ محادثة حرة مع Gemini ----------------
with t5:
    st.subheader("💬 محادثة حرة مع المساعد (Gemini)")
    st.caption("اسأل عن المذاكرة أو تنظيم الوقت أو عن جدولك. المساعد يعمل بنموذج Gemini من Google، والقرار النهائي بيدك.")
    ss.setdefault("chat", [])
    if not key:
        st.warning("المحادثة تحتاج مفتاح Gemini. أضفه في الخانة الجانبية «مفتاح Gemini».")
    for m in ss.chat:
        with st.chat_message("user" if m["role"] == "user" else "assistant"):
            st.markdown(ltr(m["text"]))
    msg = st.chat_input("اكتب سؤالك هنا...", disabled=not key)
    if msg:
        ss.chat.append({"role": "user", "text": msg})
        try:
            with st.spinner("Gemini يكتب الرد..."):
                reply = llm.chat(key, ss.chat)
            ss.chat.append({"role": "assistant", "text": reply})
        except llm.LLMError as e:
            ss.chat.pop()
            st.error(f"تعذر استخدام النموذج اللغوي: {e}")
        st.rerun()
    if ss.chat and st.button("🗑 مسح المحادثة"):
        ss.chat = []
        st.rerun()
