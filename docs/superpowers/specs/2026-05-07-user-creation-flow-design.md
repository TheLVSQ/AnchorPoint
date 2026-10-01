# User Creation Flow Redesign — Design Spec

## Overview

Three connected improvements to how AnchorPoint user accounts are created and managed:

1. **Email as login identifier** — remove the username field from user creation; email becomes the login credential
2. **Live Person match check** — HTMX fires when the admin types an email on the add user form, showing a matched Person record with a link confirmation checkbox
3. **UserProfile → Person link** — a nullable FK from `UserProfile` to `Person` records the association when confirmed

## Scope

- `user_create` form and view
- `login_view` (email lookup)
- `UserProfile` model (new FK)
- Login template label
- One new HTMX endpoint

Not in scope: editing existing users to change their email/login, bulk-linking existing User/Person records.

## Architecture

No custom User model changes. Django's `username` field stays in the database but is auto-set to the email on creation — zero migrations on auth tables, no disruption to existing sessions or the Google SSO flow.

`login_view` looks up users by email (`User.objects.filter(email__iexact=email).first()`) and verifies password with `user.check_password()` rather than Django's `authenticate()`. This is equivalent but email-keyed.

Existing users (admin, beta testers) already have email set so login continues to work unchanged. Google SSO already uses email lookup — this change aligns the password flow with it.

## Email as Login

### `CreateUserForm` changes
- Remove `username` field entirely
- Make `email` a required `EmailField`
- Add `clean_email`: raises `ValidationError` if `User.objects.filter(email__iexact=email).exists()`
- Keep: `first_name`, `last_name`, `role`, `password`, `confirm_password`

### `user_create` view changes
```python
user = User.objects.create_user(
    username=form.cleaned_data["email"],   # username = email
    email=form.cleaned_data["email"],
    first_name=form.cleaned_data["first_name"],
    last_name=form.cleaned_data["last_name"],
    password=form.cleaned_data["password"],
)
# If admin confirmed person link (checkbox value is the person PK):
link_person_id = request.POST.get("link_person")
if link_person_id:
    try:
        profile.person = Person.objects.get(pk=link_person_id)
        profile.save(update_fields=["role", "person"])
    except Person.DoesNotExist:
        pass  # silently skip stale ID
```

### `login_view` changes
Replace `authenticate(request, username=username, password=password)` with:
```python
email = request.POST.get("username", "").strip().lower()
try:
    user = User.objects.get(email__iexact=email)
except User.DoesNotExist:
    user = None

if user is not None and user.check_password(password) and user.is_active:
    login(request, user, backend="django.contrib.auth.backends.ModelBackend")
    return redirect("dashboard")
else:
    messages.error(request, "Invalid email or password.")
```

Login template: change `<label for="username">` to `Email`, change `autocomplete="username"` to `autocomplete="email"`, change `type="text"` to `type="email"`.

## Live Person Match (HTMX)

### New endpoint
**URL:** `GET /users/person-check/?email=<email>`  
**View:** `user_person_check` in `core/views.py`  
**Permission:** `@admin_required`  
**Template:** `core/templates/core/partials/person_match.html`

Logic:
```python
email = request.GET.get("email", "").strip()
if not email:
    return HttpResponse("")
person = Person.objects.filter(email__iexact=email).first()
if not person:
    return HttpResponse("")
return render(request, "core/partials/person_match.html", {"person": person})
```

### Person match partial (`person_match.html`)
```html
<div class="detail-card" style="background:var(--blue-50);border:1px solid var(--blue-200);padding:1rem;margin-top:0.5rem;">
    <p><strong>Person record found:</strong> {{ person.first_name }} {{ person.last_name }}</p>
    <label style="display:flex;align-items:center;gap:0.5rem;margin-top:0.5rem;">
        <input type="checkbox" name="link_person" value="{{ person.pk }}" checked>
        Link this user account to {{ person.first_name }}'s Person record
    </label>
</div>
```

The checkbox `value` is the Person PK. When checked, `request.POST.get("link_person")` returns the PK string directly — no hidden field or JS needed.

### Email field HTMX wiring
```html
<input type="email" name="email"
       hx-get="{% url 'user_person_check' %}"
       hx-trigger="change, keyup changed delay:500ms"
       hx-target="#person-match"
       hx-include="[name='email']">
<div id="person-match"></div>
```

## UserProfile → Person Link

```python
# core/models.py
person = models.OneToOneField(
    "people.Person",
    null=True,
    blank=True,
    on_delete=models.SET_NULL,
    related_name="user_profile",
)
```

One new migration. The link is optional — users without a Person record work normally. `OneToOneField` ensures one user per person maximum.

## Files Changed

| File | Change |
|------|--------|
| `core/models.py` | Add `person` OneToOneField to `UserProfile` |
| `core/migrations/` | New migration for `UserProfile.person` |
| `core/forms.py` | `CreateUserForm`: remove username, email required + uniqueness, add `link_person_id` hidden field |
| `core/views.py` | Update `login_view` (email lookup), `user_create` (username=email, person link), add `user_person_check` |
| `anchorpoint/anchorpoint/urls.py` | Add `path("users/person-check/", ...)` |
| `anchorpoint/templates/core/login.html` | Label/type/autocomplete for email |
| `core/templates/core/user_form.html` | HTMX on email field, `#person-match` div, remove username field |
| `core/templates/core/partials/person_match.html` | New HTMX partial |

## Security

- `user_person_check` is `@admin_required` — only admins can probe Person records by email
- `link_person_id` is validated with `Person.objects.get(pk=...)` — stale/forged IDs are silently ignored
- `login_view` uses `user.check_password()` which is bcrypt — same security as `authenticate()`
- `user.is_active` is checked before login — disabled accounts cannot log in

## Testing

- `login_view`: valid email+password → logged in; wrong password → error; unknown email → error; inactive user → error
- `CreateUserForm`: email required; duplicate email rejected; `link_person_id` passes through
- `user_create`: username auto-set to email; person linked when `link_person_id` valid; stale person ID silently skipped
- `user_person_check`: match found → partial rendered; no match → empty; no email → empty
- Existing users with email set can still log in after the change
