from django.contrib.gis.db import models

class Airport(models.Model):
    AIRPORT_TYPES = [
        ('large_airport', 'Large Airport'),
        ('medium_airport', 'Medium Airport'), 
        ('small_airport', 'Small Airport'),
    ]
    
    name = models.CharField(max_length=200, verbose_name='Name')
    iata_code = models.CharField(max_length=3, unique=True, verbose_name='IATA Code')
    icao_code = models.CharField(max_length=4, blank=True, verbose_name='ICAO Code')
    
    location = models.PointField(srid=4326, verbose_name='Location')
    altitude = models.FloatField(default=0, verbose_name='Altitude (m)')
    
    airport_type = models.CharField(
        max_length=20, 
        choices=AIRPORT_TYPES, 
        verbose_name='Airport Type'
    )
    
    country = models.CharField(max_length=100, verbose_name='Country')
    city = models.CharField(max_length=100, verbose_name='City')
    
    runway_length = models.FloatField(
        null=True, 
        blank=True, 
        verbose_name='Runway Length (m)'
    )
    
    objects = models.Manager()
    
    class Meta:
        db_table = 'airports'
        verbose_name = 'Airport'
        verbose_name_plural = 'Airports'
    
    def __str__(self):
        return f"{self.name} ({self.iata_code})"
