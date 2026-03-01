#!/usr/bin/env bash
# One-time setup for GCP service account and Google Sheets API access.
# Run this from the project root. Requires gcloud CLI authenticated.

set -euo pipefail

PROJECT_ID="${GCP_PROJECT_ID:-nicks-watch-service}"
SA_NAME="watchservice-sa"
SA_EMAIL="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
KEY_PATH="secrets/service_account.json"

echo "==> Using project: $PROJECT_ID"

# Create project (skip if already exists)
gcloud projects create "$PROJECT_ID" --name="Nicks Watch Service" 2>/dev/null || echo "(project already exists)"

# Set active project
gcloud config set project "$PROJECT_ID"

# Enable Google Sheets API
echo "==> Enabling Sheets API…"
gcloud services enable sheets.googleapis.com

# Create service account
echo "==> Creating service account: $SA_EMAIL"
gcloud iam service-accounts create "$SA_NAME" \
  --display-name="Watch Service" 2>/dev/null || echo "(service account already exists)"

# Download key
echo "==> Downloading key to $KEY_PATH"
mkdir -p secrets
gcloud iam service-accounts keys create "$KEY_PATH" \
  --iam-account="$SA_EMAIL"

echo ""
echo "Done! Now share your Google Sheet with this email (Viewer role):"
echo "  $SA_EMAIL"
echo ""
echo "Set in .env:"
echo "  GOOGLE_SERVICE_ACCOUNT_JSON=/app/secrets/service_account.json"
