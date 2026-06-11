from flask import request, jsonify
import json


def process_telnyx_webhook():

    data = request.get_json(silent=True) or {}

    print("\n==============================", flush=True)
    print("TELNYX WEBHOOK RECEIVED", flush=True)
    print("==============================", flush=True)
    print(json.dumps(data, indent=4), flush=True)
    print("==============================\n", flush=True)

    return jsonify({
        "success": True,
        "message": "Telnyx webhook received"
    }), 200