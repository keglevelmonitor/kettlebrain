"""
kettlebrain/src/sequence_manager.py
"""
import time
import threading
import math
from profile_data import BrewProfile, StepType, TimeoutBehavior, SequenceStatus

class SequenceManager:
    def __init__(self, settings_manager, relay_control, hardware_interface):
        self.settings = settings_manager
        self.relay = relay_control 
        self.hw = hardware_interface
        
        # State
        self.current_profile = None
        self.current_step_index = -1
        self.status = SequenceStatus.IDLE
        
        # Timing (Using monotonic for precision)
        self.step_start_time = 0.0
        self.total_paused_time = 0.0
        self.last_pause_start = 0.0
        self.step_elapsed_time = 0.0
        
        # Logic Flags
        self.temp_reached = False 
        
        self.current_temp = 0.0
        self.target_temp = 0.0
        self.is_heating = False
        
        # Alerting
        self.current_alert_text = None
        
        # Background Thread
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._control_loop, daemon=True)
        self._thread.start()

    def load_profile(self, profile: BrewProfile):
        self.stop()
        self.current_profile = profile
        self.current_step_index = 0
        self.status = SequenceStatus.IDLE
        print(f"[Sequence] Loaded profile: {profile.name}")

    def start_sequence(self):
        if not self.current_profile: return
        if self.status == SequenceStatus.IDLE:
            self.current_step_index = 0
            self._init_step(self.current_step_index)
            self.status = SequenceStatus.RUNNING
            print("[Sequence] Started.")

    def pause_sequence(self):
        if self.status == SequenceStatus.RUNNING:
            self.status = SequenceStatus.PAUSED
            self.last_pause_start = time.monotonic()
            self.relay.turn_off_all_relays() 
            self.is_heating = False

    def resume_sequence(self):
        if self.status in [SequenceStatus.PAUSED, SequenceStatus.WAITING_FOR_USER]:
            # Calculate how long we were paused
            if self.last_pause_start > 0:
                paused_duration = time.monotonic() - self.last_pause_start
                self.total_paused_time += paused_duration
                self.last_pause_start = 0
            
            self.current_alert_text = None # Clear alerts on resume
            self.status = SequenceStatus.RUNNING

    def stop(self):
        self.status = SequenceStatus.IDLE
        self.current_step_index = -1
        self.relay.turn_off_all_relays()
        self.is_heating = False
        self.current_alert_text = None

    def advance_step(self):
        """Manually force next step."""
        if not self.current_profile: return
        
        # If we were paused/waiting, handle the timing cleanup first
        if self.status in [SequenceStatus.PAUSED, SequenceStatus.WAITING_FOR_USER]:
             self.resume_sequence()

        next_idx = self.current_step_index + 1
        
        if next_idx < len(self.current_profile.steps):
            # --- THREAD SAFETY FIX ---
            # Reset flags BEFORE updating the index. 
            # This prevents the background thread from seeing the new index 
            # while the old "completed" flags are still active.
            self.temp_reached = False
            self.step_start_time = 0.0
            
            self.current_step_index = next_idx
            self._init_step(next_idx)
        else:
            self._complete_sequence()

    def _complete_sequence(self):
        self.status = SequenceStatus.COMPLETED
        self.relay.turn_off_all_relays()
        self.is_heating = False
        print("[Sequence] Brew Complete.")

    def _init_step(self, index):
        step = self.current_profile.steps[index]
        print(f"[Sequence] Init Step {index}: {step.name}")
        
        # Reset Timing & Logic
        self.step_start_time = 0.0 # Will be set once temp is reached
        self.total_paused_time = 0.0
        self.last_pause_start = 0.0
        self.step_elapsed_time = 0.0
        self.temp_reached = False # Assume we are not at temp yet
        
        # Determine Target Temp
        if step.setpoint_f is not None:
            self.target_temp = step.setpoint_f
        elif step.lauter_temp_f is not None:
            self.target_temp = step.lauter_temp_f
        else:
            self.target_temp = 0.0
            
        # Reset Triggers
        if hasattr(step, 'additions'):
            for add in step.additions:
                add.triggered = False
        self.current_alert_text = None

    def update(self):
        pass 

    def _control_loop(self):
        """Main PID/Logic Thread"""
        while not self._stop_event.is_set():
            time.sleep(0.1) 
            
            try:
                self.current_temp = self.hw.read_temperature()
            except:
                self.current_temp = 0.0

            if self.status == SequenceStatus.RUNNING:
                if not self.current_profile: continue
                
                step = self.current_profile.steps[self.current_step_index]
                self._process_step_logic(step)
                
            elif self.status == SequenceStatus.WAITING_FOR_USER:
                self.relay.turn_off_all_relays()
                self.is_heating = False

    def _process_step_logic(self, step):
        # --- A. Temperature Control ---
        heat_needed = False
        
        # 1. Determine Heat Demand based on Step Type
        if step.step_type == StepType.BOIL:
            if step.power_watts and step.power_watts > 0:
                heat_needed = True
            
            # BOIL LOGIC: Wait for User's Setpoint (or 212F default)
            if not self.temp_reached:
                 # If user entered a specific boil temp (e.g. 202F for altitude), use it.
                 # Otherwise default to 212.0F.
                 boil_target = step.setpoint_f if step.setpoint_f else 212.0
                 
                 if self.current_temp >= boil_target:
                     print(f"[Sequence] Boil Target ({boil_target}F) reached. Starting Timer.")
                     self.temp_reached = True
                     self.step_start_time = time.monotonic()
        
        elif step.step_type == StepType.CHILL:
            # CHILL LOGIC: Heaters OFF
            heat_needed = False
            
            # Timer Logic: Wait for temp to DROP
            if not self.temp_reached:
                # Trigger if current <= target (plus small buffer)
                if self.current_temp <= (self.target_temp + 1.0):
                    print(f"[Sequence] Chill Target {self.target_temp} reached. Starting Timer.")
                    self.temp_reached = True
                    self.step_start_time = time.monotonic()

        elif self.target_temp > 0:
            # STANDARD HEATING LOGIC (Mash, Heat, etc.)
            # Hysteresis
            if self.current_temp < (self.target_temp - 0.5):
                heat_needed = True
            elif self.current_temp > self.target_temp:
                heat_needed = False
            else:
                heat_needed = self.is_heating 
            
            # Check if we have reached temp for the first time
            if not self.temp_reached:
                # Timer only starts if we are AT or ABOVE target.
                if self.current_temp >= self.target_temp:
                    print(f"[Sequence] Target {self.target_temp} reached. Starting Timer.")
                    self.temp_reached = True
                    self.step_start_time = time.monotonic()

        else:
            # Steps with no target temp (like specific rests) start immediately
            if not self.temp_reached:
                self.temp_reached = True
                self.step_start_time = time.monotonic()
        
        # Apply Relay State
        self.is_heating = heat_needed
        if heat_needed:
            self.relay.set_relays(True, True, False)
        else:
            self.relay.set_relays(False, False, False)

        # --- B. Timer Logic ---
        
        # If we haven't reached temp yet, DO NOT increment elapsed time
        if not self.temp_reached:
            self.step_elapsed_time = 0
            return 

        # Now we are running (Temp Reached)
        now = time.monotonic()
        self.step_elapsed_time = now - self.step_start_time - self.total_paused_time
        
        # Handle Duration (Explicitly allow 0.0)
        duration_val = step.duration_min if step.duration_min is not None else 0.0
        duration_sec = duration_val * 60.0
        
        remaining_sec = duration_sec - self.step_elapsed_time
        remaining_min = remaining_sec / 60.0

        # --- C. GATEKEEPER: Check Actions/Additions ---
        
        if hasattr(step, 'additions'):
            for add in step.additions:
                if not add.triggered:
                    
                    should_trigger = False
                    
                    # Logic 1: Standard Time Check
                    # "Trigger if remaining time is less than X" (with small buffer)
                    if remaining_min <= (add.time_point_min + 0.005):
                        should_trigger = True
                        
                    # Logic 2: Zero-Duration Override
                    # If the step is 0 minutes long, ALL actions are due immediately.
                    # We force trigger them to ensure they aren't skipped.
                    if duration_val <= 0.0:
                        should_trigger = True

                    if should_trigger:
                        # TRIGGER ACTION
                        add.triggered = True 
                        self.status = SequenceStatus.WAITING_FOR_USER
                        self.current_alert_text = add.name
                        
                        # PAUSE LOGIC
                        # If we are at the very start (first 1 sec) OR the step is 0 duration,
                        # we must "Pause" the internal clock so it doesn't tick past 0
                        # while the user is acknowledging.
                        if self.step_elapsed_time < 1.0 or duration_val <= 0.0:
                             self.last_pause_start = time.monotonic()
                             print(f"[Sequence] Start Action '{add.name}': Timer PAUSED")
                        else:
                             # Mid-step action: Let timer run (Yellow Mode)
                             # We DO NOT set last_pause_start here.
                             print(f"[Sequence] Mid Action '{add.name}': Timer CONTINUES")

                        # Stop processing so we wait for user response
                        return

        # --- D. Step Completion ---
        
        # Check if time is up
        if self.step_elapsed_time >= duration_sec:
            
            # FINAL SAFETY CHECK:
            # Do not allow completion if there are still un-triggered additions.
            # This handles the case where multiple 0-min actions exist.
            if hasattr(step, 'additions'):
                if any(not a.triggered for a in step.additions):
                    return 

            # Proceed to Finish Step
            if step.timeout_behavior == TimeoutBehavior.AUTO_ADVANCE:
                self.advance_step()
            else:
                self.status = SequenceStatus.WAITING_FOR_USER
                self.last_pause_start = time.monotonic()
                self.current_alert_text = "Step Complete"
            return
                        
    # --- Data Access for UI ---
    
    def get_display_timer(self):
        if not self.current_profile: return "00:00"
        if self.status in [SequenceStatus.IDLE, SequenceStatus.COMPLETED]: return "00:00"

        # Show full duration while heating
        if self.status == SequenceStatus.RUNNING and not self.temp_reached:
             step = self.current_profile.steps[self.current_step_index]
             total = int(step.duration_min * 60)
             m = total // 60
             s = total % 60
             return f"{m:02d}:{s:02d}"

        step = self.current_profile.steps[self.current_step_index]
        total_sec = step.duration_min * 60.0
        
        # Determine if we should show "Live" time or "Frozen" time
        is_live = False
        if self.status == SequenceStatus.RUNNING:
            is_live = True
        elif self.status == SequenceStatus.WAITING_FOR_USER:
            if self.last_pause_start == 0:
                is_live = True

        if is_live:
            current_elapsed = time.monotonic() - self.step_start_time - self.total_paused_time
            rem = total_sec - current_elapsed
            if rem < 0: rem = 0 
        else:
            if self.last_pause_start > 0:
                current_elapsed = self.last_pause_start - self.step_start_time - self.total_paused_time
                rem = max(0, total_sec - current_elapsed)
            else:
                rem = max(0, total_sec - self.step_elapsed_time)
            
        # --- FIX: USE CEILING FOR SMOOTH COUNTDOWN ---
        # This ensures 5.9s shows as "06" and 5.1s shows as "06", 
        # snapping to "05" only when we truly cross the integer threshold.
        val = math.ceil(rem)
        
        m = int(val // 60)
        s = int(val % 60)
        return f"{m:02d}:{s:02d}"

    def get_status_message(self):
        if self.status == SequenceStatus.IDLE: return "Ready"
        if self.status == SequenceStatus.COMPLETED: return "Brew Complete"
        
        step = self.current_profile.steps[self.current_step_index]
        
        if self.status == SequenceStatus.RUNNING and not self.temp_reached:
            return f"HEATING - {step.name}"

        base_status = f"Step {self.current_step_index+1}: {step.name}"
        
        if self.status == SequenceStatus.PAUSED:
            return f"PAUSED - {base_status}"
        elif self.status == SequenceStatus.WAITING_FOR_USER:
            if self.current_alert_text:
                 if self.current_alert_text == "Step Complete":
                     return f"DONE: {step.name}"
                 return f"ALERT: {self.current_alert_text}"
            return f"WAITING - {base_status}"
            
        return base_status

    def get_target_temp(self):
        return self.target_temp

    def get_upcoming_additions(self):
        if not self.current_profile or self.status == SequenceStatus.IDLE: return ""
        step = self.current_profile.steps[self.current_step_index]
        if not hasattr(step, 'additions') or not step.additions: return ""
        
        sorted_adds = sorted(step.additions, key=lambda x: x.time_point_min, reverse=True)
        
        for add in sorted_adds:
            if not add.triggered:
                 return f"Next: {add.name} @ {add.time_point_min}m"
        return "No more alerts"
