"""Customer inputs never select another member or submit prices/status/stock."""
from datetime import datetime, timedelta
from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm
from django.utils import timezone
from club.availability import OPENING_TIME, CLOSING_TIME, START_INTERVAL, SESSION_LENGTH
from club.models import Court
from commerce.counter_forms import GuestSaleForm


class CustomerRegistrationForm(UserCreationForm):
    email = forms.EmailField(required=True)
    first_name = forms.CharField(max_length=150, label='Your name')

    class Meta(UserCreationForm.Meta):
        model = get_user_model()
        fields = ('username', 'first_name', 'email', 'password1', 'password2')


class CustomerSaleForm(GuestSaleForm):
    payment_method = forms.ChoiceField(choices=[('card', 'Card'), ('UPI', 'UPI')])


def start_choices():
    current = datetime.combine(timezone.localdate(), OPENING_TIME)
    closing = datetime.combine(timezone.localdate(), CLOSING_TIME)
    choices = []
    while current + SESSION_LENGTH <= closing:
        label = current.strftime('%H:%M')
        choices.append((label, label))
        current += START_INTERVAL
    return choices


class CustomerBookingForm(forms.Form):
    court = forms.ModelChoiceField(queryset=Court.objects.filter(active=True))
    date = forms.DateField(widget=forms.DateInput(attrs={'type': 'date'}))
    start_time = forms.ChoiceField(choices=start_choices)
    payment_method = forms.ChoiceField(choices=[('card', 'Card'), ('upi', 'UPI')])

    def clean(self):
        values = super().clean()
        if values.get('date') and values.get('start_time'):
            local_start = timezone.make_aware(datetime.combine(
                values['date'], datetime.strptime(values['start_time'], '%H:%M').time(),
            ))
            if local_start <= timezone.now():
                self.add_error('date', 'Choose a future court session.')
            elif values['date'] > timezone.localdate() + timedelta(days=90):
                self.add_error('date', 'Choose a session within the next 90 days.')
            values['start_datetime'] = local_start
        return values
