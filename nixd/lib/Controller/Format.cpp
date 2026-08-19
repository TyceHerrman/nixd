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
}
}

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

    int SetupPipe[2];
    if (pipe(SetupPipe) == -1) {
      Reply(error("failed to create formatter setup pipe: {0}",
                  std::error_code(errno, std::generic_category()).message()));
      return;
    }
    util::AutoCloseFD SetupRead(SetupPipe[0]);
    util::AutoCloseFD SetupWrite(SetupPipe[1]);
    int SetupFlags = fcntl(SetupWrite.get(), F_GETFD);
    if (SetupFlags == -1 ||
        fcntl(SetupWrite.get(), F_SETFD, SetupFlags | FD_CLOEXEC) == -1) {
      Reply(error("failed to configure formatter setup pipe: {0}",
                  std::error_code(errno, std::generic_category()).message()));
      return;
    }

    pid_t Child;
    try {
      Child = forkPiped(In, Out, Err);
    } catch (const std::system_error &Error) {
      Reply(error("failed to launch formatter: {0}", Error.what()));
      return;
    }
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
        SetupResult == -1
            ? std::error_code(errno, std::generic_category())
            : std::error_code();
    closeFD(SetupRead);

    // Firstly, send the document to the process stdin.
    // Invoke POSIX write(2) to do such thing.
    std::error_code WriteError;
    if (SetupResult == 0) {
      const char *Start = Code.c_str();
      const char *End = Code.c_str() + Code.size();
      while (Start != End) {
        const ssize_t Written =
            writeWithoutSigpipe(Input.get(), Start, End - Start);
        if (Written > 0) {
          Start += Written;
          continue;
        }
        WriteError = std::error_code(Written == 0 ? EIO : errno,
                                     std::generic_category());
        break;
      }
    }
    closeFD(Input);

    // And, wait for the process.
    int Exit = 0;
    std::error_code WaitError;
    if (!waitForChild(Child, Exit, WaitError)) {
      Reply(error("failed to wait for formatter: {0}", WaitError.message()));
      return;
    }

    if (WIFSIGNALED(Exit) &&
        WTERMSIG(Exit) == FormatterChdirFailureSignal) {
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

    if (WriteError) {
      Reply(error("failed to write formatter input: {0}",
                  WriteError.message()));
      return;
    }

    if (Exit != 0) {
      Reply(error("formatting {0} command exited with {1}", FormatCommand[0],
                  Exit));
      return;
    }

    // Okay, read stdout from it.
    std::string Response;
    while (true) {
      char Buf[1024];
      auto Read = read(Output.get(), Buf, sizeof(Buf));
      if (Read == 0)
        break;
      if (Read < 0) {
        if (errno == EINTR)
          continue;
        Reply(error("failed to read formatter output: {0}",
                    std::error_code(errno, std::generic_category()).message()));
        return;
      }
      // Otherwise, append it to "response"
      Response.append(Buf, Read);
    }

    if (Response == Code) {
      Reply(std::vector<TextEdit>{});
      return;
    }

    TextEdit E{{{0, 0}, {INT_MAX, INT_MAX}}, Response};
    Reply(std::vector{E});
  };

  boost::asio::post(Pool, std::move(Action));
}
