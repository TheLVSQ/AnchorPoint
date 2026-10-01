from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from checkin.models import CheckInSession
from events.models import Event
from groups.models import Group, GroupMembership
from households.models import Household, HouseholdMember
from people.models import Person

from .permissions import IsStaffOrAdmin
from .serializers import (
    CheckInSessionSerializer,
    EventSerializer,
    GroupMembershipSerializer,
    GroupSerializer,
    HouseholdMemberSerializer,
    HouseholdSerializer,
    PersonSerializer,
)


class PersonViewSet(viewsets.ModelViewSet):
    serializer_class = PersonSerializer
    permission_classes = [IsStaffOrAdmin]
    queryset = Person.objects.all().order_by("last_name", "first_name")
    search_fields = ["first_name", "last_name", "email", "phone", "normalized_phone"]
    ordering_fields = ["last_name", "first_name", "status", "birthdate"]
    ordering = ["last_name", "first_name"]

    def get_queryset(self):
        queryset = super().get_queryset()
        status_value = self.request.query_params.get("status")
        if status_value:
            queryset = queryset.filter(status=status_value)
        return queryset


class HouseholdViewSet(viewsets.ModelViewSet):
    serializer_class = HouseholdSerializer
    permission_classes = [IsStaffOrAdmin]
    queryset = Household.objects.prefetch_related("members").order_by("name")
    search_fields = ["name", "phone", "city", "state", "postal_code"]
    ordering_fields = ["name", "city", "state"]
    ordering = ["name"]

    @action(detail=True, methods=["get"], permission_classes=[IsStaffOrAdmin])
    def members(self, request, pk=None):
        household = self.get_object()
        memberships = household.memberships.select_related("person").order_by(
            "person__last_name", "person__first_name"
        )
        serializer = HouseholdMemberSerializer(memberships, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=["post"], permission_classes=[IsStaffOrAdmin])
    def add_member(self, request, pk=None):
        household = self.get_object()
        serializer = HouseholdMemberSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        person = serializer.validated_data["person"]
        relationship_type = serializer.validated_data["relationship_type"]
        membership, created = HouseholdMember.objects.get_or_create(
            household=household,
            person=person,
            defaults={"relationship_type": relationship_type},
        )
        if not created:
            membership.relationship_type = relationship_type
            membership.save(update_fields=["relationship_type"])
        return Response(
            HouseholdMemberSerializer(membership).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )

    @action(detail=True, methods=["post"], permission_classes=[IsStaffOrAdmin])
    def remove_member(self, request, pk=None):
        household = self.get_object()
        person_id = request.data.get("person")
        if not person_id:
            return Response(
                {"error": {"code": 400, "details": "person is required"}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        deleted, _ = HouseholdMember.objects.filter(
            household=household, person_id=person_id
        ).delete()
        return Response({"removed": bool(deleted)})


class GroupViewSet(viewsets.ModelViewSet):
    serializer_class = GroupSerializer
    permission_classes = [IsStaffOrAdmin]
    queryset = Group.objects.prefetch_related("memberships").order_by("name")
    search_fields = ["name", "short_code", "description", "location"]
    ordering_fields = ["name", "category", "created_at"]
    ordering = ["name"]

    @action(detail=True, methods=["get"], permission_classes=[IsStaffOrAdmin])
    def members(self, request, pk=None):
        group = self.get_object()
        memberships = group.memberships.select_related("person").order_by(
            "person__last_name", "person__first_name"
        )
        serializer = GroupMembershipSerializer(memberships, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=["post"], permission_classes=[IsStaffOrAdmin])
    def add_member(self, request, pk=None):
        group = self.get_object()
        serializer = GroupMembershipSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        person = serializer.validated_data["person"]
        role = serializer.validated_data.get("role", "member")
        notes = serializer.validated_data.get("notes", "")
        membership, created = GroupMembership.objects.get_or_create(
            group=group,
            person=person,
            defaults={"role": role, "notes": notes},
        )
        if not created:
            membership.role = role
            membership.notes = notes
            membership.save(update_fields=["role", "notes"])
        return Response(
            GroupMembershipSerializer(membership).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )

    @action(detail=True, methods=["post"], permission_classes=[IsStaffOrAdmin])
    def remove_member(self, request, pk=None):
        group = self.get_object()
        person_id = request.data.get("person")
        if not person_id:
            return Response(
                {"error": {"code": 400, "details": "person is required"}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        deleted, _ = GroupMembership.objects.filter(
            group=group, person_id=person_id
        ).delete()
        return Response({"removed": bool(deleted)})


class EventViewSet(viewsets.ModelViewSet):
    serializer_class = EventSerializer
    search_fields = ["title", "summary", "description", "slug"]
    ordering_fields = ["title", "created_at", "updated_at"]
    ordering = ["title"]

    def get_permissions(self):
        if self.action in ["list", "retrieve"]:
            return [AllowAny()]
        return [IsStaffOrAdmin()]

    def get_queryset(self):
        queryset = Event.objects.prefetch_related("occurrences").order_by("title")
        user = self.request.user
        if not user.is_authenticated:
            return queryset.filter(is_published=True)
        profile = getattr(user, "profile", None)
        if not profile:
            return queryset.filter(is_published=True)
        if profile.role in ["admin", "staff", "volunteer_admin"]:
            return queryset
        return queryset.filter(is_published=True)


class CheckInSessionViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = CheckInSessionSerializer
    permission_classes = [IsAuthenticated]
    queryset = CheckInSession.objects.prefetch_related("rooms").order_by(
        "-date", "-checkin_opens"
    )
    ordering_fields = ["date", "checkin_opens", "name"]
    ordering = ["-date", "-checkin_opens"]

    @action(detail=True, methods=["get"], permission_classes=[IsAuthenticated])
    def stats(self, request, pk=None):
        session = self.get_object()
        checked_in = session.checkins.filter(checked_out_at__isnull=True).count()
        checked_out = session.checkins.filter(checked_out_at__isnull=False).count()
        rooms = []
        for room in session.rooms.all():
            room_count = session.checkins.filter(
                room=room, checked_out_at__isnull=True
            ).count()
            rooms.append(
                {
                    "name": room.name,
                    "count": room_count,
                    "capacity": room.capacity,
                }
            )
        return Response(
            {
                "checked_in": checked_in,
                "checked_out": checked_out,
                "total": checked_in + checked_out,
                "rooms": rooms,
            }
        )
