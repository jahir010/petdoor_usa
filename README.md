# PetDoor USA — Backend API

A production-ready **FastAPI** backend for the PetDoor USA platform, built with Python 3.12. It uses **Tortoise ORM** with **MySQL** for data persistence, **Celery + Redis** for async task queues, and ships with full Docker support for both local development and production deployment.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Framework | FastAPI 0.119 + Uvicorn |
| ORM / Migrations | Tortoise ORM + Aerich |
| Database | MySQL (via aiomysql / asyncpg) |
| Task Queue | Celery 5 + Redis |
| Auth | JWT (python-jose) + Passlib/bcrypt |
| Email | fastapi-mail + aiosmtplib |
| SMS | Twilio |
| Payments | Stripe |
| Storage | Google Cloud Storage + Firebase Admin |
| Monitoring | Sentry SDK |
| Templates | Jinja2 |
| Containerisation | Docker + Docker Compose |

---

## Project Structure

```
petdoor_usa/
├── app/                  # Core FastAPI application (main.py, config, models)
├── applications/         # Domain-specific application modules
├── routes/               # API route definitions
├── tasks/                # Celery async tasks
├── templates/            # Jinja2 email/HTML templates
├── .github/workflows/    # CI/CD GitHub Actions pipelines
├── Dockerfile            # Multi-stage Docker build
├── compose.yml           # Docker Compose for deployment
├── start.sh              # Container entrypoint (DB wait + migrations + server)
├── pyproject.toml        # Aerich migration config
└── requirements.txt      # Python dependencies
```

---

## Getting Started

### Prerequisites

- Python 3.12+
- MySQL 8+
- Redis
- Docker & Docker Compose (for containerised setup)

### 1. Clone the repository

```bash
git clone https://github.com/jahir010/petdoor_usa.git
cd petdoor_usa
```

### 2. Create a virtual environment and install dependencies

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 3. Configure environment variables

Create a `.env` file in the project root. At minimum you will need:

```env
# Database
DATABASE_URL=mysql://user:password@localhost:3306/petdoor_usa
DB_HOST=localhost
DB_PORT=3306

# Security
SECRET_KEY=your-secret-key

# Redis / Celery
REDIS_URL=redis://localhost:6379/0

# Email
MAIL_USERNAME=
MAIL_PASSWORD=
MAIL_FROM=
MAIL_SERVER=

# Twilio
TWILIO_ACCOUNT_SID=
TWILIO_AUTH_TOKEN=
TWILIO_PHONE_NUMBER=

# Stripe
STRIPE_SECRET_KEY=

# Google Cloud / Firebase
GOOGLE_APPLICATION_CREDENTIALS=path/to/service-account.json
GCS_BUCKET_NAME=

# Sentry (optional)
SENTRY_DSN=
```

### 4. Run database migrations

```bash
# First-time setup
aerich init-db

# Subsequent runs
aerich upgrade
```

### 5. Start the development server

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

The API will be available at `http://localhost:8000`.  
Interactive docs: `http://localhost:8000/docs`

### 6. Start the Celery worker (separate terminal)

```bash
celery -A tasks worker --loglevel=info
```

---

## Running with Docker

### Build and start

```bash
docker compose up -d
```

The API is exposed on port **9920** (`http://localhost:9920`).

The container entrypoint (`start.sh`) will automatically:
1. Wait for the database to become reachable
2. Run Aerich migrations
3. Start Uvicorn with `WEB_CONCURRENCY` workers (default: 3)

### Environment variables for Docker

Pass your `.env` file via the `env_file` key already present in `compose.yml`, or override individual variables:

```bash
IMAGE_TAG=latest docker compose up -d
```

### Health check

Docker Compose includes a built-in health check that polls `http://localhost:8000/` every 15 seconds.

---

## CI / CD

GitHub Actions workflows are located in `.github/workflows/`. They handle automated testing and container image builds on push to `main`.

---

## Environment Variable Reference

| Variable | Description |
|---|---|
| `DATABASE_URL` | Full async DB connection URL |
| `DB_HOST` / `DB_PORT` | Used by `start.sh` to wait for DB readiness |
| `SECRET_KEY` | JWT signing secret |
| `REDIS_URL` | Celery broker URL |
| `RUN_MIGRATIONS` | Set to `false` to skip Aerich on startup (default: `true`) |
| `PORT` | Uvicorn port inside container (default: `8000`) |
| `WEB_CONCURRENCY` | Number of Uvicorn workers (default: `3`) |

---

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/your-feature`)
3. Commit your changes (`git commit -m 'Add your feature'`)
4. Push to your branch (`git push origin feature/your-feature`)
5. Open a Pull Request

---

## License

This project is private and proprietary. All rights reserved.
