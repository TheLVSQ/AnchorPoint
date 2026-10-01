# Google SSO Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add "Sign in with Google" to the login page, restricted to `@bolivar.church` emails that match an existing AnchorPoint user account.

**Architecture:** Google Identity Services renders the button and POSTs a signed JWT to `/auth/google/`. The server verifies the JWT using `google-auth`, enforces the domain restriction, matches the email to an existing Django user, and logs them in. No redirects, no stored tokens, no migrations.

**Tech Stack:** Django 5.2, `google-auth` (JWT verification), Google Identity Services JS (button rendering)

**Design Spec:** `docs/superpowers/specs/2026-05-06-google-sso-design.md`

---

## File Structure

### Modified Files
- `docker/requirements.txt` — add `google-auth`
- `anchorpoint/anchorpoint/settings.py` — add `GOOGLE_CLIENT_ID`
- `anchorpoint/anchorpoint/urls.py` — add `auth/google/` URL
- `anchorpoint/core/views.py` — add `google_auth_callback`, update `login_view`
- `anchorpoint/templates/core/login.html` — add GIS script, button, divider
- `.env.production.example` — document `GOOGLE_CLIENT_ID`
- `anchorpoint/core/tests.py` — add `GoogleAuthCallbackTests`

---

## Task 1: Dependency, Settings, and URL Wiring

**Files:**
- Modify: `docker/requirements.txt`
- Modify: `anchorpoint/anchorpoint/settings.py`
- Modify: `anchorpoint/anchorpoint/urls.py`
- Modify: `.env.production.example`

- [ ] **Step 1: Add `google-auth` to requirements**

In `docker/requirements.txt`, add after the existing Django packages:

```
google-auth==2.40.1
```

- [ ] **Step 2: Add `GOOGLE_CLIENT_ID` to settings**

In `anchorpoint/anchorpoint/settings.py`, add after the `SECRET_KEY` block (around line 32):

```python
# Google SSO
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
```

- [ ] **Step 3: Add the callback URL**

In `anchorpoint/anchorpoint/urls.py`, add this path **before** the `register/` path:

```python
path("auth/google/", core_views.google_auth_callback, name="google_auth"),
```

The full `urlpatterns` list after this change:

```python
urlpatterns = [
    path("health/", health_check, name="health_check"),
    path("admin/", admin.site.urls),
    path("login/", core_views.login_view, name="login"),
    path("logout/", core_views.logout_view, name="logout"),
    path("auth/google/", core_views.google_auth_callback, name="google_auth"),
    path("", core_views.dashboard, name="dashboard"),
    path("profile/", core_views.profile, name="profile"),
    path("permissions/roles/", core_views.manage_roles, name="manage_roles"),
    path("users/", core_views.user_list, name="user_list"),
    path("users/new/", core_views.user_create, name="user_create"),
    path("users/<int:user_id>/edit/", core_views.user_edit, name="user_edit"),
    path("users/<int:user_id>/password/", core_views.user_set_password, name="user_set_password"),
    path("settings/", core_views.settings_home, name="settings_home"),
    path(
        "settings/organization/",
        core_views.organization_settings,
        name="organization_settings",
    ),
    path("people/", include("people.urls")),
    path("groups/", include("groups.urls")),
    path("events/", include("events.urls")),
    path("communications/", include(("messaging.urls", "messaging"), namespace="messaging")),
    path("checkin/", include(("checkin.urls", "checkin"), namespace="checkin")),
    path(
        "register/<uuid:registration_token>/",
        event_views.public_event_register,
        name="event_register",
    ),
]
```

- [ ] **Step 4: Document in `.env.production.example`**

Add after the Twilio block in `.env.production.example`:

```
# Google SSO (optional - enables "Sign in with Google" on the login page)
# Create a Web Application OAuth 2.0 client ID in GCP Console
# Authorized JavaScript origins: https://anchorpoint.bolivar.church
# Authorized redirect URIs: https://anchorpoint.bolivar.church/auth/google/
# GOOGLE_CLIENT_ID=
```

- [ ] **Step 5: Run system check**

```bash
cd anchorpoint && SECRET_KEY=devsecret DB_HOST=localhost ../venv/Scripts/python.exe manage.py check
```
Expected: `System check identified no issues (0 silenced).`

- [ ] **Step 6: Commit**

```bash
git add docker/requirements.txt anchorpoint/anchorpoint/settings.py anchorpoint/anchorpoint/urls.py .env.production.example
git commit -m "feat: wire up Google SSO dependency, setting, and URL"
```

---

## Task 2: Google Auth Callback View + Tests

**Files:**
- Modify: `anchorpoint/core/views.py`
- Modify: `anchorpoint/core/tests.py`

- [ ] **Step 1: Write the failing tests**

Add this import block and test class to `anchorpoint/core/tests.py` (after the existing imports):

```python
from unittest.mock import patch
from django.test import override_settings
```

Add the test class at the end of `anchorpoint/core/tests.py`:

```python
@override_settings(GOOGLE_CLIENT_ID="test-client-id-123")
class GoogleAuthCallbackTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="jsmith",
            email="jsmith@bolivar.church",
            password="unused",
        )
        self.url = reverse("google_auth")

    def _post(self, credential="fake-jwt"):
        return self.client.post(self.url, {"credential": credential})

    def _mock_verify(self, email="jsmith@bolivar.church"):
        """Return a patch context that makes verify_oauth2_token return a valid payload."""
        return patch(
            "core.views.id_token.verify_oauth2_token",
            return_value={"email": email, "email_verified": True},
        )

    def test_valid_credential_logs_in_and_redirects(self):
        with self._mock_verify():
            response = self._post()
        self.assertRedirects(response, reverse("dashboard"))
        # User is now authenticated
        response2 = self.client.get(reverse("dashboard"))
        self.assertEqual(response2.status_code, 200)

    def test_wrong_domain_rejected(self):
        with self._mock_verify(email="hacker@gmail.com"):
            response = self._post()
        self.assertRedirects(response, reverse("login"))
        # Not logged in
        self.assertFalse(self.client.session.get("_auth_user_id"))

    def test_no_matching_user_rejected(self):
        with self._mock_verify(email="unknown@bolivar.church"):
            response = self._post()
        self.assertRedirects(response, reverse("login"))
        self.assertFalse(self.client.session.get("_auth_user_id"))

    def test_invalid_jwt_rejected(self):
        with patch(
            "core.views.id_token.verify_oauth2_token",
            side_effect=ValueError("bad token"),
        ):
            response = self._post()
        self.assertRedirects(response, reverse("login"))
        self.assertFalse(self.client.session.get("_auth_user_id"))

    def test_missing_credential_rejected(self):
        response = self.client.post(self.url, {})
        self.assertRedirects(response, reverse("login"))

    def test_get_request_redirects_to_login(self):
        response = self.client.get(self.url)
        self.assertRedirects(response, reverse("login"))

    def test_unconfigured_client_id_rejected(self):
        with override_settings(GOOGLE_CLIENT_ID=""):
            response = self._post()
        self.assertRedirects(response, reverse("login"))

    def test_email_match_is_case_insensitive(self):
        with self._mock_verify(email="JSMITH@BOLIVAR.CHURCH"):
            response = self._post()
        self.assertRedirects(response, reverse("dashboard"))
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd anchorpoint && SECRET_KEY=devsecret DB_HOST=localhost ../venv/Scripts/python.exe manage.py test core.tests.GoogleAuthCallbackTests -v2
```
Expected: FAIL — `NoReverseMatch` or `AttributeError: module 'core.views' has no attribute 'google_auth_callback'`

- [ ] **Step 3: Add the callback view to `core/views.py`**

Add these imports at the top of `anchorpoint/core/views.py`, after the existing imports:

```python
from django.conf import settings
from django.views.decorators.csrf import csrf_exempt
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests
```

Add this view at the end of `anchorpoint/core/views.py` (after `logout_view`):

```python
@csrf_exempt
def google_auth_callback(request):
    """
    Receives the signed JWT from Google Identity Services and logs the user in.
    CSRF is intentionally exempt — the JWT cryptographic signature is the security mechanism.
    Restricted to @bolivar.church emails that match an existing AnchorPoint user.
    """
    if request.method != "POST":
        return redirect("login")

    credential = request.POST.get("credential", "")
    client_id = settings.GOOGLE_CLIENT_ID

    if not credential or not client_id:
        messages.error(request, "Google sign-in is not available.")
        return redirect("login")

    try:
        idinfo = id_token.verify_oauth2_token(
            credential,
            google_requests.Request(),
            client_id,
        )
    except ValueError:
        messages.error(request, "Google sign-in failed. Please try again.")
        return redirect("login")

    email = idinfo.get("email", "").lower()

    if not email.endswith("@bolivar.church"):
        messages.error(request, "Only @bolivar.church accounts may sign in with Google.")
        return redirect("login")

    UserModel = get_user_model()
    try:
        user = UserModel.objects.get(email__iexact=email)
    except UserModel.DoesNotExist:
        messages.error(
            request,
            "No AnchorPoint account found for this Google account. "
            "Contact your administrator.",
        )
        return redirect("login")

    login(request, user, backend="django.contrib.auth.backends.ModelBackend")
    return redirect("dashboard")
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd anchorpoint && SECRET_KEY=devsecret DB_HOST=localhost ../venv/Scripts/python.exe manage.py test core.tests.GoogleAuthCallbackTests -v2
```
Expected: All 8 tests PASS

- [ ] **Step 5: Run full core test suite to check for regressions**

```bash
cd anchorpoint && SECRET_KEY=devsecret DB_HOST=localhost ../venv/Scripts/python.exe manage.py test core -v2
```
Expected: All tests PASS

- [ ] **Step 6: Commit**

```bash
git add anchorpoint/core/views.py anchorpoint/core/tests.py
git commit -m "feat: add Google SSO callback view

Verifies JWT from Google Identity Services, enforces @bolivar.church
domain restriction, and logs in matching existing users. Rejects
unknown emails, wrong domain, invalid tokens, and unconfigured client ID."
```

---

## Task 3: Update Login Page

**Files:**
- Modify: `anchorpoint/core/views.py` (update `login_view` context)
- Modify: `anchorpoint/templates/core/login.html`
- Modify: `anchorpoint/core/tests.py` (add login page tests)

- [ ] **Step 1: Write the failing tests**

Add this test class to `anchorpoint/core/tests.py`:

```python
class LoginPageTests(TestCase):
    @override_settings(GOOGLE_CLIENT_ID="test-client-id-123")
    def test_login_page_shows_google_button_when_configured(self):
        response = self.client.get(reverse("login"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "g_id_signin")
        self.assertContains(response, "test-client-id-123")

    @override_settings(GOOGLE_CLIENT_ID="")
    def test_login_page_hides_google_button_when_not_configured(self):
        response = self.client.get(reverse("login"))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "g_id_signin")

    def test_login_page_always_shows_password_form(self):
        response = self.client.get(reverse("login"))
        self.assertContains(response, 'name="username"')
        self.assertContains(response, 'name="password"')
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd anchorpoint && SECRET_KEY=devsecret DB_HOST=localhost ../venv/Scripts/python.exe manage.py test core.tests.LoginPageTests -v2
```
Expected: FAIL — `google_client_id` not in template context, `g_id_signin` not found

- [ ] **Step 3: Update `login_view` to pass `google_client_id`**

In `anchorpoint/core/views.py`, replace:

```python
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
```

with:

```python
def login_view(request):
    if request.user.is_authenticated:
        return redirect("dashboard")

    if request.method == "POST":
        username = request.POST.get("username")
        password = request.POST.get("password")
        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            return redirect("dashboard")
        else:
            messages.error(request, "Invalid username or password.")

    return render(request, "core/login.html", {
        "google_client_id": settings.GOOGLE_CLIENT_ID,
    })
```

- [ ] **Step 4: Replace `login.html` with the updated template**

Replace the full contents of `anchorpoint/templates/core/login.html`:

```html
{% extends "base.html" %}

{% block content %}
<div class="container" style="max-width:420px;margin:4rem auto;">

    <h1 style="text-align:center;margin-bottom:2rem;">AnchorPoint</h1>

    {% if messages %}
        {% for message in messages %}
            <div class="message {{ message.tags }}">{{ message }}</div>
        {% endfor %}
    {% endif %}

    {% if google_client_id %}
        <script src="https://accounts.google.com/gsi/client" async defer></script>

        <div id="g_id_onload"
             data-client_id="{{ google_client_id }}"
             data-ux_mode="redirect"
             data-login_uri="{% url 'google_auth' %}"
             data-auto_prompt="false">
        </div>

        <div class="g_id_signin"
             data-type="standard"
             data-size="large"
             data-theme="outline"
             data-text="sign_in_with"
             data-shape="rectangular"
             data-width="360"
             style="display:flex;justify-content:center;margin-bottom:1.5rem;">
        </div>

        <div style="display:flex;align-items:center;gap:1rem;margin-bottom:1.5rem;">
            <hr style="flex:1;border:none;border-top:1px solid var(--gray-200);">
            <span class="muted-text" style="font-size:0.85rem;white-space:nowrap;">or sign in with username</span>
            <hr style="flex:1;border:none;border-top:1px solid var(--gray-200);">
        </div>
    {% endif %}

    <form method="POST">
        {% csrf_token %}

        <div class="form-field">
            <label for="username">Username</label>
            <input id="username" type="text" name="username" required autocomplete="username">
        </div>

        <div class="form-field">
            <label for="password">Password</label>
            <input id="password" type="password" name="password" required autocomplete="current-password">
        </div>

        <button type="submit" class="btn" style="width:100%;margin-top:1rem;">Log In</button>
    </form>

</div>
{% endblock %}
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
cd anchorpoint && SECRET_KEY=devsecret DB_HOST=localhost ../venv/Scripts/python.exe manage.py test core.tests.LoginPageTests -v2
```
Expected: All 3 tests PASS

- [ ] **Step 6: Run full core test suite**

```bash
cd anchorpoint && SECRET_KEY=devsecret DB_HOST=localhost ../venv/Scripts/python.exe manage.py test core -v2
```
Expected: All tests PASS

- [ ] **Step 7: Run system check**

```bash
cd anchorpoint && SECRET_KEY=devsecret DB_HOST=localhost ../venv/Scripts/python.exe manage.py check
```
Expected: `System check identified no issues (0 silenced).`

- [ ] **Step 8: Commit**

```bash
git add anchorpoint/core/views.py anchorpoint/templates/core/login.html anchorpoint/core/tests.py
git commit -m "feat: add Google Sign-In button to login page

Shows Google SSO button above the username/password form when
GOOGLE_CLIENT_ID is configured. Hidden when not configured so
password login continues to work without any env var set."
```
