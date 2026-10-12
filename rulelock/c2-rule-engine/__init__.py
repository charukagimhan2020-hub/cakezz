"""c2 rule engine. Use: from rules import validate_transaction (with this folder on sys.path)."""
try:
    from .rules import validate_transaction, RULE_ACTION, COUPON_PERCENTS   # imported as a package
except ImportError:                                                         # folder is on sys.path
    from rules import validate_transaction, RULE_ACTION, COUPON_PERCENTS    # noqa: F401
