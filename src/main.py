import os
import uuid
import copy
import subprocess
import sys
import threading
import signal  # <--- NEW IMPORT
from datetime import datetime, timedelta
from sequence_manager import SequenceStatus
import atexit

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
Config.set('graphics', 'height', '410')
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
            # We avoid using __file__ here as it may be undefined during exit
            from relay_control import RelayControl
            from settings_manager import SettingsManager
            
            # Use current working directory logic to find config
            root_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
            if os.path.basename(root_dir) == 'src':
                root_dir = os.path.dirname(root_dir)
            
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

# --- MANUAL CLASS DEFINITIONS (To fix import errors) ---
class ProfileAddition:
    def __init__(self, name="New Alert", time_point_min=0.0):
        self.id = str(uuid.uuid4())
        self.name = name
        self.time_point_min = time_point_min
        self.triggered = False

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "time_point_min": float(self.time_point_min),
            "triggered": self.triggered
        }

class ProfileStep:
    def __init__(self, name="New Step", setpoint_f=150.0, duration_min=60):
        self.name = name
        self.setpoint_f = setpoint_f
        self.duration_min = duration_min
        self.additions = [] 

    def to_dict(self):
        # Handle additions safely
        adds_data = []
        for a in self.additions:
            if hasattr(a, 'to_dict'):
                adds_data.append(a.to_dict())
            else:
                # Fallback for existing additions loaded from backend objects
                adds_data.append({
                    "id": getattr(a, 'id', str(uuid.uuid4())),
                    "name": getattr(a, 'name', "Unknown"),
                    "time_point_min": float(getattr(a, 'time_point_min', 0)),
                    "triggered": False
                })
                
        return {
            "name": self.name,
            "setpoint_f": float(self.setpoint_f),
            "duration_min": float(self.duration_min),
            "additions": adds_data
        }

# --- KIVY WIDGET CLASSES ---
class StepItem(BoxLayout):
    step_index = StringProperty("")
    step_name = StringProperty("")
    step_target = StringProperty("")
    step_duration = StringProperty("")
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

# --- HELPER: Single Row for an Alert ---
class AlertRow(BoxLayout):
    def __init__(self, addition_obj, remove_callback, **kwargs):
        super().__init__(**kwargs)
        self.addition = addition_obj
        self.orientation = 'horizontal'
        self.size_hint_y = None
        self.height = dp(40)
        self.spacing = dp(5)

        # Name Input
        self.txt_name = TextInput(text=addition_obj.name, multiline=False, size_hint_x=0.6)
        self.txt_name.bind(text=self.on_name_change)
        self.add_widget(self.txt_name)

        # Time Input
        self.txt_time = TextInput(text=str(addition_obj.time_point_min), multiline=False, size_hint_x=0.25, input_filter='float')
        self.txt_time.bind(text=self.on_time_change)
        self.add_widget(self.txt_time)
        
        self.add_widget(Label(text="m", size_hint_x=None, width=dp(20)))

        # Remove Button
        btn_remove = Button(text="X", size_hint_x=None, width=dp(40), background_color=(1, 0, 0, 1))
        btn_remove.bind(on_release=lambda x: remove_callback(self))
        self.add_widget(btn_remove)

    def on_name_change(self, instance, value):
        self.addition.name = value

    def on_time_change(self, instance, value):
        if value:
            try: self.addition.time_point_min = float(value)
            except: pass


# --- 1. Define the Alert Row Item ---
class AlertItem(BoxLayout):
    name = StringProperty("")
    time = NumericProperty(0)
    # Event to tell the parent to remove this item
    def on_remove(self):
        # This will be bound in KV or Python
        pass

# --- 2. Define the Full Screen Editor ---
class StepEditorScreen(Screen):
    # Kivy Properties
    step_index = NumericProperty(-1)
    step_name = StringProperty("New Step")
    step_temp = NumericProperty(150.0)
    step_dur = NumericProperty(60.0)
    
    # Alert Input
    new_alert_name = StringProperty("Hops")
    new_alert_time = NumericProperty(10.0)
    
    # Data List for RecycleView
    current_additions = ListProperty([])

    # Internal reference
    step_obj_ref = None

    def load_step(self, step_obj, index):
        self.step_obj_ref = step_obj
        self.step_index = index
        self.step_name = step_obj.name
        self.step_temp = float(step_obj.setpoint_f) if step_obj.setpoint_f else 0.0
        self.step_dur = float(step_obj.duration_min) if step_obj.duration_min else 0.0
        
        # Load Alerts
        temp_list = []
        if hasattr(step_obj, 'additions'):
            for a in step_obj.additions:
                if isinstance(a, dict):
                    n = a.get('name', 'Alert')
                    t = a.get('time_point_min', 0)
                else:
                    n = getattr(a, 'name', 'Alert')
                    t = getattr(a, 'time_point_min', 0)
                temp_list.append({'name': n, 'time': t})
        self.current_additions = temp_list

    def add_alert(self):
        if not self.new_alert_name: return
        self.current_additions.append({
            'name': self.new_alert_name,
            'time': float(self.new_alert_time)
        })
        self.new_alert_name = "Hops"

    def remove_alert_by_index(self, index):
        if 0 <= index < len(self.current_additions):
            self.current_additions.pop(index)

    def save_step(self):
        if self.step_obj_ref:
            self.step_obj_ref.name = self.step_name
            self.step_obj_ref.setpoint_f = self.step_temp
            self.step_obj_ref.duration_min = self.step_dur
            
            # Rebuild Additions objects
            new_list = []
            for item in self.current_additions:
                new_list.append(ProfileAddition(item['name'], item['time']))
            self.step_obj_ref.additions = new_list

        # Refresh the Profile Editor List
        app = App.get_running_app()
        app.editor_screen.refresh_steps()
        
        # Go back to the Profile Editor
        app.root.current = 'editor'

    def cancel(self):
        # Just go back without saving
        App.get_running_app().root.current = 'editor'

class ProfileEditorScreen(Screen):
    temp_name = StringProperty("")
    editing_profile = ObjectProperty(None) 

    def load_data(self, profile):
        self.editing_profile = copy.deepcopy(profile)
        self.temp_name = self.editing_profile.name
        self.refresh_steps()

    def refresh_steps(self):
        data = []
        if self.editing_profile:
            for i, step in enumerate(self.editing_profile.steps):
                t = getattr(step, 'setpoint_f', 0)
                d = getattr(step, 'duration_min', 0)
                adds_count = len(step.additions) if hasattr(step, 'additions') else 0
                
                desc = f"{int(t)}F / {int(d)}m"
                if adds_count > 0:
                    desc += f" ({adds_count} alerts)"
                
                data.append({
                    'step_index': i + 1,
                    'step_name': step.name,
                    'step_desc': desc
                })
        self.ids.rv_editor_steps.data = data

    def add_new_step(self):
        new_step = ProfileStep(name="New Step", setpoint_f=150, duration_min=60)
        self.editing_profile.steps.append(new_step)
        self.refresh_steps()

    def save_profile(self):
        app = App.get_running_app()
        self.editing_profile.name = self.temp_name
        app.settings_manager.save_profile(self.editing_profile)
        app.open_profiles()

    def cancel_edit(self):
        App.get_running_app().open_profiles()

# ~ class DelayedStartPopup(Popup):
    # ~ # Dropdown Data
    # ~ hour_values = ListProperty([str(i) for i in range(1, 13)])
    # ~ min_values = ListProperty([f"{i:02d}" for i in range(0, 60)])
    # ~ ampm_values = ListProperty(["AM", "PM"])
    
    # ~ # Selected Values
    # ~ sel_hour = StringProperty("6")
    # ~ sel_min = StringProperty("00")
    # ~ sel_ampm = StringProperty("AM")
    
    # ~ # Target Values
    # ~ target_temp = NumericProperty(154.0)
    # ~ target_vol = NumericProperty(8.0)
    
    # ~ def __init__(self, **kwargs):
        # ~ super().__init__(**kwargs)
        # ~ self.app = App.get_running_app()
        # ~ self._load_defaults()
        
    # ~ def _load_defaults(self):
        # ~ # 1. Calculate Default Time (6:00 AM tomorrow if passed)
        # ~ now = datetime.now()
        # ~ next_target = now.replace(hour=6, minute=0, second=0, microsecond=0)
        # ~ if next_target <= now:
            # ~ next_target += timedelta(days=1)
            
        # ~ self.sel_hour = next_target.strftime("%I").lstrip('0')
        # ~ self.sel_min = next_target.strftime("%M")
        # ~ self.sel_ampm = next_target.strftime("%p")
        
        # ~ # 2. Load Last Used Settings
        # ~ sm = self.app.settings_manager
        # ~ self.target_temp = sm.get("manual_mode_settings", "last_setpoint_f", 154.0)
        # ~ self.target_vol = sm.get("manual_mode_settings", "last_volume_gal", 8.0)

    # ~ def activate_delay(self):
        # ~ try:
            # ~ # 1. Parse Time
            # ~ h = int(self.sel_hour)
            # ~ m = int(self.sel_min)
            # ~ is_pm = (self.sel_ampm == "PM")
            
            # ~ # Convert 12h -> 24h
            # ~ if is_pm and h != 12: h += 12
            # ~ if not is_pm and h == 12: h = 0
            
            # ~ now = datetime.now()
            # ~ target_dt = now.replace(hour=h, minute=m, second=0, microsecond=0)
            
            # ~ # If time is in past, assume tomorrow
            # ~ if target_dt <= now:
                # ~ target_dt += timedelta(days=1)
                
            # ~ # 2. Determine Context (Were we in Auto or Manual?)
            # ~ # If we are currently in Manual, we want to return to Manual if canceled.
            # ~ is_auto = (self.app.sequencer.status != SequenceStatus.MANUAL)
            
            # ~ # 3. Call Backend
            # ~ self.app.sequencer.start_delayed_mode(
                # ~ self.target_temp, 
                # ~ self.target_vol, 
                # ~ target_dt, 
                # ~ from_auto_mode=is_auto
            # ~ )
            
            # ~ # 4. Update UI
            # ~ if self.app.sequencer.status == SequenceStatus.DELAYED_WAIT:
                # ~ # Force MainScreen update
                # ~ self.app.root.get_screen('main').update_status_display()
                # ~ self.dismiss()
            # ~ else:
                # ~ print("Error: Sequencer refused Delayed Mode")
                
        # ~ except Exception as e:
            # ~ print(f"Delay Activation Error: {e}")

# ~ class DelayedStartActionPopup(Popup):
    # ~ def do_cancel(self):
        # ~ app = App.get_running_app()
        # ~ app.sequencer.cancel_delayed_mode()
        # ~ app.root.get_screen('main').update_status_display()
        # ~ self.dismiss()

class MainScreen(Screen):
    display_temp = StringProperty("--.- °F")
    display_target = StringProperty("--")
    display_status = StringProperty("System Idle")
    display_timer = StringProperty("00:00")
    display_elapsed = StringProperty("00:00")
    display_power_watts = StringProperty("1800")
    action_button_text = StringProperty("START")
    temp_color = ListProperty([0.2, 0.8, 0.2, 1])
    
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
    
    # Visual properties
    controls_disabled = BooleanProperty(False)
    heater_1_active = BooleanProperty(False) # 1000W
    heater_2_active = BooleanProperty(False) # 800W
    is_delay_active = BooleanProperty(False)
    heartbeat_color = ListProperty([0.2, 0.2, 0.2, 1]) # Grey default
    
    action_button_text = StringProperty("START")
    action_button_color = ListProperty([0.2, 0.4, 0.8, 1]) # <--- ADD THIS
    
    # Manual Mode Properties
    slider_temp_val = NumericProperty(150.0)
    slider_vol_val = NumericProperty(6.0)
    slider_time_val = NumericProperty(60.0)
    slider_power_val = NumericProperty(3) # Index 0-3

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.app = App.get_running_app()
        self.last_profile_id = None
        self.last_step_index = -1
        self.watts_map = [800, 1000, 1400, 1800] 

    def on_enter(self):
        """Syncs UI with saved settings."""
        self._load_manual_settings()

    def _load_manual_settings(self):
        sm = self.app.settings_manager
        
        last_temp = sm.get("manual_mode_settings", "last_setpoint_f", 150.0)
        last_timer = sm.get("manual_mode_settings", "last_timer_min", 60.0)
        last_vol = sm.get("manual_mode_settings", "last_volume_gal", 6.0)
        last_watts = sm.get("manual_mode_settings", "last_power_watts", 1800)

        self.slider_temp_val = last_temp
        self.slider_time_val = last_timer
        self.slider_vol_val = last_vol
        try:
            self.slider_power_val = self.watts_map.index(last_watts)
        except ValueError:
            self.slider_power_val = 3
        
        self.display_power_watts = str(last_watts)
        self._update_prediction()

    def on_slider_drag(self, slider_type, value):
        """Updates VISUALS (labels/prediction) immediately."""
        if slider_type == 'temp': 
            self.slider_temp_val = float(value)
        elif slider_type == 'vol': 
            self.slider_vol_val = float(value)
        elif slider_type == 'time': 
            self.slider_time_val = float(value)
        elif slider_type == 'power': 
            self.slider_power_val = int(value)
            idx = int(value)
            if 0 <= idx < len(self.watts_map):
                self.display_power_watts = str(self.watts_map[idx])
        
        self._update_prediction()

    def on_slider_release(self, slider_type, value):
        """Saves to backend/disk on release."""
        self.on_slider_drag(slider_type, value) # Sync
        seq = self.app.sequencer
        
        if slider_type == 'temp':
            seq.set_manual_target(float(value))
        elif slider_type == 'vol':
            seq.set_manual_volume(float(value))
        elif slider_type == 'time':
            seq.set_manual_timer_duration(float(value))
        elif slider_type == 'power':
            idx = int(value)
            if 0 <= idx < len(self.watts_map):
                w = self.watts_map[idx]
                seq.set_manual_power(w)
                
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

    def switch_to_manual(self):
        """
        Request to switch to Manual Mode. 
        If Auto is currently running/paused, ask for confirmation.
        """
        seq = self.app.sequencer
        
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

    def confirm_mode_switch(self):
        """Executed when user clicks RESET SESSION."""
        # 1. Hard Stop the current session
        self.app.sequencer.stop()
        
        # 2. Perform the switch based on target
        if self.mode_switch_target == 'manual':
            self.ids.center_content.current = 'page_manual'
            self.app.sequencer.enter_manual_mode()
            
        elif self.mode_switch_target == 'auto':
            self.ids.center_content.current = 'page_auto'
            # seq.stop() already put us in IDLE, which is correct for Auto start
            
        # 3. Restore Bottom Nav
        self.ids.bottom_nav.transition.direction = 'down'
        self.ids.bottom_nav.current = 'nav_standard'

    def cancel_mode_switch(self):
        """Executed when user clicks CANCEL."""
        self.ids.bottom_nav.transition.direction = 'down'
        self.ids.bottom_nav.current = 'nav_standard'
    
    def on_action_click(self):
        seq = self.app.sequencer
        status = seq.status
        current_screen = self.ids.center_content.current

        # --- MANUAL MODE LOGIC ---
        if current_screen == 'page_manual' or status == SequenceStatus.MANUAL:
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
            # If we were in Auto, this Resets the sequencer to IDLE (which defaults to Auto view)
            self.app.sequencer.stop()

        # 3. Restore Bottom Navigation
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

    def refresh_step_list(self):
        seq = self.app.sequencer
        if not seq.current_profile:
            self.ids.rv_steps.data = []
            return
        data = []
        current_idx = seq.current_step_index
        for i, step in enumerate(seq.current_profile.steps):
            is_active = (i == current_idx)
            is_done = (i < current_idx)
            bg = [0.2, 0.2, 0.2, 1]
            txt = [1, 1, 1, 1]
            if is_active: bg = [0.2, 0.6, 0.3, 1]
            elif is_done: txt = [0.5, 0.5, 0.5, 1]
            t_str = f"{step.setpoint_f}°F" if step.setpoint_f else "--"
            d_str = f"{step.duration_min} min" if step.duration_min > 0 else "--"
            data.append({
                'step_index': str(i + 1),
                'step_name': step.name,
                'step_target': t_str,
                'step_duration': d_str,
                'bg_color': bg,
                'text_color': txt
            })
        self.ids.rv_steps.data = data
        
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

    def open_delay_setup(self):
        """Called when DELAY START (or ACTIVE) is clicked."""
        status = self.app.sequencer.status
        
        # 1. Load Defaults
        now = datetime.now()
        
        # Determine defaults (Next morning 6am or Current settings)
        if status == SequenceStatus.DELAYED_WAIT:
            # If active, we theoretically should pull from sequencer, 
            # but for now we rely on the properties being persistent.
            pass 
        else:
            # Default target: 6:00 AM tomorrow
            next_target = now.replace(hour=6, minute=0, second=0, microsecond=0)
            if next_target <= now:
                next_target += timedelta(days=1)
            
            # Convert target hour/min to total minutes for the slider
            self.delay_minutes_total = (next_target.hour * 60) + next_target.minute
            
            # Load last manual settings for Temp/Vol
            sm = self.app.settings_manager
            self.delay_temp = sm.get("manual_mode_settings", "last_setpoint_f", 154.0)
            self.delay_vol = sm.get("manual_mode_settings", "last_volume_gal", 8.0)

        # 2. Slide the Hero Panel
        self.ids.hero_manager.transition.direction = 'left'
        self.ids.hero_manager.current = 'hero_delay'

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
            
            # 2. Context (Auto vs Manual)
            is_auto = (self.app.sequencer.status != SequenceStatus.MANUAL)
            
            # 3. Call Sequencer
            self.app.sequencer.start_delayed_mode(
                self.delay_temp, 
                self.delay_vol, 
                target_dt, 
                from_auto_mode=is_auto
            )
            
            # 4. MIRROR SETTINGS TO MANUAL UI (Visual confirmation)
            self.slider_temp_val = self.delay_temp
            self.slider_vol_val = self.delay_vol
            
            # --- FIXED: Update Timer & Power Sliders too ---
            self.slider_time_val = 30.0  # Match backend default (30 min)
            self.slider_power_val = 3    # Match backend default (1800W - Index 3)
            
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
    
    # ~ # DELETE THIS FUNCTION?
    # ~ def open_delay_start(self):
        # ~ """Called by the DELAY START button."""
        # ~ status = self.app.sequencer.status
        
        # ~ # 1. If already delayed, show management options
        # ~ if status == SequenceStatus.DELAYED_WAIT:
            # ~ p = DelayedStartActionPopup()
            # ~ p.open()
            # ~ return

        # ~ # 2. If running (Heating), prevent changes
        # ~ if status not in [SequenceStatus.IDLE, SequenceStatus.MANUAL]:
            # ~ # You might want a simple alert popup here, printing for now
            # ~ print("Cannot start delay while system is running.")
            # ~ return

        # ~ # 3. Open Setup Popup
        # ~ p = DelayedStartPopup()
        # ~ p.open()

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
        
        # 1. LOAD BOIL TEMP
        self.boil_temp = sm.get_system_setting("boil_temp_f", 212)

        # 2. LOAD SENSORS
        raw_sensors = hw.scan_available_sensors()
        self.sensor_list = ["unassigned"] + raw_sensors
        current_sensor = sm.get_system_setting("temp_sensor_id", "unassigned")
        # Ensure current is valid
        if current_sensor not in self.sensor_list:
            self.sensor_list.append(current_sensor)
        self.ids.spinner_sensor.text = current_sensor

        # 3. LOAD AUDIO DEVICES
        # hw.scan_audio_devices() returns list of (friendly, dev_str)
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
        # Use static list from legacy code 
        self.sound_list = [
            "alert.wav", "alt1_ding.wav", "alt2_buzzer.wav", 
            "alt2_ding.wav", "bell_ding.wav", "doorbell.wav", 
            "highbell.wav", "sports_buzzer.wav", "store_ding.wav"
        ]
        current_sound = sm.get_system_setting("alert_sound_file", "alert.wav")
        self.ids.spinner_sound.text = current_sound

        # 5. LOAD VOLUME (Mock or generic default as we can't easily read amixer)
        self.system_volume = 80 

    def save_changes(self):
        """Write values to SettingsManager."""
        sm = self.app.settings_manager
        
        # Boil Temp
        sm.set_system_setting("boil_temp_f", int(self.boil_temp))
        
        # Sensor
        sm.set_system_setting("temp_sensor_id", self.ids.spinner_sensor.text)
        
        # Audio Device (Map friendly name back to device string)
        selected_friendly = self.ids.spinner_audio.text
        dev_str = self.audio_map.get(selected_friendly, "default")
        sm.set_system_setting("audio_device", dev_str)
        
        # Sound File
        sm.set_system_setting("alert_sound_file", self.ids.spinner_sound.text)
        
        print("[HardwareSettings] Saved.")
        self.go_back()

    def test_audio(self):
        """Play the selected sound on the selected device."""
        import os
        selected_sound = self.ids.spinner_sound.text
        selected_friendly = self.ids.spinner_audio.text
        dev_str = self.audio_map.get(selected_friendly, "default")
        
        # Logic adapted from settings_ui.py 
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
        # Logic adapted from settings_ui.py 
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
        
        # 1. Save Units
        val_unit = self.UNIT_MAP.get(self.units_text, "imperial")
        sm.set_system_setting("units", val_unit)
        
        # 2. Save Booleans
        sm.set_system_setting("auto_start_enabled", self.auto_start)
        sm.set_system_setting("auto_resume_enabled", self.auto_resume)
        sm.set_system_setting("force_numlock", self.force_numlock)
        sm.set_system_setting("enable_csv_logging", self.csv_logging)
        
        # 3. Manage Auto-Start File (Ported logic)
        self._manage_autostart_file(self.auto_start)
        
        print("[AppSettings] Saved.")
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
        """Refresh current calibration display."""
        sm = self.app.settings_manager
        
        # Logic from settings_ui.py 
        raw_f = sm.get_system_setting("heater_ref_rate_fpm", 1.2)
        
        # Display current setting
        self.current_factor_text = f"{raw_f:.2f} °F/min (Ref: 8 Gal)"
        self.calc_result_text = "--"
        self.new_calculated_factor = None
        self.ids.btn_update.disabled = True

    def calculate_efficiency(self):
        """Math logic ported from settings_ui.py ."""
        try:
            vol = float(self.cal_vol)
            start_t = float(self.cal_start_temp)
            end_t = float(self.cal_end_temp)
            mins = float(self.cal_time)

            if mins <= 0: return

            # Calculate Rate
            delta_temp = end_t - start_t
            if delta_temp <= 0: return
            
            actual_rate_fpm = delta_temp / mins
            
            # Normalize to Reference Volume (8.0 Gal)
            # Formula: rate * (actual_vol / ref_vol)
            ref_vol = self.app.settings_manager.get_system_setting("heater_ref_volume_gal", 8.0)
            normalized_rate_fpm = actual_rate_fpm * (vol / ref_vol)
            
            self.new_calculated_factor = normalized_rate_fpm
            self.calc_result_text = f"{normalized_rate_fpm:.2f} °F/min"
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
      
        
        

class KettleApp(App):
    
    fonts_loaded = BooleanProperty(False)
    
    def build(self):
        # ... (Existing Path Logic) ...
        src_dir = os.path.dirname(os.path.abspath(__file__))
        project_dir = os.path.dirname(src_dir)
        root_dir = os.path.dirname(project_dir)
        
        self.settings_manager = SettingsManager(root_dir)
        self.hw = HardwareInterface(self.settings_manager)
        
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
        
        # NEW SETTINGS SCREENS
        self.sys_settings_screen = SystemSettingsScreen(name='sys_settings')
        self.hw_settings_screen = HardwareSettingsScreen(name='settings_hw')
        self.app_settings_screen = AppSettingsScreen(name='settings_app')
        self.cal_settings_screen = CalibrationSettingsScreen(name='settings_cal')
        self.updates_screen = UpdatesSettingsScreen(name='settings_updates')
          
        sm.add_widget(self.main_screen)
        sm.add_widget(self.profiles_screen)
        sm.add_widget(self.editor_screen)
        sm.add_widget(self.step_editor_screen)
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
        
        # --- 1. TEMPERATURES & COLORS ---
        current_temp = seq.current_temp if seq.current_temp else 0.0
        screen.display_temp = f"{current_temp:.1f} °F"
        
        tgt = seq.get_target_temp()
        screen.display_target = f"{tgt:.0f} °F" if tgt else "--"
        
        if tgt:
            diff = current_temp - tgt
            if abs(diff) < 1.0: 
                screen.temp_color = [0.2, 0.8, 0.2, 1] # Green (Good)
            elif diff < 0: 
                screen.temp_color = [0.2, 0.4, 0.8, 1] # Blue (Heating)
            else: 
                screen.temp_color = [0.8, 0.2, 0.2, 1] # Red (Hot)
        else:
            screen.temp_color = [0.2, 0.8, 0.2, 1] 
            
        # --- 2. TIMERS ---
        screen.display_timer = seq.get_display_timer()
        screen.display_elapsed = seq.get_global_elapsed_time_str()

        # --- 3. HEARTBEAT PULSE ---
        import time
        now = time.time()
        
        if status == SequenceStatus.MANUAL and getattr(seq, 'is_manual_running', False):
            # RUNNING: Pulse Green
            if int(now * 2) % 2 == 0: screen.heartbeat_color = [0, 1, 0, 1] 
            else: screen.heartbeat_color = [0, 0.3, 0, 1]
        elif status == SequenceStatus.PAUSED:
            # PAUSED: Pulse Blue
            if int(now * 2) % 2 == 0: screen.heartbeat_color = [0.2, 0.4, 0.8, 1] 
            else: screen.heartbeat_color = [0.1, 0.2, 0.4, 1] 
        elif status == SequenceStatus.DELAYED_WAIT:
            # SLEEPING: Slow Pulse Teal
            if int(now) % 2 == 0: screen.heartbeat_color = [0.2, 0.6, 0.8, 1]
            else: screen.heartbeat_color = [0.1, 0.3, 0.4, 1]
        else:
            # IDLE: Grey
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
        
        # If Delay is active, override status text here
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
                # Use prediction logic
                if hasattr(screen, '_update_prediction'): 
                    screen._update_prediction()
        else:
            screen.display_status = sys_msg

        # --- 6. VIEW SWITCHING ---
        # Allow browsing in IDLE, but snap to Manual/Auto if running/sleeping
        if status == SequenceStatus.MANUAL:
            if screen.ids.center_content.current != 'page_manual': 
                screen.ids.center_content.current = 'page_manual'
                # Force prediction update
                if hasattr(screen, '_update_prediction'): screen._update_prediction()
        elif status == SequenceStatus.DELAYED_WAIT:
            if screen.ids.center_content.current != 'page_manual':
                screen.ids.center_content.current = 'page_manual'
        elif status in [SequenceStatus.RUNNING, SequenceStatus.PAUSED, SequenceStatus.WAITING_FOR_USER]:
            if screen.ids.center_content.current != 'page_auto': 
                screen.ids.center_content.current = 'page_auto'

        # --- 7. AUTO MODE LIST REFRESH ---
        current_id = seq.current_profile.id if seq.current_profile else None
        current_idx = seq.current_step_index
        if current_id != screen.last_profile_id or current_idx != screen.last_step_index:
            screen.refresh_step_list()
            screen.last_profile_id = current_id
            screen.last_step_index = current_idx

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
                screen.action_button_text = "ACKNOWLEDGE"
                screen.action_button_color = [0.8, 0.4, 0.2, 1]
        else: 
            screen.action_button_text = "START"
            screen.action_button_color = [0.2, 0.8, 0.4, 1]

        # --- 9. DELAYED START SYNC (Automatic Unlock) ---
        # This ensures that when the backend automatically transitions 
        # from DELAYED_WAIT -> MANUAL, the UI Unlocks immediately.
        if status == SequenceStatus.DELAYED_WAIT:
            # Lock UI
            screen.is_delay_active = True
            screen.controls_disabled = True
            screen.delay_btn_text = "DELAY ACTIVE"
            screen.delay_btn_color = [0.2, 0.6, 0.8, 1]
        else:
            # Unlock UI
            screen.is_delay_active = False
            screen.controls_disabled = False
            screen.delay_btn_text = "DELAY START"
            screen.delay_btn_color = [0.2, 0.2, 0.4, 1]

    def open_profile_options(self, profile_id, profile_name):
        popup = ProfileOptionsPopup()
        popup.profile_id = profile_id
        popup.profile_name = profile_name
        popup.open()

    def load_profile(self, profile_id):
        profile = self.settings_manager.get_profile_by_id(profile_id)
        if profile:
            self.sequencer.load_profile(profile)
            self.root.current = 'main'
            self.main_screen.ids.center_content.current = 'page_auto'

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

if __name__ == '__main__':
    KettleApp().run()
