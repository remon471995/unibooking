import re
from pathlib import Path

from django.test import SimpleTestCase
from django.urls import resolve, reverse

import core.forms


class CleanupGuardTests(SimpleTestCase):
    def test_the_payment_form_is_defined_once(self):
        src = Path(core.forms.__file__).read_text(encoding="utf-8")
        self.assertEqual(len(re.findall(r"^class PaymentForm\(", src, re.M)), 1)

    def test_the_modification_screens_are_the_reviewed_ones(self):
        """If modreq failed to install its views, the placeholders would be served: make that a loud failure."""
        for kind in ("hotel", "flight", "other"):
            func = resolve(reverse(f"{kind}_payment_modify", args=[1])).func
            self.assertEqual(func.__module__, "modreq.override_views", kind)
