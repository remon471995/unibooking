# core/admin.py
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import Group
from django.utils.translation import gettext_lazy as _

from .models import (
    Department, EmployeeProfile,
    UniBookingCard, HotelBooking, FlightBooking,
    Payment, FlightPayment, OtherBooking, OtherPayment,
    TargetCycle, StaffTarget, LeaderTarget, BookingAdjustment
)

User = get_user_model()

# ================== UniBooking Card ==================
@admin.register(UniBookingCard)
class UniBookingCardAdmin(admin.ModelAdmin):
    list_display = ("id", "ub_code", "customer_name", "mobile",
                    "nationality", "country", "created_by", "created_at")
    search_fields = ("customer_name", "ub_code", "mobile")
    list_filter = ("nationality", "country", "created_by")
    ordering = ("-created_at",)


# ================== Hotel Booking ==================
@admin.register(HotelBooking)
class HotelBookingAdmin(admin.ModelAdmin):
    list_display = ("id", "hotel_name", "country", "voucher_code",
                    "checkin", "checkout", "nights", "created_at")
    search_fields = ("hotel_name", "voucher_code", "booking_ref", "card__customer_name")
    list_filter = ("country",)
    ordering = ("-created_at",)


# ================== Hotel Payment ==================
@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ("booking_hotel_display", "method", "paid_amount", "installment_date", "created_at")
    search_fields = ("booking_hotel__hotel_name", "method")
    list_filter = ("method", "installment_date", "created_at")
    ordering = ("-created_at",)

    def booking_hotel_display(self, obj):
        return f"{obj.booking_hotel.hotel_name} ({obj.booking_hotel.voucher_code})"
    booking_hotel_display.short_description = "🏨 الفندق"


# ================== Flight Booking ==================
@admin.register(FlightBooking)
class FlightBookingAdmin(admin.ModelAdmin):
    list_display = ("airline", "pnr", "net_price", "sell_price", "profit", "created_at")
    search_fields = ("airline", "pnr", "card__customer_name")
    list_filter = ("airline",)
    ordering = ("-created_at",)

    def profit(self, obj):
        return obj.profit
    profit.short_description = "💰 الربح"


# ================== Flight Payment ==================
@admin.register(FlightPayment)
class FlightPaymentAdmin(admin.ModelAdmin):
    list_display = ("booking_flight_display", "method", "paid_amount", "installment_date", "created_at")
    search_fields = ("booking_flight__airline", "booking_flight__pnr", "method")
    list_filter = ("method", "installment_date", "created_at")
    ordering = ("-created_at",)

    def booking_flight_display(self, obj):
        return f"{obj.booking_flight.airline} - {obj.booking_flight.pnr}"
    booking_flight_display.short_description = "✈️ الطيران"


# ================== Other Booking ==================
@admin.register(OtherBooking)
class OtherBookingAdmin(admin.ModelAdmin):
    list_display = ("voucher_code", "service_type", "provider_name", "booking_ref", "net_price", "sell_price", "profit")
    search_fields = ("provider_name", "booking_ref")
    list_filter = ("service_type",)
    ordering = ("-id",)

    def profit(self, obj):
        return obj.profit
    profit.short_description = "💰 الربح"


# ================== Other Payment ==================
@admin.register(OtherPayment)
class OtherPaymentAdmin(admin.ModelAdmin):
    list_display = ("booking_other_display", "service_type", "method", "paid_amount", "installment_date", "created_at")
    search_fields = ("booking_other__provider_name", "booking_other__booking_ref", "method")
    list_filter = ("method", "installment_date", "created_at", "booking_other__service_type")
    ordering = ("-created_at",)

    def booking_other_display(self, obj):
        return f"{obj.booking_other.get_service_type_display()} - {obj.booking_other.provider_name or '—'} ({obj.booking_other.voucher_code})"
    booking_other_display.short_description = "📦 أخرى"

    def service_type(self, obj):
        return obj.booking_other.get_service_type_display()
    service_type.short_description = "نوع الخدمة"


# ================== Targets & Adjustments ==================
@admin.register(TargetCycle)
class TargetCycleAdmin(admin.ModelAdmin):
    list_display = ("year", "month", "start_date", "end_date", "locked")
    list_filter = ("locked",)

@admin.register(StaffTarget)
class StaffTargetAdmin(admin.ModelAdmin):
    list_display = ("cycle", "employee", "leader", "set_by", "grade", "target_amount",
                    "thr1", "rate1", "thr2", "rate2", "thr3", "rate3")
    list_filter = ("cycle", "grade")
    search_fields = ("employee__username", "employee__first_name", "employee__last_name")

@admin.register(LeaderTarget)
class LeaderTargetAdmin(admin.ModelAdmin):
    list_display = ("cycle", "leader", "target_amount", "set_by")
    list_filter = ("cycle",)
    search_fields = ("leader__username", "leader__first_name", "leader__last_name")

@admin.register(BookingAdjustment)
class BookingAdjustmentAdmin(admin.ModelAdmin):
    list_display = ("booking_type", "booking_id", "amount", "adj_type", "apply_in_cycle", "cycle", "created_by", "created_at")
    list_filter = ("booking_type", "adj_type", "apply_in_cycle")
    search_fields = ("reason",)


# ================== Departments ==================
@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name", "code")


# ================== User + Profile ==================
class EmployeeProfileInline(admin.StackedInline):
    model = EmployeeProfile
    can_delete = False
    fk_name = "user"
    extra = 0
    fields = ("department", "role", "title", "phone")

# ألغِ التسجيل الافتراضي لـ UserAdmin ثم سجّل إصدارك
try:
    admin.site.unregister(User)
except admin.sites.NotRegistered:
    pass

@admin.register(User)
class UserAdmin(BaseUserAdmin):
    inlines = [EmployeeProfileInline]
    list_display = (
        "username", "first_name", "last_name", "email",
        "is_active", "is_staff", "is_superuser",
        "get_department", "get_role"
    )
    list_filter = (
        "is_active", "is_staff", "is_superuser",
        "employee_profile__department", "employee_profile__role",
    )
    search_fields = ("username", "first_name", "last_name", "email", "employee_profile__phone")

    def get_department(self, obj):
        return getattr(getattr(obj, "profile", None), "department", None)
    get_department.short_description = "القسم"

    def get_role(self, obj):
        prof = getattr(obj, "profile", None)
        return prof.get_role_display() if prof else "-"
    get_role.short_description = "الدور"

    def save_model(self, request, obj, form, change):
        """
        تحديث الجروبات والصلاحيات تلقائيًا حسب department/role:
        - Employee عادي: يضاف لجروب القسم (إن وُجد)، ويكون staff فقط.
        - Leader: يضاف لجروب leaders + جروب القسم، ويكون staff.
        - Super: يكون staff + superuser.
        """
        super().save_model(request, obj, form, change)
        prof = getattr(obj, "profile", None)
        if not prof:
            return

        # تأكد من وجود الجروبات الأساسية
        base_names = ("sales", "quotation", "leaders")
        base_groups = {}
        for name in base_names:
            g, _ = Group.objects.get_or_create(name=name)
            base_groups[name] = g

        # امسح عضوية الجروبات الأساسية
        obj.groups.remove(*Group.objects.filter(name__in=base_groups.keys()))

        dep_code = (getattr(prof.department, "code", "") or "").lower()

        if prof.role == EmployeeProfile.ROLE_EMP:
            if dep_code in base_groups:
                obj.groups.add(base_groups[dep_code])
            obj.is_staff = True
            obj.is_superuser = False

        elif prof.role == EmployeeProfile.ROLE_LEAD:
            obj.groups.add(base_groups["leaders"])
            if dep_code in base_groups:
                obj.groups.add(base_groups[dep_code])
            obj.is_staff = True
            obj.is_superuser = False

        elif prof.role == EmployeeProfile.ROLE_SUPER:
            obj.is_staff = True
            obj.is_superuser = True

        obj.save(update_fields=["is_staff", "is_superuser"])
