# Contributing

Bug reports and focused improvements are welcome. When reporting a detection issue, include the game title, the kind of metadata found (Steam, GOG, Unity, or executable), and relevant log lines. Remove local paths, account names, and any personal information before posting logs or screenshots.

For code changes:

1. Keep folder discovery limited to direct children of the configured root. Never follow junctions or symbolic links.
2. Preserve user-owned `desktop.ini` data and existing working icons.
3. Keep network requests bounded and validate artwork as an image before writing an icon.
4. Run `py -3 -m unittest discover -s tests -v` and `py -3 -m py_compile .\auto_folder_icons.py` on Windows.
5. Describe how you tested a change and any user-visible behavior it changes.

Please do not commit downloaded game covers, local state files, logs, credentials, or game files.
