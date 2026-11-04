# Plugin architecture status

The supplied v0.4.0 source does not contain a plugin directory, plugin loader, dependency manifest, enable/disable controls, or plugin permission boundary. Existing behavior is implemented directly in `core/bot.py` and `core/verify.py`.

No plugin API is claimed by this build. Adding a real plugin system needs a separate design for trusted-code loading, startup failure isolation, command registration, per-plugin configuration, permissions, dependency/version handling, and audit logs. A plugin cannot safely be treated as a data-only extension when Python code runs with the bot process's full privileges.

For now, extend the current `core` modules and add tests alongside each feature. Keep external integrations behind dedicated adapter modules and do not load arbitrary files from an untrusted plugin folder.
