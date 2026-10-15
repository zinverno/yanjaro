"""Process-local bounds, set before importing numerical libraries."""
import os
import resource
import sys


def configure():
    os.umask(0o077)
    sys.dont_write_bytecode = True
    for name in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS",
                 "NUMEXPR_NUM_THREADS", "NUMBA_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
        os.environ[name] = "1"
    os.environ["NUMBA_DISABLE_JIT"] = "0"
    os.environ["CUDA_VISIBLE_DEVICES"] = ""
    os.sched_setaffinity(0, sorted(os.sched_getaffinity(0))[:2])
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    ceiling = 1024**3
    soft, hard = resource.getrlimit(resource.RLIMIT_AS)
    ceiling = min(ceiling, hard) if hard != resource.RLIM_INFINITY else ceiling
    resource.setrlimit(resource.RLIMIT_AS, (min(soft, ceiling) if soft > 0 else ceiling, ceiling))
