# Methodische Grundlagen von Interis

**Was dieses Dokument ist:** eine Übersicht, welche methodischen Verfahren Interis berührt,
wofür sie im Werkzeug vorkommen und wie gesichert der Quellenstand ist. Es dient der
eigenen Prüfung.

**Was dieses Dokument nicht ist:**

- kein Methodenkapitel für die Masterarbeit (das muss selbst geschrieben und mit der
  Betreuung abgestimmt werden);
- keine rechtliche Beratung zur Anonymisierung von Interviewdaten (dafür sind die
  Datenschutzbeauftragten der Hochschule zuständig).

## Stand der Quellen

Bei der Erstellung dieses Dokuments waren die wissenschaftlichen Quellen im Sandkasten nicht
lesbar, weil die entsprechenden Websites blockiert waren. Die Angaben unten stammen aus
Suchtreffern oder sind nicht geprüft. Vor dem Zitieren ist jede Quelle im Original zu lesen.

Die Spalte „Status der Quelle“ bedeutet:

- **verifiziert:** Der Inhalt wurde aus einer abgerufenen Quelle gelesen.
- **nur Suchtreffer:** Die Quelle existiert laut Suchtreffer. Der Inhalt wurde nicht gelesen.
- **nicht geprüft:** Die Quelle ist nur als Hinweis genannt. Ob es Suchtreffer gab, ist nicht
  dokumentiert. Der Inhalt ist unbekannt.
- **nicht zutreffend:** Das Verfahren ist eine eigene Festlegung in Interis, keine
  Literaturmethode. Es ist nur im Code und in der Repo-Dokumentation belegt.

## Verfahren und Bezug zu Interis

| Verfahren | Wofür in Interis | Status der Quelle |
|---|---|---|
| **REFI-QDA-Austauschstandard** (Codebook QDC, Projekt QDPX), gepflegt von der REFI-QDA-Arbeitsgruppe | Interis exportiert derzeit kein QDPX. Im Repo ist ein QDA-Export nur als spätere Erweiterung genannt (`ARCHITECTURE.md`, Abschnitt 7). | verifiziert |
| **Transkriptionsregeln nach Dresing & Pehl** (einfaches und erweitertes System; Füllwörter, Pausen) | Der Modus „Glätten“ und die Standardgründe (Füllwort, Wortwiederholung, Satzabbruch) in `src/interis/web/edits.py`. Der Kommentar dort nennt die Quelle als Bezug. Diese Zuordnung ist noch zu prüfen. | nicht geprüft |
| **Glättung als begründeter Zusatzschritt** | Die Oberfläche speichert jede Glättung mit Grund, das Rohtranskript bleibt unverändert. Der Ablauf ist eine eigene Festlegung. | nicht zutreffend |
| **Extraktionsmethode nach Gläser & Laudel** (Extrakte aus Interviews, FQS-Beiträge 2013 und 2019 als Treffer genannt) | Das Werkzeug „Extrakt“: Kernaussage je Leitfadenfrage und Gespräch, mit Zitat. Der Begriff „Extraktion“ steht im Ablauf und im Export. | nur Suchtreffer |
| **Experteninterview nach Meuser & Nagel** | Das Erhebungsverfahren ist nicht im Werkzeug festgelegt. Interis unterstützt einen Leitfaden mit Fragen-Codes. Ob der Bezug zu Experteninterviews passt, ist offen. | nicht geprüft |
| **Qualitative Inhaltsanalyse** (Mayring; Kuckartz) | Nicht umgesetzt. Interis bildet keine Kategorien oder Codesysteme über Textstellen. Die Extrakte sind keine Kategorien. | nicht geprüft |
| **Framework-Methode** (Matrix aus Fällen und Themen; Stufen der Methode nicht geprüft) | Die Auswertungstabelle hat Gespräche als Spalten und Leitfadenfragen als Zeilen. Ob sie einer Stufenfolge der Methode entspricht, ist nicht geprüft. | nicht geprüft |
| **Leitfadenentwicklung nach Helfferich** (Kürzel „SPSS“ im Recherchehinweis; die Bedeutung der Buchstaben ist nicht geprüft) | Leitfaden mit Codes, Varianten (`~`) und geplanten Nachfragen (`>`), siehe `ARCHITECTURE.md`, Abschnitt 6b. | nicht geprüft |
| **Anonymisierungsempfehlungen** (RatSWD, Qualiservice, HWR Berlin) | Interis verwendet Pseudonyme (z. B. I01). Das Stimmprofil (biometrisch) liegt im Datenordner und wird laut `ARCHITECTURE.md`, Abschnitt 6b, nicht in Transkripte oder Exporte geschrieben. Der Glättungsgrund „Anonymisierung“ ist eine Markierung. Eine automatische Anonymisierung gibt es nicht. | nicht geprüft |
| **Maschinelle Spracherkennung mit Wortzeitstempeln und Sprechertrennung** (Whisper-basiert, Alignment, Diarisierung) | Erstellung des maschinellen Transkripts. Unsichere Wörter (Wahrscheinlichkeit unter 0,5) sind in der Oberfläche markiert. Die Genauigkeit wurde im Repo nur an synthetischen deutschen Sprachproben gemessen (`ARCHITECTURE.md`, Abschnitt 6a). | nicht geprüft (Literatur); Umsetzung im Repo dokumentiert |
| **Satz-Embeddings für Vorschläge zur Leitfadenzuordnung** | Vorschläge „Vorschläge – bitte prüfen“ mit Schwellenwerten aus einer eigenen Kalibrierung (`ARCHITECTURE.md`, Abschnitt 6b). Der Umfang der Testdaten ist dort nicht angegeben. | nicht geprüft (Modellquelle nicht gelesen) |
| **Regelbasierte Fragenerkennung** (Fragezeichen, Fragewort, Verb-Erst-Stellung) | Erkennt Fragen im Transkript. Die Regeln sind eigene Festlegungen, nicht gegen Literatur geprüft (`ARCHITECTURE.md`, Abschnitt 6b). | nicht zutreffend |

Hinweis zur Quellenlage: Die Recherche-Zusammenfassung ordnet die nicht verifizierten Quellen
nicht einzeln zu. Deshalb steht „nur Suchtreffer“ nur dort, wo ein Suchtreffer ausdrücklich
genannt wurde. Alles andere gilt als „nicht geprüft“.

## Offene Prüfpunkte

Vor dem Zitieren oder Übernehmen einer Methode:

1. **Dresing & Pehl:** Welche Auflage und welches Jahr gelten? Was sagen die Regeln zu Füllwörtern
   und Pausen im einfachen und im erweiterten System? Passt der Begriff „Glättung“ zur Quelle?
   Der Kommentar in `src/interis/web/edits.py` ist erst nach dieser Prüfung zu belassen oder zu ändern.
2. **Gläser & Laudel:** Welcher der beiden FQS-Beiträge beschreibt das Extraktionsverfahren?
   Welche Schritte und welche Definition des Extrakts gelten dort? Welche Zitierweise ist
   vorgesehen?
3. **Meuser & Nagel:** Welche Publikation ist die Referenz? Passt der Bezug zum Experteninterview
   zur eigenen Auswahl der befragten Personen?
4. **Mayring und Kuckartz:** Nur relevant, falls später eine Kategorienbildung eingebaut wird.
5. **Framework-Methode:** Welche Stufen gibt es, und bildet die Auswertungstabelle sie ab oder
   nur die Tabellenform?
6. **Helfferich:** Was bedeutet das Kürzel, und welche Schritte der Leitfadenentwicklung sind
   gemeint?
7. **Anonymisierung:** Die aktuellen Fassungen von RatSWD, Qualiservice und HWR Berlin lesen.
   Die konkrete Anonymisierung von Interviews mit der Datenschutzstelle der Hochschule klären.
   Diese Liste ist keine Rechtsauskunft.
8. **REFI-QDA:** Falls ein QDPX-Export geplant wird, die aktuelle Fassung des Standards prüfen.
   Bei Einbindung der Referenzbibliothek portableQDA (Lizenz LGPL-3.0-only, verifiziert) die
   Lizenzfolgen prüfen. Interis nimmt derzeit keine Abhängigkeit dazu auf.
9. **Sprach- und Embedding-Modelle:** Lizenz und Dokumentation der verwendeten Modelle prüfen.
   Die Genauigkeit für echte Interviews ist nicht gemessen; die Messungen im Repo stammen von
   synthetischen deutschen Beispielen.
10. **Eigene Festlegungen:** Glättungsgründe, Ablauf der Schritte und die Regeln für „erledigt“
    mit der Betreuung abstimmen und in der Methodik begründen.
