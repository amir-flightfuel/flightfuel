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
from rest_framework.permissions import AllowAny
from django.utils import timezone

# ==================== توابع کمکی ====================

def get_icao_code(code, return_original_if_not_found=True):
    """
    تبدیل هوشمند کد فرودگاه به ICAO - نسخه نهایی
    """
    if not code:
        return None
    
    code = code.upper().strip()
    
    # ۱. اگر ۴ حرفی و فقط حروف: احتمالاً ICAO است
    if len(code) == 4 and code.isalpha():
        # بررسی در airports
        airport = Airport.objects.filter(
            Q(icao_code=code) | Q(iata_code=code)
        ).first()
        if airport:
            return airport.icao_code
        return code
    
    # ۲. اگر ۳ حرفی و فقط حروف: IATA است
    elif len(code) == 3 and code.isalpha():
        # جستجو در airports
        airport = Airport.objects.filter(iata_code=code).first()
        if airport and airport.icao_code:
            return airport.icao_code
        
        # اگر پیدا نشد و flag فعال است، همان کد رو برگردون
        if return_original_if_not_found:
            return code
        
        return None
    
    # ۳. برای سایر موارد
    return code if return_original_if_not_found else None

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

# ==================== ViewSet های DRF ====================

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
        if request.user.is_authenticated:
            request.data['created_by'] = request.user.id
        return super().create(request, *args, **kwargs)
    
    def update(self, request, *args, **kwargs):
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
            
            result = self.calculate_routes(departure, arrival)
            
            return Response(result)
            
        except Exception as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=False, methods=['GET'])
    def map_data(self, request):
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
            
            # جستجوی مسیرها - جستجو با هر دو IATA و ICAO
            routes = Route.objects.filter(
                Q(departure__iexact=origin_icao) | Q(departure__iexact=origin),
                Q(arrival__iexact=destination_icao) | Q(arrival__iexact=destination)
            ).order_by('total_distance', '-created_at')
            
            # جستجوی دوطرفه
            if not routes.exists():
                routes = Route.objects.filter(
                     Q(departure__iexact=destination_icao) | Q(departure__iexact=destination),
                     Q(arrival__iexact=origin_icao) | Q(arrival__iexact=origin)
                ).order_by('total_distance', '-created_at')
            
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
            
            serializer = RouteSerializer(routes, many=True)
            
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
        """
        try:
            airport_code = request.query_params.get('airport', '').strip().upper()
            
            if not airport_code:
                return Response({
                    'error': 'Airport code is required',
                    'example': '/api/routes/search_by_airport/?airport=THR'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            airport_icao = get_icao_code(airport_code)
            
            if not airport_icao:
                return Response({
                    'error': f'Airport code not found: {airport_code}',
                    'suggestion': 'Use 3-letter IATA (e.g., THR) or 4-letter ICAO (e.g., OIII)'
                }, status=status.HTTP_404_NOT_FOUND)
            
            routes = Route.objects.filter(
                Q(departure__iexact=airport_icao) | Q(arrival__iexact=airport_icao) |
                Q(departure__iexact=airport_code) | Q(arrival__iexact=airport_code)
            ).order_by('departure', 'arrival', 'total_distance')
            
            if not routes.exists():
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
            
            departures = routes.filter(departure__iexact=airport_icao)
            arrivals = routes.filter(arrival__iexact=airport_icao)
            
            departures_serializer = RouteSerializer(departures, many=True)
            arrivals_serializer = RouteSerializer(arrivals, many=True)
            
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
    
    @action(detail=False, methods=['GET'])
    def search_airport(self, request):
        """جستجوی فرودگاه بر اساس IATA یا ICAO"""
        code = request.query_params.get('code', '').strip().upper()
        
        if not code:
            return Response({
                'error': 'Airport code is required',
                'example': '/api/routes/search_airport/?code=THR'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        airport = Airport.objects.filter(
            Q(iata_code=code) | Q(icao_code=code)
        ).first()
        
        if airport:
            return Response({
                'iata': airport.iata_code,
                'icao': airport.icao_code,
                'name': airport.name,
                'city': airport.city,
                'country': airport.country
            })
        else:
            return Response({
                'error': f'Airport code {code} not found'
            }, status=status.HTTP_404_NOT_FOUND)
    
    def calculate_routes(self, departure, arrival):
        """محاسبه مسیرهای مختلف"""
        result = {
            'departure': departure,
            'arrival': arrival,
            'routes': {}
        }
        
        result['routes']['direct'] = self.calculate_direct_route(departure, arrival)
        result['routes']['airway'] = self.calculate_airway_route(departure, arrival)
        result['routes']['via_waypoints'] = self.calculate_via_waypoints(departure, arrival)
        
        return result
    
    def calculate_direct_route(self, departure, arrival):
        """محاسبه مسیر مستقیم"""
        try:
            dep_wp = Waypoint.objects.get(identifier=departure)
            arr_wp = Waypoint.objects.get(identifier=arrival)
            
            distance_deg = dep_wp.location.distance(arr_wp.location)
            distance_nm = round(distance_deg * 60.11, 2)
            
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
            
            waypoints = Waypoint.objects.filter(
                Q(location__dwithin=(dep_wp.location, 2.0)) |
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
    queryset = FlightInformationRegion.objects.all()
    serializer_class = FlightInformationRegionSerializer
    permission_classes = [IsAuthenticatedOrReadOnly]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['identifier', 'name', 'country']
    ordering_fields = ['identifier', 'name', 'country']

# ==================== API های کاربردی ====================

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
    def get(self, request):
        regions = FlightInformationRegion.objects.filter(is_active=True)
        
        features = []
        for region in regions:
            if region.boundary:
                try:
                    import json
                    
                    geojson_str = region.boundary.geojson
                    geojson_dict = json.loads(geojson_str)
                    
                    feature = {
                        "type": "Feature",
                        "geometry": geojson_dict,
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
                    try:
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
    permission_classes = [AllowAny]
    
    def post(self, request):
        try:
            print("📦 SaveRouteAPI: دریافت داده‌ها...")
            data = request.data
            
            required_fields = ['departure', 'arrival', 'coordinates']
            for field in required_fields:
                if field not in data:
                    return JsonResponse({
                        'status': 'error',
                        'message': f'فیلد {field} وجود ندارد'
                    }, status=400)
            
            coords = data['coordinates']
            
            line_coords = []
            for coord in coords:
                if isinstance(coord, list) and len(coord) >= 2:
                    try:
                        line_coords.append((float(coord[0]), float(coord[1])))
                    except (ValueError, TypeError):
                        continue
            
            if len(line_coords) < 2:
                return JsonResponse({
                    'status': 'error',
                    'message': 'حداقل ۲ نقطه برای ساخت مسیر لازم است'
                }, status=400)
            
            departure = data['departure']
            arrival = data['arrival']
            
            existing_route = Route.objects.filter(
                departure=departure,
                arrival=arrival
            ).order_by('-created_at').first()
            
            if existing_route:
                existing_route.waypoints = data.get('waypoints', [])
                existing_route.coordinates = LineString(line_coords, srid=4326)
                existing_route.total_distance = data.get('total_distance', 0)
                existing_route.flight_time = data.get('flight_time', '')
                if User.objects.exists():
                    existing_route.updated_by = User.objects.first()
                existing_route.save()
                
                return JsonResponse({
                    'status': 'success', 
                    'route_id': existing_route.id,
                    'message': 'Route updated successfully',
                    'action': 'updated'
                })
            else:
                route = Route.objects.create(
                    name=f"Route {departure} to {arrival}",
                    departure=departure,
                    arrival=arrival,
                    waypoints=data.get('waypoints', []),
                    coordinates=LineString(line_coords, srid=4326),
                    total_distance=data.get('total_distance', 0),
                    flight_time=data.get('flight_time', ''),
                    created_by=User.objects.first() if User.objects.exists() else None
                )
                
                return JsonResponse({
                    'status': 'success', 
                    'route_id': route.id,
                    'message': 'Route saved successfully',
                    'action': 'created'
                })
                
        except Exception as e:
            import traceback
            error_details = traceback.format_exc()
            return JsonResponse({
                'status': 'error',
                'message': str(e),
                'details': error_details[:300]
            }, status=400)

class SaveAsRouteAPI(APIView):
    permission_classes = [AllowAny]
    
    def post(self, request):
        try:
            data = request.data
            
            required_fields = ['departure', 'arrival', 'coordinates']
            for field in required_fields:
                if field not in data:
                    return JsonResponse({
                        'status': 'error',
                        'message': f'فیلد {field} وجود ندارد'
                    }, status=400)
            
            coords = data['coordinates']
            
            line_coords = []
            for coord in coords:
                if isinstance(coord, list) and len(coord) >= 2:
                    try:
                        line_coords.append((float(coord[0]), float(coord[1])))
                    except (ValueError, TypeError):
                        continue
            
            if len(line_coords) < 2:
                return JsonResponse({
                    'status': 'error',
                    'message': 'حداقل ۲ نقطه برای ساخت مسیر لازم است'
                }, status=400)
            
            departure = data['departure']
            arrival = data['arrival']
            
            version_count = Route.objects.filter(
                departure=departure,
                arrival=arrival
            ).count()
            
            version = version_count + 1
            
            custom_name = data.get('name', '')
            if custom_name:
                route_name = f"{custom_name} v{version}"
            else:
                route_name = f"Route {departure} to {arrival} v{version}"
            
            route = Route.objects.create(
                name=route_name,
                departure=departure,
                arrival=arrival,
                waypoints=data.get('waypoints', []),
                coordinates=LineString(line_coords, srid=4326),
                total_distance=data.get('total_distance', 0),
                flight_time=data.get('flight_time', ''),
                description=data.get('description', f'نسخه {version} - {timezone.now().strftime("%Y-%m-%d %H:%M")}'),
                created_by=User.objects.first() if User.objects.exists() else None
            )
            
            return JsonResponse({
                'status': 'success', 
                'route_id': route.id,
                'route_name': route.name,
                'version': version,
                'message': f'Route saved as version {version}',
                'action': 'saved_as'
            })
                
        except Exception as e:
            import traceback
            error_details = traceback.format_exc()
            return JsonResponse({
                'status': 'error',
                'message': str(e),
                'details': error_details[:300]
            }, status=400)

class GetRoutesAPI(APIView):
    def get(self, request):
        try:
            routes = Route.objects.all().order_by('-created_at')
            
            routes_data = []
            for route in routes:
                coordinates = []
                if route.coordinates:
                    try:
                        if hasattr(route.coordinates, 'coords'):
                            coordinates = list(route.coordinates.coords)
                        else:
                            coordinates = route.coordinates
                    except Exception as e:
                        pass
                
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
            route_text = request.data.get('route_text', '').strip()
            
            if not route_text:
                return JsonResponse({
                    'status': 'error',
                    'message': 'Route text is required'
                }, status=400)
            
            parsed_route = parse_route_text(route_text)
            
            if not parsed_route:
                return JsonResponse({
                    'status': 'error', 
                    'message': 'Could not parse route'
                }, status=400)
            
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

# ==================== API Route Search ====================
class RouteSearchAPI(APIView):
    """
    API جدید برای جستجوی مسیرها - پشتیبانی کامل از IATA/ICAO
    """
    
    permission_classes = [IsAuthenticatedOrReadOnly]
    
    def get(self, request):
        try:
            origin = request.GET.get('origin', '').strip().upper()
            destination = request.GET.get('destination', '').strip().upper()
            
            print(f"🔍 RouteSearchAPI: {origin} → {destination}")
            
            if not origin or not destination:
                return JsonResponse({
                    'status': 'error',
                    'message': 'Both origin and destination airport codes are required'
                }, status=400)
            
            # پیدا کردن اطلاعات فرودگاه‌ها
            origin_airport = Airport.objects.filter(
                Q(iata_code=origin) | Q(icao_code=origin)
            ).first()
            
            destination_airport = Airport.objects.filter(
                Q(iata_code=destination) | Q(icao_code=destination)
            ).first()
            
            origin_icao = origin_airport.icao_code if origin_airport else origin
            destination_icao = destination_airport.icao_code if destination_airport else destination
            
            print(f"🔍 تبدیل کدها: {origin}→{origin_icao}, {destination}→{destination_icao}")
            
            # ساخت همه ترکیبات ممکن برای جستجو
            search_combinations = [
                (origin, destination),                    # اصلی‌ترین
                (origin_icao, destination_icao),          # ICAO تبدیل شده
                (origin_icao, destination),               # ترکیب ۱
                (origin, destination_icao),               # ترکیب ۲
                (destination, origin),                    # معکوس اصلی
                (destination_icao, origin_icao),          # معکوس ICAO
            ]
            
            # حذف duplicate ها
            search_combinations = list(set(search_combinations))
            
            print(f"🔍 ترکیبات جستجو: {search_combinations}")
            
            # جستجو در همه ترکیبات
            all_routes = []
            seen_ids = set()
            
            for dep, arr in search_combinations:
                routes = Route.objects.filter(
                    departure__iexact=dep,
                    arrival__iexact=arr
                )
                
                for route in routes:
                    if route.id not in seen_ids:
                        seen_ids.add(route.id)
                        all_routes.append(route)
            
            print(f"✅ یافت شد: {len(all_routes)} مسیر")
            
            # آماده‌سازی نتایج
            routes_list = []
            for route in all_routes:
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
                    'created_by': route.created_by.username if route.created_by else 'Unknown',
                    'created_at': route.created_at.strftime('%Y-%m-%d %H:%M'),
                    'updated_at': route.updated_at.strftime('%Y-%m-%d %H:%M') if route.updated_at else None
                }
                routes_list.append(route_data)
            
            # اطلاعات فرودگاه‌ها برای نمایش
            origin_info = {
                'code': origin,
                'icao': origin_icao,
                'name': origin_airport.name if origin_airport else origin,
                'city': origin_airport.city if origin_airport else 'N/A',
                'country': origin_airport.country if origin_airport else 'N/A'
            }
            
            destination_info = {
                'code': destination,
                'icao': destination_icao,
                'name': destination_airport.name if destination_airport else destination,
                'city': destination_airport.city if destination_airport else 'N/A',
                'country': destination_airport.country if destination_airport else 'N/A'
            }
            
            response_data = {
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
            }
            
            return JsonResponse(response_data, status=200)
            
        except Exception as e:
            import traceback
            error_details = traceback.format_exc()
            print(f"❌ RouteSearchAPI Error: {str(e)}")
            
            return JsonResponse({
                'status': 'error',
                'message': f'Search failed: {str(e)}',
                'detail': str(e)
            }, status=500)


# ==================== View برای صفحه داشبورد ====================

def dashboard_view(request):
    """صفحه اصلی داشبورد"""
    waypoint_count = Waypoint.objects.count()
    route_count = Route.objects.count()
    airway_count = Airway.objects.count()
    fir_count = FlightInformationRegion.objects.count()
    
    routes_by_direction = Route.objects.values('departure', 'arrival').distinct().count()
    
    return render(request, 'base.html', {
        'waypoint_count': waypoint_count,
        'route_count': route_count,
        'airway_count': airway_count,
        'fir_count': fir_count,
        'unique_routes_count': routes_by_direction
    })
