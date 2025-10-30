from django.urls import path
from . import views

app_name = "helpdesk"

urlpatterns = [
    # صناديق الوارد
    path("", views.my_inbox, name="my_inbox"),
    path("department/<slug:slug>/", views.department_inbox, name="department_inbox"),

    # إنشاء/عرض التذاكر
    path("ticket/new/", views.ticket_create, name="ticket_create"),
    path("ticket/<int:pk>/", views.ticket_detail, name="ticket_detail"),
    path("ticket/<int:pk>/assign-me/", views.assign_me, name="assign_me"),
    path("ticket/<int:pk>/status/<str:new_status>/", views.change_status, name="change_status"),

    # أدوات مساعدة
    path("dashboard/", views.dashboard, name="dashboard"),
    path("search/", views.search, name="search"),
    path("export.csv", views.export_csv, name="export_csv"),

    # HTMX partials
    path("ticket/<int:pk>/messages-partial/", views.ticket_messages_partial, name="ticket_messages_partial"),
    path("categories/options/", views.category_options, name="category_options"),  # NEW
]
