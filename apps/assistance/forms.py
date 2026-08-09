from django import forms


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
