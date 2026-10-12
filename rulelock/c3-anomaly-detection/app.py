"""Optional standalone wrapper: POST /score, GET /health, GET /ready. At runtime c1 imports scoring.py directly."""
import os

from flask import Flask, jsonify, request

import scoring

app = Flask(__name__)


@app.get("/health")
def health():
    return jsonify(status="ok"), 200


@app.get("/ready")
def ready():
    status = scoring.model_status()
    return jsonify(status="ready" if status["loaded"] else "not_ready", **status), (200 if status["loaded"] else 503)


@app.post("/score")
def score():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify(error="send a JSON object with the four feature values"), 400
    try:
        raw, anomaly = scoring.score_session(body)
    except scoring.ModelNotLoadedError as exc:
        return jsonify(error=str(exc)), 503
    t = scoring.thresholds()
    return jsonify(raw_score=raw, is_anomaly=anomaly, hold_threshold=t["hold"], reject_threshold=t["reject"])


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5003")), debug=os.environ.get("FLASK_DEBUG", "0") == "1")
