# Google SSO — Design Spec

## Overview

Add "Sign in with Google" to the AnchorPoint login page alongside the existing username/password form. Uses Google Identity Services (GIS) for zero-JavaScript authentication — Google posts a signed JWT directly to our server, which verifies it and logs the user in.

**Restrictions:**
- Only `@bolivar.church` email addresses are accepted
- The Google email must match an existing AnchorPoint user's email (case-insensitive)
- No new accounts are created automatically — admin must provision the user first

## Architecture

Google Identity Services renders a "Sign in with Google" button. When clicked, Google authenticates the user in a popup and POSTs a signed JWT credential directly to `/auth/google/` via browser form submit (`data-ux_mode="redirect"`). The server verifies the JWT signature using Google's public keys (via `google-auth` library), enforces the domain restriction, looks up the matching Django user by email, and logs them in via Django's standard `login()`.

No OAuth2 redirect flow. No stored tokens. No new database tables.

## Data Flow

```
User clicks "Sign in with Google"
    → Google popup authenticates user
    → Google POSTs JWT to /auth/google/ (browser form submit)
    → verify JWT signature + audience (google-auth library)
        → invalid JWT → redirect to /login/ with error
    → check email ends in @bolivar.church
        → wrong domain → redirect to /login/ with error message
    → User.objects.get(email__iexact=google_email)
        → no match → redirect to /login/ with "contact administrator" message
    → login(request, user, backend="django.contrib.auth.backends.ModelBackend")
    → redirect to /
```

## Security

- JWT is verified using Google's public keys — cannot be forged
- `aud` (audience) claim must match `GOOGLE_CLIENT_ID` — prevents tokens issued to other apps
- `@csrf_exempt` on the callback view is safe: cryptographic JWT verification replaces CSRF protection (the POST originates from Google's redirect, not a third-party form)
- Domain restriction (`@bolivar.church`) enforced server-side — not bypassable from the client
- Email lookup is case-insensitive (`__iexact`)
- Errors return the same generic redirect to avoid leaking whether an email exists

## New Dependency

```
google-auth
```

Added to `docker/requirements.txt`. Provides `google.oauth2.id_token.verify_oauth2_token()` which fetches Google's public keys and verifies the JWT signature, expiry, issuer, and audience. No `google-auth-oauthlib` needed — we don't do the OAuth2 code flow.

## Environment Variable

`GOOGLE_CLIENT_ID` — the OAuth 2.0 client ID from GCP Console (Web Application type).

- Added to `settings.py` as `GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")`
- Documented in `.env.production.example`
- The client **secret** is not needed for GIS JWT verification

If `GOOGLE_CLIENT_ID` is empty, the Google button is not rendered and username/password continues to work normally. This allows safe deployment before the GCP credentials are configured.

## GCP Setup (for operator reference)

In GCP Console → APIs & Services → Credentials:
1. Create an OAuth 2.0 Client ID (type: Web Application)
2. Add the production URL to "Authorized JavaScript origins": `https://anchorpoint.bolivar.church`
3. Add the callback to "Authorized redirect URIs": `https://anchorpoint.bolivar.church/auth/google/`
4. Copy the Client ID into `GOOGLE_CLIENT_ID` env var (secret not needed)

## Login Page

The existing username/password form is unchanged. Above it:

1. Google's GIS `<script>` tag (loaded async/defer from `https://accounts.google.com/gsi/client`)
2. `<div id="g_id_onload">` with:
   - `data-client_id="{{ google_client_id }}"`
   - `data-ux_mode="redirect"` — browser form-posts the JWT, no custom JS needed
   - `data-login_uri="{% url 'google_auth' %}"` — our callback URL
   - `data-auto_prompt="false"` — don't auto-show the One Tap popup
3. `<div class="g_id_signin">` — Google renders its standard button here
4. A centered "— or —" divider between the Google button and the username/password form

The Google section is wrapped in `{% if google_client_id %}` so it only renders when configured.

## Callback View

**URL:** `POST /auth/google/`  
**View:** `google_auth_callback` in `core/views.py`  
**Decorators:** `@csrf_exempt` (JWT verification is the security mechanism)

```python
@csrf_exempt
def google_auth_callback(request):
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

    User = get_user_model()
    try:
        user = User.objects.get(email__iexact=email)
    except User.DoesNotExist:
        messages.error(request, "No AnchorPoint account found. Contact your administrator.")
        return redirect("login")

    login(request, user, backend="django.contrib.auth.backends.ModelBackend")
    return redirect("dashboard")
```

## Login View Update

`login_view` passes `google_client_id` to the template context:

```python
def login_view(request):
    ...
    return render(request, "core/login.html", {
        "google_client_id": settings.GOOGLE_CLIENT_ID,
    })
```

## Files Changed

| File | Change |
|------|--------|
| `docker/requirements.txt` | Add `google-auth` |
| `anchorpoint/anchorpoint/settings.py` | Add `GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")` |
| `anchorpoint/anchorpoint/urls.py` | Add `path("auth/google/", core_views.google_auth_callback, name="google_auth")` |
| `anchorpoint/core/views.py` | Add `google_auth_callback`, update `login_view` to pass `google_client_id` |
| `anchorpoint/templates/core/login.html` | Add GIS script, Google button, divider |
| `.env.production.example` | Document `GOOGLE_CLIENT_ID` |

No migrations required.

## Testing

- Valid `@bolivar.church` JWT matching an existing user → logs in, redirects to dashboard
- Valid JWT but non-`@bolivar.church` email → error message, stays on login
- Valid JWT but no matching user → error message, stays on login  
- Invalid/tampered JWT → error message, stays on login
- Missing credential in POST → error message, stays on login
- `GOOGLE_CLIENT_ID` not set → Google button not rendered, password login still works
- GET to `/auth/google/` → redirects to login (not a 405)
