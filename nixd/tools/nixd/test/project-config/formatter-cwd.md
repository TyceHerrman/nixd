# RUN: python3 %S/formatter-cwd.py root-uri
# RUN: python3 %S/formatter-cwd.py root-path
# RUN: python3 %S/formatter-cwd.py launch
# RUN: python3 %S/formatter-cwd.py exit-125
# RUN: python3 %S/formatter-cwd.py signal-usr2

Each real server loads a project-relative `./formatter`. Its literal output is
observable only when the formatter child runs from the selected `rootUri`,
non-empty `rootPath`, or the captured launch-directory fallback.
An ordinary formatter exit status of 125 must remain an ordinary command
failure rather than being confused with a child working-directory failure.
A formatter genuinely terminated by SIGUSR2 is likewise an ordinary formatter
failure; that signal is not a private child-setup protocol.
