# Mittaukset

Tässä dokumentissa on hakulaadun mittaukset, niiden perusteella tehdyt muutokset ja
päätökset. Periaate on ollut, että jokaisen laatumuutoksen vaikutus mitataan ennen kuin se
jätetään käyttöön.

## Miten laatua mitataan

Mittaukseen tarvitaan joukko kysymyksiä, joiden oikea vastaus tiedetään. Demoaineistolle
kysymykset ovat tiedostossa `examples/questions.yaml`. Jokaisella kysymyksellä on:

- **odotettu tiedosto**, jossa vastaus on (`expected`)
- **odotettu teksti**, joka on osa vastausta, esimerkiksi "99,5 %" (`expected_text`)

Komento `localrag eval` ajaa jokaisen kysymyksen haun läpi ja katsoo, missä kohdassa
tuloslistaa oikea vastaus on. Tulos mitataan kahdella tasolla:

- **Dokumenttitaso**: onko oikea tiedosto tulosten joukossa?
- **Palataso**: onko tulosten joukossa pala, joka sisältää vastauksen?

Palataso on tärkeämpi, koska agentti saa haulta paloja eikä kokonaisia tiedostoja. Oikea
tiedosto voi olla tuloksissa väärällä palalla, jolloin agentti ei näe vastausta.

Kummallekin tasolle lasketaan kaksi lukua:

- **Hit@3**: kuinka suuri osa kysymyksistä löysi oikean vastauksen kolmen ensimmäisen
  tuloksen joukosta. Arvo 0,94 tarkoittaa, että 15 kysymystä 16:sta onnistui.
- **MRR@3** (mean reciprocal rank): kuinka korkealla oikea vastaus keskimäärin on. Sijalta 1
  löytynyt vastaus antaa 1, sijalta 2 puolet, sijalta 3 kolmanneksen ja ohilyönti 0. Arvo 1,0
  tarkoittaisi, että oikea vastaus oli aina ensimmäisenä.

## Aineisto

Demoaineisto (`examples/docs`) on kuvitteellisen Lumikko Demo Oy:n kahdeksan dokumenttia
(markdown, teksti ja PDF), yhteensä 30 palaa. Kysymyksiä on 16, ja ne on jaettu tyypin mukaan:

- **täsmätermit**, jotka löytyvät jo tekstihaulla (esim. "Lumikko-Guest")
- **eri sanoin muotoillut** kysymykset, jotka vaativat merkityksen ymmärtämistä
- **kielten väliset** kysymykset: suomenkielinen kysymys englanninkieliseen dokumenttiin ja päinvastoin
- **versiotapaus**: kaksi versiota samasta ohjeesta, joista vain uudempi on voimassa

Kaikki mittaukset: k = 3, embedding-malli bge-m3 (Ollama), MacBook (CPU).

## Tulokset

| Vaihe | Dok. hit@3 | Dok. MRR | Pala hit@3 | Pala MRR |
| --- | --- | --- | --- | --- |
| 1. Lähtötaso: vektorihaku + tekstihaku, RRF | 0,94 | 0,75 | 0,75 | 0,66 |
| 2. + täytesanojen poisto tekstihausta | 1,00 | 0,91 | 0,94 | 0,83 |
| 3. + reranker, 20 ehdokasta | 1,00 | 0,97 | 1,00 | 0,97 |
| 4. reranker, 10 ehdokasta (nykyinen oletus) | 1,00 | 0,97 | 1,00 | 0,97 |

### Vaihe 1 -> 2: täytesanojen poisto

**Havainto.** Lähtötasossa väärät dokumentit nousivat kärkeen täytesanojen takia. Tekstihaku
yhdistää kysymyksen sanat OR-ehdolla, joten esimerkiksi:

- "**Missä** maissa reittioptimointi toimii?" nosti kärkeen perehdytysohjeen, jossa kysytään
  "**Missä** toimisto on?"
- "Paljonko hotelliyö **saa** maksaa Helsingissä?" nosti kärkeen palvelusopimuksen ("asiakas
  **saa** hyvityksen"). Tämä oli ainoa kysymys, jonka oikea dokumentti ei löytynyt lainkaan.

Lisäksi uusi palatason mittari paljasti, että englanninkielinen kysymys sopimuksen
käytettävyydestä löysi oikean dokumentin mutta ei palaa, jossa luku 99,5 % on.

**Muutos.** Noin 240 suomen- ja englanninkielistä täytesanaa poistetaan tekstihaun kyselystä.

**Tulos.** Palatason osumat nousivat 0,75 -> 0,94. Viisi kysymystä parani, eikä yksikään
huonontunut. Hotellikysymys nousi ohilyönnistä sijalle 1, ja käytettävyyskysymyksen
vastauksen sisältävä pala nousi kolmen parhaan joukkoon.

### Vaihe 2 -> 3: reranker

**Havainto.** Jäljellä olevissa virheissä tekstihaun kohina ei ollut syy. Kahdessa kysymyksessä
semanttisesti läheinen mutta väärä pala oli sijalla 1 ja oikea sijalla 2. Esimerkiksi "Kuka
auttaa, jos tietokone ei käynnisty?" antoi ensin tietoturvaohjeen laiteosion IT-tuen yhteystiedon
sijaan. Kysymyksessä "Missä maissa reittioptimointi toimii?" vastauksen sisältävä pala puuttui
kolmen parhaan joukosta kokonaan.

**Muutos.** Reranker (BAAI/bge-reranker-v2-m3, INT8) pisteyttää hybridihaun parhaat ehdokkaat
lukemalla kysymyksen ja palan yhdessä.

**Tulos.** Kaikki 16 kysymystä löytävät vastauksen sisältävän palan kolmen parhaan joukosta, 15
niistä sijalta 1. Ainoa jäljelle jäänyt virhe on maakysymys: oikea pala on sijalla 2, ja sijalla 1
on palvelusopimus, jossa puhutaan Revontuli-reittioptimointipalvelusta. Vastaus on
englanninkielisessä tuotekuvauksessa, johon suomenkielinen tekstihaku ei osu.

### Vaihe 3 -> 4: ehdokkaiden määrä

**Havainto.** Reranker teki hausta hitaan: koko komentorivihaku kesti 7,0 sekuntia, kun se ilman
rerankeria kesti 0,6 sekuntia.

**Muutos.** Ehdokkaita pisteytetään 10 aiemman 20:n sijaan.

**Tulos.** Laatu pysyi täsmälleen samana, ja aika puolittui.

## Hakuaika

Mitattu komennolla `localrag search --timing`, 10 ehdokasta:

| Vaihe | Aika |
| --- | --- |
| Kysymyksen embedding (Ollama) | 0,04 s |
| Tietokantahaku (vektori + teksti + RRF) | 0,03 s |
| Reranker (10 palaa) | 2,6 s |
| Rerankerin mallin lataus | 1,4 s |
| Koko komentorivihaku | 3,9 s |

Rerankerin pisteytys kestää noin 0,3 sekuntia palaa kohden, ja aika kasvaa suoraan
ehdokkaiden määrän mukana (20 palaa 6,7 s, 10 palaa 3,1 s erillisessä mittauksessa). Mallin
lataus tapahtuu kerran prosessia kohden: MCP-palvelin pitää mallin muistissa, joten agentin
haut maksavat vain pisteytyksen.

## Tulosten rajoitukset

- **Aineisto on pieni.** 30 palaa ja 16 kysymystä riittävät näyttämään suunnan, mutta yksi
  kysymys muuttaa tulosta yli kuusi prosenttiyksikköä.
- **Kysymykset ja dokumentit on kirjoitettu samaan aikaan**, joten kysymykset sopivat
  dokumentteihin todennäköisesti paremmin kuin oikeassa käytössä. Tulokset ovat siksi
  luultavasti optimistisia.
- **Demo ei enää erottele parannuksia.** Kun kaikki kysymykset menevät läpi, uusien muutosten
  vaikutusta ei näe. Seuraava mittari on oma kysymysjoukko omista dokumenteista.
- **Ehdokasmäärää ei ole testattu isolla indeksillä.** Demossa 10 ehdokasta kattaa kolmanneksen
  kaikista paloista. Isommassa indeksissä oikea pala voi jäädä ehdokasjoukon ulkopuolelle.

## Automaattinen tarkistus

E2E-testi (`tests/test_e2e_quality.py`, ajo `scripts/test.sh e2e`) ajaa samat kysymykset ja
epäonnistuu, jos dokumenttitason hit@3 putoaa alle 0,9 tai palatason alle 0,8. Rajat jättävät
tilaa pienelle vaihtelulle, mutta huomaavat, jos laatu putoaa takaisin vaiheen 1 tasolle
(palatasolla 0,75). Testi käyttää `.env`-tiedoston asetuksia, joten sen pitää mennä läpi myös
ilman rerankeria.
