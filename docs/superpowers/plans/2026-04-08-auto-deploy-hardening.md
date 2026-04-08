# Auto-Deploy & Droplet Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Harden the Ubuntu 22.04 DigitalOcean droplet and set up a manually-triggered GitHub Actions workflow that deploys the latest code via a self-hosted runner.

**Architecture:** A `deploy` non-root user is the shared foundation — it owns the repo, runs the GitHub Actions runner as a systemd service, and replaces root as the SSH login. Hardening and auto-deploy are implemented in a safety-first order (create + verify `deploy` user before disabling root SSH).

**Tech Stack:** Ubuntu 22.04, UFW, fail2ban, unattended-upgrades, GitHub Actions self-hosted runner, Docker Compose, systemd

---

## Part 1: Droplet Hardening

### Task 1: Create the `deploy` user and verify SSH access

**Files:**
- Droplet: `/home/deploy/.ssh/authorized_keys`

All commands run on the droplet as `root` (SSH in as root first).

- [ ] **Step 1: Create the deploy user**

```bash
adduser --disabled-password --gecos "" deploy
usermod -aG sudo deploy
usermod -aG docker deploy
```

- [ ] **Step 2: Copy root's SSH authorized key to deploy user**

```bash
mkdir -p /home/deploy/.ssh
cp /root/.ssh/authorized_keys /home/deploy/.ssh/authorized_keys
chown -R deploy:deploy /home/deploy/.ssh
chmod 700 /home/deploy/.ssh
chmod 600 /home/deploy/.ssh/authorized_keys
```

- [ ] **Step 3: Verify deploy user can SSH in**

From your local machine, open a new terminal and run:

```bash
ssh deploy@<your-droplet-ip>
```

Expected: you are logged in as `deploy` without a password prompt.

**Do not proceed until this works. Continuing without verifying will lock you out.**

- [ ] **Step 4: Verify sudo works**

While logged in as `deploy`:

```bash
sudo whoami
```

Expected output: `root`

- [ ] **Step 5: Commit (no repo changes yet — nothing to commit)**

No files changed in the repository at this step.

---

### Task 2: Configure UFW firewall

All commands run on the droplet as `root` (or `sudo` from `deploy`).

- [ ] **Step 1: Reset UFW to defaults and enable**

```bash
sudo ufw --force reset
sudo ufw default deny incoming
sudo ufw default allow outgoing
```

- [ ] **Step 2: Allow SSH**

```bash
sudo ufw allow 22/tcp
```

- [ ] **Step 3: Enable UFW**

```bash
sudo ufw --force enable
```

- [ ] **Step 4: Verify rules**

```bash
sudo ufw status verbose
```

Expected output:
```
Status: active
To                         Action      From
--                         ------      ----
22/tcp                     ALLOW IN    Anywhere
22/tcp (v6)                ALLOW IN    Anywhere (v6)
```

Port 80 should NOT appear in the list.

---

### Task 3: Fix Docker/UFW port binding bypass

Docker modifies iptables directly, bypassing UFW. Binding the port to `127.0.0.1` prevents the app from being reachable on the public IP even though Docker bypasses UFW.

**Files:**
- Modify: `docker/docker-compose.yml`

- [ ] **Step 1: Update port binding in docker-compose.yml**

In `docker/docker-compose.yml`, change:

```yaml
    ports:
      - "80:8000"
```

to:

```yaml
    ports:
      - "127.0.0.1:80:8000"
```

- [ ] **Step 2: Commit the change**

```bash
git add docker/docker-compose.yml
git commit -m "fix: bind web port to localhost only to block direct IP access"
```

- [ ] **Step 3: Pull and apply the change on the droplet**

SSH into the droplet as `root` (or `deploy` with sudo), navigate to the repo, and run:

```bash
cd /root/anchorpoint/docker   # adjust path if your repo is elsewhere
git pull origin main
docker compose up -d
```

Expected: Docker recreates the `web` container.

- [ ] **Step 4: Verify the app is NOT reachable directly**

From your local machine:

```bash
curl -I http://<your-droplet-ip>/
```

Expected: connection refused or timeout (not a 200 or redirect).

- [ ] **Step 5: Verify Cloudflare Tunnel still works**

Visit your tunnel URL (e.g., `https://anchorpoint.yourdomain.com`) in a browser.

Expected: AnchorPoint login page loads.

**Note:** If the Cloudflare Tunnel config says `http://localhost:8000` (as shown in DEPLOY.md), update it to `http://localhost:80` — that is the host port Docker actually exposes. Check your tunnel config at `~/.cloudflared/config.yml`:

```yaml
ingress:
  - hostname: anchorpoint.yourdomain.com
    service: http://localhost:80   # <-- should be 80, not 8000
  - service: http_status:404
```

If you're using Cloudflare Dashboard tunnels, update the service URL there instead. Restart cloudflared after any change:

```bash
sudo systemctl restart cloudflared
```

---

### Task 4: Harden SSH configuration

**Do this only after Task 1 Step 3 is confirmed working.**

All commands run on the droplet.

- [ ] **Step 1: Edit sshd_config**

```bash
sudo nano /etc/ssh/sshd_config
```

Find and update (or add) these lines:

```
PermitRootLogin no
PasswordAuthentication no
PubkeyAuthentication yes
```

- [ ] **Step 2: Validate the config**

```bash
sudo sshd -t
```

Expected: no output (no errors).

- [ ] **Step 3: Restart SSH**

```bash
sudo systemctl restart ssh
```

- [ ] **Step 4: Verify root login is rejected**

From your local machine, in a new terminal:

```bash
ssh root@<your-droplet-ip>
```

Expected: `Permission denied (publickey)` — root login refused.

Your `deploy` session should still be active and functional.

---

### Task 5: Install fail2ban

- [ ] **Step 1: Install fail2ban**

```bash
sudo apt-get update
sudo apt-get install -y fail2ban
```

- [ ] **Step 2: Create a local jail config**

```bash
sudo tee /etc/fail2ban/jail.local > /dev/null <<'EOF'
[sshd]
enabled = true
port = 22
maxretry = 5
bantime = 600
findtime = 600
EOF
```

- [ ] **Step 3: Enable and start fail2ban**

```bash
sudo systemctl enable fail2ban
sudo systemctl start fail2ban
```

- [ ] **Step 4: Verify it's running and the SSH jail is active**

```bash
sudo fail2ban-client status sshd
```

Expected output includes:
```
Status for the jail: sshd
|- Filter
|  |- Currently failed: 0
|  `- Total failed:     0
`- Actions
   |- Currently banned: 0
   `- Total banned:     0
```

---

### Task 6: Enable unattended security upgrades

- [ ] **Step 1: Install the package**

```bash
sudo apt-get install -y unattended-upgrades
```

- [ ] **Step 2: Enable automatic security updates**

```bash
sudo dpkg-reconfigure --priority=low unattended-upgrades
```

When prompted, select **Yes**.

- [ ] **Step 3: Verify the config**

```bash
cat /etc/apt/apt.conf.d/20auto-upgrades
```

Expected output:
```
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
```

- [ ] **Step 4: Run a dry-run to confirm it works**

```bash
sudo unattended-upgrades --dry-run --debug 2>&1 | head -30
```

Expected: output showing packages being evaluated (no errors).

---

## Part 2: Auto-Deploy

### Task 7: Set up repo under deploy user

The current repo is likely at `/root/anchorpoint`. We clone a fresh copy for the `deploy` user. The `.env.production` file from the old location needs to be copied over.

- [ ] **Step 1: Generate an SSH key for the deploy user (GitHub deploy key)**

On the droplet, as `deploy`:

```bash
ssh-keygen -t ed25519 -C "anchorpoint-deploy" -f ~/.ssh/github_deploy -N ""
cat ~/.ssh/github_deploy.pub
```

Copy the public key output.

- [ ] **Step 2: Add the deploy key to the GitHub repo**

In a browser: go to `https://github.com/TheLVSQ/AnchorPoint/settings/keys` → **Add deploy key**:
- Title: `droplet-deploy`
- Key: paste the public key from Step 1
- Allow write access: **No** (read-only is sufficient)

- [ ] **Step 3: Configure SSH to use the deploy key for GitHub**

On the droplet as `deploy`:

```bash
cat >> ~/.ssh/config <<'EOF'

Host github.com
  IdentityFile ~/.ssh/github_deploy
  StrictHostKeyChecking accept-new
EOF
chmod 600 ~/.ssh/config
```

- [ ] **Step 4: Test GitHub SSH access**

```bash
ssh -T git@github.com
```

Expected: `Hi TheLVSQ! You've successfully authenticated, but GitHub does not provide shell access.`

- [ ] **Step 5: Clone the repo**

```bash
git clone git@github.com:TheLVSQ/AnchorPoint.git /home/deploy/anchorpoint
```

- [ ] **Step 6: Copy .env.production from the old location**

```bash
sudo cp /root/anchorpoint/docker/.env.production /home/deploy/anchorpoint/docker/.env.production
chown deploy:deploy /home/deploy/anchorpoint/docker/.env.production
```

- [ ] **Step 7: Verify Docker Compose still starts correctly**

```bash
cd /home/deploy/anchorpoint/docker
docker compose up -d
docker compose ps
```

Expected: `web` and `db` containers show as `running`.

---

### Task 8: Install the GitHub Actions self-hosted runner

- [ ] **Step 1: Get the runner registration token from GitHub**

In a browser: go to `https://github.com/TheLVSQ/AnchorPoint/settings/actions/runners` → **New self-hosted runner** → select **Linux** / **x64**.

GitHub will show a `config.sh` command with a `--token <TOKEN>` argument. Copy that token value — you'll need it in Step 3.

- [ ] **Step 2: Download and extract the runner**

On the droplet as `deploy`:

```bash
mkdir -p /home/deploy/actions-runner
cd /home/deploy/actions-runner
curl -o actions-runner-linux-x64.tar.gz -L \
  https://github.com/actions/runner/releases/download/v2.323.0/actions-runner-linux-x64-2.323.0.tar.gz
tar xzf actions-runner-linux-x64.tar.gz
```

**Note:** Check the GitHub "New self-hosted runner" page for the latest runner version and use the exact URL shown there — the version above may be outdated.

- [ ] **Step 3: Register the runner**

Replace `<TOKEN>` with the token from Step 1:

```bash
./config.sh \
  --url https://github.com/TheLVSQ/AnchorPoint \
  --token <TOKEN> \
  --name "anchorpoint-droplet" \
  --labels "self-hosted,Linux,x64" \
  --work "/home/deploy/actions-runner/_work" \
  --unattended
```

Expected: `Runner successfully added` and `Runner settings saved.`

- [ ] **Step 4: Install as a systemd service**

```bash
sudo ./svc.sh install deploy
sudo ./svc.sh start
```

- [ ] **Step 5: Verify the runner is online**

```bash
sudo ./svc.sh status
```

Expected: `active (running)`

Also check the GitHub UI at `https://github.com/TheLVSQ/AnchorPoint/settings/actions/runners` — the runner should show as **Idle**.

---

### Task 9: Create the GitHub Actions deploy workflow

**Files:**
- Create: `.github/workflows/deploy.yml`

- [ ] **Step 1: Create the workflows directory**

```bash
mkdir -p .github/workflows
```

- [ ] **Step 2: Create the deploy workflow**

Create `.github/workflows/deploy.yml`:

```yaml
name: Deploy to Production

on:
  workflow_dispatch:

jobs:
  deploy:
    runs-on: self-hosted
    steps:
      - name: Pull latest code
        working-directory: /home/deploy/anchorpoint
        run: git pull origin main

      - name: Build Docker image
        working-directory: /home/deploy/anchorpoint/docker
        run: docker compose build

      - name: Recreate containers
        working-directory: /home/deploy/anchorpoint/docker
        run: docker compose up -d

      - name: Run migrations
        working-directory: /home/deploy/anchorpoint/docker
        run: docker compose exec -T web python manage.py migrate
```

- [ ] **Step 3: Commit and push**

```bash
git add .github/workflows/deploy.yml
git commit -m "feat: add manual deploy workflow with self-hosted runner"
git push origin main
```

---

### Task 10: Test the deploy workflow

- [ ] **Step 1: Trigger the workflow manually**

In a browser: go to `https://github.com/TheLVSQ/AnchorPoint/actions` → **Deploy to Production** → **Run workflow** → **Run workflow**.

- [ ] **Step 2: Watch the run**

Click the running workflow. Expected steps all show green checkmarks:
- Pull latest code ✓
- Build Docker image ✓
- Recreate containers ✓
- Run migrations ✓

If any step fails, click it to read the full log output.

- [ ] **Step 3: Verify the app is still healthy after deploy**

Visit your Cloudflare Tunnel URL. Expected: AnchorPoint login page loads normally.

- [ ] **Step 4: Make a trivial test change to confirm end-to-end**

On your local machine, make any visible change (e.g., a one-word text change in a template), commit, push to `main`, then trigger the workflow again. Verify the change appears live after the run completes.

---

## Safety Checklist (run before closing your root session)

Before ending your last root SSH session, confirm:

- [ ] `ssh deploy@<ip>` works from a fresh terminal
- [ ] `sudo whoami` returns `root` as `deploy`
- [ ] `ssh root@<ip>` is rejected with `Permission denied`
- [ ] `curl -I http://<ip>/` times out or is refused
- [ ] `https://anchorpoint.yourdomain.com` loads correctly
- [ ] GitHub Actions runner shows **Idle** at `github.com/TheLVSQ/AnchorPoint/settings/actions/runners`
- [ ] GitHub Actions workflow completes successfully
