from django import forms

from .models import Product, Sale


class GuestSaleForm(forms.Form):
    """One guest draft line; totals and stock eligibility belong to checkout."""

    product = forms.ModelChoiceField(queryset=Product.objects.filter(is_active=True))
    quantity = forms.IntegerField(min_value=1, max_value=2147483647)
    payment_method = forms.ChoiceField(choices=Sale.PaymentMethod.choices)
