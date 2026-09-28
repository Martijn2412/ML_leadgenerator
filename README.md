# Leadgenerator Takkenkamp

Zoekt in een provincie de woningen met de grootste kans om klant te worden bij Takkenkamp
Vastgoed Verduurzamers. Het model leert van bestaande klanten (TIOS) welke kenmerken
kansrijke woningen hebben (bouwjaar, energielabel, oppervlakte, buurt, CBS-gasverbruik en
-inkomen, klanten in de buurt) en geeft elk ander adres in Assetmaps een score.

## Zo maak je een leadlijst (binnendienst)

1. Zet de Assetmaps-export (bijv. `Woningen_Zeeland.xlsx`) en de TIOS-export in de gedeelde
   map `Leadgenerator`.
2. Open de repository in GitHub → tabblad **Actions** → **Leadlijst maken** →
   knop **Run workflow**.
3. Vul de bestandsnamen in, eventueel een gemeente, en klik op de groene knop.
4. Na afloop (5 tot 30 minuten) staat de lijst in `Leadgenerator\output\<datum>_<bestand>\leadlijst.xlsx`.
   In GitHub zie je bij de run een samenvatting van het model.

### De leadlijst lezen
| tabblad / kolom | betekenis |
|---|---|
| **Top** | de kansrijkste adressen van de hele provincie |
| **Witte vlekken** | kansrijke adressen in postcodegebieden waar nog geen klant is |
| **per gemeente** | de kansrijkste adressen per gemeente, bijv. voor een brievenactie |
| `klasse` | A = top 10%, B = volgende 20%, C = rest |
| `score` | 0–100, hoger is kansrijker. Het is een volgorde, geen letterlijke kans |
| `eerder_contact` | "ja" = staat al in TIOS (bijv. offerte), maar werd geen klant |
| `klanten_in_buurt` | aantal bestaande klanten in dezelfde buurt |

Alle adressen staan in `leadlijst_volledig.csv` (Excel kan maximaal ~1 miljoen rijen tonen).

## Beheer

- Eenmalig: de runner installeren, zie [docs/runner-installeren.md](docs/runner-installeren.md).
- Instellingen (statussen die als order tellen, bladnamen, modelinstellingen): `config.yaml`.
- CBS-cijfers vernieuwen (bijv. jaarlijks): `python cli.py cbs-vernieuwen` en de bestanden in
  `data/cbs/` committen. Lukt ophalen niet, dan draait het model zonder die kenmerken en staat
  dat als waarschuwing in het rapport.

### Lokaal draaien
```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python cli.py run --map "S:\Leadgenerator" --tios Adressenbestand_TIOS.xlsx --assetmaps Woningen_Zeeland.xlsx
```
Opties: `--gemeente Veere`, `--max-adressen 2000`, `--geen-evaluatie` (sneller).

### Ontwikkelen
```bash
pip install -r requirements.txt -r requirements-dev.txt
ruff check . && pytest
```
De tests gebruiken alleen verzonnen data. Zet **nooit** echte klantbestanden in git.

## Opbouw
| bestand | wat |
|---|---|
| `leadgenerator/inlezen.py` | Excel inlezen, kolomnamen, BAG-ID-controle (voorloopnullen, verwisselde kolommen) |
| `leadgenerator/cbs.py` | CBS-gasverbruik en -inkomen ophalen, cachen, koppelen op buurtcode of naam |
| `leadgenerator/kenmerken.py` | TIOS samenvatten, koppelen, label `is_klant`, kenmerken, buurteffect |
| `leadgenerator/model.py` | ensemble (logistic regression + RandomForest), out-of-fold scoren |
| `leadgenerator/evaluatie.py` | kruisvalidatie, nieuwe postcodegebieden, tijdsbacktest, belangrijkste kenmerken |
| `leadgenerator/export.py` | Excel/CSV en modelrapport |
| `leadgenerator/pipeline.py` | de hele run in één functie (ook voor de toekomstige Streamlit-app) |
| `notebooks/` | het oorspronkelijke Colab-notebook, ter referentie |

## Verschillen met het Colab-notebook
- Buurteffect per **gemeente + buurt** (voorheen telden gelijknamige buurten in verschillende gemeenten samen).
- Logistic regression met **schaling** (voorheen domineerde WOZ en convergeerde het model slecht; de waarschuwing werd verborgen).
- **Out-of-fold scoren**: elk adres in de leadlijst wordt gescoord door een model dat dat adres niet in de training had.
- **BAG-ID's als tekst** met controle op objecttype; verwisselde vbo/pand-kolommen worden automatisch hersteld.
- Pand-order telt alleen als klant bij **grondgebonden woningen**, niet voor alle bewoners van een flat. Nieuw kenmerk `woningen_in_pand`.
- `-99997` wordt in **alle** getalkolommen leeg gemaakt; energielabels `A+`/`A++` worden herkend en ontbrekend label is een eigen kenmerk.
- **CBS-cache** in de repo en koppeling op buurtcode als Assetmaps die heeft.
- **Tijdsbacktest**: train met klanten tot jaar X, test of de klanten van daarna bovenaan staan.
- Kolom **eerder_contact**, klasse A/B/C, tabbladen per gemeente, en de volledige lijst als CSV (geen Excel-limiet meer).
- `pand_leeftijd` verwijderd (was gelijk aan bouwjaar, alleen omgekeerd).
