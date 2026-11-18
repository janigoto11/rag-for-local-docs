"""Tekstihaun kyselystä poistettavat täytesanat (suomi ja englanti).

Tekstihaku yhdistää kyselyn sanat OR-ehdolla, joten kysymyssanat ja muut täytesanat
("missä", "saa", "how", "many") tuovat tuloksiin dokumentteja, joissa sattuu olemaan
sama täytesana. Sanat poistetaan vain kyselystä; dokumenttien indeksiin ne jäävät.

Lista on tarkoituksella maltillinen: mukana on vain sanoja, jotka eivät juuri koskaan ole
haun varsinainen kohde. Sisältösanoja (esim. "mennessä", "aika") ei poisteta.
"""

FINNISH = """
mikä mitä mitkä minkä missä mistä mihin millä miltä mille mikään mitään
kuka ketkä kenen ketä kenet kenelle keneltä kenellä
miksi miten kuinka milloin millainen millaiset millaista millaisia
paljonko montako monta kumpi kumman kumpaa
onko ovatko oliko olivatko voiko voinko saako saanko pitääkö täytyykö tarvitseeko
on ovat oli olivat olla ole olen olet olemme olette ollut olleet
ei en et emme ette eivät eikä
saa saan saat saamme saatte saavat
voi voin voit voimme voitte voivat
pitää pitäisi täytyy tarvitsee tarvitaan tulee
ja tai sekä että jos kun kuin mutta vai myös vain jo nyt sitten vielä siis
se ne sen sitä siitä siihen sillä siinä sille niitä niiden niistä niihin
tämä tämän tätä tästä tähän tällä tässä nämä näiden näitä
tuo tuon tuota nuo
joka jotka jonka joita joiden jossa josta johon jolla
minä sinä hän me te he minun sinun hänen meidän teidän heidän
minua sinua häntä meitä teitä heitä minulle sinulle hänelle meille teille heille
"""

ENGLISH = """
a an the and or but if then than so as
of to in on at by for with from about into over under
is are was were be been being am do does did done
can could should would will shall may might must
what which who whom whose when where why how
many much there here this that these those it its
i you he she we they me him her us them my your his our their
not no any some all
"""

STOPWORDS: tuple[str, ...] = tuple(sorted(set(FINNISH.split()) | set(ENGLISH.split())))
