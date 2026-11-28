import sys
from unittest import mock

from django.test import SimpleTestCase

from core import background


class BackgroundRunnerTests(SimpleTestCase):
    def test_it_never_starts_under_tests_or_management_commands(self):
        for argv in (["manage.py", "test"], ["manage.py", "migrate"], ["manage.py", "collectstatic"],
                     ["manage.py", "installment_reminders"], ["python", "-m", "pytest"]):
            with mock.patch.object(sys, "argv", argv):
                self.assertFalse(background._is_web_server(), argv)

    def test_it_starts_under_gunicorn(self):
        with mock.patch.object(sys, "argv", ["/usr/local/bin/gunicorn", "unibooking.wsgi:application"]):
            self.assertTrue(background._is_web_server())

    def test_it_can_be_switched_off(self):
        with mock.patch.object(sys, "argv", ["gunicorn"]), mock.patch.dict("os.environ", {"DISABLE_BACKGROUND_JOBS": "1"}), \
                mock.patch.object(background, "_started", False):
            self.assertFalse(background.start())
