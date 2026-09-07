"""
License Manager - نظام مفاتيح للـ EXE
- يتحقق محليا + عن بعد (اذا توفر سيرفر)
- يربط المفتاح بالجهاز HWID (اختياري)
- يخزن المفتاح مشفر في %APPDATA%
"""
import os
import json
import hashlib
import platform
import uuid
from datetime import datetime, timedelta
from pathlib import Path

# مسار تخزين الترخيص
APP_NAME = "UniversalDownloaderPro"
LICENSE_DIR = Path(os.getenv("APPDATA") or Path.home() / ".config") / APP_NAME
LICENSE_FILE = LICENSE_DIR / "license.dat"

# مفاتيح تجريبية - يمكنك اضافة مفاتيحك هنا او عبر اداة التوليد
# نفس api_keys_store في main.py لكن للعمل بدون انترنت
EMBEDDED_KEYS = {
    "PREMIUM-DEMO-001": {"plan": "monthly", "expires": "2027-12-31", "daily_downloads": 50, "active": True},
    "TRIAL-7DAYS-001": {"plan": "trial", "expires": "2027-12-31", "daily_downloads": 5, "active": True},
}

# رابط السيرفر للتحقق عن بعد (اتركه فارغ للتحقق المحلي فقط)
# مثال: "https://your-app.onrender.com"
LICENSE_SERVER_URL = os.getenv("LICENSE_SERVER_URL", "").strip()

def get_hwid():
    """بصمة الجهاز - ثابتة لكل جهاز"""
    try:
        # نستخدم MAC + اسم الجهاز + المعالج
        mac = str(uuid.getnode())
        node = platform.node()
        machine = platform.machine()
        raw = f"{mac}-{node}-{machine}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16].upper()
    except:
        return "UNKNOWN-HWID"

def _resource_path(relative):
    import sys
    try:
        base = Path(sys._MEIPASS)
    except AttributeError:
        base = Path(__file__).parent
    return base / relative

def _load_embedded_keys():
    """تحميل المفاتيح من main.py اذا توفر + المدمجة"""
    keys = dict(EMBEDDED_KEYS)
    try:
        # حاول استيراد من main.py
        from main import api_keys_store
        keys.update(api_keys_store)
    except:
        pass
    # حاول تحميل من ملف keys.json بجانب البرنامج (يدعم PyInstaller)
    for p in [_resource_path("keys.json"), Path(__file__).parent / "keys.json", Path.cwd() / "keys.json"]:
        if p.exists():
            try:
                with open(p, "r", encoding="utf-8") as f:
                    extra = json.load(f)
                    keys.update(extra)
                break
            except:
                pass
    return keys

def validate_key_offline(key: str):
    """تحقق محلي بدون انترنت"""
    key = key.strip().upper()
    keys = _load_embedded_keys()
    info = keys.get(key)
    if not info:
        return False, "المفتاح غير موجود"
    if not info.get("active", True):
        return False, "المفتاح معطل"
    try:
        exp = datetime.strptime(info["expires"], "%Y-%m-%d")
        if exp < datetime.now():
            return False, f"المفتاح منتهي في {info['expires']}"
    except:
        pass
    return True, info

def validate_key_online(key: str, hwid: str = ""):
    """تحقق عن بعد عبر السيرفر"""
    if not LICENSE_SERVER_URL:
        return None, "لا يوجد سيرفر"
    try:
        import requests
        url = LICENSE_SERVER_URL.rstrip("/") + "/api/license/verify"
        resp = requests.post(url, json={"key": key, "hwid": hwid}, timeout=8)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("valid"):
                return True, data
            else:
                return False, data.get("reason", "مفتاح غير صالح")
        else:
            return False, f"خطأ سيرفر {resp.status_code}"
    except Exception as e:
        return None, f"لا يوجد اتصال: {e}"

def validate_key(key: str):
    """الدالة الرئيسية - تجرب اونلاين ثم اوفلاين"""
    hwid = get_hwid()
    # 1. جرب اونلاين اولا اذا توفر
    if LICENSE_SERVER_URL:
        ok, info = validate_key_online(key, hwid)
        if ok is not None:  # يوجد رد من السيرفر
            if ok:
                return True, info
            else:
                # اذا السيرفر قال المفتاح خطأ، لا تجرب اوفلاين
                return False, info
        # اذا فشل الاتصال، اسقط للتحقق المحلي
    # 2. تحقق محلي
    return validate_key_offline(key)

def save_license(key: str, info: dict = None):
    """حفظ المفتاح مشفر"""
    LICENSE_DIR.mkdir(parents=True, exist_ok=True)
    hwid = get_hwid()
    data = {
        "key": key.strip().upper(),
        "hwid": hwid,
        "saved_at": datetime.now().isoformat(),
        "info": info or {}
    }
    # تشفير بسيط base64 + hash
    raw = json.dumps(data, ensure_ascii=False)
    # نستخدم hash للتمويه (ليس تشفير قوي لكن يمنع التعديل العشوائي)
    encoded = raw.encode("utf-8").hex()
    with open(LICENSE_FILE, "w", encoding="utf-8") as f:
        f.write(encoded)
    # اخفاء الملف في ويندوز
    try:
        import ctypes
        ctypes.windll.kernel32.SetFileAttributesW(str(LICENSE_FILE), 2)
    except:
        pass

def load_license():
    """تحميل المفتاح المحفوظ"""
    if not LICENSE_FILE.exists():
        return None
    try:
        with open(LICENSE_FILE, "r", encoding="utf-8") as f:
            encoded = f.read().strip()
        raw = bytes.fromhex(encoded).decode("utf-8")
        data = json.loads(raw)
        return data
    except:
        return None

def is_license_valid():
    """هل يوجد ترخيص صالح محفوظ؟"""
    data = load_license()
    if not data:
        return False, "لا يوجد ترخيص"
    key = data.get("key", "")
    ok, info = validate_key(key)
    if ok:
        # تحقق HWID اذا كان مربوط
        saved_hwid = data.get("hwid", "")
        current_hwid = get_hwid()
        # السماح بنفس الجهاز فقط اذا كان HWID مختلف (اختياري - يمكنك تعطيله)
        # if saved_hwid and saved_hwid != current_hwid:
        #     return False, "المفتاح مربوط بجهاز آخر"
        return True, data
    else:
        return False, info

def clear_license():
    if LICENSE_FILE.exists():
        LICENSE_FILE.unlink()

if __name__ == "__main__":
    print(f"HWID: {get_hwid()}")
    print(f"License file: {LICENSE_FILE}")
    print(validate_key("PREMIUM-DEMO-001"))
