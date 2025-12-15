"""
src/profile_data.py
"""
import uuid
import copy
from enum import Enum

class StepType(Enum):
    STEP = "Step"
    MASH = "Mash"
    MASH_OUT = "Mash-out"
    BOIL = "Boil"
    CHILL = "Chill"
    # DELAYED_START Removed

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
    # --- NEW STATES ---
    MANUAL = "MANUAL"           # Manual Mode Active
    DELAYED_WAIT = "DELAY_WAIT" # Sleeping/Waiting for start time

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
                 power_watts=None, timeout_behavior=TimeoutBehavior.MANUAL_ADVANCE, 
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
        self.power_watts = power_watts
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
            "power_watts": self.power_watts,
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
    def __init__(self, id=None, name="New Profile", steps=None):
        self.id = id if id else str(uuid.uuid4())
        self.name = name
        self.steps = steps if steps else []

    def add_step(self, step):
        self.steps.append(step)

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "steps": [step.to_dict() for step in self.steps]
        }

    @classmethod
    def from_dict(cls, data):
        profile = cls(
            id=data.get("id"),
            name=data.get("name", "Unknown Profile")
        )
        return profile
