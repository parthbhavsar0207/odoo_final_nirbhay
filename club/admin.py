"""
Club Django Admin Registration
"""

from django.contrib import admin
from .models import MembershipPlan, Member, Court, Booking, BookingParticipant


@admin.register(MembershipPlan)
class MembershipPlanAdmin(admin.ModelAdmin):
    list_display = ('name', 'tier', 'court_hourly_rate', 'shop_discount_percent', 'bar_discount_percent', 'active')
    list_filter = ('tier', 'active')
    search_fields = ('name',)


@admin.register(Member)
class MemberAdmin(admin.ModelAdmin):
    list_display = ('name', 'plan', 'phone', 'membership_start', 'membership_end', 'is_active_member', 'is_suspended')
    list_filter = ('plan', 'is_club_member', 'is_suspended')
    search_fields = ('name', 'email', 'phone')


@admin.register(Court)
class CourtAdmin(admin.ModelAdmin):
    list_display = ('name', 'sport', 'capacity', 'hourly_rate', 'active')
    list_filter = ('sport', 'active')
    search_fields = ('name',)


class BookingParticipantInline(admin.TabularInline):
    model = BookingParticipant
    extra = 1


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = ('id', 'court', 'booked_by_member', 'walkin_name', 'start_datetime', 'end_datetime', 'status', 'booking_type', 'price')
    list_filter = ('court', 'status', 'booking_type', 'start_datetime')
    search_fields = ('court__name', 'booked_by_member__name', 'walkin_name')
    inlines = [BookingParticipantInline]
