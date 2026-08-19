# RUN: sed 's|ROOT|%S/fixtures/project|g' %s > %t && nixd --enable-project-config --lit-test < %t | FileCheck %s

This catches an editor options patch that merges with, rather than replaces,
the complete project-file options map.

<-- initialize(0)

```json
{ "jsonrpc": "2.0", "id": 0, "method": "initialize", "params": { "processId": 123, "rootUri": "file://ROOT", "capabilities": { "workspace": { "configuration": true } } } }
```

```json
{ "jsonrpc": "2.0", "id": 1, "result": [null] }
```

```nix file:///options-replace.nix
{  }
```

<-- workspace/didChangeConfiguration

```json
{ "jsonrpc": "2.0", "method": "workspace/didChangeConfiguration", "params": { "settings": {} } }
```

```json
{ "jsonrpc": "2.0", "id": 2, "result": [{ "options": { "editor": { "expr": "{ editor.option = { _type = \"option\"; }; }" } } }] }
```

```json
{ "jsonrpc": "2.0", "id": 3, "method": "textDocument/completion", "params": { "textDocument": { "uri": "file:///options-replace.nix" }, "position": { "line": 0, "character": 2 }, "context": { "triggerKind": 1 } } }
```

```
CHECK: "id": 3,
CHECK-NOT: "label": "project"
CHECK: "detail": "editor"
CHECK: "label": "editor"
```

```json
{ "jsonrpc": "2.0", "method": "exit" }
```
