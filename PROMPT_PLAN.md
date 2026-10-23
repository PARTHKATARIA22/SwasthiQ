1. Phase 2A (Right Now): Replace backend/agent. py with a complete, self-
contained deterministic NLU + tool-execution state machine (with optional
lightweight LLM polish) and verify locally with a 1-command test script (no server
needed yet).

2. Phase 2B: Update backend/app.py (FastAPI endpoints for /agent/run + UI
dashboard endpoints) and run python runner.py -- repeat 3 and
python grade.py.

3.Phase 3: Create the 8 adversarial test scripts in /adversarial and verify they
pass runner .py.

4. Phase 4: Create the React frontend ( /frontend ) with the exact 2 screens
(Handoff Queue and Conversation Detail).

5. Phase 5: Write DECISIONS. md and README. md.
