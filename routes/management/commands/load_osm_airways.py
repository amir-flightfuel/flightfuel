from django.contrib.gis.geos import Point
from django.core.management.base import BaseCommand
from routes.models import Waypoint, Airway, AirwaySegment
from airports.models import Airport
import math

class Command(BaseCommand):
    help = 'Create sample airway network based on major airports'
    
    def handle(self, *args, **options):
        # فرودگاه‌های اصلی برای ایجاد شبکه
        major_airports = [
            # ایران
            'THR', 'MHD', 'SYZ', 'TBZ', 'KIH', 'AWZ', 'IFN', 'ABD',
            # منطقه
            'DXB', 'DOH', 'AUH', 'BAH', 'KWI', 'RUH', 'JED',
            # اروپا
            'IST', 'FRA', 'CDG', 'LHR', 'AMS', 'MAD', 'FCO',
            # آسیا
            'BKK', 'SIN', 'KUL', 'HKG', 'NRT', 'ICN',
            # آمریکا
            'JFK', 'LAX', 'ORD', 'DFW', 'SFO'
        ]
        
        # ایجاد Waypoint برای فرودگاه‌های اصلی
        waypoint_map = {}
        for iata in major_airports:
            try:
                airport = Airport.objects.get(iata_code=iata)
                waypoint, created = Waypoint.objects.get_or_create(
                    identifier=iata,
                    defaults={
                        'name': f"{airport.name} Waypoint",
                        'location': airport.location,
                        'country': airport.country,
                        'type': 'FIX'
                    }
                )
                waypoint_map[iata] = waypoint
            except Airport.DoesNotExist:
                continue
        
        # ایجاد مسیرهای هوایی نمونه
        airway_routes = [
            {'id': 'A10', 'type': 'A', 'route': ['THR', 'MHD', 'ASB', 'TAS']},
            {'id': 'A20', 'type': 'A', 'route': ['THR', 'SYZ', 'DOH', 'DXB']},
            {'id': 'B30', 'type': 'B', 'route': ['IST', 'THR', 'KIH', 'AUH']},
            {'id': 'G40', 'type': 'G', 'route': ['FRA', 'IST', 'THR', 'KHI']},
        ]
        
        airways_created = 0
        segments_created = 0
        
        for route_data in airway_routes:
            airway, created = Airway.objects.get_or_create(
                identifier=route_data['id'],
                defaults={
                    'name': f"Airway {route_data['id']}",
                    'type': route_data['type']
                }
            )
            
            if created:
                airways_created += 1
            
            # ایجاد Segment ها
            route = route_data['route']
            for i in range(len(route) - 1):
                from_iata = route[i]
                to_iata = route[i + 1]
                
                if from_iata in waypoint_map and to_iata in waypoint_map:
                    from_wp = waypoint_map[from_iata]
                    to_wp = waypoint_map[to_iata]
                    
                    distance = self.calculate_distance(from_wp.location, to_wp.location)
                    
                    segment, seg_created = AirwaySegment.objects.get_or_create(
                        airway=airway,
                        from_waypoint=from_wp,
                        to_waypoint=to_wp,
                        defaults={
                            'sequence': i,
                            'distance': distance
                        }
                    )
                    
                    if seg_created:
                        segments_created += 1
        
        self.stdout.write(
            self.style.SUCCESS(
                f'Created {airways_created} airways and {segments_created} segments'
            )
        )
    
    def calculate_distance(self, point1, point2):
        """محاسبه فاصله بین دو نقطه (کیلومتر)"""
        lat1, lon1 = point1.coords
        lat2, lon2 = point2.coords
        
        R = 6371
        dlat = math.radians(lat2 - lat1)
        dlon = math.radians(lon2 - lon1)
        
        a = (math.sin(dlat/2) * math.sin(dlat/2) + 
             math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * 
             math.sin(dlon/2) * math.sin(dlon/2))
        
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
        return R * c
