class BrewMath:
    @staticmethod
    def calculate_water(grain_wt, dough_in_temp, mash_temp, target_vol, trub_loss, 
                        boil_time, boiloff_rate, abs_rate, method, thickness, is_metric):
        # Post Boil = Fermenter + Trub
        post_boil_vol = target_vol + trub_loss
        total_boiloff = boiloff_rate * (boil_time / 60.0)
        pre_boil_vol = post_boil_vol + total_boiloff
        
        # Absorption Calculation
        if is_metric:
            # Input is L/kg, result is L
            total_abs = grain_wt * abs_rate
        else:
            # Input is qt/lb, convert to gallons (qt / 4)
            # Result is gallons
            total_abs = (grain_wt * abs_rate) / 4.0
        
        total_water_needed = pre_boil_vol + total_abs
        
        # Strike / Sparge Split
        if method == "Sparge":
            strike_vol = (grain_wt * thickness) if is_metric else (grain_wt * thickness) / 4.0
            strike_vol = min(strike_vol, total_water_needed)
            sparge_vol = total_water_needed - strike_vol
        else:
            strike_vol = total_water_needed
            sparge_vol = 0.0
        
        # Mash Volume & Strike Temp
        grain_disp = grain_wt * (0.67 if is_metric else 0.08)
        total_mash_vol = strike_vol + grain_disp
        
        # Set strike_temp directly to the user's Dough-In target
        strike_temp = dough_in_temp

        return {
            "strike_vol": strike_vol, "strike_temp": strike_temp, "sparge_vol": sparge_vol,
            "total_mash_vol": total_mash_vol, "pre_boil_vol": pre_boil_vol, "total_water": total_water_needed
        }

    @staticmethod
    def calculate_chemistry(water_vol, srm, target_ph, grain_wt, 
                            tgt_ca, tgt_mg, tgt_na, tgt_so4, tgt_cl, is_metric):
        if water_vol <= 0: return {k: 0.0 for k in ["gypsum", "cacl2", "epsom", "salt", "lime", "acid", "acid_g"]}

        # Normalize to Liters and Kg for chemistry math
        vol_L = water_vol if is_metric else water_vol * 3.78541
        grain_kg = grain_wt if is_metric else grain_wt * 0.453592

        # Salts
        g_epsom = (tgt_mg * vol_L) / 98.6
        added_so4_epsom = (g_epsom * 1000 * 0.39) / vol_L
        g_salt = (tgt_na * vol_L) / 393.0
        added_cl_salt = (g_salt * 1000 * 0.607) / vol_L
        
        rem_so4 = max(0, tgt_so4 - added_so4_epsom)
        g_gypsum = (rem_so4 * vol_L) / 558.0 
        added_ca_gypsum = (g_gypsum * 1000 * 0.233) / vol_L
        
        rem_cl = max(0, tgt_cl - added_cl_salt)
        g_cacl2 = (rem_cl * vol_L) / 482.0    
        added_ca_cacl2 = (g_cacl2 * 1000 * 0.272) / vol_L
        
        total_ca_salts = added_ca_gypsum + added_ca_cacl2
        rem_ca = max(0, tgt_ca - total_ca_salts)
        g_lime = (rem_ca * vol_L) / 540.0 if rem_ca > 0.1 else 0.0
        
        # Acid Calculation
        # Base pH intercept 5.70 aligned with RO water
        base_mash_ph = 5.70 - (0.018 * srm) # changed base mash pH from 5.7 to 5.77 for higher pH result
        meq_ca = (total_ca_salts + rem_ca) / 20.0  
        meq_mg = tgt_mg / 12.15
        salt_ph_drop = (meq_ca * 0.04) + (meq_mg * 0.03) # changed meq_ca multiplier from 0.04 to 0.028 for higher pH result
        est_mash_ph = base_mash_ph - salt_ph_drop
        
        # Switch to volume-based buffering (Braukaiser logic: ~0.82 ml/L/pH)
        if est_mash_ph > target_ph:
            ml_acid_base = (est_mash_ph - target_ph) * vol_L * 0.82
        else:
            ml_acid_base = 0.0
        # ml_acid_base = (est_mash_ph - target_ph) * grain_kg * 3.3 if grain_kg > 0 else 0.0 # changed multiplier from 3.0 to 3.3 for higher pH result
        total_acid = max(0, ml_acid_base + (g_lime * 2.3))
        
        return {
            "gypsum": g_gypsum, "cacl2": g_cacl2, "epsom": g_epsom, "salt": g_salt,
            "lime": g_lime, "acid": total_acid, "acid_g": total_acid * 1.21
        }
