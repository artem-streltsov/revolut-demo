# Revolut Webhook Handler

A FastAPI application that handles Revolut webhooks using ngrok for local development.

## Setup

1. Install ngrok:
   ```bash
   brew install ngrok
   ```

2. Add your ngrok auth token:
   ```bash
   ngrok config add-authtoken YOUR_AUTH_TOKEN
   ```

3. Configure your environment variables in `.env` (see `.env.example`)

4. Run the application:
   ```bash
   brew install uv
   uv venv
   source .venv/bin/activate
   uv sync
   uv run main.py
   ```

The ngrok dashboard will be available at: http://localhost:4040
