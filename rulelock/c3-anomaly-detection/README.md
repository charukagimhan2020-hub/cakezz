# c3-anomaly-detection (Nihara)

Isolation Forest that scores one session on four features. Lower score = more anomalous.

```python
import sys; sys.path.insert(0, "rulelock/c3-anomaly-detection")
from scoring import score_session, model_metadata, is_model_loaded, model_status
raw_score, is_anomaly = score_session({"coupon_attempts_per_session": 6, "avg_seconds_between_requests": 3,
                                       "distinct_accounts_same_device": 1, "distinct_addresses_same_phone": 1})
```
- `is_anomaly` = `raw_score < ANOMALY_HOLD_THRESHOLD` (-0.06). c1/c4 use the reject threshold (-0.1) from `model_metadata()["thresholds"]`.
- `model_metadata()` never raises. `model_status()` tries to load and returns `{loaded, path, error}` (this is what `/ready` shows).
- The model file is loaded on the first call. If `model.joblib` is missing, importing still works; `score_session` raises `ModelNotLoadedError("... not found ... run python train_model.py")`.
- **`model.joblib` is not in the repo** (it is in `.gitignore`). Run `python train_model.py` (the Docker build must do it) or set `MODEL_PATH`.

## Env vars
`MODEL_PATH` (default `model.joblib` next to the code), `ANOMALY_HOLD_THRESHOLD` (-0.06), `ANOMALY_REJECT_THRESHOLD` (-0.1). Read when called. A bad value falls back to the default. (The old name `ANOMALY_THRESHOLD` is gone.)

## What c1 must supply for each feature
c1 builds these from `transaction_events` (the shop sends the events, see CONTRACT.md). Same counting as the deployed `routes/events.py`:
| feature | how to count | default if unknown |
|---|---|---|
| `coupon_attempts_per_session` | number of `APPLY_COUPON` events with this `session_id` in the last 30 minutes. The shop sends one per coupon at checkout, before the order is reviewed | 0 |
| `avg_seconds_between_requests` | all events of this `session_id` in the last 30 minutes: (last time - first time) / (count - 1). Fewer than 3 events -> 30. Helper: `features.average_seconds_between_requests(rows, now)` | 30 |
| `distinct_accounts_same_device` | number of different `user_id` among events with this `device_id` in the last 24 hours (at least 1) | 1 |
| `distinct_addresses_same_phone` | number of different `address_hash` among events with this `phone_hash` in the last 24 hours (at least 1). The shop sends `null` hashes when unknown | 1 |

Missing, text, NaN, infinite or bool values become the default; values are clipped to the training range: coupons 0 to 15, seconds 1 to 600, accounts 1 to 8, addresses 1 to 8.

## Honest limits
- **The data is synthetic.** Training sessions, abuse sessions and the labels are all made up by us (`synthetic_data.py`). There is no real shop traffic.
- **The evaluation is circular.** `evaluate.py` and the tests check the model against abuse that we generated with the same assumptions. A good score proves the pipeline works, not that it would catch real abuse.
- **It is close to a rule.** The model flags a session with 3+ accounts on a device, 3+ addresses on a phone, or 4+ coupon attempts a few seconds apart. It also flags many sessions with exactly 2 accounts or 2 addresses (see the numbers).

## Measured numbers (python evaluate.py, scikit-learn 1.8.0 here)
Thresholds: hold < -0.06, reject < -0.1.
| group | n | mean | min | max | % hold or worse | % reject |
|---|---|---|---|---|---|---|
| normal: demo definition (0-2 coupons, 20-90 s, 1 account, 1 address) | 1000 | 0.146 | 0.086 | 0.183 | 0% | 0% |
| normal: broad training mix | 1000 | 0.115 | -0.199 | 0.182 | 8% | 6% |
| abuse: coupon stacking (4-10 attempts, 1-5 s apart) | 200 | -0.123 | -0.137 | -0.090 | 100% | 88% |
| abuse: multi account (3-6 accounts, one device) | 200 | -0.129 | -0.154 | -0.110 | 100% | 100% |
| abuse: COD address farming (3-7 addresses, one phone) | 200 | -0.125 | -0.144 | -0.102 | 100% | 100% |

Precision / recall (abuse = positive, 1000 broad normal vs 600 abuse): hold 0.876 / 1.000; reject 0.901 / 0.960.
Hand-written fixtures: typical customer accept (0.18); customer idle 420 s hold (-0.066); two accounts on one device reject (-0.128); coupon burst, account farming, address farming all reject.
So: the demo normal sessions all stay above -0.06 and all demo abuse falls below it, but the **broad normal mix has 8% hold and 6% reject**, mostly sessions with 2 accounts on a device or 2 addresses on a phone, and some very slow or very fast ones. For the demo, shop with a fresh account and one device.

## What I changed so the model really separates the demo abuse
With the deployed settings (contamination 0.03, normal pauses lognormal sigma 1.0) the model did NOT separate them. Abuse that changes one feature only (coupon stacking alone, multi account alone, address farming alone) scored about 0.0 (between -0.02 and +0.04), never below -0.06. The deployed abuse generator changed all four features at once, so that gap was hidden. Changes:
1. `train_model.py`: `contamination` 0.03 -> **0.13**. Contamination only moves the score offset (the decision threshold of the forest), so it shifts every score down; with the thresholds fixed by the contract (-0.06 / -0.1) this is what puts abuse below them. The cost is the false alarms above. Below about 0.09 the separation disappears, so do not lower it without re-running `evaluate.py`.
2. `train_model.py`: `n_estimators` 100 -> 200 (steadier scores).
3. `synthetic_data.py`: normal pauses `lognormal(log 35, sigma)` sigma 1.0 -> **1.3**, so a customer who pauses a few minutes is not punished as much. Everything else in the normal data is unchanged (poisson 0.8 coupons clipped to 5, 97%/3% for 1 or 2 accounts and addresses).
4. `synthetic_data.py`: abuse is now three separate generators (`generate_coupon_stacking`, `generate_multi_account`, `generate_cod_address_farming`) that each change ONE feature, plus `generate_demo_normal` for the demo definition. `generate_abuse_sessions` mixes the three.
5. Training is still on normal sessions only; thresholds are unchanged.
Scores can differ a little with another scikit-learn version (the repo pins 1.5.1, this check ran on 1.8.0). Re-run `python evaluate.py` and `pytest` after building with the pinned versions.

## Other changes from the deployed code
- `evaluate.py` no longer imports `decision` (that is c4) and no longer compares with One-Class SVM; it prints one table per group, precision/recall at both thresholds, and the fixtures. It never overwrites `model.joblib`.
- `train_model.py` and `scoring.py` use the same `MODEL_PATH` env var (the deployed trainer ignored it).
- `anomaly_scoring.py` is now `scoring.py`; `score_service.py` is now `app.py` (no CORS, no hard-coded origins from another project; added `/ready`).
- Bad session input (None, text, bool) no longer raises.
- The old `anomaly-detection/` folder (legacy copy, Dockerfile, flask-cors) was not copied.

## Run
`pip install -r requirements.txt && python train_model.py && pytest` (15 tests) and `python evaluate.py`. Standalone service: `python app.py` (port 5003): `POST /score`, `GET /health`, `GET /ready`.
