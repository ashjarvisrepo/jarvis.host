# Test report for v0.6.6

## Checks completed

- Python 3.12 bytecode compilation passed for `main.py`, `core`, and `tests`.
- `BUILD_MANIFEST.json` parses as valid JSON.
- Runtime bot construction passed in the configured Python 3.14 virtual environment: 77 prefix commands register and the local application-command tree is empty.
- Role visibility check passed: members see member commands; staff do not see admin-only or owner commands; admins see staff/admin commands; the Discord guild owner sees all groups and passes the owner permission check.
- `$help` command groups stay within Discord's response embed limits.
- Release archive integrity passed.

## Not tested live

- Pytest cases were not run.
- Live Discord interactions, remote slash-command removal, and verification-panel posting were not tested. The updated bot must connect for remote slash commands to be cleared.
- SellAuth checkout and webhooks still require the user's live store settings and public HTTPS endpoint.
