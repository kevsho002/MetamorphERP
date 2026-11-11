from rest_framework import serializers

from apps.roster.models import RosterAttribute, RosterDimension, RosterDimensionItem


class RosterDimensionItemSerializer(serializers.ModelSerializer):
    parent = serializers.CharField(source="parent.code", default=None, read_only=True)
    country = serializers.CharField(source="country.country_code", default=None, read_only=True)

    class Meta:
        model = RosterDimensionItem
        fields = ["code", "name", "parent", "country", "is_active"]


class RosterDimensionSerializer(serializers.ModelSerializer):
    parent = serializers.CharField(source="parent.code", default=None, read_only=True)
    items = serializers.SerializerMethodField()

    class Meta:
        model = RosterDimension
        fields = ["code", "name", "parent", "is_active", "items"]

    def get_items(self, obj) -> list[dict]:
        include_inactive = self.context.get("include_inactive", False)
        items = [i for i in obj.items.all() if include_inactive or i.is_active]
        return RosterDimensionItemSerializer(items, many=True).data


class RosterAttributeSerializer(serializers.ModelSerializer):
    """Definición que la interfaz React usa para dibujar y validar cada campo del roster."""

    dimension = serializers.CharField(source="dimension.code", default=None, read_only=True)
    dimension_name = serializers.CharField(source="dimension.name", default=None, read_only=True)
    depends_on = serializers.CharField(source="depends_on.code", default=None, read_only=True)
    data_type_label = serializers.CharField(source="get_data_type_display", read_only=True)

    class Meta:
        model = RosterAttribute
        fields = [
            "code", "name", "group", "display_order", "data_type", "data_type_label", "dimension", "dimension_name",
            "depends_on", "choices", "rules", "help", "is_active",
        ]
