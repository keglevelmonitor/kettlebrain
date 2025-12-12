"""
kettlebrain app
profile_data.py
"""
from dataclasses import dataclass, field, asdict
from typing import List, Optional
from enum import Enum
import uuid

# --- Enums for Logic Control ---

class StepType(str, Enum):
    # Actions (Hardware Control)
    DELAYED_START = "Delayed Start" 
    STEP = "Step"                   
    MASH = "Mash"                   
    MASH_OUT = "Mash-out"           
    BOIL = "Boil" 
    CHILL = "Chill"  # <--- NEW ACTION ADDED

class TimeoutBehavior(str, Enum):
    AUTO_ADVANCE = "Auto Advance"
    MANUAL_ADVANCE = "Manual Advance" 
    END_PROGRAM = "End Profile"       

class SequenceStatus(str, Enum):
    IDLE = "Idle"
    RUNNING = "Running"
    PAUSED = "Paused"
    WAITING_FOR_USER = "Waiting for User"
    COMPLETED = "Completed"

# --- Process Additions ---

@dataclass
class BrewAddition:
    """
    Represents an event that happens DURING a step (e.g. Hops at 60min).
    """
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    name: str = "New Addition"
    time_point_min: int = 0  # Minutes REMAINING when this triggers
    triggered: bool = False  # Runtime flag

# --- Main Data Class ---

@dataclass
class BrewStep:
    """
    Represents a single step in a brewing profile.
    """
    # Identifiers
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    name: str = "New Step"
    step_type: StepType = StepType.STEP
    note: str = ""
    
    # --- ACTION FIELDS ---
    setpoint_f: Optional[float] = None  
    
    # --- TIMING FIELDS ---
    duration_min: float = 0.0
    target_completion_time: Optional[str] = None
    
    # --- POWER / VOLUME ---
    power_watts: Optional[int] = None 
    lauter_volume: Optional[float] = None
    lauter_temp_f: Optional[float] = None

    # What happens when the timer hits zero?
    timeout_behavior: TimeoutBehavior = TimeoutBehavior.MANUAL_ADVANCE

    # --- ADDITIONS LIST ---
    additions: List[BrewAddition] = field(default_factory=list)

    # --- ACTIVITY RESULT FIELDS (For Logging) ---
    sg_reading: Optional[float] = None
    sg_temp_f: Optional[float] = None
    sg_temp_correction: bool = False
    sg_corrected_value: Optional[float] = None
    
    # Runtime fields (not saved)
    time_remaining: float = 0.0
    
    def reset(self):
        """Resets runtime flags for a fresh run."""
        self.time_remaining = self.duration_min * 60
        for a in self.additions:
            a.triggered = False

    def to_dict(self):
        return asdict(self)

@dataclass
class BrewProfile:
    """
    A collection of steps comprising a full recipe/schedule.
    """
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = "New Profile"
    created_date: str = "" 
    steps: List[BrewStep] = field(default_factory=list)

    def add_step(self, step: BrewStep):
        self.steps.append(step)
        
    def remove_step(self, step_id: str):
        self.steps = [s for s in self.steps if s.id != step_id]

    def reorder_steps(self, new_order_ids: List[str]):
        step_map = {s.id: s for s in self.steps}
        new_steps = []
        for uid in new_order_ids:
            if uid in step_map:
                new_steps.append(step_map[uid])
        
        if len(new_steps) < len(self.steps):
            for s in self.steps:
                if s.id not in new_order_ids:
                    new_steps.append(s)
                    
        self.steps = new_steps
