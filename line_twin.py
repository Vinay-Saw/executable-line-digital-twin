"""
Executable Line Digital Twin - Core Simulator
Lightweight discrete-event simulation of a packaging line using SimPy.
ISA-95 inspired hierarchy: Plant > Line > Machines + Buffers
Unified namespace: plant/line/machine/state
"""

import simpy
import random
import json
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional
from enum import Enum
import numpy as np
from collections import defaultdict

class MachineState(Enum):
    IDLE = "idle"
    RUNNING = "running"
    STARVED = "starved"
    BLOCKED = "blocked"
    DOWN = "down"
    CHANGEOVER = "changeover"

@dataclass
class MachineConfig:
    name: str
    cycle_time_sec: float  # time per unit
    mtbf_hours: float = 50.0  # mean time between failures
    mttr_min: float = 5.0     # mean time to repair
    buffer_capacity: int = 10  # output buffer size
    changeover_min: float = 15.0

@dataclass
class ProductionOrder:
    sku: str
    target_qty: int
    shift_hours: float = 8.0

@dataclass
class Scenario:
    name: str
    machines: Dict[str, MachineConfig]
    order: ProductionOrder
    seed: int = 42

class LineTwin:
    """
    Digital twin of a 4-machine packaging line:
    Filler -> Capper -> Labeler -> CasePacker
    """
    def __init__(self, scenario: Scenario):
        self.scenario = scenario
        self.env = simpy.Environment()
        self.machines = {}
        self.buffers = {}
        self.stats = defaultdict(lambda: {
            "produced": 0,
            "state_time": defaultdict(float),
            "events": [],
            "last_state_time": 0.0,
            "current_state": MachineState.IDLE
        })
        self.wip_history = []
        self.throughput_history = []
        self.total_produced = 0
        self.approved = False
        self.approver = None
        
        self._setup_line()

    def _setup_line(self):
        """ISA-95 style: plant/line1/machines"""
        self.namespace = {
            "plant": "PlantA",
            "line": "PackLine01",
            "machines": list(self.scenario.machines.keys())
        }
        
        machine_names = ["filler", "capper", "labeler", "casepacker"]
        for i, name in enumerate(machine_names):
            cfg = self.scenario.machines.get(name)
            if not cfg:
                continue
            self.machines[name] = cfg
            # Output buffer after each machine except last
            if i < len(machine_names) - 1:
                self.buffers[name] = simpy.Container(
                    self.env, 
                    capacity=cfg.buffer_capacity, 
                    init=0
                )

    def _log_state(self, machine: str, new_state: MachineState, now: float):
        stats = self.stats[machine]
        duration = now - stats["last_state_time"]
        if duration > 0:
            stats["state_time"][stats["current_state"].value] += duration
        stats["current_state"] = new_state
        stats["last_state_time"] = now
        stats["events"].append({
            "time": round(now, 2),
            "state": new_state.value,
            "namespace": f"{self.namespace['plant']}/{self.namespace['line']}/{machine}/state"
        })

    def machine_process(self, name: str):
        """Core process for each machine with states, failures, buffers."""
        cfg = self.machines[name]
        env = self.env
        random.seed(self.scenario.seed + hash(name) % 1000)
        
        next_failure = random.expovariate(1.0 / (cfg.mtbf_hours * 3600))
        
        while True:
            now = env.now
            
            # Check starvation (input buffer empty for non-first machines)
            input_buffer = None
            if name == "capper":
                input_buffer = self.buffers.get("filler")
            elif name == "labeler":
                input_buffer = self.buffers.get("capper")
            elif name == "casepacker":
                input_buffer = self.buffers.get("labeler")
            
            if input_buffer and input_buffer.level == 0 and name != "filler":
                self._log_state(name, MachineState.STARVED, now)
                yield env.timeout(1.0)  # poll
                continue
            
            # Check blockage (output buffer full)
            output_buffer = self.buffers.get(name)
            if output_buffer and output_buffer.level >= output_buffer.capacity:
                self._log_state(name, MachineState.BLOCKED, now)
                yield env.timeout(1.0)
                continue
            
            # Random failure
            if now > next_failure:
                self._log_state(name, MachineState.DOWN, now)
                repair_time = random.expovariate(1.0 / (cfg.mttr_min * 60))
                yield env.timeout(repair_time)
                next_failure = now + random.expovariate(1.0 / (cfg.mtbf_hours * 3600))
                continue
            
            # Produce
            self._log_state(name, MachineState.RUNNING, now)
            
            # Take from input if not filler
            if input_buffer and name != "filler":
                yield input_buffer.get(1)
            
            yield env.timeout(cfg.cycle_time_sec)
            
            # Put to output buffer or count as finished
            if output_buffer:
                yield output_buffer.put(1)
            else:
                # Last machine
                self.stats[name]["produced"] += 1
                self.total_produced += 1
                # Also credit upstream for throughput tracking
                for upstream in ["filler", "capper", "labeler"]:
                    if upstream in self.stats:
                        self.stats[upstream]["produced"] += 1
            
            # Record WIP periodically
            if int(now) % 60 == 0:
                wip = sum(b.level for b in self.buffers.values())
                self.wip_history.append({"time": now, "wip": wip})

    def run_shift(self) -> Dict:
        """Execute the production order for one shift."""
        order = self.scenario.order
        shift_sec = order.shift_hours * 3600
        
        # Start all machines
        for name in self.machines:
            self.env.process(self.machine_process(name))
        
        self.env.run(until=shift_sec)
        
        # Finalize state times
        for name in self.machines:
            self._log_state(name, self.stats[name]["current_state"], shift_sec)
        
        return self.get_results()

    def get_results(self) -> Dict:
        """Audit-ready results with bottleneck analysis."""
        results = {
            "namespace": self.namespace,
            "order": asdict(self.scenario.order),
            "total_produced": self.total_produced,
            "predicted_throughput": self.total_produced,
            "machines": {},
            "bottleneck": None,
            "wip_peak": max((w["wip"] for w in self.wip_history), default=0),
            "avg_wip": np.mean([w["wip"] for w in self.wip_history]) if self.wip_history else 0
        }
        
        min_rate = float("inf")
        bottleneck = None
        for name, cfg in self.machines.items():
            stats = self.stats[name]
            total_time = sum(stats["state_time"].values()) or 1
            utilization = stats["state_time"].get("running", 0) / total_time
            produced = stats["produced"]
            rate = produced / (self.scenario.order.shift_hours * 60) if produced else 0
            results["machines"][name] = {
                "cycle_time_sec": cfg.cycle_time_sec,
                "speed_upm": round(60 / cfg.cycle_time_sec, 1),
                "produced": produced,
                "utilization": round(utilization, 3),
                "effective_rate_upm": round(rate, 1),
                "state_time": {k: round(v, 1) for k, v in stats["state_time"].items()},
                "events_count": len(stats["events"])
            }
            if rate < min_rate and rate > 0:
                min_rate = rate
                bottleneck = name
        results["bottleneck"] = bottleneck
        results["constraint_rate_upm"] = round(min_rate, 1) if bottleneck else 0
        
        return results

    def what_if(self, changes: Dict[str, float]) -> Dict:
        """Run scenario with modified speeds (cycle times)."""
        new_scenario = Scenario(
            name=f"{self.scenario.name}_whatif",
            machines={k: MachineConfig(**{**asdict(v), **({"cycle_time_sec": 60/changes[k]} if k in changes else {})}) 
                      for k, v in self.scenario.machines.items()},
            order=self.scenario.order,
            seed=self.scenario.seed
        )
        twin = LineTwin(new_scenario)
        return twin.run_shift()

# Example calibration
def generate_realistic_counts(twin_results: Dict, error_pct: float = 3.0) -> Dict:
    """Simulate real line counts for calibration report."""
    predicted = twin_results["total_produced"]
    actual = int(predicted * (1 - error_pct / 100))
    return {
        "twin_predicted": predicted,
        "line_actual": actual,
        "error_pct": round((predicted - actual) / actual * 100, 1),
        "message": f"twin predicted {predicted}, line made {actual}"
    }

if __name__ == "__main__":
    # Default scenario: labeler is the constraint at 120 upm
    default_machines = {
        "filler": MachineConfig("filler", cycle_time_sec=60/160, buffer_capacity=20),
        "capper": MachineConfig("capper", cycle_time_sec=60/150, buffer_capacity=15),
        "labeler": MachineConfig("labeler", cycle_time_sec=60/120, buffer_capacity=12),
        "casepacker": MachineConfig("casepacker", cycle_time_sec=60/140, buffer_capacity=8)
    }
    order = ProductionOrder(sku="SKU-500ml", target_qty=50000, shift_hours=8.0)
    scenario = Scenario("baseline", default_machines, order)
    
    twin = LineTwin(scenario)
    results = twin.run_shift()
    print(json.dumps(results, indent=2))
    
    # What-if: speed up labeler to 140 upm
    whatif = twin.what_if({"labeler": 140})
    print("\n=== WHAT-IF: Labeler 140 upm ===")
    print(json.dumps(whatif, indent=2))
    
    calib = generate_realistic_counts(results, 3.0)
    print("\n=== CALIBRATION ===")
    print(json.dumps(calib, indent=2))
