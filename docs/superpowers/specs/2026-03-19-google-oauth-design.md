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

**django-allauth[google]** — handles the OAuth2 redirect, token exchange, and session creation. A custom adapter overrides two behaviours: domain enforcement and account auto-creation.

### Components

| File | Change |
|------|--------|
| `requirements.txt` | Add `django-allauth[google]` |
| `anchorpoint/settings.py` | Add allauth apps, backends, and provider config; point to custom adapter |
| `anchorpoint/urls.py` | Add `path('accounts/', include('allauth.urls'))` |
| `core/adapters.py` | New — `BolicarSocialAccountAdapter` |
| `templates/core/login.html` | Add "Sign in with Google" button |

## Custom Adapter (`core/adapters.py`)

`BolicarSocialAccountAdapter` extends `allauth.socialaccount.adapter.DefaultSocialAccountAdapter` and overrides:

- **`is_open_for_signup(request, sociallogin)`** — returns `True` only if the email domain is `bolivar.church`; raises `ImmediateHttpResponse` with a redirect to login + error message otherwise
- **`save_user(request, sociallogin, form=None)`** — calls `super()`, then ensures the created user's `UserProfile` has `role = UserProfile.Role.STAFF` and `can_manage_communications = False`

Account linking (Google login matched to existing `User` by email) is handled automatically by allauth's default behaviour.

## Settings Changes

```python
INSTALLED_APPS += [
    'django.contrib.sites',
    'allauth',
    'allauth.account',
    'allauth.socialaccount',
    'allauth.socialaccount.providers.google',
]

SITE_ID = 1

AUTHENTICATION_BACKENDS = [
    'django.contrib.auth.backends.ModelBackend',
    'allauth.account.auth_backends.AuthenticationBackend',
]

SOCIALACCOUNT_ADAPTER = 'core.adapters.BolicarSocialAccountAdapter'

SOCIALACCOUNT_PROVIDERS = {
    'google': {
        'SCOPE': ['profile', 'email'],
        'AUTH_PARAMS': {'access_type': 'online'},
        'FETCH_USERINFO': True,
    }
}

LOGIN_REDIRECT_URL = '/'
ACCOUNT_EMAIL_REQUIRED = True
```

Google client ID and secret stored in environment variables (`GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`) and wired into the `SocialApp` via the Django admin (one-time setup).

## Login Page Update

The existing `templates/core/login.html` gets a "Sign in with Google" button rendered above the username/password form, separated by an "or" divider. The button uses the standard Google branding guidelines (white background, Google logo, "Sign in with Google" text).

## Authentication Flow

1. User clicks "Sign in with Google" on login page
2. Redirected to Google consent screen
3. Google returns to allauth callback with auth code
4. allauth exchanges code for user info (email, name)
5. Custom adapter checks domain:
   - Not `@bolivar.church` → redirect to login with error: "Only @bolivar.church accounts can sign in with Google."
   - `@bolivar.church` → continue
6. Email matches existing `User` → link Google account, log in
7. New email → create `User` + `UserProfile` (role=Staff) → log in
8. Redirect to dashboard (`/`)

## Error Handling

- **Wrong domain:** Redirect to `/login/` with a Django message: "Only @bolivar.church accounts can sign in with Google."
- **Google OAuth failure / cancelled:** allauth handles this; user lands back on login page
- **Duplicate email conflict:** allauth's default email-matching links the Google identity to the existing account automatically

## Environment Variables Required

```
GOOGLE_CLIENT_ID=<from Google Cloud Console>
GOOGLE_CLIENT_SECRET=<from Google Cloud Console>
```

## Google Cloud Console Setup (manual, one-time)

1. Create a project in [Google Cloud Console](https://console.cloud.google.com)
2. Enable the **Google+ API** (or People API)
3. Create OAuth 2.0 credentials (Web Application type)
4. Add authorised redirect URI: `https://yourdomain/accounts/google/callback/`
5. Copy Client ID and Secret into `.env.production`
6. In Django admin → Sites → update domain to match production URL
7. In Django admin → Social Applications → add Google app with Client ID and Secret

## Testing

- Sign in with a `@bolivar.church` Google account → lands on dashboard, account created with Staff role
- Sign in with a non-`@bolivar.church` account → error message, no account created
- Sign in with Google using an email that already has a password account → links successfully, logs in
- Existing password-login users unaffected
