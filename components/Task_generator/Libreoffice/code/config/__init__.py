import os

_PROGRAM = os.environ.get("LIBREOFFICE_TASKGEN_PROGRAM", "write").lower()

if _PROGRAM in {"calc", "libreoffice_calc"}:
    from .config_calc import *  # noqa: F401,F403
elif _PROGRAM in {"impress", "libreoffice_impress"}:
    from .config_impress import *  # noqa: F401,F403
elif _PROGRAM in {"write", "writer", "libreoffice_writer"}:
    from .config_write import *  # noqa: F401,F403
else:
    raise ValueError(
        "Unsupported LIBREOFFICE_TASKGEN_PROGRAM. "
        "Use one of: calc, impress, writer."
    )
