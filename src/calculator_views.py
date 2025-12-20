import tkinter as tk
from tkinter import ttk, messagebox
from utils import UnitUtils, BrewMath, WaterProfileLoader

class WaterCalculatorView:
    def __init__(self, settings_manager):
        self.settings = settings_manager
        
        # Input Variables
        self.grain_wt = tk.DoubleVar(value=10.0)
        self.grain_temp = tk.DoubleVar(value=65.0)
        self.mash_temp = tk.DoubleVar(value=152.0)
        self.target_vol = tk.DoubleVar(value=5.5)
        self.boil_time = tk.DoubleVar(value=60.0)
        self.boiloff = tk.DoubleVar(value=0.5)
        self.trub = tk.DoubleVar(value=0.25)
        self.abs_rate = tk.DoubleVar(value=0.6)
        self.method_var = tk.StringVar(value="no_sparge")
        self.thickness = tk.DoubleVar(value=1.5)
        
        # Result Variables
        self.res_strike_vol = tk.StringVar(value="--")
        self.res_strike_temp = tk.StringVar(value="--")
        self.res_sparge_vol = tk.StringVar(value="--")
        self.res_mash_vol = tk.StringVar(value="--")
        self.res_pre_boil = tk.StringVar(value="--")
        self.res_post_boil = tk.StringVar(value="--")

    def build_ui(self, parent):
        """Builds the UI widgets inside the given parent frame."""
        container = ttk.Frame(parent)
        container.pack(side='top', fill='both', expand=True)

        is_metric = UnitUtils.is_metric(self.settings)
        
        u_wt = "kg" if is_metric else "lbs"
        u_temp = "°C" if is_metric else "°F"
        u_vol = "L" if is_metric else "Gal"
        u_boiloff = "L/hr" if is_metric else "Gal/hr"
        u_abs = "L/kg" if is_metric else "qt/lb"
        u_thick = "L/kg" if is_metric else "qt/lb"

        # --- LEFT PANE: INPUTS ---
        left_pane = ttk.LabelFrame(container, text="Inputs", padding=10)
        left_pane.place(relx=0.0, rely=0.0, relwidth=0.45, relheight=1.0)
        
        row = 0
        pad = 3
        
        # METHOD SELECTION
        method_frame = ttk.Frame(left_pane)
        method_frame.grid(row=row, column=0, columnspan=2, sticky='ew', pady=(0, 5))
        
        rb_no = ttk.Radiobutton(method_frame, text="No Sparge", variable=self.method_var, 
                                value="no_sparge", command=self._toggle_inputs)
        rb_no.pack(side='left', padx=(0, 10))
        
        rb_sp = ttk.Radiobutton(method_frame, text="Sparge", variable=self.method_var, 
                                value="sparge", command=self._toggle_inputs)
        rb_sp.pack(side='left')
        
        row += 1
        
        # Inputs
        inputs = [
            (f"Grain Bill ({u_wt}):", self.grain_wt),
            (f"Grain Temp ({u_temp}):", self.grain_temp),
            (f"Target Mash ({u_temp}):", self.mash_temp),
            ("SEP", None),
            (f"Fermenter Vol ({u_vol}):", self.target_vol),
            (f"Trub Loss ({u_vol}):", self.trub),
            ("Boil Time (min):", self.boil_time),
            (f"Boiloff Rate ({u_boiloff}):", self.boiloff),
            (f"Grain Abs ({u_abs}):", self.abs_rate),
            (f"Mash Thickness ({u_thick}):", self.thickness)
        ]

        for label, var in inputs:
            if label == "SEP":
                row += 1
                ttk.Separator(left_pane, orient='horizontal').grid(row=row, column=0, columnspan=2, sticky='ew', pady=5)
            else:
                ttk.Label(left_pane, text=label).grid(row=row, column=0, sticky='e', pady=pad)
                ent = ttk.Entry(left_pane, textvariable=var, width=8)
                ent.grid(row=row, column=1, sticky='w', padx=5)
                if "Mash Thickness" in label:
                    self.ent_thickness = ent
            row += 1

        # Calculate Button
        ttk.Button(left_pane, text="CALCULATE", command=self.calculate).grid(row=row, column=0, columnspan=2, sticky='ew', pady=(5, 2))

        # --- RIGHT PANE: RESULTS ---
        right_pane = ttk.LabelFrame(container, text="Water Requirements", padding=10)
        right_pane.place(relx=0.46, rely=0.0, relwidth=0.54, relheight=1.0)
        
        # Hero Results
        f_hero = ttk.Frame(right_pane)
        f_hero.pack(fill='x', pady=5)
        
        ttk.Label(f_hero, text=f"Strike Water:", font=('Arial', 11)).pack(anchor='center')
        ttk.Label(f_hero, textvariable=self.res_strike_vol, font=('Arial', 24, 'bold'), foreground='#0044CC').pack(anchor='center')
        
        ttk.Label(f_hero, text=f"Strike Temperature:", font=('Arial', 11)).pack(anchor='center', pady=(5, 0))
        ttk.Label(f_hero, textvariable=self.res_strike_temp, font=('Arial', 24, 'bold'), foreground='#e74c3c').pack(anchor='center')

        ttk.Label(f_hero, text=f"Sparge Water:", font=('Arial', 11)).pack(anchor='center', pady=(5, 0))
        ttk.Label(f_hero, textvariable=self.res_sparge_vol, font=('Arial', 20, 'bold'), foreground='#27ae60').pack(anchor='center')

        ttk.Separator(right_pane, orient='horizontal').pack(fill='x', pady=10)
        
        # Breakdown
        f_break = ttk.Frame(right_pane)
        f_break.pack(fill='x', padx=10)
        
        breakdown = [
            ("Total Mash Volume:", self.res_mash_vol),
            ("Pre-Boil Volume:", self.res_pre_boil),
            ("Post-Boil Volume:", self.res_post_boil)
        ]
        
        for r, (txt, var) in enumerate(breakdown):
            ttk.Label(f_break, text=txt, font=('Arial', 10, 'bold')).grid(row=r, column=0, sticky='w', pady=2)
            ttk.Label(f_break, textvariable=var).grid(row=r, column=1, sticky='e')
        
        f_break.columnconfigure(1, weight=1)
        self._toggle_inputs()

    def _toggle_inputs(self):
        if self.method_var.get() == "sparge":
            self.ent_thickness.config(state='normal')
        else:
            self.ent_thickness.config(state='disabled')

    def load_data(self, data):
        """Loads data from a dictionary (e.g., from settings or profile)."""
        if not data: return
        try:
            self.grain_wt.set(data.get("grain_weight", 10.0))
            self.grain_temp.set(data.get("grain_temp", 65.0))
            self.mash_temp.set(data.get("mash_temp", 152.0))
            self.target_vol.set(data.get("target_vol", 5.5))
            self.boil_time.set(data.get("boil_time", 60.0))
            self.boiloff.set(data.get("boiloff_rate", 0.5))
            self.trub.set(data.get("trub_loss", 0.25))
            self.abs_rate.set(data.get("abs_rate", 0.6))
            self.method_var.set(data.get("calc_method", "no_sparge"))
            self.thickness.set(data.get("mash_thickness", 1.5))
            self._toggle_inputs()
        except Exception as e:
            print(f"Error loading calc data: {e}")

    def get_data(self):
        """Returns current values as a dictionary."""
        return {
            "grain_weight": self.grain_wt.get(),
            "grain_temp": self.grain_temp.get(),
            "mash_temp": self.mash_temp.get(),
            "target_vol": self.target_vol.get(),
            "boil_time": self.boil_time.get(),
            "boiloff_rate": self.boiloff.get(),
            "trub_loss": self.trub.get(),
            "abs_rate": self.abs_rate.get(),
            "calc_method": self.method_var.get(),
            "mash_thickness": self.thickness.get()
        }

    def get_grain_weight(self):
        return self.grain_wt.get()

    def calculate(self):
        try:
            grain_wt = self.grain_wt.get()
            grain_temp = self.grain_temp.get()
            mash_temp = self.mash_temp.get()
            target_vol = self.target_vol.get()
            trub_loss = self.trub.get()
            boil_time = self.boil_time.get()
            boiloff_rate = self.boiloff.get()
            abs_rate = self.abs_rate.get()
            method = self.method_var.get()
            thickness = self.thickness.get()
            
            is_metric = UnitUtils.is_metric(self.settings)
            
            # --- USE SHARED MATH ---
            res = BrewMath.calculate_water(
                grain_wt, grain_temp, mash_temp, target_vol, trub_loss,
                boil_time, boiloff_rate, abs_rate, method, thickness, is_metric
            )

            u_vol = "L" if is_metric else "Gal"
            u_temp = "°C" if is_metric else "°F"
            
            self.res_strike_vol.set(f"{res['strike_vol']:.2f} {u_vol}")
            self.res_strike_temp.set(f"{res['strike_temp']:.1f} {u_temp}")
            self.res_sparge_vol.set(f"{res['sparge_vol']:.2f} {u_vol}")
            self.res_mash_vol.set(f"{res['total_mash_vol']:.2f} {u_vol}")
            self.res_pre_boil.set(f"{res['pre_boil_vol']:.2f} {u_vol}")
            self.res_post_boil.set(f"{res['post_boil_vol']:.2f} {u_vol}")

        except ZeroDivisionError:
             messagebox.showerror("Math Error", "Grain weight cannot be zero.")
        except Exception as e:
            messagebox.showerror("Error", f"Calculation failed: {e}")


class WaterChemistryView:
    def __init__(self, settings_manager):
        self.settings = settings_manager
        
        # Inputs
        self.vol = tk.DoubleVar(value=8.0)
        self.srm = tk.DoubleVar(value=5.0)
        self.target_ph = tk.DoubleVar(value=5.4)
        
        self.tgt_ca = tk.DoubleVar(value=50.0)
        self.tgt_mg = tk.DoubleVar(value=10.0)
        self.tgt_na = tk.DoubleVar(value=0.0)
        self.tgt_so4 = tk.DoubleVar(value=70.0)
        self.tgt_cl = tk.DoubleVar(value=50.0)
        
        # Results
        self.res_gypsum = tk.StringVar(value="-- g")
        self.res_cacl2 = tk.StringVar(value="-- g")
        self.res_epsom = tk.StringVar(value="-- g")
        self.res_salt = tk.StringVar(value="-- g")
        self.res_lime = tk.StringVar(value="-- g")
        self.res_acid = tk.StringVar(value="-- ml")
        
        self.grain_wt_getter = None

    def build_ui(self, parent, grain_wt_getter=None):
        self.grain_wt_getter = grain_wt_getter
        
        container = ttk.Frame(parent)
        container.pack(side='top', fill='both', expand=True)

        is_metric = UnitUtils.is_metric(self.settings)
        u_vol = "L" if is_metric else "Gal"

        # --- LEFT PANE: TARGETS ---
        left_pane = ttk.LabelFrame(container, text="Targets & Stats", padding=10)
        left_pane.place(relx=0.0, rely=0.0, relwidth=0.45, relheight=0.88)
        
        row = 0
        pad = 4
        
        # 1. Top Section
        ttk.Label(left_pane, text=f"Total Water ({u_vol}):").grid(row=row, column=0, sticky='e', pady=pad)
        ttk.Entry(left_pane, textvariable=self.vol, width=6).grid(row=row, column=1, sticky='w', padx=5)
        row += 1
        
        # Note
        ttk.Label(left_pane, text="(Uses Grain Wt from Calculator)", font=('Arial', 9, 'italic'), foreground='#7f8c8d').grid(row=row, column=0, columnspan=2, sticky='e', pady=(0, 5))
        row += 1

        ttk.Label(left_pane, text="Beer SRM (Color):").grid(row=row, column=0, sticky='e', pady=pad)
        ttk.Entry(left_pane, textvariable=self.srm, width=6).grid(row=row, column=1, sticky='w', padx=5)
        row += 1
        
        ttk.Label(left_pane, text="Target Mash pH:").grid(row=row, column=0, sticky='e', pady=pad)
        ttk.Entry(left_pane, textvariable=self.target_ph, width=6).grid(row=row, column=1, sticky='w', padx=5)
        row += 1

        # --- NEW: Water Profile Dropdown (Standardized) ---
        row += 1
        ttk.Label(left_pane, text="Load Profile:").grid(row=row, column=0, sticky='e', pady=(10, 5))
        
        self.water_profiles = WaterProfileLoader.load_profiles()
        self.profile_names = [p['name'] for p in self.water_profiles]
        self.cb_water_profile = ttk.Combobox(left_pane, values=self.profile_names, state='readonly', width=18)
        self.cb_water_profile.grid(row=row, column=1, sticky='w', pady=(10, 5), padx=5)
        self.cb_water_profile.bind("<<ComboboxSelected>>", self._on_water_profile_select)

        # FIX: Force open + 'break' to stop event propagation
        def _handle_click(event):
            try:
                event.widget.focus_set()
                event.widget.event_generate('<Down>')
                return 'break' # CRITICAL
            except: pass
            
        self.cb_water_profile.bind('<Button-1>', _handle_click)
        
        row += 1
        # -----------------------------------

        # 2. Targets Section
        targets = [
            ("Target Calcium (ppm):", self.tgt_ca),
            ("Target Magnesium (ppm):", self.tgt_mg),
            ("Target Sodium (ppm):", self.tgt_na),
            ("Target Sulfate (ppm):", self.tgt_so4),
            ("Target Chloride (ppm):", self.tgt_cl)
        ]
        
        for label, var in targets:
            ttk.Label(left_pane, text=label).grid(row=row, column=0, sticky='e', pady=pad)
            ttk.Entry(left_pane, textvariable=var, width=6).grid(row=row, column=1, sticky='w', padx=5)
            row += 1

        # Calculate Button
        ttk.Button(left_pane, text="CALCULATE ADDITIONS", command=self.calculate).grid(row=row+1, column=0, columnspan=2, sticky='ew', pady=(15, 5))

        # --- RIGHT PANE: ADDITIONS (Unchanged) ---
        right_pane = ttk.LabelFrame(container, text="Additions (To Total Water)", padding=10)
        right_pane.place(relx=0.46, rely=0.0, relwidth=0.54, relheight=0.88)
        
        f_res = ttk.Frame(right_pane)
        f_res.pack(fill='both', expand=True)
        
        r = 0
        res_list = [
            ("Gypsum (CaSO4):", self.res_gypsum),
            ("Calc. Chlor (CaCl2):", self.res_cacl2),
            ("Epsom Salt (MgSO4):", self.res_epsom),
            ("Table Salt (NaCl):", self.res_salt),
            ("Slaked Lime (CaOH2):", self.res_lime)
        ]
        
        for txt, var in res_list:
            ttk.Label(f_res, text=txt, font=('Arial', 10, 'bold')).grid(row=r, column=0, sticky='w', pady=5)
            ttk.Label(f_res, textvariable=var, foreground='#0044CC').grid(row=r, column=1, sticky='e', padx=10)
            r += 1
            
        r += 1
        ttk.Separator(f_res, orient='horizontal').grid(row=r, column=0, columnspan=2, sticky='ew', pady=10)
        r += 1
        ttk.Label(f_res, text="Lactic Acid (88%):", font=('Arial', 11, 'bold')).grid(row=r, column=0, sticky='w', pady=5)
        ttk.Label(f_res, textvariable=self.res_acid, font=('Arial', 14, 'bold'), foreground='#e74c3c').grid(row=r, column=1, sticky='e', padx=10)

    def _on_water_profile_select(self, event):
        selection = self.cb_water_profile.get()
        if not selection: return
        
        profile = next((p for p in self.water_profiles if p['name'] == selection), None)
        if profile:
            try:
                self.tgt_ca.set(profile.get('ca', 0))
                self.tgt_mg.set(profile.get('mg', 0))
                self.tgt_na.set(profile.get('na', 0))
                self.tgt_so4.set(profile.get('so4', 0))
                self.tgt_cl.set(profile.get('cl', 0))
            except Exception as e:
                print(f"Error applying profile: {e}")

    def load_data(self, data):
        if not data: return
        try:
            self.vol.set(data.get("water_vol", 8.0))
            self.srm.set(data.get("beer_srm", 5.0))
            self.target_ph.set(data.get("target_ph", 5.4))
            self.tgt_ca.set(data.get("target_ca", 50.0))
            self.tgt_mg.set(data.get("target_mg", 10.0))
            self.tgt_na.set(data.get("target_na", 0.0))
            self.tgt_so4.set(data.get("target_so4", 70.0))
            self.tgt_cl.set(data.get("target_cl", 50.0))
        except Exception as e:
            print(f"Error loading chemistry data: {e}")

    def get_data(self):
        return {
            "water_vol": self.vol.get(),
            "beer_srm": self.srm.get(),
            "target_ph": self.target_ph.get(),
            "target_ca": self.tgt_ca.get(),
            "target_mg": self.tgt_mg.get(),
            "target_na": self.tgt_na.get(),
            "target_so4": self.tgt_so4.get(),
            "target_cl": self.tgt_cl.get()
        }

    def calculate(self):
        try:
            vol = self.vol.get()
            srm = self.srm.get()
            tgt_ph = self.target_ph.get()
            
            tgt_ca = self.tgt_ca.get()
            tgt_mg = self.tgt_mg.get()
            tgt_na = self.tgt_na.get()
            tgt_so4 = self.tgt_so4.get()
            tgt_cl = self.tgt_cl.get()
            
            # Get grain weight dynamically
            grain_wt = 10.0
            if self.grain_wt_getter:
                grain_wt = self.grain_wt_getter()
            
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
            self.res_acid.set(f"{res['acid']:.1f} ml")

        except Exception as e:
            messagebox.showerror("Error", f"Calculation failed: {e}")
