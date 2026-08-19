# RUN: sed 's|ROOT|%S/fixtures/project|g' %s > %t && nixd --enable-project-config --lit-test < %t | FileCheck %s

This catches project configuration that parses diagnostic.suppress but does not
apply it when publishing diagnostics.

<-- initialize(0)

```json
{
  "jsonrpc": "2.0",
  "id": 0,
  "method": "initialize",
  "params": { "processId": 123, "rootUri": "file://ROOT", "capabilities": {} }
}
```

```nix file:///modern-diagnostic.nix
{x, y}: x + 1
```

```
CHECK: "diagnostics": [],
CHECK: "uri": "file:///modern-diagnostic.nix",
```

```json
{ "jsonrpc": "2.0", "method": "exit" }
```
