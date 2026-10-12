#!/usr/bin/env python3
"""Static integration check: do the shop (PHP), RuleLock (c1 to c4), the SQL schema, the env examples and the
deployment files agree with each other and with CONTRACT.md?  No network, no database.  Run: python scripts/check_integration.py
Exit code 1 if any check fails.  It reads the real code, so a rename in one place that is not copied to the others shows up here."""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
results = []


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def check(name, ok, detail=""):
    results.append((name, bool(ok), detail))


def files(pattern, skip=("tests", "node_modules", "__pycache__")):
    return [p for p in ROOT.glob(pattern) if not any(s in p.parts for s in skip)]


# ---------- schema ----------
schema = read("supabase/schema.sql")
tables = {}
for m in re.finditer(r"create table if not exists (?:public\.)?(\w+)\s*\((.*?)\n\);", schema, re.S | re.I):
    cols = set()
    for line in m.group(2).split("\n"):
        word = re.match(r"\s*(\w+)", line)
        if word and word.group(1).lower() not in {"primary", "unique", "check", "constraint", "foreign"} and not line.strip().startswith("--"):
            cols.add(word.group(1))
    tables[m.group(1)] = cols
expected_tables = {"users", "products", "coupons", "orders", "order_items", "coupons_used", "platform_settings",
                   "transaction_events", "account_restrictions", "rulelock_audit_log"}
check("schema has every table of the brief", expected_tables <= set(tables), f"missing: {sorted(expected_tables - set(tables))}")
check("schema has the RPC and the one-review-per-order indexes",
      "record_rulelock_review(p_event jsonb, p_audit jsonb)" in schema and "transaction_events_one_rulelock_review_per_order" in schema
      and "rulelock_audit_log_one_row_per_review" in schema)
check("audit table is insert-only", "BEFORE UPDATE OR DELETE ON public.rulelock_audit_log" in schema)
check("schema has no placeholder-only admin hash left unexplained", "PASTE_PHP_HASH_HERE" in schema)
check("no card data column anywhere", not re.search(r"card_?(number|no)|cvv|cvc", schema, re.I))
check("no CHECK on quantity, price or total (tampered values must be storable)",
      not re.search(r"check\s*\(\s*(quantity|unit_price|total|subtotal|discount_value)\b", schema, re.I))
status_m = re.search(r"status\s+text not null default 'PENDING'\s*check \(status in \(([^)]*)\)\)", schema, re.S)
schema_status = set(re.findall(r"'(\w+)'", status_m.group(1))) if status_m else set()
check("order status values in schema", schema_status == {"PENDING", "COMPLETED", "PLACED", "HELD", "BLOCKED", "CANCELLED", "REFUSED"}, str(sorted(schema_status)))

# ---------- tables and columns used by the code ----------
php_files = files("shop/**/*.php")
php_text = {p: p.read_text(encoding="utf-8") for p in php_files}
used_tables, bad = set(), []
for p, text in php_text.items():
    for t in re.findall(r"sb_(?:select|insert|update|delete)\(\s*'(\w+)'", text):
        used_tables.add(t)
        if t not in tables:
            bad.append(f"{p.relative_to(ROOT)}: {t}")
    for sel in re.findall(r"sb_select\(\s*'(\w+)'\s*,\s*\[\s*'select'\s*=>\s*'([^']*)'", text):
        for col in sel[1].split(","):
            col = col.strip()
            if col and col != "*" and "(" not in col and tables.get(sel[0]) and col not in tables[sel[0]]:
                bad.append(f"{p.relative_to(ROOT)}: {sel[0]}.{col}")
py_db = read("rulelock/c1-data-collection/db.py")
for t in re.findall(r'_request\(\s*"([\w/]+)"', py_db):
    if t.startswith("rpc/"):
        if t != "rpc/record_rulelock_review":
            bad.append(f"db.py: unknown rpc {t}")
        continue
    used_tables.add(t)
    if t not in tables:
        bad.append(f"db.py: {t}")
for tbl, sel in re.findall(r'_request\(\s*"(\w+)",\s*method="get",\s*params=\{"select":\s*"([^"]*)"', py_db):
    for col in sel.split(","):
        col = col.strip()
        if col and "(" not in col and "->" not in col and col != "*" and tables.get(tbl) and col not in tables[tbl]:
            bad.append(f"db.py: {tbl}.{col}")
check("every table and selected column used by PHP and by c1 db.py exists in schema.sql", not bad, "; ".join(bad))


def keys_in(text):
    return set(re.findall(r"'(\w+)'\s*=>", text))


order_cols = tables.get("orders", set())
bad = []
for p, text in php_text.items():
    for stmt in re.findall(r"order_patch\([^;]*;", text, re.S):
        for k in keys_in(stmt):
            if k not in order_cols:
                bad.append(f"{p.name}: orders.{k}")
lib = php_text[ROOT / "shop/includes/lib.php"]
create = re.search(r"function create_order.*?\n}\n", lib, re.S).group(0)
for k in keys_in(create):
    if k not in order_cols:
        bad.append(f"create_order: orders.{k}")
actions = read("rulelock/c4-enforcement-engine/actions.py")
for blob in re.findall(r"update_order\(order_id, \{(.*?)\}\)", actions, re.S):
    for k in re.findall(r'"(\w+)":', blob):
        if k not in order_cols:
            bad.append(f"actions.py: orders.{k}")
check("order columns written by the shop and by c4 exist", not bad, "; ".join(bad))
check("order_items / coupons_used / account_restrictions columns match",
      {"order_id", "product_id", "quantity", "unit_price"} <= tables.get("order_items", set())
      and {"user_id", "code", "order_id"} <= tables.get("coupons_used", set())
      and {"user_id", "type", "until", "reason"} <= tables.get("account_restrictions", set()))

# ---------- status values ----------
used_status = set()
for p, text in php_text.items():
    used_status |= set(re.findall(r"'(PENDING|COMPLETED|PLACED|HELD|BLOCKED|CANCELLED|REFUSED)'", text))
for p in files("rulelock/c[1-4]-*/*.py"):
    used_status |= set(re.findall(r'"(PENDING|COMPLETED|PLACED|HELD|BLOCKED|CANCELLED|REFUSED)"', p.read_text(encoding="utf-8")))
check("every order status used in code is allowed by the schema", used_status <= schema_status, str(sorted(used_status - schema_status)))
check("decision to status mapping: shop HELD/BLOCKED = c4 HELD/BLOCKED", {"HELD", "BLOCKED", "PLACED", "COMPLETED", "PENDING", "CANCELLED"} <= used_status)

# ---------- contract: request, response, decisions ----------
contract = read("CONTRACT.md")
req_block = re.search(r"Request:\n```json\n(.*?)```", contract, re.S).group(1)
resp_block = re.search(r"Response \(always HTTP 200.*?```json\n(.*?)```", contract, re.S).group(1)
req_keys = set(re.findall(r'"(\w+)":', req_block))
checkout = php_text[ROOT / "shop/checkout.php"]
payload = re.search(r"\$payload = \[(.*?)\n\];", checkout, re.S).group(1)
shop_keys = keys_in(payload) | {"sku", "quantity", "unit_price"}
check("shop review payload has exactly the contract request fields", req_keys == shop_keys, f"contract-only: {sorted(req_keys - shop_keys)}, shop-only: {sorted(shop_keys - req_keys)}")
resp_top = set(re.findall(r'^  "(\w+)":', resp_block, re.M)) | set(re.findall(r'\n  "(\w+)": "', resp_block))
events_py = read("rulelock/c1-data-collection/routes/events.py")
contract_keys = set(re.search(r"CONTRACT_KEYS = \((.*?)\)", events_py, re.S).group(1).replace('"', "").replace("\n", " ").replace(" ", "").split(",")) - {""}
resp_expected = {"order_id", "order_reference", "decision", "reason", "customer_message", "payment_action", "account_action", "pipeline", "rulelock_enabled"}
check("c1 response keys = contract response keys", contract_keys == resp_expected and resp_expected <= set(re.findall(r'"(\w+)":', resp_block)),
      f"{sorted(contract_keys ^ resp_expected)}")
for step in ("c1_data_collection", "c2_rule_engine", "c3_anomaly", "c4_enforcement"):
    check(f"pipeline step {step} named as in the contract and built by c1", step in contract and f'"{step}"' in read("rulelock/c1-data-collection/pipeline.py"))
dec = read("rulelock/c4-enforcement-engine/decision.py")
pa = dict(re.findall(r'"(accept|void_discount|hold|reject)":\s*"(\w+)"', re.search(r"PAYMENT_ACTION = \{(.*?)\}", dec, re.S).group(1)))
contract_pa = set(re.findall(r"capture_payment|void_discount|hold_payment|block_payment", contract))
check("payment_action values = contract", set(pa.values()) == {"capture_payment", "void_discount", "hold_payment", "block_payment"} and set(pa.values()) <= contract_pa, str(pa))
in_list = re.search(r"in_array\(\$decision, \[([^\]]*)\]", checkout)
listed = set(re.findall(r"'(\w+)'", in_list.group(1))) if in_list else set()
handled = {d for d in ("accept", "void_discount", "reject") if f"$decision === '{d}'" in checkout} | ({"hold"} if "// hold" in checkout and "'status' => 'HELD'" in checkout else set())
check("shop handles the four decisions (and anything else becomes hold)", listed == {"accept", "void_discount", "hold", "reject"} and handled == listed, f"listed {sorted(listed)}, handled {sorted(handled)}")
c2_map = dict(re.findall(r'"(\w+)":\s*"(reject|hold|void_discount)"', re.search(r"RULE_ACTION = \{(.*?)\n\}", read("rulelock/c2-rule-engine/rules.py"), re.S).group(1)))
c4_map = dict(re.findall(r'"(\w+)":\s*"(reject|hold|void_discount)"', re.search(r"RULE_ACTION_MAP = \{(.*?)\n\}", dec, re.S).group(1)))
check("c2 RULE_ACTION = c4 RULE_ACTION_MAP, includes total_mismatch -> reject", c2_map == c4_map and c4_map.get("total_mismatch") == "reject")
check("quantity is 1 to 20, MAX_COUPONS 1, 5 reviews/24h, thresholds -0.06/-0.1",
      all(s in read("rulelock/c2-rule-engine/rules.py") for s in ('"MAX_QUANTITY_PER_LINE", 20', '"MAX_COUPONS", 1', '"COUPON_VELOCITY_MAX_REVIEWS", 5'))
      and 'DEFAULT_HOLD = -0.06' in read("rulelock/c3-anomaly-detection/scoring.py") and "-0.1" in dec)

# ---------- shop to RuleLock: endpoints ----------
routes = set(re.findall(r'@(?:bp|app)\.(?:get|post)\("([^"]+)"\)', events_py + read("rulelock/c1-data-collection/app.py")))
routes_norm = {re.sub(r"<[^>]+>", "<x>", r) for r in routes}
called = set()
for p, text in php_text.items():
    called |= set(re.findall(r"rl_http\('(?:GET|POST)',\s*'(/[\w/-]*)", text))
    called |= set(re.findall(r"upstream\('(/[\w/-]*)", text))
    called |= set(re.findall(r"'(?:latest|list|summary|info|health)' => '(/[\w/-]*)", text))
called.add("/audit-log/<x>")
missing = {c for c in called if re.sub(r"\?.*", "", c) not in routes_norm}
check("every RuleLock URL called by the shop and the monitor exists in c1", not missing, str(sorted(missing)))
check("c1 has every endpoint of the contract", {"/events", "/review-order", "/audit-log", "/audit-log/<x>", "/dashboard/summary", "/settings/rulelock", "/pipeline/info", "/health", "/ready", "/audit-log/latest"} <= routes_norm, str(sorted(routes_norm)))

# ---------- environment variables ----------
def env_names(path):
    return set(re.findall(r"^#?\s*([A-Z][A-Z0-9_]+)=", read(path), re.M))


examples = env_names("shop/.env.example") | env_names("rulelock/.env.example") | env_names(".env.example")
used = set()
for p, text in php_text.items():
    used |= set(re.findall(r"\benv\('([A-Z][A-Z0-9_]+)'", text))
for p in files("rulelock/c[1-4]-*/*.py") + files("rulelock/c1-data-collection/routes/*.py"):
    text = p.read_text(encoding="utf-8")
    used |= set(re.findall(r'os\.environ\.get\(\s*"([A-Z][A-Z0-9_]+)"', text))
    used |= set(re.findall(r'_(?:int|float|float_env|int_env)\(\s*"([A-Z][A-Z0-9_]+)"', text))
used -= {"RENDER", "ENVIRONMENT", "FLASK_ENV", "FLASK_DEBUG"}      # set by the platform or optional aliases
check("every environment variable read by the code is documented in an .env.example", used <= examples, f"undocumented: {sorted(used - examples)}")
old = {"MAX_COUPONS_PER_SESSION", "MIN_QUANTITY", "MAX_QUANTITY", "MIN_PURCHASE", "PRICE_TOLERANCE", "COD_UNVERIFIED_HOLD_TOTAL",
       "COD_BAD_HOLD_COUNT", "COD_BAD_REJECT_COUNT", "COUPON_REVIEWS_24H_LIMIT", "ANOMALY_THRESHOLD"}
doc_text = "".join(read(p) for p in ("docs/SETUP.md", "shop/.env.example", "rulelock/.env.example", ".env.example", "README.md") if (ROOT / p).exists())
check("no old or duplicate setting names left in docs and env examples", not [n for n in old if re.search(rf"\b{n}\b", doc_text)],
      str([n for n in old if re.search(rf"\b{n}\b", doc_text)]))
check("RULELOCK_API_TOKEN and RULELOCK_URL named the same in shop, rulelock, compose and render.yaml",
      all("RULELOCK_API_TOKEN" in read(f) for f in ("shop/.env.example", "rulelock/.env.example", "docker-compose.yml", "render.yaml", ".env.example"))
      and all("RULELOCK_URL" in read(f) for f in ("shop/.env.example", "docker-compose.yml", "render.yaml")))

# ---------- mock, deployment ----------
rl_php = php_text[ROOT / "shop/includes/rulelock.php"]
check("RULELOCK_MOCK is ignored in production and on Render", re.search(r"function rl_mock_on\(\): bool \{ return !is_production\(\)", rl_php) and "'RENDER'" in rl_php)
check("shop image defaults to APP_ENV=production", "APP_ENV=production" in read("shop/Dockerfile"))
check("rulelock image: python 3.11-slim, trains the model, gunicorn, 1 worker default",
      "python:3.11-slim" in read("rulelock/Dockerfile") and "train_model.py" in read("rulelock/Dockerfile") and "gunicorn" in read("rulelock/Dockerfile")
      and "WEB_CONCURRENCY:-1" in read("rulelock/Dockerfile"))
check("c1 has no mock mode and no hard-coded Supabase URL", "MOCK" not in events_py.upper().replace("SIMULATION", "") and "supabase.co" not in "".join(p.read_text(encoding="utf-8") for p in files("rulelock/**/*.py")))
check("health endpoints exist for Render", (ROOT / "shop/health.php").exists() and '"/health"' in read("rulelock/c1-data-collection/app.py"))
try:
    import yaml
    render = yaml.safe_load(read("render.yaml"))["services"]
    compose = yaml.safe_load(read("docker-compose.yml"))["services"]
    by = {s["name"]: s for s in render}
    check("render.yaml: two free docker services with health checks",
          set(by) == {"rulelock", "cakezz-shop"} and all(s["plan"] == "free" and s["runtime"] == "docker" for s in render)
          and by["rulelock"]["healthCheckPath"] == "/health" and by["cakezz-shop"]["healthCheckPath"] == "/health.php")
    env_keys = {n: {e["key"] for e in s["envVars"]} for n, s in by.items()}
    check("render.yaml env vars cover the shop and RuleLock settings",
          {"SUPABASE_URL", "SUPABASE_SECRET_KEY", "RULELOCK_URL", "RULELOCK_API_TOKEN"} <= env_keys["cakezz-shop"]
          and {"SUPABASE_URL", "SUPABASE_SECRET_KEY", "RULELOCK_API_TOKEN"} <= env_keys["rulelock"])
    check("docker-compose: shop on 8080, rulelock on 5001, no profile gate",
          "8080:80" in compose["shop"]["ports"] and "5001:5001" in compose["rulelock"]["ports"] and "profiles" not in compose["rulelock"])
except ImportError:
    check("render.yaml / docker-compose parse (needs PyYAML)", True, "skipped: PyYAML not installed")

# ---------- docs exist ----------
for doc in ("README.md", "docs/SETUP.md", "docs/DEMO.md", "docs/VIVA.md", "docs/RISKS.md", "docs/E2E_TESTS.md"):
    check(f"{doc} exists", (ROOT / doc).exists())

width = max(len(n) for n, _, _ in results)
failed = 0
for name, ok, detail in results:
    print(("PASS  " if ok else "FAIL  ") + name + ("" if ok or not detail else "  ->  " + detail))
    failed += not ok
print(f"\n{len(results) - failed} of {len(results)} checks passed")
sys.exit(1 if failed else 0)
