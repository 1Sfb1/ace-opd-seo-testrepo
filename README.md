# De maandagredactie · SEO-contentpipeline voor Kade & Hof Wonen

Deze pipeline maakt van een vrijdagnotitie van een makelaar en een zoekvraag een onderbouwd Nederlands concept.
De redacteur kan dat concept bewerken, goedkeuren of afwijzen met een reden. Per editie (een week) komen er vier
concepten: per makelaar één weekterugblik en één thema-artikel. De pipeline eindigt bij menselijke review: er gaat
niets naar een website.

Inzending voor de praktijkopdracht ACE-OPD-SEO, versie 2. Alle invoer komt uit bijlage A tot en met C van de opdracht.

## Wat je nodig hebt

- Python 3.10 of nieuwer. Er zijn geen pakketten nodig: geen `pip install`, geen sleutel, geen account, geen netwerk.
- Een teksteditor om de Markdown-concepten te bewerken.

```
git clone https://github.com/1Sfb1/ace-opd-seo-testrepo.git
cd ace-opd-seo-testrepo
python run.py --help
```

Gebruik op Windows `python` of `py`; op macOS en Linux zo nodig `python3`.

## Een editie maken (de starthandeling)

Eén commando per editie, met een instelbare week:

```
python run.py editie --week W50
```

Dat schrijft vier documenten naar `uitvoer/W50/`:

| Sleutel (week-makelaar-soort) | Wat het is |
|---|---|
| `W50-M1-terugblik` | Noors weekterugblik op notitie N1 |
| `W50-M1-thema` | Noors thema-artikel bij zoekvraag Q1: een update van `/gids/fietsberging` |
| `W50-M2-terugblik` | Ivo's weekterugblik op notitie N2 |
| `W50-M2-thema` | Ivo's thema-artikel bij zoekvraag Q2: een nieuwe pagina |

Daarnaast schrijft de run:

- `uitvoer/redactielog.csv` en `redactielog.csv` in de hoofdmap: één regel per concept (zie hieronder);
- `uitvoer/taken.md`: open taken voor de redacteur, zoals beeldtaken;
- `uitvoer/revisies/`: elke versie van elk concept, plus de diff na een besluit;
- `uitvoer/prompts/`: de prompt per concept (zie "Hoe de tekst ontstaat").

Een schone kopie van deze repository heeft een lege `uitvoer/`. Wil je opnieuw beginnen, gebruik dan
`python run.py reset`. Dat maakt alleen `uitvoer/` leeg; `voorbeelden/` blijft staan (die wis je alleen met
`reset --werkmap voorbeelden --ja`). `invoer`, `kopij` en `tests` kunnen geen werkmap zijn.

Draai de weken in volgorde. Draai je toch eerst W51, dan waarschuwt de pipeline dat W50 nog ontbreekt. De
onderwerpkalender houdt de plek van W50 dan vrij, zodat W50 later gewoon Q1 en Q2 krijgt.

## Een concept lezen

Elk document heeft drie delen:

1. **De lezerskopij**: kop, onderkop, lopende tekst (maximaal 600 woorden) en de bio. Die eindigt bij de regel
   `<!-- einde lezerskopij -->`.
2. **Voor de website en Voor de reviewer**: metatitel, metabeschrijving, drie tags, de zoekvraag of notitie die de
   aanleiding is, de paginakeuze (update of nieuw) met reden, waarom het stuk nu past, een tabel met elke belangrijke
   claim, het bron-ID en de bronregel zelf, open redactievragen en, bij een update, wat er verandert ten opzichte van
   de huidige pagina.
3. **Pad, beeld en controle**: het voorgestelde URL-pad, het beeld met bestandsnaam en rechtenstatus, de uitkomst van
   de controles en het besluit. Dit blok schrijft de pipeline bij elke run opnieuw.

De controles melden met `OK`, `AANDACHT` of `FOUT`:

- ontbrekende kop, onderkop, metatitel, metabeschrijving, URL-pad, bio, of geen drie tags;
- te lange metatitel (meer dan 60 tekens) of metabeschrijving (meer dan 160 tekens), en meer dan 600 woorden;
- een URL-pad dat al bestaat in `invoer/sitemap.json` of dat een ander concept ook voorstelt;
- een percentage of prijsontwikkeling in de lezerskopij, ook uitgeschreven ("twaalf procent", "gestegen"), of een
  claim die naar X1 verwijst;
- een getal of maat die niet zo in een geciteerde bron staat. Het buurwoord telt mee: "1,10 m" en "huis 3" passen bij
  hun bron, maar "8 uur zon" niet, ook al staat "Hof 8" in de bron. Uitgeschreven maten zoals "zes uur" tellen ook;
- een update zonder tabel met wijzigingen ten opzichte van de huidige pagina;
- 'u' in plaats van 'je';
- geen vrijgegeven, passend beeld (dan komt er een beeldtaak);
- kopij uit het sjabloon in plaats van uit opgeslagen modeluitvoer, of opgeslagen kopij die bij andere feedback
  hoort;
- tekst die na een besluit nog is bewerkt.

## Bewerken, goedkeuren en afwijzen

**Bewerken**: open het Markdown-bestand in een editor en pas de tekst aan, alles behalve het blok
"Pad, beeld en controle". Een volgende run laat je tekst staan. Een ander URL-pad zet je onder "Voor de website"
(`- URL-pad: ...`); de pipeline neemt het over en controleert het opnieuw op dubbelingen. Een wijziging in het blok
zelf neemt de pipeline niet over: die bewaart je wijziging in `uitvoer/revisies/<sleutel>/pipelineblok-bewerkt-N.md`
en meldt dat in het document.

**Goedkeuren** (ook na een bewerking):

```
python run.py besluit W50-M1-thema goedgekeurd
```

**Afwijzen** kan alleen met een reden:

```
python run.py besluit W50-M2-thema afgewezen --reden "Geef de lezer een concrete controle voor het volgende bezoek."
```

Na een besluit:

- staan status, reden en revisienummer in het document, in `redactielog.csv` en in `uitvoer/besluiten.csv`;
- staat de bewerking als zin in het document ("Toegevoegd door de redacteur: ..."), met de volledige diff in
  `uitvoer/revisies/<sleutel>/diff-r1-rN.diff`;
- blijft de afgewezen tekst staan;
- gaat een afwijzing of bewerking van een thema als feedback mee naar het volgende thema van dezelfde makelaar.
  Het log zegt in `feedback_verwerkt` waar die feedback is verwerkt;
- leidt een latere bewerking tot de melding "De tekst is na het besluit bewerkt ... Beslis opnieuw" en de status
  "goedgekeurd (na besluit bewerkt)" in het log.

**De twee besluiten uit bijlage B in één keer**: `python run.py bijlage-b`. Dat voegt in Noors thema de zin "Meet thuis
ook hoe breed je stuur is." toe (na stap 1), keurt dat stuk goed, en wijst Ivo's thema af met de reden uit bijlage B.
Wil je het zelf doen, gebruik dan de editor en de twee `besluit`-commando's hierboven.

## Opnieuw draaien

```
python run.py editie --week W50
```

Een tweede run voor dezelfde week:

- maakt geen extra documenten: de sleutel is altijd week + makelaar + soort;
- laat bewerkte, goedgekeurde en afgewezen tekst staan. Een handmatige bewerking krijgt de status
  "concept (handmatig bewerkt)" en een eigen revisie;
- ververst alleen het blok "Pad, beeld en controle". Een nieuw dubbel pad of een nieuw vrijgegeven beeld zie je dus
  meteen;
- houdt de zoekvraag die eerder voor een thema is gekozen;
- zet een verwijderd document terug uit de laatste revisie, met tekst en besluit.

## Zo werkt de planning

- **Thema-onderwerp**: uit de onderwerpkalender (bijlage B). Een zoekvraag is per kalendermaand voor de hele redactie
  maar één keer beschikbaar, en een afgewezen concept houdt zijn plaats. In W51 wil Ivo Q2, maar die is in december al
  gebruikt door zijn afgewezen W50-thema. Daarom krijgt hij het alternatief Q4. De reden staat in het document en in
  `keuzereden` in het log.
- **Update of nieuw**: heeft de zoekvraag een bestaande pagina (Q1 met `/gids/fietsberging`), dan wordt het een update
  op hetzelfde pad. De huidige tekst uit bijlage C gaat mee in de prompt, en het document toont per passage wat er
  behouden, vervangen of toegevoegd is. Anders wordt het een nieuwe pagina onder `/gids/`.
- **Beeld**: het best passende beeld uit het register voor het gebied en het onderwerp van de makelaar. Passen er
  meer even goed, dan wint een vrijgegeven beeld, en daarvan het laatst geregistreerde. Is geen enkel best passend
  beeld vrijgegeven (F4 is verlopen), dan krijgt het stuk geen beeld maar een beeldtaak.
- **Bronnen**: alleen vrijgegeven feiten uit het gebied van de makelaar mogen in de tekst. X1 staat in de prompt
  alleen als "onbevestigd" en komt in de reviewer-sectie terug als open redactievraag.

## Een ontbrekend beeld afhandelen

In W51 hebben Ivo's twee stukken een beeldtaak: F4 (`hof8-fietsroute.jpg`) past, maar de rechten zijn verlopen.
De taak staat in het document, in `aandacht` in het log en in `uitvoer/taken.md`. Afhandelen gaat zo:

1. Regel de rechten opnieuw of laat een nieuwe foto maken.
2. Pas `invoer/redactiebron.json` aan, onder `beeldregister`:
   - Rechten van F4 verlengd? Zet bij F4 `"recht": "vrijgegeven"`.
   - Nieuwe foto? Voeg een regel toe, bijvoorbeeld
     `{"id": "F5", "bestand": "hof8-fietsroute-2027.jpg", "gebied": "Lindehof", "onderwerp": "route naar fietsenstalling", "recht": "vrijgegeven"}`.
3. Draai de week opnieuw: `python run.py editie --week W51`. Het beeld staat dan in het document en de taak verdwijnt
   uit `taken.md`. De tekst verandert niet.

## Hoe de tekst ontstaat (AI-inzet en de modus zonder sleutel)

Per concept bouwt de pipeline een prompt (`uitvoer/prompts/<sleutel>-<vingerafdruk>.txt`). Die bevat het profiel en de
stem van de makelaar, de notitie of zoekvraag, de vrijgegeven feiten, X1 als onbevestigd, bij een update de huidige
pagina, en eventuele feedback van de redacteur. De vingerafdruk is een hash van die prompt.

**Modus `opgeslagen`** (standaard, geen sleutel nodig): staat er in `kopij/` een modelantwoord met dezelfde sleutel en
vingerafdruk, dan gebruikt de pipeline dat. Is er alleen een antwoord voor dezelfde bronnen en hetzelfde onderwerp
maar met andere feedback (bijvoorbeeld omdat de redacteur iets anders aanpaste dan in bijlage B), dan gebruikt de
pipeline dat dichtstbijzijnde antwoord en meldt `AANDACHT: De opgeslagen kopij is geschreven bij andere feedback`.
De feedback telt dan niet als verwerkt; de redacteur controleert het of laat het stuk herschrijven. De acht antwoorden in `kopij/` zijn geschreven door Claude (Anthropic,
Claude Opus 5.5) in een Claude Code-sessie op 25 november 2026, als antwoord op precies deze prompts. Vier ervan
zijn na een blinde beoordeling op dezelfde dag op één punt herschreven; het veld `herzien` in het bestand zegt wat. De beoordelaar
heeft daardoor geen sleutel, account of betaalde dienst nodig, en de voorbeelden zijn reproduceerbaar.

**Sjabloon als vangnet**: verandert de invoer zodat er geen passend antwoord is (bijvoorbeeld een andere week, of W51
draaien in een nieuwe werkmap zonder passend antwoord), dan maakt de pipeline een eenvoudig concept uit de
bronzinnen die bij het onderwerp passen. Dat concept is als
`AANDACHT: Kopij uit het sjabloon` gemarkeerd. Je kunt het sjabloon ook afdwingen met `--modus sjabloon`.

**Nieuwe tekst laten schrijven**: geef de prompt uit `uitvoer/prompts/` aan een taalmodel naar keuze. Sla het
JSON-antwoord op als `kopij/<sleutel>-<vingerafdruk>.json` en draai de week opnieuw. Een concept dat nog niet bewerkt
of beoordeeld is, wordt dan bijgewerkt. Een rechtstreekse API-koppeling zit er bewust niet in: die zou een sleutel
vragen.

Gebruikte hulpmiddelen: Python 3 (standaardbibliotheek), Git, GitHub Actions. De code, de tests en deze README zijn
geschreven met Claude Code (Claude Opus 5.5). De beslissingen in de pipeline zijn regels in code, geen modeluitvoer:
onderwerp, update of nieuw, beeld, controles, sleutels, het bewaren van bewerkingen en feedback.

## De voorbeelden

`voorbeelden/` is een volledige run, gemaakt met dezelfde commando's in een eigen werkmap:

```
python run.py editie --week W50 --werkmap voorbeelden
python run.py bijlage-b --werkmap voorbeelden
python run.py editie --week W50 --werkmap voorbeelden
python run.py editie --week W51 --werkmap voorbeelden
```

- Acht concepten in `voorbeelden/W50/` en `voorbeelden/W51/`.
- `W50-M1-thema` is goedgekeurd met de extra zin van de redacteur. De diff staat in
  `voorbeelden/revisies/W50-M1-thema/diff-r1-r2.diff`.
- `W50-M2-thema` is afgewezen met reden. De afgewezen tekst staat er nog.
- `W51-M2-thema` gebruikt Q4. Het log zegt waarom, de sectie "Controle voor je volgende bezoek" verwerkt de
  afwijzing, en het stuk heeft een open beeldtaak voor F4.
- `W51-M1-thema` verwerkt Noors bewerking als feedback, in de sectie "Bereid je thuis voor".

`redactielog.csv` in de hoofdmap bundelt de logs van `voorbeelden/` en `uitvoer/`. De kolom `werkmap` zegt welke
rij waarbij hoort. In een schone kopie staan er dus alleen voorbeeldrijen in; je eigen runs komen erbij.

Kolommen: `werkmap, week, makelaar, soort, sleutel, documentpad, status, bron_ids, aanleiding, paginakeuze,
keuzereden, url_pad, beeld, beeldstatus, besluit, reden, revisie, feedback_verwerkt, aandacht, kopij`.

## De proeven zelf herhalen

```
python proeven.py
```

Dit kopieert de repository naar een tijdelijke map met een lege `uitvoer/` en voert de zes proeven uit de opdracht
uit, met de commando's uit deze README:

1. W50 vanaf een schone kopie;
2. geen X1 in de lezerskopij en alleen vrijgegeven beeld;
3. de besluiten uit bijlage B, daarna W50 opnieuw;
4. W51;
5. een extra pad in de sitemap, daarna W51 opnieuw;
6. de overdracht: een cijfer terugvolgen, een handmatige bewerking die blijft staan, een beeldtaak afhandelen.

Daarna volgt proef 7 met randgevallen buiten het scenario: een andere bewerking dan in bijlage B, uitgeschreven
percentages en maten, bewerken na goedkeuren, een verwijderd document, een eigen URL-pad, een wijziging in het
pipelineblok, een nieuwe foto F5, W51 vóór W50 en de beveiliging van `reset`. Het script controleert telkens het
waarneembare resultaat en eindigt met "48 van 48 controles geslaagd". In deze map
verandert niets. De unittests voor de controles draai je met `python -m unittest discover -s tests`. GitHub Actions
draait beide bij elke push (workflow "Tests").

**Proef 5 met de hand**: voeg in `invoer/sitemap.json` een regel toe met het pad van Ivo's W51-thema
(`/gids/looproute-fietsenstalling`) en draai `python run.py editie --week W51`. In het document staat dan
`AANDACHT: URL-pad ... bestaat al`. Tekst, sleutel en aantal documenten blijven gelijk.

## Bekende beperkingen

- Er is geen ingebouwde koppeling met een taalmodel (zie hierboven). Nieuwe kopij voor andere weken loopt via de
  prompts en `kopij/`.
- De algemene kennis over zonnestand (oosten: ochtendzon, westen: later op de dag, zuiden: rond het midden van de
  dag) staat in de claims als "algemene kennis", niet met een bron-ID. De redacteur controleert die formulering.
- De controle op getallen kijkt naar cijfers met hun buurwoord en naar uitgeschreven getallen met een eenheid ("zes
  uur"). Losse telwoorden zoals "vier bezoekers" controleert ze niet; die staan als claim met bron in de tabel.
- De controles zijn regels, geen begrip van de tekst. Een verzonnen bewering zonder getal ("allebei lichte kamers")
  vangen ze niet; daarvoor is de claimtabel en de redacteur.
- De stemcontrole kijkt alleen naar 'je' tegenover 'u'. Of de stem klopt, beoordeelt de redacteur.
- De beeldkeuze is regelgebaseerd: gebied plus woorden uit het onderwerp. Bij een groter beeldregister is een
  handmatige keuze of een betere zoekfunctie nodig.
- Besluiten worden met een tijdstempel vastgelegd. De verder gelijke runs zijn bit voor bit herhaalbaar, de
  tijdstempels niet.
- `redactielog.csv` in de hoofdmap wordt bij elke run opnieuw geschreven uit de status van de werkmappen, dus ook je
  eigen runs veranderen dat bestand. Bewerk hem niet met de hand: zet besluiten in het document of met `run.py besluit`.
- Bij een andere bewerking dan in bijlage B gebruikt de pipeline het dichtstbijzijnde opgeslagen antwoord; zonder
  modelkoppeling kan ze geen nieuwe tekst schrijven die de nieuwe feedback precies volgt.

## Mappen

| Pad | Inhoud |
|---|---|
| `run.py` | De commando's: `editie`, `besluit`, `bijlage-b`, `status`, `reset` |
| `redactie.py` | De pipeline: planning, prompt, kopij, controles, besluiten, log |
| `invoer/redactiebron.json` | Het bronpakket uit de opdracht (bijlagen A tot en met C), ongewijzigd |
| `invoer/sitemap.json` | Bestaande paden op de website (bijlage C), voor de controle op dubbele paden |
| `invoer/instellingen.json` | Modus, woordgrens, lengtes voor metadata, werkmappen |
| `kopij/` | Opgeslagen modelantwoorden per sleutel en vingerafdruk |
| `voorbeelden/` | De volledige voorbeeldrun (acht concepten, revisies, besluiten, log, taken) |
| `uitvoer/` | Je eigen runs; leeg in een schone kopie |
| `redactielog.csv` | Het redactielog van alle werkmappen |
| `proeven.py`, `tests/` | De proeven uit de opdracht en de unittests |

Alle namen, adressen en gegevens komen uit het fictieve bronpakket van de opdracht. Er staan geen persoonsgegevens en
geen sleutels in deze repository.
