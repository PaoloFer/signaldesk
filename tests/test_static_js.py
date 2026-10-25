"""H4: controllo statico di sintassi dei file JavaScript.

Esegue ``node --check`` su ogni ``static/*.js`` quando Node è disponibile;
in ambienti senza Node (es. CI minimale) il test viene saltato invece di
fallire, perché il gate definitivo resta la CI.
"""

from __future__ import annotations

import shutil
import subprocess
import unittest
from pathlib import Path


STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


@unittest.skipUnless(shutil.which("node"), "Node.js non disponibile")
class StaticJavaScriptTest(unittest.TestCase):
    def test_js_files_have_valid_syntax(self):
        files = sorted(STATIC_DIR.glob("*.js"))
        self.assertTrue(files, "Nessun file JS trovato in static/")
        for path in files:
            result = subprocess.run(
                ["node", "--check", str(path)],
                capture_output=True, text=True, timeout=60,
            )
            self.assertEqual(
                result.returncode, 0,
                msg=f"{path.name}: {result.stderr.strip()}",
            )


if __name__ == "__main__":
    unittest.main()
