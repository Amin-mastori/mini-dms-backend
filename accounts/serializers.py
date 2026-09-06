from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from core.serializers import StrictInputMixin

User = get_user_model()


class UserSerializer(serializers.ModelSerializer):
    role = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ["id", "username", "email", "role", "is_active", "date_joined"]
        read_only_fields = fields

    def get_role(self, obj) -> str:
        return "admin" if obj.is_staff else "user"


class CreateUserSerializer(StrictInputMixin, serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, trim_whitespace=False, max_length=128)
    role = serializers.ChoiceField(choices=["user", "admin"], default="user")

    class Meta:
        model = User
        fields = ["id", "username", "email", "password", "role"]
        read_only_fields = ["id"]

    def validate(self, data):
        candidate = User(username=data["username"], email=data.get("email", ""))
        try:
            validate_password(data["password"], candidate)
        except DjangoValidationError as exc:
            raise serializers.ValidationError({"password": exc.messages}) from exc
        return data

    def create(self, validated_data):
        role = validated_data.pop("role", "user")
        return User.objects.create_user(**validated_data, is_staff=role == "admin")
