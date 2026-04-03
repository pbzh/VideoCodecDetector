#!/usr/bin/env python3
"""
VideoCodecDetector  v2.1

Scans a folder for video files, detects each file's video codec via ffprobe,
lets you filter the results by codec tag, and move selected files to another folder.

Requirements
------------
    pip install customtkinter
    ffprobe must be on PATH  (bundled with FFmpeg: https://ffmpeg.org/download.html)
"""

import json
import queue
import shutil
import subprocess
import sys
import threading
from pathlib import Path

import customtkinter as ctk
from tkinter import filedialog, messagebox, ttk

# ── Constants ──────────────────────────────────────────────────────────────────
VERSION = "2.1.0"

from codec_common import VIDEO_EXTENSIONS, probe_file, ffprobe_available

CODEC_COLORS: dict[str, str] = {
    "h264":       "#2ecc71",
    "h265":       "#3498db",
    "hevc":       "#3498db",
    "av1":        "#9b59b6",
    "vp9":        "#e67e22",
    "vp8":        "#f39c12",
    "mpeg4":      "#e74c3c",
    "xvid":       "#c0392b",
    "mpeg2video": "#e67e22",
    "dnxhd":      "#1abc9c",
    "prores":     "#16a085",
    "utvideo":    "#f1c40f",
    "msmpeg4v3":  "#e74c3c",
    "unknown":    "#7f8c8d",
    "error":      "#e74c3c",
}


# ── Helpers ────────────────────────────────────────────────────────────────────
def format_size(size: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024:
            return f"{size:.1f} {unit}"
        size //= 1024
    return f"{size:.1f} PB"


def format_level(level: int) -> str:
    if level <= 0:
        return "–"
    if level >= 10:
        return f"{level // 10}.{level % 10}"
    return str(level)


def format_duration(seconds: float | None) -> str:
    if not seconds:
        return "–"
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


from codec_common import probe_file, ffprobe_available


# ── Data model ─────────────────────────────────────────────────────────────────
class VideoFile:
    __slots__ = ("path", "codec", "codec_tag", "profile", "level",
                 "size", "duration", "resolution", "error")

    def __init__(self, path: Path) -> None:
        self.path       = path
        self.codec      = ""
        self.codec_tag  = "–"
        self.profile    = "–"
        self.level      = 0
        self.duration   = "–"
        self.resolution = "–"
        self.error: str | None = None
        try:
            self.size = path.stat().st_size
        except OSError:
            self.size = 0


# ── Application ────────────────────────────────────────────────────────────────
class App(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()

        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        # Use customtkinter's own DPI scale — this is correct on retina, HiDPI,
        # and over RDP (no manual SetProcessDpiAwareness; ctk handles that itself).
        # We only use this to scale the ttk.Treeview which ctk doesn't touch.
        try:
            self._scale: float = ctk.ScalingTracker.get_window_dpi_scaling(self)
        except Exception:
            self._scale = 1.0

        self.title(f"Video Codec Detector  v{VERSION}")
        # Geometry in logical pixels — ctk converts to physical pixels internally.
        self.geometry("1300x820")
        self.minsize(960, 620)

        self._scan_thread: threading.Thread | None = None
        self._stop_event  = threading.Event()
        self._queue: queue.Queue = queue.Queue()

        self._video_files: list[VideoFile] = []
        self._detached:    set[str]        = set()
        self._filter_vars: dict[str, ctk.BooleanVar] = {}

        self._build_ui()
        self._poll_queue()

        if not ffprobe_available():
            messagebox.showwarning(
                "ffprobe not found",
                "ffprobe was not found on PATH.\n\n"
                "Install FFmpeg and ensure ffprobe is accessible:\n"
                "https://ffmpeg.org/download.html",
            )

    # ── UI ─────────────────────────────────────────────────────────────────────
    def _build_ui(self) -> None:
        # ── Folder rows ───────────────────────────────────────────────────────
        self.src_var = ctk.StringVar()
        self.dst_var = ctk.StringVar()
        self._folder_row("Source",      self.src_var, "src")
        self._folder_row("Destination", self.dst_var, "dst")

        # ── Button row ────────────────────────────────────────────────────────
        # Fixed height via pack_propagate(False) so the row never expands.
        btn_row = ctk.CTkFrame(self, fg_color="transparent", height=34)
        btn_row.pack_propagate(False)
        btn_row.pack(fill="x", padx=8, pady=(4, 0))

        _b = {"height": 26, "corner_radius": 5}

        self.btn_scan = ctk.CTkButton(
            btn_row, text="⟳  Scan", width=90,
            fg_color="#2980b9", hover_color="#1a6fa8",
            command=self._start_scan, **_b,
        )
        self.btn_scan.pack(side="left", padx=(0, 3))

        self.btn_stop = ctk.CTkButton(
            btn_row, text="■  Stop", width=70,
            fg_color="#c0392b", hover_color="#96281b", state="disabled",
            command=self._stop_scan, **_b,
        )
        self.btn_stop.pack(side="left", padx=(0, 10))

        self.btn_select_all = ctk.CTkButton(
            btn_row, text="All", width=50,
            fg_color="#444", hover_color="#555",
            command=self._select_all, **_b,
        )
        self.btn_select_all.pack(side="left", padx=(0, 3))

        self.btn_deselect = ctk.CTkButton(
            btn_row, text="None", width=55,
            fg_color="#444", hover_color="#555",
            command=self._deselect_all, **_b,
        )
        self.btn_deselect.pack(side="left", padx=(0, 10))

        self.btn_move = ctk.CTkButton(
            btn_row, text="➤  Move Selected", width=140,
            fg_color="#27ae60", hover_color="#1e8449",
            command=self._move_selected, **_b,
        )
        self.btn_move.pack(side="left")

        # ── Filter row ────────────────────────────────────────────────────────
        # Also fixed height — CTkScrollableFrame would otherwise expand freely.
        filter_row = ctk.CTkFrame(self, fg_color="transparent", height=34)
        filter_row.pack_propagate(False)
        filter_row.pack(fill="x", padx=8, pady=(3, 0))

        ctk.CTkLabel(filter_row, text="Filter:", width=44,
                     font=ctk.CTkFont(size=12)).pack(side="left")
        self.filter_frame = ctk.CTkScrollableFrame(
            filter_row, height=28, orientation="horizontal", fg_color="transparent",
        )
        self.filter_frame.pack(side="left", fill="both", expand=True)

        # ── Progress bar ──────────────────────────────────────────────────────
        prog_row = ctk.CTkFrame(self, fg_color="transparent", height=20)
        prog_row.pack_propagate(False)
        prog_row.pack(fill="x", padx=8, pady=(3, 0))

        self.progress = ctk.CTkProgressBar(prog_row, height=6)
        self.progress.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.progress.set(0)

        self.lbl_progress = ctk.CTkLabel(
            prog_row, text="Ready", width=340, anchor="w",
            font=ctk.CTkFont(size=11), text_color="#aaa",
        )
        self.lbl_progress.pack(side="left")

        # ── File table ────────────────────────────────────────────────────────
        table_frame = ctk.CTkFrame(self)
        table_frame.pack(fill="both", expand=True, padx=8, pady=(4, 0))

        sc    = self._scale
        row_h = round(28 * sc)    # physical pixels — must be scaled explicitly
        fs    = round(11 * sc)    # font in points already DPI-scaled by tk,
        fs_h  = round(11 * sc)    # but we match the scale so ctk and ttk agree

        style = ttk.Style()
        style.theme_use("clam")
        style.configure(
            "VCD.Treeview",
            background="#1e1e1e", foreground="#dddddd",
            fieldbackground="#1e1e1e",
            rowheight=row_h,
            font=("Consolas", fs),
        )
        style.configure(
            "VCD.Treeview.Heading",
            background="#1a1a2e", foreground="white",
            relief="flat", font=("Segoe UI", fs_h, "bold"),
        )
        style.map(
            "VCD.Treeview",
            background=[("selected", "#1e3a5f")],
            foreground=[("selected", "white")],
        )

        cols = ("sel", "filename", "codec", "tag", "profile",
                "resolution", "duration", "size", "folder")
        self.tree = ttk.Treeview(
            table_frame, columns=cols,
            show="headings", style="VCD.Treeview",
            selectmode="none",
        )

        for col, text, width, anchor in (
            ("sel",        "☑",              36,  "center"),
            ("filename",   "File Name",      260,  "w"),
            ("codec",      "Codec",           85,  "center"),
            ("tag",        "Tag",             75,  "center"),
            ("profile",    "Profile / Level",160,  "w"),
            ("resolution", "Resolution",      95,  "center"),
            ("duration",   "Duration",        75,  "center"),
            ("size",       "Size",            85,  "center"),
            ("folder",     "Folder",         310,  "w"),
        ):
            pw = round(width * sc)
            self.tree.heading(col, text=text, anchor=anchor)
            self.tree.column(
                col, width=pw,
                minwidth=max(round(36 * sc), pw - round(60 * sc)),
                anchor=anchor,
                stretch=(col == "folder"),
            )
        self.tree.column("sel", width=round(36 * sc), stretch=False)

        vsb = ttk.Scrollbar(table_frame, orient="vertical",   command=self.tree.yview)
        hsb = ttk.Scrollbar(table_frame, orient="horizontal",  command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        vsb.pack(side="right",  fill="y")
        hsb.pack(side="bottom", fill="x")
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<Button-1>", self._on_tree_click)

        # ── Status bar ────────────────────────────────────────────────────────
        self.lbl_status = ctk.CTkLabel(
            self, text="Select a source folder and click Scan.",
            anchor="w", font=ctk.CTkFont(size=11), text_color="#888",
        )
        self.lbl_status.pack(fill="x", padx=10, pady=(2, 4))

    def _folder_row(self, label: str, var: ctk.StringVar, target: str) -> None:
        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(fill="x", padx=8, pady=(4, 0))
        ctk.CTkLabel(row, text=f"{label}:", width=80, anchor="e",
                     font=ctk.CTkFont(size=12)).pack(side="left", padx=(0, 4))
        ctk.CTkEntry(row, textvariable=var,
                     placeholder_text="Select a folder…",
                     height=28).pack(side="left", fill="x", expand=True, padx=(0, 4))
        ctk.CTkButton(
            row, text="Browse…", width=80, height=28,
            command=lambda t=target: self._browse(t),
        ).pack(side="left")

    # ── Folder browse ──────────────────────────────────────────────────────────
    def _browse(self, target: str) -> None:
        folder = filedialog.askdirectory(title="Select folder")
        if folder:
            (self.src_var if target == "src" else self.dst_var).set(folder)

    # ── Scan ──────────────────────────────────────────────────────────────────
    def _start_scan(self) -> None:
        src = self.src_var.get().strip()
        if not src or not Path(src).is_dir():
            messagebox.showerror("Invalid folder", "Please select a valid source folder.")
            return

        self.tree.delete(*self.tree.get_children())
        self._video_files.clear()
        self._detached.clear()
        for w in self.filter_frame.winfo_children():
            w.destroy()
        self._filter_vars.clear()

        self._stop_event.clear()
        self.btn_scan.configure(state="disabled")
        self.btn_stop.configure(state="normal")
        self.progress.set(0)
        self.lbl_progress.configure(text="Collecting files…")

        self._scan_thread = threading.Thread(
            target=self._scan_worker, args=(Path(src),), daemon=True,
        )
        self._scan_thread.start()

    def _stop_scan(self) -> None:
        self._stop_event.set()
        self.btn_stop.configure(state="disabled")

    def _scan_worker(self, src: Path) -> None:
        try:
            video_paths = sorted(
                p for p in src.rglob("*")
                if p.suffix.lower() in VIDEO_EXTENSIONS and p.is_file()
            )
        except PermissionError as exc:
            self._queue.put(("error", str(exc)))
            return

        total = len(video_paths)
        self._queue.put(("total", total))

        for i, path in enumerate(video_paths):
            if self._stop_event.is_set():
                break

            vf = VideoFile(path)
            try:
                data = probe_file(path)
                for stream in data.get("streams", []):
                    if stream.get("codec_type") == "video":
                        vf.codec      = stream.get("codec_name", "unknown").lower()
                        tag           = stream.get("codec_tag_string", "")
                        vf.codec_tag  = tag if (tag and tag != "0x0000") else "–"
                        vf.profile    = stream.get("profile") or "–"
                        vf.level      = int(stream.get("level") or 0)
                        w             = stream.get("width",  0)
                        h             = stream.get("height", 0)
                        vf.resolution = f"{w}×{h}" if (w and h) else "–"
                        break
                if not vf.codec:
                    vf.codec = "unknown"
                dur         = float(data.get("format", {}).get("duration") or 0)
                vf.duration = format_duration(dur)
            except subprocess.TimeoutExpired:
                vf.codec = "error"
                vf.error = "Timeout"
            except (json.JSONDecodeError, ValueError):
                vf.codec = "error"
                vf.error = "Could not parse ffprobe output"
            except Exception as exc:
                vf.codec = "error"
                vf.error = str(exc)

            self._queue.put(("file", vf, i + 1, total))

        self._queue.put(("done", total, self._stop_event.is_set()))

    # ── Queue polling ──────────────────────────────────────────────────────────
    def _poll_queue(self) -> None:
        try:
            while True:
                msg  = self._queue.get_nowait()
                kind = msg[0]

                if kind == "total":
                    self.lbl_progress.configure(text=f"0 / {msg[1]}  files…")

                elif kind == "file":
                    _, vf, current, total = msg
                    self._video_files.append(vf)
                    self._add_row(vf)
                    self._ensure_filter_checkbox(vf.codec_tag, vf.codec)
                    self.progress.set(current / total if total else 0)
                    self.lbl_progress.configure(
                        text=f"{current} / {total}  —  {vf.path.name}",
                    )
                    self._update_status()

                elif kind == "done":
                    _, total, stopped = msg
                    self.btn_scan.configure(state="normal")
                    self.btn_stop.configure(state="disabled")
                    if not stopped:
                        self.progress.set(1)
                    self.lbl_progress.configure(text=(
                        f"Stopped — {total} files processed."
                        if stopped else
                        f"Done — {total} files scanned."
                    ))
                    self._update_status()

                elif kind == "error":
                    messagebox.showerror("Scan error", msg[1])

        except queue.Empty:
            pass

        self.after(80, self._poll_queue)

    def _add_row(self, vf: VideoFile) -> None:
        iid         = str(vf.path)
        tag         = f"c_{vf.codec}"
        color       = CODEC_COLORS.get(vf.codec, "#95a5a6")
        level_str   = format_level(vf.level)
        profile_str = vf.profile if vf.profile != "–" else ""
        profile_col = (
            f"{profile_str} @ L{level_str}" if profile_str and level_str != "–"
            else profile_str or level_str
        )
        self.tree.insert(
            "", "end", iid=iid,
            values=(
                "☐", vf.path.name, vf.codec.upper(), vf.codec_tag,
                profile_col, vf.resolution, vf.duration,
                format_size(vf.size), str(vf.path.parent),
            ),
            tags=(tag,),
        )
        self.tree.tag_configure(tag, foreground=color)

    # ── Codec-tag filter ───────────────────────────────────────────────────────
    def _ensure_filter_checkbox(self, codec_tag: str, codec_name: str) -> None:
        if codec_tag in self._filter_vars:
            return
        var   = ctk.BooleanVar(value=True)
        color = CODEC_COLORS.get(codec_name, "#95a5a6")
        self._filter_vars[codec_tag] = var
        label = codec_tag if codec_tag != "–" else codec_name.upper()
        ctk.CTkCheckBox(
            self.filter_frame,
            text=label, variable=var, text_color=color,
            font=ctk.CTkFont(size=11, weight="bold"),
            command=self._apply_filter,
            height=22,
        ).pack(side="left", padx=6, pady=1)

    def _apply_filter(self) -> None:
        active = {c for c, v in self._filter_vars.items() if v.get()}
        for vf in self._video_files:
            iid          = str(vf.path)
            show         = vf.codec_tag in active
            was_detached = iid in self._detached
            if show and was_detached:
                self.tree.reattach(iid, "", "end")
                self._detached.discard(iid)
            elif not show and not was_detached:
                if self.tree.exists(iid):
                    self.tree.detach(iid)
                    self._detached.add(iid)
        self._update_status()

    # ── Selection ──────────────────────────────────────────────────────────────
    def _on_tree_click(self, event) -> None:
        col = self.tree.identify_column(event.x)
        row = self.tree.identify_row(event.y)
        if row and col == "#1":
            vals    = list(self.tree.item(row, "values"))
            vals[0] = "☑" if vals[0] == "☐" else "☐"
            self.tree.item(row, values=vals)
            self._update_status()

    def _select_all(self) -> None:
        for iid in self.tree.get_children():
            vals = list(self.tree.item(iid, "values"))
            vals[0] = "☑"
            self.tree.item(iid, values=vals)
        self._update_status()

    def _deselect_all(self) -> None:
        for iid in self.tree.get_children():
            vals = list(self.tree.item(iid, "values"))
            vals[0] = "☐"
            self.tree.item(iid, values=vals)
        self._update_status()

    def _get_selected_iids(self) -> list[str]:
        return [
            iid for iid in self.tree.get_children()
            if self.tree.item(iid, "values")[0] == "☑"
        ]

    def _update_status(self) -> None:
        visible  = len(self.tree.get_children())
        selected = len(self._get_selected_iids())
        total    = len(self._video_files)
        self.lbl_status.configure(
            text=f"Total: {total}  |  Visible: {visible}  |  Selected: {selected}",
        )

    # ── Move files ─────────────────────────────────────────────────────────────
    def _move_selected(self) -> None:
        dst_str = self.dst_var.get().strip()
        if not dst_str:
            messagebox.showerror("No destination", "Please select a destination folder.")
            return

        dst_path     = Path(dst_str)
        src_path_str = self.src_var.get().strip()
        if src_path_str and Path(src_path_str).resolve() == dst_path.resolve():
            messagebox.showerror("Same folder", "Source and destination must be different.")
            return

        if not dst_path.exists():
            if messagebox.askyesno("Create folder?",
                                   f'"{dst_str}" does not exist.\nCreate it?'):
                dst_path.mkdir(parents=True, exist_ok=True)
            else:
                return

        selected = self._get_selected_iids()
        if not selected:
            messagebox.showinfo("Nothing selected",
                                "Click the ☑ column to select files, then try again.")
            return

        if not messagebox.askyesno("Confirm move",
                                   f"Move {len(selected)} file(s) to:\n{dst_str}"):
            return

        moved, errors = 0, []
        for iid in selected:
            src = Path(iid)
            tgt = dst_path / src.name
            if tgt.exists():
                stem, suffix, counter = tgt.stem, tgt.suffix, 1
                while tgt.exists():
                    tgt = dst_path / f"{stem}_{counter}{suffix}"
                    counter += 1
            try:
                shutil.move(str(src), str(tgt))
                self.tree.delete(iid)
                self._detached.discard(iid)
                moved += 1
            except Exception as exc:
                errors.append(f"{src.name}: {exc}")

        remaining = set(self.tree.get_children()) | self._detached
        self._video_files = [vf for vf in self._video_files
                             if str(vf.path) in remaining]

        summary = f"Successfully moved {moved} file(s)."
        if errors:
            preview = "\n".join(errors[:10])
            more    = f"\n…and {len(errors) - 10} more." if len(errors) > 10 else ""
            summary += f"\n\nFailed ({len(errors)}):\n{preview}{more}"
        messagebox.showinfo("Move complete", summary)
        self._update_status()


# ── Entry point ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app = App()
    app.mainloop()
