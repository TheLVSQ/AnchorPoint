import json
from datetime import time, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from checkin.models import CheckIn, CheckInSession, PrintAgent, PrintJob, hash_agent_token
from checkin.services.print_queue import enqueue_checkin_labels
from core.models import UserProfile
from people.models import Person


def _session():
    now = timezone.localtime()
    return CheckInSession.objects.create(
        name="Sunday",
        date=timezone.localdate(),
        checkin_opens=time(0, 0),
        checkin_closes=time(23, 50),
        event_starts=time(0, 5),
        event_ends=time(23, 55),
        is_active=True,
    )


class PairingTests(TestCase):
    def test_pair_with_valid_code_returns_token(self):
        agent = PrintAgent.objects.create(name="Desk")
        code = agent.issue_pairing_code()
        resp = self.client.post(
            reverse("checkin:print_pair"),
            data=json.dumps({"pairing_code": code}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        token = resp.json()["token"]
        agent.refresh_from_db()
        self.assertTrue(agent.is_paired)
        self.assertEqual(agent.token_hash, hash_agent_token(token))
        self.assertEqual(agent.pairing_code, "")

    def test_bad_code_rejected(self):
        resp = self.client.post(
            reverse("checkin:print_pair"),
            data=json.dumps({"pairing_code": "NOPE1234"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_expired_code_rejected(self):
        agent = PrintAgent.objects.create(name="Desk")
        agent.issue_pairing_code()
        agent.pairing_expires_at = timezone.now() - timedelta(minutes=1)
        agent.save(update_fields=["pairing_expires_at"])
        resp = self.client.post(
            reverse("checkin:print_pair"),
            data=json.dumps({"pairing_code": agent.pairing_code}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)


class JobApiTests(TestCase):
    def setUp(self):
        self.agent = PrintAgent.objects.create(name="Desk")
        self.token = self.agent.complete_pairing()
        self.auth = {"HTTP_AUTHORIZATION": f"Bearer {self.token}"}

    def _job(self, status=PrintJob.PENDING):
        return PrintJob.objects.create(
            agent=self.agent, image_data=b"\x89PNG-fake", kind="child",
            description="Kid", status=status,
        )

    def test_next_requires_token(self):
        self.assertEqual(self.client.get(reverse("checkin:print_next")).status_code, 401)

    def test_next_claims_pending_job(self):
        job = self._job()
        resp = self.client.get(reverse("checkin:print_next"), **self.auth)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["id"], job.pk)
        job.refresh_from_db()
        self.assertEqual(job.status, PrintJob.CLAIMED)
        self.assertEqual(job.attempts, 1)

    def test_next_empty_returns_204(self):
        self.assertEqual(self.client.get(reverse("checkin:print_next"), **self.auth).status_code, 204)

    def test_image_returns_png_bytes(self):
        job = self._job()
        resp = self.client.get(reverse("checkin:print_job_image", args=[job.pk]), **self.auth)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "image/png")
        self.assertEqual(resp.content, b"\x89PNG-fake")

    def test_ack_printed(self):
        job = self._job(status=PrintJob.CLAIMED)
        self.client.post(
            reverse("checkin:print_ack", args=[job.pk]),
            data=json.dumps({"status": "printed"}),
            content_type="application/json", **self.auth,
        )
        job.refresh_from_db()
        self.assertEqual(job.status, PrintJob.PRINTED)
        self.assertIsNotNone(job.printed_at)

    def test_ack_failed_records_error(self):
        job = self._job(status=PrintJob.CLAIMED)
        self.client.post(
            reverse("checkin:print_ack", args=[job.pk]),
            data=json.dumps({"status": "failed", "error": "out of paper"}),
            content_type="application/json", **self.auth,
        )
        job.refresh_from_db()
        self.assertEqual(job.status, PrintJob.FAILED)
        self.assertIn("out of paper", job.error_message)

    def test_jobs_are_scoped_to_their_agent(self):
        other = PrintAgent.objects.create(name="Other")
        other_token = other.complete_pairing()
        job = self._job()
        resp = self.client.get(
            reverse("checkin:print_job_image", args=[job.pk]),
            HTTP_AUTHORIZATION=f"Bearer {other_token}",
        )
        self.assertEqual(resp.status_code, 404)


class EnqueueTests(TestCase):
    def setUp(self):
        self.session = _session()
        self.person = Person.objects.create(first_name="Kid", last_name="One")

    def _checkin(self):
        return CheckIn.objects.create(
            session=self.session, person=self.person, security_code="ABCD"
        )

    def test_no_agent_queues_nothing(self):
        self.assertEqual(enqueue_checkin_labels([self._checkin()], self.session), 0)
        self.assertEqual(PrintJob.objects.count(), 0)

    def test_queues_child_and_pickup_with_real_png(self):
        agent = PrintAgent.objects.create(name="Desk")
        agent.complete_pairing()
        count = enqueue_checkin_labels([self._checkin()], self.session)
        self.assertEqual(count, 2)  # one child label + one pickup tag
        self.assertEqual(PrintJob.objects.filter(agent=agent, kind="child").count(), 1)
        self.assertEqual(PrintJob.objects.filter(agent=agent, kind="pickup").count(), 1)
        for job in PrintJob.objects.all():
            self.assertTrue(bytes(job.image_data).startswith(b"\x89PNG"))


class AgentManagementTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.staff = user_model.objects.create_user(username="s", password="pw")
        self.staff.profile.role = UserProfile.Role.STAFF
        self.staff.profile.save()

    def test_list_requires_login(self):
        self.assertEqual(self.client.get(reverse("checkin:print_agents")).status_code, 302)

    def test_staff_can_list(self):
        self.client.login(username="s", password="pw")
        self.assertEqual(self.client.get(reverse("checkin:print_agents")).status_code, 200)

    def test_create_issues_pairing_code(self):
        self.client.login(username="s", password="pw")
        resp = self.client.post(reverse("checkin:print_agent_create"), {"name": "Front Desk"})
        self.assertRedirects(resp, reverse("checkin:print_agents"))
        agent = PrintAgent.objects.get(name="Front Desk")
        self.assertTrue(agent.pairing_code)
        self.assertFalse(agent.is_paired)

    def test_test_print_requires_paired_agent(self):
        self.client.login(username="s", password="pw")
        agent = PrintAgent.objects.create(name="Unpaired")
        self.client.post(reverse("checkin:print_agent_test", args=[agent.id]))
        self.assertEqual(PrintJob.objects.count(), 0)

    def test_test_print_queues_job_when_paired(self):
        self.client.login(username="s", password="pw")
        agent = PrintAgent.objects.create(name="Paired")
        agent.complete_pairing()
        self.client.post(reverse("checkin:print_agent_test", args=[agent.id]))
        self.assertEqual(PrintJob.objects.filter(agent=agent, kind="test").count(), 1)
