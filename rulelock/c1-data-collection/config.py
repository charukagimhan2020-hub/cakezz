"""c1 settings, all from environment variables (one name per setting, see rulelock/.env.example)."""
import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:          # python-dotenv is optional; real environment variables still work
    pass


def _int(name, default):
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return int(default)


SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_SECRET_KEY = os.environ.get("SUPABASE_SECRET_KEY", "")
RULELOCK_API_TOKEN = os.environ.get("RULELOCK_API_TOKEN") or None
RULELOCK_ALLOW_NO_AUTH = os.environ.get("RULELOCK_ALLOW_NO_AUTH", "0") == "1"   # local development only
APP_ENV = (os.environ.get("APP_ENV") or os.environ.get("ENVIRONMENT") or os.environ.get("FLASK_ENV") or "").strip().lower()
IS_PRODUCTION = APP_ENV in {"production", "prod"} or os.environ.get("RENDER", "").lower() == "true"
PORT = _int("PORT", 5001)
MAX_BODY_BYTES = _int("MAX_BODY_BYTES", 65536)          # any request body
EVENT_MAX_BYTES = _int("EVENT_MAX_BYTES", 8192)         # POST /events is smaller still
# CORS is OFF by default: the PHP shop calls RuleLock from its server, not from the browser.
CORS_ORIGINS = [o.strip().rstrip("/") for o in os.environ.get("CORS_ORIGINS", "").split(",") if o.strip()]


def validate_auth_configuration(token=RULELOCK_API_TOKEN, production=IS_PRODUCTION):
    if production and not token:
        raise RuntimeError("RULELOCK_API_TOKEN is required in production")


validate_auth_configuration()
