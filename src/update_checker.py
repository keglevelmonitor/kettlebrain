import subprocess
import os
import sys

class UpdateChecker:
    @staticmethod
    def check_for_updates(repo_path):
        """
        Checks if the local git repo is behind the remote origin.
        Returns: (bool, str) -> (update_available, status_message)
        """
        try:
            # 1. Fetch latest data (timeout ensures we don't hang if offline)
            subprocess.run(
                ["git", "fetch"], 
                cwd=repo_path, 
                check=True, 
                timeout=5,
                capture_output=True
            )

            # 2. Get Local Hash
            local_hash = subprocess.check_output(
                ["git", "rev-parse", "HEAD"], 
                cwd=repo_path
            ).decode().strip()

            # 3. Get Upstream Hash
            # Dynamically determine the tracking branch (e.g., origin/main or origin/master)
            try:
                branch = subprocess.check_output(
                    ["git", "rev-parse", "--abbrev-ref", "HEAD"], 
                    cwd=repo_path
                ).decode().strip()
                
                remote_hash = subprocess.check_output(
                    ["git", "rev-parse", f"origin/{branch}"], 
                    cwd=repo_path
                ).decode().strip()
            except subprocess.CalledProcessError:
                # Fallback if detached HEAD or odd state
                return False, "Git: Detached HEAD or no upstream."

            if local_hash != remote_hash:
                short_local = local_hash[:7]
                short_remote = remote_hash[:7]
                return True, f"New version available.\nLocal: {short_local}\nRemote: {short_remote}"
            
            return False, "System is up to date."

        except subprocess.TimeoutExpired:
            return False, "Update check timed out (No Internet?)"
        except subprocess.CalledProcessError:
            return False, "Git Error: Not a valid repository or network issue."
        except Exception as e:
            return False, f"Error checking updates: {e}"

    @staticmethod
    def run_update_script(script_path):
        """
        Executes the update script and shuts down the current app.
        """
        try:
            if not os.path.exists(script_path):
                return False, "Update script not found."

            # Ensure executable permissions
            subprocess.run(["chmod", "+x", script_path], check=False)
            
            # Launch the update script detached
            subprocess.Popen(["bash", script_path])
            return True, "Starting update..."
        except Exception as e:
            return False, f"Failed to launch update: {e}"
