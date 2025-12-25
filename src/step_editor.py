"""
step_editor_kivy.py
A Kivy ModalView for editing a BrewStep (Name, Temp, Duration, Alerts)
"""

from kivy.uix.modalview import ModalView
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.textinput import TextInput
from kivy.uix.slider import Slider
from kivy.uix.button import Button
from kivy.uix.scrollview import ScrollView
from kivy.metrics import dp
from kivy.properties import ObjectProperty, StringProperty, NumericProperty

# Assuming you have a basic data structure for Additions/Alerts
# If not, we use this simple one for the UI to work
class BrewAddition:
    def __init__(self, name="New Alert", time_point_min=0):
        self.name = name
        self.time_point_min = time_point_min

class AlertRow(BoxLayout):
    """A single row in the alerts list: [Name Input] [Time Input] [X Button]"""
    def __init__(self, addition_obj, remove_callback, **kwargs):
        super().__init__(**kwargs)
        self.addition = addition_obj
        self.orientation = 'horizontal'
        self.size_hint_y = None
        self.height = dp(50)
        self.spacing = dp(10)

        # Alert Name
        self.txt_name = TextInput(text=addition_obj.name, multiline=False, size_hint_x=0.6)
        self.txt_name.bind(text=self.on_name_change)
        self.add_widget(self.txt_name)

        # Alert Time
        self.txt_time = TextInput(text=str(addition_obj.time_point_min), multiline=False, size_hint_x=0.2, input_filter='float')
        self.txt_time.bind(text=self.on_time_change)
        self.add_widget(self.txt_time)
        
        self.add_widget(Label(text="min", size_hint_x=None, width=dp(40)))

        # Remove Button
        btn_remove = Button(text="X", size_hint_x=None, width=dp(50), background_color=(1, 0, 0, 1))
        btn_remove.bind(on_release=lambda x: remove_callback(self))
        self.add_widget(btn_remove)

    def on_name_change(self, instance, value):
        self.addition.name = value

    def on_time_change(self, instance, value):
        if value:
            try:
                self.addition.time_point_min = float(value)
            except ValueError: pass

class StepEditorPopup(ModalView):
    def __init__(self, step_obj, save_callback, **kwargs):
        super().__init__(**kwargs)
        self.size_hint = (0.9, 0.9)
        self.auto_dismiss = False
        self.step = step_obj
        self.save_callback = save_callback
        
        # Working copy of additions to allow "Cancel" to work properly
        # (If you don't have deepcopy imported, add 'import copy' at top)
        import copy
        self.temp_additions = [copy.deepcopy(a) for a in step_obj.additions] if hasattr(step_obj, 'additions') else []

        self._build_ui()

    def _build_ui(self):
        # MAIN LAYOUT
        self.main_layout = BoxLayout(orientation='vertical', padding=dp(20), spacing=dp(15))
        self.add_widget(self.main_layout)

        # HEADER
        header = Label(text=f"Edit Step: {self.step.name}", font_size=dp(24), size_hint_y=None, height=dp(40), bold=True)
        self.main_layout.add_widget(header)

        # --- FORM AREA (Name, Temp, Dur) ---
        form_grid = GridLayout(cols=2, spacing=dp(10), size_hint_y=None, height=dp(180))
        
        # 1. Step Name
        form_grid.add_widget(Label(text="Step Name:", halign="right", size_hint_x=0.3))
        self.input_name = TextInput(text=self.step.name, multiline=False)
        form_grid.add_widget(self.input_name)

        # 2. Target Temp
        form_grid.add_widget(Label(text="Temp (°F):", halign="right", size_hint_x=0.3))
        temp_box = BoxLayout()
        self.slider_temp = Slider(min=0, max=212, value=self.step.setpoint_f if self.step.setpoint_f else 0, step=1)
        self.label_temp_val = Label(text=f"{int(self.slider_temp.value)}", size_hint_x=None, width=dp(50))
        self.slider_temp.bind(value=lambda instance, val: setattr(self.label_temp_val, 'text', str(int(val))))
        temp_box.add_widget(self.slider_temp)
        temp_box.add_widget(self.label_temp_val)
        form_grid.add_widget(temp_box)

        # 3. Duration
        form_grid.add_widget(Label(text="Duration (m):", halign="right", size_hint_x=0.3))
        dur_box = BoxLayout()
        self.slider_dur = Slider(min=0, max=120, value=self.step.duration_min if self.step.duration_min else 0, step=1)
        self.label_dur_val = Label(text=f"{int(self.slider_dur.value)}", size_hint_x=None, width=dp(50))
        self.slider_dur.bind(value=lambda instance, val: setattr(self.label_dur_val, 'text', str(int(val))))
        dur_box.add_widget(self.slider_dur)
        dur_box.add_widget(self.label_dur_val)
        form_grid.add_widget(dur_box)

        self.main_layout.add_widget(form_grid)

        # --- ALERTS SECTION HEADER ---
        self.main_layout.add_widget(Label(text="Alerts & Additions", size_hint_y=None, height=dp(30), bold=True))

        # --- ALERTS LIST (Scrollable) ---
        self.scroll = ScrollView(size_hint=(1, 1)) # Takes remaining space
        self.alerts_container = BoxLayout(orientation='vertical', size_hint_y=None, spacing=dp(5))
        self.alerts_container.bind(minimum_height=self.alerts_container.setter('height'))
        self.scroll.add_widget(self.alerts_container)
        
        self.main_layout.add_widget(self.scroll)

        # Populate existing alerts
        self._refresh_alerts_list()

        # --- ADD ALERT BUTTON ---
        btn_add_alert = Button(text="+ Add Alert", size_hint_y=None, height=dp(50))
        btn_add_alert.bind(on_release=self._add_new_alert)
        self.main_layout.add_widget(btn_add_alert)

        # --- FOOTER (Save/Cancel) ---
        footer = BoxLayout(size_hint_y=None, height=dp(60), spacing=dp(20))
        
        btn_cancel = Button(text="Cancel", background_color=(0.5, 0.5, 0.5, 1))
        btn_cancel.bind(on_release=self.dismiss)
        
        btn_save = Button(text="Save Step", background_color=(0, 0.8, 0, 1))
        btn_save.bind(on_release=self._save_and_close)
        
        footer.add_widget(btn_cancel)
        footer.add_widget(btn_save)
        self.main_layout.add_widget(footer)

    def _refresh_alerts_list(self):
        self.alerts_container.clear_widgets()
        # Sort by time descending
        self.temp_additions.sort(key=lambda x: x.time_point_min, reverse=True)
        
        for add in self.temp_additions:
            row = AlertRow(add, self._remove_alert)
            self.alerts_container.add_widget(row)

    def _add_new_alert(self, instance):
        new_alert = BrewAddition(name="New Alert", time_point_min=5.0)
        self.temp_additions.append(new_alert)
        self._refresh_alerts_list()

    def _remove_alert(self, row_widget):
        if row_widget.addition in self.temp_additions:
            self.temp_additions.remove(row_widget.addition)
        self._refresh_alerts_list()

    def _save_and_close(self, instance):
        # 1. Update the Step Object
        self.step.name = self.input_name.text
        self.step.setpoint_f = self.slider_temp.value
        self.step.duration_min = self.slider_dur.value
        self.step.additions = self.temp_additions
        
        # 2. Trigger Callback
        if self.save_callback:
            self.save_callback()
            
        self.dismiss()
