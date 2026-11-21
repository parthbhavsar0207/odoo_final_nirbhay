"""
Commerce App URL Configuration (Owned by Utkarsh)
"""

from django.urls import path
from . import views

app_name = 'commerce'

urlpatterns = [
    path('', views.shop_index, name='index'),
    path('shop/', views.shop_index, name='shop'),
]
