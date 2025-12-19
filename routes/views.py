from django.http import JsonResponse
from django.shortcuts import render
from rest_framework import viewsets, filters, status
from rest_framework.response import Response
from rest_framework.decorators import action
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticatedOrReadOnly
from django.contrib.gis.geos import Point, LineString
from django.db.models import Q
import json
import re
import math

from .models import Waypoint, Airway, AirwaySegment, Route, FlightInformationRegion
from .serializers import (
    WaypointSerializer, AirwaySerializer,
    AirwaySegmentSerializer, RouteSerializer,
    FlightInformationRegionSerializer
)
from airports.models import Airport
from django.contrib.auth.models import User

# ==================== توابع کمکی ====================

def get_icao_code(code):
    """
    تبدیل کد فرودگاه به ICAO
    - اگر 4 حرفی و فقط حروف باشد: فرض ICAO است
    - اگر 3 حرفی و فقط حروف باشد: جستجو در IATA و تبدیل به ICAO
    - در غیر این صورت: None
    
    مثال:
    get_icao_code('THR') → 'OIII'  (IATA به ICAO)
    get_icao_code('OIII') → 'OIII' (ICAO بدون تغییر)
    get_icao_code('XYZ') → None    (یافت نشد)
    """
    if not code:
        return None
    
    code = code.upper().strip()
    
    # اگر 4 حرفی و فقط حروف (ICAO)
    if len(code) == 4 and code.isalpha():
        # بررسی وجود در airports
        try:
            airport = Airport.objects.filter(icao_code=code).first()
            if airport:
                return airport.icao_code
        except Exception:
            pass
        return code  # حتی اگر در دیتابیس نبود، بازگردانده شود (ممکن است در Route ذخیره شده باشد)
    
    # اگر 3 حرفی و فقط حروف (IATA)
    elif len(code) == 3 and code.isalpha():
        try:
            airport = Airport.objects.filter(iata_code=code).first()
            if airport:
                return airport.icao_code
        except Exception:
            pass
        return None  # اگر IATA پیدا نشد
    
    return None  # فرمت نامعتبر

def validate_airport_code(code):
    """
    اعتبارسنجی کد فرودگاه و برگرداندن اطلاعات
    """
    if not code:
        return {'valid': False, 'error': 'کد فرودگاه خالی است'}
    
    code = code.upper().strip()
    
    # بررسی طول
    if len(code) not in [3, 4]:
        return {
            'valid': False, 
            'error': 'کد فرودگاه باید ۳ حرفی (IATA) یا ۴ حرفی (ICAO) باشد',
            'input': code
        }
    
    # بررسی حروف
    if not code.isalpha():
        return {
            'valid': False,
            'error': 'کد فرودگاه باید فقط شامل حروف باشد',
            'input': code
        }
    
    # تبدیل به ICAO
    icao_code = get_icao_code(code)
    
    if not icao_code:
        return {
            'valid': False,
            'error': f'کد فرودگاه "{code}" در پایگاه داده یافت نشد',
            'input': code,
            'suggestion': 'از کد IATA (THR) یا ICAO (OIII) معتبر استفاده کنید'
        }
    
    # پیدا کردن اطلاعات فرودگاه
    airport = Airport.objects.filter(
        Q(icao_code=icao_code) | Q(iata_code=code)
    ).first()
    
    return {
        'valid': True,
        'input': code,
        'icao': icao_code,
        'airport': airport
    }

def parse_route_text(route_text):
    """پارس کردن متن مسیر - پشتیبانی از IATA و ICAO"""
    try:
        parts = [p for p in route_text.split() if p not in ['DCT']]
        
        if len(parts) < 2:
            return None
            
        departure = parts[0]
        arrival = parts[-1]
        
        waypoints = []
        coordinates = []
        
        # اضافه کردن مختصات برای هر بخش
        for part in parts:
            # تشخیص نوع کد (IATA یا ICAO)
            is_airport = False
            airport = None
            
            # اگر 3 حرفی است (IATA)
            if len(part) == 3 and part.isalpha():
                airport = Airport.objects.filter(iata_code=part).first()
                if airport:
                    is_airport = True
            
            # اگر 4 حرفی است (ICAO)  
            if not airport and len(part) == 4 and part.isalpha():
                airport = Airport.objects.filter(icao_code=part).first()
                if airport:
                    is_airport = True
            
            # اگر فرودگاه پیدا شد
            if is_airport and airport:
                coordinates.append([airport.location.x, airport.location.y])
                if part not in [departure, arrival]:
                    waypoints.append(part)
                continue
                
            # اگر waypoint است
            waypoint = Waypoint.objects.filter(identifier=part).first()
            if waypoint:
                coordinates.append([waypoint.location.x, waypoint.location.y])
                waypoints.append(part)
                continue
                
            # اگر airway است - نادیده بگیر
            if re.match(r'^[ABGRULMNZW]\d+', part):
                continue
                
            # اگر SID/STAR است - نادیده بگیر
            if re.match(r'.*[0-9][A-Z]$', part):
                continue
        
        # اگر مختصات کافی نداریم
        if len(coordinates) < 2:
            return None
            
        # محاسبه مسافت
        total_distance = calculate_route_distance(coordinates)
        
        return {
            'departure': departure,
            'arrival': arrival,
            'waypoints': waypoints,
            'coordinates': coordinates,
            'total_distance': total_distance
        }
        
    except Exception as e:
        print(f"Parse error: {e}")
        return None

def calculate_route_distance(coordinates):
    """محاسبه مسافت کل مسیر"""
    total_distance = 0
    for i in range(len(coordinates) - 1):
        coord1 = coordinates[i]
        coord2 = coordinates[i + 1]
        total_distance += calculate_distance_nm(coord1, coord2)
    return total_distance

def calculate_distance_nm(coord1, coord2):
    """محاسبه فاصله بین دو نقطه به ناتیکال مایل"""
    lon1, lat1 = coord1
    lon2, lat2 = coord2
    
    R = 3440.065  # شعاع زمین به ناتیکال مایل
    dLat = (lat2 - lat1) * math.pi / 180
    dLon = (lon2 - lon1) * math.pi / 180
    
    a = (math.sin(dLat/2) * math.sin(dLat/2) +
         math.cos(lat1 * math.pi / 180) * math.cos(lat2 * math.pi / 180) *
         math.sin(dLon/2) * math.sin(dLon/2))
    
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    return R * c

# ==================== ViewSet های DRF (برای API REST) ====================

class WaypointViewSet(viewsets.ModelViewSet):
    queryset = Waypoint.objects.all()
    serializer_class = WaypointSerializer
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['identifier', 'name', 'country', 'type']
    ordering_fields = ['identifier', 'name', 'type']
    permission_classes = [IsAuthenticatedOrReadOnly]
    
    @action(detail=False, methods=['GET'])
    def by_type(self, request):
        wp_type = request.query_params.get('type')
        if wp_type:
            waypoints = Waypoint.objects.filter(type=wp_type)
        else:
            waypoints = Waypoint.objects.all()
        serializer = self.get_serializer(waypoints, many=True)
        return Response(serializer.data)

class AirwayViewSet(viewsets.ModelViewSet):
    queryset = Airway.objects.all()
    serializer_class = AirwaySerializer
    permission_classes = [IsAuthenticatedOrReadOnly]
    
    @action(detail=True, methods=['GET'])
    def segments(self, request, pk=None):
        airway = self.get_object()
        segments = airway.segments.all()
        serializer = AirwaySegmentSerializer(segments, many=True)
        return Response(serializer.data)

class AirwaySegmentViewSet(viewsets.ModelViewSet):
    queryset = AirwaySegment.objects.all()
    serializer_class = AirwaySegmentSerializer
    permission_classes = [IsAuthenticatedOrReadOnly]

class RouteViewSet(viewsets.ModelViewSet):
    queryset = Route.objects.all()
    serializer_class = RouteSerializer
    permission_classes = [IsAuthenticatedOrReadOnly]
    
    def create(self, request, *args, **kwargs):
        # اضافه کردن created_by از کاربر فعلی
        if request.user.is_authenticated:
            request.data['created_by'] = request.user.id
        return super().create(request, *args, **kwargs)
    
    def update(self, request, *args, **kwargs):
        # اضافه کردن updated_by از کاربر فعلی
        if request.user.is_authenticated:
            request.data['updated_by'] = request.user.id
        return super().update(request, *args, **kwargs)
    
    @action(detail=False, methods=['POST'])
    def calculate(self, request):
        try:
            departure = request.data.get('departure')
            arrival = request.data.get('arrival')
            
            if not departure or not arrival:
                return Response(
                    {'error': 'Departure and arrival are required'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # محاسبه مسیرها
            result = self.calculate_routes(departure, arrival)
            
            return Response(result)
            
        except Exception as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=False, methods=['GET'])
    def map_data(self, request):
        """داده‌های نقشه برای فرانت‌اند"""
        waypoints = Waypoint.objects.filter(is_active=True)[:500]
        airways = Airway.objects.all()
        segments = AirwaySegment.objects.select_related('airway', 'from_waypoint', 'to_waypoint').all()
        
        waypoint_data = WaypointSerializer(waypoints, many=True).data
        airway_data = []
        
        for airway in airways:
            airway_segments = segments.filter(airway=airway)
            if airway_segments:
                airway_data.append({
                    'id': airway.id,
                    'identifier': airway.identifier,
                    'name': airway.name,
                    'type': airway.type,
                    'segments': AirwaySegmentSerializer(airway_segments, many=True).data
                })
        
        return Response({
            'waypoints': waypoint_data,
            'airways': airway_data
        })
    
    @action(detail=False, methods=['GET'])
    def search(self, request):
        """
        جستجوی مسیرهای ذخیره شده بر اساس مبدا و مقصد
        
        مثال:
        GET /api/routes/search/?origin=OIII&destination=OIMM
        GET /api/routes/search/?origin=THR&destination=MHD
        """
        try:
            origin = request.query_params.get('origin', '').strip().upper()
            destination = request.query_params.get('destination', '').strip().upper()
            
            if not origin or not destination:
                return Response({
                    'error': 'Both origin and destination airport codes are required',
                    'example': '/api/routes/search/?origin=THR&destination=MHD'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # تبدیل به ICAO
            origin_icao = get_icao_code(origin)
            destination_icao = get_icao_code(destination)
            
            if not origin_icao:
                return Response({
                    'error': f'Origin airport code not found: {origin}',
                    'suggestion': 'Use 3-letter IATA (e.g., THR) or 4-letter ICAO (e.g., OIII)'
                }, status=status.HTTP_404_NOT_FOUND)
            
            if not destination_icao:
                return Response({
                    'error': f'Destination airport code not found: {destination}',
                    'suggestion': 'Use 3-letter IATA (e.g., MHD) or 4-letter ICAO (e.g., OIMM)'
                }, status=status.HTTP_404_NOT_FOUND)
            
            if origin_icao == destination_icao:
                return Response({
                    'error': 'Origin and destination cannot be the same airport'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # جستجوی مسیرها
            routes = Route.objects.filter(
                departure__iexact=origin_icao,
                arrival__iexact=destination_icao
            ).order_by('total_distance', '-created_at')
            
            # جستجوی دوطرفه (مبدا/مقصد معکوس)
            if not routes.exists():
                routes = Route.objects.filter(
                    departure__iexact=destination_icao,
                    arrival__iexact=origin_icao
                ).order_by('total_distance', '-created_at')
            
            # اگر هنوز هیچ مسیری پیدا نشد
            if not routes.exists():
                return Response({
                    'message': f'No saved routes found from {origin} ({origin_icao}) to {destination} ({destination_icao})',
                    'origin': origin,
                    'origin_icao': origin_icao,
                    'destination': destination,
                    'destination_icao': destination_icao,
                    'count': 0,
                    'routes': []
                }, status=status.HTTP_200_OK)
            
            # سریالایز کردن نتایج
            serializer = RouteSerializer(routes, many=True)
            
            # پیدا کردن اطلاعات فرودگاه‌ها
            origin_airport = Airport.objects.filter(
                Q(icao_code=origin_icao) | Q(iata_code=origin)
            ).first()
            
            destination_airport = Airport.objects.filter(
                Q(icao_code=destination_icao) | Q(iata_code=destination)
            ).first()
            
            return Response({
                'message': f'Found {len(routes)} route(s) from {origin} to {destination}',
                'origin': origin,
                'origin_icao': origin_icao,
                'origin_name': origin_airport.name if origin_airport else origin_icao,
                'destination': destination,
                'destination_icao': destination_icao,
                'destination_name': destination_airport.name if destination_airport else destination_icao,
                'count': len(routes),
                'routes': serializer.data
            }, status=status.HTTP_200_OK)
            
        except Exception as e:
            return Response({
                'error': f'Search error: {str(e)}',
                'detail': 'Please check the API logs for more information'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    @action(detail=False, methods=['GET'])
    def search_by_airport(self, request):
        """
        جستجوی همه مسیرهای مرتبط با یک فرودگاه
        
        مثال:
        GET /api/routes/search_by_airport/?airport=OIII
        GET /api/routes/search_by_airport/?airport=THR
        """
        try:
            airport_code = request.query_params.get('airport', '').strip().upper()
            
            if not airport_code:
                return Response({
                    'error': 'Airport code is required',
                    'example': '/api/routes/search_by_airport/?airport=THR'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # تبدیل به ICAO
            airport_icao = get_icao_code(airport_code)
            
            if not airport_icao:
                return Response({
                    'error': f'Airport code not found: {airport_code}',
                    'suggestion': 'Use 3-letter IATA (e.g., THR) or 4-letter ICAO (e.g., OIII)'
                }, status=status.HTTP_404_NOT_FOUND)
            
            # جستجوی مسیرهایی که این فرودگاه مبدا یا مقصد آنهاست
            routes = Route.objects.filter(
                Q(departure__iexact=airport_icao) | Q(arrival__iexact=airport_icao)
            ).order_by('departure', 'arrival', 'total_distance')
            
            if not routes.exists():
                # پیدا کردن اطلاعات فرودگاه
                airport = Airport.objects.filter(
                    Q(icao_code=airport_icao) | Q(iata_code=airport_code)
                ).first()
                
                airport_name = airport.name if airport else airport_icao
                
                return Response({
                    'message': f'No routes found for airport {airport_code} ({airport_name})',
                    'airport': airport_code,
                    'airport_icao': airport_icao,
                    'airport_name': airport_name,
                    'count': 0,
                    'routes': []
                }, status=status.HTTP_200_OK)
            
            # گروه‌بندی نتایج
            departures = routes.filter(departure__iexact=airport_icao)
            arrivals = routes.filter(arrival__iexact=airport_icao)
            
            departures_serializer = RouteSerializer(departures, many=True)
            arrivals_serializer = RouteSerializer(arrivals, many=True)
            
            # پیدا کردن اطلاعات فرودگاه
            airport = Airport.objects.filter(
                Q(icao_code=airport_icao) | Q(iata_code=airport_code)
            ).first()
            
            airport_name = airport.name if airport else airport_icao
            
            return Response({
                'message': f'Found {len(routes)} route(s) for airport {airport_code} ({airport_name})',
                'airport': airport_code,
                'airport_icao': airport_icao,
                'airport_name': airport_name,
                'departures_count': departures.count(),
                'arrivals_count': arrivals.count(),
                'total_count': len(routes),
                'departures': departures_serializer.data,
                'arrivals': arrivals_serializer.data
            }, status=status.HTTP_200_OK)
            
        except Exception as e:
            return Response({
                'error': f'Search error: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    def calculate_routes(self, departure, arrival):
        """محاسبه مسیرهای مختلف"""
        result = {
            'departure': departure,
            'arrival': arrival,
            'routes': {}
        }
        
        # ۱. مسیر مستقیم
        result['routes']['direct'] = self.calculate_direct_route(departure, arrival)
        
        # ۲. مسیر با استفاده از airwayها
        result['routes']['airway'] = self.calculate_airway_route(departure, arrival)
        
        # ۳. مسیر با نقاط میانی
        result['routes']['via_waypoints'] = self.calculate_via_waypoints(departure, arrival)
        
        return result
    
    def calculate_direct_route(self, departure, arrival):
        """محاسبه مسیر مستقیم"""
        try:
            dep_wp = Waypoint.objects.get(identifier=departure)
            arr_wp = Waypoint.objects.get(identifier=arrival)
            
            distance_deg = dep_wp.location.distance(arr_wp.location)
            distance_nm = round(distance_deg * 60.11, 2)  # مایل دریایی
            
            return {
                'type': 'DIRECT',
                'waypoints': [departure, arrival],
                'distance': distance_nm,
                'description': f'Direct route from {departure} to {arrival}'
            }
        except Waypoint.DoesNotExist:
            return {'error': 'Waypoint not found'}
    
    def calculate_airway_route(self, departure, arrival):
        """محاسبه مسیر با استفاده از airwayها"""
        # اینجا باید الگوریتم Dijkstra یا A* برای شبکه airwayها پیاده‌سازی شود
        # فعلاً یک نمونه ساده
        return {
            'type': 'AIRWAY',
            'waypoints': [],
            'distance': 0,
            'description': 'Airway route calculation not implemented yet'
        }
    
    def calculate_via_waypoints(self, departure, arrival):
        """محاسبه مسیر با نقاط میانی"""
        try:
            dep_wp = Waypoint.objects.get(identifier=departure)
            arr_wp = Waypoint.objects.get(identifier=arrival)
            
            # پیدا کردن نقاط میانی نزدیک
            waypoints = Waypoint.objects.filter(
                Q(location__dwithin=(dep_wp.location, 2.0)) |  # حدود 120 ناتیکال مایل
                Q(location__dwithin=(arr_wp.location, 2.0))
            ).exclude(
                Q(identifier=departure) | Q(identifier=arrival)
            )[:5]
            
            waypoint_list = [departure]
            waypoint_list.extend([wp.identifier for wp in waypoints])
            waypoint_list.append(arrival)
            
            return {
                'type': 'VIA_WAYPOINTS',
                'waypoints': waypoint_list,
                'distance': self.calculate_distance_for_waypoints(waypoint_list),
                'description': f'Route via {len(waypoint_list)-2} intermediate waypoints'
            }
        except Waypoint.DoesNotExist:
            return {'error': 'Waypoint not found'}
    
    def calculate_distance_for_waypoints(self, waypoints):
        """محاسبه مسافت برای لیست waypoints"""
        total_nm = 0
        for i in range(len(waypoints) - 1):
            try:
                wp1 = Waypoint.objects.get(identifier=waypoints[i])
                wp2 = Waypoint.objects.get(identifier=waypoints[i + 1])
                
                distance_deg = wp1.location.distance(wp2.location)
                total_nm += distance_deg * 60.11
            except Waypoint.DoesNotExist:
                continue
        
        return round(total_nm, 2)

class FlightInformationRegionViewSet(viewsets.ModelViewSet):
    """ViewSet برای مناطق اطلاعات پرواز (FIR)"""
    queryset = FlightInformationRegion.objects.all()
    serializer_class = FlightInformationRegionSerializer
    permission_classes = [IsAuthenticatedOrReadOnly]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['identifier', 'name', 'country']
    ordering_fields = ['identifier', 'name', 'country']

# ==================== API های کاربردی (برای Frontend) ====================

class AirportGeoJSON(APIView):
    def get(self, request):
        airports = Airport.objects.all()
        
        features = []
        for airport in airports:
            feature = {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [airport.location.x, airport.location.y]
                },
                "properties": {
                    "name": airport.name,
                    "iata": airport.iata_code,
                    "icao": airport.icao_code,
                    "city": airport.city
                }
            }
            features.append(feature)
        
        geojson = {
            "type": "FeatureCollection",
            "features": features
        }
        
        return JsonResponse(geojson)

class WaypointGeoJSON(APIView):
    def get(self, request):
        waypoints = Waypoint.objects.all()
        
        features = []
        for waypoint in waypoints:
            feature = {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [waypoint.location.x, waypoint.location.y]
                },
                "properties": {
                    "identifier": waypoint.identifier,
                    "name": waypoint.name,
                    "type": waypoint.type,
                    "country": waypoint.country
                }
            }
            features.append(feature)
        
        geojson = {
            "type": "FeatureCollection",
            "features": features
        }
        
        return JsonResponse(geojson)

class FIRGeoJSON(APIView):
    """GeoJSON مناطق FIR برای Frontend - نسخه کامل با پشتیبانی MultiPolygon"""
    def get(self, request):
        regions = FlightInformationRegion.objects.filter(is_active=True)
        
        features = []
        for region in regions:
            if region.boundary:
                try:
                    import json
                    
                    # گرفتن GeoJSON از geometry
                    geojson_str = region.boundary.geojson
                    geojson_dict = json.loads(geojson_str)
                    
                    # ایجاد feature
                    feature = {
                        "type": "Feature",
                        "geometry": geojson_dict,  # همینجا MultiPolygon را قبول می‌کند
                        "properties": {
                            "id": region.id,
                            "identifier": region.identifier,
                            "name": region.name,
                            "country": region.country,
                            "country_code": region.country_code,
                            "frequency": region.frequency,
                            "emergency_frequency": region.emergency_frequency,
                            "upper_limit": region.upper_limit,
                            "lower_limit": region.lower_limit,
                            "icao_region": region.icao_region,
                            "area_km2": region.get_area_km2()
                        }
                    }
                    features.append(feature)
                    
                except Exception as e:
                    print(f"Error processing FIR {region.identifier}: {e}")
                    # بازگشت به geometry ساده
                    try:
                        # گرفتن envelope (مستطیل محیطی)
                        bbox = region.boundary.envelope
                        feature = {
                            "type": "Feature",
                            "geometry": {
                                "type": "Polygon",
                                "coordinates": [list(bbox.coords[0])]
                            },
                            "properties": {
                                "id": region.id,
                                "identifier": region.identifier,
                                "name": f"{region.name} (APPROXIMATE)",
                                "country": region.country,
                                "country_code": region.country_code,
                                "frequency": region.frequency,
                                "notes": "Simplified boundary due to parsing error"
                            }
                        }
                        features.append(feature)
                    except:
                        continue
        
        geojson = {
            "type": "FeatureCollection",
            "features": features
        }
        
        return JsonResponse(geojson, json_dumps_params={'ensure_ascii': False})

class CalculateRoute(APIView):
    def post(self, request):
        try:
            # استفاده از request.data به جای request.body
            departure = request.data.get('departure')
            arrival = request.data.get('arrival')
            
            if not departure or not arrival:
                return JsonResponse({'error': 'Departure and arrival required'}, status=400)
            
            from .routing import AirwayRouter
            router = AirwayRouter()
            route = router.find_route(departure, arrival)
            
            if route:
                return JsonResponse(route)
            else:
                return JsonResponse({'error': 'No route found'}, status=404)
                
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)

class SaveRouteAPI(APIView):
    def post(self, request):
        try:
            # استفاده از request.data
            data = request.data
            
            # ایجاد مسیر جدید
            route = Route.objects.create(
                name=data.get('name', 'New Route'),
                departure=data['departure'],
                arrival=data['arrival'],
                waypoints=data['waypoints'],
                coordinates=LineString(data['coordinates']),
                total_distance=data['total_distance'],
                created_by=User.objects.first()  # فعلاً کاربر اول
            )
            
            return JsonResponse({
                'status': 'success', 
                'route_id': route.id,
                'message': 'Route saved successfully'
            })
            
        except Exception as e:
            return JsonResponse({
                'status': 'error',
                'message': str(e)
            }, status=400)

class GetRoutesAPI(APIView):
    def get(self, request):
        try:
            routes = Route.objects.all().order_by('-created_at')
            
            routes_data = []
            for route in routes:
                # تبدیل LineString به لیست مختصات
                coordinates = []
                if route.coordinates:
                    try:
                        # اگر coordinates یک LineString Django GIS است
                        if hasattr(route.coordinates, 'coords'):
                            coordinates = list(route.coordinates.coords)
                        else:
                            # اگر JSONField است یا فرمت دیگر
                            coordinates = route.coordinates
                    except Exception as e:
                        print(f"Error converting coordinates for route {route.id}: {e}")
                        coordinates = []
                
                routes_data.append({
                    'id': route.id,
                    'name': route.name,
                    'departure': route.departure,
                    'arrival': route.arrival,
                    'total_distance': route.total_distance,
                    'flight_time': route.flight_time,
                    'waypoints': route.waypoints,
                    'coordinates': coordinates,
                    'created_by': route.created_by.username if route.created_by else 'Unknown',
                    'created_at': route.created_at.strftime('%Y-%m-%d %H:%M'),
                })
            
            return JsonResponse({
                'status': 'success',
                'routes': routes_data
            })
            
        except Exception as e:
            return JsonResponse({
                'status': 'error',
                'message': str(e)
            }, status=400)

class DeleteRouteAPI(APIView):
    def delete(self, request, route_id):
        try:
            route = Route.objects.get(id=route_id)
            route.delete()
            
            return JsonResponse({
                'status': 'success',
                'message': 'Route deleted successfully'
            })
            
        except Route.DoesNotExist:
            return JsonResponse({
                'status': 'error',
                'message': 'Route not found'
            }, status=404)
        except Exception as e:
            return JsonResponse({
                'status': 'error',
                'message': str(e)
            }, status=400)

class ImportRouteAPI(APIView):
    def post(self, request):
        try:
            # استفاده از request.data
            route_text = request.data.get('route_text', '').strip()
            
            if not route_text:
                return JsonResponse({
                    'status': 'error',
                    'message': 'Route text is required'
                }, status=400)
            
            # پارس کردن مسیر
            parsed_route = parse_route_text(route_text)
            
            if not parsed_route:
                return JsonResponse({
                    'status': 'error', 
                    'message': 'Could not parse route'
                }, status=400)
            
            # ذخیره مسیر
            route = Route.objects.create(
                name=f"Imported: {parsed_route['departure']} to {parsed_route['arrival']}",
                departure=parsed_route['departure'],
                arrival=parsed_route['arrival'],
                waypoints=parsed_route['waypoints'],
                coordinates=LineString(parsed_route['coordinates']),
                total_distance=parsed_route['total_distance'],
                created_by=User.objects.first()
            )
            
            return JsonResponse({
                'status': 'success',
                'route_id': route.id,
                'route': {
                    'name': route.name,
                    'departure': route.departure,
                    'arrival': route.arrival,
                    'coordinates': route.coordinates.coords
                }
            })
            
        except Exception as e:
            return JsonResponse({
                'status': 'error',
                'message': str(e)
            }, status=400)

# ==================== API Route Search (برای Frontend جدید) ====================

class RouteSearchAPI(APIView):
    """
    API جستجوی مسیرهای ذخیره شده با پشتیبانی از IATA و ICAO
    
    مثال استفاده:
    GET /api/route-search/?origin=OIII&destination=OIMM
    GET /api/route-search/?origin=THR&destination=MHD
    GET /api/route-search/?origin=thr&destination=mhd  (حروف کوچک هم کار می‌کند)
    """
    
    permission_classes = [IsAuthenticatedOrReadOnly]
    
    def get(self, request):
        try:
            # گرفتن پارامترها
            origin = request.GET.get('origin', '').strip().upper()
            destination = request.GET.get('destination', '').strip().upper()
            
            # اعتبارسنجی
            if not origin or not destination:
                return JsonResponse({
                    'status': 'error',
                    'message': 'Both origin and destination airport codes are required',
                    'example_iata': '/api/route-search/?origin=THR&destination=MHD',
                    'example_icao': '/api/route-search/?origin=OIII&destination=OIMM'
                }, status=400)
            
            # اعتبارسنجی طول و حروف
            if len(origin) not in [3, 4] or not origin.isalpha():
                return JsonResponse({
                    'status': 'error',
                    'message': 'Origin must be a 3-letter IATA or 4-letter ICAO code',
                    'input': origin,
                    'example_iata': 'THR, MHD, SYZ',
                    'example_icao': 'OIII, OIMM, OISS'
                }, status=400)
            
            if len(destination) not in [3, 4] or not destination.isalpha():
                return JsonResponse({
                    'status': 'error',
                    'message': 'Destination must be a 3-letter IATA or 4-letter ICAO code',
                    'input': destination,
                    'example_iata': 'THR, MHD, SYZ',
                    'example_icao': 'OIII, OIMM, OISS'
                }, status=400)
            
            # تبدیل به ICAO
            origin_icao = get_icao_code(origin)
            destination_icao = get_icao_code(destination)
            
            # بررسی وجود فرودگاه‌ها
            if not origin_icao:
                return JsonResponse({
                    'status': 'error',
                    'message': f'Origin airport code not found: {origin}',
                    'input': origin,
                    'suggestion': 'Use a valid 3-letter IATA code (e.g., THR) or 4-letter ICAO code (e.g., OIII)'
                }, status=404)
            
            if not destination_icao:
                return JsonResponse({
                    'status': 'error',
                    'message': f'Destination airport code not found: {destination}',
                    'input': destination,
                    'suggestion': 'Use a valid 3-letter IATA code (e.g., MHD) or 4-letter ICAO code (e.g., OIMM)'
                }, status=404)
            
            if origin_icao == destination_icao:
                return JsonResponse({
                    'status': 'error',
                    'message': 'Origin and destination cannot be the same airport',
                    'origin': origin,
                    'origin_icao': origin_icao,
                    'destination': destination,
                    'destination_icao': destination_icao
                }, status=400)
            
            # پیدا کردن اطلاعات فرودگاه‌ها
            origin_airport = Airport.objects.filter(
                Q(icao_code=origin_icao) | Q(iata_code=origin)
            ).first()
            
            destination_airport = Airport.objects.filter(
                Q(icao_code=destination_icao) | Q(iata_code=destination)
            ).first()
            
            # جستجوی مسیرها
            routes = Route.objects.filter(
                departure__iexact=origin_icao,
                arrival__iexact=destination_icao
            ).order_by('total_distance', '-created_at')
            
            # جستجوی دوطرفه (اگر هیچ مسیری پیدا نشد)
            if not routes.exists():
                routes = Route.objects.filter(
                    departure__iexact=destination_icao,
                    arrival__iexact=origin_icao
                ).order_by('total_distance', '-created_at')
            
            # آماده‌سازی پاسخ
            routes_list = []
            for route in routes:
                # تبدیل LineString به لیست مختصات
                coordinates = []
                if route.coordinates:
                    try:
                        if hasattr(route.coordinates, 'coords'):
                            coordinates = list(route.coordinates.coords)
                        else:
                            coordinates = route.coordinates
                    except:
                        pass
                
                route_data = {
                    'id': route.id,
                    'name': route.name,
                    'departure': route.departure,
                    'arrival': route.arrival,
                    'total_distance': route.total_distance,
                    'flight_time': route.flight_time,
                    'waypoints': route.waypoints,
                    'coordinates': coordinates,
                    'coordinates_geojson': {
                        'type': 'LineString',
                        'coordinates': coordinates
                    } if coordinates else None,
                    'description': route.description,
                    'created_by': route.created_by.username if route.created_by else 'Unknown',
                    'created_at': route.created_at.strftime('%Y-%m-%d %H:%M'),
                    'updated_at': route.updated_at.strftime('%Y-%m-%d %H:%M') if route.updated_at else None
                }
                routes_list.append(route_data)
            
            # آماده کردن اطلاعات فرودگاه‌ها برای پاسخ
            origin_info = {
                'code': origin,
                'icao': origin_icao,
                'name': origin_airport.name if origin_airport else origin_icao,
                'city': origin_airport.city if origin_airport else 'N/A',
                'country': origin_airport.country if origin_airport else 'N/A'
            }
            
            destination_info = {
                'code': destination,
                'icao': destination_icao,
                'name': destination_airport.name if destination_airport else destination_icao,
                'city': destination_airport.city if destination_airport else 'N/A',
                'country': destination_airport.country if destination_airport else 'N/A'
            }
            
            return JsonResponse({
                'status': 'success',
                'message': f'Found {len(routes_list)} route(s) from {origin} to {destination}',
                'search': {
                    'origin': origin,
                    'destination': destination,
                    'origin_icao': origin_icao,
                    'destination_icao': destination_icao
                },
                'airports': {
                    'origin': origin_info,
                    'destination': destination_info
                },
                'count': len(routes_list),
                'routes': routes_list
            }, status=200)
            
        except Exception as e:
            return JsonResponse({
                'status': 'error',
                'message': f'Search failed: {str(e)}',
                'detail': 'Please check the server logs for more information'
            }, status=500)

# ==================== View برای صفحه داشبورد ====================

def dashboard_view(request):
    """صفحه اصلی داشبورد"""
    waypoint_count = Waypoint.objects.count()
    route_count = Route.objects.count()
    airway_count = Airway.objects.count()
    fir_count = FlightInformationRegion.objects.count()
    
    # آمار مسیرهای ذخیره شده
    routes_by_direction = Route.objects.values('departure', 'arrival').distinct().count()
    
    return render(request, 'routes/dashboard.html', {
        'waypoint_count': waypoint_count,
        'route_count': route_count,
        'airway_count': airway_count,
        'fir_count': fir_count,
        'unique_routes_count': routes_by_direction
    })
