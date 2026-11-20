from django.conf import settings
from django.db import models


class ModificationRequest(models.Model):
    """طلب تعديل (أسعار / دفعة / ملفات) على حجز. بيستنى اعتماد الداتا انتري قبل ما يتنفّذ على الحجز."""

    PENDING, APPROVED, RETURNED = "pending", "approved", "returned"
    STATUS_CHOICES = [(PENDING, "بانتظار الاعتماد"), (APPROVED, "معتمد"), (RETURNED, "مرجوع")]

    kind = models.CharField(max_length=10, db_index=True)            # hotel / flight / other
    booking_id = models.PositiveIntegerField(db_index=True)
    card_id = models.PositiveBigIntegerField(db_index=True)
    ref = models.CharField(max_length=60, blank=True)
    customer = models.CharField(max_length=150, blank=True)

    # الفروق المطلوبة (بتتطبق على القيم الحالية وقت الاعتماد)
    delta_sell = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    delta_net = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    delta_paid = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    method = models.CharField(max_length=10, blank=True)
    payment_link = models.CharField(max_length=500, blank=True)
    bank_file = models.FileField(upload_to="modifications/banks/", null=True, blank=True)
    invoice_file = models.FileField(upload_to="modifications/invoices/", null=True, blank=True)
    voucher_original = models.FileField(upload_to="modifications/vouchers/", null=True, blank=True)
    note = models.CharField(max_length=255, blank=True)

    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=PENDING, db_index=True)
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                     on_delete=models.SET_NULL, related_name="+")
    requested_by_name = models.CharField(max_length=150, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                    on_delete=models.SET_NULL, related_name="+")
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_note = models.CharField(max_length=255, blank=True)
    applied_payment_id = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        verbose_name = "طلب تعديل"
        verbose_name_plural = "طلبات التعديل"

    def __str__(self):
        return f"طلب تعديل {self.kind} #{self.booking_id} ({self.get_status_display()})"
