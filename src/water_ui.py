import os
import json
from kivy.uix.screenmanager import Screen
from kivy.properties import NumericProperty, StringProperty, BooleanProperty, ListProperty
from kivy.lang import Builder
from brew_math import BrewMath

# Load KV file specifically for this screen
current_dir = os.path.dirname(os.path.abspath(__file__))
Builder.load_file(os.path.join(current_dir, 'water.kv'))

class WaterCalculatorScreen(Screen):
    # --- GLOBAL SETTINGS ---
    is_metric = BooleanProperty(False)
    mash_method = StringProperty("No Sparge (BIAB)")
    
    # --- INPUTS: WATER ---
    grain_wt = NumericProperty(10.0)
    boil_time = NumericProperty(60.0)
    grain_temp = NumericProperty(68.0)  # <--- CHANGED: Default 68 F
    mash_temp = NumericProperty(152.0)
    boiloff = NumericProperty(1.0)
    abs_rate = NumericProperty(0.5)
    trub_vol = NumericProperty(0.25)
    ferm_vol = NumericProperty(5.5)
    thickness = NumericProperty(1.5)
    
    # --- INPUTS: CHEMISTRY ---
    srm = NumericProperty(5.0)
    target_ph = NumericProperty(5.4)
    
    # Target Profile inputs
    tgt_ca = NumericProperty(50)
    tgt_mg = NumericProperty(10)
    tgt_na = NumericProperty(15)    # <--- CHANGED: Default 15
    tgt_so4 = NumericProperty(75)   # <--- CHANGED: Default 75
    tgt_cl = NumericProperty(63)    # <--- CHANGED: Default 63
    
    profile_names = ListProperty(["Default"])
    loaded_profiles = []

    # --- RESULTS ---
    strike_vol = StringProperty("--")
    sparge_vol = StringProperty("--")
    strike_temp = StringProperty("--")
    pre_boil_vol = StringProperty("--")
    total_mash_vol = StringProperty("--")
    total_water = NumericProperty(0.0) 
    
    res_gypsum = StringProperty("0.0 g")
    res_cacl2 = StringProperty("0.0 g")
    res_epsom = StringProperty("0.0 g")
    res_salt = StringProperty("0.0 g")
    res_lime = StringProperty("0.0 g")
    res_acid = StringProperty("0.0 ml")
    res_acid_g = StringProperty("0.0 g")

    def on_enter(self):
        self._load_profiles()

    def update_units(self, value):
        self.is_metric = (value == "Metric")

    def _load_profiles(self):
        try:
            path = os.path.join(os.path.dirname(__file__), 'assets', 'target_water_profiles.json')
            if os.path.exists(path):
                with open(path, 'r') as f:
                    self.loaded_profiles = json.load(f)
                    self.profile_names = [p['name'] for p in self.loaded_profiles]
            else:
                self.profile_names = ["Default"]
        except:
            pass

    def load_target_profile(self, name):
        for p in self.loaded_profiles:
            if p['name'] == name:
                self.tgt_ca = int(p.get('ca', 0))
                self.tgt_mg = int(p.get('mg', 0))
                self.tgt_na = int(p.get('na', 0))
                self.tgt_so4 = int(p.get('so4', 0))
                self.tgt_cl = int(p.get('cl', 0))
                return

    def calculate_all(self):
        """
        Runs the full calculation pipeline:
        1. Calculate Water Volumes
        2. Use Total Water to Calculate Chemistry
        """
        # 1. WATER CALC
        res_w = BrewMath.calculate_water(
            self.grain_wt, self.grain_temp, self.mash_temp, 
            self.ferm_vol, self.trub_vol, self.boil_time, 
            self.boiloff, self.abs_rate, self.mash_method, 
            self.thickness, self.is_metric
        )
        
        u_vol = "L" if self.is_metric else "gal"
        u_temp = "C" if self.is_metric else "F"

        self.strike_vol = f"{res_w['strike_vol']:.2f} {u_vol}"
        self.sparge_vol = f"{res_w['sparge_vol']:.2f} {u_vol}"
        self.strike_temp = f"{res_w['strike_temp']:.0f} {u_temp}"
        self.pre_boil_vol = f"{res_w['pre_boil_vol']:.2f} {u_vol}"
        self.total_mash_vol = f"{res_w['total_mash_vol']:.2f} {u_vol}"
        
        self.total_water = res_w['total_water']
        
        # 2. CHEMISTRY CALC
        res_c = BrewMath.calculate_chemistry(
            self.total_water, self.srm, self.target_ph, self.grain_wt,
            self.tgt_ca, self.tgt_mg, self.tgt_na, self.tgt_so4, self.tgt_cl, 
            self.is_metric
        )
        
        self.res_gypsum = f"{res_c['gypsum']:.2f} g"
        self.res_cacl2 = f"{res_c['cacl2']:.2f} g"
        self.res_epsom = f"{res_c['epsom']:.2f} g"
        self.res_salt = f"{res_c['salt']:.2f} g"
        self.res_lime = f"{res_c['lime']:.2f} g"
        self.res_acid = f"{res_c['acid']:.1f} ml"
        self.res_acid_g = f"{res_c['acid_g']:.2f} g"

    def exit_app(self):
        from kivy.app import App
        App.get_running_app().stop()
