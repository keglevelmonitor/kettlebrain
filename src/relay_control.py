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
        
        # PIN CONFIGURATION
        self.RELAY_MAP = {
            "Heater1": 26,
            "Heater2": 20,
            "Aux":     21
        }

        # Initialize Internal State Tracking
        self.relay_states = {
            "Heater1": False,
            "Heater2": False,
            "Aux":     False
        }

        # GPIO Setup
        try:
            GPIO.setmode(GPIO.BCM)
            GPIO.setwarnings(False)

            # Detect logic immediately to ensure safe startup state
            active_high = False
            if self.settings:
                active_high = self.settings.get_system_setting("relay_active_high", False)

            # Set initial state to OFF
            # If Active High: OFF = LOW
            # If Active Low:  OFF = HIGH
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
        Control a SINGLE relay independently.
        :param relay_name: "Heater1", "Heater2", or "Aux"
        :param state: True (ON) or False (OFF)
        """
        if relay_name not in self.RELAY_MAP:
            print(f"[RelayControl] Error: Unknown relay name '{relay_name}'")
            return

        # 1. Update our internal memory
        self.relay_states[relay_name] = state
        
        # 2. Check Logic Preference
        active_high = False
        if self.settings:
            active_high = self.settings.get_system_setting("relay_active_high", False)

        # 3. Determine Physical Signal
        # If Active High: ON=High, OFF=Low
        # If Active Low:  ON=Low,  OFF=High
        if active_high:
            gpio_state = GPIO.HIGH if state else GPIO.LOW
        else:
            gpio_state = GPIO.LOW if state else GPIO.HIGH
        
        # 4. Update Hardware
        pin = self.RELAY_MAP[relay_name]
        try:
            GPIO.output(pin, gpio_state)
        except Exception as e:
            print(f"[RelayControl] Hardware Error setting {relay_name}: {e}")

    def set_relays(self, h1_state, h2_state, aux_state):
        """Batch method: Set ALL relays at once."""
        self.set_relay("Heater1", h1_state)
        self.set_relay("Heater2", h2_state)
        self.set_relay("Aux", aux_state)

    def stop_all(self):
        """Helper to safely shut everything down"""
        self.set_relays(False, False, False)

    def turn_off_all_relays(self):
        """Alias for stop_all()."""
        self.stop_all()

    def cleanup_gpio(self):
        """Release GPIO pins on shutdown"""
        print("[RelayControl] Cleaning up GPIO...")
        self.stop_all()
        try:
            GPIO.cleanup()
        except:
            pass
