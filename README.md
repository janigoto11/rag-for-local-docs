# localrag

Paikallinen RAG hakemiston dokumenteille. Tiedostot parsitaan, pilkotaan rakenteen mukaan,
embeddataan (oletuksena paikallisesti Ollamalla) ja tallennetaan PostgreSQL + pgvector
-kantaan. Haku yhdistää vektorihaun ja tekstihaun, ja tulokset järjestetään lopuksi
reranker-mallilla. LLM-agentit kyselevät indeksiä MCP-palvelimen kautta.

Dokumentit eivät oletusasetuksilla lähde koneelta: sekä embeddingit että tietokanta ovat
paikallisia. Vain agentti (esim. Claude) näkee ne palat, jotka se haulla noutaa.

Dokumentaatio:

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md): miten indeksointi ja haku toimivat ja miksi
- [docs/MEASUREMENTS.md](docs/MEASUREMENTS.md): hakulaadun mittaukset ja niiden perusteella tehdyt päätökset
- [docs/ROADMAP.md](docs/ROADMAP.md): mitä on tehty, tunnetut rajoitteet ja seuraavat askeleet

## Vaatimukset

- Python 3.11+ ja [uv](https://docs.astral.sh/uv/)
- Docker (PostgreSQL + pgvector)
- [Ollama](https://ollama.com/) paikallisille embeddingeille, tai OpenAI API -avain

## Asennus

```bash
cp .env.example .env
uv sync                       # lisää --extra docling, jos tarvitset docx/pptx/xlsx/html-tuen
scripts/services.sh start     # tietokanta ja Ollama, lataa embedding-mallin tarvittaessa
```

### Palveluiden käynnistys ja pysäytys

localrag tarvitsee kaksi taustapalvelua: PostgreSQL + pgvector -kannan (Docker, portti 5433)
ja Ollaman (portti 11434), joka laskee embeddingit. Molempia hallitaan samalla skriptillä:

```bash
scripts/services.sh start     # käynnistää kannan ja Ollaman, lataa mallin (oletus bge-m3)
scripts/services.sh status    # näyttää palveluiden ja mallin tilan
scripts/services.sh stop      # pysäyttää palvelut
```

Ollama ajetaan natiivisti eikä Dockerissa, koska macOS:llä Docker ei pääse käyttämään GPU:ta.
Jos Ollama on jo käynnissä (esimerkiksi Ollama-sovellus), skripti käyttää sitä eikä sammuta
sitä `stop`-komennolla. Itse käynnistämänsä Ollaman loki on tiedostossa `.localrag/ollama.log`.
Tietokannan data säilyy Docker-volyymissa pysäytyksen yli.

Jos palvelu ei ole käynnissä, `localrag` kertoo sen ja neuvoo käynnistämään palvelut.

## Pikakokeilu esimerkkidokumenteilla

Hakemistossa `examples/docs` on kuvitteellisen Lumikko Demo Oy:n dokumentteja (md, txt ja PDF):
matkustusohje, tietoturvaohje, kaksi versiota lomakäytännöstä, palvelusopimus, kokousmuistio,
perehdytyksen UKK ja englanninkielinen tuotekuvaus. Yritys, henkilöt ja tiedot ovat keksittyjä.

Demo kannattaa ajaa omaan tietokantaansa, jotta esimerkit eivät sekoitu omiin dokumentteihisi:

```bash
scripts/services.sh start
scripts/services.sh createdb localrag_demo
export LOCALRAG_DATABASE_URL=postgresql://localrag:localrag@localhost:5433/localrag_demo

uv run localrag index examples/docs
uv run localrag search "kuinka nopeasti pitää ilmoittaa, jos läppäri varastetaan"
uv run localrag search "What is the guaranteed availability in the Virvatuli contract?"
uv run localrag search "Montako API-kutsua minuutissa Revontuli sallii?"
uv run localrag eval examples/questions.yaml -k 3
```

`eval` mittaa haun laatua kahdella tasolla. Sarake `dok` kertoo, monennellako sijalla oikea
dokumentti on. Sarake `pala` kertoo, monennellako sijalla on pala, joka sisältää varsinaisen
vastauksen (kysymyksen `expected_text`). Agentti saa haulta paloja, joten palataso kertoo
paremmin, löytyykö vastaus oikeasti.

Yksittäisen parannuksen vaikutuksen näkee ajamalla evalin ilman sitä ja vertaamalla tuloksia:

```bash
LOCALRAG_RERANKER=none uv run localrag eval examples/questions.yaml -k 3
LOCALRAG_FTS_STOPWORDS=false uv run localrag eval examples/questions.yaml -k 3
```

Kokeile ainakin näitä:

- **Eri sanoin muotoiltu kysymys:** "kuinka nopeasti pitää ilmoittaa, jos läppäri varastetaan"
  pitäisi löytää tietoturvaohjeen sivu 2, vaikka dokumentissa puhutaan tietoturvapoikkeamasta.
- **Kieltenvälinen haku:** suomenkielinen kysymys löytää englanninkielisen tuotekuvauksen,
  ja englanninkielinen kysymys suomenkielisen sopimuksen.
- **Versiot:** "Mihin mennessä kesälomatoiveet pitää jättää?" löytää sekä vuoden 2025 että
  2026 lomakäytännön. Haku ei tiedä, kumpi on voimassa. Agentti voi päätellä sen vain, jos
  dokumentti sen kertoo (2026-versiossa lukee, että se korvaa edellisen).
- **Tunnettu rajoite:** pelkkä tekstihaku ei ymmärrä suomen taivutusta. Sopimuksessa lukee
  "irtisanomisajan", joten hakusana "irtisanomisaika" voi löytää sopimuksen vain vektorihaun
  kautta.

MCP-palvelimen kautta Claudelta voi kysyä esimerkiksi: "Mitä Lumikon ohjausryhmä päätti
lokakuussa, ja miten se vaikuttaa Virvatulin sopimukseen?" Vastaus edellyttää tietojen
yhdistämistä kahdesta dokumentista.

PDF:t generoidaan lähteistä `examples/pdf-sources/*.md` komennolla
`uv run python scripts/generate_example_pdfs.py`. Generoidut tiedostot ovat versionhallinnassa,
joten demo ei vaadi generointia.

## Miten haku toimii

1. **Vektorihaku** löytää palat, jotka tarkoittavat samaa kuin kysymys, vaikka sanat olisivat eri.
2. **Tekstihaku** löytää palat, joissa on kysymyksen sanoja; se on tarkka nimissä ja tunnisteissa.
3. **Yhdistäminen** (Reciprocal Rank Fusion) nostaa kärkeen palat, jotka sijoittuvat hyvin
   kummassakin haussa.
4. **Reranker** lukee kysymyksen ja 10 parasta palaa yhdessä ja järjestää ne uudelleen.

Tarkempi kuvaus perusteluineen: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

Reranker on valinnainen (`.env.example`:ssä päällä) ja haun hitain vaihe: CPU:lla noin
2,6 sekuntia haulta. Malli (noin 0,6 Gt) ladataan hakemistoon `~/.cache/localrag/models`
komennolla `scripts/services.sh start` tai `uv run localrag prepare`. Vaiheiden kestot näkee
valinnalla `uv run localrag search "..." --timing`.

## Käyttö

```bash
uv run localrag index ~/Documents/jokin-kansio     # voi ajaa uudelleen; vain muutokset käsitellään
uv run localrag search "mikä on irtisanomisaika"
uv run localrag search "määräaika" --prefix ~/Documents/jokin-kansio/sopimukset --full
uv run localrag stats
uv run localrag eval evals/questions.yaml -k 5
```

Indeksiä voi kysellä jo indeksoinnin aikana. Tulokset sisältävät silloin vain valmiiksi
käsitellyt tiedostot.

Embedding-mallin vaihto: päivitä `.env`, aja `uv run localrag reset -y` ja indeksoi uudelleen.

### Tuetut tiedostotyypit

| Tyyppi | Parseri |
| --- | --- |
| Markdown, teksti, lähdekoodi, CSV, JSON, YAML ym. | luetaan sellaisenaan |
| PDF | pypdf (sivukohtaiset otsikot), tai docling jos asennettu |
| docx, pptx, xlsx, html | docling (`uv sync --extra docling`) |

Piilotiedostot ja -hakemistot sekä tyypilliset build- ja riippuvuushakemistot
(`node_modules`, `dist`, `venv` ym.) ohitetaan.

## Käyttö Claude Desktopista ja Claude Codesta (MCP)

Korvaa `/polku/rag-for-local-docs` repositorion sijainnilla.

Claude Desktop, `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "local-docs": {
      "command": "uv",
      "args": ["run", "--directory", "/polku/rag-for-local-docs", "localrag-mcp"]
    }
  }
}
```

Claude Code:

```bash
claude mcp add local-docs -- uv run --directory /polku/rag-for-local-docs localrag-mcp
```

Työkalut:

- `search_documents(query, path_prefix?, limit?)` - hybridihaku, palauttaa osuvimmat palat
- `list_documents(path_prefix?)` - indeksoidut tiedostot
- `read_document(path, offset?, max_chars?)` - koko tiedoston teksti (vain indeksoidut tiedostot)

## Konfiguraatio

Asetukset luetaan `.env`-tiedostosta tai ympäristömuuttujista (etuliite `LOCALRAG_`).
Kaikki asetukset oletusarvoineen löytyvät tiedostosta `src/localrag/config.py`.

| Muuttuja | Oletus | Kuvaus |
| --- | --- | --- |
| `LOCALRAG_DATABASE_URL` | `postgresql://localrag:localrag@localhost:5433/localrag` | tietokantayhteys |
| `LOCALRAG_EMBEDDING_PROVIDER` | `ollama` | `ollama` tai `openai` |
| `LOCALRAG_EMBEDDING_MODEL` | `bge-m3` | embedding-malli |
| `LOCALRAG_EMBEDDING_DIM` | `1024` | mallin vektorin ulottuvuus |
| `LOCALRAG_CHUNK_TARGET_TOKENS` | `500` | palan tavoitekoko |
| `LOCALRAG_CHUNK_OVERLAP_TOKENS` | `60` | peräkkäisten palojen päällekkäisyys |
| `LOCALRAG_FTS_STOPWORDS` | `true` | poistetaanko täytesanat tekstihaun kyselystä |
| `LOCALRAG_RERANKER` | `none` | `fastembed` ottaa rerankerin käyttöön (`.env.example`:ssä päällä) |
| `LOCALRAG_RERANK_MODEL` | `BAAI/bge-reranker-v2-m3-int8` | reranker-malli; täysi tarkkuus: `BAAI/bge-reranker-v2-m3` |
| `LOCALRAG_RERANK_CANDIDATES` | `10` | montako ehdokasta reranker pisteyttää; aika kasvaa suoraan tämän mukana |
| `LOCALRAG_MODEL_CACHE_DIR` | `~/.cache/localrag/models` | ladattujen mallien hakemisto |

## Hakemistorakenne

```
docker-compose.yml        Postgres 17 + pgvector
src/localrag/
  config.py               asetukset .env-tiedostosta (LOCALRAG_*)
  db.py                   yhteys, skeema (vektorin dimensio konfiguraatiosta), reset
  parsing.py              teksti/markdown/koodi, PDF (pypdf), docx/pptx/xlsx/html (docling)
  chunking.py             otsikoiden mukaiset osiot -> kappaleiden pakkaus päällekkäisyydellä
  embeddings.py           Ollama- ja OpenAI-embedderit
  indexer.py              inkrementaalinen skannaus: mtime/koko, sha256, poistot
  search.py               hybridihaku RRF:llä
  mcp_server.py           MCP-työkalut agenteille
  evaluation.py           osumaosuus ja MRR tiedostosta evals/questions.yaml
  cli.py                  `localrag`-komento
tests/                    yksikkö-, integraatio- ja e2e-testit
docs/                     arkkitehtuuri, mittaukset ja tiekartta
examples/docs/            demokorpus (kuvitteellinen Lumikko Demo Oy)
examples/pdf-sources/     demon PDF-tiedostojen markdown-lähteet
examples/questions.yaml   demokorpuksen eval-kysymykset
scripts/                  palveluiden hallinta, testien ajo ja PDF-generointi
evals/                    omien dokumenttien eval-kysymysten esimerkki
```

## Kehitys

```bash
scripts/test.sh               # yksikkö- ja integraatiotestit
scripts/test.sh e2e           # laatutesti oikealla embedding-mallilla
uv run ruff check . && uv run ruff format .
```

`scripts/test.sh` käynnistää testien tarvitsemat palvelut ja pysäyttää lopuksi ne, jotka eivät
olleet käynnissä ennen ajoa. Lisäparametrit välitetään pytestille (`scripts/test.sh -k mcp`).
Jos palvelut ovat jo käynnissä, testit voi ajaa myös suoraan: `uv run pytest` ja
`uv run pytest -m e2e -s`.

Testit:

- **Yksikkötestit** eivät tarvitse mitään ulkoista. `tests/test_chunking.py` testaa
  pilkkomisen. `tests/test_examples.py` varmistaa, että jokaisen eval-kysymyksen odotettu
  teksti on kokonaisena jossain demokorpuksen palassa ja vain oikeissa tiedostoissa.
- **Integraatiotestit** (`tests/test_integration.py`) indeksoivat demokorpuksen oikeaan
  Postgres + pgvector -kantaan deterministisellä testiembedderillä. Ne testaavat indeksoinnin,
  inkrementaalisuuden, poistot, tekstihaun ja sen täytesanasuodatuksen, polkurajauksen ja
  MCP-työkalut. Testit ohitetaan,
  jos tietokanta ei ole käynnissä.
- **E2E-laatutesti** (`tests/test_e2e_quality.py`) käyttää `.env`-tiedoston embedding-mallia,
  ajaa `examples/questions.yaml`-kysymykset ja vaatii, että vähintään 90 % niistä löytää
  oikean dokumentin ja vähintään 80 % vastauksen sisältävän palan kolmen parhaan joukosta.
  Rajat ovat lattioita, joita nostetaan haun parantuessa. Testi ohitetaan, jos malli ei ole
  käytettävissä.

Testit käyttävät erillistä kantaa `localrag_test` (luodaan tarvittaessa) ja tyhjentävät sen
joka ajolla. Kannan voi vaihtaa muuttujalla `LOCALRAG_TEST_DATABASE_URL`; nimen pitää päättyä
`_test`, ettei oma indeksi tyhjene vahingossa.

## Tekotapa

Projekti on toteutettu AI-avusteisesti: koodi, testit ja dokumentaatio on kirjoitettu pääosin
yhdessä Clauden (Anthropic) kanssa. Tavoitteet, rajaukset ja jatkosuunta on päätetty itse, ja
hakulaatuun vaikuttavat muutokset on mitattu omalla koneella ennen käyttöönottoa. Mittaukset ja
niiden perusteella tehdyt päätökset on kirjattu tiedostoon
[docs/MEASUREMENTS.md](docs/MEASUREMENTS.md).

## Lisenssi

[MIT](LICENSE)
