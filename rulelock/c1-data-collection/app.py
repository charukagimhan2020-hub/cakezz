"""RuleLock backend (c1): ONE Flask process that imports c2, c3 and c4 as plain Python modules.
Run: gunicorn app:app   (from this folder; see Dockerfile)."""
import paths  # noqa: F401  (must be first: sets sys.path for c2, c3, c4)

import logging

from flask import Flask, jsonify

import config
import db
import scoring as c3_scoring
from routes.events import bp as events_bp

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__, static_folder=None)
app.config["MAX_CONTENT_LENGTH"] = config.MAX_BODY_BYTES
if config.CORS_ORIGINS:                            # off by default
    from flask_cors import CORS
    CORS(app, origins=config.CORS_ORIGINS)
app.register_blueprint(events_bp)


@app.errorhandler(404)
def not_found(_error):
    return jsonify(error="not found"), 404


@app.errorhandler(405)
def method_not_allowed(_error):
    return jsonify(error="method not allowed"), 405


@app.errorhandler(413)
def too_large(_error):
    return jsonify(error=f"request body is larger than {config.MAX_BODY_BYTES} bytes"), 413


@app.get("/health")
def health():
    """Fast liveness check. No auth, no database."""
    return jsonify(status="ok"), 200


@app.get("/ready")
def ready():
    """Model loaded and Supabase reachable."""
    model = c3_scoring.model_status()
    checks = {"model_loaded": model["loaded"], "supabase_reachable": False}
    try:
        db.check_supabase()
        checks["supabase_reachable"] = True
    except Exception:
        logger.exception("Supabase readiness check failed")
    is_ready = all(checks.values())
    body = {"ready": is_ready, "checks": checks}
    if model["error"]:
        body["model_error"] = model["error"]
    return jsonify(body), 200 if is_ready else 503


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=config.PORT, debug=False)
