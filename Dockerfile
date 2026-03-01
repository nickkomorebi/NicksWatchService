FROM python:3.12-slim

WORKDIR /app

# System deps (curl for healthcheck; chromium deps installed by playwright)
RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY pyproject.toml .
RUN pip install --no-cache-dir -e .

# Install Playwright browsers
RUN playwright install chromium --with-deps

# Copy application code
COPY . .

# Ensure data dir exists (SQLite volume mount target)
RUN mkdir -p data secrets

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
