# TikMatrix

TikMatrix is a desktop app that automates TikTok and Instagram on connected
Android phones — multi-account management, bulk posting, follower and DM
automation, and task scheduling across a whole device farm.

- Website: <https://www.tikmatrix.com>
- Documentation: <https://tikmatrix.com/docs/intro>
- Downloads: <https://www.tikmatrix.com/Download-TikMatrix>
- Bug reports and feature requests: [Issues](https://github.com/tikmatrix/tikmatrix-desktop/issues)

## What is in this repository

| Path | Contents |
|---|---|
| [`sdk/python/`](sdk/python) | Python client and examples for the custom-script API — write your own automation and let TikMatrix hand you a phone |
| `.github/workflows/` | Release build pipelines for the desktop app, the script binary, and the APK |
| `scripts/` | Operational helpers |

The desktop app itself is closed source; this repository holds the parts you
build against, plus the pipelines that produce the published binaries.

## Custom scripts

The built-in scripts cover the common flows. When you need one they do not, you
can write it yourself in any language and drive the phone through TikMatrix's
local HTTP API:

```python
from tikmatrix import TikMatrix

client = TikMatrix()
with client.device("192.168.1.5:5555") as d:
    d.press("home")
    d.wait_for(text="Settings", timeout=15)
    d.screenshot("settings.png")
```

Start at [`sdk/python/README.md`](sdk/python/README.md), or read the full guide
at <https://tikmatrix.com/docs/api/custom-script>. The API is plain JSON over
HTTP, so the Python client is a convenience, not a requirement.

Custom scripts require a Pro plan or higher.

## License

The contents of this repository — the SDK, the examples, and the workflows —
are [MIT licensed](LICENSE), so you can copy `tikmatrix.py` into your own
project and change it freely. The TikMatrix desktop application itself is not
covered by this licence; it is proprietary and distributed under its own
[terms of service](https://www.tikmatrix.com/terms-of-service).
