import os
import sys

# 1. Import Config BEFORE other Kivy imports
from kivy.config import Config

# 2. Match KettleBrain Settings (800x410 positioned at 0,50)
Config.set('graphics', 'width', '800')
Config.set('graphics', 'height', '410')  # <--- Adjusted height
Config.set('graphics', 'resizable', '0')
Config.set('graphics', 'position', 'custom')
Config.set('graphics', 'top', '50')      # <--- Push down below Pi Taskbar
Config.set('graphics', 'left', '0')

from kivy.app import App
from kivy.uix.screenmanager import ScreenManager
from water_ui import WaterCalculatorScreen

class WaterBrainApp(App):
    def build(self):
        self.title = "WaterBrain"
        sm = ScreenManager()
        # Add the screen we built in water_ui.py
        sm.add_widget(WaterCalculatorScreen(name='water_calc'))
        return sm

if __name__ == '__main__':
    WaterBrainApp().run()
