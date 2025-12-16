"""
kettlebrain app
update_checker.py
"""
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
        Executes the update script in a new terminal window and shuts down the current app.
        Uses lxterminal to ensure the process survives the parent app closing
        and sets the correct CWD so git commands work.
        """
        try:
            if not os.path.exists(script_path):
                return False, "Update script not found."

            # Ensure executable permissions
            subprocess.run(["chmod", "+x", script_path], check=False)
            
            # CRITICAL FIX 1: Determine the repo root directory
            # The script is likely in the root, so we use its directory as the CWD
            repo_dir = os.path.dirname(script_path)

            # CRITICAL FIX 2: Launch in a new lxterminal window.
            # - 'lxterminal -e' opens a new window and runs the command.
            # - This creates a new process group, so when Python exits, this window stays open.
            # - passing 'cwd=repo_dir' ensures 'git pull' runs in the right folder.
            subprocess.Popen(
                ["lxterminal", "--working-directory", repo_dir, "-e", f"bash {script_path}"],
                cwd=repo_dir
            )
            
            return True, "Starting update..."
        except Exception as e:
            # Fallback for headless or if lxterminal is missing: 
            # Use 'start_new_session=True' to detach from parent process
            try:
                repo_dir = os.path.dirname(script_path)
                subprocess.Popen(
                    ["bash", script_path], 
                    cwd=repo_dir, 
                    start_new_session=True
                )
                return True, "Starting update (Background mode)..."
            except Exception as e2:
                return False, f"Failed to launch update: {e}"
