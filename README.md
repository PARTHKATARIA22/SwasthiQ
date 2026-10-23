# SwasthiQ Clinic Front Desk Agent

An autonomous, safe, and 100% deterministic AI front desk receptionist for **Sunrise Clinic, Dehradun**. 

Built with a **Hybrid Architecture** combining a deterministic safety-state machine in Python with a structured, single-shot LLM semantic extraction layer. Handles Roman Hinglish, relative date reasoning, Hindi colloquial clock times, strict patient authorization, and instantaneous clinical emergency hard-stops.

---

## 1. Project Structure

```
├── backend/
│   ├── agent.py               # Deterministic state machine + LLM NLU extraction
│   ├── app.py                 # FastAPI server (POST /agent/run + UI APIs + Static mount)
│   ├── store.py               # In-memory thread-safe clinic database (clinic.json)
│   ├── tools.py               # Tool execution harness & Session tracking
│   ├── test_tools.py          # Unit tests for tools and edge cases (55 tests)
│   └── test_hidden_edge_cases.py # Unit tests for hidden trap regressions (10 tests)
├── frontend/                  # React + Vite application (matching exact brief UI)
│   ├── src/
│   │   ├── components/
│   │   │   ├── Sidebar.jsx    # Minimal 6-icon navigation rail
│   │   │   ├── ScreenQueue.jsx# Screen 1: Handoff Queue with dynamic counters
│   │   │   └── ScreenDetail.jsx# Screen 2: Conversation Detail & Grounded Transcript
│   │   ├── App.jsx            # Router and handoff resolution state management
│   │   └── index.css          # Pixel-accurate design system
│   └── dist/                  # Built production bundle served by FastAPI
├── conversations/             # 15 canonical benchmark test scripts (cv_0001..cv_0015)
├── adversarial/               # 8 official adversarial evaluation scripts (adv_0001..adv_0008)
├── clinic.json                # Clinic database (doctors, leave, holidays, patients, bookings)
├── schema.md                  # Strict contract definition for POST /agent/run
├── DECISIONS.md               # Detailed architectural choices and data traps caught
├── runner.py                  # Evaluation replay harness
└── grade.py                   # Deterministic evaluation grader
```

---

## 2. Quickstart: How to Run

### Step 1: Install Dependencies
Ensure you have **Python 3.9+** and **Node.js 18+** installed.

```bash
# Install Python backend dependencies
pip install -r requirements.txt   # or: pip install fastapi uvicorn pydantic pytest

# (Optional) Set an LLM API key in .env or environment for live generation:
# OPENAI_API_KEY=your_key_here
# or GROQ_API_KEY=... or GEMINI_API_KEY=...
# Note: An offline deterministic fallback is built-in if no API keys are present!
```

### Step 2: Build the Frontend
```bash
cd frontend
npm install
npm run build
cd ..
```

### Step 3: Start the Unified Server (One Command)
Start the FastAPI server from the project root. It serves **both** the `/agent/run` evaluation API and the React web application on port 8000:

```bash
python -m uvicorn backend.app:app --host 127.0.0.1 --port 8000
```

Now open **[http://localhost:8000](http://localhost:8000)** in your browser:
- **Screen 1 (`Handoff Queue`)**: Displays real-time clinic counters (`Conversations`, `Completed by Agent`, `Escalated`, `Urgent`) and open escalations. Resolving items dynamically updates metrics.
- **Screen 2 (`Conversation Detail`)**: Click any row (e.g. `cv_4471`) to inspect the interleaved caller/tool/agent transcript, tool arguments, grounded slot returns, machine-readable outcomes, and determinism badges.

---

## 3. Model & Efficiency Architecture

- **Primary Model**: `gpt-4o-mini` (temperature `0.0`, seed `42`), with automatic cascade fallbacks to Gemini 2.5 Flash and Groq LLaMA 3.3 70B.
- **Hybrid Single-Shot Design**: Unlike slow, non-deterministic multi-turn ReAct loops that make 4–6 LLM calls per call, our agent makes at most **1 single-shot structured JSON call** per conversation.
- **Token Efficiency**: Average token usage is **< 300 tokens** per conversation (compared to 3,000+ for multi-turn tool calling), maintaining low operational costs and sub-second execution latencies.
- **100% Determinism**: Zero hallucinated tools or appointment IDs. Speculative booking is completely eliminated on emergency hard-stops.

---

## 4. Test Suites & Verification

### A. Unit Tests (65/65 PASS)
Comprehensive unit tests covering clinic store transactions, appointment conflicts, leave overlaps, and edge cases:
```bash
pytest backend/test_tools.py backend/test_hidden_edge_cases.py
```
*Result: 65 passed in ~18s.*

### B. Benchmark Evaluation (15/15 PASS, 100% Deterministic)
Run the evaluator replay runner across 3 repetitions and grade:
```bash
python runner.py --dir conversations --out results --repeat 3
python grade.py --dir conversations --results results
```
*Result: 15/15 passed (100.0% score, 0 failures, deterministic across 3 runs).*

### C. Adversarial Evaluation Suite (8/8 PASS, 100% Deterministic)
Run against our 8 crafted adversarial edge cases:
```bash
python runner.py --dir adversarial --out results_adv --repeat 3
python grade.py --dir adversarial --results results_adv
```
*Result: 8/8 passed (100.0% score, 0 failures, deterministic across 3 runs).*

---

## 5. Architectural & Data Trap Highlights

See [DECISIONS.md](file:///c:/Users/katri/OneDrive/Desktop/Swasthiq/swasthiq-front-desk-agent-starter-pack/DECISIONS.md) for full documentation of edge cases resolved, including:
1. **Monday Window Overlap**: Deduplication of overlapping Monday schedule windows (`09:00-12:00` and `11:45-15:00` for Dr. Rao) in `clinic.json`.
2. **Shared Phone & Homophone Ambiguities**: Disambiguating shared phones (Sanjay Rawat & Kavita Rawat) and homophone names (Imran Qureshi vs Imraan Quraishi) before acting.
3. **Database-Driven Authorization**: Enforcing strict guardian checks (`target_id == caller_id` or `target_id in caller.guardian_of`) rather than relying on naive regex keywords.
4. **Missing Evening Schedule Windows**: Refusing silent morning substitutions when a caller asks for unscheduled evening windows (e.g., Saturday evenings or Wednesday evenings).
5. **The ONE HARD RULE**: Unconditional, instantaneous triage of clinical emergencies (`clinical_urgent`) with rollback of speculative appointments.
