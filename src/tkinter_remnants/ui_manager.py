"""
src/ui_manager.py
"""
import tkinter as tk
from tkinter import ttk, messagebox
import traceback
from datetime import datetime, timedelta 
from profile_data import BrewProfile, TimeoutBehavior, SequenceStatus
from settings_ui import SettingsPopup
import uuid
import copy
from utils import UnitUtils

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
        
        # --- OPTIMIZED SIZES ---
        LABEL_FONT = ('Arial', 14, 'bold') 
        SLIDER_WIDTH = 30
        SLIDER_LENGTH = 300
        
        # --- LEFT CARD: Target & Volume ---
        f_left = tk.Frame(self, bg=card_bg)
        f_left.grid(row=0, column=0, sticky='nsew', padx=4, pady=4)
        
        # Target Temp
        self.lbl_target_val = tk.Label(f_left, text="Target: --°F", font=LABEL_FONT, bg=card_bg, fg=text_fg)
        self.lbl_target_val.pack(pady=(10, 5)) 
        
        self.scale_temp = tk.Scale(f_left, from_=70, to=212, orient='horizontal', 
                                   length=SLIDER_LENGTH, width=SLIDER_WIDTH,
                                   showvalue=0, command=self._on_temp_slide, variable=self.var_target,
                                   bg=card_bg, activebackground=card_bg, fg=text_fg,
                                   highlightthickness=0, troughcolor=trough_col)
        self.scale_temp.pack(fill='x', padx=15, pady=(0, 5))
        self.scale_temp.bind("<ButtonRelease-1>", self._on_temp_release)

        # Volume
        self.lbl_vol_val = tk.Label(f_left, text="Volume: --", font=LABEL_FONT, bg=card_bg, fg=text_fg)
        self.lbl_vol_val.pack(pady=(5, 5))
        
        self.scale_vol = tk.Scale(f_left, from_=2.0, to=9.0, orient='horizontal', 
                                  length=SLIDER_LENGTH, width=SLIDER_WIDTH, resolution=0.25,
                                  showvalue=0, command=self._on_vol_slide, variable=self.var_vol,
                                  bg=card_bg, activebackground=card_bg, fg=text_fg,
                                  highlightthickness=0, troughcolor=trough_col)
        self.scale_vol.pack(fill='x', padx=15, pady=(0, 10))
        self.scale_vol.bind("<ButtonRelease-1>", self._on_vol_release)

        # --- RIGHT CARD: Timer & Power ---
        f_right = tk.Frame(self, bg=card_bg)
        f_right.grid(row=0, column=1, sticky='nsew', padx=4, pady=4)
        
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
        self.lbl_pwr_val.pack(pady=(5, 5))
        
        self.scale_pwr = tk.Scale(f_right, from_=0, to=3, orient='horizontal', 
                                  length=SLIDER_LENGTH, width=SLIDER_WIDTH,
                                  showvalue=0, command=self._on_pwr_slide, variable=self.var_power_idx,
                                  bg=card_bg, activebackground=card_bg, fg=text_fg,
                                  highlightthickness=0, troughcolor=trough_col)
        self.scale_pwr.pack(fill='x', padx=15, pady=(0, 10))
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
        current_metric = UnitUtils.is_metric(self.settings)
        if current_metric != self.last_is_metric:
            self._sync_from_sequencer()
        elif self.sequencer.status == SequenceStatus.DELAYED_WAIT:
            self._sync_from_sequencer()
        self._update_prediction()

    def _sync_from_sequencer(self):
        is_metric = UnitUtils.is_metric(self.settings)
        self.last_is_metric = is_metric
        
        if self.sequencer.status == SequenceStatus.DELAYED_WAIT:
            t_sys = getattr(self.sequencer, 'delayed_target_temp', 150.0)
            m = self.settings.get("manual_mode_settings", "last_timer_min", 60.0)
        else:
            t_sys = self.settings.get("manual_mode_settings", "last_setpoint_f", 150.0)
            m = self.settings.get("manual_mode_settings", "last_timer_min", 60.0)

        v_sys = self.settings.get("manual_mode_settings", "last_volume_gal", 6.0)

        if is_metric:
            t_ui = UnitUtils.to_user_temp(t_sys, self.settings)
            self.scale_temp.config(from_=20, to=100)
            temp_unit = "°C"
            v_ui = round(v_sys * 3.78541)
            self.scale_vol.config(from_=8.0, to=32.0, resolution=1.0)
            vol_unit = "L"
            if v_ui < 8.0: v_ui = 8.0
            if v_ui > 32.0: v_ui = 32.0
        else:
            t_ui = t_sys
            self.scale_temp.config(from_=70, to=212)
            temp_unit = "°F"
            v_ui = round(v_sys * 4) / 4.0
            self.scale_vol.config(from_=2.0, to=9.0, resolution=0.25)
            vol_unit = "Gal"
            if v_ui < 2.0: v_ui = 2.0
            if v_ui > 9.0: v_ui = 9.0

        watts = self.settings.get("manual_mode_settings", "last_power_watts", 1800)
        watts_map = [800, 1000, 1400, 1800]
        try: p_idx = watts_map.index(watts)
        except ValueError: p_idx = 3

        self.var_target.set(t_ui)
        self.var_timer.set(m)
        self.var_vol.set(v_ui)
        self.var_power_idx.set(p_idx)
        
        sys_boil = self.settings.get_system_setting("boil_temp_f", 212.0)
        if t_sys >= (sys_boil - 0.01):
            self.lbl_target_val.config(text=f"Target: {int(t_ui)}{temp_unit} BOILING", fg='red')
        else:
            self.lbl_target_val.config(text=f"Target: {int(t_ui)}{temp_unit}", fg='#0044CC')
            
        self.lbl_timer_val.config(text=f"Timer: {int(m)}m")
        self.lbl_vol_val.config(text=f"Volume: {v_ui:.2f} {vol_unit}")
        self.lbl_pwr_val.config(text=f"Power: {watts}W")
        
        self._update_prediction()

    def _on_temp_slide(self, val):
        v = float(val)
        is_metric = UnitUtils.is_metric(self.settings)
        unit = "°C" if is_metric else "°F"
        
        sys_boil_f = self.settings.get_system_setting("boil_temp_f", 212.0)
        sys_boil_user = UnitUtils.to_user_temp(sys_boil_f, self.settings) if is_metric else sys_boil_f
            
        if v >= (sys_boil_user - 0.1):
             self.lbl_target_val.config(text=f"Target: {int(v)}{unit} BOILING")
        else:
             self.lbl_target_val.config(text=f"Target: {int(v)}{unit}")
        self._update_prediction()

    def _on_temp_release(self, event):
        if self.sequencer.status == SequenceStatus.DELAYED_WAIT:
            self._sync_from_sequencer()
            return
        val_ui = self.var_target.get()
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
            v_snapped = round(v)
            unit = "L"
            text_str = f"{v_snapped:.2f}"
        else:
            v_snapped = round(v * 4) / 4.0
            unit = "Gal"
            text_str = f"{v_snapped:.2f}"
        self.lbl_vol_val.config(text=f"Volume: {text_str} {unit}")
        self._update_prediction()

    def _on_vol_release(self, event):
        val_raw = self.var_vol.get()
        is_metric = UnitUtils.is_metric(self.settings)
        if is_metric:
            val_ui = round(val_raw)
            val_sys = val_ui / 3.78541
        else:
            val_ui = round(val_raw * 4) / 4.0
            val_sys = val_ui
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
        if self.sequencer.status == SequenceStatus.DELAYED_WAIT:
            ready_str = getattr(self.sequencer, 'delayed_ready_time_str', "--:--")
            self.status_var.set(f"Ready At: {ready_str}")
            return

        if self.sequencer.status != SequenceStatus.MANUAL:
            return

        if not hasattr(self.sequencer, 'calculate_ramp_minutes'):
            self.status_var.set("")
            return

        import time
        from datetime import datetime

        curr_temp_sys = self.sequencer.current_temp if self.sequencer.current_temp else 60.0
        target_ui = self.var_target.get()
        target_sys = UnitUtils.to_system_temp(target_ui, self.settings)
        vol_ui = self.var_vol.get()
        is_metric = UnitUtils.is_metric(self.settings)
        
        if is_metric:
            vol_ui_snapped = round(vol_ui)
            vol_sys = vol_ui_snapped / 3.78541
        else:
            vol_ui_snapped = round(vol_ui * 4) / 4.0
            vol_sys = vol_ui_snapped
        
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


class UIManager:
    def __init__(self, root, sequence_manager, hardware_interface):
        self.root = root
        self.sequencer = sequence_manager
        self.settings = sequence_manager.settings
        self.hw = hardware_interface 
        self.title_clicks = 0
        self.last_click_time = 0
        
        self.settings_window = None
        self.delayed_start_window = None
        
        self.last_profile_id = None 
        self.last_active_iid = None 
        
        self.root.title("KettleBrain")
        self.root.configure(bg='#222222')
        
        # --- REVERTED TO SYNCHRONOUS STARTUP (Fixes UI Freezing) ---
        # 1. Set Geometry
        self.root.geometry("798x418+1+38")
        
        # 2. Show Immediately (No 'after' delays)
        self.root.deiconify()
        
        # 3. Force Focus/Lift immediately so inputs work on first click
        self.root.lift()
        self.root.focus_force()
        self.root.bind("<Escape>", lambda e: self.root.attributes('-fullscreen', False))

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
        
        # Force a pending event update to clear any startup "cobwebs"
        # This ensures the window is fully responsive before the user clicks.
        self.root.update_idletasks()
        
    # def __init__(self, root, sequence_manager, hardware_interface):
        # self.root = root
        # self.sequencer = sequence_manager
        # self.settings = sequence_manager.settings
        # self.hw = hardware_interface 
        # self.title_clicks = 0
        # self.last_click_time = 0
        
        # self.settings_window = None
        # self.delayed_start_window = None
        
        # self.last_profile_id = None 
        # self.last_active_iid = None 
        
        # self.root.title("KettleBrain")
        # self.root.configure(bg='#222222')
        
        # # --- FIX: EXACT POSITIONING & VISIBILITY ORDER ---
        # # 1. Set Size/Position FIRST
        # self.root.geometry("798x418+1+38")
        
        # # 2. THEN Show the window (Deiconify)
        # self.root.deiconify()
        
        # self.root.lift()
        # self.root.focus_force()
        # self.root.bind("<Escape>", lambda e: self.root.attributes('-fullscreen', False))

        # self._configure_styles()
        
        # self.current_temp_var = tk.StringVar(value="--.-°F")
        # self.timer_var = tk.StringVar(value="--:--:--") 
        # self.target_sub_var = tk.StringVar(value="Target: --")
        # self.elapsed_sub_var = tk.StringVar(value="Elapsed: 00:00")
        # self.status_text_var = tk.StringVar(value="System Idle")
        # self.target_text_var = tk.StringVar(value="") 
        # self.next_addition_var = tk.StringVar(value="")
        # self.action_btn_text = tk.StringVar(value="START")
        
        # self._create_main_layout()
        # self._update_loop()
        
        # # --- FIX: FORCE RENDER ---
        # # Force the Window Manager to draw the window frames IMMEDIATELY.
        # # This prevents the "ghost window" issue where the app runs but is invisible.
        # self.root.update()
        
    def _open_delayed_start(self):
        try:
            grabber = self.root.grab_current()
            if grabber: grabber.grab_release()
        except: pass
        self.root.after(50, self._real_delayed_start_logic)

    def _real_delayed_start_logic(self):
        if self.delayed_start_window:
            try: self.delayed_start_window.destroy()
            except: pass
            self.delayed_start_window = None

        def cleanup_ref():
            self.delayed_start_window = None

        try:
            if self.sequencer.status == SequenceStatus.DELAYED_WAIT:
                def do_cancel():
                    self.sequencer.cancel_delayed_mode()
                def do_edit():
                    data = {
                        'vol': getattr(self.sequencer, 'delayed_vol', 8.0),
                        'temp': getattr(self.sequencer, 'delayed_target_temp', 154.0),
                        'time_str': getattr(self.sequencer, 'delayed_ready_time_str', "")
                    }
                    was_auto = getattr(self.sequencer, 'delayed_is_auto', True)
                    self.sequencer.stop() 
                    self.sequencer.enter_manual_mode()
                    self.delayed_start_window = DelayedStartPopup(
                        self.root, self.sequencer, self.settings, 
                        initial_data=data, initial_context=was_auto, on_cleanup=cleanup_ref
                    )
                self.delayed_start_window = DelayedStartActionDialog(
                    self.root, on_cancel=do_cancel, on_edit=do_edit, on_cleanup=cleanup_ref
                )
                return

            can_proceed = False
            if self.sequencer.status == SequenceStatus.IDLE:
                 can_proceed = True
            elif self.sequencer.status == SequenceStatus.MANUAL:
                if not self.sequencer.is_manual_running: 
                    can_proceed = True

            if not can_proceed:
                 messagebox.showwarning("System Busy", "Stop the current process before setting a Delayed Start.", parent=self.root)
                 return

            self.delayed_start_window = DelayedStartPopup(
                self.root, self.sequencer, self.settings, on_cleanup=cleanup_ref
            )
            
        except Exception as e:
            print(f"[UI ERROR] Failed to open Delayed Start: {e}")
            messagebox.showerror("UI Error", f"Failed to open Delayed Start dialog:\n{e}", parent=self.root)

    def _request_mode_switch(self, target_mode):
        try: self.root.focus_set()
        except: pass
        
        current_stat = self.sequencer.status
        is_active = current_stat in [SequenceStatus.RUNNING, SequenceStatus.PAUSED, SequenceStatus.WAITING_FOR_USER]
        if current_stat == SequenceStatus.MANUAL and self.sequencer.is_manual_running:
            is_active = True
            
        def perform_switch():
            self.sequencer.stop() 
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
            try:
                self.root.update_idletasks()
                self.root.focus_set()
            except: pass

        if is_active:
            from ui_manager import CustomConfirmDialog 
            CustomConfirmDialog(
                self.root, "Switch Modes?", "Switching modes will STOP the current process.\nAre you sure?",
                callback=perform_switch
            )
        else:
            perform_switch()

    def _configure_styles(self):
        style = ttk.Style()
        style.theme_use('default') 
        style.configure('Hero.TFrame', background='#222222')
        
        style.configure('HeroTemp.TLabel', font=('Arial', 28, 'bold'), background='#222222', foreground='white')
        style.configure('HeroTempRed.TLabel', font=('Arial', 28, 'bold'), background='#222222', foreground='#ff4444')
        style.configure('HeroTempBlue.TLabel', font=('Arial', 28, 'bold'), background='#222222', foreground='#3498db')
        style.configure('HeroTempGreen.TLabel', font=('Arial', 28, 'bold'), background='#222222', foreground='#00ff00')

        style.configure('HeroTimer.TLabel', font=('Arial', 28, 'bold'), background='#222222', foreground='#00ff00') 
        style.configure('HeroTimerAlert.TLabel', font=('Arial', 28, 'bold'), background='#222222', foreground='#f1c40f') 

        style.configure('HeroSub.TLabel', font=('Arial', 12, 'bold'), background='#222222', foreground='#cccccc')
        style.configure('HeroStatus.TLabel', font=('Arial', 12, 'bold'), background='#222222', foreground='#cccccc')
        style.configure('HeroStatusAlert.TLabel', font=('Arial', 12, 'bold'), background='#222222', foreground='#f1c40f')
        style.configure('HeroAddition.TLabel', font=('Arial', 12, 'bold'), background='#222222', foreground='#f1c40f')
        
        style.configure('Strip.TFrame', background='#444444')
        style.configure('Controls.TFrame', background='#222222')
        
        style.configure('Action.TButton', font=('Arial', 12, 'bold'), foreground='blue')
        style.configure('Stop.TButton', font=('Arial', 12, 'bold'), foreground='red')
        style.configure('Advance.TButton', font=('Arial', 12, 'bold'), foreground='blue')
        style.configure('Alert.TButton', font=('Arial', 12, 'bold'), foreground='black', background='#f1c40f')
        style.map('Alert.TButton', background=[('active', '#d4ac0d')], foreground=[('active', 'black')])

    def _set_btn_color(self, btn, bg, fg):
        try:
            if getattr(btn, "_current_base_bg", None) == bg and getattr(btn, "_current_base_fg", None) == fg:
                return
            btn.config(bg=bg, fg=fg, activebackground=fg, activeforeground=bg)
            btn._current_base_bg = bg
            btn._current_base_fg = fg
            btn.unbind("<Enter>")
            btn.unbind("<Leave>")
            btn.bind("<Enter>", lambda e, b=bg, f=fg: btn.config(bg=f, fg=b))
            btn.bind("<Leave>", lambda e, b=bg, f=fg: btn.config(bg=b, fg=f))
        except Exception: pass

    def _disable_custom_btn(self, btn):
        try:
            btn.config(state='disabled', disabledforeground='#bdc3c7')
            btn.unbind("<Enter>")
            btn.unbind("<Leave>")
            if hasattr(btn, "_current_base_bg"): del btn._current_base_bg
            if hasattr(btn, "_current_base_fg"): del btn._current_base_fg
        except Exception: pass

    def _create_main_layout(self):
        # 1. CONTROLS FRAME (Bottom)
        self.controls_frame = ttk.Frame(self.root, style='Controls.TFrame', height=60)
        self.controls_frame.pack(side='bottom', fill='both', expand=False)
        self._create_control_widgets()

        # 2. STRIP FRAME (Middle) - FIXED HEIGHT 220px
        self.strip_frame = ttk.Frame(self.root, style='Strip.TFrame', height=220)
        self.strip_frame.pack(side='bottom', fill='x', expand=False)
        self.strip_frame.pack_propagate(False)
        self._create_sequence_strip_widgets()

        # 3. HERO FRAME (Top) - INCREASED TO 135px (Was 120px)
        # This utilizes the empty slack in the 418px window to prevent clipping
        self.hero_frame = ttk.Frame(self.root, style='Hero.TFrame', height=135)
        self.hero_frame.pack(side='top', fill='x', expand=False)
        self.hero_frame.pack_propagate(False) 
        self._create_hero_widgets()
        self.hero_frame.bind("<Button-1>", self._on_header_click)

    def _create_hero_widgets(self):
        # --- SWAPPED PACKING ORDER TO PREVENT CLIPPING ---
        
        # 1. TOP ROW (Heaters, Temp, Timer) - PACK FIRST
        # This ensures the Temp/Timer area reserves its height before the status row
        top_data_row = ttk.Frame(self.hero_frame, style='Hero.TFrame')
        top_data_row.pack(side='top', fill='both', expand=True, padx=10)
        self._bind_header_clicks(top_data_row)
        
        # A. HEATERS
        heater_stack = ttk.Frame(top_data_row, style='Hero.TFrame')
        heater_stack.pack(side='left', anchor='center', padx=(0, 10), fill='y') 
        self._bind_header_clicks(heater_stack)

        self.h1_container = tk.Frame(heater_stack, bg='#222222', height=24, width=60)
        self.h1_container.pack(side='top', pady=(10, 2))
        self.h1_container.pack_propagate(False) 
        
        self.h2_container = tk.Frame(heater_stack, bg='#222222', height=24, width=60)
        self.h2_container.pack(side='top', pady=(2, 0))
        self.h2_container.pack_propagate(False)

        self.lbl_h1 = tk.Label(self.h1_container, text="1000W", font=('Arial', 10, 'bold'),
                               bg='#e74c3c', fg='white', relief='flat')
        self.lbl_h2 = tk.Label(self.h2_container, text="800W", font=('Arial', 10, 'bold'),
                               bg='#e67e22', fg='white', relief='flat')

        # B. TEMP
        left_stack = ttk.Frame(top_data_row, style='Hero.TFrame')
        left_stack.pack(side='left', anchor='center', expand=True)
        self._bind_header_clicks(left_stack)
        
        self.lbl_temp = ttk.Label(left_stack, textvariable=self.current_temp_var, style='HeroTemp.TLabel')
        self.lbl_temp.pack(side='top', anchor='center')
        self.lbl_temp.bind("<Button-1>", self._on_temp_or_header_click)
        
        self.lbl_sub_target = ttk.Label(left_stack, textvariable=self.target_sub_var, style='HeroSub.TLabel')
        self.lbl_sub_target.pack(side='top', anchor='center')
        self._bind_header_clicks(self.lbl_sub_target)

        # C. DELAY BUTTON
        center_wrapper = tk.Frame(top_data_row, bg='#222222', width=150, height=65)
        center_wrapper.pack(side='left', padx=5, anchor='center')
        center_wrapper.pack_propagate(False) 
        self._bind_header_clicks(center_wrapper)
        
        self.btn_delayed = tk.Button(center_wrapper, text="DELAYED\nSTART", font=('Arial', 12, 'bold'),
                                     command=self._open_delayed_start)
        self._set_btn_color(self.btn_delayed, '#e0e0e0', '#0044CC')
        self.btn_delayed.pack(fill='both', expand=True)

        # D. TIMER
        right_complex = ttk.Frame(top_data_row, style='Hero.TFrame')
        right_complex.pack(side='right', anchor='center', expand=True)
        self._bind_header_clicks(right_complex)
        
        self.cv_heartbeat = tk.Canvas(right_complex, width=16, height=16, 
                                      bg='#222222', highlightthickness=0)
        self.cv_heartbeat.pack(side='right', anchor='center', padx=(10, 0))
        self.heartbeat_id = self.cv_heartbeat.create_oval(2, 2, 14, 14, fill='#444444', outline='')

        right_stack = ttk.Frame(right_complex, style='Hero.TFrame')
        right_stack.pack(side='right', anchor='center')
        self._bind_header_clicks(right_stack)
        
        self.lbl_timer = ttk.Label(right_stack, textvariable=self.timer_var, style='HeroTimer.TLabel')
        self.lbl_timer.pack(side='top', anchor='center')
        self._bind_header_clicks(self.lbl_timer)
        
        self.lbl_sub_elapsed = ttk.Label(right_stack, textvariable=self.elapsed_sub_var, style='HeroSub.TLabel')
        self.lbl_sub_elapsed.pack(side='top', anchor='center')
        self._bind_header_clicks(self.lbl_sub_elapsed)

        # 2. STATUS ROW (Packed SECOND so it expands into remaining space without pushing top row)
        msg_stack = ttk.Frame(self.hero_frame, style='Hero.TFrame')
        msg_stack.pack(side='bottom', fill='x', pady=(0, 5)) 
        self._bind_header_clicks(msg_stack)

        self.lbl_status = ttk.Label(msg_stack, textvariable=self.status_text_var, style='HeroStatus.TLabel', justify='center')
        self.lbl_status.pack(side='top', anchor='center')
        self._bind_header_clicks(self.lbl_status)
        
        self.lbl_addition = ttk.Label(msg_stack, textvariable=self.next_addition_var, style='HeroAddition.TLabel', justify='center')
        self.lbl_addition.pack(side='top', anchor='center')
        self._bind_header_clicks(self.lbl_addition)
    
    # def _create_hero_widgets(self):
        # # 1. STATUS ROW (Packed First)
        # msg_stack = ttk.Frame(self.hero_frame, style='Hero.TFrame')
        # msg_stack.pack(side='bottom', fill='x', pady=(0, 5)) 
        # self._bind_header_clicks(msg_stack)

        # self.lbl_status = ttk.Label(msg_stack, textvariable=self.status_text_var, style='HeroStatus.TLabel', justify='center')
        # self.lbl_status.pack(side='top', anchor='center')
        # self._bind_header_clicks(self.lbl_status)
        
        # self.lbl_addition = ttk.Label(msg_stack, textvariable=self.next_addition_var, style='HeroAddition.TLabel', justify='center')
        # self.lbl_addition.pack(side='top', anchor='center')
        # self._bind_header_clicks(self.lbl_addition)

        # # 2. TOP ROW (Heaters, Temp, Timer)
        # top_data_row = ttk.Frame(self.hero_frame, style='Hero.TFrame')
        # top_data_row.pack(side='top', fill='both', expand=True, padx=10)
        # self._bind_header_clicks(top_data_row)
        
        # # A. HEATERS
        # heater_stack = ttk.Frame(top_data_row, style='Hero.TFrame')
        # heater_stack.pack(side='left', anchor='center', padx=(0, 10), fill='y') 
        # self._bind_header_clicks(heater_stack)

        # self.h1_container = tk.Frame(heater_stack, bg='#222222', height=24, width=60)
        # self.h1_container.pack(side='top', pady=(10, 2))
        # self.h1_container.pack_propagate(False) 
        
        # self.h2_container = tk.Frame(heater_stack, bg='#222222', height=24, width=60)
        # self.h2_container.pack(side='top', pady=(2, 0))
        # self.h2_container.pack_propagate(False)

        # self.lbl_h1 = tk.Label(self.h1_container, text="1000W", font=('Arial', 10, 'bold'),
                               # bg='#e74c3c', fg='white', relief='flat')
        # self.lbl_h2 = tk.Label(self.h2_container, text="800W", font=('Arial', 10, 'bold'),
                               # bg='#e67e22', fg='white', relief='flat')

        # # B. TEMP
        # left_stack = ttk.Frame(top_data_row, style='Hero.TFrame')
        # left_stack.pack(side='left', anchor='center', expand=True)
        # self._bind_header_clicks(left_stack)
        
        # self.lbl_temp = ttk.Label(left_stack, textvariable=self.current_temp_var, style='HeroTemp.TLabel')
        # self.lbl_temp.pack(side='top', anchor='center')
        # self.lbl_temp.bind("<Button-1>", self._on_temp_or_header_click)
        
        # self.lbl_sub_target = ttk.Label(left_stack, textvariable=self.target_sub_var, style='HeroSub.TLabel')
        # self.lbl_sub_target.pack(side='top', anchor='center')
        # self._bind_header_clicks(self.lbl_sub_target)

        # # C. DELAY BUTTON
        # center_wrapper = tk.Frame(top_data_row, bg='#222222', width=150, height=65)
        # center_wrapper.pack(side='left', padx=5, anchor='center')
        # center_wrapper.pack_propagate(False) 
        # self._bind_header_clicks(center_wrapper)
        
        # self.btn_delayed = tk.Button(center_wrapper, text="DELAYED\nSTART", font=('Arial', 12, 'bold'),
                                     # command=self._open_delayed_start)
        # self._set_btn_color(self.btn_delayed, '#e0e0e0', '#0044CC')
        # self.btn_delayed.pack(fill='both', expand=True)

        # # D. TIMER
        # right_complex = ttk.Frame(top_data_row, style='Hero.TFrame')
        # right_complex.pack(side='right', anchor='center', expand=True)
        # self._bind_header_clicks(right_complex)
        
        # self.cv_heartbeat = tk.Canvas(right_complex, width=16, height=16, 
                                      # bg='#222222', highlightthickness=0)
        # self.cv_heartbeat.pack(side='right', anchor='center', padx=(10, 0))
        # self.heartbeat_id = self.cv_heartbeat.create_oval(2, 2, 14, 14, fill='#444444', outline='')

        # right_stack = ttk.Frame(right_complex, style='Hero.TFrame')
        # right_stack.pack(side='right', anchor='center')
        # self._bind_header_clicks(right_stack)
        
        # self.lbl_timer = ttk.Label(right_stack, textvariable=self.timer_var, style='HeroTimer.TLabel')
        # self.lbl_timer.pack(side='top', anchor='center')
        # self._bind_header_clicks(self.lbl_timer)
        
        # self.lbl_sub_elapsed = ttk.Label(right_stack, textvariable=self.elapsed_sub_var, style='HeroSub.TLabel')
        # self.lbl_sub_elapsed.pack(side='top', anchor='center')
        # self._bind_header_clicks(self.lbl_sub_elapsed)

    def _bind_header_clicks(self, widget):
        widget.bind("<Button-1>", self._on_header_click)

    def _create_sequence_strip_widgets(self):
        self.view_auto = ttk.Frame(self.strip_frame, style='Strip.TFrame')
        self.view_auto.pack(fill='both', expand=True)
        
        scrollbar = ttk.Scrollbar(self.view_auto)
        scrollbar.pack(side='right', fill='y')
        
        columns = ('step_num', 'name', 'target', 'duration', 'ready', 'action')
        self.step_list = ttk.Treeview(self.view_auto, columns=columns, show='headings', yscrollcommand=scrollbar.set, height=5)
        
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
        
        self.step_list.tag_configure('done_step', foreground='#777777')
        self.step_list.tag_configure('active_step', background='#34495e', foreground='white', font=('Arial', 12, 'bold'))
        self.step_list.tag_configure('pending_step', foreground='black')
        self.step_list.tag_configure('alert_step', background='#f1c40f', foreground='black', font=('Arial', 12, 'bold'))
        
        self.step_list.pack(side='left', fill='both', expand=True)
        scrollbar.config(command=self.step_list.yview)
        
        self.view_manual = ManualPanel(self.strip_frame, self.sequencer, self.settings, self.status_text_var)

    def _set_layout_mode(self, mode="AUTO"):
        # INCREASED target_hero_h to 135 (Was 120)
        target_hero_h = 135
        target_strip_h = 220
        
        if self.hero_frame.winfo_height() != target_hero_h:
            self.hero_frame.configure(height=target_hero_h)
            
        if self.strip_frame.winfo_height() != target_strip_h:
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
            
            ready_str = getattr(step, 'predicted_ready_time', "")
            if ready_str is None: ready_str = ""
            
            step_iid = str(i)
            self.step_list.insert(
                "", "end", iid=step_iid,
                values=(i + 1, step.name, temp_str, dur_str, ready_str, mode_str),
                tags=('pending_step',), open=True
            )
            
            if hasattr(step, 'additions') and step.additions:
                sorted_additions = sorted(step.additions, key=lambda x: x.time_point_min, reverse=True)
                for j, add in enumerate(sorted_additions):
                    child_iid = f"{step_iid}_add_{j}"
                    add_name = f"   ↳ {add.name}"
                    add_time = f"@ {add.time_point_min}m"
                    self.step_list.insert(
                        step_iid, "end", iid=child_iid,
                        values=("", add_name, "", add_time, "", "Alert"),
                        tags=('pending_step',)
                    )

    def _create_control_widgets(self):
        wrapper = tk.Frame(self.controls_frame, bg='#222222', height=60)
        wrapper.pack(side='bottom', fill='x', pady=0)
        wrapper.pack_propagate(False) 
        
        wrapper.columnconfigure(0, weight=1) 
        wrapper.columnconfigure(1, weight=2) 
        wrapper.columnconfigure(2, weight=1) 
        wrapper.rowconfigure(0, weight=1)
        wrapper.rowconfigure(1, weight=1)
        
        self.btn_mode_auto = tk.Button(wrapper, text="AUTO", font=('Arial', 14, 'bold'),
                                       command=lambda: self._request_mode_switch("AUTO"))
        self._set_btn_color(self.btn_mode_auto, '#e0e0e0', '#0044CC')
        self.btn_mode_auto.grid(row=0, column=0, sticky='nsew', padx=1, pady=1)
        
        self.btn_mode_manual = tk.Button(wrapper, text="MANUAL", font=('Arial', 14, 'bold'),
                                         command=lambda: self._request_mode_switch("MANUAL"))
        self._set_btn_color(self.btn_mode_manual, '#e0e0e0', '#0044CC')
        self.btn_mode_manual.grid(row=1, column=0, sticky='nsew', padx=1, pady=1)

        self.btn_action = tk.Button(wrapper, textvariable=self.action_btn_text, font=('Arial', 14, 'bold'),
                                    command=self._on_action_click)
        self._set_btn_color(self.btn_action, '#e0e0e0', '#0044CC')
        self.btn_action.grid(row=0, column=1, rowspan=2, sticky='nsew', padx=1, pady=1)

        self.btn_stop = tk.Button(wrapper, text="STOP", font=('Arial', 14, 'bold'),
                                  command=self._on_abort_click)
        self._set_btn_color(self.btn_stop, '#e74c3c', 'white')
        self.btn_stop.grid(row=0, column=2, sticky='nsew', padx=1, pady=1)
        
        self.btn_settings = tk.Button(wrapper, text="SETTINGS", font=('Arial', 14, 'bold'),
                                      command=self._on_settings_click)
        self._set_btn_color(self.btn_settings, '#e0e0e0', '#0044CC')
        self.btn_settings.grid(row=1, column=2, sticky='nsew', padx=1, pady=1)

    def _on_sys_minimize(self):
        try: self.root.iconify()
        except Exception as e: print(f"[UI] Minimize error: {e}")

    def _on_sys_close(self):
        if messagebox.askyesno("Exit App", "Close KettleBrain and return to desktop?", parent=self.root):
            try: self.root.destroy()
            except Exception: pass

    def _on_settings_click(self):
        try:
            grabber = self.root.grab_current()
            if grabber: grabber.grab_release()
        except: pass
        self.root.after(50, self._real_settings_logic)

    def _real_settings_logic(self):
        if self.settings_window:
            try:
                if self.settings_window.winfo_exists():
                    self.settings_window.lift()
                    return
                else:
                    self.settings_window = None
            except:
                self.settings_window = None
        self.settings_window = SettingsPopup(
            self.root, self.settings, self.hw, self.sequencer.relay, self.sequencer
        )

    def _on_action_click(self):
        st = self.sequencer.status
        if st == SequenceStatus.MANUAL:
            if hasattr(self.sequencer, 'toggle_manual_playback'):
                self.sequencer.toggle_manual_playback()
            elif hasattr(self.sequencer, 'is_manual_running'):
                if self.sequencer.is_manual_running:
                    self.sequencer.pause_manual_mode()
                else:
                    self.sequencer.resume_manual_mode()
            return

        if st == SequenceStatus.IDLE:
            self.sequencer.start_sequence()
        elif st == SequenceStatus.RUNNING:
            self.sequencer.pause_sequence()
        elif st == SequenceStatus.PAUSED:
            self.sequencer.resume_sequence()
        elif st == SequenceStatus.WAITING_FOR_USER:
            if self.sequencer.current_alert_text == "Step Complete":
                self.sequencer.advance_step()
            else:
                self.sequencer.resume_sequence()
        self.update_ui_from_state()

    def _on_abort_click(self):
        try:
            grabber = self.root.grab_current()
            if grabber: grabber.grab_release()
        except: pass
        
        # CHANGED: Show popup for ANY active state (anything not IDLE)
        # This covers RUNNING, PAUSED, WAITING, MANUAL, DELAYED_WAIT, COMPLETED
        if self.sequencer.status != SequenceStatus.IDLE:
            from ui_manager import CustomConfirmDialog 
            CustomConfirmDialog(
                self.root, "Stop / Reset?", "This will STOP operation and RESET progress.\nAre you sure?",
                callback=self._real_abort_logic
            )
        else:
            # If already IDLE, just ensure we are clean
            self._real_abort_logic()

    def _real_abort_logic(self):
        st = self.sequencer.status
        
        # CASE 1: Delayed Start
        if st == SequenceStatus.DELAYED_WAIT:
            # cancel_delayed_mode() handles returning to IDLE or MANUAL 
            # based on where it was launched from (Requirement 2A).
            self.sequencer.cancel_delayed_mode()
            
        # CASE 2: Manual Mode
        elif st == SequenceStatus.MANUAL:
            # Requirement 2B: Return to Manual Mode (Reset state).
            # enter_manual_mode() stops heaters/timers and resets state 
            # while keeping Status=MANUAL.
            self.sequencer.enter_manual_mode()
            
        # CASE 3: Auto Mode (Running, Paused, Waiting, Completed)
        elif st in [SequenceStatus.RUNNING, SequenceStatus.PAUSED, SequenceStatus.WAITING_FOR_USER, SequenceStatus.COMPLETED]:
            # Requirement 2C: Reset as if just loaded.
            # This stops relays, sets status to IDLE, rewinds step index to 0, and clears alerts.
            self.sequencer.reset_profile()
            
        # Fallback / Safety
        else:
            self.sequencer.stop()

        # Update UI Elements immediately
        self._set_btn_color(self.btn_mode_auto, '#e0e0e0', '#0044CC')
        
        # If we returned to Manual Mode, highlight that button
        if self.sequencer.status == SequenceStatus.MANUAL:
            self._set_btn_color(self.btn_mode_manual, '#2ecc71', 'black')
        else:
            self._set_btn_color(self.btn_mode_manual, '#e0e0e0', '#0044CC')
            
        self.action_btn_text.set("START")
        self.btn_action.config(state='normal')
        self.update_ui_from_state()

    def _on_header_click(self, event):
        now = self.root.tk.call('clock', 'clicks', '-milliseconds')
        if now - self.last_click_time < 500:
            self.title_clicks += 1
        else:
            self.title_clicks = 1
        self.last_click_time = now
        if self.title_clicks >= 5:
            self.title_clicks = 0
            self._on_sys_close()

    def _on_temp_or_header_click(self, event):
        self._on_header_click(event)

    def _update_loop(self):
        try:
            self.update_ui_from_state()
        except Exception:
            traceback.print_exc()
        finally:
            self.root.after(200, self._update_loop)

    def update_ui_from_state(self):
        import time 
        if not hasattr(self, 'last_pred_refresh'): self.last_pred_refresh = 0
        now = time.time()
        if now - self.last_pred_refresh > 30.0:
            if self.sequencer.current_profile:
                self.sequencer.update_predictions()
                for i, step in enumerate(self.sequencer.current_profile.steps):
                    iid = str(i)
                    if self.step_list.exists(iid):
                        current_vals = self.step_list.item(iid, "values")
                        new_ready = getattr(step, 'predicted_ready_time', "")
                        if current_vals and len(current_vals) > 4:
                            if str(current_vals[4]) != str(new_ready):
                                new_vals_list = list(current_vals)
                                new_vals_list[4] = new_ready
                                self.step_list.item(iid, values=new_vals_list)
            self.last_pred_refresh = now
        
        t = self.sequencer.current_temp
        st = self.sequencer.status
        tgt = self.sequencer.get_target_temp()

        show_manual_view = False
        if st == SequenceStatus.MANUAL:
            show_manual_view = True
        elif st == SequenceStatus.DELAYED_WAIT:
            show_manual_view = True
            
        # Update layout heights dynamically for 480p
        if show_manual_view:
            self._set_layout_mode("MANUAL")
        else:
            self._set_layout_mode("AUTO")

        if show_manual_view:
            if self.view_auto.winfo_ismapped():
                self.root.focus_set()
                self.view_auto.pack_forget()
            if not self.view_manual.winfo_ismapped():
                self.view_manual.pack(fill='both', expand=True)
            self.view_manual.refresh()
            self.next_addition_var.set(" ") 
        else:
            if self.view_manual.winfo_ismapped():
                self.root.focus_set()
                self.view_manual.pack_forget()
            if not self.view_auto.winfo_ismapped():
                self.view_auto.pack(fill='both', expand=True)

        formatted_temp = UnitUtils.format_temp(t, self.settings)
        self.current_temp_var.set(formatted_temp)
        t_display = t if t is not None else 0.0
        
        if tgt and tgt > 0:
            fmt_tgt = UnitUtils.format_temp(tgt, self.settings)
            sys_boil = self.settings.get_system_setting("boil_temp_f", 212.0)
            if tgt >= (sys_boil - 0.01):
                self.target_sub_var.set(f"Target: {fmt_tgt} BOILING")
            else:
                self.target_sub_var.set(f"Target: {fmt_tgt}")
        else:
            self.target_sub_var.set("Target: --")

        global_str = self.sequencer.get_global_elapsed_time_str()
        self.elapsed_sub_var.set(f"Elapsed: {global_str}")

        new_style = 'HeroTemp.TLabel' 
        should_color = False
        if st == SequenceStatus.MANUAL:
            if self.sequencer.is_manual_running: should_color = True
        elif st in [SequenceStatus.RUNNING, SequenceStatus.WAITING_FOR_USER]:
            should_color = True
            
        if should_color and tgt is not None and tgt > 0:
            diff = t_display - tgt
            if diff < -1.0: new_style = 'HeroTempBlue.TLabel'
            elif diff > 1.0: new_style = 'HeroTempRed.TLabel'
            else: new_style = 'HeroTempGreen.TLabel'
        self.lbl_temp.configure(style=new_style)

        if st == SequenceStatus.DELAYED_WAIT:
            time_info = self.sequencer.get_delayed_status_msg()
            btn_txt = f"DELAY - SLEEPING\n{time_info}"
            self.btn_delayed.config(text=btn_txt, font=('Arial', 10, 'bold')) 
            self._set_btn_color(self.btn_delayed, '#0044CC', '#e0e0e0')
            if hasattr(self, 'btn_mode_auto'):
                 self._set_btn_color(self.btn_mode_auto, '#e0e0e0', '#0044CC')
                 self._disable_custom_btn(self.btn_mode_auto)
            if hasattr(self, 'btn_mode_manual'):
                 self._set_btn_color(self.btn_mode_manual, '#2ecc71', 'black')
                 self._disable_custom_btn(self.btn_mode_manual)
            self._disable_custom_btn(self.btn_action)
            self.view_manual.set_enabled(False)
            self.timer_var.set(self.sequencer.get_display_timer())
            self._update_indicators(st, time.time())
            return 
        else:
            self.btn_delayed.config(text="DELAYED\nSTART", font=('Arial', 12, 'bold'))
            self._set_btn_color(self.btn_delayed, '#e0e0e0', '#0044CC')
            self.view_manual.set_enabled(True)
            if st == SequenceStatus.IDLE:
                 if hasattr(self, 'btn_mode_auto'): self.btn_mode_auto.config(state='normal')
                 if hasattr(self, 'btn_mode_manual'): self.btn_mode_manual.config(state='normal')
                 self.action_btn_text.set("START")
                 self._set_btn_color(self.btn_action, '#e0e0e0', '#0044CC')
                 if self.view_auto.winfo_ismapped():
                     if hasattr(self, 'btn_mode_auto'): self._set_btn_color(self.btn_mode_auto, '#2ecc71', 'black')
                     if hasattr(self, 'btn_mode_manual'): self._set_btn_color(self.btn_mode_manual, '#e0e0e0', '#0044CC')

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
                    except: pass

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
             
        self._update_indicators(st, time.time())

    def _update_indicators(self, status, now):
        h1_on = False
        h2_on = False
        if hasattr(self.sequencer, 'relay'):
             h1_on = self.sequencer.relay.relay_states.get("Heater1", False)
             h2_on = self.sequencer.relay.relay_states.get("Heater2", False)

        if h1_on:
            if not self.lbl_h1.winfo_ismapped():
                self.lbl_h1.pack(fill='both', expand=True)
        else:
            if self.lbl_h1.winfo_ismapped():
                self.lbl_h1.pack_forget()
            
        if h2_on:
            if not self.lbl_h2.winfo_ismapped():
                self.lbl_h2.pack(fill='both', expand=True)
        else:
            if self.lbl_h2.winfo_ismapped():
                self.lbl_h2.pack_forget()
            
        color = '#444444' 
        should_pulse_green = False
        
        if status == SequenceStatus.RUNNING:
            should_pulse_green = True
        elif status == SequenceStatus.MANUAL:
            if self.sequencer.is_manual_running:
                should_pulse_green = True
        
        if should_pulse_green:
            if (int(now) % 2) == 0: color = '#2ecc71' 
            else: color = '#145a32' 
        elif status == SequenceStatus.WAITING_FOR_USER:
            if (int(now * 4) % 2) == 0: color = '#f1c40f' 
            else: color = '#7d6608' 
        elif status == SequenceStatus.DELAYED_WAIT:
            if (int(now) % 2) == 0: color = '#3498db'
            else: color = '#1b4f72'
                
        self.cv_heartbeat.itemconfig(self.heartbeat_id, fill=color)

class CustomConfirmDialog(tk.Toplevel):
    def __init__(self, parent, title, message, callback=None):
        super().__init__(parent)
        self.callback = callback
        self.title(title)
        self.configure(bg='#ecf0f1')
        self.geometry("480x240")
        self.transient(parent) 
        self.resizable(False, False)
        try:
            sw = self.winfo_screenwidth()
            sh = self.winfo_screenheight()
            x = (sw - 480) // 2
            y = (sh - 240) // 2
            self.geometry(f"+{x}+{y}")
        except: pass
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
        self.deiconify()
        self.lift()
        self.focus_force()

    def _on_yes(self):
        if self.callback:
            self.root = self.master 
            self.destroy()
            self.root.after(50, self._run_callback)
        else:
            self.destroy()

    def _run_callback(self):
        if self.callback:
            self.callback()

    def _on_no(self):
        self.destroy()

class DelayedStartActionDialog(tk.Toplevel):
    def __init__(self, parent, on_cancel, on_edit, on_cleanup=None):
        super().__init__(parent)
        self.withdraw()
        self.on_cancel = on_cancel
        self.on_edit = on_edit
        self.on_cleanup = on_cleanup
        self.title("Delayed Start Active")
        self.configure(bg='#ecf0f1')
        self.geometry("400x180")
        self.transient(parent)
        self.resizable(False, False)
        try:
            sw = self.winfo_screenwidth()
            sh = self.winfo_screenheight()
            x = (sw - 400) // 2
            y = (sh - 180) // 2
            self.geometry(f"+{x}+{y}")
        except: pass
        lbl = tk.Label(self, text="Delayed Start is currently ACTIVE.\nSystem is sleeping until start time.",
                       font=('Arial', 12), bg='#ecf0f1', fg='#2c3e50', justify='center')
        lbl.pack(pady=20, padx=20, fill='both', expand=True)
        btn_frame = tk.Frame(self, bg='#ecf0f1')
        btn_frame.pack(side='bottom', fill='x', pady=20)
        btn_cancel = tk.Button(btn_frame, text="CANCEL DELAY", font=('Arial', 11, 'bold'),
                               bg='#e74c3c', fg='white', width=14, height=2, relief='flat',
                               command=self._do_cancel)
        btn_cancel.pack(side='left', padx=20, expand=True)
        btn_edit = tk.Button(btn_frame, text="EDIT TIME", font=('Arial', 11, 'bold'),
                             bg='#3498db', fg='white', width=14, height=2, relief='flat',
                             command=self._do_edit)
        btn_edit.pack(side='right', padx=20, expand=True)
        self.protocol("WM_DELETE_WINDOW", self._safe_close)
        self.deiconify()
        self.lift()
        self.focus_force()

    def _do_cancel(self):
        self._safe_close()
        if self.on_cancel: self.on_cancel()

    def _do_edit(self):
        self._safe_close()
        if self.on_edit: self.on_edit()
        
    def _safe_close(self):
        try: self.destroy()
        except: pass
        if self.on_cleanup: self.on_cleanup()

class DelayedStartPopup(tk.Toplevel):
    def __init__(self, parent, sequencer, settings, initial_data=None, initial_context=None, on_cleanup=None):
        super().__init__(parent)
        
        self.withdraw()
        
        self.sequencer = sequencer
        self.settings = settings
        self.initial_context = initial_context
        self.on_cleanup = on_cleanup 
        
        self.title("Delayed Start Setup")
        self.configure(bg='#2c3e50')
        self.geometry("500x380")
        
        self.transient(parent)
        self.resizable(False, False)
        
        try:
            sw = self.winfo_screenwidth()
            sh = self.winfo_screenheight()
            x = (sw - 500) // 2
            y = (sh - 380) // 2
            self.geometry(f"+{x}+{y}")
        except: pass

        # --- 12/24 Hour Detection ---
        now = datetime.now()
        # Fallback: Assume 12h if %p returns text, 24h if empty
        self.is_24h = (now.strftime("%p") == "")

        self.target_vol = 8.0
        self.target_temp = 154.0
        
        # Load Defaults
        if initial_data:
            self.target_vol = initial_data.get('vol', 8.0)
            self.target_temp = initial_data.get('temp', 154.0)
        else:
             self.target_temp = self.settings.get("manual_mode_settings", "last_setpoint_f", 154.0)
             self.target_vol = self.settings.get("manual_mode_settings", "last_volume_gal", 8.0)

        self.var_hours = tk.StringVar()
        self.var_mins = tk.StringVar()
        self.var_ampm = tk.StringVar()
        self.var_temp = tk.DoubleVar(value=self.target_temp)
        self.var_vol = tk.DoubleVar(value=self.target_vol)
        
        # Determine Default Time
        if initial_data and initial_data.get('time_str'):
            try:
                parts = initial_data['time_str'].split()
                t_part = parts[0]
                hh, mm = t_part.split(':')
                
                if self.is_24h:
                    if len(parts) > 1: 
                        ap = parts[1]
                        h_int = int(hh)
                        if ap == "PM" and h_int != 12: h_int += 12
                        elif ap == "AM" and h_int == 12: h_int = 0
                        self.var_hours.set(f"{h_int:02d}")
                    else:
                        self.var_hours.set(hh)
                    self.var_ampm.set("")
                else:
                    self.var_hours.set(hh)
                    if len(parts) > 1: self.var_ampm.set(parts[1])
                    else: self.var_ampm.set("AM")
                self.var_mins.set(mm)
            except: 
                self._set_default_time()
        else:
            self._set_default_time()

        self._build_ui()
        self.deiconify()
        self.lift()
        self.focus_force()
        self.protocol("WM_DELETE_WINDOW", self._safe_close)

    def _set_default_time(self):
        now = datetime.now()
        next_target = now.replace(hour=6, minute=0, second=0, microsecond=0)
        if next_target <= now:
            next_target += timedelta(days=1)
            
        if self.is_24h:
            self.var_hours.set(next_target.strftime("%H"))
            self.var_ampm.set("")
        else:
            self.var_hours.set(next_target.strftime("%I"))
            self.var_ampm.set(next_target.strftime("%p"))
            
        self.var_mins.set(next_target.strftime("%M"))

    def _build_ui(self):
        # 1. TIME SECTION
        f_time = tk.LabelFrame(self, text="Ready Time", font=('Arial', 12, 'bold'), 
                               bg='#2c3e50', fg='white', bd=1)
        f_time.pack(fill='x', padx=20, pady=10)
        
        f_clock = tk.Frame(f_time, bg='#2c3e50')
        f_clock.pack(pady=10)
        
        # Configure Ranges
        if self.is_24h:
            h_from, h_to = 0, 23
        else:
            h_from, h_to = 1, 12

        # FIX: repeatdelay set to ~16 minutes effectively DISABLES auto-repeat
        # This forces the user to tap/click for every increment, preventing "runaway".
        sb_h = tk.Spinbox(f_clock, from_=h_from, to=h_to, textvariable=self.var_hours,
                          font=('Arial', 24, 'bold'), width=3, justify='center', 
                          format="%02.0f", wrap=True,
                          repeatdelay=1000000, repeatinterval=1000000) 
        sb_h.pack(side='left', padx=5)
        
        tk.Label(f_clock, text=":", font=('Arial', 24, 'bold'), bg='#2c3e50', fg='white').pack(side='left')
        
        sb_m = tk.Spinbox(f_clock, from_=0, to=59, textvariable=self.var_mins,
                          font=('Arial', 24, 'bold'), width=3, justify='center', 
                          format="%02.0f", wrap=True,
                          repeatdelay=1000000, repeatinterval=1000000)
        sb_m.pack(side='left', padx=5)
        
        # AM/PM Selector
        if not self.is_24h:
            vals = ('AM', 'PM')
            sb_ap = tk.Spinbox(f_clock, values=vals, textvariable=self.var_ampm,
                               font=('Arial', 24, 'bold'), width=4, justify='center', 
                               wrap=True, state='readonly',
                               repeatdelay=1000000, repeatinterval=1000000)
            sb_ap.pack(side='left', padx=10)

        # 2. TARGETS SECTION
        f_targs = tk.Frame(self, bg='#2c3e50')
        f_targs.pack(fill='x', padx=20, pady=5)
        
        tk.Label(f_targs, text="Target Temp (°F):", font=('Arial', 11), bg='#2c3e50', fg='#bdc3c7').grid(row=0, column=0, sticky='w', pady=5)
        s_temp = tk.Scale(f_targs, from_=70, to=212, orient='horizontal', variable=self.var_temp,
                          bg='#2c3e50', fg='white', highlightthickness=0, length=250)
        s_temp.grid(row=0, column=1, sticky='ew', padx=10)
        tk.Label(f_targs, textvariable=self.var_temp, font=('Arial', 11, 'bold'), bg='#2c3e50', fg='white').grid(row=0, column=2)
        
        tk.Label(f_targs, text="Volume (Gal):", font=('Arial', 11), bg='#2c3e50', fg='#bdc3c7').grid(row=1, column=0, sticky='w', pady=15)
        s_vol = tk.Scale(f_targs, from_=2.0, to=9.0, resolution=0.25, orient='horizontal', variable=self.var_vol,
                          bg='#2c3e50', fg='white', highlightthickness=0, length=250)
        s_vol.grid(row=1, column=1, sticky='ew', padx=10)
        tk.Label(f_targs, textvariable=self.var_vol, font=('Arial', 11, 'bold'), bg='#2c3e50', fg='white').grid(row=1, column=2)

        # 3. ACTION BUTTONS
        f_btn = tk.Frame(self, bg='#2c3e50')
        f_btn.pack(side='bottom', fill='x', pady=20)
        
        b_cancel = tk.Button(f_btn, text="CANCEL", font=('Arial', 12, 'bold'),
                             bg='#e74c3c', fg='white', height=2, width=12, relief='flat',
                             command=self._safe_close)
        b_cancel.pack(side='left', padx=30)
        
        b_ok = tk.Button(f_btn, text="ACTIVATE DELAY", font=('Arial', 12, 'bold'),
                         bg='#2ecc71', fg='white', height=2, width=18, relief='flat',
                         command=self._on_activate)
        b_ok.pack(side='right', padx=30)

    def _safe_close(self):
        try:
            self.destroy()
        except: pass
        if self.on_cleanup: self.on_cleanup()

    def _on_activate(self):
        try:
            hh = int(self.var_hours.get())
            mm = int(self.var_mins.get())
            now = datetime.now()
            
            # 1. Resolve Target Hour (12h vs 24h)
            if self.is_24h:
                target_hour = hh
            else:
                ap = self.var_ampm.get()
                if ap == "PM" and hh != 12: target_hour = hh + 12
                elif ap == "AM" and hh == 12: target_hour = 0
                else: target_hour = hh
            
            target_dt = now.replace(hour=target_hour, minute=mm, second=0, microsecond=0)
            
            # If target is in past, assume tomorrow
            if target_dt <= now:
                target_dt += timedelta(days=1)
                
            t_f = self.var_temp.get()
            v_gal = self.var_vol.get()
            
            # FIX: Force Stop before calling start_delayed_mode.
            # The sequencer requires IDLE state to accept a new mode.
            if hasattr(self.sequencer, 'stop'):
                self.sequencer.stop()
            
            # FIX: Call the function without expecting a return value.
            # (The backend function likely returns None even on success)
            self.sequencer.start_delayed_mode(
                t_f, 
                v_gal, 
                target_dt, 
                from_auto_mode=self.initial_context
            )
            
            # FIX: Verify success by checking the system STATUS instead.
            if self.sequencer.status == SequenceStatus.DELAYED_WAIT:
                self._safe_close()
            else:
                msg = f"Sequencer failed to enter Delayed Mode.\nCurrent Status: {self.sequencer.status}"
                messagebox.showerror("Activation Failed", msg, parent=self)
                
        except Exception as e:
            messagebox.showerror("Error", f"Invalid Time/Data: {e}", parent=self)
