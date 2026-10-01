# AnchorPoint Deployment Guide

This guide walks through deploying AnchorPoint on a homelab server with Cloudflare Tunnel.

## Prerequisites

- Docker and Docker Compose installed on your server
- A Cloudflare account with a domain
- SSH access to your homelab server

## Step 1: Clone the Repository to Your Server

```bash
# On your homelab server
git clone <your-repo-url> anchorpoint
cd anchorpoint
```

## Step 2: Create Production Environment File

```bash
# Copy the example file
cp .env.production.example .env.production

# Generate a secret key
python3 -c "import secrets; print(secrets.token_urlsafe(50))"

# Edit the file with your values
nano .env.production
```

Fill in these values:
```env
SECRET_KEY=<paste-generated-key>
DEBUG=False
DB_NAME=anchorpoint
DB_USER=anchorpoint
DB_PASS=<choose-a-strong-password>
DB_HOST=db
DB_PORT=5432
ALLOWED_HOSTS=localhost,127.0.0.1,<your-tunnel-domain>
CSRF_TRUSTED_ORIGINS=https://<your-tunnel-domain>
```

## Step 3: Build and Start the Containers

```bash
cd docker

# Build the image
docker compose build

# Start in detached mode
docker compose up -d

# Check logs
docker compose logs -f web
```

## Step 4: Run Database Migrations

```bash
# Run migrations
docker compose exec web python manage.py migrate

# Create beta test users (save the output!)
docker compose exec web python manage.py setup_beta_users \
    --admin-username=luke \
    --admin-email=luke@example.com \
    --tester1-username=tester1 \
    --tester1-email=tester1@example.com \
    --tester2-username=tester2 \
    --tester2-email=tester2@example.com
```

**IMPORTANT:** Save the passwords that are printed! They won't be shown again.

## Step 5: Set Up Cloudflare Tunnel

### Option A: Using cloudflared CLI (Recommended)

```bash
# Install cloudflared
# On Debian/Ubuntu:
curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb -o cloudflared.deb
sudo dpkg -i cloudflared.deb

# Login to Cloudflare
cloudflared tunnel login

# Create a tunnel
cloudflared tunnel create anchorpoint

# Configure the tunnel
cat > ~/.cloudflared/config.yml << EOF
tunnel: <TUNNEL_ID>
credentials-file: /root/.cloudflared/<TUNNEL_ID>.json

ingress:
  - hostname: anchorpoint.yourdomain.com
    service: http://localhost:8000
  - service: http_status:404
EOF

# Create DNS record
cloudflared tunnel route dns anchorpoint anchorpoint.yourdomain.com

# Run the tunnel (or set up as a service)
cloudflared tunnel run anchorpoint
```

### Option B: Using Cloudflare Dashboard

1. Go to **Zero Trust** > **Networks** > **Tunnels**
2. Click **Create a tunnel**
3. Name it "anchorpoint"
4. Install the connector on your server (follow Cloudflare's instructions)
5. Add a public hostname:
   - Subdomain: `anchorpoint` (or your choice)
   - Domain: Your domain
   - Service Type: `HTTP`
   - URL: `localhost:8000`

## Step 6: Update Environment with Tunnel Domain

After setting up the tunnel, update `.env.production`:

```env
ALLOWED_HOSTS=localhost,127.0.0.1,anchorpoint.yourdomain.com
CSRF_TRUSTED_ORIGINS=https://anchorpoint.yourdomain.com
```

Then restart the web container:

```bash
docker compose restart web
```

## Step 7: Verify Everything Works

1. Visit `https://anchorpoint.yourdomain.com`
2. You should see the login page
3. Log in with the admin credentials from Step 4
4. Go to Settings > Organization to configure your church name and logo

## Useful Commands

```bash
# View logs
docker compose logs -f web

# Restart services
docker compose restart

# Stop everything
docker compose down

# Stop and remove volumes (DELETES DATA!)
docker compose down -v

# Run a Django management command
docker compose exec web python manage.py <command>

# Access Django shell
docker compose exec web python manage.py shell

# Create a new superuser manually
docker compose exec web python manage.py createsuperuser
```

## Troubleshooting

### "CSRF verification failed"
- Make sure `CSRF_TRUSTED_ORIGINS` includes your full URL with `https://`
- Restart the web container after changing environment variables

### "Bad Request (400)"
- Check that your domain is in `ALLOWED_HOSTS`
- Restart the web container after changes

### Static files not loading
- Run: `docker compose exec web python manage.py collectstatic --noinput`
- Check that whitenoise is in MIDDLEWARE

### Database connection errors
- Wait for the database container to be healthy
- Check `DB_HOST=db` (not localhost)

## Security Notes

- Change the default database password before deploying
- Keep your `.env.production` file secure (don't commit to git)
- The Cloudflare tunnel provides SSL/TLS encryption
- Consider enabling Cloudflare Access for additional security
