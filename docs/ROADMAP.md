# Tiekartta

## Valmiina

- **Indeksointi**: markdown, teksti, lähdekoodi ja PDF; inkrementaalinen päivitys ja poistot.
- **Hybridihaku**: vektorihaku ja tekstihaku yhdistettynä RRF:llä, täytesanat poistettuna.
- **Reranker**: paikallinen monikielinen cross-encoder parantaa tulosten järjestystä.
- **MCP-palvelin**: Claude Desktop ja Claude Code voivat hakea, listata ja lukea dokumentteja.
- **Laadun mittaus**: eval dokumentti- ja palatasolla, demoaineisto ja automaattinen laatutesti.
- **Kehitysympäristö**: palveluiden käynnistys ja pysäytys sekä testien ajo yhdellä komennolla.

Toteutuksen kuvaus: [ARCHITECTURE.md](ARCHITECTURE.md). Mittaukset: [MEASUREMENTS.md](MEASUREMENTS.md).

## Tunnetut rajoitteet

- **Suomen taivutus**: tekstihaku ei tunnista saman sanan eri muotoja ("irtisanomisaika" ja
  "irtisanomisajan"). Vektorihaku paikkaa tätä osittain. Rajoite on kirjattu testiksi, joka
  alkaa mennä läpi, kun asia korjataan.
- **Harvinaisten sanojen painotus**: tekstihaun järjestys ei huomioi, kuinka harvinainen sana
  on. Kaikissa dokumenteissa toistuva yrityksen nimi painaa yhtä paljon kuin harvinainen
  tunniste.
- **Kielten välinen tekstihaku**: suomenkielinen kysymys ei osu englanninkieliseen tekstiin
  tekstihaussa, vain vektorihaussa.
- **Dokumenttien versiot**: haku ei tiedä, mikä samasta ohjeesta on voimassa oleva versio.
- **Office-tiedostot** (docx, pptx, xlsx) vaativat raskaan docling-kirjaston.
- **Hakuaika**: reranker vie noin 2,6 sekuntia haulta CPU:lla.

## Seuraavaksi

1. **Oma kysymysjoukko omista dokumenteista** (20-50 kysymystä). Demoaineisto ei enää erottele
   parannuksia, joten jatkokehitys tarvitsee todellisen mittarin.
2. **Oma agenttikomento** (`localrag ask`): kysymykseen vastataan lähdeviitteineen ilman
   erillistä MCP-asiakasta.
3. **Suomen taivutus tekstihakuun**: vaihtoehtoina merkkijonojen osittainen vertailu
   (`pg_trgm`) tai sanojen perusmuotoistus (esim. Voikko).

## Myöhemmin

- BM25-järjestys tekstihakuun (huomioi sanojen harvinaisuuden), esim. ParadeDB `pg_search`
- Rerankerin nopeuttaminen: lyhyempi teksti rerankerille tai Macin näytönohjaimen käyttö
- Jatkuva indeksointi tiedostojen muuttuessa
- HTTP-rajapinta, jos hakua halutaan käyttää omasta käyttöliittymästä
- Kevyempi docx-tuki ilman doclingia
- Kuvat ja skannatut PDF:t (tekstintunnistus)
