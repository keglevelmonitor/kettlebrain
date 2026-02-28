"""
src/hardware_interface.py
Handles sensor readings and the "Developer Mode" simulation logic.
"""
import random
import os
import glob
import time
from collections import deque

class HardwareInterface:
    def __init__(self, settings_mgr):
        self.settings = settings_mgr
        
        # Load state from settings (Default to False)
        self._dev_mode_active = self.settings.get_system_setting("dev_mode", False)
        self._virtual_temp = 70.0  # Start simulation at room temp
        
        # SMOOTHING: Buffer for last 5 readings
        self._temp_buffer = deque(maxlen=5)
        
        if self._dev_mode_active:
            print("[HARDWARE] Developer Mode Active (Virtual Sensors).")

    # --- DEV MODE CONTROLS ---
    def set_dev_mode(self, enabled: bool):
        self._dev_mode_active = enabled
        self.settings.set_system_setting("dev_mode", enabled)
        print(f"[HARDWARE] Developer Simulation Mode: {'ON' if enabled else 'OFF'}")

    def is_dev_mode(self):
        return self._dev_mode_active

    def set_virtual_temp(self, temp_f):
        """Called by the UI Slider in Dev Mode"""
        if self._dev_mode_active:
            self._virtual_temp = float(temp_f)

    # --- SENSOR INTERFACE ---
    
    def scan_available_sensors(self):
        """Returns a list of 1-wire sensor IDs."""
        # If Dev Mode is ON, only show virtual sensors
        if self._dev_mode_active:
            return ["Virtual-Probe-01", "Virtual-Probe-02"]
            
        try:
            base_dir = '/sys/bus/w1/devices/'
            # Find all folders starting with 28-
            device_folders = glob.glob(base_dir + '28-*')
            # Extract just the folder name (the ID)
            sensors = [os.path.basename(f) for f in device_folders]
            return sensors
        except Exception as e:
            print(f"[HARDWARE] Error scanning sensors: {e}")
            return []

    def scan_audio_devices(self):
        """
        Parses 'aplay -l' to find audio devices.
        Returns a list of tuples: (friendly_name, device_string)
        e.g. [("Default (System)", "default"), ("Headphones (3.5mm)", "plughw:0,0"), ("USB Audio", "plughw:1,0")]
        """
        devices = [("Default (System)", "default")]
        
        if self._dev_mode_active:
            devices.append(("Virtual Speaker", "default"))
            return devices

        try:
            import subprocess
            import re
            
            # Run aplay -l to list hardware devices
            result = subprocess.run(["aplay", "-l"], capture_output=True, text=True)
            output = result.stdout
            
            # Regex to find: card X: [Name], device Y: [Description]
            # Output format example: 
            # card 1: Device [USB Audio Device], device 0: USB Audio [USB Audio]
            pattern = re.compile(r'card (\d+): (.*?) \[.*\], device (\d+): (.*?) \[.*\]')
            
            for line in output.split('\n'):
                match = pattern.search(line)
                if match:
                    card_num = match.group(1)
                    card_name = match.group(2)
                    dev_num = match.group(3)
                    dev_desc = match.group(4)
                    
                    # Construct a friendly name
                    # e.g. "USB Audio Device (USB Audio)"
                    friendly = f"{card_name} - {dev_desc}"
                    
                    # Construct ALSA device string
                    # plughw:X,Y allows software resampling if needed (safer than hw:X,Y)
                    dev_str = f"plughw:{card_num},{dev_num}"
                    
                    devices.append((friendly, dev_str))
                    
        except Exception as e:
            print(f"[HARDWARE] Error scanning audio: {e}")
            
        return devices

    def read_temperature(self):
        """
        Returns the SMOOTHED temperature in Fahrenheit.
        Returns None if sensor is missing/error.
        """
        if self._dev_mode_active:
            raw_val = self._virtual_temp
        else:
            raw_val = self._read_physical_sensor()
            
        if raw_val is not None:
            self._temp_buffer.append(raw_val)
            # Return the average of the buffer
            return sum(self._temp_buffer) / len(self._temp_buffer)
            
        return None

    def _read_physical_sensor(self):
        sensor_id = self.settings.get_system_setting("temp_sensor_id", "unassigned")
        if not sensor_id or sensor_id == "unassigned":
            return None

        try:
            device_file = f'/sys/bus/w1/devices/{sensor_id}/w1_slave'
            if not os.path.exists(device_file):
                return None
                
            with open(device_file, 'r', encoding='utf-8') as f:
                lines = f.readlines()
                
            if not lines:
                return None
                
            # Line 1 check: "YES"
            if lines[0].strip()[-3:] != 'YES':
                return None
                
            # Line 2: "t=23123"
            equals_pos = lines[1].find('t=')
            if equals_pos != -1:
                temp_string = lines[1][equals_pos+2:]
                temp_c = float(temp_string) / 1000.0
                temp_f = temp_c * 9.0 / 5.0 + 32.0
                return temp_f
                
            return None
            
        except Exception as e:
            return None
