"""
Main module for the graphical user interface (GUI) of the MailSenderSystem.
Implements a Tkinter-based workbench for managing settings,
prompts, input files, and for controlling the research and mailing processes.
"""

from __future__ import annotations

import csv
import queue
import shutil
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk
from typing import Any, Sequence, cast

from gui.settings_store import (
    ENV_SCHEMA,
    PROJECT_ROOT,
    SETTINGS_SCHEMA,
    SettingSpec,
    coerce_value,
    load_env,
    load_settings,
    write_env,
    write_settings,
)
from mail_sender.prompts import load_prompts, save_prompts

HOVER_TEXTS = {
    "Reload": "Reload settings.toml and .env from disk.",
    "Load Config": "Load another settings TOML file into the Settings tab.",
    "Save Config As": "Write the current Settings tab to a new TOML file.",
    "Save All": "Write both settings.toml and .env now.",
    "Run Pipeline": "Run research and mail sending through code/main.py using the current settings.",
    "Research Only": "Run only the AI/self/Ollama research step.",
    "Mail Only": "Run only the mail sender for the currently selected mode.",
    "Stop": "Terminate the currently running subprocess.",
    "Refresh": "Refresh file lists, mail tables, and log lists from disk.",
    "Import CSV/TXT": "Copy a CSV or TXT lead file into the selected input mode folder.",
}

SENT_MAIL_TABS = (
    ("PhD", "PhD"),
    ("Freelance", "Freelance"),
    ("Invalid", "Invalid"),
)

MAIL_TEMPLATE_FILES = (
    ("PhD", "templates/phd.txt"),
    ("PhD spam-safe", "templates/phd_spam_safe.txt"),
    ("Freelance German", "templates/freelance_german.txt"),
    ("Freelance German spam-safe", "templates/freelance_german_spam_safe.txt"),
    ("Freelance English", "templates/freelance_english.txt"),
    ("Freelance English spam-safe", "templates/freelance_english_spam_safe.txt"),
    ("Signature", "templates/signature.txt"),
)


def _create_variable(spec: SettingSpec, source: dict[str, Any]) -> tk.Variable:
    """
    Creates an appropriate Tkinter variable (BooleanVar, IntVar, etc.) based
    on the setting specification.
    """
    value = source.get(spec.key, spec.default)
    if spec.kind == "bool":
        return tk.BooleanVar(value=bool(value))
    if spec.kind == "int":
        val = 0
        raw_val = value if value is not None else spec.default
        if isinstance(raw_val, (int, float, str)):
            try:
                val = int(raw_val)
            except (ValueError, TypeError):
                pass
        return tk.IntVar(value=val)
    if spec.kind == "float":
        val = 0.0
        raw_val = value if value is not None else spec.default
        if isinstance(raw_val, (int, float, str)):
            try:
                val = float(raw_val)
            except (ValueError, TypeError):
                pass
        return tk.DoubleVar(value=val)
    return tk.StringVar(value=str(value if value is not None else spec.default or ""))


def _make_tree(parent: tk.Widget, columns: tuple[str, ...]) -> ttk.Treeview:
    """
    Helper function to create a configured table view (Treeview).
    """
    tree = ttk.Treeview(parent, columns=columns, show="headings")
    for column in columns:
        tree.heading(column, text=column)
        tree.column(column, width=180 if column != "source_url" else 320, anchor="w")
    tree.pack(fill="both", expand=True)
    return tree


class MailSenderWorkbench:
    """
    The main class of the application, managing the window and all tabs.
    Provides functions for loading/saving configurations, displaying logs,
    and executing background processes.
    """

    PALETTE = {
        "window_bg": "#eef5ff",
        "surface": "#ffffff",
        "surface_alt": "#e6f0ff",
        "border": "#b9d3f2",
        "text": "#09213f",
        "muted": "#486581",
        "accent": "#0b66c3",
        "accent_active": "#084f96",
        "navy": "#06213f",
        "danger": "#ef4444",
        "success": "#12b76a",
        "warning": "#f79009",
    }

    def __init__(self, root: tk.Tk | None = None, *, project_root: Path = PROJECT_ROOT) -> None:
        """
        Initializes the main window, loads settings, and builds the UI.

        Args:
            root (tk.Tk | None): Optional root window.
            project_root (Path): The project root directory.
        """
        self.root = root or tk.Tk()
        self.project_root = project_root
        self.settings_path = project_root / "settings.toml"
        self.env_path = project_root / ".env"
        self.values = load_settings(self.settings_path)
        self.env_values = load_env(self.env_path)
        self.variables: dict[str, tk.Variable] = {}
        self.env_variables: dict[str, tk.Variable] = {}
        self.text_widgets: dict[str, tk.Text] = {}
        self.env_text_widgets: dict[str, tk.Text] = {}
        self.setting_search_vars: dict[str, tk.StringVar] = {}
        self.setting_search_counts: dict[str, tk.StringVar] = {}
        self.setting_row_widgets: dict[str, list[dict[str, Any]]] = {"settings": [], "env": []}
        self.setting_section_widgets: dict[str, list[dict[str, Any]]] = {"settings": [], "env": []}
        self.keyword_text: tk.Text | None = None
        self.compact_save = tk.BooleanVar(value=False)
        self.autosave = tk.BooleanVar(value=True)
        self.process: subprocess.Popen[str] | None = None
        self.message_queue: queue.Queue[tuple[str, str]] = queue.Queue()
        self.current_view_path: Path | None = None
        self.current_view_kind: str | None = None
        self._last_prompt_mode: str | None = None
        self._last_mail_template: str | None = None
        self._save_after_id: str | None = None
        self._loading = True
        self._autosave_after_id: str | None = None
        self._autosave_target = "all"
        self.auto_refresh = tk.BooleanVar(value=True)
        self.prompts = load_prompts(self.project_root / "prompts.toml")
        self.mail_templates = self._load_mail_templates()
        self.root.title("MailSenderSystem Workbench")
        self.root.geometry("1220x780")
        self.root.configure(bg=self.PALETTE["window_bg"])
        self._configure_styles()
        self._build_shell()
        self._load_form_values()
        self._load_env_values()
        self._loading = False
        self.refresh_tables()
        self.root.after(5000, self._auto_refresh_tick, None)
        self.root.after(100, self._drain_queue, None)

    def run(self) -> None:
        """
        Starts the Tkinter main loop.
        """
        self.root.mainloop()

    def _configure_styles(self) -> None:
        """
        Configures the visual styles (colors, padding, fonts) for all ttk widgets.
        """
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("TFrame", background=self.PALETTE["window_bg"])
        style.configure("Surface.TFrame", background=self.PALETTE["surface"], relief="solid", borderwidth=1)
        style.configure("TLabel", background=self.PALETTE["window_bg"], foreground=self.PALETTE["text"])
        style.configure("Muted.TLabel", foreground=self.PALETTE["muted"])
        style.configure(
            "TButton",
            padding=(12, 7),
            background=self.PALETTE["surface"],
            foreground=self.PALETTE["text"],
            bordercolor=self.PALETTE["border"],
            lightcolor=self.PALETTE["surface"],
            darkcolor=self.PALETTE["border"],
            focuscolor=self.PALETTE["accent"],
        )
        style.map(
            "TButton",
            background=[("active", self.PALETTE["surface_alt"]), ("pressed", "#d7eaff")],
            foreground=[("disabled", self.PALETTE["muted"])],
        )
        style.configure("Accent.TButton", background=self.PALETTE["accent"], foreground="#ffffff")
        style.map("Accent.TButton", background=[("active", self.PALETTE["accent_active"])])
        style.configure("Danger.TButton", background=self.PALETTE["danger"], foreground="#ffffff")
        style.map("Danger.TButton", background=[("active", "#d42f2f")])
        style.configure(
            "TNotebook",
            background=self.PALETTE["window_bg"],
            bordercolor=self.PALETTE["border"],
            tabmargins=(4, 4, 4, 0),
        )
        style.configure(
            "TNotebook.Tab",
            background=self.PALETTE["surface_alt"],
            foreground=self.PALETTE["text"],
            padding=(14, 8),
            bordercolor=self.PALETTE["border"],
            lightcolor=self.PALETTE["surface_alt"],
            darkcolor=self.PALETTE["border"],
        )
        style.map(
            "TNotebook.Tab",
            background=[("selected", self.PALETTE["accent"]), ("active", "#d7eaff")],
            foreground=[("selected", "#ffffff"), ("active", self.PALETTE["text"])],
        )
        style.configure(
            "TLabelframe",
            background=self.PALETTE["surface"],
            bordercolor=self.PALETTE["border"],
            lightcolor=self.PALETTE["surface"],
            darkcolor=self.PALETTE["border"],
        )
        style.configure(
            "TLabelframe.Label",
            background=self.PALETTE["surface"],
            foreground=self.PALETTE["accent_active"],
            font=("Segoe UI", 10, "bold"),
        )
        style.configure("TCheckbutton", background=self.PALETTE["window_bg"], foreground=self.PALETTE["text"])
        style.map("TCheckbutton", background=[("active", self.PALETTE["window_bg"])])
        style.configure("TEntry", fieldbackground=self.PALETTE["surface"], foreground=self.PALETTE["text"])
        style.configure("TCombobox", fieldbackground=self.PALETTE["surface"], foreground=self.PALETTE["text"])
        style.map("TCombobox", fieldbackground=[("readonly", self.PALETTE["surface"])])
        style.configure("Horizontal.TScale", background=self.PALETTE["surface"], troughcolor="#d7eaff")
        style.configure(
            "Treeview",
            rowheight=26,
            background=self.PALETTE["surface"],
            fieldbackground=self.PALETTE["surface"],
            foreground=self.PALETTE["text"],
            bordercolor=self.PALETTE["border"],
        )
        style.configure("Treeview.Heading", background=self.PALETTE["surface_alt"], foreground=self.PALETTE["text"])
        style.configure("Status.TLabel", background=self.PALETTE["surface_alt"], foreground=self.PALETTE["muted"])
        style.configure("Header.TFrame", background=self.PALETTE["navy"])
        style.configure("Header.TLabel", background=self.PALETTE["navy"], foreground="#ffffff")

    def _build_shell(self) -> None:
        """
        Creates the shell of the UI including header, toolbar, tabs, and status bar.
        """
        header = ttk.Frame(self.root, padding=(18, 14, 18, 10), style="Header.TFrame")
        header.pack(fill="x")
        ttk.Label(header, text="MailSenderSystem", font=("Segoe UI", 18, "bold"), style="Header.TLabel").pack(side="left")
        ttk.Label(header, text=f"Settings: {self.settings_path}", style="Header.TLabel").pack(side="left", padx=(16, 0))

        actions = ttk.Frame(header)
        actions.pack(side="right")
        self._toolbar_button(actions, "Reload", self.reload_settings)
        self._toolbar_button(actions, "Load Config", self.load_config_file)
        self._toolbar_button(actions, "Save Config As", self.save_config_file)
        self._toolbar_button(actions, "Save All", self.save_all, style="Accent.TButton")
        self._toolbar_button(actions, "Run Pipeline", lambda: self.start_process(["code/main.py"]))
        self._toolbar_button(actions, "Research Only", lambda: self.start_process(["code/research/research_leads.py"]))
        self._toolbar_button(actions, "Mail Only", self.start_mail_only)
        self._toolbar_button(actions, "Stop", self.stop_process, style="Danger.TButton")

        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill="both", expand=True, padx=16, pady=(0, 16))
        self.settings_tab = ttk.Frame(self.notebook, padding=12)
        self.env_tab = ttk.Frame(self.notebook, padding=12)
        self.prompts_tab = ttk.Frame(self.notebook, padding=12)
        self.mail_templates_tab = ttk.Frame(self.notebook, padding=12)
        self.inputs_tab = ttk.Frame(self.notebook, padding=12)
        self.found_tab = ttk.Frame(self.notebook, padding=12)
        self.sent_tab = ttk.Frame(self.notebook, padding=12)
        self.logs_tab = ttk.Frame(self.notebook, padding=12)
        self.console_tab = ttk.Frame(self.notebook, padding=12)
        self.notebook.add(self.settings_tab, text="Settings")
        self.notebook.add(self.env_tab, text=".env")
        self.notebook.add(self.prompts_tab, text="Prompts")
        self.notebook.add(self.mail_templates_tab, text="Mail Templates")
        self.notebook.add(self.inputs_tab, text="AI Inputs")
        self.notebook.add(self.found_tab, text="Found Mails")
        self.notebook.add(self.sent_tab, text="Sent Mails")
        self.notebook.add(self.logs_tab, text="Saved Logs")
        self.notebook.add(self.console_tab, text="Run Console")
        self._build_settings_tab()
        self._build_env_tab()
        self._build_prompts_tab()
        self._build_mail_templates_tab()
        self._build_inputs_tab()
        self._build_found_tab()
        self._build_sent_tab()
        self._build_logs_tab()
        self._build_console_tab()
        self.status_var = tk.StringVar(value="Ready.")
        ttk.Label(self.root, textvariable=self.status_var, style="Status.TLabel", padding=(16, 5)).pack(fill="x", side="bottom")

    def _toolbar_button(self, parent: ttk.Frame, text: str, command, *, style: str = "TButton") -> ttk.Button:
        """
        Creates a button for the toolbar with hover text.
        """
        button = ttk.Button(parent, text=text, command=command, style=style)
        button.pack(side="left", padx=4)
        self._attach_hover(button, HOVER_TEXTS.get(text, text))
        return button

    def _on_enter(self, text: str) -> None:
        """
        Called when the mouse enters a widget; updates the status bar.
        """
        if hasattr(self, "status_var") and self.status_var:
            self.status_var.set(text)

    def _on_leave(self) -> None:
        """
        Called when the mouse leaves a widget; resets the status bar.
        """
        if hasattr(self, "status_var") and self.status_var:
            self.status_var.set("Ready.")

    def _attach_hover(self, widget: tk.Widget, text: str) -> None:
        """
        Attaches enter/leave events of a widget to the status bar display.
        """
        widget.bind("<Enter>", lambda _e: self._on_enter(text))
        widget.bind("<Leave>", lambda _e: self._on_leave())

    def _build_settings_tab(self) -> None:
        """
        Builds the tab for general settings (settings.toml).
        """
        top = ttk.Frame(self.settings_tab)
        top.pack(fill="x", pady=(0, 10))
        self._build_setting_search_controls(top, "settings", "Search settings")
        ttk.Checkbutton(top, text="Auto-save changes directly", variable=self.autosave).pack(side="left", padx=(18, 0))
        ttk.Checkbutton(top, text="Auto-refresh tables", variable=self.auto_refresh).pack(side="left", padx=(18, 0))

        body = self._scrollable_body(self.settings_tab)

        self._build_settings_sections(body, SETTINGS_SCHEMA)

    def _build_env_tab(self) -> None:
        """
        Builds the tab for secrets (.env).
        """
        top = ttk.Frame(self.env_tab)
        top.pack(fill="x", pady=(0, 10))
        ttk.Label(top, text=f".env: {self.env_path}", style="Muted.TLabel").pack(side="left")
        self._build_setting_search_controls(top, "env", "Search .env", padx=(18, 0))
        body = self._scrollable_body(self.env_tab)
        self._build_settings_sections(body, ENV_SCHEMA, env=True)

    def _build_setting_search_controls(
            self,
            parent: ttk.Frame,
            target: str,
            placeholder: str,
            *,
            padx: tuple[int, int] = (0, 0),
    ) -> None:
        """Creates search controls for settings-style tabs."""
        wrapper = ttk.Frame(parent)
        wrapper.pack(side="left", padx=padx)
        ttk.Label(wrapper, text=placeholder).pack(side="left", padx=(0, 6))

        search_var = tk.StringVar()
        self.setting_search_vars[target] = search_var
        entry = ttk.Entry(wrapper, textvariable=search_var, width=28)
        entry.pack(side="left")
        self._attach_hover(entry, "Filters by setting key, label, section, and help text.")
        search_var.trace_add("write", lambda *_args, search_target=target: self._apply_setting_search(search_target))

        ttk.Button(wrapper, text="Clear", command=lambda: search_var.set("")).pack(side="left", padx=(6, 0))
        count_var = tk.StringVar(value="")
        self.setting_search_counts[target] = count_var
        ttk.Label(wrapper, textvariable=count_var, style="Muted.TLabel").pack(side="left", padx=(8, 0))

    def _build_settings_sections(
            self,
            body: ttk.Frame,
            schema: Sequence[SettingSpec],
            *,
            env: bool = False,
            column_count: int = 2,
    ) -> None:
        """Arranges setting groups in balanced columns."""
        target = "env" if env else "settings"
        self.setting_row_widgets[target] = []
        self.setting_section_widgets[target] = []
        sections: dict[str, list[SettingSpec]] = {}
        for spec in schema:
            sections.setdefault(spec.section, []).append(spec)

        columns = []
        weights = [0] * column_count
        for index in range(column_count):
            column = ttk.Frame(body)
            column.grid(row=0, column=index, sticky="nsew", padx=8)
            body.columnconfigure(index, weight=1, uniform="settings")
            columns.append(column)

        for section, specs in sections.items():
            target_column = weights.index(min(weights))
            frame = ttk.LabelFrame(columns[target_column], text=section, padding=12)
            frame.pack(fill="x", expand=False, pady=8)
            section_entry: dict[str, Any] = {"frame": frame, "section": section, "rows": []}
            self.setting_section_widgets[target].append(section_entry)
            for row, spec in enumerate(specs):
                row_widget = self._add_setting_row(frame, row, spec, env=env)
                row_entry = {
                    "widget": row_widget,
                    "section": section_entry,
                    "key": spec.key,
                    "visible": True,
                    "search_text": " ".join(
                        [section, spec.key, spec.label, spec.kind, spec.help_text, *spec.choices]
                    ).lower(),
                }
                self.setting_row_widgets[target].append(row_entry)
                section_entry["rows"].append(row_entry)
            weights[target_column] += _settings_section_weight(specs)
        self._apply_setting_search(target)

    def _scrollable_body(self, parent: ttk.Frame) -> ttk.Frame:
        """
        Creates a scrollable area within a frame.
        """
        canvas = tk.Canvas(parent, borderwidth=0, highlightthickness=0, background=self.PALETTE["window_bg"])
        scrollbar = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        body = ttk.Frame(canvas, style="TFrame")
        body.bind("<Configure>", lambda _event: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=body, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        return body

    def _add_setting_row(self, parent: tk.Widget, row: int, spec: SettingSpec, *, env: bool = False) -> tk.Widget:
        """
        Adds a single setting row (label + widget) to the UI.
        Supports checkboxes, sliders, choice menus, and text fields.
        """
        row_frame = ttk.Frame(parent)
        row_frame.grid(row=row, column=0, sticky="ew")
        ttk.Label(row_frame, text=spec.label).grid(row=0, column=0, sticky="w", padx=(0, 10), pady=5)

        var = _create_variable(spec, self.env_values if env else self.values)
        variables = self.env_variables if env else self.variables
        variables[spec.key] = var

        var.trace_add("write", lambda *_args, target="env" if env else "settings": self._schedule_autosave(target))
        widget: tk.Widget
        if spec.kind == "bool":
            widget = ttk.Checkbutton(row_frame, variable=var)
        elif spec.kind == "choice":
            state = "normal" if spec.key == "RESEARCH_MODEL" else "readonly"
            widget = ttk.Combobox(row_frame, textvariable=var, values=spec.choices, state=state, width=28)
        elif spec.kind in {"int", "float"} and spec.slider and spec.min_value is not None and spec.max_value is not None:
            wrapper = ttk.Frame(row_frame)
            entry_var = tk.StringVar(value=str(var.get()))
            updating = {"active": False}

            def sync_entry(*_args, source_var=var, target_var=entry_var, integer=spec.kind == "int") -> None:
                """Mirrors slider changes into the adjacent text entry field."""
                if updating["active"]:
                    return
                updating["active"] = True
                value = source_var.get()
                text_val = str(int(value)) if integer else str(round(float(value), 2))
                target_var.set(text_val)
                updating["active"] = False

            def sync_slider(*_args, source_var=entry_var, target_var=var, setting=spec) -> None:
                """Applies manual entries from the text field to the slider value."""
                if updating["active"]:
                    return
                raw = source_var.get().strip()
                if raw in {"", "-", "."}:
                    return
                try:
                    parsed = float(raw)
                except ValueError:
                    return
                if setting.min_value is not None:
                    parsed = max(float(setting.min_value), parsed)
                if setting.max_value is not None:
                    parsed = min(float(setting.max_value), parsed)
                updating["active"] = True
                var_val = int(parsed) if setting.kind == "int" else parsed
                target_var.set(var_val)
                updating["active"] = False
                self._schedule_autosave("env" if env else "settings")

            var.trace_add("write", sync_entry)
            entry_var.trace_add("write", sync_slider)
            scale_kwargs = {
                "from_": spec.min_value,
                "to": spec.max_value,
                "orient": "horizontal",
            }
            if spec.kind == "int":
                int_var = cast(tk.IntVar, var)
                scale = ttk.Scale(
                    wrapper,
                    variable=int_var,
                    command=lambda value: int_var.set(int(float(value))),
                    **scale_kwargs,
                )
            else:
                scale = ttk.Scale(
                    wrapper,
                    variable=cast(tk.DoubleVar, var),
                    **scale_kwargs,
                )
            scale.pack(side="left", fill="x", expand=True)
            value_entry = ttk.Entry(wrapper, textvariable=entry_var, width=8, justify="right")
            value_entry.pack(side="right", padx=(8, 0))
            widget = wrapper
        elif spec.kind == "list":
            text = tk.Text(row_frame, height=5, width=46, wrap="word")
            self._style_text_widget(text)
            (self.env_text_widgets if env else self.text_widgets)[spec.key] = text
            if spec.key == "SELF_SEARCH_KEYWORDS":
                self.keyword_text = text
            autosave_target = "env" if env else "settings"

            def schedule_text_autosave(_event: tk.Event) -> None:
                """Schedules autosave for multi-line entry fields."""
                self._schedule_autosave(autosave_target)

            text.bind("<KeyRelease>", schedule_text_autosave)
            text.bind("<FocusOut>", schedule_text_autosave)
            widget = text
        else:
            show = "*" if any(secret in spec.key.lower() for secret in ("password", "api_key", "token", "secret")) else ""
            widget = ttk.Entry(row_frame, textvariable=var, width=32, show=show)
        widget.grid(row=0, column=1, sticky="ew", pady=5)
        self._attach_hover(widget, f"{spec.key}: {spec.help_text}")
        help_label = ttk.Label(row_frame, text=spec.help_text, style="Muted.TLabel", wraplength=360)
        help_label.grid(row=0, column=2, sticky="w", padx=(12, 0))
        self._attach_hover(help_label, f"{spec.key}: {spec.help_text}")
        row_frame.columnconfigure(1, weight=1)
        parent.columnconfigure(0, weight=1)
        return row_frame

    def _apply_setting_search(self, target: str) -> None:
        """Filters setting rows for the selected settings-style tab."""
        rows = self.setting_row_widgets.get(target, [])
        if not rows:
            return

        query = self.setting_search_vars.get(target, tk.StringVar()).get().strip().lower()
        tokens = [token for token in query.split() if token]
        visible_count = 0

        for row in rows:
            visible = all(token in row["search_text"] for token in tokens)
            row["visible"] = visible
            if visible:
                row["widget"].grid()
                visible_count += 1
            else:
                row["widget"].grid_remove()

        sections = self.setting_section_widgets.get(target, [])
        for section in sections:
            section["frame"].pack_forget()

        for section in sections:
            section_visible = any(row["visible"] for row in section["rows"])
            frame = section["frame"]
            if section_visible:
                frame.pack(fill="x", expand=False, pady=8)

        count_var = self.setting_search_counts.get(target)
        if count_var is not None:
            total = len(rows)
            count_var.set(f"{visible_count}/{total}" if tokens else "")

    def _build_prompts_tab(self) -> None:
        """
        Builds the tab for editing AI prompts.
        Includes mode selection and text editor for templates.
        """
        top = ttk.Frame(self.prompts_tab)
        top.pack(fill="x", pady=(0, 10))

        ttk.Label(top, text="Select Mode:").pack(side="left", padx=(0, 10))

        self.prompt_mode_var = tk.StringVar()
        modes = list(self.prompts.keys())
        self.prompt_mode_combo = ttk.Combobox(
            top, textvariable=self.prompt_mode_var, values=modes, state="readonly", width=25
        )
        self.prompt_mode_combo.pack(side="left")
        self.prompt_mode_combo.bind("<<ComboboxSelected>>", self._on_prompt_mode_change)

        self.prompt_info_var = tk.StringVar()
        ttk.Label(top, textvariable=self.prompt_info_var, style="Muted.TLabel").pack(side="left", padx=(20, 0))

        if modes:
            self.prompt_mode_var.set(modes[0])

        self.prompt_text = scrolledtext.ScrolledText(self.prompts_tab, wrap="word", undo=True, font=("Consolas", 10))
        self.prompt_text.pack(fill="both", expand=True, pady=10)
        self._style_text_widget(self.prompt_text)

        bottom = ttk.Frame(self.prompts_tab)
        bottom.pack(fill="x")

        ttk.Button(bottom, text="Save Prompts", command=self.save_all_prompts, style="Accent.TButton").pack(side="right")
        ttk.Button(bottom, text="Reset current to Default", command=self._reset_current_prompt).pack(side="right", padx=10)

        self._on_prompt_mode_change()

    def _build_mail_templates_tab(self) -> None:
        """
        Builds the tab for editing the actual mail templates used for sending.
        """
        top = ttk.Frame(self.mail_templates_tab)
        top.pack(fill="x", pady=(0, 10))

        ttk.Label(top, text="Select Template:").pack(side="left", padx=(0, 10))

        self.mail_template_var = tk.StringVar()
        template_names = list(self.mail_templates.keys())
        self.mail_template_combo = ttk.Combobox(
            top,
            textvariable=self.mail_template_var,
            values=template_names,
            state="readonly",
            width=32,
        )
        self.mail_template_combo.pack(side="left")
        self.mail_template_combo.bind("<<ComboboxSelected>>", self._on_mail_template_change)

        self.mail_template_path_var = tk.StringVar()
        ttk.Label(top, textvariable=self.mail_template_path_var, style="Muted.TLabel").pack(side="left", padx=(20, 0))

        if template_names:
            self.mail_template_var.set(template_names[0])

        self.mail_template_text = scrolledtext.ScrolledText(
            self.mail_templates_tab,
            wrap="word",
            undo=True,
            font=("Consolas", 10),
        )
        self.mail_template_text.pack(fill="both", expand=True, pady=10)
        self._style_text_widget(self.mail_template_text)

        bottom = ttk.Frame(self.mail_templates_tab)
        bottom.pack(fill="x")
        ttk.Button(bottom, text="Save Mail Templates", command=self.save_mail_templates, style="Accent.TButton").pack(side="right")
        ttk.Button(bottom, text="Reload current from Disk", command=self._reload_current_mail_template).pack(side="right", padx=10)

        self._on_mail_template_change()

    def _load_mail_templates(self) -> dict[str, str]:
        """Reads all editable mail templates from disk."""
        templates: dict[str, str] = {}
        for label, relative_path in MAIL_TEMPLATE_FILES:
            path = self.project_root / relative_path
            if path.exists():
                templates[label] = path.read_text(encoding="utf-8", errors="replace").strip()
            else:
                templates[label] = ""
        return templates

    def _mail_template_path(self, label: str) -> Path:
        """Returns the file path for a mail template label."""
        mapping = dict(MAIL_TEMPLATE_FILES)
        return self.project_root / mapping[label]

    def _on_mail_template_change(self, _event=None) -> None:
        """Caches current mail-template text and loads the selected template."""
        if hasattr(self, "_last_mail_template") and self._last_mail_template:
            self.mail_templates[self._last_mail_template] = self.mail_template_text.get("1.0", tk.END).strip()

        label = self.mail_template_var.get()
        if not label:
            return

        self._last_mail_template = label
        path = self._mail_template_path(label)
        self.mail_template_path_var.set(str(path))
        self.mail_template_text.delete("1.0", tk.END)
        self.mail_template_text.insert("1.0", self.mail_templates.get(label, ""))

    def _on_prompt_mode_change(self, _event=None) -> None:
        """
        Called when a different prompt mode is selected.
        Caches the current text and loads the new content.
        """
        if hasattr(self, "_last_prompt_mode") and self._last_prompt_mode:
            self.prompts[self._last_prompt_mode] = self.prompt_text.get("1.0", tk.END).strip()

        mode = self.prompt_mode_var.get()
        if not mode:
            return

        if mode == "Overseer":
            info_text = (
                "Placeholders: {MODE_LABEL}, {TASK_INSTRUCTIONS}, {MIN_COMPANIES}, {MAX_COMPANIES}, "
                "{CONTACT_REQUIREMENT}, {EXCLUDED_EMAILS}, {EXCLUDED_COMPANIES}, {INPUT_CONTEXT}"
            )
            self.prompt_info_var.set(info_text)
        else:
            self.prompt_info_var.set("")

        self._last_prompt_mode = mode
        self.prompt_text.delete("1.0", tk.END)
        self.prompt_text.insert("1.0", self.prompts.get(mode, ""))

    def _build_inputs_tab(self) -> None:
        """
        Builds the tab for input files (leads).
        Allows viewing, editing, and deleting CSV/TXT files.
        """
        toolbar = ttk.Frame(self.inputs_tab)
        toolbar.pack(fill="x", pady=(0, 8))
        ttk.Label(toolbar, text="Mode").pack(side="left", padx=(0, 6))
        self.input_mode_var = tk.StringVar(value="PhD")
        mode_combo = ttk.Combobox(
            toolbar,
            textvariable=self.input_mode_var,
            values=("PhD", "Freelance_German", "Freelance_English"),
            state="readonly",
            width=22,
        )
        mode_combo.pack(side="left", padx=(0, 8))
        mode_combo.bind("<<ComboboxSelected>>", lambda _event: self.refresh_tables())
        self._toolbar_button(toolbar, "Refresh", self.refresh_tables)
        self._toolbar_button(toolbar, "Import CSV/TXT", self.import_input_file)
        self._toolbar_button(toolbar, "Delete Selected", self._delete_selected_input, style="Danger.TButton")

        pane = ttk.PanedWindow(self.inputs_tab, orient="horizontal")
        pane.pack(fill="both", expand=True)
        left = ttk.Frame(pane)
        right = ttk.Frame(pane)
        pane.add(left, weight=1)
        pane.add(right, weight=2)
        self.input_tree = _make_tree(left, ("file", "mode", "size"))
        self.input_tree.bind("<<TreeviewSelect>>", lambda _event: self._show_selected_file(self.input_tree, "input"))
        self.input_tree.bind("<Double-1>", lambda _event: self._show_selected_file(self.input_tree, "input"))
        self.file_view_title = tk.StringVar(value="Select a file to edit or preview.")
        ttk.Label(right, textvariable=self.file_view_title, font=("Segoe UI", 11, "bold")).pack(fill="x")
        self.file_viewer = scrolledtext.ScrolledText(right, height=22, wrap="none")
        self._style_text_widget(self.file_viewer)
        self.file_viewer.pack(fill="both", expand=True, pady=(8, 0))
        self.file_viewer.bind("<KeyRelease>", self._on_input_edit)

    def _build_found_tab(self) -> None:
        """
        Builds the tab for found leads (output/Found).
        Shows a tabular overview of research results.
        """
        toolbar = ttk.Frame(self.found_tab)
        toolbar.pack(fill="x", pady=(0, 8))
        self._toolbar_button(toolbar, "Refresh", self.refresh_tables)
        self.found_tree = _make_tree(self.found_tab, ("file", "mode", "company", "mail", "source_url"))
        self.found_tree.bind("<<TreeviewSelect>>", lambda _event: self._show_selected_file(self.found_tree, "found"))

    def _build_sent_tab(self) -> None:
        """
        Builds the tab for already sent emails.
        Subdivided into PhD, Freelance, and Invalid tabs.
        """
        toolbar = ttk.Frame(self.sent_tab)
        toolbar.pack(fill="x", pady=(0, 8))
        self._toolbar_button(toolbar, "Refresh", self.refresh_tables)
        self.sent_notebook = ttk.Notebook(self.sent_tab)
        self.sent_notebook.pack(fill="both", expand=True)
        self.sent_trees: dict[str, ttk.Treeview] = {}
        for tab_key, tab_label in SENT_MAIL_TABS:
            frame = ttk.Frame(self.sent_notebook, padding=4)
            self.sent_notebook.add(frame, text=tab_label)
            tree = _make_tree(frame, ("file", "company", "mail", "detail"))

            def show_sent_file(_event: tk.Event, selected_tree: ttk.Treeview = tree) -> None:
                """Opens the CSV file associated with the currently selected sending row."""
                self._show_selected_file(selected_tree, "sent")

            tree.bind("<<TreeviewSelect>>", show_sent_file)
            self.sent_trees[tab_key] = tree
        self.sent_tree = self.sent_trees["PhD"]

    def _build_logs_tab(self) -> None:
        """
        Builds the tab for run logs (history of console outputs).
        """
        toolbar = ttk.Frame(self.logs_tab)
        toolbar.pack(fill="x", pady=(0, 8))
        self._toolbar_button(toolbar, "Refresh", self.refresh_tables)
        self.log_tree = _make_tree(self.logs_tab, ("file", "modified", "size"))
        self.log_tree.bind("<<TreeviewSelect>>", lambda _event: self._show_selected_file(self.log_tree, "log"))
        self.log_tree.bind("<Double-1>", lambda _event: self.open_selected_log_tab())

    def _build_console_tab(self) -> None:
        """
        Builds the tab for the live console of the current process.
        """
        toolbar = ttk.Frame(self.console_tab)
        toolbar.pack(fill="x", pady=(0, 8))
        self._toolbar_button(toolbar, "Run Pipeline", lambda: self.start_process(["code/main.py"]))
        self._toolbar_button(toolbar, "Stop", self.stop_process)
        ttk.Button(toolbar, text="Clear", command=lambda: self.console.delete("1.0", "end")).pack(side="left", padx=4)
        self.console = scrolledtext.ScrolledText(self.console_tab, height=28, wrap="word")
        self._style_text_widget(self.console)
        self.console.pack(fill="both", expand=True)

    @staticmethod
    def _load_values(schema: Sequence[SettingSpec], source: dict[str, Any], variables: dict[str, tk.Variable], text_widgets: dict[str, tk.Text]) -> None:
        """
        Transfers values from a dictionary into the corresponding UI variables and text widgets.
        """
        for spec in schema:
            value = source.get(spec.key, spec.default)
            if spec.kind == "list" and spec.key in text_widgets:
                text_widgets[spec.key].delete("1.0", "end")
                text_widgets[spec.key].insert("1.0", "\n".join(value or []))
            elif spec.key in variables:
                variables[spec.key].set(value)

    def _load_form_values(self) -> None:
        """
        Loads settings.toml values into the form.
        """
        self._load_values(SETTINGS_SCHEMA, self.values, self.variables, self.text_widgets)

    def _load_env_values(self) -> None:
        """
        Loads .env values into the form.
        """
        self._load_values(ENV_SCHEMA, self.env_values, self.env_variables, self.env_text_widgets)

    @staticmethod
    def _collect_values(schema: Sequence[SettingSpec], variables: dict[str, tk.Variable], text_widgets: dict[str, tk.Text]) -> dict[str, Any]:
        """Collects values."""
        values: dict[str, Any] = {}
        for spec in schema:
            if spec.kind == "list" and spec.key in text_widgets:
                raw_value = text_widgets[spec.key].get("1.0", "end")
            else:
                raw_value = variables[spec.key].get()
            values[spec.key] = coerce_value(spec, raw_value)
        return values

    def collect_form_values(self) -> dict[str, Any]:
        """Collects form values."""
        return self._collect_values(SETTINGS_SCHEMA, self.variables, self.text_widgets)

    def collect_env_values(self) -> dict[str, Any]:
        """Collects environment values."""
        return self._collect_values(ENV_SCHEMA, self.env_variables, self.env_text_widgets)

    def save_all(self) -> None:
        """
        Saves both settings.toml and .env files immediately.
        """
        self.save_settings()
        self.save_env()
        self.save_all_prompts()
        self.save_mail_templates()

    def save_all_prompts(self) -> None:
        """
        Saves the currently edited prompt and writes all prompts to the file.
        """
        mode = self.prompt_mode_var.get()
        if mode:
            self.prompts[mode] = self.prompt_text.get("1.0", tk.END).strip()

        try:
            save_prompts(self.prompts, self.project_root / "prompts.toml")
        except OSError as exc:
            messagebox.showerror("Save failed", f"Failed to save prompts: {exc}")
            return

        self._append_console(f"[INFO] Saved prompts to {self.project_root / 'prompts.toml'}\n")
        if hasattr(self, "status_var") and self.status_var:
            self.status_var.set("Prompts saved successfully.")

    def save_mail_templates(self) -> None:
        """
        Saves the currently edited mail template and writes all mail templates to disk.
        """
        label = self.mail_template_var.get()
        if label:
            self.mail_templates[label] = self.mail_template_text.get("1.0", tk.END).strip()

        try:
            for template_label, text in self.mail_templates.items():
                path = self._mail_template_path(template_label)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text.rstrip() + "\n", encoding="utf-8")
        except OSError as exc:
            messagebox.showerror("Save failed", f"Failed to save mail templates: {exc}")
            return

        self._append_console(f"[INFO] Saved mail templates under {self.project_root / 'templates'}\n")
        if hasattr(self, "status_var") and self.status_var:
            self.status_var.set("Mail templates saved successfully.")

    def _reload_current_mail_template(self) -> None:
        """Reloads the selected mail template from disk."""
        label = self.mail_template_var.get()
        if not label:
            return
        path = self._mail_template_path(label)
        text = path.read_text(encoding="utf-8", errors="replace").strip() if path.exists() else ""
        self.mail_templates[label] = text
        self.mail_template_text.delete("1.0", tk.END)
        self.mail_template_text.insert("1.0", text)
        if hasattr(self, "status_var") and self.status_var:
            self.status_var.set(f"Reloaded {label}.")

    def _reset_current_prompt(self) -> None:
        """Resets the currently selected prompt to the built-in default."""
        from mail_sender.prompts import DEFAULT_PROMPTS

        mode = self.prompt_mode_var.get()
        if mode and mode in DEFAULT_PROMPTS:
            if messagebox.askyesno("Reset Prompt", f"Are you sure you want to reset the prompt for '{mode}' to its default?"):
                self.prompt_text.delete("1.0", tk.END)
                self.prompt_text.insert("1.0", DEFAULT_PROMPTS[mode])
                if hasattr(self, "status_var") and self.status_var:
                    self.status_var.set(f"Reset prompt for {mode} to default.")

    def save_settings(self) -> None:
        """Saves settings."""
        try:
            write_settings(self.settings_path, self.collect_form_values(), omit_defaults=self.compact_save.get())
        except OSError as exc:
            messagebox.showerror("Save failed", str(exc))
            return
        self._append_console(f"[INFO] Saved settings to {self.settings_path}\n")

    def save_env(self) -> None:
        """Saves environment values."""
        try:
            write_env(self.env_path, self.collect_env_values())
        except OSError as exc:
            messagebox.showerror("Save failed", str(exc))
            return
        self._append_console(f"[INFO] Saved .env to {self.env_path}\n")

    def reload_settings(self) -> None:
        """Reloads settings.toml, .env, and prompt data from disk."""
        self._loading = True
        self.values = load_settings(self.settings_path)
        self.env_values = load_env(self.env_path)
        self.prompts = load_prompts(self.project_root / "prompts.toml")
        self.mail_templates = self._load_mail_templates()
        self._last_prompt_mode = None
        self._last_mail_template = None
        self._load_form_values()
        self._load_env_values()
        self._on_prompt_mode_change()
        self._on_mail_template_change()
        self._loading = False
        self._append_console("[INFO] Reloaded settings.toml, .env, prompts.toml and mail templates\n")

    def load_config_file(self) -> None:
        """
        Opens a dialog to load an external TOML configuration file.
        """
        selected = filedialog.askopenfilename(
            title="Load settings TOML",
            initialdir=str(self.project_root),
            filetypes=[("TOML files", "*.toml"), ("All files", "*.*")],
        )
        if not selected:
            return
        self.settings_path = Path(selected)
        self.values = load_settings(self.settings_path)
        self._load_form_values()
        self._append_console(f"[INFO] Loaded settings config: {self.settings_path}\n")

    def save_config_file(self) -> None:
        """
        Opens a dialog to save the current settings to a new file.
        """
        selected = filedialog.asksaveasfilename(
            title="Save settings TOML",
            initialdir=str(self.project_root),
            defaultextension=".toml",
            filetypes=[("TOML files", "*.toml"), ("All files", "*.*")],
        )
        if not selected:
            return
        write_settings(Path(selected), self.collect_form_values(), omit_defaults=self.compact_save.get())
        self._append_console(f"[INFO] Saved settings config: {selected}\n")

    def refresh_tables(self) -> None:
        """
        Updates all list views (files, mails, logs) by re-reading the directories.
        """
        if hasattr(self, "found_tree"):
            self._refresh_found_mails()
        if hasattr(self, "sent_tree"):
            self._refresh_sent_mails()
        if hasattr(self, "input_tree"):
            self._refresh_input_files()
        if hasattr(self, "log_tree"):
            self._refresh_logs()

    def _refresh_sent_mails(self) -> None:
        """Updates sent entries mails."""
        for tree in self.sent_trees.values():
            tree.delete(*tree.get_children())
        output_dir = self.project_root / "output"
        for path in sorted(output_dir.glob("*.csv")) if output_dir.exists() else []:
            mode_name = _mode_from_output_filename(path.name)
            tree = self.sent_trees.get(mode_name, self.sent_trees["Freelance"])
            try:
                with path.open(newline="", encoding="utf-8-sig") as handle:
                    for row in csv.DictReader(handle):
                        tree.insert("", "end", values=(
                            path.name,
                            row.get("company", ""),
                            row.get("mail", row.get("email", "")),
                            _sent_row_detail(mode_name, row),
                        ))
            except OSError:
                continue

    def _refresh_found_mails(self) -> None:
        """Updates found mails."""
        self.found_tree.delete(*self.found_tree.get_children())
        input_dir = self.project_root / "input"
        for path in sorted(input_dir.glob("*/*.csv")) if input_dir.exists() else []:
            try:
                with path.open(newline="", encoding="utf-8-sig") as handle:
                    for row in csv.DictReader(handle):
                        self.found_tree.insert("", "end", values=(
                            path.name,
                            path.parent.name,
                            row.get("company", ""),
                            row.get("mail", row.get("email", "")),
                            row.get("source_url", row.get("source", "")),
                        ))
            except OSError:
                continue

    def _refresh_input_files(self) -> None:
        """Updates input files."""
        self.input_tree.delete(*self.input_tree.get_children())
        input_dir = self.project_root / "input"
        selected_mode = self.input_mode_var.get()
        modes = [selected_mode] if selected_mode else ["PhD", "Freelance_German", "Freelance_English"]
        for mode in modes:
            mode_dir = input_dir / mode
            for path in sorted(mode_dir.glob("*")) if mode_dir.exists() else []:
                if path.is_file() and path.suffix.lower() in {".csv", ".txt"}:
                    self.input_tree.insert("", "end", values=(path.name, mode, path.stat().st_size), tags=(str(path),))

    def import_input_file(self) -> None:
        """Imports input file."""
        selected = filedialog.askopenfilename(
            title="Import lead CSV/TXT",
            initialdir=str(self.project_root),
            filetypes=[("Lead files", "*.csv *.txt"), ("All files", "*.*")],
        )
        if not selected:
            return
        source = Path(selected)
        target_dir = self.project_root / "input" / self.input_mode_var.get()
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / source.name
        shutil.copy2(source, target)
        self._append_console(f"[INFO] Imported {source} -> {target}\n")
        self.refresh_tables()

    def _show_selected_file(self, tree: ttk.Treeview, kind: str) -> None:
        """Displays the file of the currently selected table row in the editor."""
        selection = tree.selection()
        if not selection:
            return
        item = tree.item(selection[0])
        values = list(item.get("values", []))
        path = self._path_for_tree_row(kind, values)
        if path is None or not path.exists() or not hasattr(self, "file_viewer"):
            return
        self.current_view_path = path
        self.current_view_kind = kind
        self.file_view_title.set(str(path))
        try:
            text = path.read_text(encoding="utf-8-sig", errors="replace")
        except OSError as exc:
            text = f"Could not read file: {exc}"

        self.file_viewer.config(state="normal")
        self.file_viewer.delete("1.0", "end")
        self.file_viewer.insert("1.0", text)

        if kind != "input":
            self.file_viewer.config(state="disabled")
        else:
            self.file_viewer.config(state="normal")

    def _on_input_edit(self, _event=None) -> None:
        """Reacts to the event for input edit."""
        if self._save_after_id:
            self.root.after_cancel(self._save_after_id)
        self._save_after_id = self.root.after(500, self._perform_input_save, None)

    def _perform_input_save(self, _=None) -> None:
        """Saves the current content of the input file editor."""
        self._save_after_id = None
        if self.current_view_kind != "input" or not self.current_view_path:
            return

        try:
            content = self.file_viewer.get("1.0", tk.END)
            # Remove last newline added by Tkinter Text widget
            if content.endswith("\n"):
                content = content[:-1]
            self.current_view_path.write_text(content, encoding="utf-8-sig")
        except (OSError, tk.TclError) as exc:
            self._append_console(f"[ERROR] Auto-save failed for {self.current_view_path.name}: {exc}\n")

    def _delete_selected_input(self) -> None:
        """Deletes selected input."""
        selection = self.input_tree.selection()
        if not selection:
            messagebox.showinfo("No Selection", "Please select an input file to delete.")
            return

        item = self.input_tree.item(selection[0])
        values = list(item.get("values", []))
        path = self._path_for_tree_row("input", values)

        if not path or not path.exists():
            messagebox.showerror("Error", "File not found.")
            return

        if path.name == ".gitkeep":
            messagebox.showwarning("Warning", "Cannot delete .gitkeep file.")
            return

        if messagebox.askyesno("Confirm Delete", f"Are you sure you want to delete '{path.name}'?"):
            try:
                path.unlink()
                self._append_console(f"[INFO] Deleted {path}\n")
                if hasattr(self, "current_view_path") and self.current_view_path == path:
                    self.file_viewer.config(state="normal")
                    self.file_viewer.delete("1.0", tk.END)
                    self.file_view_title.set("Select a file to edit or preview.")
                    self.current_view_path = None
                self.refresh_tables()
            except OSError as exc:
                messagebox.showerror("Error", f"Could not delete file: {exc}")

    def _path_for_tree_row(self, kind: str, values: list[Any]) -> Path | None:
        """Determines the file path belonging to the selected table row."""
        if not values:
            return None
        filename = str(values[0])
        if kind in {"input", "found"} and len(values) >= 2:
            return self.project_root / "input" / str(values[1]) / filename
        if kind == "sent":
            return self.project_root / "output" / filename
        if kind == "log":
            log_dir_value = self.collect_form_values().get("VERBOSE_LOG_DIR", "logs")
            log_dir = Path(str(log_dir_value))
            if not log_dir.is_absolute():
                log_dir = self.project_root / log_dir
            return log_dir / filename
        return None

    def open_selected_log_tab(self) -> None:
        """Opens selected log data tab."""
        selection = self.log_tree.selection()
        if not selection:
            return
        path = self._path_for_tree_row("log", list(self.log_tree.item(selection[0]).get("values", [])))
        if path is None or not path.exists():
            return
        frame = ttk.Frame(self.notebook, padding=8)
        title = f"Log: {path.name}"
        toolbar = ttk.Frame(frame)
        toolbar.pack(fill="x", pady=(0, 8))
        ttk.Label(toolbar, text=str(path), style="Muted.TLabel").pack(side="left")

        def close_current_log_tab(tab: ttk.Frame = frame) -> None:
            """Schließt den gerade geöffneten Log-Reiter."""
            self.close_tab(tab)

        ttk.Button(toolbar, text="Close Log Tab", command=close_current_log_tab).pack(side="right")
        text = scrolledtext.ScrolledText(frame, wrap="word")
        self._style_text_widget(text)
        text.pack(fill="both", expand=True)
        text.insert("1.0", path.read_text(encoding="utf-8", errors="replace"))
        self.notebook.add(frame, text=title)
        self.notebook.select(frame)

    def close_tab(self, tab: ttk.Frame) -> None:
        """Schließt einen dynamisch geöffneten Datei- oder Log-Reiter."""
        self.notebook.forget(tab)

    def _refresh_logs(self) -> None:
        """Updates log data."""
        self.log_tree.delete(*self.log_tree.get_children())
        log_dir_value = self.collect_form_values().get("VERBOSE_LOG_DIR", "logs") if self.variables else "logs"
        log_dir = Path(str(log_dir_value))
        if not log_dir.is_absolute():
            log_dir = self.project_root / log_dir
        for path in sorted(log_dir.glob("*.log"), reverse=True) if log_dir.exists() else []:
            stat = path.stat()
            self.log_tree.insert("", "end", values=(path.name, _format_mtime(stat.st_mtime), stat.st_size))

    def start_process(self, script_args: list[str]) -> None:
        """
        Starts an external Python process (research or pipeline)
        and redirects the output to the console.
        """
        if self.process and self.process.poll() is None:
            messagebox.showwarning("Process running", "A process is already running.")
            return
        self.save_all()
        command = [sys.executable, *script_args]
        self._start_command(command)

    def start_mail_only(self) -> None:
        """Starts mail only."""
        self.save_all()
        command = self._mail_only_command()
        self._start_command(command)

    def _mail_only_command(self) -> list[str]:
        """Builds the command-line call for a pure mail sending run."""
        settings = self.collect_form_values()
        args = [
            sys.executable,
            "-c",
            "from mail_sender.cli import main; raise SystemExit(main())",
            "--mode",
            str(settings["MODE"]),
            "--base-dir",
            str(self.project_root),
            "--signature-logo",
            str(settings["SIGNATURE_LOGO"]),
            "--signature-logo-width",
            str(settings["SIGNATURE_LOGO_WIDTH"]),
            "--parallel-threads",
            str(settings["PARALLEL_THREADS"]),
            "--verify-email-smtp-timeout",
            str(settings["VERIFY_EMAIL_SMTP_TIMEOUT"]),
        ]
        for flag, key in [
            ("--send", "SEND"),
            ("--verbose", "VERBOSE"),
            ("--resend-existing", "RESEND_EXISTING"),
            ("--skip-invalid-check", "SKIP_INVALID_CHECK"),
            ("--allow-empty-attachments", "ALLOW_EMPTY_ATTACHMENTS"),
            ("--spam-safe", "SPAM_SAFE_MODE"),
            ("--log-dry-run", "LOG_DRY_RUN"),
            ("--delete-input-after-success", "DELETE_INPUT_AFTER_SUCCESS"),
            ("--verify-email-smtp", "VERIFY_EMAIL_SMTP"),
        ]:
            if settings[key]:
                args.append(flag)
        if not settings["SKIP_INVALID_CHECK"]:
            args.append("--no-skip-invalid-check")
        if not settings["WRITE_SENT_LOG"]:
            args.append("--no-write-sent-log")
        return args

    def _start_command(self, command: list[str]) -> None:
        """Starts command."""
        if self.process and self.process.poll() is None:
            messagebox.showwarning("Process running", "A process is already running.")
            return
        self._append_console(f"[INFO] Starting: {' '.join(command)}\n")
        self.process = subprocess.Popen(
            command,
            cwd=self.project_root,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        threading.Thread(target=self._read_process_output, daemon=True).start()

    def stop_process(self) -> None:
        """
        Terminates the currently running background process immediately (kill).
        """
        if self.process and self.process.poll() is None:
            self.process.kill()
            self._append_console("[INFO] Instant stop signal sent (SIGKILL).\n")

    def _read_process_output(self) -> None:
        """
        Internal thread method: Reads the standard output of the background process
        line by line and pushes it into the queue for display in the GUI.
        """
        assert self.process is not None
        assert self.process.stdout is not None
        for line in self.process.stdout:
            self.message_queue.put(("log", line))
        exit_code = self.process.wait()
        self.message_queue.put(("log", f"[INFO] Process exited with code {exit_code}\n"))
        self.message_queue.put(("refresh", ""))

    def _drain_queue(self, _=None) -> None:
        """Transfers output from the background process to the GUI console."""
        while True:
            try:
                kind, payload = self.message_queue.get_nowait()
            except queue.Empty:
                break
            if kind == "log":
                self._append_console(payload)
            elif kind == "refresh":
                self.refresh_tables()
        self.root.after(100, self._drain_queue, None)

    def _append_console(self, text: str) -> None:
        """Writes process output to the console."""
        if hasattr(self, "console") and self.console:
            self.console.insert("end", text)
            self.console.see("end")

    def _style_text_widget(self, widget: tk.Text) -> None:
        """Applies consistent colors and borders for text fields."""
        widget.configure(
            background=self.PALETTE["surface"],
            foreground=self.PALETTE["text"],
            insertbackground=self.PALETTE["accent"],
            relief="solid",
            borderwidth=1,
            highlightthickness=1,
            highlightbackground=self.PALETTE["border"],
            highlightcolor=self.PALETTE["accent"],
        )

    def _schedule_autosave(self, target: str = "all") -> None:
        """Schedules a delayed save so that entries do not write with every keystroke."""
        if self._loading or not self.autosave.get():
            return
        self._autosave_target = target
        if self._autosave_after_id is not None:
            self.root.after_cancel(self._autosave_after_id)
        self._autosave_after_id = self.root.after(500, self._autosave_now, None)

    def _autosave_now(self, _=None) -> None:
        """Saves the last changed settings immediately if autosave is active."""
        self._autosave_after_id = None
        if self._autosave_target == "settings":
            self.save_settings()
        elif self._autosave_target == "env":
            self.save_env()
        else:
            self.save_all()

    def _auto_refresh_tick(self, _=None) -> None:
        """Refreshes tables regularly as long as auto-refresh is enabled."""
        if self.auto_refresh.get():
            self.refresh_tables()
        self.root.after(5000, self._auto_refresh_tick, None)


def _format_mtime(timestamp: float) -> str:
    """
    Formats a file timestamp into a readable date/time format.
    """
    from datetime import datetime

    return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")


def _mode_from_output_filename(filename: str) -> str:
    """Derives the mailing mode from the name of an output CSV file."""
    normalized = filename.lower()
    if "invalid" in normalized:
        return "Invalid"
    if "phd" in normalized:
        return "PhD"
    if "freelance" in normalized or "english" in normalized or "german" in normalized:
        return "Freelance"
    return "Freelance"


def _sent_row_detail(mode_name: str, row: dict[str, str]) -> str:
    """Reads the relevant detail column for the GUI depending on the mailing list."""
    if mode_name == "Invalid":
        return row.get("invalid_reason", row.get("reason", ""))
    return row.get("source_url", row.get("source", ""))


def _settings_section_weight(specs: Sequence[SettingSpec]) -> int:
    """Estimates the visible height of a setting group for the column layout."""
    return sum(4 if spec.kind == "list" else 1 for spec in specs)


def main() -> int:
    """
    Main entry point for the GUI application.
    Initializes Tkinter and starts the workbench.
    """
    root = tk.Tk()
    app = MailSenderWorkbench(root)
    app.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
