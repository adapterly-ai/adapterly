FROM python:3.12-slim

WORKDIR /app

# Install dependencies
COPY pyproject.toml .
RUN pip install --no-cache-dir .

# Copy source
COPY alembic.ini .
COPY alembic/ alembic/
COPY src/ src/

# Data directory for SQLite
RUN mkdir -p /app/data

ENV PYTHONPATH=/app/src
ENV ADAPTERLY_MODE=standalone

EXPOSE 8080

CMD ["python", "-m", "adapterly"]
