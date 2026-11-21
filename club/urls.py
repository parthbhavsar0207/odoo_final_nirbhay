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

    # Bookings
    path('bookings/', views.booking_list, name='booking_list'),
    path('bookings/new/', views.booking_create, name='booking_create'),
    path('bookings/<int:pk>/', views.booking_detail, name='booking_detail'),
    path('bookings/<int:pk>/cancel/', views.booking_cancel, name='booking_cancel'),

    # Public Live Availability
    path('availability/', views.public_availability, name='public_availability'),
]
