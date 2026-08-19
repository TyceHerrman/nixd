#pragma once

namespace nixd {

enum class ForkPipedExtraPipeFailure { None, Create, Configure };

struct ForkPipedExtraPipe {
  int Read;
  int Write;
  ForkPipedExtraPipeFailure Failure = ForkPipedExtraPipeFailure::None;
};

/// \brief fork this process and create some pipes connected to the new process.
///
/// stdin, stdout, stderr in the new process will be closed, and these fds could
/// be used to communicate with it.
///
/// \returns pid of child process, in parent.
/// \returns 0 in child.
int forkPiped(int &In, int &Out, int &Err, ForkPipedExtraPipe *Extra = nullptr);

} // namespace nixd
