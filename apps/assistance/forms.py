from django import forms

from apps.assistance.models import CitizenRequest


class RecoverAccessForm(forms.Form):
    email = forms.EmailField(
        label="Email address",
        max_length=254,
        widget=forms.EmailInput(
            attrs={
                "autocomplete": "email",
                "placeholder": "you@example.com",
            }
        ),
    )

    def clean_email(self):
        return self.cleaned_data["email"].strip().lower()


class TrackRequestForm(forms.Form):
    tracking_code = forms.CharField(
        label="Tracking code",
        max_length=24,
        widget=forms.TextInput(
            attrs={
                "autocomplete": "off",
                "placeholder": "Example: TP-20260525123045",
            }
        ),
    )

    def clean_tracking_code(self):
        tracking_code = self.cleaned_data["tracking_code"].strip()
        if not CitizenRequest.objects.filter(
            tracking_code=tracking_code,
            is_active=True,
        ).exists():
            raise forms.ValidationError(
                "We could not find an active request with that tracking code. "
                "Please check the code or recover your request links below."
            )
        return tracking_code
