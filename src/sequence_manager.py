"""
kettlebrain/src/sequence_manager.py
"""
import time
import threading
import math
import csv
from datetime import datetime # <--- ADD THIS
from profile_data import BrewProfile, StepType, TimeoutBehavior, SequenceStatus
import subprocess
import os
from pid_controller import PIDController  # <--- NEW IMPORT

class SequenceManager:
    def __init__(self, settings_manager, relay_control, hardware_interface):
        self.settings = settings_manager
        self.relay = relay_control 
        self.hw = hardware_interface
        
        self.current_profile = None
        self.current_step_index = -1
        self.status = SequenceStatus.IDLE
        
        self.is_manual_running = False
        self.temp_reached = False
        
        # --- NEW: Hard Stop Flag ---
        self.override_hard_stop = False
        
        # --- PID SETUP ---
        # CORRECTED: Use get_section() to retrieve the full dict
        pid_cfg = self.settings.get_section("pid_settings") 
        self.pid = PIDController(
            kp=pid_cfg.get("kp", 50.0),   
            ki=pid_cfg.get("ki", 0.02),   
            kd=pid_cfg.get("kd", 10.0),   
            output_limits=(0, 100)
        )
        self.last_pid_update = 0.0
        self.last_applied_power = 0 

        # Track if Delayed Start was launched from Auto (IDLE) or Manual context
        self.delayed_is_auto = True
        
        self.step_start_time = 0.0
        self.total_paused_time = 0.0
        self.last_pause_start = 0.0
        self.step_elapsed_time = 0.0
        
        self.global_start_time = None
        self.global_paused_time = 0.0
        
        self.current_temp = 0.0
        self.target_temp = 0.0
        self.is_heating = False
        
        self.current_alert_text = None
        
        # --- ALERTS ---
        self.last_alert_time = 0.0
        self.last_alert_nag_time = 0.0 

        # --- RECOVERY HEARTBEAT ---
        self.last_recovery_save = 0.0
        self.RECOVERY_SAVE_INTERVAL = 30.0 
        
        self.last_log_write = 0.0  
        
        # --- NEW: ENERGY INTEGRATION ---
        self.total_watt_seconds = 0.0
        self.last_integration_time = time.monotonic()
        
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._control_loop, daemon=True)
        self._thread.start()

    
    def reset_energy_counter(self):
        """Resets the accumulated kWh counter."""
        self.total_watt_seconds = 0.0
        self.last_integration_time = time.monotonic()
        self.log_message("Energy Counter Reset")
    
    def log_message(self, msg):
        print(f"[SequenceManager] {msg}")
    
    def _play_alert_sound(self):
        """Plays the configured alert sound using aplay (non-blocking)."""
        try:
            base_dir = os.path.dirname(os.path.abspath(__file__))
            
            # Retrieve configured filename (default to alert.wav)
            sound_filename = self.settings.get_system_setting("alert_sound_file", "alert.wav")
            sound_file = os.path.join(base_dir, "assets", sound_filename)
            
            if os.path.exists(sound_file):
                # Retrieve Audio Device
                audio_dev = self.settings.get_system_setting("audio_device", "default")
                
                cmd = ["aplay", "-q"]
                if audio_dev != "default":
                    cmd.extend(["-D", audio_dev])
                cmd.append(sound_file)
                
                subprocess.Popen(cmd, stderr=subprocess.DEVNULL)
                
                # UPDATE TIMER
                self.last_alert_nag_time = time.monotonic()
                
        except Exception as e:
            print(f"[SequenceManager] Alert Sound Error: {e}")
    
    def load_profile(self, profile: BrewProfile):
        self.stop()
        self.current_profile = profile
        self.current_step_index = 0
        self.status = SequenceStatus.IDLE
        
        # --- NEW: Persist this selection for next startup ---
        if self.settings:
            self.settings.set_system_setting("last_profile_id", profile.id)
            
        print(f"[Sequence] Loaded profile: {profile.name}")
    
    # def load_profile(self, profile: BrewProfile):
        # self.stop()
        # self.current_profile = profile
        # self.current_step_index = 0
        # self.status = SequenceStatus.IDLE
        # print(f"[Sequence] Loaded profile: {profile.name}")

    def start_sequence(self):
        if not self.current_profile: return
        
        # --- FIX: Ensure Hard Stop is cleared on Start ---
        self.override_hard_stop = False
        
        if self.status == SequenceStatus.IDLE:
            # --- NEW: Reset Energy Counter on Auto Start ---
            self.reset_energy_counter()
            
            self.current_step_index = 0
            self.global_start_time = None
            self.global_paused_time = 0.0
            
            self._init_step(self.current_step_index)
            self.status = SequenceStatus.RUNNING
            print("[Sequence] Started.")

    def pause_sequence(self):
        # Ensure Soft Pause (Heat allowed to hold temp)
        self.override_hard_stop = False
        
        if self.status == SequenceStatus.RUNNING:
            self.status = SequenceStatus.PAUSED
            self.last_pause_start = time.monotonic()
            
            # CHANGE: Removed relay cutoff to maintain temperature hold
            # Heat remains active (via _manage_temperature in the control loop)
            # self.relay.turn_off_all_relays() 
            # self.is_heating = False
            
            # Save state immediately on pause
            self._save_recovery_snapshot()

    def resume_sequence(self):
        # Clear Hard Stop flag to allow heating
        self.override_hard_stop = False
        
        if self.status in [SequenceStatus.PAUSED, SequenceStatus.WAITING_FOR_USER]:
            if self.last_pause_start > 0:
                paused_duration = time.monotonic() - self.last_pause_start
                self.total_paused_time += paused_duration
                if self.global_start_time is not None:
                    self.global_paused_time += paused_duration
                self.last_pause_start = 0
             
            self.current_alert_text = None 
            self.status = SequenceStatus.RUNNING
            # Save state immediately on resume
            self._save_recovery_snapshot()

    def reset_profile(self):
        """
        Stops the sequence and rewinds to Step 1.
        """
        # Clear Hard Stop so system is clean
        self.override_hard_stop = False
        
        # 1. Stop (Now safe to use)
        self.stop()
        
        # 1b. Explicitly reset elapsed time so UI timer resets to full duration
        self.step_elapsed_time = 0.0
        
        # 2. Rewind to Step 0 (Ready to Start)
        if self.current_profile:
            self.current_step_index = 0
            
            # 3. Reset all addition/alert flags
            for step in self.current_profile.steps:
                if hasattr(step, 'additions'):
                    for add in step.additions:
                        add.triggered = False
            
            # 4. Refresh predictions assuming a "Start Now"
            self.update_predictions()
    
    def advance_step(self):
        if not self.current_profile: return
        
        if self.status in [SequenceStatus.PAUSED, SequenceStatus.WAITING_FOR_USER]:
             self.resume_sequence()

        next_idx = self.current_step_index + 1
        
        if next_idx < len(self.current_profile.steps):
            self.temp_reached = False
            self.step_start_time = 0.0
            
            self.current_step_index = next_idx
            self._init_step(next_idx)
            # Save state on step change
            self._save_recovery_snapshot()
        else:
            self._complete_sequence()

    def _complete_sequence(self):
        self.status = SequenceStatus.COMPLETED
        self.relay.turn_off_all_relays()
        self.is_heating = False
        print("[Sequence] Brew Complete.")
        self.settings.clear_recovery_state()

    def _init_step(self, index):
        step = self.current_profile.steps[index]
        print(f"[Sequence] Init Step {index}: {step.name}")
        
        self.step_start_time = 0.0 
        self.total_paused_time = 0.0
        self.last_pause_start = 0.0
        self.step_elapsed_time = 0.0
        self.temp_reached = False 
        
        # --- NEW: DEBOUNCE TIMER ---
        self.trigger_start_time = 0.0
        # ---------------------------
        
        # --- CAPTURE INITIAL TEMP ---
        self.initial_step_temp = self.current_temp if self.current_temp is not None else 0.0

        if self.global_start_time is None:
            self.global_start_time = time.monotonic()
        
        # --- CENTRALIZED TARGET LOGIC ---
        # 1. Prefer explicit Setpoint
        # 2. Fallback to Lauter Temp (for Mash/Sparge steps)
        # 3. Default to 0.0 (Off)
        if step.setpoint_f is not None:
            self.target_temp = float(step.setpoint_f)
        elif step.lauter_temp_f is not None:
            self.target_temp = float(step.lauter_temp_f)
        else:
            self.target_temp = 0.0
            
        print(f"[Sequence] Target calculated as: {self.target_temp} F")
            
        if hasattr(step, 'additions'):
            for add in step.additions:
                add.triggered = False
        self.current_alert_text = None
        
    def calculate_ramp_minutes(self, start_temp, target_temp, vol_gal, watts):
        """
        Calculates time to heat water based on system calibration.
        """
        if target_temp <= start_temp: return 0.0
        if vol_gal <= 0.1: return 0.0 # Avoid div/0
        
        # --- FIX: Sanitize watts (Treat None as 1800W to match control logic) ---
        safe_watts = float(watts) if watts is not None else 1800.0
        
        # 1. Get Calibration Constants (Reference: 1800W @ 8.0 Gal)
        ref_rate_fpm = self.settings.get_system_setting("heater_ref_rate_fpm", 1.2)
        ref_vol = self.settings.get_system_setting("heater_ref_volume_gal", 8.0)
        
        # 2. Adjust for Volume
        # Rate increases if volume is lower than reference
        vol_factor = ref_vol / float(vol_gal)
        
        # 3. Adjust for Power
        # Rate decreases if power is lower than 1800W
        power_factor = safe_watts / 1800.0
        
        # 4. Calculate Real Rate
        real_rate_fpm = ref_rate_fpm * vol_factor * power_factor
        
        if real_rate_fpm <= 0.01: return 999.0 # Safety
        
        delta_temp = target_temp - start_temp
        return delta_temp / real_rate_fpm

    def update_predictions(self):
        """
        Refreshes 'ready_at' timestamps for the active profile.
        Calculates when each step will be REACHED (Target Temp Hit).
        """
        if not self.current_profile: return
        
        import time
        from datetime import datetime
        
        # 1. Base Time: Start calculation from 'Now'
        current_time = time.time()
        
        # Start simulation at current actual temp
        sim_temp = self.current_temp if self.current_temp else 60.0
        
        # 2. Determine Simulation Volume
        sim_vol = self.settings.get("manual_mode_settings", "last_volume_gal", 6.0)
        for s in self.current_profile.steps:
            if s.lauter_volume and s.lauter_volume > 0:
                sim_vol = s.lauter_volume
                break
        
        # 3. Iteration
        for i, step in enumerate(self.current_profile.steps):
            
            # --- PAST STEPS ---
            if i < self.current_step_index:
                step.predicted_ready_time = "Done"
                # For past steps, simply assume we ended at the setpoint
                if step.setpoint_f: sim_temp = step.setpoint_f
                continue
            
            # --- CURRENT STEP ---
            if i == self.current_step_index:
                # Logic: Is the step "done" temperature-wise?
                is_ready_now = False
                
                if self.status == SequenceStatus.RUNNING and self.temp_reached:
                    is_ready_now = True
                elif step.setpoint_f and self.current_temp and self.current_temp >= step.setpoint_f:
                    # Even if not "RUNNING", if we are hot enough, we are effectively ready
                    is_ready_now = True

                if is_ready_now:
                    step.predicted_ready_time = "Now"
                    
                    # Add REMAINING hold time to the accumulator
                    d_sec = (step.duration_min * 60.0) if step.duration_min else 0.0
                    rem_sec = d_sec - self.step_elapsed_time
                    if rem_sec < 0: rem_sec = 0
                    
                    current_time += rem_sec
                    
                    # UPDATE SIM TEMP FOR NEXT STEP
                    # FIX: Use the ACTUAL temp if it's hotter than the target.
                    # This prevents calculating a ramp from 50F -> 156F if we are already at 92F.
                    tgt = step.setpoint_f if step.setpoint_f else sim_temp
                    sim_temp = max(tgt, self.current_temp if self.current_temp else tgt)
                    
                else:
                    # We are RAMPING (or IDLE/PAUSED/WAITING)
                    tgt = step.setpoint_f if step.setpoint_f else sim_temp
                    watts = step.power_watts if step.power_watts else 1800
                    
                    # Use current actual temp as start for this immediate step
                    start_t = self.current_temp if self.current_temp else sim_temp
                    
                    # Calc Ramp Time
                    ramp_min = self.calculate_ramp_minutes(start_t, tgt, sim_vol, watts)
                    ramp_sec = ramp_min * 60.0
                    
                    # Ready At = Now + Ramp
                    ready_epoch = current_time + ramp_sec
                    
                    dt = datetime.fromtimestamp(ready_epoch)
                    step.predicted_ready_time = dt.strftime("%H:%M")
                    
                    # Advance accumulator for NEXT step: (Now + Ramp + Hold)
                    hold_sec = (step.duration_min * 60.0) if step.duration_min else 0.0
                    current_time += (ramp_sec + hold_sec)
                    
                    # UPDATE SIM TEMP
                    # We assume we reach the target at the end of this step
                    sim_temp = tgt

            # --- FUTURE STEPS ---
            else:
                tgt = step.setpoint_f if step.setpoint_f else sim_temp
                watts = step.power_watts if step.power_watts else 1800
                
                # Calc Ramp from PREVIOUS step's end temp (sim_temp)
                ramp_min = self.calculate_ramp_minutes(sim_temp, tgt, sim_vol, watts)
                ramp_sec = ramp_min * 60.0
                
                # Ready At = Accumulator + Ramp
                ready_epoch = current_time + ramp_sec
                
                dt = datetime.fromtimestamp(ready_epoch)
                step.predicted_ready_time = dt.strftime("%H:%M")
                
                # Advance accumulator
                hold_sec = (step.duration_min * 60.0) if step.duration_min else 0.0
                current_time += (ramp_sec + hold_sec)
                
                sim_temp = tgt

    # --- DELAYED START LOGIC ---
    def start_delayed_mode(self, target_temp, volume_gal, ready_time_dt, from_auto_mode=None):
        """
        Calculates when to fire the heater so water is ready at ready_time_dt.
        Enters DELAYED_WAIT state.
        
        Sets Manual Mode defaults (30m timer, 1800W) immediately so UI reflects the pending state.
        """
        # 1. Determine Context (Auto vs Manual)
        if from_auto_mode is not None:
            self.delayed_is_auto = from_auto_mode
        else:
            # Default: If not Manual, assume Auto
            self.delayed_is_auto = (self.status != SequenceStatus.MANUAL)

        self.stop() # Reset status
        
        # 2. Get Constants
        ref_vol = self.settings.get_system_setting("heater_ref_volume_gal", 8.0)
        ref_rate = self.settings.get_system_setting("heater_ref_rate_fpm", 1.2)
        
        # 3. Calculate adjusted rate for this volume
        try:
            adj_rate = ref_rate * (ref_vol / float(volume_gal))
        except ZeroDivisionError:
            adj_rate = ref_rate

        # 4. Calculate Temp Rise needed
        current = self.current_temp if self.current_temp else 60.0 # Fallback
        rise = float(target_temp) - current
        if rise < 0: rise = 0
        
        # 5. Calculate Duration (Minutes)
        duration_min = rise / adj_rate
        
        # 6. Calculate Start Time (Epoch)
        ready_epoch = ready_time_dt.timestamp()
        start_epoch = ready_epoch - (duration_min * 60)
        
        # --- STORE DATA ---
        self.delayed_ready_epoch = ready_epoch 
        self.delayed_start_epoch = start_epoch
        self.delayed_target_temp = float(target_temp)
        self.delayed_vol = float(volume_gal) 
        self.delayed_ready_time_str = ready_time_dt.strftime("%H:%M")
        self.delayed_start_time_str = datetime.fromtimestamp(start_epoch).strftime("%H:%M")
        
        # --- UPDATE MANUAL SETTINGS IMMEDIATELY ---
        # This ensures the UI sliders (Target, Timer, Power, Vol) update visually 
        # to match what will happen when the delay triggers.
        self.set_manual_target(self.delayed_target_temp)
        self.set_manual_volume(self.delayed_vol)
        self.set_manual_timer_duration(30.0) # User Requested Default: 30 minutes
        self.set_manual_power(1800)          # User Requested Default: 1800W
        
        self.status = SequenceStatus.DELAYED_WAIT
        print(f"[Sequence] Delayed Start Set (Auto Context: {self.delayed_is_auto}).")
        print(f"   Ready By: {self.delayed_ready_time_str}")
        print(f"   Heater Fires At: {self.delayed_start_time_str}")
        print(f"   Configured Manual Mode: {self.delayed_target_temp}F, 30min, 1800W")
        
        self._save_recovery_snapshot()

    def cancel_delayed_mode(self):
        """Cancels delay and returns to the previous context (Auto or Manual)."""
        if self.status != SequenceStatus.DELAYED_WAIT:
            return

        # Check the flag we saved when delay started
        if getattr(self, 'delayed_is_auto', True):
            print("[Sequence] Cancel Delay -> Returning to Auto (IDLE)")
            self.stop() # Returns to IDLE
        else:
            print("[Sequence] Cancel Delay -> Returning to Manual Mode")
            self.enter_manual_mode() # Returns to MANUAL
    
    def get_delayed_status_msg(self):
        """Returns the dynamic lines for the UI button."""
        if self.status != SequenceStatus.DELAYED_WAIT: return ""
        # The UI will prepend "DELAY ACTIVE" and "SLEEPING"
        # REVERSED ORDER: Heat starts first, then Ready time
        return f"Heat starts at: {self.delayed_start_time_str}\nReady at: {self.delayed_ready_time_str}"

    # --- MANUAL MODE METHODS ---
    
    # [Add setters for new manual controls]
    def set_manual_power(self, watts):
        self.manual_power_watts = int(watts)
        self.settings.set("manual_mode_settings", "last_power_watts", self.manual_power_watts)

    def set_manual_volume(self, vol_gal):
        self.manual_volume_gal = float(vol_gal)
        self.settings.set("manual_mode_settings", "last_volume_gal", self.manual_volume_gal)
    
    def enter_manual_mode(self):
        """Transitions to Manual Mode (Standby)."""
        self.stop() 
        self.status = SequenceStatus.MANUAL
        self.is_manual_running = False 
        
        # Load saved defaults
        self.manual_target_temp = self.settings.get("manual_mode_settings", "last_setpoint_f", 150.0)
        self.manual_timer_duration = self.settings.get("manual_mode_settings", "last_timer_min", 60.0) * 60.0
        self.manual_power_watts = self.settings.get("manual_mode_settings", "last_power_watts", 1800)
        
        # Initialize the Countdown Bucket
        self.manual_timer_remaining = self.manual_timer_duration
        self.temp_reached = False
        
        self.target_temp = self.manual_target_temp
        self.log_message("Entered Manual Mode")

    def start_manual(self):
        """Starts OR Resumes the heater/timer in Manual Mode."""
        # Clear Hard Stop flag
        self.override_hard_stop = False
        
        if self.status != SequenceStatus.MANUAL:
            self.enter_manual_mode()
            
        self.is_manual_running = True
        self.is_heating = True
        
        # IMPORTANT: Reset the tick tracker so we don't calculate a huge 
        # delta from when we were paused.
        self.last_tick_time = time.monotonic()
        
        # If this is a fresh start (Latch Open), reset PID
        if not self.temp_reached:
            self.pid.reset()
            self.log_message("Manual Mode STARTED - Heating to Target")
        else:
             self.log_message("Manual Mode RESUMED")

    def pause_manual(self):
        """
        Pauses heating/timer.
        If Timer hasn't started counting yet (Pre-heat), this acts as a RESET.
        """
        # Ensure Soft Pause (Heat allowed)
        self.override_hard_stop = False
        
        # LOGIC CHECK: Are we in Pre-heat (Latch still waiting)?
        if not self.temp_reached:
            # Case A: Timer NOT counting down yet -> Full Reset (Safety)
            self.log_message("Pause requested during Pre-Heat -> RESETTING.")
            # If resetting, we DO want to kill heat
            if hasattr(self, 'relay'): self.relay.stop_all()
            elif hasattr(self, 'relays'): self.relays.stop_all()
            self.enter_manual_mode() 
            return

        # Case B: Timer IS counting down -> Freeze Timer, KEEP HEAT
        self.is_manual_running = False
        
        # CHANGE: Removed is_heating=False so PID continues
        # self.is_heating = False 
        
        # We do NOT reset manual_timer_remaining here. It stays frozen.
        self.log_message("Manual Mode PAUSED (Timer Frozen, Heat Active)")

    def stop(self):
        """Full System Reset."""
        # --- FIX: Ensure Hard Stop is cleared on Reset ---
        self.override_hard_stop = False
        
        self.status = SequenceStatus.IDLE
        self.is_manual_running = False
        self.is_heating = False
        
        # Turn off hardware
        if hasattr(self, 'relay'):
            self.relay.stop_all()
        elif hasattr(self, 'relays'):
             self.relays.stop_all()
        
        self.current_step_index = -1
        # REMOVED: self.current_profile = None  <-- Kept to ensure profile persists
        self.step_start_time = 0.0
        self.log_message("STOPPED / RESET")

    def reset_manual_state(self):
        """Alias for enter_manual_mode to prevent legacy crashes."""
        self.enter_manual_mode()
    
    def emergency_cut_power(self):
        """Smart Stop Action (Hard Stop)."""
        # 1. Engage Hard Stop Override (Prevents Control Loop from reheating)
        self.override_hard_stop = True
        
        # 2. Cut Physical Power
        if hasattr(self, 'relay'): self.relay.stop_all()
        elif hasattr(self, 'relays'): self.relays.stop_all()
        
        # 3. Halt Execution Flags
        self.is_manual_running = False
        self.is_heating = False
        
        # 4. Update Status if Running (Auto)
        if self.status == SequenceStatus.RUNNING:
            self.status = SequenceStatus.PAUSED
            self.last_pause_start = time.monotonic()
            
        self.log_message("EMERGENCY STOP TRIGGERED")

    def _process_manual_logic(self):
        """
        Handles Heating logic for Manual Mode.
        """
        # 1. READ SENSORS
        if self.current_temp is None:
             if hasattr(self, 'relay'): self.relay.stop_all()
             elif hasattr(self, 'relays'): self.relays.stop_all()
             return
             
        current_temp = self.current_temp 
        now = time.monotonic()
        
        # 2. TIMER LOGIC (Only runs if "Running")
        if self.is_manual_running:
            # Calculate time passed since last tick
            if not hasattr(self, 'last_tick_time'): self.last_tick_time = now
            delta = now - self.last_tick_time
            self.last_tick_time = now
            
            # Retrieve System Boil Temp for Latch Logic
            sys_boil = self.settings.get_system_setting("boil_temp_f", 212.0)
            
            # Determine effective trigger threshold (Clamp to Boil Temp)
            # If target (212) > Boil (205), we trigger at 205
            trigger_threshold = min(self.manual_target_temp, sys_boil)

            # A. Wait for Temp (Latch)
            if not self.temp_reached:
                # Use the clamped threshold - 0.5 buffer
                if current_temp >= (trigger_threshold - 0.5):
                    self.temp_reached = True
                    # Timer technically starts NOW
                    self.log_message(f"Target Reached ({current_temp:.1f}F). Timer Started.")
            # B. Countdown
            else:
                # Subtract actual elapsed time from the bucket
                self.manual_timer_remaining -= delta
                
                # C. Auto-Reset on Expiry
                if self.manual_timer_remaining <= 0:
                    self.manual_timer_remaining = 0
                    self.log_message("Timer Expired. Resetting Manual Mode.")
                    self.enter_manual_mode() # Full Reset
                    return 
        else:
             # Update tick time to avoid huge jumps on resume
             self.last_tick_time = now

        # 3. HEATER CONTROL (Independent of Timer status)
        # CHANGE: Decoupled from is_manual_running to allow Heat-While-Paused
        if self.is_heating:
            # Over-temp Safety
            if current_temp > (self.manual_target_temp + 1.0) or current_temp > 215:
                 if hasattr(self, 'relay'): self.relay.stop_all()
                 elif hasattr(self, 'relays'): self.relays.stop_all()
                 return

            # PID Calculation
            pid_out = self.pid.compute(current_temp, self.manual_target_temp)
            
            watts_to_apply = 0
            if pid_out > 90: watts_to_apply = 1800
            elif pid_out > 75: watts_to_apply = 1400
            elif pid_out > 50: watts_to_apply = 1000
            elif pid_out > 20: watts_to_apply = 800
            else: watts_to_apply = 0 

            if watts_to_apply > self.manual_power_watts:
                watts_to_apply = self.manual_power_watts

            self._apply_power_logic(watts_to_apply)
            
        else:
            if hasattr(self, 'relay'): self.relay.stop_all()
            elif hasattr(self, 'relays'): self.relays.stop_all()

    def toggle_manual_heater(self, enabled):
        """Toggles the heater on/off in manual mode."""
        self.is_heating = enabled
        self.settings.set("manual_mode_settings", "heater_enabled", enabled)
        if not enabled:
            self.relay.turn_off_all_relays()

    def set_manual_target(self, temp_f):
        """Updates the manual mode setpoint."""
        val = float(temp_f)
        self.target_temp = val
        self.manual_target_temp = val  # <--- ADD THIS LINE TO SYNC PID
        self.settings.set("manual_mode_settings", "last_setpoint_f", self.target_temp)

    def toggle_manual_timer(self):
        """Starts or Stops the manual timer."""
        if self.step_start_time > 0:
            # STOP Timer
            self.step_start_time = 0.0
        else:
            # START Timer
            self.step_start_time = time.monotonic()

    def set_manual_timer_duration(self, minutes):
        self.manual_timer_duration = float(minutes) * 60.0
        self.settings.set("manual_mode_settings", "last_timer_min", float(minutes))
    
    def update(self):
        pass 

    def _control_loop(self):
        last_delay_calc = 0.0  # Track last recalculation time

        while not self._stop_event.is_set():
            time.sleep(0.1) 
            try:
                self.current_temp = self.hw.read_temperature()
            except:
                # FIX: On crash/error, set to None (not 0.0)
                self.current_temp = None

            # --- NEW: ENERGY INTEGRATION START ---
            now_mono = time.monotonic()
            dt = now_mono - self.last_integration_time
            self.last_integration_time = now_mono
            
            # Calculate instantaneous watts based on ACTUAL relay state
            current_watts = 0
            if self.relay and hasattr(self.relay, 'relay_states'):
                states = self.relay.relay_states
                if states.get("Heater1", False): current_watts += 1000
                if states.get("Heater2", False): current_watts += 800
            
            if current_watts > 0 and dt > 0:
                self.total_watt_seconds += (current_watts * dt)
            # --- NEW: ENERGY INTEGRATION END ---

            # Safety: If sensor fails, kill power
            if self.current_temp is None:
                self.relay.set_relays(False, False, False)
                continue
                
            # --- HARD STOP OVERRIDE ---
            # If Emergency Stop is active, forcefully cut power and skip logic
            if getattr(self, 'override_hard_stop', False):
                 self.relay.set_relays(False, False, False)
                 continue

            # --- CSV LOGGING ---
            # now_mono already defined above
            if now_mono - self.last_log_write > 30.0:
                self._log_csv()
                self.last_log_write = now_mono

            # --- ALERT NAG / REPEAT LOGIC ---
            if self.status == SequenceStatus.WAITING_FOR_USER:
                freq = self.settings.get_system_setting("alert_repeat_freq", 15)
                # Only repeat if freq > 0 and time has elapsed
                if freq > 0 and (now_mono - self.last_alert_nag_time > freq):
                    self._play_alert_sound() # This will update last_alert_nag_time

            # --- DELAYED START WAIT ---
            if self.status == SequenceStatus.DELAYED_WAIT:
                now = time.time()
                
                # ADAPTIVE RECALCULATION
                if now - last_delay_calc > 30.0:
                    last_delay_calc = now
                    # FIX: Check for correct variables set in start_delayed_mode
                    if hasattr(self, 'delayed_target_temp') and hasattr(self, 'delayed_ready_epoch'):
                         # FIX: Calculate Ramp needs arguments (Current Temp -> Target Temp)
                         # We use 1800W (default) for calculation estimation
                         current_t = self.current_temp if self.current_temp else 60.0
                         ramp_min = self.calculate_ramp_minutes(
                             current_t, 
                             self.delayed_target_temp, 
                             getattr(self, 'delayed_vol', 8.0), 
                             1800
                         )
                         
                         # Update Start Epoch based on new ramp
                         # Start = ReadyTime - RampTime
                         self.delayed_start_epoch = self.delayed_ready_epoch - (ramp_min * 60.0)
                         
                         # Update UI String
                         self.delayed_start_time_str = datetime.fromtimestamp(self.delayed_start_epoch).strftime("%H:%M")
                         
                         # Update Profile Predictions if applicable
                         self.update_predictions()

                # CHECK FOR START
                # FIX: Variable name mismatch (delayed_start_trigger_time -> delayed_start_epoch)
                if hasattr(self, 'delayed_start_epoch'):
                    if now >= self.delayed_start_epoch:
                         print("[SequenceManager] Delayed Start Triggered!")
                         
                         # --- NEW: Reset Energy Counter Here ---
                         self.reset_energy_counter()
                         
                         # FIX: Context Awareness (Auto vs Manual)
                         if getattr(self, 'delayed_is_auto', True):
                             self.status = SequenceStatus.RUNNING
                             self.start_sequence()
                         else:
                             self.start_manual()
            
            # --- MAIN SEQUENCE LOGIC ---
            # CHANGE: Consolidated RUNNING, PAUSED, and WAITING to maintain Temp Hold
            elif self.status in [SequenceStatus.RUNNING, SequenceStatus.PAUSED, SequenceStatus.WAITING_FOR_USER]:
                if self.current_profile:
                     # Get current step
                     step = self.current_profile.steps[self.current_step_index]
                     
                     # ALWAYS Manage Temp (Hold Target)
                     self._manage_temperature(step)
                     
                     # ONLY Process Time if RUNNING
                     if self.status == SequenceStatus.RUNNING:
                         self._process_time_logic(step)
            
            # --- MANUAL MODE LOGIC ---
            elif self.status == SequenceStatus.MANUAL:
                self._process_manual_logic()
                
            else:
                # IDLE, COMPLETED -> Safety Off
                self.relay.set_relays(False, False, False)

    def _process_time_logic(self, step):
        # 1. Strict Check: If Temp Not Reached, NO TIME PASSES.
        if not self.temp_reached:
            self.step_elapsed_time = 0
            return 

        # CHANGE: If waiting for "Step Complete", allow time to freeze (effectively paused).
        # But for Additions, we proceed to update step_elapsed_time.
        if self.status == SequenceStatus.WAITING_FOR_USER and self.current_alert_text == "Step Complete":
            return

        now = time.monotonic()
        self.step_elapsed_time = now - self.step_start_time - self.total_paused_time
        
        # CHANGE: If we are already waiting for an Alert, just update the time (above) and exit.
        # We don't want to re-check triggers or auto-advance while waiting.
        if self.status == SequenceStatus.WAITING_FOR_USER:
            return

        duration_val = step.duration_min if step.duration_min is not None else 0.0
        duration_sec = duration_val * 60.0
        remaining_sec = duration_sec - self.step_elapsed_time
        remaining_min = remaining_sec / 60.0

        if hasattr(step, 'additions'):
            for add in step.additions:
                if not add.triggered:
                    should_trigger = False
                    # Trigger if within 0.005 min (0.3 sec)
                    if remaining_min <= (add.time_point_min + 0.005):
                        should_trigger = True
                    if duration_val <= 0.0:
                        should_trigger = True

                    if should_trigger:
                        add.triggered = True 
                        self.status = SequenceStatus.WAITING_FOR_USER
                        self.current_alert_text = add.name
                        
                        self._play_alert_sound()
                        self._save_recovery_snapshot()
                        
                        # CHANGE: Do NOT set last_pause_start. 
                        # This ensures the timer keeps running during the wait.
                        return

        if self.step_elapsed_time >= duration_sec:
            if hasattr(step, 'additions'):
                # Ensure all additions have fired before completing step
                if any(not a.triggered for a in step.additions):
                    return 

            if duration_val > 0.0:
                self._play_alert_sound()

            if step.timeout_behavior == TimeoutBehavior.AUTO_ADVANCE:
                self.advance_step()
            else:
                self.status = SequenceStatus.WAITING_FOR_USER
                self.last_pause_start = time.monotonic() # Keep this pause for End of Step
                self.current_alert_text = "Step Complete"
                self._save_recovery_snapshot()
            return
                    
    def _manage_temperature_generic(self, target):
        """PID control for Manual Mode."""
        if target <= 0: 
            self.relay.set_relays(False, False, False)
            self.last_applied_power = 0
            return

        # --- FIX: CLAMP TRIGGER TO BOIL TEMP ---
        sys_boil = self.settings.get_system_setting("boil_temp_f", 212.0)
        trigger_threshold = min(target, sys_boil)

        # Check for Timer Trigger
        if not self.temp_reached:
             if self.current_temp >= trigger_threshold:
                 self.temp_reached = True
                 self.step_start_time = time.monotonic()
                 
                 # Only beep if we started below target
                 start_t = getattr(self, 'initial_manual_temp', 0.0)
                 if start_t < (trigger_threshold - 0.5):
                     self._play_alert_sound()

        # --- HEATER CALCULATION ---
        watts_to_apply = 0
        
        # Limit by User Setting (Always enforce)
        limit = getattr(self, 'manual_power_watts', 1800)

        # OPEN LOOP CHECK: If target is at/above boil point, bypass PID
        if target >= sys_boil:
            # Force full manual power setting (Open Loop)
            watts_to_apply = limit
            self.is_heating = True
            
        else:
            # STANDARD: PID Control
            pid_out = self.pid.compute(self.current_temp, target)
            
            # Map to discrete power
            if pid_out <= 0: watts_to_apply = 0
            elif pid_out < 20: watts_to_apply = 0
            elif pid_out < 50: watts_to_apply = 800
            elif pid_out < 75: watts_to_apply = 1000
            elif pid_out < 90: watts_to_apply = 1400
            else: watts_to_apply = 1800
                
            # Apply Manual Limit
            if watts_to_apply > limit:
                watts_to_apply = limit
            
        # Apply
        if watts_to_apply > 0:
            self._apply_power_logic(watts_to_apply)
        else:
            self.relay.set_relays(False, False, False)
            
        # Store for logging
        self.last_applied_power = watts_to_apply
                        
    def _save_recovery_snapshot(self):
        """Saves current progress to settings for power-loss recovery."""
        state = {
            "status": self.status.value,
            "timestamp": time.time()
        }

        # 1. SAVE DELAY STATE
        if self.status == SequenceStatus.DELAYED_WAIT:
            state["mode_type"] = "DELAY"
            state["delayed_ready_epoch"] = getattr(self, 'delayed_ready_epoch', 0) # <--- NEW
            state["delayed_start_epoch"] = getattr(self, 'delayed_start_epoch', 0)
            state["delayed_target_temp"] = getattr(self, 'delayed_target_temp', 0)
            state["delayed_vol"] = getattr(self, 'delayed_vol', 0)
            state["delayed_ready_time_str"] = getattr(self, 'delayed_ready_time_str', "")
            state["delayed_start_time_str"] = getattr(self, 'delayed_start_time_str', "")
            
            # Save the context flag so we know where to return if cancelled
            state["delayed_is_auto"] = getattr(self, 'delayed_is_auto', True)
            
            self.settings.save_recovery_state(state)
            return

        # 2. SAVE MANUAL STATE
        if self.status == SequenceStatus.MANUAL:
            state["mode_type"] = "MANUAL"
            state["target_temp"] = self.target_temp
            state["heater_enabled"] = self.is_heating
            state["manual_timer_duration"] = getattr(self, 'manual_timer_duration', 3600.0)
            state["temp_reached"] = self.temp_reached
            
            # Calculate elapsed time for the manual timer if it's running
            if self.step_start_time > 0:
                now = time.monotonic()
                if self.last_pause_start > 0:
                     state["elapsed_time"] = self.last_pause_start - self.step_start_time - self.total_paused_time
                else:
                     state["elapsed_time"] = now - self.step_start_time - self.total_paused_time
            else:
                state["elapsed_time"] = 0.0

            self.settings.save_recovery_state(state)
            return

        # 3. SAVE PROFILE STATE
        if self.current_profile:
            state["mode_type"] = "PROFILE"
            state["profile_id"] = self.current_profile.id
            state["step_index"] = self.current_step_index
            state["elapsed_time"] = self.step_elapsed_time
            state["temp_reached"] = self.temp_reached
            state["global_elapsed"] = self._get_total_elapsed_seconds()
            
            self.settings.save_recovery_state(state)
            
    def _log_csv(self):
        """Appends a row to the CSV log if enabled."""
        # 1. Check if enabled
        if not self.settings.get_system_setting("enable_csv_logging", False):
            return

        # 2. Skip if IDLE (User requested only Active modes)
        if self.status == SequenceStatus.IDLE:
            return

        try:
            # 3. Gather Data points
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            mode = "UNKNOWN"
            status = self.status.value

            # Determine Mode & Step Info
            step_info = "-"
            if self.status == SequenceStatus.DELAYED_WAIT:
                mode = "DELAY"
                step_info = f"Starts: {self.delayed_start_time_str}"
            elif self.status == SequenceStatus.MANUAL:
                mode = "MANUAL"
                step_info = "Manual Hold"
            elif self.current_profile:
                mode = "AUTO"
                if 0 <= self.current_step_index < len(self.current_profile.steps):
                    step_info = self.current_profile.steps[self.current_step_index].name

            # Temperatures
            curr_t = f"{self.current_temp:.2f}" if self.current_temp else "0.00"

            # Determine Target Temp
            if self.status == SequenceStatus.DELAYED_WAIT:
                tgt = getattr(self, 'delayed_target_temp', 0.0)
            else:
                tgt = self.target_temp
            tgt_t = f"{tgt:.0f}"

            # --- FIX: REAL HARDWARE POWER ---
            # Checks the physical state of the relays at this exact moment.
            watts = 0
            if self.relay and hasattr(self.relay, 'relay_states'):
                states = self.relay.relay_states
                
                # Heater 1 = 1000W
                val_1 = 1000 if states.get("Heater1", False) else 0
                
                # Heater 2 = 800W
                val_2 = 800  if states.get("Heater2", False) else 0
                
                watts = val_1 + val_2
            # --------------------------------

            # Determine Timer
            timer_str = self.get_display_timer()

            # 4. Write to File
            data_dir = self.settings.data_dir
            log_file = os.path.join(data_dir, "kettlebrain-log.csv")
            file_exists = os.path.isfile(log_file)

            with open(log_file, mode='a', newline='') as f:
                writer = csv.writer(f)

                # Write Header if new file
                if not file_exists:
                    writer.writerow(["Timestamp", "Mode", "Status", "Temp(F)", "Target(F)", "Power(W)", "Step", "Timer"])

                # Write Data
                writer.writerow([timestamp, mode, status, curr_t, tgt_t, watts, step_info, timer_str])

        except Exception as e:
            print(f"[Sequence] Log Error: {e}")
            
    def _get_total_elapsed_seconds(self):
        if self.global_start_time is None: return 0
        return time.monotonic() - self.global_start_time - self.global_paused_time

    # --- RESTORE LOGIC ---
    def restore_from_recovery(self, state_dict):
        """Called by Main to resume a crashed/interrupted session."""
        mode_type = state_dict.get("mode_type", "PROFILE")
        print(f"[Sequence] Restoring from recovery. Mode: {mode_type}")
        
        # --- RESTORE DELAYED START ---
        if mode_type == "DELAY":
            print("[Sequence] Restoring Delayed Start...")
            
            # 1. Restore Variables
            self.delayed_is_auto = state_dict.get("delayed_is_auto", True)
            self.delayed_ready_epoch = state_dict.get("delayed_ready_epoch", 0) # <--- NEW
            self.delayed_start_epoch = state_dict.get("delayed_start_epoch", 0)
            self.delayed_target_temp = state_dict.get("delayed_target_temp", 0)
            self.delayed_vol = state_dict.get("delayed_vol", 0)
            self.delayed_ready_time_str = state_dict.get("delayed_ready_time_str", "")
            self.delayed_start_time_str = state_dict.get("delayed_start_time_str", "")
            
            # Ensure Manual Target is synced
            self.set_manual_target(self.delayed_target_temp)
            
            # 2. Check Time
            now = time.time()
            if now >= self.delayed_start_epoch:
                # We missed the start time (or it's happening now) -> WAKE UP IMMEDIATELY
                print("[Sequence] Restore: Start time passed. Firing Heater immediately.")
                self.enter_manual_mode()
                self.set_manual_target(self.delayed_target_temp)
                self.toggle_manual_heater(True)
            else:
                # We are still early -> GO BACK TO SLEEP
                print("[Sequence] Restore: Still early. Resuming Delayed Wait.")
                self.status = SequenceStatus.DELAYED_WAIT
                self._save_recovery_snapshot()
                
            return

        # --- RESTORE MANUAL MODE ---
        if mode_type == "MANUAL":
            print("[Sequence] Restoring Manual Mode...")
            self.enter_manual_mode()
            
            # 1. Restore Values
            saved_target = state_dict.get("target_temp", 150.0)
            saved_duration = state_dict.get("manual_timer_duration", 3600.0)
            was_heating = state_dict.get("heater_enabled", False)
            self.temp_reached = state_dict.get("temp_reached", False)
            saved_elapsed = state_dict.get("elapsed_time", 0.0)
            
            self.set_manual_target(saved_target)
            
            # Restore custom duration (convert back to minutes for the setter)
            self.set_manual_timer_duration(saved_duration / 60.0)

            # 2. Restore Timer State
            if saved_elapsed > 0:
                # Timer was running, so backdate start time
                self.step_start_time = time.monotonic() - saved_elapsed
            else:
                # Timer was not running (or waiting for temp)
                self.step_start_time = 0.0

            # 3. Restore Heater
            # Only turn on if it was on previously
            if was_heating:
                self.toggle_manual_heater(True)

            return

        # --- RESTORE PROFILE ---
        # SAFETY GUARD: If we get here, we expect a profile. If none, stop to prevent crash.
        if not self.current_profile:
            print(f"[Sequence] CRITICAL ERROR: Attempted to restore PROFILE mode (derived from {mode_type}) without a loaded profile. Aborting restore.")
            self.status = SequenceStatus.IDLE
            return

        # 1. First, initialize the step to load standard defaults (Setpoints, etc.)
        self.current_step_index = state_dict.get("step_index", 0)
        self._init_step(self.current_step_index)
        
        # 2. NOW overwrite the defaults with our saved state
        self.temp_reached = state_dict.get("temp_reached", False)
        saved_elapsed = state_dict.get("elapsed_time", 0.0)
        
        now = time.monotonic()
        
        # Restore Global Time approximation
        saved_global = state_dict.get("global_elapsed", 0.0)
        self.global_start_time = now - saved_global
        
        # Restore Step Timer
        if self.temp_reached:
            # Force the start time to be in the past so the timer resumes correctly
            self.step_start_time = now - saved_elapsed
            self.step_elapsed_time = saved_elapsed
        else:
            # If we hadn't reached temp, start fresh waiting for temp
            self.step_start_time = 0 
            
        self.status = SequenceStatus.RUNNING
        self.last_recovery_save = now
        
        print(f"[Sequence] Restored Step {self.current_step_index + 1}. Temp Reached: {self.temp_reached}, Elapsed: {saved_elapsed:.1f}s")

    def _manage_temperature(self, step):
        # 1. Use the Target determined in _init_step
        target = self.target_temp

        # Safety Clamp
        if target > 215: target = 215
        
        # Safety Protocol
        if self.current_temp is None:
            self.relay.set_relays(False, False, False)
            return

        # Retrieve System Boil Temp for Latch AND Control Logic
        sys_boil = self.settings.get_system_setting("boil_temp_f", 212.0)

        # 2. Timer Latch Logic (Temp Reached?)
        # Only check if we haven't reached temp yet
        if target > 0 and not self.temp_reached:
            # Clamp trigger check to system boil temp so we don't wait for 213F
            trigger_threshold = min(target, sys_boil)
            
            # Check if we crossed the threshold
            if self.current_temp >= trigger_threshold:
                # --- DEBOUNCE LOGIC (Hold for 5 seconds) ---
                now = time.monotonic()
                if self.trigger_start_time == 0.0:
                    self.trigger_start_time = now  # Start counting
                
                # Check if 5 seconds have passed
                elif (now - self.trigger_start_time) >= 5.0:
                    self.temp_reached = True
                    self.step_start_time = time.monotonic()
                    
                    # --- FIX: Reset Paused Time so Timer starts fresh at 00:00 ---
                    self.total_paused_time = 0.0
                    
                    self.trigger_start_time = 0.0 # Reset
                    
                    # Alert sound if we started cold
                    start_t = getattr(self, 'initial_step_temp', 0.0)
                    if start_t < (target - 0.5):
                        self._play_alert_sound()
                    self._save_recovery_snapshot()
            else:
                # Reset if temp drops below target before confirmed
                self.trigger_start_time = 0.0

        # 3. Heater Power Logic
        watts_to_apply = 0

        # EXCEPTION: BOIL Steps OR High Target are Open Loop (Ignore PID)
        # Checks if step type is BOIL OR if the numeric target implies boiling
        if step.step_type == StepType.BOIL or target >= sys_boil:
            # Force "In Demand" at the configured wattage without regard to PID
            watts_to_apply = step.power_watts if step.power_watts is not None else 1800
            self.is_heating = True
            
        # STANDARD: PID Control
        elif target > 0:
            # Execute PID
            pid_out = self.pid.compute(self.current_temp, target)
            self.is_heating = (pid_out > 0)
            
            # Map PID % to Discrete Power Levels
            if pid_out <= 0:
                watts_to_apply = 0
            elif pid_out < 20:
                watts_to_apply = 0
            elif pid_out < 50:
                watts_to_apply = 800
            elif pid_out < 75:
                watts_to_apply = 1000
            elif pid_out < 90:
                watts_to_apply = 1400
            else:
                watts_to_apply = 1800
                
            # Limit by Step Setting
            step_limit = step.power_watts if step.power_watts is not None else 1800
            if watts_to_apply > step_limit:
                watts_to_apply = step_limit
                
        else:
            # Target 0 -> Off
            watts_to_apply = 0
            self.is_heating = False
            # If target is 0, we are "reached" immediately
            if not self.temp_reached:
                self.temp_reached = True
                self.step_start_time = time.monotonic()
                # --- FIX: Ensure clean start for 0-target steps as well ---
                self.total_paused_time = 0.0
                
                self._save_recovery_snapshot()

        # 4. Apply Power
        if watts_to_apply > 0:
            self._apply_power_logic(watts_to_apply)
        else:
            self.relay.set_relays(False, False, False)
            
        # Store for logging
        self.last_applied_power = watts_to_apply

    def _apply_power_logic(self, watts):
        h1 = False 
        h2 = False 

        if watts >= 1800:
            h1 = True; h2 = True
        elif watts == 1400:
            h1 = True
            cycle_time = time.monotonic() % 30
            if cycle_time < 15: h2 = True
            else: h2 = False
        elif watts == 1000:
            h1 = True; h2 = False
        elif watts == 800:
            h1 = False; h2 = True
        else:
            # SAFETY UPDATE: Catch-all defaults to OFF (0W)
            h1 = False; h2 = False

        self.relay.set_relays(h1, h2, False)


    def get_display_timer(self):
        # 1. Manual Mode
        if self.status == SequenceStatus.MANUAL:
            return self._fmt_time(self.manual_timer_remaining)
            
        # 2. Delayed Wait
        if self.status == SequenceStatus.DELAYED_WAIT:
             val = getattr(self, 'manual_timer_duration', 0.0)
             return self._fmt_time(val)

        # 3. Auto Mode (Running/Paused/Waiting)
        # Added bounds check: ensure index is within the list size
        if self.current_profile and self.current_step_index >= 0 and self.current_step_index < len(self.current_profile.steps):
            step = self.current_profile.steps[self.current_step_index]
            
            # Calculate duration in seconds
            duration_sec = (step.duration_min * 60.0) if step.duration_min else 0.0
            
            # Calculate remaining
            # Note: step_elapsed_time only increments once temp is reached. 
            # So this stays at "Full Duration" while heating, which is correct.
            remaining = duration_sec - self.step_elapsed_time
            if remaining < 0: remaining = 0
            
            return self._fmt_time(remaining)
            
        return "00:00"

    def _fmt_time(self, seconds):
        """Helper to format seconds into MMM:SS (e.g. 120:00)"""
        import math
        val = math.ceil(seconds)
        
        # Calculate total minutes and remaining seconds
        m = int(val // 60)
        s = int(val % 60)
        
        # Return strict MMM:SS format
        return f"{m:02d}:{s:02d}"
    
    def get_global_elapsed_time_str(self):
        if self.global_start_time is None:
            return "00:00"
            
        now = time.monotonic()
        
        if self.status in [SequenceStatus.PAUSED, SequenceStatus.WAITING_FOR_USER] and self.last_pause_start > 0:
            current_pause_duration = now - self.last_pause_start
            total_elapsed = now - self.global_start_time - self.global_paused_time - current_pause_duration
        else:
            total_elapsed = now - self.global_start_time - self.global_paused_time
            
        if total_elapsed < 0: total_elapsed = 0
        
        minutes = int(total_elapsed // 60)
        hours = int(minutes // 60)
        minutes = minutes % 60
        
        return f"{hours:02d}:{minutes:02d}"

    def get_status_message(self):
        if self.status == SequenceStatus.IDLE: return "Ready"
        if self.status == SequenceStatus.COMPLETED: return "Brew Complete"
        if self.status == SequenceStatus.MANUAL: return "MANUAL MODE"
        if self.status == SequenceStatus.DELAYED_WAIT: return self.get_delayed_status_msg()
        
        # --- PROFILE SAFETY CHECK ---
        # If we are here, we expect a profile. If none, return error or idle.
        if not self.current_profile or self.current_step_index < 0:
            return "No Profile Loaded"

        # Safe to access steps now
        try:
            step = self.current_profile.steps[self.current_step_index]
        except IndexError:
            return "Step Error"
        
        if self.status == SequenceStatus.RUNNING and not self.temp_reached:
            return f"HEATING - {step.name}"

        base_status = f"Step {self.current_step_index+1}: {step.name}"
        
        if self.status == SequenceStatus.PAUSED:
            return f"PAUSED - {base_status}"
        elif self.status == SequenceStatus.WAITING_FOR_USER:
             if self.current_alert_text:
                 if self.current_alert_text == "Step Complete":
                     return f"DONE:\n{step.name}"
                 return f"ALERT: {self.current_alert_text}"
             return f"WAITING - {base_status}"
            
        return base_status

    def get_target_temp(self):
        # FIXED: Return delayed target as source of truth during Wait Phase
        if self.status == SequenceStatus.DELAYED_WAIT:
            return getattr(self, 'delayed_target_temp', 0.0)
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
        
