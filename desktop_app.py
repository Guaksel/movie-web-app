"""
Desktop App - EXE بدون متصفح وبدون CMD + نظام مفاتيح
Fix: انتظار السيرفر حتى يجهز + معالجة مسار PyInstaller
"""
import threading
import time
import sys
import os

PORT = 8000
URL = f"http://127.0.0.1:{PORT}"

# لوج للتشخيص في حالة الخطأ (بجانب الEXE)
import pathlib
LOG_FILE = pathlib.Path.home() / "UniversalDownloaderPro_startup.log"
def log(msg):
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%H:%M:%S')}] {msg}\n")
    except:
        pass

log("=== Starting app ===")

def start_server():
    try:
        log("Importing main.app...")
        from main import app
        import uvicorn
        log(f"Starting uvicorn on {PORT}...")
        # مهم: تعطيل الوان السجل لان الـ EXE بدون console يسبب AttributeError: isatty
        uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="error", access_log=False, log_config=None)
    except Exception as e:
        import traceback
        log(f"SERVER ERROR: {e}\n{traceback.format_exc()}")
        # اظهر رسالة خطأ
        try:
            import tkinter.messagebox as mb
            mb.showerror("خطأ السيرفر", f"فشل تشغيل السيرفر:\n{e}\n\nراجع {LOG_FILE}")
        except:
            pass

def show_license_dialog():
    import tkinter as tk
    from tkinter import messagebox
    import license_manager

    ok, data = license_manager.is_license_valid()
    if ok:
        log(f"License valid: {data['key']}")
        return data["key"]

    hwid = license_manager.get_hwid()
    result = {"key": None, "ok": False}
    root = tk.Tk()
    root.title("تفعيل البرنامج - Universal Downloader Pro")
    root.geometry("480x400")
    root.resizable(False, False)
    bg = "#0f0f23"
    card = "#1a1a3e"
    accent = "#6c63ff"
    root.configure(bg=bg)
    tk.Label(root, text="Universal Downloader Pro", font=("Segoe UI", 16, "bold"), bg=bg, fg="white").pack(pady=(25, 5))
    tk.Label(root, text="ادخل مفتاح التفعيل للمتابعة", font=("Segoe UI", 10), bg=bg, fg="#aaa").pack(pady=(0, 15))
    frame = tk.Frame(root, bg=bg)
    frame.pack(pady=10)
    tk.Label(frame, text="مفتاح التفعيل:", font=("Segoe UI", 10), bg=bg, fg="white").pack(anchor="w")
    key_var = tk.StringVar()
    entry = tk.Entry(frame, textvariable=key_var, font=("Consolas", 11), width=32, justify="center", bg="#222", fg="white", insertbackground="white", relief="flat")
    entry.pack(pady=6, ipady=8)
    entry.focus()
    tk.Label(root, text=f"معرف جهازك: {hwid}", font=("Consolas", 8), bg=bg, fg="#666").pack(pady=(5, 0))
    tk.Label(root, text="ارسل هذا المعرف للمسؤول للحصول على مفتاح", font=("Segoe UI", 7), bg=bg, fg="#555").pack()
    status = tk.Label(root, text="", font=("Segoe UI", 9), bg=bg, fg="#ff6b6b", wraplength=400)
    status.pack(pady=8)
    tk.Label(root, text="للتجربة استخدم: PREMIUM-DEMO-001", font=("Segoe UI", 8), bg=bg, fg="#27ae60").pack()
    def do_activate():
        key = key_var.get().strip()
        if not key:
            status.config(text="الرجاء ادخال المفتاح", fg="#ff6b6b")
            return
        status.config(text="جاري التحقق...", fg="#aaa")
        root.update()
        ok, info = license_manager.validate_key(key)
        if ok:
            license_manager.save_license(key, info if isinstance(info, dict) else {})
            result["key"] = key
            result["ok"] = True
            log(f"Activated: {key}")
            root.destroy()
        else:
            log(f"Activation failed {key}: {info}")
            status.config(text=f"فشل: {info}", fg="#ff6b6b")
    def do_exit():
        root.destroy()
        sys.exit(0)
    btn_frame = tk.Frame(root, bg=bg)
    btn_frame.pack(pady=15)
    tk.Button(btn_frame, text="  تفعيل  ", command=do_activate, bg=accent, fg="white", font=("Segoe UI", 10, "bold"), relief="flat", padx=20, pady=6, cursor="hand2").pack(side="left", padx=8)
    tk.Button(btn_frame, text=" خروج ", command=do_exit, bg="#333", fg="white", font=("Segoe UI", 10), relief="flat", padx=20, pady=6, cursor="hand2").pack(side="left", padx=8)
    root.bind("<Return>", lambda e: do_activate())
    root.mainloop()
    return result["key"] if result["ok"] else None

def wait_for_server(timeout=30):
    """انتظار حتى يصبح السيرفر جاهزا عبر طلب HTTP حقيقي"""
    import socket
    start = time.time()
    while time.time() - start < timeout:
        try:
            # 1. تحقق socket
            s = socket.socket()
            s.settimeout(1)
            try:
                s.connect(("127.0.0.1", PORT))
                s.close()
            except:
                s.close()
                time.sleep(0.7)
                continue
            # 2. تحقق HTTP
            import urllib.request
            with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/api/health", timeout=2) as r:
                if r.status == 200:
                    log("Server ready!")
                    return True
        except Exception as e:
            log(f"Waiting server... {e}")
        time.sleep(0.7)
    log("Server timeout!")
    return False

if __name__ == "__main__":
    # اخفاء CMD
    try:
        import ctypes
        ctypes.windll.user32.ShowWindow(ctypes.windll.kernel32.GetConsoleWindow(), 0)
    except:
        pass

    activated_key = show_license_dialog()
    if not activated_key:
        sys.exit(0)

    t = threading.Thread(target=start_server, daemon=True)
    t.start()

    # انتظر بجدية حتى يجهز (30 ثانية كاملة لان yt-dlp يأخذ وقت في الاستيراد)
    if not wait_for_server(timeout=30):
        import tkinter.messagebox as mb
        try:
            mb.showerror("خطأ", f"فشل الاتصال بالسيرفر المحلي.\nالمنفذ {PORT} قد يكون مشغول.\nراجع {LOG_FILE}")
        except:
            pass
        sys.exit(1)

    try:
        import webview
        log(f"Opening webview {URL}")
        webview.create_window(
            title="Universal Downloader Pro - مفعل",
            url=URL,
            width=1220,
            height=820,
            resizable=True,
            min_size=(1000, 650),
            background_color="#0f0f23"
        )
        webview.start()
    except Exception as e:
        log(f"Webview error {e}, fallback to browser")
        import webbrowser, traceback
        log(traceback.format_exc())
        webbrowser.open(URL)
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
