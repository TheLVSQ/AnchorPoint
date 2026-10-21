"""Copy SmsMessage/SmsRecipient, PhoneBlast/PhoneCall and stand-alone CommunicationLog rows
into Communication/Delivery. The legacy tables are dropped in the next migration."""

from django.db import migrations

MESSAGE_STATUS = {
    "scheduled": "scheduled",
    "processing": "sending",
    "completed": "completed",
    "failed": "failed",
}
CALL_STATUS = {"completed": "answered", "no_answer": "no_answer", "failed": "failed"}


def _keep_timestamps(model, pk, created_at, updated_at=None):
    fields = {"created_at": created_at}
    if updated_at is not None:
        fields["updated_at"] = updated_at
    model.objects.filter(pk=pk).update(**fields)


def copy_forward(apps, schema_editor):
    SmsMessage = apps.get_model("messaging", "SmsMessage")
    PhoneBlast = apps.get_model("messaging", "PhoneBlast")
    CommunicationLog = apps.get_model("messaging", "CommunicationLog")
    Communication = apps.get_model("messaging", "Communication")
    Delivery = apps.get_model("messaging", "Delivery")

    for sms in SmsMessage.objects.all():
        comm = Communication.objects.create(
            channel="sms",
            kind="broadcast",
            status=MESSAGE_STATUS.get(sms.status, "failed"),
            created_by_id=sms.created_by_id,
            body=sms.body,
            target_type=sms.target_type,
            person_id=sms.person_id,
            group_id=sms.group_id,
            scheduled_for=sms.scheduled_for,
            started_at=sms.sent_at,
            completed_at=sms.sent_at,
        )
        _keep_timestamps(Communication, comm.pk, sms.created_at, sms.updated_at)
        for r in sms.recipients.all():
            d = Delivery.objects.create(
                communication=comm,
                person_id=r.person_id,
                address=r.phone_number,
                status=r.status,  # pending / sent / failed map 1:1
                provider_id=r.twilio_sid,
                error_message=r.error_message,
                sent_at=r.sent_at,
            )
            _keep_timestamps(Delivery, d.pk, r.sent_at or sms.created_at)

    for blast in PhoneBlast.objects.all():
        comm = Communication.objects.create(
            channel="voice",
            kind="broadcast",
            status=MESSAGE_STATUS.get(blast.status, "failed"),
            created_by_id=blast.created_by_id,
            title=blast.title,
            audio_file=blast.audio_file.name if blast.audio_file else "",
            notes=blast.notes,
            target_type="group",
            group_id=blast.group_id,
            scheduled_for=blast.scheduled_for,
            started_at=blast.started_at,
            completed_at=blast.completed_at,
        )
        _keep_timestamps(Communication, comm.pk, blast.created_at, blast.updated_at)
        for call in blast.calls.all():
            if call.status == "pending":
                status = "sent" if call.call_sid else "pending"
            else:
                status = CALL_STATUS.get(call.status, "failed")
            d = Delivery.objects.create(
                communication=comm,
                person_id=call.person_id,
                address=call.phone_number,
                status=status,
                provider_id=call.call_sid,
                error_message=call.error_message,
                sent_at=call.started_at,
                completed_at=call.completed_at,
            )
            _keep_timestamps(Delivery, d.pk, call.started_at or blast.created_at)

    # Logs tied to an SMS/blast are already represented by its Deliveries. Stand-alone
    # logs (check-in pickup-code texts) become transactional Communications.
    standalone = CommunicationLog.objects.filter(
        sms_message__isnull=True, phone_blast__isnull=True
    )
    for log in standalone:
        meta = log.metadata or {}
        comm = Communication.objects.create(
            channel="sms" if log.communication_type == "sms" else "voice",
            kind="transactional",
            status="completed",
            created_by_id=log.recorded_by_id,
            title=log.summary,
            body=log.detail,
            metadata={k: v for k, v in meta.items() if k not in ("phone_number", "twilio_sid")},
            started_at=log.created_at,
            completed_at=log.created_at,
        )
        _keep_timestamps(Communication, comm.pk, log.created_at, log.created_at)
        d = Delivery.objects.create(
            communication=comm,
            person_id=log.person_id,
            address=meta.get("phone_number", ""),
            status="sent",
            provider_id=meta.get("twilio_sid", ""),
            sent_at=log.created_at,
        )
        _keep_timestamps(Delivery, d.pk, log.created_at)


class Migration(migrations.Migration):
    dependencies = [
        ("messaging", "0002_communication_delivery"),
    ]

    operations = [
        migrations.RunPython(copy_forward, migrations.RunPython.noop),
    ]
