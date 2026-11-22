from django.contrib.auth.views import LoginView, LogoutView
from django.urls import path
from . import customer_views as views

app_name = 'customer'
urlpatterns = [
    path('', views.home, name='home'),
    path('courts/', views.courts, name='courts'),
    path('shop/', views.shop, name='shop'),
    path('plans/', views.plans, name='plans'),
    path('register/', views.register, name='register'),
    path('login/', LoginView.as_view(template_name='customer/login.html', next_page='customer:dashboard', redirect_authenticated_user=True), name='login'),
    path('logout/', LogoutView.as_view(next_page='customer:home'), name='logout'),
    path('account/', views.dashboard, name='dashboard'),
    path('bookings/new/', views.booking_create, name='booking_create'),
    path('bookings/<int:pk>/', views.booking_detail, name='booking_detail'),
    path('bookings/<int:pk>/cancel/', views.booking_cancel, name='booking_cancel'),
    path('sales/create/', views.sale_create, name='sale_create'),
    path('sales/<int:pk>/', views.sale_detail, name='sale_detail'),
    path('sales/<int:pk>/cancel/', views.sale_cancel, name='sale_cancel'),
    path('checkout/<str:kind>/<int:pk>/', views.checkout, name='checkout'),
]
