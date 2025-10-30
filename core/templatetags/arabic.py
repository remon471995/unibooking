# core/templatetags/arabic.py
from django import template
import arabic_reshaper
from bidi.algorithm import get_display

register = template.Library()

@register.filter
def ar(value):
    """
    يرجّع النص العربي مشكّل وجاهز للعرض في PDF مع xhtml2pdf.
    يتجاهل None ويحوّله لسلسلة فاضية.
    """
    if value is None:
        return ""
    text = str(value)
    # لو في أسطر متعددة (مثل أسماء نزلاء كل واحد في سطر)
    lines = text.splitlines() if "\n" in text else [text]
    shaped_lines = []
    for line in lines:
        # تشكيل جليفات + ترتيب بصري صحيح
        reshaped = arabic_reshaper.reshape(line)
        bidi_text = get_display(reshaped)
        shaped_lines.append(bidi_text)
    return "\n".join(shaped_lines)
