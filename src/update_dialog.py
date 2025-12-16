import tkinter as tk
from tkinter import ttk
import os
import sys
from update_checker import UpdateChecker

class UpdateDialog(tk.Toplevel):
    def __init__(self, parent, repo_path, changelog_text):
        super().__init__(parent)
        self.repo_path = repo_path
        self.title("Update Available")
        self.geometry("600x450")
        
        # Make modal
        self.transient(parent)
        self.grab_set()
        
        self._layout(changelog_text)
        
        # Center on screen
        self.update_idletasks()
        w = self.winfo_width()
        h = self.winfo_height()
        x = (self.winfo_screenwidth() // 2) - (w // 2)
        y = (self.winfo_screenheight() // 2) - (h // 2)
        self.geometry(f"+{x}+{y}")

    def _layout(self, text):
        # Header
        hdr = ttk.Frame(self, padding=10)
        hdr.pack(fill='x')
        ttk.Label(hdr, text="New version available!", font=('Arial', 14, 'bold')).pack(anchor='w')
        ttk.Label(hdr, text="The following changes will be installed:", font=('Arial', 10)).pack(anchor='w')

        # Scrollable Text Area
        txt_frame = ttk.Frame(self, padding=10)
        txt_frame.pack(fill='both', expand=True)
        
        self.txt_log = tk.Text(txt_frame, height=10, font=('Consolas', 10), wrap='word')
        self.txt_log.pack(side='left', fill='both', expand=True)
        
        sb = ttk.Scrollbar(txt_frame, orient='vertical', command=self.txt_log.yview)
        sb.pack(side='right', fill='y')
        self.txt_log.config(yscrollcommand=sb.set)
        
        # Insert log
        self.txt_log.insert('1.0', text)
        self.txt_log.config(state='disabled') # Read-only

        # Buttons
        btn_frame = ttk.Frame(self, padding=15)
        btn_frame.pack(fill='x', side='bottom')
        
        ttk.Button(btn_frame, text="Not Now", command=self.destroy).pack(side='right', padx=5)
        
        # Green Update Button
        style = ttk.Style()
        style.configure("Update.TButton", font=('Arial', 11, 'bold'), foreground='green')
        ttk.Button(btn_frame, text="Install Update & Restart", style="Update.TButton", command=self._do_update).pack(side='right', padx=5)

    def _do_update(self):
        script_path = os.path.join(self.repo_path, "update.sh")
        success, msg = UpdateChecker.run_update_script(script_path)
        
        if success:
            # Close the app immediately to release file locks/resources for the update
            self.master.destroy()
            sys.exit(0)
        else:
            tk.messagebox.showerror("Update Failed", msg)
