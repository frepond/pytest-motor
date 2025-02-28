"""A pytest plugin which helps test applications using Motor."""
import asyncio
import socket
import tempfile
from pathlib import Path
from typing import AsyncIterator, Iterator, List

import pytest
import pytest_asyncio
from _pytest.config import Config as PytestConfig
from motor.motor_asyncio import AsyncIOMotorClient

from pytest_motor.mongod_binary import MongodBinary


def _event_loop() -> Iterator[asyncio.AbstractEventLoop]:
    """Yield an event loop.

    This is necessary because pytest-asyncio needs an event loop with a with an equal or higher
    pytest fixture scope as any of the async fixtures. And remember, pytest-asynio is what allows us
    to have async pytest fixtures.
    """
    loop = asyncio.get_event_loop()
    yield loop
    loop.close()


event_loop = pytest.fixture(fixture_function=_event_loop, scope='session', name="event_loop")


@pytest_asyncio.fixture(scope='session')
async def root_directory(pytestconfig: PytestConfig) -> Path:
    """Return the root path of pytest."""
    return pytestconfig.rootpath


@pytest_asyncio.fixture(scope='session')
async def mongod_binary(root_directory: Path) -> Path:
    # pylint: disable=redefined-outer-name
    """Return a path to a mongod binary."""
    destination: Path = root_directory / '.mongod'
    binary = MongodBinary(destination=destination)
    if not binary.exists:
        await binary.download_and_unpack()
    return binary.path


@pytest.fixture(scope='session')
def new_port() -> int:
    """Return an unused port for mongod to run on."""
    port: int = 27017
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as opened_socket:
        opened_socket.bind(("127.0.0.1", 0))  # system will automaticly assign port
        port = opened_socket.getsockname()[1]
    return port


@pytest.fixture(scope="session")
def database_path() -> Iterator[str]:
    """Yield a database path for a mongod process to store data."""
    with tempfile.TemporaryDirectory() as tmpdirname:
        yield tmpdirname


@pytest_asyncio.fixture(scope='session')
async def mongod_socket(new_port: int, database_path: Path,
                        mongod_binary: Path) -> AsyncIterator[str]:
    # pylint: disable=redefined-outer-name
    """Yield a mongod."""
    # yapf: disable
    arguments: List[str] = [
        str(mongod_binary),
        '--port', str(new_port),
        '--storageEngine', 'ephemeralForTest',
        '--logpath', '/dev/null',
        '--dbpath', str(database_path)
    ]
    # yapf: enable

    mongod = await asyncio.create_subprocess_exec(*arguments)

    # mongodb binds to localhost by default
    yield f'localhost:{new_port}'

    try:
        mongod.terminate()
    except ProcessLookupError:  # pragma: no cover
        pass


@pytest.fixture(scope="session")
def __motor_client(mongod_socket: str) -> AsyncIterator[AsyncIOMotorClient]:
    # pylint: disable=redefined-outer-name
    """Yield a Motor client."""
    connection_string = f'mongodb://{mongod_socket}'

    motor_client_: AsyncIOMotorClient = \
        AsyncIOMotorClient(connection_string, serverSelectionTimeoutMS=3000)

    yield motor_client_

    motor_client_.close()


@pytest_asyncio.fixture(scope='function')
async def motor_client(__motor_client: AsyncIterator[AsyncIOMotorClient]) -> AsyncIterator[AsyncIOMotorClient]:
    # pylint: disable=redefined-outer-name
    """Yield a Motor client."""
    yield __motor_client

    dbs = await __motor_client.list_database_names()

    for db in dbs:
        if db not in ["config", "admin", "local"]:
            await __motor_client.drop_database(db)
