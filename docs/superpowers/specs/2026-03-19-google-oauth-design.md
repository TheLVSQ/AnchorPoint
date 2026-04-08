# Google OAuth Integration — Design Spec
**Date:** 2026-03-19
**Status:** Approved

## Overview

Add Google OAuth login to AnchorPoint. Only `@bolivar.church` Google accounts may use OAuth. All other users continue to authenticate via username/password. First-time Google sign-ins auto-create a user account with the Staff role; admins can adjust permissions afterward.

## Goals

- Allow `@bolivar.church` staff to sign in with their Google account (no separate password to manage)
- Auto-provision new accounts on first Google login
- Leave the existing username/password flow untouched for all other users

## Out of Scope

- Google Workspace directory sync
- OAuth login for non-`@bolivar.church` domains
- Automated role assignment beyond the default Staff role

## Architecture

### Library

**django-allauth[google]** — handles the OAuth2 redirect, token exchange, and session creation. A custom adapter overrides domain enforcement and first-time account provisioning.

### Components

| File | Change |
|------|--------|
| `requirements.txt` | Add `django-allauth[google]` |
| `anchorpoint/settings.py` | Add allauth apps, middleware, backends, and provider config |
| `anchorpoint/urls.py` | Add `path('accounts/', include('allauth.urls'))` |
| `core/adapters.py` | New — `BolivarSocialAccountAdapter` |
| `templates/core/login.html` | Add "Sign in with Google" button |

## Custom Adapter (`core/adapters.py`)

`BolivarSocialAccountAdapter` extends `DefaultSocialAccountAdapter`:

### `pre_social_login(request, sociallogin)`

Primary domain enforcement. Runs during the OAuth callback before any login or signup. Reads `sociallogin.user.email`, checks for `@bolivar.church` domain. If not matching, raises `ImmediateHttpResponse` redirecting to `/login/` with a Django error message: "Only @bolivar.church accounts can sign in with Google."

### `is_auto_signup_allowed(request, sociallogin)`

Secondary domain check (belt-and-suspenders). Returns `False` for any non-`@bolivar.church` email. Catches edge cases where `pre_social_login` ordering differs across allauth versions.

### `save_user(request, sociallogin, form=None)`

Sets the Staff role on first-time user creation only. Uses `sociallogin.is_existing` — `not sociallogin.is_existing` means this is the first OAuth login for this user. Uses `UserProfile.objects.get_or_create(user=user)` to safely retrieve the profile (the post-save signal fires during `super().save_user()` and creates the profile with the default Volunteer role; `save_user` immediately overwrites it with Staff).

```python
def save_user(self, request, sociallogin, form=None):
    user = super().save_user(request, sociallogin, form)
    if not sociallogin.is_existing:
        profile, _ = UserProfile.objects.get_or_create(user=user)
        profile.role = UserProfile.Role.STAFF
        profile.can_manage_communications = False
        profile.save()
    return user
```

## Settings Changes

Add the following to `anchorpoint/settings.py`:

```python
INSTALLED_APPS += [
    'django.contrib.sites',       # required by allauth
    'allauth',
    'allauth.account',
    'allauth.socialaccount',
    'allauth.socialaccount.providers.google',
]

SITE_ID = 1  # required by django.contrib.sites / allauth

MIDDLEWARE += [
    'allauth.account.middleware.AccountMiddleware',  # required by allauth 0.56+
]

AUTHENTICATION_BACKENDS = [
    'django.contrib.auth.backends.ModelBackend',
    'allauth.account.auth_backends.AuthenticationBackend',
]

SOCIALACCOUNT_ADAPTER = 'core.adapters.BolivarSocialAccountAdapter'
ACCOUNT_EMAIL_REQUIRED = True
SOCIALACCOUNT_EMAIL_VERIFICATION = 'none'  # trust Google's own email verification
LOGIN_REDIRECT_URL = '/'

_google_client_id = os.getenv('GOOGLE_CLIENT_ID')
_google_client_secret = os.getenv('GOOGLE_CLIENT_SECRET')
if not _google_client_id or not _google_client_secret:
    raise ValueError(
        'GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET environment variables are required.'
    )

SOCIALACCOUNT_PROVIDERS = {
    'google': {
        'APP': {
            'client_id': _google_client_id,
            'secret': _google_client_secret,
            'key': '',
        },
        'SCOPE': ['profile', 'email'],
        'AUTH_PARAMS': {'access_type': 'online'},
        'FETCH_USERINFO': True,
    }
}
```

**Notes:**
- `SOCIALACCOUNT_EMAIL_VERIFICATION = 'none'` — Google has already verified the email; setting this to `'mandatory'` would cause allauth to send its own verification email and block login, breaking the OAuth flow.
- `ValueError` is used for missing credentials, consistent with how `SECRET_KEY` is validated in the existing codebase.
- The `ImproperlyConfigured` guard on credentials only applies when allauth is installed. For local dev without Google credentials, either omit the allauth apps from `INSTALLED_APPS` or add placeholder values to `.env.development`.

## Account Linking Security Decision

Auto-linking a Google sign-in to an existing password account by matching email is **intentional**. `@bolivar.church` accounts are managed via Google Workspace, so Google has already verified domain ownership. `SOCIALACCOUNT_EMAIL_VERIFICATION = 'none'` trusts this verification implicitly.

## Self-Registration Policy

Username/password self-registration is not enabled — users are created by admins or via Google OAuth only. The existing codebase has no public signup URL so no changes to `ACCOUNT_ADAPTER` are needed.

## Login Page Update

The existing `templates/core/login.html` gets a "Sign in with Google" button rendered above the username/password form, separated by an "or" divider. Follows standard Google branding guidelines (white background, Google logo, "Sign in with Google" text).

## Authentication Flow

1. User clicks "Sign in with Google"
2. Redirected to Google consent screen
3. Google returns to allauth callback at `/accounts/google/login/callback/`
4. `pre_social_login` fires — domain check, rejects non-`@bolivar.church`
5. Email matches existing `User` → link Google account, log in (role unchanged)
6. New email → `save_user` creates `User` + sets `UserProfile` role to Staff
7. Redirect to dashboard (`/`)

**Note:** Allauth's OAuth callback uses a `state` parameter for CSRF protection — Django's CSRF middleware does not apply to the callback URL. No additional CSRF configuration is required.

## Error Handling

- **Wrong domain:** Redirect to `/login/` with message: "Only @bolivar.church accounts can sign in with Google."
- **OAuth failure / cancelled:** allauth default handling, user lands back on login page
- **Duplicate email:** allauth links the Google identity to the existing account (intentional — see Account Linking section)
- **Missing credentials:** `ValueError` raised at startup, app does not start

## Environment Variables Required

```
GOOGLE_CLIENT_ID=<from Google Cloud Console>
GOOGLE_CLIENT_SECRET=<from Google Cloud Console>
```

Add to both `.env.production` and `.env.production.example`.

## Deployment Steps (one-time)

1. **Google Cloud Console:**
   - Navigate to APIs & Services → Credentials
   - Create OAuth 2.0 credentials (Web Application type)
   - Add authorised redirect URI: `https://yourdomain/accounts/google/login/callback/`
     *(The exact path is `/accounts/google/login/callback/` — including `login/` — omitting it causes a redirect mismatch error in Google Console)*
   - Copy Client ID and Secret into `.env.production`

2. **Database:**
   - Run `python manage.py migrate` — creates the `django_site` table
   - Immediately update the default `Site` record in Django admin → Sites → change domain from `example.com` to the production domain (e.g. `app.bolivar.church`)
   - **Do not test the OAuth flow before completing this step** — incorrect domain causes allauth to generate wrong callback URLs silently

## Testing

- New `@bolivar.church` Google sign-in → account created with Staff role, lands on dashboard
- `@bolivar.church` user with elevated Admin role signs in again via Google → role is **unchanged**
- Non-`@bolivar.church` Google account → error message shown, no account created, redirected to `/login/`
- Existing password account with matching `@bolivar.church` email → Google account linked, user logged in, role preserved
- Existing password-only users with non-`@bolivar.church` emails → unaffected, password login works as before
- Missing `GOOGLE_CLIENT_ID` or `GOOGLE_CLIENT_SECRET` → `ValueError` at startup, app does not start
