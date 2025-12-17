"""
kettlebrain app
main.py
"""
import tkinter as tk
import sys
import os
import signal
import atexit
import time

# Ensure src is in path
sys.path.append(os.path.join(os.path.dirname(__file__), 'src'))

from settings_manager import SettingsManager
from relay_control import RelayControl
from sequence_manager import SequenceManager
from ui_manager import UIManager
from hardware_interface import HardwareInterface 
from startup_wizard import StartupWizard

# --- CONSTANTS ---
APP_NAME = "KettleBrain"
VERSION = "0.2.1-Dev"

# Wait this many seconds ONLY on auto-start to allow drivers to stabilize
STARTUP_DELAY_S = 3

# --- GLOBAL REFERENCE (Crucial for Signal Handling) ---
kettle_app = None 

def handle_exit_signal(signum, frame):
    """ROBUST SHUTDOWN HANDLER"""
    signal_name = "SIGHUP" if signum == signal.SIGHUP else "SIGTERM"
    print(f"\n[{APP_NAME}] CRITICAL: Received {signal_name}. initiating EMERGENCY STOP.")

    # 1. HARDWARE SAFETY FIRST
    try:
        if kettle_app and kettle_app.relay:
            kettle_app.relay.turn_off_all_relays()
            if hasattr(kettle_app.relay, 'cleanup_gpio'):
                kettle_app.relay.cleanup_gpio()
            print(f"[{APP_NAME}] SAFETY: Relays forced OFF.")
    except Exception as e:
        try: print(f"[{APP_NAME}] Hardware cleanup error: {e}")
        except: pass

    # 2. HARD KILL
    print(f"[{APP_NAME}] Process Terminated.")
    os._exit(0)

class KettleBrainApp:
    def __init__(self):
        self.root = None
        self.relay = None 
        self.is_shutting_down = False 

        # Register Safety Net
        atexit.register(self._emergency_cleanup)

    def run(self):
        # --- 1. HARDWARE STABILIZATION DELAY (Conditional) ---
        if "--auto-start" in sys.argv:
            print(f"[{APP_NAME}] Auto-Start detected. Waiting {STARTUP_DELAY_S}s for drivers...")
            time.sleep(STARTUP_DELAY_S)
        else:
            print(f"[{APP_NAME}] Normal start detected. Skipping boot delay.")

        self.root = tk.Tk()
        base_dir = os.path.expanduser("~")
        self.settings_mgr = SettingsManager(base_dir)

        # --- UNCONTROLLED SHUTDOWN CHECK ---
        uncontrolled = not self.settings_mgr.last_shutdown_was_clean
        auto_resume = self.settings_mgr.get_system_setting("auto_resume_enabled", False)
        recovery_data = self.settings_mgr.get_recovery_state()
        
        resume_success = False

        self.hardware = HardwareInterface(self.settings_mgr)
        self.relay = RelayControl(self.settings_mgr)

        # --- WIZARD CHECK ---
        if not self.settings_mgr.get_system_setting("relay_logic_configured"):
            print("[Main] Relay logic not configured. Launching Startup Wizard...")
            wizard = StartupWizard(self.root, self.settings_mgr, self.relay)
            self.root.wait_window(wizard.window)

        self.sequencer = SequenceManager(self.settings_mgr, self.relay, self.hardware)
        self.ui = UIManager(self.root, self.sequencer, self.hardware)

        # --- RECOVERY LOGIC ---
        if uncontrolled and auto_resume and recovery_data:
            print("[Main] Attempting Auto-Resume from Power Loss...")
            
            mode_type = recovery_data.get("mode_type", "PROFILE")
            
            if mode_type in ["DELAY", "MANUAL"]:
                self.sequencer.restore_from_recovery(recovery_data)
                resume_success = True
                print(f"[Main] Auto-Resume Successful ({mode_type} Mode).")
            
            elif mode_type == "PROFILE":
                p_id = recovery_data.get("profile_id")
                profiles = self.settings_mgr.get_all_profiles()
                target_profile = next((p for p in profiles if p.id == p_id), None)
                
                if target_profile:
                    self.sequencer.load_profile(target_profile)
                    self.sequencer.restore_from_recovery(recovery_data)
                    resume_success = True
                    print("[Main] Auto-Resume Successful (Profile Mode).")
                else:
                    print("[Main] Recovery failed: Profile not found.")
        
        # --- DEFAULT STARTUP (If not resuming) ---
        if not resume_success:
            print("[Main] Performing Standard Startup...")
            # 1. Load Default Profile (so Auto mode isn't empty if they switch)
            profiles = self.settings_mgr.get_all_profiles()
            if profiles:
                # Try to find "Default Profile", else take the first one
                default_p = next((p for p in profiles if p.name == "Default Profile"), profiles[0])
                self.sequencer.load_profile(default_p)
                print(f"[Main] Loaded startup profile: {default_p.name}")
            else:
                print("[Main] No profiles found to load.")
            
            # 2. Enter Manual Mode immediately (This will now preserve the loaded profile)
            self.sequencer.enter_manual_mode()

        # Handle "X" Button
        self.root.protocol("WM_DELETE_WINDOW", self.shutdown)

        print(f"[{APP_NAME} {VERSION}] Starting Main Loop...")
        try:
            self.root.mainloop()
        except KeyboardInterrupt:
            print(f"\n[{APP_NAME}] KeyboardInterrupt (Ctrl+C).")
            self.shutdown()
        except Exception as e:
            print(f"\n[{APP_NAME}] CRITICAL MAIN LOOP ERROR: {e}")
            self._emergency_cleanup()
            raise

    def shutdown(self):
        if self.is_shutting_down: return
        self.is_shutting_down = True 
        print(f"[{APP_NAME}] Performing Controlled Shutdown...")
        
        if hasattr(self, 'sequencer'):
            try: self.sequencer.stop()
            except Exception as e: print(f"[{APP_NAME}] Error stopping sequencer: {e}")

        self._emergency_cleanup()
        
        if hasattr(self, 'settings_mgr'):
            print(f"[{APP_NAME}] Marking session as Clean Exit.")
            self.settings_mgr.set_controlled_shutdown(True)

        if self.root:
            try: self.root.destroy()
            except: pass

        print(f"[{APP_NAME}] Goodbye.")
        sys.exit(0)

    def _emergency_cleanup(self):
        if hasattr(self, 'relay') and self.relay:
            try:
                self.relay.turn_off_all_relays()
                if hasattr(self.relay, 'cleanup_gpio'):
                    self.relay.cleanup_gpio()
                print(f"[{APP_NAME}] Relays forced OFF (Emergency Cleanup).")
            except Exception as e:
                print(f"[{APP_NAME}] CRITICAL: Failed to cleanup relays: {e}")

if __name__ == "__main__":
    app = KettleBrainApp()
    kettle_app = app
    signal.signal(signal.SIGHUP, handle_exit_signal)
    signal.signal(signal.SIGTERM, handle_exit_signal)
    app.run()
