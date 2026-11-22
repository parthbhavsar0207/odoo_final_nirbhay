from django.contrib import admin
from .models import CustomerAccount


@admin.register(CustomerAccount)
class CustomerAccountAdmin(admin.ModelAdmin):
    """Staff verify identity before linking an existing membership."""
    list_display = ('user', 'member')
    raw_id_fields = ('user', 'member')
    search_fields = ('user__username', 'member__name')
