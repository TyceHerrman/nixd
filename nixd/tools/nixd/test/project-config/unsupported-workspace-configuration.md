# RUN: nixd --lit-test -config='{ "formatting": { "command": ["sh", "-c", "printf cli-format"] } }' < %s | FileCheck %s

This catches capability fallback that changes the selected CLI configuration
when the client does not support workspace/configuration.

<-- initialize(0)

```json
{ "jsonrpc": "2.0", "id": 0, "method": "initialize", "params": { "processId": 123, "rootPath": "", "capabilities": {} } }
```

```nix file:///unsupported-workspace-configuration.nix
{ x = 1; }
```

<-- textDocument/formatting(2)

```json
{ "jsonrpc": "2.0", "id": 2, "method": "textDocument/formatting", "params": { "textDocument": { "uri": "file:///unsupported-workspace-configuration.nix" }, "options": { "tabSize": 2, "insertSpaces": true } } }
```

```
CHECK: "id": 2,
CHECK: "newText": "cli-format"
```

```json
{ "jsonrpc": "2.0", "method": "exit" }
```
