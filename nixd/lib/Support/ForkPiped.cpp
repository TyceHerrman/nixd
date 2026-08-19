#include "nixd/Support/ForkPiped.h"
#include "nixd/Support/AutoCloseFD.h"

#include <cerrno>

#include <fcntl.h>
#include <mutex>
#include <optional>
#include <system_error>
#include <unistd.h>

namespace {
std::mutex &launchMutex() {
  static std::mutex *Mutex = new std::mutex;
  return *Mutex;
}

void setCloseOnExec(int FD) {
  int Flags;
  do {
    Flags = fcntl(FD, F_GETFD);
  } while (Flags == -1 && errno == EINTR);
  if (Flags == -1)
    throw std::system_error(errno, std::generic_category());

  int Result;
  do {
    Result = fcntl(FD, F_SETFD, Flags | FD_CLOEXEC);
  } while (Result == -1 && errno == EINTR);
  if (Result == -1)
    throw std::system_error(errno, std::generic_category());
}

void moveAboveStdio(int &FD) {
  if (FD > STDERR_FILENO)
    return;

  int Duplicate;
  do {
    Duplicate = fcntl(FD, F_DUPFD, STDERR_FILENO + 1);
  } while (Duplicate == -1 && errno == EINTR);
  if (Duplicate == -1)
    throw std::system_error(errno, std::generic_category());
  try {
    setCloseOnExec(Duplicate);
  } catch (...) {
    close(Duplicate);
    throw;
  }
  close(FD);
  FD = Duplicate;
}

void makePipe(int (&Pipe)[2], nixd::ForkPipedExtraPipe *Extra = nullptr) {
  if (Extra)
    Extra->Failure = nixd::ForkPipedExtraPipeFailure::Create;

  int Result;
  do {
    Result = pipe(Pipe);
  } while (Result == -1 && errno == EINTR);
  if (Result == -1)
    throw std::system_error(errno, std::generic_category());

  if (Extra)
    Extra->Failure = nixd::ForkPipedExtraPipeFailure::Configure;
  try {
    moveAboveStdio(Pipe[0]);
    moveAboveStdio(Pipe[1]);
    setCloseOnExec(Pipe[0]);
    setCloseOnExec(Pipe[1]);
  } catch (...) {
    close(Pipe[0]);
    close(Pipe[1]);
    throw;
  }
  if (Extra)
    Extra->Failure = nixd::ForkPipedExtraPipeFailure::None;
}

bool redirect(int Source, int Target) {
  if (Source != Target) {
    int Result;
    do {
      Result = dup2(Source, Target);
    } while (Result == -1 && errno == EINTR);
    return Result != -1;
  }

  int Flags;
  do {
    Flags = fcntl(Target, F_GETFD);
  } while (Flags == -1 && errno == EINTR);
  if (Flags == -1)
    return false;

  int Result;
  do {
    Result = fcntl(Target, F_SETFD, Flags & ~FD_CLOEXEC);
  } while (Result == -1 && errno == EINTR);
  return Result != -1;
}
} // namespace

int nixd::forkPiped(int &In, int &Out, int &Err, ForkPipedExtraPipe *Extra) {
  static constexpr int READ = 0;
  static constexpr int WRITE = 1;
  int PipeIn[2];
  int PipeOut[2];
  int PipeErr[2];
  int ExtraPipe[2];

  std::unique_lock LaunchGuard(launchMutex());

  makePipe(PipeIn);
  util::AutoCloseFD PipeInRead(PipeIn[READ]);
  util::AutoCloseFD PipeInWrite(PipeIn[WRITE]);

  makePipe(PipeOut);
  util::AutoCloseFD PipeOutRead(PipeOut[READ]);
  util::AutoCloseFD PipeOutWrite(PipeOut[WRITE]);

  makePipe(PipeErr);
  util::AutoCloseFD PipeErrRead(PipeErr[READ]);
  util::AutoCloseFD PipeErrWrite(PipeErr[WRITE]);

  std::optional<util::AutoCloseFD> ExtraRead;
  std::optional<util::AutoCloseFD> ExtraWrite;
  if (Extra) {
    makePipe(ExtraPipe, Extra);
    ExtraRead.emplace(ExtraPipe[READ]);
    ExtraWrite.emplace(ExtraPipe[WRITE]);
  }

  pid_t Child = fork();

  if (Child == 0) {
    // The copied mutex remains locked until exec/exit. Do not let a C++ guard
    // attempt to unlock the parent's synchronization object in the child.
    LaunchGuard.release();

    // Redirect stdin, stdout, stderr.
    if (!redirect(PipeIn[READ], STDIN_FILENO) ||
        !redirect(PipeOut[WRITE], STDOUT_FILENO) ||
        !redirect(PipeErr[WRITE], STDERR_FILENO))
      _exit(127);

    if (PipeIn[READ] == STDIN_FILENO)
      PipeInRead.release();
    if (PipeOut[WRITE] == STDOUT_FILENO)
      PipeOutWrite.release();
    if (PipeErr[WRITE] == STDERR_FILENO)
      PipeErrWrite.release();

    if (Extra) {
      Extra->Read = ExtraPipe[READ];
      Extra->Write = ExtraPipe[WRITE];
      ExtraRead->release();
      ExtraWrite->release();
    }
    // Child process.
    return 0;
  }

  LaunchGuard.unlock();

  if (Child == -1)
    throw std::system_error(errno, std::generic_category());

  In = PipeIn[WRITE];
  PipeInWrite.release();
  Out = PipeOut[READ];
  PipeOutRead.release();
  Err = PipeErr[READ];
  PipeErrRead.release();
  if (Extra) {
    Extra->Read = ExtraPipe[READ];
    Extra->Write = ExtraPipe[WRITE];
    ExtraRead->release();
    ExtraWrite->release();
  }
  return Child;
}
