# Auto-Deploy & Droplet Hardening Design

**Date:** 2026-04-08
**Status:** Approved

## Overview

Two goals:
1. Set up a GitHub Actions workflow (manually triggered) that deploys the latest code to the DigitalOcean droplet
2. Harden the droplet against common threats

The two goals share a core dependency: a `deploy` non-root user that owns the repo, runs the GitHub Actions runner, and replaces root as the SSH login.

---

## Part 1: Auto-Deploy

### Trigger

GitHub Actions `workflow_dispatch` — triggered manually from the GitHub UI on the `main` branch.

### Runner

A GitHub Actions self-hosted runner is installed on the droplet under the `deploy` user and registered as a systemd service so it starts automatically on reboot. The `deploy` user is added to the `docker` group, allowing it to run Docker commands without sudo.

### Workflow Steps

`.github/workflows/deploy.yml`:

1. Pull latest code: `git pull origin main`
2. Rebuild Docker image: `docker compose build`
3. Recreate containers: `docker compose up -d`
4. Run migrations: `docker compose exec -T web python manage.py migrate`

Steps run inside the `docker/` directory (where `docker-compose.yml` lives). The `-T` flag on `exec` disables TTY allocation, which is required in non-interactive CI environments.

### Secrets & Environment

The `.env.production` file stays on the droplet at `docker/.env.production` and is never committed to the repo. The deploy workflow only pulls code — secrets are not touched.

### Repo Location

The repo is cloned to `/home/deploy/anchorpoint` and owned by the `deploy` user.

---

## Part 2: Droplet Hardening

### Target Environment

- DigitalOcean droplet
- Ubuntu 22.04.5 LTS
- Currently: root login via RSA key, port 80 open publicly

### Changes

#### 1. Non-root `deploy` user

- Create `deploy` user with sudo privileges
- Copy root's `~/.ssh/authorized_keys` to `deploy` user
- Add `deploy` to the `docker` group
- All future SSH sessions use `deploy`, not `root`

#### 2. Disable root SSH login

In `/etc/ssh/sshd_config`:
```
PermitRootLogin no
PasswordAuthentication no
```

Restart `sshd` after confirming `deploy` login works first — prevents lockout.

#### 3. UFW firewall

Reset UFW to deny-all defaults, then allow only:
- Port 22 (SSH)

Port 80 is removed from UFW — the app is no longer directly reachable on the public IP.

#### 4. Fix Docker/UFW bypass

Docker modifies `iptables` directly and bypasses UFW rules. Even with port 80 removed from UFW, Docker would still expose the port publicly without this fix.

Fix: change the port binding in `docker/docker-compose.yml` from:
```yaml
ports:
  - "80:8000"
```
to:
```yaml
ports:
  - "127.0.0.1:80:8000"
```

This binds the app to localhost only. The Cloudflare Tunnel (configured as `http://localhost:80`) continues to work; direct public IP access is blocked.

#### 5. fail2ban

Install `fail2ban` with the default SSH jail:
- 5 failed attempts triggers a 10-minute ban
- Protects against SSH brute-force attacks

#### 6. Unattended security upgrades

Enable Ubuntu's `unattended-upgrades` package to automatically apply security patches. Only security updates are applied automatically; major upgrades remain manual.

---

## Sequence of Operations (Safety Order)

To avoid being locked out of the droplet, changes must be applied in this order:

1. Create `deploy` user and verify SSH login works
2. Install GitHub Actions runner under `deploy`
3. Apply UFW rules and Docker/localhost fix
4. Disable root SSH login
5. Install fail2ban
6. Enable unattended upgrades

---

## Files Changed

| File | Change |
|------|--------|
| `.github/workflows/deploy.yml` | New — GitHub Actions deploy workflow |
| `docker/docker-compose.yml` | Bind port to `127.0.0.1` |
| `/etc/ssh/sshd_config` (droplet) | Disable root login + password auth |
| `/etc/ufw/` (droplet) | SSH-only rules |

Droplet-side changes (user creation, runner install, fail2ban, unattended-upgrades) are applied manually via SSH during implementation.
