import re
import os
f = "driver_tool.py"
with open(f, encoding="utf-8") as file:
    content = file.read()

# 1. & 2. Fix Hardcoded C:\ for Restore Points natively
content = re.sub(r'Enable-ComputerRestore -Drive "C:\\\\"', r'Enable-ComputerRestore -Drive "$($env:SystemDrive)\\\"', content)
content = content.replace("vssadmin', 'resize', 'shadowstorage', '/for=C:', '/on=C:',", "vssadmin', 'resize', 'shadowstorage', f'/for={os.environ.get(\\'SystemDrive\\', \\'C:\\')}', f'/on={os.environ.get(\\'SystemDrive\\', \\'C:\\')}',")

# 3. & 4. CLI AttachConsole and multiprocessing.freeze_support
cli_fix = """if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()
    
    if "--cli" in sys.argv:
        if getattr(sys, "frozen", False):
            import ctypes
            # Attach to the parent console if running from cmd in windowed mode
            if ctypes.windll.kernel32.AttachConsole(-1):
                import io
                sys.stdout = open("CONOUT$", "w", encoding="utf-8")
                sys.stderr = open("CONOUT$", "w", encoding="utf-8")
                sys.stdin = open("CONIN$", "r", encoding="utf-8")
"""
content = content.replace("if __name__ == \"__main__\":", cli_fix)

# Remove unused globals (F824)
content = re.sub(r'^[ \t]*global _webview_ready, _webview_error\n', '', content, flags=re.MULTILINE)
content = re.sub(r'^[ \t]*global _webview_error\n', '', content, flags=re.MULTILINE)

with open(f, "w", encoding="utf-8") as file:
    file.write(content)
print("Phase 4 Built successfully!")
