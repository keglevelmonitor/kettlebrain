"""
src/profile_data.py
"""
import uuid
import copy
from enum import Enum

class StepType(Enum):
    STEP = "Step"
    PREP_WATER = "Prep Water"
    DOUGH_IN = "Dough-in"
    MASH = "Mash"
    MASH_OUT = "Mash-out"
    SPARGE = "Sparge"
    BOIL_START = "Boil Start"
    BOIL = "Boil Off"
    CHILL = "Chill"

class TimeoutBehavior(Enum):
    AUTO_ADVANCE = "Auto Advance"
    MANUAL_ADVANCE = "Manual Advance"
    END_PROGRAM = "End Program"

class SequenceStatus(Enum):
    IDLE = "IDLE"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    WAITING_FOR_USER = "WAITING"
    COMPLETED = "COMPLETED"
    MANUAL = "MANUAL"
    DELAYED_WAIT = "DELAY_WAIT"

class BrewAddition:
    def __init__(self, id=None, name="Alert", time_point_min=0, triggered=False):
        self.id = id if id else str(uuid.uuid4())
        self.name = name
        self.time_point_min = time_point_min
        self.triggered = triggered

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "time_point_min": self.time_point_min
        }

class BrewStep:
    def __init__(self, id=None, name="New Step", step_type=StepType.STEP, note="", 
                 setpoint_f=None, duration_min=0.0, target_completion_time=None,
                 ramp_power_watts=None, hold_power_watts=None, # <--- CHANGED
                 timeout_behavior=TimeoutBehavior.MANUAL_ADVANCE, 
                 sg_reading=None, sg_temp_f=None, sg_temp_correction=False, sg_corrected_value=None,
                 lauter_temp_f=None, lauter_volume=None):
        
        self.id = id if id else str(uuid.uuid4())
        self.name = name
        self.step_type = step_type
        self.note = note
        
        # Control Vars
        self.setpoint_f = setpoint_f
        self.duration_min = duration_min
        self.target_completion_time = target_completion_time
        
        # NEW: Dual Power Settings
        self.ramp_power_watts = ramp_power_watts
        self.hold_power_watts = hold_power_watts
        
        self.timeout_behavior = timeout_behavior
        
        # Data Logging
        self.sg_reading = sg_reading
        self.sg_temp_f = sg_temp_f
        self.sg_temp_correction = sg_temp_correction
        self.sg_corrected_value = sg_corrected_value
        
        # Lautering
        self.lauter_temp_f = lauter_temp_f
        self.lauter_volume = lauter_volume
        
        self.additions = []

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "step_type": self.step_type.value,
            "note": self.note,
            "setpoint_f": self.setpoint_f,
            "duration_min": self.duration_min,
            "target_completion_time": self.target_completion_time,
            # NEW KEYS
            "ramp_power_watts": self.ramp_power_watts,
            "hold_power_watts": self.hold_power_watts,
            
            "timeout_behavior": self.timeout_behavior.value,
            "sg_reading": self.sg_reading,
            "sg_temp_f": self.sg_temp_f,
            "sg_temp_correction": self.sg_temp_correction,
            "sg_corrected_value": self.sg_corrected_value,
            "lauter_temp_f": self.lauter_temp_f,
            "lauter_volume": self.lauter_volume,
            "additions": [a.to_dict() for a in self.additions]
        }

class BrewProfile:
    def __init__(self, id=None, name="New Profile", steps=None, water_data=None, chemistry_data=None):
        self.id = id if id else str(uuid.uuid4())
        self.name = name
        self.steps = steps if steps else []
        
        # NEW: Dictionaries to store calculator inputs/results
        self.water_data = water_data if water_data else {}
        self.chemistry_data = chemistry_data if chemistry_data else {}

    def add_step(self, step):
        self.steps.append(step)

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "water_data": self.water_data,
            "chemistry_data": self.chemistry_data,
            "steps": [step.to_dict() for step in self.steps]
        }

    @classmethod
    def from_dict(cls, data):
        # 1. Reconstruct Steps
        steps = []
        for s_data in data.get("steps", []):
            try:
                # Determine Step Type
                st_str = s_data.get("step_type", "Step")
                try:
                    st_enum = StepType(st_str)
                except ValueError:
                    st_enum = StepType.STEP
                
                # Determine Timeout Behavior
                tb_str = s_data.get("timeout_behavior", "Manual Advance")
                try:
                    tb_enum = TimeoutBehavior(tb_str)
                except ValueError:
                    tb_enum = TimeoutBehavior.MANUAL_ADVANCE
                
                # --- BACKWARD COMPATIBILITY LOGIC ---
                # Check for new keys. If missing, look for legacy 'power_watts'.
                # If legacy exists, apply it to BOTH Ramp and Hold.
                legacy_power = s_data.get("power_watts")
                ramp_p = s_data.get("ramp_power_watts")
                hold_p = s_data.get("hold_power_watts")
                
                if ramp_p is None: ramp_p = legacy_power
                if hold_p is None: hold_p = legacy_power

                step = BrewStep(
                    id=s_data.get("id"),
                    name=s_data.get("name", "New Step"),
                    step_type=st_enum,
                    duration_min=s_data.get("duration_min", 0),
                    setpoint_f=s_data.get("setpoint_f", 0), # Corrected key from target_temp to setpoint_f
                    ramp_power_watts=ramp_p, # <--- NEW
                    hold_power_watts=hold_p, # <--- NEW
                    timeout_behavior=tb_enum,
                    sg_reading=s_data.get("sg_reading"),
                    sg_temp_f=s_data.get("sg_temp_f"),
                    sg_temp_correction=s_data.get("sg_temp_correction", False),
                    sg_corrected_value=s_data.get("sg_corrected_value"),
                    lauter_temp_f=s_data.get("lauter_temp_f"),
                    lauter_volume=s_data.get("lauter_volume")
                )
                
                # Rehydrate Additions
                raw_additions = s_data.get("additions", [])
                for add_data in raw_additions:
                    if isinstance(add_data, dict):
                        new_add = BrewAddition(
                            id=add_data.get("id"),
                            name=add_data.get("name", "Alert"),
                            time_point_min=add_data.get("time_point_min", 0),
                            triggered=False
                        )
                        step.additions.append(new_add)
                
                steps.append(step)
            except Exception as e:
                print(f"[ProfileData] Error inflating step: {e}")

        # 2. Rehydrate Water Data (Ensure defaults exist)
        w_data = data.get("water_data", {})
        if "tun_capacity" not in w_data:
            w_data["tun_capacity"] = 10.0 
            
        # 3. Rehydrate Chemistry Data
        c_data = data.get("chemistry_data", {})

        return cls(
            id=data.get("id"),
            name=data.get("name", "New Profile"),
            steps=steps,
            water_data=w_data,
            chemistry_data=c_data
        )
