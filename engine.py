"""محرك القواعد: تنظيف البيانات، وترتيب الأولويات، وبناء جدول المذاكرة."""
from datetime import date, datetime, timedelta

FIELDS = ["task_id", "course", "task_type", "deadline", "difficulty", "remaining_hours", "status"]
STATUSES = ["لم تبدأ", "قيد التنفيذ", "مكتملة"]
STATUS_MAP = {
    "not started": "لم تبدأ", "todo": "لم تبدأ", "لم تبدأ": "لم تبدأ",
    "in progress": "قيد التنفيذ", "doing": "قيد التنفيذ", "قيد التنفيذ": "قيد التنفيذ",
    "done": "مكتملة", "completed": "مكتملة", "complete": "مكتملة", "مكتملة": "مكتملة", "منجزة": "مكتملة",
}
SESSION_MAX = 1.0  # أقصى طول للجلسة بالساعات
DATE_FORMATS = ["%Y-%m-%d", "%d/%m/%Y", "%Y/%m/%d", "%d-%m-%Y"]


def parse_date(value):
    if isinstance(value, date):
        return value
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def parse_number(value):
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    try:
        num = float(str(value).strip().replace("٫", "."))
    except ValueError:
        return None
    return num


def clean_tasks(raw_tasks):
    """يعيد (المهام الصالحة، المهام التي تحتاج استكمالًا، سجل التنظيف). لا يخمّن أي قيمة مفقودة."""
    valid, incomplete, log, seen = [], [], [], set()
    for i, raw in enumerate(raw_tasks, start=1):
        t = {k: raw.get(k) for k in FIELDS}
        tid = str(t["task_id"]).strip() if t["task_id"] not in (None, "") else f"N{i:02d}"
        t["task_id"] = tid
        problems = []

        if tid in seen:
            log.append((tid, "سجل مكرر بالمعرّف نفسه", "حُذف التكرار"))
            continue
        seen.add(tid)

        for key in ("course", "task_type"):
            value = t[key]
            if value is None or not str(value).strip():
                problems.append("اسم المقرر مفقود" if key == "course" else "نوع المهمة مفقود")
            elif str(value) != str(value).strip():
                t[key] = str(value).strip()
                log.append((tid, f"مسافات زائدة في {key}", "أُزيلت المسافات"))

        d = parse_date(t["deadline"])
        if t["deadline"] in (None, "") or (isinstance(t["deadline"], str) and not t["deadline"].strip()):
            problems.append("الموعد النهائي مفقود")
        elif d is None:
            problems.append(f"تاريخ غير صالح: {t['deadline']}")
        else:
            iso = d.isoformat()
            if str(t["deadline"]) != iso:
                log.append((tid, f"صيغة تاريخ مختلفة: {t['deadline']}", f"وُحّدت إلى {iso}"))
            t["deadline"] = iso

        diff = parse_number(t["difficulty"])
        if diff is None:
            problems.append("الصعوبة مفقودة أو غير رقمية")
        elif diff != int(diff) or not 1 <= diff <= 5:
            problems.append(f"الصعوبة خارج النطاق 1-5: {t['difficulty']}")
        else:
            t["difficulty"] = int(diff)

        status_raw = "" if t["status"] is None else str(t["status"]).strip()
        status = STATUS_MAP.get(status_raw.lower())
        if status is None:
            problems.append(f"حالة غير معروفة: {status_raw or 'فارغة'}")
        else:
            if status_raw != status:
                log.append((tid, f"حالة غير موحدة: {status_raw}", f"وُحّدت إلى «{status}»"))
            t["status"] = status

        hours = parse_number(t["remaining_hours"])
        if hours is None:
            problems.append("الساعات المتبقية مفقودة أو غير رقمية")
        else:
            if isinstance(t["remaining_hours"], str):
                log.append((tid, "المدة مكتوبة نصًا", "حُوّلت إلى رقم"))
            if hours < 0:
                problems.append(f"مدة سالبة: {hours}")
            elif hours == 0 and t.get("status") != "مكتملة":
                problems.append("المدة صفر لمهمة غير مكتملة")
            elif hours > 200:
                problems.append(f"مدة غير منطقية: {hours} ساعة")
            t["remaining_hours"] = int(hours) if float(hours).is_integer() else hours

        if problems:
            t["problems"] = problems
            incomplete.append(t)
            log.append((tid, "؛ ".join(problems), "عُزل السجل وطُلب استكماله دون تخمين"))
        else:
            valid.append(t)
    return valid, incomplete, log


def priority_key(t):
    """أقرب موعد ← الأعلى صعوبة ← الأقصر مدة ← المعرّف."""
    return (t["deadline"], -t["difficulty"], t["remaining_hours"], t["task_id"])


def build_schedule(tasks, start, availability, default_hours=0):
    """tasks: مهام صالحة. availability: قاموس تاريخ ← ساعات متاحة."""
    start = parse_date(start)
    avail = {parse_date(k): float(v) for k, v in (availability or {}).items() if parse_date(k)}
    completed = [t for t in tasks if t["status"] == "مكتملة"]
    pending = [t for t in tasks if t["status"] != "مكتملة"]
    overdue = [t for t in pending if parse_date(t["deadline"]) < start]
    active = sorted([t for t in pending if parse_date(t["deadline"]) >= start], key=priority_key)

    left = {t["task_id"]: float(t["remaining_hours"]) for t in active}
    sessions = []
    if active:
        last = max(parse_date(t["deadline"]) for t in active)
        day = start
        while day <= last:
            cap = avail.get(day, float(default_hours))
            for t in active:
                if cap <= 0:
                    break
                if parse_date(t["deadline"]) < day or left[t["task_id"]] <= 0:
                    continue
                while cap > 0 and left[t["task_id"]] > 0:
                    h = min(SESSION_MAX, cap, left[t["task_id"]])
                    sessions.append({"date": day.isoformat(), "task_id": t["task_id"], "course": t["course"],
                                     "task_type": t["task_type"], "hours": round(h, 2), "deadline": t["deadline"]})
                    cap -= h
                    left[t["task_id"]] -= h
            day += timedelta(days=1)

    deficits = [{"task_id": t["task_id"], "course": t["course"], "task_type": t["task_type"],
                 "deadline": t["deadline"], "missing_hours": round(left[t["task_id"]], 2)}
                for t in active if left[t["task_id"]] > 1e-9]
    return {"order": active, "sessions": sessions, "deficits": deficits,
            "overdue": overdue, "completed": completed}


def reasons(order):
    """تفسير ثابت لسبب ترتيب كل مهمة، يعمل دون نموذج لغوي."""
    out = []
    for i, t in enumerate(order):
        why = f"موعدها {t['deadline']}"
        if i > 0:
            prev = order[i - 1]
            if prev["deadline"] == t["deadline"]:
                why += "، وتساوت في الموعد مع ما قبلها"
                if prev["difficulty"] > t["difficulty"]:
                    why += " لكنها أقل صعوبة"
                elif prev["difficulty"] == t["difficulty"]:
                    why += " وفي الصعوبة، فقُدّمت الأقصر مدة"
        out.append(f"{i + 1}. {t['course']} – {t['task_type']}: {why} (صعوبة {t['difficulty']}، {t['remaining_hours']} ساعة).")
    return out


def compare(old, new):
    """يوضح سبب تغير الجدول بعد التحديث."""
    def per_task(s):
        r = {}
        for x in s["sessions"]:
            r[x["task_id"]] = r.get(x["task_id"], 0) + x["hours"]
        return r
    a, b = per_task(old), per_task(new)
    changes = []
    for tid in sorted(set(a) | set(b)):
        if round(a.get(tid, 0), 2) != round(b.get(tid, 0), 2):
            changes.append(f"{tid}: الساعات المجدولة تغيرت من {a.get(tid, 0):g} إلى {b.get(tid, 0):g}")
    old_def = {d["task_id"] for d in old["deficits"]}
    new_def = {d["task_id"] for d in new["deficits"]}
    for tid in sorted(old_def - new_def):
        changes.append(f"{tid}: زال العجز الزمني بعد التحديث")
    for tid in sorted(new_def - old_def):
        changes.append(f"{tid}: ظهر عجز زمني بعد التحديث")
    return changes
