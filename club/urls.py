"""
Club App URL Configuration
Owned by Nayan (Backend: Membership and Bookings)
"""

from django.urls import path
from . import views

app_name = 'club'

urlpatterns = [
    # Members
    path('', views.member_list, name='index'),
    path('members/', views.member_list, name='member_list'),
    path('members/new/', views.member_create, name='member_create'),
    path('members/<int:pk>/edit/', views.member_edit, name='member_edit'),
    path('members/<int:pk>/change-plan/', views.member_change_plan, name='member_change_plan'),

    # Membership Plans Management (Staff & Public)
    path('plans/', views.plan_list, name='plan_list'),
    path('plans/new/', views.plan_create, name='plan_create'),
    path('plans/<int:pk>/edit/', views.plan_edit, name='plan_edit'),
    path('plans/<int:pk>/toggle-active/', views.plan_toggle_active, name='plan_toggle_active'),
    path('plans/public/', views.public_plans, name='public_plans'),

    # 10 Sports Section & Shared Detail Flow
    path('sports/', views.sports_directory, name='sports_directory'),
    path('sports/<str:sport_slug>/', views.sport_detail, name='sport_detail'),

    # Bookings
    path('bookings/', views.booking_list, name='booking_list'),
    path('bookings/new/', views.booking_create, name='booking_create'),
    path('bookings/<int:pk>/', views.booking_detail, name='booking_detail'),
    path('bookings/<int:pk>/cancel/', views.booking_cancel, name='booking_cancel'),

    # Public Live Availability
    path('availability/', views.public_availability, name='public_availability'),

    # Interactive APIs (Search Suggestions & Help Bot)
    path('api/suggestions/', views.search_suggestions_api, name='search_suggestions'),
    path('api/faq/', views.help_bot_faq_api, name='help_bot_faq'),
]
