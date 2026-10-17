import pytest
from sqlalchemy.engine import make_url

from app import create_app
from app.config import ProductionConfig


@pytest.mark.parametrize('scheme', ['postgresql', 'postgresql+psycopg2'])
def test_production_uses_installed_postgres_driver(mocker, scheme):
    mocker.patch.object(ProductionConfig, 'SECRET_KEY', 'isolated-driver-test')
    mocker.patch.object(
        ProductionConfig, 'SQLALCHEMY_DATABASE_URI',
        f'{scheme}://test:test@localhost/test',
    )

    class StopBeforeConnection(Exception):
        pass

    def inspect_database_config(app):
        url = make_url(app.config['SQLALCHEMY_DATABASE_URI'])
        assert url.drivername == 'postgresql+psycopg2'
        assert url.get_dialect().import_dbapi().__name__ == 'psycopg2'
        raise StopBeforeConnection

    mocker.patch('app.db.init_app', side_effect=inspect_database_config)
    with pytest.raises(StopBeforeConnection):
        create_app('production')
