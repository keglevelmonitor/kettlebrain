import subprocess
import os
import sys

class UpdateChecker:
    @staticmethod
    def get_available_updates(repo_path):
        """
        Checks for updates and returns the commit log if available.
        Returns: (bool, str) -> (update_available, log_text_or_status)
        """
        try:
            # 1. Fetch latest data (timeout ensures we don't hang if offline)
            subprocess.run(
                ["git", "fetch"], 
                cwd=repo_path, 
                check=True, 
                timeout=10,
                capture_output=True
            )

            # 2. Get the log of commits between local HEAD and upstream
            # --pretty=format:"%h - %s (%cr)" gives: "a1b2c3d - Fixed bug X (2 days ago)"
            try:
                # Determine current branch dynamically
                branch = subprocess.check_output(
                    ["git", "rev-parse", "--abbrev-ref", "HEAD"], 
                    cwd=repo_path
                ).decode().strip()
                
                upstream = f"origin/{branch}"
                
                # Check if we are behind
                local = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo_path).decode().strip()
                remote = subprocess.check_output(["git", "rev-parse", upstream], cwd=repo_path).decode().strip()
                
                if local == remote:
                    return False, "System is up to date."
                
                # Get the formatted log
                log_output = subprocess.check_output(
                    ["git", "log", "--pretty=format:• %s (%cr)", f"HEAD..{upstream}"],
                    cwd=repo_path
                ).decode().strip()
                
                return True, log_output

            except subprocess.CalledProcessError:
                return False, "Git: Detached HEAD or no upstream branch configured."

        except subprocess.TimeoutExpired:
            return False, "Update check timed out (No Internet?)"
        except Exception as e:
            return False, f"Error checking updates: {e}"

    @staticmethod
    def run_update_script(script_path):
        """
        Executes the update script in a new terminal window.
        CRITICAL FIX: Explicitly sets 'cwd' to the repo root to fix Shortcut issues.
        """
        try:
            if not os.path.exists(script_path):
                return False, "Update script not found."

            # Ensure executable
            subprocess.run(["chmod", "+x", script_path], check=False)
            
            # CRITICAL FIX: The script MUST run inside the repo directory
            repo_dir = os.path.dirname(script_path)

            # Launch in lxterminal so the user sees the process
            # This detaches the process so it survives when Python closes
            subprocess.Popen(
                ["lxterminal", "--working-directory", repo_dir, "-e", f"bash {script_path}"],
                cwd=repo_dir
            )
            
            return True, "Update initiated."
        except Exception as e:
            return False, f"Failed to launch update: {e}"
