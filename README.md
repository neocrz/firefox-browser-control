# firefox-browser-control

## Linux env
Requirements: Ollama installed + qwen3.5:2b model.

Clone the repo.

`chmod +x control-server/host.py`

Create file `~/.mozilla/native-messaging-hosts/com.nil.browser_control.json` (modify the `path` value first)
```json
{
  "name": "com.nil.browser_control",
  "description": "Python Native Bridge",
  "path": "/home/nil/Shared/projects/firefox-browser-control/control-server/host.py",
  "type": "stdio",
  "allowed_extensions": [
    "control@nil.com"
  ]
}
```


`about:debugging#/runtime/this-firefox`
- Load temporary extension (select the manifest from `control-extension`)

```
uv venv .venv
source .venv/bin/activate
uv pip install ollama requests

python main.py
```