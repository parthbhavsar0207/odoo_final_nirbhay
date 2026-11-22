"""
Champions Club Frontend URLs
Routes owner dashboard and UI views.
"""

from django.urls import path, include
from .views import dashboard_view

urlpatterns = [
    path('customer/', include('frontend.customer_urls')),
    path('', dashboard_view, name='dashboard'),
]
