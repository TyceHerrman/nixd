# RUN: python3 %S/project-config-io-error.py %s %t-root | FileCheck %s

This creates an accessible workspace with an existing unreadable project
configuration file. Initialization
must retain the built-in configuration after recording a structured I/O error;
it must not let filesystem status exceptions escape.

<-- initialize(0)

```json
{ "jsonrpc": "2.0", "id": 0, "method": "initialize", "params": { "processId": 123, "rootPath": "ROOT", "capabilities": {} } }
```

```nix file:///project-config-io-error.nix
{ x = 1; }
```

<-- textDocument/formatting(2)

```json
{ "jsonrpc": "2.0", "id": 2, "method": "textDocument/formatting", "params": { "textDocument": { "uri": "file:///project-config-io-error.nix" }, "options": { "tabSize": 2, "insertSpaces": true } } }
```

```
CHECK: "id": 2,
```

```json
{ "jsonrpc": "2.0", "method": "exit" }
```
