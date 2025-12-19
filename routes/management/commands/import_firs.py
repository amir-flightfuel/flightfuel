# routes/management/commands/import_firs.py
import os
import json
from django.core.management.base import BaseCommand
from django.contrib.gis.geos import GEOSGeometry
from routes.models import FlightInformationRegion

class Command(BaseCommand):
    help = 'Import FIR regions from ne_10m_admin_0_countries.geojson file'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--file',
            type=str,
            default='ne_10m_admin_0_countries.geojson',
            help='Path to GeoJSON file'
        )
        parser.add_argument(
            '--clear',
            action='store_true',
            help='Clear existing FIR data before import'
        )
        parser.add_argument(
            '--skip-existing',
            action='store_true',
            help='Skip countries that already exist in database'
        )
    
    def handle(self, *args, **options):
        file_path = options['file']
        
        if options['clear']:
            deleted_count, _ = FlightInformationRegion.objects.all().delete()
            self.stdout.write(self.style.WARNING(f'🗑️ Deleted {deleted_count} existing FIRs'))
        
        if not os.path.exists(file_path):
            self.stdout.write(self.style.ERROR(f'❌ File not found: {file_path}'))
            return
        
        self.stdout.write(f'📂 Reading GeoJSON file: {file_path}')
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                geojson_data = json.load(f)
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'❌ Error reading file: {e}'))
            return
        
        features = geojson_data.get('features', [])
        self.stdout.write(f'🌍 Found {len(features)} countries in GeoJSON')
        
        icao_mapping = self.get_icao_mapping()
        
        imported_count = 0
        skipped_count = 0
        updated_count = 0
        
        for i, feature in enumerate(features, 1):
            try:
                result = self.process_feature(feature, icao_mapping, options['skip_existing'])
                
                if result == 'imported':
                    imported_count += 1
                elif result == 'updated':
                    updated_count += 1
                elif result == 'skipped':
                    skipped_count += 1
                
                if i % 20 == 0:
                    self.stdout.write(f'  📊 Processed {i}/{len(features)} countries...')
                
            except Exception as e:
                skipped_count += 1
                continue
        
        self.print_results(imported_count, updated_count, skipped_count)
        self.check_important_countries()
    
    def process_feature(self, feature, icao_mapping, skip_existing=False):
        properties = feature.get('properties', {})
        geometry = feature.get('geometry', {})
        
        # گرفتن نام کشور و کد ISO - کلیدهای مختلف را چک کن
        country_name = properties.get('NAME') or properties.get('ADMIN') or properties.get('name') or 'Unknown'
        iso_code = properties.get('ISO_A2') or properties.get('ISO_A2_EH') or properties.get('iso_a2') or ''
        iso_code = iso_code.upper()
        
        if not iso_code or iso_code in ['-99', '']:
            return 'skipped'
        
        # شناسه FIR فقط بر اساس ISO Code
        fir_identifier = self.get_fir_identifier(iso_code, icao_mapping)
        
        if skip_existing and FlightInformationRegion.objects.filter(identifier=fir_identifier).exists():
            return 'skipped'
        
        icao_region = self.get_icao_region(iso_code)
        
        try:
            geos_geometry = GEOSGeometry(json.dumps(geometry))
            if hasattr(geos_geometry, 'num_points') and geos_geometry.num_points > 500:
                geos_geometry = geos_geometry.simplify(tolerance=0.01, preserve_topology=True)
        except:
            # اگر geometry مشکل دارد، کشور کوچک است - skip
            return 'skipped'
        
        # تنظیم فرکانس بر اساس منطقه
        frequency = '121.5'
        if icao_region in ['EU', 'NA']:
            frequency = '127.1, 121.5'
        
        # اگر کشور خاصی است، نام FIR خاص بده
        fir_name = f"{country_name.upper()} FLIGHT INFORMATION REGION"
        special_names = {
            'US': 'WASHINGTON FLIGHT INFORMATION REGION',
            'CN': 'BEIJING FLIGHT INFORMATION REGION',
            'RU': 'MOSCOW FLIGHT INFORMATION REGION',
            'GB': 'LONDON FLIGHT INFORMATION REGION',
            'FR': 'PARIS FLIGHT INFORMATION REGION',
            'DE': 'FRANKFURT FLIGHT INFORMATION REGION',
            'JP': 'TOKYO FLIGHT INFORMATION REGION',
            'IN': 'DELHI FLIGHT INFORMATION REGION',
            'AU': 'CANBERRA FLIGHT INFORMATION REGION',
            'BR': 'BRASILIA FLIGHT INFORMATION REGION',
            'CA': 'OTTAWA FLIGHT INFORMATION REGION',
            'IR': 'TEHRAN FLIGHT INFORMATION REGION',
            'SA': 'RIYADH FLIGHT INFORMATION REGION',
            'TR': 'ANKARA FLIGHT INFORMATION REGION',
            'AE': 'ABU DHABI FLIGHT INFORMATION REGION',
        }
        
        if iso_code in special_names:
            fir_name = special_names[iso_code]
        
        fir, created = FlightInformationRegion.objects.update_or_create(
            identifier=fir_identifier,
            defaults={
                'name': fir_name,
                'country': country_name,
                'country_code': iso_code,
                'frequency': frequency,
                'emergency_frequency': '121.5',
                'boundary': geos_geometry,
                'upper_limit': 99999,
                'lower_limit': 0,
                'icao_region': icao_region,
                'is_active': True,
                'notes': f"ISO: {iso_code}"
            }
        )
        
        return 'imported' if created else 'updated'
    
    def get_icao_mapping(self):
        """مپ کد کشور به کد ICAO - فقط بر اساس ISO Code"""
        return {
            # خاورمیانه
            'IR': 'OIIX', 'TR': 'LTAA', 'IQ': 'ORBB', 'SA': 'OEJD',
            'AE': 'OMAE', 'PK': 'OPKR', 'AF': 'OAKX', 'OM': 'OOMM',
            'KW': 'OKAC', 'QA': 'OTBD', 'BH': 'OBBB', 'JO': 'OJAC',
            'LB': 'OLBB', 'SY': 'OSDI', 'YE': 'OYSC', 'IL': 'LLBB',
            
            # اروپا
            'GB': 'EGTT', 'FR': 'LFFF', 'DE': 'EDGG', 'IT': 'LIMM',
            'ES': 'LEMM', 'NL': 'EHAA', 'BE': 'EBBU', 'CH': 'LSAS',
            'AT': 'LOVV', 'PL': 'EPWW', 'SE': 'ESMM', 'NO': 'ENOR',
            'FI': 'EFIN', 'DK': 'EKDK', 'GR': 'LGGG', 'PT': 'LPPC',
            'IE': 'EISN', 'CZ': 'LKAA', 'HU': 'LHCC', 'RO': 'LRBB',
            'BG': 'LBBB', 'RS': 'LYBA', 'HR': 'LDZO', 'SI': 'LJLA',
            
            # آسیا
            'CN': 'ZBPE', 'JP': 'RJJC', 'KR': 'RKRR', 'IN': 'VECF',
            'ID': 'WIIF', 'TH': 'VTBB', 'VN': 'VVVN', 'MY': 'WMSA',
            'PH': 'RPHI', 'SG': 'WSJC', 'MM': 'VYMM', 'KH': 'VDPF',
            'LA': 'VLVT', 'BD': 'VGBF', 'NP': 'VNKT', 'LK': 'VCCC',
            'TW': 'RCAA', 'HK': 'VHHK', 'MO': 'VMMC',
            
            # آمریکای شمالی
            'US': 'KZXX', 'CA': 'CZEG', 'MX': 'MMMX', 'CU': 'MUHA',
            
            # آمریکای جنوبی
            'BR': 'SBAO', 'AR': 'SAAF', 'CL': 'SCEZ', 'CO': 'SKED',
            'PE': 'SPIM', 'VE': 'SVZM', 'EC': 'SEGU',
            
            # آفریقا
            'ZA': 'FACA', 'EG': 'HECC', 'NG': 'DNKK', 'KE': 'HKNA',
            'ET': 'HAAA', 'DZ': 'DAAG', 'MA': 'GMMM',
            
            # اقیانوسیه
            'AU': 'YBBB', 'NZ': 'NZZC',
            
            # روسیه و CIS
            'RU': 'UUWV', 'UA': 'UKDV', 'KZ': 'UAKK', 'UZ': 'UTTT',
            'AZ': 'UBBA', 'BY': 'UMMV', 'GE': 'UGGG', 'AM': 'UDDD',
            'TJ': 'UTDD', 'TM': 'UTAK', 'KG': 'UCFM',
        }
    
    def get_fir_identifier(self, iso_code, icao_mapping):
        """شناسه FIR فقط بر اساس ISO Code"""
        if iso_code in icao_mapping:
            return icao_mapping[iso_code]
        
        # اگر کشور بزرگ است ولی در مپ نیست
        large_countries = ['BD', 'PK', 'NG', 'MX', 'PH', 'ET', 'CD', 'TZ']
        if iso_code in large_countries:
            return f"{iso_code}XX"
        
        # پیش‌فرض
        return f"{iso_code}ZZ"
    
    def get_icao_region(self, iso_code):
        region_map = {
            # خاورمیانه
            'IR': 'ME', 'TR': 'ME', 'IQ': 'ME', 'SA': 'ME', 'AE': 'ME',
            'QA': 'ME', 'KW': 'ME', 'OM': 'ME', 'BH': 'ME', 'JO': 'ME',
            'LB': 'ME', 'SY': 'ME', 'YE': 'ME', 'IL': 'ME', 'PS': 'ME',
            'EG': 'ME', 'AZ': 'ME', 'AM': 'ME', 'GE': 'ME', 'CY': 'ME',
            
            # آسیا
            'CN': 'AS', 'JP': 'AS', 'KR': 'AS', 'IN': 'AS', 'ID': 'AS',
            'TH': 'AS', 'VN': 'AS', 'MY': 'AS', 'PH': 'AS', 'SG': 'AS',
            'MM': 'AS', 'KH': 'AS', 'LA': 'AS', 'BD': 'AS', 'NP': 'AS',
            'LK': 'AS', 'BT': 'AS', 'MN': 'AS', 'KP': 'AS', 'TW': 'AS',
            'HK': 'AS', 'MO': 'AS', 'BN': 'AS', 'TL': 'AS',
            'KZ': 'AS', 'UZ': 'AS', 'TJ': 'AS', 'TM': 'AS', 'KG': 'AS',
            
            # اروپا
            'GB': 'EU', 'FR': 'EU', 'DE': 'EU', 'IT': 'EU', 'ES': 'EU',
            'NL': 'EU', 'BE': 'EU', 'CH': 'EU', 'AT': 'EU', 'PL': 'EU',
            'SE': 'EU', 'NO': 'EU', 'FI': 'EU', 'DK': 'EU', 'GR': 'EU',
            'PT': 'EU', 'IE': 'EU', 'CZ': 'EU', 'HU': 'EU', 'RO': 'EU',
            'BG': 'EU', 'RS': 'EU', 'HR': 'EU', 'SI': 'EU', 'SK': 'EU',
            'LT': 'EU', 'LV': 'EU', 'EE': 'EU', 'LU': 'EU', 'MT': 'EU',
            'CY': 'EU', 'IS': 'EU', 'AL': 'EU', 'MK': 'EU', 'BA': 'EU',
            'ME': 'EU', 'MD': 'EU', 'UA': 'EU', 'BY': 'EU',
            
            # آفریقا
            'ZA': 'AF', 'NG': 'AF', 'KE': 'AF', 'ET': 'AF', 'DZ': 'AF',
            'MA': 'AF', 'TN': 'AF', 'LY': 'AF', 'SD': 'AF', 'GH': 'AF',
            'CI': 'AF', 'CM': 'AF', 'MG': 'AF', 'MZ': 'AF', 'UG': 'AF',
            'CD': 'AF', 'TZ': 'AF', 'ZW': 'AF',
            
            # آمریکای شمالی
            'US': 'NA', 'CA': 'NA', 'MX': 'NA', 'CU': 'NA',
            
            # آمریکای جنوبی
            'BR': 'SA', 'AR': 'SA', 'CL': 'SA', 'CO': 'SA', 'PE': 'SA',
            'VE': 'SA', 'EC': 'SA',
            
            # اقیانوسیه
            'AU': 'PA', 'NZ': 'PA',
            
            # روسیه
            'RU': 'EU',
        }
        
        return region_map.get(iso_code, 'AS')
    
    def print_results(self, imported, updated, skipped):
        self.stdout.write(self.style.SUCCESS('\n' + '='*60))
        self.stdout.write(self.style.SUCCESS('✅ IMPORT COMPLETED SUCCESSFULLY'))
        self.stdout.write(self.style.SUCCESS(f'📊 Newly Imported: {imported} FIRs'))
        self.stdout.write(self.style.SUCCESS(f'📊 Updated: {updated} existing FIRs'))
        self.stdout.write(self.style.WARNING(f'⚠️ Skipped: {skipped} countries'))
        
        total_in_db = FlightInformationRegion.objects.count()
        self.stdout.write(self.style.SUCCESS(f'🗄️ Total FIRs in database: {total_in_db}'))
        self.stdout.write(self.style.SUCCESS('='*60))
    
    def check_important_countries(self):
        important = [
            ('Iran', 'OIIX'),
            ('France', 'LFFF'),
            ('Norway', 'ENOR'),
            ('Germany', 'EDGG'),
            ('United Kingdom', 'EGTT'),
            ('Spain', 'LEMM'),
            ('Italy', 'LIMM'),
            ('China', 'ZBPE'),
            ('Japan', 'RJJC'),
            ('India', 'VECF'),
            ('United States', 'KZXX'),
            ('Russia', 'UUWV'),
            ('Saudi Arabia', 'OEJD'),
            ('Turkey', 'LTAA'),
            ('Oman', 'OOMM'),
            ('United Arab Emirates', 'OMAE'),
            ('Pakistan', 'OPKR'),
        ]
        
        self.stdout.write("\n🔍 Important Countries Check:")
        all_good = True
        
        for country_name, expected_code in important:
            # جستجوی هوشمند برای نام کشور
            search_terms = [country_name]
            if ' ' in country_name:
                search_terms.append(country_name.split()[0])  # قسمت اول
            
            fir = None
            for term in search_terms:
                fir = FlightInformationRegion.objects.filter(
                    country__icontains=term
                ).first()
                if fir:
                    break
            
            if fir:
                if fir.identifier == expected_code:
                    self.stdout.write(self.style.SUCCESS(f'  ✅ {country_name}: {fir.identifier}'))
                else:
                    self.stdout.write(self.style.ERROR(f'  ❌ {country_name}: {fir.identifier} (expected {expected_code})'))
                    all_good = False
            else:
                self.stdout.write(self.style.ERROR(f'  ❌ {country_name}: NOT FOUND'))
                all_good = False
        
        if all_good:
            self.stdout.write(self.style.SUCCESS("\n🎉 All important countries imported correctly!"))
        else:
            self.stdout.write(self.style.ERROR("\n⚠️ Some countries have issues. Check above."))
