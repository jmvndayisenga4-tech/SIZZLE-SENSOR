from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm
from django.core.exceptions import ValidationError


class ApprovalAuthenticationForm(AuthenticationForm):
    """Login form that tells a correct-password-but-not-yet-approved user why they cannot sign in."""

    def clean(self):
        username = self.cleaned_data.get("username")
        password = self.cleaned_data.get("password")
        if username and password:
            User = get_user_model()
            user = User._default_manager.filter(**{User.USERNAME_FIELD: username}).first()
            if user is not None and not user.is_active and user.check_password(password):
                raise ValidationError(
                    "Your account is waiting for admin approval (or has been disabled). "
                    "Please try again later.",
                    code="pending",
                )
        return super().clean()
