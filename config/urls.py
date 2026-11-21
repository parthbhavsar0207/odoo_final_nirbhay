"""
URL configuration for Champions Club project.
"""

from django.contrib import admin
from django.urls import path, include
from django.contrib.staticfiles.urls import staticfiles_urlpatterns

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('frontend.urls')),
    path('club/', include('club.urls', namespace='club')),
    path('commerce/', include('commerce.urls', namespace='commerce')),
]

urlpatterns += staticfiles_urlpatterns()
