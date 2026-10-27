from rest_framework import serializers

from apps.chronic.models import IngredientClass
from .models import (
    SoftechIngredientRaw, SoftechIngredientClassRaw, IngredientParseCandidate,
    ItemMoleculeIndex,
)


class IngredientClassSerializer(serializers.ModelSerializer):
    class Meta:
        model  = IngredientClass
        fields = ['id', 'key', 'name', 'name_ar', 'softech_code', 'is_active']


class ItemMoleculeIndexSerializer(serializers.ModelSerializer):
    class_name    = serializers.CharField(source='ingredient_class.name', read_only=True, default='')
    class_name_ar = serializers.CharField(source='ingredient_class.name_ar', read_only=True, default='')

    class Meta:
        model  = ItemMoleculeIndex
        fields = [
            'id', 'item_softech_id', 'item', 'item_name', 'aicode',
            'molecule', 'active_ingredient', 'strength_value', 'strength_unit',
            'ingredient_class', 'class_name', 'class_name_ar',
            'dosage_form', 'source',
        ]


class SoftechIngredientClassRawSerializer(serializers.ModelSerializer):
    class Meta:
        model  = SoftechIngredientClassRaw
        fields = ['id', 'softech_code', 'name', 'synced_at']


class SoftechIngredientRawSerializer(serializers.ModelSerializer):
    class Meta:
        model  = SoftechIngredientRaw
        fields = ['id', 'aicode', 'ainame', 'class_code', 'class_name',
                  'item_count', 'is_blocked', 'synced_at']


class IngredientParseCandidateSerializer(serializers.ModelSerializer):
    primary_molecule     = serializers.CharField(read_only=True)
    item_count           = serializers.IntegerField(source='raw.item_count', read_only=True)
    status_display       = serializers.CharField(source='get_status_display', read_only=True)
    # classifier-proposed class (FK → chronic.IngredientClass); distinct from the
    # SOFTECH-derived proposed_class_name/_code strings on the model.
    proposed_class_label = serializers.CharField(source='proposed_class.name', read_only=True, default='')
    proposed_class_key   = serializers.CharField(source='proposed_class.key', read_only=True, default='')

    class Meta:
        model  = IngredientParseCandidate
        fields = [
            'id', 'raw', 'raw_aicode', 'raw_ainame',
            'parsed_components', 'primary_molecule',
            'is_combination', 'is_placeholder',
            'proposed_class_code', 'proposed_class_name',
            'proposed_class', 'proposed_class_label', 'proposed_class_key',
            'class_rule', 'class_confidence',
            'confidence', 'parser_version',
            'status', 'status_display', 'canonical_ingredient',
            'item_count', 'reviewed_by', 'reviewed_at', 'review_notes',
            'created_at', 'updated_at',
        ]
        read_only_fields = fields  # read-only review layer; approval flow lands in Track B.
