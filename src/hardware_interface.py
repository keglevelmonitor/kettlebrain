"""
src/hardware_interface.py
Handles sensor readings and the "Developer Mode" simulation logic.
"""
import random

class HardwareInterface:
    def __init__(self, settings_mgr):
        self.settings = settings_mgr
        
        # --- DEV MODE STATE ---
        self._dev_mode_active = False
        self._virtual_temp = 70.0  # Start simulation at room temp
        
    # --- DEV MODE CONTROLS ---
    def set_dev_mode(self, enabled: bool):
        self._dev_mode_active = enabled
        print(f"[HARDWARE] Developer Simulation Mode: {'ON' if enabled else 'OFF'}")

    def is_dev_mode(self):
        return self._dev_mode_active

    def set_virtual_temp(self, temp_f):
        """Called by the UI Slider in Dev Mode"""
        if self._dev_mode_active:
            self._virtual_temp = float(temp_f)

    # --- SENSOR INTERFACE ---
    def read_temperature(self):
        """
        Returns the temperature from either the Virtual Slider (Dev Mode)
        or the Real Hardware Probe (Live Mode).
        """
        if self._dev_mode_active:
            return self._virtual_temp
        else:
            return self._read_physical_sensor()

    def _read_physical_sensor(self):
        """
        REAL HARDWARE IMPLEMENTATION HERE.
        Connect to your MAX31865 / DS18B20 libraries here.
        """
        try:
            # Example placeholder:
            # return self.pt100.temperature
            return 0.0 
        except Exception as e:
            print(f"[SENSOR ERROR] {e}")
            return 0.0
