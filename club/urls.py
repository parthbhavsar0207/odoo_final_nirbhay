"""
Club App URL Configuration (Owned by Nayan)
"""

from django.urls import path
from . import views

app_name = 'club'

urlpatterns = [
    path('', views.member_list, name='index'),
    path('members/', views.member_list, name='member_list'),
    path('bookings/', views.booking_list, name='booking_list'),
]
