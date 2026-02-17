#include <pybind11/pybind11.h>
#include <fstream>
#include <sstream>
#include <string>
#include <unordered_map>
#include <unordered_set>
#include <vector>
#include <chrono>
#include <algorithm>
#include <filesystem>
#include <cctype>

namespace py = pybind11;
namespace fs = std::filesystem;

class DiscActivityEngine {
public:
    DiscActivityEngine() {
        tracked_disks = detect_physical_disks();
        rebuild_display_names();
        last_time = std::chrono::steady_clock::now();
        last_counters = collect_counters();
    }

    double get_usage() {
        try {
            auto all = compute_all_usage();
            if (all.empty()) return last_avg_value;

            double sum = 0.0;
            for (const auto& [_, v] : all) sum += v;
            last_avg_value = sum / static_cast<double>(all.size());
            return last_avg_value;
        } catch (...) {
            return last_avg_value;
        }
    }

    py::dict get_all_usage() {
        py::dict out;
        try {
            auto all = compute_all_usage();
            for (const auto& [disk, usage] : all) {
                auto it = disk_display_names.find(disk);
                const std::string& label = (it != disk_display_names.end()) ? it->second : disk;
                out[py::str(label)] = usage;
            }
        } catch (...) {
            // leave empty dict
        }
        return out;
    }

private:
    struct Counters {
        long long io_ms = 0;
        long long weighted_io_ms = 0;
    };

    std::vector<std::string> tracked_disks;
    std::unordered_map<std::string, std::string> disk_display_names;
    std::chrono::steady_clock::time_point last_time;
    std::unordered_map<std::string, Counters> last_counters;
    double last_avg_value = 0.0;

    static bool is_physical_disk_name(const std::string& name) {
        // SATA / HDD / SSD
        if (name.rfind("sd", 0) == 0) return true;      // sda
        if (name.rfind("hd", 0) == 0) return true;      // hda
        if (name.rfind("vd", 0) == 0) return true;      // vda
        if (name.rfind("xvd", 0) == 0) return true;     // xvda
        // NVMe
        if (name.rfind("nvme", 0) == 0 && name.find('p') == std::string::npos) return true; // nvme0n1
        // eMMC / similar
        if (name.rfind("mmcblk", 0) == 0 && name.find('p') == std::string::npos) return true;
        // USB mass storage often appears as sdX (already covered)
        return false;
    }

    static std::string basename_from_dev_path(const std::string& src) {
        auto pos = src.find_last_of('/');
        if (pos == std::string::npos) return src;
        return src.substr(pos + 1);
    }

    static std::string strip_partition_suffix(const std::string& name) {
        // nvme0n1p3 -> nvme0n1
        auto ppos = name.rfind('p');
        if (ppos != std::string::npos && ppos + 1 < name.size()) {
            bool tail_digits = true;
            for (size_t i = ppos + 1; i < name.size(); ++i) {
                if (!std::isdigit(static_cast<unsigned char>(name[i]))) {
                    tail_digits = false;
                    break;
                }
            }
            if (tail_digits && name.rfind("nvme", 0) == 0) return name.substr(0, ppos);
            if (tail_digits && name.rfind("mmcblk", 0) == 0) return name.substr(0, ppos);
        }

        // sda1 -> sda, vda2 -> vda, xvda3 -> xvda, hda1 -> hda
        if (name.rfind("sd", 0) == 0 || name.rfind("vd", 0) == 0 || name.rfind("xvd", 0) == 0 || name.rfind("hd", 0) == 0) {
            size_t i = name.size();
            while (i > 0 && std::isdigit(static_cast<unsigned char>(name[i - 1]))) i--;
            if (i < name.size()) return name.substr(0, i);
        }
        return name;
    }

    static std::vector<std::string> detect_physical_disks() {
        std::unordered_set<std::string> set;

        // 1) Najpierw bierzemy zamontowane urządzenia, bo to najlepiej odzwierciedla realny I/O użytkownika.
        std::ifstream mounts("/proc/self/mounts");
        std::string line;
        while (std::getline(mounts, line)) {
            std::istringstream iss(line);
            std::string source, mount_point, fs_type;
            if (!(iss >> source >> mount_point >> fs_type)) continue;
            if (source.rfind("/dev/", 0) != 0) continue;

            std::string base = basename_from_dev_path(source);
            if (!base.empty()) {
                // dm-* trzymamy bezpośrednio (LUKS/LVM może nie mieć prostego parenta).
                if (base.rfind("dm-", 0) == 0) {
                    set.insert(base);
                } else {
                    std::string parent = strip_partition_suffix(base);
                    if (!parent.empty()) set.insert(parent);
                }
            }

            // Dla /dev/mapper/* często realne urządzenie to dm-*; spróbujmy resolve.
            try {
                fs::path p(source);
                if (fs::exists(p)) {
                    fs::path resolved = fs::canonical(p);
                    std::string rbase = resolved.filename().string();
                    if (!rbase.empty()) {
                        if (rbase.rfind("dm-", 0) == 0) {
                            set.insert(rbase);
                        } else {
                            std::string rparent = strip_partition_suffix(rbase);
                            if (!rparent.empty()) set.insert(rparent);
                        }
                    }
                }
            } catch (...) {
                // ignore
            }
        }

        // 2) Zawsze dołączamy /sys/block, żeby wykrywać także nośniki bez aktywnego mountu
        // (np. świeżo podpięty pendrive/USB, który jeszcze nie ma filesystem mountu).
        fs::path sys_block("/sys/block");
        if (fs::exists(sys_block)) {
            for (const auto& entry : fs::directory_iterator(sys_block)) {
                if (!entry.is_directory()) continue;
                std::string name = entry.path().filename().string();
                if (is_physical_disk_name(name)) {
                    set.insert(name);
                }
            }
        }

        std::unordered_set<std::string> normalized;
        for (const auto& n : set) {
            if (n.rfind("dm-", 0) == 0) {
                normalized.insert(n);
            } else {
                normalized.insert(strip_partition_suffix(n));
            }
        }

        std::vector<std::string> out(normalized.begin(), normalized.end());
        std::sort(out.begin(), out.end());
        return out;
    }

    static std::string trim_copy(const std::string& input) {
        size_t start = 0;
        while (start < input.size() && std::isspace(static_cast<unsigned char>(input[start]))) start++;
        size_t end = input.size();
        while (end > start && std::isspace(static_cast<unsigned char>(input[end - 1]))) end--;
        return input.substr(start, end - start);
    }

    static std::string collapse_spaces(const std::string& input) {
        std::string out;
        out.reserve(input.size());
        bool prev_space = false;
        for (char c : input) {
            bool is_space = std::isspace(static_cast<unsigned char>(c)) != 0;
            if (is_space) {
                if (!prev_space) out.push_back(' ');
                prev_space = true;
            } else {
                out.push_back(c);
                prev_space = false;
            }
        }
        return trim_copy(out);
    }

    static std::string read_first_line(const fs::path& p) {
        std::ifstream f(p);
        if (!f.is_open()) return {};
        std::string line;
        if (!std::getline(f, line)) return {};
        return collapse_spaces(line);
    }

    static std::string human_name_for_disk(const std::string& disk) {
        // Generic block device attributes.
        const fs::path base = fs::path("/sys/block") / disk / "device";
        std::string vendor = read_first_line(base / "vendor");
        std::string model = read_first_line(base / "model");

        // NVMe sometimes exposes cleaner metadata in /sys/class/nvme/<controller>/.
        if (disk.rfind("nvme", 0) == 0) {
            // nvme0n1 -> nvme0 (bierzemy 'n' po prefiksie "nvme")
            size_t npos = std::string::npos;
            for (size_t i = 4; i < disk.size(); ++i) {
                if (disk[i] == 'n') {
                    npos = i;
                    break;
                }
            }
            if (npos != std::string::npos && npos > 0) {
                std::string ctrl = disk.substr(0, npos);
                fs::path nvme_base = fs::path("/sys/class/nvme") / ctrl;
                std::string nvme_model = read_first_line(nvme_base / "model");
                std::string nvme_vendor = read_first_line(nvme_base / "vendor");
                if (!nvme_model.empty()) model = nvme_model;
                if (!nvme_vendor.empty()) vendor = nvme_vendor;
            }
        }

        std::string label;
        if (!vendor.empty() && !model.empty()) {
            std::string vendor_low = vendor;
            std::string model_low = model;
            std::transform(vendor_low.begin(), vendor_low.end(), vendor_low.begin(), ::tolower);
            std::transform(model_low.begin(), model_low.end(), model_low.begin(), ::tolower);
            if (model_low.find(vendor_low) != std::string::npos) {
                label = model;
            } else {
                label = vendor + " " + model;
            }
        } else if (!model.empty()) {
            label = model;
        } else if (!vendor.empty()) {
            label = vendor;
        } else {
            label = disk;
        }

        if (label != disk) {
            label += " (" + disk + ")";
        }
        return label;
    }

    void rebuild_display_names() {
        disk_display_names.clear();
        std::unordered_map<std::string, int> seen_labels;
        for (const auto& disk : tracked_disks) {
            std::string label = human_name_for_disk(disk);
            int& count = seen_labels[label];
            count++;
            if (count > 1) {
                label += " #" + std::to_string(count);
            }
            disk_display_names[disk] = label;
        }
    }

    std::unordered_map<std::string, Counters> collect_counters() const {
        std::unordered_map<std::string, Counters> out;
        std::unordered_set<std::string> tracked_set(tracked_disks.begin(), tracked_disks.end());
        std::ifstream f("/proc/diskstats");
        if (!f.is_open()) return out;

        std::string line;
        while (std::getline(f, line)) {
            std::istringstream iss(line);
            int major = 0, minor = 0;
            std::string name;
            long long reads_completed = 0, reads_merged = 0, sectors_read = 0, ms_reading = 0;
            long long writes_completed = 0, writes_merged = 0, sectors_written = 0, ms_writing = 0;
            long long ios_in_progress = 0, ms_doing_io = 0, weighted_ms_doing_io = 0;

            if (!(iss >> major >> minor >> name
                  >> reads_completed >> reads_merged >> sectors_read >> ms_reading
                  >> writes_completed >> writes_merged >> sectors_written >> ms_writing
                  >> ios_in_progress >> ms_doing_io >> weighted_ms_doing_io)) {
                continue;
            }

            std::string bucket;
            if (tracked_set.find(name) != tracked_set.end()) {
                bucket = name;
            } else {
                // Próbujemy przypisać partycję do bazowego dysku z tracked_set.
                std::string parent = strip_partition_suffix(name);
                if (tracked_set.find(parent) != tracked_set.end()) {
                    bucket = parent;
                } else {
                    continue;
                }
            }

            Counters c;
            c.io_ms = ms_doing_io;
            c.weighted_io_ms = weighted_ms_doing_io;
            auto it = out.find(bucket);
            if (it == out.end()) {
                out[bucket] = c;
            } else {
                // Bierzemy max, żeby nie zaniżać i nie dublować parent/partition.
                it->second.io_ms = std::max(it->second.io_ms, c.io_ms);
                it->second.weighted_io_ms = std::max(it->second.weighted_io_ms, c.weighted_io_ms);
            }
        }
        return out;
    }

    std::unordered_map<std::string, double> compute_all_usage() {
        // Jeśli w locie zmienił się zestaw dysków, odśwież listę.
        auto fresh_disks = detect_physical_disks();
        if (fresh_disks != tracked_disks) {
            tracked_disks = std::move(fresh_disks);
            rebuild_display_names();
            last_counters = collect_counters();
            last_time = std::chrono::steady_clock::now();
            return zero_usage_map();
        }

        auto now = std::chrono::steady_clock::now();
        double elapsed_ms = std::chrono::duration<double, std::milli>(now - last_time).count();
        if (elapsed_ms <= 1.0) return zero_usage_map();

        auto current = collect_counters();
        if (current.empty()) return zero_usage_map();

        std::unordered_map<std::string, double> out;
        for (const auto& disk : tracked_disks) {
            auto it_now = current.find(disk);
            auto it_prev = last_counters.find(disk);
            if (it_now == current.end() || it_prev == last_counters.end()) continue;

            long long delta_io = it_now->second.io_ms - it_prev->second.io_ms;
            long long delta_weighted = it_now->second.weighted_io_ms - it_prev->second.weighted_io_ms;
            if (delta_io < 0) delta_io = 0;
            if (delta_weighted < 0) delta_weighted = 0;

            // Używamy większej z wartości: zwykły busy time i weighted busy time.
            double basis = static_cast<double>(std::max(delta_io, delta_weighted));
            double util = (basis / elapsed_ms) * 100.0;
            out[disk] = std::clamp(util, 0.0, 100.0);
        }

        last_time = now;
        last_counters = std::move(current);
        if (out.empty()) return zero_usage_map();
        return out;
    }

    std::unordered_map<std::string, double> zero_usage_map() const {
        std::unordered_map<std::string, double> out;
        for (const auto& d : tracked_disks) out[d] = 0.0;
        return out;
    }
};

static DiscActivityEngine global_disc;

PYBIND11_MODULE(disc, m) {
    m.def("get_usage", []() { return global_disc.get_usage(); }, "Returns average disk I/O activity %");
    m.def("get_all_usage", []() { return global_disc.get_all_usage(); }, "Returns disk I/O activity % per disk with readable model names");
}
