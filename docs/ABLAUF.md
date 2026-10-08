# Ablauf: vom Gespräch zur Auswertungstabelle

Dieses Dokument beschreibt, was du in Interis in welcher Reihenfolge tust. Die Seite
**Ablauf** eines Projekts zeigt dieselben acht Schritte und den Stand jedes Gesprächs.
Die Regeln für „erledigt“ stehen auf dem Server (`src/interis/web/workflow.py`,
Funktion `interview_row`). Die Seite zeigt nur an, was der Server berechnet.

## Überblick

| # | Schritt | Erledigt, wenn (Seite Ablauf) |
|---|---|---|
| 1 | Leitfaden festlegen | keine Haken-Regel; die Anzahl der Fragen wird angezeigt |
| 2 | Transkribieren | das Gespräch ist transkribiert |
| 3 | Korrigieren | „Korrektur abgeschlossen“ ist gesetzt |
| 4 | Glätten (optional) | mindestens eine Glättung vorhanden; blockiert nichts |
| 5 | Fragen zuordnen | keine Haken-Regel; Zahlen werden angezeigt |
| 6 | Fehlende Fragen klären | keine Leitfadenfrage ist mehr offen |
| 7 | Extrahieren | mindestens ein Extrakt im Gespräch |
| 8 | Exportieren | kein gespeicherter Zustand |

## Die Seite Ablauf lesen

- **Eine Zeile je Gespräch**, eine Spalte je Schritt mit Haken (erledigt) oder Strich (offen).
- **Geglättet (optional)** zeigt einen Strich, wenn keine Glättung vorhanden ist. Das ist
  kein Mangel.
- **Fragen zugeordnet** zeigt keine Haken, sondern die Zahl der gestellten Leitfadenfragen
  („gestellt“) und die Zahl der Fragen ohne Leitfaden-Zuordnung („spontan“).
- **Fehlende geklärt** zeigt „–“, solange das Gespräch nicht transkribiert ist.
- **Analyse veraltet** erscheint, wenn Korrekturen oder Glättungen nach der letzten Analyse
  gespeichert wurden (siehe Schritt 4).
- **offen: F3, F5** nennt die Leitfadenfragen, die in diesem Gespräch noch ohne Antwort und
  ohne Begründung sind.
- Die Links führen zum **Transkript** des Gesprächs und zur Ansicht **Nebeneinander**.

---

## 1. Leitfaden festlegen

**Was tun:** Unter „Leitfaden & Gespräche“ im Reiter „Leitfaden“ den Leitfaden eingeben
oder als Datei laden (.docx, .md, .txt). Jede Frage bekommt einen Code (F1, F2 …). Eine Frage
ohne Code bekommt den nächsten Code über dem höchsten vorhandenen; beim Speichern schreibt
Interis diesen Code in den Leitfaden, er ändert sich danach nicht mehr. Bei einer
.docx-Datei gelten nur Zeilen mit „- “ als Fragen; die Oberfläche bittet dann um eine Prüfung.

Wird ein Leitfaden gespeichert, werden alle Gespräche des Projekts neu analysiert. Sie
werden **nicht** neu transkribiert.

**Warum:** Die Codes sind die gemeinsamen Zeilen, über die alle Gespräche verglichen werden.

**Erledigt:** Keine eigene Regel. Ohne Leitfaden zeigt die Seite Ablauf den Hinweis „Noch
kein Leitfaden“.

## 2. Transkribieren

**Was tun:** Unter „Leitfaden & Gespräche“ im Reiter „Gespräche“ die Aufnahme hinzufügen
und „Transkription starten“ wählen. Die Transkription läuft im Hintergrund. Das Ergebnis
bleibt unverändert; alle Änderungen werden separat gespeichert.

**Warum:** Das maschinelle Transkript ist die Grundlage. Es wird nie überschrieben, alle
weiteren Schritte legen sich als Änderungen darüber.

**Erledigt:** Das Gespräch ist transkribiert.

**Achtung:** „Neu transkribieren“ löscht alle Markierungen dieses Gesprächs: Fragenzuordnungen,
Verknüpfungen, Korrekturen, Glättungen, Begründungen, Extrakte und das Häkchen „Korrektur
abgeschlossen“. Dafür fragt Interis nach, und die Bestätigung nennt genau diese Arten. Gelöscht
wird erst, wenn die neue Transkription fertig ist. Bricht man den Auftrag ab oder schlägt er
fehl, bleiben die Markierungen erhalten. Solange eine Transkription wartet oder läuft, lassen
sich keine Markierungen setzen oder ändern; Interis lehnt das ab.

## 3. Korrigieren

**Was tun:** Im Transkript den Modus **„Korrigieren“** wählen.

- Ein Wort anklicken, den richtigen Text eingeben und speichern.
- Oder einen Abschnitt markieren und **„Ersetzen …“** wählen.
- **„Änderung zurücknehmen“** im Dialog hebt eine Änderung wieder auf.
- Die Checkbox **„Änderungen anzeigen“** unterstreicht korrigierte Wörter. Darüberfahren
  zeigt den Originaltext.

Eine Ersetzung über mehrere Wörter schreibt den neuen Text in das erste Wort. Die übrigen
Wörter des Abschnitts werden gelöscht; ihre Zeitangaben bleiben erhalten. Ein Ersatztext
darf höchstens 200 Zeichen lang sein.

Ein Wort trägt nur eine Art Änderung. Wer ein korrigiertes Wort glätten will, nimmt zuerst die
Korrektur zurück; sonst meldet Interis „Diese Stelle hat schon eine andere Änderung“.

Korrekturen machen die Analyse veraltet, wie Glättungen. Danach „Analyse aktualisieren“ wählen,
damit die Fragenerkennung den korrigierten Text nutzt.

Wenn alle Fehler korrigiert sind, die Checkbox **„Korrektur abgeschlossen“** ankreuzen.

**Warum:** Falsch erkannte Wörter müssen stimmen, bevor geglättet, analysiert und zitiert wird.

**Erledigt:** „Korrektur abgeschlossen“ ist gesetzt. Das Häkchen prüft den Text nicht. Es ist
deine Angabe, dass du das Transkript durchgesehen hast.

## 4. Glätten (optional)

**Was tun:** Im Transkript den Modus **„Glätten“** wählen. Einen Abschnitt markieren und
**„Entfernen“** oder **„Ersetzen …“** wählen. Ein **Grund** ist Pflicht. Die Gründe kommen
aus den Glättungs-Tags des Projekts. Standard sind: Füllwort, Wortwiederholung, Satzabbruch,
Grammatik, Dialekt, Anonymisierung, Sonstiges. Eigene Gründe trägst du unter „Leitfaden &
Gespräche“ im Reiter „Einstellungen“ ein, eine Zeile pro Grund.

Geglättete Wörter erscheinen bei „Änderungen anzeigen“ durchgestrichen.

Nach dem Glätten zeigt Interis **„Analyse veraltet“**. Mit **„Analyse aktualisieren“**
startest du die Analyse neu. Erst dann nutzt die Fragenerkennung den geglätteten Text.

**Warum:** Die Analyse soll auf dem Text laufen, der die Grundlage der Auswertung ist. Jede
Änderung soll mit einem Grund nachvollziehbar sein.

**Erledigt:** Mindestens eine Glättung ist vorhanden. Der Schritt blockiert nichts. Wer nicht
glätten möchte, überspringt ihn.

**Hinweis:** Zitate in Extrakten und im Export zeigen den **geglätteten** Text, nicht das
Rohtranskript.

## 5. Fragen zuordnen

**Was tun:** In der Ansicht **„Nebeneinander“** (oder im Transkript) prüfen, ob die erkannten
Fragen zur richtigen Leitfadenfrage gehören.

- **Frage auf eine Leitfadenfrage ziehen:** Das Frage-Kürzel auf die Kopfzeile der Leitfadenfrage
  ziehen. Die Frage wird Hauptfrage dieser Leitfadenfrage.
- **Frage auf „Fragen ohne Leitfaden-Zuordnung“ ziehen:** Sie wird eine spontane Nachfrage.
- **Ohne Ziehen:** Auf das Frage-Kürzel klicken. Im Dialog **„Frage zuordnen“** wählst du die
  Leitfadenfrage. Mit „geplante Nachfrage dazu“ wird sie als Nachfrage dieser Leitfadenfrage
  eingeordnet. Die Schaltfläche **„Ist keine Frage“** nimmt sie aus der Auswertung heraus.
- **Antwort verknüpfen:** Den Griff **„Antwort ziehen“** am Redebeitrag der befragten Person auf
  eine Leitfadenfrage ziehen. Dabei wird der ganze Redebeitrag verknüpft, nicht eine Textauswahl.
- **Frage nicht erkannt:** Im Transkript markieren und **„Als Frage markieren“** wählen.

Das Ziehen ist nur eine Abkürzung. Jede Zuordnung geht auch über einen Dialog.

**Warum:** Die Analyse erkennt Fragen am Satzbau. Welche Leitfadenfrage gemeint war, entscheidest du.

**Erledigt:** Keine Haken-Regel. Die Seite zeigt, wie viele Leitfadenfragen gestellt wurden
(„gestellt“) und wie viele Fragen ohne Leitfaden-Zuordnung übrig sind („spontan“).

## 6. Fehlende Fragen klären

**Was tun:** Jede Leitfadenfrage, die in der Ansicht „Nebeneinander“ den Status **„fehlt –
begründen“** hat, braucht eine der beiden Angaben:

- **Antwort an anderer Stelle.** Im Transkript die Antwort markieren und **„Antwort auf Frage …“**
  wählen. Oder unter **„Vorschläge – bitte prüfen“** einen Vorschlag übernehmen oder verwerfen.
  Die Zelle wird dann „anderswo beantwortet“. Wenn die Frage deshalb nicht gestellt wurde,
  die Checkbox **„Diese Frage habe ich deshalb weggelassen“** ankreuzen. Dann lautet der Status
  „weggelassen – schon beantwortet“.
- **Begründung.** Die Schaltfläche **„Begründen“** öffnet den Dialog „Warum wurde diese Frage
  nicht gestellt?“. Zur Wahl stehen „Nicht gestellt“, „Nicht relevant für diese Person“ und
  „Sonstiges“, dazu eine Notiz (höchstens 2000 Zeichen). Die Zelle lautet dann „nicht gestellt –
  begründet“. Mit „Begründung ändern“ oder „Begründung entfernen“ bearbeitest du sie.

**Warum:** Eine fehlende Antwort ohne Grund lässt sich nicht von einer Antwort unterscheiden,
die an anderer Stelle steht.

**Erledigt:** Keine Leitfadenfrage hat mehr den Status „fehlt“. Solange welche offen sind, zeigt
die Seite Ablauf „offen: …“ mit den Codes.

## 7. Extrahieren

**Was tun:** Im Transkript eine Textstelle markieren und **„Als Extrakt übernehmen …“** wählen.
Im Dialog **„Extrakt anlegen“** wählst du die Leitfadenfrage und schreibst die **Kernaussage in
eigenen Worten** (Pflichtfeld, höchstens 2000 Zeichen). Das Zitat bleibt im Transkript.

Auf der Seite **„Auswertung“** kannst du Kernaussagen ändern („Kernaussage speichern“) und
löschen. Vor dem Löschen fragt Interis nach („Extrakt löschen?“).

**Warum:** Die Kernaussage je Frage und Gespräch ist das Ergebnis, das in die frühe Auswertung
geht. Das Zitat belegt sie.

**Erledigt:** Das Gespräch hat mindestens einen Extrakt.

**Hinweis:** Das Zitat in der Auswertung ist der korrigierte bzw. geglättete Text.

## 8. Exportieren

**Was tun:** Auf der Seite **„Auswertung“** wählen:

- **„Als Word exportieren“**: Datei `extraktion-p<Projektnummer>.docx`
- **„Als CSV (Excel) exportieren“**: Datei `extraktion-p<Projektnummer>.csv`

Die Tabelle hat sechs Spalten: Gespräch | Frage | Leitfadenfrage | Kernaussage | Zitat | Zeit.
Die Zeit ist Anfang–Ende der Textstelle.

Die CSV-Datei ist UTF-8 mit Byte-Order-Mark, mit Semikolon getrennt und hat Windows-Zeilenenden,
damit Excel die Umlaute richtig anzeigt. Zellen, die mit `=`, `+`, `-`, `@` oder einem
Tabulator- bzw. Zeilenumbruch beginnen, werden mit einem vorangestellten Apostroph geschrieben.
So werden sie in Excel nicht als Formel ausgeführt.

**Warum:** Die Tabelle ist die Grundlage für die frühe Auswertung.

**Erledigt:** Der Export hat keinen gespeicherten Zustand. Die Datei entsteht im Arbeitsspeicher
und wird an den Browser übergeben. Interis legt sie nicht im Datenordner ab.

---

## Warum diese Reihenfolge

- **Das Transkript bleibt roh.** Korrekturen, Glättungen, Zuordnungen und Begründungen liegen
  getrennt daneben. So bleibt jede Änderung nachvollziehbar und lässt sich zurücknehmen.
- **Korrigieren vor Glätten.** Geglättet wird nur ein Text, dessen Wortlaut stimmt. Wer vorher
  glättet, glättet Fehler der Erkennung mit.
- **Glätten vor Fragenzuordnung.** Die Analyse (Fragenerkennung, Zuordnung, Vorschläge) läuft
  auf dem geglätteten Text. Ändert sich der Text, zeigt Interis „Analyse veraltet“. Wer nach dem
  Glätten die Analyse aktualisiert, arbeitet bei der Zuordnung nicht mit veralteten Vorschlägen.
- **Fehlende Fragen zuletzt.** „Fehlt“ ergibt sich erst, wenn die Zuordnung steht. Wer vorher
  begründet, muss nach jeder Änderung an der Zuordnung nachprüfen.
- **Extrahieren nach dem Klären.** Extrakte hängen an Leitfadenfragen und Textstellen. Erst mit
  geklärten Fragen ist die Auswertungstabelle vollständig.

## Was die Seite nicht prüft

- Die Seite Ablauf zeigt **Fortschritt**, keine Qualität. Ein Haken heißt nicht, dass eine
  Zuordnung inhaltlich richtig ist.
- Interis anonymisiert nichts automatisch. Der Glättungsgrund „Anonymisierung“ ist eine
  Markierung, mehr nicht. Was zu anonymisieren ist, entscheidest du selbst (siehe
  [METHODEN.md](METHODEN.md)).
- Änderungen am Transkript lösen **keine** automatische Analyse aus. Die Analyse startest du
  mit „Analyse aktualisieren“.
