# Executable Line Digital Twin

## What this proves
- Discrete-event simulation (SimPy) with states, queues, starvation, blocking, stochastic micro-stops
- Constraint thinking: line rate = bottleneck rate
- Auditable model: cycle times and MTBF from config, not magic numbers
- Closed-loop with safety rail: what-if → simulated shift stays in limits → human approve → bounded publish
- Calibration page: “twin predicted X, line made Y” with explicit error
- ISA-95 lightweight equipment hierarchy + unified namespace (`PlantA/PackLine01/machine/state`)

## Stack
- Simulator: SimPy (explainable event loop)
- UI: Flask + minimal schematic (not a game engine)
- Storage: in-memory scenarios/approvals (swap for SQLite or MQTT replay)

## Run
```bash
pip install -r requirements.txt
python line_twin.py          # CLI baseline + what-if + calibration
python app.py                # Web UI on :5000
```

## Interview line
“The twin was wrong by 3% on throughput and I left that on the screen. A twin nobody can falsify is a video.”
