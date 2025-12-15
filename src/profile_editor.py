"""
kettlebrain app
profile_editor.py
"""
import tkinter as tk
from tkinter import ttk, messagebox
import copy
from datetime import datetime, timedelta
from profile_data import BrewProfile, BrewStep, StepType, TimeoutBehavior, BrewAddition
from utils import UnitUtils 

class AdditionsDialog(tk.Toplevel):
    def __init__(self, parent, step_name, additions_list):
        super().__init__(parent)
        self.withdraw()
        self.title(f"Alerts for: {step_name}")
        self.geometry("400x300")
        self.transient(parent)
        
        self.additions = additions_list 
        self.editing_index = None    
        
        self._layout()
        self._refresh()
        
        self.update_idletasks()
        try:
            x = parent.winfo_rootx() + 20
            y = parent.winfo_rooty() + 20
            self.geometry(f"+{x}+{y}")
        except:
            pass

        self.deiconify()
        self.focus_set()
        self.protocol("WM_DELETE_WINDOW", self.close)

    def close(self):
        self.destroy()

    def _layout(self):
        list_frame = ttk.Frame(self, padding=5)
        list_frame.pack(fill='both', expand=True)
        
        self.lb_additions = tk.Listbox(list_frame, height=6, font=('Arial', 11))
        self.lb_additions.pack(side='left', fill='both', expand=True)
        
        sb = ttk.Scrollbar(list_frame, orient='vertical', command=self.lb_additions.yview)
        sb.pack(side='right', fill='y')
        
        self.lb_additions.config(yscrollcommand=sb.set)
        
        input_frame = ttk.LabelFrame(self, text="Item Details", padding=5)
        input_frame.pack(fill='x', padx=5)
        
        ttk.Label(input_frame, text="Name:").grid(row=0, column=0, sticky='w')
        self.var_name = tk.StringVar()
        ttk.Entry(input_frame, textvariable=self.var_name).grid(row=0, column=1, sticky='ew', padx=5)
        
        ttk.Label(input_frame, text="Min Remaining:").grid(row=1, column=0, sticky='w')
        self.var_time = tk.StringVar()
        ttk.Entry(input_frame, textvariable=self.var_time, width=5).grid(row=1, column=1, sticky='w', padx=5)
        
        input_frame.columnconfigure(1, weight=1)
        
        btn_frame = ttk.Frame(self, padding=5)
        btn_frame.pack(fill='x')
        
        self.btn_save = ttk.Button(btn_frame, text="Add New", command=self._save_addition)
        self.btn_save.pack(side='left', fill='x', expand=True, padx=2)
        
        ttk.Button(btn_frame, text="Edit Selected", command=self._load_for_edit).pack(side='left', fill='x', expand=True, padx=2)
        ttk.Button(btn_frame, text="Remove", command=self._remove).pack(side='left', fill='x', expand=True, padx=2)

        done_frame = ttk.Frame(self, padding=(5, 0, 5, 5))
        done_frame.pack(fill='x', side='bottom')
        ttk.Button(done_frame, text="Done / Close", command=self.close).pack(fill='x', pady=2)

    def _refresh(self):
        self.lb_additions.delete(0, tk.END)
        self.additions.sort(key=lambda x: x.time_point_min, reverse=True)
        for add in self.additions:
            self.lb_additions.insert(tk.END, f"{add.time_point_min}m: {add.name}")

    def _load_for_edit(self):
        sel = self.lb_additions.curselection()
        if not sel: return
        idx = sel[0]
        self.editing_index = idx
        item = self.additions[idx]
        self.var_name.set(item.name)
        self.var_time.set(str(item.time_point_min))
        self.btn_save.config(text="Update Item")

    def _save_addition(self):
        name = self.var_name.get().strip()
        t_str = self.var_time.get().strip()
        if not name or not t_str: return
        
        try:
            t_val = int(t_str)
            if self.editing_index is not None:
                item = self.additions[self.editing_index]
                item.name = name
                item.time_point_min = t_val
                self.editing_index = None
                self.btn_save.config(text="Add New")
            else:
                new_add = BrewAddition(name=name, time_point_min=t_val)
                self.additions.append(new_add)
                
            self._refresh()
            self.var_name.set("")
            self.var_time.set("")
        except ValueError:
            messagebox.showerror("Error", "Time must be an integer (minutes).", parent=self)

    def _remove(self):
        sel = self.lb_additions.curselection()
        if not sel: return
        if self.editing_index == sel[0]:
            self.editing_index = None
            self.btn_save.config(text="Add New")
            self.var_name.set("")
            self.var_time.set("")
        self.additions.pop(sel[0])
        self._refresh()


class ProfileEditor(tk.Toplevel):
    def __init__(self, parent, profile: BrewProfile, settings_manager, on_save_callback):
        super().__init__(parent)
        self.withdraw()
        
        self.title(f"Editing Profile")
        
        # INCREASED HEIGHT: 780x440
        self.geometry("780x440")
        self.transient(parent)
        
        self.profile = profile
        self.settings = settings_manager
        self.on_save = on_save_callback
        
        self.steps_working_copy = copy.deepcopy(profile.steps) 
        self.current_step_index = None 
        
        self.list_map = [] 
        self.loading_step = False 
        
        self._configure_styles()
        self._create_layout()
        self._refresh_step_list()
        
        if self.steps_working_copy:
            self._select_visual_row(0)
        
        self.protocol("WM_DELETE_WINDOW", self.close)
        
        self.update_idletasks()
        try:
            x = parent.winfo_rootx() + 10
            y = parent.winfo_rooty() + 10
            self.geometry(f"+{x}+{y}")
        except:
            pass

        self.focus_set()
        self.grab_set() 
        self.lift()
        self.deiconify() 

    def close(self):
        if self.current_step_index is not None:
             self._save_current_edit()

        if self.steps_working_copy != self.profile.steps:
            if not messagebox.askyesno("Unsaved Changes", "You have made changes. Discard them?", parent=self):
                return 

        try:
            self.grab_release()
            if self.master:
                self.master.focus_set() 
        except:
            pass
        finally:
            self.destroy()

    def _configure_styles(self):
        s = ttk.Style()
        s.configure('Editor.TFrame', background='#f0f0f0')
        s.configure('StepList.TFrame', background='white', relief='sunken')
        s.configure('Header.TLabel', font=('Arial', 12, 'bold'))
        s.configure('SubHeader.TLabel', font=('Arial', 10, 'bold'), foreground='#555555')

    def _create_layout(self):
        # 1. PACK BUTTONS FIRST (Bottom) - Ensures they are never pushed off screen
        bot_frame = ttk.Frame(self)
        bot_frame.pack(side='bottom', fill='x', padx=10, pady=5)
        
        ttk.Button(bot_frame, text="Cancel", command=self.close).pack(side='right', padx=5)
        ttk.Button(bot_frame, text="Save Profile", command=self._save_and_close).pack(side='right', padx=5)

        # 2. PACK MAIN CONTENT (Fills remaining space)
        self.main_frame = ttk.Frame(self, padding=5)
        self.main_frame.pack(side='top', fill='both', expand=True)
        
        # TOP ROW: Name Input
        top_frame = ttk.Frame(self.main_frame)
        top_frame.pack(fill='x', pady=(0, 5))
        
        ttk.Label(top_frame, text="Profile Name:", style='Header.TLabel').pack(side='left')
        self.var_profile_name = tk.StringVar(value=self.profile.name)
        ent_name = ttk.Entry(top_frame, textvariable=self.var_profile_name, font=('Arial', 11))
        ent_name.pack(side='left', fill='x', expand=True, padx=10)
        
        content_frame = ttk.Frame(self.main_frame)
        content_frame.pack(fill='both', expand=True)

        # LEFT PANE (List)
        left_pane = ttk.Frame(content_frame, width=220)
        left_pane.pack(side='left', fill='both', padx=(0, 5), expand=False)
        
        ttk.Label(left_pane, text="Sequence", style='SubHeader.TLabel').pack(anchor='w', pady=(0, 2))
        
        list_container = ttk.Frame(left_pane)
        list_container.pack(fill='both', expand=True)
        
        self.step_listbox = tk.Listbox(list_container, font=('Arial', 10), selectmode=tk.SINGLE, activator=None, height=10)
        self.step_listbox.pack(side='left', fill='both', expand=True)
        self.step_listbox.bind('<<ListboxSelect>>', self._on_step_select)
        
        scroll = ttk.Scrollbar(list_container, orient='vertical', command=self.step_listbox.yview)
        scroll.pack(side='right', fill='y')
        self.step_listbox.config(yscrollcommand=scroll.set)
        
        btn_row = ttk.Frame(left_pane)
        btn_row.pack(fill='x', pady=2)
        ttk.Button(btn_row, text="+ Add", width=5, command=self._add_step).pack(side='left', expand=True, fill='x', padx=1)
        ttk.Button(btn_row, text="- Del", width=5, command=self._delete_step).pack(side='left', expand=True, fill='x', padx=1)
        ttk.Button(btn_row, text="▲", width=3, command=self._move_up).pack(side='left', padx=1)
        ttk.Button(btn_row, text="▼", width=3, command=self._move_down).pack(side='left', padx=1)

        # RIGHT PANE (Form)
        self.right_pane = ttk.LabelFrame(content_frame, text="Selected Step Details", padding=5)
        self.right_pane.pack(side='right', fill='both', expand=True)
        
        self._init_form_vars()
        self._build_form_widgets()

    def _init_form_vars(self):
        self.var_name = tk.StringVar()
        self.var_type = tk.StringVar()
        self.var_temp = tk.StringVar()
        self.var_duration = tk.StringVar()
        self.var_power = tk.StringVar(value="1800")
        self.var_volume = tk.StringVar()
        self.var_timeout = tk.StringVar()
        
        self.var_ds_date = tk.StringVar()
        self.var_ds_hour = tk.StringVar(value="00")
        self.var_ds_min = tk.StringVar(value="00")
        
        self.var_type.trace_add('write', self._on_type_change)

    def _generate_date_options(self):
        dates = []
        now = datetime.now()
        for i in range(31):
            d = now + timedelta(days=i)
            dates.append(d.strftime("%Y-%m-%d %a"))
        return dates

    def _build_form_widgets(self):
        f = self.right_pane
        f.columnconfigure(1, weight=1)
        f.columnconfigure(3, weight=1)

        row = 0
        pad_y = 5 
        pad_x = 5

        # --- ROW 0: Type & Name ---
        type_opts = [e.value for e in StepType]
        self.cb_type = ttk.Combobox(f, textvariable=self.var_type, values=type_opts, state='readonly', width=12)
        
        ttk.Label(f, text="Type:").grid(row=row, column=0, sticky='e', padx=pad_x, pady=pad_y)
        self.cb_type.grid(row=row, column=1, sticky='ew', padx=pad_x, pady=pad_y)
        
        ttk.Label(f, text="Name:").grid(row=row, column=2, sticky='e', padx=pad_x, pady=pad_y)
        ttk.Entry(f, textvariable=self.var_name).grid(row=row, column=3, sticky='ew', padx=pad_x, pady=pad_y)
        row += 1

        # --- ROW 1: Setpoint & Duration ---
        is_metric = UnitUtils.is_metric(self.settings)
        t_label = "Temp (°C):" if is_metric else "Temp (°F):"
        
        self.lbl_temp = ttk.Label(f, text=t_label)
        self.lbl_temp.grid(row=row, column=0, sticky='e', padx=pad_x, pady=pad_y)
        
        self.ent_temp = ttk.Entry(f, textvariable=self.var_temp, width=8)
        self.ent_temp.grid(row=row, column=1, sticky='w', padx=pad_x, pady=pad_y)
        
        self.lbl_dur = ttk.Label(f, text="Duration (min):")
        self.lbl_dur.grid(row=row, column=2, sticky='e', padx=pad_x, pady=pad_y)
        
        self.frm_dur_container = ttk.Frame(f)
        self.frm_dur_container.grid(row=row, column=3, sticky='ew', padx=pad_x, pady=pad_y)
        
        self.ent_dur = ttk.Entry(self.frm_dur_container, textvariable=self.var_duration)
        self.ent_dur.pack(fill='x', expand=True)
        
        self.frm_delay = ttk.Frame(self.frm_dur_container)
        date_opts = self._generate_date_options()
        self.cb_date = ttk.Combobox(self.frm_delay, textvariable=self.var_ds_date, values=date_opts, state='readonly', width=12)
        self.cb_date.pack(side='left', padx=(0, 2))
        if date_opts: self.cb_date.set(date_opts[0])
        
        sb_h = ttk.Spinbox(self.frm_delay, from_=0, to=23, textvariable=self.var_ds_hour, width=3, format="%02.0f", wrap=True)
        sb_h.pack(side='left')
        ttk.Label(self.frm_delay, text=":").pack(side='left')
        sb_m = ttk.Spinbox(self.frm_delay, from_=0, to=59, textvariable=self.var_ds_min, width=3, format="%02.0f", wrap=True)
        sb_m.pack(side='left')
        
        row += 1

        # --- ROW 2: Power & Volume ---
        pwr_values = ["1800", "1400", "1000", "800"]
        self.cb_pwr = ttk.Combobox(f, textvariable=self.var_power, values=pwr_values, state='readonly', width=8)
        
        self.lbl_pwr = ttk.Label(f, text="Watts:")
        self.lbl_pwr.grid(row=row, column=0, sticky='e', padx=pad_x, pady=pad_y)
        self.cb_pwr.grid(row=row, column=1, sticky='w', padx=pad_x, pady=pad_y)
        
        v_label = "Vol (L):" if is_metric else "Vol (Gal):"
        self.lbl_vol = ttk.Label(f, text=v_label)
        self.lbl_vol.grid(row=row, column=2, sticky='e', padx=pad_x, pady=pad_y)
        
        self.ent_vol = ttk.Entry(f, textvariable=self.var_volume)
        self.ent_vol.grid(row=row, column=3, sticky='ew', padx=pad_x, pady=pad_y)
        row += 1
        
        # --- ROW 3: Timeout Behavior ---
        ttk.Label(f, text="Timeout:").grid(row=row, column=0, sticky='e', padx=pad_x, pady=pad_y)
        to_opts = [e.value for e in TimeoutBehavior]
        self.cb_to = ttk.Combobox(f, textvariable=self.var_timeout, values=to_opts, state='readonly')
        self.cb_to.grid(row=row, column=1, columnspan=3, sticky='ew', padx=pad_x, pady=pad_y)
        row += 1
        
        # --- ROW 4: Additions Button ---
        self.btn_additions = ttk.Button(f, text="Manage Alerts / Additions...", command=self._open_additions)
        self.btn_additions.grid(row=row, column=1, columnspan=3, sticky='ew', padx=pad_x, pady=pad_y)
        row += 1
        
        # --- ROW 5: Notes (Multi-line Text) ---
        ttk.Label(f, text="Notes:").grid(row=row, column=0, sticky='ne', padx=pad_x, pady=pad_y)
        self.txt_note = tk.Text(f, height=2, width=30, font=('Arial', 10))
        self.txt_note.grid(row=row, column=1, columnspan=3, sticky='ew', padx=pad_x, pady=pad_y)
        row += 1
        
        # --- ROW 6: Alerts Preview (REDUCED to 5 lines) ---
        ttk.Label(f, text="Alerts:").grid(row=row, column=0, sticky='ne', padx=pad_x, pady=pad_y)
        self.lb_alerts_preview = tk.Listbox(f, height=5, font=('Arial', 10), bg='white', bd=1, relief='sunken')
        self.lb_alerts_preview.grid(row=row, column=1, columnspan=3, sticky='ew', padx=pad_x, pady=pad_y)
        row += 1
        
        self._toggle_form_state(False)

    def _refresh_step_list(self):
        self.step_listbox.delete(0, tk.END)
        self.list_map = [] 
        
        for i, step in enumerate(self.steps_working_copy):
            desc = f"{i+1}. {step.name} [{step.step_type.value}]"
            self.step_listbox.insert(tk.END, desc)
            self.list_map.append(i) 
            
            if step.additions:
                sorted_adds = sorted(step.additions, key=lambda x: x.time_point_min, reverse=True)
                for add in sorted_adds:
                    self.step_listbox.insert(tk.END, f"    ↳ {add.name}")
                    last_idx = self.step_listbox.size() - 1
                    self.step_listbox.itemconfigure(last_idx, fg='#666666')
                    self.list_map.append(i) 

    def _refresh_alerts_preview(self, step):
        self.lb_alerts_preview.delete(0, tk.END)
        if not step.additions:
            self.lb_alerts_preview.insert(0, "(None)")
            return
            
        sorted_adds = sorted(step.additions, key=lambda x: x.time_point_min, reverse=True)
        for add in sorted_adds:
            self.lb_alerts_preview.insert(tk.END, f"{add.time_point_min}m: {add.name}")

    def _save_current_edit(self):
        if self.current_step_index is None: return True
        if not (0 <= self.current_step_index < len(self.steps_working_copy)): return True
        
        step = self.steps_working_copy[self.current_step_index]
        
        try:
            step.name = self.var_name.get()
            step.step_type = StepType(self.var_type.get())
            step.timeout_behavior = TimeoutBehavior(self.var_timeout.get())
            step.note = self.txt_note.get("1.0", tk.END).strip()
            
            t_val = self.var_temp.get().strip()
            if t_val != "":
                step.setpoint_f = UnitUtils.to_system_temp(float(t_val), self.settings)
            else:
                step.setpoint_f = None
                
            step.lauter_temp_f = None
            
            p_val = self.var_power.get().strip()
            step.power_watts = int(p_val) if p_val != "" else None
            
            v_val = self.var_volume.get().strip()
            if v_val != "":
                step.lauter_volume = UnitUtils.to_system_vol(float(v_val), self.settings)
            else:
                step.lauter_volume = None
            
            d_val = self.var_duration.get().strip()
            
            # REMOVED DELAYED_START IF/ELSE BLOCK
            if d_val == "":
                 step.duration_min = 0.0
            else:
                 f_val = float(d_val)
                 if f_val < 0:
                     messagebox.showerror("Error", "Duration cannot be negative.", parent=self)
                     return False
                 step.duration_min = f_val
                 
            step.target_completion_time = None
                 
            return True
            
        except ValueError as e:
            messagebox.showerror("Validation Error", f"Invalid input: {e}", parent=self)
            return False

    def _on_step_select(self, event):
        if not self._save_current_edit():
            self._select_visual_row_by_step_index(self.current_step_index)
            return

        sel = self.step_listbox.curselection()
        if not sel: return
        
        visual_index = sel[0]
        if visual_index < len(self.list_map):
            real_index = self.list_map[visual_index]
        else:
            return

        step = self.steps_working_copy[real_index]
        self.current_step_index = real_index 
        
        self.loading_step = True
        
        self.var_name.set(step.name)
        self.var_type.set(step.step_type.value) 
        
        if step.setpoint_f is not None:
            user_t = UnitUtils.to_user_temp(step.setpoint_f, self.settings)
            self.var_temp.set(f"{user_t:.1f}")
        else:
            self.var_temp.set("")
        
        self.var_duration.set(str(step.duration_min) if step.duration_min is not None else "")
        
        pwr = str(step.power_watts) if step.power_watts is not None else "1800"
        self.var_power.set(pwr)
        
        if step.lauter_volume is not None:
            user_v = UnitUtils.to_user_vol(step.lauter_volume, self.settings)
            self.var_volume.set(f"{user_v:.2f}")
        else:
            self.var_volume.set("")
            
        self.var_timeout.set(step.timeout_behavior.value)
        
        # REMOVED DELAYED_START LOADING BLOCK
        
        self.txt_note.delete('1.0', tk.END)
        self.txt_note.insert('1.0', step.note)
        
        self._refresh_alerts_preview(step)
        
        self.loading_step = False
        
        self._toggle_form_state(True)

    def _select_visual_row(self, visual_idx):
        self.step_listbox.selection_clear(0, tk.END)
        self.step_listbox.selection_set(visual_idx)
        self.step_listbox.event_generate("<<ListboxSelect>>")

    def _select_visual_row_by_step_index(self, step_idx):
        if step_idx is None: return
        try:
            visual_idx = self.list_map.index(step_idx)
            self._select_visual_row(visual_idx)
            self.step_listbox.see(visual_idx)
        except ValueError:
            pass

    def _open_additions(self):
        self._save_current_edit()
        
        if self.current_step_index is None: return
        step = self.steps_working_copy[self.current_step_index]
        
        self._toggle_interaction(False)
        dlg = AdditionsDialog(self, step.name, step.additions)
        self.wait_window(dlg)
        
        if not self.winfo_exists(): return

        self._toggle_interaction(True)
        self._refresh_step_list()
        self._select_visual_row_by_step_index(self.current_step_index)
        self._refresh_alerts_preview(step)

    def _toggle_interaction(self, enable):
        state = '!disabled' if enable else 'disabled'
        for child in self.main_frame.winfo_children():
            self._recursive_state(child, state)

    def _recursive_state(self, widget, state):
        try:
            widget.state([state])
        except:
            pass
        for child in widget.winfo_children():
            self._recursive_state(child, state)

    def _on_type_change(self, *args):
        t_val = self.var_type.get()
        try:
            t = StepType(t_val)
        except:
            return

        if not self.loading_step:
            self.var_name.set(t_val)

        # Default State: Everything Enabled
        self._set_state(self.ent_temp, True)
        self._set_state(self.ent_dur, True)
        self._set_state(self.cb_pwr, True) 
        self._set_state(self.ent_vol, True) 
        
        self.lbl_dur.config(text="Duration (min):")
        self.lbl_pwr.config(text="Watts:")
        self._set_state(self.btn_additions, True)
        
        self.ent_dur.pack(fill='x', expand=True)
        self.frm_delay.pack_forget()

        # REMOVED DELAYED_START BLOCK HERE

        if t == StepType.BOIL:
            self._set_state(self.ent_temp, True)
            if self.var_temp.get() == "":
                is_metric = UnitUtils.is_metric(self.settings)
                self.var_temp.set("100" if is_metric else "212")
            
        elif t == StepType.CHILL:
            self._set_state(self.cb_pwr, False)
            self.var_power.set("")

    def _set_state(self, widget, enabled):
        state = '!disabled' if enabled else 'disabled'
        widget.state([state])

    def _add_step(self):
        self._save_current_edit()
        new_step = BrewStep(name="New Step")
        self.steps_working_copy.append(new_step)
        self._refresh_step_list()
        new_idx = len(self.steps_working_copy) - 1
        self._select_visual_row_by_step_index(new_idx)

    def _delete_step(self):
        if self.current_step_index is None: return
        if not (0 <= self.current_step_index < len(self.steps_working_copy)): return
        
        self.steps_working_copy.pop(self.current_step_index)
        
        new_idx = None
        if self.steps_working_copy:
            new_idx = max(0, self.current_step_index - 1)
        
        self.current_step_index = None 
        self._refresh_step_list()
        self._toggle_form_state(False)
        
        if new_idx is not None:
             self._select_visual_row_by_step_index(new_idx)

    def _move_up(self):
        self._save_current_edit()
        if self.current_step_index is None or self.current_step_index == 0: return
        
        i = self.current_step_index
        self.steps_working_copy[i], self.steps_working_copy[i-1] = self.steps_working_copy[i-1], self.steps_working_copy[i]
        
        self._refresh_step_list()
        self._select_visual_row_by_step_index(i-1)

    def _move_down(self):
        self._save_current_edit()
        if self.current_step_index is None or self.current_step_index == len(self.steps_working_copy)-1: return
        
        i = self.current_step_index
        self.steps_working_copy[i], self.steps_working_copy[i+1] = self.steps_working_copy[i+1], self.steps_working_copy[i]
        
        self._refresh_step_list()
        self._select_visual_row_by_step_index(i+1)

    def _toggle_form_state(self, enabled):
        state = '!disabled' if enabled else 'disabled'
        for child in self.right_pane.winfo_children():
            try: child.state([state])
            except: pass 

    def _save_and_close(self):
        if not self._save_current_edit(): return
        
        try:
            self.profile.name = self.var_profile_name.get()
            self.profile.steps = self.steps_working_copy
            
            if self.on_save:
                self.on_save(self.profile)
            
            try:
                self.grab_release()
                if self.master:
                    self.master.focus_set()
            except:
                pass
            finally:
                self.destroy()
            
        except Exception as e:
            messagebox.showerror("Save Error", f"An error occurred while saving:\n{e}", parent=self)
            print(f"[ProfileEditor] Save Error: {e}")
