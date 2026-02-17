# pyright: reportAttributeAccessIssue=false
import glob
import os
import re
import shutil
import subprocess
import time

from ui.widgets.graph_widget import GraphWidget


class MetricsMixin:
    def _log_psu_debug_snapshot(self, psu_all):
        if not isinstance(psu_all, dict):
            return
        if not hasattr(self, "console_logic") or self.console_logic is None:
            return
        now = time.time()
        last = float(getattr(self, "_psu_debug_last_log_ts", 0.0))
        if (now - last) < 2.0:
            return
        self._psu_debug_last_log_ts = now

        source = str(psu_all.get("source") or "none")
        total_w = float(psu_all.get("total_w", 0.0) or 0.0)
        cats = {
            "cpu": float(psu_all.get("cpu_w", 0.0) or 0.0),
            "gpu": float(psu_all.get("gpu_w", 0.0) or 0.0),
            "disk": float(psu_all.get("disk_w", 0.0) or 0.0),
            "board": float(psu_all.get("board_w", 0.0) or 0.0),
            "memory": float(psu_all.get("memory_w", 0.0) or 0.0),
            "net": float(psu_all.get("net_w", 0.0) or 0.0),
            "other": float(psu_all.get("other_w", 0.0) or 0.0),
        }
        non_zero = [f"{k}={v:.2f}W" for k, v in cats.items() if v > 0.0]
        cat_txt = ", ".join(non_zero) if non_zero else "all=0W"

        src = psu_all.get("sources") or {}
        top_txt = "none"
        if isinstance(src, dict) and src:
            pairs = []
            for name, value in src.items():
                try:
                    pairs.append((str(name), float(value)))
                except Exception:
                    continue
            pairs.sort(key=lambda x: x[1], reverse=True)
            top_txt = ", ".join([f"{n}={v:.2f}W" for n, v in pairs[:8]]) if pairs else "none"

        self.console_logic.log(
            f"PSU debug: total={total_w:.2f}W source={source} | categories[{cat_txt}] | sensors[{top_txt}]",
            "DEBUG",
        )

    def _normalize_gpu_name(self, name):
        if not name:
            return "GPU"
        txt = str(name).strip()
        txt = re.sub(r"\s*\(TM\)\s*", " ", txt, flags=re.IGNORECASE)
        txt = re.sub(r"\s*\(R\)\s*", " ", txt, flags=re.IGNORECASE)
        txt = re.sub(r"\s*\[[^\]]+\]\s*", " ", txt)
        txt = re.sub(r"\s{2,}", " ", txt).strip(" -")
        low = txt.lower()
        # Common AMD Polaris ambiguous naming from PCI DB.
        if "rx 470/480/570/570x/580/580x/590" in low or "ellesmere" in low:
            return "AMD Radeon RX 500 Series (Polaris)"
        if low.startswith("mesa intel"):
            txt = txt.replace("Mesa", "").strip()
        return txt

    def _looks_like_storage_name(self, text):
        if not text:
            return False
        low = text.lower()
        storage_markers = (
            "nvme",
            "ssd",
            "hdd",
            "sata",
            "wdc",
            "sandisk",
            "seagate",
            "kingston",
            "sdbpnpz",
            "pc sn",
            "disk",
        )
        return any(marker in low for marker in storage_markers)

    def _metric_display_name(self, metric_name):
        tr = self.lang_handler.tr
        if metric_name == "cpu":
            return tr("graph_cpu_load")
        if metric_name == "ram":
            return tr("gauge_ram")
        if metric_name == "gpu":
            return tr("graph_gpu_load")
        if metric_name == "psu":
            return tr("graph_psu_power")
        if metric_name.startswith("gpu:"):
            return tr("graph_gpu_load")
        if metric_name == "net_total":
            return tr("graph_net_total")
        if metric_name == "cpu_temp":
            return tr("graph_cpu_temp")
        if metric_name == "gpu_temp":
            return tr("graph_gpu_temp")
        if metric_name.startswith("disk:"):
            return tr("graph_disk_usage")
        if metric_name.startswith("net:"):
            return tr("graph_net_iface")
        if metric_name.startswith("bt:"):
            return tr("graph_bt_iface")
        return metric_name

    def _metric_card_subtitle(self, metric_name):
        tr = self.lang_handler.tr
        if metric_name == "cpu":
            return self.cpu_name or tr("card_subtitle_cpu")
        if metric_name == "ram":
            total_kb = self.latest_sensor_values.get("sys_mem_total_kb")
            if total_kb:
                return f"{(float(total_kb) / 1024.0 / 1024.0):.1f} GB"
            return tr("card_subtitle_ram")
        if metric_name == "gpu":
            return self.gpu_name or tr("card_subtitle_gpu")
        if metric_name == "psu":
            mode = self.get_power_mode_resolved() if hasattr(self, "get_power_mode_resolved") else "auto"
            psu_all = self.latest_sensor_values.get("psu_all") or {}
            total_src = str(psu_all.get("source") or "").strip().lower()
            if mode == "laptop":
                if total_src == "battery":
                    return tr("power_subtitle_battery")
                return tr("power_subtitle_laptop")
            if mode == "desktop":
                return tr("power_subtitle_desktop")
            if total_src == "components":
                return tr("power_subtitle_components")
            if total_src == "battery":
                return tr("power_subtitle_battery")
            return tr("power_subtitle_auto")
        if metric_name.startswith("gpu:"):
            gpu_id = metric_name.split(":", 1)[1]
            for item in self.latest_sensor_values.get("gpu_all", []):
                if item.get("id") == gpu_id:
                    return item.get("name") or gpu_id
            return gpu_id
        if metric_name == "net_total":
            return tr("card_subtitle_net_total")
        if metric_name.startswith("disk:"):
            return metric_name.split(":", 1)[1]
        if metric_name.startswith("net:"):
            iface = metric_name.split(":", 1)[1]
            merge = (self.latest_sensor_values.get("net_bt_merge") or {}).get(iface, {})
            if merge.get("merged", False):
                return f"{self._net_iface_kind(iface)} + BT ({iface})"
            return f"{self._net_iface_kind(iface)} ({iface})"
        if metric_name.startswith("bt:"):
            adapter = metric_name.split(":", 1)[1]
            bt_all = self.latest_sensor_values.get("bt_all") or {}
            if isinstance(bt_all, dict):
                item = bt_all.get(adapter) or {}
                bt_name = str(item.get("name") or "").strip()
                if bt_name and bt_name != adapter:
                    addr = str(item.get("address") or "").strip()
                    if addr:
                        return f"{bt_name} ({addr})"
                    return f"{bt_name} ({adapter})"
            return adapter
        return self._metric_device_info(metric_name)

    def _net_iface_kind(self, iface):
        tr = self.lang_handler.tr
        wireless_path = f"/sys/class/net/{iface}/wireless"
        if os.path.isdir(wireless_path) or iface.startswith(("wl", "wlan")):
            return tr("net_kind_wifi")
        if iface.startswith(("ww", "wwan")):
            return tr("net_kind_mobile")
        if iface.startswith(("en", "eth", "eno", "enp")):
            return tr("net_kind_ethernet")
        return tr("net_kind_interface")

    def _metric_accent(self, metric_name):
        if metric_name == "cpu":
            return "#42c7f5"
        if metric_name == "ram":
            return "#59d29b"
        if metric_name == "gpu":
            return "#f58f6a"
        if metric_name == "psu":
            return "#e9b44c"
        if metric_name.startswith("gpu:"):
            return "#f58f6a"
        if metric_name == "cpu_temp":
            return "#ffd166"
        if metric_name == "gpu_temp":
            return "#ff7b72"
        if metric_name == "net_total":
            return "#d38cff"
        if metric_name.startswith("disk:"):
            return "#8fb1ff"
        if metric_name.startswith("net:"):
            return "#c99dff"
        if metric_name.startswith("bt:"):
            return "#7cc4ff"
        return "#4ec9b0"

    def _metric_locked(self, metric_name):
        if metric_name.startswith("disk:"):
            return False
        if metric_name.startswith("net:") or metric_name == "net_total":
            return False
        if metric_name.startswith("bt:"):
            return False
        if metric_name == "psu":
            return False
        if metric_name.startswith("gpu:"):
            return self.metric_locks.get("gpu", True)
        return self.metric_locks.get(metric_name, False)

    def _metric_device_info(self, metric_name):
        if metric_name == "cpu":
            return self.cpu_name or "CPU"
        if metric_name == "ram":
            return "RAM"
        if metric_name == "gpu":
            return self.gpu_name or "GPU"
        if metric_name == "psu":
            mode = self.get_power_mode_resolved() if hasattr(self, "get_power_mode_resolved") else "auto"
            if mode == "laptop":
                return self.lang_handler.tr("power_mode_laptop")
            if mode == "desktop":
                return self.lang_handler.tr("power_mode_desktop")
            return self.lang_handler.tr("power_mode_auto")
        if metric_name.startswith("gpu:"):
            gpu_id = metric_name.split(":", 1)[1]
            for item in self.latest_sensor_values.get("gpu_all", []):
                if item.get("id") == gpu_id:
                    return item.get("name") or gpu_id
            return gpu_id
        if metric_name == "net_total":
            return "Network"
        if metric_name == "cpu_temp":
            return "CPU Sensor"
        if metric_name == "gpu_temp":
            return "GPU Sensor"
        if metric_name.startswith("disk:"):
            return metric_name.split(":", 1)[1]
        if metric_name.startswith("net:"):
            return metric_name.split(":", 1)[1]
        if metric_name.startswith("bt:"):
            adapter = metric_name.split(":", 1)[1]
            bt_all = self.latest_sensor_values.get("bt_all") or {}
            if isinstance(bt_all, dict):
                item = bt_all.get(adapter) or {}
                bt_name = str(item.get("name") or "").strip()
                if bt_name:
                    return bt_name
            return adapter
        return "System"

    def _format_value(self, value, unit):
        if unit == "%":
            return f"{int(round(float(value)))}%"
        if unit == "C":
            return f"{float(value):.1f} C"
        if unit == "Mbps":
            v = float(value)
            if v < 10.0:
                return f"{v:.2f} Mbps"
            return f"{v:.1f} Mbps"
        if unit == "W":
            v = float(value)
            if v < 10.0:
                return f"{v:.2f} W"
            return f"{v:.1f} W"
        return f"{float(value):.1f} {unit}"

    def _format_uptime(self, seconds):
        if seconds is None:
            return "-"
        total = int(max(0, float(seconds)))
        d, rem = divmod(total, 86400)
        h, rem = divmod(rem, 3600)
        m, s = divmod(rem, 60)
        if d > 0:
            return f"{d}d {h:02}:{m:02}:{s:02}"
        return f"{h:02}:{m:02}:{s:02}"

    def _detect_cpu_name(self):
        try:
            with open("/proc/cpuinfo", "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    if line.lower().startswith("model name"):
                        model = line.split(":", 1)[1].strip()
                        model = re.sub(r"\s*\(R\)\s*", " ", model, flags=re.IGNORECASE)
                        model = re.sub(r"\s*\(TM\)\s*", " ", model, flags=re.IGNORECASE)
                        model = re.sub(r"\s{2,}", " ", model).strip()
                        return model
        except Exception:
            pass
        if shutil.which("lscpu"):
            try:
                out = subprocess.check_output(
                    ["sh", "-lc", "lscpu | grep -m1 'Model name:'"],
                    text=True,
                    stderr=subprocess.DEVNULL,
                ).strip()
                if ":" in out:
                    return out.split(":", 1)[1].strip()
            except Exception:
                pass
        return "CPU"

    def _detect_gpu_name(self):
        # 1) Prefer runtime renderer string (usually closest to user-facing model name).
        if shutil.which("glxinfo"):
            try:
                out = subprocess.check_output(
                    ["sh", "-lc", "glxinfo -B 2>/dev/null | grep -m1 'OpenGL renderer string'"],
                    text=True,
                    stderr=subprocess.DEVNULL,
                ).strip()
                if ":" in out:
                    candidate = out.split(":", 1)[1].strip()
                    if candidate and not self._looks_like_storage_name(candidate):
                        return self._normalize_gpu_name(candidate)
            except Exception:
                pass

        if shutil.which("vulkaninfo"):
            try:
                out = subprocess.check_output(
                    ["sh", "-lc", "vulkaninfo --summary 2>/dev/null | grep -m1 'GPU id'"],
                    text=True,
                    stderr=subprocess.DEVNULL,
                ).strip()
                if ":" in out:
                    candidate = out.split(":", 1)[1].strip()
                    if candidate and not self._looks_like_storage_name(candidate):
                        return self._normalize_gpu_name(candidate)
            except Exception:
                pass

        # 2) PCI fallback
        if shutil.which("lspci"):
            try:
                out = subprocess.check_output(
                    [
                        "sh",
                        "-lc",
                        "lspci -nn | grep -E 'VGA compatible controller|3D controller|Display controller' | head -n1",
                    ],
                    text=True,
                    stderr=subprocess.DEVNULL,
                ).strip()
                if out:
                    if ": " in out:
                        candidate = out.split(": ", 1)[1].strip()
                    else:
                        parts = out.split(" ", 1)
                        candidate = parts[1].strip() if len(parts) > 1 else out
                    if candidate and not self._looks_like_storage_name(candidate):
                        return self._normalize_gpu_name(candidate)
            except Exception:
                pass

        # 3) sysfs fallback
        for card in sorted(glob.glob("/sys/class/drm/card[0-9]*")):
            product = os.path.join(card, "device", "product_name")
            if os.path.isfile(product):
                try:
                    val = open(product, "r", encoding="utf-8", errors="ignore").read().strip()
                    if val and not self._looks_like_storage_name(val):
                        return self._normalize_gpu_name(val)
                except Exception:
                    pass
        return "GPU"

    def _is_dynamic_metric(self, metric_name):
        return metric_name.startswith("disk:") or metric_name.startswith("net:") or metric_name.startswith("bt:")

    def _is_value_active(self, metric_name, value):
        val = abs(float(value))
        if metric_name.startswith("net:"):
            return val >= 0.02
        if metric_name.startswith("disk:"):
            return val >= 0.3
        if metric_name.startswith("bt:"):
            return val >= 0.001
        return val > 0.0

    def _remove_metric_card(self, metric_name, fallback_metric):
        parts = self.metric_cards.get(metric_name)
        if not parts:
            return
        card = parts["card"]
        self.sidebar_layout.removeWidget(card)
        card.setParent(None)
        del self.metric_cards[metric_name]
        if hasattr(self, "_refresh_metric_separators"):
            self._refresh_metric_separators()
        if self.selected_metric == metric_name:
            self.selected_metric = fallback_metric
            self._select_metric(self.selected_metric)

    def _set_metric_value(self, metric_name, value):
        parts = self.metric_cards.get(metric_name)
        if not parts:
            return
        now = time.time()
        self.metric_last_seen[metric_name] = now
        if self._is_value_active(metric_name, value):
            self.metric_last_active[metric_name] = now
        parts["last"] = float(value)
        parts["seen"] = True
        self._set_card_subtitle(metric_name, self._metric_card_subtitle(metric_name))
        parts["spark"].add_value(float(value))
        parts["value"].setText(self._format_value(value, parts["unit"]))

        if self.selected_metric == metric_name:
            self.primary_graph.data = list(parts["spark"].data)
            self.primary_graph.recent_raw = list(parts["spark"].recent_raw)
            self.primary_graph.update()
            self._refresh_primary_info(metric_name)

    def _select_metric(self, metric_name):
        if metric_name not in self.metric_cards:
            return

        self.selected_metric = metric_name
        for name, parts in self.metric_cards.items():
            parts["card"].setObjectName("metricCardActive" if name == metric_name else "metricCard")
            parts["card"].style().unpolish(parts["card"])
            parts["card"].style().polish(parts["card"])

        parts = self.metric_cards[metric_name]
        self._set_primary_title(self._metric_display_name(metric_name))
        self._set_primary_subtitle(self._metric_device_info(metric_name))

        self.primary_graph.label = self._metric_display_name(metric_name)
        self.primary_graph.unit = parts["unit"]
        self.primary_graph.max_value = parts["max"]
        self.primary_graph.set_accent_color(parts.get("accent", "#4ec9b0"))
        self.primary_graph.data = list(parts["spark"].data)
        self.primary_graph.recent_raw = list(parts["spark"].recent_raw)
        self.primary_graph.set_blocked(
            self._metric_locked(metric_name),
            self.lang_handler.tr("graph_blocked_no_permissions"),
        )
        self.primary_graph.setStyleSheet(self._primary_graph_style(parts.get("accent", "#31405b")))
        self.primary_graph.update()

        detail_mode = metric_name if metric_name in ("cpu", "psu") else None
        show_primary_graph = detail_mode is None
        self.primary_graph.setVisible(show_primary_graph)
        self.graph_separator.setVisible(show_primary_graph)
        self.cpu_cores_scroll.setVisible(detail_mode is not None)
        if detail_mode == "cpu":
            self._render_cpu_core_graphs()
        elif detail_mode == "psu":
            self._render_power_sensor_graphs()
        else:
            self._clear_detail_layout()
        self._refresh_primary_info(metric_name)

    def _clear_cpu_core_graphs(self):
        for widget in self.cpu_core_graphs.values():
            widget.setParent(None)
        self.cpu_core_graphs.clear()

    def _clear_power_sensor_graphs(self):
        for widget in self.power_sensor_graphs.values():
            widget.setParent(None)
        self.power_sensor_graphs.clear()

    def _clear_detail_layout(self):
        while self.cpu_cores_layout.count():
            item = self.cpu_cores_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.setParent(None)

    def _power_sensor_accent(self, name):
        low = str(name or "").lower()
        if "gpu" in low or "amdgpu" in low or "nvidia" in low:
            return "#f58f6a"
        if "rapl" in low or "cpu" in low or "package" in low:
            return "#42c7f5"
        if "disk" in low or "nvme" in low:
            return "#8fb1ff"
        if "net" in low or "wifi" in low or "ethernet" in low:
            return "#c99dff"
        if "board" in low or "chipset" in low or "soc" in low or "vrm" in low:
            return "#ffd166"
        return "#4ec9b0"

    def _render_cpu_core_graphs(self):
        self._clear_detail_layout()
        cols = 4
        idx = 0
        for core_name in sorted(
            self.cpu_core_graphs.keys(),
            key=lambda n: int(n[3:]) if n.startswith("cpu") and n[3:].isdigit() else n,
        ):
            row = idx // cols
            col = idx % cols
            self.cpu_cores_layout.addWidget(self.cpu_core_graphs[core_name], row, col)
            idx += 1

    def _render_power_sensor_graphs(self):
        self._clear_detail_layout()
        cols = 2
        idx = 0
        for sensor_name in sorted(self.power_sensor_graphs.keys()):
            row = idx // cols
            col = idx % cols
            self.cpu_cores_layout.addWidget(self.power_sensor_graphs[sensor_name], row, col)
            idx += 1

    def _update_cpu_core_graphs(self, core_usage):
        if not isinstance(core_usage, list):
            return
        incoming_names = [str(item.get("name")) for item in core_usage if isinstance(item, dict) and item.get("name")]
        incoming_set = set(incoming_names)
        existing_set = set(self.cpu_core_graphs.keys())

        for name in list(existing_set - incoming_set):
            widget = self.cpu_core_graphs.pop(name)
            widget.setParent(None)

        for item in core_usage:
            if not isinstance(item, dict):
                continue
            core_name = str(item.get("name", "")).strip()
            if not core_name:
                continue
            usage = float(item.get("usage", 0.0))

            graph = self.cpu_core_graphs.get(core_name)
            if graph is None:
                graph = GraphWidget(label=core_name, unit="%", max_value=100.0, peak_window=1, max_points=40)
                graph.setMinimumHeight(64)
                graph.setMaximumHeight(64)
                graph.setStyleSheet(self._spark_style())
                graph.set_accent_color("#42c7f5")
                graph.update_theme(self._theme_is_dark())
                self.cpu_core_graphs[core_name] = graph
            graph.add_value(usage)

        if self.selected_metric == "cpu":
            self._render_cpu_core_graphs()

    def _update_power_sensor_graphs(self, psu_all):
        if not isinstance(psu_all, dict):
            return
        tr = self.lang_handler.tr
        incoming = {}

        # Always-visible category totals so CPU/board/disk are present in the Power tab.
        category_defs = [
            ("cat:cpu", tr("details_power_cpu"), "cpu_w"),
            ("cat:gpu", tr("details_power_gpu"), "gpu_w"),
            ("cat:disk", tr("details_power_disk"), "disk_w"),
            ("cat:board", tr("details_power_board"), "board_w"),
            ("cat:memory", tr("details_power_memory"), "memory_w"),
            ("cat:net", tr("details_power_net"), "net_w"),
            ("cat:other", tr("details_power_other"), "other_w"),
        ]
        for key, label, src_key in category_defs:
            try:
                watts = max(0.0, float(psu_all.get(src_key, 0.0)))
            except Exception:
                watts = 0.0
            incoming[key] = {"label": label, "watts": watts}

        # Raw sensor channels from kernel/sysfs as extra detailed plots.
        sources = psu_all.get("sources") or {}
        if isinstance(sources, dict):
            for src_name, value in sources.items():
                try:
                    watts = max(0.0, float(value))
                except Exception:
                    continue
                sensor_key = f"sensor:{src_name}"
                incoming[sensor_key] = {"label": str(src_name), "watts": watts, "blocked": False}

        blocked_sources = psu_all.get("blocked_sources") or []
        if isinstance(blocked_sources, list):
            for src_name in blocked_sources:
                name = str(src_name or "").strip()
                if not name:
                    continue
                sensor_key = f"sensor:{name}"
                # Keep real sensor when available; otherwise show blocked placeholder.
                if sensor_key in incoming:
                    continue
                incoming[sensor_key] = {"label": name, "watts": 0.0, "blocked": True}

        existing = set(self.power_sensor_graphs.keys())
        incoming_set = set(incoming.keys())
        for removed in list(existing - incoming_set):
            widget = self.power_sensor_graphs.pop(removed)
            widget.setParent(None)

        for sensor_name in sorted(incoming.keys()):
            payload = incoming[sensor_name]
            label = str(payload.get("label", sensor_name))
            watts = float(payload.get("watts", 0.0))
            is_blocked = bool(payload.get("blocked", False))
            graph = self.power_sensor_graphs.get(sensor_name)
            if graph is None:
                graph = GraphWidget(label=label, unit="W", max_value=None, peak_window=2, max_points=50)
                graph.setMinimumHeight(80)
                graph.setMaximumHeight(80)
                graph.setStyleSheet(self._spark_style())
                graph.set_accent_color(self._power_sensor_accent(label))
                graph.update_theme(self._theme_is_dark())
                self.power_sensor_graphs[sensor_name] = graph
            else:
                graph.label = label
            graph.set_blocked(is_blocked, self.lang_handler.tr("metric_password_required"))
            if not is_blocked:
                graph.add_value(watts)

        if self.selected_metric == "psu":
            self._render_power_sensor_graphs()

    def _refresh_primary_info(self, metric_name):
        tr = self.lang_handler.tr
        parts = self.metric_cards.get(metric_name)
        if not parts:
            return
        advanced = bool(getattr(self, "advanced_details_enabled", True))

        if not parts.get("seen", False):
            current_value = self.lang_handler.tr("value_na")
        else:
            current_value = parts["value"].text()
        status = tr("graph_blocked_no_permissions") if self._metric_locked(metric_name) else tr("details_live")

        left_lines = [
            tr("window_title"),
            self._metric_display_name(metric_name),
            f"{tr('details_value_label')}: {current_value}",
            f"{tr('details_sample_label')}: {self.poll_interval_ms} ms",
        ]
        scale_text = tr("details_scale_auto") if parts["max"] is None else f"0-{int(parts['max'])}"
        right_lines = [
            f"{tr('details_status_label')}: {status}",
            f"{tr('details_unit_label')}: {parts['unit']}",
            f"{tr('details_scale_label')}: {scale_text}",
            f"{tr('details_source_label')}: {self._metric_device_info(metric_name)}",
        ]

        if metric_name == "cpu":
            cpu_temp = self.latest_sensor_values.get("cpu_temp")
            cpu_temp_text = (
                tr("graph_blocked_no_permissions")
                if self.metric_locks.get("cpu_temp", True)
                else (self._format_value(cpu_temp, "C") if cpu_temp is not None else tr("details_not_available"))
            )
            right_lines.append(f"{tr('details_cpu_temp')}: {cpu_temp_text}")
            cpu_vendor = self.latest_sensor_values.get("sys_cpu_vendor")
            cpu_packages = self.latest_sensor_values.get("sys_cpu_packages")
            if cpu_vendor:
                if advanced:
                    right_lines.append(f"{tr('details_cpu_vendor')}: {cpu_vendor}")
            if cpu_packages is not None:
                if advanced:
                    right_lines.append(f"{tr('details_cpu_packages')}: {cpu_packages}")
        elif metric_name == "gpu" or metric_name.startswith("gpu:"):
            gpu_temp = self.latest_sensor_values.get("gpu_temp")
            gpu_item = None
            if metric_name.startswith("gpu:"):
                gpu_id = metric_name.split(":", 1)[1]
                for item in self.latest_sensor_values.get("gpu_all", []):
                    if item.get("id") == gpu_id:
                        gpu_item = item
                        gpu_temp = item.get("temp")
                        break
            elif self.latest_sensor_values.get("gpu_all"):
                gpu_item = self.latest_sensor_values.get("gpu_all")[0]
            gpu_temp_text = (
                tr("graph_blocked_no_permissions")
                if self.metric_locks.get("gpu_temp", True)
                else (self._format_value(gpu_temp, "C") if gpu_temp is not None else tr("details_not_available"))
            )
            right_lines.append(f"{tr('details_gpu_temp')}: {gpu_temp_text}")
            if gpu_item:
                gpu_driver = str(gpu_item.get("driver") or "").strip()
                gpu_slot = str(gpu_item.get("slot") or "").strip()
                gpu_vid = str(gpu_item.get("vendor_id") or "").strip()
                gpu_did = str(gpu_item.get("device_id") or "").strip()
                if advanced and gpu_driver:
                    right_lines.append(f"{tr('details_gpu_driver')}: {gpu_driver}")
                if advanced and gpu_slot:
                    right_lines.append(f"{tr('details_gpu_slot')}: {gpu_slot}")
                if advanced and (gpu_vid or gpu_did):
                    right_lines.append(f"{tr('details_gpu_pci_id')}: {gpu_vid} {gpu_did}".strip())
        elif metric_name == "ram":
            mem_total_kb = self.latest_sensor_values.get("sys_mem_total_kb")
            mem_available_kb = self.latest_sensor_values.get("sys_mem_available_kb")
            swap_total_kb = self.latest_sensor_values.get("sys_swap_total_kb")
            swap_free_kb = self.latest_sensor_values.get("sys_swap_free_kb")
            if mem_total_kb is not None and mem_available_kb is not None and mem_total_kb > 0:
                used_kb = max(0, mem_total_kb - mem_available_kb)
                used_gb = float(used_kb) / 1024.0 / 1024.0
                total_gb = float(mem_total_kb) / 1024.0 / 1024.0
                mem_pct = (used_kb / float(mem_total_kb)) * 100.0
                right_lines.append(f"{tr('details_mem_used')}: {used_gb:.1f}/{total_gb:.1f} GB ({mem_pct:.0f}%)")
            if advanced and swap_total_kb is not None and swap_free_kb is not None and swap_total_kb > 0:
                swap_used_kb = max(0, swap_total_kb - swap_free_kb)
                swap_used_gb = float(swap_used_kb) / 1024.0 / 1024.0
                swap_total_gb = float(swap_total_kb) / 1024.0 / 1024.0
                right_lines.append(f"{tr('details_swap_used')}: {swap_used_gb:.1f}/{swap_total_gb:.1f} GB")
        elif metric_name == "psu":
            psu_all = self.latest_sensor_values.get("psu_all") or {}
            if isinstance(psu_all, dict):
                has_battery = bool(psu_all.get("has_battery", False))
                ac_online = bool(psu_all.get("ac_online", False))
                source = str(psu_all.get("source") or "none")
                right_lines.append(f"{tr('details_power_mode')}: {self.lang_handler.tr(f'power_mode_{self.get_power_mode_resolved()}')}")
                right_lines.append(f"{tr('details_power_source')}: {source}")
                right_lines.append(f"{tr('details_power_ac')}: {tr('details_yes') if ac_online else tr('details_no')}")
                for key, lbl in (
                    ("cpu_w", "details_power_cpu"),
                    ("gpu_w", "details_power_gpu"),
                    ("disk_w", "details_power_disk"),
                    ("net_w", "details_power_net"),
                    ("board_w", "details_power_board"),
                    ("memory_w", "details_power_memory"),
                    ("other_w", "details_power_other"),
                ):
                    try:
                        value = float(psu_all.get(key, 0.0))
                    except Exception:
                        value = 0.0
                    if value > 0.0:
                        right_lines.append(f"{tr(lbl)}: {self._format_value(value, 'W')}")
                if has_battery:
                    cap = psu_all.get("battery_capacity_avg")
                    if cap is not None:
                        try:
                            right_lines.append(f"{tr('details_battery_level')}: {float(cap):.0f}%")
                        except Exception:
                            pass
                    batt_w = psu_all.get("battery_total_w")
                    if batt_w is not None:
                        try:
                            right_lines.append(f"{tr('details_battery_power')}: {self._format_value(float(batt_w), 'W')}")
                        except Exception:
                            pass
                sources = psu_all.get("sources")
                if advanced and isinstance(sources, dict) and sources:
                    pairs = []
                    for k, v in sources.items():
                        try:
                            pairs.append((str(k), float(v)))
                        except Exception:
                            continue
                    pairs.sort(key=lambda x: x[1], reverse=True)
                    if pairs:
                        right_lines.append(f"{tr('details_power_channels')}:")
                        for name, watts in pairs[:24]:
                            right_lines.append(f"{name}: {self._format_value(watts, 'W')}")
        elif metric_name == "net_total" or metric_name.startswith("net:"):
            rx = self._format_value(self.latest_sensor_values.get("net_rx", 0.0), "Mbps")
            tx = self._format_value(self.latest_sensor_values.get("net_tx", 0.0), "Mbps")
            right_lines.append(f"{tr('details_net_rx')}: {rx}")
            right_lines.append(f"{tr('details_net_tx')}: {tx}")
            if metric_name.startswith("net:"):
                iface = metric_name.split(":", 1)[1]
                merge = (self.latest_sensor_values.get("net_bt_merge") or {}).get(iface, {})
                if merge.get("merged", False):
                    bt_rx = self._format_value(float(merge.get("bt_rx_mbps", 0.0)), "Mbps")
                    bt_tx = self._format_value(float(merge.get("bt_tx_mbps", 0.0)), "Mbps")
                    right_lines.append(f"{tr('details_bt_rx')}: {bt_rx}")
                    right_lines.append(f"{tr('details_bt_tx')}: {bt_tx}")
                    names = ", ".join(merge.get("adapters", [])[:3])
                    if names:
                        right_lines.append(f"{tr('details_bt_adapters')}: {names}")
        elif metric_name.startswith("bt:"):
            adapter = metric_name.split(":", 1)[1]
            bt_all = self.latest_sensor_values.get("bt_all") or {}
            item = bt_all.get(adapter) if isinstance(bt_all, dict) else {}
            rx = self._format_value(float((item or {}).get("rx_mbps", 0.0)), "Mbps")
            tx = self._format_value(float((item or {}).get("tx_mbps", 0.0)), "Mbps")
            right_lines.append(f"{tr('details_bt_rx')}: {rx}")
            right_lines.append(f"{tr('details_bt_tx')}: {tx}")
            address = str((item or {}).get("address") or "").strip()
            if advanced and address:
                right_lines.append(f"{tr('details_bt_address')}: {address}")
            driver = str((item or {}).get("driver") or "").strip()
            if advanced and driver:
                right_lines.append(f"{tr('details_bt_driver')}: {driver}")
            chipset = str((item or {}).get("chipset") or "").strip()
            if advanced and chipset:
                right_lines.append(f"{tr('details_bt_chipset')}: {chipset}")
            rfkill = (item or {}).get("rfkill_blocked", None)
            if advanced and rfkill is True:
                right_lines.append(f"{tr('details_bt_rfkill')}: {tr('details_bt_state_blocked')}")
            elif advanced and rfkill is False:
                right_lines.append(f"{tr('details_bt_rfkill')}: {tr('details_bt_state_on')}")
            conn = (item or {}).get("connected_devices", None)
            if conn is not None:
                right_lines.append(f"{tr('details_bt_connected')}: {int(conn)}")

        uptime_s = self.latest_sensor_values.get("sys_uptime_s")
        if metric_name in ("cpu", "ram", "gpu"):
            left_lines.append(f"{tr('details_uptime')}: {self._format_uptime(uptime_s)}")
        elif metric_name.startswith("gpu:"):
            left_lines.append(f"{tr('details_uptime')}: {self._format_uptime(uptime_s)}")

        if metric_name == "cpu":
            processes = self.latest_sensor_values.get("sys_processes_total")
            running = self.latest_sensor_values.get("sys_procs_running")
            blocked = self.latest_sensor_values.get("sys_procs_blocked")
            cpu_count = self.latest_sensor_values.get("sys_cpu_count")
            load_1m = self.latest_sensor_values.get("sys_load_1m")
            load_5m = self.latest_sensor_values.get("sys_load_5m")
            load_15m = self.latest_sensor_values.get("sys_load_15m")

            if advanced and processes is not None:
                left_lines.append(f"{tr('details_processes')}: {processes}")
            if advanced and running is not None:
                left_lines.append(f"{tr('details_running')}: {running}")
            if advanced and blocked is not None:
                left_lines.append(f"{tr('details_blocked')}: {blocked}")
            if cpu_count is not None:
                left_lines.append(f"{tr('details_cpu_count')}: {cpu_count}")
            if advanced and load_1m is not None and load_5m is not None and load_15m is not None:
                right_lines.append(
                    f"{tr('details_loadavg')}: {load_1m:.2f} / {load_5m:.2f} / {load_15m:.2f}"
                )
            # Intentionally omitted: per-core "top usage" text is noisy when
            # dedicated per-core graphs are visible in CPU tab.

        if metric_name == "gpu":
            gpu_all = self.latest_sensor_values.get("gpu_all") or []
            if gpu_all:
                right_lines.append(f"{tr('details_gpus_count')}: {len(gpu_all)}")

        self.info_left.setText("\n".join(left_lines))
        self.info_right.setText("\n".join(right_lines))

    def update_widgets(self, data):
        now = time.time()
        can_rebuild_dynamic = (now - float(getattr(self, "_dynamic_last_rebuild_ts", 0.0))) >= float(
            getattr(self, "dynamic_rebuild_interval_s", 1.0)
        )
        if "cpu" in data:
            self._set_metric_value("cpu", float(data["cpu"]))

        if "ram" in data:
            self._set_metric_value("ram", float(data["ram"]))

        if "psu" in data:
            self._set_metric_value("psu", float(data["psu"]))
        psu_all = data.get("psu_all")
        if isinstance(psu_all, dict):
            self.latest_sensor_values["psu_all"] = psu_all
            if hasattr(self, "_update_auto_power_profile"):
                self._update_auto_power_profile(psu_all)
            self._update_power_sensor_graphs(psu_all)
            if self.selected_metric == "psu":
                self._refresh_primary_info("psu")

        gpu_all = data.get("gpu_all")
        if isinstance(gpu_all, list):
            self.latest_sensor_values["gpu_all"] = gpu_all
            valid_gpus = [item for item in gpu_all if isinstance(item, dict) and item.get("id")]
            telemetry_gpus = []
            for item in valid_gpus:
                load = item.get("load")
                temp = item.get("temp")
                has_load = load is not None and self._is_value_active("gpu", load)
                has_temp = temp is not None and float(temp) > 0.0
                if has_load or has_temp:
                    telemetry_gpus.append(item)
            has_multi_gpu = len(telemetry_gpus) > 1

            # Keep base "gpu" card as single/aggregate view.
            if valid_gpus:
                # Refresh primary GPU label from live data if available.
                first_name = valid_gpus[0].get("name")
                if first_name:
                    self.gpu_name = self._normalize_gpu_name(first_name)
                loads = [float(item["load"]) for item in telemetry_gpus if item.get("load") is not None]
                if loads and not self.metric_locks.get("gpu", True):
                    # Aggregate: average across GPUs.
                    self._set_metric_value("gpu", sum(loads) / float(len(loads)))
                elif self.metric_locks.get("gpu", True):
                    parts = self.metric_cards.get("gpu")
                    if parts:
                        parts["value"].setText(self.lang_handler.tr("graph_blocked_no_permissions"))

            # Remove stale per-GPU cards if device list changed or if only one GPU remains.
            existing_gpu_metrics = [name for name in self.metric_cards.keys() if name.startswith("gpu:")]
            incoming_gpu_metrics = {f"gpu:{item.get('id')}" for item in telemetry_gpus}
            for metric_name in existing_gpu_metrics:
                if metric_name in incoming_gpu_metrics and has_multi_gpu:
                    continue
                self._remove_metric_card(metric_name, "gpu")

            # Add per-GPU cards only when there are 2+ GPUs to avoid duplicate single-GPU entry.
            if has_multi_gpu:
                for item in telemetry_gpus:
                    gpu_id = item.get("id")
                    if not gpu_id:
                        continue
                    metric_name = f"gpu:{gpu_id}"
                    load = item.get("load")
                    temp = item.get("temp")
                    is_active = (load is not None and self._is_value_active("gpu", load)) or (temp is not None and float(temp) > 0.0)
                    if metric_name not in self.metric_cards:
                        if not is_active:
                            continue
                        self._add_metric_card(metric_name, "graph_gpu_load", "%", 100.0, peak_window=6, protected=True)
                    if load is not None and not self.metric_locks.get("gpu", True):
                        self._set_metric_value(metric_name, float(load))
                    elif self.metric_locks.get("gpu", True):
                        parts = self.metric_cards.get(metric_name)
                        if parts:
                            parts["value"].setText(self.lang_handler.tr("graph_blocked_no_permissions"))
                    self._set_card_subtitle(metric_name, self._metric_card_subtitle(metric_name))

        gpu = data.get("gpu_nvidia") or data.get("gpu_others") or data.get("gpu")
        if gpu is not None and not self.metric_locks.get("gpu", True):
            # Fallback path when per-card GPU list is unavailable.
            if not isinstance(gpu_all, list) or not gpu_all:
                self._set_metric_value("gpu", float(gpu))

        # If backend no longer reports gpu_all, clear per-GPU cards to avoid stale duplicates.
        if ("gpu_all" not in data) and any(name.startswith("gpu:") for name in self.metric_cards.keys()):
            for metric_name in [name for name in self.metric_cards.keys() if name.startswith("gpu:")]:
                self._remove_metric_card(metric_name, "gpu")

        cpu_temp = data.get("cpu_temp")
        if cpu_temp is not None:
            self.latest_sensor_values["cpu_temp"] = float(cpu_temp)
            if self.selected_metric == "cpu":
                self._refresh_primary_info("cpu")

        gpu_temp = data.get("gpu_temp")
        if gpu_temp is not None:
            self.latest_sensor_values["gpu_temp"] = float(gpu_temp)
            if self.selected_metric == "gpu":
                self._refresh_primary_info("gpu")

        net_total = data.get("net")
        if net_total is not None:
            self._set_metric_value("net_total", float(net_total))
        net_rx = data.get("net_rx")
        net_tx = data.get("net_tx")
        if net_rx is not None:
            self.latest_sensor_values["net_rx"] = float(net_rx)
        if net_tx is not None:
            self.latest_sensor_values["net_tx"] = float(net_tx)

        net_all = data.get("net_all")
        net_meta = data.get("net_meta")
        if isinstance(net_meta, dict):
            self.latest_sensor_values["net_meta"] = net_meta

        bt_all = data.get("bt_all")
        if isinstance(bt_all, dict):
            self.latest_sensor_values["bt_all"] = bt_all

        merged_bt_adapters = set()
        net_bt_merge = {}
        if isinstance(net_all, dict) and net_all and isinstance(bt_all, dict) and bt_all:
            # Merge BT telemetry into NET tab when both share same PCI slot (2-in-1 cards).
            slot_to_iface = {}
            for iface_name in net_all.keys():
                slot = ((self.latest_sensor_values.get("net_meta") or {}).get(iface_name) or {}).get("slot")
                if slot:
                    slot_to_iface.setdefault(str(slot), []).append(iface_name)

            for bt_adapter, bt_item in bt_all.items():
                if not isinstance(bt_item, dict):
                    continue
                slot = str(bt_item.get("slot") or "").strip()
                if not slot or slot not in slot_to_iface:
                    continue
                target_iface = slot_to_iface[slot][0]
                bucket = net_bt_merge.setdefault(
                    target_iface,
                    {"merged": True, "bt_mbps": 0.0, "bt_rx_mbps": 0.0, "bt_tx_mbps": 0.0, "adapters": []},
                )
                bucket["bt_mbps"] += float(bt_item.get("mbps", 0.0))
                bucket["bt_rx_mbps"] += float(bt_item.get("rx_mbps", 0.0))
                bucket["bt_tx_mbps"] += float(bt_item.get("tx_mbps", 0.0))
                bt_label = str(bt_item.get("name") or bt_adapter)
                bucket["adapters"].append(bt_label)
                merged_bt_adapters.add(bt_adapter)
        self.latest_sensor_values["net_bt_merge"] = net_bt_merge

        if isinstance(net_all, dict) and net_all:
            for iface_name, iface_val in net_all.items():
                metric_name = f"net:{iface_name}"
                merge_extra = float((net_bt_merge.get(iface_name) or {}).get("bt_mbps", 0.0))
                val = float(iface_val) + merge_extra
                self.metric_last_seen[metric_name] = now
                if self._is_value_active(metric_name, val):
                    self.metric_last_active[metric_name] = now
                    self.dynamic_metric_hidden.discard(metric_name)
                if metric_name not in self.metric_cards:
                    if not can_rebuild_dynamic:
                        continue
                    if not self._is_value_active(metric_name, val):
                        continue
                    self._add_metric_card(metric_name, "graph_net_iface", "Mbps", None, peak_window=4, protected=False)
                self._set_metric_value(metric_name, val)

        if isinstance(bt_all, dict):
            for adapter_name, bt_item in bt_all.items():
                if not isinstance(bt_item, dict):
                    continue
                if adapter_name in merged_bt_adapters:
                    # 2-in-1 card: merged into corresponding NET tab.
                    metric_name = f"bt:{adapter_name}"
                    if metric_name in self.metric_cards:
                        self._remove_metric_card(metric_name, "net_total")
                    continue
                metric_name = f"bt:{adapter_name}"
                val = float(bt_item.get("mbps", 0.0))
                self.metric_last_seen[metric_name] = now
                # Presence-based: keep adapter card even if idle.
                self.metric_last_active[metric_name] = now
                self.dynamic_metric_hidden.discard(metric_name)
                if metric_name not in self.metric_cards:
                    if not can_rebuild_dynamic:
                        continue
                    self._add_metric_card(metric_name, "graph_bt_iface", "Mbps", None, peak_window=4, protected=False)
                self._set_metric_value(metric_name, val)

        for key in (
            "sys_processes_total",
            "sys_procs_running",
            "sys_procs_blocked",
            "sys_uptime_s",
            "sys_load_1m",
            "sys_load_5m",
            "sys_load_15m",
            "sys_mem_total_kb",
            "sys_mem_available_kb",
            "sys_swap_total_kb",
            "sys_swap_free_kb",
            "sys_cpu_count",
            "sys_cpu_vendor",
            "sys_cpu_packages",
            "sys_cpu_cores_usage",
        ):
            if key in data:
                self.latest_sensor_values[key] = data[key]
        self._update_cpu_core_graphs(self.latest_sensor_values.get("sys_cpu_cores_usage") or [])
        if self.selected_metric in self.metric_cards:
            self._refresh_primary_info(self.selected_metric)

        all_disks = data.get("disc_all")
        if isinstance(all_disks, dict) and all_disks:
            for disk_name, disk_val in all_disks.items():
                metric_name = f"disk:{disk_name}"
                val = float(disk_val)
                self.metric_last_seen[metric_name] = now
                # Disk presence itself is treated as active feedback.
                self.metric_last_active[metric_name] = now
                self.dynamic_metric_hidden.discard(metric_name)
                if metric_name not in self.metric_cards:
                    if not can_rebuild_dynamic:
                        continue
                    self._add_metric_card(metric_name, "graph_disk_usage", "%", 100.0, peak_window=6, protected=False)
                self._set_metric_value(metric_name, val)
        else:
            disk = data.get("disc")
            if disk is not None:
                metric_name = "disk:disk"
                val = float(disk)
                self.metric_last_seen[metric_name] = now
                self.metric_last_active[metric_name] = now
                self.dynamic_metric_hidden.discard(metric_name)
                if metric_name not in self.metric_cards:
                    if can_rebuild_dynamic:
                        self._add_metric_card(metric_name, "graph_disk_usage", "%", 100.0, peak_window=6, protected=False)
                if metric_name in self.metric_cards:
                    self._set_metric_value(metric_name, val)

        if can_rebuild_dynamic:
            for metric_name in list(self.metric_cards.keys()):
                if not self._is_dynamic_metric(metric_name):
                    continue
                last_seen = self.metric_last_seen.get(metric_name, 0.0)
                last_active = self.metric_last_active.get(metric_name, last_seen)
                if metric_name.startswith("disk:"):
                    should_remove = (now - last_seen) > self.dynamic_metric_missing_hide_s
                elif metric_name.startswith("bt:"):
                    should_remove = (now - last_seen) > self.dynamic_metric_missing_hide_s
                else:
                    should_remove = (now - last_seen) > self.dynamic_metric_missing_hide_s or (
                        now - last_active
                    ) > self.dynamic_metric_idle_hide_s
                if should_remove:
                    self.dynamic_metric_hidden.add(metric_name)
                    fallback = "net_total" if metric_name.startswith(("net:", "bt:")) else "cpu"
                    self._remove_metric_card(metric_name, fallback)
            self._dynamic_last_rebuild_ts = now
