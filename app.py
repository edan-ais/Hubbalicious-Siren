import os
from flask import Flask, request, jsonify
from collections import deque
import threading
from datetime import datetime

app = Flask(__name__)

# Simple in-memory queue (good for MVP). Upgrade later to Redis/Postgres if needed.
_queue = deque()
_lock = threading.Lock()

QUEUE_SECRET = os.getenv("QUEUE_SECRET", "change-me")  # set in Render dashboard

@app.get("/health")
def health():
    return {"ok": True, "time": datetime.utcnow().isoformat()}

@app.post("/clover_webhook")
def clover_webhook():
    """
    Clover POSTs here.
    - If it's a verification PING, respond with the verificationCode.
    - If it's a payment/order, enqueue a trigger for the local agent.
    """
    data = request.get_json(silent=True) or {}
    print("Webhook received:", data)

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
        print(f"Enqueued trigger for event: {etype}")
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
    print("Manual test trigger queued")
    return "queued", 200

if __name__ == "__main__":
    # For local testing only. Render will use gunicorn.
    app.run(host="0.0.0.0", port=5000)
