# Interis

Lokales, offline laufendes Werkzeug zum Verwalten, Transkribieren und Vergleichen der
Interviews für die Masterarbeit (Deutsch, Interviewer + eine befragte Person).

- [PLAN.md](PLAN.md): Ziele, Features, Phasen
- [ARCHITECTURE.md](ARCHITECTURE.md): Architektur, Datenmodell, API, Sicherheitskonzept
- [DEPENDENCIES.md](DEPENDENCIES.md): Abhängigkeiten, bekannte CVEs, Schutz vor Datenabfluss

**Wichtig:** Interviewdaten (Audio, Datenbank, Exporte, Modelle) gehören **nie** in dieses
Repository. Sie liegen ausschließlich im verschlüsselten Datenverzeichnis (siehe
ARCHITECTURE.md §6). Die `.gitignore` blockiert die üblichen Dateitypen zusätzlich.

Status: Planung abgeschlossen, Implementierung noch nicht begonnen.
