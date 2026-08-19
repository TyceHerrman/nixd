/// \file
/// \brief Implementation of [Formatting].
/// [Formatting]:
/// https://microsoft.github.io/language-server-protocol/specifications/lsp/3.17/specification/#textDocument_formatting
///
/// For now nixd only support "external" formatting. That is, invokes an
/// external command and then let that process do formatting.

#include "nixd/Controller/Controller.h"
#include "nixd/Support/AutoCloseFD.h"
#include "nixd/Support/ForkPiped.h"

#include <boost/asio/post.hpp>
#include <fcntl.h>
#include <poll.h>
#include <pthread.h>
#include <signal.h>
#include <sys/wait.h>

using namespace nixd;
using namespace lspserver;

namespace {
constexpr int FormatterChdirFailureSignal = SIGUSR2;
constexpr char FormatterChdirFailure = 'C';
constexpr char FormatterExecFailure = 'E';

void closeFD(nixd::util::AutoCloseFD &FD) {
  if (FD.isReleased())
    return;
  close(FD.get());
  FD.release();
}

bool waitForChild(pid_t Child, int &Status, std::error_code &Error) {
  while (waitpid(Child, &Status, 0) == -1) {
    if (errno == EINTR)
      continue;
    Error = std::error_code(errno, std::generic_category());
    return false;
  }
  return true;
}

void reportSetupFailure(int FD, char Failure) {
  while (write(FD, &Failure, sizeof(Failure)) == -1 && errno == EINTR) {
  }
}

ssize_t writeWithoutSigpipe(int FD, const void *Buffer, size_t Size) {
#ifdef F_SETNOSIGPIPE
  ssize_t Result;
  do {
    Result = write(FD, Buffer, Size);
  } while (Result == -1 && errno == EINTR);
  return Result;
#else
  sigset_t Sigpipe;
  sigemptyset(&Sigpipe);
  sigaddset(&Sigpipe, SIGPIPE);

  sigset_t PreviousMask;
  int MaskError = pthread_sigmask(SIG_BLOCK, &Sigpipe, &PreviousMask);
  if (MaskError != 0) {
    errno = MaskError;
    return -1;
  }

  sigset_t Pending;
  if (sigpending(&Pending) == -1) {
    int PendingError = errno;
    pthread_sigmask(SIG_SETMASK, &PreviousMask, nullptr);
    errno = PendingError;
    return -1;
  }
  const bool WasPending = sigismember(&Pending, SIGPIPE) == 1;

  ssize_t Result;
  do {
    Result = write(FD, Buffer, Size);
  } while (Result == -1 && errno == EINTR);
  int WriteError = errno;

  if (Result == -1 && WriteError == EPIPE && !WasPending) {
    int Signal = 0;
    while ((MaskError = sigwait(&Sigpipe, &Signal)) == EINTR) {
    }
  }

  int RestoreError = pthread_sigmask(SIG_SETMASK, &PreviousMask, nullptr);
  if (Result != -1 && RestoreError != 0) {
    errno = RestoreError;
    return -1;
  }
  errno = WriteError;
  return Result;
#endif
}

std::error_code suppressSigpipe(int FD) {
#ifdef F_SETNOSIGPIPE
  int Result;
  do {
    Result = fcntl(FD, F_SETNOSIGPIPE, 1);
  } while (Result == -1 && errno == EINTR);
  if (Result == -1)
    return std::error_code(errno, std::generic_category());
#endif
  return {};
}

std::error_code setNonBlocking(int FD) {
  int Flags;
  do {
    Flags = fcntl(FD, F_GETFL);
  } while (Flags == -1 && errno == EINTR);
  if (Flags == -1)
    return std::error_code(errno, std::generic_category());

  int Result;
  do {
    Result = fcntl(FD, F_SETFL, Flags | O_NONBLOCK);
  } while (Result == -1 && errno == EINTR);
  if (Result == -1)
    return std::error_code(errno, std::generic_category());
  return {};
}

struct FormatterIOResult {
  std::string Response;
  std::error_code ConfigurationError;
  std::error_code WriteError;
  std::error_code ReadError;
  std::error_code StderrReadError;
  std::error_code PollError;
};

void drainFormatterFD(util::AutoCloseFD &FD, std::string *Output,
                      std::error_code &Error) {
  while (!FD.isReleased()) {
    char Buffer[8192];
    const ssize_t Read = read(FD.get(), Buffer, sizeof(Buffer));
    if (Read > 0) {
      if (Output)
        Output->append(Buffer, Read);
      return;
    }
    if (Read == 0) {
      closeFD(FD);
      return;
    }
    if (errno == EINTR)
      continue;
    if (errno == EAGAIN || errno == EWOULDBLOCK)
      return;
    Error = std::error_code(errno, std::generic_category());
    closeFD(FD);
  }
}

FormatterIOResult pumpFormatter(const std::string &Code,
                                util::AutoCloseFD &Input,
                                util::AutoCloseFD &Output,
                                util::AutoCloseFD &Error, bool SendInput) {
  FormatterIOResult Result;

  if (std::error_code EC = suppressSigpipe(Input.get())) {
    Result.ConfigurationError = EC;
    closeFD(Input);
    closeFD(Output);
    closeFD(Error);
    return Result;
  }

  for (int FD : {Input.get(), Output.get(), Error.get()}) {
    if (std::error_code EC = setNonBlocking(FD)) {
      Result.ConfigurationError = EC;
      closeFD(Input);
      closeFD(Output);
      closeFD(Error);
      return Result;
    }
  }

  const char *InputPosition = Code.data();
  const char *InputEnd = Code.data() + Code.size();
  if (!SendInput || InputPosition == InputEnd)
    closeFD(Input);

  while (!Input.isReleased() || !Output.isReleased() || !Error.isReleased()) {
    pollfd PollFDs[3];
    nfds_t Count = 0;
    int InputIndex = -1;
    int OutputIndex = -1;
    int ErrorIndex = -1;

    if (!Input.isReleased()) {
      InputIndex = Count;
      PollFDs[Count++] = {Input.get(), POLLOUT, 0};
    }
    if (!Output.isReleased()) {
      OutputIndex = Count;
      PollFDs[Count++] = {Output.get(), POLLIN, 0};
    }
    if (!Error.isReleased()) {
      ErrorIndex = Count;
      PollFDs[Count++] = {Error.get(), POLLIN, 0};
    }

    int PollResult;
    do {
      PollResult = poll(PollFDs, Count, -1);
    } while (PollResult == -1 && errno == EINTR);
    if (PollResult == -1) {
      Result.PollError = std::error_code(errno, std::generic_category());
      closeFD(Input);
      closeFD(Output);
      closeFD(Error);
      break;
    }

    auto Drain = [&](int Index, util::AutoCloseFD &FD, std::string *Contents,
                     std::error_code &ReadError) {
      if (Index == -1)
        return;
      const short Events = PollFDs[Index].revents;
      if (Events & POLLNVAL) {
        ReadError = std::error_code(EBADF, std::generic_category());
        closeFD(FD);
        return;
      }
      if (Events & (POLLIN | POLLHUP | POLLERR))
        drainFormatterFD(FD, Contents, ReadError);
    };

    Drain(OutputIndex, Output, &Result.Response, Result.ReadError);
    Drain(ErrorIndex, Error, nullptr, Result.StderrReadError);

    if (InputIndex == -1)
      continue;
    const short InputEvents = PollFDs[InputIndex].revents;
    if (InputEvents & POLLNVAL) {
      Result.WriteError = std::error_code(EBADF, std::generic_category());
      closeFD(Input);
      continue;
    }
    if (!(InputEvents & (POLLOUT | POLLHUP | POLLERR)))
      continue;

    const ssize_t Written = writeWithoutSigpipe(Input.get(), InputPosition,
                                                InputEnd - InputPosition);
    if (Written > 0) {
      InputPosition += Written;
    } else if (Written != -1 || (errno != EAGAIN && errno != EWOULDBLOCK)) {
      Result.WriteError =
          std::error_code(Written == 0 ? EIO : errno, std::generic_category());
      closeFD(Input);
    }
    if (!Input.isReleased() && InputPosition == InputEnd)
      closeFD(Input);
  }

  return Result;
}
} // namespace

void Controller::onFormat(const DocumentFormattingParams &Params,
                          Callback<std::vector<TextEdit>> Reply) {
  auto Action = [this, Params, Reply = std::move(Reply)]() mutable {
    lspserver::PathRef File = Params.textDocument.uri.file();
    const std::string &Code = *Store.getDraft(File)->Contents;
    // Invokes another process and then read it's stdout.
    std::vector<std::string> FormatCommand;
    {
      // Read from config, get format options.
      std::lock_guard G(ConfigLock);
      FormatCommand = Config.formatting.command;
    }

    if (FormatCommand.empty()) {
      Reply(error("formating command is empty, please set external formatter"));
      return;
    }

    // Convert vectors to syscall form. This should be cheap.
    std::vector<char *> Syscall;
    Syscall.reserve(FormatCommand.size());
    for (const auto &Str : FormatCommand) {
      // For compatibility with existing C code.
      Syscall.emplace_back(const_cast<char *>(Str.c_str()));
    }

    // Null terminator.
    Syscall.emplace_back(nullptr);

    int In;
    int Out;
    int Err;
    const std::filesystem::path RootPath = Root.path;

    ForkPipedExtraPipe SetupPipe;
    pid_t Child;
    try {
      Child = forkPiped(In, Out, Err, &SetupPipe);
    } catch (const std::system_error &Error) {
      if (SetupPipe.Failure == ForkPipedExtraPipeFailure::Create) {
        Reply(error("failed to create formatter setup pipe: {0}",
                    Error.code().message()));
        return;
      }
      if (SetupPipe.Failure == ForkPipedExtraPipeFailure::Configure) {
        Reply(error("failed to configure formatter setup pipe: {0}",
                    Error.code().message()));
        return;
      }
      Reply(error("failed to launch formatter: {0}", Error.what()));
      return;
    }
    util::AutoCloseFD SetupRead(SetupPipe.Read);
    util::AutoCloseFD SetupWrite(SetupPipe.Write);
    if (Child == 0) {
      close(SetupRead.get());
      if (chdir(RootPath.c_str()) != 0) {
        reportSetupFailure(SetupWrite.get(), FormatterChdirFailure);
        close(SetupWrite.get());
        kill(getpid(), FormatterChdirFailureSignal);
        _exit(-1);
      }
      execvp(Syscall[0], Syscall.data());
      reportSetupFailure(SetupWrite.get(), FormatterExecFailure);
      close(SetupWrite.get());
      _exit(-1);
    }

    util::AutoCloseFD Input(In);
    util::AutoCloseFD Output(Out);
    util::AutoCloseFD Error(Err);
    closeFD(SetupWrite);

    char SetupFailure = 0;
    ssize_t SetupResult;
    do {
      SetupResult = read(SetupRead.get(), &SetupFailure, sizeof(SetupFailure));
    } while (SetupResult == -1 && errno == EINTR);
    const std::error_code SetupError =
        SetupResult == -1 ? std::error_code(errno, std::generic_category())
                          : std::error_code();
    closeFD(SetupRead);

    FormatterIOResult IO =
        pumpFormatter(Code, Input, Output, Error, SetupResult == 0);

    // Reap only after closing input and draining both output pipes.
    int Exit = 0;
    std::error_code WaitError;
    if (!waitForChild(Child, Exit, WaitError)) {
      Reply(error("failed to wait for formatter: {0}", WaitError.message()));
      return;
    }

    if (WIFSIGNALED(Exit) && WTERMSIG(Exit) == FormatterChdirFailureSignal) {
      Reply(error("failed to change formatter working directory to {0}",
                  RootPath.string()));
      return;
    }

    if (SetupResult == -1) {
      Reply(error("failed to inspect formatter setup: {0}",
                  SetupError.message()));
      return;
    }

    if (SetupResult != 0 && SetupFailure != FormatterExecFailure) {
      Reply(error("formatter setup failed before execution"));
      return;
    }

    if (IO.ConfigurationError) {
      Reply(error("failed to configure formatter pipes: {0}",
                  IO.ConfigurationError.message()));
      return;
    }

    if (Exit != 0) {
      Reply(error("formatting {0} command exited with {1}", FormatCommand[0],
                  Exit));
      return;
    }

    if (IO.WriteError) {
      Reply(error("failed to write formatter input: {0}",
                  IO.WriteError.message()));
      return;
    }

    if (IO.ReadError) {
      Reply(error("failed to read formatter output: {0}",
                  IO.ReadError.message()));
      return;
    }

    if (IO.StderrReadError) {
      Reply(error("failed to read formatter error output: {0}",
                  IO.StderrReadError.message()));
      return;
    }

    if (IO.PollError) {
      Reply(error("failed to communicate with formatter: {0}",
                  IO.PollError.message()));
      return;
    }

    if (IO.Response == Code) {
      Reply(std::vector<TextEdit>{});
      return;
    }

    TextEdit E{{{0, 0}, {INT_MAX, INT_MAX}}, IO.Response};
    Reply(std::vector{E});
  };

  boost::asio::post(Pool, std::move(Action));
}
