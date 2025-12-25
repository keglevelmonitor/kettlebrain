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

# ==============================================================================
# 1. EDIT STEP POPUP (Replaces the old AdditionsDialog)
# ==============================================================================
class EditStepPopup(tk.Toplevel):
    def __init__(self, parent, step_obj, on_save):
        super().__init__(parent)
        self.step = step_obj
        self.on_save = on_save
        
        self.title(f"Edit Step: {step_obj.name}")
        self.geometry("780x460") 
        self.configure(bg='#2c3e50')
        
        self.transient(parent)
        self.resizable(False, False)
        
        # Center Window
        try:
            sw = self.winfo_screenwidth()
            sh = self.winfo_screenheight()
            x = (sw - 780) // 2
            y = (sh - 460) // 2
            self.geometry(f"+{x}+{y}")
        except: pass

        # Data Variables
        self.var_name = tk.StringVar(value=step_obj.name)
        self.var_temp = tk.DoubleVar(value=step_obj.setpoint_f if step_obj.setpoint_f else 0.0)
        self.var_dur = tk.DoubleVar(value=step_obj.duration_min if step_obj.duration_min else 0.0)
        
        # Working copy of additions (Deep Copy so we can Cancel)
        self.temp_additions = [copy.deepcopy(a) for a in step_obj.additions]

        self._build_ui()
        
        self.deiconify()
        self.lift()
        self.focus_force()
        self.grab_set()

    def _build_ui(self):
        # Styles
        BG = '#2c3e50'
        FG = 'white'
        SLIDER_BG = '#34495e'
        LBL_FONT = ('Arial', 12, 'bold')
        
        # --- TOP FORM (Name, Temp, Dur) ---
        f_form = tk.Frame(self, bg=BG)
        f_form.pack(side='top', fill='x', padx=20, pady=10)
        
        # Row 1: Name
        r1 = tk.Frame(f_form, bg=BG)
        r1.pack(fill='x', pady=5)
        tk.Label(r1, text="Step Name:", font=LBL_FONT, bg=BG, fg='#bdc3c7', width=12, anchor='e').pack(side='left')
        tk.Entry(r1, textvariable=self.var_name, font=('Arial', 14), width=30).pack(side='left', padx=10)

        # Row 2: Temp
        r2 = tk.Frame(f_form, bg=BG)
        r2.pack(fill='x', pady=5)
        tk.Label(r2, text="Target Temp:", font=LBL_FONT, bg=BG, fg='#bdc3c7', width=12, anchor='e').pack(side='left')
        
        s_temp = tk.Scale(r2, from_=0, to=212, orient='horizontal', variable=self.var_temp, 
                          length=350, width=30, bg=BG, fg=FG, troughcolor=SLIDER_BG, highlightthickness=0)
        s_temp.pack(side='left', padx=10)
        
        tk.Entry(r2, textvariable=self.var_temp, font=('Arial', 14, 'bold'), width=5).pack(side='left')
        tk.Label(r2, text="°F", font=LBL_FONT, bg=BG, fg=FG).pack(side='left')

        # Row 3: Duration
        r3 = tk.Frame(f_form, bg=BG)
        r3.pack(fill='x', pady=5)
        tk.Label(r3, text="Duration:", font=LBL_FONT, bg=BG, fg='#bdc3c7', width=12, anchor='e').pack(side='left')
        
        s_dur = tk.Scale(r3, from_=0, to=120, orient='horizontal', variable=self.var_dur, 
                         length=350, width=30, bg=BG, fg=FG, troughcolor=SLIDER_BG, highlightthickness=0)
        s_dur.pack(side='left', padx=10)
        
        tk.Entry(r3, textvariable=self.var_dur, font=('Arial', 14, 'bold'), width=5).pack(side='left')
        tk.Label(r3, text="min", font=LBL_FONT, bg=BG, fg=FG).pack(side='left')

        # --- ADDITIONS LIST ---
        tk.Label(self, text="Alerts & Additions", font=('Arial', 11, 'bold'), bg=BG, fg='#ecf0f1').pack(pady=(10, 0))
        
        f_list = tk.Frame(self, bg='white')
        f_list.pack(side='top', fill='both', expand=True, padx=20, pady=5)
        
        sb = tk.Scrollbar(f_list)
        sb.pack(side='right', fill='y')
        
        self.lb_additions = tk.Listbox(f_list, font=('Arial', 12), height=4, yscrollcommand=sb.set)
        self.lb_additions.pack(side='left', fill='both', expand=True)
        sb.config(command=self.lb_additions.yview)
        
        # List Buttons
        f_list_btns = tk.Frame(self, bg=BG)
        f_list_btns.pack(side='top', fill='x', padx=20, pady=5)
        
        tk.Button(f_list_btns, text="+ ADD ALERT", font=('Arial', 10, 'bold'), 
                  bg='#2ecc71', fg='white', width=15, command=self._add_addition).pack(side='left')
        
        tk.Button(f_list_btns, text="- REMOVE SELECTED", font=('Arial', 10, 'bold'), 
                  bg='#e74c3c', fg='white', width=20, command=self._remove_addition).pack(side='right')

        # --- BOTTOM ACTIONS ---
        f_bot = tk.Frame(self, bg=BG)
        f_bot.pack(side='bottom', fill='x', pady=15, padx=20)
        
        tk.Button(f_bot, text="CANCEL", font=('Arial', 12, 'bold'), 
                  bg='#95a5a6', fg='white', height=2, width=12, 
                  command=self.destroy).pack(side='left')
        
        tk.Button(f_bot, text="SAVE STEP", font=('Arial', 12, 'bold'), 
                  bg='#3498db', fg='white', height=2, width=15, 
                  command=self._do_save).pack(side='right')

        self._refresh_list()

    def _refresh_list(self):
        self.lb_additions.delete(0, 'end')
        self.temp_additions.sort(key=lambda x: x.time_point_min, reverse=True)
        for add in self.temp_additions:
            self.lb_additions.insert('end', f"{add.name} @ {add.time_point_min} min")

    def _add_addition(self):
        from tkinter import simpledialog
        name = simpledialog.askstring("New Alert", "Alert Name (e.g. 'Add Hops'):", parent=self)
        if not name: return
        t_val = simpledialog.askfloat("New Alert", "Time Remaining (Minutes):", parent=self, minvalue=0, maxvalue=240)
        if t_val is None: return
        
        self.temp_additions.append(BrewAddition(name=name, time_point_min=t_val))
        self._refresh_list()

    def _remove_addition(self):
        sel = self.lb_additions.curselection()
        if not sel: return
        idx = sel[0]
        del self.temp_additions[idx]
        self._refresh_list()

    def _do_save(self):
        try:
            self.step.name = self.var_name.get()
            self.step.setpoint_f = self.var_temp.get()
            self.step.duration_min = self.var_dur.get()
            self.step.additions = self.temp_additions
            if self.on_save: self.on_save()
            self.destroy()
        except Exception as e:
            messagebox.showerror("Error", f"Invalid Values: {e}", parent=self)


# ==============================================================================
# 2. MAIN PROFILE EDITOR (The Tabbed Window)
# ==============================================================================
class ProfileEditor(tk.Toplevel):
    def __init__(self, parent, profile: BrewProfile, settings_manager, sequencer, on_save_callback):
        super().__init__(parent)
        self.withdraw()
        
        self.title(f"Editing Profile: {profile.name}")
        
        # Fixed Size for 800x480
        target_w = 800
        target_h = 420
        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()
        x = (screen_w // 2) - (target_w // 2)
        y = (screen_h // 2) - (target_h // 2)
        y = max(0, y)
        self.geometry(f"{target_w}x{target_h}+{x}+{y}")

        self.transient(parent)
        
        self.profile = profile
        self.settings = settings_manager
        self.sequencer = sequencer
        self.on_save = on_save_callback
        
        self.steps_working_copy = copy.deepcopy(profile.steps) 
        self.current_step_index = None 
        self.list_map = [] 

        self._init_water_vars()
        self._init_chem_vars()
        self._configure_styles()
        self._create_layout()
        
        self._refresh_step_list()
        
        self.protocol("WM_DELETE_WINDOW", self.close)
        
        self.deiconify()
        self.lift()
        self.focus_force()

    def close(self):
        try:
            if self.master: self.master.focus_set()
        except: pass
        self.destroy()

    def _configure_styles(self):
        s = ttk.Style()
        s.configure('Editor.TFrame', background='#f0f0f0')
        s.configure('StepList.TFrame', background='white', relief='sunken')
        s.configure('Header.TLabel', font=('Arial', 12, 'bold'))
        s.configure('SubHeader.TLabel', font=('Arial', 10, 'bold'), foreground='#555555')

    def _init_water_vars(self):
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
        self.res_strike_vol = tk.StringVar(value="--")
        self.res_strike_temp = tk.StringVar(value="--")
        self.res_sparge_vol = tk.StringVar(value="--")
        self.res_mash_vol = tk.StringVar(value="--")
        self.res_pre_boil = tk.StringVar(value="--")
        self.res_post_boil = tk.StringVar(value="--")

    def _init_chem_vars(self):
        cd = self.profile.chemistry_data
        self.var_chem_profile_name = tk.StringVar(value=cd.get("source_profile_name", ""))
        self.loading_chem_profile = False
        self.chem_vol = tk.DoubleVar(value=cd.get("water_vol", 8.0))
        self.chem_srm = tk.DoubleVar(value=cd.get("beer_srm", 5.0))
        self.chem_target_ph = tk.DoubleVar(value=cd.get("target_ph", 5.4))
        self.chem_tgt_ca = tk.DoubleVar(value=cd.get("target_ca", 50.0))
        self.chem_tgt_mg = tk.DoubleVar(value=cd.get("target_mg", 10.0))
        self.chem_tgt_na = tk.DoubleVar(value=cd.get("target_na", 0.0))
        self.chem_tgt_so4 = tk.DoubleVar(value=cd.get("target_so4", 70.0))
        self.chem_tgt_cl = tk.DoubleVar(value=cd.get("target_cl", 50.0))
        self.res_gypsum = tk.StringVar(value="--")
        self.res_cacl2 = tk.StringVar(value="--")
        self.res_epsom = tk.StringVar(value="--")
        self.res_salt = tk.StringVar(value="--")
        self.res_lime = tk.StringVar(value="--")
        self.res_acid = tk.StringVar(value="--")

    def _create_layout(self):
        # 1. PROFILE NAME
        top_frame = ttk.Frame(self)
        top_frame.pack(fill='x', padx=10, pady=5)
        ttk.Label(top_frame, text="Profile Name:", style='Header.TLabel').pack(side='left')
        self.var_profile_name = tk.StringVar(value=self.profile.name)
        ttk.Entry(top_frame, textvariable=self.var_profile_name, font=('Arial', 11)).pack(side='left', fill='x', expand=True, padx=10)

        # 2. GLOBAL BUTTONS
        bot_frame = ttk.Frame(self)
        bot_frame.pack(side='bottom', fill='x', padx=10, pady=5)
        ttk.Button(bot_frame, text="Cancel", command=self.close).pack(side='right', padx=5)
        ttk.Button(bot_frame, text="Save Profile", command=self._save_and_close).pack(side='right', padx=5)

        # 3. NOTEBOOK
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(side='top', fill='both', expand=True, padx=5, pady=5)
        
        self.tab_seq = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_seq, text="Brew Sequence")
        self._build_sequence_tab()
        
        self.tab_calc = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_calc, text="Profile Water")
        self._build_water_tab()
        
        self.tab_chem = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_chem, text="Profile Chemistry")
        self._build_chem_tab()

    # --- TAB 1: SEQUENCE ---
    def _build_sequence_tab(self):
        content_frame = ttk.Frame(self.tab_seq, padding=5)
        content_frame.pack(fill='both', expand=True)

        ttk.Label(content_frame, text="Step Sequence", style='SubHeader.TLabel').pack(anchor='w', pady=(0, 2))
        
        list_container = ttk.Frame(content_frame)
        list_container.pack(fill='both', expand=True)
        
        self.step_listbox = tk.Listbox(list_container, font=('Arial', 12), selectmode=tk.SINGLE, activator=None)
        self.step_listbox.pack(side='left', fill='both', expand=True)
        self.step_listbox.bind('<Double-Button-1>', self._on_step_double_click)
        self.step_listbox.bind('<<ListboxSelect>>', self._on_list_select)
        
        scroll = ttk.Scrollbar(list_container, orient='vertical', command=self.step_listbox.yview)
        scroll.pack(side='right', fill='y')
        self.step_listbox.config(yscrollcommand=scroll.set)
        
        btn_row = ttk.Frame(content_frame, padding=5)
        btn_row.pack(fill='x', pady=5)
        
        ttk.Button(btn_row, text="Add Step", command=self._add_step).pack(side='left', expand=True, fill='x', padx=2)
        self.btn_edit = ttk.Button(btn_row, text="Edit Step", command=self._edit_selected_step, state='disabled')
        self.btn_edit.pack(side='left', expand=True, fill='x', padx=2)
        
        ttk.Button(btn_row, text="Delete", command=self._delete_step).pack(side='left', expand=True, fill='x', padx=2)
        ttk.Button(btn_row, text="▲", width=4, command=self._move_up).pack(side='left', padx=1)
        ttk.Button(btn_row, text="▼", width=4, command=self._move_down).pack(side='left', padx=1)

    def _refresh_step_list(self):
        self.step_listbox.delete(0, tk.END)
        self.list_map = [] 
        for i, step in enumerate(self.steps_working_copy):
            t_str = f"{step.setpoint_f}F" if step.setpoint_f else "--"
            if step.step_type == StepType.BOIL: t_str = "BOIL"
            d_str = f"{step.duration_min}m"
            desc = f"{i+1}. {step.name} ({t_str}, {d_str})"
            
            self.step_listbox.insert(tk.END, desc)
            self.list_map.append(i) 
            
            if step.additions:
                sorted_adds = sorted(step.additions, key=lambda x: x.time_point_min, reverse=True)
                for add in sorted_adds:
                    self.step_listbox.insert(tk.END, f"    ↳ Alert: {add.name} @ {add.time_point_min}m")
                    last_idx = self.step_listbox.size() - 1
                    self.step_listbox.itemconfigure(last_idx, fg='#666666')
                    self.list_map.append(i) 

    def _on_list_select(self, event):
        sel = self.step_listbox.curselection()
        if sel: self.btn_edit.config(state='normal')
        else: self.btn_edit.config(state='disabled')

    def _on_step_double_click(self, event):
        self._edit_selected_step()

    def _get_selected_real_index(self):
        sel = self.step_listbox.curselection()
        if not sel: return None
        visual_index = sel[0]
        if visual_index >= len(self.list_map): return None
        return self.list_map[visual_index]

    def _add_step(self):
        new_step = BrewStep(name="New Step")
        self.steps_working_copy.append(new_step)
        self._refresh_step_list()
        self._open_step_editor(new_step)

    def _edit_selected_step(self):
        idx = self._get_selected_real_index()
        if idx is None: return
        step = self.steps_working_copy[idx]
        self._open_step_editor(step)

    def _open_step_editor(self, step):
        # Calls the new EditStepPopup
        def on_save_callback():
            self._refresh_step_list()
        dlg = EditStepPopup(self, step, on_save_callback)
        self.wait_window(dlg)

    def _delete_step(self):
        idx = self._get_selected_real_index()
        if idx is None: return
        self.steps_working_copy.pop(idx)
        self._refresh_step_list()

    def _move_up(self):
        idx = self._get_selected_real_index()
        if idx is None or idx == 0: return
        self.steps_working_copy[idx], self.steps_working_copy[idx-1] = self.steps_working_copy[idx-1], self.steps_working_copy[idx]
        self._refresh_step_list()

    def _move_down(self):
        idx = self._get_selected_real_index()
        if idx is None or idx == len(self.steps_working_copy)-1: return
        self.steps_working_copy[idx], self.steps_working_copy[idx+1] = self.steps_working_copy[idx+1], self.steps_working_copy[idx]
        self._refresh_step_list()

    # --- TAB 2: WATER ---
    def _build_water_tab(self):
        is_metric = UnitUtils.is_metric(self.settings)
        u_wt = "kg" if is_metric else "lbs"
        u_temp = "°C" if is_metric else "°F"
        u_vol = "L" if is_metric else "Gal"
        u_boiloff = "L/hr" if is_metric else "Gal/hr"
        u_abs = "L/kg" if is_metric else "qt/lb"
        u_thick = "L/kg" if is_metric else "qt/lb"

        f_top = ttk.Frame(self.tab_calc, padding=5)
        f_top.pack(fill='x')
        ttk.Label(f_top, text="Method:", font=('Arial', 10, 'bold')).pack(side='left', padx=(0, 10))
        ttk.Radiobutton(f_top, text="No Sparge", variable=self.calc_method_var, value="no_sparge", command=self._toggle_calc_inputs).pack(side='left')
        ttk.Radiobutton(f_top, text="Sparge", variable=self.calc_method_var, value="sparge", command=self._toggle_calc_inputs).pack(side='left', padx=10)

        paned = ttk.PanedWindow(self.tab_calc, orient='horizontal')
        paned.pack(fill='both', expand=True, padx=10, pady=(0, 10))
        
        f_in = ttk.LabelFrame(paned, text="Recipe Inputs", padding=5)
        paned.add(f_in, weight=1)
        r = 0; pad = 2 
        ttk.Label(f_in, text=f"Grain ({u_wt}):").grid(row=r, column=0, sticky='e', pady=pad);
        ttk.Entry(f_in, textvariable=self.calc_grain_wt, width=6).grid(row=r, column=1, sticky='w', padx=5); r+=1
        ttk.Label(f_in, text=f"Grain T ({u_temp}):").grid(row=r, column=0, sticky='e', pady=pad);
        ttk.Entry(f_in, textvariable=self.calc_grain_temp, width=6).grid(row=r, column=1, sticky='w', padx=5); r+=1
        ttk.Label(f_in, text=f"Mash T ({u_temp}):").grid(row=r, column=0, sticky='e', pady=pad);
        ttk.Entry(f_in, textvariable=self.calc_mash_temp, width=6).grid(row=r, column=1, sticky='w', padx=5); r+=1
        ttk.Separator(f_in, orient='horizontal').grid(row=r, column=0, columnspan=2, sticky='ew', pady=2); r+=1
        ttk.Label(f_in, text=f"Ferm Vol ({u_vol}):").grid(row=r, column=0, sticky='e', pady=pad);
        ttk.Entry(f_in, textvariable=self.calc_target_vol, width=6).grid(row=r, column=1, sticky='w', padx=5); r+=1
        ttk.Label(f_in, text=f"Trub ({u_vol}):").grid(row=r, column=0, sticky='e', pady=pad);
        ttk.Entry(f_in, textvariable=self.calc_trub, width=6).grid(row=r, column=1, sticky='w', padx=5); r+=1
        ttk.Label(f_in, text=f"Boil Min:").grid(row=r, column=0, sticky='e', pady=pad);
        ttk.Entry(f_in, textvariable=self.calc_boil_time, width=6).grid(row=r, column=1, sticky='w', padx=5); r+=1
        ttk.Label(f_in, text=f"Boiloff ({u_boiloff}):").grid(row=r, column=0, sticky='e', pady=pad);
        ttk.Entry(f_in, textvariable=self.calc_boiloff, width=6).grid(row=r, column=1, sticky='w', padx=5); r+=1
        ttk.Label(f_in, text=f"Abs ({u_abs}):").grid(row=r, column=0, sticky='e', pady=pad);
        ttk.Entry(f_in, textvariable=self.calc_abs, width=6).grid(row=r, column=1, sticky='w', padx=5); r+=1
        ttk.Label(f_in, text=f"Thick ({u_thick}):").grid(row=r, column=0, sticky='e', pady=pad)
        self.ent_thickness = ttk.Entry(f_in, textvariable=self.calc_thickness, width=6)
        self.ent_thickness.grid(row=r, column=1, sticky='w', padx=5); r+=1
        
        f_out = ttk.LabelFrame(paned, text="Requirements", padding=10)
        paned.add(f_out, weight=1)
        f_hero = ttk.Frame(f_out)
        f_hero.pack(fill='x', pady=5)
        f_h1 = ttk.Frame(f_hero)
        f_h1.pack(side='left', expand=True, fill='x')
        ttk.Label(f_h1, text="Strike Water:", font=('Arial', 10)).pack(anchor='center')
        ttk.Label(f_h1, textvariable=self.res_strike_vol, font=('Arial', 20, 'bold'), foreground='#0044CC').pack(anchor='center')
        f_h2 = ttk.Frame(f_hero)
        f_h2.pack(side='left', expand=True, fill='x')
        ttk.Label(f_h2, text="Strike Temp:", font=('Arial', 10)).pack(anchor='center')
        ttk.Label(f_h2, textvariable=self.res_strike_temp, font=('Arial', 20, 'bold'), foreground='#e74c3c').pack(anchor='center')
        ttk.Separator(f_out, orient='horizontal').pack(fill='x', pady=10)
        f_det = ttk.Frame(f_out)
        f_det.pack(fill='x')
        ttk.Label(f_det, text="Sparge Water:").grid(row=0, column=0, sticky='e')
        ttk.Label(f_det, textvariable=self.res_sparge_vol, font=('Arial', 10, 'bold')).grid(row=0, column=1, sticky='w', padx=5)
        ttk.Label(f_det, text="Total Mash Vol:").grid(row=1, column=0, sticky='e')
        ttk.Label(f_det, textvariable=self.res_mash_vol).grid(row=1, column=1, sticky='w', padx=5)
        ttk.Label(f_det, text="Pre-Boil Vol:").grid(row=2, column=0, sticky='e')
        ttk.Label(f_det, textvariable=self.res_pre_boil).grid(row=2, column=1, sticky='w', padx=5)
        ttk.Button(f_out, text="CALCULATE", command=self._calculate_water_req).pack(side='bottom', fill='x', pady=10)
        self._toggle_calc_inputs()

    def _toggle_calc_inputs(self):
        if self.calc_method_var.get() == "sparge": self.ent_thickness.config(state='normal')
        else: self.ent_thickness.config(state='disabled')

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
            self.chem_vol.set(round(res['total_water'], 2))
        except Exception as e: messagebox.showerror("Calc Error", str(e), parent=self)

    # --- TAB 3: CHEMISTRY ---
    def _build_chem_tab(self):
        u_vol = "L" if UnitUtils.is_metric(self.settings) else "Gal"
        f = ttk.Frame(self.tab_chem, padding=10)
        f.pack(fill='both', expand=True)
        
        lf = ttk.LabelFrame(f, text="Targets & Stats", padding=10)
        lf.place(relx=0, rely=0, relwidth=0.45, relheight=1.0)
        r=0; pad=4 
        ttk.Label(lf, text=f"Total Water ({u_vol}):").grid(row=r, column=0, sticky='e', pady=pad);
        ttk.Entry(lf, textvariable=self.chem_vol, width=6).grid(row=r, column=1, sticky='w'); r+=1
        ttk.Label(lf, text="Beer SRM:").grid(row=r, column=0, sticky='e', pady=pad);
        ttk.Entry(lf, textvariable=self.chem_srm, width=6).grid(row=r, column=1, sticky='w'); r+=1
        ttk.Label(lf, text="Target pH:").grid(row=r, column=0, sticky='e', pady=pad);
        ttk.Entry(lf, textvariable=self.chem_target_ph, width=6).grid(row=r, column=1, sticky='w'); r+=1
        
        r+=1
        ttk.Label(lf, text="Load Profile:").grid(row=r, column=0, sticky='e', pady=(10, 2))
        self.water_profiles = WaterProfileLoader.load_profiles()
        self.profile_names = [p['name'] for p in self.water_profiles]
        self.cb_water_profile = ttk.Combobox(lf, textvariable=self.var_chem_profile_name, values=self.profile_names, state='readonly', width=18)
        self.cb_water_profile.grid(row=r, column=1, sticky='w', pady=(10, 2), padx=0)
        self.cb_water_profile.bind("<<ComboboxSelected>>", self._on_water_profile_select)
        self.cb_water_profile.bind('<Button-1>', lambda e: self.after(1, self.cb_water_profile.focus_set))
        r+=1
        
        targets = [
            ("Target Ca (ppm):", self.chem_tgt_ca), ("Target Mg (ppm):", self.chem_tgt_mg),
            ("Target Na (ppm):", self.chem_tgt_na), ("Target SO4 (ppm):", self.chem_tgt_so4),
            ("Target Cl (ppm):", self.chem_tgt_cl)
        ]
        for label, var in targets:
            ttk.Label(lf, text=label).grid(row=r, column=0, sticky='e', pady=pad)
            ttk.Entry(lf, textvariable=var, width=6).grid(row=r, column=1, sticky='w')
            var.trace_add("write", self._on_chem_manual_edit)
            r+=1
        
        rf = ttk.LabelFrame(f, text="Additions (to Total Water)", padding=10)
        rf.place(relx=0.46, rely=0, relwidth=0.54, relheight=1.0)
        r=0; res_pad = 6
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
        ttk.Separator(rf, orient='horizontal').grid(row=r, column=0, columnspan=2, sticky='ew', pady=10); r+=1 
        ttk.Label(rf, text="Lactic Acid (88%):", font=('Arial', 10, 'bold')).grid(row=r, column=0, sticky='e', pady=res_pad);
        ttk.Label(rf, textvariable=self.res_acid, font=('Arial', 12, 'bold'), foreground='#e74c3c').grid(row=r, column=1, sticky='w', padx=10); r+=1
        ttk.Frame(rf, height=10).grid(row=r, column=0); r+=1 
        ttk.Button(rf, text="CALCULATE ADDITIONS", command=self._calculate_chemistry).grid(row=r, column=0, columnspan=2, sticky='ew', pady=5)

    def _on_water_profile_select(self, event):
        selection = self.cb_water_profile.get()
        if not selection: return
        profile = next((p for p in self.water_profiles if p['name'] == selection), None)
        if profile:
            try:
                self.loading_chem_profile = True
                self.chem_tgt_ca.set(profile.get('ca', 0))
                self.chem_tgt_mg.set(profile.get('mg', 0))
                self.chem_tgt_na.set(profile.get('na', 0))
                self.chem_tgt_so4.set(profile.get('so4', 0))
                self.chem_tgt_cl.set(profile.get('cl', 0))
            except Exception as e: print(f"Error applying profile: {e}")
            finally: self.loading_chem_profile = False

    def _on_chem_manual_edit(self, *args):
        if self.loading_chem_profile: return
        if self.cb_water_profile.get() != "": self.cb_water_profile.set("")

    def _calculate_chemistry(self):
        try:
            vol = self.chem_vol.get()
            if vol <= 0: raise ValueError("Volume must be > 0")
            srm = self.chem_srm.get()
            tgt_ph = self.chem_target_ph.get()
            grain_wt = self.calc_grain_wt.get() 
            tgt_ca = self.chem_tgt_ca.get()
            tgt_mg = self.chem_tgt_mg.get()
            tgt_na = self.chem_tgt_na.get()
            tgt_so4 = self.chem_tgt_so4.get()
            tgt_cl = self.chem_tgt_cl.get()
            is_metric = UnitUtils.is_metric(self.settings)
            res = BrewMath.calculate_chemistry(
                vol, srm, tgt_ph, grain_wt, 
                tgt_ca, tgt_mg, tgt_na, tgt_so4, tgt_cl, is_metric
            )
            self.res_gypsum.set(f"{res['gypsum']:.1f} g")
            self.res_cacl2.set(f"{res['cacl2']:.1f} g")
            self.res_epsom.set(f"{res['epsom']:.1f} g")
            self.res_salt.set(f"{res['salt']:.1f} g")
            self.res_lime.set(f"{res['lime']:.1f} g")
            self.res_acid.set(f"{res['acid']:.1f} ml / {res['acid_g']:.1f} g")
        except Exception as e: messagebox.showerror("Calc Error", str(e), parent=self)

    def _save_and_close(self):
        try:
            self.profile.name = self.var_profile_name.get()
            self.profile.steps = self.steps_working_copy
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
            if self.on_save: self.on_save(self.profile)
            try:
                if self.master: self.master.focus_set()
            except: pass
            finally: self.destroy()
        except Exception as e:
            messagebox.showerror("Save Error", f"An error occurred while saving:\n{e}", parent=self)
            print(f"[ProfileEditor] Save Error: {e}")
