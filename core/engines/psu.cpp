#include <pybind11/pybind11.h>

#include <algorithm>
#include <chrono>
#include <filesystem>
#include <fstream>
#include <sstream>
#include <string>
#include <unordered_map>
#include <unordered_set>
#include <vector>
#include <cctype>
#include <cmath>
#include <unistd.h>

namespace py = pybind11;
namespace fs = std::filesystem;

class PowerTelemetryEngine {
public:
    PowerTelemetryEngine() = default;

    double get_usage() {
        const auto snap = collect_snapshot();
        return std::max(0.0, snap.total_w);
    }

    py::dict get_all_usage() {
        const auto snap = collect_snapshot();
        py::dict out;
        out["total_w"] = snap.total_w;
        out["source"] = snap.total_source;
        out["has_battery"] = snap.has_battery;
        out["battery_count"] = snap.battery_count;
        out["ac_online"] = snap.ac_online;
        out["battery_total_w"] = snap.battery_total_w;
        out["battery_discharge_w"] = snap.battery_discharge_w;
        out["battery_charge_w"] = snap.battery_charge_w;
        out["battery_capacity_avg"] = snap.battery_capacity_avg;

        out["cpu_w"] = snap.cpu_w;
        out["gpu_w"] = snap.gpu_w;
        out["disk_w"] = snap.disk_w;
        out["net_w"] = snap.net_w;
        out["board_w"] = snap.board_w;
        out["memory_w"] = snap.memory_w;
        out["other_w"] = snap.other_w;

        py::dict src;
        for (const auto& [name, value] : snap.sources_w) {
            src[py::str(name)] = value;
        }
        out["sources"] = src;
        py::list blocked;
        for (const auto& name : snap.blocked_sources) {
            blocked.append(py::str(name));
        }
        out["blocked_sources"] = blocked;
        return out;
    }

private:
    struct Snapshot {
        double total_w = 0.0;
        std::string total_source = "none";
        bool has_battery = false;
        int battery_count = 0;
        bool ac_online = false;
        double battery_total_w = 0.0;
        double battery_discharge_w = 0.0;
        double battery_charge_w = 0.0;
        double battery_capacity_avg = 0.0;

        double cpu_w = 0.0;
        double gpu_w = 0.0;
        double disk_w = 0.0;
        double net_w = 0.0;
        double board_w = 0.0;
        double memory_w = 0.0;
        double other_w = 0.0;

        std::vector<std::pair<std::string, double>> sources_w;
        std::vector<std::string> blocked_sources;
    };

    struct RaplPrev {
        unsigned long long energy_uj = 0ULL;
        std::chrono::steady_clock::time_point ts;
        bool valid = false;
    };

    std::unordered_map<std::string, RaplPrev> rapl_prev_;

    static std::string read_text(const fs::path& p) {
        std::ifstream f(p);
        if (!f.is_open()) return {};
        std::string s;
        std::getline(f, s);
        return s;
    }

    static unsigned long long read_u64(const fs::path& p, bool* ok = nullptr) {
        std::ifstream f(p);
        if (!f.is_open()) {
            if (ok) *ok = false;
            return 0ULL;
        }
        unsigned long long v = 0ULL;
        f >> v;
        const bool good = !f.fail();
        if (ok) *ok = good;
        return good ? v : 0ULL;
    }

    static double read_double(const fs::path& p, bool* ok = nullptr) {
        std::ifstream f(p);
        if (!f.is_open()) {
            if (ok) *ok = false;
            return 0.0;
        }
        double v = 0.0;
        f >> v;
        const bool good = !f.fail();
        if (ok) *ok = good;
        return good ? v : 0.0;
    }

    static std::string sanitize_label(const std::string& in) {
        std::string s = in;
        for (char& c : s) {
            if (c == '\t' || c == '\n' || c == '\r') c = ' ';
        }
        while (!s.empty() && s.front() == ' ') s.erase(s.begin());
        while (!s.empty() && s.back() == ' ') s.pop_back();
        return s;
    }

    static std::string to_lower(std::string s) {
        for (char& c : s) {
            c = static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
        }
        return s;
    }

    static bool contains_any(const std::string& s, const std::vector<std::string>& needles) {
        for (const auto& n : needles) {
            if (!n.empty() && s.find(n) != std::string::npos) return true;
        }
        return false;
    }

    static int parse_sensor_index(const std::string& filename, const std::string& prefix) {
        if (filename.rfind(prefix, 0) != 0) return -1;
        const size_t start = prefix.size();
        size_t pos = start;
        while (pos < filename.size() && std::isdigit(static_cast<unsigned char>(filename[pos]))) pos++;
        if (pos == start) return -1;
        try {
            return std::stoi(filename.substr(start, pos - start));
        } catch (...) {
            return -1;
        }
    }

    static void append_source(std::vector<std::pair<std::string, double>>& out, const std::string& name, double watts) {
        if (watts < 0.0 || watts > 3000.0) return;
        out.emplace_back(name, watts);
    }

    static bool can_read_file(const fs::path& p) {
        return fs::exists(p) && (::access(p.c_str(), R_OK) == 0);
    }

    static void mark_blocked(std::unordered_set<std::string>& blocked, const std::string& label) {
        if (!label.empty()) blocked.insert(label);
    }

    struct SourceMeta {
        std::string cls;
        std::string entity;
        int priority = 0;
    };

    static std::string extract_token_after(const std::string& s, const std::string& key) {
        auto pos = s.find(key);
        if (pos == std::string::npos) return {};
        pos += key.size();
        std::string out;
        while (pos < s.size()) {
            const char c = s[pos];
            if (std::isalnum(static_cast<unsigned char>(c)) || c == '_' || c == '-' || c == '.') {
                out.push_back(c);
                pos++;
            } else {
                break;
            }
        }
        return out;
    }

    static SourceMeta source_meta(const std::string& name) {
        SourceMeta m;
        const std::string low = to_lower(name);

        if (low.rfind("gpu:", 0) == 0 || contains_any(low, {"amdgpu", "radeon", "nvidia", "nouveau", "i915", "xe", "vddgfx", "ppt"})) {
            m.cls = "gpu";
            m.entity = extract_token_after(low, "card");
            if (m.entity.empty()) {
                if (low.find("amdgpu") != std::string::npos) m.entity = "amdgpu";
                else if (low.find("nvidia") != std::string::npos) m.entity = "nvidia";
                else if (low.find("nouveau") != std::string::npos) m.entity = "nouveau";
                else if (low.find("i915") != std::string::npos) m.entity = "i915";
                else if (low.find("xe") != std::string::npos) m.entity = "xe";
            }
            if (low.rfind("hwmon:", 0) == 0) m.priority = 30;
            else if (low.rfind("gpu:", 0) == 0) m.priority = 20;
            else m.priority = 10;
            return m;
        }
        if (low.rfind("rapl:", 0) == 0 || contains_any(low, {"cpu", "package", "coretemp", "k10temp", "tctl", "tdie"})) {
            m.cls = "cpu";
            m.entity = extract_token_after(low, "rapl:");
            if (m.entity.empty()) m.entity = "cpu";
            m.priority = (low.rfind("rapl:", 0) == 0) ? 30 : 10;
            return m;
        }

        return m;
    }

    static bool likely_duplicate_sensor(
        const std::pair<std::string, double>& a,
        const std::pair<std::string, double>& b
    ) {
        const auto ma = source_meta(a.first);
        const auto mb = source_meta(b.first);
        if (ma.cls.empty() || mb.cls.empty()) return false;
        if (ma.cls != mb.cls) return false;
        if (!ma.entity.empty() && !mb.entity.empty() && ma.entity != mb.entity) return false;

        const double max_w = std::max(std::abs(a.second), std::abs(b.second));
        const double eps = std::max(0.35, max_w * 0.03);
        return std::abs(a.second - b.second) <= eps;
    }

    static int dedupe_score(const std::string& name) {
        const auto m = source_meta(name);
        int score = m.priority;
        if (name.rfind("hwmon:", 0) == 0) score += 3;
        if (name.rfind("rapl:", 0) == 0) score += 3;
        if (name.rfind("gpu:", 0) == 0) score += 1;
        if (name.rfind("supply:", 0) == 0) score -= 1;
        return score;
    }

    void collect_hwmon_power(
        std::vector<std::pair<std::string, double>>& out,
        std::unordered_set<std::string>& blocked
    ) {
        const fs::path hwmon_root("/sys/class/hwmon");
        if (!fs::exists(hwmon_root)) return;

        for (const auto& hw : fs::directory_iterator(hwmon_root)) {
            if (!hw.is_directory()) continue;

            const std::string chip = sanitize_label(read_text(hw.path() / "name"));
            std::unordered_map<int, double> in_mv;
            std::unordered_map<int, double> curr_ma;
            std::unordered_map<int, std::string> in_label;
            std::unordered_map<int, std::string> curr_label;
            for (const auto& f : fs::directory_iterator(hw.path())) {
                const std::string fname = f.path().filename().string();
                if (!f.is_regular_file()) continue;

                // Direct power files (microwatts in most drivers).
                if (fname.rfind("power", 0) == 0 &&
                    (fname.find("_input") != std::string::npos || fname.find("_average") != std::string::npos)) {
                    std::string suffix = (fname.find("_input") != std::string::npos) ? "_input" : "_average";
                    std::string prefix = fname.substr(0, fname.find(suffix));
                    std::string label = sanitize_label(read_text(hw.path() / (prefix + "_label")));
                    if (label.empty()) label = prefix;
                    std::string blocked_label = "hwmon:";
                    if (!chip.empty()) blocked_label += chip + ":";
                    blocked_label += label;
                    if (!can_read_file(f.path())) {
                        mark_blocked(blocked, blocked_label);
                        continue;
                    }

                    bool ok = false;
                    const auto raw = read_u64(f.path(), &ok);
                    if (!ok) continue;
                    double watts = static_cast<double>(raw) / 1'000'000.0;
                    if (watts <= 0.0) continue;

                    std::string name = "hwmon:";
                    if (!chip.empty()) name += chip + ":";
                    name += label;
                    append_source(out, name, watts);
                    continue;
                }

                // Cache voltage/current channels for computed power.
                if (fname.rfind("in", 0) == 0 && fname.find("_input") != std::string::npos) {
                    const int idx = parse_sensor_index(fname, "in");
                    if (idx >= 0) {
                        bool ok = false;
                        const auto raw = read_u64(f.path(), &ok);
                        if (ok) in_mv[idx] = static_cast<double>(raw); // typically mV
                    }
                    continue;
                }
                if (fname.rfind("curr", 0) == 0 && fname.find("_input") != std::string::npos) {
                    const int idx = parse_sensor_index(fname, "curr");
                    if (idx >= 0) {
                        bool ok = false;
                        const auto raw = read_u64(f.path(), &ok);
                        if (ok) curr_ma[idx] = static_cast<double>(raw); // typically mA
                    }
                    continue;
                }
                if (fname.rfind("in", 0) == 0 && fname.find("_label") != std::string::npos) {
                    const int idx = parse_sensor_index(fname, "in");
                    if (idx >= 0) in_label[idx] = sanitize_label(read_text(f.path()));
                    continue;
                }
                if (fname.rfind("curr", 0) == 0 && fname.find("_label") != std::string::npos) {
                    const int idx = parse_sensor_index(fname, "curr");
                    if (idx >= 0) curr_label[idx] = sanitize_label(read_text(f.path()));
                    continue;
                }
            }

            // Derived power from V * I channels (common on VRM/board controllers).
            for (const auto& [idx, mv] : in_mv) {
                auto itc = curr_ma.find(idx);
                if (itc == curr_ma.end()) continue;
                const double ma = itc->second;
                if (mv <= 0.0 || ma <= 0.0) continue;

                const double watts = (mv / 1000.0) * (ma / 1000.0);
                if (watts <= 0.0 || watts > 3000.0) continue;

                std::string label = in_label[idx];
                if (label.empty()) label = curr_label[idx];
                if (label.empty()) label = "rail" + std::to_string(idx);

                std::string name = "hwmon_vi:";
                if (!chip.empty()) name += chip + ":";
                name += label;
                append_source(out, name, watts);
            }
        }
    }

    void collect_drm_gpu_power(std::vector<std::pair<std::string, double>>& out) {
        const fs::path drm_root("/sys/class/drm");
        if (!fs::exists(drm_root)) return;

        for (const auto& e : fs::directory_iterator(drm_root)) {
            if (!e.is_directory()) continue;
            const std::string card = e.path().filename().string();
            if (card.rfind("card", 0) != 0) continue;
            if (card.find('-') != std::string::npos) continue;

            const fs::path dev = e.path() / "device";
            if (!fs::exists(dev)) continue;

            std::string slot;
            {
                std::istringstream iss(read_text(dev / "uevent"));
                std::string line;
                while (std::getline(iss, line)) {
                    if (line.rfind("PCI_SLOT_NAME=", 0) == 0) {
                        slot = line.substr(std::string("PCI_SLOT_NAME=").size());
                        break;
                    }
                }
            }

            const fs::path hwmon_dir = dev / "hwmon";
            if (!fs::exists(hwmon_dir)) continue;
            for (const auto& hw : fs::directory_iterator(hwmon_dir)) {
                if (!hw.is_directory()) continue;
                for (const auto& f : fs::directory_iterator(hw.path())) {
                    const std::string fn = f.path().filename().string();
                    if (fn.rfind("power", 0) != 0 || fn.find("_input") == std::string::npos) continue;
                    if (!f.is_regular_file()) continue;
                    bool ok = false;
                    const auto raw = read_u64(f.path(), &ok);
                    if (!ok || raw == 0ULL) continue;
                    const double watts = static_cast<double>(raw) / 1'000'000.0;
                    std::string src = "gpu:" + card;
                    if (!slot.empty()) src += ":" + slot;
                    src += ":" + fn.substr(0, fn.find("_input"));
                    append_source(out, src, watts);
                }
            }
        }
    }

    void collect_nvme_power(
        std::vector<std::pair<std::string, double>>& out,
        std::unordered_set<std::string>& blocked
    ) {
        const fs::path nvme_root("/sys/class/nvme");
        if (!fs::exists(nvme_root)) return;

        for (const auto& e : fs::directory_iterator(nvme_root)) {
            if (!e.is_directory()) continue;
            const std::string ctrl = e.path().filename().string();
            if (ctrl.rfind("nvme", 0) != 0) continue;

            const fs::path hwmon_dir = e.path() / "device" / "hwmon";
            if (!fs::exists(hwmon_dir)) continue;

            for (const auto& hw : fs::directory_iterator(hwmon_dir)) {
                if (!hw.is_directory()) continue;
                for (const auto& f : fs::directory_iterator(hw.path())) {
                    const std::string fn = f.path().filename().string();
                    if (fn.rfind("power", 0) != 0 || fn.find("_input") == std::string::npos) continue;
                    if (!f.is_regular_file()) continue;
                    std::string label = "disk:" + ctrl + ":" + fn.substr(0, fn.find("_input"));
                    if (!can_read_file(f.path())) {
                        mark_blocked(blocked, label);
                        continue;
                    }
                    bool ok = false;
                    const auto raw = read_u64(f.path(), &ok);
                    if (!ok || raw == 0ULL) continue;
                    const double watts = static_cast<double>(raw) / 1'000'000.0;
                    append_source(out, label, watts);
                }
            }
        }
    }

    void collect_rapl_power(
        std::vector<std::pair<std::string, double>>& out,
        std::unordered_set<std::string>& blocked
    ) {
        const fs::path rapl_root("/sys/class/powercap");
        if (!fs::exists(rapl_root)) return;

        const auto now = std::chrono::steady_clock::now();
        for (const auto& e : fs::recursive_directory_iterator(rapl_root)) {
            if (!e.is_regular_file()) continue;
            if (e.path().filename() != "energy_uj") continue;

            const fs::path zone = e.path().parent_path();
            const fs::path key_path = zone / "name";
            std::string key = read_text(key_path);
            if (key.empty()) key = zone.filename().string();
            key = sanitize_label(key);
            if (key.empty()) key = "rapl";
            std::string rlabel = "rapl:" + key;
            if (!can_read_file(e.path())) {
                mark_blocked(blocked, rlabel);
                continue;
            }

            bool ok_energy = false;
            const unsigned long long energy_uj = read_u64(e.path(), &ok_energy);
            if (!ok_energy) continue;

            bool ok_max = false;
            const unsigned long long max_range = read_u64(zone / "max_energy_range_uj", &ok_max);

            auto& prev = rapl_prev_[zone.string()];
            if (!prev.valid) {
                prev.energy_uj = energy_uj;
                prev.ts = now;
                prev.valid = true;
                continue;
            }

            const double elapsed_s = std::chrono::duration<double>(now - prev.ts).count();
            if (elapsed_s <= 0.0001) continue;

            unsigned long long delta_uj = 0ULL;
            if (energy_uj >= prev.energy_uj) {
                delta_uj = energy_uj - prev.energy_uj;
            } else if (ok_max && max_range > prev.energy_uj) {
                delta_uj = (max_range - prev.energy_uj) + energy_uj;
            }

            prev.energy_uj = energy_uj;
            prev.ts = now;
            prev.valid = true;

            if (delta_uj == 0ULL) continue;
            const double watts = (static_cast<double>(delta_uj) / 1'000'000.0) / elapsed_s;
            append_source(out, rlabel, watts);
        }
    }

    void collect_power_supply(
        Snapshot& snap,
        std::vector<std::pair<std::string, double>>& out,
        std::unordered_set<std::string>& blocked
    ) {
        const fs::path root("/sys/class/power_supply");
        if (!fs::exists(root)) return;

        double cap_sum = 0.0;
        int cap_count = 0;

        for (const auto& e : fs::directory_iterator(root)) {
            if (!e.is_directory()) continue;
            const std::string name = e.path().filename().string();
            const std::string type = sanitize_label(read_text(e.path() / "type"));
            const std::string status = sanitize_label(read_text(e.path() / "status"));

            if (name.rfind("BAT", 0) == 0 || type == "Battery") {
                snap.has_battery = true;
                snap.battery_count += 1;

                bool ok_pow = false;
                double power_now_uW = read_double(e.path() / "power_now", &ok_pow);
                if (!ok_pow) {
                    bool ok_cur = false, ok_vol = false;
                    const double current_now_uA = read_double(e.path() / "current_now", &ok_cur);
                    const double voltage_now_uV = read_double(e.path() / "voltage_now", &ok_vol);
                    if (ok_cur && ok_vol) {
                        power_now_uW = (current_now_uA * voltage_now_uV) / 1'000'000.0;
                        ok_pow = true;
                    }
                }
                if (ok_pow && power_now_uW > 0.0) {
                    const double w = power_now_uW / 1'000'000.0;
                    snap.battery_total_w += w;
                    std::string st = to_lower(status);
                    if (st.find("discharg") != std::string::npos) snap.battery_discharge_w += w;
                    if (st.find("charg") != std::string::npos) snap.battery_charge_w += w;
                    append_source(out, "battery:" + name, w);
                }

                bool ok_cap = false;
                const double cap = read_double(e.path() / "capacity", &ok_cap);
                if (ok_cap) {
                    cap_sum += cap;
                    cap_count += 1;
                }
                continue;
            }

            if (type == "Mains" || type == "USB" || name.rfind("AC", 0) == 0 || name.rfind("ADP", 0) == 0) {
                bool ok_on = false;
                const double online = read_double(e.path() / "online", &ok_on);
                if (ok_on && online > 0.5) snap.ac_online = true;
            }

            bool ok_pow = false;
            fs::path p_pow = e.path() / "power_now";
            fs::path p_cur = e.path() / "current_now";
            fs::path p_vol = e.path() / "voltage_now";
            double power_now_uW = read_double(p_pow, &ok_pow);
            if (!ok_pow) {
                bool ok_cur = false, ok_vol = false;
                const double current_now_uA = read_double(p_cur, &ok_cur);
                const double voltage_now_uV = read_double(p_vol, &ok_vol);
                if (ok_cur && ok_vol) {
                    power_now_uW = (current_now_uA * voltage_now_uV) / 1'000'000.0;
                    ok_pow = true;
                }
            }
            if (ok_pow && power_now_uW > 0.0) {
                const double w = power_now_uW / 1'000'000.0;
                append_source(out, "supply:" + name, w);
            } else if (
                (fs::exists(p_pow) && !can_read_file(p_pow)) ||
                ((fs::exists(p_cur) || fs::exists(p_vol)) && (!can_read_file(p_cur) || !can_read_file(p_vol)))
            ) {
                mark_blocked(blocked, "supply:" + name);
            }
        }

        if (cap_count > 0) {
            snap.battery_capacity_avg = cap_sum / static_cast<double>(cap_count);
        }
    }

    Snapshot collect_snapshot() {
        Snapshot snap;
        std::vector<std::pair<std::string, double>> sources;
        std::unordered_set<std::string> blocked;
        sources.reserve(64);

        collect_hwmon_power(sources, blocked);
        // DRM GPU power often points to the same hwmon files as collect_hwmon_power(),
        // which can double-count AMD PPT on many systems. Keep hwmon as canonical source.
        collect_nvme_power(sources, blocked);
        collect_rapl_power(sources, blocked);
        collect_power_supply(snap, sources, blocked);

        std::unordered_map<std::string, double> merged;
        for (const auto& [name, w] : sources) {
            merged[name] += w;
        }
        sources.clear();
        sources.reserve(merged.size());
        for (const auto& it : merged) {
            sources.emplace_back(it.first, it.second);
        }
        // Deduplicate likely same sensor exposed under multiple paths/names.
        if (sources.size() > 1) {
            std::vector<bool> drop(sources.size(), false);
            for (size_t i = 0; i < sources.size(); ++i) {
                if (drop[i]) continue;
                for (size_t j = i + 1; j < sources.size(); ++j) {
                    if (drop[j]) continue;
                    if (!likely_duplicate_sensor(sources[i], sources[j])) continue;
                    const int si = dedupe_score(sources[i].first);
                    const int sj = dedupe_score(sources[j].first);
                    if (si >= sj) drop[j] = true;
                    else drop[i] = true;
                }
            }
            std::vector<std::pair<std::string, double>> deduped;
            deduped.reserve(sources.size());
            for (size_t i = 0; i < sources.size(); ++i) {
                if (!drop[i]) deduped.push_back(sources[i]);
            }
            sources = std::move(deduped);
        }
        std::sort(sources.begin(), sources.end(), [](const auto& a, const auto& b) {
            return a.first < b.first;
        });

        double component_total_w = 0.0;
        for (const auto& [name, w] : sources) {
            if (name.rfind("battery:", 0) == 0) continue;
            component_total_w += w;

            const std::string low = to_lower(name);
            if (low.rfind("gpu:", 0) == 0 || contains_any(low, {"amdgpu", "radeon", "nvidia", "drm", "vddgfx", "gfx"})) {
                snap.gpu_w += w;
            } else if (
                low.rfind("rapl:", 0) == 0 ||
                contains_any(low, {"cpu", "package", "core", "k10temp", "coretemp", "vddcr_cpu", "vcore", "cpu_vdd", "tctl", "tdie"})
            ) {
                snap.cpu_w += w;
            } else if (low.rfind("disk:", 0) == 0 || contains_any(low, {"nvme", "ata", "ssd", "hdd", "sata", "wdc", "seagate", "sandisk"})) {
                snap.disk_w += w;
            } else if (low.rfind("net:", 0) == 0 || contains_any(low, {"ethernet", "wifi", "wlan", "iwlwifi", "r816", "rtl", "ath", "net"})) {
                snap.net_w += w;
            } else if (contains_any(low, {"dram", "memory", "ddr"})) {
                snap.memory_w += w;
            } else if (
                low.rfind("supply:", 0) == 0 ||
                contains_any(low, {"pch", "soc", "board", "chipset", "vrm", "motherboard", "vddcr_soc", "3v", "5v", "12v", "aux"})
            ) {
                snap.board_w += w;
            } else {
                snap.other_w += w;
            }
        }

        if (component_total_w > 0.01) {
            snap.total_w = component_total_w;
            snap.total_source = "components";
        } else if (snap.battery_total_w > 0.01) {
            snap.total_w = snap.battery_total_w;
            snap.total_source = "battery";
        } else {
            snap.total_w = 0.0;
            snap.total_source = "none";
        }

        snap.sources_w = std::move(sources);
        snap.blocked_sources.assign(blocked.begin(), blocked.end());
        std::sort(snap.blocked_sources.begin(), snap.blocked_sources.end());
        return snap;
    }
};

static PowerTelemetryEngine global_power;

PYBIND11_MODULE(psu, m) {
    m.doc() = "Power telemetry engine (component-level + battery/AC)";
    m.def("get_usage", []() { return global_power.get_usage(); }, "Returns best-effort total power in watts");
    m.def("get_all_usage", []() { return global_power.get_all_usage(); }, "Returns detailed power telemetry");
}
