"""
src/pid_controller.py
Standard PID implementation for KettleBrain
"""
import time

class PIDController:
    def __init__(self, kp, ki, kd, output_limits=(0, 100)):
        self.kp = kp
        self.ki = ki
        self.kd = kd
        self.min_out, self.max_out = output_limits
        
        self._last_time = None
        self._integral = 0.0
        self._last_error = 0.0

    def reset(self):
        self._last_time = None
        self._integral = 0.0
        self._last_error = 0.0

    def compute(self, current_value, setpoint):
        now = time.monotonic()
        if self._last_time is None:
            self._last_time = now
            return 0.0  # First run, no output

        dt = now - self._last_time
        if dt <= 0: return 0.0

        # Error
        error = setpoint - current_value

        # Proportional
        p_term = self.kp * error

        # --- INTEGRAL LOGIC WITH WINDOW ---
        # Only accumulate Integral if we are close to target (e.g. within +/- 5 degrees)
        # This prevents "Windup" during the long initial heating phase.
        if abs(error) < 5.0:
            self._integral += error * dt
            # Clamp Integral Term
            if self._integral * self.ki > self.max_out: 
                self._integral = self.max_out / self.ki
            elif self._integral * self.ki < self.min_out: 
                self._integral = self.min_out / self.ki
        else:
            # If we are far away, reset the integral bucket
            self._integral = 0.0
            
        i_term = self.ki * self._integral
        # -----------------------------------

        # Derivative
        d_term = 0.0
        if dt > 0:
            d_term = self.kd * (error - self._last_error) / dt

        # Total Output
        output = p_term + i_term + d_term
        
        # Clamp Output
        if output > self.max_out: output = self.max_out
        elif output < self.min_out: output = self.min_out

        # State updates
        self._last_error = error
        self._last_time = now

        return output
