"""
kettlebrain app
main.py
"""
import tkinter as tk
import sys
import os
import signal
import subprocess

# Ensure src is in path
sys.path.append(os.path.join(os.path.dirname(__file__), 'src'))

from settings_manager import SettingsManager
from relay_control import RelayControl
from sequence_manager import SequenceManager
from ui_manager import UIManager
from hardware_interface import HardwareInterface # <--- NEW IMPORT

# --- CONSTANTS ---
APP_NAME = "KettleBrain"
VERSION = "0.2.0-Dev"

# --- HARDWARE PIN MAP (BCM) ---
RELAY_PINS = {
    "Heater1": 17, # 1000W Element
    "Heater2": 27, # 800W Element
    "Aux": 22      # Optional Fan
}

class KettleBrainApp:
    def __init__(self):
        self.root = None
        self.relay_control = None
        
    def run(self):
        print(f"[{APP_NAME}] Starting v{VERSION}...")
        
        # 1. Initialize Settings
        self.settings_mgr = SettingsManager()
        
        # --- NUMLOCK ENFORCEMENT ---
        if self.settings_mgr.get("system_settings", "force_numlock", True):
            try:
                subprocess.run(["which", "numlockx"], check=True, stdout=subprocess.DEVNULL)
                subprocess.run(["numlockx", "on"])
                print(f"[{APP_NAME}] NumLock forced ON.")
            except:
                pass 
        
        # 2. Initialize Hardware Output (Relays)
        self.relay_control = RelayControl(self.settings_mgr, RELAY_PINS)

        # 3. Initialize Hardware Input (Sensors/Simulation) <--- NEW
        self.hw_interface = HardwareInterface(self.settings_mgr)
        
        # 4. Initialize The Engine (Sequencer)
        # We now pass the HW Interface so the sequencer can read temps (real or virtual)
        self.sequencer = SequenceManager(self.settings_mgr, self.relay_control, self.hw_interface)
        
        # 5. Initialize UI
        self.root = tk.Tk()
        # We pass the HW Interface so the UI can draw the Dev Mode sliders
        self.ui = UIManager(self.root, self.sequencer, self.hw_interface)
        
        # 6. Handle Shutdown Signals
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
        
        # 7. Start Main Loop
        try:
            self.root.mainloop()
        except KeyboardInterrupt:
            self.shutdown()
        finally:
            self.shutdown()

    def _signal_handler(self, sig, frame):
        print(f"\n[{APP_NAME}] Signal received. Shutting down...")
        self.shutdown()

    def shutdown(self):
        print(f"[{APP_NAME}] Performing Cleanup...")
        
        if hasattr(self, 'sequencer'):
            self.sequencer.stop()
            
        if hasattr(self, 'relay_control'):
            self.relay_control.cleanup_gpio()
            
        if self.root:
            try:
                self.root.destroy()
            except:
                pass
                
        print(f"[{APP_NAME}] Goodbye.")
        sys.exit(0)

if __name__ == "__main__":
    app = KettleBrainApp()
    app.run()
