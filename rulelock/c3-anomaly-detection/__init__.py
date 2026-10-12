"""c3 anomaly detection. Use: from scoring import score_session (with this folder on sys.path)."""
try:
    from .scoring import score_session, model_metadata, is_model_loaded    # imported as a package
except ImportError:                                                        # folder is on sys.path
    from scoring import score_session, model_metadata, is_model_loaded     # noqa: F401
