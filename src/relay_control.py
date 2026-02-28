"""
src/relay_control.py
Relay control for KettleBrain.
"""
import RPi.GPIO as GPIO

class RelayControl:
    def __init__(self, settings_manager=None, pin_config=None):
        """
        Relay Control - Configurable Logic
        """
        self.settings = settings_manager
        
        # --- HARDCODED PIN MAP (Source of Truth) ---
        # R1=26, R2=20, R3=21
        self.RELAY_MAP = {
            "Heater1": 26,
            "Heater2": 20,
            "Heater3": 21  # <--- CHANGED KEY FROM 'Aux' TO 'Heater3'
        }
        
        print(f"[RelayControl] Mapping: {self.RELAY_MAP}")

        # Initialize Internal State Tracking
        self.relay_states = {
            "Heater1": False,
            "Heater2": False,
            "Heater3": False 
        }

        # GPIO Setup
        try:
            GPIO.setmode(GPIO.BCM)
            GPIO.setwarnings(False)

            active_high = False
            if self.settings:
                active_high = self.settings.get_system_setting("relay_active_high", False)

            # OFF State
            initial_output = GPIO.LOW if active_high else GPIO.HIGH

            for name, pin in self.RELAY_MAP.items():
                GPIO.setup(pin, GPIO.OUT)
                GPIO.output(pin, initial_output)
                
            logic_str = "Active High" if active_high else "Active Low"
            print(f"[RelayControl] Initialized ({logic_str} Mode)")
            
        except Exception as e:
            print(f"[RelayControl] GPIO Init Error: {e}")

    def set_relay(self, relay_name, state):
        """
        Sets a specific relay to True (ON) or False (OFF).
        """
        if relay_name not in self.RELAY_MAP:
            print(f"[RelayControl] Unknown Relay '{relay_name}'")
            return

        # 1. Update our internal memory
        self.relay_states[relay_name] = state
        
        # 2. Check Logic Preference
        active_high = False
        if self.settings:
            active_high = self.settings.get_system_setting("relay_active_high", False)

        # 3. Determine Physical Signal
        if active_high:
            gpio_state = GPIO.HIGH if state else GPIO.LOW
        else:
            # Active Low: True(ON) -> LOW signal
            gpio_state = GPIO.LOW if state else GPIO.HIGH
        
        # 4. Update Hardware
        pin = self.RELAY_MAP[relay_name]
        try:
            GPIO.output(pin, gpio_state)
        except Exception as e:
            print(f"[RelayControl] Hardware Error setting {relay_name} (Pin {pin}): {e}")

    def set_relays(self, h1_state, h2_state, h3_state):
        """Batch method: Set ALL relays at once."""
        self.set_relay("Heater1", h1_state)
        self.set_relay("Heater2", h2_state)
        self.set_relay("Heater3", h3_state)
        
    def stop_all(self):
        """Helper to safely shut everything down"""
        self.set_relays(False, False, False)

    def turn_off_all_relays(self):
        """Alias for stop_all()."""
        self.stop_all()

    def cleanup_gpio(self):
        """Release GPIO resources on exit."""
        try:
            GPIO.cleanup()
            print("[RelayControl] GPIO Cleaned up.")
        except:
            pass
