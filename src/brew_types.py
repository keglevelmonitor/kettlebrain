"""
src/brew_types.py
Defines the states and data structures for the brewing process.
"""
from enum import Enum, auto

class StepPhase(Enum):
    PENDING = auto()      # Step loaded, waiting to start
    RAMPING = auto()      # Heating to target (Timer PAUSED)
    PROCESSING = auto()   # Target reached (Timer RUNNING)
    COMPLETED = auto()    # Finished

class BrewStep:
    def __init__(self, name, setpoint_f, duration_minutes):
        self.name = name
        self.setpoint = float(setpoint_f)
        self.duration_seconds = int(duration_minutes * 60)
        
        # State tracking
        self.phase = StepPhase.PENDING
        self.time_remaining = self.duration_seconds

    def reset(self):
        self.phase = StepPhase.PENDING
        self.time_remaining = self.duration_seconds
