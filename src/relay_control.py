"""
kettlebrain app
relay_control.py
"""

import time
import sys

# --- GPIO IMPORT LOGIC (MATCHING KEGLEVEL) ---
try:
    # rpi-lgpio is a drop-in replacement for RPi.GPIO
    import RPi.GPIO as GPIO
    
    # Check/Set mode immediately upon import
    if GPIO.getmode() != GPIO.BCM:
        GPIO.setmode(GPIO.BCM)
        
    IS_RASPBERRY_PI_MODE = True
    print("[RelayControl] Running on RPi hardware (rpi-lgpio).")

except (ImportError, RuntimeError) as e:
    print(f"[RelayControl] WARNING: RPi.GPIO/lgpio not found ({e}). Running in simulation mode.")
    IS_RASPBERRY_PI_MODE = False
    
    # Mock GPIO class to prevent crashes on non-Pi hardware
    class MockGPIO:
        BCM = "BCM"
        OUT = "OUT"
        IN = "IN"
        LOW = 0
        HIGH = 1
        
        @staticmethod
        def setmode(mode): pass
        @staticmethod
        def setup(pin, mode, initial=None): pass
        @staticmethod
        def output(pin, state): pass
        @staticmethod
        def cleanup(): pass
        @staticmethod
        def getmode(): return "BCM"
    
    GPIO = MockGPIO
# ---------------------------------------------

class RelayControl:
    
    def __init__(self, settings_manager, relay_pins):
        """
        relay_pins dict should expect keys: "Heater1", "Heater2", "Aux"
        """
        self.settings = settings_manager
        self.pins = relay_pins
        self.gpio = GPIO
        
        # --- LOGIC CONFIGURATION ---
        self.logic_configured = self.settings.get("relay_logic_configured", False)
        
        # Default Internal States
        self.RELAY_ON = self.gpio.LOW
        self.RELAY_OFF = self.gpio.HIGH
        
        # Load the correct High/Low values
        self.update_relay_logic(initial_setup=True) 
        
        if IS_RASPBERRY_PI_MODE:
            self._setup_gpio()

    def update_relay_logic(self, initial_setup=False):
        """Refreshes High/Low definitions based on settings."""
        is_active_high = self.settings.get("relay_active_high", False)
        
        if is_active_high:
            self.RELAY_ON = self.gpio.HIGH
            self.RELAY_OFF = self.gpio.LOW
            if not initial_setup: print("[RelayControl] Logic set to ACTIVE HIGH")
        else:
            self.RELAY_ON = self.gpio.LOW
            self.RELAY_OFF = self.gpio.HIGH
            if not initial_setup: print("[RelayControl] Logic set to ACTIVE LOW")

        if not initial_setup and self.logic_configured:
             self.turn_off_all_relays()

    def _setup_gpio(self):
        # --- ROBUST INIT (MATCHING KEGLEVEL) ---
        
        # 1. Silence warnings before preemptive cleanup
        self.gpio.setwarnings(False) 
        
        try:
            # 2. Attempt cleanup first to clear stale state
            self.gpio.cleanup()
        except Exception:
            pass

        # 3. Set Mode (Must be done after cleanup)
        self.gpio.setmode(self.gpio.BCM)
        # ---------------------------------------

        for name, pin in self.pins.items():
            try:
                pin_int = int(pin)
                
                # --- SAFETY LOGIC ---
                if not self.logic_configured:
                    # SAFETY MODE: INPUT
                    self.gpio.setup(pin_int, self.gpio.IN)
                else:
                    # OPERATIONAL MODE: OUTPUT
                    self.gpio.setup(pin_int, self.gpio.OUT, initial=self.RELAY_OFF)
                    
            except Exception as e:
                # Catch "Busy Pin" errors common with lgpio if another process is holding it
                if "busy" in str(e).lower():
                    print(f"\n[CRITICAL ERROR] GPIO Pin {pin} ({name}) is BUSY.")
                    print("Another app (like KegLevel) might be running.")
                print(f"[RelayControl] Error setting up {name}: {e}")
                continue

    def set_relays(self, h1_state: bool, h2_state: bool, aux_state: bool):
        """Directly sets the states of the relays."""
        if not self.logic_configured: return

        # Map booleans to GPIO states
        gpio_h1 = self.RELAY_ON if h1_state else self.RELAY_OFF
        gpio_h2 = self.RELAY_ON if h2_state else self.RELAY_OFF
        gpio_aux = self.RELAY_ON if aux_state else self.RELAY_OFF
        
        try:
            if "Heater1" in self.pins: self.gpio.output(int(self.pins["Heater1"]), gpio_h1)
            if "Heater2" in self.pins: self.gpio.output(int(self.pins["Heater2"]), gpio_h2)
            if "Aux" in self.pins:     self.gpio.output(int(self.pins["Aux"]), gpio_aux)
        except Exception as e:
            print(f"[RelayControl] Error setting relays: {e}")

    def turn_off_all_relays(self):
        """Safety kill switch."""
        if self.logic_configured:
            for pin in self.pins.values():
                try:
                    self.gpio.output(int(pin), self.RELAY_OFF)
                except:
                    pass

    def cleanup_gpio(self):
        """Resets all GPIO pins to safe input state."""
        try:
            self.turn_off_all_relays()
            self.gpio.cleanup()
            print("[RelayControl] GPIO Cleanup complete.")
        except Exception as e:
            print(f"[RelayControl] Error during GPIO cleanup: {e}")
