FROM python:3.12-slim

WORKDIR /app

# Copy everything (gateway_core must be copied by build_prepare.sh first)
COPY . /app/

# Install as package
RUN pip install --no-cache-dir .

# Health check
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import httpx; httpx.get('http://localhost:8080/health').raise_for_status()"

EXPOSE 8080

CMD ["adapterly-gateway", "run"]
