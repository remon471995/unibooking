from django.urls import path
from . import views

urlpatterns = [
    # Dashboard
    path("", views.dashboard, name="dashboard"),
    path("overview/", views.dashboard_overview, name="dashboard_overview"),

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

    # --- الروابط الجديدة للتعديل والحذف ---
    path("payment/<int:payment_pk>/edit/", views.payment_edit, name="payment_edit"),
    path("payment/<int:payment_pk>/delete/", views.payment_delete, name="payment_delete"),
    # ------------------------------------

    # Flight
    path("cards/<int:card_pk>/flight/create/", views.flight_create, name="flight_create"),
    path("flight/<int:booking_pk>/voucher/", views.flight_voucher, name="flight_voucher"),
    path("flight/<int:booking_pk>/payment/", views.flight_payment, name="flight_payment"),


    # Transfer
    path("cards/<int:card_pk>/transfer/create/", views.transfer_create, name="transfer_create"),
    path("transfer/<int:booking_pk>/voucher/", views.transfer_voucher, name="transfer_voucher"),
    path("transfer/<int:booking_pk>/voucher/pdf/", views.transfer_voucher_pdf, name="transfer_voucher_pdf"),

    # Visa
    path("cards/<int:card_pk>/visa/create/", views.visa_create, name="visa_create"),
    path("visa/<int:booking_pk>/voucher/", views.visa_voucher, name="visa_voucher"),
    path("visa/<int:booking_pk>/voucher/pdf/", views.visa_voucher_pdf, name="visa_voucher_pdf"),

    # Reports
    path("reports/", views.reports, name="reports"),
    path("reports/export/csv/", views.reports_export_csv, name="reports_export_csv"),
    path("reports/export/xlsx/", views.reports_export_xlsx, name="reports_export_xlsx"),
    path("reports/export/pdf/", views.reports_export_pdf, name="reports_export_pdf"),

    # Voucher Upload & Generate
    path("voucher/upload/", views.voucher_upload, name="voucher_upload"),
    path("voucher/generate/", views.voucher_generate, name="voucher_generate"),
]