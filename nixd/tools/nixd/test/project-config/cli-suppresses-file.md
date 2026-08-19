# RUN: sed 's|ROOT|%S/fixtures/project|g' %s > %t && nixd --enable-project-config --lit-test -config='{ "formatting": { "command": ["sh", "-c", "printf cli-format"] } }' < %t | FileCheck %s

This catches source precedence that loads a project file despite an explicitly
supplied CLI base configuration.

<-- initialize(0)

```json
{
  "jsonrpc": "2.0",
  "id": 0,
  "method": "initialize",
  "params": { "processId": 123, "rootUri": "file://ROOT", "capabilities": {} }
}
```

```nix file:///cli-suppresses-file.nix
{ x = 1; }
```

<-- textDocument/formatting(2)

```json
{
  "jsonrpc": "2.0",
  "id": 2,
  "method": "textDocument/formatting",
  "params": {
    "textDocument": { "uri": "file:///cli-suppresses-file.nix" },
    "options": { "tabSize": 2, "insertSpaces": true }
  }
}
```

```
CHECK: "id": 2,
CHECK: "newText": "cli-format"
CHECK-NOT: project-format
```

```json
{ "jsonrpc": "2.0", "method": "exit" }
```
