# RUN: sed 's|ROOT|%S/fixtures/project|g' %s > %t && nixd --enable-project-config --lit-test < %t | FileCheck %s

This catches project configuration that accepts other fields but does not apply
its named modern options provider to completion.

<-- initialize(0)

```json
{
  "jsonrpc": "2.0",
  "id": 0,
  "method": "initialize",
  "params": { "processId": 123, "rootUri": "file://ROOT", "capabilities": {} }
}
```

```nix file:///modern-options.nix
{ pro }
```

```json
{
  "jsonrpc": "2.0",
  "id": 2,
  "method": "textDocument/completion",
  "params": {
    "textDocument": { "uri": "file:///modern-options.nix" },
    "position": { "line": 0, "character": 5 },
    "context": { "triggerKind": 1 }
  }
}
```

```
CHECK: "id": 2,
CHECK: "detail": "project"
CHECK: "label": "project"
```

```json
{ "jsonrpc": "2.0", "method": "exit" }
```
