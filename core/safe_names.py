"""اسم ملف آمن (ASCII) للتخزين. بعض خدمات التخزين (زي Supabase) بترفض حروف عربية في اسم الملف (خطأ 400)."""
import os
import re
import unicodedata


def safe_filename(name):
    base, ext = os.path.splitext(os.path.basename(name or ""))
    base = unicodedata.normalize("NFKD", base).encode("ascii", "ignore").decode("ascii")
    base = re.sub(r"[^A-Za-z0-9._-]+", "_", base).strip("._-")
    ext = re.sub(r"[^A-Za-z0-9.]", "", ext)[:10]
    return f"{base or 'file'}{ext}"
