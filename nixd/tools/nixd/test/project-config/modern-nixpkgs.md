# RUN: sed 's|ROOT|%S/fixtures/project|g' %s > %t && nixd --enable-project-config --lit-test < %t | FileCheck %s

This catches project configuration that accepts formatting but does not apply
its modern nixpkgs expression to language features.

<-- initialize(0)

```json
{
  "jsonrpc": "2.0",
  "id": 0,
  "method": "initialize",
  "params": { "processId": 123, "rootUri": "file://ROOT", "capabilities": {} }
}
```

```nix file:///modern-nixpkgs.nix
pkgs.project
```

<-- textDocument/hover(2)

```json
{
  "jsonrpc": "2.0",
  "id": 2,
  "method": "textDocument/hover",
  "params": {
    "textDocument": { "uri": "file:///modern-nixpkgs.nix" },
    "position": { "line": 0, "character": 6 }
  }
}
```

```
CHECK: "id": 2,
CHECK: "value": "## Description\n\nproject nixpkgs\n\n"
```

```json
{ "jsonrpc": "2.0", "method": "exit" }
```
