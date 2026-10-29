/* Enter the delegated accounting domains before allocating a Python heap.
 * This executable never receives setuid bits or file capabilities. */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>

int main(int argc, char **argv)
{
    if (argc < 4) return 120;
    char *end;
    errno = 0;
    long count = strtol(argv[1], &end, 10);
    if (errno || *end || end == argv[1] || count < 1 || count > 4 ||
        argc < 3 + count || argv[2 + count][0] != '/') return 121;
    char pid[32];
    int length = snprintf(pid, sizeof(pid), "%ld", (long)getpid());
    if (length < 1 || length >= (int)sizeof(pid)) return 121;
    for (long i = 0; i < count; i++) {
        if (argv[2 + i][0] != '/') return 121;
        int fd = open(argv[2 + i], O_WRONLY | O_CLOEXEC | O_NOFOLLOW);
        if (fd < 0) return 122;
        ssize_t written = write(fd, pid, (size_t)length);
        int closed = close(fd);
        if (written != length || closed) return 122;
    }
    execv(argv[2 + count], argv + 2 + count);
    return 123;
}
