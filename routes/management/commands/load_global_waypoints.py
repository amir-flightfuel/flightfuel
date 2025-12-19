import requests
import csv
from django.contrib.gis.geos import Point
from django.core.management.base import BaseCommand
from routes.models import Waypoint

class Command(BaseCommand):
    help = 'Load global waypoints from OurAirports'
    
    def handle(self, *args, **options):
        url = "https://davidmegginson.github.io/ourairports-data/navaids.csv"
        
        try:
            response = requests.get(url)
            response.encoding = 'utf-8'
            
            reader = csv.DictReader(response.text.splitlines())
            
            waypoints_created = 0
            for row in reader:
                # فیلتر و محدود کردن شناسه
                if (row['type'] in ['VOR', 'NDB', 'DME', 'TACAN'] and 
                    row['latitude_deg'] and row['longitude_deg'] and
                    len(row['ident']) <= 5):  # فقط شناسه‌های تا ۵ کاراکتر
                    
                    waypoint, created = Waypoint.objects.get_or_create(
                        identifier=row['ident'],
                        defaults={
                            'name': row['name'],
                            'location': Point(float(row['longitude_deg']), float(row['latitude_deg'])),
                            'country': row['iso_country'],
                            'type': 'FIX'
                        }
                    )
                    
                    if created:
                        waypoints_created += 1
                    
                    if waypoints_created % 100 == 0:
                        self.stdout.write(f'{waypoints_created} waypoints loaded...')
            
            self.stdout.write(
                self.style.SUCCESS(f'Successfully loaded {waypoints_created} global waypoints')
            )
            
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f'Error loading waypoints: {str(e)}')
            )
