"""Optional standalone wrapper: POST /validate, GET /health. At runtime c1 imports rules.py directly."""
import os

from flask import Flask, jsonify, request

try:
    from rules import validate_transaction
except ImportError:
    from .rules import validate_transaction

app = Flask(__name__)


@app.get("/health")
def health():
    return jsonify(status="ok"), 200


@app.post("/validate")
def validate():
    """Body: the review-order JSON. Optional extra keys: catalog, coupon_review_count,
    account_verified, past_orders, past_refusals."""
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify(error="send a JSON object"), 400
    return jsonify(validate_transaction(body, catalog=body.get("catalog"),
                                        coupon_review_count=body.get("coupon_review_count")))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5002")), debug=os.environ.get("FLASK_DEBUG", "0") == "1")
