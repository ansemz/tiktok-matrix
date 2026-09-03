"""Example of a standalone script.

Run it yourself; TikMatrix only lends you the devices:

    python example_standalone.py

Each device is leased for the duration of the `with` block, so the task queue
will not dispatch work to it. Devices already busy are skipped, and the plan's
device count caps how many can be leased at once.
"""

import sys

from tikmatrix import DeviceBusyError, TikMatrix, TikMatrixError


def main() -> int:
    client = TikMatrix()

    devices = client.devices()
    if not devices:
        print("No devices are online.", file=sys.stderr)
        return 1

    for entry in devices:
        serial = entry["serial"]
        if entry["busy"]:
            print(f"{serial}: busy, skipping")
            continue

        try:
            with client.device(serial, label="standalone example") as device:
                info = device.info()
                # Plain ASCII: this runs in whatever console the user has, and
                # a Windows code page will mangle anything fancier.
                print(
                    f"{serial}: {info.get('productName')} "
                    f"{info.get('displayWidth')}x{info.get('displayHeight')} "
                    f"sdk={info.get('sdkInt')}"
                )
                device.press("home")
        except DeviceBusyError as error:
            # Either another script took the device between listing and
            # leasing, or the plan has no free slot left.
            print(f"{serial}: {error}")

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except TikMatrixError as error:
        print(f"Failed: {error}", file=sys.stderr)
        sys.exit(1)
