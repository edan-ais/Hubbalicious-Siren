import os
from flask import Flask, request, jsonify
from collections import deque
import threading
from datetime import datetime

app = Flask(__name__)

# In-memory queue
_queue = deque()
_lock = threading.Lock()

QUEUE_SECRET = os.getenv("QUEUE_SECRET", "change-me")

@app.get("/health")
def health():
    return {"ok": True, "time": datetime.utcnow().isoformat()}

@app.post("/clover_webhook")
def clover_webhook():
    """
    Clover will POST here for subscribed events (like PAYMENT_CREATED).
    """
    data = request.get_json(silent=True) or {}
    print("📩 Clover Webhook Received:", data)

    etype = data.get("type")
    if etype in ("PAYMENT_CREATED", "ORDER_CREATED"):
        with _lock:
            _queue.append({
                "at": datetime.utcnow().isoformat(),
                "type": etype,
                "raw": data
            })
        return "", 200
    return "", 200

@app.post("/next-trigger")
def next_trigger():
    """
    Local agent polls this endpoint.
    """
    secret = request.args.get("secret")
    if secret != QUEUE_SECRET:
        return "", 403

    with _lock:
        if _queue:
            _queue.popleft()
            return jsonify({"trigger": True})
    return jsonify({"trigger": False})

@app.get("/test_fire")
def test_fire():
    secret = request.args.get("secret")
    if secret != QUEUE_SECRET:
        return "", 403
    with _lock:
        _queue.append({
            "at": datetime.utcnow().isoformat(),
            "type": "TEST"
        })
    return "queued", 200

# ✅ Dummy OAuth callback for Clover install flow
@app.get("/oauth/callback")
def oauth_callback():
    code = request.args.get("code", "")
    merchant_id = request.args.get("merchant_id", "")
    return f"✅ App installed for merchant {merchant_id}. OAuth code: {code}", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
