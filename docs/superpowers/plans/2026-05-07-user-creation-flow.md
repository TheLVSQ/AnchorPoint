# User Creation Flow Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace username-based login with email, make email required on user creation, show a live Person-match panel when an email is typed, and optionally link the new User to an existing Person record.

**Architecture:** No custom User model changes — `username` stays in the DB but is auto-set to the user's email on creation. `login_view` looks up by `email__iexact` instead of calling `authenticate()`. A nullable `OneToOneField` on `UserProfile` stores the Person link. An HTMX endpoint fires on the email field's `change` event and returns a match partial with a link checkbox.

**Tech Stack:** Django 5.2, HTMX (existing), Django migrations

**Design Spec:** `docs/superpowers/specs/2026-05-07-user-creation-flow-design.md`

---

## File Structure

### Modified Files
- `anchorpoint/core/models.py` — add `person` OneToOneField to `UserProfile`
- `anchorpoint/core/migrations/0008_userprofile_person.py` — generated migration
- `anchorpoint/core/forms.py` — `CreateUserForm`: remove username, email required + unique
- `anchorpoint/core/views.py` — update `login_view`, `user_create`; add `user_person_check`
- `anchorpoint/anchorpoint/urls.py` — add `/users/person-check/` URL
- `anchorpoint/templates/core/login.html` — label/type for email
- `anchorpoint/core/templates/core/user_form.html` — remove username field, add HTMX email, person-match div
- `anchorpoint/core/tests.py` — new test classes

### New Files
- `anchorpoint/core/templates/core/partials/person_match.html` — HTMX partial

---

## Task 1: UserProfile → Person Link (Model + Migration)

**Files:**
- Modify: `anchorpoint/core/models.py`
- Create: `anchorpoint/core/migrations/0008_userprofile_person.py` (generated)
- Modify: `anchorpoint/core/tests.py`

- [ ] **Step 1: Write the failing test**

Add to `anchorpoint/core/tests.py`:

```python
class UserProfilePersonLinkTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username="linktest", password="pw")
        self.person = Person.objects.create(
            first_name="Jane", last_name="Doe", phone="+15550001111"
        )

    def test_profile_person_defaults_to_null(self):
        self.assertIsNone(self.user.profile.person)

    def test_profile_can_be_linked_to_person(self):
        self.user.profile.person = self.person
        self.user.profile.save()
        self.user.profile.refresh_from_db()
        self.assertEqual(self.user.profile.person, self.person)

    def test_person_link_cleared_on_person_delete(self):
        self.user.profile.person = self.person
        self.user.profile.save()
        self.person.delete()
        self.user.profile.refresh_from_db()
        self.assertIsNone(self.user.profile.person)
```

Also add `from people.models import Person` to the imports at the top of `anchorpoint/core/tests.py`.

- [ ] **Step 2: Run test to verify it fails**

```bash
cd anchorpoint && SECRET_KEY=devsecret DB_HOST=localhost ../venv/Scripts/python.exe manage.py test core.tests.UserProfilePersonLinkTests -v2
```
Expected: FAIL — `AttributeError: 'UserProfile' object has no attribute 'person'`

- [ ] **Step 3: Add the `person` field to `UserProfile`**

In `anchorpoint/core/models.py`, add after `can_manage_communications`:

```python
    person = models.OneToOneField(
        "people.Person",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="user_profile",
    )
```

- [ ] **Step 4: Generate the migration**

```bash
cd anchorpoint && SECRET_KEY=devsecret DB_HOST=localhost ../venv/Scripts/python.exe manage.py makemigrations core --name="userprofile_person_link"
```
Expected: `Migrations for 'core': core/migrations/0008_userprofile_person_link.py`

- [ ] **Step 5: Run test to verify it passes**

```bash
cd anchorpoint && SECRET_KEY=devsecret DB_HOST=localhost ../venv/Scripts/python.exe manage.py test core.tests.UserProfilePersonLinkTests -v2
```
Expected: All 3 tests PASS

- [ ] **Step 6: Commit**

```bash
git add anchorpoint/core/models.py anchorpoint/core/migrations/0008_userprofile_person_link.py anchorpoint/core/tests.py
git commit -m "feat: add nullable person link to UserProfile"
```

---

## Task 2: Email-Based Login

**Files:**
- Modify: `anchorpoint/core/views.py`
- Modify: `anchorpoint/templates/core/login.html`
- Modify: `anchorpoint/core/tests.py`

- [ ] **Step 1: Write the failing tests**

Add to `anchorpoint/core/tests.py`:

```python
class EmailLoginTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(
            username="jdoe@bolivar.church",
            email="jdoe@bolivar.church",
            password="securepass123",
            first_name="Jane",
            last_name="Doe",
        )

    def test_login_with_email_succeeds(self):
        response = self.client.post(reverse("login"), {
            "username": "jdoe@bolivar.church",
            "password": "securepass123",
        })
        self.assertRedirects(response, reverse("dashboard"))

    def test_login_with_wrong_password_fails(self):
        response = self.client.post(reverse("login"), {
            "username": "jdoe@bolivar.church",
            "password": "wrongpassword",
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(self.client.session.get("_auth_user_id"))

    def test_login_with_unknown_email_fails(self):
        response = self.client.post(reverse("login"), {
            "username": "nobody@bolivar.church",
            "password": "securepass123",
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(self.client.session.get("_auth_user_id"))

    def test_login_with_inactive_user_fails(self):
        self.user.is_active = False
        self.user.save()
        response = self.client.post(reverse("login"), {
            "username": "jdoe@bolivar.church",
            "password": "securepass123",
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(self.client.session.get("_auth_user_id"))

    def test_login_page_shows_email_input(self):
        response = self.client.get(reverse("login"))
        self.assertContains(response, 'type="email"')
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd anchorpoint && SECRET_KEY=devsecret DB_HOST=localhost ../venv/Scripts/python.exe manage.py test core.tests.EmailLoginTests -v2
```
Expected: Several FAIL — login currently uses `authenticate(username=...)` not email lookup, and login template uses `type="text"`

- [ ] **Step 3: Update `login_view` in `core/views.py`**

Replace the `login_view` function:

```python
def login_view(request):
    if request.user.is_authenticated:
        return redirect("dashboard")

    if request.method == "POST":
        email = request.POST.get("username", "").strip()
        password = request.POST.get("password", "")
        try:
            user = User.objects.get(email__iexact=email)
        except User.DoesNotExist:
            user = None

        if user is not None and user.check_password(password) and user.is_active:
            login(request, user, backend="django.contrib.auth.backends.ModelBackend")
            return redirect("dashboard")
        else:
            messages.error(request, "Invalid email or password.")

    return render(request, "core/login.html", {
        "google_client_id": settings.GOOGLE_CLIENT_ID,
    })
```

- [ ] **Step 4: Update login template**

In `anchorpoint/templates/core/login.html`, replace the username input block:

```html
        <div class="form-field">
            <label for="username">Email</label>
            <input id="username" type="email" name="username" required autocomplete="email">
        </div>
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
cd anchorpoint && SECRET_KEY=devsecret DB_HOST=localhost ../venv/Scripts/python.exe manage.py test core.tests.EmailLoginTests -v2
```
Expected: All 5 tests PASS

- [ ] **Step 6: Commit**

```bash
git add anchorpoint/core/views.py anchorpoint/templates/core/login.html anchorpoint/core/tests.py
git commit -m "feat: use email for login instead of username"
```

---

## Task 3: CreateUserForm + user_create View

**Files:**
- Modify: `anchorpoint/core/forms.py`
- Modify: `anchorpoint/core/views.py`
- Modify: `anchorpoint/core/templates/core/user_form.html`
- Modify: `anchorpoint/core/tests.py`

- [ ] **Step 1: Write the failing tests**

Add to `anchorpoint/core/tests.py`:

```python
class CreateUserFormEmailTests(TestCase):
    def setUp(self):
        User = get_user_model()
        User.objects.create_user(
            username="existing@example.com",
            email="existing@example.com",
            password="pw",
        )

    def _valid_data(self, email="new@example.com"):
        return {
            "first_name": "Jane",
            "last_name": "Doe",
            "email": email,
            "role": "staff",
            "password": "securepass123",
            "confirm_password": "securepass123",
        }

    def test_email_required(self):
        from core.forms import CreateUserForm
        data = self._valid_data()
        data["email"] = ""
        form = CreateUserForm(data)
        self.assertFalse(form.is_valid())
        self.assertIn("email", form.errors)

    def test_duplicate_email_rejected(self):
        from core.forms import CreateUserForm
        form = CreateUserForm(self._valid_data(email="existing@example.com"))
        self.assertFalse(form.is_valid())
        self.assertIn("email", form.errors)

    def test_valid_form_has_no_username_field(self):
        from core.forms import CreateUserForm
        form = CreateUserForm(self._valid_data())
        self.assertNotIn("username", form.fields)

    def test_password_mismatch_rejected(self):
        from core.forms import CreateUserForm
        data = self._valid_data()
        data["confirm_password"] = "different"
        form = CreateUserForm(data)
        self.assertFalse(form.is_valid())


class UserCreateViewEmailTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_user(username="admin", password="pw")
        self.admin.profile.role = UserProfile.Role.ADMIN
        self.admin.profile.save()
        self.client.force_login(self.admin)

    def _post(self, email="newuser@example.com"):
        return self.client.post(reverse("user_create"), {
            "first_name": "New",
            "last_name": "User",
            "email": email,
            "role": "staff",
            "password": "securepass123",
            "confirm_password": "securepass123",
        })

    def test_creates_user_with_email_as_username(self):
        self._post(email="staff@example.com")
        User = get_user_model()
        user = User.objects.get(email="staff@example.com")
        self.assertEqual(user.username, "staff@example.com")

    def test_redirects_to_user_list_on_success(self):
        response = self._post()
        self.assertRedirects(response, reverse("user_list"))

    def test_duplicate_email_shows_form_error(self):
        self._post(email="dup@example.com")
        response = self._post(email="dup@example.com")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "already exists")
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd anchorpoint && SECRET_KEY=devsecret DB_HOST=localhost ../venv/Scripts/python.exe manage.py test core.tests.CreateUserFormEmailTests core.tests.UserCreateViewEmailTests -v2
```
Expected: FAIL — form still has `username` field, email is not required

- [ ] **Step 3: Replace `CreateUserForm` in `core/forms.py`**

Replace the `CreateUserForm` class:

```python
class CreateUserForm(forms.Form):
    first_name = forms.CharField(max_length=150)
    last_name = forms.CharField(max_length=150)
    email = forms.EmailField(label="Email address")
    role = forms.ChoiceField(choices=UserProfile.Role.choices)
    password = forms.CharField(widget=forms.PasswordInput, min_length=8)
    confirm_password = forms.CharField(widget=forms.PasswordInput, label="Confirm password")

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("A user with that email already exists.")
        return email

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("password") != cleaned.get("confirm_password"):
            self.add_error("confirm_password", "Passwords do not match.")
        return cleaned
```

- [ ] **Step 4: Update `user_create` in `core/views.py`**

Replace the `user_create` function:

```python
@admin_required
def user_create(request):
    if request.method == "POST":
        form = CreateUserForm(request.POST)
        if form.is_valid():
            email = form.cleaned_data["email"]
            user = User.objects.create_user(
                username=email,
                email=email,
                first_name=form.cleaned_data["first_name"],
                last_name=form.cleaned_data["last_name"],
                password=form.cleaned_data["password"],
            )
            profile, _ = UserProfile.objects.get_or_create(user=user)
            profile.role = form.cleaned_data["role"]

            link_person_id = request.POST.get("link_person")
            if link_person_id:
                try:
                    profile.person = Person.objects.get(pk=link_person_id)
                except Person.DoesNotExist:
                    pass

            profile.save(update_fields=["role", "person"])
            messages.success(request, f"User '{user.get_full_name() or email}' created successfully.")
            return redirect("user_list")
        messages.error(request, "Please fix the errors below.")
    else:
        form = CreateUserForm()
    return render(request, "core/user_form.html", {"form": form, "title": "Add User"})
```

Also ensure `Person` is imported at the top of `core/views.py` — it's already there:
```python
from people.models import Person
```

- [ ] **Step 5: Update `user_form.html` — remove username, update email field**

Replace the full contents of `anchorpoint/core/templates/core/user_form.html`:

```html
{% extends "base.html" %}
{% block content %}

<a class="ghost-link" href="{% url 'user_list' %}">&larr; Back to Users</a>

<div class="page-header" style="margin-top: 1rem;">
    <h1>{{ title }}</h1>
</div>

<div class="detail-card" style="max-width: 560px;">
    <form method="post" autocomplete="off">
        {% csrf_token %}

        <div class="form-grid">
            <div class="form-field">
                <label>First Name</label>
                {{ form.first_name }}
                {% for e in form.first_name.errors %}<span class="error-text">{{ e }}</span>{% endfor %}
            </div>
            <div class="form-field">
                <label>Last Name</label>
                {{ form.last_name }}
                {% for e in form.last_name.errors %}<span class="error-text">{{ e }}</span>{% endfor %}
            </div>
        </div>

        <div class="form-field">
            <label>Email address</label>
            {% if not target_user %}
                <input type="email" name="email"
                       value="{{ form.email.value|default:'' }}"
                       autocomplete="email"
                       hx-get="{% url 'user_person_check' %}"
                       hx-trigger="change, keyup changed delay:500ms"
                       hx-target="#person-match"
                       hx-include="[name='email']">
            {% else %}
                {{ form.email }}
            {% endif %}
            {% for e in form.email.errors %}<span class="error-text">{{ e }}</span>{% endfor %}
        </div>

        <div id="person-match"></div>

        <div class="form-field">
            <label>Role</label>
            {{ form.role }}
            {% for e in form.role.errors %}<span class="error-text">{{ e }}</span>{% endfor %}
        </div>

        {% if form.can_manage_communications %}
            <div class="form-field">
                <label style="display: flex; align-items: center; gap: 0.5rem; font-weight: 500;">
                    {{ form.can_manage_communications }}
                    Communications access
                </label>
            </div>
        {% endif %}

        {% if form.password %}
            <hr style="margin: 1.5rem 0; border: none; border-top: 1px solid var(--border);">
            <h3 style="margin: 0 0 1rem; font-size: 1rem;">Set Password</h3>

            <div class="form-field">
                <label>Password</label>
                {{ form.password }}
                {% for e in form.password.errors %}<span class="error-text">{{ e }}</span>{% endfor %}
            </div>

            <div class="form-field">
                <label>Confirm Password</label>
                {{ form.confirm_password }}
                {% for e in form.confirm_password.errors %}<span class="error-text">{{ e }}</span>{% endfor %}
            </div>
        {% endif %}

        <div class="hero-actions" style="margin-top: 1.5rem;">
            <button type="submit" class="btn">Save User</button>
            <a href="{% url 'user_list' %}" class="btn ghost">Cancel</a>
        </div>
    </form>
</div>

{% if target_user %}
    <div class="detail-card" style="max-width: 560px; margin-top: 1.5rem;">
        <h2 style="font-size: 1rem; margin-bottom: 1rem;">Password</h2>
        <p class="stat-hint" style="margin-bottom: 1rem;">To change this user's password, use the dedicated password form.</p>
        <a href="{% url 'user_set_password' target_user.pk %}" class="btn ghost">Set New Password</a>
    </div>
{% endif %}

{% endblock %}
```

- [ ] **Step 6: Run tests to verify they pass**

```bash
cd anchorpoint && SECRET_KEY=devsecret DB_HOST=localhost ../venv/Scripts/python.exe manage.py test core.tests.CreateUserFormEmailTests core.tests.UserCreateViewEmailTests -v2
```
Expected: All 7 tests PASS

- [ ] **Step 7: Commit**

```bash
git add anchorpoint/core/forms.py anchorpoint/core/views.py anchorpoint/core/templates/core/user_form.html anchorpoint/core/tests.py
git commit -m "feat: use email as user identifier in create flow

Removes username field from user creation. Email is required and
must be unique. username is auto-set to email on create."
```

---

## Task 4: Person Match HTMX Endpoint + Person Linking

**Files:**
- Modify: `anchorpoint/core/views.py`
- Modify: `anchorpoint/anchorpoint/urls.py`
- Create: `anchorpoint/core/templates/core/partials/person_match.html`
- Modify: `anchorpoint/core/tests.py`

- [ ] **Step 1: Write the failing tests**

Add to `anchorpoint/core/tests.py`:

```python
class UserPersonCheckTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_user(username="admin2", password="pw")
        self.admin.profile.role = UserProfile.Role.ADMIN
        self.admin.profile.save()
        self.client.force_login(self.admin)
        self.person = Person.objects.create(
            first_name="Jane", last_name="Doe",
            email="jane@example.com", phone="+15550001111"
        )

    def test_returns_partial_when_person_found(self):
        response = self.client.get(
            reverse("user_person_check"),
            {"email": "jane@example.com"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Jane")
        self.assertContains(response, "Doe")

    def test_returns_empty_when_no_person(self):
        response = self.client.get(
            reverse("user_person_check"),
            {"email": "nobody@example.com"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content.strip(), b"")

    def test_returns_empty_when_no_email(self):
        response = self.client.get(reverse("user_person_check"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content.strip(), b"")

    def test_requires_admin(self):
        self.client.logout()
        User = get_user_model()
        vol = User.objects.create_user(username="vol", password="pw")
        self.client.force_login(vol)
        response = self.client.get(
            reverse("user_person_check"),
            {"email": "jane@example.com"},
        )
        self.assertNotEqual(response.status_code, 200)


class UserCreatePersonLinkTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_user(username="admin3", password="pw")
        self.admin.profile.role = UserProfile.Role.ADMIN
        self.admin.profile.save()
        self.client.force_login(self.admin)
        self.person = Person.objects.create(
            first_name="Jane", last_name="Doe",
            email="jane@church.com", phone="+15550002222"
        )

    def test_links_person_when_checkbox_checked(self):
        self.client.post(reverse("user_create"), {
            "first_name": "Jane",
            "last_name": "Doe",
            "email": "jane@church.com",
            "role": "staff",
            "password": "securepass123",
            "confirm_password": "securepass123",
            "link_person": str(self.person.pk),
        })
        User = get_user_model()
        user = User.objects.get(email="jane@church.com")
        self.assertEqual(user.profile.person, self.person)

    def test_no_link_when_checkbox_absent(self):
        self.client.post(reverse("user_create"), {
            "first_name": "Jane",
            "last_name": "Doe",
            "email": "jane@church.com",
            "role": "staff",
            "password": "securepass123",
            "confirm_password": "securepass123",
        })
        User = get_user_model()
        user = User.objects.get(email="jane@church.com")
        self.assertIsNone(user.profile.person)

    def test_stale_person_id_silently_ignored(self):
        self.client.post(reverse("user_create"), {
            "first_name": "Jane",
            "last_name": "Doe",
            "email": "jane@church.com",
            "role": "staff",
            "password": "securepass123",
            "confirm_password": "securepass123",
            "link_person": "99999",
        })
        User = get_user_model()
        user = User.objects.get(email="jane@church.com")
        self.assertIsNone(user.profile.person)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd anchorpoint && SECRET_KEY=devsecret DB_HOST=localhost ../venv/Scripts/python.exe manage.py test core.tests.UserPersonCheckTests core.tests.UserCreatePersonLinkTests -v2
```
Expected: FAIL — `NoReverseMatch: Reverse for 'user_person_check' not found`

- [ ] **Step 3: Add `user_person_check` view to `core/views.py`**

Add after the `user_create` function:

```python
@admin_required
def user_person_check(request):
    """HTMX endpoint: returns a person-match partial if an existing Person has this email."""
    email = request.GET.get("email", "").strip()
    if not email:
        return HttpResponse("")
    person = Person.objects.filter(email__iexact=email).first()
    if not person:
        return HttpResponse("")
    return render(request, "core/partials/person_match.html", {"person": person})
```

Add `HttpResponse` to the existing Django imports at the top of `core/views.py`:
```python
from django.http import HttpResponse
```

- [ ] **Step 4: Add URL to `anchorpoint/urls.py`**

Add after the existing `users/new/` path:

```python
path("users/person-check/", core_views.user_person_check, name="user_person_check"),
```

- [ ] **Step 5: Create the person match partial**

Create directory and file `anchorpoint/core/templates/core/partials/person_match.html`:

```html
<div class="detail-card" style="background:#eff6ff;border:1px solid #bfdbfe;padding:1rem;margin-top:0.5rem;border-radius:8px;">
    <p style="margin:0 0 0.5rem;"><strong>Person record found:</strong> {{ person.first_name }} {{ person.last_name }}
    {% if person.email %}<span class="stat-hint"> · {{ person.email }}</span>{% endif %}</p>
    <label style="display:flex;align-items:center;gap:0.5rem;cursor:pointer;">
        <input type="checkbox" name="link_person" value="{{ person.pk }}" checked>
        Link this user account to {{ person.first_name }}'s Person record
    </label>
</div>
```

- [ ] **Step 6: Run tests to verify they pass**

```bash
cd anchorpoint && SECRET_KEY=devsecret DB_HOST=localhost ../venv/Scripts/python.exe manage.py test core.tests.UserPersonCheckTests core.tests.UserCreatePersonLinkTests -v2
```
Expected: All 7 tests PASS

- [ ] **Step 7: Run full core test suite**

```bash
cd anchorpoint && SECRET_KEY=devsecret DB_HOST=localhost ../venv/Scripts/python.exe manage.py test core -v2
```
Expected: All tests PASS

- [ ] **Step 8: Run system check**

```bash
cd anchorpoint && SECRET_KEY=devsecret DB_HOST=localhost ../venv/Scripts/python.exe manage.py check
```
Expected: `System check identified no issues (0 silenced).`

- [ ] **Step 9: Commit**

```bash
git add anchorpoint/core/views.py anchorpoint/anchorpoint/urls.py anchorpoint/core/templates/core/partials/person_match.html anchorpoint/core/tests.py
git commit -m "feat: HTMX person-match panel and person linking on user create

When an admin types an email on the Add User form, the system checks
for a matching Person record and shows a confirmation checkbox.
If checked on submit, the new User's profile is linked to that Person."
```
