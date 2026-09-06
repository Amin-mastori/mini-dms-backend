from rest_framework import serializers


class StrictInputMixin:
    def to_internal_value(self, data):
        allowed = {name for name, field in self.fields.items() if not field.read_only}
        unexpected = set(data) - allowed
        if unexpected:
            raise serializers.ValidationError(
                {name: ["Unknown or read-only field."] for name in sorted(unexpected)}
            )
        return super().to_internal_value(data)


class ErrorSerializer(serializers.Serializer):
    error = serializers.DictField()
