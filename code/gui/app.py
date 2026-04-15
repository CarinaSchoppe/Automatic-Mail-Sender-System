from __future__ import annotations

import csv
import queue
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk
from typing import Any

from gui.settings_store import ENV_SCHEMA, PROJECT_ROOT, SETTINGS_SCHEMA, SettingSpec
from gui.settings_store import coerce_value, load_env, load_settings, write_env, write_settings


class MailSenderWorkbench:
    """Tkinter workbench for settings, run logs, and output inspection."""

    PALETTE = {
        "window_bg": "#f4f7fb",
        "surface": "#ffffff",
        "surface_alt": "#f7faff",
        "border": "#d9e4f0",
        "text": "#101828",
        "muted": "#63758c",
        "accent": "#5b6cff",
        "accent_active": "#4656e6",
        "danger": "#ef4444",
        "success": "#12b76a",
    }

    def __init__(self, root: tk.Tk | None = None, *, project_root: Path = PROJECT_ROOT) -> None:
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
        self.keyword_text: tk.Text | None = None
        self.compact_save = tk.BooleanVar(value=False)
        self.autosave = tk.BooleanVar(value=True)
        self.process: subprocess.Popen[str] | None = None
        self.message_queue: queue.Queue[tuple[str, str]] = queue.Queue()
        self._loading = True
        self._autosave_after_id: str | None = None

        self.root.title("MailSenderSystem Workbench")
        self.root.geometry("1220x780")
        self.root.configure(bg=self.PALETTE["window_bg"])
        self._configure_styles()
        self._build_shell()
        self._load_form_values()
        self._load_env_values()
        self._loading = False
        self.refresh_tables()
        self.root.after(100, self._drain_queue)

    def run(self) -> None:
        self.root.mainloop()

    def _configure_styles(self) -> None:
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("TFrame", background=self.PALETTE["window_bg"])
        style.configure("Surface.TFrame", background=self.PALETTE["surface"], relief="solid", borderwidth=1)
        style.configure("TLabel", background=self.PALETTE["window_bg"], foreground=self.PALETTE["text"])
        style.configure("Muted.TLabel", foreground=self.PALETTE["muted"])
        style.configure("TButton", padding=(12, 7))
        style.configure("Accent.TButton", background=self.PALETTE["accent"], foreground="#ffffff")
        style.map("Accent.TButton", background=[("active", self.PALETTE["accent_active"])])
        style.configure("Treeview", rowheight=26)

    def _build_shell(self) -> None:
        header = ttk.Frame(self.root, padding=(18, 14, 18, 8))
        header.pack(fill="x")
        ttk.Label(header, text="MailSenderSystem", font=("Segoe UI", 18, "bold")).pack(side="left")
        ttk.Label(header, text=f"Settings: {self.settings_path}", style="Muted.TLabel").pack(side="left", padx=(16, 0))

        actions = ttk.Frame(header)
        actions.pack(side="right")
        ttk.Button(actions, text="Reload", command=self.reload_settings).pack(side="left", padx=4)
        ttk.Button(actions, text="Load Config", command=self.load_config_file).pack(side="left", padx=4)
        ttk.Button(actions, text="Save Config As", command=self.save_config_file).pack(side="left", padx=4)
        ttk.Button(actions, text="Save All", style="Accent.TButton", command=self.save_all).pack(side="left", padx=4)
        ttk.Button(actions, text="Run Pipeline", command=lambda: self.start_process(["code/main.py"])).pack(side="left", padx=4)
        ttk.Button(actions, text="Research Only", command=lambda: self.start_process(["code/research/research_leads.py"])).pack(side="left", padx=4)

        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill="both", expand=True, padx=16, pady=(0, 16))
        self.settings_tab = ttk.Frame(self.notebook, padding=12)
        self.env_tab = ttk.Frame(self.notebook, padding=12)
        self.found_tab = ttk.Frame(self.notebook, padding=12)
        self.sent_tab = ttk.Frame(self.notebook, padding=12)
        self.logs_tab = ttk.Frame(self.notebook, padding=12)
        self.console_tab = ttk.Frame(self.notebook, padding=12)
        self.notebook.add(self.settings_tab, text="Settings")
        self.notebook.add(self.env_tab, text=".env")
        self.notebook.add(self.found_tab, text="Found Mails")
        self.notebook.add(self.sent_tab, text="Sent Mails")
        self.notebook.add(self.logs_tab, text="Saved Logs")
        self.notebook.add(self.console_tab, text="Run Console")
        self._build_settings_tab()
        self._build_env_tab()
        self._build_found_tab()
        self._build_sent_tab()
        self._build_logs_tab()
        self._build_console_tab()

    def _build_settings_tab(self) -> None:
        top = ttk.Frame(self.settings_tab)
        top.pack(fill="x", pady=(0, 10))
        ttk.Checkbutton(top, text="Compact save: remove settings that match defaults", variable=self.compact_save).pack(side="left")
        ttk.Checkbutton(top, text="Auto-save changes directly", variable=self.autosave).pack(side="left", padx=(18, 0))

        body = self._scrollable_body(self.settings_tab)

        sections: dict[str, list[SettingSpec]] = {}
        for spec in SETTINGS_SCHEMA:
            sections.setdefault(spec.section, []).append(spec)
        for column, (section, specs) in enumerate(sections.items()):
            frame = ttk.LabelFrame(body, text=section, padding=12)
            frame.grid(row=column // 2, column=column % 2, sticky="nsew", padx=8, pady=8)
            for row, spec in enumerate(specs):
                self._add_setting_row(frame, row, spec)

    def _build_env_tab(self) -> None:
        top = ttk.Frame(self.env_tab)
        top.pack(fill="x", pady=(0, 10))
        ttk.Label(top, text=f".env: {self.env_path}", style="Muted.TLabel").pack(side="left")
        body = self._scrollable_body(self.env_tab)
        sections: dict[str, list[SettingSpec]] = {}
        for spec in ENV_SCHEMA:
            sections.setdefault(spec.section, []).append(spec)
        for column, (section, specs) in enumerate(sections.items()):
            frame = ttk.LabelFrame(body, text=section, padding=12)
            frame.grid(row=column // 2, column=column % 2, sticky="nsew", padx=8, pady=8)
            for row, spec in enumerate(specs):
                self._add_setting_row(frame, row, spec, env=True)

    def _scrollable_body(self, parent: ttk.Frame) -> ttk.Frame:
        canvas = tk.Canvas(parent, borderwidth=0, highlightthickness=0, background=self.PALETTE["window_bg"])
        scrollbar = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        body = ttk.Frame(canvas)
        body.bind("<Configure>", lambda event: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=body, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        return body

    def _add_setting_row(self, parent: ttk.Frame, row: int, spec: SettingSpec, *, env: bool = False) -> None:
        ttk.Label(parent, text=spec.label).grid(row=row, column=0, sticky="w", padx=(0, 10), pady=5)
        var = self._create_variable(spec, self.env_values if env else self.values)
        variables = self.env_variables if env else self.variables
        variables[spec.key] = var
        var.trace_add("write", lambda *_args: self._schedule_autosave())
        widget: tk.Widget
        if spec.kind == "bool":
            widget = ttk.Checkbutton(parent, variable=var)
        elif spec.kind == "choice":
            widget = ttk.Combobox(parent, textvariable=var, values=spec.choices, state="readonly", width=28)
        elif spec.kind in {"int", "float"} and spec.min_value is not None and spec.max_value is not None:
            wrapper = ttk.Frame(parent)
            scale = ttk.Scale(wrapper, from_=spec.min_value, to=spec.max_value, orient="horizontal", variable=var)
            value_label = ttk.Label(wrapper, textvariable=var, width=8)
            scale.pack(side="left", fill="x", expand=True)
            value_label.pack(side="right", padx=(8, 0))
            widget = wrapper
        elif spec.kind == "list":
            text = tk.Text(parent, height=5, width=46, wrap="word")
            (self.env_text_widgets if env else self.text_widgets)[spec.key] = text
            if spec.key == "SELF_SEARCH_KEYWORDS":
                self.keyword_text = text
            text.bind("<KeyRelease>", lambda _event: self._schedule_autosave())
            text.bind("<FocusOut>", lambda _event: self._schedule_autosave())
            widget = text
        else:
            show = "*" if any(secret in spec.key.lower() for secret in ("password", "api_key", "token", "secret")) else ""
            widget = ttk.Entry(parent, textvariable=var, width=32, show=show)
        widget.grid(row=row, column=1, sticky="ew", pady=5)
        ttk.Label(parent, text=spec.help_text, style="Muted.TLabel", wraplength=360).grid(row=row, column=2, sticky="w", padx=(12, 0))
        parent.columnconfigure(1, weight=1)

    def _create_variable(self, spec: SettingSpec, source: dict[str, Any]) -> tk.Variable:
        value = source.get(spec.key, spec.default)
        if spec.kind == "bool":
            return tk.BooleanVar(value=bool(value))
        if spec.kind == "int":
            return tk.IntVar(value=int(value))
        if spec.kind == "float":
            return tk.DoubleVar(value=float(value))
        return tk.StringVar(value=str(value))

    def _build_found_tab(self) -> None:
        toolbar = ttk.Frame(self.found_tab)
        toolbar.pack(fill="x", pady=(0, 8))
        ttk.Button(toolbar, text="Refresh", command=self.refresh_tables).pack(side="left")
        self.found_tree = self._make_tree(self.found_tab, ("file", "mode", "company", "mail", "source_url"))

    def _build_sent_tab(self) -> None:
        toolbar = ttk.Frame(self.sent_tab)
        toolbar.pack(fill="x", pady=(0, 8))
        ttk.Button(toolbar, text="Refresh", command=self.refresh_tables).pack(side="left")
        self.sent_tree = self._make_tree(self.sent_tab, ("file", "company", "mail", "source_url"))

    def _build_logs_tab(self) -> None:
        toolbar = ttk.Frame(self.logs_tab)
        toolbar.pack(fill="x", pady=(0, 8))
        ttk.Button(toolbar, text="Refresh", command=self.refresh_tables).pack(side="left")
        self.log_tree = self._make_tree(self.logs_tab, ("file", "modified", "size"))

    def _build_console_tab(self) -> None:
        toolbar = ttk.Frame(self.console_tab)
        toolbar.pack(fill="x", pady=(0, 8))
        ttk.Button(toolbar, text="Run Pipeline", command=lambda: self.start_process(["code/main.py"])).pack(side="left", padx=4)
        ttk.Button(toolbar, text="Stop", command=self.stop_process).pack(side="left", padx=4)
        ttk.Button(toolbar, text="Clear", command=lambda: self.console.delete("1.0", "end")).pack(side="left", padx=4)
        self.console = scrolledtext.ScrolledText(self.console_tab, height=28, wrap="word")
        self.console.pack(fill="both", expand=True)

    def _make_tree(self, parent: ttk.Frame, columns: tuple[str, ...]) -> ttk.Treeview:
        tree = ttk.Treeview(parent, columns=columns, show="headings")
        for column in columns:
            tree.heading(column, text=column)
            tree.column(column, width=180 if column != "source_url" else 320, anchor="w")
        tree.pack(fill="both", expand=True)
        return tree

    def _load_form_values(self) -> None:
        for spec in SETTINGS_SCHEMA:
            value = self.values.get(spec.key, spec.default)
            if spec.kind == "list" and spec.key in self.text_widgets:
                self.text_widgets[spec.key].delete("1.0", "end")
                self.text_widgets[spec.key].insert("1.0", "\n".join(value or []))
            elif spec.key in self.variables:
                self.variables[spec.key].set(value)

    def _load_env_values(self) -> None:
        for spec in ENV_SCHEMA:
            value = self.env_values.get(spec.key, spec.default)
            if spec.kind == "list" and spec.key in self.env_text_widgets:
                self.env_text_widgets[spec.key].delete("1.0", "end")
                self.env_text_widgets[spec.key].insert("1.0", "\n".join(value or []))
            elif spec.key in self.env_variables:
                self.env_variables[spec.key].set(value)

    def collect_form_values(self) -> dict[str, Any]:
        values: dict[str, Any] = {}
        for spec in SETTINGS_SCHEMA:
            if spec.kind == "list" and spec.key in self.text_widgets:
                raw_value = self.text_widgets[spec.key].get("1.0", "end")
            else:
                raw_value = self.variables[spec.key].get()
            values[spec.key] = coerce_value(spec, raw_value)
        return values

    def collect_env_values(self) -> dict[str, Any]:
        values: dict[str, Any] = {}
        for spec in ENV_SCHEMA:
            if spec.kind == "list" and spec.key in self.env_text_widgets:
                raw_value = self.env_text_widgets[spec.key].get("1.0", "end")
            else:
                raw_value = self.env_variables[spec.key].get()
            values[spec.key] = coerce_value(spec, raw_value)
        return values

    def save_all(self) -> None:
        self.save_settings()
        self.save_env()

    def save_settings(self) -> None:
        try:
            write_settings(self.settings_path, self.collect_form_values(), omit_defaults=self.compact_save.get())
        except Exception as exc:
            messagebox.showerror("Save failed", str(exc))
            return
        self._append_console(f"[INFO] Saved settings to {self.settings_path}\n")

    def save_env(self) -> None:
        try:
            write_env(self.env_path, self.collect_env_values())
        except Exception as exc:
            messagebox.showerror("Save failed", str(exc))
            return
        self._append_console(f"[INFO] Saved .env to {self.env_path}\n")

    def reload_settings(self) -> None:
        self._loading = True
        self.values = load_settings(self.settings_path)
        self.env_values = load_env(self.env_path)
        self._load_form_values()
        self._load_env_values()
        self._loading = False
        self._append_console("[INFO] Reloaded settings.toml and .env\n")

    def load_config_file(self) -> None:
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
        if hasattr(self, "found_tree"):
            self._refresh_found_mails()
        if hasattr(self, "sent_tree"):
            self._refresh_sent_mails()
        if hasattr(self, "log_tree"):
            self._refresh_logs()

    def _refresh_sent_mails(self) -> None:
        self.sent_tree.delete(*self.sent_tree.get_children())
        output_dir = self.project_root / "output"
        for path in sorted(output_dir.glob("*.csv")) if output_dir.exists() else []:
            try:
                with path.open(newline="", encoding="utf-8-sig") as handle:
                    for row in csv.DictReader(handle):
                        self.sent_tree.insert("", "end", values=(
                            path.name,
                            row.get("company", ""),
                            row.get("mail", ""),
                            row.get("source_url", ""),
                        ))
            except OSError:
                continue

    def _refresh_found_mails(self) -> None:
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

    def _refresh_logs(self) -> None:
        self.log_tree.delete(*self.log_tree.get_children())
        log_dir_value = self.collect_form_values().get("VERBOSE_LOG_DIR", "logs") if self.variables else "logs"
        log_dir = Path(str(log_dir_value))
        if not log_dir.is_absolute():
            log_dir = self.project_root / log_dir
        for path in sorted(log_dir.glob("*.log"), reverse=True) if log_dir.exists() else []:
            stat = path.stat()
            self.log_tree.insert("", "end", values=(path.name, _format_mtime(stat.st_mtime), stat.st_size))

    def start_process(self, script_args: list[str]) -> None:
        if self.process and self.process.poll() is None:
            messagebox.showwarning("Process running", "A process is already running.")
            return
        self.save_all()
        command = [sys.executable, *script_args]
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
        if self.process and self.process.poll() is None:
            self.process.terminate()
            self._append_console("[INFO] Stop requested.\n")

    def _read_process_output(self) -> None:
        assert self.process is not None
        assert self.process.stdout is not None
        for line in self.process.stdout:
            self.message_queue.put(("log", line))
        exit_code = self.process.wait()
        self.message_queue.put(("log", f"[INFO] Process exited with code {exit_code}\n"))
        self.message_queue.put(("refresh", ""))

    def _drain_queue(self) -> None:
        while True:
            try:
                kind, payload = self.message_queue.get_nowait()
            except queue.Empty:
                break
            if kind == "log":
                self._append_console(payload)
            elif kind == "refresh":
                self.refresh_tables()
        self.root.after(100, self._drain_queue)

    def _append_console(self, text: str) -> None:
        self.console.insert("end", text)
        self.console.see("end")

    def _schedule_autosave(self) -> None:
        if self._loading or not self.autosave.get():
            return
        if self._autosave_after_id is not None:
            self.root.after_cancel(self._autosave_after_id)
        self._autosave_after_id = self.root.after(500, self._autosave_now)

    def _autosave_now(self) -> None:
        self._autosave_after_id = None
        self.save_all()


def _format_mtime(timestamp: float) -> str:
    from datetime import datetime

    return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")


def main() -> int:
    root = tk.Tk()
    app = MailSenderWorkbench(root)
    app.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
