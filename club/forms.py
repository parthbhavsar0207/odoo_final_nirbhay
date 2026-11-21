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
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['court'].queryset = Court.objects.filter(active=True)
        # All members (active, expired, suspended) can be selected for booking history;
        # inactive members automatically receive the walk-in rate.
        self.fields['booked_by_member'].queryset = Member.objects.all()
        self.fields['booked_by_member'].required = False

    def clean(self):
        cleaned_data = super().clean()
        booked_by = cleaned_data.get('booked_by_member')
        walkin_name = cleaned_data.get('walkin_name')

        if not booked_by and not walkin_name:
            raise forms.ValidationError("Please select a registered member or enter a walk-in guest name.")

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
