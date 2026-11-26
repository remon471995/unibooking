from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from accounts.forms import DEPARTMENT_CHOICES
from accounts.models import UserProfile

User = get_user_model()
DEP = next(v for v, _ in DEPARTMENT_CHOICES if v)
ROLE = next(v for v, _ in UserProfile.ROLE_CHOICES if v and v != "agent")


class BulkStaffActionsTests(TestCase):
    def setUp(self):
        self.root = User.objects.create_user("root", password="x", is_superuser=True, is_staff=True)
        self.u1 = User.objects.create_user("u1", password="x")
        self.u2 = User.objects.create_user("u2", password="x")
        self.url = reverse("accounts:manage_staff")
        self.client.force_login(self.root)

    def _post(self, **data):
        return self.client.post(self.url, data)

    def test_the_checkboxes_belong_to_the_bulk_form(self):
        r = self.client.get(self.url)
        self.assertContains(r, 'form="bulk-form"')
        self.assertContains(r, 'id="bulk-form"')

    def test_move_the_selected_users_to_a_department(self):
        self._post(action="set_department", department=DEP, selected=[self.u1.id, self.u2.id])
        self.assertEqual(User.objects.get(pk=self.u1.pk).profile.department, DEP)
        self.assertEqual(User.objects.get(pk=self.u2.pk).profile.department, DEP)

    def test_promote_the_selected_user(self):
        self._post(action="change_role", role=ROLE, selected=[self.u1.id])
        self.assertEqual(User.objects.get(pk=self.u1.pk).profile.role, ROLE)
        self.assertNotEqual(User.objects.get(pk=self.u2.pk).profile.role, ROLE)

    def test_nothing_chosen_does_not_clear_the_department(self):
        UserProfile.objects.filter(user=self.u1).update(department=DEP)
        self._post(action="set_department", department="", selected=[self.u1.id])
        self.assertEqual(User.objects.get(pk=self.u1.pk).profile.department, DEP)

    def test_no_user_selected_changes_nothing(self):
        self._post(action="set_department", department=DEP)
        self.assertNotEqual(User.objects.get(pk=self.u1.pk).profile.department, DEP)
