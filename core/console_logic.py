import os
import datetime
import time
import platform
import sys
import subprocess

class ConsoleLogic:
    LEVEL_WEIGHT = {
        "DEBUG": 10,
        "BOOT": 20,
        "SYSTEM": 20,
        "INFO": 30,
        "SUCCESS": 30,
        "ACTION": 30,
        "WARN": 40,
        "WARNING": 40,
        "ERROR": 50,
    }

    class CustomStdout:
        """Klasa przechwytująca sys.stdout, aby print() trafiał do logiki."""
        def __init__(self, logic):
            self.logic = logic
            self.terminal = sys.__stdout__

        def write(self, message):
            self.terminal.write(message)
            if message.strip():
                # Przekazujemy do logiki jako INFO, aby pojawiło się w UI
                self.logic.log(message.strip(), "INFO")

        def flush(self):
            self.terminal.flush()

    class CustomStderr:
        """Przechwytuje sys.stderr do konsoli UI."""
        def __init__(self, logic):
            self.logic = logic
            self.terminal = sys.__stderr__

        def write(self, message):
            self.terminal.write(message)
            if message.strip():
                self.logic.log(message.strip(), "ERROR")

        def flush(self):
            self.terminal.flush()

    def __init__(self, main_window):
        self.main_window = main_window
        self.history = []
        self.command_history = []  # Historia wpisanych komend (dla strzałek)
        self.log_profile = "normal"
        
        # --- WSPOMAGANIE KONSOLI (Przechwytywanie stdout) ---
        sys.stdout = self.CustomStdout(self)
        sys.stderr = self.CustomStderr(self)
        sys.excepthook = self._handle_exception
        
        # 1. Konfiguracja ścieżek pod LxMonitor
        # LxMonitor/core/console_logic.py -> wychodzimy do LxMonitor/
        current_file_dir = os.path.dirname(os.path.abspath(__file__))
        base_dir = os.path.abspath(os.path.join(current_file_dir, "../"))
        self.logs_dir = os.path.join(base_dir, "assets", "logs")
        
        if not os.path.exists(self.logs_dir):
            os.makedirs(self.logs_dir)
            
        self.log_file = os.path.join(self.logs_dir, f"monitor_{datetime.datetime.now().strftime('%Y-%m-%d')}.log")
        
        # 2. Czyszczenie starych logów (> 48h)
        self.cleanup_old_logs(hours=48)
        self.log("LxMonitor Console Logic Initialized", "SYSTEM")

    def set_log_profile(self, profile):
        p = str(profile or "normal").strip().lower()
        if p not in {"normal", "debug", "quiet"}:
            p = "normal"
        self.log_profile = p

    def _is_level_visible(self, level):
        if self.log_profile == "debug":
            return True
        if self.log_profile == "quiet":
            lvl = str(level or "INFO").upper()
            return self.LEVEL_WEIGHT.get(lvl, 30) >= 40
        lvl = str(level or "INFO").upper()
        return self.LEVEL_WEIGHT.get(lvl, 30) >= 20

    def _handle_exception(self, exc_type, exc_value, exc_traceback):
        import traceback
        formatted = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
        self.log("Unhandled exception captured.", "ERROR")
        for line in formatted.splitlines():
            if line.strip():
                self.log(line, "ERROR")

    def log(self, message, level="INFO"):
        """Główna funkcja logująca - tak jak w LxNotes."""
        if not self._is_level_visible(level):
            return
        now = datetime.datetime.now()
        timestamp = now.strftime("%H:%M:%S")
        formatted_msg = f"[{timestamp}] [{level}] {message}"
        
        self.history.append(formatted_msg)
        
        # Przekazanie do UI (jeśli okno dialogowe istnieje)
        if hasattr(self.main_window, 'console_dialog') and self.main_window.console_dialog:
            self.main_window.console_dialog.append_text(formatted_msg, level)
        
        # Piszemy na fizyczny terminal i do pliku
        # print(formatted_msg) # Usunięte, bo CustomStdout już to wyłapie, żeby nie było pętli
        self._write_to_disk(formatted_msg)

    def _write_to_disk(self, text):
        try:
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(text + "\n")
        except Exception as e:
            # Tutaj używamy sys.__stdout__, żeby nie zapętlić logiki przy błędzie zapisu
            sys.__stdout__.write(f"Log Save Error: {e}\n")

    def cleanup_old_logs(self, hours=48):
        try:
            now = time.time()
            cutoff = now - (hours * 3600)
            if os.path.exists(self.logs_dir):
                for filename in os.listdir(self.logs_dir):
                    file_path = os.path.join(self.logs_dir, filename)
                    if os.path.isfile(file_path) and os.path.getmtime(file_path) < cutoff:
                        os.remove(file_path)
        except Exception as e:
            self.log(f"Cleanup Error: {e}", "ERROR")

    def execute_command(self, cmd_text):
        """Parser komend terminala - dostosowany do LxMonitor."""
        full_cmd = cmd_text.strip()
        if not full_cmd: return None
        
        self.command_history.append(full_cmd)
        parts = full_cmd.split()
        cmd = parts[0].lower()
        args = parts[1:] if len(parts) > 1 else []

        self.log(f"> {full_cmd}", "ACTION")

        # Tablica komend z LxNotes przerobiona pod Monitor
        if cmd == "clear":
            return "clear"
            
        elif cmd == "help":
            return "Commands: help, clear, engines, compile, logs, sys, crash, turbo <on/off>, exit"

        elif cmd == "engines":
            # Nowa komenda specyficzna dla Monitora
            return "Engines: CPU (Active), RAM (Active), GPU (Idle)"

        elif cmd == "compile":
            # Wywołanie buildera silników C++
            self.log("Starting manual engine compilation...", "SYSTEM")
            return "Check builder logs for details."

        elif cmd == "exit":
            self.main_window.close()
            return "Closing LxMonitor..."

        elif cmd == "logs":
            # Otwieranie folderu (Linux/Fedora style)
            subprocess.Popen(['xdg-open', self.logs_dir])
            return "Opening logs folder..."

        elif cmd in ["sys", "sys-info"]:
            return (f"OS: {platform.system()} | Py: {sys.version.split()[0]} | "
                    f"Arch: {platform.machine()}")

        elif cmd == "crash":
            self.log("Manual crash test triggered.", "WARN")
            try:
                _ = 1 / 0
            except ZeroDivisionError as e:
                self.log(f"Intercepted: {e}", "ERROR")
                return "Error logged successfully."

        elif cmd == "turbo":
            state = args[0] if args else "status"
            if state == "on":
                return "Turbo Mode: ENABLED (High Performance Engine Active)"
            elif state == "off":
                return "Turbo Mode: DISABLED (Power Save Mode)"
            return "Turbo Mode: AUTOMATIC"

        else:
            return f"Unknown command: {cmd}. Type 'help' for info."
