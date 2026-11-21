"""
Champions Club Frontend URLs
Routes owner dashboard and UI views.
"""

from django.urls import path
from .views import dashboard_view

urlpatterns = [
    path('', dashboard_view, name='dashboard'),
]
