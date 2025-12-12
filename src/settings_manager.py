"""
kettlebrain app
settings_manager.py
"""

import json
import os
import threading
from typing import List, Optional, Dict

# UPDATED IMPORTS: Added BrewAddition
from profile_data import BrewProfile, BrewStep, StepType, TimeoutBehavior, BrewAddition

SETTINGS_FILE = "kettlebrain_settings.json"
DATA_DIR_NAME = "kettlebrain-data"

class SettingsManager:
    
    def __init__(self):
        # Determine path (User home directory)
        self.data_dir = os.path.join(os.path.expanduser('~'), DATA_DIR_NAME)
        self.settings_file = os.path.join(self.data_dir, SETTINGS_FILE)
        
        self._data_lock = threading.RLock()
        self.settings = {}
        
        self._ensure_data_dir()
        self._load_settings()

    def _get_default_settings(self):
        """Returns the baseline settings structure."""
        return {
            "system_settings": {
                "units": "F", # or "C"
                "heating_rate_f_min": 1.5, # Degrees per minute (for Delayed Start)
                "relay_logic_configured": False,
                "relay_active_high": False, # Default to Active Low
                "force_numlock": True # <--- NEW: Default to ON
            },
            "pid_settings": {
                "kp": 50.0,
                "ki": 0.1,
                "kd": 2.0,
                "sample_time_s": 2.0
            },
            "recovery_state": None, 
            "profiles": {} 
        }

    def _ensure_data_dir(self):
        try:
            os.makedirs(self.data_dir, exist_ok=True)
        except OSError as e:
            print(f"[SettingsManager] Error creating data dir: {e}")

    def _load_settings(self):
        with self._data_lock:
            if not os.path.exists(self.settings_file):
                print(f"[SettingsManager] No settings found. Creating defaults at {self.settings_file}")
                self.settings = self._get_default_settings()
                self._save_settings()
            else:
                try:
                    with open(self.settings_file, 'r') as f:
                        self.settings = json.load(f)
                    
                    # Merge defaults (in case of software update adding new keys)
                    defaults = self._get_default_settings()
                    for section, data in defaults.items():
                        if section not in self.settings:
                            self.settings[section] = data
                        elif isinstance(data, dict):
                            for key, val in data.items():
                                if key not in self.settings[section]:
                                    self.settings[section][key] = val
                                    
                except Exception as e:
                    print(f"[SettingsManager] Error loading settings: {e}. Reverting to defaults.")
                    self.settings = self._get_default_settings()

    def _save_settings(self):
        """Writes current settings to disk."""
        with self._data_lock:
            try:
                with open(self.settings_file, 'w') as f:
                    json.dump(self.settings, f, indent=4)
            except Exception as e:
                print(f"[SettingsManager] Error saving settings: {e}")

    # --- GENERIC GETTERS / SETTERS ---

    def get(self, section, key, default=None):
        with self._data_lock:
            return self.settings.get(section, {}).get(key, default)

    def set(self, section, key, value):
        with self._data_lock:
            if section not in self.settings:
                self.settings[section] = {}
            self.settings[section][key] = value
            self._save_settings()

    # --- PROFILE MANAGEMENT ---

    def save_profile(self, profile: BrewProfile):
        """
        Serializes a BrewProfile object and saves it to the settings dict.
        """
        with self._data_lock:
            # 1. Convert Object -> Dict (Serialization)
            # We construct a clean dict to ensure JSON compatibility
            profile_data = {
                "id": profile.id,
                "name": profile.name,
                "created_date": profile.created_date,
                "steps": [step.to_dict() for step in profile.steps]
            }
            
            # 2. Store in Settings
            self.settings["profiles"][profile.id] = profile_data
            self._save_settings()
            print(f"[SettingsManager] Saved profile: {profile.name} ({len(profile.steps)} steps)")

    def delete_profile(self, profile_id: str):
        with self._data_lock:
            if profile_id in self.settings["profiles"]:
                del self.settings["profiles"][profile_id]
                self._save_settings()

    def get_all_profiles(self) -> List[BrewProfile]:
        """
        Returns a list of re-hydrated BrewProfile objects.
        """
        profiles = []
        with self._data_lock:
            stored_data = self.settings.get("profiles", {})
            for pid, p_data in stored_data.items():
                try:
                    # Re-hydrate the Profile
                    profile = BrewProfile(
                        id=p_data.get("id", pid),
                        name=p_data.get("name", "Unknown Profile"),
                        created_date=p_data.get("created_date", "")
                    )
                    
                    # Re-hydrate Steps
                    raw_steps = p_data.get("steps", [])
                    for s_data in raw_steps:
                        # Convert string Enums back to Enum objects
                        try:
                            s_type = StepType(s_data.get("step_type", "Step"))
                        except ValueError:
                            s_type = StepType.STEP # Fallback
                            
                        try:
                            t_behavior = TimeoutBehavior(s_data.get("timeout_behavior", "Manual Advance"))
                        except ValueError:
                            t_behavior = TimeoutBehavior.MANUAL_ADVANCE
                            
                        step = BrewStep(
                            id=s_data.get("id"),
                            name=s_data.get("name", "Step"),
                            step_type=s_type,
                            note=s_data.get("note", ""),
                            setpoint_f=s_data.get("setpoint_f"),
                            duration_min=s_data.get("duration_min", 0.0),
                            target_completion_time=s_data.get("target_completion_time"),
                            power_watts=s_data.get("power_watts"),
                            timeout_behavior=t_behavior,
                            
                            # Activity Fields
                            sg_reading=s_data.get("sg_reading"),
                            sg_temp_f=s_data.get("sg_temp_f"),
                            sg_temp_correction=s_data.get("sg_temp_correction", False),
                            sg_corrected_value=s_data.get("sg_corrected_value"),
                            lauter_temp_f=s_data.get("lauter_temp_f"),
                            lauter_volume=s_data.get("lauter_volume")
                        )
                        
                        # --- FIX: RE-HYDRATE ADDITIONS ---
                        raw_additions = s_data.get("additions", [])
                        for add_data in raw_additions:
                            # Basic validation to ensure it's a dict
                            if isinstance(add_data, dict):
                                new_add = BrewAddition(
                                    id=add_data.get("id"),
                                    name=add_data.get("name", "Alert"),
                                    time_point_min=add_data.get("time_point_min", 0),
                                    triggered=False # Always reset triggered state on load
                                )
                                step.additions.append(new_add)
                        # ---------------------------------
                        
                        profile.add_step(step)
                        
                    profiles.append(profile)
                except Exception as e:
                    print(f"[SettingsManager] Error inflating profile {pid}: {e}")
                    import traceback
                    traceback.print_exc()
                    
        return profiles

    def get_profile_by_id(self, profile_id: str) -> Optional[BrewProfile]:
        all_profiles = self.get_all_profiles()
        for p in all_profiles:
            if p.id == profile_id:
                return p
        return None

    # --- RECOVERY STATE ---

    def save_recovery_state(self, state_dict: dict):
        """Called by SequenceManager to save current progress."""
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
