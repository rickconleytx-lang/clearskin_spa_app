from flask import request, jsonify


def process_telnyx_webhook():
    data = request.get_json(silent=True) or {}

    print("TELNYX WEBHOOK RECEIVED:", data, flush=True)

    return jsonify({
        "success": True,
        "message": "Telnyx webhook received"
    }), 200