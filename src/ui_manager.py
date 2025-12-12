"""
src/ui_manager.py
"""
import tkinter as tk
from tkinter import ttk, messagebox
import traceback
from profile_editor import ProfileEditor
from profile_data import BrewProfile, TimeoutBehavior, SequenceStatus

class UIManager:
    
    def __init__(self, root, sequence_manager, hardware_interface):
        self.root = root
        self.sequencer = sequence_manager
        self.settings = sequence_manager.settings
        self.hw = hardware_interface 
        self.title_clicks = 0
        self.last_click_time = 0
        
        # --- WINDOW REFERENCES ---
        self.dev_window = None
        self.library_window = None
        
        # --- STATE TRACKING ---
        self.last_profile_id = None 
        self.last_active_iid = None 
        
        self.root.title("KettleBrain")
        self.root.geometry("800x600")
        self.root.resizable(False, False)
        self._configure_styles()
        
        self.current_temp_var = tk.StringVar(value="--.-°F")
        self.timer_var = tk.StringVar(value="--:--")
        self.status_text_var = tk.StringVar(value="System Idle")
        self.target_text_var = tk.StringVar(value="Target: --.-°F")
        self.next_addition_var = tk.StringVar(value="")
        self.action_btn_text = tk.StringVar(value="START")
        
        self._create_main_layout()
        self._update_loop()

    def _configure_styles(self):
        style = ttk.Style()
        style.theme_use('default') 
        style.configure('Hero.TFrame', background='#222222')
        
        # --- TEMP COLOR STYLES ---
        style.configure('HeroTemp.TLabel', font=('Arial', 80, 'bold'), background='#222222', foreground='white')
        style.configure('HeroTempRed.TLabel', font=('Arial', 80, 'bold'), background='#222222', foreground='#ff4444')
        style.configure('HeroTempBlue.TLabel', font=('Arial', 80, 'bold'), background='#222222', foreground='#3498db')
        style.configure('HeroTempGreen.TLabel', font=('Arial', 80, 'bold'), background='#222222', foreground='#00ff00')

        # --- TIMER STYLES ---
        style.configure('HeroTimer.TLabel', font=('Arial', 80, 'bold'), background='#222222', foreground='#00ff00') # Green
        style.configure('HeroTimerAlert.TLabel', font=('Arial', 80, 'bold'), background='#222222', foreground='#f1c40f') # Yellow

        # --- STATUS LABEL STYLES ---
        # Normal (Gray/White)
        style.configure('HeroStatus.TLabel', font=('Arial', 18), background='#222222', foreground='#cccccc')
        # Alert (Bold Yellow)
        style.configure('HeroStatusAlert.TLabel', font=('Arial', 24, 'bold'), background='#222222', foreground='#f1c40f')

        style.configure('HeroTarget.TLabel', font=('Arial', 14), background='#222222', foreground='#888888')
        style.configure('HeroAddition.TLabel', font=('Arial', 14, 'bold'), background='#222222', foreground='#f1c40f')
        
        style.configure('Strip.TFrame', background='#444444')
        style.configure('Controls.TFrame', background='#222222')
        
        # --- BUTTON STYLES ---
        style.configure('Action.TButton', font=('Arial', 16, 'bold'), foreground='blue')
        style.configure('Stop.TButton', font=('Arial', 16, 'bold'), foreground='red')
        style.configure('Advance.TButton', font=('Arial', 16, 'bold'), foreground='blue')
        
        # NEW: Yellow Alert Button (Yellow Background, Black Text)
        style.configure('Alert.TButton', font=('Arial', 16, 'bold'), foreground='black', background='#f1c40f')
        # Add a map to slightly darken the yellow when clicked/active so it feels responsive
        style.map('Alert.TButton', background=[('active', '#d4ac0d')], foreground=[('active', 'black')])

    def _create_main_layout(self):
        self.hero_frame = ttk.Frame(self.root, style='Hero.TFrame', height=240)
        self.hero_frame.pack(side='top', fill='x', expand=False)
        self.hero_frame.pack_propagate(False) 
        self._create_hero_widgets()
        self.hero_frame.bind("<Button-1>", self._on_header_click)

        self.strip_frame = ttk.Frame(self.root, style='Strip.TFrame', height=210)
        self.strip_frame.pack(side='top', fill='x', expand=False)
        self.strip_frame.pack_propagate(False)
        self._create_sequence_strip_widgets()

        self.controls_frame = ttk.Frame(self.root, style='Controls.TFrame', height=150)
        self.controls_frame.pack(side='bottom', fill='both', expand=True)
        self._create_control_widgets()

    def _create_hero_widgets(self):
        top_row = ttk.Frame(self.hero_frame, style='Hero.TFrame')
        top_row.pack(fill='x', pady=(20, 0), padx=30)
        
        self.lbl_temp = ttk.Label(top_row, textvariable=self.current_temp_var, style='HeroTemp.TLabel')
        self.lbl_temp.pack(side='left')
        self.lbl_temp.bind("<Button-1>", self._on_temp_click)
        
        self.lbl_timer = ttk.Label(top_row, textvariable=self.timer_var, style='HeroTimer.TLabel')
        self.lbl_timer.pack(side='right')
        
        info_stack = ttk.Frame(self.hero_frame, style='Hero.TFrame')
        info_stack.pack(side='top', pady=(10, 0))

        self.lbl_status = ttk.Label(info_stack, textvariable=self.status_text_var, style='HeroStatus.TLabel')
        self.lbl_status.pack()
        
        self.lbl_target = ttk.Label(info_stack, textvariable=self.target_text_var, style='HeroTarget.TLabel')
        self.lbl_target.pack()

        self.lbl_addition = ttk.Label(info_stack, textvariable=self.next_addition_var, style='HeroAddition.TLabel')
        self.lbl_addition.pack(pady=(5,0))

    def _create_sequence_strip_widgets(self):
        container = ttk.Frame(self.strip_frame, style='Strip.TFrame')
        container.pack(expand=True, fill='both', padx=20, pady=10)
        
        cols = ("step_num", "name", "temp", "timer", "end_mode")
        self.step_list = ttk.Treeview(container, columns=cols, show='headings', selectmode='browse')
        
        self.step_list.heading("step_num", text="#")
        self.step_list.heading("name", text="Step Name")
        self.step_list.heading("temp", text="Target")
        self.step_list.heading("timer", text="Duration")
        self.step_list.heading("end_mode", text="Next Action") 
        
        self.step_list.column("step_num", width=40, anchor="center")
        self.step_list.column("name", width=220, anchor="w")
        self.step_list.column("temp", width=80, anchor="center")
        self.step_list.column("timer", width=80, anchor="center")
        self.step_list.column("end_mode", width=100, anchor="center") 
        
        scrollbar = ttk.Scrollbar(container, orient="vertical", command=self.step_list.yview)
        self.step_list.configure(yscrollcommand=scrollbar.set)
        
        self.step_list.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        
        # --- TAG CONFIGURATION ---
        self.step_list.tag_configure('active_step', background='#2ecc71', foreground='black') 
        self.step_list.tag_configure('pending_step', background='white', foreground='black')
        self.step_list.tag_configure('done_step', background='#7f8c8d', foreground='#bdc3c7')
        
        # NEW: Alert Tag (Yellow Background, Black Text)
        self.step_list.tag_configure('alert_step', background='#f1c40f', foreground='black')

    def _refresh_step_list(self):
        for item in self.step_list.get_children():
            self.step_list.delete(item)
            
        profile = self.sequencer.current_profile
        self.last_active_iid = None 
        
        if not profile: return

        for i, step in enumerate(profile.steps):
            try:
                d_val = getattr(step, 'duration_min', 0)
                dur_str = f"{d_val}m" if d_val is not None and d_val >= 0 else "--"
            except: dur_str = "ERR"

            try:
                t_val = getattr(step, 'setpoint_f', None)
                temp_str = f"{float(t_val):.1f}°F" if t_val is not None else "--"
            except: temp_str = "ERR"
                
            try:
                b_str = str(getattr(step, 'timeout_behavior', "")).lower()
                if "auto" in b_str: mode_str = "Auto"
                else: mode_str = "WAIT"
            except: mode_str = "?"

            step_iid = str(i)
            self.step_list.insert(
                "", "end", iid=step_iid, 
                values=(i + 1, step.name, temp_str, dur_str, mode_str),
                tags=('pending_step',),
                open=True 
            )
            
            if hasattr(step, 'additions') and step.additions:
                sorted_additions = sorted(step.additions, key=lambda x: x.time_point_min, reverse=True)
                for j, add in enumerate(sorted_additions):
                    child_iid = f"{step_iid}_add_{j}"
                    add_name = f"  ↳ {add.name}"
                    add_time = f"@ {add.time_point_min}m"
                    self.step_list.insert(
                        step_iid, "end", iid=child_iid,
                        values=("", add_name, "", add_time, "Alert"),
                        tags=('pending_step',)
                    )

    def _create_control_widgets(self):
        btn_profiles = ttk.Button(self.controls_frame, text="PROFILES\nLIBRARY", command=self._on_profiles_click)
        btn_profiles.place(relx=0.05, rely=0.2, relwidth=0.2, relheight=0.6)
        
        self.btn_action = ttk.Button(self.controls_frame, textvariable=self.action_btn_text, style='Action.TButton', command=self._on_action_click)
        self.btn_action.place(relx=0.28, rely=0.15, relwidth=0.44, relheight=0.7)
        
        btn_abort = ttk.Button(self.controls_frame, text="ABORT\nSTOP", style='Stop.TButton', command=self._on_abort_click)
        btn_abort.place(relx=0.75, rely=0.2, relwidth=0.2, relheight=0.6)

    def _on_profiles_click(self):
        # 1. Clean Check: If window exists, bring to front
        if self.library_window:
            try:
                if self.library_window.winfo_exists():
                    self.library_window.lift()
                    return
                else:
                    # It's a zombie reference (destroyed but not None), clear it
                    self.library_window = None
            except:
                self.library_window = None

        # 2. Create New Window with Cleanup Callback
        # We pass a lambda to clear the reference when the window closes
        def on_close_callback():
            self.library_window = None

        self.library_window = ProfileLibraryPopup(
            self.root, 
            self.settings, 
            self.sequencer,
            on_close=on_close_callback
        )

    def _on_action_click(self):
        status = self.sequencer.status
        if status == SequenceStatus.IDLE:
            if not self.sequencer.current_profile:
                messagebox.showinfo("No Profile", "Please load a profile.")
                return
            self.sequencer.start_sequence()
        elif status == SequenceStatus.RUNNING:
            self.sequencer.pause_sequence()
        elif status == SequenceStatus.PAUSED:
            self.sequencer.resume_sequence()
        elif status == SequenceStatus.WAITING_FOR_USER:
            if self.sequencer.current_alert_text == "Step Complete":
                self.sequencer.advance_step()
            else:
                self.sequencer.resume_sequence()

    def _on_abort_click(self):
        if messagebox.askyesno("Abort Brew?", "Are you sure you want to STOP everything?"):
            self.sequencer.stop()

    def _on_header_click(self, event):
        import time
        now = time.time()
        if now - self.last_click_time > 2.0: self.title_clicks = 0
        self.title_clicks += 1
        self.last_click_time = now
        if self.title_clicks >= 5:
            self.title_clicks = 0
            if not self.hw.is_dev_mode(): self._show_safety_dialog()
            else: self.toggle_dev_tools(True)

    def _show_safety_dialog(self):
        dialog = tk.Toplevel(self.root)
        dialog.title("SAFETY INTERLOCK")
        dialog.geometry("400x300")
        dialog.configure(bg="#c0392b")
        dialog.transient(self.root) 
        dialog.wait_visibility()
        dialog.grab_set()
        tk.Label(dialog, text="⚠ WARNING ⚠", font=("Arial", 24, "bold"), bg="#c0392b", fg="white").pack(pady=20)
        tk.Label(dialog, text="ENTERING DEVELOPER MODE", bg="#c0392b", fg="white", font=("Arial", 12)).pack(pady=10)
        self.safety_slider = tk.Scale(dialog, from_=0, to=100, orient="horizontal", length=300, showvalue=0)
        self.safety_slider.pack(pady=10)
        self.safety_slider.bind("<ButtonRelease-1>", lambda e: self._check_slider(dialog))

    def _check_slider(self, dialog_window):
        val = self.safety_slider.get()
        if val >= 100:
            self.hw.set_dev_mode(True)
            style = ttk.Style()
            style.configure('Hero.TFrame', background='#e67e22')
            self.hero_frame.configure(style='Hero.TFrame')
            self.toggle_dev_tools(True)
            dialog_window.destroy()
        else: self.safety_slider.set(0)

    def toggle_dev_tools(self, is_active):
        if not is_active:
            if self.dev_window and tk.Toplevel.winfo_exists(self.dev_window): 
                self.dev_window.destroy()
            self.dev_window = None
            return
            
        if self.dev_window and tk.Toplevel.winfo_exists(self.dev_window):
            self.dev_window.lift()
            return
            
        self.dev_window = tk.Toplevel(self.root)
        self.dev_window.title("Dev Tools")
        self.dev_window.geometry("450x220") # Widened to fit buttons
        self.dev_window.configure(bg="#333333")
        
        def _on_close():
            self.dev_window.destroy()
            self.dev_window = None
        self.dev_window.protocol("WM_DELETE_WINDOW", _on_close)
        
        # Header
        tk.Label(self.dev_window, text="Temperature Simulator", fg="white", bg="#333333", font=("Arial", 12, "bold")).pack(pady=10)
        
        # Container for Buttons + Slider
        control_frame = tk.Frame(self.dev_window, bg="#333333")
        control_frame.pack(fill="x", padx=10, pady=5)

        # --- Logic Functions ---
        def update_sim_temp(val): 
            self.hw.set_virtual_temp(float(val))

        # We must define the slider first so buttons can reference it
        slider = tk.Scale(
            control_frame, 
            from_=50, 
            to=220, 
            orient="horizontal", 
            bg="#333333", 
            fg="white", 
            highlightthickness=0, 
            command=update_sim_temp,
            length=250
        )
        # Set initial value
        current_temp = self.hw.read_temperature()
        slider.set(current_temp)

        def dec_temp():
            val = slider.get()
            new_val = max(50, val - 1) # Respect min limit
            slider.set(new_val)
            update_sim_temp(new_val) # Force update

        def inc_temp():
            val = slider.get()
            new_val = min(220, val + 1) # Respect max limit
            slider.set(new_val)
            update_sim_temp(new_val) # Force update

        # --- Layout ---
        # Decrease Button (<)
        btn_down = tk.Button(control_frame, text="<", font=("Arial", 12, "bold"), width=3, command=dec_temp)
        btn_down.pack(side="left", padx=5)

        # Slider (Center)
        slider.pack(side="left", fill="x", expand=True, padx=5)

        # Increase Button (>)
        btn_up = tk.Button(control_frame, text=">", font=("Arial", 12, "bold"), width=3, command=inc_temp)
        btn_up.pack(side="left", padx=5)

        # Force Next Step Button
        btn_skip = tk.Button(self.dev_window, text="⏭ Force Next Step", bg="#e67e22", fg="white", font=("Arial", 10, "bold"), command=self._dev_force_next)
        btn_skip.pack(pady=15, fill="x", padx=20)

    def _dev_force_next(self): self.sequencer.advance_step()

    def _on_temp_click(self, event):
        if self.hw.is_dev_mode(): self.toggle_dev_tools(True)

    def _update_loop(self):
        try:
            if hasattr(self.sequencer, 'update'): self.sequencer.update()
            self.update_ui_from_state()
        except Exception as e:
            print(f"[UI ERROR] Loop crashed: {e}")
            traceback.print_exc()
        self.root.after(100, self._update_loop)

    def update_ui_from_state(self):
        t = self.sequencer.current_temp
        self.current_temp_var.set(f"{t:.1f}°F")
        
        st = self.sequencer.status
        tgt = self.sequencer.get_target_temp()
        
        # Check if we are in an Alert State
        is_mid_step_alert = (st == SequenceStatus.WAITING_FOR_USER and self.sequencer.current_alert_text != "Step Complete")

        # --- 1. Temp Color Logic ---
        new_style = 'HeroTemp.TLabel'
        if st in [SequenceStatus.RUNNING, SequenceStatus.WAITING_FOR_USER] and tgt is not None and tgt > 0:
            diff = t - tgt
            if diff < -1.0: new_style = 'HeroTempBlue.TLabel'
            elif diff > 1.0: new_style = 'HeroTempRed.TLabel'
            else: new_style = 'HeroTempGreen.TLabel'
        self.lbl_temp.configure(style=new_style)

        # --- 2. Timer & Status Logic ---
        self.timer_var.set(self.sequencer.get_display_timer())
        
        # Get the raw status message (e.g., "Dough In")
        raw_msg = self.sequencer.get_status_message()

        if is_mid_step_alert:
            self.lbl_timer.configure(style='HeroTimerAlert.TLabel')   # Yellow Timer
            self.lbl_status.configure(style='HeroStatusAlert.TLabel') # Bold Yellow Status
            
            # FIX: Sanitize the raw message to prevent "ALERT: ALERT: ..."
            clean_msg = raw_msg.replace("ALERT: ", "").replace("ALERT:", "").strip()
            self.status_text_var.set(f"ALERT: {clean_msg}")
        else:
            self.lbl_timer.configure(style='HeroTimer.TLabel')        # Green Timer
            self.lbl_status.configure(style='HeroStatus.TLabel')      # Gray Status
            self.status_text_var.set(raw_msg)

        self.next_addition_var.set(self.sequencer.get_upcoming_additions())
        
        if tgt: self.target_text_var.set(f"Target: {tgt:.1f}°F")
        else: self.target_text_var.set("")

        # --- 3. Sequence Strip Rendering ---
        current_idx = self.sequencer.current_step_index
        profile = self.sequencer.current_profile
        
        current_pid = profile.id if profile else None
        if current_pid != self.last_profile_id:
             self._refresh_step_list()
             self.last_profile_id = current_pid

        if profile and current_idx is not None and 0 <= current_idx < len(profile.steps):
            step = profile.steps[current_idx]
            step_iid = str(current_idx)
            active_cursor_iid = step_iid
            
            alert_text = self.sequencer.current_alert_text

            if hasattr(step, 'additions') and step.additions:
                children = self.step_list.get_children(step_iid)
                sorted_adds = sorted(step.additions, key=lambda x: x.time_point_min, reverse=True)
                for j, child_iid in enumerate(children):
                    if j < len(sorted_adds):
                        add_obj = sorted_adds[j]
                        if is_mid_step_alert and alert_text and (add_obj.name in alert_text):
                            active_cursor_iid = child_iid
                            break

            for i, parent_iid in enumerate(self.step_list.get_children()):
                if i < current_idx:
                    self.step_list.item(parent_iid, tags=('done_step',))
                    for child in self.step_list.get_children(parent_iid):
                        self.step_list.item(child, tags=('done_step',))
                elif i > current_idx:
                    self.step_list.item(parent_iid, tags=('pending_step',))
                    for child in self.step_list.get_children(parent_iid):
                        self.step_list.item(child, tags=('pending_step',))
                else: 
                    self.step_list.item(parent_iid, tags=('active_step',))
                    children = self.step_list.get_children(parent_iid)
                    current_step_obj = profile.steps[current_idx]
                    
                    if hasattr(current_step_obj, 'additions') and current_step_obj.additions:
                        sorted_adds = sorted(current_step_obj.additions, key=lambda x: x.time_point_min, reverse=True)
                        for j, child_iid in enumerate(children):
                            if j < len(sorted_adds):
                                add_obj = sorted_adds[j]
                                if child_iid == active_cursor_iid:
                                    if is_mid_step_alert:
                                        self.step_list.item(child_iid, tags=('alert_step',))
                                    else:
                                        self.step_list.item(child_iid, tags=('active_step',))
                                elif add_obj.triggered:
                                    self.step_list.item(child_iid, tags=('done_step',))
                                else:
                                    self.step_list.item(child_iid, tags=('pending_step',))

            if active_cursor_iid != self.last_active_iid:
                self.step_list.see(active_cursor_iid)
                self.step_list.selection_set(active_cursor_iid)
                self.last_active_iid = active_cursor_iid

        # --- 4. Button State Logic ---
        st = self.sequencer.status
        self.btn_action.state(['!disabled']) 
        
        if st == SequenceStatus.IDLE:
            self.action_btn_text.set("START BREW")
            self.btn_action.configure(style='Action.TButton') 

        elif st == SequenceStatus.RUNNING:
            self.action_btn_text.set("PAUSE")
            self.btn_action.configure(style='Action.TButton') 

        elif st == SequenceStatus.PAUSED:
            self.action_btn_text.set("RESUME")
            self.btn_action.configure(style='Action.TButton') 
            
        elif st == SequenceStatus.WAITING_FOR_USER:
            alert_txt = self.sequencer.current_alert_text
            
            if is_mid_step_alert:
                # BUTTON SAYS "ACKNOWLEDGE" (Yellow Background)
                self.action_btn_text.set(f"ACKNOWLEDGE:\n{alert_txt}")
                self.btn_action.configure(style='Alert.TButton')
            else:
                # BUTTON SAYS "ADVANCE" (Blue Text)
                step_num = current_idx + 1
                if current_idx + 1 < len(profile.steps):
                    next_step_num = step_num + 1
                    self.action_btn_text.set(f"Step {step_num} COMPLETE\nADVANCE to Step {next_step_num}")
                else:
                    self.action_btn_text.set(f"Step {step_num} COMPLETE\nFINISH BREW")
                self.btn_action.configure(style='Advance.TButton')
            
        elif st == SequenceStatus.COMPLETED:
            self.action_btn_text.set("COMPLETE")
            self.btn_action.state(['disabled'])

class ProfileLibraryPopup(tk.Toplevel):
    def __init__(self, parent, settings_manager, sequencer, on_close=None):
        super().__init__(parent)
        self.title("Profile Library")
        self.geometry("600x400")
        self.transient(parent)
        
        self.settings = settings_manager
        self.sequencer = sequencer
        self.on_close_callback = on_close
        self.editor_window = None
        
        # 1. Build UI first
        self._layout()
        self._refresh_list()
        
        # 2. Setup Closing Protocol
        self.protocol("WM_DELETE_WINDOW", self.close) 
        
        # 3. CRITICAL FIX: Safe Launch Sequence
        # We must center/update the window BEFORE we grab focus.
        self.update_idletasks() 
        
        # Center the window relative to parent (Optional but nice)
        x = parent.winfo_rootx() + 50
        y = parent.winfo_rooty() + 50
        self.geometry(f"+{x}+{y}")
        
        # 4. Wait for visibility BEFORE locking the UI
        # This prevents the "Freeze" if the window fails to map immediately
        self.wait_visibility()
        
        # 5. Now it is safe to grab focus
        self.grab_set() 
        self.focus_set() 

    def close(self):
        # 1. Release the UI Lock immediately
        try:
            self.grab_release()
        except:
            pass
        
        # 2. Fire the cleanup callback to notify UIManager
        if self.on_close_callback:
            try:
                self.on_close_callback()
            except:
                pass
            
        # 3. Return focus to main app and destroy self
        if self.master:
            self.master.focus_set()
        self.destroy()

    def _layout(self):
        toolbar = ttk.Frame(self, padding=5)
        toolbar.pack(fill='x', side='bottom')
        
        ttk.Button(toolbar, text="Load Profile", command=self._load_selected).pack(side='right', padx=5)
        ttk.Button(toolbar, text="Edit", command=self._edit_selected).pack(side='right', padx=5)
        ttk.Button(toolbar, text="Delete", command=self._delete_selected).pack(side='right', padx=5)
        ttk.Button(toolbar, text="+ New Profile", command=self._create_new).pack(side='left', padx=5)
        self.tree = ttk.Treeview(self, columns=("steps", "date"), show="tree headings")
        self.tree.heading("#0", text="Profile Name")
        self.tree.heading("steps", text="Steps")
        self.tree.heading("date", text="Created")
        self.tree.column("steps", width=50, anchor='center')
        self.tree.column("date", width=100)
        self.tree.pack(fill='both', expand=True, padx=10, pady=10)

    def _refresh_list(self):
        self.tree.delete(*self.tree.get_children())
        profiles = self.settings.get_all_profiles()
        for p in profiles:
            self.tree.insert("", "end", iid=p.id, text=p.name, values=(len(p.steps), p.created_date))

    def _get_selected_id(self):
        sel = self.tree.selection()
        if not sel: return None
        return sel[0]

    def _load_selected(self):
        pid = self._get_selected_id()
        if not pid: return
        profile = self.settings.get_profile_by_id(pid)
        if profile:
            self.sequencer.load_profile(profile)
            self.close()

    def _edit_selected(self):
        if self.editor_window:
            try:
                if self.editor_window.winfo_exists():
                    self.editor_window.lift()
                    return
                else:
                    self.editor_window = None
            except:
                self.editor_window = None

        pid = self._get_selected_id()
        if not pid: return
        profile = self.settings.get_profile_by_id(pid)
        if profile:
            self.editor_window = ProfileEditor(self, profile, on_save_callback=self._on_editor_save)

    def _create_new(self):
        if self.editor_window:
            try:
                if self.editor_window.winfo_exists():
                    self.editor_window.lift()
                    return
                else:
                    self.editor_window = None
            except:
                self.editor_window = None
            
        new_p = BrewProfile(name="New Profile")
        self.editor_window = ProfileEditor(self, new_p, on_save_callback=self._on_editor_save)

    def _delete_selected(self):
        pid = self._get_selected_id()
        if not pid: return
        if messagebox.askyesno("Confirm", "Delete this profile?"):
            self.settings.delete_profile(pid)
            self._refresh_list()

    def _on_editor_save(self, profile):
        self.settings.save_profile(profile)
        self._refresh_list()
