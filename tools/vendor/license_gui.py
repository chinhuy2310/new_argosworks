#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
license_gui.py — Desktop GUI for ARGOS WORKS License Issuing & Management.

Designed for Windows/macOS/Linux using Tkinter with clean modern styling.
No external dependencies required (uses built-in Python standard library).
"""
import os
import sys
import csv
import json
import ctypes
from datetime import datetime, timedelta

# Enable High-DPI awareness on Windows for crisp rendering
if sys.platform == "win32":
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass

import tkinter as tk
from tkinter import ttk, messagebox, filedialog

# Add project server/ directory to import path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SERVER_DIR = os.path.join(BASE_DIR, "server")
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

from services.license_manager import (
    generate_signed_license_key,
    verify_license_key,
    LicenseSigningKeyMissing,
)

# Reference license_tool helpers if available
TOOLS_VENDOR_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_KEY_FILE = os.path.join(TOOLS_VENDOR_DIR, "license_signing_key.hex")
ISSUE_LOG = os.path.join(TOOLS_VENDOR_DIR, "issued_licenses.csv")
LICENSES_DIR = os.path.join(BASE_DIR, "licenses")
os.makedirs(LICENSES_DIR, exist_ok=True)

VALID_MODULES = [
    ("canvas", "Canvas (Bảng biểu & Dự án)"),
    ("pim", "PIM (Sản phẩm & Danh mục)"),
    ("jira", "Jira Integration (Đồng bộ Jira)"),
    ("rag", "RAG / AI Vector Search"),
    ("schedule", "Schedule (Lịch biểu & Ca làm)"),
    ("audit", "Audit & Governance (Nhật ký kiểm toán)"),
]


def read_signing_key():
    if os.path.exists(DEFAULT_KEY_FILE):
        with open(DEFAULT_KEY_FILE, "r", encoding="utf-8") as f:
            return f.read().strip()
    return (os.environ.get("ARGOS_LICENSE_SIGNING_KEY") or "").strip()


def slugify(name):
    cleaned = "".join(c if c.isalnum() or c in "-_" else "-" for c in name)
    return cleaned.strip("-").lower()[:48] or "customer"


class LicenseApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("ARGOS WORKS — Quản lý & Tạo License Bản Quyền")
        self.geometry("900x700")
        self.minsize(800, 600)

        # Style configuration
        self._init_style()

        # Layout
        self._build_header()
        self._build_tabs()
        self._build_statusbar()

        # Load initial data
        self.refresh_history()

    def _init_style(self):
        self.configure(bg="#0f172a")
        style = ttk.Style(self)
        style.theme_use("clam")

        # Palette: Slate dark / Modern blue
        style.configure(".", background="#0f172a", foreground="#f8fafc", font=("Segoe UI", 10))
        style.configure("TNotebook", background="#0f172a", borderwidth=0)
        style.configure("TNotebook.Tab", background="#1e293b", foreground="#94a3b8", padding=[16, 8], font=("Segoe UI", 10, "bold"))
        style.map("TNotebook.Tab", background=[("selected", "#2563eb")], foreground=[("selected", "#ffffff")])

        style.configure("TFrame", background="#0f172a")
        style.configure("Card.TFrame", background="#1e293b", relief="flat")
        style.configure("TLabel", background="#0f172a", foreground="#e2e8f0")
        style.configure("Card.TLabel", background="#1e293b", foreground="#e2e8f0")
        style.configure("Muted.TLabel", background="#1e293b", foreground="#94a3b8", font=("Segoe UI", 9))
        style.configure("Title.TLabel", background="#0f172a", foreground="#38bdf8", font=("Segoe UI", 14, "bold"))

        style.configure("Primary.TButton", background="#2563eb", foreground="#ffffff", font=("Segoe UI", 10, "bold"), padding=[14, 8])
        style.map("Primary.TButton", background=[("active", "#1d4ed8"), ("disabled", "#475569")])

        style.configure("Secondary.TButton", background="#334155", foreground="#f8fafc", font=("Segoe UI", 9), padding=[10, 5])
        style.map("Secondary.TButton", background=[("active", "#475569")])

        style.configure("TCheckbutton", background="#1e293b", foreground="#f8fafc", font=("Segoe UI", 10))
        style.map("TCheckbutton", background=[("active", "#1e293b")])

        style.configure("TRadiobutton", background="#1e293b", foreground="#f8fafc", font=("Segoe UI", 10))
        style.map("TRadiobutton", background=[("active", "#1e293b")])

        style.configure("Treeview", background="#1e293b", foreground="#f8fafc", fieldbackground="#1e293b", font=("Segoe UI", 9), rowheight=28)
        style.configure("Treeview.Heading", background="#334155", foreground="#38bdf8", font=("Segoe UI", 9, "bold"))
        style.map("Treeview", background=[("selected", "#2563eb")], foreground=[("selected", "#ffffff")])

    def _build_header(self):
        header_frame = tk.Frame(self, bg="#0f172a", padx=20, pady=12)
        header_frame.pack(fill=tk.X)

        title = tk.Label(header_frame, text="🛡️ ARGOS WORKS — VENDOR LICENSE MANAGER", font=("Segoe UI", 15, "bold"), fg="#38bdf8", bg="#0f172a")
        title.pack(anchor="w")

        sub = tk.Label(header_frame, text="Hệ thống cấp phép bản quyền phần mềm doanh nghiệp (Chuẩn mã hóa bất đối xứng Ed25519)", font=("Segoe UI", 9), fg="#94a3b8", bg="#0f172a")
        sub.pack(anchor="w")

    def _build_tabs(self):
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=20, pady=5)

        self.tab_issue = ttk.Frame(self.notebook)
        self.tab_inspect = ttk.Frame(self.notebook)
        self.tab_history = ttk.Frame(self.notebook)

        self.notebook.add(self.tab_issue, text="  ➕ Phát hành License  ")
        self.notebook.add(self.tab_inspect, text="  🔍 Kiểm tra File .lic  ")
        self.notebook.add(self.tab_history, text="  📋 Lịch sử đã cấp  ")

        self._setup_issue_tab()
        self._setup_inspect_tab()
        self._setup_history_tab()

    def _setup_issue_tab(self):
        canvas_container = tk.Canvas(self.tab_issue, bg="#0f172a", highlightthickness=0)
        scrollbar = ttk.Scrollbar(self.tab_issue, orient="vertical", command=canvas_container.yview)
        scrollable_frame = ttk.Frame(canvas_container)

        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas_container.configure(scrollregion=canvas_container.bbox("all"))
        )
        canvas_container.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas_container.configure(yscrollcommand=scrollbar.set)

        canvas_container.pack(side="left", fill="both", expand=True, padx=(10, 0), pady=10)
        scrollbar.pack(side="right", fill="y", pady=10)

        card = ttk.Frame(scrollable_frame, style="Card.TFrame", padding=20)
        card.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        # 1. Customer Name
        ttk.Label(card, text="Tên khách hàng / Doanh nghiệp (*):", style="Card.TLabel", font=("Segoe UI", 10, "bold")).grid(row=0, column=0, sticky="w", pady=(0, 4))
        self.ent_customer = tk.Entry(card, width=45, font=("Segoe UI", 11), bg="#0f172a", fg="#ffffff", insertbackground="#ffffff", relief="flat", highlightthickness=1, highlightbackground="#475569")
        self.ent_customer.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 15), ipady=4)

        # 2. Seats
        ttk.Label(card, text="Số lượng Seats (Tài khoản người dùng):", style="Card.TLabel", font=("Segoe UI", 10, "bold")).grid(row=2, column=0, sticky="w", pady=(0, 4))
        self.ent_seats = tk.Spinbox(card, from_=1, to=10000, font=("Segoe UI", 11), width=20, bg="#0f172a", fg="#ffffff", insertbackground="#ffffff", relief="flat", highlightthickness=1, highlightbackground="#475569")
        self.ent_seats.delete(0, tk.END)
        self.ent_seats.insert(0, "50")
        self.ent_seats.grid(row=3, column=0, sticky="w", pady=(0, 15), ipady=3)

        # 3. License Type (Commercial vs Trial)
        ttk.Label(card, text="Loại License:", style="Card.TLabel", font=("Segoe UI", 10, "bold")).grid(row=4, column=0, sticky="w", pady=(0, 4))
        
        self.license_type_var = tk.StringVar(value="commercial")
        radio_frame = ttk.Frame(card, style="Card.TFrame")
        radio_frame.grid(row=5, column=0, columnspan=2, sticky="w", pady=(0, 10))

        ttk.Radiobutton(radio_frame, text="Thương mại (Commercial)", variable=self.license_type_var, value="commercial", command=self._toggle_type).pack(side=tk.LEFT, padx=(0, 20))
        ttk.Radiobutton(radio_frame, text="Dùng thử (Trial - Đếm ngày từ lần kích hoạt đầu)", variable=self.license_type_var, value="trial", command=self._toggle_type).pack(side=tk.LEFT)

        # Frame for Type Details
        self.type_detail_frame = ttk.Frame(card, style="Card.TFrame")
        self.type_detail_frame.grid(row=6, column=0, columnspan=2, sticky="ew", pady=(0, 15))

        # Commercial Expiry
        self.lbl_expiry = ttk.Label(self.type_detail_frame, text="Ngày hết hạn (YYYY-MM-DD):", style="Card.TLabel")
        self.lbl_expiry.pack(anchor="w", pady=(0, 2))
        next_year = (datetime.now() + timedelta(days=365)).strftime("%Y-%m-%d")
        self.ent_expiry = tk.Entry(self.type_detail_frame, width=25, font=("Segoe UI", 11), bg="#0f172a", fg="#ffffff", insertbackground="#ffffff", relief="flat", highlightthickness=1, highlightbackground="#475569")
        self.ent_expiry.insert(0, next_year)
        self.ent_expiry.pack(anchor="w", ipady=3)

        # Trial Days
        self.lbl_trial_days = ttk.Label(self.type_detail_frame, text="Thời hạn dùng thử (Số ngày):", style="Card.TLabel")
        self.ent_trial_days = tk.Spinbox(self.type_detail_frame, from_=1, to=365, width=25, font=("Segoe UI", 11), bg="#0f172a", fg="#ffffff", insertbackground="#ffffff", relief="flat", highlightthickness=1, highlightbackground="#475569")
        self.ent_trial_days.delete(0, tk.END)
        self.ent_trial_days.insert(0, "60")

        # 4. Modules selection
        ttk.Label(card, text="Phân hệ chức năng (Modules):", style="Card.TLabel", font=("Segoe UI", 10, "bold")).grid(row=7, column=0, sticky="w", pady=(0, 4))
        
        mod_btn_frame = ttk.Frame(card, style="Card.TFrame")
        mod_btn_frame.grid(row=8, column=0, columnspan=2, sticky="w", pady=(0, 8))
        ttk.Button(mod_btn_frame, text="Chọn tất cả", style="Secondary.TButton", command=self._select_all_modules).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(mod_btn_frame, text="Bỏ chọn hết", style="Secondary.TButton", command=self._deselect_all_modules).pack(side=tk.LEFT)

        self.module_vars = {}
        mod_grid = ttk.Frame(card, style="Card.TFrame")
        mod_grid.grid(row=9, column=0, columnspan=2, sticky="w", pady=(0, 15))

        for idx, (m_id, m_label) in enumerate(VALID_MODULES):
            var = tk.BooleanVar(value=True)
            self.module_vars[m_id] = var
            r = idx // 2
            c = idx % 2
            ttk.Checkbutton(mod_grid, text=m_label, variable=var).grid(row=r, column=c, sticky="w", padx=(0, 25), pady=4)

        # 5. Issue Button
        btn_issue = ttk.Button(card, text="✨ TẠO VÀ XUẤT LICENSE BẢN QUYỀN", style="Primary.TButton", command=self.handle_issue)
        btn_issue.grid(row=10, column=0, columnspan=2, sticky="ew", pady=(10, 15), ipady=5)

        # 6. Result Panel
        ttk.Label(card, text="Kết quả cấp phép (License Key đã ký số):", style="Card.TLabel", font=("Segoe UI", 10, "bold")).grid(row=11, column=0, sticky="w", pady=(0, 4))
        
        self.txt_result = tk.Text(card, height=4, font=("Consolas", 10), bg="#0f172a", fg="#38bdf8", relief="flat", highlightthickness=1, highlightbackground="#475569")
        self.txt_result.grid(row=12, column=0, columnspan=2, sticky="ew", pady=(0, 8))

        res_btn_frame = ttk.Frame(card, style="Card.TFrame")
        res_btn_frame.grid(row=13, column=0, columnspan=2, sticky="w")
        ttk.Button(res_btn_frame, text="📋 Sao chép mã", style="Secondary.TButton", command=self._copy_result).pack(side=tk.LEFT, padx=(0, 10))
        ttk.Button(res_btn_frame, text="💾 Lưu thành file .lic khác...", style="Secondary.TButton", command=self._save_as_file).pack(side=tk.LEFT, padx=(0, 10))
        ttk.Button(res_btn_frame, text="📂 Mở thư mục licenses/", style="Secondary.TButton", command=self._open_licenses_dir).pack(side=tk.LEFT)

    def _toggle_type(self):
        val = self.license_type_var.get()
        if val == "commercial":
            self.lbl_trial_days.pack_forget()
            self.ent_trial_days.pack_forget()
            self.lbl_expiry.pack(anchor="w", pady=(0, 2))
            self.ent_expiry.pack(anchor="w", ipady=3)
        else:
            self.lbl_expiry.pack_forget()
            self.ent_expiry.pack_forget()
            self.lbl_trial_days.pack(anchor="w", pady=(0, 2))
            self.ent_trial_days.pack(anchor="w", ipady=3)

    def _select_all_modules(self):
        for v in self.module_vars.values():
            v.set(True)

    def _deselect_all_modules(self):
        for v in self.module_vars.values():
            v.set(False)

    def handle_issue(self):
        customer = self.ent_customer.get().strip()
        if not customer:
            messagebox.showerror("Thiếu thông tin", "Vui lòng nhập tên khách hàng / tổ chức.")
            return

        try:
            seats = int(self.ent_seats.get())
            if seats <= 0:
                raise ValueError
        except ValueError:
            messagebox.showerror("Sai dữ liệu", "Số lượng seats phải là số nguyên dương (> 0).")
            return

        selected_mods = [m_id for m_id, var in self.module_vars.items() if var.get()]
        if not selected_mods:
            messagebox.showerror("Thiếu module", "Vui lòng chọn ít nhất một module chức năng.")
            return

        is_trial = (self.license_type_var.get() == "trial")
        expiry_val = None
        term_days_val = None

        if is_trial:
            try:
                term_days_val = int(self.ent_trial_days.get())
                if term_days_val <= 0 or term_days_val > 365:
                    raise ValueError
            except ValueError:
                messagebox.showerror("Sai thời hạn", "Số ngày dùng thử phải từ 1 đến 365 ngày.")
                return
        else:
            expiry_val = self.ent_expiry.get().strip()
            try:
                datetime.strptime(expiry_val, "%Y-%m-%d")
            except ValueError:
                messagebox.showerror("Sai định dạng ngày", "Ngày hết hạn phải theo định dạng YYYY-MM-DD.")
                return

        signing_key = read_signing_key()
        if not signing_key:
            messagebox.showerror("Thiếu Signing Key", f"Không tìm thấy file private key tại:\n{DEFAULT_KEY_FILE}\nVui lòng tạo keygen trước.")
            return

        try:
            key_b64 = generate_signed_license_key(
                customer_name=customer,
                max_seats=seats,
                expiry_date_str=expiry_val,
                modules=selected_mods,
                signing_key_hex=signing_key,
                is_trial=is_trial,
                term_days=term_days_val,
            )
        except Exception as e:
            messagebox.showerror("Lỗi tạo License", f"Không thể tạo license: {e}")
            return

        # Verification check
        ok, msg, data = verify_license_key(key_b64)
        if not ok:
            messagebox.showerror("Lỗi xác minh nội bộ", f"License tạo ra không hợp lệ: {msg}")
            return

        # Auto save file
        file_name = f"{slugify(customer)}-trial.lic" if is_trial else f"{slugify(customer)}-{seats}seats.lic"
        out_file = os.path.join(LICENSES_DIR, file_name)
        with open(out_file, "w", encoding="utf-8") as f:
            f.write(key_b64.strip() + "\n")

        # Append to CSV log
        self._log_to_csv(customer, seats, expiry_val, selected_mods, is_trial, term_days_val, out_file)

        # Show in result
        self.txt_result.delete("1.0", tk.END)
        self.txt_result.insert(tk.END, key_b64)

        self.last_generated_file = out_file
        self.refresh_history()

        messagebox.showinfo(
            "Thành công",
            f"Đã tạo License thành công!\n\nKhách hàng: {customer}\nSeats: {seats}\nLoại: {'Trial (' + str(term_days_val) + ' ngày)' if is_trial else 'Thương mại (đến ' + str(expiry_val) + ')'}\nĐã lưu vào: {out_file}"
        )

    def _log_to_csv(self, customer, seats, expiry, modules, is_trial, term_days, out_path):
        import hashlib
        headers = ["issued_at", "customer", "seats", "expiry", "modules", "trial", "term_days", "file", "key_sha256"]
        new_file = not os.path.exists(ISSUE_LOG)
        try:
            with open(out_path, "r", encoding="utf-8") as f:
                key_hash = hashlib.sha256(f.read().strip().encode("utf-8")).hexdigest()
            with open(ISSUE_LOG, "a", newline="", encoding="utf-8") as log:
                writer = csv.writer(log)
                if new_file:
                    writer.writerow(headers)
                writer.writerow([
                    datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
                    customer,
                    seats,
                    expiry or "",
                    ",".join(modules),
                    "true" if is_trial else "false",
                    term_days if is_trial else "",
                    os.path.relpath(out_path, BASE_DIR),
                    key_hash,
                ])
        except Exception as e:
            print(f"[WARN] Failed to write issue log: {e}")

    def _copy_result(self):
        text = self.txt_result.get("1.0", tk.END).strip()
        if text:
            self.clipboard_clear()
            self.clipboard_append(text)
            messagebox.showinfo("Đã sao chép", "Đã sao chép chuỗi mã License vào Clipboard.")
        else:
            messagebox.showwarning("Trống", "Chưa có License nào được tạo.")

    def _save_as_file(self):
        text = self.txt_result.get("1.0", tk.END).strip()
        if not text:
            messagebox.showwarning("Trống", "Chưa có License nào để lưu.")
            return
        path = filedialog.asksaveasfilename(defaultextension=".lic", filetypes=[("License Files", "*.lic"), ("All Files", "*.*")])
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(text + "\n")
            messagebox.showinfo("Đã lưu", f"Đã lưu license vào:\n{path}")

    def _open_licenses_dir(self):
        if sys.platform == "win32":
            os.startfile(LICENSES_DIR)
        else:
            import subprocess
            subprocess.run(["open" if sys.platform == "darwin" else "xdg-open", LICENSES_DIR])

    # ------------------ TAB 2: INSPECT ------------------
    def _setup_inspect_tab(self):
        container = ttk.Frame(self.tab_inspect, padding=20)
        container.pack(fill=tk.BOTH, expand=True)

        card = ttk.Frame(container, style="Card.TFrame", padding=20)
        card.pack(fill=tk.BOTH, expand=True)

        ttk.Label(card, text="Nhập chuỗi mã License hoặc chọn file .lic để kiểm tra:", style="Card.TLabel", font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(0, 10))

        btn_bar = ttk.Frame(card, style="Card.TFrame")
        btn_bar.pack(fill=tk.X, pady=(0, 10))

        ttk.Button(btn_bar, text="📁 Chọn file .lic từ máy tính...", style="Primary.TButton", command=self._inspect_file).pack(side=tk.LEFT, padx=(0, 10))
        ttk.Button(btn_bar, text="🔍 Phân tích mã bên dưới", style="Secondary.TButton", command=self._inspect_text).pack(side=tk.LEFT)

        self.txt_inspect_input = tk.Text(card, height=4, font=("Consolas", 10), bg="#0f172a", fg="#ffffff", relief="flat", highlightthickness=1, highlightbackground="#475569")
        self.txt_inspect_input.pack(fill=tk.X, pady=(0, 15))

        # Result display
        ttk.Label(card, text="Thông tin chi tiết sau giải mã & xác thực:", style="Card.TLabel", font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(0, 5))
        
        self.txt_inspect_details = tk.Text(card, height=12, font=("Segoe UI", 10), bg="#0f172a", fg="#a7f3d0", relief="flat", highlightthickness=1, highlightbackground="#475569")
        self.txt_inspect_details.pack(fill=tk.BOTH, expand=True)

    def _inspect_file(self):
        path = filedialog.askopenfilename(initialdir=LICENSES_DIR, filetypes=[("License Files", "*.lic"), ("All Files", "*.*")])
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read().strip()
            self.txt_inspect_input.delete("1.0", tk.END)
            self.txt_inspect_input.insert(tk.END, content)
            self._do_inspect(content, source_file=path)
        except Exception as e:
            messagebox.showerror("Lỗi đọc file", f"Không thể đọc file: {e}")

    def _inspect_text(self):
        content = self.txt_inspect_input.get("1.0", tk.END).strip()
        if not content:
            messagebox.showwarning("Trống", "Vui lòng dán mã license hoặc chọn file .lic.")
            return
        self._do_inspect(content)

    def _do_inspect(self, key_str, source_file=None):
        ok, msg, data = verify_license_key(key_str)
        self.txt_inspect_details.delete("1.0", tk.END)
        
        status_line = f"KẾT QUẢ XÁC THỰC: {'[ ĐẬP ỨNG / HỢP LỆ ]' if ok else '[ KHÔNG HỢP LỆ / LỖI ]'}\n"
        self.txt_inspect_details.insert(tk.END, status_line)
        self.txt_inspect_details.insert(tk.END, f"Thông báo: {msg}\n")
        if source_file:
            self.txt_inspect_details.insert(tk.END, f"Đường dẫn file: {source_file}\n")
        self.txt_inspect_details.insert(tk.END, "=" * 65 + "\n")

        if data:
            self.txt_inspect_details.insert(tk.END, f"Khách hàng (Customer): {data.get('customer')}\n")
            self.txt_inspect_details.insert(tk.END, f"Số seats cấp phép:   {data.get('seats')}\n")
            self.txt_inspect_details.insert(tk.END, f"Loại giấy phép:      {'DÙNG THỬ (TRIAL)' if data.get('trial') else 'THƯƠNG MẠI (COMMERCIAL)'}\n")
            if data.get("trial"):
                self.txt_inspect_details.insert(tk.END, f"Thời hạn dùng thử:   {data.get('term_days')} ngày (tính từ lần đầu kích hoạt)\n")
            self.txt_inspect_details.insert(tk.END, f"Hạn chót (Expiry):   {data.get('expiry') or '(Không có hạn cứng, theo số ngày dùng thử)'}\n")
            self.txt_inspect_details.insert(tk.END, f"Ngày cấp (Issued At):{data.get('issued_at')}\n")
            self.txt_inspect_details.insert(tk.END, f"Modules kích hoạt:   {', '.join(data.get('modules') or [])}\n")

    # ------------------ TAB 3: HISTORY ------------------
    def _setup_history_tab(self):
        container = ttk.Frame(self.tab_history, padding=20)
        container.pack(fill=tk.BOTH, expand=True)

        top_bar = ttk.Frame(container)
        top_bar.pack(fill=tk.X, pady=(0, 10))

        ttk.Label(top_bar, text="Tìm kiếm:", font=("Segoe UI", 10)).pack(side=tk.LEFT, padx=(0, 8))
        self.ent_search = tk.Entry(top_bar, width=30, font=("Segoe UI", 10), bg="#1e293b", fg="#ffffff", insertbackground="#ffffff", relief="flat", highlightthickness=1, highlightbackground="#475569")
        self.ent_search.pack(side=tk.LEFT, padx=(0, 10), ipady=3)
        self.ent_search.bind("<KeyRelease>", lambda e: self.filter_history())

        ttk.Button(top_bar, text="🔄 Làm mới", style="Secondary.TButton", command=self.refresh_history).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(top_bar, text="📂 Mở thư mục licenses/", style="Secondary.TButton", command=self._open_licenses_dir).pack(side=tk.LEFT)

        # Treeview table
        cols = ("issued_at", "customer", "seats", "type", "expiry_term", "modules", "file")
        self.tree = ttk.Treeview(container, columns=cols, show="headings", selectmode="browse")
        
        self.tree.heading("issued_at", text="Thời điểm cấp")
        self.tree.heading("customer", text="Khách hàng")
        self.tree.heading("seats", text="Seats")
        self.tree.heading("type", text="Loại")
        self.tree.heading("expiry_term", text="Hạn / Thời hạn")
        self.tree.heading("modules", text="Phân hệ (Modules)")
        self.tree.heading("file", text="Tập tin lưu")

        self.tree.column("issued_at", width=130, anchor="center")
        self.tree.column("customer", width=180, anchor="w")
        self.tree.column("seats", width=60, anchor="center")
        self.tree.column("type", width=75, anchor="center")
        self.tree.column("expiry_term", width=110, anchor="center")
        self.tree.column("modules", width=160, anchor="w")
        self.tree.column("file", width=150, anchor="w")

        tree_scroll = ttk.Scrollbar(container, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=tree_scroll.set)

        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        tree_scroll.pack(side=tk.RIGHT, fill=tk.Y)

    def refresh_history(self):
        for item in self.tree.get_children():
            self.tree.delete(item)

        self.history_rows = []
        if not os.path.exists(ISSUE_LOG):
            return

        try:
            with open(ISSUE_LOG, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for r in reader:
                    is_trial = (r.get("trial") or "").lower() == "true"
                    type_str = "Trial" if is_trial else "Commercial"
                    exp_term = f"{r.get('term_days')} ngày" if is_trial else (r.get("expiry") or "N/A")
                    row_data = (
                        r.get("issued_at", "")[:19].replace("T", " "),
                        r.get("customer", ""),
                        r.get("seats", ""),
                        type_str,
                        exp_term,
                        r.get("modules", ""),
                        os.path.basename(r.get("file", "")),
                    )
                    self.history_rows.append(row_data)

            self.filter_history()
        except Exception as e:
            print(f"[WARN] Failed to load history: {e}")

    def filter_history(self):
        q = self.ent_search.get().strip().lower()
        for item in self.tree.get_children():
            self.tree.delete(item)

        for row in reversed(self.history_rows):
            if not q or q in row[1].lower() or q in row[6].lower():
                self.tree.insert("", tk.END, values=row)

    def _build_statusbar(self):
        bar = tk.Frame(self, bg="#1e293b", padx=15, pady=6)
        bar.pack(fill=tk.X, side=tk.BOTTOM)

        signing_key = read_signing_key()
        key_status = "🟢 Private Key: Đã nạp thành công" if signing_key else "🔴 Private Key: CHƯA TÌM THẤY"
        lbl_key = tk.Label(bar, text=key_status, font=("Segoe UI", 9, "bold"), fg="#10b981" if signing_key else "#ef4444", bg="#1e293b")
        lbl_key.pack(side=tk.LEFT)

        lbl_dir = tk.Label(bar, text=f"Thư mục lưu: {LICENSES_DIR}", font=("Segoe UI", 9), fg="#94a3b8", bg="#1e293b")
        lbl_dir.pack(side=tk.RIGHT)


if __name__ == "__main__":
    app = LicenseApp()
    app.mainloop()
