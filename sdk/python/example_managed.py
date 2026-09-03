"""Example of a managed custom script.

Register in TikMatrix under Devices -> Custom Scripts:

    Name:     Open settings
    Command:  python C:/scripts/example_managed.py
    Platform: Generic

Then run it from the Custom Scripts tab like any built-in script. Everything
printed here shows up in the task log, and a non-zero exit marks the task failed.
"""

import sys

from tikmatrix import TikMatrix, TikMatrixError


def main() -> int:
    # The app leased the device before starting this process and passed the
    # credentials through the environment, so there is nothing to acquire.
    with TikMatrix.from_env() as device:
        print(f"Driving {device.serial}")

        info = device.info()
        print(f"Screen: {info.get('displayWidth')}x{info.get('displayHeight')}")

        device.press("home")
        try:
            device.adb("shell", "am", "start", "-a", "android.settings.SETTINGS")
        except TikMatrixError as error:
            # ADB is opt-in (Settings -> Developer API -> Allow ADB commands).
            # Without it there is no way to launch Settings, so report that
            # rather than failing on the wait below, which would blame the
            # wrong thing.
            print(f"ADB is turned off, nothing to open: {error}")
            return 0

        # Fail loudly if the screen did not arrive — a task that silently did
        # nothing is worse than one that reports why.
        device.wait_for(text="Settings", timeout=15)
        print("Settings is open")

        device.screenshot("settings.png")
        print("Saved settings.png")

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except TikMatrixError as error:
        print(f"Script failed: {error}", file=sys.stderr)
        sys.exit(1)
