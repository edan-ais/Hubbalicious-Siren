import os
import requests
from flask import Flask, request, jsonify
from collections import deque
import threading
from datetime import datetime

app = Flask(__name__)

# =========================
# CONFIGURATION
# =========================
APP_ID = os.getenv("CLOVER_APP_ID", "YOUR_APP_ID")
APP_SECRET = os.getenv("CLOVER_APP_SECRET", "YOUR_APP_SECRET")
QUEUE_SECRET = os.getenv("QUEUE_SECRET", "change-me")  # set in Render dashboard

# Tokens & merchant ID
ACCESS_TOKEN = None
MERCHANT_ID = None

# Simple in-memory queue (good for MVP). Upgrade later to Redis/Postgres if needed.
_queue = deque()
_lock = threading.Lock()

# Track last payment ID we've seen to avoid duplicate triggers
last_payment_id = None


# =========================
# ROUTES
# =========================
@app.get("/health")
def health():
    return {"ok": True, "time": datetime.utcnow().isoformat()}


# ✅ OAuth callback to exchange `code` → `access_token`
@app.get("/oauth/callback")
def oauth_callback():
    global ACCESS_TOKEN, MERCHANT_ID

    code = request.args.get("code")
    merchant_id = request.args.get("merchant_id")

    if not code or not merchant_id:
        return "❌ Missing OAuth code or merchant_id", 400

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
    MERCHANT_ID = merchant_id

    print("✅ Got Clover access token:", ACCESS_TOKEN)
    return f"✅ App installed for merchant {merchant_id}. Access token acquired.", 200


# ✅ Poll Clover API for new payments
@app.post("/poll-clover")
def poll_clover():
    global last_payment_id

    if not ACCESS_TOKEN or not MERCHANT_ID:
        return "❌ No Clover access token. Install the app first.", 400

    url = f"https://api.clover.com/v3/merchants/{MERCHANT_ID}/payments?limit=1&order=desc"
    headers = {"Authorization": f"Bearer {ACCESS_TOKEN}"}

    try:
        resp = requests.get(url, headers=headers, timeout=5)
        resp.raise_for_status()
    except Exception as e:
        print("❌ Error calling Clover API:", e)
        return "❌ Failed to fetch payments", 500

    data = resp.json()
    elements = data.get("elements", [])

    if not elements:
        return jsonify({"new": False})

    latest = elements[0]
    payment_id = latest.get("id")

    # If this payment is new, enqueue a trigger
    if payment_id and payment_id != last_payment_id:
        last_payment_id = payment_id
        with _lock:
            _queue.append(
                {
                    "at": datetime.utcnow().isoformat(),
                    "type": "PAYMENT_CREATED",
                    "amount": latest.get("amount"),
                }
            )
        print(f"✅ New payment detected! Enqueued trigger: {payment_id}")
        return jsonify({"new": True})

    return jsonify({"new": False})


# ✅ Local agent polls this endpoint
@app.post("/next-trigger")
def next_trigger():
    secret = request.args.get("secret")
    if secret != QUEUE_SECRET:
        return "", 403

    with _lock:
        if _queue:
            _queue.popleft()
            return jsonify({"trigger": True})
    return jsonify({"trigger": False})


# ✅ Manual test: enqueue a trigger from a browser
@app.get("/test_fire")
def test_fire():
    secret = request.args.get("secret")
    if secret != QUEUE_SECRET:
        return "", 403
    with _lock:
        _queue.append({"at": datetime.utcnow().isoformat(), "type": "TEST"})
    print("✅ Manual test trigger queued")
    return "queued", 200


# =========================
# MAIN
# =========================
if __name__ == "__main__":
    # For local testing only. Render will use gunicorn.
    app.run(host="0.0.0.0", port=5000)
