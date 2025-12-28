import os
import sys

# --- 1. OS ENVIRONMENT SETUP ---
# This tells the OS: "My Window ID is 'WaterBrain', not 'python'"
os.environ['SDL_VIDEO_X11_WMCLASS'] = "WaterBrain"
os.environ['KIVY_BCM_DISPMANX_ID'] = '2'

# --- 2. Import Config first ---
from kivy.config import Config

# --- 3. Calculate the path immediately (Exact match to main.py logic) ---
current_dir = os.path.dirname(os.path.abspath(__file__))
icon_path = os.path.join(current_dir, 'assets', 'water-drop.png')

# --- 4. Set the icon in Kivy's global configuration ---
Config.set('kivy', 'window_icon', icon_path)
Config.set('input', 'mouse', 'mouse,multitouch_on_demand')

# --- 5. Graphics Settings ---
Config.set('graphics', 'width', '800')
Config.set('graphics', 'height', '410')
Config.set('graphics', 'resizable', '0')
Config.set('graphics', 'position', 'custom')
Config.set('graphics', 'top', '50')
Config.set('graphics', 'left', '0')

# --- 6. Regular Kivy Imports ---
from kivy.app import App
from kivy.uix.screenmanager import ScreenManager
from water_ui import WaterCalculatorScreen

class WaterBrainApp(App):
    def build(self):
        self.title = "WaterBrain"
        # Note: We rely on Config.set('window_icon') above, just like KettleBrain.
        # We do NOT set self.icon here to avoid path conflicts.
        
        sm = ScreenManager()
        sm.add_widget(WaterCalculatorScreen(name='water_calc'))
        return sm

if __name__ == '__main__':
    WaterBrainApp().run()
