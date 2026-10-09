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
  Die Spaltenüberschriften sind die Schrittnamen.
- **Glätten (optional)** zeigt einen Strich, wenn keine Glättung vorhanden ist. Das ist
  kein Mangel.
- **Fragen zuordnen** zeigt keine Haken, sondern die Zahl der gestellten Leitfadenfragen
  („gestellt“) und die Zahl der Fragen ohne Leitfaden-Zuordnung („spontan“).
- **Fehlende Fragen klären** zeigt „–“, solange das Gespräch nicht transkribiert ist.
- **Analyse veraltet** erscheint, wenn Korrekturen oder Glättungen nach der letzten Analyse
  gespeichert wurden (siehe Schritt 4).
- **fehlt – begründen: F3, F5** nennt die Leitfadenfragen, die in diesem Gespräch noch ohne
  Antwort und ohne Begründung sind.
- Die Links führen zum **Transkript** des Gesprächs und zur Ansicht **Nebeneinander**.

---

## 1. Leitfaden festlegen

**Was tun:** Unter „Leitfaden & Gespräche“ im Reiter „Leitfaden“ den Leitfaden eingeben
oder als Datei laden (.typ, .docx, .md, .txt); ein Typst-Leitfaden kann auch direkt
eingefügt werden. Fragen mit `[optional]` oder `[Nebenfrage]` dürfen entfallen: Fehlen sie,
heißt das „entfallen – optional“ statt „fehlt – begründen“. Jede Frage bekommt einen Code (F1, F2 …). Eine Frage
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
Verknüpfungen, Korrekturen, Sprecherkorrekturen, Glättungen, Begründungen, Extrakte und das Häkchen „Korrektur
abgeschlossen“. Dafür fragt Interis nach, und die Bestätigung nennt genau diese Arten. Gelöscht
wird erst, wenn die neue Transkription fertig ist. Bricht man den Auftrag ab oder schlägt er
fehl, bleiben die Markierungen erhalten. Solange eine Transkription wartet oder läuft, lassen
sich keine Markierungen setzen oder ändern; Interis lehnt das ab.

## 3. Korrigieren

**Was tun:** Im Transkript den Modus **„Korrigieren“** wählen.

- Ein Wort anklicken, den richtigen Text eingeben und speichern.
- Oder einen Abschnitt markieren und **„Ersetzen …“** wählen.
- **„Änderung zurücknehmen“** im Dialog hebt eine Änderung wieder auf. Dazu gehören alle Wörter,
  die dieser Dialog geändert hat (die ersetzte Stelle und die gelöschten Wörter danach).
- Die Checkbox **„Änderungen anzeigen“** unterstreicht korrigierte Wörter. Darüberfahren
  zeigt den Originaltext.

Eine Ersetzung über mehrere Wörter schreibt den neuen Text in das erste Wort. Die übrigen
Wörter des Abschnitts werden gelöscht; ihre Zeitangaben bleiben erhalten. Ein Ersatztext
darf höchstens 200 Zeichen lang sein.

Ein Wort trägt nur eine Art Änderung. Wer ein korrigiertes Wort glätten will, nimmt zuerst die
Korrektur zurück; sonst meldet Interis „Diese Stelle hat schon eine andere Änderung“.

**Falscher Sprecher:** Wörter markieren oder auf den Sprechernamen eines Abschnitts klicken
und den richtigen Sprecher wählen; „Sprecher zurücksetzen“ nimmt das zurück. Der Abschnitt
bleibt an seiner Stelle (alle Markierungen bleiben gültig); wo innerhalb eines Abschnitts der
Sprecher wechselt, steht sein Name im Text. Ein Abschnitt zählt für den Sprecher, der die
meisten seiner Wörter sagt; ein Satz ebenso. Bei „Änderungen anzeigen“ sind geänderte Wörter
gestrichelt umrandet.

**Zeitspur beim Korrigieren.** Im Modus „Korrigieren“ steht rechts neben dem Text eine senkrechte
Zeitspur (Zeit läuft nach unten). Jeder **Block** – was eine Person sagt, bis die andere spricht –
ist ein Balken in der Spur seines Sprechers (links Interviewer, rechts Befragte:r), hinterlegt mit
der **Wellenform** der Aufnahme: so siehst du, wo wirklich gesprochen wird. Die Wellenform wird beim
ersten Öffnen im Hintergrund berechnet (einmal je Gespräch, danach gespeichert). Blöcke, die sich
zeitlich überlappen, teilen sich ihre Spur nebeneinander.

- **Abspielen:** Block anklicken spielt ihn ab und springt im Text dorthin; ein Klick in die freie
  Spur spielt ab dort. Die rote Linie ist die Wiedergabe, die Spur folgt ihr. Der Regler „grob – fein“
  ändert den Maßstab; die Spur folgt auch dem Text, wenn du ihn scrollst.
- **Grenze verschieben:** Den Block wählen, dann die Linie „Anfang“ oder „Ende“ ziehen: Die
  Wörter dazwischen gehen an den anderen Sprecher (im Text sofort markiert, „3 Wörter wechseln“).
  Sprecher werden je Wort gespeichert, deshalb rastet die Grenze zwischen zwei Wörtern ein.
  Genauer geht es mit den Pfeiltasten „Anfang“/„Ende“: ein Wort früher oder später. Nach jeder
  Änderung spielt Interis zur **Hörprobe** zwei Sekunden um die neue Grenze.
- Gespeichert wird als Sprecherkorrektur (wie beim Markieren von Wörtern); die Analyse zeigt danach
  „veraltet“, bis du „Analyse aktualisieren“ wählst.

**Einen Absatz einfügen (+).** Hat die Erkennung einen Einwurf oder einen ganzen Beitrag verpasst
(z. B. ein „Mhm“ der Interviewerin), steht zwischen zwei Absätzen ein kleines **+**. Es öffnet
einen Editor unter dem Absatz: **Wer spricht?** (Interviewer oder Befragte:r, bei mehr Personen
die Auswahl), der **Text**, **Anfang** und **Ende** in der Aufnahme sowie **Anhören**. Während du
tippst, erscheint der neue Absatz in der Zeitspur als gestrichelter Balken „neu“; **seinen Anfang
und sein Ende kannst du dort ziehen** (mit Hörprobe) oder im Editor mit ±0,5 s einstellen.

- Die Zeitspanne darf sich **überlappen**: Ein Interviewer-Einwurf, der in die Rede der befragten
  Person fällt, liegt in der Spur des Interviewers neben dem Beitrag der anderen. Überlappen sich
  zwei Absätze **in derselben Spur**, teilen sie sich diese in der Breite (Spalten nebeneinander).
- Ein eingefügter Absatz trägt im Text die Marke „eingefügt ✎“ (anklicken zum Bearbeiten oder
  Entfernen) und gestrichelten Rand in der Zeitspur. Seine Wörter lassen sich wie alle anderen
  korrigieren, abspielen und für Fragen und Extrakte markieren; die Zeit der Wörter verteilt Interis
  im Verhältnis ihrer Länge über die Zeitspanne.
- **Positionen verschieben sich mit:** Ein neuer Absatz schiebt die folgenden Absätze um eins nach
  unten, und alles, was an ihnen hängt (Korrekturen, Sprecherkorrekturen, Fragenzuordnungen,
  Verknüpfungen, Extrakte), wird mitgeschoben. Ein neuer Text im Absatz oder das Entfernen löscht
  die Korrekturen und Markierungen **in diesem Absatz** (Interis fragt vorher nach).
- Die Analyse zeigt danach „veraltet“; „Analyse aktualisieren“ nimmt die eingefügten Absätze mit.
  Das aufgenommene Transkript bleibt unverändert; Neu transkribieren entfernt auch die
  eingefügten Absätze (mit der bestehenden Rückfrage zu den Markierungen).

**Sprecher nach Stimme:** Ist die Sprechertrennung schlecht, die erste Minute (oder mehr)
wie oben richtigstellen und „Sprecher nach Stimme …“ wählen. Ein Hintergrundauftrag lernt aus
diesem Anfang die Stimmen (Stimmabdruck je Satz mit dem Modell der Sprechertrennung) und gibt
jeden späteren Satz der Stimme, der er deutlich ähnlicher klingt; sehr kurze Sätze behalten
ihren Sprecher. Das Ergebnis erscheint als Sprecherkorrektur (bei „Änderungen anzeigen“
gepunktet umrandet), deine eigenen Korrekturen bleiben immer vorrangig, und „Zuordnung nach
Stimme zurücknehmen“ hebt alles davon wieder auf.

Da der Interviewer in allen Gesprächen derselbe ist, reicht ein vollständig korrigiertes
Gespräch: im selben Dialog „Stimme lernen“ mit dem Interviewer als Sprecher speichert dein
Stimmprofil. In den anderen Gesprächen dann „Meine Stimme aus dem Stimmprofil“ wählen, ohne
Referenz: die Stimme der befragten Person lernt Interis aus den Sätzen, die am wenigsten nach
dir klingen (sie spricht im Interview meist am meisten). Das Profil nutzt auch die
Interviewer-Erkennung neuer Transkripte. Gilt für Gespräche zu zweit.

**Das Stimmprofil wird besser, je mehr du korrigierst.** „Stimme lernen“ ersetzt das Profil
nicht, sondern ergänzt es: die Stimmabdrücke werden nach der Menge an Sprache gewichtet
gemittelt. Hast du nur den Anfang korrigiert, gib im Dialog an, bis wohin (nur diese Sätze
zählen). Sätze, die klanglich nicht zum Rest passen (z. B. ein falsch zugeordneter Satz),
werden aussortiert, damit sie das Profil nicht verfälschen. Das Profil enthält nur den
Abdruck und Zahlen (Sprechzeit, Anzahl der Abschnitte, aus welchen Gesprächen), nie Text.

**Sätze nach Stimme beim Transkribieren.** In den Transkriptions-Einstellungen („Sätze nach
Stimme zuordnen“) bekommt jeder Satz schon beim Transkribieren die Stimme, der er deutlich
ähnlicher klingt; die Stimme der befragten Person wird dafür aus den Sätzen gelernt, die am
wenigsten nach dir klingen. Das Ergebnis steht direkt im Transkript, ohne dass du „Sprecher
nach Stimme“ von Hand startest. Es braucht ein Stimmprofil und gilt für Gespräche zu zweit.

**Einstellungen automatisch optimieren.** Auf der Seite „Transkription“ (Karte „Automatisch
optimieren“) wählst du pro Gespräch einen Ausschnitt von 1–15 Minuten, den du korrigiert
hast – oder ein Gespräch mit gesetztem „Korrektur abgeschlossen“. „Ausschnitt im Transkript
wählen …“ öffnet ein Fenster mit dem korrigierten Transkript, **Block für Block** (ein Block ist
das, was eine Person sagt, bis die andere spricht): erst den ersten, dann den letzten Block
anklicken. Korrigierte Blöcke sind markiert, „Aus Korrekturen vorschlagen“ wählt den Bereich vom
ersten bis zum letzten korrigierten Block (höchstens 10 Minuten; bei gesetztem „Korrektur
abgeschlossen“ ohne Korrekturen den Anfang). So beginnt und endet die Aufnahme immer an einer
Blockgrenze, nie mitten im Satz. Ein zu kurzer Ausschnitt wächst um die folgenden Blöcke, ein zu
langer verliert Blöcke am Ende. Unter der Zeile steht danach, was der Ausschnitt enthält (Zeiten,
Blöcke, Wörter, Wort- und Sprecherkorrekturen, Anfang und Ende des Textes); genau dieser
Ausschnitt wird verwendet. Dein korrigierter Text
(Wortkorrekturen und Sprecherkorrekturen) ist der Maßstab. Interis transkribiert die
Ausschnitte mit verschiedenen Einstellungen neu und misst

- **falsche Wörter** (Wortfehlerrate) und
- **falsch zugeordnete Wörter** („wer hat es gesagt“; unabhängig davon, wie die Sprecher
  benannt sind).

Probiert werden: Sprecher pro Satz, Sprecherpausen, Sätze nach Stimme (mit Profil),
Glossar aus deinen Korrekturen, Sprach-Empfindlichkeit, Beam, Raummikrofon, Hall reduzieren
und Rechengenauigkeit. Ein Verfahren wie Gradient Descent passt dafür nicht, weil die
Einstellungen diskret sind und jede Messung eine ganze Transkription ist. Stattdessen wird
jede Einstellung einzeln verändert und der beste Wert behalten, bis eine ganze Runde nichts
mehr bringt (Koordinatenabstieg). Einstellungen, die nur spätere Schritte betreffen, kommen
zuerst, weil sie die schon berechnete Spracherkennung wiederverwenden.

Mit zwei oder mehr Ausschnitten wird einer zurückgehalten: Die Suche sieht ihn nicht, und das
Ergebnis wird nur übernommen, wenn es auch dort besser ist. Mit einem Ausschnitt weist
Interis darauf hin, dass das Ergebnis nicht an ungesehenen Daten geprüft wurde. Ist etwas
besser, entsteht die Einstellung „Optimiert <Datum>“, die zum Standard wird; die bisherige
Einstellung bleibt erhalten und lässt sich oben wieder als Standard wählen. Zahlen im
korrigierten Text so schreiben, wie Whisper sie ausgibt (`fünf` statt `5`), sonst zählt
das als Fehler. Auf der Kommandozeile: `interis tune --window I01:0-300 --window I02:600-900`.

Korrekturen und Sprecherkorrekturen machen die Analyse veraltet, wie Glättungen. Danach „Analyse aktualisieren“ wählen,
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

Bei „Änderungen anzeigen“ erscheinen geglättete Wörter durchgestrichen. Ersetzte Glättungen
sind gestrichelt unterstrichen, Korrekturen durchgezogen unterstrichen.

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
  Verwerfen ist endgültig: der Vorschlag verschwindet und kommt nicht zurück, es sei denn, dieselbe
  Stelle wird von Hand verknüpft. Die Zelle wird dann „anderswo beantwortet“. Wenn die Frage deshalb nicht gestellt wurde,
  die Checkbox **„Diese Frage habe ich deshalb weggelassen“** ankreuzen. Dann lautet der Status
  „weggelassen – schon beantwortet“.
- **Begründung.** Die Schaltfläche **„Begründen“** öffnet den Dialog „Warum wurde diese Frage
  nicht gestellt?“. Zur Wahl stehen „Nicht gestellt“, „Nicht relevant für diese Person“ und
  „Sonstiges“, dazu eine Notiz (höchstens 2000 Zeichen). Die Zelle lautet dann „nicht gestellt –
  begründet“. Mit „Begründung ändern“ oder „Begründung entfernen“ bearbeitest du sie.

**Warum:** Eine fehlende Antwort ohne Grund lässt sich nicht von einer Antwort unterscheiden,
die an anderer Stelle steht.

**Erledigt:** Keine Leitfadenfrage hat mehr den Status „fehlt“. Solange welche offen sind, zeigt
die Seite Ablauf „fehlt – begründen: …“ mit den Codes.

## 7. Extrahieren

**Was tun:** Im Transkript eine Textstelle markieren und **„Als Extrakt übernehmen …“** wählen.
Im Dialog **„Extrakt anlegen“** wählst du die Leitfadenfrage und schreibst die **Kernaussage in
eigenen Worten** (Pflichtfeld, höchstens 2000 Zeichen). Das Zitat bleibt im Transkript.

Auf der Seite **„Auswertung“** kannst du Kernaussagen ändern („Kernaussage speichern“) und
löschen. Vor dem Löschen fragt Interis nach („Extrakt löschen?“). Kernaussagen zu Fragen, die
aus dem Leitfaden entfernt wurden, stehen unten unter „Nicht mehr im Leitfaden“.

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
