import hashlib
import os
import re
from pathlib import Path

import numpy as np
import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

EXAMPLES_DIR = Path(__file__).resolve().parents[1] / "examples"
DEFAULT_TEST_DATABASE_URL = "postgresql://localrag:localrag@localhost:5433/localrag_test"


@pytest.fixture(scope="session")
def test_database_url() -> str:
    """Erillinen testikanta, jotta testit eivät koske käyttäjän omaan indeksiin.

    Kanta luodaan tarvittaessa. Testit ohitetaan, jos Postgres ei ole käynnissä.
    """
    url = os.environ.get("LOCALRAG_TEST_DATABASE_URL", DEFAULT_TEST_DATABASE_URL)
    dbname = conninfo_to_dict(url).get("dbname", "")
    if not dbname.endswith("_test"):
        # Testit tyhjentävät kannan, joten vaaditaan selvästi testikannaksi nimetty kanta.
        pytest.fail(f"Testikannan nimen pitää päättyä '_test' (nyt: {dbname!r})")
    try:
        with psycopg.connect(make_conninfo(url, dbname="postgres"), autocommit=True) as conn:
            exists = conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (dbname,))
            if exists.fetchone() is None:
                conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(dbname)))
    except psycopg.OperationalError as e:
        pytest.skip(f"Postgres ei ole saatavilla ({e}). Käynnistä: scripts/services.sh start")
    return url


class BagOfWordsEmbedder:
    """Deterministinen testiembedder: sanojen hajautus vektoriin.

    Ei ymmärrä merkityksiä, mutta samoja sanoja sisältävät tekstit ovat lähellä toisiaan.
    Sopii putken ja täsmätermihakujen testaamiseen ilman Ollamaa.
    """

    model = "test-bag-of-words"

    def __init__(self, dim: int = 256):
        self.dim = dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors = []
        for text in texts:
            v = np.zeros(self.dim)
            for word in re.findall(r"\w+", text.lower()):
                v[int(hashlib.md5(word.encode()).hexdigest(), 16) % self.dim] += 1
            norm = np.linalg.norm(v)
            vectors.append((v / norm if norm else v).tolist())
        return vectors
