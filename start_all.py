import subprocess
import signal
import sys
import time
from pathlib import Path

ROOT = Path(r"E:\AI\voice-agent")

processes = []


def start_service(name, command, cwd):
    print(f"\nStarting: {name}")

    process = subprocess.Popen(
        command,
        cwd=cwd,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
        shell=True
    )

    processes.append((name, process))


def cleanup():
    print("\nStopping all services...")

    for name, process in processes:
        try:
            print(f"Stopping {name}...")
            process.send_signal(signal.CTRL_BREAK_EVENT)
            process.terminate()
        except Exception as e:
            print(f"Error stopping {name}: {e}")

    print("All services stopped.")


try:
    # Backend API
    start_service(
        "Main Server",
        "python -m server.main",
        ROOT / "voice_agent_observability"
    )

    time.sleep(2)

    # Post Call Analyzer
    start_service(
        "Post Call Analyzer",
        "python -m server.services.post_call_analyzer",
        ROOT / "voice_agent_observability"
    )

    time.sleep(2)

    # Voice Obs API
    start_service(
        "Voice Obs API",
        "uvicorn main:app --reload --host 0.0.0.0 --port 8009",
        ROOT / "voice_agent_observability" / "voice_obs_api"
    )

    time.sleep(2)

    # Agent Server
    start_service(
        "Voice Agent",
        "python server.py",
        ROOT / "agent"
    )

    print("\nAll services started.")
    print("Press CTRL + C to stop everything.\n")

    while True:
        time.sleep(1)

except KeyboardInterrupt:
    cleanup()
    sys.exit(0)