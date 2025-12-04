from django.contrib import messages
from django.contrib.auth import authenticate, get_user_model, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth import update_session_auth_hash
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from people.models import Person

from .forms import (
    OrganizationSettingsForm,
    ProfileForm,
    RoleAssignmentForm,
    UserProfileForm,
)
from .models import OrganizationSettings, UserProfile


def login_view(request):
    if request.method == "POST":
        username = request.POST.get("username")
        password = request.POST.get("password")

        user = authenticate(request, username=username, password=password)

        if user is not None:
            login(request, user)
            return redirect("dashboard")
        else:
            messages.error(request, "Invalid username or password.")

    return render(request, "core/login.html")


def logout_view(request):
    logout(request)
    return redirect("login")


User = get_user_model()


def user_is_admin(user):
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    profile = getattr(user, "profile", None)
    return bool(profile and profile.is_admin)


def dashboard(request):
    if not request.user.is_authenticated:
        return redirect("login")

    people_count = Person.objects.count()
    recent_people = Person.objects.order_by("-id")[:4]

    context = {
        "people_count": people_count,
        "recent_people": recent_people,
    }
    return render(request, "core/dashboard.html", context)


@login_required
def profile(request):
    profile_obj, _ = UserProfile.objects.get_or_create(user=request.user)
    user_form = ProfileForm(instance=request.user)
    profile_form = UserProfileForm(instance=profile_obj)

    if request.method == "POST":
        # Profile update (name, email)
        if "update_profile" in request.POST:
            user_form = ProfileForm(request.POST, instance=request.user)
            profile_form = UserProfileForm(request.POST, instance=profile_obj)

            if user_form.is_valid() and profile_form.is_valid():
                user_form.save()
                profile_form.save()
                messages.success(request, "Profile updated successfully!")
                return redirect("profile")
            else:
                messages.error(request, "Please correct the errors below.")

        # Password change logic
        elif "update_password" in request.POST:
            current_password = request.POST.get("current_password")
            new_password = request.POST.get("new_password")
            confirm_password = request.POST.get("confirm_password")

            # Check current password
            if not request.user.check_password(current_password):
                messages.error(request, "Current password is incorrect.")
                return redirect("profile")

            # Validate new password match
            if new_password != confirm_password:
                messages.error(request, "New passwords do not match.")
                return redirect("profile")

            # Update password
            request.user.set_password(new_password)
            request.user.save()

            # Keep user logged in after password change
            update_session_auth_hash(request, request.user)

            messages.success(request, "Password updated successfully!")
            return redirect("profile")

    context = {
        "user_form": user_form,
        "profile_form": profile_form,
    }
    return render(request, "core/profile.html", context)


@login_required
def manage_roles(request):
    if not user_is_admin(request.user):
        return HttpResponseForbidden("You do not have permission to manage roles.")

    users = (
        User.objects.all()
        .select_related("profile")
        .order_by("first_name", "last_name", "username")
    )

    if request.method == "POST":
        form = RoleAssignmentForm(request.POST)
        if form.is_valid():
            target_user = get_object_or_404(User, pk=form.cleaned_data["user_id"])
            profile, _ = UserProfile.objects.get_or_create(user=target_user)
            profile.role = form.cleaned_data["role"]
            profile.save()
            display_name = target_user.get_full_name() or target_user.username
            messages.success(request, f"{display_name} role updated.")
            return redirect("manage_roles")
        messages.error(
            request, "There was a problem updating that role. Please try again."
        )

    context = {
        "users": users,
        "role_choices": UserProfile.Role.choices,
    }
    return render(request, "core/manage_roles.html", context)


@login_required
def organization_settings(request):
    if not user_is_admin(request.user):
        return HttpResponseForbidden("You do not have permission to edit organization settings.")

    settings_instance = OrganizationSettings.load()

    if request.method == "POST":
        form = OrganizationSettingsForm(request.POST, instance=settings_instance)
        if form.is_valid():
            form.save()
            messages.success(request, "Organization settings updated.")
            return redirect("organization_settings")
        messages.error(request, "Please correct the errors below.")
    else:
        form = OrganizationSettingsForm(instance=settings_instance)

    return render(
        request,
        "core/organization_settings.html",
        {"form": form},
    )
