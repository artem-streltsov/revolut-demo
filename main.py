import os
import json
import requests
from fastapi import FastAPI, Request, HTTPException
import uvicorn
from pyngrok import ngrok
from typing import Dict, Any

app = FastAPI(title="Revolut Webhook Handler")


class RevolutOrderClient:
    def __init__(self):
        self.api_key = os.getenv("REVOLUT_API_KEY")
        self.secret = os.getenv("REVOLUT_SECRET")
        self.base_url = os.getenv("REVOLUT_BASE_URL")
        self.api_version = os.getenv("REVOLUT_API_VERSION")

        if not all([self.api_key, self.secret, self.base_url]):
            raise ValueError("Missing required environment variables")

    def create_order(self, amount: int, currency: str) -> Dict[str, Any]:
        url = f"{self.base_url}/api/orders"
        headers = {
            "Authorization": f"Bearer {self.secret}",
            "Revolut-Api-Version": self.api_version,
        }
        payload = {"amount": amount, "currency": currency}

        try:
            print(f"Creating order: {amount} {currency}")
            response = requests.post(url, headers=headers, json=payload)

            if response.status_code == 201:
                result = response.json()
                print(f"Order created: {json.dumps(result, indent=2)}")
                return result
            else:
                error_info = {
                    "status_code": response.status_code,
                    "error": response.text,
                }
                print(f"Error: {json.dumps(error_info, indent=2)}")
                return error_info
        except Exception as e:
            error_info = {"error": str(e)}
            print(f"Unexpected error: {json.dumps(error_info, indent=2)}")
            return error_info

    def setup_webhook(self, webhook_url: str):
        url = f"{self.base_url}/api/1.0/webhooks"
        headers = {
            "Authorization": f"Bearer {self.secret}",
        }
        payload = {
            "url": webhook_url,
            "events": ["ORDER_COMPLETED", "ORDER_AUTHORISED"],
        }

        try:
            response = requests.post(url, headers=headers, json=payload)
            print(f"Webhook setup: {response.status_code} - {response.text}")
            return (
                response.json()
                if response.status_code == 200
                else {"error": response.text}
            )
        except Exception as e:
            print(f"Webhook setup failed: {str(e)}")
            return {"error": str(e)}


@app.post("/webhook/revolut")
async def handle_revolut_webhook(request: Request):
    try:
        payload = await request.json()
        print(f"\nWEBHOOK RECEIVED:\n{json.dumps(payload, indent=2)}")
        return {"status": 204}
    except json.JSONDecodeError:
        print("Invalid JSON payload")
        raise HTTPException(status_code=400, detail="Invalid JSON payload")
    except Exception as e:
        print(f"Webhook error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


def load_env():
    try:
        with open(".env", "r") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    os.environ[key] = value
    except FileNotFoundError:
        print("Warning: .env file not found")


def run_demo():
    print("Starting Revolut Demo")
    load_env()

    try:
        ngrok_tunnel = ngrok.connect(8000)
        public_url = ngrok_tunnel.public_url
        webhook_url = f"{public_url}/webhook/revolut"
        print(f"Ngrok tunnel: {public_url}")
        print(f"Webhook endpoint: {webhook_url}")

        client = RevolutOrderClient()
        client.setup_webhook(webhook_url)

        orders = [{"amount": 1000, "currency": "GBP", "description": "£10.00 GBP"}]
        payment_urls = []

        for i, order in enumerate(orders, 1):
            print(f"\nCreating order {i} ({order['description']})")
            result = client.create_order(order["amount"], order["currency"])
            if "checkout_url" in result:
                payment_urls.append(f"Order {i}: {result['checkout_url']}")

        if payment_urls:
            print("\nPayment URLs:")
            for url in payment_urls:
                print(f"   {url}")

        print("\nStarting webhook server...")
        port = int(os.getenv("PORT", 8000))
        uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")

    except KeyboardInterrupt:
        print("\nShutting down...")
        ngrok.kill()
    except Exception as e:
        print(f"Demo error: {e}")
        ngrok.kill()


if __name__ == "__main__":
    run_demo()
