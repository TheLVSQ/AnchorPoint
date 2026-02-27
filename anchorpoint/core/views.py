from django.contrib import messages
from django.contrib.auth import authenticate, get_user_model, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth import update_session_auth_hash
from django.shortcuts import get_object_or_404, redirect, render
from people.models import Person

from events.forms import ReleaseDocumentForm
from events.models import ReleaseDocument

from .forms import (
    CreateUserForm,
    EditUserForm,
    OrganizationSettingsForm,
    ProfileForm,
    RoleAssignmentForm,
    SetPasswordForm,
    UserProfileForm,
)
from .models import OrganizationSettings, UserProfile
from .permissions import admin_required


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


@admin_required
def manage_roles(request):

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
            profile.can_manage_communications = form.cleaned_data[
                "can_manage_communications"
            ]
            profile.save(update_fields=["role", "can_manage_communications"])
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


@admin_required
def organization_settings(request):

    settings_instance = OrganizationSettings.load()
    release_form = ReleaseDocumentForm()
    release_documents = ReleaseDocument.objects.all().order_by("category", "name")

    if request.method == "POST":
        form_type = request.POST.get("form_type", "settings")
        if form_type == "release":
            release_form = ReleaseDocumentForm(request.POST, request.FILES)
            if release_form.is_valid():
                release_form.save()
                messages.success(request, "Release document uploaded.")
                return redirect("organization_settings")
            messages.error(request, "Could not upload the release document.")
        elif form_type == "delete_release":
            # Admin check already done by @admin_required decorator
            doc_id = request.POST.get("document_id")
            document = get_object_or_404(ReleaseDocument, pk=doc_id)
            document.delete()
            messages.success(request, f"Deleted {document.name}.")
            return redirect("organization_settings")
        else:
            form = OrganizationSettingsForm(
                request.POST, request.FILES, instance=settings_instance
            )
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
        {
            "form": form,
            "settings_instance": settings_instance,
            "release_form": release_form,
            "release_documents": release_documents,
        },
    )


@admin_required
def settings_home(request):

    settings_instance = OrganizationSettings.load()
    settings_sections = [
        {
            "title": "Organization Identity",
            "description": "Logo, name, and contact details used across public pages.",
            "url": "organization_settings",
            "accent": True,
        },
        {
            "title": "People Defaults",
            "description": "Coming soon: customize statuses, workflows, and intake forms.",
            "url": None,
            "accent": False,
        },
        {
            "title": "Events & Registrations",
            "description": "Coming soon: configure policies, reminders, and embed themes.",
            "url": None,
            "accent": False,
        },
    ]
    return render(
        request,
        "core/settings_home.html",
        {
            "settings_sections": settings_sections,
            "settings_instance": settings_instance,
        },
    )


# ---------------------------------------------------------------------------
# User Management
# ---------------------------------------------------------------------------

@admin_required
def user_list(request):
    users = (
        User.objects.all()
        .select_related("profile")
        .order_by("first_name", "last_name", "username")
    )
    return render(request, "core/user_list.html", {"users": users})


@admin_required
def user_create(request):
    if request.method == "POST":
        form = CreateUserForm(request.POST)
        if form.is_valid():
            user = User.objects.create_user(
                username=form.cleaned_data["username"],
                first_name=form.cleaned_data["first_name"],
                last_name=form.cleaned_data["last_name"],
                email=form.cleaned_data.get("email", ""),
                password=form.cleaned_data["password"],
            )
            profile, _ = UserProfile.objects.get_or_create(user=user)
            profile.role = form.cleaned_data["role"]
            profile.save(update_fields=["role"])
            messages.success(request, f"User '{user.get_full_name() or user.username}' created successfully.")
            return redirect("user_list")
    else:
        form = CreateUserForm()
    return render(request, "core/user_form.html", {"form": form, "title": "Add User"})


@admin_required
def user_edit(request, user_id):
    target_user = get_object_or_404(User, pk=user_id)
    profile, _ = UserProfile.objects.get_or_create(user=target_user)

    if request.method == "POST":
        form = EditUserForm(request.POST, instance=target_user)
        if form.is_valid():
            form.save()
            profile.role = form.cleaned_data["role"]
            profile.can_manage_communications = form.cleaned_data.get("can_manage_communications", False)
            profile.save(update_fields=["role", "can_manage_communications"])
            messages.success(request, "User updated.")
            return redirect("user_list")
    else:
        form = EditUserForm(instance=target_user)

    return render(request, "core/user_form.html", {
        "form": form,
        "title": f"Edit {target_user.get_full_name() or target_user.username}",
        "target_user": target_user,
    })


@admin_required
def user_set_password(request, user_id):
    target_user = get_object_or_404(User, pk=user_id)

    if request.method == "POST":
        form = SetPasswordForm(request.POST)
        if form.is_valid():
            target_user.set_password(form.cleaned_data["new_password"])
            target_user.save()
            messages.success(request, f"Password updated for {target_user.get_full_name() or target_user.username}.")
            return redirect("user_list")
    else:
        form = SetPasswordForm()

    return render(request, "core/user_set_password.html", {
        "form": form,
        "target_user": target_user,
    })
