"""Everything that depends on the operating system (macOS, Linux, Windows)."""
import json
import os
import shutil
import subprocess
import sys

QUIET = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}


def acquire_lock(path):
    """Exclusive lock released when the process ends. Returns None if another run holds it."""
    handle = open(path, "w")
    try:
        if sys.platform == "win32":
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        return None
    return handle


def keep_awake():
    """Prevents the computer from sleeping until this process ends, when the system allows it."""
    pid = str(os.getpid())
    if sys.platform == "darwin":
        subprocess.Popen(["caffeinate", "-i", "-w", pid], **QUIET)
    elif sys.platform == "win32":
        import ctypes
        continuous, system_required = 0x80000000, 0x00000001
        ctypes.windll.kernel32.SetThreadExecutionState(continuous | system_required)
    elif shutil.which("systemd-inhibit") and shutil.which("tail"):
        subprocess.Popen(["systemd-inhibit", "--what=idle:sleep", "--who=TheoLDR", "--why=Processing a video",
                          "tail", f"--pid={pid}", "-f", "/dev/null"], **QUIET)


def notify(message):
    """Desktop notification, if the system has a simple way to show one."""
    if sys.platform == "darwin":
        script = f"display notification {json.dumps(message)} with title \"TheoLDR\""
        subprocess.run(["osascript", "-e", script], check=False, **QUIET)
    elif shutil.which("notify-send"):
        subprocess.run(["notify-send", "TheoLDR", message], check=False, **QUIET)


def open_folder(folder):
    if sys.platform == "darwin":
        subprocess.run(["open", str(folder)], check=False, **QUIET)
    elif sys.platform == "win32":
        os.startfile(folder)
    elif shutil.which("xdg-open"):
        subprocess.run(["xdg-open", str(folder)], check=False, **QUIET)



def h264_encoders():
    """Encoders to try in order: hardware on macOS (missing in some VMs), then libx264."""
    software = ["-c:v", "libx264", "-preset", "fast"]
    if sys.platform == "darwin":
        return [["-c:v", "h264_videotoolbox"], software]
    return [software]
