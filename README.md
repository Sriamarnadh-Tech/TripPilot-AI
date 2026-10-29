# AdaptiveTrip
Evidence-Aware Adaptive Travel Planning under Sequential Disruptions

## Run backend (PowerShell)
```powershell
cd backend
py -3.10 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload
```
Docs: http://127.0.0.1:8000/docs

## Run frontend (second terminal)
```powershell
cd frontend
npm install
npm run dev
```
Open the Vite URL, normally http://localhost:5173.

## Evaluation
From `backend`, with the venv active:
`python -m app.evaluation`

This prototype uses synthetic disruptions and illustrative activities/costs. It does not authenticate sources or connect live weather, attraction, or routing APIs. Research claims must be based on measured experiments, not the demo output.
