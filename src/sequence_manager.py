"""
kettlebrain/src/sequence_manager.py
"""
import time
import threading
import math
from datetime import datetime # <--- ADD THIS
from profile_data import BrewProfile, StepType, TimeoutBehavior, SequenceStatus
import subprocess
import os

class SequenceManager:
    def __init__(self, settings_manager, relay_control, hardware_interface):
        self.settings = settings_manager
        self.relay = relay_control 
        self.hw = hardware_interface
        
        self.current_profile = None
        self.current_step_index = -1
        self.status = SequenceStatus.IDLE
        
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
        
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._control_loop, daemon=True)
        self._thread.start()

    def _play_alert_sound(self):
        """Plays alert.wav using aplay (non-blocking)."""
        try:
            # Locate the asset relative to this file
            base_dir = os.path.dirname(os.path.abspath(__file__))
            sound_file = os.path.join(base_dir, "assets", "alert.wav")
            
            if os.path.exists(sound_file):
                # Use Popen to fire-and-forget (avoids pausing the control loop)
                subprocess.Popen(["aplay", "-q", sound_file], stderr=subprocess.DEVNULL)
            else:
                print(f"[Sequence] Alert sound missing: {sound_file}")
        except Exception as e:
            print(f"[Sequence] Error playing sound: {e}")
    
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
        self.status = SequenceStatus.IDLE
        self.current_step_index = -1
        self.relay.turn_off_all_relays()
        self.is_heating = False
        self.current_alert_text = None
        self.global_start_time = None
        
        # CLEAR RECOVERY STATE on manual stop
        self.settings.clear_recovery_state()

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
        
        # --- FIXED: Removed check for StepType.DELAYED_START ---
        if self.global_start_time is None:
            self.global_start_time = time.monotonic()
        # -------------------------------------------------------
        
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

    # --- DELAYED START LOGIC ---
    def start_delayed_mode(self, target_temp, volume_gal, ready_time_dt):
        """
        Calculates when to fire the heater so water is ready at ready_time_dt.
        Enters DELAYED_WAIT state.
        """
        self.stop() # Reset status
        
        # 1. Get Constants
        ref_vol = self.settings.get_system_setting("heater_ref_volume_gal", 8.0)
        ref_rate = self.settings.get_system_setting("heater_ref_rate_fpm", 1.2)
        
        # 2. Calculate adjusted rate for this volume
        try:
            adj_rate = ref_rate * (ref_vol / float(volume_gal))
        except ZeroDivisionError:
            adj_rate = ref_rate

        # 3. Calculate Temp Rise needed
        current = self.current_temp if self.current_temp else 60.0 # Fallback
        rise = float(target_temp) - current
        if rise < 0: rise = 0
        
        # 4. Calculate Duration (Minutes)
        duration_min = rise / adj_rate
        
        # 5. Calculate Start Time (Epoch)
        ready_epoch = ready_time_dt.timestamp()
        start_epoch = ready_epoch - (duration_min * 60)
        
        # --- STORE DATA ---
        self.delayed_start_epoch = start_epoch
        self.delayed_target_temp = float(target_temp)
        self.delayed_vol = float(volume_gal) # Stored for "Edit" feature
        self.delayed_ready_time_str = ready_time_dt.strftime("%H:%M")
        self.delayed_start_time_str = datetime.fromtimestamp(start_epoch).strftime("%H:%M")
        
        # Update Manual Mode Setpoint immediately
        self.set_manual_target(self.delayed_target_temp)
        
        self.status = SequenceStatus.DELAYED_WAIT
        print(f"[Sequence] Delayed Start Set.")
        print(f"   Ready By: {self.delayed_ready_time_str}")
        print(f"   Heater Fires At: {self.delayed_start_time_str}")
        
        # CRITICAL: Save state immediately so we can recover from power loss
        self._save_recovery_snapshot()

    def get_delayed_status_msg(self):
        """Returns the dynamic lines for the UI button."""
        if self.status != SequenceStatus.DELAYED_WAIT: return ""
        # The UI will prepend "DELAY ACTIVE" and "SLEEPING"
        return f"Ready at: {self.delayed_ready_time_str}\nHeat starts at: {self.delayed_start_time_str}"

    # --- MANUAL MODE METHODS ---
    def enter_manual_mode(self):
        """Switches the system to manual control."""
        self.stop() # Reset everything first
        self.status = SequenceStatus.MANUAL
        
        # Retrieve values individually
        self.target_temp = self.settings.get("manual_mode_settings", "last_setpoint_f", 150.0)
        timer_min = self.settings.get("manual_mode_settings", "last_timer_min", 60.0)
        self.manual_timer_duration = timer_min * 60.0
        
        # Load heater state, but reset timing logic
        self.is_heating = self.settings.get("manual_mode_settings", "heater_enabled", False)
        self.step_start_time = 0.0 
        self.temp_reached = False # [FIX] Ensure we wait for temp before counting down
        
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

            # --- DELAYED START WAIT ---
            if self.status == SequenceStatus.DELAYED_WAIT:
                # 1. Check if it's time to wake up
                if time.time() >= self.delayed_start_epoch:
                    print("[Sequence] Delayed Wait Over. Firing Heater (Transition to Manual Hold).")
                    self.enter_manual_mode()
                    self.set_manual_target(self.delayed_target_temp)
                    self.toggle_manual_heater(True)
                else:
                    # Keep relays off while sleeping
                    self.relay.set_relays(False, False, False)
                continue

            # --- MANUAL MODE LOGIC ---
            if self.status == SequenceStatus.MANUAL:
                if self.is_heating:
                    self._manage_temperature_generic(self.target_temp)
                else:
                    self.relay.set_relays(False, False, False)
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
        """Simple hysteresis control for Manual Mode + Timer Trigger."""
        if target <= 0: 
            self.relay.set_relays(False, False, False)
            return

        # [FIX] Check if we reached target to start timer
        if not self.temp_reached:
             if self.current_temp >= target:
                 self.temp_reached = True
                 self.step_start_time = time.monotonic()
                 # Play alert sound to notify user target is reached
                 self._play_alert_sound() 
                 print(f"[Sequence] Manual Target Reached ({self.current_temp}). Timer Started.")

        # Power Logic (Hysteresis)
        if self.current_temp < (target - 0.5):
            self._apply_power_logic(1800) # Full power
        elif self.current_temp > target:
            self.relay.set_relays(False, False, False)
        # else: maintain current state
            
    def _save_recovery_snapshot(self):
        """Saves current progress to settings for power-loss recovery."""
        state = {
            "status": self.status.value,
            "timestamp": time.time()
        }

        # 1. SAVE DELAY STATE
        if self.status == SequenceStatus.DELAYED_WAIT:
            state["mode_type"] = "DELAY"
            state["delayed_start_epoch"] = getattr(self, 'delayed_start_epoch', 0)
            state["delayed_target_temp"] = getattr(self, 'delayed_target_temp', 0)
            state["delayed_vol"] = getattr(self, 'delayed_vol', 0)
            state["delayed_ready_time_str"] = getattr(self, 'delayed_ready_time_str', "")
            state["delayed_start_time_str"] = getattr(self, 'delayed_start_time_str', "")
            
            self.settings.save_recovery_state(state)
            return

        # 2. SAVE PROFILE STATE
        if self.current_profile:
            state["mode_type"] = "PROFILE"
            state["profile_id"] = self.current_profile.id
            state["step_index"] = self.current_step_index
            state["elapsed_time"] = self.step_elapsed_time
            state["temp_reached"] = self.temp_reached
            state["global_elapsed"] = self._get_total_elapsed_seconds()
            
            self.settings.save_recovery_state(state)
    def _get_total_elapsed_seconds(self):
        if self.global_start_time is None: return 0
        return time.monotonic() - self.global_start_time - self.global_paused_time

    # --- RESTORE LOGIC ---
    def restore_from_recovery(self, state_dict):
        """Called by Main to resume a crashed/interrupted session."""
        mode_type = state_dict.get("mode_type", "PROFILE")
        
        # --- RESTORE DELAYED START ---
        if mode_type == "DELAY":
            print("[Sequence] Restoring Delayed Start...")
            
            # 1. Restore Variables
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
                
            return

        # --- RESTORE PROFILE ---
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
        # --- FIX: Safety Guard ---
        # If the sensor is reading None (startup or error), we cannot compare data.
        # Safety Protocol: Turn off all relays and skip this cycle.
        if self.current_temp is None:
            self.relay.set_relays(False, False, False)
            return
        # -------------------------

        heat_needed = False
        watt_target = 1800 
        
        if step.power_watts is not None:
            watt_target = step.power_watts

        if step.step_type == StepType.BOIL:
            if not self.temp_reached:
                watt_target = 1800 
                boil_target = step.setpoint_f if step.setpoint_f else 212.0
                if self.current_temp >= boil_target:
                    self.temp_reached = True
                    self.step_start_time = time.monotonic()
                    # Save state on temp reach
                    self._save_recovery_snapshot()
                heat_needed = True 
            else:
                heat_needed = True

        elif step.step_type == StepType.CHILL:
            heat_needed = False
            if not self.temp_reached:
                self.temp_reached = True
                self.step_start_time = time.monotonic()
                self._save_recovery_snapshot()

        elif self.target_temp > 0:
            if self.current_temp < (self.target_temp - 0.5):
                heat_needed = True
            elif self.current_temp > self.target_temp:
                heat_needed = False
            else:
                heat_needed = self.is_heating 
            
            if not self.temp_reached and self.current_temp >= self.target_temp:
                self.temp_reached = True
                self.step_start_time = time.monotonic()
                self._save_recovery_snapshot()
        
        else:
            if not self.temp_reached:
                self.temp_reached = True
                self.step_start_time = time.monotonic()
                self._save_recovery_snapshot()

        self.is_heating = heat_needed
        if heat_needed:
            self._apply_power_logic(watt_target)
        else:
            self.relay.set_relays(False, False, False)

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
                        # Save state on Alert
                        self._save_recovery_snapshot()
                        
                        if self.step_elapsed_time < 1.0 or duration_val <= 0.0:
                             self.last_pause_start = time.monotonic()
                        return

        if self.step_elapsed_time >= duration_sec:
            if hasattr(step, 'additions'):
                if any(not a.triggered for a in step.additions):
                    return 

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

        # 2. Handle MANUAL MODE (New Logic)
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

        # 3. Handle AUTO PROFILE MODE (Existing Logic)
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
        # Note: No parentheses because is_manual_running is a @property
        if not self.is_manual_running:
            # START: Enable Heater
            self.is_heating = True
            
            # [FIX] Only resume timer if we had already reached temp
            if self.temp_reached:
                if self.step_start_time == 0: 
                    self.step_start_time = time.monotonic()
                elif self.last_pause_start > 0: 
                    # Resume from pause
                     paused_duration = time.monotonic() - self.last_pause_start
                     self.step_start_time += paused_duration
                     self.last_pause_start = 0
            
            # If temp_reached is False, we leave step_start_time as 0.0.
            # The _manage_temperature_generic loop will detect when target is hit
            # and start the timer then.

            print("[Sequence] Manual Playback STARTED")
        else:
            # PAUSE: Disable Heater and Pause Timer
            self.is_heating = False
            self.last_pause_start = time.monotonic()
            print("[Sequence] Manual Playback PAUSED")

    def reset_manual_state(self):
        """Stops heater, resets timer, but STAYS in Manual Mode."""
        self.is_heating = False
        self.step_start_time = 0.0
        self.last_pause_start = 0.0
        self.temp_reached = False
        print("[Sequence] Manual Mode RESET")
