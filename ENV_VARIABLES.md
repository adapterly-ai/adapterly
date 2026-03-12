# Environment Variables Configuration

This file documents the environment variables used by Adapterly.

## Django Core

```bash
# Django secret key (required for production)
# Generate with: python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
SECRET_KEY=your-secret-key-here

# Debug mode (set to false in production)
DEBUG=true

# Allowed hosts (comma-separated, required in production)
# ALLOWED_HOSTS=localhost,127.0.0.1,adapterly.ai
```

## Database

The application uses SQLite by default. For production, configure PostgreSQL:

```bash
DB_ENGINE=django.db.backends.postgresql
DB_NAME=adapterly
DB_USER=adapterly
DB_PASSWORD=change-me-in-production
DB_HOST=localhost
DB_PORT=5432
```

Docker Compose uses these for the postgres container:

```bash
POSTGRES_DB=adapterly
POSTGRES_USER=adapterly
POSTGRES_PASSWORD=change-me-in-production
```

## Email (SMTP)

```bash
# SendGrid (recommended)
EMAIL_HOST=smtp.sendgrid.net
EMAIL_PORT=587
EMAIL_USE_TLS=true
EMAIL_HOST_USER=apikey
EMAIL_HOST_PASSWORD=SG.your-sendgrid-api-key
DEFAULT_FROM_EMAIL=noreply@yourdomain.com
```

## Google OAuth (optional)

For Google Sign-In support:

```bash
GOOGLE_CLIENT_ID=your-client-id.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=GOCSPX-your-client-secret
```

## Adapter Update Notifications

```bash
# Email recipients for adapter spec change notifications
ADAPTER_UPDATE_NOTIFY_EMAILS=["admin@adapterly.ai"]
```

## Creating the .env File

```bash
cp .env.example .env
# Edit with your values
```

**Note:** The `.env` file should never be committed to version control. It is automatically ignored by `.gitignore`.
