"""
kettlebrain app
settings_manager.py
"""

import json
import os
import threading
import uuid
import copy
from datetime import datetime
from profile_data import BrewProfile, BrewStep, BrewAddition, StepType, TimeoutBehavior

SETTINGS_FILE = "kettlebrain_settings.json"

DEFAULT_SETTINGS = {
    "system_settings": {
        "units": "imperial",
        "temp_sensor_id": "unassigned",
        "heater1_gpio": 26,     # Relay 1 (Hardcoded to 26 in RelayControl for now)
        "heater2_gpio": 20,     # Relay 2
        "heater3_gpio": 21,     # Relay 3 (Renamed from aux_gpio)
        "pump_gpio": 27,
        "buzzer_gpio": 13,
        "sensor_type": "DS18B20",
        "screen_timeout": 300,
        "boil_temp_f": 212,         
        "relay_active_high": False,
        "relay_logic_configured": False,
        "force_numlock": True,
        "dev_mode": False,
        "controlled_shutdown": False,
        "auto_start_enabled": True,
        "auto_resume_enabled": False,
        "enable_csv_logging": False,
        "heater_ref_volume_gal": 8.0,
        "heater_ref_rate_fpm": 1.3,
        "last_profile_id": None,
        "alert_repeat_freq": 15,
        "cost_per_kwh": 0.120
    },
    # --- HEATER CONFIG ---
    "heater_config": {
        "relay1_watts": 1000,
        "relay2_watts": 800,
        "relay3_watts": 1000
    },
    "manual_mode_settings": {
        "last_setpoint_f": 150.0,
        "last_timer_min": 60.0,
        "last_ramp_watts": 1800, # <--- NEW
        "last_hold_watts": 1800, # <--- NEW
        "last_volume_gal": 6.0,
        "heater_enabled": False
    },
    "water_defaults": {
        "mash_method": "No Sparge (BIAB)",
        "tun_capacity": 10.0,
        "grain_wt": 10.0,
        "dough_in_temp": 154.0,
        "mash_temp": 152.0,
        "boil_time": 60.0,
        "ferm_vol": 5.75,
        "trub_vol": 0.25,
        "boiloff": 1.2,
        "abs_rate": 0.3,
        "thickness": 1.5,
        "srm": 5.0,
        "target_ph": 5.4,
        "tgt_ca": 50,
        "tgt_mg": 10,
        "tgt_na": 15,
        "tgt_so4": 75,
        "tgt_cl": 63
    },
    "manual_water_session": {}, 
    "pid_settings": {
        "kp": 50.0,
        "ki": 0.02,
        "kd": 10.0,
        "sample_time_s": 2.0
    },
    "recovery_state": None
}

class SettingsManager:
    def __init__(self, base_dir):
        self.base_dir = base_dir
        self.data_dir = os.path.join(base_dir, 'kettlebrain-data')
        self.settings_file = os.path.join(self.data_dir, 'kettlebrain_settings.json')
        self.profiles_file = os.path.join(self.data_dir, 'kettlebrain_profiles.json')
        self._data_lock = threading.RLock()
        
        self.settings = {}
        self.profiles = {}
        
        self.last_shutdown_was_clean = True 
        
        self._ensure_data_dir()
        self._load_settings()
        self._load_profiles()

    def _ensure_data_dir(self):
        try:
            os.makedirs(self.data_dir, exist_ok=True)
        except OSError as e:
            print(f"[SettingsManager] Error creating data dir: {e}")

    def _get_default_settings(self):
        return copy.deepcopy(DEFAULT_SETTINGS)

    def _create_default_profile_dict(self):
        """Creates the 'Default Profile'."""
        p_id = str(uuid.uuid4())
        profile = BrewProfile(id=p_id, name="Default Profile")
        
        # Add basic default water data
        profile.water_data = copy.deepcopy(DEFAULT_SETTINGS["water_defaults"])

        # --- STEP 1: Heat to Strike ---
        s1 = BrewStep(
            id=str(uuid.uuid4()), 
            name="Step", 
            step_type=StepType.STEP, 
            setpoint_f=156.0,
            duration_min=0.0,
            ramp_power_watts=1800, # <--- NEW
            hold_power_watts=1800, # <--- NEW
            lauter_volume=7.5,
            timeout_behavior=TimeoutBehavior.AUTO_ADVANCE,
            note="Heat to dough-in, reserve water, dough-in."
        )
        s1.additions.append(BrewAddition(name="Reserve 1.5 Gal for lautering", time_point_min=0))
        s1.additions.append(BrewAddition(name="Dough-in", time_point_min=0))
        s1.additions.append(BrewAddition(name="Turn on pump", time_point_min=0))
        profile.add_step(s1)
        
        # --- STEP 2: Mash ---
        s2 = BrewStep(
            id=str(uuid.uuid4()), 
            name="Mash", 
            step_type=StepType.MASH, 
            setpoint_f=152.0, 
            duration_min=60.0,
            ramp_power_watts=1800, # <--- NEW
            hold_power_watts=1800, # <--- NEW
            lauter_volume=6.5,
            timeout_behavior=TimeoutBehavior.AUTO_ADVANCE,
            note="Mash and take SG reading"
        )
        s2.additions.append(BrewAddition(name="Take SG reading", time_point_min=0))
        profile.add_step(s2)
        
        # --- STEP 3: Mash Out ---
        s3 = BrewStep(
            id=str(uuid.uuid4()), 
            name="Mash-out", 
            step_type=StepType.MASH_OUT, 
            setpoint_f=170.0, 
            duration_min=10.0,
            ramp_power_watts=1800, # <--- NEW
            hold_power_watts=1800, # <--- NEW
            timeout_behavior=TimeoutBehavior.AUTO_ADVANCE,
            note="Mash-out, turn off pump, lift basket, lauter"
        )
        s3.additions.append(BrewAddition(name="Turn off pump", time_point_min=0))
        s3.additions.append(BrewAddition(name="Lift grain basket", time_point_min=0))
        s3.additions.append(BrewAddition(name="Lauter with reserved water", time_point_min=0))
        profile.add_step(s3)
        
        # --- STEP 4: Boil ---
        s4 = BrewStep(
            id=str(uuid.uuid4()), 
            name="Boil", 
            step_type=StepType.BOIL, 
            setpoint_f=212.0, 
            duration_min=60.0,
            ramp_power_watts=1800, # <--- NEW
            hold_power_watts=1800, # <--- NEW
            lauter_volume=6.5,
            timeout_behavior=TimeoutBehavior.AUTO_ADVANCE,
            note="Boil and follow hops schedule"
        )
        s4.additions.append(BrewAddition(name="Bittering hops", time_point_min=60))
        s4.additions.append(BrewAddition(name="Flavor hops", time_point_min=30))
        s4.additions.append(BrewAddition(name="Irish Moss", time_point_min=10))
        s4.additions.append(BrewAddition(name="Aroma hops", time_point_min=5))
        profile.add_step(s4)

        # --- STEP 5: Chill ---
        s5 = BrewStep(
            id=str(uuid.uuid4()), 
            name="Chill", 
            step_type=StepType.CHILL, 
            setpoint_f=70.0, 
            duration_min=15.0,
            ramp_power_watts=1800, # <--- NEW
            hold_power_watts=1800, # <--- NEW
            lauter_volume=5.5,
            timeout_behavior=TimeoutBehavior.END_PROGRAM,
            note=""
        )
        s5.additions.append(BrewAddition(name="Take SG reading", time_point_min=0))
        profile.add_step(s5)
        
        return {
            p_id: profile.to_dict()
        }

    def _load_settings(self):
        with self._data_lock:
            import copy
            if not os.path.exists(self.settings_file):
                self.settings = copy.deepcopy(DEFAULT_SETTINGS)
                # Initialize session with defaults on new file creation
                self.settings["manual_water_session"] = copy.deepcopy(self.settings["water_defaults"])
                self._save_settings()
            else:
                try:
                    with open(self.settings_file, 'r', encoding='utf-8') as f:
                        self.settings = json.load(f)
                    
                    defaults = copy.deepcopy(DEFAULT_SETTINGS)
                    for section, data in defaults.items():
                        if section not in self.settings:
                            self.settings[section] = data
                        elif isinstance(data, dict):
                            for key, val in data.items():
                                if key not in self.settings[section]:
                                    self.settings[section][key] = val
                                    
                    # --- CRITICAL: RESET MANUAL WATER SESSION ON BOOT ---
                    # As requested, manual mode water settings do not persist across reboots.
                    self.settings["manual_water_session"] = copy.deepcopy(self.settings.get("water_defaults", defaults["water_defaults"]))
                    
                except Exception as e:
                    print(f"[SettingsManager] Error loading settings: {e}. Reverting to defaults.")
                    self.settings = copy.deepcopy(DEFAULT_SETTINGS)
                    self.settings["manual_water_session"] = copy.deepcopy(self.settings["water_defaults"])
            
            # [Keep the rest of _load_settings]
            self.last_shutdown_was_clean = self.settings.get("system_settings", {}).get("controlled_shutdown", False)
            if "system_settings" not in self.settings: self.settings["system_settings"] = {}
            self.settings["system_settings"]["controlled_shutdown"] = False
            self._save_settings()

    def _load_profiles(self):
        with self._data_lock:
            if "profiles" in self.settings:
                legacy_profiles = self.settings.pop("profiles")
                if legacy_profiles:
                    print("[SettingsManager] Migrating profiles to kettlebrain_profiles.json")
                    self.profiles = legacy_profiles
                    self._save_profiles()
                    self._save_settings() 
                    return
                self._save_settings()

            if not os.path.exists(self.profiles_file):
                print(f"[SettingsManager] No profiles file. Creating default.")
                self.profiles = self._create_default_profile_dict()
                self._save_profiles()
            else:
                try:
                    with open(self.profiles_file, 'r', encoding='utf-8') as f:
                        self.profiles = json.load(f)
                except Exception as e:
                    print(f"[SettingsManager] Error loading profiles: {e}. Reverting.")
                    self.profiles = self._create_default_profile_dict()
                    self._save_profiles()

    def _save_settings(self):
        with self._data_lock:
            try:
                with open(self.settings_file, 'w', encoding='utf-8') as f:
                    json.dump(self.settings, f, indent=4)
            except Exception as e:
                print(f"[SettingsManager] Error saving settings: {e}")

    def _save_profiles(self):
        with self._data_lock:
            try:
                with open(self.profiles_file, 'w', encoding='utf-8') as f:
                    json.dump(self.profiles, f, indent=4)
            except Exception as e:
                print(f"[SettingsManager] Error saving profiles: {e}")

    # --- GETTERS / SETTERS ---

    def get(self, section, key, default=None):
        with self._data_lock:
            return self.settings.get(section, {}).get(key, default)
            
    def get_section(self, section):
        """Returns the entire dictionary for a section."""
        with self._data_lock:
            return self.settings.get(section, {})

    def set(self, section, key, value):
        with self._data_lock:
            if section not in self.settings:
                self.settings[section] = {}
            self.settings[section][key] = value
            self._save_settings()

    def get_system_setting(self, key, default=None):
        return self.get("system_settings", key, default)

    def set_system_setting(self, key, value):
        self.set("system_settings", key, value)
        
    def set_controlled_shutdown(self, is_controlled):
        self.set("system_settings", "controlled_shutdown", is_controlled)

    # --- RECOVERY STATE METHODS ---

    def save_recovery_state(self, state_dict):
        with self._data_lock:
            self.settings["recovery_state"] = state_dict
            self._save_settings()

    def get_recovery_state(self):
        with self._data_lock:
            return self.settings.get("recovery_state")

    def clear_recovery_state(self):
        with self._data_lock:
            self.settings["recovery_state"] = None
            self._save_settings()

    # --- PROFILE MANAGEMENT ---

    def save_profile(self, profile: BrewProfile):
        with self._data_lock:
            self.profiles[profile.id] = profile.to_dict()
            self._save_profiles()
            print(f"[SettingsManager] Saved profile: {profile.name}")

    def delete_profile(self, profile_id: str):
        with self._data_lock:
            if profile_id in self.profiles:
                p_data = self.profiles[profile_id]
                if p_data.get("name") == "Default Profile":
                    print("[SettingsManager] Prevented deletion of Default Profile.")
                    return False
                del self.profiles[profile_id]
                self._save_profiles()
                return True
            return False

    def get_all_profiles(self) -> list[BrewProfile]:
        profiles = []
        with self._data_lock:
            for pid, p_data in self.profiles.items():
                try:
                    profile = BrewProfile(
                        id=p_data.get("id", pid),
                        name=p_data.get("name", "Unknown Profile"),
                        water_data=p_data.get("water_data", {}),
                        chemistry_data=p_data.get("chemistry_data", {})
                    )
                    
                    raw_steps = p_data.get("steps", [])
                    for s_data in raw_steps:
                        try:
                            s_type = StepType(s_data.get("step_type", "Step"))
                        except ValueError:
                            s_type = StepType.STEP
                        
                        try:
                            t_behavior = TimeoutBehavior(s_data.get("timeout_behavior", "Manual Advance"))
                        except ValueError:
                            t_behavior = TimeoutBehavior.MANUAL_ADVANCE

                        # --- BACKWARD COMPATIBILITY LOGIC ---
                        legacy_power = s_data.get("power_watts")
                        ramp_p = s_data.get("ramp_power_watts")
                        hold_p = s_data.get("hold_power_watts")
                        
                        if ramp_p is None: ramp_p = legacy_power
                        if hold_p is None: hold_p = legacy_power

                        step = BrewStep(
                            id=s_data.get("id"),
                            name=s_data.get("name", "Step"),
                            step_type=s_type,
                            note=s_data.get("note", ""),
                            setpoint_f=s_data.get("setpoint_f"),
                            duration_min=s_data.get("duration_min", 0.0),
                            target_completion_time=s_data.get("target_completion_time"),
                            ramp_power_watts=ramp_p, # <--- NEW
                            hold_power_watts=hold_p, # <--- NEW
                            timeout_behavior=t_behavior,
                            sg_reading=s_data.get("sg_reading"),
                            sg_temp_f=s_data.get("sg_temp_f"),
                            sg_temp_correction=s_data.get("sg_temp_correction", False),
                            sg_corrected_value=s_data.get("sg_corrected_value"),
                            lauter_temp_f=s_data.get("lauter_temp_f"),
                            lauter_volume=s_data.get("lauter_volume")
                        )
                        
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
                        
                        profile.add_step(step)
                    profiles.append(profile)
                except Exception as e:
                    print(f"[SettingsManager] Error inflating profile {pid}: {e}")
        
        return profiles

    def get_profile_by_id(self, profile_id: str):
        all_profiles = self.get_all_profiles()
        for p in all_profiles:
            if p.id == profile_id:
                return p
        return None
