# RUN: sed 's|ROOT|%S/fixtures/project|g' %s > %t && nixd --enable-project-config --lit-test < %t | FileCheck %s

This catches editor patches that lose file-base fields, or rebuild from the
previous editor configuration instead of the immutable project-file base.

<-- initialize(0)

```json
{ "jsonrpc": "2.0", "id": 0, "method": "initialize", "params": { "processId": 123, "rootUri": "file://ROOT", "capabilities": { "workspace": { "configuration": true } } } }
```

```json
{ "jsonrpc": "2.0", "id": 1, "result": [null] }
```

```nix file:///file-editor-overlay.nix
{ x = 1; }
```

<-- workspace/didChangeConfiguration

```json
{ "jsonrpc": "2.0", "method": "workspace/didChangeConfiguration", "params": { "settings": {} } }
```

```json
{ "jsonrpc": "2.0", "id": 2, "result": [{ "diagnostic": {} }] }
```

<-- textDocument/formatting(3)

```json
{ "jsonrpc": "2.0", "id": 3, "method": "textDocument/formatting", "params": { "textDocument": { "uri": "file:///file-editor-overlay.nix" }, "options": { "tabSize": 2, "insertSpaces": true } } }
```

<-- workspace/didChangeConfiguration

```json
{ "jsonrpc": "2.0", "method": "workspace/didChangeConfiguration", "params": { "settings": {} } }
```

```json
{ "jsonrpc": "2.0", "id": 3, "result": [{ "formatting": { "command": ["sh", "-c", "printf editor-format"] } }] }
```

<-- textDocument/formatting(4)

```json
{ "jsonrpc": "2.0", "id": 4, "method": "textDocument/formatting", "params": { "textDocument": { "uri": "file:///file-editor-overlay.nix" }, "options": { "tabSize": 2, "insertSpaces": true } } }
```

<-- workspace/didChangeConfiguration

```json
{ "jsonrpc": "2.0", "method": "workspace/didChangeConfiguration", "params": { "settings": {} } }
```

```json
{ "jsonrpc": "2.0", "id": 4, "result": [{}] }
```

<-- textDocument/formatting(5)

```json
{ "jsonrpc": "2.0", "id": 5, "method": "textDocument/formatting", "params": { "textDocument": { "uri": "file:///file-editor-overlay.nix" }, "options": { "tabSize": 2, "insertSpaces": true } } }
```

```
CHECK: "newText": "project-format"
```

```json
{ "jsonrpc": "2.0", "method": "exit" }
```
