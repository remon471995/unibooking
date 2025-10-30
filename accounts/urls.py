# accounts/urls.py
from django.urls import path
from . import views

app_name = "accounts"

urlpatterns = [
    # صفحة "حسابي" و تغيير كلمة المرور (يعيد ل my_profile)
    path("me/", views.my_profile, name="my_profile"),
    path("password/", views.change_password, name="change_password"),

    # تسجيل خروج (نستخدم accounts:logout في القوالب)
    path("logout/", views.logout_view, name="logout"),

    # إدارة الموظفين (سوبر فقط)
    path("manage/", views.manage_staff, name="manage_staff"),
    path("create/", views.create_user, name="create_user"),
    path("<int:user_id>/edit/", views.edit_user, name="edit_user"),
    path("<int:user_id>/change-password/", views.change_user_password, name="change_user_password"),
    path("<int:user_id>/toggle-active/", views.toggle_active, name="toggle_active"),
]
