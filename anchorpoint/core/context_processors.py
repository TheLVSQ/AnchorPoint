from .models import OrganizationSettings


def organization_settings(request):
    return {
        "organization_settings": OrganizationSettings.load(),
    }
