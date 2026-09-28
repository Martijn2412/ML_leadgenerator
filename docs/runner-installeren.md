# De runner installeren (eenmalig, door de beheerder)

De knop **Leadlijst maken** draait niet op een server van GitHub, maar op een computer van
Takkenkamp zelf: een *self-hosted runner*. Zo blijven TIOS en Assetmaps (klantgegevens, AVG)
binnen het bedrijf. GitHub stuurt alleen de opdracht "start" en ziet alleen het modelrapport
(aantallen en scores, geen adressen).

## Wat heb je nodig
- Een pc of server die aan staat als iemand een leadlijst wil maken, met toegang tot de
  gedeelde map (bijv. `S:\Leadgenerator`). Minimaal 8 GB geheugen; 16 GB voor grote provincies.
- Beheerdersrechten op de repository in GitHub.

## Stappen
1. Ga in GitHub naar de repository → **Settings → Actions → Runners → New self-hosted runner**.
2. Kies het besturingssysteem (Windows of Linux) en voer de getoonde commando's uit op de pc.
   Beantwoord de vraag naar *labels* met: `takkenkamp`.
3. Installeer de runner als service, zodat hij na een herstart vanzelf weer draait
   (Windows: kies "Y" bij *run as service*; Linux: `sudo ./svc.sh install && sudo ./svc.sh start`).
4. Zorg dat het service-account van de runner de gedeelde map mag lezen en schrijven.
5. Ga naar **Settings → Secrets and variables → Actions → Variables** en maak de variabele
   `LEADGEN_MAP` met het pad naar de gedeelde map, bijvoorbeeld `S:\Leadgenerator`
   (gebruik bij een service op Windows liever het UNC-pad, zoals `\\server\data\Leadgenerator`,
   want netwerkschijfletters bestaan niet voor services).
6. Test: **Actions → Leadlijst maken → Run workflow** met een bestaand Assetmaps-bestand.

## Mapindeling
```
Leadgenerator\
  Adressenbestand_TIOS.xlsx     <- TIOS-export
  Woningen_Zeeland.xlsx         <- Assetmaps-export per provincie
  output\
    2026-09-28_1030_Woningen_Zeeland\
      leadlijst.xlsx            <- voor de binnendienst
      leadlijst_volledig.csv    <- alle adressen
      modelrapport.md           <- kwaliteit van het model
      model.joblib              <- getraind model
```

## Veiligheid
- Houd de repository **privé**. Een self-hosted runner op een publieke repository is onveilig.
- Excel- en CSV-bestanden staan in `.gitignore` en komen nooit in git.
- Wie de knop wil gebruiken heeft een GitHub-account met minimaal *Write*-rechten nodig.
