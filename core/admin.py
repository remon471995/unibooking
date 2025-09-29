from django.contrib import admin
from .models import (
    UniBookingCard, HotelBooking, FlightBooking,
    TransferBooking, VisaBooking, Payment
)


@admin.register(UniBookingCard)
class UniBookingCardAdmin(admin.ModelAdmin):
    list_display = ("id", "ub_code", "customer_name", "mobile", "nationality", "country", "created_by", "created_at")
    search_fields = ("customer_name", "ub_code", "mobile")
    list_filter = ("nationality", "country", "created_by")
    ordering = ("-created_at",)


@admin.register(HotelBooking)
class HotelBookingAdmin(admin.ModelAdmin):
    list_display = ("id", "hotel_name", "country", "voucher_code", "checkin", "checkout", "nights", "employee_name", "created_at")
    search_fields = ("hotel_name", "voucher_code", "booking_ref", "card__customer_name")
    list_filter = ("country", "employee_name")
    ordering = ("-created_at",)


@admin.register(FlightBooking)
class FlightBookingAdmin(admin.ModelAdmin):
    list_display = ("airline", "pnr", "net_price", "sell_price", "payment_method")
    search_fields = ("airline", "pnr", "voucher_code", "booking_ref", "card__customer_name")
    list_filter = ("airline", "payment_method")
    ordering = ("-created_at",)


@admin.register(TransferBooking)
class TransferBookingAdmin(admin.ModelAdmin):
    list_display = ("id", "pickup", "dropoff", "date", "voucher_code", "employee_name", "created_at")
    search_fields = ("pickup", "dropoff", "voucher_code", "booking_ref", "card__customer_name")
    list_filter = ("employee_name",)
    ordering = ("-created_at",)


@admin.register(VisaBooking)
class VisaBookingAdmin(admin.ModelAdmin):
    list_display = ("id", "visa_type", "nationality", "voucher_code", "employee_name", "created_at")
    search_fields = ("visa_type", "nationality", "voucher_code", "booking_ref", "card__customer_name")
    list_filter = ("visa_type", "nationality", "employee_name")
    ordering = ("-created_at",)


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "booking_hotel",
        "net_price",
        "sell_price",
        "paid_amount",
        "remaining",
        "created_at",
    )
    search_fields = ("booking_hotel__hotel_name", "booking_hotel__voucher_code")
    list_filter = ("created_at",)
    ordering = ("-created_at",)

    def remaining(self, obj):
        return obj.remain
    remaining.short_description = "المتبقي"

