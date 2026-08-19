# RUN: python3 %S/formatter-process-lifecycle.py removed-root
# RUN: python3 %S/formatter-process-lifecycle.py descriptor-stability
# RUN: python3 %S/formatter-process-lifecycle.py exec-failure

If a selected root becomes unusable after initialization, a large formatting
request must receive a coherent working-directory error without terminating
nixd via `SIGPIPE`. Repeated successful formatting under a bounded descriptor
limit must remain stable rather than leaking two descriptors per request.
An executable lookup failure must also return a normal formatter-command error
without hanging, leaking descriptors, or terminating nixd.
