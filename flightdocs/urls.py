from django.urls import path

from . import views

app_name = "flightdocs"

urlpatterns = [
    path("parse/", views.parse_ticket, name="parse"),
    path("booking/<int:booking_pk>/upload/", views.itinerary_upload, name="upload"),
    path("booking/<int:booking_pk>/voucher/", views.voucher, name="voucher"),
    path("booking/<int:booking_pk>/voucher/pdf/", views.voucher_pdf, name="voucher_pdf"),
]
