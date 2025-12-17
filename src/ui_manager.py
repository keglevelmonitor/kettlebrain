"""
src/ui_manager.py
"""
import tkinter as tk
from tkinter import ttk, messagebox
import traceback
from datetime import datetime, timedelta # <--- ADD THIS
from profile_data import BrewProfile, TimeoutBehavior, SequenceStatus
from settings_ui import SettingsPopup
import uuid
import copy
from utils import UnitUtils

class UIManager:
    
    def __init__(self, root, sequence_manager, hardware_interface):
        self.root = root
        self.sequencer = sequence_manager
        self.settings = sequence_manager.settings
        self.hw = hardware_interface 
        self.title_clicks = 0
        self.last_click_time = 0
        
        self.dev_window = None
        self.settings_window = None
        self.delayed_start_window = None  # <--- ADD THIS LINE
        
        self.last_profile_id = None 
        self.last_active_iid = None 
        
        self.root.title("KettleBrain")
        
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        
        target_w = 800
        target_h = 480
        
        if screen_w == target_w and screen_h == target_h:
            self.root.attributes('-fullscreen', True)
            self.root.bind("<Escape>", lambda e: self.root.attributes('-fullscreen', False))
        else:
            self.root.geometry(f"{target_w}x{target_h}")
            self.root.resizable(False, False)

        self._configure_styles()
        
        self.current_temp_var = tk.StringVar(value="--.-°F")
        self.timer_var = tk.StringVar(value="--:--:--") 
        
        self.target_sub_var = tk.StringVar(value="Target: --")
        self.elapsed_sub_var = tk.StringVar(value="Elapsed: 00:00")
        
        self.status_text_var = tk.StringVar(value="System Idle")
        self.target_text_var = tk.StringVar(value="") 
        
        self.next_addition_var = tk.StringVar(value="")
        self.action_btn_text = tk.StringVar(value="START")
        
        self._create_main_layout()
        self._update_loop()
        
    def _open_delayed_start(self):
        # 1. AGGRESSIVE GRAB CLEANUP
        try:
            grabber = self.root.grab_current()
            if grabber:
                grabber.grab_release()
        except: pass

        # 2. DECOUPLE
        self.root.after(50, self._real_delayed_start_logic)

    def _real_delayed_start_logic(self):
        # 0. PREVENT DUPLICATES
        if self.delayed_start_window:
            try:
                if self.delayed_start_window.winfo_exists():
                    self.delayed_start_window.lift()
                    return
                else:
                    self.delayed_start_window = None
            except:
                self.delayed_start_window = None

        # --- HELPER: CLEANUP REFERENCE ---
        def cleanup_ref():
            self.delayed_start_window = None

        # 1. If Active -> Open Action Dialog
        if self.sequencer.status == SequenceStatus.DELAYED_WAIT:
            
            def do_cancel():
                self.sequencer.cancel_delayed_mode()
                
            def do_edit():
                # Capture current data AND Context before stopping
                data = {
                    'vol': getattr(self.sequencer, 'delayed_vol', 8.0),
                    'temp': getattr(self.sequencer, 'delayed_target_temp', 154.0),
                    'time_str': getattr(self.sequencer, 'delayed_ready_time_str', "")
                }
                was_auto = getattr(self.sequencer, 'delayed_is_auto', True)
                
                # Stop the current Delay (Clears timer)
                self.sequencer.stop() 
                
                # --- FIX: RESTORE CONTEXT IMMEDIATELY ---
                # If we were in Manual mode, force the system back to MANUAL state 
                # so the background UI doesn't flip to Auto (IDLE).
                if not was_auto:
                    self.sequencer.enter_manual_mode()
                # ----------------------------------------
                
                # Re-open popup with data AND preserved context
                self.delayed_start_window = DelayedStartPopup(
                    self.root, 
                    self.sequencer, 
                    self.settings, 
                    initial_data=data, 
                    initial_context=was_auto
                )

            self.delayed_start_window = DelayedStartActionDialog(
                self.root, 
                on_cancel=do_cancel, 
                on_edit=do_edit,
                on_cleanup=cleanup_ref
            )
            return

        # 2. Safety Check
        can_proceed = False
        if self.sequencer.status == SequenceStatus.IDLE:
             can_proceed = True
        elif self.sequencer.status == SequenceStatus.MANUAL:
            if not self.sequencer.is_manual_running: 
                can_proceed = True

        if not can_proceed:
             messagebox.showwarning("System Busy", "Stop the current process before setting a Delayed Start.", parent=self.root)
             return

        # 3. Open Popup (New Mode)
        self.delayed_start_window = DelayedStartPopup(self.root, self.sequencer, self.settings)
        
    def _request_mode_switch(self, target_mode):
        # 1. SAFETY: Force focus to root
        try: self.root.focus_set()
        except: pass

        current_stat = self.sequencer.status
        is_active = current_stat in [SequenceStatus.RUNNING, SequenceStatus.PAUSED, SequenceStatus.WAITING_FOR_USER]
        
        # Define the actual switch logic
        def perform_switch():
            self.sequencer.stop() # Resets everything
            
            if target_mode == "MANUAL":
                self.sequencer.enter_manual_mode()
                self.view_manual.lift()
                
                self._set_btn_color(self.btn_mode_manual, '#2ecc71', 'black')
                self._set_btn_color(self.btn_mode_auto, '#e0e0e0', '#0044CC')
                
                self.action_btn_text.set("START") 
                self.btn_action.config(state='disabled') 
            else:
                self.sequencer.status = SequenceStatus.IDLE
                self.view_auto.lift()
                
                self._set_btn_color(self.btn_mode_auto, '#2ecc71', 'black')
                self._set_btn_color(self.btn_mode_manual, '#e0e0e0', '#0044CC')
                
                self.action_btn_text.set("START")
                self.btn_action.config(state='normal')

            # Ensure layout updates safely
            try:
                self.root.update_idletasks()
                self.root.focus_set()
            except: pass

        # If active, warn user via Callback Dialog
        if is_active:
            CustomConfirmDialog(
                self.root,
                "Switch Modes?", 
                "Switching modes will STOP the current process.\nAre you sure?",
                callback=perform_switch
            )
        else:
            # If idle, just do it immediately
            perform_switch()
            
    def _configure_styles(self):
        style = ttk.Style()
        style.theme_use('default') 
        style.configure('Hero.TFrame', background='#222222')
        
        # Increased fonts back to 48 (was 38)
        style.configure('HeroTemp.TLabel', font=('Arial', 48, 'bold'), background='#222222', foreground='white')
        style.configure('HeroTempRed.TLabel', font=('Arial', 48, 'bold'), background='#222222', foreground='#ff4444')
        style.configure('HeroTempBlue.TLabel', font=('Arial', 48, 'bold'), background='#222222', foreground='#3498db')
        style.configure('HeroTempGreen.TLabel', font=('Arial', 48, 'bold'), background='#222222', foreground='#00ff00')

        style.configure('HeroTimer.TLabel', font=('Arial', 48, 'bold'), background='#222222', foreground='#00ff00') 
        style.configure('HeroTimerAlert.TLabel', font=('Arial', 48, 'bold'), background='#222222', foreground='#f1c40f') 

        # Sub-info (Target/Elapsed)
        style.configure('HeroSub.TLabel', font=('Arial', 16, 'bold'), background='#222222', foreground='#cccccc')

        # Status / Alerts
        style.configure('HeroStatus.TLabel', font=('Arial', 18, 'bold'), background='#222222', foreground='#cccccc')
        style.configure('HeroStatusAlert.TLabel', font=('Arial', 18, 'bold'), background='#222222', foreground='#f1c40f')
        style.configure('HeroAddition.TLabel', font=('Arial', 12, 'bold'), background='#222222', foreground='#f1c40f')
        
        style.configure('Strip.TFrame', background='#444444')
        style.configure('Controls.TFrame', background='#222222')
        
        style.configure('Action.TButton', font=('Arial', 14, 'bold'), foreground='blue')
        style.configure('Stop.TButton', font=('Arial', 14, 'bold'), foreground='red')
        style.configure('Advance.TButton', font=('Arial', 14, 'bold'), foreground='blue')
        
        style.configure('Alert.TButton', font=('Arial', 14, 'bold'), foreground='black', background='#f1c40f')
        style.map('Alert.TButton', background=[('active', '#d4ac0d')], foreground=[('active', 'black')])

    def _set_btn_color(self, btn, bg, fg):
        """
        Helper to set button colors and bind hover inversion effects.
        Includes logic to prevent redundant updates (fixing hover flicker).
        """
        try:
            # Prevent resetting if the base colors haven't changed.
            # This allows the <Enter> hover state to persist during UI loops.
            if getattr(btn, "_current_base_bg", None) == bg and getattr(btn, "_current_base_fg", None) == fg:
                return

            btn.config(bg=bg, fg=fg, activebackground=fg, activeforeground=bg)
            
            # Store the current base colors to track changes
            btn._current_base_bg = bg
            btn._current_base_fg = fg
            
            # Unbind previous events to prevent stacking
            btn.unbind("<Enter>")
            btn.unbind("<Leave>")
            
            # Bind hover effects (Invert)
            # We capture 'bg' and 'fg' in the lambda defaults so the event 
            # always knows the correct "Base" colors to swap to/from.
            btn.bind("<Enter>", lambda e, b=bg, f=fg: btn.config(bg=f, fg=b))
            btn.bind("<Leave>", lambda e, b=bg, f=fg: btn.config(bg=b, fg=f))
        except Exception:
            pass
            
    def _disable_custom_btn(self, btn):
        """Helper to visually and functionally disable a button."""
        try:
            # Set Tkinter state to disabled (prevents clicks) and set grey text
            btn.config(state='disabled', disabledforeground='#bdc3c7')
            
            # Explicitly remove hover listeners so colors don't flip
            btn.unbind("<Enter>")
            btn.unbind("<Leave>")
            
            # Reset state tracking so _set_btn_color knows to re-bind events 
            # when this button is re-enabled later.
            if hasattr(btn, "_current_base_bg"): del btn._current_base_bg
            if hasattr(btn, "_current_base_fg"): del btn._current_base_fg
        except Exception:
            pass
    
    def _create_main_layout(self):
        # 1. HERO FRAME (Top) - Increased Height for stacked data + status lines
        self.hero_frame = ttk.Frame(self.root, style='Hero.TFrame', height=220)
        self.hero_frame.pack(side='top', fill='x', expand=False)
        self.hero_frame.pack_propagate(False) 
        self._create_hero_widgets()
        
        self.hero_frame.bind("<Button-1>", self._on_header_click)

        # 2. STRIP FRAME (Middle) - Reduced Height
        self.strip_frame = ttk.Frame(self.root, style='Strip.TFrame', height=180)
        self.strip_frame.pack(side='top', fill='x', expand=False)
        self.strip_frame.pack_propagate(False)
        self._create_sequence_strip_widgets()

        # 3. CONTROLS FRAME (Bottom)
        self.controls_frame = ttk.Frame(self.root, style='Controls.TFrame', height=80)
        self.controls_frame.pack(side='bottom', fill='both', expand=True)
        self._create_control_widgets()

    def _create_hero_widgets(self):
        # 1. TOP ROW: Temp | Delayed Start | Timer
        top_data_row = ttk.Frame(self.hero_frame, style='Hero.TFrame')
        top_data_row.pack(fill='both', expand=True, pady=0, padx=10)
        
        self._bind_header_clicks(top_data_row)
        
        # --- LEFT STACK: TEMP ---
        left_stack = ttk.Frame(top_data_row, style='Hero.TFrame')
        left_stack.pack(side='left', anchor='center', expand=True)
        self._bind_header_clicks(left_stack)
        
        self.lbl_temp = ttk.Label(left_stack, textvariable=self.current_temp_var, style='HeroTemp.TLabel')
        self.lbl_temp.pack(side='top', anchor='center')
        self.lbl_temp.bind("<Button-1>", self._on_temp_or_header_click)
        
        self.lbl_sub_target = ttk.Label(left_stack, textvariable=self.target_sub_var, style='HeroSub.TLabel')
        self.lbl_sub_target.pack(side='top', anchor='center')
        self._bind_header_clicks(self.lbl_sub_target)

        # --- RIGHT STACK: TIMER ---
        right_stack = ttk.Frame(top_data_row, style='Hero.TFrame')
        right_stack.pack(side='right', anchor='center', expand=True)
        self._bind_header_clicks(right_stack)
        
        self.lbl_timer = ttk.Label(right_stack, textvariable=self.timer_var, style='HeroTimer.TLabel')
        self.lbl_timer.pack(side='top', anchor='center')
        self._bind_header_clicks(self.lbl_timer)
        
        self.lbl_sub_elapsed = ttk.Label(right_stack, textvariable=self.elapsed_sub_var, style='HeroSub.TLabel')
        self.lbl_sub_elapsed.pack(side='top', anchor='center')
        self._bind_header_clicks(self.lbl_sub_elapsed)

        # --- CENTER STACK: DELAYED START BUTTON ---
        center_stack = ttk.Frame(top_data_row, style='Hero.TFrame')
        center_stack.pack(side='left', fill='y', expand=False, padx=2)
        self._bind_header_clicks(center_stack)
        
        self.btn_delayed = tk.Button(center_stack, text="DELAYED\nSTART", font=('Arial', 14, 'bold'),
                                     width=18, height=4,
                                     command=self._open_delayed_start)
        self._set_btn_color(self.btn_delayed, '#e0e0e0', '#0044CC')
        self.btn_delayed.pack(expand=True, anchor='center')

        # 2. STATUS ROW (Packed below)
        msg_stack = ttk.Frame(self.hero_frame, style='Hero.TFrame')
        msg_stack.pack(side='bottom', fill='x', pady=(0, 2))
        self._bind_header_clicks(msg_stack)

        self.lbl_status = ttk.Label(msg_stack, textvariable=self.status_text_var, style='HeroStatus.TLabel', justify='center')
        self.lbl_status.pack(side='top', anchor='center')
        self._bind_header_clicks(self.lbl_status)
        
        self.lbl_addition = ttk.Label(msg_stack, textvariable=self.next_addition_var, style='HeroAddition.TLabel', justify='center')
        self.lbl_addition.pack(side='top', anchor='center')
        self._bind_header_clicks(self.lbl_addition)

        # --- 3. OVERLAY INDICATORS (Floating on top) ---
        
        # A. HEATER BADGES (Top Left) - Split for 1000W and 800W
        # Heater 1 (1000W) - Red
        self.lbl_h1 = tk.Label(self.hero_frame, text="1000W", font=('Arial', 10, 'bold'),
                               bg='#e74c3c', fg='white', padx=6, pady=2, relief='flat')
        
        # Heater 2 (800W) - Orange/Red (Distinct but related)
        self.lbl_h2 = tk.Label(self.hero_frame, text="800W", font=('Arial', 10, 'bold'),
                               bg='#e67e22', fg='white', padx=6, pady=2, relief='flat')
        
        # B. HEARTBEAT PULSE (Top Right)
        self.cv_heartbeat = tk.Canvas(self.hero_frame, width=16, height=16, 
                                      bg='#222222', highlightthickness=0)
        self.cv_heartbeat.place(relx=1.0, x=-25, y=10, anchor='ne')
        
        self.heartbeat_id = self.cv_heartbeat.create_oval(2, 2, 14, 14, fill='#444444', outline='')

    def _bind_header_clicks(self, widget):
        widget.bind("<Button-1>", self._on_header_click)

    def _create_sequence_strip_widgets(self):
        # We create two "Views" inside the strip_frame:
        # 1. view_auto: The Step List (Treeview)
        # 2. view_manual: The ManualPanel controls
        
        # --- VIEW 1: AUTO STEP LIST ---
        self.view_auto = ttk.Frame(self.strip_frame, style='Strip.TFrame')
        self.view_auto.pack(fill='both', expand=True) 
        
        # Scrollbar
        scrollbar = ttk.Scrollbar(self.view_auto)
        scrollbar.pack(side='right', fill='y')
        
        # Treeview
        columns = ('step_num', 'name', 'target', 'duration', 'ready', 'action')
        self.step_list = ttk.Treeview(self.view_auto, columns=columns, show='headings', 
                                      yscrollcommand=scrollbar.set, height=5)
        
        # Column Config
        self.step_list.heading('step_num', text='#')
        self.step_list.column('step_num', width=40, anchor='center')
        
        self.step_list.heading('name', text='Step Name')
        self.step_list.column('name', width=220, anchor='w')
        
        self.step_list.heading('target', text='Target')
        self.step_list.column('target', width=80, anchor='center')
        
        self.step_list.heading('duration', text='Duration')
        self.step_list.column('duration', width=80, anchor='center')

        self.step_list.heading('ready', text='Ready At')
        self.step_list.column('ready', width=80, anchor='center')
        
        self.step_list.heading('action', text='Next Action')
        self.step_list.column('action', width=110, anchor='center')
        
        # Tags for styling
        self.step_list.tag_configure('done_step', foreground='#777777') 
        self.step_list.tag_configure('active_step', background='#34495e', foreground='white', font=('Arial', 12, 'bold'))
        self.step_list.tag_configure('pending_step', foreground='black')
        self.step_list.tag_configure('alert_step', background='#f1c40f', foreground='black', font=('Arial', 12, 'bold'))

        self.step_list.pack(side='left', fill='both', expand=True)
        scrollbar.config(command=self.step_list.yview)

        # --- VIEW 2: MANUAL PANEL ---
        # Pass status_text_var so manual panel can write "Ready At" to the header
        self.view_manual = ManualPanel(self.strip_frame, self.sequencer, self.settings, self.status_text_var)
        
    def _set_layout_mode(self, mode="AUTO"):
        """
        Dynamically adjusts frame heights to give Manual Mode more space 
        by 'borrowing' unused vertical space from the Hero section.
        """
        # Prevent redundant updates if already in the correct state
        current_hero_h = self.hero_frame.winfo_height()
        
        target_hero_h = 220
        target_strip_h = 180
        
        if mode == "MANUAL":
            # Shrink Hero (Hide empty status lines), Grow Strip (For big sliders)
            target_hero_h = 130 
            target_strip_h = 270
        else:
            # Restore Standard Auto Layout
            target_hero_h = 220
            target_strip_h = 180

        # Apply changes only if needed to avoid jitter
        # Note: We use configure(height=...) because pack_propagate is False
        if current_hero_h != target_hero_h:
            self.hero_frame.configure(height=target_hero_h)
            self.strip_frame.configure(height=target_strip_h)

    def _configure_step_list_tags(self):
        self.step_list.tag_configure('active_step', background='#2ecc71', foreground='black') 
        self.step_list.tag_configure('pending_step', background='white', foreground='black')
        self.step_list.tag_configure('done_step', background='#7f8c8d', foreground='#bdc3c7')
        self.step_list.tag_configure('alert_step', background='#f1c40f', foreground='black')

    def _refresh_step_list(self):
        for item in self.step_list.get_children():
            self.step_list.delete(item)
            
        profile = self.sequencer.current_profile
        self.last_active_iid = None 
        
        if not profile: return

        # Trigger prediction update before rendering
        if hasattr(self.sequencer, 'update_predictions'):
            self.sequencer.update_predictions()

        for i, step in enumerate(profile.steps):
            try:
                d_val = getattr(step, 'duration_min', 0)
                dur_str = f"{d_val}m" if d_val is not None and d_val >= 0 else "--"
            except: dur_str = "ERR"

            try:
                t_val = getattr(step, 'setpoint_f', None)
                temp_str = UnitUtils.format_temp(t_val, self.settings)
            except: temp_str = "ERR"
                
            try:
                b_str = str(getattr(step, 'timeout_behavior', "")).lower()
                if "auto" in b_str: mode_str = "Auto"
                else: mode_str = "WAIT"
            except: mode_str = "?"

            # Retrieve predicted time (added by sequencer.update_predictions)
            ready_str = getattr(step, 'predicted_ready_time', "")
            if ready_str is None: ready_str = ""

            step_iid = str(i)
            
            # Insert Row (Note: Added ready_str to values)
            self.step_list.insert(
                "", "end", iid=step_iid, 
                values=(i + 1, step.name, temp_str, dur_str, ready_str, mode_str),
                tags=('pending_step',),
                open=True 
            )
            
            if hasattr(step, 'additions') and step.additions:
                sorted_additions = sorted(step.additions, key=lambda x: x.time_point_min, reverse=True)
                for j, add in enumerate(sorted_additions):
                    child_iid = f"{step_iid}_add_{j}"
                    add_name = f"  ↳ {add.name}"
                    add_time = f"@ {add.time_point_min}m"
                    
                    # Insert Addition (Must provide empty string for 'ready' column to align)
                    self.step_list.insert(
                        step_iid, "end", iid=child_iid,
                        values=("", add_name, "", add_time, "", "Alert"),
                        tags=('pending_step',)
                    )

    def _create_control_widgets(self):
        # LEFT: Mode Toggle (Stacked) - AUTO ON TOP
        f_mode = ttk.Frame(self.controls_frame, style='Controls.TFrame')
        f_mode.place(relx=0.02, rely=0.1, relwidth=0.2, relheight=0.8)
        
        # Auto on Top
        self.btn_mode_auto = tk.Button(f_mode, text="AUTO", font=('Arial', 12, 'bold'),
                                       command=lambda: self._request_mode_switch("AUTO"))
        self.btn_mode_auto.pack(side='top', fill='both', expand=True, pady=1)
        
        # Manual on Bottom
        self.btn_mode_manual = tk.Button(f_mode, text="MANUAL", font=('Arial', 12, 'bold'),
                                         command=lambda: self._request_mode_switch("MANUAL"))
        self.btn_mode_manual.pack(side='top', fill='both', expand=True, pady=1)

        # CENTER: Main Action - Converted to tk.Button for consistent hover behavior
        self.btn_action = tk.Button(self.controls_frame, textvariable=self.action_btn_text, 
                                    font=('Arial', 14, 'bold'),
                                    command=self._on_action_click)
        self.btn_action.place(relx=0.25, rely=0.1, relwidth=0.5, relheight=0.8)
        self._set_btn_color(self.btn_action, '#e0e0e0', '#0044CC') # Gray BG, Dark Blue Text

        # RIGHT: Stop / Settings (Stacked)
        f_right = ttk.Frame(self.controls_frame, style='Controls.TFrame')
        f_right.place(relx=0.78, rely=0.1, relwidth=0.2, relheight=0.8)
        
        # STOP: Red BG, White Text
        btn_stop = tk.Button(f_right, text="STOP", font=('Arial', 12, 'bold'), 
                             command=self._on_abort_click)
        self._set_btn_color(btn_stop, '#e74c3c', 'white')
        btn_stop.pack(side='top', fill='both', expand=True, pady=1)
        
        # SETTINGS: Match Start/Pause (Gray BG, Dark Blue Text)
        btn_settings = tk.Button(f_right, text="SETTINGS", font=('Arial', 12, 'bold'),
                                 command=self._on_settings_click)
        self._set_btn_color(btn_settings, '#e0e0e0', '#0044CC')
        btn_settings.pack(side='top', fill='both', expand=True, pady=1)

    def _on_settings_click(self):
        # 1. AGGRESSIVE GRAB CLEANUP
        # If any window holds a grab (input lock), force release it immediately.
        # This prevents the 'frozen button' state.
        try:
            grabber = self.root.grab_current()
            if grabber:
                grabber.grab_release()
        except: pass

        # 2. DECOUPLE
        # Don't run logic inside the button click event.
        # Schedule it for 50ms later to let the UI loop breathe and the button release visually.
        self.root.after(50, self._real_settings_logic)

    def _real_settings_logic(self):
        # 1. CHECK EXISTING WINDOW
        if self.settings_window:
            try:
                if self.settings_window.winfo_exists():
                    self.settings_window.lift()
                    return
                else:
                    self.settings_window = None
            except:
                self.settings_window = None

        # 2. OPEN SETTINGS POPUP
        self.settings_window = SettingsPopup(
            self.root, 
            self.settings, 
            self.hw, 
            self.sequencer.relay, 
            self.sequencer
        )

    def _on_action_click(self):
        st = self.sequencer.status
        
        # --- MANUAL MODE ACTION ---
        if st == SequenceStatus.MANUAL:
            # Toggles between START (Active) and PAUSE (Inactive)
            self.sequencer.toggle_manual_playback()
            return

        # --- AUTO MODE ACTIONS ---
        if st == SequenceStatus.IDLE:
            self.sequencer.start_sequence()
        elif st == SequenceStatus.RUNNING:
            self.sequencer.pause_sequence() # FIXED: Was .pause()
        elif st == SequenceStatus.PAUSED:
            self.sequencer.resume_sequence() # FIXED: Was .resume()
        elif st == SequenceStatus.WAITING_FOR_USER:
            self.sequencer.advance_step()

    def _show_no_profile_dialog(self):
        dlg = tk.Toplevel(self.root)
        dlg.title("No Profile Loaded")
        dlg.geometry("400x180")
        dlg.transient(self.root)
        
        # Center it
        x = self.root.winfo_rootx() + (self.root.winfo_width() // 2) - 200
        y = self.root.winfo_rooty() + (self.root.winfo_height() // 2) - 90
        dlg.geometry(f"+{x}+{y}")
        
        # UI
        lbl = ttk.Label(dlg, text="Click Settings to load a profile.", font=('Arial', 14))
        lbl.pack(pady=30)
        
        btn_frame = ttk.Frame(dlg)
        btn_frame.pack(side='bottom', fill='x', pady=20, padx=20)
        
        def close_cleanly():
            try:
                dlg.grab_release()
                self.root.focus_set() # Return focus to Main Window
            except: pass
            dlg.destroy()

        def go_to_settings():
            close_cleanly()
            self._on_settings_click()
            
        ttk.Button(btn_frame, text="Cancel", command=close_cleanly).pack(side='right')
        ttk.Button(btn_frame, text="Settings", command=go_to_settings).pack(side='left')
        
        # SAFETY: Handle Window Manager 'X' button
        dlg.protocol("WM_DELETE_WINDOW", close_cleanly)

        dlg.wait_visibility()
        dlg.grab_set()
        dlg.focus_set()

    def _on_abort_click(self):
        # 1. AGGRESSIVE GRAB CLEANUP
        # If any window holds a grab (input lock), force release it immediately.
        try:
            grabber = self.root.grab_current()
            if grabber:
                grabber.grab_release()
        except: pass
        
        # 2. DECOUPLE
        # Don't run logic inside the button click event.
        # Schedule it for 50ms later to let the UI loop breathe.
        self.root.after(50, self._real_abort_logic)
        
    def _real_abort_logic(self):
        # 1. AGGRESSIVE CLEANUP
        if hasattr(self, '_current_dialog') and self._current_dialog:
            try:
                self._current_dialog.destroy()
            except:
                pass
            self._current_dialog = None

        st = self.sequencer.status
        
        # --- DELAYED START STOP LOGIC ---
        if st == SequenceStatus.DELAYED_WAIT:
             def do_delay_cancel():
                 self.sequencer.cancel_delayed_mode()
             
             self._current_dialog = CustomConfirmDialog(
                self.root,
                "Cancel Delayed Start?",
                "This will cancel the timer and return to the previous mode.",
                callback=do_delay_cancel
             )
             return
        
        # --- MANUAL STOP LOGIC ---
        if st == SequenceStatus.MANUAL:
            def do_manual_reset():
                self.sequencer.reset_manual_state()
                
            self._current_dialog = CustomConfirmDialog(
                self.root, 
                "Stop Manual Mode?", 
                "Heaters will be turned off and the timer will be reset.\n\nContinue?",
                callback=do_manual_reset
            )
            return

        # --- AUTO STOP LOGIC ---
        def do_auto_stop():
            self.sequencer.stop() # Resets everything to IDLE

        self._current_dialog = CustomConfirmDialog(
            self.root, 
            "Stop Session?", 
            "Heaters will be turned off.\nTimer will be reset.\nProfile will be reset.\n\nContinue?",
            callback=do_auto_stop
        )
    
    def _on_header_click(self, event):
        """
        Handles header clicks for Dev Mode AND acts as a 'Safety Valve' 
        to unstick the UI if a grab gets lost.
        """
        # --- SAFETY VALVE: FORCE RELEASE GRABS ---
        try:
            self.root.grab_release()
            self.root.focus_set()
        except:
            pass
        # -----------------------------------------

        import time
        now = time.time()
        if now - self.last_click_time > 2.0: self.title_clicks = 0
        self.title_clicks += 1
        self.last_click_time = now
        
        if self.title_clicks >= 5:
            self.title_clicks = 0
            if not self.hw.is_dev_mode(): self._show_safety_dialog()
            else: self.toggle_dev_tools(True)

    def _on_temp_or_header_click(self, event):
        if self.hw.is_dev_mode():
            self.toggle_dev_tools(True)
        else:
            self._on_header_click(event)

    def _show_safety_dialog(self):
        dialog = tk.Toplevel(self.root)
        dialog.title("SAFETY INTERLOCK")
        dialog.geometry("400x300")
        dialog.configure(bg="#c0392b")
        dialog.transient(self.root) 
        
        # Define clean close
        def close_safety():
            try:
                dialog.grab_release()
                self.root.focus_set()
            except: pass
            dialog.destroy()

        dialog.protocol("WM_DELETE_WINDOW", close_safety)
        
        dialog.wait_visibility()
        dialog.grab_set()
        
        tk.Label(dialog, text="⚠ WARNING ⚠", font=("Arial", 24, "bold"), bg="#c0392b", fg="white").pack(pady=20)
        tk.Label(dialog, text="ENTERING DEVELOPER MODE", bg="#c0392b", fg="white", font=("Arial", 12)).pack(pady=10)
        
        self.safety_slider = tk.Scale(dialog, from_=0, to=100, orient="horizontal", length=300, showvalue=0)
        self.safety_slider.pack(pady=10)
        
        # Pass the close function to the checker so it can clean up properly
        self.safety_slider.bind("<ButtonRelease-1>", lambda e: self._check_slider(dialog, close_safety))

    def _check_slider(self, dialog_window, close_callback):
        val = self.safety_slider.get()
        if val >= 100:
            self.hw.set_dev_mode(True)
            style = ttk.Style()
            style.configure('Hero.TFrame', background='#e67e22')
            self.hero_frame.configure(style='Hero.TFrame')
            self.toggle_dev_tools(True)
            
            # Call the clean closer
            close_callback()
        else: 
            self.safety_slider.set(0)

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
        self.dev_window.geometry("450x220") 
        self.dev_window.configure(bg="#333333")
        
        def _on_close():
            self.dev_window.destroy()
            self.dev_window = None
            
        self.dev_window.protocol("WM_DELETE_WINDOW", _on_close)
        
        tk.Label(self.dev_window, text="Temperature Simulator", fg="white", bg="#333333", font=("Arial", 12, "bold")).pack(pady=10)
        
        control_frame = tk.Frame(self.dev_window, bg="#333333")
        control_frame.pack(fill="x", padx=10, pady=5)

        def update_sim_temp(val): 
            self.hw.set_virtual_temp(float(val))

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
        current_temp = self.hw.read_temperature()
        if current_temp is None: current_temp = 70.0
        slider.set(current_temp)

        def dec_temp():
            val = slider.get()
            new_val = max(50, val - 1)
            slider.set(new_val)
            update_sim_temp(new_val) 

        def inc_temp():
            val = slider.get()
            new_val = min(220, val + 1)
            slider.set(new_val)
            update_sim_temp(new_val)

        btn_down = tk.Button(control_frame, text="<", font=("Arial", 12, "bold"), width=3, command=dec_temp)
        btn_down.pack(side="left", padx=5)

        slider.pack(side="left", fill="x", expand=True, padx=5)

        btn_up = tk.Button(control_frame, text=">", font=("Arial", 12, "bold"), width=3, command=inc_temp)
        btn_up.pack(side="left", padx=5)

        # --- UPDATED BUTTON TEXT ---
        btn_skip = tk.Button(self.dev_window, text="⏭ Force Next Line", bg="#e67e22", fg="white", font=("Arial", 10, "bold"), command=self._dev_force_next)
        btn_skip.pack(pady=15, fill="x", padx=20)

    def _dev_force_next(self):
        # LOGIC:
        # 1. If Waiting (Alert/Done) -> Acknowledge
        # 2. If Running -> Fast Forward timer to End of Step (Triggers next alert or completion)
        
        if self.sequencer.status == SequenceStatus.WAITING_FOR_USER:
            if self.sequencer.current_alert_text == "Step Complete":
                self.sequencer.advance_step()
            else:
                self.sequencer.resume_sequence()
                
        elif self.sequencer.status == SequenceStatus.RUNNING:
            import time
            step = self.sequencer.current_profile.steps[self.sequencer.current_step_index]
            
            # Calculate Duration
            d_min = step.duration_min if step.duration_min is not None else 0.0
            duration_sec = (d_min * 60.0) + 1.0 # +1s buffer
            
            # Manipulate Start Time to simulate full duration passing
            # Formula: elapsed = now - start - paused
            # We want: elapsed >= duration
            # So: start = now - duration - paused
            self.sequencer.step_start_time = time.monotonic() - duration_sec - self.sequencer.total_paused_time
            
        elif self.sequencer.status == SequenceStatus.IDLE:
             self.sequencer.start_sequence()
             
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
        import time 
        
        t = self.sequencer.current_temp
        st = self.sequencer.status
        tgt = self.sequencer.get_target_temp()

        # --- 1. VIEW SWITCHING (Auto vs Manual) ---
        show_manual_view = False
        
        if st == SequenceStatus.MANUAL:
            show_manual_view = True
        elif st == SequenceStatus.DELAYED_WAIT:
            # Check context flag
            if not getattr(self.sequencer, 'delayed_is_auto', True):
                show_manual_view = True

        if show_manual_view:
            # MANUAL MODE
            if self.view_auto.winfo_ismapped():
                self.root.focus_set()
                self.view_auto.pack_forget()
                
            if not self.view_manual.winfo_ismapped():
                self.view_manual.pack(fill='both', expand=True)
            
            self.view_manual.refresh()
            # Note: We do NOT clear status_text_var here anymore, 
            # because ManualPanel populates it with "Ready At".
            self.next_addition_var.set(" ") 
            
        else:
            # AUTO MODE
            if self.view_manual.winfo_ismapped():
                self.root.focus_set()
                self.view_manual.pack_forget()
            
            if not self.view_auto.winfo_ismapped():
                self.view_auto.pack(fill='both', expand=True)

        # --- 2. DATA & HERO VISUALS ---
        formatted_temp = UnitUtils.format_temp(t, self.settings)
        self.current_temp_var.set(formatted_temp)
        t_display = t if t is not None else 0.0
        
        if tgt and tgt > 0:
            fmt_tgt = UnitUtils.format_temp(tgt, self.settings)
            self.target_sub_var.set(f"Target: {fmt_tgt}")
        else:
            self.target_sub_var.set("Target: --")

        global_str = self.sequencer.get_global_elapsed_time_str()
        self.elapsed_sub_var.set(f"Elapsed: {global_str}")

        # --- COLOR LOGIC ---
        new_style = 'HeroTemp.TLabel' # Default White
        should_color = False
        
        if st == SequenceStatus.MANUAL:
            if self.sequencer.is_manual_running:
                should_color = True
        elif st in [SequenceStatus.RUNNING, SequenceStatus.WAITING_FOR_USER]:
            should_color = True
            
        if should_color and tgt is not None and tgt > 0:
            diff = t_display - tgt
            if diff < -1.0: 
                new_style = 'HeroTempBlue.TLabel'
            elif diff > 1.0: 
                new_style = 'HeroTempRed.TLabel'
            else: 
                new_style = 'HeroTempGreen.TLabel'
                
        self.lbl_temp.configure(style=new_style)

        # --- 3. DELAYED START BUTTON ---
        if st == SequenceStatus.DELAYED_WAIT:
            time_info = self.sequencer.get_delayed_status_msg()
            btn_txt = f"DELAY ACTIVE\nSLEEPING\n{time_info}"
            self.btn_delayed.config(text=btn_txt)
            self._set_btn_color(self.btn_delayed, '#0044CC', '#e0e0e0')
            
            self._disable_custom_btn(self.btn_action)
            if hasattr(self, 'btn_mode_auto'): self._disable_custom_btn(self.btn_mode_auto)
            if hasattr(self, 'btn_mode_manual'): self._disable_custom_btn(self.btn_mode_manual)
            self.view_manual.set_enabled(False)
            
            self._update_indicators(st, time.time())
            return 
        else:
            self.btn_delayed.config(text="DELAYED\nSTART")
            self._set_btn_color(self.btn_delayed, '#e0e0e0', '#0044CC')
            self.view_manual.set_enabled(True)
            
            if st == SequenceStatus.IDLE:
                 if hasattr(self, 'btn_mode_auto'): self.btn_mode_auto.config(state='normal')
                 if hasattr(self, 'btn_mode_manual'): self.btn_mode_manual.config(state='normal')
                 self.action_btn_text.set("START")
                 self._set_btn_color(self.btn_action, '#e0e0e0', '#0044CC')

        # --- 4. STATUS TEXT & ALERTS ---
        if st != SequenceStatus.MANUAL:
            self.timer_var.set(self.sequencer.get_display_timer())
            raw_msg = self.sequencer.get_status_message()
            is_mid_step_alert = (st == SequenceStatus.WAITING_FOR_USER and self.sequencer.current_alert_text != "Step Complete")

            if is_mid_step_alert:
                self.lbl_timer.configure(style='HeroTimerAlert.TLabel')   
                self.lbl_status.configure(style='HeroStatusAlert.TLabel') 
                clean_msg = raw_msg.replace("ALERT: ", "").replace("ALERT:", "").strip()
                self.status_text_var.set(f"ALERT: {clean_msg}")
            else:
                self.lbl_timer.configure(style='HeroTimer.TLabel')        
                self.lbl_status.configure(style='HeroStatus.TLabel') 
                self.status_text_var.set(raw_msg)

            next_txt = self.sequencer.get_upcoming_additions()
            if not next_txt or "No more" in next_txt:
                self.next_addition_var.set(" ")
            else:
                self.next_addition_var.set(next_txt)
        else:
            self.timer_var.set(self.sequencer.get_display_timer())
            self.lbl_timer.configure(style='HeroTimer.TLabel')
            self.lbl_status.configure(style='HeroStatus.TLabel')

        self.lbl_addition.pack(side='top', anchor='center') 

        # --- 5. STEP LIST REFRESH ---
        if st != SequenceStatus.MANUAL:
            current_idx = self.sequencer.current_step_index
            profile = self.sequencer.current_profile
            last_obj = getattr(self, "last_profile_obj", None)

            if profile is not last_obj:
                 self._refresh_step_list()
                 self.last_profile_obj = profile
                 self.last_profile_id = profile.id if profile else None

            if profile and current_idx is not None and 0 <= current_idx < len(profile.steps):
                step = profile.steps[current_idx]
                step_iid = str(current_idx)
                active_cursor_iid = step_iid
                alert_text = self.sequencer.current_alert_text
                is_mid_step_alert = (st == SequenceStatus.WAITING_FOR_USER and self.sequencer.current_alert_text != "Step Complete")

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
                        else:
                             for child_iid in children:
                                self.step_list.item(child_iid, tags=('pending_step',))

                if active_cursor_iid != self.last_active_iid:
                    try:
                        self.step_list.see(active_cursor_iid)
                        self.step_list.selection_set(active_cursor_iid)
                        self.last_active_iid = active_cursor_iid
                    except:
                        pass

        # --- 6. ACTION BUTTON LABELS ---
        self.btn_action.config(state='normal')
        if hasattr(self, 'btn_mode_auto'): self.btn_mode_auto.config(state='normal')
        if hasattr(self, 'btn_mode_manual'): self.btn_mode_manual.config(state='normal')

        if st == SequenceStatus.MANUAL:
            if self.sequencer.is_manual_running:
                self.action_btn_text.set("PAUSE")
            else:
                self.action_btn_text.set("START")
            self._set_btn_color(self.btn_action, '#e0e0e0', '#0044CC')
            if hasattr(self, 'btn_mode_manual'): self._set_btn_color(self.btn_mode_manual, '#2ecc71', 'black')
            if hasattr(self, 'btn_mode_auto'): self._set_btn_color(self.btn_mode_auto, '#e0e0e0', '#0044CC')

        elif st == SequenceStatus.RUNNING:
            self.action_btn_text.set("PAUSE")
            self._set_btn_color(self.btn_action, '#e0e0e0', '#0044CC')

        elif st == SequenceStatus.PAUSED:
            self.action_btn_text.set("RESUME")
            self._set_btn_color(self.btn_action, '#e0e0e0', '#0044CC')
            
        elif st == SequenceStatus.WAITING_FOR_USER:
            alert_txt = self.sequencer.current_alert_text
            is_mid_step_alert = (st == SequenceStatus.WAITING_FOR_USER and self.sequencer.current_alert_text != "Step Complete")
            if is_mid_step_alert:
                self.action_btn_text.set(f"ACKNOWLEDGE:\n{alert_txt}")
                self._set_btn_color(self.btn_action, '#f1c40f', 'black')
            else:
                step_num = current_idx + 1
                if current_idx is not None and current_idx + 1 < len(profile.steps):
                    next_step_num = step_num + 1
                    self.action_btn_text.set(f"Step {step_num} COMPLETE\nADVANCE to Step {next_step_num}")
                else:
                    self.action_btn_text.set(f"Step {step_num} COMPLETE\nFINISH BREW")
                self._set_btn_color(self.btn_action, '#e0e0e0', '#0044CC')
            
        elif st == SequenceStatus.COMPLETED:
            self.action_btn_text.set("COMPLETE")
            self.btn_action.config(state='disabled')
        
        elif st == SequenceStatus.IDLE:
             self.action_btn_text.set("START")
             self._set_btn_color(self.btn_action, '#e0e0e0', '#0044CC')
             if hasattr(self, 'btn_mode_auto'): self._set_btn_color(self.btn_mode_auto, '#2ecc71', 'black')
             if hasattr(self, 'btn_mode_manual'): self._set_btn_color(self.btn_mode_manual, '#e0e0e0', '#0044CC')
             
        # --- 7. INDICATORS ---
        self._update_indicators(st, time.time())

    def _update_indicators(self, status, now):
        # A. HEATER STATUS (Top Left)
        # We check the ACTUAL relay state from the relay controller
        # This confirms physical activation, not just "enabled" status
        h1_on = False
        h2_on = False
        
        if hasattr(self.sequencer, 'relay'):
             h1_on = self.sequencer.relay.relay_states.get("Heater1", False)
             h2_on = self.sequencer.relay.relay_states.get("Heater2", False)

        # Draw H1 (1000W)
        if h1_on:
            self.lbl_h1.place(x=10, y=10)
        else:
            self.lbl_h1.place_forget()
            
        # Draw H2 (800W) - Offset so they don't overlap if both are on
        if h2_on:
            self.lbl_h2.place(x=80, y=10) 
        else:
            self.lbl_h2.place_forget()
            
        # B. HEARTBEAT (Top Right)
        color = '#444444' # Default Idle Gray
        
        # Logic: Pulse if Auto Running OR (Manual AND actively running)
        should_pulse_green = False
        
        if status == SequenceStatus.RUNNING:
            should_pulse_green = True
        elif status == SequenceStatus.MANUAL:
            # Only pulse if Manual Mode is unpaused (Timer active or Heater active)
            if self.sequencer.is_manual_running:
                should_pulse_green = True
        
        if should_pulse_green:
            # Blink Green (2s period: 1s ON, 1s Dim)
            if (int(now) % 2) == 0:
                color = '#2ecc71' # Bright Green
            else:
                color = '#145a32' # Dim Green
                
        elif status == SequenceStatus.WAITING_FOR_USER:
            # Blink Yellow (Fast: 0.5s)
            if (int(now * 4) % 2) == 0:
                color = '#f1c40f' # Bright Yellow
            else:
                color = '#7d6608' # Dim Yellow
                
        elif status == SequenceStatus.DELAYED_WAIT:
            # Blink Blue (Slow)
            if (int(now) % 2) == 0:
                color = '#3498db'
            else:
                color = '#1b4f72'
                
        self.cv_heartbeat.itemconfig(self.heartbeat_id, fill=color)
            
class ManualPanel(ttk.Frame):
    def __init__(self, parent, sequencer, settings, status_var):
        super().__init__(parent, style='Strip.TFrame')
        self.sequencer = sequencer
        self.settings = settings
        self.status_var = status_var 
        
        self.var_target = tk.DoubleVar(value=150.0)
        self.var_timer = tk.DoubleVar(value=60.0)
        self.var_vol = tk.DoubleVar(value=6.0)
        self.var_power_idx = tk.IntVar(value=3)
        
        self.last_is_metric = None 
        
        self._init_ui()
        self._sync_from_sequencer()
        
        self._pred_timer = None
        self._schedule_prediction()

    def _init_ui(self):
        # Grid: 2 Columns
        self.columnconfigure(0, weight=1)
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)

        card_bg = '#e0e0e0'
        text_fg = '#0044CC'
        trough_col = '#c0c0c0'
        
        # --- SIZES ---
        LABEL_FONT = ('Arial', 14, 'bold')
        SLIDER_WIDTH = 30
        SLIDER_LENGTH = 300
        
        # --- LEFT CARD: Target & Volume ---
        f_left = tk.Frame(self, bg=card_bg)
        f_left.grid(row=0, column=0, sticky='nsew', padx=5, pady=5)
        
        # Target Temp
        self.lbl_target_val = tk.Label(f_left, text="Target: --°F", font=LABEL_FONT, bg=card_bg, fg=text_fg)
        self.lbl_target_val.pack(pady=(10, 5))
        
        self.scale_temp = tk.Scale(f_left, from_=50, to=212, orient='horizontal', 
                                   length=SLIDER_LENGTH, width=SLIDER_WIDTH,
                                   showvalue=0, command=self._on_temp_slide, variable=self.var_target,
                                   bg=card_bg, activebackground=card_bg, fg=text_fg,
                                   highlightthickness=0, troughcolor=trough_col)
        self.scale_temp.pack(fill='x', padx=15, pady=(0, 5))
        self.scale_temp.bind("<ButtonRelease-1>", self._on_temp_release)

        # Volume
        self.lbl_vol_val = tk.Label(f_left, text="Volume: --", font=LABEL_FONT, bg=card_bg, fg=text_fg)
        self.lbl_vol_val.pack(pady=(5, 0))
        
        # Initial config; updated dynamically in _sync
        self.scale_vol = tk.Scale(f_left, from_=2.0, to=9.0, orient='horizontal', 
                                  length=SLIDER_LENGTH, width=SLIDER_WIDTH, resolution=0.25,
                                  showvalue=0, command=self._on_vol_slide, variable=self.var_vol,
                                  bg=card_bg, activebackground=card_bg, fg=text_fg,
                                  highlightthickness=0, troughcolor=trough_col)
        self.scale_vol.pack(fill='x', padx=15, pady=(0, 5))
        self.scale_vol.bind("<ButtonRelease-1>", self._on_vol_release)

        # --- RIGHT CARD: Timer & Power ---
        f_right = tk.Frame(self, bg=card_bg)
        f_right.grid(row=0, column=1, sticky='nsew', padx=5, pady=5)
        
        # Timer
        self.lbl_timer_val = tk.Label(f_right, text="Timer: --m", font=LABEL_FONT, bg=card_bg, fg=text_fg)
        self.lbl_timer_val.pack(pady=(10, 5))
        
        self.scale_timer = tk.Scale(f_right, from_=1, to=120, orient='horizontal', 
                                    length=SLIDER_LENGTH, width=SLIDER_WIDTH,
                                    showvalue=0, command=self._on_timer_slide, variable=self.var_timer,
                                    bg=card_bg, activebackground=card_bg, fg=text_fg,
                                    highlightthickness=0, troughcolor=trough_col)
        self.scale_timer.pack(fill='x', padx=15, pady=(0, 5))
        self.scale_timer.bind("<ButtonRelease-1>", self._on_timer_release)

        # Power
        self.lbl_pwr_val = tk.Label(f_right, text="Power: 1800W", font=LABEL_FONT, bg=card_bg, fg=text_fg)
        self.lbl_pwr_val.pack(pady=(5, 0))
        
        self.scale_pwr = tk.Scale(f_right, from_=0, to=3, orient='horizontal', 
                                  length=SLIDER_LENGTH, width=SLIDER_WIDTH,
                                  showvalue=0, command=self._on_pwr_slide, variable=self.var_power_idx,
                                  bg=card_bg, activebackground=card_bg, fg=text_fg,
                                  highlightthickness=0, troughcolor=trough_col)
        self.scale_pwr.pack(fill='x', padx=15, pady=(0, 5))
        self.scale_pwr.bind("<ButtonRelease-1>", self._on_pwr_release)

    def set_enabled(self, enabled):
        state = 'normal' if enabled else 'disabled'
        fg_col = '#0044CC' if enabled else '#bdc3c7'
        
        self.lbl_target_val.config(fg=fg_col)
        self.lbl_timer_val.config(fg=fg_col)
        self.lbl_vol_val.config(fg=fg_col)
        self.lbl_pwr_val.config(fg=fg_col)

        self.scale_temp.config(state=state, fg=fg_col)
        self.scale_timer.config(state=state, fg=fg_col)
        self.scale_vol.config(state=state, fg=fg_col)
        self.scale_pwr.config(state=state, fg=fg_col)

    def refresh(self):
        # 1. Check for Unit Change (Metric <-> Imperial)
        current_metric = UnitUtils.is_metric(self.settings)
        if current_metric != self.last_is_metric:
            self._sync_from_sequencer()
            
        # 2. Sync if in Delayed Mode (Variables change externally)
        elif self.sequencer.status == SequenceStatus.DELAYED_WAIT:
            self._sync_from_sequencer()
            
        self._update_prediction()

    def _sync_from_sequencer(self):
        # Update our tracker
        is_metric = UnitUtils.is_metric(self.settings)
        self.last_is_metric = is_metric
        
        # 1. Fetch Basic Settings (System Units: F, Gal)
        if self.sequencer.status == SequenceStatus.DELAYED_WAIT:
            t_sys = getattr(self.sequencer, 'delayed_target_temp', 150.0)
            m = self.settings.get("manual_mode_settings", "last_timer_min", 60.0)
        else:
            t_sys = self.settings.get("manual_mode_settings", "last_setpoint_f", 150.0)
            m = self.settings.get("manual_mode_settings", "last_timer_min", 60.0)

        v_sys = self.settings.get("manual_mode_settings", "last_volume_gal", 6.0)

        # 2. Convert to UI Units & Set Ranges
        if is_metric:
            # TEMP: Fahrenheit -> Celsius
            t_ui = UnitUtils.to_user_temp(t_sys, self.settings)
            self.scale_temp.config(from_=10, to=100)
            temp_unit = "°C"

            # VOL: Gallons -> Liters (8-32L, Step 1.0)
            v_ui = v_sys * 3.78541
            # Round to nearest 1.0 immediately to prevent float drift
            v_ui = round(v_ui)
            
            self.scale_vol.config(from_=8.0, to=32.0, resolution=1.0)
            vol_unit = "L"
            
            # Clamp Metric Vol
            if v_ui < 8.0: v_ui = 8.0
            if v_ui > 32.0: v_ui = 32.0
            
        else:
            # TEMP: Fahrenheit
            t_ui = t_sys
            self.scale_temp.config(from_=50, to=212)
            temp_unit = "°F"

            # VOL: Gallons (2-9 Gal, Step 0.25)
            v_ui = v_sys
            # Force snap to nearest 0.25 immediately
            v_ui = round(v_ui * 4) / 4.0
            
            self.scale_vol.config(from_=2.0, to=9.0, resolution=0.25)
            vol_unit = "Gal"

            # Clamp Imperial Vol
            if v_ui < 2.0: v_ui = 2.0
            if v_ui > 9.0: v_ui = 9.0

        # 3. Configure Power
        watts = self.settings.get("manual_mode_settings", "last_power_watts", 1800)
        watts_map = [800, 1000, 1400, 1800]
        try:
            p_idx = watts_map.index(watts)
        except ValueError:
            p_idx = 3

        # 4. Apply to Widgets
        self.var_target.set(t_ui)
        self.var_timer.set(m)
        self.var_vol.set(v_ui)
        self.var_power_idx.set(p_idx)
        
        self.lbl_target_val.config(text=f"Target: {int(t_ui)}{temp_unit}")
        self.lbl_timer_val.config(text=f"Timer: {int(m)}m")
        self.lbl_vol_val.config(text=f"Volume: {v_ui:.2f} {vol_unit}")
        self.lbl_pwr_val.config(text=f"Power: {watts}W")
        
        self._update_prediction()

    def _on_temp_slide(self, val):
        v = float(val)
        is_metric = UnitUtils.is_metric(self.settings)
        unit = "°C" if is_metric else "°F"
        self.lbl_target_val.config(text=f"Target: {int(v)}{unit}")
        self._update_prediction()

    def _on_temp_release(self, event):
        if self.sequencer.status == SequenceStatus.DELAYED_WAIT:
            self._sync_from_sequencer()
            return
            
        val_ui = self.var_target.get()
        # Convert UI Value back to System (F)
        val_sys = UnitUtils.to_system_temp(val_ui, self.settings)
        self.sequencer.set_manual_target(val_sys)

    def _on_timer_slide(self, val):
        self.lbl_timer_val.config(text=f"Timer: {int(float(val))}m")
        
    def _on_timer_release(self, event):
        if self.sequencer.status == SequenceStatus.DELAYED_WAIT:
            self._sync_from_sequencer()
            return
        val = self.var_timer.get()
        self.sequencer.set_manual_timer_duration(val)

    def _on_vol_slide(self, val):
        v = float(val)
        is_metric = UnitUtils.is_metric(self.settings)
        
        if is_metric:
            # Enforce snap to 1.0 L for display
            v_snapped = round(v)
            unit = "L"
            text_str = f"{v_snapped:.2f}" # Display as 9.00
        else:
            # Enforce snap to 0.25 Gal for display
            # Even if the slider is slightly off-pixel, we round the math here.
            v_snapped = round(v * 4) / 4.0
            unit = "Gal"
            text_str = f"{v_snapped:.2f}" # Display as 2.25, 2.50, 2.75
            
        self.lbl_vol_val.config(text=f"Volume: {text_str} {unit}")
        self._update_prediction()

    def _on_vol_release(self, event):
        # Determine current 'visual' value by running the same snap logic
        val_raw = self.var_vol.get()
        is_metric = UnitUtils.is_metric(self.settings)
        
        if is_metric:
            val_ui = round(val_raw)
            # Convert to System (Gal)
            val_sys = val_ui / 3.78541
        else:
            val_ui = round(val_raw * 4) / 4.0
            # System is Gal
            val_sys = val_ui
            
        # Push the SNAPPED value back to the variable so the slider physically jumps to grid
        self.var_vol.set(val_ui)
            
        if hasattr(self.sequencer, 'set_manual_volume'):
            self.sequencer.set_manual_volume(val_sys)

    def _on_pwr_slide(self, val):
        idx = int(val)
        watts_map = [800, 1000, 1400, 1800]
        w = watts_map[idx]
        self.lbl_pwr_val.config(text=f"Power: {w}W")
        self._update_prediction()

    def _on_pwr_release(self, event):
        idx = self.var_power_idx.get()
        watts_map = [800, 1000, 1400, 1800]
        w = watts_map[idx]
        if hasattr(self.sequencer, 'set_manual_power'):
            self.sequencer.set_manual_power(w)

    def _update_prediction(self):
        if self.sequencer.status != SequenceStatus.MANUAL:
            return

        if not hasattr(self.sequencer, 'calculate_ramp_minutes'):
            self.status_var.set("")
            return

        import time
        from datetime import datetime

        # Get Current System Temp (Always F)
        curr_temp_sys = self.sequencer.current_temp if self.sequencer.current_temp else 60.0
        
        # Get Target from UI and convert to System (F)
        target_ui = self.var_target.get()
        target_sys = UnitUtils.to_system_temp(target_ui, self.settings)

        # Get Volume (Use the snapped variable value)
        vol_ui = self.var_vol.get()
        is_metric = UnitUtils.is_metric(self.settings)
        
        if is_metric:
            vol_ui_snapped = round(vol_ui)
            vol_sys = vol_ui_snapped / 3.78541
        else:
            vol_ui_snapped = round(vol_ui * 4) / 4.0
            vol_sys = vol_ui_snapped
        
        # Power
        idx = self.var_power_idx.get()
        watts = [800, 1000, 1400, 1800][idx]
        
        if target_sys > curr_temp_sys:
            mins = self.sequencer.calculate_ramp_minutes(curr_temp_sys, target_sys, vol_sys, watts)
            ready_epoch = time.time() + (mins * 60)
            dt = datetime.fromtimestamp(ready_epoch)
            self.status_var.set(f"Ready At: {dt.strftime('%H:%M')}")
        else:
            self.status_var.set("Ready At: Now")

    def _schedule_prediction(self):
        self._update_prediction()
        self._pred_timer = self.after(5000, self._schedule_prediction)
        
class DelayedStartActionDialog(tk.Toplevel):
    def __init__(self, parent, on_cancel, on_edit, on_cleanup=None):
        super().__init__(parent)
        
        # 1. HIDE IMMEDIATELY
        self.withdraw()
        
        self.on_cleanup = on_cleanup
        self.title("Delayed Start Active")
        self.geometry("400x180")
        self.transient(parent)
        
        # 2. BIND "X" BUTTON
        self.protocol("WM_DELETE_WINDOW", self._safe_close)
        
        # Layout
        pad = 20
        msg = "Delayed Start is currently ACTIVE.\nThe system is waiting to fire the heater.\n\nWhat would you like to do?"
        ttk.Label(self, text=msg, justify='center', font=('Arial', 11)).pack(pady=pad, padx=pad)
        
        btn_frame = ttk.Frame(self)
        btn_frame.pack(side='bottom', fill='x', pady=20, padx=20)
        
        # Buttons
        # "Keep Waiting" is just a close action
        ttk.Button(btn_frame, text="Keep Waiting", command=self._safe_close).pack(side='right', padx=5)
        
        # Edit and Cancel delegate to wrappers
        ttk.Button(btn_frame, text="Edit Delay", command=lambda: self._do_edit(on_edit)).pack(side='left', padx=5)
        ttk.Button(btn_frame, text="Cancel Delay", command=lambda: self._do_cancel(on_cancel)).pack(side='left', padx=5)
        
        # 3. Build & Show
        self.update_idletasks()
        try:
            x = parent.winfo_rootx() + (parent.winfo_width() // 2) - 200
            y = parent.winfo_rooty() + (parent.winfo_height() // 2) - 90
            self.geometry(f"+{x}+{y}")
        except:
            pass
            
        self.deiconify()
        self.lift()
        self.focus_set()
        
        try:
            self.grab_set()
        except:
            pass

    def _safe_close(self):
        """Standard teardown for 'X' or 'Keep Waiting'."""
        try:
            self.grab_release()
        except:
            pass
        self.destroy()
        
        # Clear the reference in UIManager so it knows we are gone
        if self.on_cleanup:
            self.on_cleanup()

    def _do_edit(self, callback):
        """Teardown, then trigger edit logic."""
        try:
            self.grab_release()
        except:
            pass
        self.destroy()
        
        # Important: clear the OLD reference before the callback creates the NEW one
        if self.on_cleanup:
            self.on_cleanup()
            
        callback()

    def _do_cancel(self, callback):
        """Teardown, then trigger cancel logic."""
        try:
            self.grab_release()
        except:
            pass
        self.destroy()
        
        if self.on_cleanup:
            self.on_cleanup()
            
        callback()
        
class DelayedStartPopup(tk.Toplevel):
    def __init__(self, parent, sequencer, settings, initial_data=None, initial_context=None):
        super().__init__(parent)
        
        # 1. HIDE IMMEDIATELY to prevent rendering race conditions
        self.withdraw()
        
        self.sequencer = sequencer
        self.settings = settings
        self.initial_context = initial_context
        
        self.title("Setup Delayed Start")
        self.geometry("500x380")
        self.transient(parent)
        
        # 2. Initialize Variables
        if initial_data:
            self.var_vol = tk.StringVar(value=str(initial_data.get('vol', "8.0")))
            self.var_temp = tk.StringVar(value=str(initial_data.get('temp', "154.0")))
            rt_str = initial_data.get('time_str', "")
            if ":" in rt_str:
                parts = rt_str.split(":")
                self.var_hr = tk.StringVar(value=parts[0])
                self.var_min = tk.StringVar(value=parts[1])
            else:
                now = datetime.now()
                self.var_hr = tk.StringVar(value=now.strftime("%H"))
                self.var_min = tk.StringVar(value=now.strftime("%M"))
        else:
            self.var_vol = tk.StringVar(value="8.0")
            self.var_temp = tk.StringVar(value="154.0")
            now = datetime.now()
            target = now + timedelta(hours=4)
            self.var_hr = tk.StringVar(value=target.strftime("%H"))
            self.var_min = tk.StringVar(value=target.strftime("%M"))
        
        # 3. Build UI
        self._build_ui()
        
        # 4. Center Window (Force geometry update first)
        self.update_idletasks()
        try:
            x = parent.winfo_rootx() + 50
            y = parent.winfo_rooty() + 50
            self.geometry(f"+{x}+{y}")
        except:
            pass
            
        # 5. SAFE SHOW SEQUENCE (Replicates ProfileEditor pattern)
        # We DO NOT use wait_visibility() here. We show it, then grab it.
        self.deiconify()
        self.lift()
        self.focus_set()
        
        try:
            self.grab_set()
        except Exception as e:
            print(f"Warning: DelayedStart grab failed: {e}")

    def _build_ui(self):
        # (This remains unchanged)
        pad = 10
        ttk.Label(self, text="Ready-By Timer", font=('Arial', 14, 'bold')).pack(pady=pad)
        
        container = ttk.Frame(self, padding=pad)
        container.pack(fill='both', expand=True)
        
        r1 = ttk.Frame(container)
        r1.pack(fill='x', pady=5)
        ttk.Label(r1, text="Total Water Volume (Gal):", width=25).pack(side='left')
        ttk.Entry(r1, textvariable=self.var_vol, width=8).pack(side='left')
        
        r2 = ttk.Frame(container)
        r2.pack(fill='x', pady=5)
        ttk.Label(r2, text="Target Temperature (°F):", width=25).pack(side='left')
        ttk.Entry(r2, textvariable=self.var_temp, width=8).pack(side='left')
        
        r3 = ttk.Frame(container)
        r3.pack(fill='x', pady=20)
        ttk.Label(r3, text="Have water ready at:", width=20, font=('Arial', 11)).pack(side='left')
        
        sb_h = ttk.Spinbox(r3, from_=0, to=23, textvariable=self.var_hr, width=3, 
                          format="%02.0f", wrap=True, font=('Arial', 12))
        sb_h.pack(side='left')
        ttk.Label(r3, text=":", font=('Arial', 12, 'bold')).pack(side='left', padx=2)
        sb_m = ttk.Spinbox(r3, from_=0, to=59, textvariable=self.var_min, width=3, 
                           format="%02.0f", wrap=True, font=('Arial', 12))
        sb_m.pack(side='left')
        ttk.Label(r3, text="(24h Format)").pack(side='left', padx=10)

        btn_frame = ttk.Frame(self)
        btn_frame.pack(side='bottom', fill='x', pady=10, padx=10)
        ttk.Button(btn_frame, text="Cancel", command=self.destroy).pack(side='right', padx=5)
        
        b_start = tk.Button(btn_frame, text="ACTIVATE DELAY", bg='#34495e', fg='white', 
                            font=('Arial', 11, 'bold'), height=2,
                            command=self._on_activate)
        b_start.pack(side='left', fill='x', expand=True, padx=5)

    def _on_activate(self):
        try:
            vol = float(self.var_vol.get())
            temp = float(self.var_temp.get())
            hr = int(self.var_hr.get())
            mn = int(self.var_min.get())
            
            now = datetime.now()
            target = now.replace(hour=hr, minute=mn, second=0, microsecond=0)
            
            if target < now:
                target = target + timedelta(days=1)
                
            diff = target - now
            hours_out = diff.total_seconds() / 3600.0
            
            if hours_out < 2.0:
                messagebox.showerror("Error", "Time is too short (Under 2h).\nJust use Manual Mode.", parent=self)
                return
            
            if hours_out > 24.0:
                messagebox.showerror("Error", "Time is too far (Over 24h).", parent=self)
                return
                
            self.sequencer.start_delayed_mode(temp, vol, target, from_auto_mode=self.initial_context)
            self.destroy()
            
        except ValueError:
            messagebox.showerror("Error", "Invalid numeric input.", parent=self)
            
class CustomConfirmDialog(tk.Toplevel):
    def __init__(self, parent, title, message, callback=None):
        """
        Safety-First Dialog (Version 3)
        - Force Topmost
        - No Grabs
        - Debug Prints
        """
        super().__init__(parent)
        print(f"[UI] Creating Dialog: {title}") # DEBUG
        
        self.callback = callback
        self.title(title)
        
        # Visual Styling
        self.configure(bg='#ecf0f1')
        self.geometry("480x240")
        
        # Force window to float above everything else
        self.attributes('-topmost', True)
        self.resizable(False, False)
        
        # Center logic
        try:
            sw = self.winfo_screenwidth()
            sh = self.winfo_screenheight()
            x = (sw - 480) // 2
            y = (sh - 240) // 2
            self.geometry(f"+{x}+{y}")
        except: pass
        
        # Layout
        lbl = tk.Label(self, text=message, font=('Arial', 14), 
                  bg='#ecf0f1', fg='#2c3e50', justify='center', wraplength=440)
        lbl.pack(pady=30, padx=20, expand=True, fill='both')
        
        btn_frame = tk.Frame(self, bg='#ecf0f1')
        btn_frame.pack(side='bottom', fill='x', pady=20)
        
        btn_yes = tk.Button(btn_frame, text="YES", font=('Arial', 14, 'bold'), 
                           bg='#2ecc71', fg='white', activebackground='#27ae60',
                           height=2, width=12, relief='flat',
                           command=self._on_yes)
        btn_yes.pack(side='left', padx=30, expand=True)
        
        btn_no = tk.Button(btn_frame, text="NO", font=('Arial', 14, 'bold'), 
                          bg='#e74c3c', fg='white', activebackground='#c0392b',
                          height=2, width=12, relief='flat',
                          command=self._on_no)
        btn_no.pack(side='right', padx=30, expand=True)
        
        self.protocol("WM_DELETE_WINDOW", self._on_no)
        
        # Ensure visibility without grabbing focus
        self.deiconify()
        self.lift()
        self.focus_force()

    def _on_yes(self):
        print("[UI] Dialog: YES clicked") # DEBUG
        self.destroy()
        if self.callback:
            # Run callback slightly later to allow UI to clear
            self.after(50, self._run_callback)

    def _run_callback(self):
        try:
            if self.callback: self.callback()
        except Exception as e:
            print(f"[UI] Dialog Callback Error: {e}")

    def _on_no(self):
        print("[UI] Dialog: NO clicked") # DEBUG
        self.destroy()
