from rest_framework import serializers

from checkin.models import CheckInSession
from events.models import Event, EventOccurrence
from groups.models import Group, GroupMembership
from households.models import Household, HouseholdMember
from people.models import Person


class PersonSerializer(serializers.ModelSerializer):
    age = serializers.ReadOnlyField()
    is_minor = serializers.ReadOnlyField()

    class Meta:
        model = Person
        fields = [
            "id",
            "first_name",
            "last_name",
            "email",
            "phone",
            "phone_opt_in",
            "birthdate",
            "age",
            "is_minor",
            "grade",
            "marital_status",
            "gender",
            "status",
            "notes",
            "allergies",
            "security_notes",
            "custody_flag",
            "custody_notes",
            "unauthorized_pickup",
        ]


class HouseholdMemberSerializer(serializers.ModelSerializer):
    person_name = serializers.SerializerMethodField()

    class Meta:
        model = HouseholdMember
        fields = [
            "id",
            "household",
            "person",
            "person_name",
            "relationship_type",
        ]

    def get_person_name(self, obj):
        return str(obj.person)


class HouseholdSerializer(serializers.ModelSerializer):
    primary_adult_name = serializers.SerializerMethodField()
    member_count = serializers.SerializerMethodField()

    class Meta:
        model = Household
        fields = [
            "id",
            "name",
            "phone",
            "address_line1",
            "address_line2",
            "city",
            "state",
            "postal_code",
            "primary_adult",
            "primary_adult_name",
            "member_count",
        ]

    def get_primary_adult_name(self, obj):
        return str(obj.primary_adult) if obj.primary_adult else None

    def get_member_count(self, obj):
        return obj.members.count()


class GroupMembershipSerializer(serializers.ModelSerializer):
    person_name = serializers.SerializerMethodField()

    class Meta:
        model = GroupMembership
        fields = [
            "id",
            "group",
            "person",
            "person_name",
            "role",
            "joined_at",
            "notes",
        ]
        read_only_fields = ["joined_at"]

    def get_person_name(self, obj):
        return str(obj.person)


class GroupSerializer(serializers.ModelSerializer):
    member_count = serializers.SerializerMethodField()

    class Meta:
        model = Group
        fields = [
            "id",
            "name",
            "short_code",
            "description",
            "category",
            "location",
            "meeting_schedule",
            "capacity",
            "is_active",
            "member_count",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["created_at", "updated_at"]

    def get_member_count(self, obj):
        return obj.memberships.count()


class EventOccurrenceSerializer(serializers.ModelSerializer):
    class Meta:
        model = EventOccurrence
        fields = ["id", "starts_at", "ends_at", "is_all_day"]


class EventSerializer(serializers.ModelSerializer):
    occurrences = EventOccurrenceSerializer(many=True, read_only=True)
    display_cost = serializers.ReadOnlyField()
    can_register = serializers.SerializerMethodField()

    class Meta:
        model = Event
        fields = [
            "id",
            "title",
            "slug",
            "summary",
            "description",
            "location_name",
            "contact_name",
            "contact_email",
            "contact_phone",
            "is_free",
            "cost_amount",
            "cost_type",
            "display_cost",
            "registration_token",
            "registration_deadline",
            "registration_capacity",
            "registration_open",
            "is_published",
            "created_at",
            "updated_at",
            "occurrences",
            "can_register",
        ]
        read_only_fields = [
            "slug",
            "registration_token",
            "created_at",
            "updated_at",
            "display_cost",
            "can_register",
        ]

    def get_can_register(self, obj):
        return obj.can_register()


class CheckInSessionSerializer(serializers.ModelSerializer):
    total_checked_in = serializers.SerializerMethodField()

    class Meta:
        model = CheckInSession
        fields = [
            "id",
            "name",
            "date",
            "checkin_opens",
            "checkin_closes",
            "event_starts",
            "event_ends",
            "is_active",
            "total_checked_in",
        ]

    def get_total_checked_in(self, obj):
        return obj.total_checked_in()
