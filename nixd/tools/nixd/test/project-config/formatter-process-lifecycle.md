# RUN: python3 %S/formatter-process-lifecycle.py removed-root
# RUN: python3 %S/formatter-process-lifecycle.py stdout-after-input
# RUN: python3 %S/formatter-process-lifecycle.py stderr-then-echo
# RUN: python3 %S/formatter-process-lifecycle.py stdout-before-input
# RUN: python3 %S/formatter-process-lifecycle.py cross-inherited-stdin-eof
# RUN: python3 %S/formatter-process-lifecycle.py descriptor-stability
# RUN: python3 %S/formatter-process-lifecycle.py exec-failure

If a selected root becomes unusable after initialization, a large formatting
request must receive a coherent working-directory error without terminating
nixd via `SIGPIPE`.

A formatter that writes 4 MiB to stdout after reading its input catches nixd
waiting for child exit before draining stdout. A formatter that writes 4 MiB
to stderr before echoing its input catches nixd failing to drain the stderr
pipe. A formatter that writes 4 MiB to stdout before reading a 512 KiB input
catches serialized stdin/stdout handling that lets both pipe writers block.

Two gated concurrent formatters catch a formatter child inheriting an
unrelated request's stdin writer: after request A is released and consumes its
large input, it must receive EOF and complete while request B is still alive
behind its gate.

Repeated successful formatting under a bounded descriptor limit must remain
stable rather than leaking two descriptors per request. An executable lookup
failure must also return a normal formatter-command error without hanging,
leaking descriptors, or terminating nixd.
