from django.core.management.base import BaseCommand
from django.contrib.gis.geos import Point
from routes.models import Waypoint, Airway, AirwaySegment

class Command(BaseCommand):
    help = 'Load sample waypoints and airway segments for testing'
    
    def handle(self, *args, **options):
        # ایجاد Waypoint های نمونه
        waypoints_data = [
            {'ident': 'THR', 'name': 'TEHRAN', 'lat': 35.6892, 'lon': 51.3890},
            {'ident': 'MHD', 'name': 'MASHHAD', 'lat': 36.2352, 'lon': 59.6410},
            {'ident': 'SYZ', 'name': 'SHIRAZ', 'lat': 29.5392, 'lon': 52.5890},
            {'ident': 'BND', 'name': 'BANDAR', 'lat': 35.5, 'lon': 51.5},
            {'ident': 'ABEDI', 'name': 'ABEDI', 'lat': 35.8, 'lon': 52.0},
        ]
        
        for wp_data in waypoints_data:
            waypoint, created = Waypoint.objects.get_or_create(
                identifier=wp_data['ident'],
                defaults={
                    'name': wp_data['name'],
                    'location': Point(wp_data['lon'], wp_data['lat']),
                    'country': 'Iran'
                }
            )
        
        # ایجاد Airway نمونه
        airway, created = Airway.objects.get_or_create(
            identifier='A10',
            defaults={'name': 'Airway A10', 'type': 'A'}
        )
        
        # ایجاد AirwaySegment های نمونه
        segments_data = [
            {'from_wp': 'THR', 'to_wp': 'BND', 'seq': 1, 'dist': 50},
            {'from_wp': 'BND', 'to_wp': 'ABEDI', 'seq': 2, 'dist': 80},
            {'from_wp': 'ABEDI', 'to_wp': 'MHD', 'seq': 3, 'dist': 600},
        ]
        
        for seg_data in segments_data:
            from_wp = Waypoint.objects.get(identifier=seg_data['from_wp'])
            to_wp = Waypoint.objects.get(identifier=seg_data['to_wp'])
            
            AirwaySegment.objects.get_or_create(
                airway=airway,
                from_waypoint=from_wp,
                to_waypoint=to_wp,
                defaults={
                    'sequence': seg_data['seq'],
                    'distance': seg_data['dist']
                }
            )
        
        self.stdout.write(
            self.style.SUCCESS('Sample waypoints and airway segments loaded successfully')
        )
