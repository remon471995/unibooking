from django.urls import path
from django.views.generic import RedirectView
from . import views

urlpatterns = [
    # Dashboard
    path("", views.dashboard, name="dashboard"),

    # Boards
    path("agent/board/", views.agent_board, name="agent_board"),
    path("installments/", views.installments_board, name="installments_board"),

    # Cards
    path("cards/create/", views.card_create, name="card_create"),
    path("cards/<int:pk>/", views.card_detail, name="card_detail"),
    path("cards/export/", views.cards_bulk_export, name="cards_bulk_export"),
    path("cards/delete/", views.cards_bulk_delete, name="cards_bulk_delete"),

    # Hotel
    path("cards/<int:card_pk>/hotel/create/", views.hotel_create, name="hotel_create"),
    path("hotel/<int:booking_pk>/payment/", views.hotel_payment, name="hotel_payment"),
    path("hotel/<int:booking_pk>/voucher/", views.hotel_voucher, name="hotel_voucher"),
    path("hotel/<int:booking_pk>/voucher/pdf/", views.hotel_voucher_pdf, name="hotel_voucher_pdf"),

    # Payment edit/delete (Hotel payments)
    path("payment/<int:payment_pk>/edit/", views.payment_edit, name="payment_edit"),
    path("payment/<int:payment_pk>/delete/", views.payment_delete, name="payment_delete"),

    # Flight
    path("cards/<int:card_pk>/flight/create/", views.flight_create, name="flight_create"),
    path("flight/<int:booking_pk>/voucher/", views.flight_voucher, name="flight_voucher"),
    path("flight/<int:booking_pk>/voucher/pdf/", views.flight_voucher_pdf, name="flight_voucher_pdf"),
    path("flight/<int:booking_pk>/payment/", views.flight_payment, name="flight_payment"),

    # Other
    path("cards/<int:card_pk>/other/create/", views.other_create, name="other_create"),
    path("other/<int:pk>/payment/", views.other_payment, name="other_payment"),

    # Reports (main)
    path("reports/", views.reports, name="reports"),
    path("reports/export/csv/", views.reports_export_csv, name="reports_export_csv"),
    path("reports/export/xlsx/", views.reports_export_xlsx, name="reports_export_xlsx"),
    path("reports/export/pdf/", views.reports_export_pdf, name="reports_export_pdf"),

    # Reports: Analysis
    path("reports/analysis/", views.reports_analysis, name="reports_analysis"),
    path("reports/analysis/export/xlsx/", views.reports_analysis_export_xlsx, name="reports_analysis_export_xlsx"),

    # Reports: Suppliers (canonical)
    path("reports/suppliers/", views.suppliers_report, name="suppliers_report"),
    path("reports/suppliers/export/xlsx/", views.suppliers_export_xlsx, name="suppliers_export_xlsx"),

    # Legacy/short redirects
    path("dashboard/add/", RedirectView.as_view(pattern_name="card_create", permanent=False)),
    path("dashboard/", RedirectView.as_view(pattern_name="dashboard", permanent=False)),
    path("suppliers/", RedirectView.as_view(pattern_name="suppliers_report", permanent=False)),

    # Placeholder
    path("cards/<int:card_pk>/transfer/create/", views.not_implemented, name="transfer_create"),
    path("cards/<int:card_pk>/visa/create/", views.not_implemented, name="visa_create"),

    # Notifications
    path("notifications/", views.notifications_list, name="notifications_list"),
    path("notifications/<int:pk>/read/", views.notification_mark_read, name="notification_mark_read"),

    # Performance
    path("performance/", views.performance_dashboard, name="performance_dashboard"),
    path("performance/export/xlsx/", views.performance_export_xlsx, name="performance_export_xlsx"),

    # Search & Employees
    path("search/", views.global_search, name="global_search"),
    path("employees/", views.employees_list, name="employees_list"),
]
