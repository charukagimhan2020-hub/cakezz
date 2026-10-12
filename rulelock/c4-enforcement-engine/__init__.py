"""c4 enforcement engine. Use: from decision import decide (with this folder on sys.path)."""
try:
    from .decision import decide, RULE_ACTION_MAP, thresholds, payment_action_for, customer_message_for   # as a package
    from .actions import apply_enforcement
    from .audit import build_audit_payload, record
except ImportError:                                                                                       # on sys.path
    from decision import decide, RULE_ACTION_MAP, thresholds, payment_action_for, customer_message_for     # noqa: F401
    from actions import apply_enforcement                                                                  # noqa: F401
    from audit import build_audit_payload, record                                                          # noqa: F401
