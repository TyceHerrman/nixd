# RUN: sed 's|ROOT|%S/fixtures/ancestor/child|g' %s > %t && nixd --enable-project-config --lit-test < %t | FileCheck %s

This catches ancestor traversal: only the exact initialized root may supply a
.nixd.json, so the parent formatter must not be selected for its child.

<-- initialize(0)

```json
{
  "jsonrpc": "2.0",
  "id": 0,
  "method": "initialize",
  "params": { "processId": 123, "rootPath": "ROOT", "capabilities": {} }
}
```

```nix file:///no-ancestor.nix
{ x = 1; }
```

<-- textDocument/formatting(2)

```json
{
  "jsonrpc": "2.0",
  "id": 2,
  "method": "textDocument/formatting",
  "params": {
    "textDocument": { "uri": "file:///no-ancestor.nix" },
    "options": { "tabSize": 2, "insertSpaces": true }
  }
}
```

```
CHECK: "id": 2,
CHECK-NOT: ancestor-format
```

```json
{ "jsonrpc": "2.0", "method": "exit" }
```
