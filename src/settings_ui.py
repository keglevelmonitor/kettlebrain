"""
src/settings_ui.py 
09:16
Settings popup for KettleBrain. 
"""
import tkinter as tk
from tkinter import ttk, messagebox
import uuid
import copy
import os
import sys
import subprocess
import threading  # <--- Insert this new import
from profile_editor import ProfileEditor
from profile_data import BrewProfile, SequenceStatus
from utils import UnitUtils

class SettingsPopup(tk.Toplevel):
    def __init__(self, parent, settings_manager, hardware_interface, relay_control, sequencer):
        super().__init__(parent)
        
        # 1. HIDE IMMEDIATELY
        self.withdraw()
        
        self.settings = settings_manager
        self.hw = hardware_interface
        self.relay = relay_control
        self.sequencer = sequencer
        self.editor_window = None
        
        self.system_settings_dirty = False
        self.suppress_dirty_flag = False
        self.original_tab_index = 0 
        self.system_settings_index = -1 
        self.relay_test_index = -1
        
        self.title("KettleBrain Settings")
        self.geometry("780x440")
        self.transient(parent)
        
        # 2. Load Data & Build UI
        self._load_data()
        self._create_layout()
        
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        
        # 3. Center Window
        self.update_idletasks()
        try:
            x = parent.winfo_rootx() + 10
            y = parent.winfo_rooty() + 10
            self.geometry(f"+{x}+{y}")
        except:
            pass
        
        # 4. SAFE SHOW SEQUENCE
        # Removed self.wait_visibility()
        self.deiconify()
        self.lift()
        self.focus_set()
        
        try:
            self.grab_set()
        except Exception as e:
            print(f"Warning: SettingsPopup grab failed: {e}")

    def _cleanup_and_close(self):
        try:
            self.grab_release()
            if self.master:
                self.master.focus_set()
        except:
            pass
        finally:
            self.destroy()

    def _load_data(self):
        # 1. Fetch values from SettingsManager
        units = self.settings.get_system_setting("units", "imperial")
        sensor = self.settings.get_system_setting("temp_sensor_id", "unassigned")
        alt = str(self.settings.get_system_setting("altitude_ft", "0"))
        numlock = self.settings.get_system_setting("force_numlock", True)
        
        # NEW: Dev Mode
        dev_mode = self.settings.get_system_setting("dev_mode", False)
        
        auto_start = self.settings.get_system_setting("auto_start_enabled", True)
        auto_resume = self.settings.get_system_setting("auto_resume_enabled", False)

        # 2. Suppress dirty flag while loading/reverting
        self.suppress_dirty_flag = True

        try:
            if hasattr(self, 'units_var'):
                self.units_var.set(units)
                self.temp_sensor_var.set(sensor)
                self.altitude_var.set(alt)
                self.numlock_var.set(numlock)
                self.dev_mode_var.set(dev_mode) # Update existing
                self.auto_start_var.set(auto_start)
                self.auto_resume_var.set(auto_resume)
                
                self.relay_h1_var.set(False)
                self.relay_h2_var.set(False)
                self.relay_aux_var.set(False)
            else:
                self.units_var = tk.StringVar(value=units)
                self.temp_sensor_var = tk.StringVar(value=sensor)
                self.altitude_var = tk.StringVar(value=alt)
                self.numlock_var = tk.BooleanVar(value=numlock)
                self.dev_mode_var = tk.BooleanVar(value=dev_mode) # Create new
                
                self.auto_start_var = tk.BooleanVar(value=auto_start)
                self.auto_resume_var = tk.BooleanVar(value=auto_resume)
                
                self.relay_h1_var = tk.BooleanVar(value=False)
                self.relay_h2_var = tk.BooleanVar(value=False)
                self.relay_aux_var = tk.BooleanVar(value=False)
        finally:
            self.suppress_dirty_flag = False

    def _create_layout(self):
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill='both', expand=True, padx=10, pady=5)
        
        self.notebook.bind("<<NotebookTabChanged>>", self._on_tab_change)
        
        # 1. Profile Library
        self.tab_profiles = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_profiles, text="Profile Library")
        self._build_profiles_tab()
        
        # 2. System Settings
        self.tab_system = ttk.Frame(self.notebook, padding=15)
        self.notebook.add(self.tab_system, text="System Settings")
        self._build_system_tab()
        
        # 3. Calibration (NEW)
        self.tab_calibration = ttk.Frame(self.notebook, padding=15)
        self.notebook.add(self.tab_calibration, text="Calibration")
        self._build_calibration_tab()
        
        # 4. Updates
        self.tab_updates = ttk.Frame(self.notebook, padding=15)
        self.notebook.add(self.tab_updates, text="Updates")
        self._build_updates_tab()
        
        # 5. Relay Test
        self.tab_relay_test = ttk.Frame(self.notebook, padding=15)
        self.notebook.add(self.tab_relay_test, text="Relay Test")
        self._build_relay_test_tab()

        # 6. Developer
        self.tab_developer = ttk.Frame(self.notebook, padding=15)
        self.notebook.add(self.tab_developer, text="Developer")
        self._build_developer_tab()
        
        # Indices for tab change logic
        self.system_settings_index = self.notebook.index(self.tab_system)
        self.relay_test_index = self.notebook.index(self.tab_relay_test)
        self.developer_index = self.notebook.index(self.tab_developer)

    def _on_tab_change(self, event):
        """Intercepts tab change to warn user about unsaved settings."""
        
        current_tab_index = self.notebook.index(self.notebook.select())
        
        # If we were previously on the System Settings tab and changes were made
        if self.original_tab_index == self.system_settings_index and self.system_settings_dirty:
            
            response = messagebox.askyesnocancel(
                "Unsaved Changes",
                "You have unsaved changes in System Settings.\n\n"
                "Save changes before navigating away?",
                parent=self
            )
            
            if response is True:
                # YES: Save and proceed
                if self._save_settings_no_popup():
                    self.system_settings_dirty = False
                    self.original_tab_index = current_tab_index 
                else:
                    # Save failed (e.g., input error), block navigation
                    self.notebook.select(self.system_settings_index)
                    self.original_tab_index = self.system_settings_index 
            
            elif response is False:
                # NO: Discard changes and proceed
                self.system_settings_dirty = False
                
                # Reload data and refresh widgets
                self._load_data() 
                self._reload_system_widgets() 
                
                self.original_tab_index = current_tab_index 
            
            elif response is None:
                # CANCEL: Block navigation, return to System Settings tab
                self.notebook.select(self.system_settings_index)
                self.original_tab_index = self.system_settings_index
                return 
        
        # Update the original index for the next check
        self.original_tab_index = self.notebook.index(self.notebook.select())

    def _set_dirty(self, *args):
        """Sets the dirty flag when any tracked variable changes."""
        if self.suppress_dirty_flag: return
        self.system_settings_dirty = True
        
    # --- TAB 1: PROFILES ---
    
    def _build_profiles_tab(self):
        toolbar = ttk.Frame(self.tab_profiles, padding=5)
        toolbar.pack(fill='x', side='bottom', padx=10)
        
        ttk.Button(toolbar, text="Close", command=self._on_close).pack(side='right', padx=5)
        ttk.Button(toolbar, text="LOAD PROFILE", command=self._load_selected, width=15).pack(side='right', padx=5)
        
        ttk.Button(toolbar, text="Copy", command=self._copy_selected).pack(side='right', padx=5)
        ttk.Button(toolbar, text="Edit", command=self._edit_selected).pack(side='right', padx=5)
        ttk.Button(toolbar, text="Delete", command=self._delete_selected).pack(side='right', padx=5)
        
        ttk.Button(toolbar, text="+ New Profile", command=self._create_new).pack(side='left', padx=5)
        
        list_container = ttk.Frame(self.tab_profiles)
        list_container.pack(fill='both', expand=True, padx=10, pady=(10, 0))

        cols = ("steps",)
        self.tree = ttk.Treeview(list_container, columns=cols, show="tree headings")
        self.tree.heading("#0", text="Profile Name")
        self.tree.heading("steps", text="Steps")
        
        self.tree.column("steps", width=50, anchor='center')
        
        sb = ttk.Scrollbar(list_container, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        
        self.tree.pack(side='left', fill='both', expand=True)
        sb.pack(side='right', fill='y')
        
        self._refresh_profile_list()

    def _refresh_profile_list(self):
        self.tree.delete(*self.tree.get_children())
        profiles = self.settings.get_all_profiles()
        
        # 1. Separate "Default Profile" from the rest
        default_profile = None
        other_profiles = []
        
        for p in profiles:
            if p.name == "Default Profile":
                default_profile = p
            else:
                other_profiles.append(p)
        
        # 2. Sort the others alphabetically (case-insensitive)
        other_profiles.sort(key=lambda x: x.name.lower())
        
        # 3. Recombine: Default first, then sorted others
        display_list = []
        if default_profile:
            display_list.append(default_profile)
        display_list.extend(other_profiles)

        # 4. Insert into TreeView
        for p in display_list:
            self.tree.insert("", "end", iid=p.id, text=p.name, values=(len(p.steps),))

    def _get_selected_id(self):
        sel = self.tree.selection()
        if not sel: return None
        return sel[0]

    def _load_selected(self):
        # --- RESTORED LOGIC ---
        if self.sequencer.status in [SequenceStatus.RUNNING, SequenceStatus.PAUSED, SequenceStatus.WAITING_FOR_USER]:
            messagebox.showwarning(
                "System Active", 
                "Cannot load a new profile while a sequence is running.\n\nPlease STOP the current session on the main screen first.",
                parent=self
            )
            return

        pid = self._get_selected_id()
        if not pid: return
        profile = self.settings.get_profile_by_id(pid)
        if profile:
            self.sequencer.load_profile(profile)
            self._cleanup_and_close()

    def _create_new(self):
        self._open_editor(BrewProfile(name="New Profile"))

    def _edit_selected(self):
        pid = self._get_selected_id()
        if not pid: return
        profile = self.settings.get_profile_by_id(pid)
        if profile:
            self._open_editor(profile)

    def _copy_selected(self):
        pid = self._get_selected_id()
        if not pid: return
        original = self.settings.get_profile_by_id(pid)
        if not original: return
        
        new_p = BrewProfile(
            id=str(uuid.uuid4()),
            name=f"Copy of {original.name}"
        )
        new_p.steps = copy.deepcopy(original.steps)
        self._open_editor(new_p)

    def _delete_selected(self):
        pid = self._get_selected_id()
        if not pid: return
        
        profile = self.settings.get_profile_by_id(pid)
        if profile and profile.name == "Default Profile":
            messagebox.showwarning("Restricted", "The Default Profile cannot be deleted.", parent=self)
            return

        if messagebox.askyesno("Confirm", "Delete this profile?", parent=self):
            self.settings.delete_profile(pid)
            self._refresh_profile_list()

    def _open_editor(self, profile):
        if self.editor_window and tk.Toplevel.winfo_exists(self.editor_window):
            self.editor_window.lift()
            return
            
        self.editor_window = ProfileEditor(self, profile, self.settings, on_save_callback=self._on_editor_save)

    def _on_editor_save(self, profile):
        self.settings.save_profile(profile)
        self._refresh_profile_list()

    # --- TAB 2: SYSTEM SETTINGS ---

    def _set_system_volume(self, val):
        """Sets system volume using amixer (0-100%)."""
        try:
            # Cast string "55.0" to int 55
            vol_int = int(float(val))
            
            # Try 'PCM' first (standard for Pi headphone jack)
            subprocess.run(["amixer", "sset", "PCM", f"{vol_int}%"], 
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            
            # Try 'HDMI' just in case
            subprocess.run(["amixer", "sset", "HDMI", f"{vol_int}%"], 
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                         
            # Try 'Master' (some USB cards)
            subprocess.run(["amixer", "sset", "Master", f"{vol_int}%"], 
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                         
        except Exception as e:
            print(f"Error setting volume: {e}")
            
    def _on_volume_release(self, event):
        """Plays a test sound when the user releases the volume slider."""
        import subprocess
        import os
        
        # Get the folder where this script lives (src/)
        current_dir = os.path.dirname(os.path.abspath(__file__))
        
        # Build path to src/assets/alert.wav
        sound_file = os.path.join(current_dir, "assets", "alert.wav")
        
        if os.path.exists(sound_file):
            try:
                # -q = quiet mode
                subprocess.Popen(["aplay", "-q", sound_file])
            except Exception as e:
                print(f"[UI] Error playing test sound: {e}")
        else:
            print(f"[UI] Warning: Could not find '{sound_file}' to preview volume.")
    
    def _build_system_tab(self):
        content_frame = ttk.Frame(self.tab_system)
        content_frame.pack(fill='both', expand=True)

        # --- SENSOR SECTION ---
        lbl_frame = ttk.LabelFrame(content_frame, text="Temperature Sensor", padding=5)
        lbl_frame.pack(fill='x', pady=(0, 5))
        
        ttk.Label(lbl_frame, text="Select ID:").pack(side='left')
        
        available_sensors = self.hw.scan_available_sensors()
        if not available_sensors:
            available_sensors = ["unassigned"]
        else:
            if "unassigned" not in available_sensors:
                available_sensors.insert(0, "unassigned")
                
        self.combo_sensor = ttk.Combobox(lbl_frame, textvariable=self.temp_sensor_var, values=available_sensors, state="readonly", width=25)
        self.combo_sensor.pack(side='left', padx=10)
        self.temp_sensor_var.trace_add("write", self._set_dirty)
        
        ttk.Button(lbl_frame, text="Refresh", command=self._refresh_sensors).pack(side='left')
        
        # --- GENERAL CONFIG ---
        gen_frame = ttk.LabelFrame(content_frame, text="Configuration", padding=5)
        gen_frame.pack(fill='x', pady=(0, 5))
        
        # Units
        u_frame = ttk.Frame(gen_frame)
        u_frame.pack(fill='x', pady=2)
        ttk.Label(u_frame, text="Display Units:", width=15).pack(side='left')
        ttk.Radiobutton(u_frame, text="US Imperial (°F / Gal)", variable=self.units_var, value="imperial", command=self._set_dirty).pack(side='left')
        ttk.Radiobutton(u_frame, text="Metric (°C / L)", variable=self.units_var, value="metric", command=self._set_dirty).pack(side='left', padx=15)
        
        # Altitude
        a_frame = ttk.Frame(gen_frame)
        a_frame.pack(fill='x', pady=2)
        ttk.Label(a_frame, text="Altitude (ft):", width=15).pack(side='left')
        self.altitude_entry = ttk.Entry(a_frame, textvariable=self.altitude_var, width=10)
        self.altitude_entry.pack(side='left')
        self.altitude_var.trace_add("write", self._set_dirty)
        ttk.Label(a_frame, text="(For boiling point calculation)").pack(side='left', padx=5)
        
        # Autostart / Resume
        r_frame = ttk.Frame(gen_frame)
        r_frame.pack(fill='x', pady=2)
        
        self.auto_start_check = ttk.Checkbutton(r_frame, text="Auto-Start App on Boot", variable=self.auto_start_var, command=self._set_dirty)
        self.auto_start_check.pack(anchor='w')
        
        self.auto_resume_check = ttk.Checkbutton(r_frame, text="Auto-Resume after Power Loss", variable=self.auto_resume_var, command=self._set_dirty)
        self.auto_resume_check.pack(anchor='w')

        self.auto_start_var.trace_add("write", self._toggle_resume_dependency)
        self._toggle_resume_dependency()
        
        # Volume Control
        v_frame = ttk.Frame(gen_frame)
        v_frame.pack(fill='x', pady=2)
        
        ttk.Label(v_frame, text="System Volume:", width=15).pack(side='left')
        
        # Scale widget (Slider)
        vol_scale = tk.Scale(v_frame, from_=0, to=100, orient='horizontal', command=self._set_system_volume, width=15)
        vol_scale.set(80) 
        vol_scale.pack(side='left', fill='x', expand=True, padx=5)

        # --- NEW: Bind mouse release to sound preview ---
        # This triggers only when the user lets go of the slider handle
        vol_scale.bind("<ButtonRelease-1>", self._on_volume_release)
        
        # Numlock 
        n_frame = ttk.Frame(gen_frame)
        n_frame.pack(fill='x', pady=2)
        ttk.Checkbutton(n_frame, text="Force NumLock ON at startup", variable=self.numlock_var, command=self._set_dirty).pack(anchor='w')

        # --- BUTTONS ---
        sys_btn_frame = ttk.Frame(self.tab_system)
        sys_btn_frame.pack(fill='x', side='bottom', pady=10)
        ttk.Button(sys_btn_frame, text="Close", command=self._on_close).pack(side='right')
        ttk.Button(sys_btn_frame, text="Save System Settings", command=self._save_settings).pack(side='right', padx=10)

    # --- TAB 3: UPDATES ---

    def _build_updates_tab(self):
        # Main Container
        frame = ttk.Frame(self.tab_updates)
        frame.pack(fill='both', expand=True)

        # Log Area (Text Widget + Scrollbar)
        log_frame = ttk.LabelFrame(frame, text="Update Status", padding=5)
        log_frame.pack(fill='both', expand=True, pady=(0, 10))

        self.txt_update_log = tk.Text(log_frame, height=10, state='disabled', font=('Courier', 10))
        self.txt_update_log.pack(side='left', fill='both', expand=True)

        sb = ttk.Scrollbar(log_frame, orient='vertical', command=self.txt_update_log.yview)
        sb.pack(side='right', fill='y')
        self.txt_update_log.config(yscrollcommand=sb.set)

        # Buttons Area
        btn_frame = ttk.Frame(frame)
        btn_frame.pack(fill='x', side='bottom')

        # Close Button (Right)
        ttk.Button(btn_frame, text="Close", command=self._on_close).pack(side='right', padx=5)

        # Action Buttons (Left)
        self.btn_check_updates = ttk.Button(btn_frame, text="Check for Updates", command=self._on_check_updates)
        self.btn_check_updates.pack(side='left', padx=5)

        self.btn_install_updates = ttk.Button(btn_frame, text="Install Updates", command=self._on_install_updates, state='disabled')
        self.btn_install_updates.pack(side='left', padx=5)

    def _safe_append_log(self, text):
        """Thread-safe way to append text to the log widget."""
        def _update():
            self.txt_update_log.config(state='normal')
            self.txt_update_log.insert(tk.END, text)
            self.txt_update_log.see(tk.END)
            self.txt_update_log.config(state='disabled')
        self.after(0, _update)

    def _safe_toggle_install(self, enable):
        """Thread-safe way to enable/disable the install button."""
        state = 'normal' if enable else 'disabled'
        self.after(0, lambda: self.btn_install_updates.config(state=state))

    def _on_check_updates(self):
        # Clear log
        self.txt_update_log.config(state='normal')
        self.txt_update_log.delete(1.0, tk.END)
        self.txt_update_log.config(state='disabled')
        
        self.btn_check_updates.config(state='disabled')
        self.btn_install_updates.config(state='disabled')
        
        # Start Thread: Pass flags ONLY
        t = threading.Thread(target=self._run_update_process, args=(["--check"], True))
        t.start()

    def _on_install_updates(self):
        self.btn_check_updates.config(state='disabled')
        self.btn_install_updates.config(state='disabled')
        
        # Start Thread: No flags for install
        t = threading.Thread(target=self._run_update_process, args=([], False))
        t.start()

    def _run_update_process(self, flags, is_check_mode):
        """Runs the bash command and monitors output."""
        try:
            # 1. Calculate Absolute Path to update.sh
            # This file is in .../kettlebrain/src/settings_ui.py
            current_dir = os.path.dirname(os.path.abspath(__file__))
            # Go up one level to .../kettlebrain/
            project_root = os.path.dirname(current_dir)
            script_path = os.path.join(project_root, "update.sh")

            if not os.path.exists(script_path):
                self._safe_append_log(f"Error: Could not find update script at:\n{script_path}\n")
                self.after(0, lambda: self.btn_check_updates.config(state='normal'))
                return

            # 2. Build Command
            command = ["bash", script_path]
            if flags:
                command.extend(flags)

            process = subprocess.Popen(
                command, 
                stdout=subprocess.PIPE, 
                stderr=subprocess.STDOUT, 
                text=True, 
                bufsize=1
            )

            update_available = False

            # Read output line by line
            while True:
                line = process.stdout.readline()
                if not line and process.poll() is not None:
                    break
                if line:
                    self._safe_append_log(line)
                    
                    # --- FIXED DETECTION LOGIC ---
                    # Detect "Update available" (KegLevel style) OR standard Git output indicating changes
                    lower_line = line.lower()
                    if "update available" in lower_line:
                        update_available = True
                    elif "fast-forward" in lower_line:
                        update_available = True
                    elif "changed" in lower_line and "file" in lower_line:
                        # Catches "1 file changed" or "5 files changed"
                        update_available = True
                    # -----------------------------

            return_code = process.poll()

            # Post-Process Logic
            if is_check_mode:
                self.after(0, lambda: self.btn_check_updates.config(state='normal'))
                
                if update_available:
                    self._safe_toggle_install(True)
                    # Optional: Add a note that it's ready to install/restart
                    self._safe_append_log("\n[Check Complete] Updates found. Click 'Install Updates'.\n")
                else:
                    self._safe_append_log("\n[Check Complete] No updates found.\n")
            else:
                # Install Mode
                if return_code == 0:
                    self._safe_append_log("\n[Update Successful] Please restart the application.\n")
                else:
                    self._safe_append_log("\n[Update Failed] Check console for details.\n")
                
                # Re-enable check button so they can try again if needed
                self.after(0, lambda: self.btn_check_updates.config(state='normal'))

        except Exception as e:
            self._safe_append_log(f"\nError running update utility: {e}\n")
            self.after(0, lambda: self.btn_check_updates.config(state='normal'))
    
    # --- TAB 3: CALIBRATION ---

    def _build_calibration_tab(self):
        # 1. Init Variables
        self.cal_vol_var = tk.StringVar()
        self.cal_start_temp_var = tk.StringVar()
        self.cal_end_temp_var = tk.StringVar()
        self.cal_time_var = tk.StringVar()
        self.cal_result_var = tk.StringVar(value="--")
        
        # Track the raw calculated factor (Fahrenheit) for saving
        self.cal_calculated_factor_f = None

        content = ttk.Frame(self.tab_calibration)
        content.pack(fill='both', expand=True)
        
        # --- SECTION 1: Current Factor (Top) ---
        info_frame = ttk.LabelFrame(content, text="Current Configuration", padding=10)
        info_frame.pack(fill='x', pady=(0, 10))
        
        self.lbl_current_factor = ttk.Label(info_frame, text="Loading...", font=('Arial', 11, 'bold'))
        self.lbl_current_factor.pack(anchor='w')
        
        ttk.Label(info_frame, text="(Used for Delayed Start calculations)", 
                 font=('Arial', 9, 'italic')).pack(anchor='w', pady=(2,0))
        
        self._refresh_calibration_label()

        # --- SECTION 2: Calculator (Main Area) ---
        calc_frame = ttk.LabelFrame(content, text="Calculate Temperature Rise Factor", padding=10)
        calc_frame.pack(fill='both', expand=True, pady=(0, 5))
        
        # Instructions (Top of Calculator)
        is_metric = UnitUtils.is_metric(self.settings)
        units_vol = "Liters" if is_metric else "Gallons"
        units_temp = "°C" if is_metric else "°F"
        
        instr = (f"Heat 3-4 {units_vol} of water to ~120{units_temp} using Manual Mode.\n"
                 "Enter the results below to calculate your system's efficiency.")
        ttk.Label(calc_frame, text=instr, justify='left').pack(anchor='w', pady=(0, 10))

        # --- SPLIT CONTAINER (Inputs Left / Buttons Right) ---
        split_frame = ttk.Frame(calc_frame)
        split_frame.pack(fill='both', expand=True)

        # LEFT COLUMN: Inputs
        input_pane = ttk.Frame(split_frame)
        input_pane.pack(side='left', fill='both', expand=True, padx=(0, 10))
        
        row = 0
        pad = 5
        
        ttk.Label(input_pane, text=f"Start Volume ({units_vol}):").grid(row=row, column=0, sticky='e', padx=pad, pady=pad)
        ttk.Entry(input_pane, textvariable=self.cal_vol_var, width=8).grid(row=row, column=1, sticky='w', padx=pad, pady=pad)
        
        row += 1
        ttk.Label(input_pane, text=f"Start Temp ({units_temp}):").grid(row=row, column=0, sticky='e', padx=pad, pady=pad)
        ttk.Entry(input_pane, textvariable=self.cal_start_temp_var, width=8).grid(row=row, column=1, sticky='w', padx=pad, pady=pad)
        
        row += 1
        ttk.Label(input_pane, text=f"End Temp ({units_temp}):").grid(row=row, column=0, sticky='e', padx=pad, pady=pad)
        ttk.Entry(input_pane, textvariable=self.cal_end_temp_var, width=8).grid(row=row, column=1, sticky='w', padx=pad, pady=pad)
        
        row += 1
        ttk.Label(input_pane, text="Elapsed Min:").grid(row=row, column=0, sticky='e', padx=pad, pady=pad)
        ttk.Entry(input_pane, textvariable=self.cal_time_var, width=8).grid(row=row, column=1, sticky='w', padx=pad, pady=pad)

        # RIGHT COLUMN: Actions
        action_pane = ttk.Frame(split_frame)
        action_pane.pack(side='right', fill='both', expand=False, padx=(10, 0))
        
        # Calculate Button
        ttk.Button(action_pane, text="Calculate Heat Rise", command=self._calculate_calibration).pack(fill='x', pady=(0, 10))
        
        # Result Display (Centered in action pane)
        lbl_res_title = ttk.Label(action_pane, text="Calculated Result:", font=('Arial', 9))
        lbl_res_title.pack(anchor='center')
        
        lbl_res_val = ttk.Label(action_pane, textvariable=self.cal_result_var, foreground='#0044CC', font=('Arial', 11, 'bold'))
        lbl_res_val.pack(anchor='center', pady=(0, 15))
        
        # Update Button
        self.btn_update_cal = ttk.Button(action_pane, text="Update Factor", state='disabled', command=self._apply_calibration)
        self.btn_update_cal.pack(fill='x', pady=(0, 5))
        
        # Restore Button
        ttk.Button(action_pane, text="Restore Default", command=self._restore_calibration_default).pack(fill='x')

        # --- SECTION 3: Bottom Close Button ---
        btn_frame = ttk.Frame(self.tab_calibration)
        btn_frame.pack(side='bottom', fill='x', pady=5)
        
        ttk.Button(btn_frame, text="Close", command=self._on_close).pack(side='right')
        
    def _refresh_calibration_label(self):
        """Reads the current setting and formats it for display."""
        raw_f = self.settings.get_system_setting("heater_ref_rate_fpm", 1.2)
        ref_vol = self.settings.get_system_setting("heater_ref_volume_gal", 8.0)
        
        if UnitUtils.is_metric(self.settings):
            # Convert F per min -> C per min
            # Delta C = Delta F * 5/9
            val_c = raw_f * 5.0 / 9.0
            
            # Display Vol in L? Usually kept as "Ref Volume" constant, 
            # but user prompt said "with 8 gallons". We will stick to the prompt's text 
            # for the constant part to avoid confusion, or convert if strict metric desired.
            # Prompt: "with 8 gallons in vessel (programming note, this is a constant)"
            
            self.lbl_current_factor.config(text=f"{val_c:.2f}°C per minute (Ref: 8 Gallons)")
        else:
            self.lbl_current_factor.config(text=f"{raw_f:.2f}°F per minute (Ref: 8 Gallons)")

    def _calculate_calibration(self):
        try:
            # 1. Get Inputs
            vol = float(self.cal_vol_var.get())
            start_t = float(self.cal_start_temp_var.get())
            end_t = float(self.cal_end_temp_var.get())
            mins = float(self.cal_time_var.get())
            
            if mins <= 0:
                messagebox.showerror("Error", "Time must be greater than 0.", parent=self)
                return

            # 2. Convert to Standard Units (Gallons, F) if Metric
            is_metric = UnitUtils.is_metric(self.settings)
            
            if is_metric:
                # L -> Gal
                vol_gal = vol * 0.264172
                # C -> F
                start_f = (start_t * 9.0/5.0) + 32
                end_f = (end_t * 9.0/5.0) + 32
            else:
                vol_gal = vol
                start_f = start_t
                end_f = end_t
                
            # 3. Calculate Actual Rate (Delta T / Time)
            delta_temp = end_f - start_f
            if delta_temp <= 0:
                messagebox.showerror("Error", "Ending temperature must be higher than starting temperature.", parent=self)
                return
                
            actual_rate_fpm = delta_temp / mins
            
            # 4. Normalize to Reference Volume (8.0 Gal)
            # Logic: Rate * (TestVol / RefVol)
            # Example: 2.0 F/min at 4gal -> 2.0 * (4/8) = 1.0 F/min at 8gal
            ref_vol = self.settings.get_system_setting("heater_ref_volume_gal", 8.0)
            normalized_rate_fpm = actual_rate_fpm * (vol_gal / ref_vol)
            
            # Store internally for saving
            self.cal_calculated_factor_f = normalized_rate_fpm
            
            # 5. Display Result
            if is_metric:
                norm_c = normalized_rate_fpm * 5.0 / 9.0
                self.cal_result_var.set(f"{norm_c:.2f}°C per minute (Ref: 8 Gal)")
            else:
                self.cal_result_var.set(f"{normalized_rate_fpm:.2f}°F per minute (Ref: 8 Gal)")
                
            # Enable Update Button
            self.btn_update_cal.config(state='normal')
            
        except ValueError:
            messagebox.showerror("Input Error", "Please enter valid numeric values.", parent=self)

    def _apply_calibration(self):
        if self.cal_calculated_factor_f is None: return
        
        # Save to settings
        self.settings.set_system_setting("heater_ref_rate_fpm", self.cal_calculated_factor_f)
        
        messagebox.showinfo("Success", "Calibration factor updated.", parent=self)
        
        # Refresh UI
        self._refresh_calibration_label()
        
        # Reset Form
        self.cal_calculated_factor_f = None
        self.btn_update_cal.config(state='disabled')
        self.cal_result_var.set("--")

    def _restore_calibration_default(self):
        if messagebox.askyesno("Confirm", "Restore default calibration factor (1.2°F/min)?", parent=self):
            self.settings.set_system_setting("heater_ref_rate_fpm", 1.2)
            self._refresh_calibration_label()
            messagebox.showinfo("Restored", "Default calibration restored.", parent=self)
            
    def _build_developer_tab(self):
        content_frame = ttk.Frame(self.tab_developer)
        content_frame.pack(fill='both', expand=True)

        dev_frame = ttk.LabelFrame(content_frame, text="Developer Configuration", padding=10)
        dev_frame.pack(fill='x', pady=(0, 10))
        
        ttk.Checkbutton(dev_frame, text="Allow Developer Mode (interlocked - for developer use only)", variable=self.dev_mode_var, command=self._set_dirty).pack(anchor='w')

        # Warning/Info text
        ttk.Label(dev_frame, text="Enables hardware simulation sliders in the main UI.", font=("Arial", 9, "italic")).pack(anchor='w', pady=(5,0))

        # Buttons
        btn_frame = ttk.Frame(self.tab_developer)
        btn_frame.pack(fill='x', side='bottom', pady=10)
        ttk.Button(btn_frame, text="Close", command=self._on_close).pack(side='right')
        ttk.Button(btn_frame, text="Save Settings", command=self._save_settings).pack(side='right', padx=10)

    def _reload_system_widgets(self):
        """Forces the System Settings and Relay Test widgets to visually reload their state."""
        # Temporarily suppress dirty flag because we are just refreshing the UI to match data
        was_suppressed = self.suppress_dirty_flag
        self.suppress_dirty_flag = True
        
        try:
            # 1. Re-trigger dependency logic to ensure correct visual state (Disabled/Normal)
            self._toggle_resume_dependency() 
            
            # 2. Relay vars were already reset in _load_data, this confirms safety
            self.relay_h1_var.set(False)
            self.relay_h2_var.set(False)
            self.relay_aux_var.set(False)
        finally:
            self.suppress_dirty_flag = was_suppressed

    def _toggle_resume_dependency(self, *args):
        """Disables and clears Auto-Resume if Auto-Start is disabled."""
        if not self.auto_start_var.get():
            # If Auto-Start is unchecked, force Auto-Resume off and disable it
            # We do NOT set the dirty flag here; the Checkbutton's command callback handles that.
            self.auto_resume_var.set(False)
            self.auto_resume_check.config(state='disabled')
        else:
            # Enable the Auto-Resume checkbox
            self.auto_resume_check.config(state='normal')

    # --- TAB 3: RELAY TEST ---

    def _build_relay_test_tab(self):
        relay_frame = ttk.LabelFrame(self.tab_relay_test, text="Manual Relay Control", padding=10)
        relay_frame.pack(fill='x', pady=(0, 10))
        
        is_safe = (self.sequencer.status == SequenceStatus.IDLE)
        state_str = 'normal' if is_safe else 'disabled'
        
        if is_safe:
            ttk.Label(relay_frame, text="WARNING: Buttons toggle real hardware immediately.", foreground="red").pack(anchor='w', pady=(0,5))
        else:
            ttk.Label(relay_frame, text="Relay testing disabled while Sequence is Active.", foreground="red").pack(anchor='w', pady=(0,5))

        btn_box = ttk.Frame(relay_frame)
        btn_box.pack(fill='x')
        
        ttk.Checkbutton(btn_box, text="HEATER 1", variable=self.relay_h1_var, command=lambda: self._toggle_relay("Heater1", self.relay_h1_var), state=state_str).pack(side='left', padx=10)
        ttk.Checkbutton(btn_box, text="HEATER 2", variable=self.relay_h2_var, command=lambda: self._toggle_relay("Heater2", self.relay_h2_var), state=state_str).pack(side='left', padx=10)
        ttk.Checkbutton(btn_box, text="AUX", variable=self.relay_aux_var, command=lambda: self._toggle_relay("Aux", self.relay_aux_var), state=state_str).pack(side='left', padx=10)
        
        # --- BUTTONS ---
        test_btn_frame = ttk.Frame(self.tab_relay_test)
        test_btn_frame.pack(fill='x', side='bottom', pady=10)
        
        ttk.Button(test_btn_frame, text="Close", command=self._on_close).pack(side='right')

    # --- HELPER METHODS ---

    def _save_settings_no_popup(self):
        """Saves settings but handles errors internally, returning True/False."""
        try:
            self.settings.set_system_setting("temp_sensor_id", self.temp_sensor_var.get())
            self.settings.set_system_setting("units", self.units_var.get())
            self.settings.set_system_setting("force_numlock", self.numlock_var.get())
            self.settings.set_system_setting("auto_start_enabled", self.auto_start_var.get())
            self.settings.set_system_setting("auto_resume_enabled", self.auto_resume_var.get())
            
            # --- NEW: Save Dev Mode ---
            new_dev_mode = self.dev_mode_var.get()
            self.settings.set_system_setting("dev_mode", new_dev_mode)
            # Push change to hardware interface immediately
            self.hw.set_dev_mode(new_dev_mode)
            
            try:
                alt = int(self.altitude_var.get())
                self.settings.set_system_setting("altitude_ft", alt)
            except ValueError:
                messagebox.showerror("Input Error", "Altitude must be a whole number.", parent=self); 
                return False
                
            self._manage_autostart_file(self.auto_start_var.get())
            self.system_settings_dirty = False
            return True
        except Exception as e:
            messagebox.showerror("Error", f"An unexpected error occurred during save: {e}", parent=self)
            return False
            
    def _save_settings(self):
        """Public save function that shows success dialog."""
        if self._save_settings_no_popup():
            messagebox.showinfo("Saved", "System Settings saved successfully.", parent=self)


    def _refresh_sensors(self):
        sensors = self.hw.scan_available_sensors()
        if not sensors: sensors = ["unassigned"]
        elif "unassigned" not in sensors: sensors.insert(0, "unassigned")
        self.combo_sensor['values'] = sensors
        if self.temp_sensor_var.get() not in sensors:
            self.temp_sensor_var.set(sensors[0])

    def _toggle_relay(self, name, var):
        state = var.get()
        if state:
            self.relay.set_relay(name, True)
        else:
            self.relay.set_relay(name, False)

    def _manage_autostart_file(self, enable):
        """Creates or removes the XDG autostart file for Bookworm/Trixie."""
        autostart_dir = os.path.expanduser("~/.config/autostart")
        file_path = os.path.join(autostart_dir, "kettlebrain.desktop")
        
        if enable:
            if not os.path.exists(autostart_dir):
                os.makedirs(autostart_dir)
            
            # 1. Determine Paths
            src_dir = os.path.dirname(os.path.abspath(__file__))
            app_root = os.path.dirname(src_dir)
            
            # 2. Check for Virtual Environment Python
            venv_python = os.path.join(app_root, "venv", "bin", "python")
            if os.path.exists(venv_python):
                python_exe = venv_python
            else:
                python_exe = sys.executable

            # 3. Locate Main Script
            main_script = os.path.join(app_root, "main.py")
            if not os.path.exists(main_script):
                main_script = os.path.join(src_dir, "main.py")

            # 4. Define Icon Path
            icon_path = os.path.join(src_dir, "assets", "kettle.png")
            
            # 5. Generate Content (Now with --auto-start flag)
            content = f"""[Desktop Entry]
Type=Application
Name=KettleBrain
Comment=Brewing Controller
Path={app_root}
Exec={python_exe} {main_script} --auto-start
Icon={icon_path}
Terminal=false
Categories=Utility;
"""
            try:
                with open(file_path, "w") as f:
                    f.write(content)
                
                os.chmod(file_path, 0o755)
                
                print(f"[Settings] Created executable autostart file: {file_path}")
            except Exception as e:
                print(f"[Settings] Error creating autostart: {e}")
        else:
            if os.path.exists(file_path):
                try:
                    os.remove(file_path)
                    print(f"[Settings] Removed autostart file.")
                except Exception as e:
                    print(f"[Settings] Error removing autostart: {e}")

    def _on_close(self):
        # 1. Check for unsaved changes on the System Settings tab
        if self.system_settings_dirty:
            response = messagebox.askyesnocancel(
                "Unsaved Changes",
                "You have unsaved changes in System Settings.\n\n"
                "Save changes before closing?",
                parent=self
            )
            
            if response is True:
                if not self._save_settings_no_popup():
                    return 
            elif response is None:
                return 

        # 2. Safety: Turn off relays on close
        self.relay.set_relay("Heater1", False)
        self.relay.set_relay("Heater2", False)
        self.relay.set_relay("Aux", False)
        self._cleanup_and_close()
