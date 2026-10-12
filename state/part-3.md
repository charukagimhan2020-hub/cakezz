Status: DONE
Part: 3
Last session: 2026-10-11

## Done (short)
c3 anomaly detection: `features.py`, `synthetic_data.py`, `train_model.py`, `scoring.py`, `evaluate.py`, tiny `app.py` (/score, /health, /ready), 15 tests, README with real numbers and honest limits.

## Files created or changed
rulelock/c3-anomaly-detection/: features.py, synthetic_data.py, train_model.py, scoring.py, evaluate.py, app.py, requirements.txt, .gitignore, README.md, tests/test_c3.py (model.joblib is NOT committed; it is trained at build time)

## Interfaces (exact function signatures / endpoints / tables touched)
`scoring.score_session(features: dict) -> (raw_score: float, is_anomaly: bool)` (is_anomaly = raw < hold threshold)
`scoring.model_metadata() -> dict` (never raises; keys model, loaded, error, trained_at, thresholds{hold,reject}, features, feature_ranges, training_data)
`scoring.is_model_loaded() -> bool`, `scoring.model_status() -> {loaded, path, error}`, `scoring.thresholds() -> {hold, reject}`, `scoring.ModelNotLoadedError`
`features.session_to_features(dict) -> ndarray (1,4)`, `features.average_seconds_between_requests(rows, now)`, `FEATURE_NAMES`
`train_model.train(path=None)`, `train_model.build_model()`; `evaluate.run()`
Standalone: `POST /score`, `GET /health`, `GET /ready` (503 when no model). No tables touched.
Import: put `rulelock/c3-anomaly-detection` on sys.path, then `from scoring import ...`. The module names `features`, `scoring`, `train_model`, `evaluate`, `synthetic_data` are top-level names: Part 5 must avoid clashing names in c1/c2/c4.

## Env vars (name, meaning, default)
MODEL_PATH (model.joblib next to the code), ANOMALY_HOLD_THRESHOLD -0.06, ANOMALY_REJECT_THRESHOLD -0.1 (read at call time; old name ANOMALY_THRESHOLD removed)

## How to run and test (and the test result you actually saw)
`cd rulelock/c3-anomaly-detection && python train_model.py && pytest`. pytest is not installed in this sandbox, so the same test functions were run with a plain-Python runner: 15 passed, 0 failed (scikit-learn 1.8.0, numpy 2.4.4; the pinned requirements are 1.5.1 / 1.26.4, not tested). `python evaluate.py` output is in the README: demo-normal 0% flagged, all demo abuse below -0.06 (max -0.090), normal min +0.086.

## Kept / changed / why (reused teammate code)
Base = deployed `data-collection/` copies (features, train_model, anomaly_scoring, synthetic_data, evaluate). Kept: Isolation Forest, four features, clipping, thresholds from env, training on normal sessions only. Changed (details in README): contamination 0.03 -> 0.13, n_estimators 200, normal pause sigma 1.0 -> 1.3, abuse split into three single-feature generators, evaluate no longer imports c4's decision, one shared MODEL_PATH, bad input no longer raises, CORS and legacy files dropped.

## Decisions (anything you chose because the brief was unclear)
- With the deployed settings the model did not separate single-feature abuse (scores about 0.0). Fixed by contamination 0.13 plus wider normal pauses; the cost is 8% hold / 6% reject on the broad normal mix, mostly sessions with 2 accounts or 2 addresses. Documented in the README.
- The model is trained at build time (Dockerfile in Part 5 must run `python train_model.py`); no model file is committed, so a version mismatch cannot break loading.
- Feature counting for c1 copied from the deployed `routes/events.py` (30 minute session window; 24 h for device and phone).

## Known issues
- Real pytest and the pinned scikit-learn 1.5.1 were not run here. Scores can shift slightly: re-run `python evaluate.py` and `pytest` after the first build.
- A customer idle about 7 minutes scores -0.066 (hold). A shared device with 2 accounts scores about -0.13 (reject, which c4 turns into a 30 minute rate limit). Keep demo accounts to one per device.

## Requests to other parts
- Part 5 (c1): build the four features as in this folder's README; c1's Dockerfile must run `python rulelock/c3-anomaly-detection/train_model.py` (or set MODEL_PATH) during the build; call `scoring.model_status()` in `/ready`.
- Part 4 (c4): reject threshold is `scoring.thresholds()["reject"]`; c3 only returns `(raw_score, is_anomaly)` where is_anomaly means hold or worse.
- Part 0 / Part 5 (`rulelock/.env.example`): add MODEL_PATH (optional); ANOMALY_HOLD_THRESHOLD and ANOMALY_REJECT_THRESHOLD names are already right.

## Next step (only if PARTIAL: exact file and function to continue from)
(not partial)
