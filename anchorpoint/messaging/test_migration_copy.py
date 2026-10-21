"""0003 copies legacy SMS / phone-blast / log rows into Communication + Delivery."""
from datetime import timedelta

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase
from django.utils import timezone


class CopyLegacyCommunicationsTests(TransactionTestCase):
    before = [("messaging", "0001_initial")]
    after = [("messaging", "0004_drop_legacy_tables")]

    def setUp(self):
        self.addCleanup(self._migrate_to_latest)  # even if setUp fails midway
        executor = MigrationExecutor(connection)
        executor.migrate(self.before)
        # Every other app at its latest state (that's what the DB holds), messaging at 0001.
        others = [n for n in executor.loader.graph.leaf_nodes() if n[0] != "messaging"]
        old = executor.loader.project_state(others + self.before).apps

        User = old.get_model("auth", "User")
        Person = old.get_model("people", "Person")
        SmsMessage = old.get_model("messaging", "SmsMessage")
        SmsRecipient = old.get_model("messaging", "SmsRecipient")
        PhoneBlast = old.get_model("messaging", "PhoneBlast")
        PhoneCall = old.get_model("messaging", "PhoneCall")
        CommunicationLog = old.get_model("messaging", "CommunicationLog")

        user = User.objects.create(username="legacy")
        self.person_pk = Person.objects.create(
            first_name="Old", last_name="Row", phone="+15550001", normalized_phone="15550001"
        ).pk
        self.created = timezone.now() - timedelta(days=30)

        sms = SmsMessage.objects.create(created_by=user, body="Legacy text", status="completed",
                                        target_type="person", person_id=self.person_pk)
        SmsMessage.objects.filter(pk=sms.pk).update(created_at=self.created)
        SmsRecipient.objects.create(message=sms, person_id=self.person_pk, phone_number="+15550001",
                                    status="sent", twilio_sid="SM1")
        CommunicationLog.objects.create(person_id=self.person_pk, communication_type="sms",
                                        summary="SMS sent", sms_message=sms)

        blast = PhoneBlast.objects.create(created_by=user, title="Legacy blast", status="processing",
                                          audio_file="communications/phone_blasts/x.mp3")
        PhoneCall.objects.create(blast=blast, person_id=self.person_pk, phone_number="+15550001",
                                 call_sid="CA1", status="pending")
        PhoneCall.objects.create(blast=blast, phone_number="+15550002", call_sid="CA2",
                                 status="completed")

        CommunicationLog.objects.create(
            person_id=self.person_pk, communication_type="sms", summary="Check-in pickup code",
            detail="Kids checked in. Pickup code: ABCD",
            metadata={"phone_number": "+15550001", "twilio_sid": "SM9", "security_code": "ABCD"},
        )

        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(self.after)
        self.apps = executor.loader.project_state(self.after).apps

    def _migrate_to_latest(self):
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(executor.loader.graph.leaf_nodes())

    def test_rows_are_copied(self):
        Communication = self.apps.get_model("messaging", "Communication")
        Delivery = self.apps.get_model("messaging", "Delivery")

        sms = Communication.objects.get(channel="sms", kind="broadcast")
        self.assertEqual((sms.body, sms.status), ("Legacy text", "completed"))
        self.assertEqual(sms.created_at, self.created)
        d = Delivery.objects.get(communication=sms)
        self.assertEqual((d.person_id, d.status, d.provider_id), (self.person_pk, "sent", "SM1"))

        blast = Communication.objects.get(channel="voice")
        self.assertEqual((blast.title, blast.status, blast.audio_file.name),
                         ("Legacy blast", "sending", "communications/phone_blasts/x.mp3"))
        statuses = dict(Delivery.objects.filter(communication=blast).values_list("provider_id", "status"))
        self.assertEqual(statuses, {"CA1": "sent", "CA2": "answered"})

        pickup = Communication.objects.get(kind="transactional")
        self.assertEqual(pickup.title, "Check-in pickup code")
        self.assertEqual(pickup.metadata, {"security_code": "ABCD"})
        d = Delivery.objects.get(communication=pickup)
        self.assertEqual((d.address, d.provider_id, d.status), ("+15550001", "SM9", "sent"))

        # The log tied to the SMS didn't become a second Communication.
        self.assertEqual(Communication.objects.count(), 3)
