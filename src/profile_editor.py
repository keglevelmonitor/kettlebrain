"""
kettlebrain app
profile_editor.py
"""
import tkinter as tk
from tkinter import ttk, messagebox
import copy
from datetime import datetime, timedelta
from profile_data import BrewProfile, BrewStep, StepType, TimeoutBehavior, BrewAddition
from utils import UnitUtils, BrewMath, WaterProfileLoader

class AdditionsDialog(tk.Toplevel):
    def __init__(self, parent, step_name, additions_list):
        super().__init__(parent)
        self.withdraw()
        self.title(f"Alerts for: {step_name}")
        self.geometry("400x300")
        self.transient(parent)
        self.attributes('-topmost', True)
        
        self.additions = additions_list 
        self.editing_index = None    
        
        self._layout()
        self._refresh()
        
        self.update_idletasks()
        try:
            x = parent.winfo_rootx() + 20
            y = parent.winfo_rooty() + 20
            self.geometry(f"+{x}+{y}")
        except:
            pass

        self.deiconify()
        self.lift()
        self.focus_force()
        self.protocol("WM_DELETE_WINDOW", self.close)

    def close(self):
        self.destroy()

    def _layout(self):
        list_frame = ttk.Frame(self, padding=5)
        list_frame.pack(fill='both', expand=True)
         
        self.lb_additions = tk.Listbox(list_frame, height=6, font=('Arial', 11))
        self.lb_additions.pack(side='left', fill='both', expand=True)
        
        sb = ttk.Scrollbar(list_frame, orient='vertical', command=self.lb_additions.yview)
        sb.pack(side='right', fill='y')
        
        self.lb_additions.config(yscrollcommand=sb.set)
        
        input_frame = ttk.LabelFrame(self, text="Item Details", padding=5)
        input_frame.pack(fill='x', padx=5)
        
        ttk.Label(input_frame, text="Name:").grid(row=0, column=0, sticky='w')
        self.var_name = tk.StringVar()
        ttk.Entry(input_frame, textvariable=self.var_name).grid(row=0, column=1, sticky='ew', padx=5)
        
        ttk.Label(input_frame, text="Min Remaining:").grid(row=1, column=0, sticky='w')
        self.var_time = tk.StringVar()
        ttk.Entry(input_frame, textvariable=self.var_time, width=5).grid(row=1, column=1, sticky='w', padx=5)
        
        input_frame.columnconfigure(1, weight=1)
        
        btn_frame = ttk.Frame(self, padding=5)
        btn_frame.pack(fill='x')
        
        self.btn_save = ttk.Button(btn_frame, text="Add New", command=self._save_addition)
        self.btn_save.pack(side='left', fill='x', expand=True, padx=2)
        
        ttk.Button(btn_frame, text="Edit Selected", command=self._load_for_edit).pack(side='left', fill='x', expand=True, padx=2)
        ttk.Button(btn_frame, text="Remove", command=self._remove).pack(side='left', fill='x', expand=True, padx=2)

        done_frame = ttk.Frame(self, padding=(5, 0, 5, 5))
        done_frame.pack(fill='x', side='bottom')
        ttk.Button(done_frame, text="Done / Close", command=self.close).pack(fill='x', pady=2)

    def _refresh(self):
        self.lb_additions.delete(0, tk.END)
        self.additions.sort(key=lambda x: x.time_point_min, reverse=True)
        for add in self.additions:
            self.lb_additions.insert(tk.END, f"{add.time_point_min}m: {add.name}")

    def _load_for_edit(self):
        sel = self.lb_additions.curselection()
        if not sel: return
        idx = sel[0]
        self.editing_index = idx
        item = self.additions[idx]
        self.var_name.set(item.name)
        self.var_time.set(str(item.time_point_min))
        self.btn_save.config(text="Update Item")

    def _save_addition(self):
        name = self.var_name.get().strip()
        t_str = self.var_time.get().strip()
        if not name or not t_str: return
        
        try:
            t_val = int(t_str)
            if self.editing_index is not None:
                item = self.additions[self.editing_index]
                item.name = name
                item.time_point_min = t_val
                self.editing_index = None
                self.btn_save.config(text="Add New")
            else:
                new_add = BrewAddition(name=name, time_point_min=t_val)
                self.additions.append(new_add)
                
            self._refresh()
            self.var_name.set("")
            self.var_time.set("")
        except ValueError:
            messagebox.showerror("Error", "Time must be an integer (minutes).", parent=self)

    def _remove(self):
        sel = self.lb_additions.curselection()
        if not sel: return
        if self.editing_index == sel[0]:
            self.editing_index = None
            self.btn_save.config(text="Add New")
            self.var_name.set("")
            self.var_time.set("")
        self.additions.pop(sel[0])
        self._refresh()


class ProfileEditor(tk.Toplevel):
    def __init__(self, parent, profile: BrewProfile, settings_manager, sequencer, on_save_callback):
        super().__init__(parent)
        self.withdraw()
        
        self.title(f"Editing Profile: {profile.name}")
        
        # --- FIXED SIZE & CENTERED STRATEGY ---
        # Target: 800x430
        target_w = 800
        target_h = 420
        
        # Get actual screen dimensions
        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()
        
        # Calculate center position
        x = (screen_w // 2) - (target_w // 2)
        y = (screen_h // 2) - (target_h // 2)
        
        # Ensure Y is not negative (keeps title bar accessible)
        y = max(0, y)
        
        self.geometry(f"{target_w}x{target_h}+{x}+{y}")
        # --------------------------------------

        self.transient(parent)
        self.attributes('-topmost', True)
        
        self.profile = profile
        self.settings = settings_manager
        self.sequencer = sequencer  # Store sequencer reference
        self.on_save = on_save_callback
        
        self.steps_working_copy = copy.deepcopy(profile.steps) 
        self.current_step_index = None 
        self.list_map = [] 
        self.loading_step = False 

        # Init variables for all tabs
        self._init_form_vars()
        self._init_water_vars()
        self._init_chem_vars()
        
        self._configure_styles()
        self._create_layout()
        
        self._refresh_step_list()
        
        if self.steps_working_copy:
            self._select_visual_row(0)
        
        self.protocol("WM_DELETE_WINDOW", self.close)
        
        # Final display sequence
        self.deiconify()
        self.lift()
        self.focus_force()

    def close(self):
        try:
            if self.master:
                self.master.focus_set()
        except:
            pass
        self.destroy()

    def _configure_styles(self):
        s = ttk.Style()
        s.configure('Editor.TFrame', background='#f0f0f0')
        s.configure('StepList.TFrame', background='white', relief='sunken')
        s.configure('Header.TLabel', font=('Arial', 12, 'bold'))
        s.configure('SubHeader.TLabel', font=('Arial', 10, 'bold'), foreground='#555555')

    def _init_form_vars(self):
        # Step Details
        self.var_name = tk.StringVar()
        self.var_type = tk.StringVar()
        self.var_temp = tk.StringVar()
        self.var_duration = tk.StringVar()
        self.var_power = tk.StringVar(value="1800")
        self.var_volume = tk.StringVar()
        self.var_timeout = tk.StringVar()
        self.var_type.trace_add('write', self._on_type_change)

    def _init_water_vars(self):
        # Load from profile.water_data or defaults
        wd = self.profile.water_data
        
        self.calc_method_var = tk.StringVar(value=wd.get("calc_method", "no_sparge"))
        self.calc_grain_wt = tk.DoubleVar(value=wd.get("grain_weight", 10.0))
        self.calc_grain_temp = tk.DoubleVar(value=wd.get("grain_temp", 65.0))
        self.calc_mash_temp = tk.DoubleVar(value=wd.get("mash_temp", 152.0))
        self.calc_target_vol = tk.DoubleVar(value=wd.get("target_vol", 5.5))
        self.calc_trub = tk.DoubleVar(value=wd.get("trub_loss", 0.25))
        self.calc_boil_time = tk.DoubleVar(value=wd.get("boil_time", 60.0))
        self.calc_boiloff = tk.DoubleVar(value=wd.get("boiloff_rate", 0.5))
        self.calc_abs = tk.DoubleVar(value=wd.get("abs_rate", 0.6))
        self.calc_thickness = tk.DoubleVar(value=wd.get("mash_thickness", 1.5))
        
        # Results
        self.res_strike_vol = tk.StringVar(value="--")
        self.res_strike_temp = tk.StringVar(value="--")
        self.res_sparge_vol = tk.StringVar(value="--")
        self.res_mash_vol = tk.StringVar(value="--")
        self.res_pre_boil = tk.StringVar(value="--")
        self.res_post_boil = tk.StringVar(value="--")

    def _init_chem_vars(self):
        # Load from profile.chemistry_data or defaults
        cd = self.profile.chemistry_data
        
        # New: Track the source profile name (default to empty)
        self.var_chem_profile_name = tk.StringVar(value=cd.get("source_profile_name", ""))
        self.loading_chem_profile = False # Safety flag for change detection
        
        self.chem_vol = tk.DoubleVar(value=cd.get("water_vol", 8.0))
        self.chem_srm = tk.DoubleVar(value=cd.get("beer_srm", 5.0))
        self.chem_target_ph = tk.DoubleVar(value=cd.get("target_ph", 5.4))
        
        self.chem_tgt_ca = tk.DoubleVar(value=cd.get("target_ca", 50.0))
        self.chem_tgt_mg = tk.DoubleVar(value=cd.get("target_mg", 10.0))
        self.chem_tgt_na = tk.DoubleVar(value=cd.get("target_na", 0.0))
        self.chem_tgt_so4 = tk.DoubleVar(value=cd.get("target_so4", 70.0))
        self.chem_tgt_cl = tk.DoubleVar(value=cd.get("target_cl", 50.0))
        
        # Results
        self.res_gypsum = tk.StringVar(value="--")
        self.res_cacl2 = tk.StringVar(value="--")
        self.res_epsom = tk.StringVar(value="--")
        self.res_salt = tk.StringVar(value="--")
        self.res_lime = tk.StringVar(value="--")
        self.res_acid = tk.StringVar(value="--")

    def _create_layout(self):
        # 1. PROFILE NAME (Global to all tabs)
        top_frame = ttk.Frame(self)
        top_frame.pack(fill='x', padx=10, pady=5)
        ttk.Label(top_frame, text="Profile Name:", style='Header.TLabel').pack(side='left')
        self.var_profile_name = tk.StringVar(value=self.profile.name)
        ent_name = ttk.Entry(top_frame, textvariable=self.var_profile_name, font=('Arial', 11))
        ent_name.pack(side='left', fill='x', expand=True, padx=10)

        # 2. GLOBAL BUTTONS (Bottom)
        bot_frame = ttk.Frame(self)
        bot_frame.pack(side='bottom', fill='x', padx=10, pady=5)
        ttk.Button(bot_frame, text="Cancel", command=self.close).pack(side='right', padx=5)
        ttk.Button(bot_frame, text="Save Profile", command=self._save_and_close).pack(side='right', padx=5)

        # 3. NOTEBOOK (Main Content)
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(side='top', fill='both', expand=True, padx=5, pady=5)
        
        # TAB 1: Sequence Editor
        self.tab_seq = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_seq, text="Brew Sequence")
        self._build_sequence_tab()
        
        # TAB 2: Profile Water
        self.tab_calc = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_calc, text="Profile Water")
        self._build_water_tab()
        
        # TAB 3: Profile Chemistry
        self.tab_chem = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_chem, text="Profile Chemistry")
        self._build_chem_tab()

    # ==========================
    # TAB 1: SEQUENCE EDITOR
    # ==========================
    def _build_sequence_tab(self):
        content_frame = ttk.Frame(self.tab_seq, padding=5)
        content_frame.pack(fill='both', expand=True)

        # LEFT PANE (List)
        left_pane = ttk.Frame(content_frame, width=220)
        left_pane.pack(side='left', fill='both', padx=(0, 5), expand=False)
        
        ttk.Label(left_pane, text="Steps", style='SubHeader.TLabel').pack(anchor='w', pady=(0, 2))
        
        list_container = ttk.Frame(left_pane)
        list_container.pack(fill='both', expand=True)
        
        # REDUCED HEIGHT: height=8 (was 10) to fit 480px screen
        self.step_listbox = tk.Listbox(list_container, font=('Arial', 10), selectmode=tk.SINGLE, activator=None, height=8)
        self.step_listbox.pack(side='left', fill='both', expand=True)
        self.step_listbox.bind('<<ListboxSelect>>', self._on_step_select)
        
        scroll = ttk.Scrollbar(list_container, orient='vertical', command=self.step_listbox.yview)
        scroll.pack(side='right', fill='y')
        self.step_listbox.config(yscrollcommand=scroll.set)
        
        btn_row = ttk.Frame(left_pane)
        btn_row.pack(fill='x', pady=2)
        ttk.Button(btn_row, text="+", width=4, command=self._add_step).pack(side='left', expand=True, fill='x')
        ttk.Button(btn_row, text="-", width=4, command=self._delete_step).pack(side='left', expand=True, fill='x')
        ttk.Button(btn_row, text="▲", width=3, command=self._move_up).pack(side='left', padx=1)
        ttk.Button(btn_row, text="▼", width=3, command=self._move_down).pack(side='left', padx=1)

        # RIGHT PANE (Form)
        self.right_pane = ttk.LabelFrame(content_frame, text="Selected Step Details", padding=5)
        self.right_pane.pack(side='right', fill='both', expand=True)
        
        self._build_form_widgets()

    def _build_form_widgets(self):
        f = self.right_pane
        f.columnconfigure(1, weight=1)
        f.columnconfigure(3, weight=1)

        row = 0
        pad_y = 5 
        pad_x = 5

        # --- ROW 0: Type & Name ---
        type_opts = [e.value for e in StepType]
        self.cb_type = ttk.Combobox(f, textvariable=self.var_type, values=type_opts, state='readonly', width=12)
        # FIX: Force focus
        self.cb_type.bind("<Button-1>", lambda e: self.after(1, self.cb_type.focus_set))
        
        ttk.Label(f, text="Type:").grid(row=row, column=0, sticky='e', padx=pad_x, pady=pad_y)
        self.cb_type.grid(row=row, column=1, sticky='ew', padx=pad_x, pady=pad_y)
        
        ttk.Label(f, text="Name:").grid(row=row, column=2, sticky='e', padx=pad_x, pady=pad_y)
        ttk.Entry(f, textvariable=self.var_name).grid(row=row, column=3, sticky='ew', padx=pad_x, pady=pad_y)
        row += 1

        # --- ROW 1: Setpoint & Duration ---
        is_metric = UnitUtils.is_metric(self.settings)
        t_label = "Temp (°C):" if is_metric else "Temp (°F):"
        
        self.lbl_temp = ttk.Label(f, text=t_label)
        self.lbl_temp.grid(row=row, column=0, sticky='e', padx=pad_x, pady=pad_y)
        
        self.frm_temp = ttk.Frame(f)
        self.frm_temp.grid(row=row, column=1, sticky='w', padx=pad_x, pady=pad_y)
        
        self.ent_temp = ttk.Entry(self.frm_temp, textvariable=self.var_temp, width=8)
        self.ent_temp.pack(side='left')
        self.lbl_boiling_indicator = ttk.Label(self.frm_temp, text="BOILING", foreground='red', font=('Arial', 9, 'bold'))
        
        self.lbl_dur = ttk.Label(f, text="Duration (min):")
        self.lbl_dur.grid(row=row, column=2, sticky='e', padx=pad_x, pady=pad_y)
        
        self.ent_dur = ttk.Entry(f, textvariable=self.var_duration)
        self.ent_dur.grid(row=row, column=3, sticky='ew', padx=pad_x, pady=pad_y)
        row += 1

        # --- ROW 2: Power & Volume ---
        pwr_values = ["1800", "1400", "1000", "800"]
        self.cb_pwr = ttk.Combobox(f, textvariable=self.var_power, values=pwr_values, state='readonly', width=8)
        # FIX: Force focus
        self.cb_pwr.bind("<Button-1>", lambda e: self.after(1, self.cb_pwr.focus_set))
        
        self.lbl_pwr = ttk.Label(f, text="Watts:")
        self.lbl_pwr.grid(row=row, column=0, sticky='e', padx=pad_x, pady=pad_y)
        self.cb_pwr.grid(row=row, column=1, sticky='w', padx=pad_x, pady=pad_y)
        
        v_label = "Vol (L):" if is_metric else "Vol (Gal):"
        self.lbl_vol = ttk.Label(f, text=v_label)
        self.lbl_vol.grid(row=row, column=2, sticky='e', padx=pad_x, pady=pad_y)
        
        self.ent_vol = ttk.Entry(f, textvariable=self.var_volume)
        self.ent_vol.grid(row=row, column=3, sticky='ew', padx=pad_x, pady=pad_y)
        row += 1
        
        # --- ROW 3: Timeout Behavior ---
        ttk.Label(f, text="Timeout:").grid(row=row, column=0, sticky='e', padx=pad_x, pady=pad_y)
        to_opts = [e.value for e in TimeoutBehavior]
        self.cb_to = ttk.Combobox(f, textvariable=self.var_timeout, values=to_opts, state='readonly')
        # FIX: Force focus
        self.cb_to.bind("<Button-1>", lambda e: self.after(1, self.cb_to.focus_set))
        self.cb_to.grid(row=row, column=1, columnspan=3, sticky='ew', padx=pad_x, pady=pad_y)
        row += 1
        
        # --- ROW 4: Additions Button ---
        self.btn_additions = ttk.Button(f, text="Manage Alerts / Additions...", command=self._open_additions)
        self.btn_additions.grid(row=row, column=1, columnspan=3, sticky='ew', padx=pad_x, pady=pad_y)
        row += 1
        
        # --- ROW 5: Notes ---
        ttk.Label(f, text="Notes:").grid(row=row, column=0, sticky='ne', padx=pad_x, pady=pad_y)
        self.txt_note = tk.Text(f, height=2, width=30, font=('Arial', 10))
        self.txt_note.grid(row=row, column=1, columnspan=3, sticky='ew', padx=pad_x, pady=pad_y)
        row += 1
        
        # --- ROW 6: Alerts Preview ---
        ttk.Label(f, text="Alerts:").grid(row=row, column=0, sticky='ne', padx=pad_x, pady=pad_y)
        self.lb_alerts_preview = tk.Listbox(f, height=3, font=('Arial', 10), bg='white', bd=1, relief='sunken')
        self.lb_alerts_preview.grid(row=row, column=1, columnspan=3, sticky='ew', padx=pad_x, pady=pad_y)
        row += 1
        
        self._toggle_form_state(False)

    # ==========================
    # TAB 2: PROFILE WATER
    # ==========================
    def _build_water_tab(self):
        is_metric = UnitUtils.is_metric(self.settings)
        u_wt = "kg" if is_metric else "lbs"
        u_temp = "°C" if is_metric else "°F"
        u_vol = "L" if is_metric else "Gal"
        u_boiloff = "L/hr" if is_metric else "Gal/hr"
        u_abs = "L/kg" if is_metric else "qt/lb"
        u_thick = "L/kg" if is_metric else "qt/lb"

        # 1. TOP FRAME: Method Selection
        f_top = ttk.Frame(self.tab_calc, padding=5)
        f_top.pack(fill='x')
        ttk.Label(f_top, text="Method:", font=('Arial', 10, 'bold')).pack(side='left', padx=(0, 10))
        ttk.Radiobutton(f_top, text="No Sparge", variable=self.calc_method_var, value="no_sparge", command=self._toggle_calc_inputs).pack(side='left')
        ttk.Radiobutton(f_top, text="Sparge", variable=self.calc_method_var, value="sparge", command=self._toggle_calc_inputs).pack(side='left', padx=10)

        # 2. SPLIT PANE
        paned = ttk.PanedWindow(self.tab_calc, orient='horizontal')
        paned.pack(fill='both', expand=True, padx=10, pady=(0, 10))
        
        # LEFT: Inputs
        f_in = ttk.LabelFrame(paned, text="Recipe Inputs", padding=5)
        paned.add(f_in, weight=1)
        
        r = 0
        pad = 2 
        
        # Inputs
        ttk.Label(f_in, text=f"Grain ({u_wt}):").grid(row=r, column=0, sticky='e', pady=pad); ttk.Entry(f_in, textvariable=self.calc_grain_wt, width=6).grid(row=r, column=1, sticky='w', padx=5); r+=1
        ttk.Label(f_in, text=f"Grain T ({u_temp}):").grid(row=r, column=0, sticky='e', pady=pad); ttk.Entry(f_in, textvariable=self.calc_grain_temp, width=6).grid(row=r, column=1, sticky='w', padx=5); r+=1
        ttk.Label(f_in, text=f"Mash T ({u_temp}):").grid(row=r, column=0, sticky='e', pady=pad); ttk.Entry(f_in, textvariable=self.calc_mash_temp, width=6).grid(row=r, column=1, sticky='w', padx=5); r+=1
        ttk.Separator(f_in, orient='horizontal').grid(row=r, column=0, columnspan=2, sticky='ew', pady=2); r+=1
        ttk.Label(f_in, text=f"Ferm Vol ({u_vol}):").grid(row=r, column=0, sticky='e', pady=pad); ttk.Entry(f_in, textvariable=self.calc_target_vol, width=6).grid(row=r, column=1, sticky='w', padx=5); r+=1
        ttk.Label(f_in, text=f"Trub ({u_vol}):").grid(row=r, column=0, sticky='e', pady=pad); ttk.Entry(f_in, textvariable=self.calc_trub, width=6).grid(row=r, column=1, sticky='w', padx=5); r+=1
        ttk.Label(f_in, text=f"Boil Min:").grid(row=r, column=0, sticky='e', pady=pad); ttk.Entry(f_in, textvariable=self.calc_boil_time, width=6).grid(row=r, column=1, sticky='w', padx=5); r+=1
        ttk.Label(f_in, text=f"Boiloff ({u_boiloff}):").grid(row=r, column=0, sticky='e', pady=pad); ttk.Entry(f_in, textvariable=self.calc_boiloff, width=6).grid(row=r, column=1, sticky='w', padx=5); r+=1
        ttk.Label(f_in, text=f"Abs ({u_abs}):").grid(row=r, column=0, sticky='e', pady=pad); ttk.Entry(f_in, textvariable=self.calc_abs, width=6).grid(row=r, column=1, sticky='w', padx=5); r+=1
        ttk.Label(f_in, text=f"Thick ({u_thick}):").grid(row=r, column=0, sticky='e', pady=pad)
        self.ent_thickness = ttk.Entry(f_in, textvariable=self.calc_thickness, width=6)
        self.ent_thickness.grid(row=r, column=1, sticky='w', padx=5); r+=1
        
        # RIGHT: Results
        f_out = ttk.LabelFrame(paned, text="Requirements", padding=10)
        paned.add(f_out, weight=1)
        
        # HERO SECTION (Side-by-Side Layout)
        f_hero = ttk.Frame(f_out)
        f_hero.pack(fill='x', pady=5)
        
        # Left Hero: Strike Vol
        f_h1 = ttk.Frame(f_hero)
        f_h1.pack(side='left', expand=True, fill='x')
        ttk.Label(f_h1, text="Strike Water:", font=('Arial', 10)).pack(anchor='center')
        ttk.Label(f_h1, textvariable=self.res_strike_vol, font=('Arial', 20, 'bold'), foreground='#0044CC').pack(anchor='center')
        
        # Right Hero: Strike Temp
        f_h2 = ttk.Frame(f_hero)
        f_h2.pack(side='left', expand=True, fill='x')
        ttk.Label(f_h2, text="Strike Temp:", font=('Arial', 10)).pack(anchor='center')
        ttk.Label(f_h2, textvariable=self.res_strike_temp, font=('Arial', 20, 'bold'), foreground='#e74c3c').pack(anchor='center')
        
        # Divider
        ttk.Separator(f_out, orient='horizontal').pack(fill='x', pady=10)
        
        # Details
        f_det = ttk.Frame(f_out)
        f_det.pack(fill='x')
        ttk.Label(f_det, text="Sparge Water:").grid(row=0, column=0, sticky='e')
        ttk.Label(f_det, textvariable=self.res_sparge_vol, font=('Arial', 10, 'bold')).grid(row=0, column=1, sticky='w', padx=5)
        
        ttk.Label(f_det, text="Total Mash Vol:").grid(row=1, column=0, sticky='e')
        ttk.Label(f_det, textvariable=self.res_mash_vol).grid(row=1, column=1, sticky='w', padx=5)
        
        ttk.Label(f_det, text="Pre-Boil Vol:").grid(row=2, column=0, sticky='e')
        ttk.Label(f_det, textvariable=self.res_pre_boil).grid(row=2, column=1, sticky='w', padx=5)
        
        # CALCULATE BUTTON (Bottom)
        ttk.Button(f_out, text="CALCULATE", command=self._calculate_water_req).pack(side='bottom', fill='x', pady=10)
        
        self._toggle_calc_inputs()

    def _toggle_calc_inputs(self):
        if self.calc_method_var.get() == "sparge":
            self.ent_thickness.config(state='normal')
        else:
            self.ent_thickness.config(state='disabled')

    def _calculate_water_req(self):
        try:
            grain_wt = self.calc_grain_wt.get()
            grain_temp = self.calc_grain_temp.get()
            mash_temp = self.calc_mash_temp.get()
            target_vol = self.calc_target_vol.get()
            trub = self.calc_trub.get()
            boil_time = self.calc_boil_time.get()
            boiloff = self.calc_boiloff.get()
            abs_rate = self.calc_abs.get()
            method = self.calc_method_var.get()
            thickness = self.calc_thickness.get()
            
            is_metric = UnitUtils.is_metric(self.settings)
            
            # --- USE SHARED MATH ---
            res = BrewMath.calculate_water(
                grain_wt, grain_temp, mash_temp, target_vol, trub,
                boil_time, boiloff, abs_rate, method, thickness, is_metric
            )

            u_vol = "L" if is_metric else "Gal"
            u_temp = "°C" if is_metric else "°F"
            
            self.res_strike_vol.set(f"{res['strike_vol']:.2f} {u_vol}")
            self.res_strike_temp.set(f"{res['strike_temp']:.1f} {u_temp}")
            self.res_sparge_vol.set(f"{res['sparge_vol']:.2f} {u_vol}")
            self.res_mash_vol.set(f"{res['total_mash_vol']:.2f} {u_vol}")
            self.res_pre_boil.set(f"{res['pre_boil_vol']:.2f} {u_vol}")
            self.res_post_boil.set(f"{res['post_boil_vol']:.2f} {u_vol}")
            
            # Auto-populate chemistry volume
            self.chem_vol.set(round(res['total_water'], 2))
            
        except Exception as e:
            messagebox.showerror("Calc Error", str(e), parent=self)

    # ==========================
    # TAB 3: PROFILE CHEMISTRY
    # ==========================
    def _build_chem_tab(self):
        u_vol = "L" if UnitUtils.is_metric(self.settings) else "Gal"
        
        f = ttk.Frame(self.tab_chem, padding=10)
        f.pack(fill='both', expand=True)
        
        # Left: Targets
        lf = ttk.LabelFrame(f, text="Targets & Stats", padding=10)
        lf.place(relx=0, rely=0, relwidth=0.45, relheight=1.0)
        
        r=0
        pad=4 
        ttk.Label(lf, text=f"Total Water ({u_vol}):").grid(row=r, column=0, sticky='e', pady=pad);
        ttk.Entry(lf, textvariable=self.chem_vol, width=6).grid(row=r, column=1, sticky='w'); r+=1
        ttk.Label(lf, text="Beer SRM:").grid(row=r, column=0, sticky='e', pady=pad);
        ttk.Entry(lf, textvariable=self.chem_srm, width=6).grid(row=r, column=1, sticky='w'); r+=1
        ttk.Label(lf, text="Target pH:").grid(row=r, column=0, sticky='e', pady=pad);
        ttk.Entry(lf, textvariable=self.chem_target_ph, width=6).grid(row=r, column=1, sticky='w'); r+=1
        
        # --- NEW: Water Profile Dropdown ---
        r+=1
        ttk.Label(lf, text="Load Profile:").grid(row=r, column=0, sticky='e', pady=(10, 2))
        
        self.water_profiles = WaterProfileLoader.load_profiles()
        self.profile_names = [p['name'] for p in self.water_profiles]
        
        # Bind to self.var_chem_profile_name so it loads saved values
        self.cb_water_profile = ttk.Combobox(lf, textvariable=self.var_chem_profile_name, values=self.profile_names, state='readonly', width=18)
        self.cb_water_profile.grid(row=r, column=1, sticky='w', pady=(10, 2), padx=0)
        self.cb_water_profile.bind("<<ComboboxSelected>>", self._on_water_profile_select)
        
        # FIX: Force focus on click
        self.cb_water_profile.bind('<Button-1>', lambda e: self.after(1, self.cb_water_profile.focus_set))
        
        r+=1
        # -----------------------------------
        
        # Define Targets with Traces
        targets = [
            ("Target Ca (ppm):", self.chem_tgt_ca),
            ("Target Mg (ppm):", self.chem_tgt_mg),
            ("Target Na (ppm):", self.chem_tgt_na),
            ("Target SO4 (ppm):", self.chem_tgt_so4),
            ("Target Cl (ppm):", self.chem_tgt_cl)
        ]

        for label, var in targets:
            ttk.Label(lf, text=label).grid(row=r, column=0, sticky='e', pady=pad)
            ttk.Entry(lf, textvariable=var, width=6).grid(row=r, column=1, sticky='w')
            # Add listener for manual edits
            var.trace_add("write", self._on_chem_manual_edit)
            r+=1
        
        # Right: Results
        rf = ttk.LabelFrame(f, text="Additions (to Total Water)", padding=10)
        rf.place(relx=0.46, rely=0, relwidth=0.54, relheight=1.0)
        
        r=0
        res_pad = 6
        ttk.Label(rf, text="Gypsum (CaSO4):", font=('Arial', 9, 'bold')).grid(row=r, column=0, sticky='e', pady=res_pad);
        ttk.Label(rf, textvariable=self.res_gypsum, foreground='#0044CC').grid(row=r, column=1, sticky='w', padx=10); r+=1
        ttk.Label(rf, text="Calc. Chlor (CaCl2):", font=('Arial', 9, 'bold')).grid(row=r, column=0, sticky='e', pady=res_pad);
        ttk.Label(rf, textvariable=self.res_cacl2, foreground='#0044CC').grid(row=r, column=1, sticky='w', padx=10); r+=1
        ttk.Label(rf, text="Epsom Salt (MgSO4):", font=('Arial', 9, 'bold')).grid(row=r, column=0, sticky='e', pady=res_pad);
        ttk.Label(rf, textvariable=self.res_epsom, foreground='#0044CC').grid(row=r, column=1, sticky='w', padx=10); r+=1
        ttk.Label(rf, text="Table Salt (NaCl):", font=('Arial', 9, 'bold')).grid(row=r, column=0, sticky='e', pady=res_pad);
        ttk.Label(rf, textvariable=self.res_salt, foreground='#0044CC').grid(row=r, column=1, sticky='w', padx=10); r+=1
        ttk.Label(rf, text="Slaked Lime (CaOH2):", font=('Arial', 9, 'bold')).grid(row=r, column=0, sticky='e', pady=res_pad);
        ttk.Label(rf, textvariable=self.res_lime, foreground='#0044CC').grid(row=r, column=1, sticky='w', padx=10); r+=1
        
        ttk.Separator(rf, orient='horizontal').grid(row=r, column=0, columnspan=2, sticky='ew', pady=10);
        r+=1 
        
        ttk.Label(rf, text="Lactic Acid (88%):", font=('Arial', 10, 'bold')).grid(row=r, column=0, sticky='e', pady=res_pad);
        ttk.Label(rf, textvariable=self.res_acid, font=('Arial', 12, 'bold'), foreground='#e74c3c').grid(row=r, column=1, sticky='w', padx=10); r+=1

        # MOVED BUTTON: Now at the bottom of the Right Frame (Results)
        # Using a spacer or just placing it at the next row
        ttk.Frame(rf, height=10).grid(row=r, column=0); r+=1 # Spacer
        ttk.Button(rf, text="CALCULATE ADDITIONS", command=self._calculate_chemistry).grid(row=r, column=0, columnspan=2, sticky='ew', pady=5)
                                              
    def _on_water_profile_select(self, event):
        selection = self.cb_water_profile.get()
        if not selection: return
        
        profile = next((p for p in self.water_profiles if p['name'] == selection), None)
        if profile:
            try:
                # Set flag so the trace listeners know this is an automatic update
                self.loading_chem_profile = True
                
                self.chem_tgt_ca.set(profile.get('ca', 0))
                self.chem_tgt_mg.set(profile.get('mg', 0))
                self.chem_tgt_na.set(profile.get('na', 0))
                self.chem_tgt_so4.set(profile.get('so4', 0))
                self.chem_tgt_cl.set(profile.get('cl', 0))
                
            except Exception as e:
                print(f"Error applying profile: {e}")
            finally:
                # Release flag
                self.loading_chem_profile = False

    def _on_chem_manual_edit(self, *args):
        # If we are programmatically loading a profile, ignore the changes
        if self.loading_chem_profile:
            return
            
        # Otherwise, the user typed something manually.
        # Clear the dropdown to indicate "Custom" state.
        if self.cb_water_profile.get() != "":
            self.cb_water_profile.set("")

    def _calculate_chemistry(self):
        try:
            vol = self.chem_vol.get()
            if vol <= 0: raise ValueError("Volume must be > 0")
            
            srm = self.chem_srm.get()
            tgt_ph = self.chem_target_ph.get()
            
            # Get grain weight dynamically from the other tab
            grain_wt = self.calc_grain_wt.get() 
            
            tgt_ca = self.chem_tgt_ca.get()
            tgt_mg = self.chem_tgt_mg.get()
            tgt_na = self.chem_tgt_na.get()
            tgt_so4 = self.chem_tgt_so4.get()
            tgt_cl = self.chem_tgt_cl.get()

            is_metric = UnitUtils.is_metric(self.settings)

            # --- USE SHARED MATH ---
            res = BrewMath.calculate_chemistry(
                vol, srm, tgt_ph, grain_wt, 
                tgt_ca, tgt_mg, tgt_na, tgt_so4, tgt_cl, is_metric
            )

            self.res_gypsum.set(f"{res['gypsum']:.1f} g")
            self.res_cacl2.set(f"{res['cacl2']:.1f} g")
            self.res_epsom.set(f"{res['epsom']:.1f} g")
            self.res_salt.set(f"{res['salt']:.1f} g")
            self.res_lime.set(f"{res['lime']:.1f} g")
            
            # UPDATED: Display both ml and grams
            self.res_acid.set(f"{res['acid']:.1f} ml / {res['acid_g']:.1f} g")
            
        except Exception as e:
            messagebox.showerror("Calc Error", str(e), parent=self)
            
    # ==========================
    # LOGIC: SAVE & CLOSE
    # ==========================
    def _refresh_step_list(self):
        self.step_listbox.delete(0, tk.END)
        self.list_map = [] 
        for i, step in enumerate(self.steps_working_copy):
            desc = f"{i+1}. {step.name} [{step.step_type.value}]"
            self.step_listbox.insert(tk.END, desc)
            self.list_map.append(i) 
            if step.additions:
                sorted_adds = sorted(step.additions, key=lambda x: x.time_point_min, reverse=True)
                for add in sorted_adds:
                    self.step_listbox.insert(tk.END, f"    ↳ {add.name}")
                    last_idx = self.step_listbox.size() - 1
                    self.step_listbox.itemconfigure(last_idx, fg='#666666')
                    self.list_map.append(i) 

    def _refresh_alerts_preview(self, step):
        self.lb_alerts_preview.delete(0, tk.END)
        if not step.additions:
            self.lb_alerts_preview.insert(0, "(None)")
            return
        sorted_adds = sorted(step.additions, key=lambda x: x.time_point_min, reverse=True)
        for add in sorted_adds:
            self.lb_alerts_preview.insert(tk.END, f"{add.time_point_min}m: {add.name}")

    def _save_current_edit(self):
        if self.current_step_index is None: return True
        if not (0 <= self.current_step_index < len(self.steps_working_copy)): return True
        
        step = self.steps_working_copy[self.current_step_index]
        try:
            step.name = self.var_name.get()
            step.step_type = StepType(self.var_type.get())
            step.timeout_behavior = TimeoutBehavior(self.var_timeout.get())
            step.note = self.txt_note.get("1.0", tk.END).strip()
            
            t_val = self.var_temp.get().strip()
            step.setpoint_f = UnitUtils.to_system_temp(float(t_val), self.settings) if t_val else None
            
            p_val = self.var_power.get().strip()
            step.power_watts = int(p_val) if p_val else None
            
            v_val = self.var_volume.get().strip()
            step.lauter_volume = UnitUtils.to_system_vol(float(v_val), self.settings) if v_val else None
            
            d_val = self.var_duration.get().strip()
            if d_val == "": step.duration_min = 0.0
            else:
                f_val = float(d_val)
                if f_val < 0: raise ValueError("Negative duration")
                step.duration_min = f_val
                
            return True
        except ValueError as e:
            messagebox.showerror("Validation Error", f"Invalid input: {e}", parent=self)
            return False

    def _on_step_select(self, event):
        if not self._save_current_edit():
            self._select_visual_row_by_step_index(self.current_step_index)
            return

        sel = self.step_listbox.curselection()
        if not sel: return
        visual_index = sel[0]
        if visual_index >= len(self.list_map): return

        real_index = self.list_map[visual_index]
        step = self.steps_working_copy[real_index]
        self.current_step_index = real_index 
        
        self.loading_step = True
        self.var_name.set(step.name)
        self.var_type.set(step.step_type.value) 
        self._on_type_change() 
        
        if step.setpoint_f is not None:
            user_t = UnitUtils.to_user_temp(step.setpoint_f, self.settings)
            self.var_temp.set(f"{user_t:.1f}")
        elif step.step_type != StepType.BOIL:
            self.var_temp.set("")
        
        self.var_duration.set(str(step.duration_min) if step.duration_min is not None else "")
        self.var_power.set(str(step.power_watts) if step.power_watts is not None else "1800")
        
        if step.lauter_volume is not None:
            user_v = UnitUtils.to_user_vol(step.lauter_volume, self.settings)
            self.var_volume.set(f"{user_v:.2f}")
        else:
            self.var_volume.set("")
            
        self.var_timeout.set(step.timeout_behavior.value)
        self.txt_note.delete('1.0', tk.END)
        self.txt_note.insert('1.0', step.note)
        self._refresh_alerts_preview(step)
        
        self.loading_step = False
        self._toggle_form_state(True)

    def _select_visual_row(self, visual_idx):
        self.step_listbox.selection_clear(0, tk.END)
        self.step_listbox.selection_set(visual_idx)
        self.step_listbox.event_generate("<<ListboxSelect>>")

    def _select_visual_row_by_step_index(self, step_idx):
        if step_idx is None: return
        try:
            visual_idx = self.list_map.index(step_idx)
            self._select_visual_row(visual_idx)
            self.step_listbox.see(visual_idx)
        except ValueError:
            pass

    def _open_additions(self):
        self._save_current_edit()
        if self.current_step_index is None: return
        step = self.steps_working_copy[self.current_step_index]
        self._toggle_interaction(False)
        dlg = AdditionsDialog(self, step.name, step.additions)
        self.wait_window(dlg)
        if not self.winfo_exists(): return
        self._toggle_interaction(True)
        self._refresh_step_list()
        self._select_visual_row_by_step_index(self.current_step_index)
        self._refresh_alerts_preview(step)

    def _toggle_interaction(self, enable):
        state = '!disabled' if enable else 'disabled'
        for child in self.tab_seq.winfo_children():
            self._recursive_state(child, state)

    def _recursive_state(self, widget, state):
        try: widget.state([state])
        except: pass
        for child in widget.winfo_children():
            self._recursive_state(child, state)

    def _on_type_change(self, *args):
        t_val = self.var_type.get()
        try: t = StepType(t_val)
        except: return

        if not self.loading_step: self.var_name.set(t_val)

        self._set_state(self.ent_temp, True)
        self._set_state(self.ent_dur, True)
        self._set_state(self.cb_pwr, True) 
        self._set_state(self.ent_vol, True) 
        self._set_state(self.btn_additions, True)
        self.lbl_boiling_indicator.pack_forget()

        if t == StepType.BOIL:
            self._set_state(self.ent_temp, False)
            sys_boil = self.settings.get_system_setting("boil_temp_f", 212.0)
            user_boil = UnitUtils.to_user_temp(sys_boil, self.settings)
            self.var_temp.set(f"{user_boil:.1f}")
            self.lbl_boiling_indicator.pack(side='left', padx=(5, 0))
        elif t == StepType.CHILL:
            self._set_state(self.cb_pwr, False)
            self.var_power.set("")

    def _set_state(self, widget, enabled):
        state = '!disabled' if enabled else 'disabled'
        widget.state([state])

    def _add_step(self):
        self._save_current_edit()
        new_step = BrewStep(name="New Step")
        self.steps_working_copy.append(new_step)
        self._refresh_step_list()
        new_idx = len(self.steps_working_copy) - 1
        self._select_visual_row_by_step_index(new_idx)

    def _delete_step(self):
        if self.current_step_index is None: return
        if not (0 <= self.current_step_index < len(self.steps_working_copy)): return
        
        self.steps_working_copy.pop(self.current_step_index)
        
        new_idx = None
        if self.steps_working_copy:
            new_idx = max(0, self.current_step_index - 1)
        
        self.current_step_index = None 
        self._refresh_step_list()
        self._toggle_form_state(False)
        if new_idx is not None:
             self._select_visual_row_by_step_index(new_idx)

    def _move_up(self):
        self._save_current_edit()
        if self.current_step_index is None or self.current_step_index == 0: return
        i = self.current_step_index
        self.steps_working_copy[i], self.steps_working_copy[i-1] = self.steps_working_copy[i-1], self.steps_working_copy[i]
        self._refresh_step_list()
        self._select_visual_row_by_step_index(i-1)

    def _move_down(self):
        self._save_current_edit()
        if self.current_step_index is None or self.current_step_index == len(self.steps_working_copy)-1: return
        i = self.current_step_index
        self.steps_working_copy[i], self.steps_working_copy[i+1] = self.steps_working_copy[i+1], self.steps_working_copy[i]
        self._refresh_step_list()
        self._select_visual_row_by_step_index(i+1)

    def _toggle_form_state(self, enabled):
        state = '!disabled' if enabled else 'disabled'
        for child in self.right_pane.winfo_children():
            try: child.state([state])
            except: pass 

    def _save_and_close(self):
        if not self._save_current_edit(): return
        
        try:
            self.profile.name = self.var_profile_name.get()
            self.profile.steps = self.steps_working_copy
            
            # SAVE WATER DATA
            self.profile.water_data = {
                "calc_method": self.calc_method_var.get(),
                "grain_weight": self.calc_grain_wt.get(),
                "grain_temp": self.calc_grain_temp.get(),
                "mash_temp": self.calc_mash_temp.get(),
                "target_vol": self.calc_target_vol.get(),
                "trub_loss": self.calc_trub.get(),
                "boil_time": self.calc_boil_time.get(),
                "boiloff_rate": self.calc_boiloff.get(),
                "abs_rate": self.calc_abs.get(),
                "mash_thickness": self.calc_thickness.get()
            }
            
            # SAVE CHEM DATA
            # Now includes source_profile_name for persistent dropdowns
            self.profile.chemistry_data = {
                "source_profile_name": self.cb_water_profile.get(),
                "water_vol": self.chem_vol.get(),
                "beer_srm": self.chem_srm.get(),
                "target_ph": self.chem_target_ph.get(),
                "target_ca": self.chem_tgt_ca.get(),
                "target_mg": self.chem_tgt_mg.get(),
                "target_na": self.chem_tgt_na.get(),
                "target_so4": self.chem_tgt_so4.get(),
                "target_cl": self.chem_tgt_cl.get()
            }
            
            if self.on_save:
                self.on_save(self.profile)
            
            try:
                if self.master: self.master.focus_set()
            except: pass
            finally: self.destroy()
            
        except Exception as e:
            messagebox.showerror("Save Error", f"An error occurred while saving:\n{e}", parent=self)
            print(f"[ProfileEditor] Save Error: {e}")
