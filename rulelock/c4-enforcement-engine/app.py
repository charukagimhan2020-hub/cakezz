"""Optional standalone wrapper: POST /enforce, GET /health.
DECISION ONLY: it runs decide() and builds the audit payload but writes nothing (no database here).
At runtime c1 imports decision.py / actions.py and passes its Supabase helper to apply_enforcement()."""
import os

from flask import Flask, jsonify, request

try:
    from decision import decide, payment_action_for, customer_message_for
    from audit import build_audit_payload
except ImportError:
    from .decision import decide, payment_action_for, customer_message_for
    from .audit import build_audit_payload

app = Flask(__name__)


@app.get("/health")
def health():
    return jsonify(status="ok"), 200


@app.post("/enforce")
def enforce():
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or "order_id" not in data:
        return jsonify(error="send a JSON object with at least order_id"), 400
    result = decide(order_id=data["order_id"], account_id=data.get("account_id"),
                    rule_passed=bool(data.get("rule_passed", True)), rule_reason=data.get("rule_reason", ""),
                    anomaly_score=data.get("anomaly_score"), payment_method=data.get("payment_method", "CARD"),
                    rule_code=data.get("rule_code"), violations=data.get("violations"))
    result["payment_action"] = payment_action_for(result["decision"])
    result["customer_message"] = customer_message_for(result["decision"])
    try:
        audit = build_audit_payload(result, data["order_id"], data.get("account_id"), data.get("payment_method"),
                                    data.get("total"), data.get("order_reference"), data.get("anomaly_score"),
                                    event_type="RULELOCK_SIMULATION")
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    return jsonify(result=result, audit_preview=audit, written=False)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5004")), debug=os.environ.get("FLASK_DEBUG", "0") == "1")
