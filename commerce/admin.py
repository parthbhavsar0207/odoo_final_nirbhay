from django.contrib import admin

from .forms import ProductForm
from .models import Product


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    form = ProductForm
    list_display = [
        "id",
        "name",
        "category",
        "price",
        "stock_quantity",
        "low_stock_threshold",
        "low_stock",
        "is_active",
    ]
    list_filter = ["category", "is_active"]
    search_fields = ["name"]
    readonly_fields = ["low_stock"]

    def get_readonly_fields(self, request, obj=None):
        fields = tuple(super().get_readonly_fields(request, obj))
        if obj is not None:
            # Absolute stock edits from an old admin page can overwrite sales.
            return fields + ("stock_quantity",)
        return fields

    def save_model(self, request, obj, form, change):
        if not change:
            return super().save_model(request, obj, form, change)
        # Save only submitted changes, never the stale inventory on obj.
        changed_fields = [
            field for field in self.form._meta.fields
            if field in form.changed_data and field != "stock_quantity"
        ]
        if changed_fields:
            obj.save(update_fields=changed_fields)

    @admin.display(boolean=True, description="Low stock")
    def low_stock(self, obj):
        return obj.is_low_stock
