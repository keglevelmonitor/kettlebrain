"""
src/startup_wizard.py
Hardware Logic Detection Wizard (Auto-Start like FermVault)
"""
import tkinter as tk
from tkinter import ttk, messagebox
import os

class StartupWizard:
    def __init__(self, root, settings_manager, relay_control):
        self.root = root
        self.settings = settings_manager
        self.relay = relay_control
        
        self.window = tk.Toplevel(root)
        self.window.title("Hardware Setup: Relay Logic")
        
        # --- FIXED SIZE & CENTERED STRATEGY (480p Optimization) ---
        target_w = 600
        target_h = 400  # Updated to fit within 418px constraint
        
        screen_width = self.window.winfo_screenwidth()
        screen_height = self.window.winfo_screenheight()
        
        x = int((screen_width/2) - (target_w/2))
        y = int((screen_height/2) - (target_h/2))
        
        # Ensure Y is not negative
        y = max(0, y)
        
        self.window.geometry(f"{target_w}x{target_h}+{x}+{y}")
        self.window.protocol("WM_DELETE_WINDOW", self._on_close_attempt)
        
        # Force modal behavior
        self.window.transient(root)
        self.window.grab_set()
        
        self._setup_ui()
        
        # AUTOMATICALLY START THE TEST
        # We wait 500ms to let the UI render, then click the relay.
        self.window.after(500, self._auto_energize_relay)
        
    def _setup_ui(self):
        container = ttk.Frame(self.window, padding=20)
        container.pack(fill='both', expand=True)
        
        # Header
        ttk.Label(container, text="Hardware Logic Detection", font=("Arial", 16, "bold")).pack(pady=(0,20))
        
        # Instructions
        msg = ("The system has sent a LOW signal to the AUX Relay.\n\n"
               "Please look at your relay board.\n"
               "Is the LED indicator for the AUX relay ON?")
        
        self.lbl_instructions = ttk.Label(container, text=msg, font=("Arial", 12), justify="center")
        self.lbl_instructions.pack(pady=10)
        
        # Image Logic
        try:
            base_path = os.path.dirname(os.path.abspath(__file__))
            img_path = os.path.join(base_path, "assets", "relay_led.gif")
            if os.path.exists(img_path):
                self.img = tk.PhotoImage(file=img_path)
                ttk.Label(container, image=self.img).pack(pady=10, expand=True)
        except Exception:
            pass

        # Buttons Area - IMMEDIATELY VISIBLE
        self.btn_frame = ttk.Frame(container)
        self.btn_frame.pack(side='bottom', fill='x', pady=20)
        
        # YES Button (Active Low)
        self.btn_yes = ttk.Button(self.btn_frame, text="YES, AUX LED is ON\n(Active Low Board)", command=self._confirm_active_low)
        self.btn_yes.pack(side='left', padx=10, expand=True, fill='x')
        
        # NO Button (Active High)
        self.btn_no = ttk.Button(self.btn_frame, text="NO, AUX LED is OFF\n(Active High Board)", command=self._confirm_active_high)
        self.btn_no.pack(side='left', padx=10, expand=True, fill='x')

    def _auto_energize_relay(self):
        """
        Called automatically. Sends LOW signal to Aux Relay (Pin 21).
        We use the 'Active Low' assumption: Low (False) = ON.
        """
        print("Wizard: Auto-energizing Aux Relay (LOW Signal)...")
        try:
            # RelayControl is initialized HIGH (OFF).
            # We send (False, False, True) -> Heater1=OFF, Heater2=OFF, Aux=ON(Low)
            self.relay.set_relays(False, False, True)
        except Exception as e:
            print(f"Wizard Error: Failed to auto-energize relays. Details: {e}")

    def _confirm_active_low(self):
        """User saw the light. The board responds to LOW = ON."""
        print("Wizard: Confirmed Active Low.")
        self.settings.set_system_setting("relay_active_high", False)
        self._finish()

    def _confirm_active_high(self):
        """User did NOT see the light. The board needs HIGH = ON."""
        print("Wizard: Confirmed Active High.")
        self.settings.set_system_setting("relay_active_high", True)
        self._finish()

    def _finish(self):
        """Cleanup and Close"""
        print("Wizard: Resetting relays to OFF.")
        try:
            # Turn everything OFF
            self.relay.set_relays(False, False, False)
        except:
            pass
            
        self.settings.set_system_setting("relay_logic_configured", True)
        self.window.destroy()

    def _on_close_attempt(self):
        if messagebox.askyesno("Exit?", "Setup incomplete. Exit application?"):
            try:
                self.relay.set_relays(False, False, False)
                self.relay.cleanup_gpio()
            except:
                pass
            os._exit(0)
