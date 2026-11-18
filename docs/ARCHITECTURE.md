# Miten localrag toimii

Tämä dokumentti kuvaa, mitä tapahtuu, kun dokumentit indeksoidaan ja kun niistä haetaan
tietoa. Jokaisen vaiheen kohdalla kerrotaan myös, miksi ratkaisu on valittu ja mitä
vaihtoehtoja oli. Termit on selitetty lopun sanastossa.

## Kokonaiskuva

localrag on RAG-järjestelmä (retrieval-augmented generation): kielimalli ei vastaa
kysymykseen pelkän oman tietonsa varassa, vaan se hakee ensin dokumenteista aiheeseen
liittyvät kohdat ja vastaa niiden perusteella.

Järjestelmässä on kaksi erillistä kulkua:

```
INDEKSOINTI (kerran, ja uudelleen kun tiedostot muuttuvat)

  hakemisto -> tiedostojen   -> tekstiksi -> paloiksi -> vektoreiksi -> PostgreSQL
               löytäminen       (parsinta)   (pilkkominen) (embedding)   (pgvector + tekstihaku)

HAKU (jokaisella kysymyksellä)

  kysymys -> vektorihaku ---+
                            +-> yhdistäminen (RRF) -> reranker -> parhaat palat -> agentti
          -> tekstihaku ----+
```

Kaikki tapahtuu omalla koneella: embedding-malli ajetaan Ollamalla, reranker ONNX
Runtimella ja tietokanta Dockerissa. Ulos lähtevät vain ne palat, jotka agentti (esim. Claude)
haun kautta saa.

## Indeksointi

### 1. Tiedostojen löytäminen

`indexer.py` käy annetun hakemiston läpi ja ohittaa piilotiedostot sekä tyypilliset
build- ja riippuvuushakemistot (`node_modules`, `dist`, `venv` ym.).

Indeksointi on inkrementaalista eli uusintakerralla käsitellään vain muuttuneet tiedostot:

- Jos tiedoston muokkausaika ja koko ovat samat kuin viimeksi, tiedosto ohitetaan heti.
- Muuten tiedostosta lasketaan tarkistussumma (SHA-256). Jos sisältö on sama (esim. tiedosto
  vain kopioitiin), päivitetään pelkkä muokkausaika.
- Jos sisältö on muuttunut, tiedoston vanhat palat poistetaan ja tiedosto käsitellään alusta.
- Tiedostot, jotka on poistettu levyltä, poistetaan myös kannasta.

Jokainen tiedosto tallennetaan omassa tietokantatransaktiossaan. Siksi hakuja voi tehdä jo
indeksoinnin aikana, eikä yksi viallinen tiedosto kaada koko ajoa.

### 2. Parsinta: tiedostosta tekstiksi

`parsing.py` muuttaa tiedoston tekstiksi:

- Markdown, tekstitiedostot ja lähdekoodi luetaan sellaisenaan.
- PDF luetaan pypdf-kirjastolla. Jokaisen sivun alkuun lisätään otsikko "Page N", jolloin
  sivunumero kulkee palan mukana ja agentti voi viitata siihen.
- docx-, pptx-, xlsx- ja html-tiedostot vaativat valinnaisen docling-kirjaston, koska se on
  raskas (tuo mukanaan PyTorchin).

Markdown on suosittu välimuoto, koska seuraava vaihe hyödyntää sen otsikoita.

### 3. Pilkkominen: tekstistä paloiksi

Embedding-malli tiivistää kokonaisen tekstin yhdeksi vektoriksi. Jos koko dokumentti
tiivistettäisiin yhdeksi vektoriksi, yksittäinen yksityiskohta hukkuisi muun sisällön
alle. Jos taas palat olisivat hyvin pieniä, niistä puuttuisi konteksti. Siksi teksti
jaetaan keskikokoisiin paloihin (engl. chunk).

`chunking.py` tekee sen kahdessa vaiheessa:

1. Markdown jaetaan osioihin otsikoiden mukaan. Jokaiselle palalle tallennetaan otsikkopolku,
   esimerkiksi `Lumikko Demo Oy - Matkustusohje > Varaukset > Hotellit`.
2. Osion sisältö kootaan kappale kerrallaan noin 500 tokenin (noin 2 000 merkin) paloiksi.
   Peräkkäiset palat menevät noin 60 tokenia päällekkäin, jotta raja-alueen lause ei katkea
   kummastakaan palasta kokonaan. Liian pitkät kappaleet jaetaan riveittäin, lauseittain ja
   tarvittaessa sanoittain.

Tokenimäärä arvioidaan kaavalla merkit / 4, mikä riittää kokojen mitoitukseen.

### 4. Embedding: palasta vektoriksi

Embedding on luettelo lukuja (bge-m3-mallilla 1 024 lukua), joka kuvaa tekstin merkitystä.
Samaa tarkoittavat tekstit saavat lähekkäiset vektorit, vaikka sanat olisivat eri: "läppäri
varastetaan" ja "kadonnut tai varastettu laite" ovat lähellä toisiaan. Malli on monikielinen,
joten myös suomenkielinen kysymys ja englanninkielinen teksti voivat osua yhteen.

Ennen embeddingiä palan alkuun lisätään tiedoston nimi ja otsikkopolku. Näin pala "Kuukausimaksu
on 4 200 euroa" löytyy myös kysymyksellä, joka mainitsee sopimuksen tai asiakkaan nimen, vaikka
pala itse ei sitä mainitse.

Malli ajetaan paikallisesti Ollamalla, joten dokumentit eivät lähde koneelta. Mallin nimi ja
vektorin pituus tallennetaan kantaan. Jos asetuksia muutetaan, ohjelma kieltäytyy toimimasta,
koska eri mallien vektorit eivät ole vertailukelpoisia: kanta pitää tyhjentää ja indeksoida
uudelleen (`localrag reset`).

### 5. Tallennus

Kannassa on kaksi päätaulua: `documents` (tiedostot, tarkistussummat) ja `chunks` (palat).
Jokaisella palalla on:

- **vektori**, jota varten on HNSW-indeksi (nopea likimääräinen lähimpien naapurien haku)
- **tekstihakuindeksi** (`tsvector`), joka sisältää palan sanat perusmuodossaan sellaisinaan,
  pienillä kirjaimilla. Siihen otetaan mukaan myös tiedoston nimi ja otsikkopolku.

Tekstihaku käyttää Postgresin `simple`-konfiguraatiota, joka ei muuta sanoja perusmuotoon.
Kieltä ymmärtävä konfiguraatio toimisi vain yhdelle kielelle, ja aineisto on sekaisin suomea
ja englantia. Hinta on se, että suomen taivutusmuodot eivät osu toisiinsa ("irtisanomisaika"
ja "irtisanomisajan" ovat tekstihaulle eri sanoja).

## Haku

Haku yhdistää kaksi hakutapaa, koska kummallakin on sokea pisteensä.

### 1. Vektorihaku

Kysymyksestä lasketaan embedding samalla mallilla, ja kannasta haetaan 50 palaa, joiden
vektorit ovat lähimpänä (kosinietäisyys). Vektorihaku löytää merkityksen, vaikka sanat
olisivat eri. Se on kuitenkin heikko tarkoissa tunnisteissa, kuten sopimusnumerossa
"LUM-2025-117" tai nimessä, jota malli ei tunne.

### 2. Tekstihaku

Tekstihaku etsii palat, joissa esiintyy kysymyksen sanoja, ja järjestää ne sen mukaan, kuinka
monta sanaa ja kuinka tiheästi osuu (`ts_rank_cd`). Se löytää tunnisteet ja nimet tarkasti,
mutta ei ymmärrä merkitystä eikä taivutusta.

Kaksi yksityiskohtaa vaikuttavat laatuun merkittävästi:

- **Sanat yhdistetään OR-ehdolla.** Jos vaadittaisiin kaikkia sanoja (AND), luonnollisen kielen
  kysymys ei osuisi juuri koskaan, koska kysymyksessä on sanoja, joita palassa ei ole.
- **Täytesanat poistetaan kyselystä.** OR-ehdon takia sanat kuten "missä", "saa", "how" ja
  "many" toivat tuloksiin dokumentteja, joissa sattui olemaan sama täytesana. Noin 240 suomen-
  ja englanninkielistä täytesanaa (`stopwords.py`) poistetaan siksi kyselystä ennen hakua.
  Dokumenttien indeksiin ne jäävät, joten muutos ei vaatinut uudelleenindeksointia.

Postgresin valmis suomen täytesanalista ei kelvannut, koska siitä puuttuvat kysymyssanat kuten
"kuinka", "paljonko" ja "milloin".

### 3. Yhdistäminen: Reciprocal Rank Fusion

Vektorihaun ja tekstihaun pisteet ovat eri asteikoilla, joten niitä ei voi suoraan laskea
yhteen. RRF yhdistää tulokset pelkkien sijoitusten perusteella:

```
pisteet = 1 / (60 + sijoitus vektorihaussa) + 1 / (60 + sijoitus tekstihaussa)
```

Pala, joka on ensimmäinen molemmissa, saa 1/61 + 1/61 = 0,0328. Pala, joka löytyy vain
toisesta, saa enintään 0,0164. Molemmissa hyvin sijoittuvat palat nousevat siis kärkeen, mutta
myös vain toisen haun löytämät palat pysyvät mukana. Vakio 60 on yleisesti käytetty oletusarvo,
joka tasoittaa kärkisijojen välisiä eroja.

### 4. Reranker

Edellisissä vaiheissa kysymys ja pala käsitellään erikseen: kummastakin lasketaan oma vektori
ja vektoreita verrataan. Reranker (cross-encoder) lukee kysymyksen ja palan yhdessä ja antaa
pisteen sille, kuinka hyvin pala vastaa kysymykseen. Se on selvästi tarkempi, mutta myös
paljon hitaampi, koska jokainen pala ajetaan erikseen raskaan mallin läpi.

Siksi reranker pisteyttää vain RRF:n 10 parasta ehdokasta. Malli on BAAI/bge-reranker-v2-m3
(samaa perhettä kuin embedding-malli, monikielinen) INT8-muodossa, ja se ajetaan paikallisesti
fastembed-kirjastolla ONNX Runtimen päällä. Yksi haku vie CPU:lla noin 2,6 sekuntia, josta
lähes kaikki on rerankerin työtä (ks. [MEASUREMENTS.md](MEASUREMENTS.md)).

### Esimerkki

Kysymys: "Kuinka nopeasti pitää ilmoittaa, jos läppäri varastetaan?"

1. **Vektorihaku** löytää tietoturvaohjeen sivun 2, jossa puhutaan "kadonneesta tai varastetusta
   laitteesta" ja tietoturvapoikkeaman ilmoittamisesta. Sanat ovat eri, mutta merkitys on sama.
2. **Tekstihaku** saa kyselyksi sanat "nopeasti", "ilmoittaa", "läppäri" ja "varastetaan" (sanat
   "kuinka", "pitää" ja "jos" ovat täytesanoja). Palassa sanat ovat muodossa "Ilmoita" ja
   "varastettu", joten tekstihaku ei löydä sitä. Ennen täytesanojen poistoa tekstihaku osui
   samaan palaan, mutta ainoa yhteinen sana oli "jos": oikeaan paikkaan väärästä syystä.
3. **RRF** pitää palan kärjessä vektorihaun ansiosta.
4. **Reranker** varmistaa järjestyksen lukemalla kysymyksen ja palan yhdessä.

Komento `uv run localrag search "..."` näyttää jokaisen osuman sijoituksen kummassakin haussa
(`vec`, `fts`), RRF-pisteet ja rerankerin pisteet, joten kunkin vaiheen vaikutuksen näkee
suoraan.

## Agentti ja MCP

Haku ei itse vastaa kysymyksiin: se palauttaa palat, ja kielimalli muodostaa vastauksen.
localrag tarjoaa haun agentille MCP-palvelimena (Model Context Protocol), jolloin esimerkiksi
Claude Desktop tai Claude Code voi käyttää sitä työkaluna. Työkaluja on kolme:

- `search_documents`: hybridihaku, palauttaa parhaat palat polkuineen ja otsikoineen
- `list_documents`: indeksoidut tiedostot
- `read_document`: koko tiedoston teksti (vain indeksoidut tiedostot)

Haku on agentille työkalu eikä automaattisesti kysymykseen liitettävä konteksti. Agentti voi
silloin hakea useaan kertaan eri sanoin, rajata haun kansioon ja lukea koko dokumentin, kun
yksittäiset palat eivät riitä. Esimerkiksi "tee yhteenveto kaikista sopimuksista" ei onnistu
pelkällä palahaulla, mutta onnistuu, kun agentti voi listata ja lukea tiedostoja.

## Keskeiset valinnat

| Valinta | Vaihtoehto | Miksi näin |
| --- | --- | --- |
| PostgreSQL + pgvector | erillinen vektorikanta (Qdrant, Weaviate) | Vektorit, tekstihaku ja metatiedot samassa kannassa ja samassa transaktiossa; yksi palvelu vähemmän |
| Embeddingit paikallisesti (Ollama, bge-m3) | OpenAI:n tai muu pilvipalvelun embedding-API | Dokumentit eivät lähde koneelta; bge-m3 toimii suomeksi. OpenAI on vaihtoehtona asetuksissa |
| Hybridihaku (vektori + teksti) | pelkkä vektorihaku | Vektorihaku on heikko tunnisteissa ja nimissä, tekstihaku merkityksessä |
| Täytesanojen poisto vain kyselystä | poisto myös indeksistä | Ei vaadi uudelleenindeksointia, ja vaikutuksen voi kytkeä pois mittausta varten |
| Reranker 10 ehdokkaalle | ei rerankeria, tai enemmän ehdokkaita | Mitattu: nosti palatason osumat 0,94 -> 1,00; 10 ehdokasta antoi saman tuloksen kuin 20 puolella ajalla |
| Haku agentin työkaluna (MCP) | konteksti liitetään aina kysymykseen | Agentti voi hakea useasti ja lukea kokonaisia dokumentteja |
| Python | TypeScript (esim. Vercel AI SDK) | Dokumenttien parsinnan ja paikallisten mallien kirjastot ovat Pythonissa kypsimpiä |

## Sanasto

- **Embedding**: tekstistä laskettu lukuvektori, joka kuvaa sen merkitystä. Samaa tarkoittavat
  tekstit saavat lähekkäiset vektorit.
- **Pala (chunk)**: dokumentin osa, joka indeksoidaan ja palautetaan haussa yhtenä yksikkönä.
- **Kosinietäisyys**: kahden vektorin suunnan ero; mitä pienempi, sitä samankaltaisempi merkitys.
- **HNSW**: indeksirakenne, jolla lähimmät vektorit löytyvät nopeasti käymättä läpi kaikkia.
  Tulos on likimääräinen mutta käytännössä lähes tarkka.
- **Tekstihaku (full-text search, FTS)**: sanoihin perustuva haku. Postgresissa `tsvector`
  (dokumentin sanat) ja `tsquery` (kyselyn sanat).
- **Täytesana (stop word)**: yleinen sana, joka ei kerro hakukohteesta mitään ("missä", "the").
- **RRF (Reciprocal Rank Fusion)**: tapa yhdistää kahden haun tulokset sijoitusten perusteella.
- **Reranker / cross-encoder**: malli, joka lukee kysymyksen ja palan yhdessä ja pisteyttää,
  kuinka hyvin pala vastaa kysymykseen.
- **MCP (Model Context Protocol)**: standardi, jolla kielimalliagentti käyttää ulkoisia työkaluja.
- **Hit@k ja MRR**: hakulaadun mittareita, selitetty tiedostossa [MEASUREMENTS.md](MEASUREMENTS.md).
