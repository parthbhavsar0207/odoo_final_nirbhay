"""
URL configuration for Champions Club project.
"""

from django.contrib import admin
from django.urls import path, include
from django.contrib.staticfiles.urls import staticfiles_urlpatterns
from frontend.auth import StaffLoginView, StaffLogoutView, staff_home

urlpatterns = [
    path('accounts/login/', StaffLoginView.as_view(), name='staff_login'),
    path('accounts/logout/', StaffLogoutView.as_view(), name='staff_logout'),
    path('accounts/', staff_home, name='staff_home'),
    path('admin/', admin.site.urls),
    path('', include('frontend.urls')),
    path('club/', include('club.urls', namespace='club')),
    path('commerce/', include('commerce.urls', namespace='commerce')),
]

urlpatterns += staticfiles_urlpatterns()
