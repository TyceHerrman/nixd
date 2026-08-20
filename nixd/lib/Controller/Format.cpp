/// \file
/// \brief Implementation of [Formatting].
/// [Formatting]:
/// https://microsoft.github.io/language-server-protocol/specifications/lsp/3.17/specification/#textDocument_formatting

#include "nixd/Controller/Controller.h"
#include "nixd/Support/ForkPiped.h"
#include "nixd/Support/PipedProc.h"

#include <boost/asio/post.hpp>

#include <cerrno>
#include <chrono>
#include <csignal>
#include <cstring>
#include <fcntl.h>
#include <sys/wait.h>
#include <system_error>
#include <thread>
#include <unistd.h>

using namespace nixd;
using namespace nixd::util;
using namespace lspserver;

namespace {

void readPipe(int FD, std::string &Output, std::string &IOError) {
  if (AutoCloseFD::isReleased(FD))
    return;
  char Buffer[8192];
  while (true) {
    const ssize_t Count = read(FD, Buffer, sizeof(Buffer));
    if (Count > 0) {
      Output.append(Buffer, static_cast<std::size_t>(Count));
      continue;
    }
    if (Count == 0)
      return;
    if (errno == EINTR)
      continue;
    IOError = std::strerror(errno);
    return;
  }
}

void writePipe(AutoCloseFD FD, llvm::StringRef Input, std::string &IOError) {
  sigset_t Signals;
  sigemptyset(&Signals);
  sigaddset(&Signals, SIGPIPE);
  pthread_sigmask(SIG_BLOCK, &Signals, nullptr);

  const char *Current = Input.begin();
  const char *End = Input.end();
  while (Current != End) {
    const ssize_t Count = write(FD.get(), Current, End - Current);
    if (Count > 0) {
      Current += Count;
      continue;
    }
    if (Count < 0 && errno == EINTR)
      continue;
    IOError = std::strerror(Count == 0 ? EIO : errno);
    break;
  }
}

void setCloseOnExec(int FD) {
  int Flags;
  do {
    Flags = fcntl(FD, F_GETFD);
  } while (Flags == -1 && errno == EINTR);
  if (Flags == -1)
    throw std::system_error(errno, std::generic_category());
  while (fcntl(FD, F_SETFD, Flags | FD_CLOEXEC) == -1) {
    if (errno != EINTR)
      throw std::system_error(errno, std::generic_category());
  }
}

class ChildReaper {
  pid_t PID;
  bool Armed = true;

public:
  explicit ChildReaper(pid_t PID) : PID(PID) {}
  ChildReaper(const ChildReaper &) = delete;

  ~ChildReaper() {
    if (!Armed)
      return;
    kill(PID, SIGKILL);
    int Status;
    while (waitpid(PID, &Status, 0) == -1 && errno == EINTR) {
    }
  }

  void disarm() { Armed = false; }
};

} // namespace

void Controller::terminateFormatter(const FormatterChild &Child, int Signal) {
  std::lock_guard Guard(Child->Lock);
  if (Child->Reaped || Child->PID <= 0)
    return;
  if (kill(Child->PID, Signal) == -1 && errno != ESRCH)
    elog("failed to terminate formatter process {0}: {1}", Child->PID,
         std::strerror(errno));
}

int Controller::waitForFormatter(const FormatterChild &Child, int &WaitErrno) {
  while (true) {
    {
      std::lock_guard Guard(Child->Lock);
      if (Child->Reaped) {
        WaitErrno = ECHILD;
        return -1;
      }
      int Status = 0;
      const pid_t Result = waitpid(Child->PID, &Status, WNOHANG);
      if (Result == Child->PID) {
        Child->Reaped = true;
        Child->PID = -1;
        return Status;
      }
      if (Result == -1 && errno != EINTR) {
        WaitErrno = errno;
        Child->Reaped = true;
        Child->PID = -1;
        return -1;
      }
    }
    std::this_thread::sleep_for(std::chrono::milliseconds(1));
  }
}

void Controller::shutdownFormatters() {
  std::vector<FormatterChild> Children;
  {
    std::lock_guard ForkGuard(ChildForkLock);
    std::lock_guard FormatterGuard(FormatterLock);
    FormatterShutdown = true;
    Children.assign(ActiveFormatters.begin(), ActiveFormatters.end());
  }
  for (const FormatterChild &Child : Children)
    terminateFormatter(Child, SIGKILL);
}

void Controller::onFormat(const DocumentFormattingParams &Params,
                          Callback<std::vector<TextEdit>> Reply) {
  std::vector<std::string> FormatCommand;
  {
    std::lock_guard Guard(ConfigLock);
    FormatCommand = Config.formatting.command;
  }
  if (FormatCommand.empty())
    return Reply(std::vector<TextEdit>{});

  std::filesystem::path ChildDirectory = Root.path;
  {
    std::lock_guard Guard(FormatterLock);
    if (FormatterShutdown)
      return Reply(error("formatting is unavailable during shutdown"));
  }

  auto Action = [this, Params, FormatCommand = std::move(FormatCommand),
                 ChildDirectory = std::move(ChildDirectory),
                 Reply = std::move(Reply)]() mutable {
    const std::string CommandName = FormatCommand.front();
    try {
      lspserver::PathRef File = Params.textDocument.uri.file();
      const std::string Code = *Store.getDraft(File)->Contents;

      std::vector<char *> Syscall;
      Syscall.reserve(FormatCommand.size() + 1);
      for (auto &Argument : FormatCommand)
        Syscall.emplace_back(Argument.data());
      Syscall.emplace_back(nullptr);

      int In;
      int Out;
      int Err;
      std::unique_lock ForkGuard(ChildForkLock);
      bool RejectForShutdown;
      {
        std::lock_guard Guard(FormatterLock);
        RejectForShutdown = FormatterShutdown;
      }
      if (RejectForShutdown) {
        ForkGuard.unlock();
        return Reply(error("formatting is unavailable during shutdown"));
      }
      int ErrorPipe[2];
      if (pipe(ErrorPipe) == -1)
        throw std::system_error(errno, std::generic_category());
      AutoCloseFD ErrorRead(ErrorPipe[0]);
      AutoCloseFD ErrorWrite(ErrorPipe[1]);
      setCloseOnExec(ErrorRead.get());
      setCloseOnExec(ErrorWrite.get());
      const pid_t Child = forkPiped(In, Out, Err);
      if (Child == 0) {
        close(ErrorRead.get());
        if (dup2(ErrorWrite.get(), STDERR_FILENO) == -1)
          _exit(126);
        close(ErrorWrite.get());
        if (chdir(ChildDirectory.c_str()) != 0) {
          perror("failed to change formatter working directory");
          _exit(126);
        }
        execvp(Syscall[0], Syscall.data());
        perror("failed to launch formatter");
        _exit(127);
      }
      ChildReaper Reaper(Child);
      AutoCloseFD ParentIn(In);
      AutoCloseFD ParentOut(Out);

      close(ErrorWrite.get());
      ErrorWrite.release();
      // The existing helper aliases Err to Out. If that is corrected, close
      // its unused stderr descriptor; this formatter uses ErrorRead instead.
      if (Err != Out)
        close(Err);
      setCloseOnExec(ParentIn.get());
      setCloseOnExec(ParentOut.get());
      setCloseOnExec(ErrorRead.get());
      PipedProc Process{Child, std::move(ParentIn), std::move(ParentOut),
                        std::move(ErrorRead)};

      auto ChildState = std::make_shared<FormatterChildState>();
      ChildState->PID = Child;
      bool Registered = false;
      {
        std::lock_guard Guard(FormatterLock);
        assert(!FormatterShutdown);
        ActiveFormatters.insert(ChildState);
        Registered = true;
      }
      ForkGuard.unlock();

      std::string Response;
      std::string Stderr;
      std::string WriteError;
      std::string ReadError;
      std::string StderrError;
      std::thread Writer;
      std::thread Reader;
      std::thread ErrorReader;
      try {
        auto Write = [Stdin = std::move(Process.Stdin),
                      Input = llvm::StringRef(Code), &WriteError]() mutable {
          writePipe(std::move(Stdin), Input, WriteError);
        };
        Writer = std::thread(std::move(Write));
        Reader = std::thread(readPipe, Process.Stdout.get(), std::ref(Response),
                             std::ref(ReadError));
        ErrorReader = std::thread(readPipe, Process.Stderr.get(),
                                  std::ref(Stderr), std::ref(StderrError));
      } catch (...) {
        terminateFormatter(ChildState, SIGKILL);
        if (Writer.joinable())
          Writer.join();
        if (Reader.joinable())
          Reader.join();
        if (ErrorReader.joinable())
          ErrorReader.join();
        int Ignored = 0;
        waitForFormatter(ChildState, Ignored);
        if (Registered) {
          std::lock_guard Guard(FormatterLock);
          ActiveFormatters.erase(ChildState);
        }
        Reaper.disarm();
        throw;
      }

      int WaitErrno = 0;
      const int Status = waitForFormatter(ChildState, WaitErrno);
      if (Registered) {
        std::lock_guard Guard(FormatterLock);
        ActiveFormatters.erase(ChildState);
      }
      Reaper.disarm();
      Writer.join();
      Reader.join();
      ErrorReader.join();

      if (WaitErrno != 0)
        return Reply(error("formatting {0} wait failed: {1}", CommandName,
                           std::strerror(WaitErrno)));
      if (!WriteError.empty() || !ReadError.empty() || !StderrError.empty()) {
        const std::string &Message = !WriteError.empty()  ? WriteError
                                     : !ReadError.empty() ? ReadError
                                                          : StderrError;
        return Reply(
            error("formatting {0} I/O failed: {1}", CommandName, Message));
      }
      if (WIFEXITED(Status) && WEXITSTATUS(Status) != 0)
        return Reply(error("formatting {0} command exited with {1}",
                           CommandName, WEXITSTATUS(Status)));
      if (WIFSIGNALED(Status))
        return Reply(error("formatting {0} command terminated by signal {1}",
                           CommandName, WTERMSIG(Status)));
      if (!WIFEXITED(Status))
        return Reply(
            error("formatting {0} command ended unexpectedly", CommandName));

      if (Response == Code)
        return Reply(std::vector<TextEdit>{});
      TextEdit Edit{{{0, 0}, {INT_MAX, INT_MAX}}, std::move(Response)};
      Reply(std::vector{std::move(Edit)});
    } catch (const std::exception &Exception) {
      Reply(error("formatting {0} failed: {1}", CommandName, Exception.what()));
    }
  };

  boost::asio::post(Pool, std::move(Action));
}
