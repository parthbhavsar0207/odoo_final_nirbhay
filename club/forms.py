"""
Club Forms - Membership, Court, and Booking input forms
"""

from django import forms
from django.utils import timezone
from .models import Member, MembershipPlan, Court, Booking, BookingParticipant


class MemberForm(forms.ModelForm):
    """
    Form to register and edit club members.
    Handoff to Pratik:
    Field names: 'name', 'email', 'phone', 'contact_details', 'plan',
                 'membership_start', 'membership_end', 'is_club_member', 'is_suspended'
    """
    class Meta:
        model = Member
        fields = [
            'name',
            'email',
            'phone',
            'contact_details',
            'plan',
            'membership_start',
            'membership_end',
            'is_club_member',
            'is_suspended',
        ]
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'Full Name'}),
            'email': forms.EmailInput(attrs={'class': 'form-input', 'placeholder': 'email@example.com'}),
            'phone': forms.TextInput(attrs={'class': 'form-input', 'placeholder': '+91 9876543210'}),
            'contact_details': forms.Textarea(attrs={'class': 'form-textarea', 'rows': 3, 'placeholder': 'Address / Notes'}),
            'plan': forms.Select(attrs={'class': 'form-select'}),
            'membership_start': forms.DateInput(attrs={'class': 'form-input', 'type': 'date'}),
            'membership_end': forms.DateInput(attrs={'class': 'form-input', 'type': 'date'}),
            'is_club_member': forms.CheckboxInput(attrs={'class': 'form-checkbox'}),
            'is_suspended': forms.CheckboxInput(attrs={'class': 'form-checkbox'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk and self.instance.plan_changes.exists():
            self.fields['plan'].disabled = True
            self.fields['plan'].help_text = 'This is the original plan. Use Change Plan to update the dated assignment.'


class BookingForm(forms.ModelForm):
    """
    Form to reserve a court for a member or walk-in.
    Handoff to Pratik:
    Field names: 'court', 'booked_by_member', 'walkin_name', 'walkin_contact',
                 'start_datetime', 'booking_type'
    Note: 'price' and 'status' are strictly controlled by the backend and are not user-editable.
    """
    class Meta:
        model = Booking
        fields = [
            'court',
            'booked_by_member',
            'walkin_name',
            'walkin_contact',
            'start_datetime',
            'booking_type',
            'payment_method',
            'payment_status',
        ]
        widgets = {
            'court': forms.Select(attrs={'class': 'form-select'}),
            'booked_by_member': forms.Select(attrs={'class': 'form-select'}),
            'walkin_name': forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'Guest name (if walk-in)'}),
            'walkin_contact': forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'Contact phone (if walk-in)'}),
            'start_datetime': forms.DateTimeInput(
                attrs={
                    'class': 'form-input',
                    'type': 'datetime-local',
                    'step': '60',  # 1-minute intervals (allows selecting any minute 0-59)
                },
                format='%Y-%m-%dT%H:%M'
            ),
            'booking_type': forms.Select(attrs={'class': 'form-select'}),
            'payment_method': forms.Select(attrs={'class': 'form-select'}),
            'payment_status': forms.Select(attrs={'class': 'form-select'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['court'].queryset = Court.objects.filter(active=True)
        # All members (active, expired, suspended) can be selected for booking history;
        # inactive members automatically receive the walk-in rate.
        self.fields['booked_by_member'].queryset = Member.objects.all()
        self.fields['booked_by_member'].required = False
        self.fields['payment_method'].required = False
        self.fields['payment_status'].required = False
        self.fields['payment_method'].initial = Booking.PaymentMethod.UPI
        self.fields['payment_status'].initial = Booking.PaymentStatus.PAID

    def clean(self):
        cleaned_data = super().clean()
        booked_by = cleaned_data.get('booked_by_member')
        walkin_name = cleaned_data.get('walkin_name')

        if not booked_by and not walkin_name:
            raise forms.ValidationError("Please select a registered member or enter a walk-in guest name.")

        if not cleaned_data.get('payment_method'):
            cleaned_data['payment_method'] = Booking.PaymentMethod.UPI
        if not cleaned_data.get('payment_status'):
            cleaned_data['payment_status'] = Booking.PaymentStatus.PAID

        return cleaned_data


class BookingParticipantForm(forms.ModelForm):
    """
    Form to add a participant (member or guest) to an existing booking.
    """
    class Meta:
        model = BookingParticipant
        fields = ['member', 'guest_name']
        widgets = {
            'member': forms.Select(attrs={'class': 'form-select'}),
            'guest_name': forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'Guest name if not a member'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['member'].queryset = Member.objects.filter(is_suspended=False)
        self.fields['member'].required = False


class MembershipPlanForm(forms.ModelForm):
    """
    Staff-facing form to create and edit membership plans.
    """
    class Meta:
        model = MembershipPlan
        fields = [
            'tier',
            'name',
            'membership_fee',
            'court_hourly_rate',
            'shop_discount_percent',
            'bar_discount_percent',
            'active',
        ]
        widgets = {
            'tier': forms.Select(attrs={'class': 'form-select'}),
            'name': forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'e.g. Gold Tier VIP'}),
            'membership_fee': forms.NumberInput(attrs={'class': 'form-input', 'step': '0.01'}),
            'court_hourly_rate': forms.NumberInput(attrs={'class': 'form-input', 'step': '0.01'}),
            'shop_discount_percent': forms.NumberInput(attrs={'class': 'form-input', 'step': '0.01'}),
            'bar_discount_percent': forms.NumberInput(attrs={'class': 'form-input', 'step': '0.01'}),
            'active': forms.CheckboxInput(attrs={'class': 'form-checkbox'}),
        }


class MemberChangePlanForm(forms.Form):
    """
    Staff-facing form to upgrade or downgrade a member's plan with confirmation.
    """
    new_plan = forms.ModelChoiceField(
        queryset=MembershipPlan.objects.filter(active=True),
        empty_label=None,
        widget=forms.Select(attrs={'class': 'form-select'}),
        label="Target Membership Plan",
    )
    effective_date = forms.DateField(
        widget=forms.DateInput(attrs={'class': 'form-input', 'type': 'date'}),
        label="Effective Transition Date",
        initial=timezone.localdate,
    )
    notes = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'Reason or authorization notes (optional)'}),
        label="Adjustment Notes",
    )
    confirm_change = forms.BooleanField(
        required=True,
        label="I confirm this member plan transition without altering past historical records",
        widget=forms.CheckboxInput(attrs={'class': 'form-checkbox'}),
    )

    def clean_effective_date(self):
        value = self.cleaned_data['effective_date']
        if value < timezone.localdate():
            raise forms.ValidationError('Choose today or a future effective date.')
        return value
