/* Bundle executable for Mouthpiece.app.

macOS ties Camera, Accessibility and Input Monitoring to the code signature of
the process that is actually running. A shell script that execs Python asks for
those permissions as "Mouthpiece" and then keeps running as Python, so the
grant never satisfies the in-app check and setup cannot continue.

This binary stays in memory, embeds libpython, and runs `python -m mouthpiece`
with the original arguments (`Mouthpiece doctor` works from a terminal). The
process signature and the app the user approves are the same thing.

Two builds (scripts/make_app.py):
  release: Python lives in Contents/Resources/python, found relative to this
           executable. Nothing outside the bundle is used.
  dev:     -DMOUTHPIECE_ROOT/-DMOUTHPIECE_VENV_PYTHON point at a checkout and its .venv.
*/
#include <Python.h>
#include <fcntl.h>
#include <libgen.h>
#include <limits.h>
#include <mach-o/dyld.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

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

static int check(PyStatus s, PyConfig *c) {
    if (!PyStatus_Exception(s)) return 0;
    if (c) PyConfig_Clear(c);
    Py_ExitStatusException(s);
    return 1;
}

int main(int argc, char **argv) {
    /* A first launch (Gatekeeper/LaunchServices) can still pass -psn_0_NNN; drop it so it isn't
       read as a subcommand and the GUI run still logs to the file. */
    int n = 1;
    for (int i = 1; i < argc; i++)
        if (strncmp(argv[i], "-psn_", 5) != 0) argv[n++] = argv[i];
    argc = n;
    argv[argc] = NULL;
    /* Finder/open launch the GUI with no arguments; its output goes to the log.
       A subcommand (`Mouthpiece doctor`) is a terminal run: keep stdout. */
    if (argc < 2) redirect_log();
    fprintf(stderr, "[mouthpiece] native launcher\n");
    setenv("MOUTHPIECE_APP", "1", 1);

#ifdef MOUTHPIECE_VENV_PYTHON
    if (chdir(MOUTHPIECE_ROOT) != 0) { perror("chdir"); return 1; }
#else
    char home[PATH_MAX];
    char exe[PATH_MAX], real[PATH_MAX];
    uint32_t size = sizeof exe;
    if (_NSGetExecutablePath(exe, &size) != 0 || !realpath(exe, real)) return 1;
    snprintf(home, sizeof home, "%s/../Resources/python", dirname(real));
    if (!realpath(home, exe)) { perror(home); return 1; }
    snprintf(home, sizeof home, "%s", exe);
#endif

    /* Isolated: ignore the user's PYTHON* variables and user site-packages, and never
       write .pyc files into the signed bundle. */
    PyPreConfig pre;
    PyPreConfig_InitIsolatedConfig(&pre);
    pre.utf8_mode = 1; /* Finder gives us no LANG */
    if (check(Py_PreInitialize(&pre), NULL)) return 1;

    PyConfig c;
    PyConfig_InitIsolatedConfig(&c);
    c.buffered_stdio = 0;
    c.write_bytecode = 0;
#ifdef MOUTHPIECE_VENV_PYTHON
    /* Dev: present as the venv's python so getpath finds pyvenv.cfg and its site-packages;
       sys.path[0] is the checkout (the cwd), so edits take effect on the next launch. */
    if (check(PyConfig_SetBytesString(&c, &c.executable, MOUTHPIECE_VENV_PYTHON), &c)) return 1;
    c.safe_path = 0;
#else
    if (check(PyConfig_SetBytesString(&c, &c.home, home), &c)) return 1;
#endif
    if (check(PyConfig_SetBytesString(&c, &c.run_module, "mouthpiece"), &c)) return 1;
    if (check(PyConfig_SetBytesArgv(&c, argc, argv), &c)) return 1;
    if (check(Py_InitializeFromConfig(&c), &c)) return 1;
    PyConfig_Clear(&c);
    return Py_RunMain();
}
