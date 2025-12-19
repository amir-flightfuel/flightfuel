import requests
import csv
from django.contrib.gis.geos import Point
from django.core.management.base import BaseCommand
from airports.models import Airport

class Command(BaseCommand):
    help = 'بارگذاری فرودگاه‌های جهانی از OurAirports'
    
    def handle(self, *args, **options):
        url = "https://davidmegginson.github.io/ourairports-data/airports.csv"
        
        try:
            response = requests.get(url)
            response.encoding = 'utf-8'
            
            reader = csv.DictReader(response.text.splitlines())
            
            airports_created = 0
            for row in reader:
                # فقط فرودگاه‌های فعال و دارای کد IATA
                if (row['type'] in ['large_airport', 'medium_airport', 'small_airport'] and 
                    row['iata_code'] and 
                    row['scheduled_service'] == 'yes'):
                    
                    # بررسی وجود فرودگاه
                    if Airport.objects.filter(iata_code=row['iata_code']).exists():
                        continue
                    
                    # محدود کردن icao_code به ۴ کاراکتر
                    icao_code = row['ident'][:4] if row['ident'] else ''
                    
                    airport = Airport(
                        name=row['name'],
                        iata_code=row['iata_code'],
                        icao_code=icao_code,
                        location=Point(float(row['longitude_deg']), float(row['latitude_deg'])),
                        altitude=float(row['elevation_ft']) * 0.3048 if row['elevation_ft'] else 0,
                        airport_type=row['type'],
                        country=row['iso_country'],
                        city=row['municipality'] or '',
                        runway_length=float(row['length_ft']) * 0.3048 if row.get('length_ft') else None
                    )
                    airport.save()
                    airports_created += 1
                    
                    if airports_created % 100 == 0:
                        self.stdout.write(f'{airports_created} فرودگاه بارگذاری شد...')
            
            self.stdout.write(
                self.style.SUCCESS(f'تعداد {airports_created} فرودگاه بارگذاری شد')
            )
            
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f'خطا در بارگذاری: {str(e)}')
            )
