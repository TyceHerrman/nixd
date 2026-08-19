# RUN: nixd --lit-test -config='{ "formatting": { "command": ["sh", "-c", "printf cli"] } }' < %s | FileCheck %s

This catches workspace overlays that replace the active configuration instead
of rebuilding from the immutable CLI base. It also distinguishes valid null
overlays (which reset to the base) from an invalid empty response (which must
retain the active editor configuration).

<-- initialize(0)

```json
{
  "jsonrpc": "2.0",
  "id": 0,
  "method": "initialize",
  "params": {
    "processId": 123,
    "rootPath": "",
    "capabilities": { "workspace": { "configuration": true } }
  }
}
```

```json
{ "jsonrpc": "2.0", "id": 1, "result": [null] }
```

```nix file:///editor-overlay.nix
{ x = 1; }
```

```json
{
  "jsonrpc": "2.0",
  "id": 2,
  "method": "textDocument/formatting",
  "params": {
    "textDocument": { "uri": "file:///editor-overlay.nix" },
    "options": { "tabSize": 2, "insertSpaces": true }
  }
}
```

<-- workspace/didChangeConfiguration

```json
{ "jsonrpc": "2.0", "method": "workspace/didChangeConfiguration", "params": { "settings": {} } }
```

```json
{
  "jsonrpc": "2.0",
  "id": 2,
  "result": [{ "formatting": { "command": ["sh", "-c", "printf editor"] } }]
}
```

```json
{
  "jsonrpc": "2.0",
  "id": 3,
  "method": "textDocument/formatting",
  "params": {
    "textDocument": { "uri": "file:///editor-overlay.nix" },
    "options": { "tabSize": 2, "insertSpaces": true }
  }
}
```

<-- workspace/didChangeConfiguration

```json
{ "jsonrpc": "2.0", "method": "workspace/didChangeConfiguration", "params": { "settings": {} } }
```

```json
{ "jsonrpc": "2.0", "id": 3, "result": [{}] }
```

```json
{
  "jsonrpc": "2.0",
  "id": 4,
  "method": "textDocument/formatting",
  "params": {
    "textDocument": { "uri": "file:///editor-overlay.nix" },
    "options": { "tabSize": 2, "insertSpaces": true }
  }
}
```

<-- workspace/didChangeConfiguration

```json
{ "jsonrpc": "2.0", "method": "workspace/didChangeConfiguration", "params": { "settings": {} } }
```

```json
{ "jsonrpc": "2.0", "id": 4, "result": [{ "formatting": { "command": ["sh", "-c", "printf editor"] } }] }
```

```json
{
  "jsonrpc": "2.0",
  "id": 5,
  "method": "textDocument/formatting",
  "params": {
    "textDocument": { "uri": "file:///editor-overlay.nix" },
    "options": { "tabSize": 2, "insertSpaces": true }
  }
}
```

<-- workspace/didChangeConfiguration

```json
{ "jsonrpc": "2.0", "method": "workspace/didChangeConfiguration", "params": { "settings": {} } }
```

```json
{ "jsonrpc": "2.0", "id": 5, "result": [null] }
```

```json
{
  "jsonrpc": "2.0",
  "id": 6,
  "method": "textDocument/formatting",
  "params": {
    "textDocument": { "uri": "file:///editor-overlay.nix" },
    "options": { "tabSize": 2, "insertSpaces": true }
  }
}
```

<-- workspace/didChangeConfiguration

```json
{ "jsonrpc": "2.0", "method": "workspace/didChangeConfiguration", "params": { "settings": {} } }
```

```json
{ "jsonrpc": "2.0", "id": 6, "result": [{ "formatting": { "command": ["sh", "-c", "printf editor"] } }] }
```

```json
{
  "jsonrpc": "2.0",
  "id": 7,
  "method": "textDocument/formatting",
  "params": {
    "textDocument": { "uri": "file:///editor-overlay.nix" },
    "options": { "tabSize": 2, "insertSpaces": true }
  }
}
```

<-- workspace/didChangeConfiguration

```json
{ "jsonrpc": "2.0", "method": "workspace/didChangeConfiguration", "params": { "settings": {} } }
```

```json
{ "jsonrpc": "2.0", "id": 7, "result": [] }
```

```json
{
  "jsonrpc": "2.0",
  "id": 8,
  "method": "textDocument/formatting",
  "params": {
    "textDocument": { "uri": "file:///editor-overlay.nix" },
    "options": { "tabSize": 2, "insertSpaces": true }
  }
}
```

```
CHECK: "newText": "editor"
```

```json
{ "jsonrpc": "2.0", "method": "exit" }
```
