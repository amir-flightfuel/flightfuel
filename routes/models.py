from django.contrib.gis.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from django.contrib.gis.geos import LineString
from django.db.models import Q

class Waypoint(models.Model):
    """
    Navigation waypoint model (VOR, NDB, FIX, Airport, etc.)
    """
    TYPES = [
        ('AIRPORT', 'Airport'),
        ('VOR', 'VOR/DME'),
        ('NDB', 'NDB'),
        ('FIX', 'Fix'),
        ('IAF', 'Initial Approach Fix'),
        ('FAF', 'Final Approach Fix'),
        ('MAWP', 'Missed Approach Waypoint'),
        ('RNAV', 'RNAV Waypoint'),
        ('DME', 'DME Only'),
        ('TACAN', 'TACAN'),
        ('VORTAC', 'VORTAC'),
    ]
    
    identifier = models.CharField(max_length=10, unique=True, verbose_name='Identifier')
    name = models.CharField(max_length=100, verbose_name='Name')
    type = models.CharField(
        max_length=10, 
        choices=TYPES, 
        default='FIX',
        verbose_name='Type'
    )
    
    frequency = models.FloatField(null=True, blank=True, verbose_name='Frequency (MHz)')
    elevation = models.IntegerField(null=True, blank=True, verbose_name='Elevation (ft)')
    magnetic_variation = models.FloatField(null=True, blank=True, verbose_name='Magnetic Variation (°)')
    
    location = models.PointField(srid=4326, verbose_name='Location')
    country = models.CharField(max_length=100, verbose_name='Country')
    
    source = models.CharField(
        max_length=50, 
        default='OURAIRPORTS',
        choices=[
            ('OURAIRPORTS', 'OurAirports'),
            ('AIP', 'AIP'),
            ('MANUAL', 'Manual'),
        ],
        verbose_name='Source'
    )
    is_active = models.BooleanField(default=True, verbose_name='Active')
    
    class Meta:
        db_table = 'waypoints'
        verbose_name = 'Waypoint'
        verbose_name_plural = 'Waypoints'
        ordering = ['identifier']
        indexes = [
            models.Index(fields=['type']),
            models.Index(fields=['country']),
            models.Index(fields=['is_active']),
        ]
    
    def __str__(self):
        return f"{self.identifier} ({self.name})"
    
    def get_type_display(self):
        """Get human-readable type name"""
        for code, name in self.TYPES:
            if code == self.type:
                return name
        return self.type
    
    def get_source_display(self):
        """Get human-readable source name"""
        for code, name in self._meta.get_field('source').choices:
            if code == self.source:
                return name
        return self.source

class Airway(models.Model):
    """
    Published airway model (A, B, G, R routes)
    """
    TYPES = [
        ('A', 'Alpha - North/South'),
        ('B', 'Bravo - North/South'),
        ('G', 'Golf - East/West'), 
        ('R', 'Romeo - East/West'),
    ]
    
    identifier = models.CharField(max_length=10, verbose_name='Airway ID')
    name = models.CharField(max_length=100, verbose_name='Airway Name')
    type = models.CharField(max_length=1, choices=TYPES, verbose_name='Airway Type')
    
    class Meta:
        db_table = 'airways'
        verbose_name = 'Airway'
        verbose_name_plural = 'Airways'
        ordering = ['identifier']
    
    def __str__(self):
        return f"{self.identifier} - {self.name}"
    
    def get_type_display(self):
        """Get human-readable airway type"""
        for code, name in self.TYPES:
            if code == self.type:
                return name
        return self.type

class AirwaySegment(models.Model):
    """
    Segment of an airway connecting two waypoints
    """
    airway = models.ForeignKey(Airway, on_delete=models.CASCADE, related_name='segments')
    from_waypoint = models.ForeignKey(Waypoint, related_name='segment_starts', on_delete=models.CASCADE)
    to_waypoint = models.ForeignKey(Waypoint, related_name='segment_ends', on_delete=models.CASCADE)
    sequence = models.IntegerField()
    distance = models.FloatField(verbose_name='Distance (NM)')
    base_altitude = models.IntegerField(default=19000, verbose_name='Base Altitude (ft)')
    
    class Meta:
        db_table = 'airway_segments'
        ordering = ['airway', 'sequence']
        unique_together = ['airway', 'sequence']
    
    def __str__(self):
        return f"{self.airway.identifier}: {self.from_waypoint}→{self.to_waypoint}"

class Route(models.Model):
    """
    Flight route model with support for soft delete
    """
    name = models.CharField(max_length=100, verbose_name='Route Name')
    departure = models.CharField(max_length=4, verbose_name='Departure (ICAO)', db_index=True)
    arrival = models.CharField(max_length=4, verbose_name='Arrival (ICAO)', db_index=True)
    waypoints = models.JSONField(verbose_name='Waypoints', default=list)
    coordinates = models.LineStringField(srid=4326, verbose_name='Coordinates', null=True, blank=True)
    total_distance = models.FloatField(default=0, verbose_name='Total Distance (NM)')
    flight_time = models.CharField(max_length=20, verbose_name='Flight Time (HH:MM)', blank=True, null=True)
    
    version = models.CharField(
        max_length=50,
        verbose_name='Version/Code',
        blank=True,
        default='',
        help_text='User defined version, code, or number (e.g., v1, winter, emergency, 002)'
    )
    
    description = models.TextField(blank=True, verbose_name='Description')
    
    # Soft delete support
    is_active = models.BooleanField(default=True, verbose_name='Active', db_index=True,
                                    help_text='Soft delete flag. False means route is deleted.')
    
    # User tracking
    created_by = models.ForeignKey(
        User, 
        on_delete=models.CASCADE, 
        verbose_name='Created By', 
        related_name='created_routes'
    )
    updated_by = models.ForeignKey(
        User, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        verbose_name='Updated By', 
        related_name='updated_routes'
    )
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Created At')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='Updated At')
    
    class Meta:
        db_table = 'routes'
        verbose_name = 'Route'
        verbose_name_plural = 'Routes'
        indexes = [
            models.Index(fields=['departure']),
            models.Index(fields=['arrival']),
            models.Index(fields=['created_at']),
            models.Index(fields=['name']),
            models.Index(fields=['version']),
            models.Index(fields=['is_active']),  # Added for soft delete filtering
        ]
        ordering = ['-created_at']
        constraints = [
            # Ensure unique combination only for active routes
            models.UniqueConstraint(
                fields=['departure', 'arrival', 'name', 'version'],
                name='unique_route_combination',
                condition=models.Q(is_active=True)  # Only enforce for active routes
            )
        ]
    
    def __str__(self):
        if self.version:
            return f"{self.name} ({self.departure}→{self.arrival}) - {self.version}"
        return f"{self.name} ({self.departure}→{self.arrival})"
    
    def get_full_name(self):
        """Get complete route name with version"""
        if self.version:
            return f"{self.name} - {self.version}"
        return self.name
    
    def get_search_name(self):
        """Get simplified name for search"""
        return f"{self.departure}-{self.arrival}"
    
    def get_waypoint_objects(self):
        """Get Waypoint objects for the route's waypoints"""
        return Waypoint.objects.filter(identifier__in=self.waypoints).order_by('identifier')
    
    def calculate_coordinates(self):
        """Calculate LineString coordinates from waypoints"""
        if len(self.waypoints) < 2:
            return None
        
        waypoint_objects = Waypoint.objects.filter(identifier__in=self.waypoints)
        
        ordered_points = []
        for wp_id in self.waypoints:
            wp = waypoint_objects.filter(identifier=wp_id).first()
            if wp:
                ordered_points.append((wp.location.x, wp.location.y))
        
        if len(ordered_points) >= 2:
            return LineString(ordered_points, srid=4326)
        return None
    
    def calculate_distance(self):
        """Calculate total route distance in nautical miles"""
        if len(self.waypoints) < 2:
            return 0
        
        total_nm = 0
        for i in range(len(self.waypoints) - 1):
            wp1 = Waypoint.objects.filter(identifier=self.waypoints[i]).first()
            wp2 = Waypoint.objects.filter(identifier=self.waypoints[i + 1]).first()
            
            if wp1 and wp2:
                distance_deg = wp1.location.distance(wp2.location)
                distance_nm = distance_deg * 60.11
                total_nm += distance_nm
        
        return round(total_nm, 2)
    
    def calculate_flight_time(self):
        """Calculate estimated flight time based on distance"""
        if self.total_distance <= 0:
            return ""
        
        hours = self.total_distance / 450  # Assuming 450 knots average speed
        hour_int = int(hours)
        minute_int = int((hours - hour_int) * 60)
        
        return f"{hour_int:02d}:{minute_int:02d}"
    
    def save(self, *args, **kwargs):
        """Override save to auto-calculate fields"""
        # Set default name if not provided
        if not self.name:
            self.name = f"{self.departure}-{self.arrival}"
        
        # Calculate coordinates from waypoints
        if self.waypoints and len(self.waypoints) >= 2:
            coords = self.calculate_coordinates()
            if coords:
                self.coordinates = coords
        
        # Calculate total distance
        if self.waypoints and len(self.waypoints) >= 2:
            self.total_distance = self.calculate_distance()
        
        # Calculate flight time if not provided
        if self.total_distance > 0 and not self.flight_time:
            self.flight_time = self.calculate_flight_time()
        
        # Ensure departure and arrival are in waypoints
        if self.waypoints:
            if self.departure not in self.waypoints:
                self.waypoints.insert(0, self.departure)
            if self.arrival not in self.waypoints:
                self.waypoints.append(self.arrival)
        
        super().save(*args, **kwargs)
    
    def get_waypoint_count(self):
        """Get number of waypoints in route"""
        return len(self.waypoints) if self.waypoints else 0
    
    def get_formatted_waypoints(self):
        """Get formatted string of waypoints"""
        return " → ".join(self.waypoints) if self.waypoints else "No waypoints"
    
    def soft_delete(self):
        """Mark route as deleted (soft delete)"""
        self.is_active = False
        self.save(update_fields=['is_active', 'updated_at'])
    
    def restore(self):
        """Restore soft-deleted route"""
        self.is_active = True
        self.save(update_fields=['is_active', 'updated_at'])
    
    def hard_delete(self):
        """Permanently delete route"""
        super().delete()
    
    @classmethod
    def get_active_routes(cls):
        """Get only active routes"""
        return cls.objects.filter(is_active=True)
    
    @classmethod
    def get_deleted_routes(cls):
        """Get only soft-deleted routes"""
        return cls.objects.filter(is_active=False)
    
    @classmethod
    def get_available_versions(cls, departure, arrival):
        """Get all versions for a route pair"""
        return cls.objects.filter(
            departure=departure,
            arrival=arrival,
            is_active=True
        ).exclude(version='').values_list('version', flat=True).distinct()

class FlightInformationRegion(models.Model):
    """
    Flight Information Region (FIR) model
    """
    identifier = models.CharField(max_length=10, unique=True, verbose_name='FIR Identifier')
    name = models.CharField(max_length=200, verbose_name='Full FIR Name')
    country = models.CharField(max_length=100, verbose_name='Country')
    country_code = models.CharField(max_length=5, verbose_name='ISO Country Code', blank=True)
    
    frequency = models.CharField(max_length=100, verbose_name='Main Frequencies', blank=True)
    emergency_frequency = models.CharField(max_length=50, default='121.5', verbose_name='Emergency Frequency')
    
    boundary = models.GeometryField(srid=4326, verbose_name='FIR Boundary')
    
    upper_limit = models.IntegerField(default=99999, verbose_name='Upper Limit (ft)')
    lower_limit = models.IntegerField(default=0, verbose_name='Lower Limit (ft)')
    
    icao_region = models.CharField(
        max_length=2, 
        verbose_name='ICAO Region',
        choices=[
            ('AS', 'Asia'),
            ('EU', 'Europe'), 
            ('AF', 'Africa'),
            ('NA', 'North America'),
            ('SA', 'South America'),
            ('PA', 'Pacific'),
            ('ME', 'Middle East'),
        ]
    )
    
    is_active = models.BooleanField(default=True, verbose_name='Active')
    notes = models.TextField(blank=True, verbose_name='Notes')
    
    class Meta:
        db_table = 'fir_regions'
        verbose_name = 'Flight Information Region (FIR)'
        verbose_name_plural = 'Flight Information Regions (FIR)'
        ordering = ['identifier']
        indexes = [
            models.Index(fields=['country']),
            models.Index(fields=['icao_region']),
            models.Index(fields=['is_active']),
        ]
    
    def __str__(self):
        return f"{self.identifier} - {self.name}"
    
    def get_center_point(self):
        """Get center point of FIR boundary"""
        if self.boundary:
            return self.boundary.centroid
        return None
    
    def get_area_km2(self):
        """Calculate area in square kilometers"""
        if self.boundary:
            area_sq_deg = self.boundary.area
            area_km2 = area_sq_deg * 111 * 111  # Approximate conversion
            return round(area_km2, 2)
        return 0
    
    def get_icao_region_display(self):
        """Get human-readable ICAO region"""
        for code, name in self._meta.get_field('icao_region').choices:
            if code == self.icao_region:
                return name
        return self.icao_region
