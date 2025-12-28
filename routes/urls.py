from django.urls import path, include
from django.shortcuts import render
from rest_framework.routers import DefaultRouter
from .views import (
    WaypointViewSet, AirwayViewSet, AirwaySegmentViewSet,
    RouteViewSet, FlightInformationRegionViewSet,
    AirportGeoJSON, WaypointGeoJSON, FIRGeoJSON,
    CalculateRoute, SaveRouteAPI, SaveAsRouteAPI,
    GetRoutesAPI, GetRouteDetailAPI, DeleteRouteAPI, ImportRouteAPI,
    RouteSearchAPI, dashboard_view
)

# ==================== ROUTER CONFIGURATION ====================
router = DefaultRouter()
router.register(r'waypoints', WaypointViewSet)
router.register(r'airways', AirwayViewSet)
router.register(r'airway-segments', AirwaySegmentViewSet)
router.register(r'routes', RouteViewSet)
router.register(r'fir', FlightInformationRegionViewSet)

# ==================== URL PATTERNS ====================
urlpatterns = [
    # 0. MAIN PAGES (صفحات اصلی)
    path('', dashboard_view, name='home'),  # صفحه اصلی - آدرس: /
    path('dashboard/', dashboard_view, name='dashboard'),  # صفحه داشبورد
    
    # 1. Router URLs (برای ViewSet ها)
    path('api/', include(router.urls)),
    
    # 2. GeoJSON APIs (برای Frontend Map)
    path('api/airports/', AirportGeoJSON.as_view(), name='airports_geojson'),
    path('api/waypoints/', WaypointGeoJSON.as_view(), name='waypoints_geojson'),
    path('api/fir-geojson/', FIRGeoJSON.as_view(), name='fir_geojson'),
    
    # 3. Route Management APIs
    path('api/calculate-route/', CalculateRoute.as_view(), name='calculate_route'),
    path('api/save-route/', SaveRouteAPI.as_view(), name='save_route'),
    path('api/save-route-as/', SaveAsRouteAPI.as_view(), name='save_route_as'),
    path('api/get-routes/', GetRoutesAPI.as_view(), name='get_routes'),
    path('api/get-route/<int:route_id>/', GetRouteDetailAPI.as_view(), name='get_route_detail'),  # <-- خط جدید اضافه شده
    path('api/delete-route/<int:route_id>/', DeleteRouteAPI.as_view(), name='delete_route'),
    path('api/import-route/', ImportRouteAPI.as_view(), name='import_route'),
    
    # 4. Route Search APIs
    path('api/route-search/', RouteSearchAPI.as_view(), name='route_search'),
    
    # 5. Airport Search API (برای تبدیل IATA به ICAO)
    path('api/airports/search/', RouteViewSet.as_view({'get': 'search_airport'}), name='airport_search'),
]
