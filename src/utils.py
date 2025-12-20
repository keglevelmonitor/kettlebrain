"""
src/utils.py
Centralizes unit conversion logic for KettleBrain.
"""
import json
import os

class UnitUtils:
    @staticmethod
    def is_metric(settings_manager):
        """Returns True if settings are set to metric."""
        try:
            # Handle both raw dict and SettingsManager class
            if hasattr(settings_manager, "get_system_setting"):
                u = settings_manager.get_system_setting("units", "imperial")
            else:
                u = settings_manager.get("system_settings", {}).get("units", "imperial")
            return u == "metric"
        except:
            return False

    @staticmethod
    def format_temp(temp_f, settings_manager):
        """
        Returns string "152.0°F" or "66.7°C"
        """
        if temp_f is None: return "--.-"
        
        if UnitUtils.is_metric(settings_manager):
            c = (float(temp_f) - 32) * 5.0/9.0
            return f"{c:.1f}°C"
        return f"{float(temp_f):.1f}°F"

    @staticmethod
    def format_volume(vol_gal, settings_manager):
        """
        Returns string "5.00 Gal" or "18.93 L"
        """
        if vol_gal is None: return ""
        
        if UnitUtils.is_metric(settings_manager):
            l = float(vol_gal) * 3.78541
            return f"{l:.2f} L"
        return f"{float(vol_gal):.2f} Gal"

    @staticmethod
    def to_user_temp(temp_f, settings_manager):
        """Converts internal F to user's preferred unit value (float)."""
        if temp_f is None: return None
        if UnitUtils.is_metric(settings_manager):
            return (float(temp_f) - 32) * 5.0/9.0
        return float(temp_f)

    @staticmethod
    def to_system_temp(user_temp, settings_manager):
        """Converts user's input float back to internal F."""
        if user_temp is None: return None
        if UnitUtils.is_metric(settings_manager):
            return (float(user_temp) * 9.0/5.0) + 32
        return float(user_temp)

    @staticmethod
    def to_user_vol(vol_gal, settings_manager):
        """Converts internal Gal to user's preferred unit value (float)."""
        if vol_gal is None: return None
        if UnitUtils.is_metric(settings_manager):
            return float(vol_gal) * 3.78541
        return float(vol_gal)

    @staticmethod
    def to_system_vol(user_vol, settings_manager):
        """Converts user's input float back to internal Gal."""
        if user_vol is None: return None
        if UnitUtils.is_metric(settings_manager):
            return float(user_vol) / 3.78541
        return float(user_vol)

class BrewMath:
    """
    Centralized math logic for water volumes and chemistry.
    """
    @staticmethod
    def calculate_water(grain_wt, grain_temp, mash_temp, target_vol, trub_loss, 
                        boil_time, boiloff_rate, abs_rate, method, thickness, is_metric):
        """
        Returns a dictionary with calculated volumes and temps.
        Units are implicitly handled based on the is_metric flag (inputs are assumed to match that system).
        """
        results = {
            "strike_vol": 0.0,
            "strike_temp": 0.0,
            "sparge_vol": 0.0,
            "total_mash_vol": 0.0,
            "pre_boil_vol": 0.0,
            "post_boil_vol": 0.0,
            "total_water": 0.0
        }

        # Post Boil = Fermenter + Trub
        post_boil_vol = target_vol + trub_loss
        
        # Boiloff
        boil_hours = boil_time / 60.0
        total_boiloff = boiloff_rate * boil_hours
        
        # Pre-Boil
        pre_boil_vol = post_boil_vol + total_boiloff
        
        # Absorption
        if is_metric:
            total_abs = grain_wt * abs_rate
        else:
            # Imperial abs_rate is typically qt/lb, convert to gal
            total_abs = (grain_wt * abs_rate) / 4.0
        
        total_water_needed = pre_boil_vol + total_abs
        
        # Strike / Sparge Split
        strike_vol = 0.0
        sparge_vol = 0.0
        
        if method == "sparge":
            if is_metric:
                strike_vol = grain_wt * thickness
            else:
                # Imperial thickness is qt/lb, convert to gal
                strike_vol = (grain_wt * thickness) / 4.0
            
            if strike_vol > total_water_needed:
                strike_vol = total_water_needed
                sparge_vol = 0.0
            else:
                sparge_vol = total_water_needed - strike_vol
        else:
            strike_vol = total_water_needed
            sparge_vol = 0.0
        
        # Total Mash Vol (Water + Grain Displacement)
        if is_metric:
            grain_disp = grain_wt * 0.67
        else:
            grain_disp = grain_wt * 0.08
            
        total_mash_vol = strike_vol + grain_disp
        
        # Strike Temp Calculation
        strike_temp = mash_temp
        if grain_wt > 0 and strike_vol > 0:
            if is_metric:
                ratio = strike_vol / grain_wt
                # Metric Constant 0.41
                strike_temp = mash_temp + (0.41 / ratio) * (mash_temp - grain_temp)
            else:
                # Imperial Constant 0.2
                # Ratio for formula must be qt/lb
                strike_vol_qts = strike_vol * 4.0
                ratio = strike_vol_qts / grain_wt
                strike_temp = mash_temp + (0.2 / ratio) * (mash_temp - grain_temp)

        results["strike_vol"] = strike_vol
        results["strike_temp"] = strike_temp
        results["sparge_vol"] = sparge_vol
        results["total_mash_vol"] = total_mash_vol
        results["pre_boil_vol"] = pre_boil_vol
        results["post_boil_vol"] = post_boil_vol
        results["total_water"] = total_water_needed
        
        return results

    @staticmethod
    def calculate_chemistry(water_vol, srm, target_ph, grain_wt, 
                            tgt_ca, tgt_mg, tgt_na, tgt_so4, tgt_cl, is_metric):
        """
        Returns a dictionary of salt additions (in grams) and acid (in ml).
        """
        results = {
            "gypsum": 0.0,
            "cacl2": 0.0,
            "epsom": 0.0,
            "salt": 0.0,
            "lime": 0.0,
            "acid": 0.0
        }

        if water_vol <= 0:
            return results

        # Normalize to Liters and Kg for calculation
        if is_metric:
            vol_L = water_vol
            grain_kg = grain_wt
        else:
            vol_L = water_vol * 3.78541
            grain_kg = grain_wt * 0.453592

        # --- PART A: SALT CALCULATOR ---
        # Epsom (MgSO4)
        g_epsom = (tgt_mg * vol_L) / 98.6
        added_so4_epsom = (g_epsom * 1000 * 0.39) / vol_L
        
        # Salt (NaCl)
        g_salt = (tgt_na * vol_L) / 393.0
        added_cl_salt = (g_salt * 1000 * 0.607) / vol_L
        
        # Gypsum (CaSO4)
        rem_so4 = max(0, tgt_so4 - added_so4_epsom)
        g_gypsum = (rem_so4 * vol_L) / 558.0 
        added_ca_gypsum = (g_gypsum * 1000 * 0.233) / vol_L
        
        # CaCl2
        rem_cl = max(0, tgt_cl - added_cl_salt)
        g_cacl2 = (rem_cl * vol_L) / 482.0    
        added_ca_cacl2 = (g_cacl2 * 1000 * 0.272) / vol_L
        
        # Lime (CaOH2)
        total_ca_salts = added_ca_gypsum + added_ca_cacl2
        rem_ca = max(0, tgt_ca - total_ca_salts)
        g_lime = 0.0
        if rem_ca > 0.1:
            g_lime = (rem_ca * vol_L) / 540.0
        
        # --- PART B: ACID CALCULATOR ---
        base_mash_ph = 5.65 - (0.018 * srm)
        
        meq_ca = (total_ca_salts + rem_ca) / 20.0  
        meq_mg = tgt_mg / 12.15
        salt_ph_drop = (meq_ca * 0.04) + (meq_mg * 0.03)
        
        est_mash_ph = base_mash_ph - salt_ph_drop
        delta_ph = est_mash_ph - target_ph
        
        ml_acid_base = 0.0
        if grain_kg > 0:
            ml_acid_base = delta_ph * grain_kg * 3.0
            
        ml_acid_lime = g_lime * 2.3
        total_acid = ml_acid_base + ml_acid_lime
        
        results["gypsum"] = g_gypsum
        results["cacl2"] = g_cacl2
        results["epsom"] = g_epsom
        results["salt"] = g_salt
        results["lime"] = g_lime
        results["acid"] = max(0, total_acid)
        
        return results

class WaterProfileLoader:
    @staticmethod
    def load_profiles():
        """
        Loads water profiles from target_water_profiles.json.
        Checks 'src/assets/' first (standard), then '../assets/' (root).
        Returns a sorted list of dictionaries.
        """
        try:
            # 1. Determine potential paths
            base_dir = os.path.dirname(os.path.abspath(__file__)) # This is .../kettlebrain/src
            
            # Path A: kettlebrain/src/assets/target_water_profiles.json (Standard for images)
            path_a = os.path.join(base_dir, "assets", "target_water_profiles.json")
            
            # Path B: kettlebrain/assets/target_water_profiles.json (Sibling to src)
            path_b = os.path.join(os.path.dirname(base_dir), "assets", "target_water_profiles.json")
            
            final_path = None
            
            if os.path.exists(path_a):
                final_path = path_a
            elif os.path.exists(path_b):
                final_path = path_b
            
            if not final_path:
                # Print explicit locations we checked for debugging
                print(f"[WaterProfileLoader] ERROR: Profile file not found.")
                print(f"   Checked: {path_a}")
                print(f"   Checked: {path_b}")
                return []

            print(f"[WaterProfileLoader] Loading profiles from: {final_path}")
                
            with open(final_path, 'r') as f:
                data = json.load(f)
                
            # Validate data is a list
            if not isinstance(data, list):
                print("[WaterProfileLoader] JSON content is not a list.")
                return []

            # Sort alphabetically by name
            data.sort(key=lambda x: x.get("name", "").lower())
            return data
            
        except Exception as e:
            print(f"[WaterProfileLoader] Error loading profiles: {e}")
            return []
