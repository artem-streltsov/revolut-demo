import os
import json
import requests
from fastapi import FastAPI, Request, HTTPException
import uvicorn
from pyngrok import ngrok
from typing import Dict, Any
from datetime import datetime, timezone

app = FastAPI(title="Revolut Webhook Handler")


class RevolutOrderClient:
    def __init__(self):
        self.api_key = os.getenv("REVOLUT_API_KEY")
        self.secret = os.getenv("REVOLUT_SECRET")
        self.base_url = os.getenv("REVOLUT_BASE_URL")
        self.api_version = os.getenv("REVOLUT_API_VERSION")

        if not all([self.api_key, self.secret, self.base_url, self.api_version]):
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


class RevolutWebhookManager:
    def __init__(self):
        self.api_key = os.getenv("REVOLUT_API_KEY")
        self.secret = os.getenv("REVOLUT_SECRET")
        self.base_url = os.getenv("REVOLUT_BASE_URL")
        self.api_version = os.getenv("REVOLUT_API_VERSION")

        if not all([self.api_key, self.secret, self.base_url, self.api_version]):
            raise ValueError("Missing required environment variables")

    def validate_timestamp(self, timestamp_header: str) -> bool:
        if not timestamp_header:
            print("WEBHOOK REJECTED: Missing revolut-request-timestamp header")
            raise HTTPException(status_code=400, detail="Missing timestamp header")

        try:
            # Convert milliseconds to seconds (Revolut sends timestamp in milliseconds)
            timestamp_seconds = int(timestamp_header) / 1000
            webhook_time = datetime.fromtimestamp(timestamp_seconds, tz=timezone.utc)
            current_time = datetime.now(timezone.utc)
            time_diff = abs((current_time - webhook_time).total_seconds())

            print(f"Webhook timestamp: {webhook_time}")
            print(f"Current UTC time: {current_time}")
            print(f"Time difference: {time_diff:.2f} seconds")

            if time_diff > 300:  # 5 minutes = 300 seconds
                print(f"WEBHOOK REJECTED: Timestamp too old ({time_diff:.2f}s > 300s)")
                raise HTTPException(
                    status_code=400, detail="Webhook timestamp is too old"
                )
            else:
                print("Timestamp validation: PASSED")
                return True

        except (ValueError, TypeError) as e:
            print(f"WEBHOOK REJECTED: Invalid timestamp format: {timestamp_header}")
            raise HTTPException(status_code=400, detail="Invalid timestamp format")

    def get_webhook_list(self):
        url = f"{self.base_url}/api/1.0/webhooks"
        headers = {"Authorization": f"Bearer {self.secret}"}

        try:
            response = requests.get(url, headers=headers)
            print(f"Get webhooks response: {response.status_code}")

            if response.status_code == 200:
                webhooks = response.json()
                print(f"Found {len(webhooks)} existing webhooks")
                return webhooks
            else:
                print(f"Failed to get webhooks: {response.text}")
                return []

        except Exception as e:
            print(f"Failed to retrieve webhooks: {str(e)}")
            return []

    def delete_webhook(self, webhook_id: str):
        url = f"{self.base_url}/api/1.0/webhooks/{webhook_id}"
        headers = {"Authorization": f"Bearer {self.secret}"}

        try:
            response = requests.delete(url, headers=headers)
            print(f"Deleted webhook {webhook_id}: {response.status_code}")
            return response.status_code == 204
        except Exception as e:
            print(f"Webhook deletion failed: {str(e)}")
            return False

    def delete_all_webhooks(self):
        print("Deleting all existing webhooks...")
        webhooks = self.get_webhook_list()

        if not webhooks:
            print("No existing webhooks found")
            return

        for webhook in webhooks:
            webhook_id = webhook.get("id")
            if webhook_id:
                self.delete_webhook(webhook_id)

        print("Finished deleting existing webhooks")

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

    def process_webhook(self, headers_dict: dict, payload: dict):
        print(f"\nWEBHOOK HEADERS:")
        print(f"{json.dumps(headers_dict, indent=2)}")

        timestamp_header = headers_dict.get("revolut-request-timestamp")
        self.validate_timestamp(timestamp_header)

        print(f"\nWEBHOOK PAYLOAD:")
        print(f"{json.dumps(payload, indent=2)}")


@app.post("/webhook/revolut")
async def handle_revolut_webhook(request: Request):
    try:
        headers_dict = dict(request.headers)
        payload = await request.json()

        webhook_manager = RevolutWebhookManager()
        webhook_manager.process_webhook(headers_dict, payload)

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

        order_client = RevolutOrderClient()
        webhook_manager = RevolutWebhookManager()

        webhook_manager.delete_all_webhooks()
        webhook_manager.setup_webhook(webhook_url)

        orders = [{"amount": 1000, "currency": "GBP", "description": "£10.00 GBP"}]
        payment_urls = []

        for i, order in enumerate(orders, 1):
            print(f"\nCreating order {i} ({order['description']})")
            result = order_client.create_order(order["amount"], order["currency"])
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
