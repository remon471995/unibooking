from django.contrib import admin

from .models import FlightItinerary, FlightPassenger, FlightSegment


class PassengerInline(admin.TabularInline):
    model = FlightPassenger
    extra = 0


class SegmentInline(admin.StackedInline):
    model = FlightSegment
    extra = 0


@admin.register(FlightItinerary)
class FlightItineraryAdmin(admin.ModelAdmin):
    list_display = ("booking", "booking_ref", "trip_type", "has_transit", "created_at")
    search_fields = ("booking_ref", "passengers__name", "passengers__ticket_no")
    inlines = [PassengerInline, SegmentInline]
