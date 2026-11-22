"""
Commerce App URL Configuration (Owned by Utkarsh)
"""

from django.urls import path
from . import views
from . import payment_views

app_name = 'commerce'

urlpatterns = [
    path('demo-payment/<str:kind>/<int:pk>/', payment_views.demo_payment, name='demo_payment'),
    path('demo-payment/<str:kind>/<int:pk>/submit/', payment_views.demo_payment_submit, name='demo_payment_submit'),
    path('', views.guest_counter, name='index'),
    path('shop/', views.guest_counter, name='shop'),
    path('counter/', views.guest_counter, name='guest_counter'),
    path('counter/member/', views.member_counter, name='member_counter'),
    path('sales/member/create/', views.member_sale_create, name='member_sale_create'),
    path('sales/create/', views.sale_create, name='sale_create'),
    path('sales/<int:pk>/', views.sale_detail, name='sale_detail'),
    path('sales/<int:pk>/receipt/', views.sale_receipt, name='sale_receipt'),
    path('sales/<int:pk>/complete/', views.sale_complete, name='sale_complete'),
    path('sales/<int:pk>/cancel/', views.sale_cancel, name='sale_cancel'),
]
