from urllib.parse import urlparse
import psycopg2


def connect(url: str = None,
            host: str = None,
            port: int = None,
            database: str = None,
            username: str = None,
            password: str = None
            ) -> psycopg2.extensions.connection:
    if url is not None:
        params = urlparse(url)
        host = params.hostname
        port = params.port
        database = params.path[1:]
        username = params.username
        password = params.password

    return psycopg2.connect(
        database=database,
        user=username,
        password=password,
        host=host,
        port=port
    )
