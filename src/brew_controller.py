# brew_controller.py
import time
from brew_types import StepPhase, BrewStep
from hardware_interface import HardwareInterface

class BrewController:
    def __init__(self, hardware: HardwareInterface):
        self.hw = hardware
        self.current_step = None
        self.current_temp = 0.0
        self.is_running = False

    def load_step(self, step: BrewStep):
        """Loads a step but does not start it immediately."""
        self.current_step = step
        self.current_step.reset()
        print(f"LOADED STEP: {step.name} (Setpoint: {step.setpoint}F, Time: {step.duration_seconds/60}m)")

    def start_brew(self):
        if self.current_step:
            self.is_running = True
            # Initial state is RAMPING (Heating up)
            self.current_step.phase = StepPhase.RAMPING
            print("BREW STARTED. Phase: RAMPING")

    def stop_brew(self):
        self.is_running = False
        self.hw.set_heater_output(False)
        print("BREW STOPPED.")

    def tick(self):
        """
        Main Loop: Call this function every 1 second (or 100ms).
        """
        if not self.is_running:
            return

        # 1. READ INPUTS (Virtual or Real)
        self.current_temp = self.hw.read_temperature()

        # 2. PROCESS LOGIC
        if self.current_step:
            self._process_step_logic()

        # 3. CONTROL HEATER (Simple Hysteresis/Bang-Bang for this example)
        # In a real app, replace this block with your PID Library
        if self.current_step and self.current_step.phase in [StepPhase.RAMPING, StepPhase.PROCESSING]:
            if self.current_temp < self.current_step.setpoint:
                self.hw.set_heater_output(True)
            else:
                self.hw.set_heater_output(False)
        else:
            self.hw.set_heater_output(False)

    def _process_step_logic(self):
        step = self.current_step

        # --- PHASE 1: RAMPING ---
        if step.phase == StepPhase.RAMPING:
            # Check if we hit the target
            if self.current_temp >= step.setpoint:
                print(f"!!! TARGET REACHED ({self.current_temp}F). STARTING TIMER !!!")
                step.phase = StepPhase.PROCESSING
            else:
                # We are still heating. Timer is effectively PAUSED.
                pass

        # --- PHASE 2: PROCESSING ---
        elif step.phase == StepPhase.PROCESSING:
            # OPTION B: The "Latch" Logic.
            # We do NOT check temperature here. Timer runs regardless of temp drops.
            
            if step.time_remaining > 0:
                step.time_remaining -= 1
                # Optional: formatted print for debugging
                if step.time_remaining % 5 == 0: # Print every 5 ticks to reduce spam
                    print(f"PROCESSING: {step.time_remaining}s remaining... (Temp: {self.current_temp}F)")
            else:
                self._complete_step()

        # --- PHASE 3: COMPLETED ---
        elif step.phase == StepPhase.COMPLETED:
            self.is_running = False
            self.hw.set_heater_output(False)

    def _complete_step(self):
        print(f"STEP '{self.current_step.name}' FINISHED.")
        self.current_step.phase = StepPhase.COMPLETED
        # Logic to trigger next step would go here
