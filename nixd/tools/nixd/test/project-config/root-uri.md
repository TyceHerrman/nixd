# RUN: sed 's|ROOT|%S/fixtures/project|g' %s > %t && nixd --enable-project-config --lit-test < %t | FileCheck %s

This catches root selection that ignores `rootUri` or incorrectly prefers the
deprecated `rootPath` when both are supplied.

<-- initialize(0)

```json
{
  "jsonrpc": "2.0",
  "id": 0,
  "method": "initialize",
  "params": {
    "processId": 123,
    "rootUri": "file://ROOT",
    "rootPath": "/definitely-not-the-project-root",
    "capabilities": {}
  }
}
```

```nix file:///project-root-uri.nix
{ x = 1; }
```

<-- textDocument/formatting(2)

```json
{
  "jsonrpc": "2.0",
  "id": 2,
  "method": "textDocument/formatting",
  "params": {
    "textDocument": { "uri": "file:///project-root-uri.nix" },
    "options": { "tabSize": 2, "insertSpaces": true }
  }
}
```

```
CHECK: "newText": "project-format"
```

```json
{"jsonrpc":"2.0","method":"exit"}
```
