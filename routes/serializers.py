from rest_framework import serializers
from .models import Waypoint, Airway, AirwaySegment, Route, FlightInformationRegion
from django.contrib.auth.models import User


class WaypointSerializer(serializers.ModelSerializer):
    type_display = serializers.CharField(source='get_type_display', read_only=True)
    source_display = serializers.CharField(source='get_source_display', read_only=True)
    
    class Meta:
        model = Waypoint
        fields = [
            'id', 'identifier', 'name', 'type', 'type_display',
            'frequency', 'elevation', 'magnetic_variation',
            'location', 'country', 'source', 'source_display',
            'is_active'
        ]
        read_only_fields = ['id']


class AirwaySegmentSerializer(serializers.ModelSerializer):
    from_waypoint_identifier = serializers.CharField(source='from_waypoint.identifier', read_only=True)
    to_waypoint_identifier = serializers.CharField(source='to_waypoint.identifier', read_only=True)
    
    class Meta:
        model = AirwaySegment
        fields = [
            'id', 'airway', 'from_waypoint', 'from_waypoint_identifier',
            'to_waypoint', 'to_waypoint_identifier', 'sequence',
            'distance', 'base_altitude'
        ]


class AirwaySerializer(serializers.ModelSerializer):
    type_display = serializers.CharField(source='get_type_display', read_only=True)
    segments = AirwaySegmentSerializer(many=True, read_only=True)
    segment_count = serializers.IntegerField(read_only=True)
    total_distance = serializers.FloatField(read_only=True)
    
    class Meta:
        model = Airway
        fields = [
            'id', 'identifier', 'name', 'type', 'type_display',
            'segments', 'segment_count', 'total_distance'
        ]


class RouteSerializer(serializers.ModelSerializer):
    created_by_username = serializers.CharField(source='created_by.username', read_only=True)
    updated_by_username = serializers.CharField(source='updated_by.username', allow_null=True, read_only=True)
    waypoint_count = serializers.SerializerMethodField()
    waypoint_details = serializers.SerializerMethodField()
    coordinates_geojson = serializers.SerializerMethodField()
    flight_time = serializers.CharField(read_only=True, allow_null=True, allow_blank=True)  # اضافه شد
    
    class Meta:
        model = Route
        fields = [
            'id', 'name', 'departure', 'arrival', 'waypoints',
            'waypoint_count', 'waypoint_details', 'total_distance',
            'flight_time', 'description', 'coordinates', 'coordinates_geojson',
            'created_by', 'created_by_username',
            'updated_by', 'updated_by_username', 'created_at', 'updated_at'
        ]
        read_only_fields = ['created_by', 'updated_by', 'created_at', 'updated_at']
    
    def get_waypoint_count(self, obj):
        return len(obj.waypoints) if obj.waypoints else 0
    
    def get_waypoint_details(self, obj):
        from .models import Waypoint
        if not obj.waypoints:
            return []
        
        waypoints = Waypoint.objects.filter(identifier__in=obj.waypoints)
        return WaypointSerializer(waypoints, many=True).data
    
    def get_coordinates_geojson(self, obj):
        """تبدیل coordinates به GeoJSON"""
        if obj.coordinates:
            return {
                'type': 'LineString',
                'coordinates': obj.coordinates
            }
        return None
    
    def create(self, validated_data):
        # اضافه کردن کاربر جاری به created_by
        request = self.context.get('request')
        if request and hasattr(request, 'user'):
            validated_data['created_by'] = request.user
        return super().create(validated_data)
    
    def update(self, instance, validated_data):
        # اضافه کردن کاربر جاری به updated_by
        request = self.context.get('request')
        if request and hasattr(request, 'user'):
            validated_data['updated_by'] = request.user
        return super().update(instance, validated_data)


class FlightInformationRegionSerializer(serializers.ModelSerializer):
    """Serializer برای مناطق اطلاعات پرواز (FIR)"""
    icao_region_display = serializers.CharField(source='get_icao_region_display', read_only=True)
    area_km2 = serializers.SerializerMethodField()
    center_point = serializers.SerializerMethodField()
    boundary_geojson = serializers.SerializerMethodField()
    
    class Meta:
        model = FlightInformationRegion
        fields = [
            'id', 'identifier', 'name', 'country', 'country_code',
            'frequency', 'emergency_frequency', 'icao_region', 'icao_region_display',
            'boundary', 'boundary_geojson', 'upper_limit', 'lower_limit',
            'area_km2', 'center_point', 'is_active', 'notes'
        ]
        read_only_fields = ['id']
    
    def get_area_km2(self, obj):
        return obj.get_area_km2()
    
    def get_center_point(self, obj):
        center = obj.get_center_point()
        if center:
            return {'lat': center.y, 'lon': center.x}
        return None
    
    def get_boundary_geojson(self, obj):
        """تبدیل boundary به GeoJSON صحیح"""
        if obj.boundary:
            try:
                import json
                from django.contrib.gis import geos
                
                geojson_str = obj.boundary.geojson
                geojson_dict = json.loads(geojson_str)
                return geojson_dict
                
            except Exception as e:
                print(f"Error converting boundary to GeoJSON: {e}")
                return None
        return None


class RouteSuggestionSerializer(serializers.Serializer):
    departure = serializers.CharField(max_length=10)
    arrival = serializers.CharField(max_length=10)
    max_deviation_nm = serializers.FloatField(default=100, min_value=10, max_value=500)
    
    def validate_departure(self, value):
        from .models import Waypoint
        if not Waypoint.objects.filter(identifier=value).exists():
            raise serializers.ValidationError(f"Waypoint '{value}' پیدا نشد")
        return value
    
    def validate_arrival(self, value):
        from .models import Waypoint
        if not Waypoint.objects.filter(identifier=value).exists():
            raise serializers.ValidationError(f"Waypoint '{value}' پیدا نشد")
        return value


class UserSerializer(serializers.ModelSerializer):
    routes_created = serializers.IntegerField(source='created_routes.count', read_only=True)
    
    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'first_name', 'last_name', 'routes_created']
