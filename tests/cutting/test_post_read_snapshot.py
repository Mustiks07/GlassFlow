import pytest

from glassflow.contracts.cutting import RemnantUpdate
from glassflow.modules.cutting.service import CuttingService
from glassflow.modules.cutting.uow import read_session, write_transaction

from .conftest import make_snapshot, register


def prepared(app):
    register(app, 'read-snapshot', make_snapshot([
        ('first', 'clear-4', 100, 100, False), ('second', 'clear-4', 100, 100, False)], []))


def test_interleaved_writer_does_not_mix_read_projection_snapshots(app_client):
    app, _ = app_client
    prepared(app)
    with read_session(app.state.session_factory) as reader:
        service = CuttingService(reader)
        assert service.get_remnant('read-snapshot', 'first').version == 0
        with write_transaction(app.state.session_factory) as writer:
            CuttingService(writer).update_remnant('second', RemnantUpdate(dataset_id='read-snapshot',
                expected_version=0, location_raw='Updated location'))
        # second was not in the identity map: this assertion requires a real
        # SQLite snapshot, rather than an ORM cache hiding mixed SELECTs.
        second = service.get_remnant('read-snapshot', 'second')
        assert second.version == 0 and second.location_raw != 'Updated location'
        assert service.inventory_token('read-snapshot') == '2:0'
    with read_session(app.state.session_factory) as reader:
        assert CuttingService(reader).get_remnant('read-snapshot', 'second').version == 1


def test_borrowed_write_transaction_remains_owned_and_rolls_back(app_client):
    app, _ = app_client
    prepared(app)
    with pytest.raises(RuntimeError, match='outer rollback'):
        with write_transaction(app.state.session_factory) as writer:
            CuttingService(writer).update_remnant('first', RemnantUpdate(dataset_id='read-snapshot',
                expected_version=0, location_raw='Uncommitted'))
            with read_session(writer) as reader:
                assert reader is writer
                assert CuttingService(reader).get_remnant('read-snapshot', 'first').version == 1
            assert writer.connection().connection.driver_connection.in_transaction
            CuttingService(writer).update_remnant('second', RemnantUpdate(dataset_id='read-snapshot',
                expected_version=0, location_raw='Also uncommitted'))
            raise RuntimeError('outer rollback')
    with read_session(app.state.session_factory) as reader:
        assert CuttingService(reader).inventory_token('read-snapshot') == '2:0'
