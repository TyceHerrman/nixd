#include "nixd/Support/ForkPiped.h"
#include "nixd/Support/AutoCloseFD.h"

#include <cerrno>

#include <system_error>
#include <unistd.h>

int nixd::forkPiped(int &In, int &Out, int &Err) {
  static constexpr int READ = 0;
  static constexpr int WRITE = 1;
  int PipeIn[2];
  int PipeOut[2];
  int PipeErr[2];
  if (pipe(PipeIn) == -1)
    throw std::system_error(errno, std::generic_category());
  util::AutoCloseFD PipeInRead(PipeIn[READ]);
  util::AutoCloseFD PipeInWrite(PipeIn[WRITE]);

  if (pipe(PipeOut) == -1)
    throw std::system_error(errno, std::generic_category());
  util::AutoCloseFD PipeOutRead(PipeOut[READ]);
  util::AutoCloseFD PipeOutWrite(PipeOut[WRITE]);

  if (pipe(PipeErr) == -1)
    throw std::system_error(errno, std::generic_category());
  util::AutoCloseFD PipeErrRead(PipeErr[READ]);
  util::AutoCloseFD PipeErrWrite(PipeErr[WRITE]);

  pid_t Child = fork();

  if (Child == 0) {
    // Redirect stdin, stdout, stderr.
    if (dup2(PipeIn[READ], STDIN_FILENO) == -1 ||
        dup2(PipeOut[WRITE], STDOUT_FILENO) == -1 ||
        dup2(PipeErr[WRITE], STDERR_FILENO) == -1)
      _exit(127);
    // Child process.
    return 0;
  }

  if (Child == -1)
    throw std::system_error(errno, std::generic_category());

  In = PipeIn[WRITE];
  PipeInWrite.release();
  Out = PipeOut[READ];
  PipeOutRead.release();
  Err = PipeErr[READ];
  PipeErrRead.release();
  return Child;
}
