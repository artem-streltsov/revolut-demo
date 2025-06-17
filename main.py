import os
import json
import requests
from fastapi import FastAPI, Request, HTTPException
import uvicorn
from pyngrok import ngrok
from typing import Dict, Any
from datetime import datetime, timezone
import hmac
import hashlib

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
        self.webhook_signing_secret = None

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

    def validate_signature(
        self, signature_header: str, timestamp_header: str, raw_payload: str
    ) -> bool:
        if not signature_header:
            print("WEBHOOK REJECTED: Missing revolut-signature header")
            raise HTTPException(status_code=400, detail="Missing signature header")

        if not self.webhook_signing_secret:
            print("WEBHOOK REJECTED: No webhook signing secret available")
            raise HTTPException(
                status_code=500, detail="Missing webhook signing secret"
            )

        try:
            # Format: v1.{timestamp}.{raw_payload_without_whitespaces}
            payload_to_sign = f"v1.{timestamp_header}.{raw_payload}"
            print(f"Payload to sign: {payload_to_sign}")

            # HMAC-SHA256 with the signing secret as key
            expected_signature = (
                "v1="
                + hmac.new(
                    bytes(self.webhook_signing_secret, "utf-8"),
                    msg=bytes(payload_to_sign, "utf-8"),
                    digestmod=hashlib.sha256,
                ).hexdigest()
            )

            print(f"Expected signature: {expected_signature}")
            print(f"Received signature: {signature_header}")

            # Revolut may send multiple signatures separated by commas
            received_signatures = [sig.strip() for sig in signature_header.split(",")]

            for received_sig in received_signatures:
                if hmac.compare_digest(expected_signature, received_sig):
                    print("Signature validation: PASSED")
                    return True

            print("WEBHOOK REJECTED: Signature validation failed")
            raise HTTPException(status_code=400, detail="Invalid signature")

        except Exception as e:
            print(f"WEBHOOK REJECTED: Signature validation error: {str(e)}")
            raise HTTPException(status_code=400, detail="Signature validation failed")

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

            if response.status_code == 200:
                result = response.json()
                if "signing_secret" in result:
                    self.webhook_signing_secret = result["signing_secret"]
                    print(
                        f"Webhook signing secret captured: {self.webhook_signing_secret[:10]}..."
                    )
                return result
            else:
                return {"error": response.text}
        except Exception as e:
            print(f"Webhook setup failed: {str(e)}")
            return {"error": str(e)}

    def process_webhook(self, headers_dict: dict, payload: dict, raw_payload: str):
        print(f"\nWEBHOOK HEADERS:")
        print(f"{json.dumps(headers_dict, indent=2)}")

        timestamp_header = headers_dict.get("revolut-request-timestamp")
        signature_header = headers_dict.get("revolut-signature")

        self.validate_timestamp(timestamp_header)
        self.validate_signature(signature_header, timestamp_header, raw_payload)

        print(f"\nWEBHOOK PAYLOAD:")
        print(f"{json.dumps(payload, indent=2)}")


global_webhook_manager = None


@app.post("/webhook/revolut")
async def handle_revolut_webhook(request: Request):
    try:
        headers_dict = dict(request.headers)

        raw_payload = await request.body()
        raw_payload_str = raw_payload.decode("utf-8")
        payload = json.loads(raw_payload_str)

        if global_webhook_manager is None:
            raise HTTPException(
                status_code=500, detail="Webhook manager not initialized"
            )

        global_webhook_manager.process_webhook(headers_dict, payload, raw_payload_str)

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
    global global_webhook_manager

    print("Starting Revolut Demo")
    load_env()

    try:
        ngrok_tunnel = ngrok.connect(8000)
        public_url = ngrok_tunnel.public_url
        webhook_url = f"{public_url}/webhook/revolut"
        print(f"Ngrok tunnel: {public_url}")
        print(f"Webhook endpoint: {webhook_url}")

        order_client = RevolutOrderClient()
        global_webhook_manager = RevolutWebhookManager()

        global_webhook_manager.delete_all_webhooks()
        global_webhook_manager.setup_webhook(webhook_url)

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
