# Project license and third-party notices

Copyright (C) 2026 zinverno and Yanjaro contributors.

The owner selected **GPL-3.0-or-later** on 2026-10-07 for the Yanjaro application code and original application mark.
Yanjaro is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.
It is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See [LICENSE](LICENSE) for the full terms.

The private GitHub upload is authorized; making the repository public, issuing a Release, and submitting to AUR remain separate owner-approved actions.

Third-party components retain their own licenses:

- Adwaita SVG symbols: GNOME Project, https://www.gnome.org/, LGPL-3.0-only OR CC-BY-SA-3.0. Original SVG source, attribution, origin hashes and both texts are included under `yanjaro/icons/`. No paths changed; filenames shortened.
- yandex-music 3.2.0: LGPL-3.0-only. The native package includes the unmodified official pure-Python wheel privately under `/usr/lib/yanjaro`, including its license and metadata. The SDK is imported as a separate module; its Python source can be inspected and replaced. Source and package origin: https://pypi.org/project/yandex-music/3.2.0/ and https://github.com/MarshalX/yandex-music-api .
- PySide6 / Qt, python-mpv and libmpv are external system dependencies of the native package, not bundled binaries. Their system packages supply their licenses. PySide6/Qt used here offer LGPL terms; python-mpv offers GPL or LGPL terms; the locally available Manjaro mpv package declares GPL-2.0-or-later AND LGPL-2.1-or-later. Check the actual target dependency builds before public distribution; no claim of license clearance for every possible build is made.

No developer `.venv`, `.runtime`, authentication data, personal library, logs or private configuration is distributed in the native package.
