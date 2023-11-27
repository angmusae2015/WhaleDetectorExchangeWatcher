from urllib.parse import urlparse
import psycopg2


def connect(url: str) -> psycopg2.extensions.connection:
    params = urlparse(url)

    username = params.username
    password = params.password
    database = params.path[1:]
    hostname = params.hostname
    port = params.port

    return psycopg2.connect(
        database = database,
        user = username,
        password = password,
        host = hostname,
        port = port
    )