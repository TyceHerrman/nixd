# RUN: nixd --lit-test -config='{ "formatting": { "command": ["sh", "-c", "printf cli-format"] } }' < %s | FileCheck %s

This catches invalid workspace/configuration replies that replace the active
editor configuration instead of leaving it untouched.

<-- initialize(0)

```json
{ "jsonrpc": "2.0", "id": 0, "method": "initialize", "params": { "processId": 123, "rootPath": "", "capabilities": { "workspace": { "configuration": true } } } }
```

```json
{ "jsonrpc": "2.0", "id": 1, "result": [null] }
```

```nix file:///invalid-editor-responses.nix
{ x = 1; }
```

<-- workspace/didChangeConfiguration

```json
{ "jsonrpc": "2.0", "method": "workspace/didChangeConfiguration", "params": { "settings": {} } }
```

```json
{ "jsonrpc": "2.0", "id": 2, "result": [{ "formatting": { "command": ["sh", "-c", "printf editor-format"] } }] }
```

<-- textDocument/formatting(3)

```json
{ "jsonrpc": "2.0", "id": 3, "method": "textDocument/formatting", "params": { "textDocument": { "uri": "file:///invalid-editor-responses.nix" }, "options": { "tabSize": 2, "insertSpaces": true } } }
```

<-- workspace/didChangeConfiguration

```json
{ "jsonrpc": "2.0", "method": "workspace/didChangeConfiguration", "params": { "settings": {} } }
```

```json
{ "jsonrpc": "2.0", "id": 3, "result": null }
```

<-- textDocument/formatting(4)

```json
{ "jsonrpc": "2.0", "id": 4, "method": "textDocument/formatting", "params": { "textDocument": { "uri": "file:///invalid-editor-responses.nix" }, "options": { "tabSize": 2, "insertSpaces": true } } }
```

<-- workspace/didChangeConfiguration

```json
{ "jsonrpc": "2.0", "method": "workspace/didChangeConfiguration", "params": { "settings": {} } }
```

```json
{ "jsonrpc": "2.0", "id": 4, "result": [17] }
```

<-- textDocument/formatting(5)

```json
{ "jsonrpc": "2.0", "id": 5, "method": "textDocument/formatting", "params": { "textDocument": { "uri": "file:///invalid-editor-responses.nix" }, "options": { "tabSize": 2, "insertSpaces": true } } }
```

<-- workspace/didChangeConfiguration

```json
{ "jsonrpc": "2.0", "method": "workspace/didChangeConfiguration", "params": { "settings": {} } }
```

```json
{ "jsonrpc": "2.0", "id": 5, "result": [{ "formatting": { "command": "not-an-array" } }] }
```

<-- textDocument/formatting(6)

```json
{ "jsonrpc": "2.0", "id": 6, "method": "textDocument/formatting", "params": { "textDocument": { "uri": "file:///invalid-editor-responses.nix" }, "options": { "tabSize": 2, "insertSpaces": true } } }
```

<-- workspace/didChangeConfiguration

```json
{ "jsonrpc": "2.0", "method": "workspace/didChangeConfiguration", "params": { "settings": {} } }
```

```json
{ "jsonrpc": "2.0", "id": 6, "error": { "code": -32603, "message": "request failed" } }
```

<-- textDocument/formatting(7)

```json
{ "jsonrpc": "2.0", "id": 7, "method": "textDocument/formatting", "params": { "textDocument": { "uri": "file:///invalid-editor-responses.nix" }, "options": { "tabSize": 2, "insertSpaces": true } } }
```

```
CHECK: "newText": "editor-format"
CHECK: "newText": "editor-format"
CHECK: "newText": "editor-format"
CHECK: "newText": "editor-format"
CHECK: "newText": "editor-format"
```

```json
{ "jsonrpc": "2.0", "method": "exit" }
```
