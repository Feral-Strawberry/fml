"""Gemeinsame Testeinstellungen.

Die Test-Aufgaben ``_sleep``/``_boom``/``_die`` (``feral.web.tasks``) werden
nur registriert, wenn diese Variable gesetzt ist (#251). Sie muss stehen,
bevor ``feral.web.tasks`` importiert wird; der Worker-Prozess (spawn) erbt
sie aus der Umgebung.
"""

import os

os.environ["FML_TEST_TASKS"] = "1"
