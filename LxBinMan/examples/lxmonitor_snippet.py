from moduleapi import feedback, builder

feedback.enable_console(True)

engines = builder.build_all(source_dir="/path/to/LxMonitor/core/engines")

cpu = engines["cpu"]
print(cpu.get_usage())
