import os
import requests
from flask import Flask, request, jsonify
from collections import deque
import threading
from datetime import datetime

app = Flask(__name__)

# Simple in-memory queue (good for MVP). Upgrade later to Redis/Postgres if needed.
_queue = deque()
_lock = threading.Lock()

# Secrets from Clover Developer Dashboard
APP_ID = os.getenv("CLOVER_APP_ID", "YOUR_APP_ID")
APP_SECRET = os.getenv("CLOVER_APP_SECRET", "YOUR_APP_SECRET")
QUEUE_SECRET = os.getenv("QUEUE_SECRET", "change-me")  # set in Render dashboard

# Store token in memory for now
ACCESS_TOKEN = None

@app.get("/health")
def health():
    return {"ok": True, "time": datetime.utcnow().isoformat()}

# ✅ OAuth callback to exchange `code` → `access_token`
@app.get("/oauth/callback")
def oauth_callback():
    global ACCESS_TOKEN

    code = request.args.get("code")
    merchant_id = request.args.get("merchant_id")

    if not code:
        return "❌ No OAuth code provided", 400

    print(f"🔑 OAuth callback: merchant_id={merchant_id}, code={code}")

    # Exchange the code for an access token
    token_url = "https://www.clover.com/oauth/token"
    params = {
        "client_id": APP_ID,
        "client_secret": APP_SECRET,
        "code": code,
    }
    resp = requests.post(token_url, params=params)

    if resp.status_code != 200:
        print("❌ Failed to exchange OAuth code:", resp.text)
        return f"❌ Failed to exchange code: {resp.text}", 400

    data = resp.json()
    ACCESS_TOKEN = data.get("access_token")
    print("✅ Got Clover access token:", ACCESS_TOKEN)

    return f"✅ App installed for merchant {merchant_id}. Access token acquired.", 200

@app.post("/clover_webhook")
def clover_webhook():
    """
    Clover POSTs here.
    - If it's a verification PING, respond with the verificationCode.
    - If it's a payment/order, enqueue a trigger for the local agent.
    """
    data = request.get_json(silent=True) or {}
    print("📩 Webhook received:", data)

    # ✅ Handle Clover webhook verification
    if data.get("type") == "PING" and "verificationCode" in data:
        code = data["verificationCode"]
        print(f"Responding to Clover verification with code: {code}")
        return code, 200

    # ✅ Handle Clover events
    etype = data.get("type")
    if etype in ("PAYMENT_CREATED", "ORDER_CREATED"):
        with _lock:
            _queue.append({"at": datetime.utcnow().isoformat(), "type": etype})
        print(f"✅ Enqueued trigger for event: {etype}")
        return "", 200

    # Ignore other event types
    return "", 200

@app.post("/next-trigger")
def next_trigger():
    """
    Local agent polls this endpoint.
    Returns {"trigger": true} once per queued event, then removes it.
    Protect with a shared secret to prevent abuse.
    """
    secret = request.args.get("secret")
    if secret != QUEUE_SECRET:
        return "", 403

    with _lock:
        if _queue:
            _queue.popleft()
            return jsonify({"trigger": True})
    return jsonify({"trigger": False})

# Handy manual test: enqueue a trigger from a browser
@app.get("/test_fire")
def test_fire():
    secret = request.args.get("secret")
    if secret != QUEUE_SECRET:
        return "", 403
    with _lock:
        _queue.append({"at": datetime.utcnow().isoformat(), "type": "TEST"})
    print("✅ Manual test trigger queued")
    return "queued", 200

if __name__ == "__main__":
    # For local testing only. Render will use gunicorn.
    app.run(host="0.0.0.0", port=5000)
