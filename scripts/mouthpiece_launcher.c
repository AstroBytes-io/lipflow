/* Bundle executable for Mouthpiece.app.

macOS ties Accessibility and Input Monitoring to the code signature of the
process that is actually running. A shell script that execs the venv Python
asks for those permissions as "Mouthpiece" and then keeps running as Python, so
the grant never satisfies the in-app check and setup cannot continue.

This binary stays in memory, loads the venv's libpython, and runs
`python -m mouthpiece`. The process signature and the app the user approves
are the same thing.
*/
#include <Python.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#ifndef MOUTHPIECE_ROOT
#error "compile with -DMOUTHPIECE_ROOT=\\\"/path/to/mouthpiece\\\""
#endif
#ifndef MOUTHPIECE_PYHOME
#error "compile with -DMOUTHPIECE_PYHOME=\\\"/path/to/python/prefix\\\""
#endif
#ifndef MOUTHPIECE_SITE
#error "compile with -DMOUTHPIECE_SITE=\\\"/path/to/site-packages\\\""
#endif

static void redirect_log(void) {
    const char *home = getenv("HOME");
    if (!home) return;
    char path[4096];
    snprintf(path, sizeof path, "%s/Library/Logs/Mouthpiece.log", home);
    int fd = open(path, O_WRONLY | O_CREAT | O_APPEND, 0644);
    if (fd < 0) return;
    dup2(fd, STDOUT_FILENO);
    dup2(fd, STDERR_FILENO);
    if (fd > STDERR_FILENO) close(fd);
}

int main(int argc, char **argv) {
    redirect_log();
    fprintf(stderr, "[mouthpiece] native launcher\n");

    char pythonpath[8192];
    snprintf(pythonpath, sizeof pythonpath, "%s:%s", MOUTHPIECE_SITE, MOUTHPIECE_ROOT);

    setenv("MOUTHPIECE_APP", "1", 1);
    setenv("PYTHONUNBUFFERED", "1", 1);
    setenv("PYTHONNOUSERSITE", "1", 1);
    setenv("PYTHONHOME", MOUTHPIECE_PYHOME, 1);
    setenv("PYTHONPATH", pythonpath, 1);
    if (chdir(MOUTHPIECE_ROOT) != 0) {
        perror("chdir");
        return 1;
    }

    int n = argc + 2; /* program, -m, mouthpiece, then the original args except argv0 */
    wchar_t **wargv = calloc((size_t)n + 1, sizeof(wchar_t *));
    if (!wargv) return 1;
    wargv[0] = Py_DecodeLocale("mouthpiece", NULL);
    wargv[1] = Py_DecodeLocale("-m", NULL);
    wargv[2] = Py_DecodeLocale("mouthpiece", NULL);
    for (int i = 1; i < argc; i++) {
        wargv[i + 2] = Py_DecodeLocale(argv[i], NULL);
        if (!wargv[i + 2]) return 1;
    }
    if (!wargv[0] || !wargv[1] || !wargv[2]) return 1;
    return Py_Main(n, wargv);
}
