from django.contrib.gis.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from django.contrib.gis.geos import LineString
from django.db.models import Q

class Waypoint(models.Model):
    TYPES = [
        ('AIRPORT', 'فرودگاه'),
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
    
    identifier = models.CharField(max_length=10, unique=True, verbose_name='شناسه')
    name = models.CharField(max_length=100, verbose_name='نام')
    type = models.CharField(
        max_length=10, 
        choices=TYPES, 
        default='FIX',
        verbose_name='نوع'
    )
    
    frequency = models.FloatField(
        null=True, 
        blank=True, 
        verbose_name='فرکانس (MHz)'
    )
    elevation = models.IntegerField(
        null=True, 
        blank=True, 
        verbose_name='ارتفاع (فوت)'
    )
    magnetic_variation = models.FloatField(
        null=True, 
        blank=True, 
        verbose_name='انحراف مغناطیسی (°)'
    )
    
    location = models.PointField(srid=4326, verbose_name='موقعیت')
    country = models.CharField(max_length=100, verbose_name='کشور')
    
    source = models.CharField(
        max_length=50, 
        default='OURAIRPORTS',
        choices=[
            ('OURAIRPORTS', 'OurAirports'),
            ('AIP_IRAN', 'AIP ایران'),
            ('MANUAL', 'دستی'),
        ],
        verbose_name='منبع'
    )
    is_active = models.BooleanField(default=True, verbose_name='فعال')
    
    class Meta:
        db_table = 'waypoints'
        verbose_name = 'نقطه ناوبری'
        verbose_name_plural = 'نقاط ناوبری'
        ordering = ['identifier']
        indexes = [
            models.Index(fields=['type']),
            models.Index(fields=['country']),
            models.Index(fields=['is_active']),
        ]
    
    def __str__(self):
        return f"{self.identifier} ({self.name})"

class Airway(models.Model):
    TYPES = [
        ('A', 'Alpha - North/South'),
        ('B', 'Bravo - North/South'),
        ('G', 'Golf - East/West'), 
        ('R', 'Romeo - East/West'),
    ]
    
    identifier = models.CharField(max_length=10, verbose_name='Airway ID')
    name = models.CharField(max_length=100, verbose_name='Airway Name')
    type = models.CharField(
        max_length=1, 
        choices=TYPES,
        verbose_name='Airway Type'
    )
    
    class Meta:
        db_table = 'airways'
        verbose_name = 'Airway'
        verbose_name_plural = 'Airways'
        ordering = ['identifier']
    
    def __str__(self):
        return f"{self.identifier} - {self.name}"

class AirwaySegment(models.Model):
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
    name = models.CharField(max_length=100, verbose_name='Route Name')
    departure = models.CharField(max_length=4, verbose_name='Departure (ICAO)', db_index=True)
    arrival = models.CharField(max_length=4, verbose_name='Arrival (ICAO)', db_index=True)
    waypoints = models.JSONField(verbose_name='Waypoints', default=list)
    coordinates = models.LineStringField(srid=4326, verbose_name='Coordinates', null=True, blank=True)
    total_distance = models.FloatField(default=0, verbose_name='Total Distance (NM)')
    flight_time = models.CharField(
        max_length=20, 
        verbose_name='Flight Time (HH:MM)',
        blank=True, 
        null=True
    )
    
    # New field: User-defined version/code (can be word or number)
    version = models.CharField(
        max_length=50,
        verbose_name='Version/Code',
        blank=True,
        default='',
        help_text='User defined version, code, or number (e.g., v1, winter, emergency, 002)'
    )
    
    description = models.TextField(blank=True, verbose_name='Description')
    
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
            models.Index(fields=['version']),  # New index for version field
        ]
        ordering = ['-created_at']
        # Unique constraint: Same departure+arrival+version cannot be duplicated
        constraints = [
            models.UniqueConstraint(
                fields=['departure', 'arrival', 'version'],
                name='unique_departure_arrival_version'
            )
        ]
    
    def __str__(self):
        if self.version:
            return f"{self.name} ({self.departure}→{self.arrival}) - {self.version}"
        return f"{self.name} ({self.departure}→{self.arrival})"
    
    def get_full_name(self):
        """Get complete route name including version if exists"""
        if self.version:
            return f"{self.name} - {self.version}"
        return self.name
    
    def get_search_name(self):
        """Get name for search purposes: DEPARTURE-ARRIVAL"""
        return f"{self.departure}-{self.arrival}"
    
    def get_waypoint_objects(self):
        """Get Waypoint objects from identifiers"""
        return Waypoint.objects.filter(identifier__in=self.waypoints).order_by('identifier')
    
    def calculate_coordinates(self):
        """Calculate LineString from waypoints"""
        if len(self.waypoints) < 2:
            return None
        
        waypoint_objects = Waypoint.objects.filter(identifier__in=self.waypoints)
        
        # Sort based on order in waypoints list
        ordered_points = []
        for wp_id in self.waypoints:
            wp = waypoint_objects.filter(identifier=wp_id).first()
            if wp:
                ordered_points.append((wp.location.x, wp.location.y))
        
        if len(ordered_points) >= 2:
            return LineString(ordered_points, srid=4326)
        return None
    
    def calculate_distance(self):
        """Calculate total distance in nautical miles"""
        if len(self.waypoints) < 2:
            return 0
        
        total_nm = 0
        for i in range(len(self.waypoints) - 1):
            wp1 = Waypoint.objects.filter(identifier=self.waypoints[i]).first()
            wp2 = Waypoint.objects.filter(identifier=self.waypoints[i + 1]).first()
            
            if wp1 and wp2:
                distance_deg = wp1.location.distance(wp2.location)
                distance_nm = distance_deg * 60.11  # Convert to nautical miles
                total_nm += distance_nm
        
        return round(total_nm, 2)
    
    def calculate_flight_time(self):
        """Calculate flight time based on distance"""
        if self.total_distance <= 0:
            return ""
        
        # Average speed: 450 knots
        hours = self.total_distance / 450
        hour_int = int(hours)
        minute_int = int((hours - hour_int) * 60)
        
        return f"{hour_int:02d}:{minute_int:02d}"
    
    def save(self, *args, **kwargs):
        # 1. Auto name: DEPARTURE-ARRIVAL (simple format for search)
        if not self.name:
            self.name = f"{self.departure}-{self.arrival}"
        
        # 2. Auto coordinates
        if self.waypoints and len(self.waypoints) >= 2:
            coords = self.calculate_coordinates()
            if coords:
                self.coordinates = coords
        
        # 3. Auto distance
        if self.waypoints and len(self.waypoints) >= 2:
            self.total_distance = self.calculate_distance()
        
        # 4. Auto flight time
        if self.total_distance > 0 and not self.flight_time:
            self.flight_time = self.calculate_flight_time()
        
        # 5. Add departure and arrival to waypoints if not present
        if self.waypoints:
            if self.departure not in self.waypoints:
                self.waypoints.insert(0, self.departure)
            if self.arrival not in self.waypoints:
                self.waypoints.append(self.arrival)
        
        super().save(*args, **kwargs)
    
    def get_waypoint_count(self):
        return len(self.waypoints) if self.waypoints else 0
    
    def get_formatted_waypoints(self):
        return " → ".join(self.waypoints) if self.waypoints else "No waypoints"
    
    @classmethod
    def get_available_versions(cls, departure, arrival):
        """Get all existing versions for a departure-arrival pair"""
        return cls.objects.filter(
            departure=departure,
            arrival=arrival
        ).exclude(version='').values_list('version', flat=True).distinct()

class FlightInformationRegion(models.Model):
    """Flight Information Region (FIR) - Airspace boundaries"""
    
    identifier = models.CharField(max_length=10, unique=True, verbose_name='FIR Identifier (e.g., OIIX)')
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
        if self.boundary:
            return self.boundary.centroid
        return None
    
    def get_area_km2(self):
        if self.boundary:
            area_sq_deg = self.boundary.area
            area_km2 = area_sq_deg * 111 * 111
            return round(area_km2, 2)
        return 0
