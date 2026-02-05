import time
import sys
import os

# Ensure the script can find the other modules
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from relay_control import RelayControl
from settings_manager import SettingsManager

def run_debug():
    print("--- KettleBrain Relay 3 Debug Tool ---")
    
    # 1. Initialize Settings and Hardware
    script_path = os.path.abspath(sys.argv[0])
    src_dir = os.path.dirname(script_path)
    # Correctly resolve the path to find kettlebrain-data
    root_dir = os.path.dirname(os.path.dirname(src_dir)) 
    
    sm = SettingsManager(root_dir)
    rc = RelayControl(sm)
    
    # Explicitly check if Heater3 is in the map to avoid KeyErrors
    pin = rc.RELAY_MAP.get('Heater3', 'UNKNOWN')
    print(f"Targeting Relay 3 on GPIO Pin: {pin}")
    print("Press CTRL+C to stop the test.")
    
    try:
        while True:
            # TOGGLE ON
            print(f"[{time.strftime('%H:%M:%S')}] Relay 3 (GPIO {pin}): ON")
            rc.set_relay("Heater3", True)
            time.sleep(3)
            
            # TOGGLE OFF
            print(f"[{time.strftime('%H:%M:%S')}] Relay 3 (GPIO {pin}): OFF")
            rc.set_relay("Heater3", False)
            time.sleep(3)
            
    except KeyboardInterrupt:
        print("\nCleaning up GPIO and exiting...")
        rc.stop_all()
        rc.cleanup_gpio()

if __name__ == "__main__":
    run_debug()
