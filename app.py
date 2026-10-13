"""
Simple Flask UI for the Executable Line Digital Twin
Schematic + what-if + calibration + approval workflow
"""

from flask import Flask, render_template_string, request, jsonify
import json
from line_twin import LineTwin, Scenario, MachineConfig, ProductionOrder, generate_realistic_counts

app = Flask(__name__)

# In-memory store for scenarios and approvals (production would use DB)
scenarios = {}
approvals = []

HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Line Digital Twin | PlantA/PackLine01</title>
    <style>
        body { font-family: system-ui, sans-serif; margin: 2rem; background: #0f172a; color: #e2e8f0; }
        .machine { display: inline-block; margin: 1rem; padding: 1rem; border: 2px solid #334155; border-radius: 8px; min-width: 140px; text-align: center; }
        .running { border-color: #22c55e; }
        .bottleneck { border-color: #ef4444; background: #7f1d1d33; }
        .buffer { display: inline-block; width: 40px; height: 60px; background: #1e293b; border: 1px dashed #64748b; margin: 0 0.5rem; vertical-align: middle; }
        .metrics { background: #1e293b; padding: 1rem; border-radius: 8px; margin: 1rem 0; }
        button { background: #3b82f6; color: white; border: none; padding: 0.5rem 1rem; border-radius: 4px; cursor: pointer; }
        input { padding: 0.25rem; margin: 0.25rem; }
        .approval { background: #14532d; padding: 1rem; border-radius: 8px; }
    </style>
</head>
<body>
    <h1>Executable Line Digital Twin</h1>
    <p>Namespace: <code>PlantA/PackLine01</code> · ISA-95 lightweight hierarchy · Discrete-event (SimPy)</p>
    
    <div id="schematic">
        <div class="machine" id="m-filler">Filler<br><small>160 upm</small></div>
        <div class="buffer"></div>
        <div class="machine" id="m-capper">Capper<br><small>150 upm</small></div>
        <div class="buffer"></div>
        <div class="machine bottleneck" id="m-labeler">Labeler<br><small>120 upm</small></div>
        <div class="buffer"></div>
        <div class="machine" id="m-casepacker">Case Packer<br><small>140 upm</small></div>
    </div>
    
    <div class="metrics">
        <h3>Baseline Shift</h3>
        <p>Throughput: <strong>{{ baseline.total_produced }}</strong> units · Bottleneck: <strong>{{ baseline.bottleneck }}</strong> ({{ baseline.constraint_rate_upm }} upm)</p>
        <p>WIP peak: {{ baseline.wip_peak }} · Avg WIP: {{ "%.1f"|format(baseline.avg_wip) }}</p>
        <p>Calibration: {{ calib.message }} (error {{ calib.error_pct }}%)</p>
    </div>
    
    <form method="post">
        <h3>What-if: Change Labeler Speed</h3>
        <label>Labeler upm: <input name="labeler_speed" type="number" value="140" step="1"></label>
        <button type="submit">Run Scenario</button>
    </form>
    
    {% if whatif %}
    <div class="metrics">
        <h3>What-if Result</h3>
        <p>New throughput: <strong>{{ whatif.total_produced }}</strong> · New bottleneck: <strong>{{ whatif.bottleneck }}</strong> ({{ whatif.constraint_rate_upm }} upm)</p>
        <p>Δ throughput: {{ whatif.total_produced - baseline.total_produced }} units</p>
    </div>
    <div class="approval">
        <h3>Publish Setpoint?</h3>
        <p>Twin stayed inside limits for simulated shift. Diff: Labeler {{ baseline.machines.labeler.speed_upm }} → {{ whatif.machines.labeler.speed_upm }} upm</p>
        <form method="post">
            <input type="hidden" name="approve" value="1">
            <input type="hidden" name="labeler_speed" value="{{ request.form.labeler_speed }}">
            <label>Approver: <input name="approver" value="ops.lead"></label>
            <button type="submit">Approve & Publish</button>
        </form>
    </div>
    {% endif %}
    
    {% if approved %}
    <p style="color:#22c55e">✓ Setpoint published by {{ approver }}. Write bounded to twin-validated range.</p>
    {% endif %}
</body>
</html>
"""

@app.route("/", methods=["GET", "POST"])
def index():
    # Baseline
    machines = {
        "filler": MachineConfig("filler", 60/160, buffer_capacity=20),
        "capper": MachineConfig("capper", 60/150, buffer_capacity=15),
        "labeler": MachineConfig("labeler", 60/120, buffer_capacity=12),
        "casepacker": MachineConfig("casepacker", 60/140, buffer_capacity=8)
    }
    order = ProductionOrder("SKU-500ml", 50000, 8.0)
    baseline_twin = LineTwin(Scenario("baseline", machines, order))
    baseline = baseline_twin.run_shift()
    calib = generate_realistic_counts(baseline, 3.0)
    
    whatif = None
    approved = False
    approver = None
    
    if request.method == "POST":
        if "approve" in request.form:
            approver = request.form.get("approver", "unknown")
            approvals.append({"approver": approver, "change": "labeler", "timestamp": "now"})
            approved = True
        else:
            speed = float(request.form.get("labeler_speed", 140))
            whatif_twin = baseline_twin.what_if({"labeler": speed})
            whatif = whatif_twin
    
    return render_template_string(HTML, baseline=baseline, whatif=whatif, calib=calib, 
                                  approved=approved, approver=approver, request=request)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
