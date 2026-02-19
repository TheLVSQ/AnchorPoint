# AnchorPoint

A lightweight church management system for small-to-mid-sized churches. Inspired by other non-profit management systems but designed to be simpler, more portable, and maintainable by non-developers.

## Features

- **People & Households** — Manage contacts, family groupings, and relationships
- **Groups** — Organize volunteer teams, small groups, and ministry areas
- **Events & Registration** — Create events with online registration and attendee management
- **Check-in System** — Kiosk-based check-in for children's ministry and classrooms
- **Messaging** — SMS and phone blast communications via Twilio

## Tech Stack

- **Backend:** Django 5.2 with Django REST Framework
- **Frontend:** Django templates + HTMX (minimal JavaScript)
- **Database:** PostgreSQL 16
- **Deployment:** Docker Compose with Cloudflare Tunnel

## Quick Start (Development)

### Prerequisites

- Python 3.12+
- PostgreSQL 16
- Docker & Docker Compose (optional, for containerized setup)

### Local Development Setup

1. Clone the repository:
   ```bash
   git clone https://github.com/yourusername/anchorpoint.git
   cd anchorpoint
   ```

2. Create a virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. Install dependencies:
   ```bash
   pip install -r docker/requirements.txt
   ```

4. Create a `.env` file in `anchorpoint/anchorpoint/`:
   ```env
   SECRET_KEY=your-dev-secret-key
   DEBUG=True
   DB_NAME=anchorpoint
   DB_USER=anchorpoint
   DB_PASS=anchorpoint
   DB_HOST=localhost
   DB_PORT=5432
   ```

5. Run migrations and start the server:
   ```bash
   cd anchorpoint
   python manage.py migrate
   python manage.py createsuperuser
   python manage.py runserver
   ```

6. Visit http://localhost:8000

## Production Deployment

See [DEPLOY.md](DEPLOY.md) for full deployment instructions using Docker and Cloudflare Tunnel.

### Quick Docker Deployment

```bash
# Clone and configure
git clone https://github.com/yourusername/anchorpoint.git
cd anchorpoint
cp .env.production.example .env.production
# Edit .env.production with your values

# Build and run
cd docker
cp ../.env.production .env.production
docker compose build
docker compose up -d

# Initialize database
docker compose exec web python manage.py migrate
docker compose exec web python manage.py setup_beta_users
```

## Project Structure

```
anchorpoint/
├── anchorpoint/          # Django project config
├── core/                 # Auth, profiles, organization settings
├── people/               # Contact management
├── households/           # Family groupings
├── groups/               # Teams and ministries
├── events/               # Events and registration
├── attendance/           # Legacy check-in (deprecated)
├── checkin/              # New check-in kiosk system
├── messaging/            # SMS and phone communications
└── templates/            # Global templates
```

## Configuration

All configuration is done via environment variables:

| Variable | Description | Required |
|----------|-------------|----------|
| `SECRET_KEY` | Django secret key | Yes |
| `DEBUG` | Enable debug mode | No (default: False) |
| `DB_NAME` | PostgreSQL database name | Yes |
| `DB_USER` | PostgreSQL username | Yes |
| `DB_PASS` | PostgreSQL password | Yes |
| `DB_HOST` | Database host | Yes |
| `DB_PORT` | Database port | No (default: 5432) |
| `ALLOWED_HOSTS` | Comma-separated allowed hosts | Yes |
| `CSRF_TRUSTED_ORIGINS` | Full URLs for CSRF | For production |
| `CLOUDFLARE_TUNNEL_TOKEN` | Cloudflare Tunnel token | For CF deployment |

## Running Tests

```bash
cd anchorpoint
python manage.py test
```

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

This project is open source and available under the [MIT License](LICENSE).
