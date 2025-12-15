"""
src/utils.py
Centralizes unit conversion logic for KettleBrain.
"""

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
