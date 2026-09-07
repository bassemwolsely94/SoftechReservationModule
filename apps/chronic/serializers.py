from rest_framework import serializers
from .models import (
    MedicationTag, ActiveIngredient, IngredientTag,
    ItemIngredientMap, FollowUpProtocol,
)


# ─────────────────────────────────────────────────────────────────────────────
# MedicationTag
# ─────────────────────────────────────────────────────────────────────────────

class MedicationTagSerializer(serializers.ModelSerializer):
    tag_type_display = serializers.CharField(
        source='get_tag_type_display', read_only=True
    )

    class Meta:
        model  = MedicationTag
        fields = [
            'id', 'name', 'name_ar', 'tag_type', 'tag_type_display',
            'color', 'description', 'is_active', 'created_at',
        ]
        read_only_fields = ['id', 'created_at']


# ─────────────────────────────────────────────────────────────────────────────
# IngredientTag (through model — used when adding/removing tags)
# ─────────────────────────────────────────────────────────────────────────────

class IngredientTagSerializer(serializers.ModelSerializer):
    tag_detail = MedicationTagSerializer(source='tag', read_only=True)
    added_by_name = serializers.CharField(
        source='added_by.user.get_full_name', read_only=True, default=''
    )

    class Meta:
        model  = IngredientTag
        fields = ['id', 'tag', 'tag_detail', 'added_by', 'added_by_name', 'added_at']
        read_only_fields = ['id', 'added_at']


# ─────────────────────────────────────────────────────────────────────────────
# FollowUpProtocol
# ─────────────────────────────────────────────────────────────────────────────

class FollowUpProtocolSerializer(serializers.ModelSerializer):
    frequency_type_display       = serializers.CharField(
        source='get_frequency_type_display', read_only=True
    )
    task_type_display            = serializers.CharField(
        source='get_task_type_display', read_only=True
    )
    priority_display             = serializers.CharField(
        source='get_priority_display', read_only=True
    )
    trigger_condition_display    = serializers.CharField(
        source='get_trigger_condition_display', read_only=True
    )
    customer_type_filter_display = serializers.CharField(
        source='get_customer_type_filter_display', read_only=True
    )
    description = serializers.CharField(read_only=True)
    applies_to_branches_ids = serializers.PrimaryKeyRelatedField(
        source='applies_to_branches', many=True, read_only=True
    )

    class Meta:
        model  = FollowUpProtocol
        fields = [
            'id', 'active_ingredient', 'name',
            'frequency_type', 'frequency_type_display',
            'days',
            'trigger_condition', 'trigger_condition_display',
            'customer_type_filter', 'customer_type_filter_display',
            'task_type', 'task_type_display',
            'priority', 'priority_display',
            'message_template',
            'applies_to_branches_ids',
            'is_active', 'sort_order',
            'description',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


# ─────────────────────────────────────────────────────────────────────────────
# ItemIngredientMap
# ─────────────────────────────────────────────────────────────────────────────

class ItemIngredientMapSerializer(serializers.ModelSerializer):
    item_name       = serializers.CharField(source='item.name', read_only=True)
    item_scientific = serializers.CharField(source='item.name_scientific', read_only=True)
    item_softech_id = serializers.CharField(source='item.softech_id', read_only=True)
    ingredient_name    = serializers.CharField(source='active_ingredient.name', read_only=True)
    ingredient_name_ar = serializers.CharField(source='active_ingredient.name_ar', read_only=True)
    ingredient_chronic = serializers.BooleanField(
        source='active_ingredient.is_chronic', read_only=True
    )
    ingredient_class = serializers.CharField(
        source='active_ingredient.chronic_class', read_only=True
    )
    mapped_by_name  = serializers.CharField(
        source='mapped_by.user.get_full_name', read_only=True, default=''
    )

    class Meta:
        model  = ItemIngredientMap
        fields = [
            'id', 'item', 'item_name', 'item_scientific', 'item_softech_id',
            'active_ingredient', 'ingredient_name', 'ingredient_name_ar',
            'ingredient_chronic', 'ingredient_class',
            'concentration', 'is_primary',
            'mapped_by', 'mapped_by_name', 'mapped_at',
        ]
        read_only_fields = ['id', 'mapped_at']


# ─────────────────────────────────────────────────────────────────────────────
# ActiveIngredient — list (lightweight)
# ─────────────────────────────────────────────────────────────────────────────

class ActiveIngredientListSerializer(serializers.ModelSerializer):
    chronic_class_display = serializers.CharField(
        source='get_chronic_class_display', read_only=True
    )
    tag_count  = serializers.SerializerMethodField()
    item_count = serializers.SerializerMethodField()
    tags       = MedicationTagSerializer(many=True, read_only=True)

    class Meta:
        model  = ActiveIngredient
        fields = [
            'id', 'name', 'name_ar', 'name_scientific',
            'atc_code', 'atc_level4', 'atc_level4_name',
            'atc_level3', 'atc_level3_name',
            'is_chronic', 'chronic_class', 'chronic_class_display',
            'tags', 'tag_count', 'item_count',
            'updated_at',
        ]

    def get_tag_count(self, obj):
        return obj.ingredient_tags.count()

    def get_item_count(self, obj):
        return obj.item_maps.count()


# ─────────────────────────────────────────────────────────────────────────────
# ActiveIngredient — detail (full)
# ─────────────────────────────────────────────────────────────────────────────

class ActiveIngredientDetailSerializer(serializers.ModelSerializer):
    chronic_class_display = serializers.CharField(
        source='get_chronic_class_display', read_only=True
    )
    tags               = MedicationTagSerializer(many=True, read_only=True)
    ingredient_tags    = IngredientTagSerializer(many=True, read_only=True)
    item_maps          = ItemIngredientMapSerializer(many=True, read_only=True)
    followup_protocols = FollowUpProtocolSerializer(many=True, read_only=True)
    created_by_name    = serializers.CharField(
        source='created_by.user.get_full_name', read_only=True, default=''
    )

    class Meta:
        model  = ActiveIngredient
        fields = [
            'id', 'name', 'name_ar', 'name_scientific',
            # ATC hierarchy
            'atc_code',
            'atc_level1', 'atc_level1_name',
            'atc_level2', 'atc_level2_name',
            'atc_level3', 'atc_level3_name',
            'atc_level4', 'atc_level4_name',
            # Classification
            'is_chronic', 'chronic_class', 'chronic_class_display',
            # Relations
            'tags', 'ingredient_tags',
            'item_maps',
            'followup_protocols',
            # Meta
            'notes', 'created_by', 'created_by_name',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class ActiveIngredientWriteSerializer(serializers.ModelSerializer):
    """Used for create/update — no nested write complexity."""
    class Meta:
        model  = ActiveIngredient
        fields = [
            'id', 'name', 'name_ar', 'name_scientific',
            'atc_code',
            'atc_level1', 'atc_level1_name',
            'atc_level2', 'atc_level2_name',
            'atc_level3', 'atc_level3_name',
            'atc_level4', 'atc_level4_name',
            'is_chronic', 'chronic_class',
            'notes',
        ]
        read_only_fields = ['id']


# ─────────────────────────────────────────────────────────────────────────────
# ItemClassifier — shows catalog.Item with its classification status
# ─────────────────────────────────────────────────────────────────────────────

class ItemClassifierSerializer(serializers.Serializer):
    """
    Read-only projection of catalog.Item enriched with chronic classification.
    The queryset is annotated in ItemClassifierViewSet.get_queryset().
    """
    id          = serializers.IntegerField()
    softech_id  = serializers.CharField()
    name        = serializers.CharField()
    name_scientific = serializers.CharField()
    barcode     = serializers.CharField()
    family_code = serializers.CharField()
    medicine_type = serializers.CharField()
    is_active   = serializers.BooleanField()

    # Classification status (computed via prefetch in view)
    is_classified = serializers.SerializerMethodField()
    is_chronic    = serializers.SerializerMethodField()
    ingredient    = serializers.SerializerMethodField()
    all_maps      = serializers.SerializerMethodField()

    def get_is_classified(self, obj):
        maps = getattr(obj, '_prefetched_ingredient_maps', None)
        if maps is None:
            return obj.ingredient_maps.exists()
        return len(maps) > 0

    def get_is_chronic(self, obj):
        maps = getattr(obj, '_prefetched_ingredient_maps', None)
        if maps is None:
            return obj.ingredient_maps.filter(active_ingredient__is_chronic=True).exists()
        return any(m.active_ingredient.is_chronic for m in maps)

    def get_ingredient(self, obj):
        """Returns the primary ingredient (or first one) if classified."""
        maps = getattr(obj, '_prefetched_ingredient_maps', None)
        if maps is None:
            maps = list(obj.ingredient_maps.select_related('active_ingredient').all())
        primary = next((m for m in maps if m.is_primary), None) or (maps[0] if maps else None)
        if not primary:
            return None
        ing = primary.active_ingredient
        return {
            'map_id':        primary.id,
            'ingredient_id': ing.id,
            'name':          ing.name,
            'name_ar':       ing.name_ar,
            'is_chronic':    ing.is_chronic,
            'chronic_class': ing.chronic_class,
            'atc_code':      ing.atc_code,
            'concentration': primary.concentration,
        }

    def get_all_maps(self, obj):
        maps = getattr(obj, '_prefetched_ingredient_maps', None)
        if maps is None:
            maps = list(obj.ingredient_maps.select_related('active_ingredient').all())
        return [
            {
                'map_id':        m.id,
                'ingredient_id': m.active_ingredient.id,
                'name':          m.active_ingredient.name,
                'name_ar':       m.active_ingredient.name_ar,
                'is_chronic':    m.active_ingredient.is_chronic,
                'chronic_class': m.active_ingredient.chronic_class,
                'concentration': m.concentration,
                'is_primary':    m.is_primary,
            }
            for m in maps
        ]


class ItemClassifySerializer(serializers.Serializer):
    """
    Payload for POST /api/chronic/items/{id}/classify/
    Either links to an existing ingredient or creates a new one inline.
    """
    # Option A: link to existing ingredient
    active_ingredient_id = serializers.IntegerField(required=False, allow_null=True)

    # Option B: create new ingredient inline
    ingredient_name         = serializers.CharField(required=False, allow_blank=True)
    ingredient_name_ar      = serializers.CharField(required=False, allow_blank=True)
    ingredient_atc_code     = serializers.CharField(required=False, allow_blank=True)

    # Common fields
    is_chronic    = serializers.BooleanField(default=False)
    chronic_class = serializers.CharField(required=False, allow_blank=True)
    concentration = serializers.CharField(required=False, allow_blank=True)
    is_primary    = serializers.BooleanField(default=True)
    notes         = serializers.CharField(required=False, allow_blank=True)
    tag_ids       = serializers.ListField(
        child=serializers.IntegerField(), required=False, default=list
    )

    def validate(self, data):
        has_existing = bool(data.get('active_ingredient_id'))
        has_new_name = bool(data.get('ingredient_name', '').strip())
        if not has_existing and not has_new_name:
            raise serializers.ValidationError(
                'يجب تحديد مادة فعّالة موجودة أو إدخال اسم مادة فعّالة جديدة.'
            )
        return data
