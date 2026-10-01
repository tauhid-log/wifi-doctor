import platform
import socket

print("=== WiFi-Doctor Starting ===")
print(f"System: {platform.system()} {platform.release()}")
print(f"Hostname: {socket.gethostname()}")
print(f"Python: {platform.python_version()}")
print("Ready to diagnose your network!")