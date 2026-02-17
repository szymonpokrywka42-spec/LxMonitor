from PyQt6.QtCore import QObject, QTimer, pyqtSignal
import os
import time
import glob
import shutil
import subprocess
import re

class CppEngineWorker(QObject):
    """
    Logika zbierania danych działająca w tle. 
    Zapobiega lagom UI przy ciężkich operacjach C++.
    """
    data_ready = pyqtSignal(dict)
    error_signal = pyqtSignal(str)

    def __init__(self, bridge1):
        super().__init__()
        self.bridge1 = bridge1
        self.active_engines = []
        self.is_active = False
        self._cpu_prev_total = None
        self._cpu_prev_cores = {}
        self._gpu_name_cache = {}
        self._engine_fail_streak = {}
        self._engine_last_heal_ts = {}
        self._heal_threshold = 3
        self._heal_cooldown_s = 8.0
        self._bt_prev_time = None
        self._bt_prev_bytes = {}
        self._bt_connected_cache_ts = 0.0
        self._bt_connected_cache_val = None
        self._fb_cpu_prev = None
        self._fb_disk_prev_time = None
        self._fb_disk_prev_io = {}
        self._fb_net_prev_time = None
        self._fb_net_prev_bytes = {}

    def _emit(self, level, message):
        self.error_signal.emit(f"[{level}] {message}")

    def _mark_engine_ok(self, engine_name):
        self._engine_fail_streak[engine_name] = 0

    def _mark_engine_fail(self, engine_name, reason):
        streak = self._engine_fail_streak.get(engine_name, 0) + 1
        self._engine_fail_streak[engine_name] = streak
        if streak >= self._heal_threshold:
            self._try_self_heal_engine(engine_name, reason, streak)

    def _replace_active_engine(self, old_engine, new_engine):
        if old_engine in self.active_engines:
            self.active_engines = [new_engine if e == old_engine else e for e in self.active_engines]
        elif new_engine not in self.active_engines:
            self.active_engines.append(new_engine)

    def _try_self_heal_engine(self, engine_name, reason, streak):
        now = time.time()
        last = self._engine_last_heal_ts.get(engine_name, 0.0)
        if (now - last) < self._heal_cooldown_s:
            return
        self._engine_last_heal_ts[engine_name] = now

        self._emit(
            "WARN",
            f"Watchdog: '{engine_name}' failing ({streak}x). Reason: {reason}. Attempting relink.",
        )
        ok = self.bridge1.link_engine(engine_name)
        if ok:
            self._engine_fail_streak[engine_name] = 0
            self._emit("SUCCESS", f"Watchdog: relink OK for '{engine_name}'.")
            return

        if engine_name == "gpu_nvidia":
            fb = self.bridge1.link_engine("gpu_others")
            if fb:
                self._replace_active_engine("gpu_nvidia", "gpu_others")
                self._engine_fail_streak[engine_name] = 0
                self._engine_fail_streak["gpu_others"] = 0
                self._emit("WARN", "Watchdog: switched GPU engine 'gpu_nvidia' -> 'gpu_others'.")
                return

        # Keep trying in future cycles, but avoid hot loop.
        self._engine_fail_streak[engine_name] = self._heal_threshold - 1
        self._emit("ERROR", f"Watchdog: relink failed for '{engine_name}'.")

    def perform_check(self):
        """Pojedynczy cykl odpytania wszystkich aktywnych silników."""
        if not self.is_active:
            return

        collected_data = {}
        try:
            for engine_name in self.active_engines:
                # Wywołujemy metodę z cpp_handler1.py
                if engine_name == "disc":
                    all_disks = self.bridge1.invoke_method(engine_name, "get_all_usage")
                    if isinstance(all_disks, dict) and all_disks:
                        collected_data["disc_all"] = all_disks
                        self._mark_engine_ok(engine_name)
                    else:
                        val = self.bridge1.invoke_method(engine_name, "get_usage")
                        if val is not None:
                            collected_data[engine_name] = val
                            self._mark_engine_ok(engine_name)
                        else:
                            self._mark_engine_fail(engine_name, "no disk usage payload")
                elif engine_name == "net":
                    all_ifaces = self.bridge1.invoke_method(engine_name, "get_all_usage")
                    if isinstance(all_ifaces, dict):
                        collected_data["net_all"] = all_ifaces
                        collected_data["net_meta"] = self._read_net_iface_meta(list(all_ifaces.keys()))
                    total_mbps = self.bridge1.invoke_method(engine_name, "get_total_mbps")
                    rx_mbps = self.bridge1.invoke_method(engine_name, "get_rx_mbps")
                    tx_mbps = self.bridge1.invoke_method(engine_name, "get_tx_mbps")
                    if total_mbps is not None:
                        collected_data["net"] = total_mbps
                    if rx_mbps is not None:
                        collected_data["net_rx"] = rx_mbps
                    if tx_mbps is not None:
                        collected_data["net_tx"] = tx_mbps
                    if total_mbps is None and rx_mbps is None and tx_mbps is None:
                        self._mark_engine_fail(engine_name, "no net metrics")
                    else:
                        self._mark_engine_ok(engine_name)
                elif engine_name == "bt":
                    bt_all = self.bridge1.invoke_method(engine_name, "get_all_usage")
                    if isinstance(bt_all, dict):
                        collected_data["bt_all"] = bt_all
                        self._mark_engine_ok(engine_name)
                    else:
                        self._mark_engine_fail(engine_name, "no bt metrics")
                elif engine_name == "psu":
                    psu_all = self.bridge1.invoke_method(engine_name, "get_all_usage")
                    if isinstance(psu_all, dict):
                        collected_data["psu_all"] = psu_all
                    val = self.bridge1.invoke_method(engine_name, "get_usage")
                    if val is not None:
                        collected_data["psu"] = val
                    if isinstance(psu_all, dict) or val is not None:
                        self._mark_engine_ok(engine_name)
                    else:
                        self._mark_engine_fail(engine_name, "no power telemetry")
                else:
                    val = self.bridge1.invoke_method(engine_name, "get_usage")
                    if val is not None:
                        collected_data[engine_name] = val
                        self._mark_engine_ok(engine_name)
                    else:
                        self._mark_engine_fail(engine_name, "get_usage returned None")

            # Dodatkowe statystyki z systemu (Python fallback)
            cpu_temp = self._read_cpu_temp_c()
            if cpu_temp is not None:
                collected_data["cpu_temp"] = cpu_temp

            gpu_all = self._read_gpu_stats_all()
            if gpu_all:
                collected_data["gpu_all"] = gpu_all

            # Dodatkowe statystyki systemowe.
            collected_data.update(self._read_system_stats())

            # Core metric fallbacks (cross-distro compatibility when C++ engines are unavailable).
            if "cpu" not in collected_data:
                cpu_fb = self._fallback_cpu_usage()
                if cpu_fb is not None:
                    collected_data["cpu"] = cpu_fb
            if "ram" not in collected_data:
                ram_fb = self._fallback_ram_usage()
                if ram_fb is not None:
                    collected_data["ram"] = ram_fb
            if "disc" not in collected_data and "disc_all" not in collected_data:
                disc_all_fb = self._fallback_disk_all_usage()
                if disc_all_fb:
                    collected_data["disc_all"] = disc_all_fb
            if "net" not in collected_data and "net_all" not in collected_data:
                net_fb = self._fallback_net_usage()
                if net_fb:
                    collected_data.update(net_fb)
                    if isinstance(net_fb.get("net_all"), dict):
                        collected_data["net_meta"] = self._read_net_iface_meta(list(net_fb["net_all"].keys()))

            # Bluetooth adapters (Python fallback telemetry).
            if "bt" not in self.active_engines:
                bt_all = self._read_bluetooth_stats_all()
                if isinstance(bt_all, dict) and bt_all:
                    collected_data["bt_all"] = bt_all

            # Jeśli zebraliśmy jakiekolwiek dane, ślemy do UI
            if collected_data:
                self.data_ready.emit(collected_data)
                
        except Exception as e:
            # Przekazujemy błąd wyżej, żeby trafił do konsoli
            self._emit("ERROR", f"Worker Runtime Error: {e}")

    def _fallback_cpu_usage(self):
        try:
            with open("/proc/stat", "r", encoding="utf-8", errors="ignore") as f:
                line = f.readline().strip()
            if not line.startswith("cpu "):
                return None
            parts = line.split()
            nums = [int(x) for x in parts[1:] if x.isdigit()]
            if len(nums) < 4:
                return None
            total = sum(nums)
            idle = nums[3] + (nums[4] if len(nums) > 4 else 0)
            if self._fb_cpu_prev is None:
                self._fb_cpu_prev = (total, idle)
                return None
            prev_total, prev_idle = self._fb_cpu_prev
            dt = total - prev_total
            di = idle - prev_idle
            self._fb_cpu_prev = (total, idle)
            if dt <= 0:
                return None
            usage = 100.0 * (1.0 - float(di) / float(dt))
            return max(0.0, min(100.0, usage))
        except Exception:
            return None

    def _fallback_ram_usage(self):
        mem = {}
        try:
            with open("/proc/meminfo", "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    key, _, value = line.partition(":")
                    if not value:
                        continue
                    mem[key.strip()] = int(value.strip().split()[0])
            total_kb = mem.get("MemTotal")
            avail_kb = mem.get("MemAvailable")
            if total_kb and avail_kb is not None and total_kb > 0:
                used_kb = max(0, total_kb - avail_kb)
                return 100.0 * (float(used_kb) / float(total_kb))
        except Exception:
            pass
        return None

    def _is_physical_disk_name(self, name):
        return bool(
            re.match(r"^(sd[a-z]+|hd[a-z]+|vd[a-z]+|xvd[a-z]+|nvme\d+n\d+|mmcblk\d+|dm-\d+)$", str(name or ""))
        )

    def _fallback_disk_all_usage(self):
        try:
            now = time.time()
            curr = {}
            with open("/proc/diskstats", "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    parts = line.split()
                    if len(parts) < 14:
                        continue
                    name = parts[2]
                    if not self._is_physical_disk_name(name):
                        continue
                    io_ms = int(parts[12])
                    curr[name] = io_ms
            if not curr:
                return {}
            if self._fb_disk_prev_time is None:
                self._fb_disk_prev_time = now
                self._fb_disk_prev_io = curr
                return {}
            elapsed_ms = max(1.0, (now - self._fb_disk_prev_time) * 1000.0)
            out = {}
            for name, io_ms in curr.items():
                prev = self._fb_disk_prev_io.get(name)
                if prev is None:
                    continue
                dio = max(0, io_ms - prev)
                usage = (float(dio) / elapsed_ms) * 100.0
                out[name] = max(0.0, min(100.0, usage))
            self._fb_disk_prev_time = now
            self._fb_disk_prev_io = curr
            return out
        except Exception:
            return {}

    def _is_virtual_iface(self, iface):
        for p in ("lo", "docker", "veth", "br-", "virbr", "vmnet", "tun", "tap", "zt", "tailscale"):
            if iface.startswith(p):
                return True
        return False

    def _fallback_net_usage(self):
        try:
            now = time.time()
            curr = {}
            with open("/proc/net/dev", "r", encoding="utf-8", errors="ignore") as f:
                lines = f.read().splitlines()[2:]
            for line in lines:
                if ":" not in line:
                    continue
                iface, rest = line.split(":", 1)
                iface = iface.strip()
                if not iface or self._is_virtual_iface(iface):
                    continue
                nums = rest.split()
                if len(nums) < 16:
                    continue
                rx = int(nums[0])
                tx = int(nums[8])
                curr[iface] = (rx, tx)
            if not curr:
                return {}
            if self._fb_net_prev_time is None:
                self._fb_net_prev_time = now
                self._fb_net_prev_bytes = curr
                return {}
            elapsed = now - self._fb_net_prev_time
            if elapsed <= 0.0001:
                return {}
            net_all = {}
            total_rx_bps = 0.0
            total_tx_bps = 0.0
            for iface, (rx, tx) in curr.items():
                prev = self._fb_net_prev_bytes.get(iface)
                if prev is None:
                    continue
                d_rx = max(0, rx - prev[0])
                d_tx = max(0, tx - prev[1])
                rx_bps = float(d_rx) / elapsed
                tx_bps = float(d_tx) / elapsed
                mbps = ((rx_bps + tx_bps) * 8.0) / 1_000_000.0
                net_all[iface] = max(0.0, mbps)
                total_rx_bps += rx_bps
                total_tx_bps += tx_bps
            self._fb_net_prev_time = now
            self._fb_net_prev_bytes = curr
            rx_mbps = (total_rx_bps * 8.0) / 1_000_000.0
            tx_mbps = (total_tx_bps * 8.0) / 1_000_000.0
            return {
                "net_all": net_all,
                "net": rx_mbps + tx_mbps,
                "net_rx": rx_mbps,
                "net_tx": tx_mbps,
            }
        except Exception:
            return {}

    def _read_cpu_temp_c(self):
        # 1) Najpierw hwmon (bardziej wiarygodne dla AMD/Intel desktop).
        temp = self._read_cpu_temp_from_hwmon()
        if temp is not None:
            return temp

        # 2) Fallback: thermal_zone.
        return self._read_cpu_temp_from_thermal_zone()

    def _read_cpu_temp_from_hwmon(self):
        base = "/sys/class/hwmon"
        if not os.path.isdir(base):
            return None

        preferred_drivers = ("k10temp", "coretemp", "zenpower", "fam15h_power", "cpu_thermal")
        best = None
        for name in os.listdir(base):
            hw = os.path.join(base, name)
            driver_path = os.path.join(hw, "name")
            if not os.path.isfile(driver_path):
                continue
            try:
                driver = open(driver_path, "r", encoding="utf-8", errors="ignore").read().strip().lower()
            except Exception:
                continue
            if not any(tag in driver for tag in preferred_drivers):
                continue

            for file_name in os.listdir(hw):
                if not (file_name.startswith("temp") and file_name.endswith("_input")):
                    continue
                temp_path = os.path.join(hw, file_name)
                try:
                    raw = open(temp_path, "r", encoding="utf-8", errors="ignore").read().strip()
                    val = float(raw)
                    if val > 1000:
                        val = val / 1000.0
                    # Odrzucamy ewidentnie nierealne wartości.
                    if 10.0 <= val <= 120.0:
                        if best is None or val > best:
                            best = val
                except Exception:
                    continue
        return best

    def _read_cpu_temp_from_thermal_zone(self):
        preferred_types = (
            "x86_pkg_temp",
            "k10temp",
            "cpu",
            "package",
            "tctl",
            "tdie",
        )
        base = "/sys/class/thermal"
        if not os.path.isdir(base):
            return None
        best = None
        for name in os.listdir(base):
            if not name.startswith("thermal_zone"):
                continue
            zone = os.path.join(base, name)
            type_path = os.path.join(zone, "type")
            temp_path = os.path.join(zone, "temp")
            if not (os.path.isfile(type_path) and os.path.isfile(temp_path)):
                continue
            try:
                zone_type = open(type_path, "r", encoding="utf-8", errors="ignore").read().strip().lower()
                raw = open(temp_path, "r", encoding="utf-8", errors="ignore").read().strip()
                val = float(raw)
                if val > 1000:
                    val = val / 1000.0
                if not (10.0 <= val <= 120.0):
                    continue
                if any(t in zone_type for t in preferred_types):
                    return val
                if best is None:
                    best = val
            except Exception:
                continue
        return best

    def _read_system_stats(self):
        stats = {}
        try:
            with open("/proc/stat", "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    if line.startswith("processes "):
                        stats["sys_processes_total"] = int(line.split()[1])
                    elif line.startswith("procs_running "):
                        stats["sys_procs_running"] = int(line.split()[1])
                    elif line.startswith("procs_blocked "):
                        stats["sys_procs_blocked"] = int(line.split()[1])
        except Exception:
            pass

        try:
            with open("/proc/uptime", "r", encoding="utf-8", errors="ignore") as f:
                stats["sys_uptime_s"] = float(f.read().split()[0])
        except Exception:
            pass

        # /proc/loadavg
        try:
            with open("/proc/loadavg", "r", encoding="utf-8", errors="ignore") as f:
                parts = f.read().split()
                if len(parts) >= 3:
                    stats["sys_load_1m"] = float(parts[0])
                    stats["sys_load_5m"] = float(parts[1])
                    stats["sys_load_15m"] = float(parts[2])
        except Exception:
            pass

        # /proc/meminfo
        mem = {}
        try:
            with open("/proc/meminfo", "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    key, _, value = line.partition(":")
                    if not value:
                        continue
                    mem[key.strip()] = int(value.strip().split()[0])
        except Exception:
            mem = {}

        total_kb = mem.get("MemTotal")
        avail_kb = mem.get("MemAvailable")
        swap_total_kb = mem.get("SwapTotal")
        swap_free_kb = mem.get("SwapFree")
        if total_kb is not None:
            stats["sys_mem_total_kb"] = total_kb
        if avail_kb is not None:
            stats["sys_mem_available_kb"] = avail_kb
        if swap_total_kb is not None:
            stats["sys_swap_total_kb"] = swap_total_kb
        if swap_free_kb is not None:
            stats["sys_swap_free_kb"] = swap_free_kb

        # CPU topology
        cpu_count = os.cpu_count()
        if cpu_count is not None:
            stats["sys_cpu_count"] = int(cpu_count)

        core_usage = self._read_cpu_core_usage()
        if core_usage:
            stats["sys_cpu_cores_usage"] = core_usage

        # CPU metadata (vendor/packages) for richer UI details.
        cpu_vendor, cpu_packages = self._read_cpu_metadata()
        if cpu_vendor:
            stats["sys_cpu_vendor"] = cpu_vendor
        if cpu_packages is not None:
            stats["sys_cpu_packages"] = cpu_packages

        stats["sys_time"] = time.time()
        return stats

    def _read_cpu_metadata(self):
        vendor = None
        packages = set()
        try:
            with open("/proc/cpuinfo", "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    low = line.lower()
                    if low.startswith("vendor_id"):
                        vendor = line.split(":", 1)[1].strip()
                    elif low.startswith("physical id"):
                        try:
                            packages.add(int(line.split(":", 1)[1].strip()))
                        except Exception:
                            pass
        except Exception:
            return vendor, None
        if packages:
            return vendor, len(packages)
        return vendor, 1 if vendor else None

    def _read_cpu_core_usage(self):
        try:
            with open("/proc/stat", "r", encoding="utf-8", errors="ignore") as f:
                lines = [ln.strip() for ln in f if ln.startswith("cpu")]
        except Exception:
            return []

        core_lines = [ln for ln in lines if ln.startswith("cpu") and len(ln) > 3 and ln[3].isdigit()]
        if not core_lines:
            return []

        curr_map = {}
        for ln in core_lines:
            parts = ln.split()
            name = parts[0]
            nums = [int(x) for x in parts[1:] if x.isdigit()]
            if len(nums) < 4:
                continue
            total = sum(nums)
            idle = nums[3] + (nums[4] if len(nums) > 4 else 0)
            curr_map[name] = (total, idle)

        if not curr_map:
            return []

        cpu_count = os.cpu_count() or len(curr_map)
        expected_names = [f"cpu{i}" for i in range(int(cpu_count))]

        out = []
        prev_map = self._cpu_prev_cores if isinstance(self._cpu_prev_cores, dict) else {}
        for name in expected_names:
            cur = curr_map.get(name)
            prev = prev_map.get(name)

            # If the core is temporarily missing in /proc/stat (offline/hotplug), keep a zero plot.
            if cur is None:
                if prev is not None:
                    out.append({"name": name, "usage": 0.0})
                continue

            total, idle = cur
            if prev is None:
                # First sample for this core: expose graph immediately with zero baseline.
                out.append({"name": name, "usage": 0.0})
            else:
                prev_total, prev_idle = prev
                dt = total - prev_total
                di = idle - prev_idle
                usage = 0.0
                if dt > 0:
                    usage = 100.0 * (1.0 - float(di) / float(dt))
                out.append({"name": name, "usage": max(0.0, min(100.0, usage))})

        next_prev = dict(prev_map)
        next_prev.update(curr_map)
        self._cpu_prev_cores = next_prev
        return out

    def _read_text(self, path):
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                return f.read().strip()
        except Exception:
            return ""

    def _gpu_name_from_slot(self, slot):
        if not slot:
            return ""
        if slot in self._gpu_name_cache:
            return self._gpu_name_cache[slot]
        if shutil.which("lspci"):
            try:
                out = subprocess.check_output(
                    ["lspci", "-s", slot],
                    text=True,
                    stderr=subprocess.DEVNULL,
                ).strip()
                if out:
                    name = out.split(": ", 1)[1].strip() if ": " in out else out
                    self._gpu_name_cache[slot] = name
                    return name
            except Exception:
                pass
        self._gpu_name_cache[slot] = ""
        return ""

    def _gpu_key(self, card_id, slot, vendor_id, device_id):
        slot_s = str(slot or "").strip().lower()
        if slot_s:
            return slot_s
        ven = str(vendor_id or "").strip().lower()
        dev = str(device_id or "").strip().lower()
        if ven or dev:
            return f"{ven}:{dev}:{card_id}"
        return str(card_id or "").strip().lower()

    def _merge_gpu_item(self, existing, incoming):
        # Merge telemetry from multiple DRM nodes that can point to the same physical GPU.
        if not isinstance(existing, dict):
            return dict(incoming)
        out = dict(existing)
        for key in ("slot", "driver", "vendor_id", "device_id"):
            if not out.get(key) and incoming.get(key):
                out[key] = incoming.get(key)

        n_old = str(out.get("name") or "").strip()
        n_new = str(incoming.get("name") or "").strip()
        if not n_old and n_new:
            out["name"] = n_new
        elif n_new and (n_old.lower().startswith("card") and not n_new.lower().startswith("card")):
            out["name"] = n_new

        l_old = out.get("load")
        l_new = incoming.get("load")
        if l_old is None and l_new is not None:
            out["load"] = l_new
        elif l_new is not None and l_old is not None:
            out["load"] = max(float(l_old), float(l_new))

        t_old = out.get("temp")
        t_new = incoming.get("temp")
        if t_old is None and t_new is not None:
            out["temp"] = t_new
        elif t_new is not None and t_old is not None:
            out["temp"] = max(float(t_old), float(t_new))

        cards = set(out.get("cards") or [])
        cards.update(incoming.get("cards") or [])
        out["cards"] = sorted(cards)
        return out

    def _read_gpu_stats_all(self):
        by_gpu = {}
        for card in sorted(glob.glob("/sys/class/drm/card[0-9]*")):
            dev = os.path.join(card, "device")
            if not os.path.isdir(dev):
                continue

            card_id = os.path.basename(card)
            uevent = self._read_text(os.path.join(dev, "uevent"))
            slot = ""
            for line in uevent.splitlines():
                if line.startswith("PCI_SLOT_NAME="):
                    slot = line.split("=", 1)[1].strip()
                    break
            gpu_name = self._gpu_name_from_slot(slot) or card_id
            gpu_driver = None
            drv_link = os.path.join(dev, "driver")
            if os.path.islink(drv_link):
                try:
                    gpu_driver = os.path.basename(os.path.realpath(drv_link))
                except Exception:
                    gpu_driver = None
            vendor_id = self._read_text(os.path.join(dev, "vendor")) or None
            device_id = self._read_text(os.path.join(dev, "device")) or None

            load = None
            for p in (
                os.path.join(dev, "gpu_busy_percent"),
                os.path.join(dev, "usage"),
            ):
                raw = self._read_text(p)
                if raw:
                    try:
                        load = float(raw)
                        break
                    except Exception:
                        pass
            temp = None
            hw_paths = glob.glob(os.path.join(dev, "hwmon", "hwmon*", "temp*_input"))
            for p in hw_paths:
                raw = self._read_text(p)
                if not raw:
                    continue
                try:
                    v = float(raw)
                    if v > 1000:
                        v = v / 1000.0
                    if 0.0 <= v <= 140.0:
                        temp = max(temp, v) if temp is not None else v
                except Exception:
                    pass

            gpu_id = self._gpu_key(card_id, slot, vendor_id, device_id)
            item = {
                "id": gpu_id,
                "name": gpu_name,
                "load": load,
                "temp": temp,
                "slot": slot or None,
                "driver": gpu_driver,
                "vendor_id": vendor_id,
                "device_id": device_id,
                "cards": [card_id],
            }
            prev = by_gpu.get(gpu_id)
            by_gpu[gpu_id] = self._merge_gpu_item(prev, item)

        out = list(by_gpu.values())
        out.sort(key=lambda x: str(x.get("id") or ""))
        return out

    def _read_bluetooth_stats_all(self):
        base = "/sys/class/bluetooth"
        if not os.path.isdir(base):
            return {}

        adapters = sorted([x for x in os.listdir(base) if x.startswith("hci")])
        if not adapters:
            return {}

        now = time.time()
        prev_time = self._bt_prev_time
        elapsed = (now - prev_time) if prev_time is not None else 0.0

        current = {}
        out = {}
        connected_count = self._read_bt_connected_count_cached(now)
        for adapter in adapters:
            stat_dir = os.path.join(base, adapter, "statistics")
            rx_path = os.path.join(stat_dir, "rx_bytes")
            tx_path = os.path.join(stat_dir, "tx_bytes")
            if not (os.path.isfile(rx_path) and os.path.isfile(tx_path)):
                continue

            try:
                with open(rx_path, "r", encoding="utf-8", errors="ignore") as f:
                    rx_bytes = int((f.read() or "0").strip() or "0")
                with open(tx_path, "r", encoding="utf-8", errors="ignore") as f:
                    tx_bytes = int((f.read() or "0").strip() or "0")
            except Exception:
                continue

            current[adapter] = {"rx_bytes": rx_bytes, "tx_bytes": tx_bytes}

            prev = self._bt_prev_bytes.get(adapter)
            rx_mbps = 0.0
            tx_mbps = 0.0
            if prev and elapsed > 0.0001:
                d_rx = max(0, rx_bytes - int(prev.get("rx_bytes", 0)))
                d_tx = max(0, tx_bytes - int(prev.get("tx_bytes", 0)))
                rx_bps = float(d_rx) / elapsed
                tx_bps = float(d_tx) / elapsed
                rx_mbps = max(0.0, (rx_bps * 8.0) / 1_000_000.0)
                tx_mbps = max(0.0, (tx_bps * 8.0) / 1_000_000.0)

            # Optional friendly name from controller directory.
            adapter_name = adapter
            name_path = os.path.join(base, adapter, "device", "name")
            if os.path.isfile(name_path):
                try:
                    with open(name_path, "r", encoding="utf-8", errors="ignore") as f:
                        nm = (f.read() or "").strip()
                    if nm:
                        adapter_name = nm
                except Exception:
                    pass

            adapter_addr = self._read_text(os.path.join(base, adapter, "address")) or None
            driver, chipset = self._read_bt_driver_chipset(adapter)
            rfkill_blocked = self._read_bt_rfkill_blocked(adapter)

            out[adapter] = {
                "name": adapter_name,
                "rx_mbps": rx_mbps,
                "tx_mbps": tx_mbps,
                "mbps": rx_mbps + tx_mbps,
                "address": adapter_addr,
                "driver": driver,
                "chipset": chipset,
                "rfkill_blocked": rfkill_blocked,
                "connected_devices": connected_count,
            }

        self._bt_prev_bytes = current
        self._bt_prev_time = now
        return out

    def _read_bt_connected_count_cached(self, now_ts):
        if (now_ts - float(self._bt_connected_cache_ts)) < 5.0:
            return self._bt_connected_cache_val
        self._bt_connected_cache_ts = now_ts
        self._bt_connected_cache_val = self._read_bt_connected_count()
        return self._bt_connected_cache_val

    def _read_bt_connected_count(self):
        if not shutil.which("bluetoothctl"):
            return None
        try:
            proc = subprocess.run(
                ["bluetoothctl", "devices", "Connected"],
                capture_output=True,
                text=True,
                timeout=0.8,
            )
            if proc.returncode != 0:
                return None
            lines = [ln for ln in (proc.stdout or "").splitlines() if ln.strip()]
            return len(lines)
        except Exception:
            return None

    def _read_bt_driver_chipset(self, adapter):
        dev = os.path.join("/sys/class/bluetooth", adapter, "device")
        driver = None
        chipset = None
        uevent_path = os.path.join(dev, "uevent")
        modalias_path = os.path.join(dev, "modalias")
        try:
            if os.path.isfile(uevent_path):
                with open(uevent_path, "r", encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        if line.startswith("DRIVER="):
                            driver = line.split("=", 1)[1].strip() or None
                            break
        except Exception:
            pass

        modalias = self._read_text(modalias_path)
        if modalias:
            m = modalias.lower()
            if m.startswith("usb:"):
                # usb:v0A12p0001...
                v_idx = m.find("v")
                p_idx = m.find("p")
                if v_idx >= 0 and p_idx > v_idx + 1:
                    ven = m[v_idx + 1 : p_idx]
                    prod = m[p_idx + 1 : p_idx + 5]
                    if ven and prod:
                        chipset = f"usb:{ven}:{prod}"
            elif m.startswith("pci:"):
                # pci:v00008086d0000....
                v_pos = m.find("v")
                d_pos = m.find("d")
                if v_pos >= 0 and d_pos > v_pos + 1:
                    ven = m[v_pos + 5 : d_pos]
                    dev_id = m[d_pos + 5 : d_pos + 9]
                    if ven and dev_id:
                        chipset = f"pci:{ven}:{dev_id}"
        return driver, chipset

    def _read_bt_rfkill_blocked(self, adapter):
        rfkill_root = "/sys/class/rfkill"
        if not os.path.isdir(rfkill_root):
            return None
        for name in os.listdir(rfkill_root):
            base = os.path.join(rfkill_root, name)
            nm = self._read_text(os.path.join(base, "name")).lower()
            if adapter.lower() not in nm:
                continue
            soft = self._read_text(os.path.join(base, "soft"))
            hard = self._read_text(os.path.join(base, "hard"))
            try:
                return (int(soft or "0") == 1) or (int(hard or "0") == 1)
            except Exception:
                return None
        return None

    def _read_net_iface_meta(self, interfaces):
        out = {}
        if not isinstance(interfaces, list):
            return out
        for iface in interfaces:
            if not iface:
                continue
            dev = os.path.join("/sys/class/net", iface, "device")
            if not os.path.isdir(dev):
                continue
            slot = None
            driver = None
            vendor_id = self._read_text(os.path.join(dev, "vendor")) or None
            device_id = self._read_text(os.path.join(dev, "device")) or None
            uevent = self._read_text(os.path.join(dev, "uevent"))
            for line in uevent.splitlines():
                if line.startswith("PCI_SLOT_NAME="):
                    slot = line.split("=", 1)[1].strip()
                elif line.startswith("DRIVER="):
                    driver = line.split("=", 1)[1].strip()
            out[str(iface)] = {
                "slot": slot,
                "driver": driver,
                "vendor_id": vendor_id,
                "device_id": device_id,
            }
        return out

class CppHandler2(QObject):
    def __init__(self, bridge1, console_logic=None):
        super().__init__()
        self.bridge1 = bridge1
        self.console = console_logic
        self.watchdog_enabled = True
        
        # Inicjalizacja Workera i podpięcie jego błędów do logowania
        self.worker = CppEngineWorker(self.bridge1)
        self.worker.error_signal.connect(self._on_worker_error)
        
        # Timer sterujący częstotliwością odświeżania
        self.refresh_timer = QTimer()
        self.refresh_timer.timeout.connect(self.worker.perform_check)
        
        self._log("CppHandler2: Execution Manager ready.", "BOOT")

    def _log(self, message, level="SYSTEM"):
        """Wysyła info do konsoli F12."""
        if self.console:
            self.console.log(message, level)
        else:
            print(f"[{level}] {message}")

    def _on_worker_error(self, msg):
        text = str(msg or "")
        if text.startswith("[WARN]"):
            self._log(text[6:].strip(), "WARN")
        elif text.startswith("[SUCCESS]"):
            self._log(text[9:].strip(), "SUCCESS")
        elif text.startswith("[INFO]"):
            self._log(text[6:].strip(), "INFO")
        else:
            self._log(text, "ERROR")

    def setup_monitoring(self, engines_list):
        """
        Definiuje, które silniki mają być śledzone. 
        Przyjmuje listę z auto_discover_hardware() z Handlera 1.
        """
        self.worker.active_engines = engines_list
        self._log(f"Monitoring active for: {', '.join(engines_list)}", "INFO")

    def start(self, interval_ms=1000):
        """Uruchamia pętlę monitoringu."""
        if not self.worker.active_engines:
            self._log("No linked engines: running Python fallback collectors.", "WARN")

        self.worker.is_active = True
        self.refresh_timer.start(interval_ms)
        self._log(f"Real-time data stream started [{interval_ms}ms]", "SUCCESS")

    def stop(self):
        """Zatrzymuje pętlę."""
        self.worker.is_active = False
        self.refresh_timer.stop()
        self._log("Data stream paused.", "WARN")

    def set_speed(self, interval_ms):
        """Dynamiczna zmiana prędkości odświeżania (np. z ustawień UI)."""
        if self.refresh_timer.isActive():
            self.refresh_timer.start(interval_ms)
            self._log(f"Update interval changed to {interval_ms}ms", "INFO")

    def bind_to_dashboard(self, callback_function):
        """Łączy sygnał danych bezpośrednio z funkcją update_widgets w UI."""
        self.worker.data_ready.connect(callback_function)
