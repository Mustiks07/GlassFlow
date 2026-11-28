from glassflow.contracts.crm import Reminder
from glassflow.core.models import uid
from glassflow.core.uow import write_transaction
from glassflow.modules.crm import service


class PlatformCrmPort:
    """C3's requested consumer port, calling the same CRM service as HTTP."""

    def __init__(self, factory, services):
        self.factory, self.services = factory, services

    def rank(self, request):
        with self.factory() as session:
            return service.rank(session, request.dataset_id, request.policy)

    def draft_reminder(self, request):
        with write_transaction(self.factory) as session:
            # Canonical active-period uniqueness also covers repeated AI tool invocations.
            return Reminder.model_validate(service.create_reminder(session, request, self.services, uid()))
