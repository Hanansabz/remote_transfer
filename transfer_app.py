"""Local-network file transfer app with explicit receiver approval and integrity checks."""
import hashlib
import hmac
import json
import os
import queue
import secrets
import socket
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

PORT = 8765
CHUNK_SIZE = 1024 * 256
MAX_FILE_SIZE = 10 * 1024 * 1024 * 1024


def local_ip():
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("192.0.2.1", 9))
        return probe.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        probe.close()


def send_json(sock, value):
    sock.sendall(json.dumps(value, separators=(",", ":")).encode("utf-8") + b"\n")


def read_json(file_obj):
    line = file_obj.readline(16_384)
    if not line or len(line) >= 16_384:
        raise ValueError("Invalid transfer message")
    return json.loads(line.decode("utf-8"))


def unique_path(folder, filename):
    safe_name = os.path.basename(filename.replace("\\", "/")).strip()
    if not safe_name or safe_name in (".", ".."):
        safe_name = "received_file"
    candidate = Path(folder) / safe_name
    stem, suffix = candidate.stem, candidate.suffix
    number = 1
    while candidate.exists():
        candidate = Path(folder) / f"{stem} ({number}){suffix}"
        number += 1
    return candidate


class TransferApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Dropzone · Local File Transfer")
        self.root.geometry("820x650")
        self.root.minsize(720, 570)
        self.root.configure(bg="#0b1020")
        self.events = queue.Queue()
        self.server = None
        self.server_thread = None
        self.server_stop = threading.Event()
        self.code_lock = threading.Lock()
        self.pairing_code = self.new_code()
        self.save_folder = tk.StringVar(value=str(Path.home() / "Downloads"))
        self.active_save_folder = Path(self.save_folder.get())
        self.file_path = tk.StringVar()
        self.destination_host = tk.StringVar()
        self.destination_code = tk.StringVar()
        self.receiver_status = tk.StringVar(value="Receiver is stopped")
        self.sender_status = tk.StringVar(value="Choose a file and enter the receiver’s address")
        self.build_ui()
        self.root.after(100, self.process_events)
        self.root.protocol("WM_DELETE_WINDOW", self.close)

    @staticmethod
    def new_code():
        return f"{secrets.randbelow(1_000_000):06d}"

    def build_ui(self):
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TNotebook", background="#0b1020", borderwidth=0)
        style.configure("TNotebook.Tab", background="#16213a", foreground="#aebbd4", padding=(18, 10), font=("Segoe UI", 10, "bold"))
        style.map("TNotebook.Tab", background=[("selected", "#243552")], foreground=[("selected", "#f2f6ff")])
        style.configure("TProgressbar", troughcolor="#24314b", background="#66e3d1", bordercolor="#24314b", lightcolor="#66e3d1", darkcolor="#66e3d1")

        header = tk.Frame(self.root, bg="#0b1020", padx=28, pady=23)
        header.pack(fill="x")
        tk.Label(header, text="DROPZONE", fg="#eaf0ff", bg="#0b1020", font=("Segoe UI", 19, "bold")).pack(anchor="w")
        tk.Label(header, text="Send a file directly between computers on your local network.", fg="#93a2bd", bg="#0b1020", font=("Segoe UI", 10)).pack(anchor="w", pady=(4, 0))

        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill="both", expand=True, padx=24, pady=(0, 18))
        self.receive_tab = tk.Frame(self.notebook, bg="#10182b", padx=24, pady=22)
        self.send_tab = tk.Frame(self.notebook, bg="#10182b", padx=24, pady=22)
        self.notebook.add(self.receive_tab, text="  Receive  ")
        self.notebook.add(self.send_tab, text="  Send  ")
        self.build_receive_tab()
        self.build_send_tab()

    def card(self, parent, title, subtitle):
        frame = tk.Frame(parent, bg="#151f34", highlightbackground="#263550", highlightthickness=1, padx=18, pady=16)
        frame.pack(fill="x", pady=(0, 14))
        tk.Label(frame, text=title, fg="#edf3ff", bg="#151f34", font=("Segoe UI", 12, "bold")).pack(anchor="w")
        tk.Label(frame, text=subtitle, fg="#91a0ba", bg="#151f34", font=("Segoe UI", 9)).pack(anchor="w", pady=(3, 12))
        return frame

    def label(self, parent, text):
        tk.Label(parent, text=text, fg="#aebbd4", bg=parent.cget("bg"), font=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(5, 5))

    def entry(self, parent, variable, width=None, show=None):
        return tk.Entry(parent, textvariable=variable, width=width, show=show, relief="flat", bg="#0c1424", fg="#f1f5ff", insertbackground="#f1f5ff", font=("Segoe UI", 10), highlightthickness=1, highlightbackground="#293852", highlightcolor="#66e3d1")

    def button(self, parent, text, command, primary=False):
        return tk.Button(parent, text=text, command=command, relief="flat", cursor="hand2", padx=15, pady=9, bg="#68d9d0" if primary else "#22304a", fg="#09121d" if primary else "#e8efff", activebackground="#87ebe0" if primary else "#314462", activeforeground="#09121d" if primary else "#ffffff", font=("Segoe UI", 9, "bold"))

    def build_receive_tab(self):
        intro = self.card(self.receive_tab, "Receive a file", "Start the receiver on this computer. Share its address and temporary code with the sender.")
        self.label(intro, "SAVE FILES TO")
        row = tk.Frame(intro, bg="#151f34")
        row.pack(fill="x")
        self.entry(row, self.save_folder).pack(side="left", fill="x", expand=True, ipady=9)
        self.button(row, "Browse", self.choose_folder).pack(side="left", padx=(8, 0))

        pairing = self.card(self.receive_tab, "This computer’s connection details", "Both computers need to be on the same local network.")
        self.label(pairing, "ADDRESS")
        self.address_label = tk.Label(pairing, text=f"{local_ip()}:{PORT}", fg="#73e5d4", bg="#151f34", font=("Consolas", 15, "bold"))
        self.address_label.pack(anchor="w", pady=(0, 9))
        self.label(pairing, "ONE-TIME PAIRING CODE")
        self.code_label = tk.Label(pairing, text=self.pairing_code, fg="#edf3ff", bg="#151f34", font=("Consolas", 24, "bold"))
        self.code_label.pack(anchor="w", pady=(0, 12))
        controls = tk.Frame(pairing, bg="#151f34")
        controls.pack(fill="x")
        self.receiver_button = self.button(controls, "Start receiving", self.start_receiver, primary=True)
        self.receiver_button.pack(side="left")
        self.button(controls, "Stop", self.stop_receiver).pack(side="left", padx=8)
        tk.Label(pairing, textvariable=self.receiver_status, fg="#aebbd4", bg="#151f34", font=("Segoe UI", 9)).pack(anchor="w", pady=(12, 0))

        tk.Label(self.receive_tab, text="Trusted local network only · transfer contents are not encrypted yet.", fg="#7787a4", bg="#10182b", font=("Segoe UI", 9)).pack(anchor="w", padx=3)

    def build_send_tab(self):
        panel = self.card(self.send_tab, "Send a file", "Choose a file, then enter the receiver details shown on the other computer.")
        self.label(panel, "FILE TO SEND")
        file_row = tk.Frame(panel, bg="#151f34")
        file_row.pack(fill="x")
        self.entry(file_row, self.file_path).pack(side="left", fill="x", expand=True, ipady=8)
        self.button(file_row, "Choose file…", self.choose_file).pack(side="left", padx=(8, 0))
        self.file_info = tk.Label(panel, text="No file selected", fg="#7f90ac", bg="#151f34", font=("Segoe UI", 9))
        self.file_info.pack(anchor="w", pady=(6, 8))

        self.label(panel, "RECEIVER ADDRESS  ·  enter the full IP:port shown on their Receive tab")
        self.entry(panel, self.destination_host).pack(fill="x", ipady=8)
        self.label(panel, "ONE-TIME PAIRING CODE")
        self.entry(panel, self.destination_code, show="•").pack(fill="x", ipady=8)

        controls = tk.Frame(panel, bg="#151f34")
        controls.pack(fill="x", pady=(14, 0))
        self.send_button = self.button(controls, "Send file", self.send_file, primary=True)
        self.send_button.pack(side="left")
        self.progress = ttk.Progressbar(controls, mode="determinate", maximum=100)
        self.progress.pack(side="left", fill="x", expand=True, padx=(14, 0))
        tk.Label(panel, textvariable=self.sender_status, fg="#aebbd4", bg="#151f34", font=("Segoe UI", 9)).pack(anchor="w", pady=(10, 0))
        tk.Label(self.send_tab, text="The receiver approves the file before it is saved. Both computers must be on the same local network.", fg="#7787a4", bg="#10182b", font=("Segoe UI", 9), wraplength=650, justify="left").pack(anchor="w", padx=3)
    def choose_folder(self):
        folder = filedialog.askdirectory(initialdir=self.save_folder.get())
        if folder:
            self.save_folder.set(folder)

    def choose_file(self):
        path = filedialog.askopenfilename()
        if path:
            self.file_path.set(path)
            size = Path(path).stat().st_size
            self.file_info.config(text=f"{Path(path).name}  ·  {self.format_size(size)}")

    @staticmethod
    def format_size(size):
        units = ["B", "KB", "MB", "GB"]
        value = float(size)
        for unit in units:
            if value < 1024 or unit == units[-1]:
                return f"{value:.1f} {unit}"
            value /= 1024

    def start_receiver(self):
        folder = Path(self.save_folder.get()).expanduser()
        if not folder.is_dir():
            messagebox.showerror("Choose a folder", "Choose an existing folder to save incoming files.")
            return
        if self.server_thread and self.server_thread.is_alive():
            return
        self.server_stop.clear()
        self.active_save_folder = folder
        self.pairing_code = self.new_code()
        self.code_label.config(text=self.pairing_code)
        self.server_thread = threading.Thread(target=self.receiver_loop, daemon=True)
        self.server_thread.start()
        self.receiver_status.set(f"Listening on port {PORT} · waiting for a sender")
        self.address_label.config(text=f"{local_ip()}:{PORT}")

    def stop_receiver(self):
        self.server_stop.set()
        if self.server:
            try:
                self.server.close()
            except OSError:
                pass
        self.receiver_status.set("Receiver is stopped")

    def receiver_loop(self):
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server = server
        try:
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server.bind(("0.0.0.0", PORT))
            server.listen(5)
            server.settimeout(0.5)
            while not self.server_stop.is_set():
                try:
                    conn, address = server.accept()
                except socket.timeout:
                    continue
                except OSError:
                    break
                threading.Thread(target=self.handle_transfer, args=(conn, address), daemon=True).start()
        except OSError as exc:
            self.events.put(("receiver_error", str(exc)))
        finally:
            try:
                server.close()
            except OSError:
                pass
            self.server = None

    def handle_transfer(self, conn, address):
        temp_name = None
        try:
            conn.settimeout(60)
            file_obj = conn.makefile("rb")
            header = read_json(file_obj)
            filename = str(header.get("name", "received_file"))[:255]
            size = int(header.get("size", -1))
            expected_hash = str(header.get("sha256", ""))
            nonce = str(header.get("nonce", ""))
            proof = str(header.get("proof", ""))
            if size < 0 or size > MAX_FILE_SIZE or len(expected_hash) != 64:
                send_json(conn, {"ok": False, "message": "File size or metadata is invalid."})
                return
            message = f"{nonce}\n{filename}\n{size}\n{expected_hash}".encode("utf-8")
            with self.code_lock:
                valid = hmac.compare_digest(hmac.new(self.pairing_code.encode(), message, hashlib.sha256).hexdigest(), proof)
            if not valid:
                send_json(conn, {"ok": False, "message": "Pairing code did not match."})
                self.events.put(("status", f"Rejected an unpaired connection from {address[0]}"))
                return

            # Consume the pairing code as soon as it authenticates successfully.
            with self.code_lock:
                self.pairing_code = self.new_code()
                next_code = self.pairing_code
            self.root.after(0, lambda: self.code_label.config(text=next_code))

            decision = threading.Event()
            approved = [False]
            def ask_receiver():
                approved[0] = messagebox.askyesno("Incoming file", f"{address[0]} wants to send:\n\n{filename}\n{self.format_size(size)}\n\nAccept this file?")
                decision.set()
            self.root.after(0, ask_receiver)
            if not decision.wait(120) or not approved[0]:
                send_json(conn, {"ok": False, "message": "Transfer declined or timed out."})
                self.events.put(("status", f"Declined {filename} from {address[0]}"))
                return

            folder = self.active_save_folder
            if not folder.is_dir():
                send_json(conn, {"ok": False, "message": "Save folder is unavailable."})
                return
            target = unique_path(folder, filename)
            temp_name = str(target.with_name(target.name + ".part"))
            send_json(conn, {"ok": True, "message": "Ready to receive."})

            digest = hashlib.sha256()
            remaining = size
            with open(temp_name, "xb") as output:
                while remaining:
                    block = file_obj.read(min(CHUNK_SIZE, remaining))
                    if not block:
                        raise ConnectionError("Connection ended before the full file arrived.")
                    output.write(block)
                    digest.update(block)
                    remaining -= len(block)
            if not hmac.compare_digest(digest.hexdigest(), expected_hash):
                raise ValueError("File integrity check failed; received bytes did not match the sender’s checksum.")
            os.rename(temp_name, target)
            temp_name = None
            send_json(conn, {"ok": True, "message": "Transfer complete.", "sha256": digest.hexdigest()})
            self.events.put(("status", f"Received {target.name} · {self.format_size(size)} · SHA-256 verified"))
        except Exception as exc:
            self.events.put(("status", f"Transfer error: {exc}"))
            try:
                send_json(conn, {"ok": False, "message": str(exc)[:300]})
            except OSError:
                pass
        finally:
            if temp_name and os.path.exists(temp_name):
                try:
                    os.remove(temp_name)
                except OSError:
                    pass
            try:
                conn.close()
            except OSError:
                pass
    def send_file(self):
        path = Path(self.file_path.get()).expanduser()
        address = self.destination_host.get().strip()
        code = self.destination_code.get().strip()
        if not path.is_file():
            messagebox.showerror("Choose a file", "Choose a file to send first.")
            return
        if not address or len(code) != 6 or not code.isdigit():
            messagebox.showerror("Receiver details needed", "Enter the receiver’s full address and six-digit pairing code.")
            return
        try:
            if address.count(":") == 1:
                host, port_text = address.rsplit(":", 1)
                port = int(port_text)
            else:
                host, port = address, PORT
            if not host or not 1 <= port <= 65535:
                raise ValueError
        except ValueError:
            messagebox.showerror("Address format", "Enter an address like 192.168.1.23:8765.")
            return
        if path.stat().st_size > MAX_FILE_SIZE:
            messagebox.showerror("File is too large", "The current version supports files up to 10 GB.")
            return
        self.send_button.config(state="disabled")
        self.progress["value"] = 0
        self.sender_status.set("Connecting to receiver…")
        threading.Thread(target=self.sender_worker, args=(path, host, port, code), daemon=True).start()

    def sender_worker(self, path, host, port, code):
        try:
            size = path.stat().st_size
            digest = hashlib.sha256()
            with open(path, "rb") as source:
                while True:
                    block = source.read(CHUNK_SIZE)
                    if not block:
                        break
                    digest.update(block)
            file_hash = digest.hexdigest()
            nonce = secrets.token_hex(16)
            message = f"{nonce}\n{filename}\n{size}\n{expected_hash}".encode("utf-8")
            proof = hmac.new(code.encode(), message, hashlib.sha256).hexdigest()
            header = {"name": path.name, "size": size, "sha256": file_hash, "nonce": nonce, "proof": proof}
            with socket.create_connection((host, port), timeout=10) as conn:
                conn.settimeout(120)
                file_obj = conn.makefile("rb")
                send_json(conn, header)
                response = read_json(file_obj)
                if not response.get("ok"):
                    raise RuntimeError(response.get("message", "Receiver rejected the transfer."))
                sent = 0
                with open(path, "rb") as source:
                    while True:
                        block = source.read(CHUNK_SIZE)
                        if not block:
                            break
                        conn.sendall(block)
                        sent += len(block)
                        percent = 100 if size == 0 else int(sent * 100 / size)
                        self.events.put(("progress", percent))
                final = read_json(file_obj)
                if not final.get("ok"):
                    raise RuntimeError(final.get("message", "Transfer failed."))
                self.events.put(("send_done", f"Sent {path.name} · SHA-256 verified by receiver"))
        except Exception as exc:
            self.events.put(("send_error", str(exc)))

    def process_events(self):
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == "progress":
                    self.progress["value"] = value
                    self.sender_status.set(f"Sending… {value}%")
                elif kind == "send_done":
                    self.send_button.config(state="normal")
                    self.progress["value"] = 100
                    self.sender_status.set(value)
                    messagebox.showinfo("Transfer complete", value)
                elif kind == "send_error":
                    self.send_button.config(state="normal")
                    self.sender_status.set(f"Could not send: {value}")
                    messagebox.showerror("Transfer failed", value)
                elif kind == "receiver_error":
                    self.receiver_status.set(f"Could not start receiver: {value}")
                    messagebox.showerror("Receiver could not start", value)
                elif kind == "status":
                    self.receiver_status.set(value)
        except queue.Empty:
            pass
        self.root.after(100, self.process_events)

    def close(self):
        self.stop_receiver()
        self.root.destroy()


if __name__ == "__main__":
    window = tk.Tk()
    TransferApp(window)
    window.mainloop()




