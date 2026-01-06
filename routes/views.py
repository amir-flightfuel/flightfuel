from django.http import JsonResponse
from django.shortcuts import render
from rest_framework import viewsets, filters, status
from rest_framework.response import Response
from rest_framework.decorators import action
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticatedOrReadOnly
from django.contrib.gis.geos import Point, LineString, Polygon
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

# ==================== HELPER FUNCTIONS ====================

def get_icao_code(code, return_original_if_not_found=True):
    """
    Smart conversion of airport code to ICAO
    Converts IATA (3-letter) to ICAO (4-letter) when possible
    """
    if not code:
        return None
    
    code = code.upper().strip()
    
    # 1. If 4 letters and alphabetic: likely ICAO
    if len(code) == 4 and code.isalpha():
        # Check in airports database
        airport = Airport.objects.filter(
            Q(icao_code=code) | Q(iata_code=code)
        ).first()
        if airport:
            return airport.icao_code
        return code
    
    # 2. If 3 letters and alphabetic: IATA
    elif len(code) == 3 and code.isalpha():
        # Search in airports database
        airport = Airport.objects.filter(iata_code=code).first()
        if airport and airport.icao_code:
            return airport.icao_code
        
        # If not found and flag is active, return original
        if return_original_if_not_found:
            return code
        
        return None
    
    # 3. For other cases
    return code if return_original_if_not_found else None

def validate_airport_code(code):
    """
    Validate airport code and return detailed information
    """
    if not code:
        return {'valid': False, 'error': 'Airport code is empty'}
    
    code = code.upper().strip()
    
    # Check length
    if len(code) not in [3, 4]:
        return {
            'valid': False, 
            'error': 'Airport code must be 3-letter (IATA) or 4-letter (ICAO)',
            'input': code
        }
    
    # Check alphabetic
    if not code.isalpha():
        return {
            'valid': False,
            'error': 'Airport code must contain only letters',
            'input': code
        }
    
    # Convert to ICAO
    icao_code = get_icao_code(code)
    
    if not icao_code:
        return {
            'valid': False,
            'error': f'Airport code "{code}" not found in database',
            'input': code,
            'suggestion': 'Use valid IATA (THR) or ICAO (OIII) codes'
        }
    
    # Find airport information
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
    """
    Parse route text string into structured route data
    Supports IATA, ICAO, waypoints, airways, SID/STAR
    """
    try:
        # Remove DCT (Direct) and clean parts
        parts = [p for p in route_text.split() if p not in ['DCT']]
        
        if len(parts) < 2:
            return None
            
        departure = parts[0]
        arrival = parts[-1]
        
        waypoints = []
        coordinates = []
        
        # Process each part of the route
        for part in parts:
            # Detect code type (IATA or ICAO)
            is_airport = False
            airport = None
            
            # If 3 letters (IATA)
            if len(part) == 3 and part.isalpha():
                airport = Airport.objects.filter(iata_code=part).first()
                if airport:
                    is_airport = True
            
            # If 4 letters (ICAO)  
            if not airport and len(part) == 4 and part.isalpha():
                airport = Airport.objects.filter(icao_code=part).first()
                if airport:
                    is_airport = True
            
            # If airport found
            if is_airport and airport:
                coordinates.append([airport.location.x, airport.location.y])
                if part not in [departure, arrival]:
                    waypoints.append(part)
                continue
                
            # If waypoint
            waypoint = Waypoint.objects.filter(identifier=part).first()
            if waypoint:
                coordinates.append([waypoint.location.x, waypoint.location.y])
                waypoints.append(part)
                continue
                
            # If airway - ignore in coordinates but track
            if re.match(r'^[ABGRULMNZW]\d+', part):
                continue
                
            # If SID/STAR - ignore
            if re.match(r'.*[0-9][A-Z]$', part):
                continue
        
        # If insufficient coordinates
        if len(coordinates) < 2:
            return None
            
        # Calculate total distance
        total_distance = calculate_route_distance(coordinates)
        
        # Convert departure and arrival to ICAO
        departure_icao = get_icao_code(departure)
        arrival_icao = get_icao_code(arrival)
        
        return {
            'departure': departure_icao,
            'arrival': arrival_icao,
            'waypoints': waypoints,
            'coordinates': coordinates,
            'total_distance': total_distance
        }
        
    except Exception as e:
        print(f"Parse error: {e}")
        return None

def calculate_route_distance(coordinates):
    """
    Calculate total route distance in nautical miles
    """
    total_distance = 0
    for i in range(len(coordinates) - 1):
        coord1 = coordinates[i]
        coord2 = coordinates[i + 1]
        total_distance += calculate_distance_nm(coord1, coord2)
    return total_distance

def calculate_distance_nm(coord1, coord2):
    """
    Calculate distance between two points in nautical miles using Haversine formula
    """
    lon1, lat1 = coord1
    lon2, lat2 = coord2
    
    R = 3440.065  # Earth radius in nautical miles
    dLat = (lat2 - lat1) * math.pi / 180
    dLon = (lon2 - lon1) * math.pi / 180
    
    a = (math.sin(dLat/2) * math.sin(dLat/2) +
         math.cos(lat1 * math.pi / 180) * math.cos(lat2 * math.pi / 180) *
         math.sin(dLon/2) * math.sin(dLon/2))
    
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))  # FIXED: math.sqrt not Math.sqrt
    return R * c

def calculate_firs_for_route(coordinates):
    """
    Calculate which Flight Information Regions (FIRs) the route passes through
    
    Returns:
        tuple: (count, list_of_firs)
    """
    try:
        if not coordinates or len(coordinates) < 2:
            return 0, []
        
        # Create LineString from route coordinates
        route_line = LineString(coordinates, srid=4326)
        
        # Find intersecting FIRs
        intersecting_firs = FlightInformationRegion.objects.filter(
            boundary__intersects=route_line
        ).order_by('identifier')
        
        fir_count = intersecting_firs.count()
        
        # Prepare FIR list with details
        fir_list = []
        for fir in intersecting_firs:
            fir_list.append({
                'identifier': fir.identifier,
                'name': fir.name,
                'country': fir.country,
                'country_code': fir.country_code,
                'icao_region': fir.icao_region
            })
        
        return fir_count, fir_list
        
    except Exception as e:
        print(f"Error calculating FIRs: {e}")
        return 0, []

# ==================== DRF ViewSets ====================

class WaypointViewSet(viewsets.ModelViewSet):
    """
    API endpoint for Navigation Waypoints
    """
    queryset = Waypoint.objects.all()
    serializer_class = WaypointSerializer
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['identifier', 'name', 'country', 'type']
    ordering_fields = ['identifier', 'name', 'type']
    permission_classes = [IsAuthenticatedOrReadOnly]
    
    @action(detail=False, methods=['GET'])
    def by_type(self, request):
        """
        Filter waypoints by type (VOR, NDB, FIX, etc.)
        """
        wp_type = request.query_params.get('type')
        if wp_type:
            waypoints = Waypoint.objects.filter(type=wp_type)
        else:
            waypoints = Waypoint.objects.all()
        serializer = self.get_serializer(waypoints, many=True)
        return Response(serializer.data)

class AirwayViewSet(viewsets.ModelViewSet):
    """
    API endpoint for Airways (A, B, G, R routes)
    """
    queryset = Airway.objects.all()
    serializer_class = AirwaySerializer
    permission_classes = [IsAuthenticatedOrReadOnly]
    
    @action(detail=True, methods=['GET'])
    def segments(self, request, pk=None):
        """
        Get all segments for a specific airway
        """
        airway = self.get_object()
        segments = airway.segments.all()
        serializer = AirwaySegmentSerializer(segments, many=True)
        return Response(serializer.data)

class AirwaySegmentViewSet(viewsets.ModelViewSet):
    """
    API endpoint for Airway Segments
    """
    queryset = AirwaySegment.objects.all()
    serializer_class = AirwaySegmentSerializer
    permission_classes = [IsAuthenticatedOrReadOnly]

class RouteViewSet(viewsets.ModelViewSet):
    """
    API endpoint for Flight Routes
    Provides full CRUD operations for routes
    """
    queryset = Route.objects.all()
    serializer_class = RouteSerializer
    permission_classes = [IsAuthenticatedOrReadOnly]
    
    def create(self, request, *args, **kwargs):
        """
        Create new route with user assignment
        """
        if request.user.is_authenticated:
            request.data['created_by'] = request.user.id
        return super().create(request, *args, **kwargs)
    
    def update(self, request, *args, **kwargs):
        """
        Update existing route with user assignment
        """
        if request.user.is_authenticated:
            request.data['updated_by'] = request.user.id
        return super().update(request, *args, **kwargs)
    
    @action(detail=False, methods=['POST'])
    def calculate(self, request):
        """
        Calculate route options between two points
        """
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
        """
        Get map data including waypoints and airways for frontend display
        """
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
        Search saved routes based on origin and destination airport codes
        
        Query parameters:
        - origin: Departure airport code (IATA or ICAO)
        - destination: Arrival airport code (IATA or ICAO)
        """
        try:
            origin = request.query_params.get('origin', '').strip().upper()
            destination = request.query_params.get('destination', '').strip().upper()
            
            if not origin or not destination:
                return Response({
                    'error': 'Both origin and destination airport codes are required',
                    'example': '/api/routes/search/?origin=THR&destination=MHD'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Convert to ICAO
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
            
            # Search routes - search with both IATA and ICAO
            routes = Route.objects.filter(
                Q(departure__iexact=origin_icao) | Q(departure__iexact=origin),
                Q(arrival__iexact=destination_icao) | Q(arrival__iexact=destination)
            ).order_by('total_distance', '-created_at')
            
            # Bidirectional search
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
        Search all routes related to a specific airport
        
        Query parameters:
        - airport: Airport code (IATA or ICAO)
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
        """
        Search airport information by IATA or ICAO code
        
        Query parameters:
        - code: Airport code (IATA or ICAO)
        """
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
        """
        Calculate different route options between two points
        """
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
        """
        Calculate direct (great circle) route between two points
        """
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
        """
        Calculate route using published airways (not yet implemented)
        """
        return {
            'type': 'AIRWAY',
            'waypoints': [],
            'distance': 0,
            'description': 'Airway route calculation not implemented yet'
        }
    
    def calculate_via_waypoints(self, departure, arrival):
        """
        Calculate route via intermediate waypoints
        """
        try:
            dep_wp = Waypoint.objects.get(identifier=departure)
            arr_wp = Waypoint.objects.get(identifier=arrival)
            
            # Find waypoints near departure and arrival
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
        """
        Calculate total distance for a list of waypoints
        """
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
    """
    API endpoint for Flight Information Regions (FIRs)
    """
    queryset = FlightInformationRegion.objects.all()
    serializer_class = FlightInformationRegionSerializer
    permission_classes = [IsAuthenticatedOrReadOnly]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['identifier', 'name', 'country']
    ordering_fields = ['identifier', 'name', 'country']

# ==================== UTILITY APIs ====================

class AirportGeoJSON(APIView):
    """
    API endpoint to get airports as GeoJSON for map display
    """
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
    """
    API endpoint to get navigation waypoints as GeoJSON for map display
    """
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
    """
    API endpoint to get Flight Information Regions as GeoJSON for map display
    """
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
    """
    API endpoint to calculate optimal route between two points
    (Uses AirwayRouter for advanced routing)
    """
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

# ==================== ENHANCED SAVE ROUTE API ====================
class EnhancedSaveRouteAPI(APIView):
    """
    Enhanced route saving with proper Overwrite behavior
    - Overwrite: Keeps original name, no versioning
    - Save As: User provides custom name, no auto-versioning
    """
    permission_classes = [AllowAny]
    
    def post(self, request):
        try:
            print("🚀 EnhancedSaveRouteAPI: Starting...")
            data = request.data
            
            # Validate required fields
            required_fields = ['departure', 'arrival', 'coordinates']
            for field in required_fields:
                if field not in data:
                    return JsonResponse({
                        'status': 'error',
                        'message': f'Missing required field: {field}'
                    }, status=400)
            
            # Parse coordinates
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
                    'message': 'Minimum 2 points required'
                }, status=400)
            
            # Convert to ICAO
            departure_icao = get_icao_code(data.get('departure', ''))
            arrival_icao = get_icao_code(data.get('arrival', ''))
            
            if not departure_icao or not arrival_icao:
                return JsonResponse({
                    'status': 'error',
                    'message': 'Invalid airport codes'
                }, status=400)
            
            # Get route name from user
            route_name = data.get('name', '').strip()
            
            # Get action and decision from frontend
            action = data.get('action', 'auto')  # 'auto', 'overwrite', 'save_as'
            decision = data.get('decision')      # From popup: 'overwrite', 'save_as_new', 'cancel'
            route_id = data.get('route_id')      # For overwrite
            
            # ======== DECISION LOGIC ========
            
            # If decision from popup is 'cancel'
            if decision == 'cancel':
                return JsonResponse({
                    'status': 'cancelled',
                    'message': 'Save operation cancelled by user'
                })
            
            # Check for existing routes with same departure/arrival
            existing_routes = Route.objects.filter(
                departure=departure_icao,
                arrival=arrival_icao
            ).order_by('-created_at')
            
            # ======== ACTION: OVERWRITE ========
            if action == 'overwrite' and route_id:
                try:
                    route = Route.objects.get(id=route_id)
                    
                    # ✅ CRITICAL: DO NOT CHANGE ROUTE NAME
                    original_name = route.name
                    
                    # Update route data but keep original name
                    route.departure = departure_icao
                    route.arrival = arrival_icao
                    route.waypoints = data.get('waypoints', [])
                    route.coordinates = LineString(line_coords, srid=4326)
                    route.total_distance = data.get('total_distance', 0)
                    route.flight_time = data.get('flight_time', '')
                    route.description = data.get('description', route.description)
                    
                    # Update user
                    if User.objects.exists():
                        route.updated_by = User.objects.first()
                    
                    route.save()
                    
                    return JsonResponse({
                        'status': 'success', 
                        'route_id': route.id,
                        'route_name': original_name,
                        'original_name_preserved': True,
                        'message': f'Route "{original_name}" overwritten successfully',
                        'action': 'overwrite'
                    })
                    
                except Route.DoesNotExist:
                    return JsonResponse({
                        'status': 'error',
                        'message': f'Route with ID {route_id} not found'
                    }, status=404)
            
            # ======== ACTION: SAVE AS NEW ========
            elif action == 'save_as' or decision == 'save_as_new':
                # ✅ NO AUTO VERSIONING - User provides custom name
                if not route_name:
                    route_name = f"{departure_icao}-{arrival_icao}"
                
                # Create new route with user-provided name
                route = Route.objects.create(
                    name=route_name,
                    departure=departure_icao,
                    arrival=arrival_icao,
                    waypoints=data.get('waypoints', []),
                    coordinates=LineString(line_coords, srid=4326),
                    total_distance=data.get('total_distance', 0),
                    flight_time=data.get('flight_time', ''),
                    description=data.get('description', ''),
                    created_by=User.objects.first() if User.objects.exists() else None
                )
                
                return JsonResponse({
                    'status': 'success', 
                    'route_id': route.id,
                    'route_name': route.name,
                    'message': f'Route "{route.name}" saved as new',
                    'action': 'save_as_new'
                })
            
            # ======== AUTO DETECTION (for conflict) ========
            elif existing_routes.exists():
                # Conflict detected - SIMPLIFIED OPTIONS
                existing_route = existing_routes.first()
                
                return JsonResponse({
                    'status': 'conflict',
                    'message': f'Route "{existing_route.name}" already exists',
                    'existing_route': {
                        'id': existing_route.id,
                        'name': existing_route.name,
                        'departure': existing_route.departure,
                        'arrival': existing_route.arrival,
                        'created_at': existing_route.created_at.strftime('%Y-%m-%d %H:%M'),
                        'created_by': existing_route.created_by.username if existing_route.created_by else 'System'
                    },
                    'options': {
                        'overwrite': f'Overwrite: "{existing_route.name}"',
                        'cancel': 'Cancel'
                    }
                }, status=409)
            
            # ======== CREATE NEW ROUTE (no conflict) ========
            else:
                # No conflict - create new route
                if not route_name:
                    route_name = f"{departure_icao}-{arrival_icao}"
                
                route = Route.objects.create(
                    name=route_name,
                    departure=departure_icao,
                    arrival=arrival_icao,
                    waypoints=data.get('waypoints', []),
                    coordinates=LineString(line_coords, srid=4326),
                    total_distance=data.get('total_distance', 0),
                    flight_time=data.get('flight_time', ''),
                    description=data.get('description', ''),
                    created_by=User.objects.first() if User.objects.exists() else None
                )
                
                return JsonResponse({
                    'status': 'success', 
                    'route_id': route.id,
                    'route_name': route.name,
                    'message': 'New route created successfully',
                    'action': 'created_new'
                })
                
        except Exception as e:
            import traceback
            error_details = traceback.format_exc()
            print(f"❌ EnhancedSaveRouteAPI Error: {str(e)}")
            return JsonResponse({
                'status': 'error',
                'message': str(e),
                'details': error_details[:300]
            }, status=400)
# ==================== SIMPLE SAVE ROUTE API ====================
class SaveRouteAPI(APIView):
    """
    Simple route saving API
    - Overwrite: Keeps original name
    - Create: Uses simple name format if not provided
    - NO AUTO VERSIONING
    """
    permission_classes = [AllowAny]
    
    def post(self, request):
        try:
            print("📦 SaveRouteAPI: Receiving route data...")
            data = request.data
            
            # Validate required fields
            required_fields = ['departure', 'arrival', 'coordinates']
            for field in required_fields:
                if field not in data:
                    return JsonResponse({
                        'status': 'error',
                        'message': f'Field {field} is missing'
                    }, status=400)
            
            # Parse coordinates
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
                    'message': 'Minimum 2 points required to create a route'
                }, status=400)
            
            # Convert airport codes to ICAO
            departure_icao = get_icao_code(data.get('departure', ''))
            arrival_icao = get_icao_code(data.get('arrival', ''))
            
            if not departure_icao or not arrival_icao:
                return JsonResponse({
                    'status': 'error',
                    'message': 'Invalid airport codes'
                }, status=400)
            
            # Get route name
            route_name = data.get('name', '').strip()
            
            # ======== Check action type ========
            action = data.get('action', 'create')  # 'create' or 'overwrite'
            route_id = data.get('route_id')  # For overwrite operations
            
            if action == 'overwrite' and route_id:
                # ✅ OVERWRITE EXISTING ROUTE - KEEP ORIGINAL NAME
                try:
                    route = Route.objects.get(id=route_id)
                    original_name = route.name  # Save original name
                    
                    # Update route data but KEEP ORIGINAL NAME
                    route.departure = departure_icao
                    route.arrival = arrival_icao
                    route.waypoints = data.get('waypoints', [])
                    route.coordinates = LineString(line_coords, srid=4326)
                    route.total_distance = data.get('total_distance', 0)
                    route.flight_time = data.get('flight_time', '')
                    route.description = data.get('description', route.description)
                    
                    # Update user info
                    if User.objects.exists():
                        route.updated_by = User.objects.first()
                    
                    route.save()
                    
                    return JsonResponse({
                        'status': 'success', 
                        'route_id': route.id,
                        'route_name': original_name,  # Return ORIGINAL name
                        'original_name_preserved': True,
                        'message': f'Route "{original_name}" overwritten successfully',
                        'action': 'overwritten'
                    })
                    
                except Route.DoesNotExist:
                    return JsonResponse({
                        'status': 'error',
                        'message': f'Route with ID {route_id} not found for overwrite'
                    }, status=404)
            
            else:
                # CREATE NEW ROUTE
                # Check if similar route exists
                existing_routes = Route.objects.filter(
                    departure=departure_icao,
                    arrival=arrival_icao
                ).order_by('-created_at')
                
                if existing_routes.exists():
                    # Conflict detected
                    existing_route = existing_routes.first()
                    return JsonResponse({
                        'status': 'conflict',
                        'message': f'A route named "{existing_route.name}" already exists',
                        'existing_route': {
                            'id': existing_route.id,
                            'name': existing_route.name,
                            'departure': existing_route.departure,
                            'arrival': existing_route.arrival,
                            'created_at': existing_route.created_at.strftime('%Y-%m-%d %H:%M')
                        },
                        'suggestion': 'Send action: "overwrite" with route_id to overwrite, or use Save As with custom name'
                    }, status=409)
                
                # Create new route
                if not route_name:
                    route_name = f"{departure_icao}-{arrival_icao}"
                
                route = Route.objects.create(
                    name=route_name,
                    departure=departure_icao,
                    arrival=arrival_icao,
                    waypoints=data.get('waypoints', []),
                    coordinates=LineString(line_coords, srid=4326),
                    total_distance=data.get('total_distance', 0),
                    flight_time=data.get('flight_time', ''),
                    description=data.get('description', ''),
                    created_by=User.objects.first() if User.objects.exists() else None
                )
                
                return JsonResponse({
                    'status': 'success', 
                    'route_id': route.id,
                    'route_name': route.name,
                    'message': 'Route saved successfully',
                    'action': 'created'
                })
                
        except Exception as e:
            import traceback
            error_details = traceback.format_exc()
            print(f"❌ SaveRouteAPI Error: {str(e)}")
            return JsonResponse({
                'status': 'error',
                'message': str(e),
                'details': error_details[:300]
            }, status=400)

# ==================== SAVE AS NEW ROUTE API ====================
class SaveAsRouteAPI(APIView):
    """
    Save As API - Always creates new route with user-provided name
    NO AUTO VERSIONING
    """
    permission_classes = [AllowAny]
    
    def post(self, request):
        try:
            data = request.data
            
            # Validate required fields
            required_fields = ['departure', 'arrival', 'coordinates']
            for field in required_fields:
                if field not in data:
                    return JsonResponse({
                        'status': 'error',
                        'message': f'Field {field} is missing'
                    }, status=400)
            
            # Parse coordinates
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
                    'message': 'Minimum 2 points required to create a route'
                }, status=400)
            
            # Convert to ICAO
            departure_icao = get_icao_code(data.get('departure', ''))
            arrival_icao = get_icao_code(data.get('arrival', ''))
            
            if not departure_icao or not arrival_icao:
                return JsonResponse({
                    'status': 'error',
                    'message': 'Invalid airport codes'
                }, status=400)
            
            # Get custom name from user
            custom_name = data.get('name', '').strip()
            
            # If no custom name, use simple format
            if not custom_name:
                custom_name = f"{departure_icao}-{arrival_icao}"
            
            # ✅ NO VERSIONING - Use user's name exactly as provided
            route_name = custom_name
            
            # Create new route (always new, never overwrites)
            route = Route.objects.create(
                name=route_name,
                departure=departure_icao,
                arrival=arrival_icao,
                waypoints=data.get('waypoints', []),
                coordinates=LineString(line_coords, srid=4326),
                total_distance=data.get('total_distance', 0),
                flight_time=data.get('flight_time', ''),
                description=data.get('description', ''),
                created_by=User.objects.first() if User.objects.exists() else None
            )
            
            return JsonResponse({
                'status': 'success', 
                'route_id': route.id,
                'route_name': route.name,
                'message': f'Route saved as: "{route.name}"',
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

# ==================== GET ROUTES API ====================
class GetRoutesAPI(APIView):
    """
    API endpoint to get all saved routes
    """
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

# ==================== GET ROUTE DETAIL API ====================
class GetRouteDetailAPI(APIView):
    """
    API for getting complete details of a specific route
    """
    permission_classes = [AllowAny]
    
    def get(self, request, route_id):
        try:
            print(f"📋 GetRouteDetailAPI: Getting route details ID={route_id}")
            
            # Find route from database
            try:
                route = Route.objects.get(id=route_id)
            except Route.DoesNotExist:
                return JsonResponse({
                    'status': 'error',
                    'message': f'Route with ID {route_id} not found'
                }, status=404)
            
            # Extract coordinates
            coordinates = []
            if route.coordinates:
                try:
                    if hasattr(route.coordinates, 'coords'):
                        coordinates = list(route.coordinates.coords)
                    else:
                        coordinates = route.coordinates
                except Exception as e:
                    print(f"⚠️ Error reading coordinates: {e}")
            
            # Calculate FIRs the route passes through
            fir_count = 0
            fir_list = []
            
            if coordinates and len(coordinates) > 1:
                fir_count, fir_list = calculate_firs_for_route(coordinates)
                print(f"✅ Calculated FIRs: {fir_count} FIRs")
            
            # Prepare response
            route_data = {
                'id': route.id,
                'name': route.name,
                'departure': route.departure,
                'arrival': route.arrival,
                'total_distance': route.total_distance,
                'flight_time': route.flight_time,
                'waypoints': route.waypoints,
                'coordinates': coordinates,
                'description': route.description if hasattr(route, 'description') else '',
                'created_by': route.created_by.username if route.created_by else 'System',
                'created_at': route.created_at.strftime('%Y-%m-%d %H:%M'),
                'fir_count': fir_count,
                'fir_list': fir_list,
            }
            
            return JsonResponse({
                'status': 'success',
                'route': route_data
            })
            
        except Exception as e:
            import traceback
            print(f"❌ GetRouteDetailAPI Error: {str(e)}")
            print(traceback.format_exc())
            
            return JsonResponse({
                'status': 'error',
                'message': f'Error getting route details: {str(e)}'
            }, status=500)
# ==================== ADVANCED DELETE ROUTE API ====================
class AdvancedDeleteRouteAPI(APIView):
    """
    Advanced delete API with hard/soft delete options
    """
    permission_classes = [AllowAny]
    
    def delete(self, request, route_id):
        try:
            print(f"🗑️ AdvancedDeleteRouteAPI: Deleting route {route_id}")
            
            # Get delete options
            delete_type = request.GET.get('type', 'soft')  # 'hard' or 'soft'
            confirm = request.GET.get('confirm', 'false').lower() == 'true'
            
            # Safety check: require confirmation
            if not confirm:
                return JsonResponse({
                    'status': 'confirmation_required',
                    'message': 'Add ?confirm=true to confirm deletion',
                    'route_id': route_id,
                    'danger': 'This action cannot be undone'
                }, status=400)
            
            # Get the route
            try:
                route = Route.objects.get(id=route_id)
            except Route.DoesNotExist:
                return JsonResponse({
                    'status': 'error',
                    'message': f'Route with ID {route_id} not found'
                }, status=404)
            
            # Store info before deletion
            route_info = {
                'id': route.id,
                'name': route.name,
                'departure': route.departure,
                'arrival': route.arrival,
                'created_by': route.created_by.username if route.created_by else 'Unknown',
                'created_at': route.created_at.strftime('%Y-%m-%d %H:%M')
            }
            
            # Perform deletion based on type
            if delete_type == 'hard':
                # HARD DELETE - Permanent removal
                route.delete()
                action = 'hard_deleted'
                message = 'Route permanently deleted from database'
                warning = 'This action cannot be undone. Route is gone forever.'
            else:
                # SOFT DELETE - Mark as inactive
                if hasattr(route, 'is_active'):
                    route.is_active = False
                    route.save()
                else:
                    # If no is_active field, use hard delete
                    route.delete()
                    action = 'hard_deleted'
                    message = 'Route permanently deleted (no soft delete support)'
                    warning = 'Route deleted (no soft delete support)'
                    return JsonResponse({
                        'status': 'success',
                        'message': message,
                        'action': action,
                        'route_info': route_info,
                        'warning': warning,
                        'deleted_at': timezone.now().strftime('%Y-%m-%d %H:%M:%S')
                    })
                
                action = 'soft_deleted'
                message = 'Route marked as inactive (soft delete)'
                warning = 'Route can be restored later.'
            
            # Return success response
            return JsonResponse({
                'status': 'success',
                'message': message,
                'action': action,
                'route_info': route_info,
                'warning': warning,
                'deleted_at': timezone.now().strftime('%Y-%m-%d %H:%M:%S')
            })
            
        except Exception as e:
            import traceback
            error_details = traceback.format_exc()
            print(f"❌ AdvancedDeleteRouteAPI Error: {str(e)}")
            
            return JsonResponse({
                'status': 'error',
                'message': str(e),
                'details': error_details[:300]
            }, status=400)
    
    # Support GET method for browsers
    def get(self, request, route_id):
        return self.delete(request, route_id)


# ==================== RESTORE ROUTE API ====================
class RestoreRouteAPI(APIView):
    """
    API to restore soft-deleted routes
    Only works if route has is_active field
    """
    permission_classes = [AllowAny]
    
    def post(self, request, route_id):
        try:
            print(f"🔄 RestoreRouteAPI: Restoring route {route_id}")
            
            # Get the route
            try:
                route = Route.objects.get(id=route_id)
            except Route.DoesNotExist:
                return JsonResponse({
                    'status': 'error',
                    'message': f'Route with ID {route_id} not found'
                }, status=404)
            
            # Check if route has is_active field
            if not hasattr(route, 'is_active'):
                return JsonResponse({
                    'status': 'error',
                    'message': 'Route does not support soft delete/restore',
                    'suggestion': 'Add is_active field to Route model'
                }, status=400)
            
            # Check if route is actually inactive
            if route.is_active:
                return JsonResponse({
                    'status': 'info',
                    'message': 'Route is already active',
                    'route_id': route.id,
                    'route_name': route.name
                })
            
            # Restore the route
            route.is_active = True
            route.save()
            
            return JsonResponse({
                'status': 'success',
                'message': 'Route restored successfully',
                'route_id': route.id,
                'route_name': route.name,
                'restored_at': timezone.now().strftime('%Y-%m-%d %H:%M:%S')
            })
            
        except Exception as e:
            import traceback
            error_details = traceback.format_exc()
            print(f"❌ RestoreRouteAPI Error: {str(e)}")
            
            return JsonResponse({
                'status': 'error',
                'message': str(e)
            }, status=400)
# ==================== DELETE ROUTE API ====================
# ==================== DELETE ROUTE API ====================
class DeleteRouteAPI(APIView):
    """
    SIMPLE DELETE API - No confirmation required
    Works with frontend delete button
    """
    permission_classes = [AllowAny]
    
    def delete(self, request, route_id):
        try:
            print(f"🗑️ DELETE Route API called for ID: {route_id}")
            
            # 1. Find the route
            try:
                route = Route.objects.get(id=route_id)
            except Route.DoesNotExist:
                print(f"❌ Route {route_id} not found")
                return JsonResponse({
                    'status': 'error',
                    'message': f'Route with ID {route_id} not found'
                }, status=404)
            
            # 2. Log route info
            route_info = {
                'id': route.id,
                'name': route.name,
                'departure': route.departure,
                'arrival': route.arrival
            }
            print(f"🗑️ Deleting route: {route_info}")
            
            # 3. Delete permanently
            route.delete()
            
            # 4. Return success
            response_data = {
                'status': 'success',
                'message': f'Route "{route_info["name"]}" deleted successfully',
                'deleted_route': route_info,
                'deleted_at': timezone.now().strftime('%Y-%m-%d %H:%M:%S')
            }
            print(f"✅ Delete successful: {response_data}")
            
            return JsonResponse(response_data)
            
        except Exception as e:
            import traceback
            error_trace = traceback.format_exc()
            print(f"❌ DELETE API Error: {str(e)}")
            print(f"❌ Traceback: {error_trace}")
            
            return JsonResponse({
                'status': 'error',
                'message': f'Error deleting route: {str(e)}',
                'debug_info': error_trace[:500]
            }, status=500)

# ==================== IMPORT ROUTE API ====================
class ImportRouteAPI(APIView):
    """
    API endpoint for importing routes from text format
    """
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
            
            # Use simple name format for imported routes
            route_name = f"{parsed_route['departure']}-{parsed_route['arrival']}"
            
            route = Route.objects.create(
                name=route_name,
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

# ==================== ROUTE SEARCH API ====================
class RouteSearchAPI(APIView):
    """
    API for searching routes with IATA/ICAO support
    """
    
    permission_classes = [IsAuthenticatedOrReadOnly]
    
    def get(self, request):
        try:
            # Get and normalize input
            origin = request.GET.get('origin', '').strip().upper()
            destination = request.GET.get('destination', '').strip().upper()
            
            print(f"🔍 RouteSearchAPI: Searching {origin} → {destination}")
            
            if not origin or not destination:
                return JsonResponse({
                    'status': 'error',
                    'message': 'Both origin and destination airport codes are required'
                }, status=400)
            
            # Convert to ICAO
            origin_icao = get_icao_code(origin)
            destination_icao = get_icao_code(destination)
            
            print(f"🔍 Code conversion: {origin}→{origin_icao}, {destination}→{destination_icao}")
            
            # Prepare all possible search combinations
            all_routes = []
            seen_ids = set()
            
            # List all possible search pairs
            search_pairs = []
            
            # Combination 1: ICAO vs ICAO (primary)
            if origin_icao and destination_icao:
                search_pairs.append((origin_icao, destination_icao))
            
            # Combination 2: IATA vs IATA
            if len(origin) == 3 and len(destination) == 3:
                search_pairs.append((origin, destination))
            
            # Combination 3: ICAO vs IATA (mixed)
            if origin_icao and len(destination) == 3:
                search_pairs.append((origin_icao, destination))
            if len(origin) == 3 and destination_icao:
                search_pairs.append((origin, destination_icao))
            
            # Combination 4: IATA vs ICAO (reverse mixed)
            if len(origin) == 4 and destination_icao:
                search_pairs.append((origin, destination_icao))
            if origin_icao and len(destination) == 4:
                search_pairs.append((origin_icao, destination))
            
            # Remove duplicates
            search_pairs = list(set(search_pairs))
            
            print(f"🔍 Search pairs to try: {search_pairs}")
            
            # Search in all combinations
            for dep, arr in search_pairs:
                print(f"  🔍 Searching: {dep} → {arr}")
                
                # Use __iexact for case-insensitive search
                routes = Route.objects.filter(
                    departure__iexact=dep,
                    arrival__iexact=arr
                )
                
                for route in routes:
                    if route.id not in seen_ids:
                        seen_ids.add(route.id)
                        all_routes.append(route)
                        print(f"    ✅ Found: {route.departure}→{route.arrival} ({route.name})")
            
            # Bidirectional search (reverse)
            reverse_search_pairs = [(arr, dep) for dep, arr in search_pairs if dep != arr]
            for dep, arr in reverse_search_pairs:
                print(f"  🔍 Reverse searching: {dep} → {arr}")
                
                routes = Route.objects.filter(
                    departure__iexact=dep,
                    arrival__iexact=arr
                )
                
                for route in routes:
                    if route.id not in seen_ids:
                        seen_ids.add(route.id)
                        all_routes.append(route)
                        print(f"    ✅ Found (reverse): {route.departure}→{route.arrival} ({route.name})")
            
            print(f"✅ Total unique routes found: {len(all_routes)}")
            
            # Prepare results
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
            
            # Airport information for display
            origin_airport = Airport.objects.filter(
                Q(iata_code=origin) | Q(icao_code=origin) | Q(icao_code=origin_icao)
            ).first()
            
            destination_airport = Airport.objects.filter(
                Q(iata_code=destination) | Q(icao_code=destination) | Q(icao_code=destination_icao)
            ).first()
            
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

# ==================== DASHBOARD VIEW ====================
def dashboard_view(request):
    """
    Main dashboard page view
    """
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
