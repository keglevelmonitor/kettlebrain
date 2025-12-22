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
        
        # --- PID SETUP ---
        # CORRECTED: Use get_section() to retrieve the full dict
        pid_cfg = self.settings.get_section("pid_settings") 
        self.pid = PIDController(
            kp=pid_cfg.get("kp", 100.0),   # Increased from 50.0 to tighten steady-state deadband
            ki=pid_cfg.get("ki", 0.01),   # Reduced from 0.05 to eliminate integral overshoot
            kd=pid_cfg.get("kd", 80.0),   # Increased from 2.0 to provide braking on ramp-up
            output_limits=(0, 100)
        )
        self.last_pid_update = 0.0
        self.last_applied_power = 0  # <--- NEW: Tracks actual output for logs

        # Track if Delayed Start was launched from Auto (IDLE) or Manual context
        self.delayed_is_auto = True
        
        self.step_start_time = 0.0
        self.total_paused_time = 0.0
        self.last_pause_start = 0.0
        self.step_elapsed_time = 0.0
        
        self.global_start_time = None
        self.global_paused_time = 0.0
        
        self.temp_reached = False 
        
        self.current_temp = 0.0
        self.target_temp = 0.0
        self.is_heating = False
        
        self.current_alert_text = None
        
        # --- ALERTS ---
        self.last_alert_time = 0.0

        # --- RECOVERY HEARTBEAT ---
        self.last_recovery_save = 0.0
        self.RECOVERY_SAVE_INTERVAL = 30.0 
        
        self.last_log_write = 0.0  # <--- NEW: CSV Log Timer
        
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._control_loop, daemon=True)
        self._thread.start()

    def _play_alert_sound(self):
        """Plays the configured alert sound using aplay (non-blocking)."""
        try:
            base_dir = os.path.dirname(os.path.abspath(__file__))
            
            # Retrieve configured filename (default to alert.wav)
            sound_filename = self.settings.get_system_setting("alert_sound_file", "alert.wav")
            sound_file = os.path.join(base_dir, "assets", sound_filename)
            
            if os.path.exists(sound_file):
                dev_friendly = self.settings.get_system_setting("audio_device", "default")
                dev_str = "default"
                
                if dev_friendly != "default":
                    devices = self.hw.scan_audio_devices()
                    found = next((d_str for friendly, d_str in devices if friendly == dev_friendly), "default")
                    dev_str = found
                
                cmd = ["aplay", "-q"]
                if dev_str != "default":
                    cmd.extend(["-D", dev_str])
                
                cmd.append(sound_file)
                subprocess.Popen(cmd, stderr=subprocess.DEVNULL)
            else:
                print(f"[Sequence] Alert sound missing: {sound_file}")
        except Exception as e:
            print(f"[Sequence] Error playing sound: {e}")
    
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
        if self.status == SequenceStatus.IDLE:
            self.current_step_index = 0
            self.global_start_time = None
            self.global_paused_time = 0.0
            
            self._init_step(self.current_step_index)
            self.status = SequenceStatus.RUNNING
            print("[Sequence] Started.")

    def pause_sequence(self):
        if self.status == SequenceStatus.RUNNING:
            self.status = SequenceStatus.PAUSED
            self.last_pause_start = time.monotonic()
            self.relay.turn_off_all_relays() 
            self.is_heating = False
            # Save state immediately on pause
            self._save_recovery_snapshot()

    def resume_sequence(self):
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

    def stop(self):
        # Log the final state before we go IDLE
        if self.status != SequenceStatus.IDLE:
             self._log_csv()

        self.status = SequenceStatus.IDLE
        self.current_step_index = -1
        self.relay.turn_off_all_relays()
        self.is_heating = False
        self.current_alert_text = None
        self.global_start_time = None
        
        # CLEAR RECOVERY STATE on manual stop
        self.settings.clear_recovery_state()

    def reset_profile(self):
        """
        Stops the current sequence and resets the profile pointers to the beginning,
        clearing all triggered alerts so the profile can be run again from scratch.
        """
        # 1. Safety Stop (Heaters Off, Status=IDLE, Index=-1)
        self.stop()
        
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
        
        # --- CAPTURE INITIAL TEMP (For "Already at Target" Rule) ---
        self.initial_step_temp = self.current_temp if self.current_temp is not None else 0.0
        # -----------------------------------------------------------

        if self.global_start_time is None:
            self.global_start_time = time.monotonic()
        
        if step.setpoint_f is not None:
            self.target_temp = step.setpoint_f
        elif step.lauter_temp_f is not None:
            self.target_temp = step.lauter_temp_f
        else:
            self.target_temp = 0.0
            
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
        
        # 1. Get Calibration Constants (Reference: 1800W @ 8.0 Gal)
        ref_rate_fpm = self.settings.get_system_setting("heater_ref_rate_fpm", 1.2)
        ref_vol = self.settings.get_system_setting("heater_ref_volume_gal", 8.0)
        
        # 2. Adjust for Volume
        # Rate increases if volume is lower than reference
        vol_factor = ref_vol / float(vol_gal)
        
        # 3. Adjust for Power
        # Rate decreases if power is lower than 1800W
        power_factor = float(watts) / 1800.0
        
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
        """Switches the system to manual control."""
        # [FIX] Do NOT call self.stop().
        # self.stop() might clear the current profile in some contexts.
        # We manually reset the operational state instead to preserve the loaded profile.
        self.status = SequenceStatus.MANUAL
        self.current_step_index = -1
        self.relay.turn_off_all_relays()
        self.current_alert_text = None
        self.global_start_time = None
        
        # Clear old recovery state logic manually since we aren't calling stop()
        self.settings.clear_recovery_state()
        
        # Retrieve values
        self.target_temp = self.settings.get("manual_mode_settings", "last_setpoint_f", 150.0)
        timer_min = self.settings.get("manual_mode_settings", "last_timer_min", 60.0)
        
        # NEW: Retrieve Power and Volume
        self.manual_power_watts = self.settings.get("manual_mode_settings", "last_power_watts", 1800)
        self.manual_volume_gal = self.settings.get("manual_mode_settings", "last_volume_gal", 6.0)
        
        self.manual_timer_duration = timer_min * 60.0        
        # Always default heater to OFF when entering Manual Mode (Safety)
        self.is_heating = False
        
        self.step_start_time = 0.0 
        self.temp_reached = False 
        
        print(f"[Sequence] Entered Manual Mode. Target: {self.target_temp}")

    def toggle_manual_heater(self, enabled):
        """Toggles the heater on/off in manual mode."""
        self.is_heating = enabled
        self.settings.set("manual_mode_settings", "heater_enabled", enabled)
        if not enabled:
            self.relay.turn_off_all_relays()

    def set_manual_target(self, temp_f):
        """Updates the manual mode setpoint."""
        self.target_temp = float(temp_f)
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
                self.current_temp = 0.0

            # Safety: If sensor fails, kill power
            if self.current_temp is None:
                self.relay.set_relays(False, False, False)
                continue

            # --- NEW: CSV LOGGING (Every 30s) ---
            # We use monotonic time for the interval check so it is robust
            now_mono = time.monotonic()
            if now_mono - self.last_log_write > 30.0:
                self._log_csv()
                self.last_log_write = now_mono
            # ------------------------------------

            # --- DELAYED START WAIT ---
            if self.status == SequenceStatus.DELAYED_WAIT:
                now = time.time()
                
                # ADAPTIVE RECALCULATION (Every 30 seconds)
                if now - last_delay_calc > 30.0:
                    last_delay_calc = now
                    
                    # 1. Get Constants
                    ref_vol = self.settings.get_system_setting("heater_ref_volume_gal", 8.0)
                    ref_rate = self.settings.get_system_setting("heater_ref_rate_fpm", 1.2)
                    
                    # 2. Re-calculate rate based on stored volume
                    try:
                        adj_rate = ref_rate * (ref_vol / self.delayed_vol)
                    except:
                        adj_rate = ref_rate

                    # 3. Calculate Rise needed from CURRENT temp
                    current = self.current_temp if self.current_temp else 60.0
                    rise = self.delayed_target_temp - current
                    if rise < 0: rise = 0
                    
                    # 4. New Duration & Start Time
                    duration_min = rise / adj_rate
                    new_start_epoch = self.delayed_ready_epoch - (duration_min * 60)
                    
                    # 5. Update State
                    self.delayed_start_epoch = new_start_epoch
                    self.delayed_start_time_str = datetime.fromtimestamp(new_start_epoch).strftime("%H:%M")
                    
                # CHECK TRIGGER
                if now >= self.delayed_start_epoch:
                    print(f"[Sequence] Delayed Wait Over (Start Time: {self.delayed_start_time_str}). Firing Heater.")
                    
                    # Transition to Manual Mode
                    # Since we pre-set the settings (30m, 1800W) in start_delayed_mode, 
                    # enter_manual_mode will load those exact values.
                    self.enter_manual_mode()
                    
                    # Turn on the heater to begin the "Hold" process
                    self.toggle_manual_heater(True)
                else:
                    # Keep relays off while sleeping
                    self.relay.set_relays(False, False, False)
                continue

            # --- MANUAL MODE LOGIC ---
            if self.status == SequenceStatus.MANUAL:
                
                # 1. Check Manual Timer Expiration
                if self.step_start_time > 0 and self.last_pause_start == 0:
                    # Calculate elapsed time
                    elapsed = time.monotonic() - self.step_start_time - self.total_paused_time
                    duration = getattr(self, 'manual_timer_duration', 3600.0)
                    
                    if elapsed >= duration:
                        print("[Sequence] Manual Timer Expired. Stopping.")
                        self.reset_manual_state() # Stops heater, resets timer
                        self._play_alert_sound()  # Play Sound
                
                # 2. Heater Control
                if self.is_heating:
                    self._manage_temperature_generic(self.target_temp)
                else:
                    self.relay.set_relays(False, False, False)
                
                # 3. Heartbeat Save
                now = time.monotonic()
                if now - self.last_recovery_save > self.RECOVERY_SAVE_INTERVAL:
                    self._save_recovery_snapshot()
                    self.last_recovery_save = now
            
                continue
            
            # --- AUTO / PROFILE LOGIC ---
            if not self.current_profile or self.current_step_index < 0:
                continue

            step = self.current_profile.steps[self.current_step_index]

            if self.status in [SequenceStatus.RUNNING, SequenceStatus.WAITING_FOR_USER]:
                self._manage_temperature(step)
            elif self.status == SequenceStatus.PAUSED:
                self.relay.turn_off_all_relays()
                self.is_heating = False

            if self.status == SequenceStatus.RUNNING:
                self._process_time_logic(step)
                
                # Heartbeat Save
                now = time.monotonic()
                if now - self.last_recovery_save > self.RECOVERY_SAVE_INTERVAL:
                    self._save_recovery_snapshot()
                    self.last_recovery_save = now

            # Alert Sounds
            if self.status == SequenceStatus.WAITING_FOR_USER:
                now = time.monotonic()
                if now - self.last_alert_time > 5.0:
                    self._play_alert_sound()
                    self.last_alert_time = now
                    
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

        # --- PID CALCULATION ---
        watts_to_apply = 0
        pid_out = self.pid.compute(self.current_temp, target)
        
        # Map to discrete power
        if pid_out <= 0: watts_to_apply = 0
        elif pid_out < 20: watts_to_apply = 0
        elif pid_out < 50: watts_to_apply = 800
        elif pid_out < 75: watts_to_apply = 1000
        elif pid_out < 90: watts_to_apply = 1400
        else: watts_to_apply = 1800
            
        # --- NEW LOGIC START ---
        # Limit by User Setting (Always enforce)
        limit = getattr(self, 'manual_power_watts', 1800)
        
        if watts_to_apply > limit:
            watts_to_apply = limit
        # --- NEW LOGIC END ---
            
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
            tgt_t = f"{tgt:.2f}"

            # Determine Power (Watts) - CHANGED TO USE ACTUAL APPLIED POWER
            watts = 0
            if self.is_heating:
                watts = getattr(self, 'last_applied_power', 0)
            
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
        # Safety Protocol
        if self.current_temp is None:
            self.relay.set_relays(False, False, False)
            return

        # Define Target
        target = 0.0
        if step.setpoint_f is not None:
            target = step.setpoint_f
        elif step.lauter_temp_f is not None:
            target = step.lauter_temp_f

        # Special Case: BOIL steps usually just want 100% power if not at boil
        if step.step_type == StepType.BOIL:
             target = step.setpoint_f if step.setpoint_f else self.settings.get_system_setting("boil_temp_f", 212.0)

        # --- PID CALCULATION ---
        watts_to_apply = 0
        
        if target > 0:
            # Check for Temp Reached (Timer Trigger) logic
            if not self.temp_reached:
                # Clamp trigger to system boil temp
                sys_boil = self.settings.get_system_setting("boil_temp_f", 212.0)
                if self.current_temp >= min(target, sys_boil):
                    self.temp_reached = True
                    self.step_start_time = time.monotonic()
                    
                    # Alert sound logic
                    start_t = getattr(self, 'initial_step_temp', 0.0)
                    if start_t < (target - 0.5):
                        self._play_alert_sound()
                    self._save_recovery_snapshot()

            # Execute PID
            pid_out = self.pid.compute(self.current_temp, target)
            self.is_heating = (pid_out > 0)
            
            # --- MAP PID % TO DISCRETE POWER LEVELS ---
            if pid_out <= 0:
                watts_to_apply = 0
            elif pid_out < 20:
                watts_to_apply = 0  # Deadband at very low error
            elif pid_out < 50:
                watts_to_apply = 800
            elif pid_out < 75:
                watts_to_apply = 1000
            elif pid_out < 90:
                watts_to_apply = 1400
            else:
                watts_to_apply = 1800
                
            # --- NEW LOGIC START ---
            # Override for Manual Max Power Limit (if step has a limit)
            step_limit = step.power_watts if step.power_watts is not None else 1800
            
            if watts_to_apply > step_limit:
                watts_to_apply = step_limit
            # --- NEW LOGIC END ---
                
        else:
            # Target is 0, turn off
            watts_to_apply = 0
            self.is_heating = False
            # If step has 0 target (e.g. "Add Grains"), mark reached immediately
            if not self.temp_reached:
                self.temp_reached = True
                self.step_start_time = time.monotonic()
                self._save_recovery_snapshot()

        # Apply the Calculated Power
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
            h1 = True; h2 = False

        self.relay.set_relays(h1, h2, False)

    def _process_time_logic(self, step):
        if not self.temp_reached:
            self.step_elapsed_time = 0
            return 

        now = time.monotonic()
        self.step_elapsed_time = now - self.step_start_time - self.total_paused_time
        
        duration_val = step.duration_min if step.duration_min is not None else 0.0
        duration_sec = duration_val * 60.0
        remaining_sec = duration_sec - self.step_elapsed_time
        remaining_min = remaining_sec / 60.0

        if hasattr(step, 'additions'):
            for add in step.additions:
                if not add.triggered:
                    should_trigger = False
                    if remaining_min <= (add.time_point_min + 0.005):
                        should_trigger = True
                    if duration_val <= 0.0:
                        should_trigger = True

                    if should_trigger:
                        add.triggered = True 
                        self.status = SequenceStatus.WAITING_FOR_USER
                        self.current_alert_text = add.name
                        
                        # SOUND: Play Alert Sound
                        self._play_alert_sound()
                        
                        # Save state on Alert
                        self._save_recovery_snapshot()
                        
                        if self.step_elapsed_time < 1.0 or duration_val <= 0.0:
                             self.last_pause_start = time.monotonic()
                        return

        if self.step_elapsed_time >= duration_sec:
            if hasattr(step, 'additions'):
                if any(not a.triggered for a in step.additions):
                    return 

            # SOUND: Step Complete (Only if it actually had a duration)
            if duration_val > 0.0:
                self._play_alert_sound()

            if step.timeout_behavior == TimeoutBehavior.AUTO_ADVANCE:
                self.advance_step()
            else:
                self.status = SequenceStatus.WAITING_FOR_USER
                self.last_pause_start = time.monotonic()
                self.current_alert_text = "Step Complete"
                self._save_recovery_snapshot()
            return
                        
    def get_display_timer(self):
        # 1. Handle IDLE/COMPLETED (Zeroed)
        if self.status in [SequenceStatus.IDLE, SequenceStatus.COMPLETED]: 
            return "0:00:00"

        # 2. Handle DELAYED_WAIT (Preview the pending manual timer)
        if self.status == SequenceStatus.DELAYED_WAIT:
            # We want to show the full duration (e.g. 30:00) that will start later
            total_sec = getattr(self, 'manual_timer_duration', 1800.0)
            
            val = math.ceil(total_sec)
            h = int(val // 3600)
            rem_h = val % 3600
            m = int(rem_h // 60)
            s = int(rem_h % 60)
            return f"{h}:{m:02d}:{s:02d}"

        # 3. Handle MANUAL MODE (New Logic)
        if self.status == SequenceStatus.MANUAL:
            # Get the duration set by the slider (defaulting to 60m if missing)
            total_sec = getattr(self, 'manual_timer_duration', 3600.0)
            
            # Determine how much time has passed
            elapsed = 0.0
            if self.step_start_time > 0:
                # Timer is Active or Paused
                now = time.monotonic()
                if self.last_pause_start > 0:
                    # Currently Paused
                    elapsed = self.last_pause_start - self.step_start_time - self.total_paused_time
                else:
                    # Currently Running
                    elapsed = now - self.step_start_time - self.total_paused_time
            
            # Calculate remaining
            rem_sec = max(0, total_sec - elapsed)
            
            # Format
            val = math.ceil(rem_sec)
            h = int(val // 3600)
            rem_h = val % 3600
            m = int(rem_h // 60)
            s = int(rem_h % 60)
            return f"{h}:{m:02d}:{s:02d}"

        # 4. Handle AUTO PROFILE MODE (Existing Logic)
        if not self.current_profile: return "0:00:00"

        # Calculating Total Duration for the "Heater Active but Timer Waiting" phase
        if self.status == SequenceStatus.RUNNING and not self.temp_reached:
             step = self.current_profile.steps[self.current_step_index]
             total_sec = int(step.duration_min * 60)
             h = total_sec // 3600
             rem = total_sec % 3600
             m = rem // 60
             s = rem % 60
             return f"{h}:{m:02d}:{s:02d}"

        # Standard Step Timer Logic
        step = self.current_profile.steps[self.current_step_index]
        total_sec = step.duration_min * 60.0
        
        is_live = False
        if self.status == SequenceStatus.RUNNING:
            is_live = True
        elif self.status == SequenceStatus.WAITING_FOR_USER:
             if self.last_pause_start == 0:
                is_live = True

        if is_live:
            current_elapsed = time.monotonic() - self.step_start_time - self.total_paused_time
            rem_sec = total_sec - current_elapsed
            if rem_sec < 0: rem_sec = 0 
        else:
            if self.last_pause_start > 0:
                current_elapsed = self.last_pause_start - self.step_start_time - self.total_paused_time
                rem_sec = max(0, total_sec - current_elapsed)
            else:
                rem_sec = max(0, total_sec - self.step_elapsed_time)
            
        val = math.ceil(rem_sec)
        
        h = int(val // 3600)
        rem_h = val % 3600
        m = int(rem_h // 60)
        s = int(rem_h % 60)
        
        return f"{h}:{m:02d}:{s:02d}"

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
        
    # =========================================
    # MANUAL MODE PLAYBACK CONTROLS
    # =========================================
    @property
    def is_manual_running(self):
        """Returns True if Manual Mode is 'Active' and NOT Paused."""
        # It is running if we are in MANUAL mode, AND
        # (Heater is ON OR Timer has started) AND
        # We are NOT currently in a paused state (last_pause_start == 0)
        return (self.status == SequenceStatus.MANUAL and 
                (self.is_heating or self.step_start_time > 0) and 
                self.last_pause_start == 0)

    def toggle_manual_playback(self):
        """Toggles between START (Active) and PAUSE (Inactive) for Manual Mode."""
        if not self.is_manual_running:
            # START: Enable Heater
            self.is_heating = True
            
            # --- CAPTURE INITIAL TEMP (For Manual Sound Logic) ---
            self.initial_manual_temp = self.current_temp if self.current_temp is not None else 0.0
            # -----------------------------------------------------

            # LOGIC FIX: Always reset pause flag when starting
            if self.temp_reached:
                if self.step_start_time == 0: 
                    self.step_start_time = time.monotonic()
                elif self.last_pause_start > 0: 
                    # Resume timer from pause
                     paused_duration = time.monotonic() - self.last_pause_start
                     self.step_start_time += paused_duration
            
            # Force the system to recognize we are no longer paused
            self.last_pause_start = 0
            
            print("[Sequence] Manual Playback STARTED")
        else:
            # PAUSE: Disable Heater and Pause Timer
            self.is_heating = False
            self.last_pause_start = time.monotonic()
            print("[Sequence] Manual Playback PAUSED")

        # Save state immediately on toggle
        self._save_recovery_snapshot()

    def reset_manual_state(self):
        """Stops heater, resets timer, but STAYS in Manual Mode."""
        self.is_heating = False
        self.step_start_time = 0.0
        self.last_pause_start = 0.0
        self.temp_reached = False
        print("[Sequence] Manual Mode RESET")
