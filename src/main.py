import os
import uuid
import copy
import subprocess
import sys
import threading
import signal
import atexit
import json
from datetime import datetime, timedelta
from sequence_manager import SequenceStatus
from profile_data import BrewProfile, BrewStep, BrewAddition, StepType, TimeoutBehavior
from brew_math import BrewMath

# This tells the OS: "My Window ID is 'KettleBrain', not 'python'"
os.environ['SDL_VIDEO_X11_WMCLASS'] = "KettleBrain"
os.environ['KIVY_BCM_DISPMANX_ID'] = '2'

# 1. Import Config first
from kivy.config import Config

# 2. Calculate the path immediately
current_dir = os.path.dirname(os.path.abspath(__file__))
icon_path = os.path.join(current_dir, 'assets', 'kettle.png')

# 3. Set the icon in Kivy's global configuration
Config.set('kivy', 'window_icon', icon_path)
Config.set('input', 'mouse', 'mouse,multitouch_on_demand') 

# --- Rest of CONFIG ---
Config.set('graphics', 'width', '800')
Config.set('graphics', 'height', '418')
Config.set('graphics', 'resizable', '0')
Config.set('graphics', 'position', 'custom')
Config.set('graphics', 'top', '50')
Config.set('graphics', 'left', '0')

import kivy
from kivy.app import App
from kivy.uix.screenmanager import Screen, ScreenManager
from kivy.clock import Clock
from kivy.properties import StringProperty, ListProperty, NumericProperty, ObjectProperty, BooleanProperty
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.popup import Popup
from kivy.uix.textinput import TextInput
from kivy.lang import Builder
from kivy.metrics import dp
from kivy.uix.slider import Slider
from kivy.uix.label import Label
from kivy.uix.button import Button
from kivy.uix.scrollview import ScrollView
from kivy.uix.gridlayout import GridLayout
from kivy.uix.screenmanager import SlideTransition
from kivy.uix.spinner import Spinner
from kivy.core.window import Window

# --- BACKEND IMPORTS ---
from settings_manager import SettingsManager 
from hardware_interface import HardwareInterface
from sequence_manager import SequenceManager, SequenceStatus

# --- FAILSAFE SHUTDOWN ---
def failsafe_cleanup():
    """
    Nuclear option: Forces all Relays OFF when python exits.
    This runs on app crash, CTRL+C, or normal close.
    """
    try:
        print("[Main] Executing Failsafe Cleanup...")
        # Attempt to find the relay instance in the running app
        app = App.get_running_app()
        if app and hasattr(app, 'relay'):
            app.relay.stop_all()
            print("[Main] Relays disabled via App reference.")
        else:
            # Fallback: Create a temporary RelayControl to force shutdown
            from relay_control import RelayControl
            from settings_manager import SettingsManager
            
            # 1. Determine Path (Match logic in build() to avoid creating wrong data folder)
            script_path = os.path.abspath(sys.argv[0])
            src_dir = os.path.dirname(script_path)
            
            # Default to current dir
            root_dir = src_dir
            
            # If running from src, go up TWO levels to find the true root 
            # (parent of kettlebrain, so data ends up in ../kettlebrain-data)
            if os.path.basename(src_dir) == 'src':
                project_dir = os.path.dirname(src_dir) # e.g. /home/pi/kettlebrain
                root_dir = os.path.dirname(project_dir) # e.g. /home/pi
            
            sm = SettingsManager(root_dir)
            rc = RelayControl(sm)
            rc.stop_all()
            print("[Main] Relays disabled via Fresh Instance.")
            
    except Exception as e:
        print(f"[Main] Failsafe Error: {e}")

def handle_signal(signum, frame):
    """
    Catches OS signals (like closing the terminal or kill command).
    """
    print(f"\n[Main] Caught Signal {signum}. Shutting down safely...")
    failsafe_cleanup()
    # Force exit. sys.exit(0) triggers atexit, ensuring we don't miss anything,
    # but since we just ran cleanup, it's safe even if it runs twice (relays just stay off).
    sys.exit(0)

# 1. Register Normal Exit
atexit.register(failsafe_cleanup)

# 2. Register Signal Handlers (Terminal Close, Kill Command)
signal.signal(signal.SIGTERM, handle_signal) # Kill command
signal.signal(signal.SIGHUP, handle_signal)  # Terminal closed
# Note: SIGINT (Ctrl+C) is usually handled by Python as KeyboardInterrupt, 
# which triggers atexit automatically, so we don't strictly need it here, but it doesn't hurt.
signal.signal(signal.SIGINT, handle_signal)



# --- 1. UPDATE WIDGET CLASS ---
class StepItem(BoxLayout):
    step_index = StringProperty("")
    step_name = StringProperty("")
    step_target = StringProperty("")
    step_duration = StringProperty("")
    step_ready = StringProperty("")  # <--- NEW PROPERTY
    bg_color = ListProperty([0.2, 0.2, 0.2, 1])
    text_color = ListProperty([1, 1, 1, 1])

class ProfileOptionsPopup(Popup):
    profile_name = StringProperty("")
    profile_id = StringProperty("")

    def do_load(self):
        app = App.get_running_app()
        app.load_profile(self.profile_id)
        self.dismiss()

    def do_copy(self):
        app = App.get_running_app()
        app.copy_profile(self.profile_id)
        self.dismiss()

    def do_delete(self):
        app = App.get_running_app()
        app.delete_profile(self.profile_id)
        self.dismiss()

    def do_edit(self):
        app = App.get_running_app()
        app.launch_profile_editor(self.profile_id)
        self.dismiss()


# SHOULD BE ABLE TO DELETE THIS CLASS
# --- HELPER: Single Row for an Alert ---
# ~ class AlertRow(BoxLayout):
    # ~ def __init__(self, addition_obj, remove_callback, **kwargs):
        # ~ super().__init__(**kwargs)
        # ~ self.addition = addition_obj
        # ~ self.orientation = 'horizontal'
        # ~ self.size_hint_y = None
        # ~ self.height = dp(40)
        # ~ self.spacing = dp(5)

        # ~ # Name Input
        # ~ self.txt_name = TextInput(text=addition_obj.name, multiline=False, size_hint_x=0.6)
        # ~ self.txt_name.bind(text=self.on_name_change)
        # ~ self.add_widget(self.txt_name)

        # ~ # Time Input
        # ~ self.txt_time = TextInput(text=str(addition_obj.time_point_min), multiline=False, size_hint_x=0.25, input_filter='float')
        # ~ self.txt_time.bind(text=self.on_time_change)
        # ~ self.add_widget(self.txt_time)
        
        # ~ self.add_widget(Label(text="m", size_hint_x=None, width=dp(20)))

        # ~ # Remove Button
        # ~ btn_remove = Button(text="X", size_hint_x=None, width=dp(40), background_color=(1, 0, 0, 1))
        # ~ btn_remove.bind(on_release=lambda x: remove_callback(self))
        # ~ self.add_widget(btn_remove)

    # ~ def on_name_change(self, instance, value):
        # ~ self.addition.name = value

    # ~ def on_time_change(self, instance, value):
        # ~ if value:
            # ~ try: self.addition.time_point_min = float(value)
            # ~ except: pass

class AlertChildItem(BoxLayout):
    """
    Visual row for the 'Child' addition/alert.
    """
    alert_name = StringProperty("")
    bg_color = ListProperty([0.15, 0.15, 0.15, 1])
    text_color = ListProperty([0.8, 0.8, 0.8, 1])

# --- 1. Define the Alert Row Item ---
class AlertItem(BoxLayout):
    """
    Data container for the RecycleView row.
    Logic and Layout are handled in kettle.kv.
    """
    name = StringProperty("")
    time = NumericProperty(0)
    index = NumericProperty(0) # Ensure this property exists for the buttons to use

# --- 2. Define the Full Screen Editor ---
# In main.py, find class StepEditorScreen(Screen) and update it:

# In main.py

class StepEditorScreen(Screen):
    # --- CORE DATA ---
    step_index = NumericProperty(-1)
    step_name = StringProperty("New Step")
    
    # --- SPINNERS ---
    step_type_options = ListProperty([s.value for s in StepType]) 
    selected_type = StringProperty("Step")
    
    # Exclude 'End Program' from options if desired
    advance_options = ListProperty([TimeoutBehavior.AUTO_ADVANCE.value, TimeoutBehavior.MANUAL_ADVANCE.value])
    selected_advance = StringProperty(TimeoutBehavior.AUTO_ADVANCE.value)

    # --- SLIDERS ---
    step_temp = NumericProperty(150.0)
    step_dur = NumericProperty(60.0)
    step_vol = NumericProperty(0.0)
    step_vol_display = StringProperty("Volume: --")
    
    # Power (Discrete Map)
    # UPDATED: Default index 4 (1800W) and added 0 to map
    step_power_idx = NumericProperty(4)
    watts_map = ListProperty([0, 800, 1000, 1400, 1800])
    display_power = StringProperty("1800W")
    
    # Label Display Property
    step_target_display = StringProperty("Target: 150 F") 

    # --- STATE TRACKING (DIRTY CHECK) ---
    is_temp_locked = BooleanProperty(False)
    current_additions = ListProperty([])
    step_obj_ref = None
    
    is_dirty = BooleanProperty(False)
    original_state = {}

    def on_step_power_idx(self, instance, value):
        idx = int(value)
        if 0 <= idx < len(self.watts_map):
            self.display_power = f"{self.watts_map[idx]}W"
        self._check_dirty()

    def on_step_temp(self, instance, value):
        self._update_target_display()
        self._check_dirty()

    def on_step_name(self, instance, value): self._check_dirty()
    def on_step_dur(self, instance, value): self._check_dirty()
    
    def on_step_vol(self, instance, value):
        self._check_dirty()

        # FIX: Update label dynamically
        app = App.get_running_app()
        if not app: return
        u_vol = "L" if app.is_metric else "Gal"
        self.step_vol_display = f"Volume: {value:.2f} {u_vol}"
    
    def on_selected_type(self, instance, value): 
        self._handle_type_change(value)
        self._check_dirty()
    def on_selected_advance(self, instance, value): self._check_dirty()
    def on_current_additions(self, instance, value): self._check_dirty()

    # In src/main.py inside class StepEditorScreen(Screen):

    def _update_target_display(self):
        """Formats the label to show (BOIL) or --."""
        app = App.get_running_app()
        if not app: return
        
        # self.step_temp is in User Units (C or F)
        val = float(self.step_temp)
        
        # --- NULL CHECK (Step 1) ---
        # If value is at (or below) the "Null" threshold
        # Imperial: < 70 (i.e. 69), Metric: < 20 (i.e. 19)
        threshold = 20 if app.is_metric else 70
        
        if val < threshold: 
            self.step_target_display = "Target: --"
            return
            
        # --- UNIT CONVERSION LOGIC ---
        # 1. Convert User Value (C) back to F to compare against System Boil (stored in F)
        val_f = app.to_backend_units(val, 'temp')
        sys_boil_f = app.settings_manager.get_system_setting("boil_temp_f", 212.0)
        
        unit = "C" if app.is_metric else "F"
        
        # Compare F to F
        if val_f >= (sys_boil_f - 1.0): # Small buffer for rounding
            self.step_target_display = f"Target: {int(val)} {unit} (BOIL)"
        else:
            self.step_target_display = f"Target: {int(val)} {unit}"

    def _handle_type_change(self, value):
        app = App.get_running_app()
        if not app: return

        # 1. PREVENT OVERWRITE ON LOAD
        # If the selected type matches the saved object's type, we are likely 
        # just loading the step. Do not overwrite saved data with defaults.
        if self.step_obj_ref and hasattr(self.step_obj_ref, 'step_type'):
            if value == self.step_obj_ref.step_type.value:
                # Still check locking logic for the loaded type
                if value == "Boil": 
                    # Boil steps are now editable
                    pass
                return

        # 2. DEFINE DEFAULTS (Imperial Units)
        # Structure: Target(F), Time(m), Vol(Gal), Power(W), Advance, Additions
        sys_boil = app.settings_manager.get_system_setting("boil_temp_f", 212.0)
        
        STEP_DEFAULTS = {
            "Step": {
                "temp": 70.0, "time": 0.0, "vol": 8.0, "watts": 1800, 
                "adv": TimeoutBehavior.AUTO_ADVANCE.value,
                "adds": []
            },
            "Prep Water": {
                "temp": 0.0, "time": 0.0, "vol": 8.0, "watts": 0, 
                "adv": TimeoutBehavior.AUTO_ADVANCE.value,
                "adds": [
                    {'name': "Add water per calculations", 'time': 0},
                    {'name': "Add water salts per calculations", 'time': 0}
                ]
            },
            "Dough-in": {
                "temp": 156.0, "time": 0.0, "vol": 8.0, "watts": 1800, 
                "adv": TimeoutBehavior.AUTO_ADVANCE.value,
                "adds": [
                    {'name': "Drop grain basket", 'time': 0},
                    {'name': "Drop full grain bill", 'time': 0},
                    {'name': "Mix well, no dough balls", 'time': 0},
                    {'name': "Cover & turn on pump", 'time': 0}
                ]
            },
            "Mash": {
                "temp": 150.0, "time": 60.0, "vol": 8.75, "watts": 1800, 
                "adv": TimeoutBehavior.AUTO_ADVANCE.value,
                "adds": [
                    {'name': "Mix grains", 'time': 45},
                    {'name': "Mix grains", 'time': 30},
                    {'name': "Mix grains", 'time': 15},
                    {'name': "Mix grains", 'time': 0},
                    {'name': "Turn off pump", 'time': 0},
                    {'name': "Record SG", 'time': 0}
                ]
            },
            "Mash-out": {
                "temp": 170.0, "time": 10.0, "vol": 8.75, "watts": 1800, 
                "adv": TimeoutBehavior.AUTO_ADVANCE.value,
                "adds": [
                    {'name': "Remove cover", 'time': 10},
                    {'name': "Lift & drain grains", 'time': 0},
                    {'name': "Add make-up water if necessary", 'time': 0}
                ]
            },
            "Sparge": {
                "temp": 200.0, "time": 0.0, "vol": 4.25, "watts": 1800, 
                "adv": TimeoutBehavior.AUTO_ADVANCE.value,
                "adds": [
                    {'name': "Remove grain basket", 'time': 0}
                ]
            },
            "Boil Start": {
                "temp": sys_boil, "time": 0.0, "vol": 6.75, "watts": 1800, 
                "adv": TimeoutBehavior.MANUAL_ADVANCE.value,
                "adds": []
            },
            "Boil Off": {
                "temp": sys_boil, "time": 60.0, "vol": 6.75, "watts": 1800, 
                "adv": TimeoutBehavior.AUTO_ADVANCE.value,
                "adds": [
                    {'name': "Bittering hops", 'time': 60},
                    {'name': "Flavor hops", 'time': 30},
                    {'name': "Irish moss", 'time': 10},
                    {'name': "Sanitize chiller", 'time': 9},
                    {'name': "Aroma hops", 'time': 5},
                    {'name': "Flameout hops", 'time': 0}
                ]
            },
            "Chill": {
                "temp": 70.0, "time": 15.0, "vol": 5.75, "watts": 0, 
                "adv": TimeoutBehavior.AUTO_ADVANCE.value,
                "adds": [
                    {'name': "Drop chiller", 'time': 15},
                    {'name': "Record OG", 'time': 0}
                ]
            }
        }

        # 3. APPLY DEFAULTS
        if value in STEP_DEFAULTS:
            data = STEP_DEFAULTS[value]
            
            # Apply Name
            self.step_name = value
            
            # Apply Temp (Convert Imperial -> User Unit)
            self.step_temp = app.to_user_units(data["temp"], 'temp')
            self.is_temp_locked = False # Always unlock
            
            # Apply Time
            self.step_dur = float(data["time"])
            
            # Apply Volume (Convert Imperial -> User Unit)
            # Reconfigure slider first to ensure range validity
            app.configure_slider(self.ids.s_vol, data["vol"], 'vol')
            self.step_vol = app.to_user_units(data["vol"], 'vol')
            
            # Apply Power (Map Watts -> Index)
            w = data["watts"]
            if w in self.watts_map:
                self.step_power_idx = self.watts_map.index(w)
            else:
                self.step_power_idx = 0 # Default to 0 if unknown
                
            # Apply Advance
            self.selected_advance = data["adv"]
            
            # Apply Additions
            # Sort by time desc (Standard for UI)
            sorted_adds = sorted(data["adds"], key=lambda x: x['time'], reverse=True)
            self.current_additions = sorted_adds
            
            # Trigger Updates
            self._update_target_display()
            self._check_dirty()

    def _get_current_state(self):
        """Returns a snapshot dictionary of the current UI values."""
        # Normalize additions for accurate comparison
        adds = [{'name': x['name'], 'time': float(x['time'])} for x in self.current_additions]
        adds.sort(key=lambda x: (x['time'], x['name']))
        
        return {
            'name': self.step_name,
            'type': self.selected_type,
            'advance': self.selected_advance,
            'temp': float(self.step_temp),
            'dur': float(self.step_dur),
            'vol': float(self.step_vol),
            'power': int(self.step_power_idx),
            'additions': adds
        }

    def _check_dirty(self):
        """Compares current UI to the original loaded state."""
        if not self.original_state: return
        current = self._get_current_state()
        self.is_dirty = (current != self.original_state)

    def load_step(self, step_obj, index):
        """Populates the UI and takes a 'clean' snapshot."""
        self.step_obj_ref = step_obj
        self.step_index = index
        self.step_name = step_obj.name 
        
        app = App.get_running_app()

        try: self.selected_type = step_obj.step_type.value
        except: self.selected_type = "Step"
        
        try: self.selected_advance = step_obj.timeout_behavior.value
        except: self.selected_advance = TimeoutBehavior.AUTO_ADVANCE.value

        # --- UNIT CONVERSION START ---
        # 1. Temp: Read Imperial -> Configure Slider -> Set User Value
        raw_temp_f = float(step_obj.setpoint_f or 0.0)
        
        # Configure Slider (Handles Null mapping to 69/19 internally now)
        app.configure_slider(self.ids.s_temp, raw_temp_f, 'temp')
        
        # Read the value back from the slider to ensure self.step_temp matches UI
        self.step_temp = self.ids.s_temp.value

        # 2. Volume
        raw_vol_gal = float(step_obj.lauter_volume or 0.0)
        if raw_vol_gal < 1.0: raw_vol_gal = 6.0
        app.configure_slider(self.ids.s_vol, raw_vol_gal, 'vol')
        # -----------------------------
        
        # HANDLE LOCKING: All steps are editable now.
        self.is_temp_locked = False
            
        self.step_dur = float(step_obj.duration_min or 0.0)
        
        w = getattr(step_obj, 'power_watts', 1800)
        self.step_power_idx = self.watts_map.index(w) if w in self.watts_map else 4

        # Load Alerts
        temp_list = []
        if hasattr(step_obj, 'additions'):
            for a in step_obj.additions:
                n = a.get('name', 'Alert') if isinstance(a, dict) else getattr(a, 'name', 'Alert')
                t = a.get('time_point_min', 0) if isinstance(a, dict) else getattr(a, 'time_point_min', 0)
                temp_list.append({'name': n, 'time': float(t)})
        
        temp_list.sort(key=lambda x: x['time'], reverse=True)
        self.current_additions = temp_list
        
        self._update_target_display()
        
        # TAKE SNAPSHOT
        self.original_state = self._get_current_state()
        self.is_dirty = False

    def open_alerts_screen(self):
        self.manager.transition.direction = 'left'
        self.manager.current = 'step_alerts'
        self.manager.get_screen('step_alerts').load_data(self.step_name, self.current_additions)

    def save_step(self):
        """Commits changes to memory (the object) and exits."""
        app = App.get_running_app()
        
        if self.step_obj_ref:
            self.step_obj_ref.name = self.step_name
            
            # --- UNIT CONVERSION START ---
            # Threshold check: < 70 (Imp) or < 20 (Met) means OFF (0.0)
            threshold = 20 if app.is_metric else 70
            
            if self.step_temp < threshold:
                self.step_obj_ref.setpoint_f = 0.0
            else:
                val_f = app.to_backend_units(self.step_temp, 'temp')
                self.step_obj_ref.setpoint_f = val_f
            
            val_gal = app.to_backend_units(self.step_vol, 'vol')
            self.step_obj_ref.lauter_volume = val_gal 
            # -----------------------------
            
            self.step_obj_ref.duration_min = self.step_dur
            
            try: self.step_obj_ref.step_type = StepType(self.selected_type)
            except: pass 
            try: self.step_obj_ref.timeout_behavior = TimeoutBehavior(self.selected_advance)
            except: pass

            idx = int(self.step_power_idx)
            if 0 <= idx < len(self.watts_map):
                self.step_obj_ref.power_watts = self.watts_map[idx]
            
            new_list = []
            for item in self.current_additions:
                new_list.append(BrewAddition(name=item['name'], time_point_min=item['time']))
            self.step_obj_ref.additions = new_list

        # Refresh Main Editor List
        app.root.get_screen('editor').refresh_steps()
        app.root.current = 'editor'

    def cancel(self):
        """Exits without saving (Discard Changes)."""
        # Since we haven't touched step_obj_ref yet, simply leaving discards the changes.
        App.get_running_app().root.current = 'editor'


class StepAlertsScreen(Screen):
    step_name = StringProperty("")
    new_alert_name = StringProperty("Hops")
    new_alert_time = NumericProperty(10.0)
    
    # Edit Logic
    editing_index = NumericProperty(-1)
    btn_text = StringProperty("ADD ALERT")
    
    local_additions = ListProperty([])
    
    # --- DIRTY STATE TRACKING ---
    is_dirty = BooleanProperty(False)
    original_additions = [] # Snapshot list

    def load_data(self, step_name, additions_list):
        self.step_name = step_name
        
        # FIX: Convert Kivy's "ObservableList" to a standard "list" before deepcopying
        # This prevents the "TypeError: no default __reduce__" crash.
        plain_list = list(additions_list)
        
        # Copy list for editing
        self.local_additions = copy.deepcopy(plain_list) 
        
        # Take Snapshot for dirty check
        self.original_additions = copy.deepcopy(plain_list)
        
        self.is_dirty = False
        self._reset_inputs()

    def _reset_inputs(self):
        self.new_alert_name = "Hops"
        self.new_alert_time = 10.0
        self.editing_index = -1
        self.btn_text = "ADD ALERT"

    def _check_dirty(self):
        # Compare lists. We sort first to ensure order doesn't trigger false dirty if logic elsewhere changes it.
        # (Though list order usually matters for display, simple equality check is good enough here)
        current = [{'name': x['name'], 'time': float(x['time'])} for x in self.local_additions]
        orig = [{'name': x['name'], 'time': float(x['time'])} for x in self.original_additions]
        
        # Sort by time to ensure consistent comparison
        current.sort(key=lambda x: (x['time'], x['name']))
        orig.sort(key=lambda x: (x['time'], x['name']))
        
        self.is_dirty = (current != orig)

    def load_for_edit(self, index):
        """Called when user clicks EDIT on a row."""
        if 0 <= index < len(self.local_additions):
            item = self.local_additions[index]
            self.new_alert_name = item['name']
            self.new_alert_time = float(item['time'])
            self.editing_index = index
            self.btn_text = "UPDATE ALERT"

    def add_or_update(self):
        if not self.new_alert_name: return
        
        data = {'name': self.new_alert_name, 'time': self.new_alert_time}
        new_list = list(self.local_additions)
        
        if self.editing_index >= 0:
            # Update Existing
            new_list[self.editing_index] = data
        else:
            # Add New
            new_list.append(data)
            
        new_list.sort(key=lambda x: x['time'], reverse=True)
        self.local_additions = new_list
        self._reset_inputs()
        self._check_dirty()

    def remove_alert_by_index(self, index):
        if 0 <= index < len(self.local_additions):
            new_list = list(self.local_additions)
            new_list.pop(index)
            self.local_additions = new_list
            self._reset_inputs()
            self._check_dirty()

    def apply_changes(self):
        """Save changes back to parent screen."""
        parent = self.manager.get_screen('step_editor')
        parent.current_additions = self.local_additions
        self.manager.transition.direction = 'right'
        self.manager.current = 'step_editor'

    def discard_changes(self):
        """Exit without saving."""
        # No need to revert parent properties, just leave.
        self.manager.transition.direction = 'right'
        self.manager.current = 'step_editor'

# --- ADD THESE CLASSES TO main.py ---
class EditorStepItem(BoxLayout):
    """Row for the Parent Step in Profile Editor"""
    # Define properties to prevent binding errors
    step_index = NumericProperty(0)
    display_index = StringProperty("")
    step_name = StringProperty("")
    step_desc = StringProperty("")
    arrow_text = StringProperty(">")
    arrow_opacity = NumericProperty(1)
    arrow_disabled = BooleanProperty(False)

class EditorAlertChildItem(BoxLayout):
    """Row for the Child Alert in Profile Editor"""
    text = StringProperty("")


class ProfileEditorScreen(Screen):
    temp_name = StringProperty("")
    editing_profile = ObjectProperty(None)
    expanded_indices = ListProperty([])
    
    # --- NEW: Dirty State Tracking ---
    is_dirty = BooleanProperty(False)
    original_snapshot = ""  # We will store a string representation for easy comparison

    def load_data(self, profile):
        # Deep copy ensures we don't accidentally modify the live profile running in the sequencer
        self.editing_profile = copy.deepcopy(profile)
        self.temp_name = self.editing_profile.name
        self.expanded_indices = []
        
        # Take a snapshot of the "Clean" state
        self.original_snapshot = self._generate_snapshot()
        self.is_dirty = False
        
        self.refresh_steps()

    def on_temp_name(self, instance, value):
        # Update name in object so snapshot matches
        if self.editing_profile:
            self.editing_profile.name = value
        self._check_dirty()

    def _generate_snapshot(self):
        """Generates a string representation of the profile data for comparison."""
        if not self.editing_profile: return ""
        
        # Build a simple dict structure of all data that matters
        data = {
            'name': self.editing_profile.name,
            'steps': []
        }
        
        for s in self.editing_profile.steps:
            # Normalize additions
            adds = sorted([{'n': a.name, 't': float(a.time_point_min)} for a in s.additions], key=lambda x: x['t'])
            
            step_data = {
                'n': s.name,
                'type': getattr(s.step_type, 'value', 'Step'),
                'temp': float(s.setpoint_f or 0),
                'dur': float(s.duration_min or 0),
                'vol': float(s.lauter_volume or 0),
                'pwr': getattr(s, 'power_watts', 1800),
                'adds': adds
            }
            data['steps'].append(step_data)
            
        import json
        # Return sorted JSON string to ensure consistent order
        return json.dumps(data, sort_keys=True)

    def _check_dirty(self):
        current = self._generate_snapshot()
        self.is_dirty = (current != self.original_snapshot)

    def toggle_step_expansion(self, step_index):
        if step_index in self.expanded_indices:
            self.expanded_indices.remove(step_index)
        else:
            self.expanded_indices.append(step_index)
        self.refresh_steps()

    def refresh_steps(self):
        # 1. Update Dirty Status first
        self._check_dirty()
        
        app = App.get_running_app()
        unit = "C" if app.is_metric else "F"

        data = []
        if self.editing_profile:
            for i, step in enumerate(self.editing_profile.steps):
                
                # --- UNIT CONVERSION LOGIC ---
                if hasattr(step, 'step_type') and step.step_type == StepType.BOIL:
                    type_str = "BOIL"
                else:
                    raw_f = step.setpoint_f if step.setpoint_f else 0.0
                    if raw_f < 60:
                         type_str = "--"
                    else:
                         user_val = app.to_user_units(raw_f, 'temp')
                         type_str = f"{int(user_val)}°{unit}"
                # -----------------------------

                d_str = f"{int(step.duration_min)}m" if step.duration_min else "0m"
                desc = f"{type_str} / {d_str}"
                
                alerts_count = len(step.additions) if hasattr(step, 'additions') else 0
                has_children = (alerts_count > 0)
                
                arrow_icon = "v" if i in self.expanded_indices else ">"
                
                # Add PARENT Row
                data.append({
                    'view_type': 'EditorStepItem',
                    'step_index': i,
                    'display_index': str(i + 1),
                    'step_name': step.name,
                    'step_desc': desc,
                    'arrow_text': arrow_icon,
                    'arrow_opacity': 1 if has_children else 0,
                    'arrow_disabled': not has_children
                })

                # Add CHILD Rows
                if i in self.expanded_indices and has_children:
                    sorted_adds = sorted(step.additions, key=lambda x: x.time_point_min, reverse=True)
                    for add in sorted_adds:
                        n = getattr(add, 'name', 'Alert')
                        t = getattr(add, 'time_point_min', 0)
                        
                        data.append({
                            'view_type': 'EditorAlertChildItem',
                            'text': f"{n} (@ {int(t)}m)"
                        })

        self.ids.rv_editor_steps.data = data

    def add_new_step(self):
        new_step = BrewStep(name="New Step", setpoint_f=150, duration_min=60)
        self.editing_profile.steps.append(new_step)
        self.refresh_steps()
        # Auto-open the editor
        new_index = len(self.editing_profile.steps) - 1
        App.get_running_app().open_step_editor(new_index)

    def save_profile(self):
        """Commits the profile to disk."""
        app = App.get_running_app()
        self.editing_profile.name = self.temp_name
        app.settings_manager.save_profile(self.editing_profile)
        app.open_profiles()

    def cancel_edit(self):
        """Exits without saving."""
        App.get_running_app().open_profiles()

class MainScreen(Screen):
    display_temp = StringProperty("--.- °F")
    display_target = StringProperty("--")
    display_status = StringProperty("System Idle")
    display_timer = StringProperty("00:00")
    display_elapsed = StringProperty("00:00")
    display_power_watts = StringProperty("1800")
    display_profile_name = StringProperty("")
    action_button_text = StringProperty("START")
    temp_color = ListProperty([0.2, 0.8, 0.2, 1])
    manual_target_display = StringProperty("Target: -- F")
    manual_vol_display = StringProperty("Volume: --")
    est_end_display = StringProperty("Est. End: --:-- --")
    delay_target_dt = ObjectProperty(None) # Stores the calculated start time
    
    is_profile_loaded = BooleanProperty(False)
    
    # Properties for Mode Switch Logic
    mode_switch_target = StringProperty("") # 'auto' or 'manual'
    mode_confirm_msg = StringProperty("")
    mode_reset_btn_text = StringProperty("")
    
    # --- NEW DELAY PROPERTIES ---
    delay_hour = NumericProperty(6)
    delay_min = NumericProperty(0)
    delay_temp = NumericProperty(154.0)
    delay_vol = NumericProperty(8.0)
    delay_btn_text = StringProperty("DELAY START")
    delay_btn_color = ListProperty([0.2, 0.2, 0.4, 1])
    delay_minutes_total = NumericProperty(360) # Default 6:00 AM (6 * 60)
    delay_target_display = StringProperty("Target: --")
    delay_vol_display = StringProperty("Volume: --")
    
    # Visual properties
    controls_disabled = BooleanProperty(False)
    heater_1_active = BooleanProperty(False) # 1000W
    heater_2_active = BooleanProperty(False) # 800W
    is_delay_active = BooleanProperty(False)
    heartbeat_color = ListProperty([0.2, 0.2, 0.2, 1]) # Grey default
    _heartbeat_anim = None # Track the animation object
    
    expanded_indices = ListProperty([])

    
    action_button_text = StringProperty("START")
    action_button_color = ListProperty([0.2, 0.4, 0.8, 1]) # <--- ADD THIS
    
    # Manual Mode Properties
    slider_temp_val = NumericProperty(150.0)
    slider_vol_val = NumericProperty(6.0)
    slider_time_val = NumericProperty(60.0)
    # UPDATED: Default to index 4
    slider_power_val = NumericProperty(4) # Index 0-4

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.app = App.get_running_app()
        self.last_profile_id = None
        self.last_step_index = -1
        self.last_status = SequenceStatus.IDLE  # <--- NEW TRACKER
        # UPDATED: Added 0 to map
        self.watts_map = [0, 800, 1000, 1400, 1800]
        # Track if we have set defaults for delay this session
        self.has_initialized_delay = False
        
    def on_delay_temp(self, instance, value):
        # 1. Get Units
        u_temp = "C" if self.app.is_metric else "F"
        
        # --- NULL CHECK (New Logic) ---
        threshold = 20 if self.app.is_metric else 70
        
        if value < threshold:
            self.delay_target_display = "Target: --"
            return

        # 2. Check BOIL Threshold
        val_f = self.app.to_backend_units(value, 'temp')
        sys_boil_f = self.app.settings_manager.get_system_setting("boil_temp_f", 212.0)
        
        if val_f >= (sys_boil_f - 1.0):
            self.delay_target_display = f"Target: {int(value)} {u_temp} (BOIL)"
        else:
            self.delay_target_display = f"Target: {int(value)} {u_temp}"

    def on_delay_vol(self, instance, value):
        u_vol = "L" if self.app.is_metric else "Gal"
        self.delay_vol_display = f"Volume: {value:.2f} {u_vol}"
    
    def on_enter(self):
        """Syncs UI with saved settings."""
        self._load_manual_settings()

    def _load_manual_settings(self):
        sm = self.app.settings_manager
        
        # Load Imperial Defaults
        last_temp = sm.get("manual_mode_settings", "last_setpoint_f", 150.0)
        last_vol = sm.get("manual_mode_settings", "last_volume_gal", 6.0)
        
        # FIX: Force an update of the text labels on load
        self.on_slider_drag('temp', self.slider_temp_val)
        self.on_slider_drag('vol', self.slider_vol_val)
    
        # Time/Power don't need unit conversion
        last_timer = sm.get("manual_mode_settings", "last_timer_min", 60.0)
        last_watts = sm.get("manual_mode_settings", "last_power_watts", 1800)

        # Configure Sliders (Sets min/max/step/value)
        self.app.configure_slider(self.ids.temp_slider, last_temp, 'temp')
        self.app.configure_slider(self.ids.vol_slider, last_vol, 'vol')
        
        self.slider_time_val = last_timer
        try:
            self.slider_power_val = self.watts_map.index(last_watts)
        except ValueError:
            # UPDATED: Default to index 4 (1800W)
            self.slider_power_val = 4
        
        self.display_power_watts = str(last_watts)
        self._update_prediction()
        
    def on_slider_drag(self, slider_type, value):
        """Updates VISUALS (labels/prediction) immediately."""

        # Unit Strings
        u_temp = "C" if self.app.is_metric else "F"
        u_vol = "L" if self.app.is_metric else "Gal"

        if slider_type == 'temp': 
            val = float(value)
            self.slider_temp_val = val

            # --- NULL CHECK (New Logic) ---
            threshold = 20 if self.app.is_metric else 70
            
            if val < threshold:
                self.manual_target_display = "Target: --"
            else:
                # Normal Logic
                sys_boil = self.app.settings_manager.get_system_setting("boil_temp_f", 212.0)
                val_f = self.app.to_backend_units(val, 'temp')

                if val_f >= sys_boil:
                    self.manual_target_display = f"Target: {int(val)} {u_temp} (BOIL)"
                else:
                    self.manual_target_display = f"Target: {int(val)} {u_temp}"

        elif slider_type == 'vol': 
            self.slider_vol_val = float(value)
            self.manual_vol_display = f"Volume: {value:.2f} {u_vol}"

        elif slider_type == 'time': 
            self.slider_time_val = float(value)
        elif slider_type == 'power': 
            self.slider_power_val = int(value)
            idx = int(value)
            if 0 <= idx < len(self.watts_map):
                self.display_power_watts = str(self.watts_map[idx])

        self._update_prediction()

    def on_slider_release(self, slider_type, value):
        self.on_slider_drag(slider_type, value) 
        seq = self.app.sequencer
        
        # Convert User Input -> Backend Units
        if slider_type == 'temp':
            # --- NULL CHECK ---
            threshold = 20 if self.app.is_metric else 70
            
            if float(value) < threshold:
                seq.set_manual_target(0.0) # Send OFF
            else:
                val_f = self.app.to_backend_units(float(value), 'temp')
                seq.set_manual_target(val_f)
                
        elif slider_type == 'vol':
            val_gal = self.app.to_backend_units(float(value), 'vol')
            seq.set_manual_volume(val_gal)
        elif slider_type == 'time':
            seq.set_manual_timer_duration(float(value))
        elif slider_type == 'power':
            idx = int(value)
            if 0 <= idx < len(self.watts_map):
                seq.set_manual_power(self.watts_map[idx])
                
        self._update_prediction()

    def _update_prediction(self):
        seq = self.app.sequencer
        if seq.status != SequenceStatus.MANUAL:
            return

        current_temp = seq.current_temp if seq.current_temp else 60.0
        target_temp = self.slider_temp_val
        vol = self.slider_vol_val
        
        p_idx = int(self.slider_power_val)
        watts = self.watts_map[p_idx] if 0 <= p_idx < len(self.watts_map) else 1800

        if target_temp > current_temp:
            if hasattr(seq, 'calculate_ramp_minutes'):
                mins = seq.calculate_ramp_minutes(current_temp, target_temp, vol, watts)
                import time
                from datetime import datetime
                ready_epoch = time.time() + (mins * 60)
                dt = datetime.fromtimestamp(ready_epoch)
                self.display_status = f"Ready At: {dt.strftime('%H:%M')}"
        else:
            self.display_status = "System Idle"

    def _update_est_end(self):
        """
        Calculates estimated completion time by simulating the full profile:
        Sum(Ramp Time + Hold Time) for all remaining steps.
        """
        seq = self.app.sequencer
        status = seq.status

        # 1. Validation: Must be Auto Mode with a profile
        if not seq.current_profile or status == SequenceStatus.MANUAL:
            self.est_end_display = "Est. End: --:-- --"
            return

        # 2. Determine Start Time & Temp
        if status == SequenceStatus.DELAYED_WAIT and self.delay_target_dt:
            start_time = self.delay_target_dt
            # If delayed, assume we start heating from the current temp
            # (or we could assume room temp, but current probe reading is safest)
            sim_temp = seq.current_temp if seq.current_temp else 60.0
        else:
            start_time = datetime.now()
            sim_temp = seq.current_temp if seq.current_temp else 60.0

        total_minutes = 0.0
        
        steps = seq.current_profile.steps
        current_idx = seq.current_step_index
        
        # 3. Determine where to start in the list
        start_list_idx = 0
        if status in [SequenceStatus.RUNNING, SequenceStatus.PAUSED, SequenceStatus.WAITING_FOR_USER]:
            start_list_idx = current_idx if current_idx >= 0 else 0

        # --- Helper for Ramp Math ---
        def get_ramp_min(start_f, end_f, vol_gal, watts):
            if end_f > start_f and hasattr(seq, 'calculate_ramp_minutes'):
                # Use the backend physics engine
                return seq.calculate_ramp_minutes(start_f, end_f, vol_gal, watts)
            return 0.0
        # ----------------------------

        # 4. Loop through Steps
        for i in range(start_list_idx, len(steps)):
            step = steps[i]
            
            # Step Parameters
            target = float(step.setpoint_f or 0.0)
            vol = float(step.lauter_volume or 6.0) # Default to 6 Gal if unspecified
            watts = getattr(step, 'power_watts', 1800)
            dur = float(step.duration_min or 0.0)

            # A. ACTIVE STEP LOGIC
            if i == current_idx and status not in [SequenceStatus.DELAYED_WAIT, SequenceStatus.IDLE]:
                # If we are already holding (temp reached), no ramp needed, just remaining timer.
                if getattr(seq, 'temp_reached', False):
                    if hasattr(seq, 'timer'):
                         total_minutes += (seq.timer.remaining_time / 60.0)
                else:
                    # We are currently ramping.
                    # Add ramp from CURRENT TEMP -> TARGET
                    total_minutes += get_ramp_min(sim_temp, target, vol, watts)
                    # Add full duration (timer hasn't started yet)
                    total_minutes += dur
            
            # B. FUTURE STEP LOGIC
            else:
                # Ramp from PREV STEP TEMP -> THIS TARGET
                total_minutes += get_ramp_min(sim_temp, target, vol, watts)
                total_minutes += dur
            
            # Update simulation temp for the next iteration
            # (Assume we finish this step at the target temp)
            if target >= 60:
                sim_temp = target
        
        # 5. Format Output
        end_dt = start_time + timedelta(minutes=total_minutes)
        self.est_end_display = f"Est. End: {end_dt.strftime('%I:%M %p')}"
       
    def open_water_calculator(self):
        """Called by the WATER button."""
        app = App.get_running_app()
        seq = app.sequencer
        
        # Logic: If Auto Mode and No Profile, do nothing (Button should be disabled visually, but safe check here)
        if seq.status != SequenceStatus.MANUAL and not seq.current_profile:
            return

        self.manager.current = 'water_calc'

    def switch_to_manual(self):
        """
        Request to switch to Manual Mode. 
        If Auto is currently running/paused, ask for confirmation.
        """
        seq = self.app.sequencer
        
        # --- NEW SAFETY CHECK ---
        # If temp is 0.0 or None, it likely means Unassigned or Error
        # But allow bypass if user is just navigating, unless they try to START heaters.
        # Ideally, we block entry entirely or block the START button.
        # Per request, we intercept the navigation here.
        current_temp = seq.current_temp if seq.current_temp is not None else 0.0
        if current_temp == 0.0:
             self.ids.bottom_nav.transition.direction = 'up'
             self.ids.bottom_nav.current = 'nav_temp_warning'
             return
        # ------------------------

        # NEW: If Delay is Active, just show the screen.
        # Do NOT change mode, do NOT call enter_manual_mode().
        if seq.status == SequenceStatus.DELAYED_WAIT:
             self.ids.center_content.current = 'page_manual'
             return

        # 1. Check if AUTO is Active (Running, Paused, or Waiting)
        if seq.status in [SequenceStatus.RUNNING, SequenceStatus.PAUSED, SequenceStatus.WAITING_FOR_USER]:
            self._prompt_mode_switch('manual', active_mode="AUTO", inactive_mode="MANUAL")
            return

        # 2. Normal Switch
        self.ids.center_content.current = 'page_manual'
        # Only reset/enter if we aren't already there (avoids resetting a running Manual session)
        if seq.status != SequenceStatus.MANUAL:
            seq.enter_manual_mode()

    def switch_to_auto(self):
        """
        Request to switch to Auto Mode.
        If Manual is currently running (Timer/PID active), ask for confirmation.
        """
        seq = self.app.sequencer
        
        # --- NEW SAFETY CHECK ---
        current_temp = seq.current_temp if seq.current_temp is not None else 0.0
        if current_temp == 0.0:
             self.ids.bottom_nav.transition.direction = 'up'
             self.ids.bottom_nav.current = 'nav_temp_warning'
             return
        # ------------------------
        
        # NEW: If Delay is Active, just show the screen.
        if seq.status == SequenceStatus.DELAYED_WAIT:
             self.ids.center_content.current = 'page_auto'
             return
        
        # 1. Check if MANUAL is Active (Heater or Timer running)
        if seq.status == SequenceStatus.MANUAL and getattr(seq, 'is_manual_running', False):
            self._prompt_mode_switch('auto', active_mode="MANUAL", inactive_mode="AUTO")
            return

        # 2. Normal Switch
        self.ids.center_content.current = 'page_auto'
        # Only Stop if we are coming from Manual (avoids resetting a running Auto session)
        if seq.status == SequenceStatus.MANUAL:
            seq.stop()
    
    def _prompt_mode_switch(self, target, active_mode, inactive_mode):
        """Slides up the confirmation panel."""
        self.mode_switch_target = target
        self.mode_confirm_msg = f"{active_mode} is active. RESET {active_mode} SESSION and switch to {inactive_mode} or CANCEL to return."
        self.mode_reset_btn_text = f"RESET {active_mode} SESSION"
        
        self.ids.bottom_nav.transition.direction = 'up'
        self.ids.bottom_nav.current = 'nav_mode_confirm'

    def prompt_profile_load(self):
        """
        Redirects user to Dashboard and slides up the Warning.
        """
        # 1. Force navigation to Dashboard so they see the running state
        self.manager.current = 'main'
        
        # 2. Configure the shared Confirmation Slider
        self.mode_switch_target = 'profile_load'
        self.mode_reset_btn_text = "RESET SESSION & LOAD PROFILE"
        
        # 3. Slide it up
        self.ids.bottom_nav.transition.direction = 'up'
        self.ids.bottom_nav.current = 'nav_mode_confirm'

    # UPDATE this existing method
    def confirm_mode_switch(self):
        """Executed when user clicks the Red Action Button."""
        
        # 1. Handle Profile Load (NEW)
        if self.mode_switch_target == 'profile_load':
            self.app.finish_pending_load()
            
        # 2. Handle Manual Switch (Existing)
        elif self.mode_switch_target == 'manual':
            self.app.sequencer.stop() # Hard Stop
            self.ids.center_content.current = 'page_manual'
            self.app.sequencer.enter_manual_mode()
            
        # 3. Handle Auto Switch (Existing)
        elif self.mode_switch_target == 'auto':
            self.app.sequencer.stop() # Hard Stop
            self.ids.center_content.current = 'page_auto'
            
        # 4. Restore Bottom Nav
        self.ids.bottom_nav.transition.direction = 'down'
        self.ids.bottom_nav.current = 'nav_standard'

    def cancel_mode_switch(self):
        """Executed when user clicks CANCEL."""
        self.ids.bottom_nav.transition.direction = 'down'
        self.ids.bottom_nav.current = 'nav_standard'
    
    def open_hardware_setup(self):
        """
        Called by 'ASSIGN TEMP PROBE' button in the warning slider.
        Navigates to the Hardware Settings screen.
        """
        # 1. Close the warning slider immediately
        self.ids.bottom_nav.transition.direction = 'down'
        self.ids.bottom_nav.current = 'nav_standard'
        
        # 2. Navigate to Hardware Settings
        self.manager.current = 'settings_hw'

    def cancel_temp_warning(self):
        """
        Called by 'CANCEL' button in the warning slider.
        """
        self.ids.bottom_nav.transition.direction = 'down'
        self.ids.bottom_nav.current = 'nav_standard'
    
    def on_action_click(self):
        seq = self.app.sequencer
        status = seq.status
        current_screen = self.ids.center_content.current

        # --- MANUAL MODE LOGIC ---
        if current_screen == 'page_manual' or status == SequenceStatus.MANUAL:
            
            # --- SAFETY SYNC: Ensure Backend matches Visual Sliders ---
            # 1. Sync Power
            p_idx = int(self.slider_power_val)
            if 0 <= p_idx < len(self.watts_map):
                seq.set_manual_power(self.watts_map[p_idx])
                
            # 2. Sync Temp
            val_f = self.app.to_backend_units(self.slider_temp_val, 'temp')
            seq.set_manual_target(val_f)
            
            # 3. Sync Timer
            seq.set_manual_timer_duration(self.slider_time_val)
            # ---------------------------------------------------------

            if status != SequenceStatus.MANUAL:
                seq.enter_manual_mode()
                seq.start_manual()
            elif getattr(seq, 'is_manual_running', False):
                seq.pause_manual()
            else:
                seq.start_manual()
        
        # --- AUTO MODE LOGIC ---
        elif status == SequenceStatus.IDLE:
            if current_screen == 'page_auto': 
                seq.start_sequence()
        elif status in [SequenceStatus.RUNNING]:
            if hasattr(seq, 'pause_sequence'): seq.pause_sequence()
        elif status == SequenceStatus.PAUSED:
            if hasattr(seq, 'resume_sequence'): seq.resume_sequence()
        elif status == SequenceStatus.WAITING_FOR_USER:
            if seq.current_alert_text == "Step Complete": 
                if hasattr(seq, 'advance_step'): seq.advance_step()
            else: 
                if hasattr(seq, 'resume_sequence'): seq.resume_sequence()

    def on_stop_request(self):
        self.app.sequencer.emergency_cut_power()
        self.ids.bottom_nav.transition.direction = 'up'
        self.ids.bottom_nav.current = 'nav_confirm'

    # In src/main.py

    def on_confirm_reset(self):
        """
        Resets the system but keeps the user on their current mode (Manual or Auto).
        """
        # 1. Check which view is currently active
        was_manual = (self.ids.center_content.current == 'page_manual')

        # 2. Perform the Reset
        if was_manual:
            # If we were in Manual, this Resets the sequencer AND sets status back to MANUAL
            self.app.sequencer.enter_manual_mode()
        else:
            # If we were in Auto, calling stop() would unload the profile.
            # reset_profile() stops the relays and rewinds to Step 1, but keeps the profile loaded.
            self.app.sequencer.reset_profile()

        # 3. Restore Bottom Navigation
        self.ids.bottom_nav.transition.direction = 'down'
        self.ids.bottom_nav.current = 'nav_standard'

    def on_confirm_resume(self):
        """
        Called by the RESUME SESSION button in the Stop/Confirm menu.
        Restarts the Sequence or Manual Mode and restores the UI.
        """
        seq = self.app.sequencer
        
        # 1. Resume based on Status
        if seq.status == SequenceStatus.PAUSED:
            # Auto Mode was running -> Resume
            if hasattr(seq, 'resume_sequence'): 
                seq.resume_sequence()
                
        elif seq.status == SequenceStatus.MANUAL:
            # Manual Mode was active -> Restart Heater/Timer
            # (emergency_cut_power turns is_manual_running=False, so we must start it again)
            seq.start_manual()

        # 2. Restore Bottom Navigation
        self.ids.bottom_nav.transition.direction = 'down'
        self.ids.bottom_nav.current = 'nav_standard'
    
    def on_stop_click(self):
        # Legacy catch-all, redirects to new logic
        self.on_stop_request()

    def on_recover_pause(self):
        self.ids.bottom_nav.transition.direction = 'down'
        self.ids.bottom_nav.current = 'nav_standard'

    def open_profiles(self):
        self.manager.current = 'profiles'
        self.manager.get_screen('profiles').refresh_list()

    def open_settings(self):
        self.manager.current = 'sys_settings'

    def get_delay_time_str(self, total_minutes):
        """Formats 0-1440 minutes into HH:MM AM/PM string for the label."""
        val = int(total_minutes)
        h = val // 60
        m = val % 60
        
        ampm = "AM"
        if h >= 12:
            ampm = "PM"
        
        # Convert 24h to 12h display
        if h > 12:
            h -= 12
        if h == 0:
            h = 12
            
        return f"{h}:{m:02d} {ampm}"

    def toggle_step_expansion(self, step_index):
        """Called when the arrow button is clicked."""
        idx = int(step_index)
        if idx in self.expanded_indices:
            self.expanded_indices.remove(idx)
        else:
            self.expanded_indices.append(idx)
        
        # Force a refresh of the list
        self.refresh_step_list()

    def refresh_step_list(self):
        seq = self.app.sequencer
        if not seq.current_profile:
            self.ids.rv_steps.data = []
            return
        
        # 1. Force Refresh Predictions
        if hasattr(seq, 'update_predictions'):
            seq.update_predictions()

        # 2. Auto-Expand the Current Step
        current_idx = seq.current_step_index
        if current_idx != -1 and current_idx not in self.expanded_indices:
            self.expanded_indices.append(current_idx)

        data = []
        
        active_list_index = -1
        current_row_count = 0
        
        active_alert_name = None
        if seq.status == SequenceStatus.WAITING_FOR_USER and seq.current_alert_text:
            active_alert_name = seq.current_alert_text

        # Unit String Helper
        unit = "C" if self.app.is_metric else "F"

        for i, step in enumerate(seq.current_profile.steps):
            is_current_step = (i == current_idx)
            is_done = (i < current_idx)
            
            bg = [0.2, 0.2, 0.2, 1]
            txt = [1, 1, 1, 1]
            
            if is_current_step:
                if active_alert_name: 
                    bg = [0.2, 0.4, 0.6, 1]
                else:
                    bg = [0.2, 0.8, 0.2, 1] 
                    active_list_index = current_row_count 
            elif is_done:
                txt = [0.5, 0.5, 0.5, 1]

            # --- UNIT CONVERSION LOGIC ---
            if step.step_type == StepType.BOIL:
                sys_boil = self.app.settings_manager.get_system_setting("boil_temp_f", 212.0)
                user_boil = self.app.to_user_units(sys_boil, 'boil_temp')
                t_str = f"{user_boil:.0f}°{unit} (BOIL)"
            elif step.setpoint_f and step.setpoint_f >= 60:
                user_val = self.app.to_user_units(step.setpoint_f, 'temp')
                t_str = f"{user_val:.0f}°{unit}"
            else:
                t_str = "--"
            # -----------------------------

            # FIX: Format Duration as Integer
            # This strips the long decimals (e.g., 0.352...) seen in your screenshot
            if step.duration_min and step.duration_min > 0:
                d_str = f"{int(step.duration_min)} min"
            else:
                d_str = "--"
            
            r_str = getattr(step, 'predicted_ready_time', "--")

            has_children = (len(step.additions) > 0)
            is_expanded = (i in self.expanded_indices)
            arrow_icon = ""
            if has_children:
                arrow_icon = "v" if is_expanded else ">"

            data.append({
                'view_type': 'StepItem',
                'step_index': str(i + 1),
                'internal_index': i,
                'step_name': step.name,
                'step_target': t_str,
                'step_duration': d_str,
                'step_ready': r_str,
                'bg_color': bg,
                'text_color': txt,
                'arrow_text': arrow_icon,
                'arrow_disabled': not has_children
            })
            current_row_count += 1

            if is_expanded and has_children:
                sorted_adds = sorted(step.additions, key=lambda x: x.time_point_min, reverse=True)
                
                for add in sorted_adds:
                    is_active_child = False
                    if is_current_step and active_alert_name:
                        if add.name in active_alert_name or active_alert_name in add.name:
                            is_active_child = True
                    
                    child_bg = [0.15, 0.15, 0.15, 1]
                    child_txt = [0.7, 0.7, 0.7, 1]
                    
                    if is_active_child:
                        child_bg = [0.2, 0.8, 0.2, 1] 
                        child_txt = [1, 1, 1, 1]       
                        active_list_index = current_row_count 

                    data.append({
                        'view_type': 'AlertChildItem',
                        'alert_name': f"(@ {int(add.time_point_min)} min) {add.name}",
                        'bg_color': child_bg,
                        'text_color': child_txt
                    })
                    current_row_count += 1

        self.ids.rv_steps.data = data
        
        if active_list_index != -1:
            self.scroll_to_active(active_list_index)
        
    def scroll_to_active(self, index):
        """
        Manually calculates scroll_y to place the item at 'index' at the top.
        """
        rv = self.ids.rv_steps
        if not rv.data: return
        
        # Calculate the total height of the list and the position of our target
        # We assume StepItems are 50dp and AlertChildItems are 40dp
        total_height = 0
        target_top_offset = 0
        
        # Use dp to match Kivy's scaling
        from kivy.metrics import dp
        
        for i, item in enumerate(rv.data):
            # Determine height of this specific row
            row_h = dp(40) if item.get('view_type') == 'AlertChildItem' else dp(50)
            
            # If this is a row ABOVE our target, add to offset
            if i < index:
                target_top_offset += row_h
            
            total_height += row_h
            
        # Calculate Viewport parameters
        viewport_height = rv.height
        scrollable_distance = total_height - viewport_height
        
        # If content fits entirely in screen, just go to top
        if scrollable_distance <= 0:
            rv.scroll_y = 1.0
            return

        # Calculate scroll_y (1.0 is top, 0.0 is bottom)
        # We want the top of our target row to be at the top of the viewport.
        # This means we need to hide 'target_top_offset' pixels above the viewport.
        pixels_from_bottom = total_height - target_top_offset - viewport_height
        new_scroll_y = pixels_from_bottom / scrollable_distance
        
        # Clamp between 0 and 1 (don't scroll past bounds)
        new_scroll_y = max(0.0, min(1.0, new_scroll_y))
        
        # Apply scroll only if changed (prevents jitter)
        if not hasattr(self, '_last_scrolled_index'): self._last_scrolled_index = -1
        
        if self._last_scrolled_index != index:
            rv.scroll_y = new_scroll_y
            self._last_scrolled_index = index

    def open_delay_setup(self):
        """Called when DELAY START (or ACTIVE) is clicked."""
        status = self.app.sequencer.status
        
        # 1. Determine Values (Time, Temp, Vol)
        
        # Case A: Delay is currently running/waiting. 
        # We MUST show what is actually set in the system.
        if status == SequenceStatus.DELAYED_WAIT:
            # Convert UI Slider Values (which track the system) back to Backend for configure_slider
            raw_temp = self.app.to_backend_units(self.delay_temp, 'temp')
            raw_vol = self.app.to_backend_units(self.delay_vol, 'vol')
            # Keep existing time (don't reset to 6am)
            
        # Case B: First time opening in this session. Load Defaults.
        elif not self.has_initialized_delay:
            now = datetime.now()
            # Default target: 6:00 AM tomorrow
            next_target = now.replace(hour=6, minute=0, second=0, microsecond=0)
            if next_target <= now:
                next_target += timedelta(days=1)
            
            # Set the time property
            self.delay_minutes_total = (next_target.hour * 60) + next_target.minute
            
            # Load Manual defaults (Imperial)
            sm = self.app.settings_manager
            raw_temp = sm.get("manual_mode_settings", "last_setpoint_f", 154.0)
            raw_vol = sm.get("manual_mode_settings", "last_volume_gal", 8.0)
            
            # Mark as initialized so we don't overwrite next time
            self.has_initialized_delay = True

        # Case C: Not active, but we have opened it before. 
        # Use whatever is currently stored in the Kivy Properties (Persistence).
        else:
            # Convert the current UI values back to Imperial for configure_slider
            raw_temp = self.app.to_backend_units(self.delay_temp, 'temp')
            raw_vol = self.app.to_backend_units(self.delay_vol, 'vol')
            # Time is already in self.delay_minutes_total, no need to touch it.

        # 2. Slide the Hero Panel
        self.ids.hero_manager.transition.direction = 'left'
        self.ids.hero_manager.current = 'hero_delay'

        # 3. Configure Sliders (raw_temp/raw_vol must be Imperial here)
        self.app.configure_slider(self.ids.s_delay_temp, raw_temp, 'temp')
        self.app.configure_slider(self.ids.s_delay_vol, raw_vol, 'vol')
        
        # 4. Trigger the labels manually to ensure they appear
        self.on_delay_temp(None, self.delay_temp)
        self.on_delay_vol(None, self.delay_vol)

    def close_delay_setup(self):
        """Cancel button in Delay Setup."""
        self.ids.hero_manager.transition.direction = 'right'
        self.ids.hero_manager.current = 'hero_standard'

    def confirm_delay_start(self):
        """ACTIVATE/UPDATE button in Delay Setup."""
        try:
            # 1. Calculate Target Time
            val = int(self.delay_minutes_total)
            h = val // 60
            m = val % 60
            
            now = datetime.now()
            target_dt = now.replace(hour=h, minute=m, second=0, microsecond=0)
            
            if target_dt <= now:
                target_dt += timedelta(days=1)
            
            self.delay_target_dt = target_dt
            
            # 2. Context (Auto vs Manual)
            is_auto = (self.app.sequencer.status != SequenceStatus.MANUAL)
            
            # --- UNIT CONVERSION START ---
            threshold = 20 if self.app.is_metric else 70
            
            # Check Null Threshold for Temp
            if self.delay_temp < threshold:
                target_f = 0.0
            else:
                target_f = self.app.to_backend_units(self.delay_temp, 'temp')
                
            target_gal = self.app.to_backend_units(self.delay_vol, 'vol')
            # -----------------------------

            # 3. Call Sequencer (Always expects Imperial)
            self.app.sequencer.start_delayed_mode(
                target_f, 
                target_gal, 
                target_dt, 
                from_auto_mode=is_auto
            )
            
            # 4. MIRROR SETTINGS TO MANUAL UI (Visual confirmation)
            # Use configure_slider to handle unit ranges correctly
            # Note: configure_slider handles the < 15.0 null mapping internally
            self.app.configure_slider(self.ids.temp_slider, target_f, 'temp')
            self.app.configure_slider(self.ids.vol_slider, target_gal, 'vol')
            
            self.slider_time_val = 30.0
            self.slider_power_val = 3
            
            # 5. Update UI & Slide Back
            self.update_status_display()
            self.close_delay_setup()
            
        except Exception as e:
            print(f"Delay Start Error: {e}")
    
    def deactivate_delay(self):
        """Stops the Delayed Start and resets to Idle."""
        # This resets status to IDLE. 
        # Because we updated update_ui (below), the screen will stay where it is.
        self.app.sequencer.stop()
        
        self.update_status_display()
        self.close_delay_setup()
    
    def update_status_display(self):
        """
        Updates the Status Text, Delay Button, and Control Locking 
        based on the current Sequencer Status.
        """
        seq = self.app.sequencer
        status = seq.status

        # --- 1. HANDLE DELAYED WAIT STATE ---
        if status == SequenceStatus.DELAYED_WAIT:
            self.is_delay_active = True
            self.controls_disabled = True  # <--- LOCK CONTROLS
            
            self.delay_btn_text = "DELAY ACTIVE"
            self.delay_btn_color = [0.2, 0.6, 0.8, 1]
            
            if hasattr(seq, 'get_delayed_status_msg'):
                msg = seq.get_delayed_status_msg()
            else:
                msg = "Waiting for start time..."
            
            self.display_status = f"SLEEPING\n{msg}"

        # --- 2. HANDLE NORMAL STATES ---
        else:
            self.is_delay_active = False
            self.controls_disabled = False # <--- UNLOCK CONTROLS

            self.delay_btn_text = "DELAY START"
            self.delay_btn_color = [0.2, 0.2, 0.4, 1]

            if status == SequenceStatus.IDLE:
                self.display_status = "System Idle"
            
            elif status == SequenceStatus.MANUAL:
                self._update_prediction()

class ProfilesScreen(Screen):
    def refresh_list(self):
        app = App.get_running_app()
        profiles = app.settings_manager.get_all_profiles()
        default = [p for p in profiles if p.name == "Default Profile"]
        others = sorted([p for p in profiles if p.name != "Default Profile"], key=lambda x: x.name)
        sorted_profiles = default + others
        data_list = []
        for p in sorted_profiles:
            data_list.append({
                'text': f"{p.name}",
                'profile_name': p.name,
                'profile_id': p.id
            })
        self.ids.rv_profiles.data = data_list

    def go_back(self):
        self.manager.current = 'main'

class SystemSettingsScreen(Screen):
    """
    The 'Hub' for all settings menus.
    """
    def go_back(self):
        # Return to Dashboard
        self.manager.transition.direction = 'right'
        self.manager.current = 'main'

    def navigate_to(self, screen_name):
        # Go deeper into a settings sub-screen
        self.manager.transition.direction = 'left'
        self.manager.current = screen_name

class HardwareSettingsScreen(Screen):
    """
    Hardware Configuration: Sensors, Audio, Boil Temp, Volume.
    """
    # Properties bound to UI widgets
    boil_temp = NumericProperty(212)
    system_volume = NumericProperty(80)
    alert_repeat_freq = NumericProperty(15)  # <--- NEW PROPERTY
    
    # Selection lists for Spinners
    sensor_list = ListProperty(["unassigned"])
    audio_list = ListProperty(["default"])
    sound_list = ListProperty(["alert.wav"])

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.app = App.get_running_app()
        # Map friendly names back to internal IDs
        self.sensor_map = {} 
        self.audio_map = {}

    def on_pre_enter(self):
        """Load current values when entering the screen."""
        sm = self.app.settings_manager
        hw = self.app.hw
        
        # 1. LOAD BOIL TEMP (With Conversion)
        raw_boil = sm.get_system_setting("boil_temp_f", 212)
        self.app.configure_slider(self.ids.s_boil, raw_boil, 'boil_temp')

        # 2. LOAD SENSORS
        raw_sensors = hw.scan_available_sensors()
        self.sensor_list = ["unassigned"] + raw_sensors
        current_sensor = sm.get_system_setting("temp_sensor_id", "unassigned")
        # Ensure current is valid
        if current_sensor not in self.sensor_list:
            self.sensor_list.append(current_sensor)
        self.ids.spinner_sensor.text = current_sensor

        # 3. LOAD AUDIO DEVICES
        raw_audio = hw.scan_audio_devices()
        self.audio_list = []
        self.audio_map = {}
        
        current_audio_dev = sm.get_system_setting("audio_device", "default")
        current_friendly_text = "Default"

        for friendly, dev_str in raw_audio:
            self.audio_list.append(friendly)
            self.audio_map[friendly] = dev_str
            if dev_str == current_audio_dev:
                current_friendly_text = friendly
        
        self.ids.spinner_audio.text = current_friendly_text

        # 4. LOAD SOUNDS
        self.sound_list = [
            "alert.wav", "alt1_ding.wav", "alt2_buzzer.wav", 
            "alt2_ding.wav", "bell_ding.wav", "doorbell.wav", 
            "highbell.wav", "sports_buzzer.wav", "store_ding.wav"
        ]
        current_sound = sm.get_system_setting("alert_sound_file", "alert.wav")
        self.ids.spinner_sound.text = current_sound

        # 5. LOAD VOLUME (Mock or generic default as we can't easily read amixer)
        self.system_volume = 80 
        
        # 6. LOAD ALERT REPEAT FREQUENCY
        self.alert_repeat_freq = sm.get_system_setting("alert_repeat_freq", 15)

    def save_changes(self):
        """Write values to SettingsManager."""
        sm = self.app.settings_manager
        
        # Boil Temp: Convert User Value -> Imperial for Backend
        sys_val = self.app.to_backend_units(self.boil_temp, 'temp')
        sm.set_system_setting("boil_temp_f", int(sys_val))
        
        # Sensor
        sm.set_system_setting("temp_sensor_id", self.ids.spinner_sensor.text)
        
        # Audio Device (Map friendly name back to device string)
        selected_friendly = self.ids.spinner_audio.text
        dev_str = self.audio_map.get(selected_friendly, "default")
        sm.set_system_setting("audio_device", dev_str)
        
        # Sound File
        sm.set_system_setting("alert_sound_file", self.ids.spinner_sound.text)
        
        # Alert Frequency
        sm.set_system_setting("alert_repeat_freq", int(self.alert_repeat_freq))
        
        print("[HardwareSettings] Saved.")
        self.go_back()

    # --- RESTORED METHODS BELOW ---

    def test_audio(self):
        """Play the selected sound on the selected device."""
        import os
        selected_sound = self.ids.spinner_sound.text
        selected_friendly = self.ids.spinner_audio.text
        dev_str = self.audio_map.get(selected_friendly, "default")
        
        base_dir = os.path.dirname(os.path.abspath(__file__))
        sound_path = os.path.join(base_dir, "assets", selected_sound)
        
        if os.path.exists(sound_path):
            cmd = ["aplay", "-q"]
            if dev_str != "default":
                cmd.extend(["-D", dev_str])
            cmd.append(sound_path)
            subprocess.Popen(cmd, stderr=subprocess.DEVNULL)

    def set_volume_live(self, value):
        """Called on_touch_up of slider to set amixer volume."""
        try:
            vol_int = int(value)
            selected_friendly = self.ids.spinner_audio.text
            dev_str = self.audio_map.get(selected_friendly, "default")
            
            card_flag = []
            if dev_str.startswith("plughw:"):
                import re
                match = re.search(r'plughw:(\d+),', dev_str)
                if match:
                    card_flag = ["-c", match.group(1)]

            controls = ["PCM", "Master", "Speaker", "HDMI"]
            for control in controls:
                cmd = ["amixer"] + card_flag + ["sset", control, f"{vol_int}%"]
                subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as e:
            print(f"Vol Error: {e}")

    def go_back(self):
        self.manager.transition.direction = 'right'
        self.manager.current = 'sys_settings'
        
class AppSettingsScreen(Screen):
    """
    General App Preferences: Units, Auto-Start, Numlock, Logging.
    """
    # UI Properties
    units_text = StringProperty("Imperial (°F / Gal)")
    auto_start = BooleanProperty(False)
    auto_resume = BooleanProperty(False)
    force_numlock = BooleanProperty(False)
    csv_logging = BooleanProperty(False)

    # Unit Mapping
    UNIT_MAP = {
        "Imperial (°F / Gal)": "imperial",
        "Metric (°C / L)": "metric"
    }
    # Reverse map for loading
    UNIT_MAP_REV = {v: k for k, v in UNIT_MAP.items()}

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.app = App.get_running_app()

    def on_pre_enter(self):
        sm = self.app.settings_manager
        
        # 1. Load Units
        sys_unit = sm.get_system_setting("units", "imperial")
        self.units_text = self.UNIT_MAP_REV.get(sys_unit, "Imperial (°F / Gal)")
        
        # 2. Load Booleans
        self.auto_start = sm.get_system_setting("auto_start_enabled", True)
        self.auto_resume = sm.get_system_setting("auto_resume_enabled", False)
        self.force_numlock = sm.get_system_setting("force_numlock", True)
        self.csv_logging = sm.get_system_setting("enable_csv_logging", False)

    def on_auto_start(self, instance, value):
        """Enforce dependency: Auto-Resume requires Auto-Start."""
        if not value:
            self.auto_resume = False

    def save_changes(self):
        sm = self.app.settings_manager
        
        # 1. Update Global Prop
        is_now_metric = (self.units_text == "Metric (°C / L)")
        self.app.is_metric = is_now_metric
        
        # 2. Save Units
        val_unit = "metric" if is_now_metric else "imperial"
        sm.set_system_setting("units", val_unit)
        
        # 3. Save Booleans
        sm.set_system_setting("auto_start_enabled", self.auto_start)
        sm.set_system_setting("auto_resume_enabled", self.auto_resume)
        sm.set_system_setting("force_numlock", self.force_numlock)
        sm.set_system_setting("enable_csv_logging", self.csv_logging)
        
        # 4. Manage Auto-Start
        self._manage_autostart_file(self.auto_start)
        
        print("[AppSettings] Saved.")
        
        # 5. TRIGGER REFRESH
        self.app.refresh_all_screens()
        
        self.go_back()

    def _manage_autostart_file(self, enable):
        """Creates or removes the LXDE autostart entry."""
        autostart_dir = os.path.expanduser("~/.config/autostart")
        file_path = os.path.join(autostart_dir, "kettlebrain.desktop")
        
        if enable:
            try:
                if not os.path.exists(autostart_dir): os.makedirs(autostart_dir)
                
                # Resolve paths
                src_dir = os.path.dirname(os.path.abspath(__file__))
                app_root = os.path.dirname(src_dir)
                venv_python = os.path.join(app_root, "venv", "bin", "python")
                
                # Use venv python if exists, else system python
                python_exe = venv_python if os.path.exists(venv_python) else sys.executable
                
                main_script = os.path.join(app_root, "main.py")
                if not os.path.exists(main_script): main_script = os.path.join(src_dir, "main.py")
                
                icon_path = os.path.join(src_dir, "assets", "kettle.png")
                
                content = f"""[Desktop Entry]
Type=Application
Name=KettleBrain
Comment=Brewing Controller
Path={app_root}
Exec={python_exe} {main_script} --auto-start
Icon={icon_path}
Terminal=false
Categories=Utility;
"""
                with open(file_path, "w") as f: 
                    f.write(content)
                os.chmod(file_path, 0o755)
            except Exception as e: 
                print(f"[Settings] Error creating autostart: {e}")
        else:
            if os.path.exists(file_path):
                try: 
                    os.remove(file_path)
                except Exception as e: 
                    print(f"[Settings] Error removing autostart: {e}")

    def go_back(self):
        self.manager.transition.direction = 'right'
        self.manager.current = 'sys_settings'

class CalibrationSettingsScreen(Screen):
    """
    Heater Calibration: Calculates and sets degrees per minute.
    """
    # UI Properties
    cal_vol = NumericProperty(6.0)
    cal_start_temp = NumericProperty(70.0)
    cal_end_temp = NumericProperty(150.0)
    cal_time = NumericProperty(45.0)
    
    current_factor_text = StringProperty("Loading...")
    calc_result_text = StringProperty("--")
    
    # Internal calculated value
    new_calculated_factor = None

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.app = App.get_running_app()

    def on_pre_enter(self):
        sm = self.app.settings_manager
        
        # Display current setting (Converted for display)
        raw_fpm = sm.get_system_setting("heater_ref_rate_fpm", 1.2)
        
        if self.app.is_metric:
             # Convert F/min -> C/min (Delta conversion is just 5/9, no offset)
             val_disp = raw_fpm * 5/9
             unit = "C/min"
             ref_vol = "30L" # Approx ref
        else:
             val_disp = raw_fpm
             unit = "F/min"
             ref_vol = "8 Gal"
             
        self.current_factor_text = f"{val_disp:.2f} {unit} (Ref: {ref_vol})"
        
        # Configure Sliders (Defaults are Imperial, let configure_slider handle it)
        # Note: If we had stored last used cal values, we'd load them here. 
        # For now we default to standard start points.
        self.app.configure_slider(self.ids.s_cal_vol, 6.0, 'vol')
        self.app.configure_slider(self.ids.s_cal_start, 70.0, 'temp')
        self.app.configure_slider(self.ids.s_cal_end, 150.0, 'temp')
        
        self.calc_result_text = "--"
        self.new_calculated_factor = None
        self.ids.btn_update.disabled = True

    def calculate_efficiency(self):
        try:
            # 1. Convert User Inputs -> Imperial (Backend Truth)
            vol_gal = self.app.to_backend_units(self.cal_vol, 'vol')
            start_f = self.app.to_backend_units(self.cal_start_temp, 'temp')
            end_f = self.app.to_backend_units(self.cal_end_temp, 'temp')
            mins = float(self.cal_time)

            if mins <= 0: return

            # 2. Calculate Rate (Imperial)
            delta_temp = end_f - start_f
            if delta_temp <= 0: return
            
            actual_rate_fpm = delta_temp / mins
            
            # Normalize (Ref Volume is Gallons)
            ref_vol = self.app.settings_manager.get_system_setting("heater_ref_volume_gal", 8.0)
            normalized_rate_fpm = actual_rate_fpm * (vol_gal / ref_vol)
            
            # 3. Store result as Imperial (Backend Truth)
            self.new_calculated_factor = normalized_rate_fpm
            
            # 4. Display result in User Units
            if self.app.is_metric:
                disp_val = normalized_rate_fpm * 5/9
                unit = "C/min"
            else:
                disp_val = normalized_rate_fpm
                unit = "F/min"
                
            self.calc_result_text = f"{disp_val:.2f} {unit}"
            self.ids.btn_update.disabled = False
            
        except Exception as e:
            print(f"[Calibration] Math Error: {e}")

    def save_calibration(self):
        if self.new_calculated_factor:
            sm = self.app.settings_manager
            sm.set_system_setting("heater_ref_rate_fpm", self.new_calculated_factor)
            print(f"[Calibration] Updated factor to {self.new_calculated_factor}")
            
            # Refresh display
            self.current_factor_text = f"{self.new_calculated_factor:.2f} °F/min (Ref: 8 Gal)"
            self.calc_result_text = "Saved!"
            self.ids.btn_update.disabled = True

    def restore_defaults(self):
        sm = self.app.settings_manager
        sm.set_system_setting("heater_ref_rate_fpm", 1.2)
        self.on_pre_enter()
        print("[Calibration] Restored defaults.")

    def go_back(self):
        self.manager.transition.direction = 'right'
        self.manager.current = 'sys_settings'


class UpdatesSettingsScreen(Screen):
    """
    System Updates: Runs bash scripts to check/pull git changes.
    """
    log_text = StringProperty("Ready to check for updates.\n")
    is_working = BooleanProperty(False)
    install_enabled = BooleanProperty(False)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.app = App.get_running_app()

    def check_updates(self):
        self.log_text = "Checking for updates...\n"
        self.is_working = True
        self.install_enabled = False
        threading.Thread(target=self._run_update_process, args=(["--check"], True)).start()

    def install_updates(self):
        self.log_text += "\nStarting Install Process...\n"
        self.is_working = True
        self.install_enabled = False
        threading.Thread(target=self._run_update_process, args=([], False)).start()

    def _run_update_process(self, flags, is_check_mode):
        """Runs the update shell script in a background thread."""
        import subprocess
        
        # 1. Locate Script
        src_dir = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.dirname(src_dir)
        script_path = os.path.join(project_root, "update.sh")

        if not os.path.exists(script_path):
            self._append_log(f"Error: Could not find script at:\n{script_path}")
            self._finish_work(enable_install=False)
            return

        # 2. Run Process
        cmd = ["bash", script_path] + flags
        try:
            process = subprocess.Popen(
                cmd, 
                stdout=subprocess.PIPE, 
                stderr=subprocess.STDOUT, 
                text=True, 
                bufsize=1
            )

            update_available = False
            
            # 3. Stream Output
            while True:
                line = process.stdout.readline()
                if not line and process.poll() is not None:
                    break
                if line:
                    self._append_log(line)
                    # Simple heuristic to detect if update exists based on git output
                    lower = line.lower()
                    if "update available" in lower or "fast-forward" in lower or "file changed" in lower:
                        update_available = True

            return_code = process.poll()

            # 4. Final Status
            if is_check_mode:
                if update_available:
                    self._append_log("\n[Check Complete] Updates available.")
                    self._finish_work(enable_install=True)
                else:
                    self._append_log("\n[Check Complete] System is up to date.")
                    self._finish_work(enable_install=False)
            else:
                if return_code == 0:
                    self._append_log("\n[Success] Update installed. Please restart.")
                else:
                    self._append_log(f"\n[Failed] Process exited with code {return_code}")
                self._finish_work(enable_install=False)

        except Exception as e:
            self._append_log(f"\n[Error] Exception running update: {e}")
            self._finish_work(enable_install=False)

    def _append_log(self, text):
        """Schedule UI update on main thread."""
        Clock.schedule_once(lambda dt: self._update_log_text(text))

    def _update_log_text(self, text):
        self.log_text += text

    def _finish_work(self, enable_install):
        """Reset UI state on main thread."""
        def _reset(dt):
            self.is_working = False
            self.install_enabled = enable_install
        Clock.schedule_once(_reset)

    def go_back(self):
        self.manager.transition.direction = 'right'
        self.manager.current = 'sys_settings'    
        
    def restart_app(self):
        """
        Safely shuts down relays and restarts the Python process.
        Uses absolute paths to ensure reliability on Pi.
        """
        print("[System] Restarting application...")
        
        # 1. Safety Cleanup
        if hasattr(self.app, 'sequencer'):
            self.app.sequencer.stop()
        if hasattr(self.app, 'relay'):
            self.app.relay.stop_all()
            self.app.relay.cleanup_gpio()
            
        import sys
        import os
        
        # 2. Resolve Absolute Paths
        # Get the absolute path to the current python interpreter
        python = sys.executable
        
        # Get the absolute path to the actual script (main.py)
        # sys.argv[0] is often just 'main.py', we need '/home/pi/kettlebrain/src/main.py'
        script = os.path.abspath(sys.argv[0])
        
        # Get any command line arguments passed (excluding the script name)
        args = sys.argv[1:]
        
        # 3. Construct the Command
        # Format: [python_executable, script_path, arg1, arg2...]
        # We pass 'python' as the first arg (process name) for consistency
        cmd_args = [python, script] + args
        
        print(f"[System] Executing: {python} {script} {args}")
        
        # 4. Replace Process
        os.execv(python, cmd_args)
      
        
        

class KettleApp(App):
    
    fonts_loaded = BooleanProperty(False)
    is_metric = BooleanProperty(False) # <--- NEW GLOBAL PROPERTY
    
    def build(self):
        self.title = "KettleBrain"
        src_dir = os.path.dirname(os.path.abspath(__file__))
        project_dir = os.path.dirname(src_dir)
        root_dir = os.path.dirname(project_dir)
        
        self.settings_manager = SettingsManager(root_dir)
        
        # --- NEW: Initialize Metric State ---
        # Default is Imperial (False)
        sys_units = self.settings_manager.get_system_setting("units", "imperial")
        self.is_metric = (sys_units == "metric")
        # ------------------------------------
        
        self.hw = HardwareInterface(self.settings_manager)
        
        pending_profile_id = StringProperty(None)
        
        # Initialize relay control and sequencer
        from relay_control import RelayControl
        self.relay = RelayControl(self.settings_manager)
        self.sequencer = SequenceManager(self.settings_manager, self.relay, self.hw)
        self.sequencer.enter_manual_mode()
        
        # --- SCREEN MANAGER SETUP ---
        sm = ScreenManager()
        
        self.main_screen = MainScreen(name='main')
        self.profiles_screen = ProfilesScreen(name='profiles')
        self.editor_screen = ProfileEditorScreen(name='editor')
        self.step_editor_screen = StepEditorScreen(name='step_editor')
        self.alerts_screen = StepAlertsScreen(name='step_alerts')
        
        # ADDED: Water Screen
        self.water_screen = WaterScreen(name='water_calc')
        
        # NEW SETTINGS SCREENS
        self.sys_settings_screen = SystemSettingsScreen(name='sys_settings')
        self.hw_settings_screen = HardwareSettingsScreen(name='settings_hw')
        self.app_settings_screen = AppSettingsScreen(name='settings_app')
        self.cal_settings_screen = CalibrationSettingsScreen(name='settings_cal')
        self.updates_screen = UpdatesSettingsScreen(name='settings_updates')
        
        # Add widgets to ScreenManager         
        sm.add_widget(self.main_screen)
        sm.add_widget(self.profiles_screen)
        sm.add_widget(self.editor_screen)
        sm.add_widget(self.step_editor_screen)
        sm.add_widget(self.alerts_screen)
        sm.add_widget(self.water_screen) # <--- ADDED WIDGET
        sm.add_widget(self.cal_settings_screen)
        sm.add_widget(self.updates_screen)
        
        # Add the new settings screens
        sm.add_widget(self.sys_settings_screen)
        sm.add_widget(self.hw_settings_screen)
        sm.add_widget(self.app_settings_screen)
                
        Clock.schedule_interval(self.update_ui, 0.1)
        return sm
    
    def update_ui(self, dt):
        """
        Main UI Loop (10Hz).
        Updates Temps, Timer, Status, Heartbeat, and Heater Indicators.
        """
        # Safety check to ensure UI is ready
        if not self.root or self.root.current != 'main': 
            return
            
        seq = self.sequencer
        screen = self.main_screen
        status = seq.status
        
        screen.is_profile_loaded = (seq.current_profile is not None)
        
        # --- 1. TEMPERATURE COLORS ONLY ---
        current_temp_f = seq.current_temp if seq.current_temp else 0.0
        tgt_check_f = seq.get_target_temp()
        
        if tgt_check_f:
            diff = current_temp_f - tgt_check_f
            if abs(diff) < 1.0: 
                screen.temp_color = [0.2, 0.8, 0.2, 1] # Green (Good)
            elif diff < 0: 
                screen.temp_color = [0.2, 0.4, 0.8, 1] # Blue (Heating)
            else: 
                screen.temp_color = [0.8, 0.2, 0.2, 1] # Red (Hot)
        else:
            screen.temp_color = [0.2, 0.8, 0.2, 1] 
            
        # --- UNIT CONVERSION PREP ---
        unit = "C" if self.is_metric else "F"
        
        # --- 2. UPDATE LABELS (Temp, Target, Timer) ---
        # LIVE TEMP (Convert F -> User Unit)
        user_temp = self.to_user_units(current_temp_f, 'temp')
        screen.display_temp = f"{user_temp:.1f} °{unit}"
        
        screen.display_timer = seq.get_display_timer()
        screen.display_elapsed = seq.get_global_elapsed_time_str()
        
        # TARGET TEMP LOGIC
        sys_boil_f = self.settings_manager.get_system_setting("boil_temp_f", 212.0)
        
        raw_target_f = 0.0
        is_boil = False

        # Determine Target (In Imperial) based on State
        if status == SequenceStatus.MANUAL:
            if getattr(seq, 'is_manual_running', False):
                raw_target_f = seq.target_temp
            else:
                # Slider is User Unit -> Convert back to F to check boil
                raw_target_f = self.to_backend_units(screen.slider_temp_val, 'temp')

        elif status == SequenceStatus.DELAYED_WAIT:
             raw_target_f = self.to_backend_units(screen.delay_temp, 'temp')

        elif seq.current_profile and seq.current_step_index >= 0:
            step = seq.current_profile.steps[seq.current_step_index]
            if step.step_type == StepType.BOIL:
                is_boil = True
            else:
                raw_target_f = step.setpoint_f if step.setpoint_f else 0.0
        
        # Display Logic
        if is_boil or raw_target_f >= sys_boil_f:
            user_boil = self.to_user_units(sys_boil_f, 'boil_temp')
            screen.display_target = f"{int(user_boil)} (BOIL)"
        elif raw_target_f < 60: 
            screen.display_target = "--"
        else:
            user_target = self.to_user_units(raw_target_f, 'temp')
            screen.display_target = f"{int(user_target)} °{unit}"

        # --- 3. HEARTBEAT PULSE ---
        import time
        now = time.time()
        
        is_manual_active = (status == SequenceStatus.MANUAL and getattr(seq, 'is_manual_running', False))
        is_auto_active = (status == SequenceStatus.RUNNING or status == SequenceStatus.WAITING_FOR_USER)

        if is_manual_active or is_auto_active:
            if int(now * 2) % 2 == 0: screen.heartbeat_color = [0, 1, 0, 1] 
            else: screen.heartbeat_color = [0, 0.3, 0, 1]
            
        elif status == SequenceStatus.PAUSED:
            if int(now * 2) % 2 == 0: screen.heartbeat_color = [0.2, 0.4, 0.8, 1] 
            else: screen.heartbeat_color = [0.1, 0.2, 0.4, 1] 
            
        elif status == SequenceStatus.DELAYED_WAIT:
            if int(now) % 2 == 0: screen.heartbeat_color = [0.2, 0.6, 0.8, 1]
            else: screen.heartbeat_color = [0.1, 0.3, 0.4, 1]
            
        else:
            screen.heartbeat_color = [0.2, 0.2, 0.2, 1]
            
        # --- 4. HEATER INDICATORS ---
        relay_obj = getattr(seq, 'relay', getattr(seq, 'relays', None))
        if relay_obj and hasattr(relay_obj, 'relay_states'):
            states = relay_obj.relay_states
            screen.heater_1_active = states.get("Heater1", False)
            screen.heater_2_active = states.get("Heater2", False)
        else:
            screen.heater_1_active = False
            screen.heater_2_active = False

        # --- 5. STATUS TEXT & PREDICTION ---
        sys_msg = seq.get_status_message()
        
        if seq.current_profile:
            screen.display_profile_name = f"Profile: {seq.current_profile.name}"
        else:
            screen.display_profile_name = ""

        if status == SequenceStatus.DELAYED_WAIT:
             if hasattr(seq, 'get_delayed_status_msg'):
                msg = seq.get_delayed_status_msg()
                screen.display_status = f"SLEEPING\n{msg}"
             else:
                screen.display_status = "DELAY ACTIVE"
        elif status == SequenceStatus.MANUAL:
            if "ALERT" in sys_msg:
                screen.display_status = sys_msg
            else:
                if hasattr(screen, '_update_prediction'): 
                    screen._update_prediction()
        else:
            screen.display_status = sys_msg

        # --- 6. VIEW SWITCHING ---
        if screen.last_status == SequenceStatus.DELAYED_WAIT and status == SequenceStatus.MANUAL:
            screen.ids.center_content.current = 'page_manual'
            if hasattr(screen, '_update_prediction'): screen._update_prediction()

        elif status == SequenceStatus.MANUAL:
            if screen.ids.center_content.current != 'page_manual': 
                screen.ids.center_content.current = 'page_manual'
                if hasattr(screen, '_update_prediction'): screen._update_prediction()
                
        elif status in [SequenceStatus.RUNNING, SequenceStatus.PAUSED, SequenceStatus.WAITING_FOR_USER]:
            if screen.ids.center_content.current != 'page_auto': 
                screen.ids.center_content.current = 'page_auto'

        # --- 7. AUTO MODE LIST REFRESH ---
        now = time.time()
        current_id = seq.current_profile.id if seq.current_profile else None
        current_idx = seq.current_step_index
        
        if not hasattr(screen, 'last_refresh_time'): screen.last_refresh_time = 0
        
        should_refresh = False
        if current_id != screen.last_profile_id or current_idx != screen.last_step_index:
            should_refresh = True
        elif seq.status == SequenceStatus.RUNNING and (now - screen.last_refresh_time > 10.0):
            should_refresh = True
            
        if should_refresh:
            screen.refresh_step_list()
            screen.last_profile_id = current_id
            screen.last_step_index = current_idx
            screen.last_refresh_time = now

        # --- 8. ACTION BUTTON TEXT ---
        if status == SequenceStatus.MANUAL: 
            if getattr(seq, 'is_manual_running', False):
                screen.action_button_text = "PAUSE"
                screen.action_button_color = [0.2, 0.4, 0.8, 1] 
            else:
                if getattr(seq, 'temp_reached', False):
                    screen.action_button_text = "RESUME"
                    screen.action_button_color = [1, 0.8, 0, 1] 
                else:
                    screen.action_button_text = "START"
                    screen.action_button_color = [0.2, 0.8, 0.4, 1]
        elif status == SequenceStatus.RUNNING: 
            screen.action_button_text = "PAUSE"
            screen.action_button_color = [0.2, 0.4, 0.8, 1]
        elif status == SequenceStatus.PAUSED: 
            screen.action_button_text = "RESUME"
            screen.action_button_color = [1, 0.8, 0, 1]
        elif status == SequenceStatus.WAITING_FOR_USER:
            if seq.current_alert_text == "Step Complete": 
                screen.action_button_text = "NEXT STEP"
                screen.action_button_color = [0.2, 0.8, 0.4, 1]
            else: 
                screen.action_button_text = "CONFIRM"
                screen.action_button_color = [0.8, 0.4, 0.2, 1]
        else: 
            screen.action_button_text = "START"
            screen.action_button_color = [0.2, 0.8, 0.4, 1]

        # --- 9. DELAYED START SYNC ---
        if status == SequenceStatus.DELAYED_WAIT:
            screen.is_delay_active = True
            screen.controls_disabled = True
            screen.delay_btn_text = "DELAY ACTIVE"
            screen.delay_btn_color = [0.2, 0.6, 0.8, 1]
        else:
            screen.is_delay_active = False
            screen.controls_disabled = False
            screen.delay_btn_text = "DELAY START"
            screen.delay_btn_color = [0.2, 0.2, 0.4, 1]
            
        # FIX: Update Est. End Label
        if hasattr(screen, '_update_est_end'):
            screen._update_est_end()
                  
        screen.last_status = status
    
    def refresh_all_screens(self):
        """
        Called when Global Units change. Forces screens to re-configure their sliders/labels.
        """
        print(f"[App] Refreshing all screens. Metric={self.is_metric}")
        
        # 1. Main Screen (Manual Sliders)
        if self.main_screen:
            self.main_screen._load_manual_settings()
            
        # 2. Water Screen (Run its existing converter)
        if self.water_screen:
            self.water_screen.convert_values(self.is_metric)
            
        # 3. Hardware Settings (Re-run pre-enter)
        if self.hw_settings_screen:
            self.hw_settings_screen.on_pre_enter()
            
        # 4. Calibration Settings (Re-run pre-enter)
        if self.cal_settings_screen:
            self.cal_settings_screen.on_pre_enter()
            
        # 5. Profile Editor (Refresh List)
        if self.editor_screen:
            self.editor_screen.refresh_steps()
    
    def open_profile_options(self, profile_id, profile_name):
        popup = ProfileOptionsPopup()
        popup.profile_id = profile_id
        popup.profile_name = profile_name
        popup.open()

    def load_profile(self, profile_id):
        """
        Request to load a profile.
        If system is IDLE, loads immediately.
        If system is BUSY (Manual/Auto/Delay), prompts user on Main Screen.
        """
        seq = self.sequencer
        
        # 1. Check if System is Busy
        # We consider anything other than IDLE as "Active/Running" for safety.
        if seq.status != SequenceStatus.IDLE:
            # Store ID and Prompt User
            self.pending_profile_id = profile_id
            self.main_screen.prompt_profile_load()
            return

        # 2. Immediate Load (System is Idle)
        self._execute_load_profile(profile_id)

    def finish_pending_load(self):
        """Called by MainScreen when user confirms RESET & LOAD."""
        if self.pending_profile_id:
            # Force Stop (clears status, relays, but not profile object yet)
            self.sequencer.stop()
            # Execute Load
            self._execute_load_profile(self.pending_profile_id)
            self.pending_profile_id = None

    def _execute_load_profile(self, profile_id):
        """Internal helper to actually load the data and switch views."""
        profile = self.settings_manager.get_profile_by_id(profile_id)
        if profile:
            self.sequencer.load_profile(profile)
            self.root.current = 'main'
            self.main_screen.ids.center_content.current = 'page_auto'
            # Trigger refresh
            self.main_screen.refresh_step_list()
    
    def copy_profile(self, profile_id):
        original = self.settings_manager.get_profile_by_id(profile_id)
        if original:
            new_p = BrewProfile(id=str(uuid.uuid4()), name=f"Copy of {original.name}")
            new_p.steps = copy.deepcopy(original.steps)
            new_p.water_data = copy.deepcopy(original.water_data)
            new_p.chemistry_data = copy.deepcopy(original.chemistry_data)
            self.settings_manager.save_profile(new_p)
            self.root.get_screen('profiles').refresh_list()

    def delete_profile(self, profile_id):
        profile = self.settings_manager.get_profile_by_id(profile_id)
        if profile and profile.name == "Default Profile": return
        self.settings_manager.delete_profile(profile_id)
        self.root.get_screen('profiles').refresh_list()

    def launch_profile_editor(self, profile_id):
        profile = self.settings_manager.get_profile_by_id(profile_id)
        if profile:
            self.root.current = 'editor'
            self.editor_screen.load_data(profile)

    def open_profiles(self):
        self.root.current = 'profiles'
        self.profiles_screen.refresh_list()

    # DOUBLE VISION ---------------------------------------------------
    def move_step_up(self, index):
        """Swaps the selected step with the one above it."""
        steps = self.editor_screen.editing_profile.steps
        if index > 0 and index < len(steps):
            steps[index], steps[index-1] = steps[index-1], steps[index]
            self.editor_screen.refresh_steps()

    def move_step_down(self, index):
        """Swaps the selected step with the one below it."""
        steps = self.editor_screen.editing_profile.steps
        if index >= 0 and index < len(steps) - 1:
            steps[index], steps[index+1] = steps[index+1], steps[index]
            self.editor_screen.refresh_steps()
    # DOUBLE VISION ---------------------------------------------------
       
    def delete_step_from_editor(self, index):
        steps = self.editor_screen.editing_profile.steps
        if 0 <= index < len(steps):
            steps.pop(index)
            self.editor_screen.refresh_steps()
            
    def open_step_editor(self, step_index):
        steps = self.editor_screen.editing_profile.steps
        if 0 <= step_index < len(steps):
            step_to_edit = steps[step_index]
            
            # Load data into the screen
            self.step_editor_screen.load_step(step_to_edit, step_index)
            
            # Switch view
            self.root.current = 'step_editor'

    def update_step_in_editor(self, index, data):
        """
        Updates the step object with data dict returned from popup.
        """
        steps = self.editor_screen.editing_profile.steps
        if 0 <= index < len(steps):
            s = steps[index]
            s.name = data["name"]
            
            # Convert strings back to Enums/Types
            try:
                s.step_type = StepType(data["type"])
            except: pass
            
            s.setpoint_f = float(data["temp"])
            s.duration_min = float(data["dur"])
            
            try:
                s.power_watts = int(data["power"])
            except: s.power_watts = 1800
            
            try:
                s.lauter_volume = float(data["vol"]) if data["vol"] else None
            except: s.lauter_volume = None
            
            try:
                s.timeout_behavior = TimeoutBehavior(data["timeout"])
            except: pass
            
            s.additions = data["additions"]
            self.editor_screen.refresh_steps()
            
    def on_stop(self):
        """Called by Kivy when the app is closing normally."""
        print("[App] Stopping...")
        if hasattr(self, 'sequencer'):
            self.sequencer.stop()
        if hasattr(self, 'relay'):
            self.relay.stop_all()
            
        # Release resources
        if hasattr(self, 'hw'):
            # If HardwareInterface has a cleanup, call it
            pass
            
    # --- GLOBAL UNIT CONVERSION HELPERS ---
    
    def to_user_units(self, imperial_val, type_str):
        if not self.is_metric:
            return imperial_val
            
        # FIX: Added 'boil_temp' to the check so it converts 212F -> 100C
        if type_str == 'temp' or type_str == 'boil_temp':
            return (imperial_val - 32) * 5/9
        elif type_str == 'vol':
            return imperial_val * 3.78541
        return imperial_val

    def to_backend_units(self, user_val, type_str):
        if not self.is_metric:
            return user_val
            
        # FIX: Added 'boil_temp' to the check
        if type_str == 'temp' or type_str == 'boil_temp':
            return (user_val * 9/5) + 32
        elif type_str == 'vol':
            return user_val / 3.78541
        return user_val

    def configure_slider(self, slider_obj, imperial_val, type_str):
        """
        Central logic to snap a slider to the correct Min/Max/Step and Value
        based on the current Global Units.
        
        type_str options: 'temp', 'boil_temp', 'vol'
        """
        if not slider_obj: return

        if self.is_metric:
            # --- METRIC CONFIG ---
            converted_val = self.to_user_units(imperial_val, type_str)
            
            if type_str == 'temp':
                # General Temp: 19C (Null) -> 20C (Start) -> 100C
                slider_obj.min = 19
                slider_obj.max = 100
                slider_obj.step = 1
                
            elif type_str == 'boil_temp':
                slider_obj.min = 80
                slider_obj.max = 100
                slider_obj.step = 1
                
            elif type_str == 'vol':
                slider_obj.min = 8.0
                slider_obj.max = 35.0
                slider_obj.step = 0.5
            
            # Handle Null Case (0.0 input) mapping to Min
            if type_str == 'temp' and imperial_val < 15.0:
                 slider_obj.value = slider_obj.min
            else:
                 # Snap value
                 slider_obj.value = round(converted_val / slider_obj.step) * slider_obj.step
            
        else:
            # --- IMPERIAL CONFIG ---
            if type_str == 'temp':
                # General Temp: 69F (Null) -> 70F (Start) -> 212F
                slider_obj.min = 69
                slider_obj.max = 212
                slider_obj.step = 1
                
            elif type_str == 'boil_temp':
                slider_obj.min = 180
                slider_obj.max = 212
                slider_obj.step = 1
                
            elif type_str == 'vol':
                slider_obj.min = 2.0
                slider_obj.max = 9.0
                slider_obj.step = 0.25
            
            # Handle Null Case mapping to Min
            if type_str == 'temp' and imperial_val < 15.0:
                slider_obj.value = slider_obj.min
            else:
                slider_obj.value = imperial_val

class WaterScreen(Screen):
    # --- GLOBAL SETTINGS ---
    is_metric = BooleanProperty(False)
    mash_method = StringProperty("No Sparge (BIAB)")
    
    # --- INPUTS: WATER ---
    tun_capacity = NumericProperty(10.0) # <--- NEW INPUT
    grain_wt = NumericProperty(10.0)
    boil_time = NumericProperty(60.0)
    grain_temp = NumericProperty(68.0)
    mash_temp = NumericProperty(152.0)
    boiloff = NumericProperty(1.0)
    abs_rate = NumericProperty(0.5)
    trub_vol = NumericProperty(0.25)
    ferm_vol = NumericProperty(5.5)
    thickness = NumericProperty(1.5)
        
    # --- INPUTS: CHEMISTRY ---
    srm = NumericProperty(5.0)
    target_ph = NumericProperty(5.4)
    tgt_ca = NumericProperty(50)
    tgt_mg = NumericProperty(10)
    tgt_na = NumericProperty(15)
    tgt_so4 = NumericProperty(75)
    tgt_cl = NumericProperty(63)
    
    profile_names = ListProperty(["Default"])
    loaded_profiles = []

    # --- PROFILE TRACKING (NEW) ---
    profile_text_color = ListProperty([1, 1, 1, 1]) # Default White
    last_loaded_profile_data = {}
    current_profile_clean_name = StringProperty("")

    # --- RESULTS ---
    strike_vol = StringProperty("--")
    sparge_vol = StringProperty("--")
    strike_temp = StringProperty("--")
    pre_boil_vol = StringProperty("--")
    total_mash_vol = StringProperty("--")
    total_water = NumericProperty(0.0) 
    
    # --- NEW RESULT PROPERTIES ---
    res_total_disp = StringProperty("--")
    res_set_aside = StringProperty("--")
    res_dough_in = StringProperty("--")
    res_mash = StringProperty("--")
    # -----------------------------
    
    res_gypsum = StringProperty("0.0 g")
    res_cacl2 = StringProperty("0.0 g")
    res_epsom = StringProperty("0.0 g")
    res_salt = StringProperty("0.0 g")
    res_lime = StringProperty("0.0 g")
    res_acid = StringProperty("0.0 ml")
    res_acid_g = StringProperty("0.0 g")
    
    # --- RAW RESULTS FOR AUTO-POPULATION (System Units or Display Units? Display Units) ---
    raw_total_water = NumericProperty(0.0)
    raw_dough_in_vol = NumericProperty(0.0)
    raw_mash_vol = NumericProperty(0.0)
    raw_pre_boil_vol = NumericProperty(0.0)
    raw_strike_temp = NumericProperty(0.0)
    
    # --- CONTEXT TRACKING ---
    context = StringProperty("MANUAL") # "MANUAL" or "AUTO"

    def on_pre_enter(self):
        app = App.get_running_app()
        seq = app.sequencer
        sm = app.settings_manager
        
        # 1. Determine Context
        if seq.status != SequenceStatus.IDLE and seq.status != SequenceStatus.MANUAL and seq.current_profile:
            self.context = "AUTO"
        elif seq.status == SequenceStatus.MANUAL:
            self.context = "MANUAL"
        else:
            if seq.current_profile:
                self.context = "AUTO"
            else:
                self.context = "MANUAL"

        # 2. Load Profile Definitions
        self._load_target_profiles()

        # 3. Retrieve Saved Data based on Context
        data = {}
        if self.context == "AUTO" and seq.current_profile:
            w_data = getattr(seq.current_profile, 'water_data', {}) or {}
            c_data = getattr(seq.current_profile, 'chemistry_data', {}) or {}
            
            if not w_data and not c_data:
                 data = sm.settings.get("water_defaults", {})
            else:
                 data = {**w_data, **c_data}
        else:
            data = sm.settings.get("manual_water_session", {})
            if not data: 
                data = sm.settings.get("water_defaults", {})

        # 4. DECISION: Fresh Start vs Restore
        is_fresh = "profile_name" not in data and "grain_wt" not in data
        
        if is_fresh:
            # Fresh Start: Load defaults completely
            if self.profile_names:
                self.load_target_profile(self.profile_names[0])
            self._apply_dict_to_ui(data)
        else:
            # Restore Session: Apply saved values FIRST
            self._apply_dict_to_ui(data)
            
            # Restore Profile Context
            p_name = data.get("profile_name", "")
            if p_name and p_name in self.profile_names:
                self.current_profile_clean_name = p_name
                
                # --- FIX 3: Silence the Spinner Trigger ---
                self._ignore_spinner_load = True
                self.ids.profile_spinner.text = p_name
                self._ignore_spinner_load = False
                # ------------------------------------------
                
                # Manually populate baseline data for the asterisk check
                for p in self.loaded_profiles:
                    if p['name'] == p_name:
                        self.last_loaded_profile_data = {
                            'ca': int(p.get('ca', 0)),
                            'mg': int(p.get('mg', 0)),
                            'na': int(p.get('na', 0)),
                            'so4': int(p.get('so4', 0)),
                            'cl': int(p.get('cl', 0))
                        }
                        break
                
                self.check_profile_match()
                
            elif self.profile_names:
                 # Fallback
                 self._ignore_spinner_load = True
                 self.ids.profile_spinner.text = self.profile_names[0]
                 self._ignore_spinner_load = False

        # 5. UI Setup
        self.ids.tabs.switch_to(self.ids.tab_results)
        self.calculate_all()

        # --- NEW CODE STARTS HERE (APPEND TO END) ---
        # 6. Global Unit Sync
        # Check if the Global Setting has changed since we last saved this specific water session
        app = App.get_running_app()
        global_units = app.settings_manager.get_system_setting("units", "imperial")
        
        # Determine target state
        should_be_metric = (global_units == "metric")
        
        # If the loaded session units (self.is_metric) don't match the System Global (global_units), convert them.
        if self.is_metric != should_be_metric:
            self.convert_values(should_be_metric)
        # --------------------------------------------
    
    def _snap_and_set(self, slider_id, val, min_v, max_v, step_v):
        """Helper to reconfigure slider and snap value."""
        if slider_id not in self.ids: return val
        
        slider = self.ids[slider_id]
        slider.min = min_v
        slider.max = max_v
        slider.step = step_v
        
        # Snap logic: Round to nearest step
        snapped = round(val / step_v) * step_v
        
        # Clamp to bounds
        snapped = max(min_v, min(max_v, snapped))
        return snapped

    def convert_values(self, to_metric):
        """Converts inputs and reconfigures sliders for Metric/Imperial."""
        if to_metric:
            # --- IMPERIAL -> METRIC ---
            
            # 0. Tun Capacity: Gal -> L (Step 1.0 L)
            self.tun_capacity = self._snap_and_set('s_tun_cap', self.tun_capacity * 3.78541, 19.0, 76.0, 1.0)

            # 1. Grain: lb -> kg (Step 0.25 kg)
            # Range: ~1kg to 7kg
            self.grain_wt = self._snap_and_set('s_grain', self.grain_wt * 0.453592, 1.0, 8.0, 0.25)

            # 2. Grain Temp: F -> C (Step 1 C)
            # Range: 10C to 50C
            self.grain_temp = self._snap_and_set('s_grain_temp', (self.grain_temp - 32) * 5/9, 10, 50, 1)

            # 3. Mash Temp: F -> C (Step 1 C)
            # Range: 60C to 80C
            self.mash_temp = self._snap_and_set('s_mash_temp', (self.mash_temp - 32) * 5/9, 60, 80, 1)

            # 4. Ferm Volume: Gal -> L (Step 0.5 L)
            # Range: 8L to 30L
            self.ferm_vol = self._snap_and_set('s_ferm_vol', self.ferm_vol * 3.78541, 8.0, 32.0, 0.5)

            # 5. Boil Off: Gal -> L (Step 0.5 L)
            self.boiloff = self._snap_and_set('s_boiloff', self.boiloff * 3.78541, 2.0, 15.0, 0.5)

            # 6. Trub: Gal -> L (Step 0.25 L)
            self.trub_vol = self._snap_and_set('s_trub', self.trub_vol * 3.78541, 0.0, 12.0, 0.25)

            # 7. Absorption: qt/lb -> L/kg (Step 0.05 L/kg)
            # Factor ~2.086 (0.2 qt/lb -> ~0.4 L/kg)
            ratio = 2.08635
            self.abs_rate = self._snap_and_set('s_abs', self.abs_rate * ratio, 0.4, 2.5, 0.05)

            # 8. Thickness: qt/lb -> L/kg (Step 0.1 L/kg)
            self.thickness = self._snap_and_set('s_thick', self.thickness * ratio, 1.0, 7.0, 0.1)
            
            self.is_metric = True
            
        else:
            # --- METRIC -> IMPERIAL ---
            
            # 0. Tun Capacity: L -> Gal (Step 0.25 Gal)
            self.tun_capacity = self._snap_and_set('s_tun_cap', self.tun_capacity / 3.78541, 5.0, 20.0, 0.25)

            # 1. Grain: kg -> lb (Step 0.5 lb)
            self.grain_wt = self._snap_and_set('s_grain', self.grain_wt / 0.453592, 2.0, 16.0, 0.5)

            # 2. Grain Temp: C -> F (Step 1 F)
            self.grain_temp = self._snap_and_set('s_grain_temp', (self.grain_temp * 9/5) + 32, 50, 120, 1)

            # 3. Mash Temp: C -> F (Step 1 F)
            self.mash_temp = self._snap_and_set('s_mash_temp', (self.mash_temp * 9/5) + 32, 140, 175, 1)

            # 4. Ferm Volume: L -> Gal (Step 0.25 Gal)
            self.ferm_vol = self._snap_and_set('s_ferm_vol', self.ferm_vol / 3.78541, 2.0, 9.0, 0.25)

            # 5. Boil Off: L -> Gal (Step 0.1 Gal)
            self.boiloff = self._snap_and_set('s_boiloff', self.boiloff / 3.78541, 0.5, 4.0, 0.1)

            # 6. Trub: L -> Gal (Step 0.25 Gal)
            self.trub_vol = self._snap_and_set('s_trub', self.trub_vol / 3.78541, 0.0, 3.0, 0.25)

            # 7. Absorption: L/kg -> qt/lb (Step 0.05 qt/lb)
            ratio = 2.08635
            self.abs_rate = self._snap_and_set('s_abs', self.abs_rate / ratio, 0.20, 1.20, 0.05)

            # 8. Thickness: L/kg -> qt/lb (Step 0.1 qt/lb)
            self.thickness = self._snap_and_set('s_thick', self.thickness / ratio, 0.5, 3.5, 0.1)
            
            self.is_metric = False

        # Recalculate outputs
        self.calculate_all()
    
    def _apply_dict_to_ui(self, data):
        self.mash_method = data.get("mash_method", "No Sparge (BIAB)")
        self.tun_capacity = float(data.get("tun_capacity", 10.0)) # <--- LOAD
        self.grain_wt = float(data.get("grain_wt", 10.0))
        self.grain_temp = float(data.get("grain_temp", 68.0))
        self.mash_temp = float(data.get("mash_temp", 152.0))
        self.boil_time = float(data.get("boil_time", 60.0))
        self.ferm_vol = float(data.get("ferm_vol", 5.5))
        self.trub_vol = float(data.get("trub_vol", 0.25))
        self.boiloff = float(data.get("boiloff", 1.0))
        self.abs_rate = float(data.get("abs_rate", 0.5))
        self.thickness = float(data.get("thickness", 1.5))
        
        self.srm = float(data.get("srm", 5.0))
        self.target_ph = float(data.get("target_ph", 5.4))
        self.tgt_ca = int(data.get("tgt_ca", 50))
        self.tgt_mg = int(data.get("tgt_mg", 10))
        self.tgt_na = int(data.get("tgt_na", 15))
        self.tgt_so4 = int(data.get("tgt_so4", 75))
        self.tgt_cl = int(data.get("tgt_cl", 63))

    def _scrape_ui_to_dict(self):
        return {
            "mash_method": self.mash_method,
            "tun_capacity": self.tun_capacity, # <--- SAVE
            "grain_wt": self.grain_wt,
            "grain_temp": self.grain_temp,
            "mash_temp": self.mash_temp,
            "boil_time": self.boil_time,
            "ferm_vol": self.ferm_vol,
            "trub_vol": self.trub_vol,
            "boiloff": self.boiloff,
            "abs_rate": self.abs_rate,
            "thickness": self.thickness,
            "srm": self.srm,
            "target_ph": self.target_ph,
            "tgt_ca": self.tgt_ca,
            "tgt_mg": self.tgt_mg,
            "tgt_na": self.tgt_na,
            "tgt_so4": self.tgt_so4,
            "tgt_cl": self.tgt_cl,
            # NEW: Save the clean name of the current profile
            "profile_name": self.current_profile_clean_name 
        }

    def save_and_exit(self):
        """Save data to the correct context and return to dashboard."""
        app = App.get_running_app()
        sm = app.settings_manager
        seq = app.sequencer
        
        # Scrape all UI values into one dict
        full_data = self._scrape_ui_to_dict()
        
        if self.context == "AUTO" and seq.current_profile:
            # FIX: Split data back into Water vs Chemistry for the Profile Object
            chem_keys = [
                "srm", "target_ph", "tgt_ca", "tgt_mg", 
                "tgt_na", "tgt_so4", "tgt_cl", "profile_name"
            ]
            
            water_data = {k: v for k, v in full_data.items() if k not in chem_keys}
            chem_data = {k: v for k, v in full_data.items() if k in chem_keys}
            
            # Assign to specific attributes on the Profile object
            seq.current_profile.water_data = water_data
            seq.current_profile.chemistry_data = chem_data
            
            # Save to disk
            sm.save_profile(seq.current_profile)
            print("[WaterScreen] Saved split data to Profile.")
        else:
            # Manual mode can keep it all in one session dict
            sm.settings["manual_water_session"] = full_data
            sm._save_settings()
            print("[WaterScreen] Saved to Manual Session.")
            
        app.root.current = 'main'

    def update_units(self, value):
        self.is_metric = (value == "Metric")
        self.calculate_all()

    def _load_target_profiles(self):
        app_dir = os.path.dirname(os.path.abspath(__file__))
        path = os.path.join(app_dir, 'assets', 'target_water_profiles.json')
        print(f"[WaterScreen] Loading profiles from: {path}")

        try:
            if os.path.exists(path):
                with open(path, 'r') as f:
                    self.loaded_profiles = json.load(f)
                    names = [p['name'] for p in self.loaded_profiles]
                    self.profile_names = names
                    # FIX: Removed the automatic Clock.schedule here. 
                    # We will handle selection in on_pre_enter to avoid overwriting saved data.
                    print(f"[WaterScreen] Loaded {len(names)} profiles.")
            else:
                self.profile_names = ["Default"]
        except Exception as e:
            print(f"[WaterScreen] CRITICAL ERROR loading profiles: {e}")
            self.profile_names = ["Default"]

    def load_target_profile(self, name):
        # --- FIX 1: Check for Ignore Flag ---
        # If we are programmatically restoring the name, do not load values.
        if getattr(self, '_ignore_spinner_load', False):
            return

        # --- FIX 2: Existing Asterisk Check ---
        if " *" in name:
            return
            
        clean_name = name
        
        found_profile = None
        for p in self.loaded_profiles:
            if p['name'] == clean_name:
                found_profile = p
                break
        
        if not found_profile:
            return

        # 2. Load the values (This is what was overwriting your saved salts)
        self.tgt_ca = int(found_profile.get('ca', 0))
        self.tgt_mg = int(found_profile.get('mg', 0))
        self.tgt_na = int(found_profile.get('na', 0))
        self.tgt_so4 = int(found_profile.get('so4', 0))
        self.tgt_cl = int(found_profile.get('cl', 0))
        
        # 3. Store "Clean" state for comparison
        self.last_loaded_profile_data = {
            'ca': self.tgt_ca,
            'mg': self.tgt_mg,
            'na': self.tgt_na,
            'so4': self.tgt_so4,
            'cl': self.tgt_cl
        }
        self.current_profile_clean_name = clean_name

        # 4. Reset UI Visuals
        if self.ids.profile_spinner.text != clean_name:
            self.ids.profile_spinner.text = clean_name
            
        self.profile_text_color = [1, 1, 1, 1] 
        self.calculate_all()

    def check_profile_match(self):
        """Called during calculate_all to see if we drifted from the profile."""
        if not self.last_loaded_profile_data or not self.current_profile_clean_name:
            return

        current_data = {
            'ca': int(self.tgt_ca),
            'mg': int(self.tgt_mg),
            'na': int(self.tgt_na),
            'so4': int(self.tgt_so4),
            'cl': int(self.tgt_cl)
        }

        if current_data == self.last_loaded_profile_data:
            # MATCH: Restore clean look
            if self.ids.profile_spinner.text != self.current_profile_clean_name:
                self.ids.profile_spinner.text = self.current_profile_clean_name
                self.profile_text_color = [1, 1, 1, 1]
        else:
            # MISMATCH: Gray out and add asterisk
            dirty_name = f"{self.current_profile_clean_name} *"
            if self.ids.profile_spinner.text != dirty_name:
                self.ids.profile_spinner.text = dirty_name
                self.profile_text_color = [0.6, 0.6, 0.6, 1] # Gray

    def calculate_all(self):
        res_w = BrewMath.calculate_water(
            self.grain_wt, self.grain_temp, self.mash_temp, 
            self.ferm_vol, self.trub_vol, self.boil_time, 
            self.boiloff, self.abs_rate, self.mash_method, 
            self.thickness, self.is_metric
        )
        
        u_vol = "L" if self.is_metric else "gal"
        u_temp = "C" if self.is_metric else "F"

        self.strike_vol = f"{res_w['strike_vol']:.2f} {u_vol}"
        self.sparge_vol = f"{res_w['sparge_vol']:.2f} {u_vol}"
        self.strike_temp = f"{res_w['strike_temp']:.0f} {u_temp}"
        self.pre_boil_vol = f"{res_w['pre_boil_vol']:.2f} {u_vol}"
        self.total_mash_vol = f"{res_w['total_mash_vol']:.2f} {u_vol}"
        self.total_water = res_w['total_water']
        
        # --- NEW RESULTS LOGIC ---
        total_mash_f = res_w['total_mash_vol']
        total_water_f = res_w['total_water']
        strike_f = res_w['strike_vol']
        sparge_f = res_w['sparge_vol']
        pre_boil_f = res_w['pre_boil_vol']
        strike_temp_f = res_w['strike_temp']
        
        # 1. Set Aside
        if total_mash_f > self.tun_capacity:
            set_aside_f = total_mash_f - self.tun_capacity
        else:
            set_aside_f = 0.0
            
        # 2. Dough-in
        if sparge_f > 0:
            dough_in_f = strike_f
        else:
            dough_in_f = total_water_f - set_aside_f
            
        # 3. Mash
        if sparge_f > 0:
            mash_f = total_mash_f
        else:
            mash_f = total_mash_f - set_aside_f
            
        # 4. Strings
        self.res_total_disp = f"{total_water_f:.2f} {u_vol}"
        self.res_set_aside = f"{set_aside_f:.2f} {u_vol}"
        self.res_dough_in = f"{dough_in_f:.2f} {u_vol}"
        self.res_mash = f"{mash_f:.2f} {u_vol}"
        
        # 5. STORE RAW VALUES (For Profile Population)
        self.raw_total_water = total_water_f
        self.raw_dough_in_vol = dough_in_f
        self.raw_mash_vol = mash_f
        self.raw_pre_boil_vol = pre_boil_f
        self.raw_strike_temp = strike_temp_f
        # -------------------------
        
        res_c = BrewMath.calculate_chemistry(
            self.total_water, self.srm, self.target_ph, self.grain_wt,
            self.tgt_ca, self.tgt_mg, self.tgt_na, self.tgt_so4, self.tgt_cl, 
            self.is_metric
        )
        
        self.res_gypsum = f"{res_c['gypsum']:.2f} g"
        self.res_cacl2 = f"{res_c['cacl2']:.2f} g"
        self.res_epsom = f"{res_c['epsom']:.2f} g"
        self.res_salt = f"{res_c['salt']:.2f} g"
        self.res_lime = f"{res_c['lime']:.2f} g"
        self.res_acid = f"{res_c['acid']:.1f} ml"
        self.res_acid_g = f"{res_c['acid_g']:.2f} g"
        
        self.check_profile_match()
        
    def save_results_to_profile(self):
        """
        Populates the current profile steps with calculated water/temp values.
        Handles unit conversion (Metric -> Imperial) before saving.
        """
        # FIX: Get reference to the running App instance explicitly
        app = App.get_running_app()
        
        if not app.sequencer.current_profile:
            print("[WaterScreen] No current profile to update.")
            self.save_and_exit()
            return

        # Helper: Convert to System Units (Gallons/Fahrenheit)
        def to_sys_vol(val):
            return val / 3.78541 if self.is_metric else val

        def to_sys_temp(val):
            return (val * 9/5) + 32 if self.is_metric else val
            
        # 1. Prepare converted values
        val_total = to_sys_vol(self.raw_total_water)
        val_dough_in = to_sys_vol(self.raw_dough_in_vol)
        val_mash = to_sys_vol(self.raw_mash_vol)
        val_pre_boil = to_sys_vol(self.raw_pre_boil_vol)
        val_chill = to_sys_vol(self.ferm_vol + self.trub_vol) # Using Inputs
        
        temp_strike = to_sys_temp(self.raw_strike_temp)
        temp_mash = to_sys_temp(self.mash_temp) # Using Input
        
        # 2. Iterate and Update
        steps_updated = 0
        for step in app.sequencer.current_profile.steps:
            st = step.step_type
            
            # -- MAPPING LOGIC (Updated to use correct BrewStep attributes) --
            if st == StepType.PREP_WATER:
                step.lauter_volume = val_total
                steps_updated += 1
                
            elif st == StepType.DOUGH_IN:
                step.lauter_volume = val_dough_in
                step.setpoint_f = temp_strike
                steps_updated += 1
                
            elif st == StepType.MASH:
                step.lauter_volume = val_mash
                step.setpoint_f = temp_mash
                steps_updated += 1
                
            elif st == StepType.MASH_OUT:
                step.lauter_volume = val_pre_boil
                steps_updated += 1
                
            elif st == StepType.SPARGE:
                step.lauter_volume = val_pre_boil
                steps_updated += 1
                
            elif st == StepType.BOIL_START:
                step.lauter_volume = val_pre_boil
                steps_updated += 1
                
            elif st == StepType.BOIL: # Boil Off
                step.lauter_volume = val_pre_boil
                steps_updated += 1
                
            elif st == StepType.CHILL:
                step.lauter_volume = val_chill
                steps_updated += 1

        print(f"[WaterScreen] Updated {steps_updated} steps with new water results.")
        
        # 3. Save to Disk
        # FIX: Correct method is save_profile(profile_object)
        app.sequencer.settings.save_profile(app.sequencer.current_profile)
        
        # 4. Exit
        self.save_and_exit()
        
        
if __name__ == '__main__':
    KettleApp().run()
