#include <pybind11/pybind11.h>

#include <array>
#include <cstdio>
#include <cstdlib>
#include <string>
#include <sys/wait.h>

namespace py = pybind11;

namespace {

struct CmdResult {
    int code = 1;
    std::string output;
};

static std::string shell_escape(const std::string& in) {
    std::string out = "'";
    for (char c : in) {
        if (c == '\'') {
            out += "'\"'\"'";
        } else {
            out.push_back(c);
        }
    }
    out.push_back('\'');
    return out;
}

static CmdResult run_capture(const std::string& cmd) {
    CmdResult result;
    std::array<char, 512> buffer{};
    std::string full = cmd + " 2>&1";
    FILE* pipe = popen(full.c_str(), "r");
    if (!pipe) {
        result.output = "popen() failed";
        return result;
    }
    while (fgets(buffer.data(), static_cast<int>(buffer.size()), pipe) != nullptr) {
        result.output += buffer.data();
    }
    int status = pclose(pipe);
    if (status == -1) {
        result.code = 1;
    } else if (WIFEXITED(status)) {
        result.code = WEXITSTATUS(status);
    } else {
        result.code = 1;
    }
    return result;
}

static bool cmd_exists(const std::string& cmd) {
    auto res = run_capture("command -v " + cmd + " >/dev/null");
    return res.code == 0;
}

static std::string detect_backend() {
    if (cmd_exists("sudo")) return "local_sudo";
    if (cmd_exists("pkexec")) return "local_pkexec";

    if (cmd_exists("flatpak-spawn")) {
        if (run_capture("flatpak-spawn --host sh -lc 'command -v sudo >/dev/null 2>&1'").code == 0) {
            return "host_sudo";
        }
        if (run_capture("flatpak-spawn --host sh -lc 'command -v pkexec >/dev/null 2>&1'").code == 0) {
            return "host_pkexec";
        }
    }
    return "none";
}

static CmdResult run_privileged(const std::string& password, const std::string& command) {
    std::string backend = detect_backend();
    if (backend == "none") {
        return {1, "Brak narzędzia podnoszenia uprawnień (sudo/pkexec) lokalnie i na hoście."};
    }

    const bool host = (backend == "host_sudo" || backend == "host_pkexec");
    const bool sudo_mode = (backend == "local_sudo" || backend == "host_sudo");

    std::string cmd;
    if (sudo_mode) {
        if (password.empty()) {
            cmd = "sudo -n sh -lc " + shell_escape(command);
        } else {
            cmd = "printf %s\\\\n " + shell_escape(password) +
                  " | sudo -S -k -p '' sh -lc " + shell_escape(command);
        }
    } else {
        cmd = "pkexec sh -lc " + shell_escape(command);
    }

    if (host) {
        cmd = "flatpak-spawn --host sh -lc " + shell_escape(cmd);
    }
    return run_capture(cmd);
}

static py::dict make_result(const CmdResult& res) {
    py::dict out;
    out["ok"] = (res.code == 0);
    out["error"] = py::str(res.output);
    out["code"] = res.code;
    out["backend"] = py::str(detect_backend());
    return out;
}

}  // namespace

PYBIND11_MODULE(privilege, m) {
    m.def("detect_backend", []() { return detect_backend(); }, "Detect privilege escalation backend");
    m.def(
        "verify",
        [](const std::string& password) {
            return make_result(run_privileged(password, "true"));
        },
        "Verify privileged access");
    m.def(
        "prepare_access",
        [](const std::string& password) {
            const std::string setup_cmd =
                "for f in "
                "/sys/class/drm/card*/device/gpu_busy_percent "
                "/sys/class/drm/card*/device/usage "
                "/sys/class/hwmon/hwmon*/device/gpu_busy_percent "
                "/sys/class/thermal/thermal_zone*/temp "
                "/sys/class/thermal/thermal_zone*/type "
                "/sys/class/drm/card*/device/hwmon/hwmon*/temp*_input "
                "/dev/nvidiactl /dev/nvidia[0-9]*; do "
                "[ -e \"$f\" ] && chmod a+r \"$f\" 2>/dev/null || true; "
                "done";
            return make_result(run_privileged(password, setup_cmd));
        },
        "Prepare readable access to protected metric paths");
}
