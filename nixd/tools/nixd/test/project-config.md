# RUN: python3 "%S/project_config_test.py" empty-formatter
# RUN: python3 "%S/project_config_test.py" source-selection
# RUN: python3 "%S/project_config_test.py" startup-warnings
# RUN: python3 "%S/project_config_test.py" editor-overlays
# RUN: python3 "%S/project_config_test.py" provider-recovery
# RUN: python3 "%S/project_config_test.py" provider-shutdown-drain
# RUN: python3 "%S/project_config_test.py" provider-shutdown-pending
# RUN: python3 "%S/project_config_test.py" provider-retirement
# RUN: python3 "%S/project_config_test.py" formatter-shutdown-queue
# RUN: python3 "%S/project_config_test.py" child-fork-stress
# RUN: python3 "%S/project_config_test.py" shutdown-outbound

The stdlib driver launches the actual \`nixd\` process.  Each named scenario
asserts observable project configuration behavior: source precedence and
startup fallbacks; editor overlay reset, invalid replies, and stale responses;
provider invalidation, recovery, retirement, and blocked-RPC shutdown;
formatter disabling and queued-work shutdown; and shutdown while the outbound
\`workspace/configuration\` request is unanswered.  Scenario failures are
prefixed with the selected scenario name.
